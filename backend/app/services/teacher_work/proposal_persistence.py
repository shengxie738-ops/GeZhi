"""Strict detached proposal candidates. These values never certify a commit."""
from dataclasses import dataclass, field
from uuid import UUID
from pydantic import ValidationError
from app.schemas.teacher_work import FrozenDTO, WorkTaskDTO, Digest, Revision
from app.schemas.teacher_work_proposals import (FrozenProposalInput, MaterialProposal, ProposalCommand,
    ProposalRead, ProposalRun, ProposalRunList, ProposalReceipt, ProposalUUID)
from app.services.teacher_work.run_persistence import StoredRunState, ProviderCallToken
from app.services.teacher_work.runs import WorkRunError, OwnerLeaseFacts, CallLimits
from app.services.teacher_work.types import WorkContext, canonical_json_bytes, canonical_digest


def invalid():
    return WorkRunError('MATERIAL_PROPOSAL_STATE_UNAVAILABLE',503)


def context_data(ctx):
    if type(ctx) is not WorkContext:raise invalid()
    ctx.__post_init__()
    if any(type(getattr(ctx,name)) is not UUID for name in ('owner_storage_id','task_id')):raise invalid()
    return dict(actor_subject=ctx.actor_subject,owner_storage_id=str(ctx.owner_storage_id),task_id=str(ctx.task_id),
        institution_id=ctx.institution_id,offering_id=str(ctx.offering_id) if ctx.offering_id else None,
        input_revision=ctx.input_revision,working_revision=ctx.working_revision)


def decode_context(data):
    if type(data) is not dict or set(data)!=set(context_data(WorkContext('x',UUID(int=1),UUID(int=2),None,None,1,1))):raise invalid()
    try:
        parsed=dict(data)
        for name in ('owner_storage_id','task_id','offering_id'):
            value=parsed[name]
            if value is None and name=='offering_id':continue
            if type(value) is not str or str(UUID(value))!=value:raise ValueError()
            parsed[name]=UUID(value)
        ctx=WorkContext(**parsed)
        context_data(ctx)
        return ctx
    except (ValueError,TypeError):raise invalid() from None


def same_identity(left,right):
    return all(getattr(left,name)==getattr(right,name) for name in
        ('actor_subject','owner_storage_id','task_id','institution_id','offering_id'))


@dataclass(frozen=True)
class ProposalInputRecord:
    original_ctx:WorkContext
    command:ProposalCommand
    frozen:FrozenProposalInput
    _snapshot:bytes=field(init=False,repr=False,compare=False)

    def __post_init__(self):
        try:
            context_data(self.original_ctx)
            if type(self.command) is not ProposalCommand or type(self.frozen) is not FrozenProposalInput:raise ValueError()
            ProposalCommand.model_validate(self.command.model_dump())
            FrozenProposalInput.model_validate(self.frozen.model_dump())
            ctx,c,f=self.original_ctx,self.command,self.frozen
            if (ctx.institution_id is not None or ctx.offering_id is not None
                    or (ctx.actor_subject,ctx.task_id,ctx.input_revision,ctx.working_revision)!=
                       (f.owner,f.task_id,c.input_revision,c.expected_revision)
                    or (c.input_revision,c.source_message_id)!=(f.input_revision,f.source_message_id)):raise ValueError()
            snapshot=canonical_json_bytes(self.payload())
            if len(snapshot)>262144:raise ValueError()
            if hasattr(self,'_snapshot'):
                if snapshot!=self._snapshot:raise ValueError()
            else:object.__setattr__(self,'_snapshot',snapshot)
        except (ValueError,TypeError,AttributeError,ValidationError):raise invalid() from None

    def payload(self):
        return dict(context=context_data(self.original_ctx),command=self.command.model_dump(mode='json'),frozen=self.frozen.model_dump(mode='json'))

    @classmethod
    def decode(cls,payload):
        try:
            if type(payload) is not dict or set(payload)!={'context','command','frozen'}:raise ValueError()
            result=cls(decode_context(payload['context']),ProposalCommand.model_validate_json(canonical_json_bytes(payload['command'])),
                FrozenProposalInput.model_validate_json(canonical_json_bytes(payload['frozen'])))
            if result.payload()!=payload:raise ValueError()
            return result
        except (ValueError,TypeError,AttributeError,ValidationError):raise invalid() from None


@dataclass(frozen=True)
class ProposalState:
    state:StoredRunState
    input_record:ProposalInputRecord

    @property
    def run(self):return self.state.run
    @property
    def active_call(self):return self.state.active_call
    @property
    def repair_count(self):return self.state.repair_count
    @property
    def frozen(self):return self.input_record.frozen

    def __post_init__(self):
        if type(self.state) is not StoredRunState or type(self.input_record) is not ProposalInputRecord:raise invalid()
        self.state.__post_init__();self.input_record.__post_init__()
        r,f,c=self.run,self.frozen,self.input_record.command
        if (r.kind!='outline' or r.skill_ref!='lesson_outline@1' or r.attempt!=1 or r.provider_call_count not in (0,1)
                or self.repair_count!=0 or r.outline_revision is not None or r.result_version_id is not None
                or (r.owner,r.task_id,r.input_revision)!=(f.owner,f.task_id,f.input_revision)
                or r.request_digest!=canonical_digest(c.model_dump(mode='json'))):raise invalid()
        active=self.active_call
        if active is not None and (active.attempt!=1 or active.call_no!=1):raise invalid()
        if r.stage=='PENDING':
            if r.provider_call_count!=0 or active is not None or r.error_code is not None or r.cancelled_at is not None:raise invalid()
        elif r.stage=='OUTLINE_RUNNING':
            if r.provider_call_count!=1 or active is None or r.error_code is not None or r.cancelled_at is not None:raise invalid()
        elif r.stage=='COMPLETE':
            if r.provider_call_count!=1 or active is not None or r.error_code is not None or r.cancelled_at is not None:raise invalid()
        elif r.stage=='FAILED':
            if r.error_code is None or r.cancelled_at is not None:raise invalid()
        elif r.stage=='CANCELLED':
            if r.cancelled_at is None:raise invalid()
        else:raise invalid()


def validate_result(state,proposal):
    if proposal is None:
        if state.run.stage=='COMPLETE':raise invalid()
        return
    if type(proposal) is not MaterialProposal or state.run.stage!='COMPLETE':raise invalid()
    MaterialProposal.model_validate(proposal.model_dump())
    f=state.frozen
    if any(getattr(proposal,name)!=getattr(f,name) for name in
        ('input_revision','source_message_id','input_digest','source_digest','omitted_context')):raise invalid()
    if proposal.lesson.duration_minutes!=f.duration_minutes or len(proposal.slides)!=f.target_slide_count:raise invalid()


def validate_candidate(task,state,lease):
    if type(task) is not WorkTaskDTO or type(state) is not ProposalState or type(lease) is not OwnerLeaseFacts:raise invalid()
    WorkTaskDTO.model_validate(task.model_dump());state.__post_init__();lease.__post_init__()
    if (task.owner_subject,task.task_id,task.owner_storage_id)!=(state.run.owner,state.run.task_id,lease.owner_storage_id) or lease.owner!=task.owner_subject:raise invalid()
    ctx=WorkContext(task.owner_subject,task.owner_storage_id,task.task_id,task.institution_id,task.offering_id,task.input_revision,task.working_revision)
    if not same_identity(ctx,state.input_record.original_ctx):raise invalid()
    unsettled=state.run.stage in ('PENDING','OUTLINE_RUNNING') or state.active_call is not None
    if unsettled:
        if (lease.active_run_id,lease.expires_at)!=(state.run.run_id,state.run.deadline):raise invalid()
        if state.active_call is not None and (lease.revision,lease.process_instance)!=(state.active_call.lease_revision,state.active_call.process_instance):raise invalid()
    elif lease.active_run_id==state.run.run_id:raise invalid()


@dataclass(frozen=True)
class ProposalOutcome:
    task:WorkTaskDTO
    state:ProposalState
    lease:OwnerLeaseFacts
    proposal:MaterialProposal|None
    def __post_init__(self):
        validate_candidate(self.task,self.state,self.lease);validate_result(self.state,self.proposal)


@dataclass(frozen=True)
class ProposalAdmission(ProposalOutcome):
    context:WorkContext
    created:bool
    def __post_init__(self):
        super().__post_init__()
        if type(self.created) is not bool or context_data(self.context)!=context_data(task_context(self.task)):raise invalid()
        if self.created and self.context!=self.state.input_record.original_ctx:raise invalid()


def task_context(task):
    return WorkContext(task.owner_subject,task.owner_storage_id,task.task_id,task.institution_id,task.offering_id,task.input_revision,task.working_revision)


@dataclass(frozen=True)
class ProposalObservation:
    task:WorkTaskDTO
    context:WorkContext
    admission:ProposalAdmission|None
    def __post_init__(self):
        if type(self.task) is not WorkTaskDTO or context_data(self.context)!=context_data(task_context(self.task)):raise invalid()
        if self.admission is not None:
            if type(self.admission) is not ProposalAdmission or self.admission.created or self.admission.task!=self.task:raise invalid()
            self.admission.__post_init__()


@dataclass(frozen=True)
class ProposalReservation(ProposalOutcome):
    context:WorkContext
    token:ProviderCallToken
    limits:CallLimits
    def __post_init__(self):
        super().__post_init__()
        if (type(self.token) is not ProviderCallToken or type(self.limits) is not CallLimits
                or context_data(self.context)!=context_data(task_context(self.task))
                or self.state.active_call!=self.token or self.state.run.stage!='OUTLINE_RUNNING'
                or self.context!=self.state.input_record.original_ctx):raise invalid()
        self.token.__post_init__();self.limits.__post_init__()


@dataclass(frozen=True)
class PreparedProposal:
    original_ctx:WorkContext
    token:ProviderCallToken
    frozen:FrozenProposalInput
    proposal:MaterialProposal
    _snapshot:bytes=field(init=False,repr=False,compare=False)
    def __post_init__(self):
        try:
            if type(self.token) is not ProviderCallToken or type(self.frozen) is not FrozenProposalInput or type(self.proposal) is not MaterialProposal:raise ValueError()
            self.token.__post_init__()
            FrozenProposalInput.model_validate(self.frozen.model_dump());MaterialProposal.model_validate(self.proposal.model_dump())
            if (self.token.attempt,self.token.call_no)!=(1,1):raise ValueError()
            if (self.original_ctx.actor_subject,self.original_ctx.task_id,self.original_ctx.input_revision)!=(self.frozen.owner,self.frozen.task_id,self.frozen.input_revision):raise ValueError()
            if any(getattr(self.frozen,k)!=getattr(self.proposal,k) for k in ('input_revision','source_message_id','input_digest','source_digest','omitted_context')):raise ValueError()
            if self.proposal.lesson.duration_minutes!=self.frozen.duration_minutes or len(self.proposal.slides)!=self.frozen.target_slide_count:raise ValueError()
            snapshot=canonical_json_bytes(dict(context=context_data(self.original_ctx),token={k:str(v) if type(v) is UUID else v for k,v in vars(self.token).items()},frozen=self.frozen.model_dump(mode='json'),proposal=self.proposal.model_dump(mode='json')))
            if hasattr(self,'_snapshot'):
                if self._snapshot!=snapshot:raise ValueError()
            else:object.__setattr__(self,'_snapshot',snapshot)
        except (TypeError,ValueError,AttributeError):raise invalid() from None


@dataclass(frozen=True)
class ProposalReadOutcome:
    task:WorkTaskDTO
    outcome:ProposalOutcome
    read:ProposalRead
    def __post_init__(self):
        if type(self.outcome) is not ProposalOutcome or type(self.read) is not ProposalRead or self.task!=self.outcome.task:raise invalid()
        self.outcome.__post_init__();ProposalRead.model_validate(self.read.model_dump())
        if (self.read.task_id,self.read.run_id,self.read.proposal)!=(self.task.task_id,self.outcome.state.run.run_id,self.outcome.proposal):raise invalid()


def public_run(outcome,*,replayed=None):
    outcome.__post_init__();r,f=outcome.state.run,outcome.state.frozen
    return ProposalRun(run_id=r.run_id,task_id=r.task_id,input_revision=r.input_revision,source_message_id=f.source_message_id,
        input_digest=f.input_digest,source_digest=f.source_digest,stage=r.stage,attempt=r.attempt,provider_call_count=r.provider_call_count,
        deadline=r.deadline,cancelled_at=r.cancelled_at,error_code=r.error_code,omitted_context=f.omitted_context,
        proposal_available=outcome.proposal is not None,receipt=None if replayed is None else ProposalReceipt(replayed=replayed))


@dataclass(frozen=True)
class ProposalListOutcome:
    task:WorkTaskDTO
    outcomes:tuple[ProposalOutcome,...]
    runs:ProposalRunList
    def __post_init__(self):
        if type(self.task) is not WorkTaskDTO or type(self.outcomes) is not tuple or type(self.runs) is not ProposalRunList or len(self.outcomes)>20:raise invalid()
        if any(type(o) is not ProposalOutcome or o.task!=self.task for o in self.outcomes):raise invalid()
        if self.runs!=ProposalRunList(task_id=self.task.task_id,runs=tuple(public_run(o) for o in self.outcomes)):raise invalid()


class ProposalLineage(FrozenDTO):
    run_id:ProposalUUID
    task_id:ProposalUUID
    outline_id:ProposalUUID
    input_revision:Revision
    outline_revision:Revision
    outline_digest:Digest
    proposal_input_digest:Digest
    proposal_source_digest:Digest
    source_message_id:ProposalUUID
    source_message_digest:Digest
    proposal_result_digest:Digest
    admission_owner_storage_id:ProposalUUID
