"""Single-use dormant TrustedProcessRunner; no application configuration/caller.

Native qualification is a separate trusted integration. No native qualifier,
reviewed image or wheels lock is supplied here. Offline doubles are not evidence.
An unresolved create/cleanup retains the existing owner's reservation and lock.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from io import BytesIO
import math
import re
import threading
import time
from typing import Protocol

from parser_worker import courseware_wire as wire
from .courseware_docker_transport import CreateNotSent, DockerTransport, ProcessResult
from .courseware_extract import (
    ExtractedPage, ExtractionError, ExtractionLimits, _validate_input, _validate_pages,
)
from .courseware_parser_lifecycle import (
    CleanupReceipt, DaemonIdentity, LifecycleError, OwnershipEvidence,
    ParserLifecycleOwner, WorkerIdentity,
)

ACCEPTED_SOURCES = (
    ('courseware_extract.py', '60d12bdda6eeb0c3fb26a9d83748b358a1b3feff31f63257f63952275225db8f'),
    ('courseware_wire.py', 'b3559ebaeaa5c0575b03090e6fdb8d56c8dcea0e66e04ff9363551d1fe75f255'),
    ('courseware_worker.py', 'b0120e9d4e998e13d48b10b2c221bf90843cf8c67a604da7772b497ab48314a6'),
)


def _budgets(limits):
    if type(limits) is not ExtractionLimits:
        raise ExtractionError('INVALID_LIMITS')
    limits.__post_init__()
    return tuple(getattr(limits, f.name) for f in fields(limits))


@dataclass(frozen=True)
class QualificationEvidence:
    """Facts issued by trusted native code after actual qualification, never JSON.

    Field shape/hash equality cannot itself establish enforcement or provenance.
    The qualifier must validate reviewed image/wheels and current native controls,
    independent termination, storage, and the observation mechanism it supplies.
    """
    daemon: DaemonIdentity
    image_id: str
    sources: tuple[tuple[str, str], ...]
    wheels_lock_sha256: str
    limits: tuple[int, ...]
    expires_monotonic: float

    def validate(self, limits, now):
        if (type(self.daemon) is not DaemonIdentity or type(self.image_id) is not str or
                re.fullmatch(r'sha256:[0-9a-f]{64}', self.image_id) is None or
                type(self.sources) is not tuple or self.sources != ACCEPTED_SOURCES or
                type(self.wheels_lock_sha256) is not str or re.fullmatch(r'[0-9a-f]{64}', self.wheels_lock_sha256) is None or
                type(self.limits) is not tuple or self.limits != _budgets(limits) or
                type(self.expires_monotonic) not in (float, int) or
                not math.isfinite(self.expires_monotonic) or not now < self.expires_monotonic <= now + 5):
            raise ExtractionError('ISOLATION_UNAVAILABLE')
        self.daemon.__post_init__()


class NativeQualifier(Protocol):
    def qualify(self, transport: DockerTransport, limits: ExtractionLimits,
                deadline: float, cancellation: threading.Event) -> QualificationEvidence: ...


class CoursewareSupervisor:
    """One job. Use `with` or explicit close if verify_support is not followed by run.

    Policy is default-off; construction performs no probes/threads. There is no
    native-qualification implementation or request-controlled enablement here.
    Cancellation closes admission but never cancels an exact cleanup attempt.
    """
    def __init__(self, owner: ParserLifecycleOwner, transport: DockerTransport, *,
                 qualifier: NativeQualifier | None = None, enabled: bool = False,
                 clock=time.monotonic):
        if type(enabled) is not bool:
            raise ValueError('INVALID_SUPERVISOR_POLICY')
        self._owner, self._transport, self._qualifier = owner, transport, qualifier
        self._enabled, self._clock = enabled, clock
        self._mutex = threading.Lock()
        self._cancel = threading.Event()
        self._state = 'new'
        self._reservation = self._evidence = self._limits = None
        self._job_cancel = self._job_limits = self._receipt = None
        self._intent = self._cid = self._ownership = self._identity = self._attached = None
        self._create_dispatched = False
        self._ownership_mismatch = False

    def _gate(self, deadline=None):
        if self._cancel.is_set() or (self._job_cancel and self._job_cancel.is_set()):
            raise ExtractionError('RUNNER_FAILED')
        if deadline is not None and self._clock() >= deadline:
            raise TimeoutError()

    def verify_support(self, limits: ExtractionLimits) -> bool:
        with self._mutex:
            if self._state != 'new':
                return False
            self._state = 'verifying'
            if not self._enabled or self._qualifier is None or self._cancel.is_set():
                self._state = 'finished'
                return False
            # This synchronous owner call precedes every qualifier/probe/allocation.
            self._reservation = self._owner.try_reserve()
            if self._reservation is None:
                self._state = 'finished'
                return False
            self._job_cancel = self._reservation.cancellation
        ok = False
        try:
            self._limits = _budgets(limits)
            self._job_limits = ExtractionLimits(**dict(zip(wire.LIMIT_NAMES, self._limits)))
            deadline = self._clock() + limits.max_wall_seconds
            self._gate(deadline)
            evidence = self._qualifier.qualify(self._transport, limits,
                deadline, self._reservation.cancellation)
            if type(evidence) is not QualificationEvidence:
                raise ExtractionError('ISOLATION_UNAVAILABLE')
            evidence.validate(limits, self._clock())
            if self._transport.current_daemon(deadline, self._reservation.cancellation) != evidence.daemon:
                raise ExtractionError('ISOLATION_UNAVAILABLE')
            self._gate(deadline)
            evidence.validate(limits, self._clock())
            self._evidence = evidence
            ok = True
        except Exception:
            pass
        finally:
            with self._mutex:
                if ok and (self._cancel.is_set() or self._job_cancel.is_set()):
                    ok = False
                if ok:
                    self._state = 'verified'
            if not ok:
                try:
                    self._owner.release_unused(self._reservation)
                    self._reservation = None
                finally:
                    with self._mutex:
                        self._state = 'finished' if self._reservation is None else 'quarantined'
        return ok

    def _match(self, ownership):
        intent = self._intent
        if (type(ownership) is not OwnershipEvidence or ownership.container_id != self._cid or
                ownership.name != intent.name or ownership.owner_token != intent.owner_token or
                ownership.image_id != intent.image_id or ownership.daemon != intent.daemon):
            self._ownership_mismatch = True
            raise ExtractionError('ISOLATION_UNAVAILABLE')
        ownership.__post_init__()
        return ownership

    def _finish(self, limits):
        """Never erase uncertainty. Preserve local exact facts despite ledger faults."""
        if not self._create_dispatched and self._cid is None:
            # Minting is not acceptance. The exact owner alone can distinguish
            # an unused slot from an accepted in-memory/durable obligation,
            # including record_intent failures after persistence began.
            try:
                self._owner.release_unused(self._reservation)
            except LifecycleError as error:
                if str(error) != 'INTENT_REQUIRES_RECONCILIATION':
                    raise
                # No create was dispatched (or transport proved not sent).
                # Persist failures retain their obligation and sticky fault.
                self._owner.record_create_rejected(self._reservation)
            self._reservation = None
            return
        if self._cid is None:
            raise ExtractionError('ISOLATION_UNAVAILABLE')
        if self._ownership_mismatch:
            raise ExtractionError('ISOLATION_UNAVAILABLE')
        if self._receipt is not None:
            self._owner.record_terminal(self._reservation, self._receipt)
            self._reservation = None
            return
        cleanup_deadline = self._clock() + 3
        cleanup_cancel = threading.Event()
        if self._ownership is None:
            self._ownership = self._match(self._transport.inspect(self._intent,
                self._cid, limits, cleanup_deadline, cleanup_cancel))
            try:
                self._owner.record_inspected(self._reservation, self._ownership)
            except LifecycleError:
                # _persist retains exact evidence in memory before attempting IO.
                # Cleanup must not depend on ledger availability; terminal ack does.
                pass
        receipt = self._transport.cleanup(self._ownership, self._identity,
            self._attached, cleanup_deadline)
        if type(receipt) is not CleanupReceipt:
            raise ExtractionError('ISOLATION_UNAVAILABLE')
        receipt.__post_init__()
        if (receipt.container_id != self._cid or receipt.worker_identity != self._identity or
                not all((receipt.wait_completed, receipt.stopped, receipt.removed,
                         receipt.not_found, receipt.cgroup_empty, receipt.cli_reaped, receipt.exit_observed)) or
                (receipt.identity_gone is not True if self._identity is not None else receipt.identity_gone is not None)):
            raise ExtractionError('ISOLATION_UNAVAILABLE')
        # Same-owner retry of a failed durable acknowledgement, never a restart
        # acknowledgement inferred from NOT_FOUND. The lifecycle validates again.
        self._receipt = receipt
        self._owner.record_terminal(self._reservation, receipt)
        self._reservation = None

    def run(self, data: bytes, extension: str, limits: ExtractionLimits) -> tuple[ExtractedPage, ...]:
        with self._mutex:
            if self._state != 'verified':
                raise ExtractionError('ISOLATION_UNAVAILABLE')
            self._state = 'running'
        pages, failure = None, None
        # This deadline begins before revalidation, intent persistence and create.
        deadline = self._clock()
        try:
            if _budgets(limits) != self._limits:
                raise ExtractionError('INVALID_LIMITS')
            deadline += limits.max_wall_seconds
            extension = _validate_input(data, extension, limits)
            self._gate(deadline)
            self._evidence.validate(limits, self._clock())
            if self._transport.current_daemon(deadline, self._reservation.cancellation) != self._evidence.daemon:
                raise ExtractionError('ISOLATION_UNAVAILABLE')
            self._gate(deadline)
            self._intent = self._owner.make_intent(self._reservation, self._evidence.image_id)
            if self._intent.daemon != self._evidence.daemon:
                raise ExtractionError('ISOLATION_UNAVAILABLE')
            self._owner.record_intent(self._reservation, self._intent)
            intent = self._owner.authorize_create(self._reservation)
            self._gate(deadline)
            self._create_dispatched = True
            try:
                self._cid = self._transport.create(intent, limits, deadline, self._reservation.cancellation)
            except CreateNotSent:
                self._create_dispatched = False
                raise
            # Capture returned IDs even when cancellation/deadline arrived in flight.
            self._owner.record_created(self._reservation, self._cid)
            self._gate(deadline)
            self._ownership = self._match(self._transport.inspect(intent, self._cid,
                limits, deadline, self._reservation.cancellation))
            self._owner.record_inspected(self._reservation, self._ownership)
            self._gate(deadline)
            self._owner.authorize_start(self._reservation)
            self._attached = self._transport.start(self._ownership, deadline, self._reservation.cancellation)
            self._identity = self._transport.capture_identity(self._ownership,
                limits, deadline, self._reservation.cancellation)
            if type(self._identity) is not WorkerIdentity:
                raise ExtractionError('ISOLATION_UNAVAILABLE')
            self._identity.__post_init__()
            self._owner.record_identity(self._reservation, self._identity)
            self._gate(deadline)
            self._owner.authorize_input(self._reservation)
            self._gate(deadline)
            request = wire.encode_request(wire.WireRequest(extension, self._limits, data))
            result = self._transport.exchange(self._attached, request,
                wire.response_transport_cap(self._limits), deadline, self._reservation.cancellation)
            self._gate(deadline)
            if (type(result) is not ProcessResult or type(result.stdout) is not bytes or
                    len(result.stdout) > wire.response_transport_cap(self._limits) or result.stderr_bytes != 0):
                raise ExtractionError('INVALID_OUTPUT')
            response = wire.read_response(BytesIO(result.stdout), self._limits)
            if response.error_code is not None:
                raise ExtractionError(response.error_code)
            if type(result.exit_code) is not int or result.exit_code != 0:
                raise ExtractionError('RUNNER_FAILED')
            pages = tuple(ExtractedPage(p.page, p.text) for p in response.pages)
            _validate_pages(pages, limits)
        except BaseException as error:
            if isinstance(error, (ExtractionError, TimeoutError, KeyboardInterrupt, SystemExit)):
                failure = error
            elif isinstance(error, wire.WireProtocolError):
                failure = ExtractionError(error.code)
            else:
                failure = ExtractionError('RUNNER_FAILED')
        finally:
            try:
                self._finish(limits)
            except BaseException:
                failure = ExtractionError('ISOLATION_UNAVAILABLE')
            with self._mutex:
                self._state = 'finished' if self._reservation is None else 'quarantined'
        if failure is not None:
            raise failure from None
        self._gate(deadline)
        return pages

    def cancel(self):
        with self._mutex:
            self._cancel.set()
            if self._reservation is not None:
                self._reservation.cancellation.set()
                if self._state == 'verified':
                    self._owner.release_unused(self._reservation)
                    self._reservation = None
                    self._state = 'finished'

    def close(self) -> bool:
        self.cancel()
        retry = False
        with self._mutex:
            if self._state in ('verifying', 'running', 'cleaning'):
                return False
            if self._state == 'quarantined':
                if self._cid is None or self._ownership_mismatch:
                    return False
                self._state = 'cleaning'
                retry = True
            if not retry:
                if self._reservation is not None:
                    self._owner.release_unused(self._reservation)
                    self._reservation = None
                self._state = 'closed'
                return True
        try:
            self._finish(self._job_limits)
        except Exception:
            return False
        finally:
            with self._mutex:
                self._state = 'closed' if self._reservation is None else 'quarantined'
        return self._reservation is None

    def __enter__(self):
        return self

    def __exit__(self, kind, value, traceback):
        if not self.close() and kind is None:
            raise ExtractionError('ISOLATION_UNAVAILABLE')
