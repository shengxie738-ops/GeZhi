"""Local private FD storage. Callers own SQL path claims and execution fencing."""
from contextlib import contextmanager
import os
from pathlib import Path
import stat
from uuid import UUID

FILE_CAP=10*1024*1024
ENTRY_CAP=4096
READ_FLAGS=os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK


class PrivateArtifactAbsent(ValueError):
    """Only a missing leaf under a safely opened, identity-checked owner FD."""


def storage_key(namespace, artifact_id, kind):
    if type(namespace) is not UUID or type(artifact_id) is not UUID or kind not in ('pptx','docx'):
        raise ValueError('PRIVATE_STORAGE_UNAVAILABLE')
    return f'{namespace}/{artifact_id}.{kind}'


def _parse(key):
    if type(key) is not str or len(key.split('/'))!=2:
        raise ValueError('PRIVATE_STORAGE_UNAVAILABLE')
    namespace,leaf=key.split('/')
    try:
        identifier,kind=leaf.rsplit('.',1)
        if storage_key(UUID(namespace),UUID(identifier),kind)!=key: raise ValueError()
    except (ValueError,TypeError):
        raise ValueError('PRIVATE_STORAGE_UNAVAILABLE') from None
    return namespace,leaf


@contextmanager
def _directory(path):
    fd=os.open('/',READ_FLAGS|os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            next_fd=os.open(part,READ_FLAGS|os.O_DIRECTORY,dir_fd=fd)
            os.close(fd);fd=next_fd
        yield fd
    finally:
        os.close(fd)


class LocalPrivateStorage:
    def __init__(self,root,*,static_roots=()):
        self.root=Path(os.path.abspath(root))
        for public in static_roots:
            # Preserve '..' until symlinks resolve in filesystem order.
            public=Path(public).absolute()
            lexical=Path(os.path.abspath(public))
            # Resolve every existing public ancestor, including symlink aliases.
            # Optional absent directories have no target yet; a dangling/looped
            # public symlink is unknown and must not certify private storage.
            ancestor=public;missing=[]
            try:
                while True:
                    try:ancestor.lstat();break
                    except FileNotFoundError:
                        missing.insert(0,ancestor.name);ancestor=ancestor.parent
                resolved=ancestor.resolve(strict=True)
                if not resolved.is_dir():raise ValueError()
                target=resolved.joinpath(*missing)
            except (OSError,RuntimeError,ValueError):
                raise ValueError('PRIVATE_STORAGE_UNAVAILABLE') from None
            for candidate in (lexical,target):
                if self.root==candidate or candidate in self.root.parents or self.root in candidate.parents:
                    raise ValueError('PRIVATE_STORAGE_UNAVAILABLE')
        try:
            with _directory(self.root) as fd:
                s=os.fstat(fd);self.identity=(s.st_dev,s.st_ino)
        except OSError:
            raise ValueError('PRIVATE_STORAGE_UNAVAILABLE') from None

    @contextmanager
    def _owner(self,namespace,*,create=False):
        if str(UUID(namespace))!=namespace: raise ValueError('PRIVATE_STORAGE_UNAVAILABLE')
        with _directory(self.root) as root:
            s=os.fstat(root)
            if (s.st_dev,s.st_ino)!=self.identity: raise ValueError('PRIVATE_STORAGE_UNAVAILABLE')
            if create:
                try: os.mkdir(namespace,0o700,dir_fd=root);os.fsync(root)
                except FileExistsError: pass
            try: fd=os.open(namespace,READ_FLAGS|os.O_DIRECTORY,dir_fd=root)
            except FileNotFoundError:
                yield None;return
            try: yield fd
            finally: os.close(fd)

    def _verify_owner_binding(self,namespace,owner):
        with _directory(self.root) as root:
            current_root=os.fstat(root)
            if (current_root.st_dev,current_root.st_ino)!=self.identity:
                raise ValueError('PRIVATE_STORAGE_UNAVAILABLE')
            current=os.stat(namespace,dir_fd=root,follow_symlinks=False)
            held=os.fstat(owner)
            if not stat.S_ISDIR(current.st_mode) or (current.st_dev,current.st_ino)!=(held.st_dev,held.st_ino):
                raise ValueError('PRIVATE_STORAGE_UNAVAILABLE')

    def publish(self,key,raw):
        namespace,leaf=_parse(key)
        if type(raw) is not bytes or not 0<len(raw)<=FILE_CAP:
            raise ValueError('PRIVATE_STORAGE_UNAVAILABLE')
        with self._owner(namespace,create=True) as owner:
            try: os.stat(leaf,dir_fd=owner,follow_symlinks=False)
            except FileNotFoundError: pass
            else: raise ValueError('PRIVATE_STORAGE_ALREADY_EXISTS')
            temporary=leaf+'.tmp'
            fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=owner)
            try:
                view=memoryview(raw)
                while view:
                    count=os.write(fd,view)
                    if count<=0: raise OSError('short private write')
                    view=view[count:]
                os.fsync(fd)
                first=os.fstat(fd);current=os.stat(temporary,dir_fd=owner,follow_symlinks=False)
                if (first.st_dev,first.st_ino)!=(current.st_dev,current.st_ino): raise ValueError('PRIVATE_STORAGE_UNAVAILABLE')
                # Exclusive link publishes the same inode; no second byte copy.
                os.link(temporary,leaf,src_dir_fd=owner,dst_dir_fd=owner,follow_symlinks=False)
                os.fsync(owner)
                os.unlink(temporary,dir_fd=owner)
                os.fsync(owner)
            finally:
                # Failed/unknown publication remains charged for reconciliation.
                os.close(fd)

    def read(self,key):
        namespace,leaf=_parse(key)
        with self._owner(namespace) as owner:
            if owner is None: raise ValueError('PRIVATE_STORAGE_UNAVAILABLE')
            try:fd=os.open(leaf,READ_FLAGS,dir_fd=owner)
            except FileNotFoundError:
                self._verify_owner_binding(namespace,owner)
                raise PrivateArtifactAbsent('PRIVATE_STORAGE_UNAVAILABLE') from None
            try:
                before=os.fstat(fd)
                if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or not 0<=before.st_size<=FILE_CAP:
                    raise ValueError('PRIVATE_STORAGE_UNAVAILABLE')
                chunks=[];size=0
                while True:
                    chunk=os.read(fd,min(65536,FILE_CAP+1-size))
                    if not chunk: break
                    chunks.append(chunk);size+=len(chunk)
                    if size>FILE_CAP: raise ValueError('PRIVATE_STORAGE_UNAVAILABLE')
                after=os.fstat(fd);current=os.stat(leaf,dir_fd=owner,follow_symlinks=False)
                fields=('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns','st_nlink')
                if size!=before.st_size or any(getattr(before,f)!=getattr(after,f) for f in fields) or any(getattr(after,f)!=getattr(current,f) for f in fields):
                    raise ValueError('PRIVATE_STORAGE_UNAVAILABLE')
                self._verify_owner_binding(namespace,owner)
                return b''.join(chunks)
            finally: os.close(fd)

    def inventory(self,namespace,keys):
        namespace=str(namespace)
        expected={}
        for key in keys:
            n,leaf=_parse(key)
            if n!=namespace: raise ValueError('PRIVATE_STORAGE_UNAVAILABLE')
            expected[leaf]=key;expected[leaf+'.tmp']=key
        sizes={key:0 for key in keys}
        with self._owner(namespace) as owner:
            if owner is None:return sizes
            seen={};count=0
            with os.scandir(owner) as entries:
                for entry in entries:
                    count+=1
                    if count>ENTRY_CAP or entry.name not in expected: raise ValueError('PRIVATE_STORAGE_UNAVAILABLE')
                    fd=os.open(entry.name,READ_FLAGS,dir_fd=owner)
                    try: s=os.fstat(fd)
                    finally: os.close(fd)
                    if not stat.S_ISREG(s.st_mode) or s.st_size>FILE_CAP: raise ValueError('PRIVATE_STORAGE_UNAVAILABLE')
                    key=expected[entry.name];inode=(s.st_dev,s.st_ino)
                    if key in seen and seen[key]!=inode: raise ValueError('PRIVATE_STORAGE_UNAVAILABLE')
                    seen[key]=inode;sizes[key]=max(sizes[key],s.st_size)
        return sizes

    def remove(self,key):
        namespace,leaf=_parse(key)
        with self._owner(namespace) as owner:
            if owner is None:return
            candidates=[]
            for name in (leaf+'.tmp',leaf):
                try: s=os.stat(name,dir_fd=owner,follow_symlinks=False)
                except FileNotFoundError: continue
                if not stat.S_ISREG(s.st_mode) or s.st_size>FILE_CAP: raise ValueError('PRIVATE_STORAGE_UNAVAILABLE')
                candidates.append((name,s))
            if len({(s.st_dev,s.st_ino) for _,s in candidates})>1 or any(s.st_nlink!=len(candidates) for _,s in candidates):
                raise ValueError('PRIVATE_STORAGE_UNAVAILABLE')
            for name,before in candidates:
                current=os.stat(name,dir_fd=owner,follow_symlinks=False)
                if (current.st_dev,current.st_ino)!=(before.st_dev,before.st_ino):raise ValueError('PRIVATE_STORAGE_UNAVAILABLE')
            for name,_ in candidates:
                os.unlink(name,dir_fd=owner)
            os.fsync(owner)
