"""Exact lesson_outline@1 commands, immutable context and public proposal wire."""
from datetime import datetime
import json
from typing import Annotated, Literal
from uuid import UUID
from pydantic import BeforeValidator, Field, ValidationError, model_validator
from app.schemas.teacher_work import (
    StrictRequest, FrozenDTO, Revision, Digest, UTCDateTime, ErrorCode, IDText,
    LessonSnapshot, Slides, FrozenPackageContent, ShortText, WorkMessageDTO, _array,
)
from app.services.teacher_work.types import canonical_digest, canonical_json_bytes


def _canonical_uuid(value):
    if isinstance(value, UUID):return value
    if type(value) is not str:raise ValueError('canonical UUID required')
    parsed=UUID(value)
    if str(parsed)!=value:raise ValueError('canonical UUID required')
    return parsed


ProposalUUID=Annotated[UUID,BeforeValidator(_canonical_uuid)]


class ProposalCommand(StrictRequest):
    skill_ref:Literal['lesson_outline@1']
    input_revision:Revision
    expected_revision:Revision
    source_message_id:ProposalUUID


class ProposalCancelCommand(StrictRequest):
    pass


class ProposalTaskBrief(FrozenDTO):
    task_id:ProposalUUID
    input_revision:Revision
    title:ShortText
    topic:ShortText
    audience:ShortText
    duration_minutes:int=Field(ge=1,le=600)
    target_slide_count:int=Field(ge=6,le=12)
    requirements:str=Field(max_length=4000)
    reference_ids:Annotated[tuple[ProposalUUID,...],BeforeValidator(_array),Field(max_length=10)]


class ProposalSourceFingerprint(FrozenDTO):
    resource_id:IDText
    sha256:Digest


def _context_messages(value):
    result=[]
    for item in _array(value):
        if type(item) is dict:result.append(WorkMessageDTO.model_validate_json(canonical_json_bytes(item)))
        elif type(item) is WorkMessageDTO:result.append(WorkMessageDTO.model_validate(item.model_dump()))
        else:raise ValueError('exact context messages required')
    return tuple(result)


class ProposalContext(FrozenDTO):
    skill_ref:Literal['lesson_outline@1']
    task_brief:ProposalTaskBrief
    source_digest:Digest
    source_fingerprints:Annotated[tuple[ProposalSourceFingerprint,...],BeforeValidator(_array),Field(min_length=1,max_length=10)]
    transcript:Annotated[tuple[WorkMessageDTO,...],BeforeValidator(_context_messages),Field(min_length=1)]
    omitted_context:bool

    @model_validator(mode='after')
    def distinct_fingerprints(self):
        if len({item.resource_id for item in self.source_fingerprints})!=len(self.source_fingerprints):
            raise ValueError('distinct exact fingerprints required')
        return self


class FrozenProposalInput(FrozenDTO):
    owner:IDText
    task_id:ProposalUUID
    input_revision:Revision
    source_message_id:ProposalUUID
    input_digest:Digest
    source_digest:Digest
    duration_minutes:int=Field(ge=1,le=600)
    target_slide_count:int=Field(ge=6,le=12)
    context_json:str=Field(min_length=1,max_length=24000)
    omitted_context:bool

    @model_validator(mode='after')
    def canonical_bound_context(self):
        data=json.loads(self.context_json)
        if (type(data) is not dict or set(data)!={'skill_ref','task_brief','source_digest','source_fingerprints','transcript','omitted_context'}
                or canonical_json_bytes(data).decode('utf-8')!=self.context_json or canonical_digest(data)!=self.input_digest):
            raise ValueError('exact immutable canonical context required')
        decoded=ProposalContext.model_validate_json(self.context_json)
        if decoded.model_dump(mode='json')!=data:raise ValueError('canonical typed context required')
        brief=data['task_brief'];transcript=data['transcript']
        if (data['skill_ref']!='lesson_outline@1' or data['source_digest']!=self.source_digest
                or type(data['omitted_context']) is not bool or data['omitted_context']!=self.omitted_context
                or type(brief) is not dict or type(transcript) is not list or not transcript
                or brief.get('task_id')!=str(self.task_id) or brief.get('input_revision')!=self.input_revision
                or brief.get('duration_minutes')!=self.duration_minutes or brief.get('target_slide_count')!=self.target_slide_count):
            raise ValueError('context binding differs')
        from app.schemas.teacher_work import WorkMessageDTO
        messages=tuple(WorkMessageDTO.model_validate_json(canonical_json_bytes(item)) for item in transcript)
        if (len({item.message_id for item in messages})!=len(messages)
                or any(item.owner!=self.owner or item.task_id!=self.task_id for item in messages)
                or any(left.created_at>right.created_at for left,right in zip(messages,messages[1:]))
                or messages[-1].message_id!=self.source_message_id or messages[-1].role!='assistant'
                or messages[-1].run_id is None or messages[-1].result_type is None):
            raise ValueError('context transcript binding differs')
        return self


class MaterialProposal(FrozenDTO):
    skill_ref:Literal['lesson_outline@1']='lesson_outline@1'
    input_revision:Revision
    source_message_id:ProposalUUID
    input_digest:Digest
    source_digest:Digest
    omitted_context:bool
    lesson:LessonSnapshot
    slides:Slides
    created_at:UTCDateTime

    @model_validator(mode='after')
    def bounded_without_evidence(self):
        if self.lesson.citations or any(s.evidence_refs or s.source_note for s in self.slides):
            raise ValueError('proposal cannot invent evidence or source claims')
        FrozenPackageContent(lesson=self.lesson,slides=self.slides,source_snapshots=())
        from app.services.teacher_work.materials import check_manual_approval_content
        check_manual_approval_content(self.lesson,self.slides)
        return self


class ProposalReceipt(FrozenDTO):
    operation:Literal['generate']='generate'
    replayed:bool


class ProposalRun(FrozenDTO):
    run_id:ProposalUUID
    task_id:ProposalUUID
    kind:Literal['outline']='outline'
    skill_ref:Literal['lesson_outline@1']='lesson_outline@1'
    input_revision:Revision
    source_message_id:ProposalUUID
    input_digest:Digest
    source_digest:Digest
    stage:Literal['PENDING','OUTLINE_RUNNING','COMPLETE','FAILED','CANCELLED']
    attempt:int=Field(strict=True,ge=1,le=1)
    provider_call_count:int=Field(strict=True,ge=0,le=1)
    deadline:UTCDateTime
    cancelled_at:UTCDateTime|None
    error_code:ErrorCode|None
    omitted_context:bool
    proposal_available:bool
    receipt:ProposalReceipt|None

    @model_validator(mode='after')
    def available_complete(self):
        if self.proposal_available and self.stage!='COMPLETE':raise ValueError('confirmed COMPLETE required')
        return self



def _proposal_runs(value):
    result=[]
    for item in _array(value):
        if type(item) is ProposalRun:result.append(ProposalRun.model_validate(item.model_dump()))
        elif type(item) is dict:
            try:result.append(ProposalRun.model_validate(item))
            except ValidationError:result.append(ProposalRun.model_validate_json(canonical_json_bytes(item)))
        else:raise ValueError('exact proposal run rows required')
    return tuple(result)


class ProposalRunList(FrozenDTO):
    task_id:ProposalUUID
    runs:Annotated[tuple[ProposalRun,...],BeforeValidator(_proposal_runs),Field(max_length=20)]

    @model_validator(mode='after')
    def exact_owned_runs(self):
        if (len({item.run_id for item in self.runs})!=len(self.runs)
                or any(item.task_id!=self.task_id or item.receipt is not None for item in self.runs)):
            raise ValueError('distinct exact task runs without admission receipts required')
        return self


class ProposalFreshness(FrozenDTO):
    adoptable:bool
    reason:Literal['PROPOSAL_NOT_READY','STALE_INPUT_REVISION','SOURCE_CHANGED','SOURCE_UNAVAILABLE','SOURCE_MESSAGE_INELIGIBLE']|None

    @model_validator(mode='after')
    def exact_reason(self):
        if self.adoptable!=(self.reason is None):raise ValueError('exact freshness reason required')
        return self


class ProposalRead(FrozenDTO):
    task_id:ProposalUUID
    run_id:ProposalUUID
    proposal:MaterialProposal|None
    freshness:ProposalFreshness

    @model_validator(mode='after')
    def ready_freshness(self):
        if self.proposal is None and (self.freshness.adoptable or self.freshness.reason!='PROPOSAL_NOT_READY'):
            raise ValueError('absent proposal is not ready')
        return self


class ProposalLimits(FrozenDTO):
    max_context_characters:Literal[24000]=24000
    max_content_utf8_bytes:Literal[131072]=131072
    max_envelope_utf8_bytes:Literal[262144]=262144
    max_retained_runs_per_task:Literal[20]=20
    max_provider_calls:Literal[1]=1
    max_attempts:Literal[1]=1
    max_timeout_seconds:Literal[90]=90
    max_output_tokens:Literal[8192]=8192

    @model_validator(mode='before')
    @classmethod
    def strict_fixed_integers(cls,value):
        if isinstance(value,dict) and any(type(item) is not int for item in value.values()):
            raise ValueError('strict fixed integer limits required')
        return value


def _strict_false(value):
    if type(value) is not bool or value is not False:raise ValueError('strict false required')
    return value


class ProposalCapabilities(FrozenDTO):
    skill_ref:Literal['lesson_outline@1']='lesson_outline@1'
    generate:bool
    read:bool
    cancel:bool
    provider_configured:bool
    external_provider_verified:Annotated[Literal[False],BeforeValidator(_strict_false)]=False
    reasons:dict[Literal['generate','read','cancel'],Literal['private_material_proposals_disabled','proposal_schema_unavailable','materials_unavailable','proposal_runtime_unavailable','provider_unconfigured']]
    limits:ProposalLimits

    @model_validator(mode='after')
    def exact_reasons(self):
        if set(self.reasons)!={key for key in ('generate','read','cancel') if getattr(self,key) is False}:
            raise ValueError('exact disabled operation reasons required')
        if type(self.external_provider_verified) is not bool:raise ValueError('strict false required')
        return self
