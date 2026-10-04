"""Pure current-authority decisions and one caller-owned Work request workflow.

Facts must be supplied by trusted request-local adapters after ordered locks.
These helpers do not acquire authority, inspect a schema, open a transaction or
certify production readiness. Concrete identity/teaching/transport bindings and
the account-incarnation gate remain separate integration requirements.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID

from app.repositories.teacher_work import WorkRepositoryError
from app.schemas.teacher_work import WorkTaskDTO
from app.services.teacher_work.types import WorkActor, WorkContext


class WorkAuthorizationError(Exception):
    """Controlled outcome without account, policy, transport or SQL details."""
    def __init__(self, code: str, status_code: int):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class CurrentAccountFacts:
    username: str
    role: str


@dataclass(frozen=True)
class PolicySnapshot:
    generation: str
    institution_id: str | None


@dataclass(frozen=True)
class HeldWorkAuthority:
    subject: str
    institution_id: str | None
    offering_id: UUID | None
    footprint_token: object
    policy: PolicySnapshot


@dataclass(frozen=True)
class NamespaceObservation:
    subject: str
    namespace_id: UUID


@dataclass(frozen=True)
class NamespaceReceipt:
    subject: str
    namespace_id: UUID
    provisional: bool
    mode: str
    footprint_token: object


@dataclass(frozen=True)
class OfferingDecision:
    subject: str
    institution_id: str
    offering_id: UUID
    action: str
    readable: bool
    teaching: bool


@dataclass(frozen=True)
class HeldAdmissionReceipt:
    subject: str
    institution_id: str | None
    offering_id: UUID | None
    footprint_token: object
    policy_generation: str
    at: datetime
    allowed: bool


@dataclass(frozen=True)
class CommitReceipt:
    confirmed: bool


@dataclass(frozen=True)
class BoundCandidate:
    value: object
    subject: str
    owner_storage_id: UUID
    institution_id: str | None
    offering_id: UUID | None


def _subject(value: object) -> bool:
    return type(value) is str and bool(value) and value == value.strip() and len(value) <= 255


def _scope(institution_id: object, offering_id: object) -> bool:
    return (institution_id is None and offering_id is None) or (
        type(institution_id) is str and bool(institution_id.strip()) and len(institution_id) <= 64
        and isinstance(offering_id, UUID))


def _authority(subject: str, held: HeldWorkAuthority) -> None:
    if (not _subject(subject) or not isinstance(held, HeldWorkAuthority) or held.subject != subject
            or held.footprint_token is None or not _scope(held.institution_id, held.offering_id)
            or not isinstance(held.policy, PolicySnapshot)
            or type(held.policy.generation) is not str or not held.policy.generation
            or held.policy.institution_id != held.institution_id):
        raise WorkAuthorizationError("CURRENT_AUTHORITY_UNAVAILABLE", 503)


def require_current_teacher_facts(signed_subject: str, current_account_facts: CurrentAccountFacts | None) -> str:
    """Use the exact signed subject and current account role, never token role."""
    if (not _subject(signed_subject) or not isinstance(current_account_facts, CurrentAccountFacts)
            or not _subject(current_account_facts.username) or current_account_facts.username != signed_subject
            or type(current_account_facts.role) is not str or current_account_facts.role not in ("teacher", "student")):
        raise WorkAuthorizationError("INVALID_CURRENT_IDENTITY", 401)
    if current_account_facts.role != "teacher":
        raise WorkAuthorizationError("CURRENT_TEACHER_REQUIRED", 403)
    return signed_subject


def prepare_namespace_receipt(subject: str, *, mode: str, authority: HeldWorkAuthority,
                              observation: NamespaceObservation | None, task_namespace_ids: tuple[UUID, ...],
                              new_uuid: Callable[[], UUID], prior: NamespaceReceipt | None = None) -> NamespaceReceipt:
    """Resolve supplied observations; only a locked first write may propose UUID.

    There is no insertion here. The existing SQL owner-lease initializer performs
    that reservation in the caller transaction; final admission verifies it.
    """
    _authority(subject, authority)
    if mode not in ("read", "write"):
        raise WorkAuthorizationError("REQUEST_MODE_MISMATCH", 503)
    if type(task_namespace_ids) is not tuple or any(not isinstance(value, UUID) for value in task_namespace_ids):
        raise WorkAuthorizationError("OWNER_NAMESPACE_MISMATCH", 503)
    if prior is not None and (not isinstance(prior, NamespaceReceipt) or prior.subject != subject
            or prior.mode != mode or prior.footprint_token is not authority.footprint_token
            or not isinstance(prior.namespace_id, UUID) or type(prior.provisional) is not bool
            or (mode == "read" and prior.provisional)):
        raise WorkAuthorizationError("OWNER_NAMESPACE_MISMATCH", 503)
    if observation is not None:
        if (not isinstance(observation, NamespaceObservation) or observation.subject != subject
                or not isinstance(observation.namespace_id, UUID)
                or any(value != observation.namespace_id for value in task_namespace_ids)
                or (prior is not None and prior.namespace_id != observation.namespace_id)):
            raise WorkAuthorizationError("OWNER_NAMESPACE_MISMATCH", 503)
        return NamespaceReceipt(subject, observation.namespace_id, False, mode, authority.footprint_token)
    if mode == "read":
        raise WorkAuthorizationError("OWNER_NAMESPACE_UNAVAILABLE", 503)
    if task_namespace_ids or (prior is not None and not prior.provisional):
        raise WorkAuthorizationError("OWNER_NAMESPACE_MISMATCH", 503)
    if prior is not None:
        return prior
    try:
        namespace = new_uuid()
    except Exception:
        raise WorkAuthorizationError("OWNER_NAMESPACE_UNAVAILABLE", 503) from None
    if not isinstance(namespace, UUID):
        raise WorkAuthorizationError("OWNER_NAMESPACE_UNAVAILABLE", 503)
    return NamespaceReceipt(subject, namespace, True, mode, authority.footprint_token)


def bind_work_actor(subject: str, namespace_receipt: NamespaceReceipt) -> WorkActor:
    if (not _subject(subject) or not isinstance(namespace_receipt, NamespaceReceipt)
            or namespace_receipt.subject != subject or not isinstance(namespace_receipt.namespace_id, UUID)
            or namespace_receipt.mode not in ("read", "write")
            or type(namespace_receipt.provisional) is not bool or namespace_receipt.footprint_token is None
            or (namespace_receipt.mode == "read" and namespace_receipt.provisional)):
        raise WorkAuthorizationError("OWNER_NAMESPACE_MISMATCH", 503)
    return WorkActor(subject, "teacher", namespace_receipt.namespace_id)


def authorize_task(actor: WorkActor, task: WorkTaskDTO,
                   offering_decision: OfferingDecision | None = None) -> WorkContext:
    if not isinstance(actor, WorkActor) or not isinstance(task, WorkTaskDTO) or task.owner_subject != actor.subject:
        raise WorkAuthorizationError("NOT_FOUND", 404)
    if task.owner_storage_id != actor.owner_storage_id:
        raise WorkAuthorizationError("OWNER_NAMESPACE_MISMATCH", 503)
    if task.offering_id is not None:
        decision = offering_decision
        if (not isinstance(decision, OfferingDecision) or decision.subject != actor.subject
                or decision.institution_id != task.institution_id or decision.offering_id != task.offering_id
                or decision.action != "READ_OFFERING" or decision.readable is not True or decision.teaching is not True):
            raise WorkAuthorizationError("OFFERING_AUTHORITY_REQUIRED", 403)
    return WorkContext(actor.subject, actor.owner_storage_id, task.task_id, task.institution_id,
                       task.offering_id, task.input_revision, task.working_revision)


class TeacherWorkRequestOwner:
    """Single-use Work finalization on the exact caller Session/root/footprint.

    Transport operations are narrowly injected; this class neither begins nor
    repairs a transaction. A commit exception cannot establish whether the
    database committed, even if a later cleanup rollback succeeds.
    """
    def __init__(self, *, transport, mode: str, actor: WorkActor, namespace_receipt: NamespaceReceipt,
                 authority: HeldWorkAuthority, clock: Callable[[], datetime],
                 policy_provider: Callable[[], PolicySnapshot], namespace_observer: Callable[[], NamespaceObservation],
                 evaluate_held: Callable[[HeldWorkAuthority, PolicySnapshot, datetime], HeldAdmissionReceipt]):
        _authority(actor.subject if isinstance(actor, WorkActor) else "", authority)
        if mode not in ("read", "write") or not isinstance(namespace_receipt, NamespaceReceipt) or namespace_receipt.mode != mode:
            raise WorkAuthorizationError("REQUEST_MODE_MISMATCH", 503)
        if (bind_work_actor(actor.subject, namespace_receipt) != actor
                or namespace_receipt.footprint_token is not authority.footprint_token):
            raise WorkAuthorizationError("REQUEST_BINDING_CHANGED", 503)
        self.transport, self.mode, self.actor = transport, mode, actor
        self.namespace_receipt, self.authority = namespace_receipt, authority
        self._held, self._actor, self._namespace = authority, actor, namespace_receipt
        self.clock, self.policy_provider = clock, policy_provider
        self.namespace_observer, self.evaluate_held = namespace_observer, evaluate_held
        self.state = "open"
        self._session, self._root = transport.session_identity(), transport.root_identity()
        if self._session is None or self._root is None:
            raise WorkAuthorizationError("REQUEST_BINDING_CHANGED", 503)
        self._binding()

    def _binding(self) -> None:
        if (self.authority is not self._held or self.actor is not self._actor or self.namespace_receipt is not self._namespace
                or self.namespace_receipt.footprint_token is not self.authority.footprint_token
                or self.transport.in_transaction() is not True or self.transport.session_identity() is not self._session
                or self.transport.root_identity() is not self._root
                or (self.mode == "read" and self.transport.has_pending_writes() is not False)):
            raise WorkAuthorizationError("REQUEST_BINDING_CHANGED", 503)

    def _open(self, mode: str) -> None:
        if self.state != "open":
            raise WorkAuthorizationError("REQUEST_FINISHED", 503)
        if self.mode != mode:
            raise WorkAuthorizationError("REQUEST_MODE_MISMATCH", 503)

    def _admit(self, candidate: BoundCandidate) -> None:
        self._binding()
        held = self.authority
        if (not isinstance(candidate, BoundCandidate) or candidate.subject != self.actor.subject
                or candidate.owner_storage_id != self.actor.owner_storage_id
                or (candidate.institution_id, candidate.offering_id) != (held.institution_id, held.offering_id)):
            raise WorkAuthorizationError("REQUEST_BINDING_CHANGED", 503)
        namespace = self.namespace_observer()
        if (not isinstance(namespace, NamespaceObservation) or namespace.subject != self.actor.subject
                or namespace.namespace_id != self.actor.owner_storage_id):
            raise WorkAuthorizationError("OWNER_NAMESPACE_MISMATCH", 503)
        policy = self.policy_provider()
        if (not isinstance(policy, PolicySnapshot) or policy != held.policy):
            raise WorkAuthorizationError("POLICY_CHANGED", 503)
        now = self.clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise WorkAuthorizationError("CURRENT_AUTHORITY_UNAVAILABLE", 503)
        now = now.astimezone(timezone.utc)
        receipt = self.evaluate_held(held, policy, now)
        if (not isinstance(receipt, HeldAdmissionReceipt) or receipt.subject != held.subject
                or (receipt.institution_id, receipt.offering_id) != (held.institution_id, held.offering_id)
                or receipt.footprint_token is not held.footprint_token or receipt.policy_generation != policy.generation
                or receipt.at != now or type(receipt.allowed) is not bool):
            raise WorkAuthorizationError("CURRENT_AUTHORITY_UNAVAILABLE", 503)
        if not receipt.allowed:
            raise WorkAuthorizationError("CURRENT_AUTHORITY_DENIED", 403)
        self._binding()
        if self.transport.has_pending_writes() is not False:
            raise WorkAuthorizationError("REQUEST_BINDING_CHANGED", 503)

    def _cleanup(self) -> bool:
        cleaned = True
        for operation in (self.transport.rollback, self.transport.close):
            try:
                operation()
            except Exception:
                cleaned = False
        return cleaned

    def finish_write(self, candidate: BoundCandidate) -> object:
        self._open("write")
        try:
            self._binding()
            self.transport.flush()
            self._admit(candidate)
        except (WorkAuthorizationError, WorkRepositoryError):
            self.state = "aborted"
            self._cleanup()
            raise
        except Exception:
            self.state = "aborted"
            self._cleanup()
            raise WorkAuthorizationError("WRITE_ABORTED", 503) from None
        try:
            outcome = self.transport.commit()
            if not isinstance(outcome, CommitReceipt) or outcome.confirmed is not True:
                raise WorkAuthorizationError("COMMIT_OUTCOME_UNKNOWN", 503)
        except Exception:
            self.state = "unknown"
            self._cleanup()
            raise WorkAuthorizationError("COMMIT_OUTCOME_UNKNOWN", 503) from None
        self.state = "committed"
        try:
            self.transport.close()
        except Exception:
            # Commit was confirmed. A cleanup failure cannot undo that outcome.
            pass
        return candidate.value

    def finish_read(self, candidate: BoundCandidate) -> object:
        self._open("read")
        try:
            self._admit(candidate)
        except WorkAuthorizationError:
            self.state = "aborted"
            self._cleanup()
            raise
        except Exception:
            self.state = "aborted"
            self._cleanup()
            raise WorkAuthorizationError("READ_ABORTED", 503) from None
        self.state = "read_closed"
        if not self._cleanup():
            self.state = "aborted"
            raise WorkAuthorizationError("READ_ABORTED", 503)
        return candidate.value
