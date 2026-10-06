"""Reviewed additive v3 shape. Original v2 definitions and hash remain pinned."""
from copy import deepcopy
from app.services.teacher_work.schema import (
    TEACHER_WORK_SCHEMA_CONTRACT as V2_CONTRACT, inspect_teacher_work_schema_contract,
)
from app.services.teacher_work.types import canonical_digest

TEACHER_WORK_SCHEMA_VERSION=3
TEACHER_WORK_SCHEMA_CONTRACT=deepcopy(V2_CONTRACT)
TEACHER_WORK_SCHEMA_CONTRACT['version']=3
tables=TEACHER_WORK_SCHEMA_CONTRACT['tables']
tables['teacher_work_outline_approvals']['unique']+=(('approval_id','task_id'),)
tables['teacher_work_package_versions']['columns']['approval_id']={'type':'varchar(36)','nullable':True}
tables['teacher_work_package_versions']['composite_foreign_keys']={
    'fk_tw_version_approval_task':{'columns':('approval_id','task_id'),'target_table':'teacher_work_outline_approvals','target_columns':('approval_id','task_id')},
}
MANUAL_CHECK="model_id <> 'manual-approved@1' OR (approval_id IS NOT NULL AND (JSON_LENGTH(source_snapshots) = 0) AND (JSON_LENGTH(skill_versions) = 0))"
PACKAGE_CHECK="kind <> 'package' OR (provider_call_count = 0 AND repair_count = 0 AND active_call_no IS NULL AND active_call_attempt IS NULL AND active_call_lease_revision IS NULL AND active_call_process_instance IS NULL AND stage IN ('PENDING','CONTENT_VALIDATED','FILES_RUNNING','PACKAGE_READY','COMPLETE','FAILED','CANCELLED','INTERRUPTED'))"
READY_CHECK="state <> 'READY' OR (storage_key IS NOT NULL AND byte_size > 0 AND sha256 IS NOT NULL AND validation_summary IS NOT NULL AND (0 <> COALESCE(((JSON_TYPE(JSON_EXTRACT(validation_summary,'$.valid')) = 'BOOLEAN') AND (JSON_UNQUOTE(JSON_EXTRACT(validation_summary,'$.valid')) = 'true')), FALSE)) AND error_code IS NULL)"
tables['teacher_work_package_versions']['checks']['ck_tw_version_manual_binding']=MANUAL_CHECK
tables['teacher_work_runs']['checks']['ck_tw_run_manual_package']=PACKAGE_CHECK
tables['teacher_work_artifacts']['checks']['ck_tw_artifact_ready']=READY_CHECK
TEACHER_WORK_CONTRACT_HASH=canonical_digest(TEACHER_WORK_SCHEMA_CONTRACT)


def inspect_teacher_work_schema_v3(observation):
    return inspect_teacher_work_schema_contract(observation,TEACHER_WORK_SCHEMA_CONTRACT,TEACHER_WORK_CONTRACT_HASH,3)
