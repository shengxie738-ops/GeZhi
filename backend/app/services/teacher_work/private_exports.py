"""Synchronous bounded private Office requests; no background execution service."""
import json
from pathlib import Path
import re
import os
from threading import Lock
from uuid import UUID,uuid4
from app.schemas.teacher_work import BODY_LIMIT
from app.schemas.teacher_work_exports import PrivatePackageCapabilities
from app.repositories.teacher_work import WorkRepositoryError
from app.services.teacher_work.authorization import WorkAuthorizationError
from app.services.teacher_work.private_storage import LocalPrivateStorage

_process_id=os.getpid()
_process_instance=uuid4()
_executions={}
_execution_lock=Lock()


def process_instance():
    global _process_id,_process_instance,_executions
    with _execution_lock:
        if os.getpid()!=_process_id:
            _process_id=os.getpid();_process_instance=uuid4();_executions={}
        return _process_instance


def execution_evidence(fence,active):
    with _execution_lock:
        _executions[fence]=active
        # Dropping old stopped evidence merely defers recovery to expiry.
        for old in tuple(_executions):
            if len(_executions)<=128:break
            if _executions[old] is False:del _executions[old]


def stopped_fences():
    process_instance()
    with _execution_lock:return frozenset(f for f,active in _executions.items() if active is False)


def configured_storage():
    from app.core.config import settings
    root=settings.TEACHER_WORK_STORAGE_ROOT
    if type(root) is not str or not root or not Path(root).is_absolute():raise WorkAuthorizationError('PRIVATE_STORAGE_UNAVAILABLE',503)
    backend=Path(__file__).resolve().parents[3]
    static=(backend/'app/static',backend.parent/'frontend',Path(settings.COURSEWARE_FRONTEND_ROOT))
    try:return LocalPrivateStorage(root,static_roots=static)
    except (ValueError,OSError):raise WorkAuthorizationError('PRIVATE_STORAGE_UNAVAILABLE',503) from None


def package_capabilities(connection):
    from app.core.config import settings
    from app.services.teacher_work.schema_mysql_v3 import observe_teacher_work_mysql_v3
    from app.services.teacher_work.material_sources import source_configured
    enabled=settings.TEACHER_WORK_PRIVATE_EXPORTS_ENABLED is True
    storage=False
    if enabled:
        try:configured_storage();storage=True
        except WorkAuthorizationError:pass
    schema=enabled and observe_teacher_work_mysql_v3(connection).ready
    read=enabled and schema and storage
    create=read and settings.TEACHER_WORK_PRIVATE_MATERIALS_ENABLED is True and source_configured()
    flags={'create':create,'read':read,'retry':create,'download':read,'storage_configured':storage}
    reason='private_exports_disabled' if not enabled else 'package_schema_unavailable' if not schema else 'private_storage_unavailable' if not storage else 'materials_unavailable'
    reasons={k:reason for k,v in flags.items() if not v}
    if not storage:reasons['storage_configured']='private_exports_disabled' if not enabled else 'private_storage_unavailable'
    return PrivatePackageCapabilities(**flags,reasons=reasons)


def bounded_package(value):
    data=value.public_data()
    raw=json.dumps({'code':200,'message':'ok','data':data},ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8')
    if len(raw)>BODY_LIMIT:raise WorkRepositoryError('PACKAGE_RESPONSE_TOO_LARGE',503)
    return data


class PrivateExportRequests:
    def __init__(self,authorization,request_factory,dependencies_factory,clock):
        self.authorization,self.request_factory,self.dependencies_factory,self.clock=authorization,request_factory,dependencies_factory,clock

    def transaction(self,operation,work,*,current=False):
        mode='read' if operation=='private_package_read' else 'write'
        with self.request_factory(self.authorization,mode=mode,operation=operation) as session:
            binding=self.dependencies_factory(session,authorization=self.authorization,mode=mode,operation=operation,clock=self.clock,new_uuid=uuid4)
            value,token=work(binding)
            bounded_package(value) # Prepare exact public envelope before commit.
            if token is not None and operation in ('private_package_create','private_package_retry'):execution_evidence(token,True)
            try:
                saved=binding.finish_package_outcome(value,current=(current and token is not None) or binding.packages.completed_in_root,
                    fence=token if token is not None and value.run.stage=='FILES_RUNNING' else None)
            except BaseException:
                if token is not None and operation in ('private_package_create','private_package_retry'):execution_evidence(token,False)
                raise
            return saved,token

    def create(self,task_id,request,key):
        value,fence=self.transaction('private_package_create',lambda b:b.packages.create(b.subject,task_id,request,key,process_instance(),stopped_fences()),current=True)
        return self.execute(value,fence) if fence else value

    def retry(self,task_id,run_id):
        value,fence=self.transaction('private_package_retry',lambda b:b.packages.retry(b.subject,task_id,run_id,process_instance(),stopped_fences()),current=True)
        return self.execute(value,fence) if fence else value

    def get(self,task_id,version_id):
        return self.transaction('private_package_read',lambda b:(b.packages.get(b.subject,task_id,version_id),None))[0]

    def list(self,task_id,limit=20,before=None):
        return self.transaction('private_package_read',lambda b:(b.packages.list(b.subject,task_id,limit=limit,before=before),None))[0]

    def execute(self,value,fence):
        from app.services.teacher_work.office_execution import OfficeTerminationUnknown
        stopped=True
        try:return self._execute(value,fence)
        except OfficeTerminationUnknown:
            stopped=False
            raise
        finally:execution_evidence(fence,not stopped)

    def _execute(self,value,fence):
        from app.services.teacher_work.office_execution import build_validated_office
        task_id,version_id=value.task.task_id,value.version.version_id
        receipt=value.receipt
        for artifact in value.artifacts:
            if artifact.state=='READY':continue
            remaining=(value.run.deadline-self.clock()).total_seconds()
            if remaining<=0:break
            raw=verdict=None;failure=None
            try:raw,verdict=build_validated_office(artifact.kind,value.version,timeout_seconds=min(30,remaining))
            except ValueError as exc:
                failure=str(exc) if re.fullmatch(r'[A-Z][A-Z0-9_]{0,63}',str(exc)) else 'OFFICE_EXECUTION_FAILED'
            try:
                value,_=self.transaction('private_package_file',lambda b:(b.packages.record_file(b.subject,task_id,version_id,fence,artifact.kind,
                    raw=raw,verdict=verdict,failure=failure),fence),current=True)
            except WorkRepositoryError as exc:
                if exc.code not in ('SOURCE_CHANGED','OUTLINE_APPROVAL_CONFLICT','NORMALIZATION_REQUIRED','PACKAGE_DEADLINE_EXPIRED','PRIVATE_STORAGE_UNAVAILABLE'):raise
                # The bounded child has returned/stopped, and this file root did
                # not attempt commit. Retain every path claim and any candidate;
                # terminalize under a fresh exact fence without deleting bytes.
                self.transaction('private_package_file',lambda b:(b.packages.finish(b.subject,task_id,version_id,fence,failure=exc.code),None))
                raise
        try:
            value,_=self.transaction('private_package_file',lambda b:(b.packages.finish(b.subject,task_id,version_id,fence),None),current=True)
        except WorkRepositoryError as exc:
            if exc.code not in ('SOURCE_CHANGED','OUTLINE_APPROVAL_CONFLICT','NORMALIZATION_REQUIRED','PACKAGE_DEADLINE_EXPIRED'):raise
            self.transaction('private_package_file',lambda b:(b.packages.finish(b.subject,task_id,version_id,fence,failure=exc.code),None))
            raise
        return value.model_copy(update={'receipt':receipt})

    def download(self,task_id,artifact_id):
        from sqlalchemy import select
        from app.models.teacher_work import Artifact,WorkTask
        from app.models.teacher_work_v3 import PackageVersion
        result=None
        def read(binding):
            nonlocal result
            # Discover only within the actor/task; do not reveal foreign UUIDs.
            found=binding.packages._read(select(PackageVersion).join(Artifact,Artifact.version_id==PackageVersion.version_id)
                .join(WorkTask,WorkTask.task_id==PackageVersion.task_id).where(WorkTask.owner_subject==binding.subject,
                    WorkTask.task_id==str(task_id),Artifact.artifact_id==str(artifact_id)).limit(2))
            if len(found)!=1:raise WorkRepositoryError('NOT_FOUND',404)
            value=binding.packages.get(binding.subject,task_id,UUID(found[0].version_id))
            result=binding.packages.verified_download(value,artifact_id)
            binding.packages.download_target=artifact_id
            return value,None
        self.transaction('private_package_read',read)
        return result
