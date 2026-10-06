"""Narrow manual Office persistence on the existing caller-owned SQL root."""
from dataclasses import dataclass
from datetime import timedelta
from hashlib import sha256
import json
from uuid import UUID

from sqlalchemy import insert, select, update
from app.models.teacher_work import Artifact, OwnerRunLease, WorkRun, WorkTask, OutlineApproval
from app.models.teacher_work_v3 import PackageVersion
from app.repositories.teacher_work import TaskRecord, WorkRepositoryError
from app.repositories.teacher_work_sql import _utc
from app.schemas.teacher_work import ArtifactDTO, PackageVersionDTO, WorkTaskDTO
from app.schemas.teacher_work_exports import PrivatePackageState, PrivatePackageRun, PrivatePackageReceipt,PrivatePackageList,PackageListEntry,PackageArtifactSummary
from app.services.teacher_work.exporters.theme import TEMPLATE_VERSION,PPTX_EXPORTER_VERSION,DOCX_EXPORTER_VERSION
from app.services.teacher_work.materials import check_manual_approval_content
from app.services.teacher_work.private_storage import FILE_CAP,storage_key,PrivateArtifactAbsent
from app.services.teacher_work.types import canonical_digest

OWNER_CAP=200*1024*1024
MIMES={'pptx':'application/vnd.openxmlformats-officedocument.presentationml.presentation','docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}
EXPORTERS={'pptx':PPTX_EXPORTER_VERSION,'docx':DOCX_EXPORTER_VERSION}


def error(code='PACKAGE_STATE_UNAVAILABLE',status=503):return WorkRepositoryError(code,status)


@dataclass(frozen=True)
class PackageFence:
    run_id:UUID
    attempt:int
    lease_revision:int
    process_instance:UUID


class PrivatePackageRepository:
    def __init__(self,core,materials,storage):
        if materials.core is not core:raise ValueError('same caller root required')
        self.core,self.materials,self.storage=core,materials,storage
        self.guard=core.run_rows
        self.completed_in_root=False
        self.expected_lease=None
        self.download_target=None

    def _locked(self,owner,task_id,*,write=False):
        row,draft=self.materials._locked(owner,task_id)
        self.guard._task(owner,task_id,write=write)
        return row,draft

    def _read(self,statement):return self.guard._read(statement)

    def _one(self,statement,*,absent=False):
        found=self._read(statement.limit(2).with_for_update())
        if len(found)!=1:
            if not found and absent:return None
            raise error()
        return found[0]

    def _lease(self,owner):
        return self._one(select(OwnerRunLease).where(OwnerRunLease.owner==owner))

    def list(self,owner,task_id,*,limit=20,before=None):
        task=self._locked(owner,task_id)[0].task
        if type(limit) is not int or not 1<=limit<=20:raise error('INVALID_PRIVATE_PACKAGE_LIST_REQUEST',422)
        query=select(PackageVersion).where(PackageVersion.task_id==str(task_id),PackageVersion.model_id=='manual-approved@1',PackageVersion.approval_id.is_not(None))
        if before is not None:
            cursor=self._one(select(PackageVersion).where(PackageVersion.task_id==str(task_id),PackageVersion.version_id==str(before)),absent=True)
            if cursor is None:raise error('NOT_FOUND',404)
            query=query.where(PackageVersion.version_no<cursor.version_no)
        rows=self._read(query.order_by(PackageVersion.version_no.desc()).limit(limit+1))
        items=[]
        for row in rows[:limit]:
            value=self.get(owner,task_id,UUID(row.version_id))
            summaries=[]
            for artifact in value.artifacts:
                available=artifact.state=='READY' and self.file_available(value,artifact)
                summaries.append(PackageArtifactSummary(artifact_id=artifact.artifact_id,kind=artifact.kind,state=artifact.state,download_available=available))
            items.append(PackageListEntry(version_id=value.version.version_id,version_no=value.version.version_no,run_id=value.run.run_id,
                approval_id=value.approval.approval_id,created_at=value.version.created_at,stage=value.run.stage,attempt=value.run.attempt,artifacts=tuple(summaries)))
        more=len(rows)>limit
        result=PrivatePackageList(task=task,items=tuple(items),next_before=items[-1].version_id if more else None,truncated=more)
        self._list_request=(limit,before)
        return result

    def _write(self,statement,*,one=False):
        result=self.core.uow.execute_write(statement.execution_options(synchronize_session=False))
        if one and (type(result.rowcount) is not int or result.rowcount!=1):raise error('PACKAGE_FENCE_CHANGED',409)

    @staticmethod
    def _digest(version):
        return canonical_digest(version.model_dump(mode='json',include={'lesson','slides','source_snapshots'}))

    def _version(self,row):
        try:
            data={name:getattr(row,name) for name in PackageVersionDTO.model_fields}
            data['created_at']=_utc(data['created_at']).isoformat()
            value=PackageVersionDTO.model_validate_json(json.dumps(data,ensure_ascii=False,allow_nan=False))
            if (self._digest(value)!=value.content_digest or value.model_id!='manual-approved@1'
                    or value.source_snapshots or value.skill_versions or any(s.evidence_refs for s in value.slides)
                    or value.exporter_versions!=(PPTX_EXPORTER_VERSION,DOCX_EXPORTER_VERSION)
                    or value.template_version!=TEMPLATE_VERSION or row.approval_id is None):raise ValueError()
            return value
        except (ValueError,TypeError,AttributeError):raise error() from None

    def _artifact(self,row,version,namespace):
        try:
            value=ArtifactDTO.model_validate_json(json.dumps({n:getattr(row,n) for n in ArtifactDTO.model_fields},allow_nan=False))
            if (value.version_id!=version.version_id or value.exporter_version!=EXPORTERS[value.kind]
                    or row.storage_key!=storage_key(namespace,value.artifact_id,value.kind)):raise ValueError()
            return value
        except (ValueError,TypeError,AttributeError):raise error() from None

    def get(self,owner,task_id,version_id,*,receipt=None):
        task=self._locked(owner,task_id)[0].task
        stored=self._one(select(PackageVersion).where(PackageVersion.task_id==str(task_id),PackageVersion.version_id==str(version_id)),absent=True)
        if stored is None:raise error('NOT_FOUND',404)
        version=self._version(stored)
        run=self._one(select(WorkRun).where(WorkRun.owner==owner,WorkRun.task_id==str(task_id),WorkRun.run_id==str(version.run_id)))
        try:
            data={n:getattr(run,n) for n in PrivatePackageRun.model_fields}
            data['deadline']=_utc(data['deadline']).isoformat()
            public_run=PrivatePackageRun.model_validate_json(json.dumps(data,allow_nan=False))
            if run.repair_count!=0 or run.skill_ref is not None or any(getattr(run,n) is not None for n in ('active_call_no','active_call_attempt','active_call_lease_revision','active_call_process_instance','cancelled_at')):raise ValueError()
        except (ValueError,TypeError,AttributeError):raise error() from None
        bound=self._one(select(OutlineApproval).where(OutlineApproval.owner==owner,OutlineApproval.task_id==str(task_id),OutlineApproval.approval_id==stored.approval_id))
        snapshot=self.materials.rows.get_outline(owner,task_id,UUID(bound.outline_id))
        approval=self.materials.rows.approval(owner,snapshot)
        if (approval is None or str(approval.approval_id)!=stored.approval_id or version.lesson!=snapshot.lesson or version.slides!=snapshot.slides):raise error()
        rows=self._read(select(Artifact).where(Artifact.version_id==str(version_id)).order_by(Artifact.kind.desc()).with_for_update())
        if len(rows)!=2:raise error()
        artifacts=tuple(self._artifact(r,version,task.owner_storage_id) for r in rows)
        lease=self._lease(owner)
        from app.core.config import settings
        retry=(settings.TEACHER_WORK_PRIVATE_MATERIALS_ENABLED is True and public_run.stage in ('FAILED','INTERRUPTED') and public_run.attempt==1 and self.core._instant()<public_run.deadline
               and lease.active_run_id is None and any(a.state=='FAILED' for a in artifacts))
        if retry:
            try:self.verify_current(PrivatePackageState(task=task,run=public_run,version=version,approval=approval,artifacts=artifacts,retry_available=False))
            except WorkRepositoryError:retry=False
        return PrivatePackageState(task=task,run=public_run,version=version,approval=approval,artifacts=artifacts,retry_available=retry,receipt=receipt)

    def verify_current(self,value):
        row,draft=self._locked(value.task.owner_subject,value.task.task_id)
        current=row.task
        snapshot=self.materials.rows.latest(current.owner_subject,current.task_id)
        if (current.input_revision!=value.approval.input_revision or current.current_outline_id!=value.approval.outline_id
                or snapshot is None or snapshot.outline_id!=value.approval.outline_id):raise error('OUTLINE_APPROVAL_CONFLICT',409)
        if self.materials._source(current,draft.payload)!=value.approval.source_digest:raise error('SOURCE_CHANGED',409)
        from app.services.teacher_work.legacy import preserve_legacy_lesson,normalize_legacy_for_task
        from app.services.teacher_work.types import canonical_json_bytes
        if normalize_legacy_for_task(draft.payload['content'],current.duration_minutes).needs_normalization_fields:
            raise error('NORMALIZATION_REQUIRED',409)
        try:
            if canonical_json_bytes(preserve_legacy_lesson(draft.payload['content'],value.version.lesson.model_dump(mode='json')))!=canonical_json_bytes(draft.payload['content']):raise ValueError()
            check_manual_approval_content(value.version.lesson,value.version.slides)
        except (ValueError,TypeError,KeyError):raise error('PACKAGE_STATE_UNAVAILABLE') from None

    def quota(self,owner,namespace,*,extra=0):
        self.guard._owner(owner)
        rows=self._read(select(Artifact).join(PackageVersion,Artifact.version_id==PackageVersion.version_id).join(WorkTask,PackageVersion.task_id==WorkTask.task_id).where(WorkTask.owner_subject==owner))
        keys=set();claims=0
        entries=2*(extra//FILE_CAP)
        for row in rows:
            if row.storage_key is None:raise error()
            if row.storage_key!=storage_key(namespace,UUID(row.artifact_id),row.kind) or row.storage_key in keys:raise error()
            keys.add(row.storage_key)
            if row.state=='READY':
                entries+=1
                value=ArtifactDTO.model_validate_json(json.dumps({n:getattr(row,n) for n in ArtifactDTO.model_fields}))
                raw=self.storage.read(row.storage_key)
                if len(raw)!=value.byte_size or sha256(raw).hexdigest()!=value.sha256:raise error('PRIVATE_STORAGE_UNAVAILABLE')
                claims+=value.byte_size
            else:claims+=FILE_CAP;entries+=2
        from app.services.teacher_work.private_storage import ENTRY_CAP
        if entries>ENTRY_CAP:raise error('OWNER_STORAGE_QUOTA_EXCEEDED',429)
        try:observed=self.storage.inventory(namespace,keys)
        except (ValueError,OSError):raise error('PRIVATE_STORAGE_UNAVAILABLE') from None
        if sum(observed.values())>claims:raise error('PRIVATE_STORAGE_UNAVAILABLE')
        if claims+extra>OWNER_CAP:raise error('OWNER_STORAGE_QUOTA_EXCEEDED',429)

    def recover(self,owner,task_id,run_id,stopped):
        row=self._one(select(PackageVersion).where(PackageVersion.task_id==str(task_id),PackageVersion.run_id==str(run_id)))
        value=self.get(owner,task_id,UUID(row.version_id))
        if value.run.stage!='FILES_RUNNING':return value
        lease=self._lease(owner)
        try:fence=PackageFence(run_id,value.run.attempt,lease.revision,UUID(lease.process_instance))
        except (ValueError,TypeError):raise error() from None
        if lease.active_run_id!=str(run_id) or _utc(lease.expires_at)!=value.run.deadline:raise error()
        expired=self.core._instant()>=value.run.deadline
        if not expired and fence not in stopped:return value
        if not expired and all(a.state=='READY' for a in value.artifacts):
            try:self.verify_current(value)
            except WorkRepositoryError:pass
            else:return self.finish(owner,task_id,value.version.version_id,fence)
        # Fresh authority/owner locks fence every old publisher. Unknown files
        # and complete path claims remain intact; no byte cleanup or rebuild.
        code='PACKAGE_DEADLINE_EXPIRED' if expired else 'PACKAGE_EXECUTION_INTERRUPTED'
        self._write(update(Artifact).where(Artifact.version_id==row.version_id,Artifact.state.in_(('PENDING','BUILDING','VALIDATING'))).values(state='FAILED',error_code=code))
        self._write(update(WorkRun).where(WorkRun.owner==owner,WorkRun.task_id==str(task_id),WorkRun.run_id==str(run_id),WorkRun.attempt==fence.attempt,WorkRun.stage=='FILES_RUNNING').values(stage='INTERRUPTED',error_code=code),one=True)
        self._write(update(OwnerRunLease).where(OwnerRunLease.owner==owner,OwnerRunLease.active_run_id==str(run_id),OwnerRunLease.revision==fence.lease_revision,
            OwnerRunLease.process_instance==str(fence.process_instance),OwnerRunLease.expires_at==value.run.deadline.replace(tzinfo=None)).values(
            revision=fence.lease_revision+1,active_run_id=None,process_instance=None,expires_at=None),one=True)
        self.expected_lease=(fence.lease_revision+1,None,None,None)
        return self.get(owner,task_id,value.version.version_id)

    def create(self,owner,task_id,request,key,process_instance,stopped=frozenset()):
        row,draft=self._locked(owner,task_id,write=True);task=row.task
        digest=canonical_digest(request.model_dump(mode='json'))
        existing=self._one(select(WorkRun).where(WorkRun.owner==owner,WorkRun.task_id==str(task_id),WorkRun.kind=='package',WorkRun.idempotency_key==key.encode('utf-8')),absent=True)
        if existing is not None:
            if existing.request_digest!=digest:raise error('IDEMPOTENCY_CONFLICT',409)
            self.recover(owner,task_id,UUID(existing.run_id),stopped)
            version=self._one(select(PackageVersion).where(PackageVersion.run_id==existing.run_id,PackageVersion.task_id==str(task_id)))
            receipt=PrivatePackageReceipt(operation='create',run_id=UUID(existing.run_id),version_id=UUID(version.version_id),attempt=1,replayed=True)
            return self.get(owner,task_id,UUID(version.version_id),receipt=receipt),None
        from app.core.config import settings
        if settings.TEACHER_WORK_PRIVATE_MATERIALS_ENABLED is not True:raise error('PRIVATE_MATERIALS_DISABLED')
        if request.expected_revision!=task.working_revision:raise error('REVISION_CONFLICT',409)
        active=self._lease(owner)
        if active.active_run_id is not None:
            held=self._one(select(WorkRun).where(WorkRun.owner==owner,WorkRun.run_id==active.active_run_id))
            if held.kind=='package' and held.task_id==str(task_id):self.recover(owner,task_id,UUID(held.run_id),stopped)
        material=self.materials.get(owner,task_id)
        if material.approval is None or (request.approval_id,request.input_revision,request.outline_revision,request.outline_digest,request.source_digest)!=(material.approval.approval_id,material.approval.input_revision,material.approval.outline_revision,material.approval.outline_digest,material.approval.source_digest):raise error('OUTLINE_APPROVAL_CONFLICT',409)
        if not material.approval_current:raise error(material.approval_blocker or 'OUTLINE_APPROVAL_CONFLICT',409)
        lease=self._lease(owner)
        if lease.active_run_id is not None:raise error('OWNER_RUN_BUSY',409)
        self.quota(owner,task.owner_storage_id,extra=2*FILE_CAP)
        now=self.core._instant();run_id=self.core._uuid();version_id=self.core._uuid()
        latest=self._read(select(PackageVersion).where(PackageVersion.task_id==str(task_id)).order_by(PackageVersion.version_no.desc()).limit(1))
        version=PackageVersionDTO(version_id=version_id,task_id=task_id,version_no=latest[0].version_no+1 if latest else 1,
            base_version_id=None,run_id=run_id,lesson=material.outline.lesson,slides=material.outline.slides,source_snapshots=(),content_digest='0'*64,
            model_id='manual-approved@1',skill_versions=(),exporter_versions=(PPTX_EXPORTER_VERSION,DOCX_EXPORTER_VERSION),template_version=TEMPLATE_VERSION,created_at=now)
        version=version.model_copy(update={'content_digest':self._digest(version)})
        self._write(insert(WorkRun).values(run_id=str(run_id),owner=owner,task_id=str(task_id),kind='package',skill_ref=None,
            input_revision=request.input_revision,outline_revision=request.outline_revision,idempotency_key=key.encode('utf-8'),request_digest=digest,
            stage='FILES_RUNNING',attempt=1,provider_call_count=0,repair_count=0,deadline=(now+timedelta(seconds=300)).replace(tzinfo=None)))
        values=version.model_dump(mode='json');values['created_at']=now.replace(tzinfo=None)
        self._write(insert(PackageVersion).values(**values,approval_id=str(request.approval_id)))
        for kind in ('pptx','docx'):
            identifier=self.core._uuid()
            self._write(insert(Artifact).values(artifact_id=str(identifier),version_id=str(version_id),kind=kind,state='PENDING',
                storage_key=storage_key(task.owner_storage_id,identifier,kind),download_name=f'GeZhi-{version_id}.{kind}',mime=MIMES[kind],byte_size=0,
                sha256=None,exporter_version=EXPORTERS[kind],validation_summary=None,error_code=None))
        fence=PackageFence(run_id,1,lease.revision+1,process_instance)
        self._write(update(OwnerRunLease).where(OwnerRunLease.owner==owner,OwnerRunLease.revision==lease.revision,OwnerRunLease.active_run_id.is_(None)).values(
            revision=fence.lease_revision,active_run_id=str(run_id),process_instance=str(process_instance),expires_at=(now+timedelta(seconds=300)).replace(tzinfo=None)),one=True)
        self.expected_lease=(fence.lease_revision,str(run_id),str(process_instance),now+timedelta(seconds=300))
        receipt=PrivatePackageReceipt(operation='create',run_id=run_id,version_id=version_id,attempt=1,replayed=False)
        return self.get(owner,task_id,version_id,receipt=receipt),fence

    def _fenced(self,value,fence):
        owner=value.task.owner_subject
        lease=self._lease(owner)
        if (fence.run_id!=value.run.run_id or fence.attempt!=value.run.attempt or value.run.stage!='FILES_RUNNING'
                or (lease.active_run_id,lease.revision,lease.process_instance)!=(str(fence.run_id),fence.lease_revision,str(fence.process_instance))):raise error('PACKAGE_FENCE_CHANGED',409)
        if _utc(lease.expires_at)!=value.run.deadline:raise error('PACKAGE_FENCE_CHANGED',409)
        if self.core._instant()>=value.run.deadline:raise error('PACKAGE_DEADLINE_EXPIRED',409)
        self.verify_current(value)

    def retry(self,owner,task_id,run_id,process_instance,stopped=frozenset()):
        self._locked(owner,task_id,write=True)
        row=self._one(select(PackageVersion).where(PackageVersion.task_id==str(task_id),PackageVersion.run_id==str(run_id)),absent=True)
        if row is None:raise error('NOT_FOUND',404)
        self.recover(owner,task_id,run_id,stopped)
        value=self.get(owner,task_id,UUID(row.version_id))
        receipt=PrivatePackageReceipt(operation='retry',run_id=run_id,version_id=value.version.version_id,attempt=2,replayed=value.run.attempt==2)
        if value.run.attempt==2:return value.model_copy(update={'receipt':receipt}),None
        from app.core.config import settings
        if settings.TEACHER_WORK_PRIVATE_MATERIALS_ENABLED is not True:raise error('PRIVATE_MATERIALS_DISABLED')
        if self.core._instant()>=value.run.deadline:raise error('PACKAGE_DEADLINE_EXPIRED',409)
        if not value.retry_available:raise error('PACKAGE_RETRY_UNAVAILABLE',409)
        self.verify_current(value);lease=self._lease(owner)
        self.quota(owner,value.task.owner_storage_id)
        for artifact in value.artifacts:
            if artifact.state!='FAILED':continue
            key=storage_key(value.task.owner_storage_id,artifact.artifact_id,artifact.kind)
            # This run has a committed terminal failure and no held execution.
            # Unknown filesystem layouts refuse before any unlink or SQL claim.
            try:self.storage.remove(key)
            except (ValueError,OSError):raise error('PRIVATE_STORAGE_UNAVAILABLE') from None
            self._write(update(Artifact).where(Artifact.artifact_id==str(artifact.artifact_id),Artifact.state=='FAILED').values(state='PENDING',byte_size=0,sha256=None,validation_summary=None,error_code=None),one=True)
        fence=PackageFence(run_id,2,lease.revision+1,process_instance)
        self._write(update(WorkRun).where(WorkRun.run_id==str(run_id),WorkRun.attempt==1,WorkRun.stage.in_(('FAILED','INTERRUPTED'))).values(attempt=2,stage='FILES_RUNNING',error_code=None),one=True)
        self._write(update(OwnerRunLease).where(OwnerRunLease.owner==owner,OwnerRunLease.revision==lease.revision,OwnerRunLease.active_run_id.is_(None)).values(
            revision=fence.lease_revision,active_run_id=str(run_id),process_instance=str(process_instance),expires_at=value.run.deadline.replace(tzinfo=None)),one=True)
        self.expected_lease=(fence.lease_revision,str(run_id),str(process_instance),value.run.deadline)
        return self.get(owner,task_id,value.version.version_id,receipt=receipt),fence

    def record_file(self,owner,task_id,version_id,fence,kind,*,raw=None,verdict=None,failure=None):
        self._locked(owner,task_id,write=True)
        value=self.get(owner,task_id,version_id);self._fenced(value,fence)
        artifact=next(a for a in value.artifacts if a.kind==kind)
        if artifact.state!='PENDING':raise error('PACKAGE_FENCE_CHANGED',409)
        key=storage_key(value.task.owner_storage_id,artifact.artifact_id,kind)
        if failure is not None:
            self._write(update(Artifact).where(Artifact.artifact_id==str(artifact.artifact_id),Artifact.state=='PENDING').values(state='FAILED',error_code=failure),one=True)
        else:
            if verdict is None or not verdict.valid or not 0<len(raw)<=FILE_CAP:raise error('INVALID_OFFICE_PACKAGE',422)
            self.quota(owner,value.task.owner_storage_id)
            try:
                self.storage.publish(key,raw)
                verified=self.storage.read(key)
                if verified!=raw:raise ValueError()
            except (ValueError,OSError):raise error('PRIVATE_STORAGE_UNAVAILABLE') from None
            self._write(update(Artifact).where(Artifact.artifact_id==str(artifact.artifact_id),Artifact.state=='PENDING').values(state='READY',byte_size=len(raw),
                sha256=sha256(raw).hexdigest(),validation_summary=verdict.model_dump(mode='json'),error_code=None),one=True)
        return self.get(owner,task_id,version_id)

    def finish(self,owner,task_id,version_id,fence,*,failure=None):
        self._locked(owner,task_id,write=True)
        value=self.get(owner,task_id,version_id)
        # A terminated child may have consumed the absolute deadline; failure
        # finalization still requires exact owner/attempt/fence and current input.
        lease=self._lease(owner)
        if (lease.active_run_id,lease.revision,lease.process_instance,value.run.attempt)!=(str(fence.run_id),fence.lease_revision,str(fence.process_instance),fence.attempt):raise error('PACKAGE_FENCE_CHANGED',409)
        if value.run.run_id!=fence.run_id or value.run.stage!='FILES_RUNNING' or _utc(lease.expires_at)!=value.run.deadline:raise error('PACKAGE_FENCE_CHANGED',409)
        if failure not in ('SOURCE_CHANGED','OUTLINE_APPROVAL_CONFLICT','NORMALIZATION_REQUIRED','PACKAGE_DEADLINE_EXPIRED','PRIVATE_STORAGE_UNAVAILABLE'):
            self.verify_current(value)
        complete=all(a.state=='READY' for a in value.artifacts) and self.core._instant()<value.run.deadline and failure is None
        code=failure or ('PACKAGE_DEADLINE_EXPIRED' if self.core._instant()>=value.run.deadline else 'PACKAGE_FILES_FAILED')
        if not complete:
            self._write(update(Artifact).where(Artifact.version_id==str(version_id),Artifact.state.in_(('PENDING','BUILDING','VALIDATING'))).values(state='FAILED',error_code=code))
        self._write(update(WorkRun).where(WorkRun.run_id==str(fence.run_id),WorkRun.attempt==fence.attempt,WorkRun.stage=='FILES_RUNNING').values(
            stage='COMPLETE' if complete else 'FAILED',result_version_id=str(version_id) if complete else None,error_code=None if complete else code),one=True)
        if complete:
            self.completed_in_root=True
            locked=self.core.rows.locked_tasks[(owner,task_id)]
            saved=WorkTaskDTO.model_validate({**value.task.model_dump(),'latest_version_id':version_id,'working_revision':value.task.working_revision+1,'updated_at':self.core._instant()})
            if not self.core.rows.compare_and_swap_task(owner,task_id,value.task.working_revision,TaskRecord(saved,locked.create_idempotency_key,locked.create_request_digest)):raise error('REVISION_CONFLICT',409)
        self._write(update(OwnerRunLease).where(OwnerRunLease.owner==owner,OwnerRunLease.revision==fence.lease_revision,OwnerRunLease.active_run_id==str(fence.run_id)).values(
            revision=fence.lease_revision+1,active_run_id=None,process_instance=None,expires_at=None),one=True)
        self.expected_lease=(fence.lease_revision+1,None,None,None)
        return self.get(owner,task_id,version_id)

    def file_available(self,value,artifact):
        try:raw=self.storage.read(storage_key(value.task.owner_storage_id,artifact.artifact_id,artifact.kind))
        except PrivateArtifactAbsent:return False
        except (ValueError,OSError):raise error('PRIVATE_STORAGE_UNAVAILABLE') from None
        return len(raw)==artifact.byte_size and sha256(raw).hexdigest()==artifact.sha256

    def verified_download(self,value,artifact_id):
        artifact=next((a for a in value.artifacts if a.artifact_id==artifact_id),None)
        if artifact is None:raise error('NOT_FOUND',404)
        if artifact.state!='READY':raise error('ARTIFACT_NOT_READY',409)
        try:raw=self.storage.read(storage_key(value.task.owner_storage_id,artifact.artifact_id,artifact.kind))
        except (ValueError,OSError):raise error('PRIVATE_STORAGE_UNAVAILABLE') from None
        if len(raw)!=artifact.byte_size or sha256(raw).hexdigest()!=artifact.sha256:raise error('PRIVATE_STORAGE_UNAVAILABLE')
        return raw,artifact

    def verify_outcome(self,value,*,current=False,fence=None,metadata_read=False):
        if type(metadata_read) is not bool or metadata_read and (type(value) is not PrivatePackageState
                or self.guard.state.mode!='read' or current or fence is not None or self.completed_in_root
                or self.expected_lease is not None or self.download_target is not None):
            raise error()
        if type(value) is PrivatePackageList:
            limit,before=self._list_request
            if self.list(value.task.owner_subject,value.task.task_id,limit=limit,before=before)!=value:raise error()
            return
        observed=self.get(value.task.owner_subject,value.task.task_id,value.version.version_id,receipt=value.receipt)
        if observed!=value:raise error()
        if current:self.verify_current(value)
        if self.completed_in_root and self.core._instant()>=value.run.deadline:raise error('PACKAGE_DEADLINE_EXPIRED',409)
        if self.expected_lease is not None:
            lease=self._lease(value.task.owner_subject)
            actual=(lease.revision,lease.active_run_id,lease.process_instance,_utc(lease.expires_at) if lease.expires_at is not None else None)
            if actual!=self.expected_lease:raise error('PACKAGE_FENCE_CHANGED',409)
        if fence:self._fenced(value,fence)
        if self.download_target is not None and self.download_target not in {a.artifact_id for a in value.artifacts}:
            raise error()
        for artifact in value.artifacts:
            if metadata_read:
                # Check existing paths for every state without reading bytes.
                # A nonREADY generation may never have made its owner directory.
                try:self.storage.check_metadata_path(storage_key(value.task.owner_storage_id,artifact.artifact_id,artifact.kind),
                    allow_absent_owner=artifact.state!='READY')
                except (ValueError,OSError):raise error('PRIVATE_STORAGE_UNAVAILABLE') from None
            elif artifact.state=='READY' and self.download_target in (None,artifact.artifact_id):
                self.verified_download(value,artifact.artifact_id)
