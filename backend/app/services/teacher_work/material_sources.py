"""Fresh allowlisted byte fingerprints, never courseware text or evidence."""
from hashlib import sha256
import os
from pathlib import Path
import stat

from app.repositories.teacher_work import WorkRepositoryError


FILE_LIMIT = 10 * 1024 * 1024
ENTRY_LIMIT = 4096
DEPTH_LIMIT = 16


def configured_root():
    from app.core.config import settings
    configured = settings.COURSEWARE_FRONTEND_ROOT
    return Path(configured).resolve() if type(configured) is str and configured.strip() else Path(__file__).resolve().parents[4] / "frontend"


def source_configured():
    try:
        return configured_root().is_dir()
    except (OSError, ValueError):
        return False


class MaterialSources:
    def __init__(self):
        self.root = configured_root()

    def observe(self, resource_ids):
        from app.services.teacher_lesson_prep.courseware_catalog import DEFAULT_COURSE_DIRECTORIES, SUPPORTED_EXTENSIONS
        try:
            if (configured_root() != self.root or not self.root.is_dir() or type(resource_ids) not in (list, tuple)
                    or not 1 <= len(resource_ids) <= 10 or len(set(resource_ids)) != len(resource_ids)):
                raise ValueError("unchanged source configuration required")
            selected, entries = {key: [] for key in resource_ids}, 0
            def walk(directory_fd, parts):
                nonlocal entries
                if len(parts) > DEPTH_LIMIT:
                    raise ValueError("bounded directory depth required")
                with os.scandir(directory_fd) as listing:
                    for entry in listing:
                        entries += 1
                        if entries > ENTRY_LIMIT:
                            raise ValueError("bounded directory entry count required")
                        information = entry.stat(follow_symlinks=False)
                        path = (*parts, entry.name)
                        if stat.S_ISDIR(information.st_mode):
                            child = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
                            try:
                                walk(child, path)
                            finally:
                                os.close(child)
                        elif stat.S_ISREG(information.st_mode) and Path(entry.name).suffix.casefold() in SUPPORTED_EXTENSIONS:
                            # Exactly CoursewareCatalog's public ID derivation.
                            key = "courseware-" + sha256("/".join(path).casefold().encode("utf-8")).hexdigest()[:24]
                            if key in selected:
                                selected[key].append((path, information.st_dev, information.st_ino))
            root_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                for course in DEFAULT_COURSE_DIRECTORIES:
                    try:
                        course_fd = os.open(course, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
                    except FileNotFoundError:
                        continue
                    try:
                        walk(course_fd, (course,))
                    finally:
                        os.close(course_fd)
                result = []
                for key in resource_ids:
                    if len(selected[key]) != 1:
                        raise ValueError("one exact allowlisted resource required")
                    relative, device, inode = selected[key][0]
                    directory_fd = root_fd
                    try:
                        for component in relative[:-1]:
                            next_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
                            if directory_fd != root_fd:
                                os.close(directory_fd)
                            directory_fd = next_fd
                        fd = os.open(relative[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
                        try:
                            before = os.fstat(fd)
                            if not stat.S_ISREG(before.st_mode) or before.st_size > FILE_LIMIT or (before.st_dev, before.st_ino) != (device, inode):
                                raise ValueError("unchanged bounded regular file required")
                            digest, count = sha256(), 0
                            while chunk := os.read(fd, 65536):
                                count += len(chunk)
                                if count > FILE_LIMIT:
                                    raise ValueError("file byte limit")
                                digest.update(chunk)
                            after = os.fstat(fd)
                            if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) !=
                                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) or count != after.st_size):
                                raise ValueError("file changed during hashing")
                            result.append((key, digest.hexdigest()))
                        finally:
                            os.close(fd)
                    finally:
                        if directory_fd != root_fd:
                            os.close(directory_fd)
                return tuple(result)
            finally:
                os.close(root_fd)
        except (OSError, ValueError, TypeError, AttributeError):
            raise WorkRepositoryError("MATERIAL_SOURCES_UNAVAILABLE", 503) from None
