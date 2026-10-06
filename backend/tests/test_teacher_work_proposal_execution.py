"""Finite detached proposal execution; synchronous finalized fake port, no DB."""
import asyncio
from dataclasses import replace
from datetime import timedelta
import json
from uuid import UUID
import pytest
from tests.test_teacher_work_proposal_persistence import state
from tests.test_teacher_work_proposals import task, command, NOW
from tests.test_teacher_work_private_materials import lesson, slides
from app.services.teacher_work.proposal_persistence import (ProposalOutcome,ProposalAdmission,ProposalObservation,
    ProposalReservation,task_context)
from app.services.teacher_work.run_persistence import ProviderCallToken,StoredRunState
from app.services.teacher_work.runs import OwnerLeaseFacts,CallLimits,WorkRunError

class Clock:
    seconds=0
    def utc_now(self):return NOW+timedelta(seconds=self.seconds)
    def monotonic(self):return float(self.seconds)
    async def wait_until(self,deadline):
        while self.seconds<deadline:await asyncio.sleep(.001)

class Port:
    def __init__(self):
        self.t=task();self.s=state();self.process=UUID(int=10);self.writes=[];self.unknown=None;self.gets=0
        self.lease=OwnerLeaseFacts(owner='owner',owner_storage_id=UUID(int=1),active_run_id=self.s.run.run_id,revision=2,process_instance=self.process,expires_at=self.s.run.deadline)
        self.proposal=None;self.replay=False
    def outcome(self):return ProposalOutcome(self.t,self.s,self.lease,self.proposal)
    def inspect(self,*args):
        if args[-2]!=command():raise WorkRunError('IDEMPOTENCY_CONFLICT',409)
        return ProposalObservation(self.t,task_context(self.t),self.admission(False) if self.replay else None)
    def admission(self,created):return ProposalAdmission(self.t,self.s,self.lease,self.proposal,task_context(self.t),created)
    def admit(self,*args,**kw):
        self.writes.append('admit');self.replay=True
        if self.unknown=='admit':raise WorkRunError('COMMIT_OUTCOME_UNKNOWN',503)
        return self.admission(True)
    def reserve(self,*args,**kw):
        self.writes.append('reserve')
        if self.unknown=='reserve':raise WorkRunError('COMMIT_OUTCOME_UNKNOWN',503)
        token=ProviderCallToken(self.s.run.run_id,1,1,2,self.process)
        self.s=replace(self.s,state=StoredRunState(self.s.run.model_copy(update=dict(stage='OUTLINE_RUNNING',provider_call_count=1)),0,token))
        return ProposalReservation(self.t,self.s,self.lease,None,task_context(self.t),token,CallLimits(8192,90))
    def complete(self,p,**kw):
        self.writes.append('complete');p.__post_init__()
        if self.unknown=='complete_before':raise WorkRunError('COMMIT_OUTCOME_UNKNOWN',503)
        self.proposal=p.proposal;self.terminal('COMPLETE')
        if self.unknown=='complete_after':raise WorkRunError('COMMIT_OUTCOME_UNKNOWN',503)
        return self.outcome()
    def terminal(self,stage,error=None,cancelled=None):
        self.s=replace(self.s,state=StoredRunState(self.s.run.model_copy(update=dict(stage=stage,error_code=error,cancelled_at=cancelled)),0,None))
        self.lease=replace(self.lease,active_run_id=None,expires_at=None,process_instance=None)
    def fail(self,ctx,token,code):
        self.writes.append('fail')
        if self.s.run.stage=='CANCELLED':self.terminal('CANCELLED',cancelled=NOW)
        else:self.terminal('FAILED',code)
        return self.outcome()
    def expire(self,*a):self.writes.append('expire');return self.outcome()
    def fail_pending(self,*a,**kw):self.writes.append('fail_pending');self.terminal('FAILED',kw['error_code']);return self.outcome()
    def get(self,*a):self.gets+=1;return self.outcome()
    def cancel(self,*a):
        if self.s.run.stage not in ('COMPLETE','FAILED','CANCELLED'):
            active=self.s.active_call
            self.s=replace(self.s,state=StoredRunState(self.s.run.model_copy(update=dict(stage='CANCELLED',cancelled_at=NOW)),0,active))
            if active is None:self.lease=replace(self.lease,active_run_id=None,expires_at=None,process_instance=None)
        return self.outcome()

class AI:
    def __init__(self):self.calls=[];self.entered=asyncio.Event();self.release=asyncio.Event();self.block=False;self.stubborn=False;self.raw=json.dumps(dict(lesson=lesson(),slides=slides()))
    async def complete_proposal(self,prompt,**limits):
        self.calls.append((prompt,limits));self.entered.set()
        if self.block:
            try:await self.release.wait()
            except asyncio.CancelledError:
                if not self.stubborn:raise
                await self.release.wait()
        return self.raw

def build(*,pool=None,schedule=None):
    from app.services.teacher_work.proposal_execution import TeacherProposalExecution
    p=Port();ai=AI();c=Clock()
    e=TeacherProposalExecution(transactions=p,ai=ai,process_instance=p.process,clock=c,
        configured_output_tokens=9000,configured_timeout_seconds=100,capacity=1,pool=pool,schedule=schedule)
    return e,p,ai,c
async def start(e):return await e.start_proposal('owner',task().task_id,command(),'key')
async def done(e):
    tasks=[v.supervisor for v in e._runs.values() if v.supervisor]
    if tasks:await asyncio.gather(*tasks)

@pytest.mark.parametrize('mode',['normal','replay','changed','invalid','unknown_admit','unknown_reserve','unknown_complete_before','unknown_complete_after'])
def test_finite_dispatch_exact_budget_and_uncertainty(mode):
    async def run():
        e,p,ai,c=build()
        if mode.startswith('unknown_'):p.unknown=mode[len('unknown_'):]
        if mode=='replay':p.replay=True
        if mode=='invalid':ai.raw='{"lesson":{},"lesson":{},"slides":[]}'
        if mode=='unknown_admit':
            with pytest.raises(WorkRunError):await start(e)
        else:
            receipt=await start(e);assert receipt.receipt.replayed==(mode=='replay');await done(e)
        if mode=='changed':
            with pytest.raises(WorkRunError) as error:await e.start_proposal('owner',task().task_id,command().model_copy(update={'expected_revision':3}),'key')
            assert error.value.code=='IDEMPOTENCY_CONFLICT'
        calls=0 if mode in ('replay','unknown_admit','unknown_reserve') else 1
        assert len(ai.calls)==calls
        if calls:assert ai.calls[0][0]==p.s.frozen.context_json and ai.calls[0][1]==dict(max_output_tokens=8192,timeout_seconds=90)
        if mode.startswith('unknown_complete'):
            assert p.writes.count('complete')==1 and p.gets==1
            assert bool(e._slots)==(mode=='unknown_complete_before')
        if mode in ('unknown_admit','unknown_reserve'):assert 'fail' not in p.writes and 'fail_pending' not in p.writes
        if mode=='invalid':assert p.s.run.stage=='FAILED' and p.s.run.error_code=='INVALID_MATERIAL_PROPOSAL_RESPONSE'
        if mode in ('normal','changed','unknown_complete_after'):assert p.s.run.stage=='COMPLETE' and not e._slots
        if mode=='normal':
            replay=await start(e);assert replay.receipt.replayed and replay.stage=='COMPLETE';assert len(ai.calls)==1
    asyncio.run(run())

@pytest.mark.parametrize('trigger',['cancel','timeout','close'])
@pytest.mark.parametrize('stubborn',[False,True])
def test_actual_transport_settlement_and_late_result_fence(trigger,stubborn):
    async def run():
        e,p,ai,c=build();ai.block=True;ai.stubborn=stubborn
        await start(e);await ai.entered.wait()
        if trigger=='cancel':await e.cancel_proposal('owner',task().task_id,p.s.run.run_id)
        elif trigger=='timeout':c.seconds=91
        else:
            for local in e._runs.values():local.supervisor.cancel()
        await asyncio.sleep(.01)
        if stubborn:assert e._slots and p.s.active_call is not None
        ai.release.set();await done(e)
        assert len(ai.calls)==1 and p.proposal is None and p.s.active_call is None and not e._slots
        assert p.s.run.stage==('CANCELLED' if trigger=='cancel' else 'FAILED')
    asyncio.run(run())

def test_preentry_cancel_and_scheduling_failure_do_not_dispatch():
    async def run():
        e,p,ai,c=build();await start(e);await e.cancel_proposal('owner',task().task_id,p.s.run.run_id);await done(e)
        assert ai.calls==[] and not e._slots
        def bad(coro):raise RuntimeError('private')
        e,p,ai,c=build(schedule=bad)
        with pytest.raises(WorkRunError):await start(e)
        assert p.s.run.stage=='FAILED' and ai.calls==[] and not e._slots
        e,p,ai,c=build();await start(e);next(iter(e._runs.values())).supervisor.cancel();await asyncio.sleep(.01)
        assert p.s.run.stage=='FAILED' and ai.calls==[] and not e._slots
    asyncio.run(run())

def test_shared_capacity_atomic_across_chat_and_proposal():
    from app.services.teacher_work.execution_capacity import InstanceRunCapacity
    from app.services.teacher_work.chat_execution import TeacherChatExecution
    pool=InstanceRunCapacity(1)
    chat=TeacherChatExecution(transactions=None,ai=None,context_source=None,process_instance=UUID(int=10),clock=Clock(),new_uuid=lambda:UUID(int=11),configured_output_tokens=1,configured_timeout_seconds=1,capacity=1,pool=pool)
    async def run():
        e,p,ai,c=build(pool=pool);ai.block=True
        await start(e);await ai.entered.wait();assert chat._slots is e._slots and len(pool.slots)==1
        other,_,_,_=build(pool=pool)
        with pytest.raises(WorkRunError) as error:await start(other)
        assert error.value.code=='INSTANCE_BUSY'
        ai.release.set();await done(e);assert not pool.slots
    asyncio.run(run())


def test_shared_pool_closed_loop_replacement_never_discards_uncertainty(monkeypatch):
    from app.services.teacher_work import execution_capacity as module
    from types import SimpleNamespace
    monkeypatch.setattr(module,'_shared_capacity',None)
    async def first():
        pool=module.get_shared_capacity(2);pool.owners.add(SimpleOwner(False))
        with pytest.raises(WorkRunError):module.get_shared_capacity(1)
        pool.owners.clear();pool.owners.add(SimpleOwner(True))
        assert module.get_shared_capacity(1).capacity==1
        return module._shared_capacity
    class SimpleOwner:
        def __init__(self,closed):self.closed=closed
    old=asyncio.run(first())
    async def reopened():
        new=module.get_shared_capacity(1);assert new is not old
        new.acquire()
        return new
    occupied=asyncio.run(reopened())
    async def denied():
        with pytest.raises(WorkRunError):module.get_shared_capacity(1)
        assert module._shared_capacity is occupied and len(occupied.slots)==1
    asyncio.run(denied())


def test_positive_completion_passes_absolute_monotonic_fence_to_port():
    async def run():
        e,p,ai,c=build();base=p.complete;captured={}
        def complete(prepared,**kw):
            captured.update(kw)
            assert kw['monotonic_deadline']==90 and kw['monotonic_clock']()==0
            return base(prepared,**kw)
        p.complete=complete
        await start(e);await done(e)
        assert p.s.run.stage=='COMPLETE' and captured['monotonic_deadline']==90
    asyncio.run(run())


def test_cancel_fallback_does_not_require_available_local_runtime(monkeypatch):
    from app.services.teacher_work import private_proposals
    from types import SimpleNamespace
    monkeypatch.setattr(private_proposals,'_runtime',SimpleNamespace(closed=True))
    assert private_proposals.get_runtime(create=False) is None


def test_known_manual_size_failure_return_is_terminal_and_releases_capacity():
    async def run():
        e,p,ai,c=build()
        def complete(prepared,**kw):
            p.terminal('FAILED','PROPOSAL_DRAFT_TOO_LARGE')
            return p.outcome()
        p.complete=complete
        await start(e);await done(e)
        assert p.s.run.error_code=='PROPOSAL_DRAFT_TOO_LARGE' and not e._slots and ai.calls
    asyncio.run(run())


@pytest.mark.parametrize('change',['capacity','zero','timeout','tokens','pool'])
def test_existing_runtime_config_and_pool_mismatch_refuse_new_dispatch(monkeypatch,change):
    import sys
    from types import SimpleNamespace
    from app.services.teacher_work import private_proposals,private_chat,execution_capacity
    from app.services.teacher_work.execution_capacity import InstanceRunCapacity
    settings=SimpleNamespace(TEACHER_WORK_MAX_ACTIVE_RUNS=4,AI_LESSON_PREP_TIMEOUT_SECONDS=5,AI_LESSON_PREP_MAX_OUTPUT_TOKENS=8192)
    monkeypatch.setitem(sys.modules,'app.core.config',SimpleNamespace(settings=settings))
    async def run():
        pool=InstanceRunCapacity(4,loop=asyncio.get_running_loop())
        class Runtime:
            closed=False
        runtime=Runtime();runtime.loop=asyncio.get_running_loop();runtime.pool=pool
        runtime.execution=SimpleNamespace(configured_timeout_seconds=5,configured_output_tokens=8192)
        pool.owners.add(runtime)
        monkeypatch.setattr(execution_capacity,'_shared_capacity',pool)
        monkeypatch.setattr(private_proposals,'_runtime',runtime);monkeypatch.setattr(private_chat,'_runtime',runtime)
        if change in ('capacity','zero'):settings.TEACHER_WORK_MAX_ACTIVE_RUNS=1 if change=='capacity' else 0
        if change=='timeout':settings.AI_LESSON_PREP_TIMEOUT_SECONDS=4
        if change=='tokens':settings.AI_LESSON_PREP_MAX_OUTPUT_TOKENS=8191
        if change=='pool':monkeypatch.setattr(execution_capacity,'_shared_capacity',InstanceRunCapacity(4,loop=runtime.loop))
        with pytest.raises(WorkRunError) as error:private_proposals.get_runtime()
        assert error.value.code=='PROPOSAL_RUNTIME_UNAVAILABLE'
        assert private_proposals.get_runtime(create=False) is runtime
        assert private_proposals.runtime_available() is False
        if change in ('capacity','zero','pool'):
            with pytest.raises(WorkRunError) as error:private_chat.get_runtime()
            assert error.value.code=='CHAT_RUNTIME_UNAVAILABLE'
        else:assert private_chat.get_runtime() is runtime
    asyncio.run(run())


def test_new_chat_runtime_shared_capacity_denial_keeps_chat_error_namespace(monkeypatch):
    import sys
    from types import SimpleNamespace
    from app.services.teacher_work import private_chat,execution_capacity
    settings=SimpleNamespace(TEACHER_WORK_MAX_ACTIVE_RUNS=4)
    monkeypatch.setitem(sys.modules,'app.core.config',SimpleNamespace(settings=settings))
    monkeypatch.setitem(sys.modules,'app.services.teacher_lesson_prep.ai_client',SimpleNamespace(LessonPrepAIClient=lambda:object()))
    def unavailable(*args):raise WorkRunError('PROPOSAL_RUNTIME_UNAVAILABLE',503)
    monkeypatch.setattr(execution_capacity,'get_shared_capacity',unavailable)
    async def run():
        with pytest.raises(WorkRunError) as error:private_chat.PrivateChatRuntime()
        assert error.value.code=='CHAT_RUNTIME_UNAVAILABLE'
    asyncio.run(run())
