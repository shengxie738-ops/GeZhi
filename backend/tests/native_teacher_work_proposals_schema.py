"""Explicit-only owned MySQL proposal schema acceptance; no app/settings/AI."""
from dataclasses import replace
import json
from uuid import uuid4
import pytest
from sqlalchemy import text,event,insert,select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.sql.ddl import CreateTable
from tests.native_teacher_work_mysql import native_server,native_db,prepare,task_values,NOW
from app.models.teacher_work import WorkTask,WorkRun,OutlineSnapshot
from app.models.teacher_work_proposals import MaterialProposalRecord
from app.services.teacher_work.proposal_schema import PROPOSAL_TABLE,PROPOSAL_COMPONENT,PROPOSAL_CONTRACT_HASH,observe_teacher_work_proposals_mysql
from app.services.teacher_work.schema_mysql_v3 import observe_teacher_work_mysql_v3
from app.services.teacher_work.schema_v3 import TEACHER_WORK_CONTRACT_HASH as CORE_HASH
from migrations.v20261006_teacher_work_exports_mysql import apply_teacher_work_exports_mysql
from migrations.v20261006_teacher_work_proposals_mysql import apply_teacher_work_proposals_mysql,ProposalsMigrationError


@pytest.fixture
def core_db(native_db):
    prepare(native_db)
    with native_db.engine.connect() as c:assert apply_teacher_work_exports_mysql(c,native_db.identity).completed
    return native_db


def extension(db):
    with db.engine.connect() as c:return apply_teacher_work_proposals_mysql(c,db.identity)


def test_fresh_extension_preserves_core_and_independent_receipt(core_db):
    db=core_db
    print('FIRST_REAL_SQL_CONFIRMED',json.dumps(native_server_facts(db)),flush=True)
    with db.engine.connect() as c:
        core_before=dict(c.execute(text("SELECT * FROM teacher_work_schema_versions WHERE component='teacher_work'")).mappings().one())
    result=extension(db)
    assert result.completed and result.ledger_written and result.ledger_commit_state=='ACKNOWLEDGED'
    assert result.attempted_tables==result.confirmed_tables==(PROPOSAL_TABLE,)
    with db.engine.connect() as c:
        observed=observe_teacher_work_proposals_mysql(c)
        assert observed.ready,observed.issues
        assert observe_teacher_work_mysql_v3(c).ready
        core_after=dict(c.execute(text("SELECT * FROM teacher_work_schema_versions WHERE component='teacher_work'")).mappings().one())
        assert core_before==core_after and core_after['version']==3 and core_after['contract_hash']==CORE_HASH
        receipt=dict(c.execute(text('SELECT * FROM teacher_work_schema_versions WHERE component=:component'),{'component':PROPOSAL_COMPONENT}).mappings().one())
        assert receipt['version']==1 and receipt['contract_hash']==PROPOSAL_CONTRACT_HASH
        facts={family:[dict(r) for r in c.execute(text(statement)).mappings()] for family,statement in {
            'columns':"SELECT COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,COLUMN_DEFAULT,DATETIME_PRECISION,CHARACTER_SET_NAME,COLLATION_NAME FROM information_schema.columns WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='teacher_work_material_proposal_records'",
            'checks':"SELECT CONSTRAINT_NAME,CHECK_CLAUSE FROM information_schema.check_constraints WHERE CONSTRAINT_SCHEMA=DATABASE() AND CONSTRAINT_NAME LIKE 'ck_tw_proposal_%'",
            'indexes':"SELECT INDEX_NAME,COLUMN_NAME,SEQ_IN_INDEX,SUB_PART,NON_UNIQUE FROM information_schema.statistics WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='teacher_work_material_proposal_records' ORDER BY INDEX_NAME,SEQ_IN_INDEX",
        }.items()}
    (db.evidence/'proposal-schema.json').write_text(json.dumps({'core_before':core_before,'core_after':core_after,'receipt':receipt,'physical':facts},default=str,indent=2)+'\n')


def native_server_facts(db):return json.loads((db.evidence/'first-sql.json').read_text())


def test_exact_completed_replay_read_only(core_db):
    extension(core_db);statements=[]
    def record(c,cursor,statement,params,context,many):statements.append(statement)
    event.listen(core_db.engine,'before_cursor_execute',record)
    try:result=extension(core_db)
    finally:event.remove(core_db.engine,'before_cursor_execute',record)
    assert result.completed and result.ledger_written is False and result.attempted_tables==()
    assert statements and all(s.lstrip().upper().startswith(('SELECT','SHOW')) for s in statements)


@pytest.mark.parametrize('field',['schema_name','server_uuid','datadir','socket'])
def test_wrong_identity_refuses_before_ddl(core_db,field):
    wrong=replace(core_db.identity,**{field:getattr(core_db.identity,field)+'-wrong'})
    with core_db.engine.connect() as c:
        with pytest.raises(ProposalsMigrationError) as error:apply_teacher_work_proposals_mysql(c,wrong)
        assert error.value.attempted_tables==() and error.value.code=='teacher_work_identity_mismatch'


@pytest.mark.parametrize('setting',['foreign_key_checks','unique_checks'])
def test_disabled_session_checks_refuse(core_db,setting):
    with core_db.engine.connect() as c:
        c.execute(text(f'SET SESSION {setting}=0'));c.commit()
        with pytest.raises(ProposalsMigrationError) as error:apply_teacher_work_proposals_mysql(c,core_db.identity)
        assert error.value.attempted_tables==()


@pytest.mark.parametrize('persistent',[False,True])
@pytest.mark.parametrize('target',[PROPOSAL_TABLE,'teacher_work_schema_versions','teacher_work_tasks'])
def test_temporary_resolution_refuses(core_db,target,persistent):
    if persistent:extension(core_db)
    with core_db.engine.connect() as c:
        c.execute(text('CREATE TEMPORARY TABLE '+target+' (shadow INT)'));c.commit()
        with pytest.raises(ProposalsMigrationError) as error:apply_teacher_work_proposals_mysql(c,core_db.identity)
        assert error.value.attempted_tables==()


@pytest.mark.parametrize('defect',['unledgered','partial','wrong_receipt','unenforced_check'])
def test_existing_partial_or_unledgered_refused(core_db,defect):
    if defect in ('wrong_receipt','unenforced_check'):extension(core_db)
    with core_db.engine.begin() as c:
        if defect=='unledgered':c.execute(CreateTable(MaterialProposalRecord.__table__))
        elif defect=='partial':c.execute(text('CREATE TABLE '+PROPOSAL_TABLE+' (bad INT) ENGINE=InnoDB'))
        elif defect=='wrong_receipt':c.execute(text('UPDATE teacher_work_schema_versions SET version=2 WHERE component=:component'),{'component':PROPOSAL_COMPONENT})
        else:c.execute(text('ALTER TABLE '+PROPOSAL_TABLE+' ALTER CHECK ck_tw_proposal_record_identity NOT ENFORCED'))
    with core_db.engine.connect() as c:
        assert not observe_teacher_work_proposals_mysql(c).ready;c.rollback()
        with pytest.raises(ProposalsMigrationError) as error:apply_teacher_work_proposals_mysql(c,core_db.identity)
        assert error.value.attempted_tables==()


def test_core_v2_is_not_v3(native_db):
    prepare(native_db)
    with native_db.engine.connect() as c:
        with pytest.raises(ProposalsMigrationError) as error:apply_teacher_work_proposals_mysql(c,native_db.identity)
        assert error.value.code=='teacher_work_proposals_exact_v3_required' and not error.value.attempted_tables


def test_active_caller_transaction_preserved(core_db):
    with core_db.engine.connect() as c:
        tx=c.begin();c.execute(text('SELECT 1'))
        with pytest.raises(ProposalsMigrationError) as error:apply_teacher_work_proposals_mysql(c,core_db.identity)
        assert error.value.code=='teacher_work_fresh_connection_required' and c.get_transaction() is tx and tx.is_active


def seed(db):
    task=task_values();run=str(uuid4());outline=str(uuid4())
    with db.engine.begin() as c:
        c.execute(insert(WorkTask).values(**task))
        c.execute(insert(WorkRun).values(run_id=run,owner=task['owner_subject'],task_id=task['task_id'],kind='outline',skill_ref='lesson_outline@1',input_revision=1,idempotency_key=b'proposal',request_digest='a'*64,stage='PENDING',attempt=1,provider_call_count=0,deadline=NOW))
        c.execute(insert(OutlineSnapshot).values(outline_id=outline,task_id=task['task_id'],input_revision=1,outline_revision=1,lesson={},slides=[],source_digest='a'*64,outline_digest='b'*64,skill_versions=[],created_at=NOW))
    return dict(run_id=run,record_type='input',record_key=run,owner=task['owner_subject'],task_id=task['task_id'],payload={'unicode':'合成😀','array':[]},created_at=NOW,outline_id=None),outline


def test_native_typed_pk_checks_foreign_keys_unique_json_datetime(core_db):
    extension(core_db);row,outline=seed(core_db)
    second_run=str(uuid4())
    with core_db.engine.begin() as c:
        c.execute(insert(WorkRun).values(run_id=second_run,owner=row['owner'],task_id=row['task_id'],kind='outline',skill_ref='lesson_outline@1',input_revision=1,idempotency_key=b'proposal-second',request_digest='a'*64,stage='PENDING',attempt=1,provider_call_count=0,deadline=NOW))
        for values in (row,{**row,'record_type':'result'},{**row,'record_type':'lineage','record_key':outline,'outline_id':outline}):c.execute(insert(MaterialProposalRecord).values(**values))
    with core_db.engine.connect() as c:
        found=c.execute(select(MaterialProposalRecord.__table__)).mappings().all()
        assert len(found)==3 and all(r['payload']==row['payload'] and r['created_at']==NOW and r['created_at'].microsecond==123456 for r in found)
    invalid=[({**row,'record_type':'other'},3819),({**row,'record_key':str(uuid4())},3819),
        ({**row,'record_type':'result','outline_id':outline},3819),({**row,'record_type':'lineage'},3819),
        ({**row,'record_type':'lineage','record_key':str(uuid4()),'outline_id':outline},3819),
        ({**row,'run_id':str(uuid4()),'record_key':'same'},3819),
        ({**row,'run_id':second_run,'record_key':second_run,'task_id':str(uuid4()),'record_type':'result'},1452),
        ({**row,'run_id':second_run,'record_type':'lineage','record_key':outline,'outline_id':outline},1062),
        (row,1062)]
    for values,errno in invalid:
        with core_db.engine.connect() as c:
            with pytest.raises(DBAPIError) as error:c.execute(insert(MaterialProposalRecord).values(**values))
            assert error.value.orig.args[0]==errno
            c.rollback()


def test_failed_ddl_never_ledgers_or_resumes(core_db):
    def fail_after_create(c,cursor,statement,params,context,many):
        if statement.lstrip().upper().startswith('CREATE TABLE '+PROPOSAL_TABLE.upper()):raise RuntimeError('synthetic lost DDL acknowledgement')
    event.listen(core_db.engine,'after_cursor_execute',fail_after_create)
    try:
        with core_db.engine.connect() as c:
            with pytest.raises(ProposalsMigrationError) as error:apply_teacher_work_proposals_mysql(c,core_db.identity)
            assert error.value.attempted_tables==(PROPOSAL_TABLE,) and error.value.confirmed_tables==()
    finally:event.remove(core_db.engine,'after_cursor_execute',fail_after_create)
    with core_db.engine.connect() as c:
        report=observe_teacher_work_proposals_mysql(c)
        assert report.physical_valid and not report.ledger_present
    with core_db.engine.connect() as c:
        with pytest.raises(ProposalsMigrationError) as error:apply_teacher_work_proposals_mysql(c,core_db.identity)
        assert error.value.attempted_tables==()


def test_lost_actual_ledger_insert_acknowledgement_refuses_unledgered_target(core_db):
    db=core_db;executed=[]
    with db.engine.connect() as c:
        core_before=dict(c.execute(text("SELECT * FROM teacher_work_schema_versions WHERE component='teacher_work'")).mappings().one())
    def lost_insert(c,cursor,statement,params,context,many):
        if statement.lstrip().upper().startswith('INSERT INTO TEACHER_WORK_SCHEMA_VERSIONS'):
            executed.append(statement)
            raise RuntimeError('synthetic lost INSERT acknowledgement after actual SQL')
    event.listen(db.engine,'after_cursor_execute',lost_insert)
    try:
        with db.engine.connect() as c:
            with pytest.raises(ProposalsMigrationError) as error:apply_teacher_work_proposals_mysql(c,db.identity)
            result=error.value.report
            assert result.ledger_commit_state=='UNKNOWN' and result.ledger_written is None and result.completed is False
            assert result.confirmed_tables==(PROPOSAL_TABLE,)
    finally:event.remove(db.engine,'after_cursor_execute',lost_insert)
    assert len(executed)==1
    with db.engine.connect() as c:
        report=observe_teacher_work_proposals_mysql(c)
        core_after=dict(c.execute(text("SELECT * FROM teacher_work_schema_versions WHERE component='teacher_work'")).mappings().one())
        assert report.physical_valid and report.ledger_present is False and report.ready is False
        assert core_before==core_after
    with db.engine.connect() as c:
        with pytest.raises(ProposalsMigrationError) as replay:apply_teacher_work_proposals_mysql(c,db.identity)
        assert replay.value.attempted_tables==()
    (db.evidence/'proposal-lost-insert-ack.json').write_text(json.dumps({'actual_insert_statements':executed,
        'ledger_commit_state':result.ledger_commit_state,'ledger_written':result.ledger_written,'physical_target_retained':True,
        'independent_receipt_present':report.ledger_present,'fresh_apply_refused':True,'core_before':core_before,'core_after':core_after},default=str,indent=2)+'\n')


def test_lost_actual_commit_acknowledgement_observes_exact_receipt_read_only(core_db,monkeypatch):
    db=core_db;actual_commits=[]
    with db.engine.connect() as c:
        core_before=dict(c.execute(text("SELECT * FROM teacher_work_schema_versions WHERE component='teacher_work'")).mappings().one())
    with db.engine.connect() as c:
        real_commit=c.commit
        def lost_commit():
            real_commit()
            actual_commits.append('COMMIT returned before synthetic acknowledgement loss')
            raise RuntimeError('synthetic lost COMMIT acknowledgement after native commit')
        monkeypatch.setattr(c,'commit',lost_commit)
        with pytest.raises(ProposalsMigrationError) as error:apply_teacher_work_proposals_mysql(c,db.identity)
        result=error.value.report
        assert result.ledger_commit_state=='UNKNOWN' and result.ledger_written is None and result.completed is False
    assert len(actual_commits)==1
    with db.engine.connect() as c:
        report=observe_teacher_work_proposals_mysql(c)
        core_after=dict(c.execute(text("SELECT * FROM teacher_work_schema_versions WHERE component='teacher_work'")).mappings().one())
        receipt=dict(c.execute(text('SELECT * FROM teacher_work_schema_versions WHERE component=:component'),{'component':PROPOSAL_COMPONENT}).mappings().one())
        assert report.ready and core_before==core_after
    statements=[]
    def record(c,cursor,statement,params,context,many):statements.append(statement)
    event.listen(db.engine,'before_cursor_execute',record)
    try:replay=extension(db)
    finally:event.remove(db.engine,'before_cursor_execute',record)
    assert replay.completed and replay.ledger_written is False and replay.attempted_tables==()
    assert statements and all(statement.lstrip().upper().startswith(('SELECT','SHOW')) for statement in statements)
    (db.evidence/'proposal-lost-commit-ack.json').write_text(json.dumps({'actual_commits':actual_commits,
        'ledger_commit_state':result.ledger_commit_state,'ledger_written':result.ledger_written,'independent_receipt':receipt,
        'exact_replay_read_only':True,'core_before':core_before,'core_after':core_after},default=str,indent=2)+'\n')
