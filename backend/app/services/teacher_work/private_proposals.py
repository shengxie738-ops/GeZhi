"""Private server-owned proposal assembly. No Session/client I/O at import."""
import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import math
import time
from uuid import uuid4
from app.repositories.teacher_work import WorkRepositoryError
from app.services.teacher_work.authorization import WorkAuthorizationError
from app.services.teacher_work.runs import WorkRunError
from app.services.teacher_work.private_chat import provider_configured

request_authorization = ContextVar('private_proposal_authorization', default=None)
_runtime = None


def _now():
    return datetime.now(timezone.utc)


def capabilities(*, enabled, schema_ready, materials_ready):
    from app.schemas.teacher_work_proposals import ProposalCapabilities, ProposalLimits
    configured = provider_configured()
    available = runtime_available()
    reason = ('private_material_proposals_disabled' if not enabled else 'proposal_schema_unavailable' if not schema_ready else None)
    read = reason is None
    generate_reason = reason or ('materials_unavailable' if not materials_ready else
        'proposal_runtime_unavailable' if not available else 'provider_unconfigured' if not configured else None)
    return ProposalCapabilities(generate=generate_reason is None, read=read, cancel=read,
        provider_configured=configured, external_provider_verified=False,
        reasons={**({} if read else dict(read=reason,cancel=reason)),
                 **({} if generate_reason is None else dict(generate=generate_reason))}, limits=ProposalLimits())


def runtime_available():
    from app.core.config import settings
    from app.services.teacher_work.execution_capacity import _shared_capacity
    capacity = settings.TEACHER_WORK_MAX_ACTIVE_RUNS
    if type(capacity) is not int or capacity < 1:
        return False
    if _runtime is not None:
        if (_runtime.closed or _runtime.loop.is_closed() or _runtime.pool is not _shared_capacity
                or _runtime.pool.loop is not _runtime.loop or _runtime.pool.capacity != min(capacity,4)):
            return False
        limits = (settings.AI_LESSON_PREP_TIMEOUT_SECONDS, settings.AI_LESSON_PREP_MAX_OUTPUT_TOKENS)
        if any(type(limit) is not int or limit < 1 for limit in limits):
            return False
        if (min(limits[0],90), min(limits[1],8192)) != (
                _runtime.execution.configured_timeout_seconds, _runtime.execution.configured_output_tokens):
            return False
    if _shared_capacity is not None:
        # Capabilities are called on a synchronous request worker, so no local
        # event-loop assumption can authorize resetting occupied capacity.
        if _shared_capacity.capacity != min(capacity,4):
            if _shared_capacity.slots or not all(owner.closed for owner in _shared_capacity.owners):
                return False
        if _shared_capacity.loop.is_closed() and _shared_capacity.slots:
            return False
    return True


class PrivateProposalTransactions:
    """Finite synchronous port; every return follows owner commit/close/root exit."""
    def __init__(self, *, request_owner_factory=None, dependencies_factory=None):
        from app.services.teacher_work.bootstrap import open_teacher_work_request, build_request_dependencies
        self.request_owner_factory = request_owner_factory or open_teacher_work_request
        self.dependencies_factory = dependencies_factory or build_request_dependencies

    @contextmanager
    def _binding(self, mode, *, clock=_now, operation=None):
        authorization = request_authorization.get()
        operation = operation or ('private_proposal_read' if mode == 'read' else 'private_proposal_write')
        with self.request_owner_factory(authorization, mode=mode, operation=operation) as session:
            binding = self.dependencies_factory(session, authorization=authorization, mode=mode,
                operation=operation, clock=clock, new_uuid=uuid4)
            yield binding

    def subject(self):
        # A genuine dedicated root observes current authority/core before the
        # server derives owner; no caller-controlled owner field exists.
        with self._binding('read', operation='private_read') as binding:
            subject = binding.subject
            binding.finish_proposal_capabilities()
            return subject

    def _operation(self, name, owner, *args, **kwargs):
        mode = 'read' if name in ('inspect','get','read_proposal','list_runs') else 'write'
        with self._binding(mode) as binding:
            if owner != binding.subject:
                raise WorkAuthorizationError('NOT_FOUND',404)
            if name in ('admit','reserve') and not provider_configured():
                raise WorkRunError('WORK_AI_UNAVAILABLE',503)
            value = getattr(binding.proposals,name)(owner,*args,**kwargs)
            try:
                return binding.finish_proposal_outcome(value,mode=mode)
            except (WorkRepositoryError, WorkAuthorizationError) as error:
                if error.code == 'COMMIT_OUTCOME_UNKNOWN':
                    state = getattr(value,'state',None)
                    if state is not None:
                        error.run_id = state.run.run_id
                raise

    def inspect(self,owner,task_id,command,key):return self._operation('inspect',owner,task_id,command,key)
    def admit(self,owner,task_id,command,key,**kw):return self._operation('admit',owner,task_id,command,key,**kw)
    def reserve(self,owner,task_id,run_id,**kw):return self._operation('reserve',owner,task_id,run_id,**kw)
    def get(self,owner,task_id,run_id):return self._operation('get',owner,task_id,run_id)
    def cancel(self,owner,task_id,run_id):return self._operation('cancel',owner,task_id,run_id)
    def read_proposal(self,owner,task_id,run_id):return self._operation('read_proposal',owner,task_id,run_id)
    def list_runs(self,owner,task_id):return self._operation('list_runs',owner,task_id)
    def fail_pending(self,owner,task_id,run_id,**kw):return self._operation('fail_pending',owner,task_id,run_id,**kw)

    def _context_operation(self,name,original,*args):
        with self._binding('write') as binding:
            if original.actor_subject != binding.subject:
                raise WorkAuthorizationError('NOT_FOUND',404)
            value = getattr(binding.proposals,name)(original,*args)
            return binding.finish_proposal_outcome(value,mode='write')

    def fail(self,original,token,code):return self._context_operation('fail',original,token,code)
    def expire(self,original,token):return self._context_operation('expire',original,token)

    def complete(self, prepared, *, monotonic_deadline, monotonic_clock):
        def fenced_now():
            current = monotonic_clock()
            if (type(monotonic_deadline) not in (int,float) or not math.isfinite(monotonic_deadline)
                    or type(current) not in (int,float) or not math.isfinite(current) or current < 0):
                raise WorkRepositoryError('MATERIAL_PROPOSAL_STATE_UNAVAILABLE',503)
            if current >= monotonic_deadline:
                raise WorkRepositoryError('PROPOSAL_DEADLINE_EXPIRED',409)
            return _now()
        with self._binding('write',clock=fenced_now) as binding:
            if prepared.original_ctx.actor_subject != binding.subject:
                raise WorkAuthorizationError('NOT_FOUND',404)
            try:
                value = binding.proposals.complete(prepared)
                return binding.finish_proposal_outcome(value,mode='write')
            except (WorkRepositoryError,WorkAuthorizationError) as error:
                if error.code == 'COMMIT_OUTCOME_UNKNOWN':
                    error.run_id = prepared.token.run_id
                raise


class _Clock:
    utc_now = staticmethod(_now)
    monotonic = staticmethod(time.monotonic)
    async def wait_until(self,deadline):
        await asyncio.sleep(max(0,deadline-time.monotonic()))


class PrivateProposalRuntime:
    def __init__(self, *, transactions=None):
        from app.core.config import settings
        from app.services.teacher_lesson_prep.ai_client import LessonPrepAIClient
        from app.services.teacher_work.ai import LessonPrepWorkAI
        from app.services.teacher_work.execution_capacity import get_shared_capacity
        from app.services.teacher_work.proposal_execution import TeacherProposalExecution
        self.loop, self.closed = asyncio.get_running_loop(), False
        self.transactions = transactions or PrivateProposalTransactions()
        self.ai = LessonPrepWorkAI(LessonPrepAIClient())
        self.pool = get_shared_capacity(settings.TEACHER_WORK_MAX_ACTIVE_RUNS)
        self.pool.owners.add(self)
        self.execution = TeacherProposalExecution(transactions=self.transactions,ai=self.ai,clock=_Clock(),
            process_instance=uuid4(),configured_output_tokens=settings.AI_LESSON_PREP_MAX_OUTPUT_TOKENS,
            configured_timeout_seconds=settings.AI_LESSON_PREP_TIMEOUT_SECONDS,capacity=self.pool.capacity,pool=self.pool)

    async def close(self):
        self.closed = True
        tasks = tuple(local.supervisor for local in self.execution._runs.values() if local.supervisor is not None)
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks,return_exceptions=True)


def get_runtime(*, create=True, transactions=None):
    global _runtime
    if _runtime is not None:
        if _runtime.closed or _runtime.loop is not asyncio.get_running_loop():
            if not create:
                return None
            raise WorkRunError('PROPOSAL_RUNTIME_UNAVAILABLE',503)
        if transactions is not None and (_runtime.transactions.request_owner_factory is not transactions.request_owner_factory
                or _runtime.transactions.dependencies_factory is not transactions.dependencies_factory):
            if not create:
                return None
            raise WorkRunError('PROPOSAL_RUNTIME_UNAVAILABLE',503)
        if create and not runtime_available():
            raise WorkRunError('PROPOSAL_RUNTIME_UNAVAILABLE',503)
        return _runtime
    if not create:
        return None
    if not provider_configured():
        raise WorkRunError('WORK_AI_UNAVAILABLE',503)
    _runtime = PrivateProposalRuntime(transactions=transactions)
    return _runtime


async def close_runtime():
    if _runtime is not None:
        await _runtime.close()
