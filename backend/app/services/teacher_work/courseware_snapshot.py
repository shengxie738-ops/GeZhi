"""Detached selected-byte foundation; not wired to Work or a readiness claim.

The authorization callback is a TRUSTED SERVER PORT, not a client permission
flag. It must freshly resolve current teacher/task/namespace/selection and an
explicit deployment shared-library policy. DTO construction grants no access.
No configuration, database, provider, or credential imports occur here.

Filesystem deadlines below are cooperative between syscalls, NOT a hard I/O
sandbox. Call only from a bounded trusted executor; never an async event loop
or a live database transaction. Deployment/runtime integration remains closed.
"""
from dataclasses import dataclass, field
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import stat
import time
from typing import Callable
from uuid import UUID

from app.services.teacher_lesson_prep.courseware_catalog import DEFAULT_COURSE_DIRECTORIES, SUPPORTED_EXTENSIONS


class CoursewareSourceError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _fail(code='COURSEWARE_SOURCE_UNAVAILABLE'):
    raise CoursewareSourceError(code)


@dataclass(frozen=True)
class AuthorizedSelection:
    subject: str
    owner_namespace: UUID
    task_id: UUID
    run_id: UUID
    input_revision: int
    resource_ids: tuple[str, ...]
    policy_generation: str
    shared_library_enabled: bool = False
    source_root: str = field(default="", repr=False)  # Internal; never expose in a public DTO.

    def __post_init__(self):
        if (type(self.subject) is not str or not self.subject.strip() or self.subject != self.subject.strip()
                or len(self.subject) > 255 or any(type(value) is not UUID for value in
                (self.owner_namespace, self.task_id, self.run_id)) or type(self.input_revision) is not int
                or self.input_revision < 1 or type(self.resource_ids) is not tuple
                or not 1 <= len(self.resource_ids) <= 10
                or any(type(value) is not str or re.fullmatch(r'courseware-[0-9a-f]{24}', value) is None for value in self.resource_ids)
                or len(set(self.resource_ids)) != len(self.resource_ids)
                or type(self.policy_generation) is not str or not self.policy_generation.strip()
                or len(self.policy_generation) > 255 or type(self.shared_library_enabled) is not bool
                or type(self.source_root) is not str or not self.source_root or len(self.source_root) > 4096
                or not Path(self.source_root).is_absolute() or '..' in Path(self.source_root).parts):
            _fail('COURSEWARE_AUTHORITY_UNAVAILABLE')


@dataclass(frozen=True)
class SnapshotLimits:
    file_bytes: int = 10 * 1024 * 1024
    total_bytes: int = 25 * 1024 * 1024
    entries: int = 4096
    depth: int = 16
    seconds: float = 15.0

    def __post_init__(self):
        for name, maximum in (('file_bytes', 10 * 1024 * 1024), ('total_bytes', 25 * 1024 * 1024),
                              ('entries', 4096), ('depth', 16)):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= maximum:
                _fail('COURSEWARE_INVALID_LIMITS')
        if type(self.seconds) not in (int, float) or not math.isfinite(self.seconds) or not 0 < self.seconds <= 15:
            _fail('COURSEWARE_INVALID_LIMITS')


@dataclass(frozen=True)
class CapturedResource:
    resource_id: str
    name: str
    extension: str
    data: bytes = field(repr=False)
    sha256: str


@dataclass(frozen=True)
class SourceManifest:
    selection: AuthorizedSelection
    root_identity: tuple[int, int]
    resources: tuple[CapturedResource, ...]
    manifest_digest: str


def _authorize(selection, authorize):
    if type(selection) is not AuthorizedSelection or not callable(authorize):
        _fail('COURSEWARE_AUTHORITY_UNAVAILABLE')
    selection.__post_init__()
    if not selection.shared_library_enabled:
        _fail('COURSEWARE_POLICY_UNAVAILABLE')
    try:
        current = authorize(selection)
    except Exception:
        _fail('COURSEWARE_AUTHORITY_UNAVAILABLE')
    if type(current) is not AuthorizedSelection or current != selection:
        _fail('COURSEWARE_AUTHORITY_UNAVAILABLE')
    current.__post_init__()


def _open_root(path):
    """Never resolve away symlink components, including ancestors of the root."""
    if not path.is_absolute() or '..' in path.parts:
        _fail()
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def capture_selected(root: Path, selection: AuthorizedSelection, *,
                     authorize: Callable[[AuthorizedSelection], AuthorizedSelection],
                     limits: SnapshotLimits = SnapshotLimits(), monotonic=time.monotonic) -> SourceManifest:
    """Capture all selected resources or fail, preserving order and byte hashes.

    Fresh authorization runs both before filesystem I/O and after capture.
    No hidden fallback, index cache, settings activation or path disclosure.
    Returned data is a historical observation, never fresh dispatch authority.
    """
    _authorize(selection, authorize)
    if type(limits) is not SnapshotLimits:
        _fail('COURSEWARE_INVALID_LIMITS')
    limits.__post_init__()
    if not all(hasattr(os, name) for name in ('O_NOFOLLOW', 'O_DIRECTORY', 'O_NONBLOCK')):
        _fail('COURSEWARE_PLATFORM_UNAVAILABLE')
    try:
        root = Path(root)
        if str(root) != selection.source_root:
            _fail('COURSEWARE_AUTHORITY_UNAVAILABLE')
        start = monotonic()
        if type(start) not in (int, float) or not math.isfinite(start) or start < 0:
            _fail('COURSEWARE_CLOCK_UNAVAILABLE')
        def check_time():
            now = monotonic()
            if type(now) not in (int, float) or not math.isfinite(now) or now < start:
                _fail('COURSEWARE_CLOCK_UNAVAILABLE')
            if now - start >= limits.seconds:
                _fail('COURSEWARE_SOURCE_TIMEOUT')
        check_time()
        selected = {key: [] for key in selection.resource_ids}
        count = 0
        def walk(directory_fd, parts):
            nonlocal count
            check_time()
            if len(parts) > limits.depth:
                _fail('COURSEWARE_SCAN_LIMIT')
            with os.scandir(directory_fd) as listing:
                for entry in listing:
                    check_time()
                    count += 1
                    if count > limits.entries:
                        _fail('COURSEWARE_SCAN_LIMIT')
                    info = entry.stat(follow_symlinks=False)
                    relative = (*parts, entry.name)
                    if stat.S_ISDIR(info.st_mode):
                        child = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
                        try:
                            opened = os.fstat(child)
                            if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino): _fail()
                            walk(child, relative)
                        finally:
                            os.close(child)
                    elif Path(entry.name).suffix.casefold() in SUPPORTED_EXTENSIONS:
                        key = 'courseware-' + sha256('/'.join(relative).casefold().encode('utf-8')).hexdigest()[:24]
                        # Count nonregular aliases too: a symlink/casefold collision
                        # must not let an ambiguous public ID choose a regular peer.
                        if key in selected:
                            selected[key].append((relative, info.st_dev, info.st_ino))
        root_fd = _open_root(root)
        try:
            root_info = os.fstat(root_fd)
            for course in DEFAULT_COURSE_DIRECTORIES:
                check_time()
                try:
                    course_fd = os.open(course, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
                except FileNotFoundError:
                    continue
                try:
                    walk(course_fd, (course,))
                finally:
                    os.close(course_fd)
            result, total = [], 0
            for key in selection.resource_ids:
                check_time()
                if len(selected[key]) != 1: _fail()
                parts, device, inode = selected[key][0]
                directory_fd = os.dup(root_fd)
                try:
                    for part in parts[:-1]:
                        child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
                        os.close(directory_fd)
                        directory_fd = child
                    fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
                    try:
                        before = os.fstat(fd)
                        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                                or (before.st_dev, before.st_ino) != (device, inode)): _fail()
                        if before.st_size > limits.file_bytes or before.st_size + total > limits.total_bytes:
                            _fail('COURSEWARE_BYTE_LIMIT')
                        chunks, size = [], 0
                        while True:
                            check_time()
                            chunk = os.read(fd, min(65536, limits.file_bytes - size + 1))
                            if not chunk: break
                            size += len(chunk)
                            if size > limits.file_bytes or total + size > limits.total_bytes:
                                _fail('COURSEWARE_BYTE_LIMIT')
                            chunks.append(chunk)
                        after = os.fstat(fd)
                        if _identity(before) != _identity(after) or size != after.st_size or after.st_nlink != 1:
                            _fail('COURSEWARE_SOURCE_CHANGED')
                        data = b''.join(chunks)
                        result.append(CapturedResource(key, parts[-1], Path(parts[-1]).suffix.casefold(), data, sha256(data).hexdigest()))
                        total += size
                    finally:
                        os.close(fd)
                finally:
                    os.close(directory_fd)
            # Ensure the configured path still names the opened root. This is
            # an observation, not an atomic lock on a filesystem publisher.
            reopened = _open_root(root)
            try:
                current_root = os.fstat(reopened)
                if (root_info.st_dev, root_info.st_ino) != (current_root.st_dev, current_root.st_ino):
                    _fail('COURSEWARE_SOURCE_CHANGED')
            finally:
                os.close(reopened)
            check_time()
            _authorize(selection, authorize)
            check_time()
            canonical = {'subject': selection.subject, 'owner_namespace': str(selection.owner_namespace),
                'task_id': str(selection.task_id), 'run_id': str(selection.run_id), 'input_revision': selection.input_revision,
                'policy_generation': selection.policy_generation, 'source_root': selection.source_root, 'root_identity': [root_info.st_dev, root_info.st_ino],
                'resources': [[resource.resource_id, resource.sha256] for resource in result]}
            digest = sha256(json.dumps(canonical, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')).hexdigest()
            return SourceManifest(selection, (root_info.st_dev, root_info.st_ino), tuple(result), digest)
        finally:
            os.close(root_fd)
    except CoursewareSourceError:
        raise
    except (OSError, ValueError, TypeError, AttributeError, UnicodeError):
        raise CoursewareSourceError('COURSEWARE_SOURCE_UNAVAILABLE') from None
