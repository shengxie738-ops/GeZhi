"""Exact manual package wire, with no caller-controlled execution or storage."""
from typing import Literal
from uuid import UUID
from pydantic import Field, model_validator
from app.schemas.teacher_work import (
    StrictRequest, FrozenDTO, Revision, Digest, UTCDateTime, ErrorCode,
    PackageVersionDTO, ArtifactDTO, ApprovalReceipt, WorkTaskDTO,
)


class PrivatePackageCreateRequest(StrictRequest):
    approval_id: UUID
    input_revision: Revision
    outline_revision: Revision
    outline_digest: Digest
    source_digest: Digest
    expected_revision: Revision


class PrivatePackageRetryRequest(StrictRequest):
    expected_attempt: int = Field(strict=True, ge=1, le=1)


class PrivatePackageCapabilities(FrozenDTO):
    create:bool
    read:bool
    retry:bool
    download:bool
    storage_configured:bool
    reasons:dict[str,Literal['private_exports_disabled','package_schema_unavailable','private_storage_unavailable','materials_unavailable']]

    @model_validator(mode='after')
    def exact_disabled_reasons(self):
        disabled={name for name in ('create','read','retry','download','storage_configured') if getattr(self,name) is False}
        if set(self.reasons)!=disabled or any(not reason for reason in self.reasons.values()):raise ValueError('exact disabled reasons required')
        return self


class PrivatePackageRun(FrozenDTO):
    run_id: UUID
    kind: Literal['package'] = 'package'
    input_revision: Revision
    outline_revision: Revision
    stage: Literal['PENDING','CONTENT_VALIDATED','FILES_RUNNING','PACKAGE_READY','COMPLETE','FAILED','CANCELLED','INTERRUPTED']
    attempt: int = Field(strict=True, ge=1, le=2)
    provider_call_count: int = Field(strict=True, ge=0, le=0)
    deadline: UTCDateTime
    error_code: ErrorCode | None
    result_version_id: UUID | None


class PrivatePackageReceipt(FrozenDTO):
    operation: Literal['create','retry']
    run_id: UUID
    version_id: UUID
    attempt: int = Field(strict=True, ge=1, le=2)
    replayed: bool

    @model_validator(mode='after')
    def exact_attempt(self):
        if self.attempt != (1 if self.operation == 'create' else 2):
            raise ValueError('receipt operation and attempt differ')
        return self


class PrivatePackageState(FrozenDTO):
    task: WorkTaskDTO
    run: PrivatePackageRun
    version: PackageVersionDTO
    approval: ApprovalReceipt
    provenance: Literal['manual'] = 'manual'
    artifacts: tuple[ArtifactDTO, ArtifactDTO]
    retry_available: bool
    receipt: PrivatePackageReceipt | None = None

    @model_validator(mode='after')
    def bound_manual_state(self):
        if (self.version.task_id != self.task.task_id or self.approval.task_id != self.task.task_id
                or self.approval.owner != self.task.owner_subject or self.version.run_id != self.run.run_id
                or self.version.model_id != 'manual-approved@1' or self.version.skill_versions
                or self.version.source_snapshots or any(s.evidence_refs for s in self.version.slides)
                or (self.run.input_revision,self.run.outline_revision) != (self.approval.input_revision,self.approval.outline_revision)
                or tuple(a.kind for a in self.artifacts) != ('pptx','docx')
                or any(a.version_id != self.version.version_id for a in self.artifacts)
                or self.run.result_version_id not in (None,self.version.version_id)):
            raise ValueError('incoherent manual package')
        if self.run.stage in ('PACKAGE_READY','COMPLETE') and (self.run.result_version_id != self.version.version_id or any(a.state!='READY' for a in self.artifacts)):
            raise ValueError('complete package requires both ready files')
        if self.receipt and (self.receipt.run_id,self.receipt.version_id)!=(self.run.run_id,self.version.version_id):
            raise ValueError('receipt scope differs')
        return self

    def public_data(self):
        data=self.model_dump(mode='json',exclude={'task'})
        data['task_id']=str(self.task.task_id)
        data['approval'].pop('owner')
        return data


class PackageArtifactSummary(FrozenDTO):
    artifact_id:UUID
    kind:Literal['pptx','docx']
    state:Literal['PENDING','BUILDING','VALIDATING','READY','FAILED']
    download_available:bool

    @model_validator(mode='after')
    def exact_availability(self):
        if self.download_available and self.state!='READY':raise ValueError('only verified READY bytes downloadable')
        return self


class PackageListEntry(FrozenDTO):
    version_id:UUID
    version_no:Revision
    run_id:UUID
    approval_id:UUID
    created_at:UTCDateTime
    stage:Literal['PENDING','CONTENT_VALIDATED','FILES_RUNNING','PACKAGE_READY','COMPLETE','FAILED','CANCELLED','INTERRUPTED']
    attempt:int=Field(strict=True,ge=1,le=2)
    artifacts:tuple[PackageArtifactSummary,PackageArtifactSummary]

    @model_validator(mode='after')
    def exact_formats(self):
        if tuple(a.kind for a in self.artifacts)!=('pptx','docx'):raise ValueError('fixed package formats required')
        return self


class PrivatePackageList(FrozenDTO):
    task:WorkTaskDTO
    items:tuple[PackageListEntry,...]=Field(max_length=20)
    next_before:UUID|None
    truncated:bool

    @model_validator(mode='after')
    def exact_page(self):
        numbers=tuple(item.version_no for item in self.items)
        if (numbers!=tuple(sorted(set(numbers),reverse=True)) or self.truncated!=(self.next_before is not None)
                or self.truncated and (not self.items or self.next_before!=self.items[-1].version_id)):
            raise ValueError('exact descending bounded page required')
        return self

    def public_data(self):
        return {'task_id':str(self.task.task_id),**self.model_dump(mode='json',exclude={'task'})}
