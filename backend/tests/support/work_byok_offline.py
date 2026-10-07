"""Synthetic-only offline test utilities. This is a test fence, not a sandbox."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import importlib.abc
import importlib.machinery
import os
from pathlib import Path
import sys
import sysconfig


NATIVE_DB_FENCED = True


class OfflineViolation(RuntimeError):
    def __init__(self):
        super().__init__('OFFLINE_UNREGISTERED_IO')


_state = {'unexpected_io': 0, 'expected_denials': 0, 'expected_depth': 0,
          'source_pin_mismatches': [], 'real_environment_accesses': [], 'source_root': None}


def reject():
    key = 'expected_denials' if _state['expected_depth'] else 'unexpected_io'
    _state[key] += 1
    raise OfflineViolation()


@contextmanager
def expect_denied():
    before = _state['expected_denials']
    _state['expected_depth'] += 1
    try:
        yield
        assert _state['expected_denials'] > before, 'expected denial was not exercised'
    finally:
        _state['expected_depth'] -= 1


class _SourceFinder(importlib.abc.MetaPathFinder):
    def __init__(self, root, allowed):
        self.root, self.allowed = root, set(allowed)

    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'openai', 'langchain_openai', 'langchain', 'dotenv', 'pymysql', 'MySQLdb'}:
            reject()
        if fullname != 'app' and not fullname.startswith('app.'):
            return None
        is_parent = any(name.startswith(fullname + '.') for name in self.allowed)
        if fullname != 'app' and fullname not in self.allowed and not is_parent:
            reject()
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None:
            return None
        origins = [spec.origin] if spec.origin and spec.origin != 'namespace' else []
        origins += list(spec.submodule_search_locations or [])
        if not origins or any(not Path(origin).resolve().is_relative_to(self.root / 'backend/app') for origin in origins):
            reject()
        return spec


def install_fences(root: Path, manifest: dict):
    root = root.resolve()
    _state['source_root'] = str(root)
    read_roots = {root, Path.cwd().resolve(), Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve()}
    for key in ('stdlib', 'platstdlib', 'purelib', 'platlib'):
        value = sysconfig.get_path(key)
        if value:
            read_roots.add(Path(value).resolve())
    allowed = manifest['allowed_app_modules']
    sys.meta_path.insert(0, _SourceFinder(root, allowed))
    forbidden_parts = {'.git', '.env', 'sessions', 'secrets', '.aws'}

    def audit(event, args):
        if event.startswith('socket.') or event in {'subprocess.Popen', 'os.system', 'os.exec', 'os.spawn', 'ctypes.dlopen', 'sqlite3.connect', 'sqlite3.connect/handle', 'sqlite3.load_extension'}:
            reject()
        if event == 'open' and args and not isinstance(args[0], int):
            p = Path(os.fsdecode(args[0])).resolve()
            if p == Path(os.devnull):
                return
            if any(part in forbidden_parts or part.startswith('.env.') for part in p.parts):
                reject()
            if not any(p.is_relative_to(base) for base in read_roots):
                reject()
            mode, flags = args[1], args[2]
            writing = (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT))
            if writing and not p.is_relative_to(Path.cwd()):
                reject()
        if event in {'os.remove', 'os.rmdir', 'os.mkdir', 'os.rename', 'os.link', 'os.symlink', 'os.chmod', 'os.chown', 'os.truncate', 'os.chdir'}:
            targets = args[:2] if event in {'os.rename', 'os.link', 'os.symlink'} else args[:1]
            for target in targets:
                if isinstance(target, (str, bytes, os.PathLike)):
                    p = Path(os.fsdecode(target)).resolve()
                    if not p.is_relative_to(Path.cwd()) or p.is_relative_to(root):
                        reject()
        if event in {'os.listdir', 'os.scandir'} and args and args[0] is not None and not isinstance(args[0], int):
            p = Path(os.fsdecode(args[0])).resolve()
            if any(part in forbidden_parts for part in p.parts) or not any(p.is_relative_to(base) for base in read_roots):
                reject()
    # Load ctypes before blocking dlopen; no third-party native loading is needed
    # by these pure contract suites. Native/provider tests need a separate gate.
    import ctypes  # noqa: F401
    sys.addaudithook(audit)


def source_report():
    app_modules = {}
    mismatches = []
    for name, module in sorted(sys.modules.items()):
        if name == 'app' or name.startswith('app.'):
            filename = getattr(module, '__file__', None)
            if filename:
                p = Path(filename).resolve()
                root = Path(_state['source_root'])
                if not p.is_relative_to(root / 'backend/app'):
                    mismatches.append(name)
                else:
                    app_modules[name] = {'path': str(p.relative_to(root)), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
    return {k: v for k, v in _state.items() if k != 'expected_depth'} | {'app_modules': app_modules, 'source_pin_mismatches': mismatches}


@dataclass(frozen=True)
class SyntheticAccount:
    username: str = 'synthetic-student'
    role: str = 'student'


@dataclass
class FakeClock:
    now: float = 0.0
    def __call__(self):
        return self.now
    def advance(self, seconds):
        if seconds < 0:
            raise ValueError('clock cannot move backwards')
        self.now += seconds


@dataclass
class SyntheticDB:
    rows: dict = field(default_factory=dict)


@dataclass
class RecordingPort:
    names: frozenset[str] = frozenset({'main', 'tutor', 'profile', 'visual_text', 'teacher_chat', 'teacher_proposal', 'probe'})
    calls: list = field(default_factory=list)
    def __call__(self, name, payload):
        if name not in self.names:
            reject()
        self.calls.append((name, payload))
        return {'content': 'synthetic result', 'finish_reason': 'stop'}


@dataclass
class OfflineScenario:
    actor: SyntheticAccount = field(default_factory=SyntheticAccount)
    db: SyntheticDB = field(default_factory=SyntheticDB)
    clock: FakeClock = field(default_factory=FakeClock)
    platform: RecordingPort = field(default_factory=RecordingPort)
    custom: RecordingPort = field(default_factory=RecordingPort)
