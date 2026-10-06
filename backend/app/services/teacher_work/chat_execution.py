"""Detached first-call chat integration with explicit trusted server assembly.

All transaction operations are trusted server construction dependencies. They
must finalize through the existing request owner and close their fresh root
before returning. This module opens no Session, creates no client/settings and
cannot turn a detached candidate, request flag or GET into dispatch authority.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Callable, Protocol
from uuid import UUID

from app.repositories.teacher_work import WorkRepositoryError
from app.schemas.teacher_work import ChatCommand, ChatTaskBrief, EvidenceSnapshotDTO, RunDTO, WorkMessageDTO
from app.services.teacher_work.authorization import WorkAuthorizationError
from app.services.teacher_work.chat import ChatPreparationError, prepare_chat_prompt, parse_chat_result
from app.services.teacher_work.run_persistence import (
    ChatCallReservation, ChatRequestObservation, ChatRunAdmission, ChatRunOutcome,
    PreparedChatCompletion, ProviderCallToken, validate_chat_completion,
)
from app.services.teacher_work.runs import WorkRunError, chat_request_digest, require_chat_slot
from app.services.teacher_work.types import WorkAI, WorkContext, canonical_json_bytes


class ChatTransactionOperations(Protocol):
    """Synchronous fresh-root owner-finalized operations, never raw candidates."""
    def inspect_chat_request(self, owner: str, task_id: UUID, command: ChatCommand, key: str) -> ChatRequestObservation: ...
    def admit_chat(self, owner: str, task_id: UUID, command: ChatCommand, key: str, *, process_instance: UUID,
                   configured_timeout_seconds: int) -> ChatRunAdmission: ...
    def reserve_chat_call(self, owner: str, task_id: UUID, run_id: UUID, *, process_instance: UUID,
                          configured_output_tokens: int, configured_timeout_seconds: int,
                          repair: bool = False) -> ChatCallReservation: ...
    def complete_prepared_chat_call(self, prepared: PreparedChatCompletion) -> ChatRunOutcome: ...
    def fail_chat_call(self, original_ctx: WorkContext, token: ProviderCallToken, error_code: str) -> ChatRunOutcome: ...
    def expire_chat_call(self, original_ctx: WorkContext, token: ProviderCallToken) -> ChatRunOutcome: ...
    def fail_pending_chat(self, owner: str, task_id: UUID, run_id: UUID, *, process_instance: UUID,
                          error_code: str) -> ChatRunOutcome: ...
    def cancel_chat(self, owner: str, task_id: UUID, run_id: UUID) -> ChatRunOutcome: ...
    def get_chat_run(self, owner: str, task_id: UUID, run_id: UUID) -> ChatRunOutcome: ...


class ChatExecutionClock(Protocol):
    def utc_now(self) -> datetime: ...
    def monotonic(self) -> float: ...
    async def wait_until(self, monotonic_deadline: float) -> None: ...


@dataclass(frozen=True, init=False)
class ChatExecutionContext:
    """Immutable server snapshots; request schemas themselves remain unchanged.

    ChatCommand is mutable in the existing HTTP schema. Keep immutable canonical
    bytes here and return a fresh validated command, never an aliased request.
    History/evidence use the existing frozen DTOs with immutable tuple fields.
    Snapshot coherence cannot certify current evidence authority or readiness.
    """
    _command_bytes: bytes
    history: tuple[WorkMessageDTO, ...]
    evidence: tuple[EvidenceSnapshotDTO, ...]
    task_brief: ChatTaskBrief | None

    def __init__(self, *, command: ChatCommand, history: tuple[WorkMessageDTO, ...],
                 evidence: tuple[EvidenceSnapshotDTO, ...], task_brief: ChatTaskBrief | None = None):
        try:
            if (type(command) is not ChatCommand or type(history) is not tuple or type(evidence) is not tuple
                    or any(type(item) is not WorkMessageDTO for item in history)
                    or any(type(item) is not EvidenceSnapshotDTO for item in evidence)):
                raise ValueError("exact server snapshots required")
            strict = ChatCommand.model_validate(command.model_dump())
            object.__setattr__(self, "_command_bytes", canonical_json_bytes(strict.model_dump(mode="json")))
            object.__setattr__(self, "history", tuple(WorkMessageDTO.model_validate(item.model_dump()) for item in history))
            object.__setattr__(self, "evidence", tuple(EvidenceSnapshotDTO.model_validate(item.model_dump()) for item in evidence))
            if task_brief is not None and type(task_brief) is not ChatTaskBrief:
                raise ValueError("exact brief required")
            object.__setattr__(self, "task_brief", None if task_brief is None else ChatTaskBrief.model_validate(task_brief.model_dump()))
        except (ValueError, TypeError, AttributeError, UnicodeError):
            raise WorkRunError("INVALID_CHAT_INPUT", 422) from None

    @property
    def command(self) -> ChatCommand:
        return ChatCommand.model_validate_json(self._command_bytes)


class ChatContextSource(Protocol):
    def load(self, admission: ChatRunAdmission) -> ChatExecutionContext: ...


class ChatExecutionError(WorkRunError):
    """Controlled internal error with an actual run locator when one exists."""
    def __init__(self, code: str, status_code: int = 503, *, run_id: UUID | None = None,
                 transaction_unknown: bool = False):
        super().__init__(code, status_code)
        self.run_id = run_id
        self.transaction_unknown = transaction_unknown


@dataclass
class _LocalChat:
    admission: ChatRunAdmission
    slot: object
    monotonic_deadline: float
    supervisor: asyncio.Task | None = None
    entry_coroutine: object | None = None
    provider: asyncio.Task | None = None
    timer: asyncio.Task | None = None
    reservation: ChatCallReservation | None = None
    prepared: PreparedChatCompletion | None = None
    started: bool = False
    cancelled: bool = False
    timed_out: bool = False
    claim_attempted: bool = False
    unresolved_completion: bool = False


_CONTROLLED = (WorkRunError, WorkRepositoryError, WorkAuthorizationError)
_AI_ERRORS = frozenset({"WORK_AI_UNAVAILABLE", "WORK_AI_TIMEOUT", "WORK_AI_RATE_LIMITED",
                        "WORK_AI_UPSTREAM_FAILED", "WORK_AI_INVALID_RESPONSE"})


class TeacherChatExecution:
    """One first call per confirmed local admission, no queue/restart/recovery."""
    def __init__(self, *, transactions: ChatTransactionOperations, ai: WorkAI,
                 context_source: ChatContextSource, process_instance: UUID, clock: ChatExecutionClock,
                 new_uuid: Callable[[], UUID], configured_output_tokens: int,
                 configured_timeout_seconds: int, capacity: int = 4,
                 schedule: Callable[[object], asyncio.Task] | None = None):
        if (type(process_instance) is not UUID or not callable(new_uuid)
                or type(configured_output_tokens) is not int or configured_output_tokens < 1
                or type(configured_timeout_seconds) is not int or configured_timeout_seconds < 1
                or type(capacity) is not int or not 1 <= capacity <= 4
                or (schedule is not None and not callable(schedule))):
            raise WorkRunError("INVALID_CALL_LIMITS", 503)
        self.transactions, self.ai, self.context_source = transactions, ai, context_source
        self.process_instance, self.clock, self.new_uuid = process_instance, clock, new_uuid
        self.configured_output_tokens, self.configured_timeout_seconds = configured_output_tokens, configured_timeout_seconds
        self.capacity, self.schedule = capacity, schedule if schedule is not None else asyncio.create_task
        self._slots: set[object] = set()
        self._runs: dict[UUID, _LocalChat] = {}

    def _utc(self) -> datetime:
        value = self.clock.utc_now()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ChatExecutionError("WORK_EXECUTION_UNAVAILABLE")
        return value.astimezone(timezone.utc)

    def _monotonic(self) -> float:
        value = self.clock.monotonic()
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ChatExecutionError("WORK_EXECUTION_UNAVAILABLE")
        return float(value)

    def _transaction(self, name: str, expected: type, *args, **kwargs):
        write = name not in ("inspect_chat_request", "get_chat_run")
        try:
            value = getattr(self.transactions, name)(*args, **kwargs)
        except _CONTROLLED:
            raise
        except Exception:
            # A violated server-operation contract gives no commit certainty.
            # Keep its public error controlled while completion reconciliation
            # treats an unclassified write outcome conservatively as unknown.
            raise ChatExecutionError("WORK_EXECUTION_UNAVAILABLE", transaction_unknown=write) from None
        try:
            # Transaction dependencies are strictly synchronous. An accidental
            # coroutine is not finalized data or permission to dispatch.
            if asyncio.iscoroutine(value):
                value.close()
                raise ChatExecutionError("WORK_EXECUTION_UNAVAILABLE", transaction_unknown=write)
            if type(value) is not expected:
                raise ChatExecutionError("WORK_EXECUTION_UNAVAILABLE", transaction_unknown=write)
            value.__post_init__()
            return value
        except ChatExecutionError:
            raise
        except Exception:
            raise ChatExecutionError("WORK_EXECUTION_UNAVAILABLE", transaction_unknown=write) from None

    def _release(self, local: _LocalChat) -> None:
        # Called only for known absence/actual local terminal transport. Durable
        # cleanup may still be denied; releasing local capacity does not invent
        # an owner-lease release or authorize another call for that owner.
        if local.provider is not None and not local.provider.done():
            return
        if local.unresolved_completion:
            return
        self._slots.discard(local.slot)
        if self._runs.get(local.admission.state.run.run_id) is local:
            del self._runs[local.admission.state.run.run_id]

    @staticmethod
    def _uncharged_terminal_entry(local: _LocalChat, outcome: ChatRunOutcome) -> bool:
        """Fresh finalized facts, never the admission's stale zero-call snapshot."""
        ctx, original = local.admission.context, local.admission.state.run
        task, state, lease = outcome.task, outcome.state, outcome.lease
        run = state.run
        return ((task.owner_subject, task.owner_storage_id, task.task_id,
                 task.institution_id, task.offering_id) ==
                (ctx.actor_subject, ctx.owner_storage_id, ctx.task_id,
                 ctx.institution_id, ctx.offering_id)
                and (run.owner, run.task_id, run.run_id, run.input_revision,
                     run.attempt, run.request_digest, run.idempotency_key, run.deadline) ==
                    (original.owner, original.task_id, original.run_id, original.input_revision,
                     original.attempt, original.request_digest, original.idempotency_key, original.deadline)
                and run.kind == "chat" and run.skill_ref is None
                and run.stage in {"FAILED", "CANCELLED"}
                and run.provider_call_count == 0 and state.repair_count == 0
                and state.active_call is None and outcome.completion is None
                and (lease.owner, lease.owner_storage_id) == (ctx.actor_subject, ctx.owner_storage_id)
                and lease.active_run_id != original.run_id)

    def _finish_unentered(self, local: _LocalChat, supervisor: asyncio.Task) -> None:
        """A cancelled-before-entry coroutine cannot run its own finally block."""
        run = local.admission.state.run
        if (self._runs.get(run.run_id) is not local or local.supervisor is not supervisor
                or not supervisor.done() or local.started or local.claim_attempted
                or local.provider is not None or local.reservation is not None):
            return
        try:
            supervisor.result()
        except asyncio.CancelledError:
            pass
        except Exception:
            pass  # Consume a failed wrapper without logging its private repr.
        try:
            if local.entry_coroutine is not None:
                local.entry_coroutine.close()
        except Exception:
            return  # Unknown coroutine state is not unused-capacity evidence.
        try:
            outcome = self._transaction("fail_pending_chat", ChatRunOutcome, run.owner,
                run.task_id, run.run_id, process_instance=self.process_instance,
                error_code="WORK_EXECUTION_UNAVAILABLE")
        except _CONTROLLED:
            # A charge, denial, replacement lease or unknown write may have
            # intervened. One fresh authorized read can confirm an old terminal
            # no-call run; it cannot replay cleanup or touch a newer lease.
            try:
                outcome = self._transaction("get_chat_run", ChatRunOutcome,
                    run.owner, run.task_id, run.run_id)
            except _CONTROLLED:
                return
        if self._uncharged_terminal_entry(local, outcome):
            self._release(local)

    async def start_chat(self, owner: str, task_id: UUID, command: ChatCommand, key: str) -> RunDTO:
        utc_anchor, monotonic_anchor = self._utc(), self._monotonic()
        observation = self._transaction("inspect_chat_request", ChatRequestObservation, owner, task_id, command, key)
        if observation.admission is not None:
            return observation.admission.state.run
        if len(self._slots) >= self.capacity:
            # The one permitted fresh read can observe a concurrently committed
            # exact receipt; it still cannot schedule/adopt/recover that run.
            observation = self._transaction("inspect_chat_request", ChatRequestObservation, owner, task_id, command, key)
            if observation.admission is not None:
                return observation.admission.state.run
            require_chat_slot(len(self._slots), limit=self.capacity)
        slot = object()
        self._slots.add(slot)  # Immediate and outside a transaction; no await.
        try:
            admission = self._transaction("admit_chat", ChatRunAdmission, owner, task_id, command, key,
                process_instance=self.process_instance, configured_timeout_seconds=self.configured_timeout_seconds)
        except BaseException:
            self._slots.discard(slot)
            raise
        if not admission.created:
            self._slots.discard(slot)
            return admission.state.run
        run = admission.state.run
        maximum = 3 * min(self.configured_timeout_seconds, 90)
        remaining = min(maximum, max(0.0, (run.deadline - utc_anchor).total_seconds()))
        local = _LocalChat(admission, slot, monotonic_anchor + remaining)
        if run.run_id in self._runs:
            self._slots.discard(slot)
            raise ChatExecutionError("WORK_EXECUTION_UNAVAILABLE", run_id=run.run_id)
        self._runs[run.run_id] = local
        coroutine = self.execute_first_chat(admission)
        local.entry_coroutine = coroutine
        try:
            supervisor = self.schedule(coroutine)
            if not isinstance(supervisor, asyncio.Task):
                raise ChatExecutionError("WORK_EXECUTION_UNAVAILABLE")
            local.supervisor = supervisor
            supervisor.add_done_callback(lambda finished: self._finish_unentered(local, finished))
        except Exception:
            coroutine.close()
            self._release(local)
            try:
                self._transaction("fail_pending_chat", ChatRunOutcome, owner, task_id, run.run_id,
                    process_instance=self.process_instance, error_code="WORK_EXECUTION_UNAVAILABLE")
            except _CONTROLLED as error:
                code = "COMMIT_OUTCOME_UNKNOWN" if error.code == "COMMIT_OUTCOME_UNKNOWN" else "WORK_EXECUTION_UNAVAILABLE"
                raise ChatExecutionError(code, run_id=run.run_id) from None
            raise ChatExecutionError("WORK_EXECUTION_UNAVAILABLE", run_id=run.run_id) from None
        return run

    async def cancel_chat(self, owner: str, task_id: UUID, run_id: UUID) -> RunDTO:
        outcome = self._transaction("cancel_chat", ChatRunOutcome, owner, task_id, run_id)
        local = self._runs.get(run_id)
        if local is not None and outcome.state.run.stage == "CANCELLED":
            local.cancelled = True
            reservation = local.reservation
            if (reservation is not None and outcome.state.active_call == reservation.token
                    and local.provider is not None and not local.provider.done()):
                local.provider.cancel()  # Commit/close already happened above.
            elif local.provider is None and reservation is None:
                # Keep the cancelled supervisor's identity until it observes
                # cancellation, while immediately releasing known-unused capacity.
                self._slots.discard(local.slot)
        return outcome.state.run

    def get_chat_run(self, owner: str, task_id: UUID, run_id: UUID) -> RunDTO:
        return self._transaction("get_chat_run", ChatRunOutcome, owner, task_id, run_id).state.run

    def _fail_pending(self, local: _LocalChat, code: str) -> None:
        run = local.admission.state.run
        try:
            self._transaction("fail_pending_chat", ChatRunOutcome, run.owner, run.task_id, run.run_id,
                process_instance=self.process_instance, error_code=code)
        except _CONTROLLED:
            # No broader cleanup authority or uncertainty-based replay exists.
            pass

    def _settle(self, local: _LocalChat, code: str) -> None:
        reservation = local.reservation
        if reservation is None or (local.provider is not None and not local.provider.done()):
            return
        try:
            self._transaction("fail_chat_call", ChatRunOutcome, local.admission.context, reservation.token, code)
        except _CONTROLLED:
            # Current denial/mismatched token retains the durable blocker.
            pass

    def _expire_if_due(self, local: _LocalChat) -> None:
        reservation = local.reservation
        if reservation is None or self._utc() < reservation.state.run.deadline:
            return
        try:
            self._transaction("expire_chat_call", ChatRunOutcome, local.admission.context, reservation.token)
        except _CONTROLLED:
            pass

    @staticmethod
    def _failure_code(error: Exception, *, preparation: bool = False) -> str:
        if isinstance(error, ChatPreparationError):
            return "WORK_AI_INVALID_RESPONSE" if not preparation else "WORK_EXECUTION_UNAVAILABLE"
        code = getattr(error, "code", None)
        if type(code) is str and code in _AI_ERRORS:
            return code
        if preparation and code == "WORK_EVIDENCE_UNAVAILABLE":
            return code
        if code == "WORK_EXECUTION_UNAVAILABLE":
            return code
        return "WORK_EXECUTION_UNAVAILABLE" if preparation else "WORK_AI_UPSTREAM_FAILED"

    async def _wait_terminal(self, local: _LocalChat) -> None:
        provider = local.provider
        if provider is None:
            return
        while not provider.done():
            try:
                await asyncio.shield(provider)
            except asyncio.CancelledError:
                if not provider.done():
                    local.cancelled = True
                    provider.cancel()
            except Exception:
                # An exception from the awaited provider is a terminal outcome.
                break

    async def _disarm(self, local: _LocalChat) -> None:
        timer = local.timer
        if timer is not None:
            if not timer.done():
                timer.cancel()
            try:
                await asyncio.shield(timer)
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

    @staticmethod
    def _discard_terminal(local: _LocalChat) -> None:
        if local.provider is not None and local.provider.done():
            try:
                local.provider.result()
            except asyncio.CancelledError:
                pass
            except Exception:
                # Consume a rejected late failure too, so asyncio cannot emit
                # an unhandled exception repr containing upstream private data.
                pass

    @staticmethod
    def _same_context(outcome: ChatRunOutcome, prepared: PreparedChatCompletion) -> bool:
        task, ctx = outcome.task, prepared.original_ctx
        return (task.owner_subject, task.owner_storage_id, task.task_id, task.institution_id,
                task.offering_id, task.input_revision) == (ctx.actor_subject, ctx.owner_storage_id,
                ctx.task_id, ctx.institution_id, ctx.offering_id, ctx.input_revision)

    def _committed_completion(self, outcome: ChatRunOutcome, prepared: PreparedChatCompletion) -> bool:
        run, token = outcome.state.run, prepared.token
        return (self._same_context(outcome, prepared) and outcome.completion == prepared.receipt
                and run.run_id == token.run_id and run.stage == "COMPLETE"
                and (run.owner, run.task_id, run.input_revision) ==
                    (prepared.original_ctx.actor_subject, prepared.original_ctx.task_id, prepared.original_ctx.input_revision)
                and run.kind == "chat" and run.skill_ref is None and run.cancelled_at is None and run.error_code is None
                and run.attempt == token.attempt and run.provider_call_count == token.call_no
                and outcome.state.active_call is None and outcome.lease.active_run_id != token.run_id)

    def _same_active_completion(self, outcome: ChatRunOutcome, prepared: PreparedChatCompletion,
                                local: _LocalChat) -> bool:
        run, lease, token = outcome.state.run, outcome.lease, prepared.token
        return (self._same_context(outcome, prepared) and outcome.completion is None
                and outcome.state.active_call == token and run.run_id == token.run_id
                and (run.owner, run.task_id, run.input_revision) ==
                    (prepared.original_ctx.actor_subject, prepared.original_ctx.task_id, prepared.original_ctx.input_revision)
                and run.stage == "CHAT_RUNNING" and run.cancelled_at is None
                and run.attempt == token.attempt and run.provider_call_count == token.call_no
                and local.reservation is not None and run.deadline == local.reservation.state.run.deadline
                and outcome.state.repair_count == local.reservation.state.repair_count
                and run.request_digest == local.admission.state.run.request_digest
                and run.idempotency_key == local.admission.state.run.idempotency_key
                and lease.active_run_id == token.run_id and lease.process_instance == token.process_instance
                and lease.revision == token.lease_revision and self._utc() < run.deadline
                and lease.expires_at is not None and self._utc() < lease.expires_at
                and self._monotonic() < local.monotonic_deadline and not local.cancelled and not local.timed_out)

    def _reconcile_completion(self, local: _LocalChat) -> bool:
        prepared = local.prepared
        if prepared is None:
            return False
        # At most one exact completion retry and at most two fresh reads. This
        # does not retry any provider, admission, charge or uncertain cleanup.
        for observation_no in range(2):
            try:
                outcome = self._transaction("get_chat_run", ChatRunOutcome, prepared.original_ctx.actor_subject,
                    prepared.original_ctx.task_id, prepared.token.run_id)
            except _CONTROLLED:
                return False
            if self._committed_completion(outcome, prepared):
                return True
            if observation_no != 0 or not self._same_active_completion(outcome, prepared, local):
                return False
            try:
                outcome = self._transaction("complete_prepared_chat_call", ChatRunOutcome, prepared)
                return self._committed_completion(outcome, prepared)
            except _CONTROLLED as error:
                if error.code != "COMMIT_OUTCOME_UNKNOWN" and not getattr(error, "transaction_unknown", False):
                    return False
        return False

    async def execute_first_chat(self, admission: ChatRunAdmission) -> None:
        if type(admission) is not ChatRunAdmission:
            raise ChatExecutionError("WORK_EXECUTION_UNAVAILABLE")
        local = self._runs.get(admission.state.run.run_id)
        if (local is None or local.admission is not admission or local.started
                or asyncio.current_task() is not local.supervisor
                or (local.slot not in self._slots and not local.cancelled)):
            raise ChatExecutionError("WORK_EXECUTION_UNAVAILABLE")
        local.started = True
        try:
            if local.cancelled:
                return
            ChatRunAdmission.__post_init__(admission)
            original = admission.state
            if (not admission.created or original.run.stage != "PENDING" or original.run.attempt != 1
                    or original.run.provider_call_count != 0 or original.repair_count != 0 or original.active_call is not None):
                raise ChatExecutionError("WORK_EXECUTION_UNAVAILABLE")
            snapshots = self.context_source.load(admission)
            if type(snapshots) is not ChatExecutionContext:
                raise ChatExecutionError("WORK_EVIDENCE_UNAVAILABLE")
            command = snapshots.command
            if (chat_request_digest(command) != original.run.request_digest
                    or command.payload.text != admission.user_message.plain_text
                    or command.payload.client_message_key != admission.user_message.client_message_key):
                raise ChatExecutionError("WORK_EXECUTION_UNAVAILABLE")
            prompt = prepare_chat_prompt(admission.context, command, snapshots.history, snapshots.evidence, task_brief=snapshots.task_brief)
            local.claim_attempted = True
            reservation = self._transaction("reserve_chat_call", ChatCallReservation, original.run.owner,
                original.run.task_id, original.run.run_id, process_instance=self.process_instance,
                configured_output_tokens=self.configured_output_tokens,
                configured_timeout_seconds=self.configured_timeout_seconds, repair=False)
            local.reservation = reservation
            if (reservation.context != admission.context or reservation.state.run.run_id != original.run.run_id
                    or reservation.state.run.deadline != original.run.deadline
                    or reservation.state.run.attempt != 1 or reservation.state.run.provider_call_count != 1
                    or reservation.state.repair_count != 0 or reservation.token.process_instance != self.process_instance):
                self._settle(local, "WORK_EXECUTION_UNAVAILABLE")
                return
            remaining = min(reservation.limits.timeout_seconds, local.monotonic_deadline - self._monotonic())
            timeout = math.floor(remaining)
            if timeout < 1:
                local.timed_out = True
                self._expire_if_due(local)
                self._settle(local, "WORK_AI_TIMEOUT")  # Known absence: transport never opened.
                return
            call_deadline = min(local.monotonic_deadline, self._monotonic() + timeout)
            coroutine = self.ai.complete(prompt.prompt, max_output_tokens=reservation.limits.max_output_tokens,
                timeout_seconds=timeout)
            try:
                local.provider = asyncio.create_task(coroutine)
            except Exception:
                if asyncio.iscoroutine(coroutine):
                    coroutine.close()
                self._settle(local, "WORK_AI_UNAVAILABLE")
                return
            timer_coroutine = self.clock.wait_until(call_deadline)
            try:
                local.timer = asyncio.create_task(timer_coroutine)
            except Exception:
                if asyncio.iscoroutine(timer_coroutine):
                    timer_coroutine.close()
                raise ChatExecutionError("WORK_EXECUTION_UNAVAILABLE") from None
            await asyncio.wait((local.provider, local.timer), return_when=asyncio.FIRST_COMPLETED)
            if local.timer.done() and self._monotonic() < call_deadline:
                raise ChatExecutionError("WORK_EXECUTION_UNAVAILABLE")
            if local.timer.done() or self._monotonic() >= call_deadline:
                local.timed_out = True
                if not local.provider.done():
                    local.provider.cancel()
                self._expire_if_due(local)
                await self._wait_terminal(local)
            await self._disarm(local)
            if local.cancelled or local.timed_out:
                self._discard_terminal(local)
                self._settle(local, "WORK_AI_TIMEOUT" if local.timed_out else "WORK_EXECUTION_UNAVAILABLE")
                return
            try:
                raw = local.provider.result()
            except asyncio.CancelledError:
                self._settle(local, "WORK_EXECUTION_UNAVAILABLE")
                return
            except Exception as error:
                self._settle(local, self._failure_code(error))
                return
            # Actual raw response is parsed once. No dict reserialization,
            # salvage, repair call, tool dispatch or fabricated assistant exists.
            result = parse_chat_result(raw, allowed_result_refs=prompt.allowed_result_refs,
                omitted_context=prompt.omitted_context)
            if self._monotonic() >= local.monotonic_deadline:
                local.timed_out = True
                self._expire_if_due(local)
                self._settle(local, "WORK_AI_TIMEOUT")
                return
            message_id = self.new_uuid()
            if type(message_id) is not UUID:
                raise ChatExecutionError("WORK_EXECUTION_UNAVAILABLE")
            message = WorkMessageDTO(message_id=message_id, owner=admission.context.actor_subject,
                task_id=admission.context.task_id, client_message_key=None, role="assistant",
                plain_text=result.plain_text, run_id=reservation.token.run_id, result_refs=result.result_refs,
                result_type=result.type, omitted_context=result.omitted_context, created_at=self._utc())
            receipt = validate_chat_completion(reservation.state.run, message, reservation.token.run_id)
            local.prepared = PreparedChatCompletion(admission.context, reservation.token, result,
                prompt.allowed_result_refs, prompt.omitted_context, message, receipt)
            try:
                outcome = self._transaction("complete_prepared_chat_call", ChatRunOutcome, local.prepared)
                if not self._committed_completion(outcome, local.prepared):
                    local.unresolved_completion = True
            except _CONTROLLED as error:
                if error.code == "COMMIT_OUTCOME_UNKNOWN" or getattr(error, "transaction_unknown", False):
                    local.unresolved_completion = not self._reconcile_completion(local)
                else:
                    self._settle(local, "WORK_EXECUTION_UNAVAILABLE")
        except asyncio.CancelledError:
            local.cancelled = True
            if local.provider is not None and not local.provider.done():
                local.provider.cancel()
                await self._wait_terminal(local)
            if local.reservation is not None:
                self._settle(local, "WORK_EXECUTION_UNAVAILABLE")
            elif not local.claim_attempted:
                self._fail_pending(local, "WORK_EXECUTION_UNAVAILABLE")
        except Exception as error:
            if local.provider is not None and not local.provider.done():
                local.provider.cancel()
                await self._wait_terminal(local)
            if local.reservation is not None:
                self._settle(local, self._failure_code(error))
            elif not local.claim_attempted:
                self._fail_pending(local, self._failure_code(error, preparation=True))
            # A claim failure/unknown is never retried, dispatched or converted
            # into a definitely uncharged pending run. Its durable blocker stays.
        finally:
            await self._disarm(local)
            self._discard_terminal(local)
            self._release(local)
