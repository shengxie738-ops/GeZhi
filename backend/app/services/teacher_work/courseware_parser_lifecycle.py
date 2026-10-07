"""Durable local admission and ownership for the dormant courseware runner.

This module performs no daemon, parser or subprocess operations. Trusted
transport must reserve before allocating work, persist authorize_create before
requesting create, authorize_start before requesting start, and authorize_input
before sending bytes. Recovery evidence comes from that transport, never from
request JSON, diagnostic text, or an untrusted worker.

The operator must provision an owned 0700 directory on a qualified local
filesystem. flock, rename and file/directory fsync semantics require native
qualification; accepting a path does not prove a filesystem is local or durable.
There is deliberately no reset, unlock override, daemon create, or automatic
retry. NOT_FOUND cannot fence an accepted/in-flight create request. Every
restart requires fresh trusted revalidation even of a saved terminal receipt:
a terminal rename can be visible despite a failed directory fsync, and storage
may be unable to persist a subsequent fault marker. Same-owner successful jobs
can reuse the slot after their complete durable cleanup acknowledgement.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
import fcntl
from hashlib import sha256
import hmac
import json
import os
from pathlib import Path
import re
import stat
import threading
from typing import Any
from uuid import uuid4
import weakref

MAX_LEDGER_BYTES = 16 * 1024
MAX_DIRECTORY_ENTRIES = 16
_RECORD = "lifecycle.json"
_LOCK = ".lock"
_FAULT = ".fault"
_SCHEMA = 1
_TERMINAL = frozenset(("TERMINAL", "CREATE_REJECTED"))
_STATES = frozenset(("INTENT_DURABLE", "CREATE_IN_FLIGHT", "CREATED", "INSPECTED",
    "STARTED", "IDENTITY_CAPTURED", "STREAMING", "CREATE_UNRESOLVED",
    "CLEANUP_UNRESOLVED")) | _TERMINAL
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_HEX32 = re.compile(r"[0-9a-f]{32}\Z")

# A single weak registry avoids retaining every historical owner in an at-fork
# callback. The gate keeps descriptor open/close transitions atomic with fork.
_FORK_GATE = threading.RLock()
_OPEN_OWNERS: weakref.WeakSet[ParserLifecycleOwner] = weakref.WeakSet()


def _before_fork() -> None:
    _FORK_GATE.acquire()


def _after_fork_parent() -> None:
    _FORK_GATE.release()


def _after_fork_child() -> None:
    global _FORK_GATE
    # Never take an owner mutex: it may belong to a vanished parent thread.
    # LOCK_UN would unlock the parent's shared open-file description too.
    for owner in list(_OPEN_OWNERS):
        if not owner._closed:
            for attribute in ("_lock_fd", "_directory_fd"):
                fd = getattr(owner, attribute)
                setattr(owner, attribute, -1)
                if fd >= 0:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
            owner._closed = True
            owner._ready = False
    _OPEN_OWNERS.clear()
    _FORK_GATE = threading.RLock()


os.register_at_fork(before=_before_fork, after_in_parent=_after_fork_parent,
                    after_in_child=_after_fork_child)


class LifecycleError(RuntimeError):
    """Bounded operational code without document bytes or daemon diagnostics."""


def _text(value: object, pattern: str | re.Pattern[str]) -> None:
    if type(value) is not str or re.fullmatch(pattern, value) is None:
        raise ValueError("INVALID_LIFECYCLE_FIELD")


def _integer(value: object, minimum: int, maximum: int) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("INVALID_LIFECYCLE_FIELD")


def _boolean(value: object) -> None:
    if type(value) is not bool:
        raise ValueError("INVALID_LIFECYCLE_FIELD")


@dataclass(frozen=True)
class DaemonIdentity:
    server_id: str
    fingerprint: str

    def __post_init__(self) -> None:
        _text(self.server_id, r"[A-Za-z0-9_.:-]{1,128}")
        _text(self.fingerprint, _HEX64)


@dataclass(frozen=True)
class CreateIntent:
    name: str
    owner_token: str
    image_id: str
    daemon: DaemonIdentity
    generation: str

    def __post_init__(self) -> None:
        _text(self.name, r"gezhi-parser-[0-9a-f]{32}")
        _text(self.owner_token, _HEX64)
        _text(self.image_id, r"sha256:[0-9a-f]{64}")
        _text(self.generation, _HEX32)
        if type(self.daemon) is not DaemonIdentity:
            raise ValueError("INVALID_LIFECYCLE_FIELD")


@dataclass(frozen=True)
class WorkerIdentity:
    pid: int
    start_time_ticks: int
    cgroup_path: str
    cgroup_device: int
    cgroup_inode: int

    def __post_init__(self) -> None:
        _integer(self.pid, 1, (1 << 31) - 1)
        _integer(self.start_time_ticks, 1, (1 << 63) - 1)
        _integer(self.cgroup_device, 0, (1 << 64) - 1)
        _integer(self.cgroup_inode, 1, (1 << 64) - 1)
        if (type(self.cgroup_path) is not str or not 1 < len(self.cgroup_path) <= 1024
                or not self.cgroup_path.isascii() or not self.cgroup_path.startswith("/")
                or any(part in ("", ".", "..") for part in self.cgroup_path[1:].split("/"))
                or any(ord(char) < 32 or ord(char) == 127 for char in self.cgroup_path)):
            raise ValueError("INVALID_LIFECYCLE_FIELD")


@dataclass(frozen=True)
class OwnershipEvidence:
    container_id: str
    name: str
    owner_token: str
    image_id: str
    daemon: DaemonIdentity

    def __post_init__(self) -> None:
        _text(self.container_id, _HEX64)
        CreateIntent(self.name, self.owner_token, self.image_id, self.daemon, "0" * 32)


@dataclass(frozen=True)
class CleanupReceipt:
    container_id: str
    wait_completed: bool
    stopped: bool
    removed: bool
    not_found: bool
    cgroup_empty: bool
    cli_reaped: bool
    identity_gone: bool | None
    exit_observed: bool
    worker_identity: WorkerIdentity | None = None

    def __post_init__(self) -> None:
        _text(self.container_id, _HEX64)
        for key in ("wait_completed", "stopped", "removed", "not_found",
                    "cgroup_empty", "cli_reaped", "exit_observed"):
            _boolean(getattr(self, key))
        if self.identity_gone is not None:
            _boolean(self.identity_gone)
        if self.worker_identity is not None and type(self.worker_identity) is not WorkerIdentity:
            raise ValueError("INVALID_LIFECYCLE_FIELD")


@dataclass(frozen=True)
class RecoveryEvidence:
    """CREATE_REJECTED means authoritative rejection before resource creation.

    CLI failure, timeout, a lost connection, absent name or NOT_FOUND never proves
    rejection. OBSERVED binds exact matching ownership for cleanup only, and may
    acknowledge already verified cleanup. These assertions are trusted evidence,
    not a substitute for independently qualifying the transport that produces it.
    """
    outcome: str
    ownership: OwnershipEvidence | None = None
    cleanup: CleanupReceipt | None = None

    def __post_init__(self) -> None:
        if type(self.outcome) is not str or self.outcome not in (
                "NOT_FOUND", "OBSERVED", "CREATE_REJECTED"):
            raise ValueError("INVALID_RECOVERY_OUTCOME")
        if self.outcome == "OBSERVED":
            if type(self.ownership) is not OwnershipEvidence:
                raise ValueError("OWNERSHIP_REQUIRED")
            if self.cleanup is not None and type(self.cleanup) is not CleanupReceipt:
                raise ValueError("INVALID_LIFECYCLE_FIELD")
        elif self.ownership is not None or self.cleanup is not None:
            raise ValueError("UNEXPECTED_RECOVERY_EVIDENCE")


@dataclass(frozen=True)
class JobReservation:
    """Opaque, object-identity-checked capability from try_reserve()."""
    _generation: str
    _nonce: str
    cancellation: threading.Event = field(default_factory=threading.Event,
                                          compare=False, repr=False)


@dataclass(frozen=True)
class PendingIntent:
    intent: CreateIntent
    state: str
    container_id: str | None = None
    identity: WorkerIdentity | None = None
    ownership: OwnershipEvidence | None = None
    cleanup: CleanupReceipt | None = None


@dataclass(frozen=True)
class RecoveryReport:
    quarantined: bool
    pending: PendingIntent | None
    reason: str | None


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("ascii")


def _keys(value: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError("INVALID_LEDGER_SCHEMA")
    return value


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("DUPLICATE_LEDGER_KEY")
        result[key] = value
    return result


def _daemon(value: Any) -> DaemonIdentity:
    return DaemonIdentity(**_keys(value, ("server_id", "fingerprint")))


def _intent(value: Any) -> CreateIntent:
    data = dict(_keys(value, ("name", "owner_token", "image_id", "daemon", "generation")))
    data["daemon"] = _daemon(data["daemon"])
    return CreateIntent(**data)


def _identity(value: Any) -> WorkerIdentity:
    return WorkerIdentity(**_keys(value, ("pid", "start_time_ticks", "cgroup_path",
                                         "cgroup_device", "cgroup_inode")))


def _ownership(value: Any) -> OwnershipEvidence:
    data = dict(_keys(value, ("container_id", "name", "owner_token", "image_id", "daemon")))
    data["daemon"] = _daemon(data["daemon"])
    return OwnershipEvidence(**data)


def _receipt(value: Any) -> CleanupReceipt:
    data = dict(_keys(value, ("container_id", "wait_completed", "stopped", "removed",
        "not_found", "cgroup_empty", "cli_reaped", "identity_gone", "exit_observed", "worker_identity")))
    if data["worker_identity"] is not None:
        data["worker_identity"] = _identity(data["worker_identity"])
    return CleanupReceipt(**data)


def _matched(record: PendingIntent, evidence: OwnershipEvidence) -> bool:
    intent = record.intent
    return (evidence.name == intent.name and evidence.owner_token == intent.owner_token
        and evidence.image_id == intent.image_id and evidence.daemon == intent.daemon
        and (record.container_id is None or record.container_id == evidence.container_id))


def _valid_receipt(record: PendingIntent, receipt: CleanupReceipt) -> bool:
    return (record.ownership is not None and receipt.container_id == record.container_id
        and receipt.worker_identity == record.identity
        and all((receipt.wait_completed, receipt.stopped, receipt.removed,
                 receipt.not_found, receipt.cgroup_empty, receipt.cli_reaped,
                 receipt.exit_observed))
        and (receipt.identity_gone is True if record.identity is not None
             else receipt.identity_gone is None))


def _decode(raw: bytes) -> PendingIntent:
    envelope = _keys(json.loads(raw, object_pairs_hook=_no_duplicates), ("checksum", "payload"))
    _text(envelope["checksum"], _HEX64)
    data = _keys(envelope["payload"], ("version", "intent", "state", "container_id",
                                      "identity", "ownership", "cleanup"))
    if type(data["version"]) is not int or data["version"] != _SCHEMA:
        raise ValueError("INVALID_LEDGER_VERSION")
    if not hmac.compare_digest(envelope["checksum"], sha256(_canonical(data)).hexdigest()):
        raise ValueError("INVALID_LEDGER_CHECKSUM")
    state = data["state"]
    if type(state) is not str or state not in _STATES:
        raise ValueError("INVALID_LEDGER_STATE")
    cid = data["container_id"]
    if cid is not None:
        _text(cid, _HEX64)
    identity = _identity(data["identity"]) if data["identity"] is not None else None
    ownership = _ownership(data["ownership"]) if data["ownership"] is not None else None
    receipt = _receipt(data["cleanup"]) if data["cleanup"] is not None else None
    record = PendingIntent(_intent(data["intent"]), state, cid, identity, ownership, receipt)
    if ((ownership is not None and (cid is None or not _matched(record, ownership)))
        or (identity is not None and ownership is None)
        or (state in ("CREATED", "INSPECTED", "STARTED", "IDENTITY_CAPTURED", "STREAMING",
                      "CLEANUP_UNRESOLVED", "TERMINAL") and cid is None)
        or (state in ("INSPECTED", "STARTED", "IDENTITY_CAPTURED", "STREAMING", "TERMINAL")
            and ownership is None)
        or (state in ("IDENTITY_CAPTURED", "STREAMING") and identity is None)
        or (state in ("INTENT_DURABLE", "CREATE_IN_FLIGHT", "CREATE_UNRESOLVED", "CREATE_REJECTED")
            and any(value is not None for value in (cid, identity, ownership, receipt)))
        or (state == "TERMINAL" and (receipt is None or not _valid_receipt(record, receipt)))
        or (state != "TERMINAL" and receipt is not None)):
        raise ValueError("INCONSISTENT_LEDGER_STATE")
    return record


def _secure_directory(path: Path) -> int:
    # Open components relative to an already-open ancestor; lstat followed by an
    # absolute reopen would introduce a symlink check/use race.
    absolute = os.path.abspath(os.fspath(path))
    if ".." in Path(path).parts:
        raise LifecycleError("UNSAFE_LEDGER_DIRECTORY")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open("/", flags)
    try:
        for component in Path(absolute).parts[1:]:
            new_fd = os.open(component, flags, dir_fd=fd)
            previous_fd, fd = fd, new_fd
            os.close(previous_fd)
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise LifecycleError("UNSAFE_LEDGER_DIRECTORY")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _private_regular(info: os.stat_result) -> None:
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
        raise LifecycleError("UNSAFE_LEDGER_ENTRY")


class ParserLifecycleOwner:
    """One local lifecycle owner, with a lifetime OS lock and no internal threads.

    Every public operation serializes with an in-process mutex. A sticky storage
    fault closes admission, including after subsequent successful cleanup writes.
    If all storage writes fail, software cannot promise a new durable marker;
    the previous intent remains authoritative and admission stays closed in memory.
    Recovery never interprets ambiguous writes or absence as permission to create.
    """

    def __init__(self) -> None:
        raise TypeError("USE_ParserLifecycleOwner_open")

    @classmethod
    def open(cls, ledger_dir: Path, expected_daemon: DaemonIdentity) -> ParserLifecycleOwner:
        with _FORK_GATE:
            return cls._open_locked(ledger_dir, expected_daemon)

    @classmethod
    def _open_locked(cls, ledger_dir: Path,
                     expected_daemon: DaemonIdentity) -> ParserLifecycleOwner:
        if type(expected_daemon) is not DaemonIdentity:
            raise ValueError("INVALID_DAEMON_IDENTITY")
        owner = object.__new__(cls)
        owner._pid = os.getpid()
        owner._mutex = threading.RLock()
        owner._closed = False
        owner._closing = False
        owner._ready = False
        owner._restart_revalidation = False
        owner._fault: str | None = None
        owner._generation = uuid4().hex
        owner._daemon = expected_daemon
        owner._reservation: JobReservation | None = None
        owner._issuance: tuple[JobReservation, CreateIntent, bytes] | None = None
        owner._has_intent = False
        owner._record: PendingIntent | None = None
        owner._directory_fd = -1
        owner._lock_fd = -1
        try:
            owner._directory_fd = _secure_directory(ledger_dir)
            owner._validate_entries()
            owner._lock_fd = os.open(_LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW
                                     | os.O_CLOEXEC, 0o600, dir_fd=owner._directory_fd)
            _private_regular(os.fstat(owner._lock_fd))
            fcntl.flock(owner._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            entries = owner._validate_entries()
            if os.fstat(owner._lock_fd).st_size != 0:
                owner._fault = "INVALID_LOCK_FILE"
            if _FAULT in entries:
                owner._fault = "LEDGER_IO_FAILED"
            if any(name.startswith(".record-") for name in entries):
                owner._fault = owner._fault or "INTERRUPTED_LEDGER_WRITE"
            if _RECORD in entries:
                try:
                    owner._record = _decode(owner._read_record())
                except (ValueError, TypeError, UnicodeError, RecursionError, OSError):
                    owner._fault = owner._fault or "INVALID_LEDGER"
            if owner._record is not None:
                owner._restart_revalidation = owner._record.state in _TERMINAL
                if owner._record.intent.daemon != expected_daemon:
                    owner._fault = "DAEMON_MISMATCH"
            _OPEN_OWNERS.add(owner)
            return owner
        except (OSError, LifecycleError) as error:
            for attribute in ("_lock_fd", "_directory_fd"):
                fd = getattr(owner, attribute)
                setattr(owner, attribute, -1)
                if fd >= 0:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
            owner._closed = True
            if isinstance(error, LifecycleError):
                raise
            raise LifecycleError("LEDGER_LOCK_OR_PATH_UNAVAILABLE") from None

    def _validate_entries(self) -> set[str]:
        names: set[str] = set()
        with os.scandir(self._directory_fd) as entries:
            for entry in entries:
                if len(names) >= MAX_DIRECTORY_ENTRIES:
                    raise LifecycleError("TOO_MANY_LEDGER_ENTRIES")
                if entry.name not in (_LOCK, _FAULT, _RECORD) and re.fullmatch(
                        r"\.record-[0-9a-f]{32}\.tmp", entry.name) is None:
                    raise LifecycleError("UNEXPECTED_LEDGER_ENTRY")
                _private_regular(entry.stat(follow_symlinks=False))
                names.add(entry.name)
        return names

    def _read_record(self) -> bytes:
        fd = os.open(_RECORD, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                     dir_fd=self._directory_fd)
        try:
            info = os.fstat(fd)
            _private_regular(info)
            if not 0 < info.st_size <= MAX_LEDGER_BYTES:
                raise ValueError("INVALID_LEDGER_SIZE")
            chunks: list[bytes] = []
            remaining = MAX_LEDGER_BYTES + 1
            while remaining:
                block = os.read(fd, min(remaining, 4096))
                if not block:
                    break
                chunks.append(block)
                remaining -= len(block)
            raw = b"".join(chunks)
            if len(raw) > MAX_LEDGER_BYTES:
                raise ValueError("INVALID_LEDGER_SIZE")
            return raw
        finally:
            os.close(fd)

    def _mark_fault(self) -> None:
        self._fault = self._fault or "LEDGER_IO_FAILED"
        self._ready = False
        if self._reservation is not None:
            self._reservation.cancellation.set()
        # This independent sticky marker prevents accepting a terminal record
        # whose rename happened but whose directory fsync failed. Never reset it.
        try:
            fd = os.open(_FAULT, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                         | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=self._directory_fd)
            try:
                os.write(fd, b"LEDGER_IO_FAILED\n")
                os.fsync(fd)
            finally:
                os.close(fd)
            os.fsync(self._directory_fd)
        except OSError:
            pass

    def _persist(self, record: PendingIntent) -> None:
        # Preserve known exact identities even when persistence fails: storage
        # availability must never be a prerequisite for best-effort cleanup.
        self._record = record
        payload = {"version": _SCHEMA, **asdict(record)}
        raw = _canonical({"checksum": sha256(_canonical(payload)).hexdigest(), "payload": payload})
        if len(raw) > MAX_LEDGER_BYTES:
            self._mark_fault()
            raise LifecycleError("LEDGER_TOO_LARGE")
        temporary = ".record-" + uuid4().hex + ".tmp"
        fd = -1
        try:
            self._validate_entries()
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                         | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=self._directory_fd)
            _private_regular(os.fstat(fd))
            view = memoryview(raw)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("short ledger write")
                view = view[written:]
            os.fsync(fd)
            closing_fd, fd = fd, -1
            os.close(closing_fd)
            os.replace(temporary, _RECORD, src_dir_fd=self._directory_fd,
                       dst_dir_fd=self._directory_fd)
            os.fsync(self._directory_fd)
        except (OSError, LifecycleError):
            self._mark_fault()
            raise LifecycleError("LEDGER_WRITE_FAILED") from None
        finally:
            if fd >= 0:
                os.close(fd)
            try:
                os.unlink(temporary, dir_fd=self._directory_fd)
            except OSError:
                pass

    @contextmanager
    def _locked(self):
        # Check before acquiring a possibly inherited, locked thread mutex. A
        # forked copy is never a second owner. The child hook drops its fds.
        if os.getpid() != self._pid:
            raise LifecycleError("OWNER_PROCESS_MISMATCH")
        with _FORK_GATE, self._mutex:
            yield

    def _live(self) -> None:
        if self._closed or self._lock_fd < 0:
            raise LifecycleError("OWNER_CLOSED")

    def _active(self, reservation: JobReservation, *, cleanup: bool = False) -> None:
        self._live()
        if (reservation is not self._reservation or type(reservation) is not JobReservation
                or reservation._generation != self._generation):
            raise LifecycleError("INVALID_RESERVATION")
        if not cleanup and (self._fault is not None or self._closing
                            or reservation.cancellation.is_set()):
            raise LifecycleError("ADMISSION_QUARANTINED")

    def _phase(self, *states: str) -> PendingIntent:
        if self._record is None or self._record.state not in states:
            raise LifecycleError("INVALID_LIFECYCLE_TRANSITION")
        return self._record

    def _report(self) -> RecoveryReport:
        pending = self._record if self._record and (
            self._record.state not in _TERMINAL or self._restart_revalidation) else None
        reason = "TERMINAL_REVALIDATION_REQUIRED" if self._restart_revalidation else (
            "RECOVERY_REQUIRED" if pending else None)
        return RecoveryReport(bool(self._fault or pending or not self._ready), pending,
                              self._fault or reason)

    def recover_pending(self) -> RecoveryReport:
        with self._locked():
            self._live()
            if self._reservation is not None:
                raise LifecycleError("LIVE_RESERVATION")
            self._ready = (self._fault is None and not self._closing
                           and not self._restart_revalidation)
            if self._record and self._record.state not in _TERMINAL:
                self._ready = False
                state = "CLEANUP_UNRESOLVED" if self._record.container_id else "CREATE_UNRESOLVED"
                if self._record.state != state and self._fault is None:
                    try:
                        self._persist(replace(self._record, state=state))
                    except LifecycleError:
                        pass
            return self._report()

    def try_reserve(self) -> JobReservation | None:
        if os.getpid() != self._pid:
            return None
        with self._locked():
            if (self._closed or self._closing or not self._ready or self._fault
                    or self._restart_revalidation or self._reservation is not None
                    or (self._record is not None and self._record.state not in _TERMINAL)):
                return None
            self._reservation = JobReservation(self._generation, uuid4().hex)
            self._issuance = None
            self._has_intent = False
            return self._reservation

    def make_intent(self, reservation: JobReservation, image_id: str) -> CreateIntent:
        """Mint one outstanding intent; a repeat replaces the unrecorded issuance."""
        with self._locked():
            self._active(reservation)
            if self._has_intent:
                raise LifecycleError("INVALID_CREATE_INTENT")
            intent = CreateIntent("gezhi-parser-" + uuid4().hex, uuid4().hex + uuid4().hex,
                                  image_id, replace(self._daemon), self._generation)
            # Object identity binds issuance, immutable bytes bind its facts.
            self._issuance = reservation, intent, _canonical(asdict(intent))
            return intent

    def record_intent(self, reservation: JobReservation, intent: CreateIntent) -> None:
        with self._locked():
            self._active(reservation)
            issued = self._issuance
            if (type(intent) is not CreateIntent or issued is None
                    or issued[0] is not reservation or issued[1] is not intent
                    or _canonical(asdict(intent)) != issued[2]
                    or intent.generation != self._generation
                    or intent.daemon != self._daemon or self._has_intent
                    or (self._record is not None and self._record.state not in _TERMINAL)):
                raise LifecycleError("INVALID_CREATE_INTENT")
            self._has_intent = True
            self._issuance = None
            # Do not retain an alias that a caller could change after recording.
            self._persist(PendingIntent(_intent(json.loads(issued[2])), "INTENT_DURABLE"))

    def authorize_create(self, reservation: JobReservation) -> CreateIntent:
        with self._locked():
            self._active(reservation)
            record = self._phase("INTENT_DURABLE")
            self._persist(replace(record, state="CREATE_IN_FLIGHT"))
            return _intent(asdict(record.intent))

    def record_created(self, reservation: JobReservation, container_id: str) -> None:
        with self._locked():
            # Preserve returned evidence even if cancellation arrived in flight.
            self._active(reservation, cleanup=True)
            _text(container_id, _HEX64)
            record = self._phase("CREATE_IN_FLIGHT")
            self._persist(replace(record, state="CREATED", container_id=container_id))

    def record_inspected(self, reservation: JobReservation, ownership: OwnershipEvidence) -> None:
        with self._locked():
            self._active(reservation, cleanup=True)
            record = self._phase("CREATED", "INSPECTED")
            if type(ownership) is not OwnershipEvidence or not _matched(record, ownership):
                raise LifecycleError("OWNERSHIP_MISMATCH")
            self._persist(replace(record, state="INSPECTED", ownership=ownership))

    def authorize_start(self, reservation: JobReservation) -> None:
        """Durable barrier BEFORE external start; STARTED means start may be in flight."""
        with self._locked():
            self._active(reservation)
            self._persist(replace(self._phase("INSPECTED"), state="STARTED"))

    def record_started(self, reservation: JobReservation) -> None:
        """Compatibility spelling of authorize_start; call BEFORE the start request."""
        self.authorize_start(reservation)

    def record_identity(self, reservation: JobReservation, identity: WorkerIdentity) -> None:
        with self._locked():
            self._active(reservation, cleanup=True)
            if type(identity) is not WorkerIdentity:
                raise ValueError("INVALID_WORKER_IDENTITY")
            self._persist(replace(self._phase("STARTED"), state="IDENTITY_CAPTURED", identity=identity))

    def authorize_input(self, reservation: JobReservation) -> None:
        with self._locked():
            self._active(reservation)
            self._persist(replace(self._phase("IDENTITY_CAPTURED"), state="STREAMING"))

    def cleanup_target(self, reservation: JobReservation | None = None) -> OwnershipEvidence | None:
        with self._locked():
            self._live()
            if reservation is not None:
                self._active(reservation, cleanup=True)
                if not self._has_intent:
                    return None
            elif self._reservation is not None:
                raise LifecycleError("RESERVATION_REQUIRED")
            if self._fault == "DAEMON_MISMATCH":
                raise LifecycleError("DAEMON_MISMATCH")
            return self._record.ownership if self._record is not None else None

    def record_terminal(self, reservation: JobReservation, receipt: CleanupReceipt) -> None:
        with self._locked():
            self._active(reservation, cleanup=True)
            record = self._record
            if (not self._has_intent or type(receipt) is not CleanupReceipt or record is None
                    or record.state == "CREATE_REJECTED" or not _valid_receipt(record, receipt)
                    or (record.state == "TERMINAL" and record.cleanup != receipt)):
                raise LifecycleError("INCOMPLETE_CLEANUP_EVIDENCE")
            # A failed previous acknowledgement is retryable, but cannot clear a
            # sticky storage fault. Only a successful durable commit drops the slot.
            self._persist(replace(record, state="TERMINAL", cleanup=receipt))
            self._reservation = None
            self._issuance = None
            self._has_intent = False
            self._ready = self._fault is None and not self._closing

    def record_create_rejected(self, reservation: JobReservation) -> None:
        """Acknowledge trusted authoritative rejection BEFORE resource creation.

        Also usable when the caller never passed authorize_create. Never use for
        an ambiguous create error, timeout or missing lookup.
        """
        with self._locked():
            self._active(reservation, cleanup=True)
            record = self._phase("INTENT_DURABLE", "CREATE_IN_FLIGHT", "CREATE_REJECTED")
            if not self._has_intent or record.container_id is not None:
                raise LifecycleError("CREATED_RESOURCE_REQUIRES_CLEANUP")
            self._persist(replace(record, state="CREATE_REJECTED"))
            self._reservation = None
            self._issuance = None
            self._has_intent = False
            self._ready = self._fault is None and not self._closing

    def release_unused(self, reservation: JobReservation) -> None:
        with self._locked():
            self._active(reservation, cleanup=True)
            if self._has_intent:
                raise LifecycleError("INTENT_REQUIRES_RECONCILIATION")
            self._reservation = None
            self._issuance = None

    def reconcile(self, evidence: RecoveryEvidence) -> RecoveryReport:
        with self._locked():
            self._live()
            if self._reservation is not None:
                raise LifecycleError("LIVE_RESERVATION")
            if type(evidence) is not RecoveryEvidence:
                raise ValueError("INVALID_RECOVERY_EVIDENCE")
            if self._fault in ("DAEMON_MISMATCH", "INVALID_LEDGER", "INVALID_LOCK_FILE"):
                raise LifecycleError("RECOVERY_IDENTITY_UNAVAILABLE")
            record = self._record
            if record is None or (record.state in _TERMINAL and not self._restart_revalidation):
                return self._report()
            if evidence.outcome == "NOT_FOUND":
                return self._report()
            if evidence.outcome == "CREATE_REJECTED":
                if record.container_id is not None:
                    raise LifecycleError("CREATED_RESOURCE_REQUIRES_CLEANUP")
                self._persist(replace(record, state="CREATE_REJECTED"))
            else:
                ownership = evidence.ownership
                assert ownership is not None  # Frozen RecoveryEvidence validated it.
                if not _matched(record, ownership):
                    raise LifecycleError("OWNERSHIP_MISMATCH")
                if record.state == "TERMINAL":
                    # Preserve the previous receipt as evidence of earlier wait/
                    # exit observations, but do not infer a fresh acknowledgement.
                    if evidence.cleanup is None:
                        return self._report()
                else:
                    record = replace(record, state="CLEANUP_UNRESOLVED", cleanup=None,
                                     container_id=ownership.container_id, ownership=ownership)
                    self._persist(record)
                if evidence.cleanup is not None:
                    if not _valid_receipt(record, evidence.cleanup):
                        raise LifecycleError("INCOMPLETE_CLEANUP_EVIDENCE")
                    self._persist(replace(record, state="TERMINAL", cleanup=evidence.cleanup))
            if self._record.state in _TERMINAL:
                self._restart_revalidation = False
            self._ready = (self._fault is None and self._record.state in _TERMINAL
                           and not self._closing and not self._restart_revalidation)
            return self._report()

    def close(self) -> bool:
        """Stop admission and signal cancellation; do not abandon live cleanup.

        False means the transport must finish/acknowledge cleanup and call again.
        A recovery-only owner has no live reservation and can leave its durable
        quarantine for the next recovery process. Python fork children close
        inherited owner fds without unlocking the parent. Native forks that
        bypass Python at-fork hooks require a separately qualified integration.
        After abnormal owner death, recovery can wait for a child hook to run;
        normal successful close explicitly releases the lock before returning.
        A close error consumes that descriptor number; only still-unattempted
        descriptors remain eligible for a later close call.
        No atexit reset or force-close API is installed.
        """
        with self._locked():
            if self._closed:
                return True
            self._closing = True
            self._ready = False
            if self._reservation is not None:
                self._reservation.cancellation.set()
                if self._has_intent:
                    return False
                self._reservation = None
                self._issuance = None
            # Parent-only, after every live cleanup obligation is acknowledged.
            # A fork child's hook may not yet be scheduled; successful close
            # must not depend on that child dropping its duplicate descriptor.
            if self._lock_fd >= 0:
                try:
                    fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
                except OSError:
                    raise LifecycleError("LEDGER_UNLOCK_FAILED") from None
            for attribute in ("_lock_fd", "_directory_fd"):
                fd = getattr(self, attribute)
                # close may release a number and still report an error. Never
                # retry that number: another file may already have reused it.
                setattr(self, attribute, -1)
                if fd >= 0:
                    os.close(fd)
            self._closed = True
            _OPEN_OWNERS.discard(self)
            return True
