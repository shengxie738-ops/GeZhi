"""Pure finite chat-run comparisons and detached value transitions.

No provider dispatch, semaphore/lease reservation, durable budget, authority
loader, transaction, restart or commit lives here. Supplied fresh facts must
come from the separately reviewed Task4b boundaries; equality is not readiness.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from pydantic import TypeAdapter, ValidationError

from app.schemas.teacher_work import ChatCommand, MessageKey, RunDTO
from app.services.teacher_work.types import WorkContext, canonical_digest


class WorkRunError(Exception):
    def __init__(self, code: str, status_code: int):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def _instant(value, code="INVALID_RUN_FACTS"):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise WorkRunError(code, 503)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class OwnerLeaseFacts:
    owner: str
    owner_storage_id: UUID
    active_run_id: UUID | None
    process_instance: UUID | None
    expires_at: datetime | None
    revision: int

    def __post_init__(self):
        if (type(self.owner) is not str or not self.owner or self.owner != self.owner.strip() or len(self.owner) > 255
                or not isinstance(self.owner_storage_id, UUID) or type(self.revision) is not int or self.revision < 1):
            raise WorkRunError("INVALID_LEASE", 503)
        active = (self.active_run_id, self.process_instance, self.expires_at)
        if all(value is None for value in active):
            return
        if any(value is None for value in active) or not isinstance(self.active_run_id, UUID) or not isinstance(self.process_instance, UUID):
            raise WorkRunError("INVALID_LEASE", 503)
        _instant(self.expires_at, "INVALID_LEASE")


@dataclass(frozen=True)
class CallLimits:
    max_output_tokens: int
    timeout_seconds: int

    def __post_init__(self):
        if (type(self.max_output_tokens) is not int or not 1 <= self.max_output_tokens <= 8192
                or type(self.timeout_seconds) is not int or not 1 <= self.timeout_seconds <= 90):
            raise WorkRunError("INVALID_CALL_LIMITS", 503)


@dataclass
class WorkBudget:
    """Local ledger only; a durable pre-dispatch charge remains Task4b."""
    attempt: int = 1
    provider_call_count: int = 0
    repair_count: int = 0

    def __post_init__(self):
        self._validate()

    def _validate(self):
        if (type(self.attempt) is not int or not 1 <= self.attempt <= 2
                or type(self.provider_call_count) is not int or not 0 <= self.provider_call_count <= 3
                or type(self.repair_count) is not int or not 0 <= self.repair_count <= 1
                or self.repair_count > self.provider_call_count):
            raise WorkRunError("INVALID_BUDGET", 503)

    def consume_ai_call(self, *, repair=False):
        self._validate()
        if type(repair) is not bool:
            raise WorkRunError("INVALID_BUDGET", 503)
        if self.provider_call_count >= 3:
            raise WorkRunError("AI_CALL_BUDGET_EXHAUSTED", 409)
        if repair and self.repair_count >= 1:
            raise WorkRunError("REPAIR_BUDGET_EXHAUSTED", 409)
        self.provider_call_count += 1
        if repair:
            self.repair_count += 1

    def advance_attempt(self):
        self._validate()
        if self.attempt >= 2:
            raise WorkRunError("ATTEMPT_BUDGET_EXHAUSTED", 409)
        self.attempt += 1  # Calls/repairs deliberately remain cumulative.


def chat_request_digest(command: ChatCommand) -> str:
    if not isinstance(command, ChatCommand):
        raise WorkRunError("INVALID_CHAT_COMMAND", 422)
    try:
        strict = ChatCommand.model_validate(command.model_dump())
        return canonical_digest(strict.model_dump(mode="json"))
    except (ValidationError, TypeError, ValueError, UnicodeError):
        raise WorkRunError("INVALID_CHAT_COMMAND", 422) from None


def match_chat_replay(ctx: WorkContext, command: ChatCommand, key: str, existing: RunDTO | None) -> RunDTO | None:
    try:
        exact_key = TypeAdapter(MessageKey).validate_python(key)
    except ValidationError:
        raise WorkRunError("INVALID_MESSAGE_KEY", 422) from None
    digest = chat_request_digest(command)
    if not isinstance(ctx, WorkContext):
        raise WorkRunError("RUN_SCOPE_MISMATCH", 404)
    if existing is None:
        return None
    if (not isinstance(existing, RunDTO) or existing.owner != ctx.actor_subject
            or existing.task_id != ctx.task_id or existing.kind != "chat"):
        raise WorkRunError("RUN_SCOPE_MISMATCH", 404)
    if existing.idempotency_key != exact_key:
        raise WorkRunError("RUN_RECEIPT_MISMATCH", 503)
    if existing.request_digest != digest:
        raise WorkRunError("IDEMPOTENCY_CONFLICT", 409)
    if existing.input_revision != command.input_revision or existing.skill_ref is not None:
        raise WorkRunError("RUN_RECEIPT_MISMATCH", 503)
    return existing  # Receipt observation only; never dispatch or allocate.


def chat_call_limits(configured_output_tokens: int, configured_timeout_seconds: int, *, deadline: datetime, now: datetime) -> CallLimits:
    if (type(configured_output_tokens) is not int or configured_output_tokens < 1
            or type(configured_timeout_seconds) is not int or configured_timeout_seconds < 1):
        raise WorkRunError("INVALID_CALL_LIMITS", 503)
    remaining = (_instant(deadline, "INVALID_CALL_LIMITS") - _instant(now, "INVALID_CALL_LIMITS")).total_seconds()
    if remaining < 1:
        raise WorkRunError("CHAT_DEADLINE_EXPIRED", 409)
    # The positive minimum's integer conversion is floor, never rounds upward.
    return CallLimits(min(configured_output_tokens, 8192), int(min(configured_timeout_seconds, 90, remaining)))


def require_chat_slot(active_count: int, *, limit: int = 4) -> None:
    if type(active_count) is not int or active_count < 0 or type(limit) is not int or limit < 1:
        raise WorkRunError("INVALID_SLOT_FACTS", 503)
    if active_count >= limit:
        raise WorkRunError("INSTANCE_BUSY", 429)


def require_owner_lease_available(ctx: WorkContext, lease: OwnerLeaseFacts | None) -> None:
    if not isinstance(ctx, WorkContext) or lease is None:
        raise WorkRunError("OWNER_NAMESPACE_UNAVAILABLE", 503)
    if not isinstance(lease, OwnerLeaseFacts) or (lease.owner, lease.owner_storage_id) != (ctx.actor_subject, ctx.owner_storage_id):
        raise WorkRunError("OWNER_NAMESPACE_MISMATCH", 503)
    if lease.active_run_id is not None:
        raise WorkRunError("OWNER_RUN_BUSY", 409)


_TERMINAL = frozenset({"COMPLETE", "FAILED", "CANCELLED", "INTERRUPTED"})


def _chat_run(run):
    if not isinstance(run, RunDTO) or run.kind != "chat" or run.stage not in _TERMINAL | {"PENDING", "CHAT_RUNNING"}:
        raise WorkRunError("INVALID_RUN_FACTS", 503)


def _linked_lease(run, lease):
    if not isinstance(lease, OwnerLeaseFacts) or lease.owner != run.owner or lease.active_run_id != run.run_id:
        raise WorkRunError("OWNER_LEASE_LOST", 409)


def check_chat_commit(ctx: WorkContext, run: RunDTO, lease: OwnerLeaseFacts, current_ctx: WorkContext | None,
                      *, process_instance: UUID, now: datetime) -> WorkContext:
    """Compare supplied facts only; this neither obtains authority nor commits."""
    _chat_run(run)
    at = _instant(now)
    if not isinstance(ctx, WorkContext) or run.owner != ctx.actor_subject or run.task_id != ctx.task_id:
        raise WorkRunError("RUN_SCOPE_MISMATCH", 404)
    if run.cancelled_at is not None:
        raise WorkRunError("RUN_CANCELLED", 409)
    if run.stage != "CHAT_RUNNING":
        raise WorkRunError("RUN_NOT_ACTIVE", 409)
    if run.input_revision != ctx.input_revision:
        raise WorkRunError("STALE_INPUT_REVISION", 409)
    if at >= run.deadline:
        raise WorkRunError("RUN_DEADLINE_EXPIRED", 409)
    _linked_lease(run, lease)
    if (not isinstance(process_instance, UUID) or lease.process_instance != process_instance
            or lease.owner_storage_id != ctx.owner_storage_id or at >= lease.expires_at):
        raise WorkRunError("OWNER_LEASE_LOST", 409)
    if not isinstance(current_ctx, WorkContext):
        raise WorkRunError("CURRENT_AUTHORITY_UNAVAILABLE", 403)
    identity = (ctx.actor_subject, ctx.owner_storage_id, ctx.task_id, ctx.institution_id, ctx.offering_id)
    current_identity = (current_ctx.actor_subject, current_ctx.owner_storage_id, current_ctx.task_id,
                        current_ctx.institution_id, current_ctx.offering_id)
    if current_identity != identity:
        raise WorkRunError("CURRENT_SCOPE_CHANGED", 403)
    if current_ctx.input_revision != ctx.input_revision:
        raise WorkRunError("STALE_INPUT_REVISION", 409)
    return current_ctx


def cancel_chat_run(run: RunDTO, *, now: datetime) -> RunDTO:
    _chat_run(run)
    at = _instant(now)
    if run.stage in _TERMINAL:
        return run
    return run.model_copy(update={"stage": "CANCELLED", "cancelled_at": run.cancelled_at or at})


def can_release_chat_lease(run: RunDTO, *, call_in_flight: bool) -> bool:
    _chat_run(run)
    if type(call_in_flight) is not bool:
        raise WorkRunError("INVALID_RUN_FACTS", 503)
    return run.stage in _TERMINAL and not call_in_flight


def interrupt_expired_chat_run(run: RunDTO, lease: OwnerLeaseFacts, *, now: datetime, process_alive: bool) -> RunDTO:
    _chat_run(run)
    at = _instant(now)
    if type(process_alive) is not bool:
        raise WorkRunError("INVALID_RUN_FACTS", 503)
    _linked_lease(run, lease)
    if run.stage in _TERMINAL or process_alive or at < lease.expires_at:
        return run
    return run.model_copy(update={"stage": "INTERRUPTED", "error_code": "PROCESS_INTERRUPTED"})
