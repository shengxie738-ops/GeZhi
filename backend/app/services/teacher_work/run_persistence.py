"""Pure Teacher Work persistence values, never row readers or durable writers.

Supplied tokens/counts/receipts are strict records, not authority or evidence of
admission, dispatch, settlement, cancellation, storage or a committed reply. The
later SQL boundary must decode all-or-none fields, compare current authority,
charge before dispatch and finalize the actual assistant row atomically.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from pydantic import TypeAdapter, ValidationError

from app.schemas.teacher_work import ChatResult, MessageKey, RunDTO, WorkMessageDTO
from app.services.teacher_work.runs import WorkBudget, WorkRunError


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
