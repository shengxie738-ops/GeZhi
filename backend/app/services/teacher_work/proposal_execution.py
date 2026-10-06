"""Detached finite lesson_outline@1 supervisor, one charged provider invocation."""
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import math
from uuid import UUID
from app.repositories.teacher_work import WorkRepositoryError
from app.services.teacher_work.authorization import WorkAuthorizationError
from app.services.teacher_work.runs import WorkRunError
from app.services.teacher_work.execution_capacity import InstanceRunCapacity
from app.services.teacher_work.proposal_persistence import (ProposalOutcome, ProposalObservation,
    ProposalAdmission, ProposalReservation, PreparedProposal, public_run)
from app.services.teacher_work.proposals import parse_material_proposal, ProposalPreparationError

_CONTROLLED = (WorkRunError, WorkRepositoryError, WorkAuthorizationError)
_AI_ERRORS = {'WORK_AI_UNAVAILABLE', 'WORK_AI_TIMEOUT', 'WORK_AI_RATE_LIMITED',
              'WORK_AI_UPSTREAM_FAILED', 'WORK_AI_INVALID_RESPONSE'}


class ProposalExecutionError(WorkRunError):
    def __init__(self, code='MATERIAL_PROPOSAL_STATE_UNAVAILABLE', status_code=503, *, run_id=None,
                 transaction_unknown=False):
        super().__init__(code, status_code)
        self.run_id, self.transaction_unknown = run_id, transaction_unknown


@dataclass
class _LocalProposal:
    admission: ProposalAdmission
    slot: object
    monotonic_deadline: float
    supervisor: asyncio.Task | None = None
    entry_coroutine: object | None = None
    provider: asyncio.Task | None = None
    timer: asyncio.Task | None = None
    reservation: ProposalReservation | None = None
    prepared: PreparedProposal | None = None
    started: bool = False
    claim_attempted: bool = False
    cancelled: bool = False
    timed_out: bool = False
    unresolved: bool = False


class TeacherProposalExecution:
    def __init__(self, *, transactions, ai, process_instance, clock, configured_output_tokens,
                 configured_timeout_seconds, capacity=4, pool=None, schedule=None):
        if (type(process_instance) is not UUID or type(configured_output_tokens) is not int
                or configured_output_tokens < 1 or type(configured_timeout_seconds) is not int
                or configured_timeout_seconds < 1 or type(capacity) is not int or not 1 <= capacity <= 4
                or schedule is not None and not callable(schedule)):
            raise ProposalExecutionError('PROPOSAL_RUNTIME_UNAVAILABLE')
        self.pool = pool if pool is not None else InstanceRunCapacity(capacity)
        if type(self.pool) is not InstanceRunCapacity or self.pool.capacity != capacity:
            raise ProposalExecutionError('PROPOSAL_RUNTIME_UNAVAILABLE')
        self.transactions, self.ai, self.process_instance, self.clock = transactions, ai, process_instance, clock
        self.configured_output_tokens = min(configured_output_tokens, 8192)
        self.configured_timeout_seconds = min(configured_timeout_seconds, 90)
        self.capacity, self.schedule = capacity, schedule or asyncio.create_task
        self._slots, self._runs = self.pool.slots, {}

    def _utc(self):
        value = self.clock.utc_now()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ProposalExecutionError()
        return value.astimezone(timezone.utc)

    def _monotonic(self):
        value = self.clock.monotonic()
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ProposalExecutionError()
        return float(value)

    def _transaction(self, name, expected, *args, **kwargs):
        write = name not in ('inspect', 'get')
        try:
            value = getattr(self.transactions, name)(*args, **kwargs)
        except _CONTROLLED:
            raise
        except Exception:
            raise ProposalExecutionError(transaction_unknown=write) from None
        try:
            if asyncio.iscoroutine(value):
                value.close()
                raise ValueError()
            if type(value) is not expected:
                raise ValueError()
            value.__post_init__()
            return value
        except Exception:
            raise ProposalExecutionError(transaction_unknown=write) from None

    @staticmethod
    def _unknown(error):
        return error.code == 'COMMIT_OUTCOME_UNKNOWN' or getattr(error, 'transaction_unknown', False)

    def _release(self, local):
        if local.unresolved or local.provider is not None and not local.provider.done():
            return
        self._slots.discard(local.slot)
        if self._runs.get(local.admission.state.run.run_id) is local:
            del self._runs[local.admission.state.run.run_id]

    def _terminal(self, local, outcome, *, uncharged=False):
        original, run = local.admission.state.run, outcome.state.run
        return (outcome.state.input_record == local.admission.state.input_record
                and (run.run_id, run.task_id, run.owner, run.deadline, run.idempotency_key, run.request_digest) ==
                    (original.run_id, original.task_id, original.owner, original.deadline, original.idempotency_key, original.request_digest)
                and run.stage in ('FAILED', 'CANCELLED') and outcome.proposal is None
                and outcome.state.active_call is None and outcome.lease.active_run_id != run.run_id
                and (run.provider_call_count == 0 if uncharged else run.provider_call_count == 1))

    def _fail_pending(self, local, code):
        run = local.admission.state.run
        try:
            value = self._transaction('fail_pending', ProposalOutcome, run.owner, run.task_id, run.run_id,
                process_instance=self.process_instance, error_code=code)
        except _CONTROLLED:
            # One observation confirms absence/terminal facts; it never retries cleanup.
            try:
                value = self._transaction('get', ProposalOutcome, run.owner, run.task_id, run.run_id)
            except _CONTROLLED:
                local.unresolved = True
                return
        local.unresolved = not self._terminal(local, value, uncharged=True)

    def _finish_unentered(self, local, supervisor):
        if (local.supervisor is not supervisor or local.started or local.claim_attempted
                or not supervisor.done() or self._runs.get(local.admission.state.run.run_id) is not local):
            return
        try:
            supervisor.result()
        except (asyncio.CancelledError, Exception):
            pass
        try:
            local.entry_coroutine.close()
        except Exception:
            local.unresolved = True
            return
        self._fail_pending(local, 'PROPOSAL_RUNTIME_UNAVAILABLE')
        self._release(local)

    async def start_proposal(self, owner, task_id, command, key):
        utc, mono = self._utc(), self._monotonic()
        observed = self._transaction('inspect', ProposalObservation, owner, task_id, command, key)
        if observed.admission is not None:
            return public_run(observed.admission, replayed=True)
        if len(self._slots) >= self.capacity:
            observed = self._transaction('inspect', ProposalObservation, owner, task_id, command, key)
            if observed.admission is not None:
                return public_run(observed.admission, replayed=True)
        slot = self.pool.acquire()  # Check+allocate is synchronous, with no await.
        try:
            admission = self._transaction('admit', ProposalAdmission, owner, task_id, command, key,
                process_instance=self.process_instance, configured_timeout_seconds=self.configured_timeout_seconds)
        except _CONTROLLED as error:
            if not self._unknown(error):
                self._slots.discard(slot)
            raise
        except BaseException:
            # Unclassified admission may have committed; no assumption of absence.
            raise
        if not admission.created:
            self._slots.discard(slot)
            return public_run(admission, replayed=True)
        remaining = min(self.configured_timeout_seconds, max(0., (admission.state.run.deadline - utc).total_seconds()))
        local = _LocalProposal(admission, slot, mono + remaining)
        run_id = admission.state.run.run_id
        if run_id in self._runs:
            raise ProposalExecutionError(run_id=run_id)
        self._runs[run_id] = local
        coroutine = self.execute_proposal(admission)
        local.entry_coroutine = coroutine
        try:
            local.supervisor = self.schedule(coroutine)
            if not isinstance(local.supervisor, asyncio.Task):
                raise ValueError()
            local.supervisor.add_done_callback(lambda task: self._finish_unentered(local, task))
        except Exception:
            coroutine.close()
            self._fail_pending(local, 'PROPOSAL_RUNTIME_UNAVAILABLE')
            self._release(local)
            raise ProposalExecutionError('PROPOSAL_RUNTIME_UNAVAILABLE', run_id=run_id) from None
        return public_run(admission, replayed=False)

    async def cancel_proposal(self, owner, task_id, run_id):
        value = self._transaction('cancel', ProposalOutcome, owner, task_id, run_id)
        local = self._runs.get(run_id)
        if local is not None and value.state.run.stage == 'CANCELLED':
            local.cancelled = True
            if (local.reservation is not None and value.state.active_call == local.reservation.token
                    and local.provider is not None and not local.provider.done()):
                local.provider.cancel()
            elif local.provider is None and not local.claim_attempted and self._terminal(local, value, uncharged=True):
                self._slots.discard(local.slot)
        return public_run(value)

    def get_proposal_run(self, owner, task_id, run_id):
        return public_run(self._transaction('get', ProposalOutcome, owner, task_id, run_id))

    def _settle(self, local, code):
        if local.reservation is None or local.unresolved or local.provider is not None and not local.provider.done():
            return
        try:
            value = self._transaction('fail', ProposalOutcome, local.admission.context, local.reservation.token, code)
            local.unresolved = not self._terminal(local, value)
        except _CONTROLLED:
            local.unresolved = True

    async def _wait_terminal(self, local):
        while local.provider is not None and not local.provider.done():
            try:
                await asyncio.shield(local.provider)
            except asyncio.CancelledError:
                if not local.provider.done():
                    local.cancelled = True
                    local.provider.cancel()
            except Exception:
                break

    async def _disarm(self, local):
        if local.timer is not None:
            if not local.timer.done():
                local.timer.cancel()
            try:
                await asyncio.shield(local.timer)
            except (asyncio.CancelledError, Exception):
                pass

    @staticmethod
    def _discard(local):
        if local.provider is not None and local.provider.done():
            try:
                local.provider.result()
            except (asyncio.CancelledError, Exception):
                pass

    def _committed(self, local, outcome):
        prepared, original, run = local.prepared, local.admission.state.run, outcome.state.run
        return (prepared is not None and outcome.proposal == prepared.proposal
                and outcome.state.input_record == local.admission.state.input_record
                and (run.owner, run.task_id, run.run_id, run.deadline, run.request_digest, run.idempotency_key) ==
                    (original.owner, original.task_id, original.run_id, original.deadline, original.request_digest, original.idempotency_key)
                and run.stage == 'COMPLETE' and run.attempt == 1 and run.provider_call_count == 1
                and run.cancelled_at is None and run.error_code is None and outcome.state.active_call is None
                and outcome.lease.active_run_id != prepared.token.run_id)

    @staticmethod
    def _failure_code(error):
        if isinstance(error, ProposalPreparationError):
            return error.code
        code = getattr(error, 'code', None)
        if code in _AI_ERRORS or code in {'PROPOSAL_DRAFT_TOO_LARGE', 'PROPOSAL_DEADLINE_EXPIRED',
                'STALE_INPUT_REVISION', 'SOURCE_CHANGED', 'SOURCE_MESSAGE_INELIGIBLE', 'CURRENT_AUTHORITY_DENIED',
                'CURRENT_TEACHER_REQUIRED', 'INVALID_CURRENT_IDENTITY', 'PROPOSAL_RUNTIME_UNAVAILABLE'}:
            return code
        return 'MATERIAL_PROPOSAL_STATE_UNAVAILABLE'

    async def execute_proposal(self, admission):
        local = self._runs.get(admission.state.run.run_id) if type(admission) is ProposalAdmission else None
        if (local is None or local.admission is not admission or local.started
                or asyncio.current_task() is not local.supervisor
                or local.slot not in self._slots and not local.cancelled):
            raise ProposalExecutionError()
        local.started = True
        try:
            if local.cancelled:
                return
            admission.__post_init__()
            original = admission.state
            if (not admission.created or original.run.stage != 'PENDING' or original.run.provider_call_count != 0
                    or original.active_call is not None or original.repair_count != 0):
                raise ProposalExecutionError()
            local.claim_attempted = True
            try:
                reservation = self._transaction('reserve', ProposalReservation, original.run.owner, original.run.task_id,
                    original.run.run_id, process_instance=self.process_instance,
                    configured_output_tokens=self.configured_output_tokens,
                    configured_timeout_seconds=self.configured_timeout_seconds)
            except _CONTROLLED:
                local.unresolved = True
                raise
            local.reservation = reservation
            if (reservation.context != admission.context or reservation.state.input_record != original.input_record
                    or reservation.state.run.run_id != original.run.run_id or reservation.state.run.deadline != original.run.deadline
                    or reservation.token.process_instance != self.process_instance or reservation.limits.max_output_tokens > self.configured_output_tokens
                    or reservation.limits.timeout_seconds > self.configured_timeout_seconds):
                raise ProposalExecutionError()
            timeout = math.floor(min(reservation.limits.timeout_seconds, local.monotonic_deadline - self._monotonic()))
            if timeout < 1 or self._utc() >= original.run.deadline:
                local.timed_out = True
                self._settle(local, 'PROPOSAL_DEADLINE_EXPIRED')
                return
            coroutine = self.ai.complete_proposal(original.frozen.context_json,
                max_output_tokens=reservation.limits.max_output_tokens, timeout_seconds=timeout)
            try:
                local.provider = asyncio.create_task(coroutine)
            except Exception:
                if asyncio.iscoroutine(coroutine):
                    coroutine.close()
                raise ProposalExecutionError('WORK_AI_UNAVAILABLE') from None
            timer = self.clock.wait_until(local.monotonic_deadline)
            try:
                local.timer = asyncio.create_task(timer)
            except Exception:
                if asyncio.iscoroutine(timer):
                    timer.close()
                raise ProposalExecutionError() from None
            await asyncio.wait((local.provider, local.timer), return_when=asyncio.FIRST_COMPLETED)
            if local.timer.done() and self._monotonic() < local.monotonic_deadline:
                raise ProposalExecutionError()
            if local.timer.done() or self._monotonic() >= local.monotonic_deadline or self._utc() >= original.run.deadline:
                local.timed_out = True
                if not local.provider.done():
                    local.provider.cancel()
                await self._wait_terminal(local)
            await self._disarm(local)
            if local.cancelled or local.timed_out:
                self._settle(local, 'WORK_AI_TIMEOUT' if local.timed_out else 'PROPOSAL_RUNTIME_UNAVAILABLE')
                return
            try:
                raw = local.provider.result()
            except asyncio.CancelledError:
                self._settle(local, 'PROPOSAL_RUNTIME_UNAVAILABLE')
                return
            proposal = parse_material_proposal(raw, frozen=original.frozen, created_at=self._utc())
            if self._monotonic() >= local.monotonic_deadline or self._utc() >= original.run.deadline:
                self._settle(local, 'PROPOSAL_DEADLINE_EXPIRED')
                return
            local.prepared = PreparedProposal(admission.context, reservation.token, original.frozen, proposal)
            try:
                value = self._transaction('complete', ProposalOutcome, local.prepared,
                    monotonic_deadline=local.monotonic_deadline, monotonic_clock=self._monotonic)
                # The actual manual-size preparation may return a committed
                # FAILED outcome rather than a candidate. Confirm its exact
                # terminal token/lease facts; unknown reconciliation still
                # accepts only the exact prepared COMPLETE result below.
                local.unresolved = not (self._committed(local, value) or self._terminal(local, value))
            except _CONTROLLED as error:
                if self._unknown(error):
                    local.unresolved = True
                    try:
                        value = self._transaction('get', ProposalOutcome, original.run.owner, original.run.task_id, original.run.run_id)
                        local.unresolved = not self._committed(local, value)
                    except _CONTROLLED:
                        pass
                else:
                    self._settle(local, self._failure_code(error))
        except asyncio.CancelledError:
            local.cancelled = True
            if local.provider is not None and not local.provider.done():
                local.provider.cancel()
                await self._wait_terminal(local)
            if local.reservation is not None:
                self._settle(local, 'PROPOSAL_RUNTIME_UNAVAILABLE')
            elif not local.claim_attempted:
                self._fail_pending(local, 'PROPOSAL_RUNTIME_UNAVAILABLE')
        except Exception as error:
            if local.provider is not None and not local.provider.done():
                local.provider.cancel()
                await self._wait_terminal(local)
            if local.reservation is not None:
                self._settle(local, self._failure_code(error))
            elif not local.claim_attempted:
                self._fail_pending(local, self._failure_code(error))
        finally:
            await self._disarm(local)
            self._discard(local)
            self._release(local)
