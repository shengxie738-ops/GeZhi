"""Pure Teacher Work persistence candidates and strict attribute-row decoders.

Supplied tokens/counts/receipts are strict records, not authority or evidence of
admission, dispatch, settlement, cancellation, storage or a committed reply. The
SQL boundary supplies already-read attributes, compares current authority,
charges before dispatch and finalizes the actual assistant row atomically.
Nothing here imports SQL, obtains rows or certifies a transaction outcome.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

from pydantic import TypeAdapter, ValidationError

from app.schemas.teacher_work import ChatResult, MessageKey, RunDTO, WorkMessageDTO, WorkTaskDTO
from app.services.teacher_work.runs import CallLimits, OwnerLeaseFacts, WorkBudget, WorkRunError
from app.services.teacher_work.types import WorkContext, canonical_json_bytes


def encode_work_key(key: str) -> bytes:
    """Exact public key to bytes; never trim, fold case or normalize Unicode."""
    try:
        exact = TypeAdapter(MessageKey).validate_python(key)
        encoded = exact.encode("utf-8", errors="strict")
        if len(encoded) > 512:
            raise ValueError("key byte bound")
        return encoded
    except (ValidationError, ValueError, TypeError, UnicodeError):
        raise WorkRunError("INVALID_MESSAGE_KEY", 422) from None


def decode_work_key(raw: bytes) -> str:
    """Stored nullable columns handle None separately; stored keys are bytes."""
    if type(raw) is not bytes or not 1 <= len(raw) <= 512:
        raise WorkRunError("INVALID_STORED_KEY", 503)
    try:
        decoded = raw.decode("utf-8", errors="strict")
        exact = TypeAdapter(MessageKey).validate_python(decoded)
        if exact.encode("utf-8", errors="strict") != raw:
            raise ValueError("key roundtrip")
        return exact
    except (ValidationError, ValueError, TypeError, UnicodeError):
        raise WorkRunError("INVALID_STORED_KEY", 503) from None


def _validate_run(run: RunDTO) -> None:
    if not isinstance(run, RunDTO):
        raise WorkRunError("INVALID_STORED_RUN", 503)
    try:
        RunDTO.model_validate(run.model_dump())
    except (ValidationError, ValueError, TypeError):
        raise WorkRunError("INVALID_STORED_RUN", 503) from None


def _validate_message(message: WorkMessageDTO) -> None:
    if not isinstance(message, WorkMessageDTO):
        raise WorkRunError("INVALID_STORED_MESSAGE", 503)
    try:
        WorkMessageDTO.model_validate(message.model_dump())
    except (ValidationError, ValueError, TypeError):
        raise WorkRunError("INVALID_STORED_MESSAGE", 503) from None


@dataclass(frozen=True)
class ProviderCallToken:
    run_id: UUID
    attempt: int
    call_no: int
    lease_revision: int
    process_instance: UUID

    def __post_init__(self):
        if (type(self.run_id) is not UUID or type(self.process_instance) is not UUID
                or type(self.attempt) is not int or not 1 <= self.attempt <= 2
                or type(self.call_no) is not int or not 1 <= self.call_no <= 3
                or type(self.lease_revision) is not int or self.lease_revision < 1):
            raise WorkRunError("INVALID_CALL_TOKEN", 503)


@dataclass(frozen=True)
class StoredRunState:
    run: RunDTO
    repair_count: int
    active_call: ProviderCallToken | None

    def __post_init__(self):
        _validate_run(self.run)
        WorkBudget(attempt=self.run.attempt, provider_call_count=self.run.provider_call_count,
                   repair_count=self.repair_count)
        if self.active_call is None:
            return
        if type(self.active_call) is not ProviderCallToken:
            raise WorkRunError("INVALID_CALL_TOKEN", 503)
        ProviderCallToken.__post_init__(self.active_call)
        if (self.active_call.run_id != self.run.run_id or self.active_call.attempt != self.run.attempt
                or self.active_call.call_no != self.run.provider_call_count):
            raise WorkRunError("INVALID_STORED_RUN", 503)
        # No stage restriction: cancellation cannot erase an unsettled call.


def matches_active_call(state: StoredRunState, token: ProviderCallToken) -> bool:
    """Exact five-component comparison; no settlement/release side effects."""
    if type(state) is not StoredRunState or type(token) is not ProviderCallToken:
        raise WorkRunError("INVALID_CALL_TOKEN", 503)
    StoredRunState.__post_init__(state)
    ProviderCallToken.__post_init__(token)
    return state.active_call is not None and state.active_call == token


@dataclass(frozen=True)
class ChatCompletionReceipt:
    run_id: UUID
    message_id: UUID

    def __post_init__(self):
        if type(self.run_id) is not UUID or type(self.message_id) is not UUID:
            raise WorkRunError("INVALID_CHAT_COMPLETION", 503)


@dataclass(frozen=True)
class PreparedChatCompletion:
    """One server-prepared immutable candidate, never request authority.

    Its actual message UUID/time and result survive unknown commit outcomes.
    The immutable snapshot additionally detects mutation through a DTO's private
    implementation storage; every write revalidates both coherence and snapshot.
    Construction/validation alone proves neither current authority nor commit.
    """
    original_ctx: WorkContext
    token: ProviderCallToken
    result: ChatResult
    allowed_result_refs: frozenset[UUID]
    omitted_context: bool
    message: WorkMessageDTO
    receipt: ChatCompletionReceipt
    _snapshot: bytes = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        code = "INVALID_CHAT_COMPLETION"
        try:
            if (type(self.original_ctx) is not WorkContext or type(self.token) is not ProviderCallToken
                    or type(self.result) is not ChatResult or type(self.message) is not WorkMessageDTO
                    or type(self.receipt) is not ChatCompletionReceipt
                    or type(self.allowed_result_refs) is not frozenset
                    or len(self.allowed_result_refs) > 10
                    or any(type(ref) is not UUID for ref in self.allowed_result_refs)
                    or type(self.omitted_context) is not bool):
                raise ValueError("exact prepared records required")
            WorkContext.__post_init__(self.original_ctx)
            ProviderCallToken.__post_init__(self.token)
            ChatCompletionReceipt.__post_init__(self.receipt)
            result = ChatResult.model_validate(self.result.model_dump())
            message = WorkMessageDTO.model_validate(self.message.model_dump())
            context, token = self.original_ctx, self.token
            if (type(context.owner_storage_id) is not UUID or type(context.task_id) is not UUID
                    or (context.offering_id is not None and type(context.offering_id) is not UUID)
                    or type(self.result.result_refs) is not tuple or type(self.message.result_refs) is not tuple
                    or result.omitted_context is not self.omitted_context
                    or not set(result.result_refs) <= self.allowed_result_refs
                    or message.client_message_key is not None or message.role != "assistant"
                    or (message.owner, message.task_id, message.run_id) !=
                       (context.actor_subject, context.task_id, token.run_id)
                    or self.receipt != ChatCompletionReceipt(token.run_id, message.message_id)
                    or chat_result_from_message(message) != result):
                raise ValueError("prepared completion binding mismatch")
            snapshot = canonical_json_bytes({
                "context": {"subject": context.actor_subject, "namespace": str(context.owner_storage_id),
                    "task": str(context.task_id), "institution": context.institution_id,
                    "offering": str(context.offering_id) if context.offering_id is not None else None,
                    "input_revision": context.input_revision, "working_revision": context.working_revision},
                "token": {"run": str(token.run_id), "attempt": token.attempt, "call": token.call_no,
                    "lease_revision": token.lease_revision, "process": str(token.process_instance)},
                "result": result.model_dump(mode="json"), "message": message.model_dump(mode="json"),
                "receipt": {"run": str(self.receipt.run_id), "message": str(self.receipt.message_id)},
                "allowed_refs": sorted(str(ref) for ref in self.allowed_result_refs),
                "omitted_context": self.omitted_context,
            })
            if hasattr(self, "_snapshot"):
                if type(self._snapshot) is not bytes or self._snapshot != snapshot:
                    raise ValueError("prepared completion changed")
            else:
                object.__setattr__(self, "_snapshot", snapshot)
        except (WorkRunError, ValidationError, ValueError, TypeError, AttributeError, UnicodeError):
            raise WorkRunError(code, 503) from None


def chat_result_from_message(message: WorkMessageDTO) -> ChatResult | None:
    """Project an actual classified candidate, never manufacture a result."""
    _validate_message(message)
    if message.result_type is None and message.omitted_context is None:
        return None
    try:
        return ChatResult.model_validate({"type": message.result_type, "plain_text": message.plain_text,
                                          "result_refs": message.result_refs, "omitted_context": message.omitted_context})
    except (ValidationError, ValueError, TypeError):
        raise WorkRunError("INVALID_STORED_MESSAGE", 503) from None


def validate_chat_completion(run: RunDTO, message: WorkMessageDTO, completion_run_id: UUID) -> ChatCompletionReceipt:
    """Validate one proposed receipt; this does not certify a committed row."""
    _validate_run(run)
    _validate_message(message)
    if (run.kind != "chat" or type(completion_run_id) is not UUID or completion_run_id != run.run_id
            or message.owner != run.owner or message.task_id != run.task_id or message.run_id != run.run_id
            or message.role != "assistant" or chat_result_from_message(message) is None):
        raise WorkRunError("INVALID_CHAT_COMPLETION", 503)
    return ChatCompletionReceipt(run_id=run.run_id, message_id=message.message_id)


def _validate_chat_candidate(task: WorkTaskDTO, state: StoredRunState,
                             lease: OwnerLeaseFacts, *, code: str,
                             context: WorkContext | None = None) -> None:
    """Check detached value coherence, never current authority or commit."""
    try:
        if type(task) is not WorkTaskDTO or type(state) is not StoredRunState or type(lease) is not OwnerLeaseFacts:
            raise ValueError("exact candidate records required")
        WorkTaskDTO.model_validate(task.model_dump())
        StoredRunState.__post_init__(state)
        OwnerLeaseFacts.__post_init__(lease)
        if (type(lease.owner_storage_id) is not UUID
                or (lease.active_run_id is not None and type(lease.active_run_id) is not UUID)
                or (lease.process_instance is not None and type(lease.process_instance) is not UUID)
                or state.run.kind != "chat"
                or state.run.stage not in {"PENDING", "CHAT_RUNNING", "COMPLETE", "FAILED", "CANCELLED", "INTERRUPTED"}
                or (state.run.owner, state.run.task_id) != (task.owner_subject, task.task_id)
                or (lease.owner, lease.owner_storage_id) != (task.owner_subject, task.owner_storage_id)):
            raise ValueError("candidate binding mismatch")
        if context is not None:
            if type(context) is not WorkContext:
                raise ValueError("exact context required")
            WorkContext.__post_init__(context)
            if (type(context.owner_storage_id) is not UUID or type(context.task_id) is not UUID
                    or (context.offering_id is not None and type(context.offering_id) is not UUID)
                    or (context.actor_subject, context.owner_storage_id, context.task_id,
                        context.institution_id, context.offering_id, context.input_revision,
                        context.working_revision) !=
                    (task.owner_subject, task.owner_storage_id, task.task_id,
                     task.institution_id, task.offering_id, task.input_revision, task.working_revision)):
                raise ValueError("candidate context mismatch")
    except (WorkRunError, ValidationError, ValueError, TypeError, AttributeError):
        raise WorkRunError(code, 503) from None


@dataclass(frozen=True)
class ChatRunAdmission:
    """Uncommitted admission/replay facts; created never certifies dispatch."""
    task: WorkTaskDTO
    context: WorkContext
    state: StoredRunState
    user_message: WorkMessageDTO
    lease: OwnerLeaseFacts
    created: bool

    def __post_init__(self):
        code = "INVALID_CHAT_ADMISSION"
        if type(self.context) is not WorkContext or type(self.created) is not bool:
            raise WorkRunError(code, 503)
        _validate_chat_candidate(self.task, self.state, self.lease, code=code, context=self.context)
        _validate_message(self.user_message)
        message = self.user_message
        if (type(message) is not WorkMessageDTO or message.role != "user"
                or message.client_message_key is None
                or (message.owner, message.task_id, message.run_id) !=
                (self.state.run.owner, self.state.run.task_id, self.state.run.run_id)
                or message.result_type is not None or message.omitted_context is not None):
            raise WorkRunError(code, 503)
        # Replay may observe a historical revision or another run's current lease.
        # The command coordinator, not this value, decides whether creation is valid.


@dataclass(frozen=True)
class ChatRequestObservation:
    """Authorized lookup candidate; its construction proves no authorization."""
    task: WorkTaskDTO
    context: WorkContext
    admission: ChatRunAdmission | None

    def __post_init__(self):
        code = "INVALID_CHAT_OBSERVATION"
        try:
            if type(self.task) is not WorkTaskDTO or type(self.context) is not WorkContext:
                raise ValueError("exact observation records required")
            WorkTaskDTO.model_validate(self.task.model_dump())
            WorkContext.__post_init__(self.context)
            if (type(self.context.owner_storage_id) is not UUID or type(self.context.task_id) is not UUID
                    or (self.context.offering_id is not None and type(self.context.offering_id) is not UUID)):
                raise ValueError("exact context UUIDs required")
            if (self.context.actor_subject, self.context.owner_storage_id, self.context.task_id,
                    self.context.institution_id, self.context.offering_id, self.context.input_revision,
                    self.context.working_revision) != (
                    self.task.owner_subject, self.task.owner_storage_id, self.task.task_id,
                    self.task.institution_id, self.task.offering_id, self.task.input_revision,
                    self.task.working_revision):
                raise ValueError("observation binding mismatch")
            if self.admission is not None:
                if type(self.admission) is not ChatRunAdmission:
                    raise ValueError("exact admission required")
                ChatRunAdmission.__post_init__(self.admission)
                if (self.admission.created or self.admission.task != self.task
                        or self.admission.context != self.context):
                    raise ValueError("observation receipt mismatch")
        except (WorkRunError, ValidationError, ValueError, TypeError, AttributeError):
            raise WorkRunError(code, 503) from None


@dataclass(frozen=True)
class ChatCallReservation:
    """Uncommitted charged-call candidate, never permission to open transport."""
    task: WorkTaskDTO
    context: WorkContext
    state: StoredRunState
    lease: OwnerLeaseFacts
    token: ProviderCallToken
    limits: CallLimits

    def __post_init__(self):
        code = "INVALID_CHAT_RESERVATION"
        if type(self.context) is not WorkContext:
            raise WorkRunError(code, 503)
        _validate_chat_candidate(self.task, self.state, self.lease, code=code, context=self.context)
        if type(self.token) is not ProviderCallToken or type(self.limits) is not CallLimits:
            raise WorkRunError(code, 503)
        ProviderCallToken.__post_init__(self.token)
        CallLimits.__post_init__(self.limits)
        if (self.state.active_call != self.token or self.state.run.stage != "CHAT_RUNNING"
                or self.state.run.cancelled_at is not None
                or self.state.run.input_revision != self.context.input_revision
                or (self.lease.active_run_id, self.lease.process_instance, self.lease.revision) !=
                (self.token.run_id, self.token.process_instance, self.token.lease_revision)):
            raise WorkRunError(code, 503)


@dataclass(frozen=True)
class ChatRunOutcome:
    """Uncommitted run/receipt observation, not a successful commit receipt."""
    task: WorkTaskDTO
    state: StoredRunState
    lease: OwnerLeaseFacts
    completion: ChatCompletionReceipt | None

    def __post_init__(self):
        code = "INVALID_CHAT_OUTCOME"
        _validate_chat_candidate(self.task, self.state, self.lease, code=code)
        if self.completion is None:
            if self.state.run.stage == "COMPLETE":
                raise WorkRunError(code, 503)
            return
        if type(self.completion) is not ChatCompletionReceipt:
            raise WorkRunError(code, 503)
        ChatCompletionReceipt.__post_init__(self.completion)
        if (self.completion.run_id != self.state.run.run_id
                or self.state.run.stage != "COMPLETE" or self.state.active_call is not None):
            raise WorkRunError(code, 503)


def _stored_uuid(value: object) -> UUID:
    if type(value) is not str:
        raise ValueError("canonical stored UUID required")
    decoded = UUID(value)
    if str(decoded) != value:
        raise ValueError("canonical stored UUID required")
    return decoded


def _stored_optional_uuid(value: object) -> UUID | None:
    return None if value is None else _stored_uuid(value)


def _stored_integer(value: object, *, minimum: int, maximum: int | None = None) -> int:
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise ValueError("exact bounded stored integer required")
    return value


def _stored_subject(value: object) -> str:
    if type(value) is not str or not value or value != value.strip() or len(value) > 255:
        raise ValueError("exact stored subject required")
    return value


def _stored_utc(value: object) -> datetime:
    """MySQL DATETIME stores UTC without tzinfo under the Work SQL contract.

    Only an actual datetime is accepted: naive MySQL values receive UTC tzinfo,
    while aware values are converted to UTC. Text/epoch values are not decoded.
    """
    if type(value) is not datetime:
        raise ValueError("stored datetime required")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    if value.utcoffset() is None:
        raise ValueError("stored datetime offset required")
    return value.astimezone(timezone.utc)


def _stored_optional_utc(value: object) -> datetime | None:
    return None if value is None else _stored_utc(value)


def _stored_boolean(value: object) -> bool:
    """Documented MySQL BOOLEAN representations: native bool or exact int 0/1."""
    if type(value) is bool:
        return value
    if type(value) is int and value in (0, 1):
        return value == 1
    raise ValueError("documented stored Boolean required")


def _stored_result_refs(value: object) -> tuple[UUID, ...]:
    # The SQL boundary supplies decoded JSON. A JSON string, tuple, scalar,
    # UUID object or malformed canonical UUID must not be silently converted.
    if type(value) is not list or len(value) > 10:
        raise ValueError("stored result-ref JSON array required")
    refs = tuple(_stored_uuid(item) for item in value)
    if len(set(refs)) != len(refs):
        raise ValueError("stored result refs must be distinct")
    return refs


def decode_stored_run(row: object) -> StoredRunState:
    """Decode trusted attribute-shaped row data without importing SQL objects.

    Every nullable attribute must exist explicitly. There are no defaults for
    historical budgets or token fields and no coercion of binary receipt keys.
    """
    try:
        run = RunDTO(
            run_id=_stored_uuid(row.run_id), owner=_stored_subject(row.owner),
            task_id=_stored_uuid(row.task_id), kind=row.kind, skill_ref=row.skill_ref,
            input_revision=_stored_integer(row.input_revision, minimum=1),
            outline_revision=(None if row.outline_revision is None else
                              _stored_integer(row.outline_revision, minimum=1)),
            idempotency_key=decode_work_key(row.idempotency_key), request_digest=row.request_digest,
            stage=row.stage, attempt=_stored_integer(row.attempt, minimum=1, maximum=2),
            provider_call_count=_stored_integer(row.provider_call_count, minimum=0, maximum=3),
            deadline=_stored_utc(row.deadline), cancelled_at=_stored_optional_utc(row.cancelled_at),
            error_code=row.error_code, result_version_id=_stored_optional_uuid(row.result_version_id),
        )
        repairs = _stored_integer(row.repair_count, minimum=0, maximum=1)
        fields = (row.active_call_no, row.active_call_attempt,
                  row.active_call_lease_revision, row.active_call_process_instance)
        active = None
        if any(value is not None for value in fields):
            if any(value is None for value in fields):
                raise ValueError("stored token fields must be paired")
            active = ProviderCallToken(
                run_id=run.run_id,
                attempt=_stored_integer(row.active_call_attempt, minimum=1, maximum=2),
                call_no=_stored_integer(row.active_call_no, minimum=1, maximum=3),
                lease_revision=_stored_integer(row.active_call_lease_revision, minimum=1),
                process_instance=_stored_uuid(row.active_call_process_instance),
            )
        return StoredRunState(run, repairs, active)
    except (WorkRunError, ValidationError, ValueError, TypeError, AttributeError, OverflowError):
        raise WorkRunError("INVALID_STORED_RUN", 503) from None


def decode_stored_message(row: object) -> tuple[WorkMessageDTO, UUID | None]:
    """Return the exact message plus its separate completion-run identity.

    Historical unclassified messages stay unclassified; no answer/omission
    metadata or assistant client key is fabricated from role or run linkage.
    """
    try:
        fields = (row.completion_run_id, row.result_type, row.omitted_context)
        classified = any(value is not None for value in fields)
        if classified and any(value is None for value in fields):
            raise ValueError("stored completion fields must be paired")
        completion_run_id = _stored_optional_uuid(row.completion_run_id)
        run_id = _stored_optional_uuid(row.run_id)
        client_key = None if row.client_message_key is None else decode_work_key(row.client_message_key)
        if classified and (row.role != "assistant" or client_key is not None
                           or run_id is None or run_id != completion_run_id):
            raise ValueError("stored completion linkage mismatch")
        message = WorkMessageDTO(
            message_id=_stored_uuid(row.message_id), task_id=_stored_uuid(row.task_id),
            owner=_stored_subject(row.owner), client_message_key=client_key, role=row.role,
            plain_text=row.plain_text, run_id=run_id, result_refs=_stored_result_refs(row.result_refs),
            result_type=row.result_type,
            omitted_context=_stored_boolean(row.omitted_context) if classified else None,
            created_at=_stored_utc(row.created_at),
        )
        return message, completion_run_id
    except (WorkRunError, ValidationError, ValueError, TypeError, AttributeError, OverflowError):
        raise WorkRunError("INVALID_STORED_MESSAGE", 503) from None


def decode_owner_lease(row: object) -> OwnerLeaseFacts:
    """Decode one existing namespace row; never initialize or renew a lease."""
    try:
        fields = (row.active_run_id, row.process_instance, row.expires_at)
        if any(value is not None for value in fields) and any(value is None for value in fields):
            raise ValueError("stored active lease fields must be paired")
        return OwnerLeaseFacts(
            owner=_stored_subject(row.owner), owner_storage_id=_stored_uuid(row.owner_storage_id),
            active_run_id=_stored_optional_uuid(row.active_run_id),
            process_instance=_stored_optional_uuid(row.process_instance),
            expires_at=_stored_optional_utc(row.expires_at),
            revision=_stored_integer(row.revision, minimum=1),
        )
    except (WorkRunError, ValueError, TypeError, AttributeError, OverflowError):
        raise WorkRunError("INVALID_LEASE", 503) from None
