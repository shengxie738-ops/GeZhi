"""Bounded owner-bound observation windows, never durable payment deduplication.

All model calls use the shared protected adapter. State records hold ONLY safe
metadata; a short-lived task owns its invocation input and clears it on exit.
Unknown/expired operations are read failures, never invitations to resend.
"""
from __future__ import annotations
import asyncio
from contextlib import aclosing
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
import math
import time
from typing import Annotated, Literal
from uuid import UUID
from pydantic import Field, field_validator, model_validator
from app.services.byok.errors import ByokError, PUBLIC_MESSAGES
from app.services.byok.limits import CAPS
from app.services.byok.types import (SafeFrozenModel, AuthenticatedModelActor, ProbeKind, ProbeStatus,
    Version, Digest, ADAPTER_ID, validate_destination_consent)
from app.schemas.model_selection import ModelID, ConfigID
from app.schemas.user_model import SavedProbeRequest, DraftProbeRequest
from app.services.byok.endpoint_policy import normalize_endpoint
from app.services.byok import adapter

PROBE_PROMPTS = {
    'text': 'Reply exactly OK.',
    'stream': 'Reply exactly OK.',
    'json': 'Reply with exactly the JSON object {"ok":true}.',
    'tools': 'Call byok_probe exactly once with arguments {"ok":true}.',
}


class ProbeIdentity(SafeFrozenModel):
    actor_subject: Annotated[str, Field(min_length=1,max_length=255)]
    actor_epoch: Annotated[str, Field(min_length=1,max_length=128)]
    actor_role: Literal['student','teacher'] = 'student'
    source: Literal['saved','draft']
    config_id: ConfigID | None = None
    config_version: Version | None = None
    draft_revision: Version | None = None
    model_id: ModelID
    probe_kind: ProbeKind
    # A saved exact config+version is the immutable destination reference. It
    # needs no envelope/URL read on a duplicate POST. Drafts bind their digest.
    destination_digest: Digest | None = None
    adapter_id: Literal['openai_chat_completions_v1'] = ADAPTER_ID
    response_model_aliases: tuple[ModelID,...] = ()

    @model_validator(mode='after')
    def exact_source(self):
        if len(self.response_model_aliases)>CAPS.aliases_per_model:
            raise ValueError('bounded aliases required')
        if self.source=='saved':
            if self.config_id is None or self.config_version is None or self.draft_revision is not None:
                raise ValueError('exact saved reference required')
        elif (self.config_id is not None or self.config_version is not None or
            self.draft_revision is None or self.destination_digest is None):
            raise ValueError('exact draft identity required')
        return self


class ProbeOutcome(SafeFrozenModel):
    status: ProbeStatus
    code: str | None = None
    transport_reachable: bool = False
    checked_at: datetime
    duration_ms: Annotated[int, Field(ge=0,le=2**31-1)]
    retry_after_seconds: Annotated[int, Field(ge=0,le=CAPS.retry_after_seconds)] | None = None
    # Execution-only lifecycle fact; never serialized or cached in safe state.
    transport_closed: bool = Field(default=True,exclude=True,repr=False)
    inventory_revision: Annotated[int, Field(ge=0,le=2**63-1)] | None = None

    @field_validator('checked_at')
    @classmethod
    def aware(cls,value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('aware probe time required')
        return value.astimezone(timezone.utc)

    @model_validator(mode='after')
    def controlled_result(self):
        if self.code is not None and self.code not in PUBLIC_MESSAGES:
            raise ValueError('controlled code required')
        if self.status in {'usable_for_text','capability_verified'} and (self.code is not None or not self.transport_reachable):
            raise ValueError('usable probe requires inference success')
        return self


class ProbeState(SafeFrozenModel):
    operation_id: UUID
    identity: ProbeIdentity
    status: ProbeStatus = 'checking'
    code: str | None = None
    transport_reachable: bool = False
    checked_at: datetime
    duration_ms: Annotated[int, Field(ge=0,le=2**31-1)] = 0
    retry_after_seconds: Annotated[int, Field(ge=0,le=CAPS.retry_after_seconds)] | None = None
    inventory_revision: Annotated[int, Field(ge=0,le=2**63-1)] | None = None
    # Window and cost facts are deliberately explicit even for cancelled/unknown.
    observation_window_seconds: int = CAPS.probe_retention_seconds
    may_have_incurred_cost: bool = True
    resend_existing_operation: Literal[False] = False


@dataclass
class _Record:
    state: ProbeState
    finished_at: float | None = None
    cancelled: bool = False
    started: bool = False
    transport_closed: bool = True


# Only safe lifecycle facts cross final persistence/cancellation. No invocation,
# Key, factory, provider body or exception is held in this observation context.
_CURRENT_RECORD = ContextVar('byok_probe_lifecycle_record', default=None)


class ProbeRegistry:
    """Synchronous admission, one asynchronous invocation, no queue or retries.

    The event-loop owns this registry. Every mutation before/after an await is
    synchronous. Tasks are held separately from the key-free status records.
    Finished records are retained rather than evicted before the 15m window.
    """
    def __init__(self, *, clock=time.monotonic, wall_clock=lambda:datetime.now(timezone.utc)):
        self.clock,self.wall_clock=clock,wall_clock
        self._records,self._tasks,self._starts={},{},{}
        self._last_now=None

    def _now(self):
        now=self.clock()
        if type(now) not in (int,float) or not math.isfinite(now) or (self._last_now is not None and now<self._last_now):
            raise ByokError('MODEL_CAPACITY_EXCEEDED')
        self._last_now=now
        return now

    def _actor(self,actor):
        if not isinstance(actor,AuthenticatedModelActor):
            raise ByokError('AUTHENTICATED_ACTOR_REQUIRED')
        return actor.subject

    def _sweep(self,now):
        for key,record in tuple(self._records.items()):
            if record.finished_at is not None and now-record.finished_at>=CAPS.probe_retention_seconds:
                del self._records[key]
        for owner,starts in tuple(self._starts.items()):
            remaining=[stamp for stamp in starts if now-stamp<60]
            if remaining:self._starts[owner]=remaining
            else:del self._starts[owner]

    def _size(self,state):
        if len(state.model_dump_json().encode('utf-8'))>CAPS.probe_record_bytes:
            raise ByokError('MODEL_CAPACITY_EXCEEDED',retry_after_seconds=60)

    def start(self,actor,operation_id:UUID,fingerprint:ProbeIdentity,task_factory)->ProbeState:
        owner=self._actor(actor);now=self._now();self._sweep(now)
        if (not isinstance(operation_id,UUID) or not isinstance(fingerprint,ProbeIdentity) or
            fingerprint.actor_subject!=actor.subject or fingerprint.actor_role!=actor.role or not callable(task_factory)):
            raise ByokError('INVALID_INPUT')
        # Revalidate even a locally model_copy-created DTO before acceptance.
        try:fingerprint=ProbeIdentity.model_validate_json(fingerprint.model_dump_json())
        except Exception:raise ByokError('INVALID_INPUT') from None
        # Role/auth changes alter identity, never the retained account-bound ID
        # namespace. A completed operation cannot become a second paid call.
        key=(owner,operation_id)
        record=self._records.get(key)
        if record is not None:
            if record.state.identity!=fingerprint:raise ByokError('PROBE_OPERATION_CONFLICT')
            return record.state
        if any(k[0]==owner for k in self._tasks):
            raise ByokError('MODEL_CAPACITY_EXCEEDED',retry_after_seconds=1)
        if len(self._records)>=CAPS.probe_records_per_process or sum(k[0]==owner for k in self._records)>=CAPS.probe_records_per_actor:
            raise ByokError('MODEL_CAPACITY_EXCEEDED',retry_after_seconds=60)
        starts=self._starts.get(owner,[])
        if len(starts)>=CAPS.probe_starts_per_minute:
            retry=max(1,min(60,math.ceil(60-(now-starts[0]))))
            raise ByokError('PROBE_RATE_LIMITED',retry_after_seconds=retry)
        state=ProbeState(operation_id=operation_id,identity=fingerprint,checked_at=self.wall_clock())
        self._size(state)
        # Reserve space BEFORE dispatch for any safe terminal state. An initial
        # record at the byte boundary cannot later spill after code/time/revision
        # are added. This bounds both success and exception fallback metadata.
        terminal=state.model_copy(update={'status':'capability_verified',
            'code':max(PUBLIC_MESSAGES,key=len),'duration_ms':2**31-1,
            'retry_after_seconds':CAPS.retry_after_seconds,'inventory_revision':2**63-1,
            'checked_at':state.checked_at.replace(microsecond=999999)})
        self._size(terminal)
        record=_Record(state)
        # No factory runs before an accepted record and actor slot exist.
        task=asyncio.get_running_loop().create_task(self._run(key,record,task_factory))
        self._records[key]=record;self._tasks[key]=task;self._starts[owner]=[*starts,now]
        task.add_done_callback(lambda finished:self._task_done(key,record,finished))
        return state

    def _task_done(self,key,record,task):
        # A task cancelled before its first turn never opened an invocation.
        if task.cancelled() and not record.started:
            record.finished_at=self._now();self._tasks.pop(key,None)

    def _begin_invocation(self):
        record=_CURRENT_RECORD.get()
        if record is not None:record.transport_closed=False

    def observe_transport(self,result):
        """Publish actual-close knowledge BEFORE any final persistence step."""
        if not isinstance(result,ProbeOutcome):raise ByokError('OUTCOME_UNKNOWN')
        record=_CURRENT_RECORD.get()
        if record is not None:
            record.transport_closed=result.transport_closed
            record.state=record.state.model_copy(update={'transport_reachable':result.transport_reachable,
                'checked_at':result.checked_at,'duration_ms':result.duration_ms})

    async def _run(self,key,record,task_factory):
        record.started=True
        token=_CURRENT_RECORD.set(record)
        factory=task_factory;task_factory=None
        try:
            result=await factory()
            if not isinstance(result,ProbeOutcome):raise ByokError('OUTCOME_UNKNOWN')
            self.observe_transport(result)
            result=ProbeOutcome.model_validate(result.model_dump() | {'transport_closed':record.transport_closed})
            status='outcome_unknown' if not record.transport_closed else 'cancelled' if record.cancelled else result.status
            code='OUTCOME_UNKNOWN' if not record.transport_closed else 'CANCELLED' if record.cancelled else result.code
            state=record.state.model_copy(update={'status':status,'code':code,'transport_reachable':result.transport_reachable,
                'checked_at':result.checked_at,'duration_ms':result.duration_ms,'retry_after_seconds':result.retry_after_seconds,
                'inventory_revision':result.inventory_revision})
            self._size(state);record.state=state
        except asyncio.CancelledError:
            record.state=record.state.model_copy(update={
                'status':'cancelled' if record.transport_closed else 'outcome_unknown',
                'code':'CANCELLED' if record.transport_closed else 'OUTCOME_UNKNOWN'})
        except BaseException as error:
            code=error.code if record.transport_closed and isinstance(error,ByokError) else 'OUTCOME_UNKNOWN'
            record.state=record.state.model_copy(update={'status':'outcome_unknown' if code=='OUTCOME_UNKNOWN' else 'failed','code':code})
        finally:
            factory=None
            _CURRENT_RECORD.reset(token)
            if record.transport_closed:
                record.finished_at=self._now();self._tasks.pop(key,None)
            # An uncertain transport close keeps the active slot and record.

    def _record(self,actor,operation_id,actor_epoch=None):
        owner=self._actor(actor);self._sweep(self._now())
        if not isinstance(operation_id,UUID):raise ByokError('INVALID_INPUT',fields=('operation_id',))
        record=self._records.get((owner,operation_id))
        if record is None or record.state.identity.actor_role!=actor.role or (actor_epoch is not None and record.state.identity.actor_epoch!=actor_epoch):
            raise ByokError('CUSTOM_MODEL_NOT_FOUND',404)
        return (owner,operation_id),record

    def read(self,actor,operation_id,*,actor_epoch=None)->ProbeState:
        return self._record(actor,operation_id,actor_epoch)[1].state

    def cancel(self,actor,operation_id,*,actor_epoch=None)->ProbeState:
        key,record=self._record(actor,operation_id,actor_epoch)
        if record.finished_at is None and not record.cancelled:
            record.cancelled=True
            record.state=record.state.model_copy(update={'status':'cancelled','code':'CANCELLED'})
            task=self._tasks.get(key)
            if task is not None and not task.done():task.cancel()
        return record.state

    async def wait(self,actor,operation_id):
        key,record=self._record(actor,operation_id)
        task=self._tasks.get(key)
        if task is not None:
            try:await asyncio.shield(task)
            except asyncio.CancelledError:pass
        return record.state

    def states(self):
        self._sweep(self._now())
        return tuple(record.state for record in self._records.values())


PROBE_REGISTRY=ProbeRegistry()


def saved_identity(actor,epoch,config_id,command):
    if not isinstance(command,SavedProbeRequest) or isinstance(command,DraftProbeRequest):raise ByokError('INVALID_INPUT')
    return ProbeIdentity(actor_subject=actor.subject,actor_epoch=epoch,actor_role=actor.role,source='saved',config_id=config_id,
        config_version=command.expected_config_version,model_id=command.model_id,probe_kind=command.probe_kind)


def draft_identity(actor,epoch,command):
    ep=normalize_endpoint(command.base_url)
    return ProbeIdentity(actor_subject=actor.subject,actor_epoch=epoch,actor_role=actor.role,source='draft',draft_revision=command.draft_revision,
        model_id=command.model_id,probe_kind=command.probe_kind,destination_digest=ep.destination_digest,
        adapter_id=command.adapter_id,response_model_aliases=command.response_model_aliases.get(command.model_id,()))


def commit_saved_probe(pending,receipt):
    from app.repositories.user_models import PendingProbeReservation,_PROBE_RESERVATION_AUTHORITY
    from app.services.byok.reservations import commit_custom_reservation
    if not isinstance(pending,PendingProbeReservation) or pending._authority is not _PROBE_RESERVATION_AUTHORITY:
        raise ByokError('OUTCOME_UNKNOWN')
    pending.pending=commit_custom_reservation(pending.pending,receipt)
    return pending


def _request(kind,limits):
    specs=({'type':'function','function':{'name':adapter._PROBE_TOOL,'strict':True,
        'parameters':{'type':'object','properties':{'ok':{'type':'boolean','const':True}},'required':['ok'],'additionalProperties':False}}},) if kind=='tools' else ()
    return adapter.ModelRequest(messages=({'role':'user','content':PROBE_PROMPTS[kind]},),purpose='probe_'+kind,
        limits=limits,stream=kind=='stream',tool_specs=specs)


async def _execute(kind,scope,*,clock,wall_clock):
    started=clock();inv=None;status='failed';code=None;retry=None
    try:
        async with scope as inv:
            request=_request(kind,inv.limits);port=adapter.ChatCompletionsAdapter(clock=clock)
            if kind=='stream':
                result=None
                async with aclosing(port.stream(inv,request,deadline=started+CAPS.probe_seconds)) as events:
                    async for event in events:
                        if isinstance(event,adapter.TerminalEvent):result=event.result
                if result is None:raise ByokError('PROVIDER_INCOMPLETE')
            else:result=await port.complete(inv,request,deadline=started+CAPS.probe_seconds)
            if kind=='tools':
                if len(result.tool_calls)!=1 or result.tool_calls[0].name!=adapter._PROBE_TOOL or result.tool_calls[0].arguments!={'ok':True}:
                    raise ByokError('PROVIDER_INVALID_RESPONSE')
            elif result.model_state!='complete':raise ByokError('PROVIDER_INCOMPLETE')
            elif kind in {'text','stream'} and result.content!='OK':raise ByokError('PROVIDER_INVALID_RESPONSE')
            status='usable_for_text' if kind=='text' else 'capability_verified'
    except asyncio.CancelledError:status,code='cancelled','CANCELLED'
    except ByokError as error:
        code,retry=error.code,error.retry_after_seconds
        status='outcome_unknown' if code=='OUTCOME_UNKNOWN' else 'failed'
    except Exception:status,code='outcome_unknown','OUTCOME_UNKNOWN'
    ended=clock()
    duration=max(0,min(2**31-1,int((ended-started)*1000)))
    return ProbeOutcome(status=status,code=code,transport_reachable=bool(inv and inv._transport_reachable),
        transport_closed=bool(inv is None or inv._transport_closed),checked_at=wall_clock(),duration_ms=duration,retry_after_seconds=retry)


async def execute_saved_probe(reservation,keyring,*,clock=time.monotonic,wall_clock=lambda:datetime.now(timezone.utc)):
    PROBE_REGISTRY._begin_invocation()
    try:
        result=await _execute(reservation.binding.probe_kind,adapter.open_invocation(reservation.pending,keyring),clock=clock,wall_clock=wall_clock)
        PROBE_REGISTRY.observe_transport(result)
        return result
    finally:reservation.pending=None


async def execute_draft_probe(actor,command,*,clock=time.monotonic,wall_clock=lambda:datetime.now(timezone.utc)):
    PROBE_REGISTRY._begin_invocation()
    try:
        result=await _execute(command.probe_kind,adapter.open_draft_probe_invocation(actor,command),clock=clock,wall_clock=wall_clock)
        PROBE_REGISTRY.observe_transport(result)
        return result
    finally:command=None
