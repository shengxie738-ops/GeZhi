"""Fresh-only proposal v1 addition to exact physically verified core v3.

No app startup, engine, DDL rollback or partial-schema recovery is provided.
The independent component receipt is inserted only after exact physical checks.
"""
from dataclasses import dataclass
from datetime import datetime,timezone
from sqlalchemy import text
from sqlalchemy.sql.ddl import CreateTable
from app.services.teacher_work.proposal_schema import (
    PROPOSAL_COMPONENT,PROPOSAL_CONTRACT_HASH,PROPOSAL_SCHEMA_CONTRACT,PROPOSAL_TABLE,
    observe_teacher_work_proposals_mysql,proposal_mysql_tables,
)
from app.services.teacher_work.schema_mysql_v3 import observe_teacher_work_mysql_v3
from app.services.teacher_work.types import canonical_digest
from migrations.v20261005_teacher_work_mysql import _identity,_fresh_connection,MysqlMigrationError


@dataclass(frozen=True)
class ProposalsMigrationReport:
    identity:object
    contract_hash:str
    attempted_tables:tuple[str,...]
    confirmed_tables:tuple[str,...]
    completed:bool
    ledger_written:bool|None
    ledger_commit_state:str


class ProposalsMigrationError(RuntimeError):
    def __init__(self,code,report):
        self.code,self.report=code,report
        self.attempted_tables,self.confirmed_tables=report.attempted_tables,report.confirmed_tables
        self.ledger_commit_state=report.ledger_commit_state
        super().__init__(code)


def apply_teacher_work_proposals_mysql(connection,expected_identity,*,contract_hash=PROPOSAL_CONTRACT_HASH):
    attempted=[];confirmed=[];ledger='NOT_ATTEMPTED';written=False
    def report(completed=False):
        return ProposalsMigrationReport(expected_identity,PROPOSAL_CONTRACT_HASH,tuple(attempted),tuple(confirmed),completed,written,ledger)
    def fail(code):raise ProposalsMigrationError(code,report())
    try:
        if contract_hash!=PROPOSAL_CONTRACT_HASH or canonical_digest(PROPOSAL_SCHEMA_CONTRACT)!=PROPOSAL_CONTRACT_HASH:
            fail('teacher_work_proposals_contract_hash_mismatch')
        _fresh_connection(connection);_identity(connection,expected_identity)
        if not observe_teacher_work_mysql_v3(connection).ready:
            fail('teacher_work_proposals_exact_v3_required')
        initial=observe_teacher_work_proposals_mysql(connection)
        if initial.ready:return report(True)
        if initial.issues or initial.missing_tables!=(PROPOSAL_TABLE,) or initial.ledger_present:
            fail('teacher_work_proposals_existing_target_refused')
        tables=proposal_mysql_tables()
        if tuple(table.name for table in tables)!=(PROPOSAL_TABLE,):fail('teacher_work_proposals_allowlist_changed')
        for table in tables:
            _identity(connection,expected_identity)
            # Re-observe immediately before irreversible DDL; temporary shadows
            # and changed session enforcement remain refusals.
            before=observe_teacher_work_proposals_mysql(connection)
            if before.issues or before.missing_tables!=(PROPOSAL_TABLE,) or before.ledger_present:
                fail('teacher_work_proposals_existing_target_refused')
            attempted.append(table.name)
            connection.execute(CreateTable(table))
            confirmed.append(table.name)
        _identity(connection,expected_identity)
        physical=observe_teacher_work_proposals_mysql(connection)
        if not physical.physical_valid or physical.ledger_present:
            fail('teacher_work_proposals_physical_verification_failed')
        if not observe_teacher_work_mysql_v3(connection).ready:fail('teacher_work_proposals_core_changed')
        ledger='UNKNOWN';written=None
        connection.execute(text('INSERT INTO teacher_work_schema_versions (component,version,contract_hash,completed_at) VALUES (:component,1,:contract_hash,:completed_at)'),
            {'component':PROPOSAL_COMPONENT,'contract_hash':PROPOSAL_CONTRACT_HASH,'completed_at':datetime.now(timezone.utc).replace(tzinfo=None)})
        connection.commit();ledger='ACKNOWLEDGED';written=True
        if not observe_teacher_work_proposals_mysql(connection).ready:fail('teacher_work_proposals_completion_unverified')
        return report(True)
    except ProposalsMigrationError:raise
    except MysqlMigrationError as exc:
        raise ProposalsMigrationError(exc.code,report()) from None
    except Exception:
        raise ProposalsMigrationError('teacher_work_proposals_prepare_failed',report()) from None
