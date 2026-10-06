"""Explicit exact-v2→v3 only. No automatic startup, DDL rollback or resume."""
from dataclasses import dataclass
from datetime import datetime,timezone
from sqlalchemy import text
from app.services.teacher_work.schema import TEACHER_WORK_CONTRACT_HASH as V2_HASH
from app.services.teacher_work.schema_v3 import TEACHER_WORK_CONTRACT_HASH,MANUAL_CHECK,PACKAGE_CHECK,READY_CHECK
from app.services.teacher_work.schema_mysql import observe_teacher_work_mysql
from app.services.teacher_work.schema_mysql_v3 import observe_teacher_work_mysql_v3
from migrations.v20261005_teacher_work_mysql import _identity,_fresh_connection,MysqlMigrationError


@dataclass(frozen=True)
class ExportsMigrationReport:
    identity: object
    attempted_steps: tuple[str,...]
    confirmed_steps: tuple[str,...]
    completed: bool
    ledger_commit_state: str


class ExportsMigrationError(RuntimeError):
    def __init__(self,code,report):
        self.code,self.report=code,report
        super().__init__(code)


def apply_teacher_work_exports_mysql(connection,expected_identity):
    attempted=[];confirmed=[];ledger='NOT_ATTEMPTED'
    def report(completed=False):
        return ExportsMigrationReport(expected_identity,tuple(attempted),tuple(confirmed),completed,ledger)
    try:
        _fresh_connection(connection);_identity(connection,expected_identity)
        if observe_teacher_work_mysql_v3(connection).ready:return report(True)
        if not observe_teacher_work_mysql(connection).ready:
            raise ExportsMigrationError('teacher_work_exports_exact_v2_required',report())
        # Validate all existing data before the first irreversible DDL.
        for table,condition in (('teacher_work_runs',PACKAGE_CHECK),('teacher_work_artifacts',READY_CHECK)):
            if connection.scalar(text(f'SELECT COUNT(*) FROM {table} WHERE NOT ({condition})')):
                raise ExportsMigrationError('teacher_work_exports_existing_data_incompatible',report())
        if connection.scalar(text("SELECT COUNT(*) FROM teacher_work_package_versions WHERE model_id='manual-approved@1'")):
            raise ExportsMigrationError('teacher_work_exports_unbound_manual_rows',report())
        steps=(
            ('approval_reference','ALTER TABLE teacher_work_outline_approvals ADD CONSTRAINT uq_tw_approval_id_task UNIQUE (approval_id,task_id)'),
            ('immutable_binding',"ALTER TABLE teacher_work_package_versions ADD COLUMN approval_id VARCHAR(36) NULL, ADD CONSTRAINT fk_tw_version_approval_task FOREIGN KEY (approval_id,task_id) REFERENCES teacher_work_outline_approvals (approval_id,task_id), ADD CONSTRAINT ck_tw_version_manual_binding CHECK ("+MANUAL_CHECK+')'),
            ('manual_run','ALTER TABLE teacher_work_runs ADD CONSTRAINT ck_tw_run_manual_package CHECK ('+PACKAGE_CHECK+')'),
            ('ready_files','ALTER TABLE teacher_work_artifacts ADD CONSTRAINT ck_tw_artifact_ready CHECK ('+READY_CHECK+')'),
        )
        for name,statement in steps:
            _identity(connection,expected_identity)
            attempted.append(name);connection.execute(text(statement));confirmed.append(name)
        _identity(connection,expected_identity)
        if not observe_teacher_work_mysql_v3(connection).physical_valid:
            raise ExportsMigrationError('teacher_work_exports_physical_verification_failed',report())
        ledger='UNKNOWN'
        result=connection.execute(text('UPDATE teacher_work_schema_versions SET version=3,contract_hash=:new_hash,completed_at=:at WHERE component=\'teacher_work\' AND version=2 AND contract_hash=:old_hash'),
            {'new_hash':TEACHER_WORK_CONTRACT_HASH,'old_hash':V2_HASH,'at':datetime.now(timezone.utc).replace(tzinfo=None)})
        if result.rowcount!=1:raise ExportsMigrationError('teacher_work_exports_ledger_conflict',report())
        connection.commit();ledger='CONFIRMED'
        if not observe_teacher_work_mysql_v3(connection).ready:
            raise ExportsMigrationError('teacher_work_exports_completion_unverified',report())
        return report(True)
    except ExportsMigrationError:raise
    except MysqlMigrationError as exc:
        raise ExportsMigrationError(exc.code,report()) from None
    except Exception:
        # No DROP/ALTER reversal and no claim that DDL was rolled back.
        raise ExportsMigrationError('teacher_work_exports_prepare_failed',report()) from None
