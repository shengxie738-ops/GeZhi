"""Explicit-only signed current identity/native SQL proposal and origin acceptance.

Existing owned fixture; blank cwd/synthetic sources; no provider or app.main.
The selected assistant reply is committed through the official chat repository.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime,timezone,timedelta
import json
from uuid import UUID,uuid4
import pytest
from sqlalchemy import select,text,event,update,insert
from app.models.teacher_work import WorkRun,WorkMessage,OutlineSnapshot,OwnerRunLease,WorkTask
from app.models.teacher_work_proposals import MaterialProposalRecord
from app.schemas.teacher_work import ChatCommand,ChatResult
from app.schemas.teacher_work_proposals import ProposalCommand
from app.services.teacher_work.proposals import parse_material_proposal
from app.services.teacher_work.proposal_persistence import PreparedProposal,public_run
from tests.native_teacher_work_mysql import native_server,native_db
from tests.native_teacher_work_private_http import http_db,create,create_body,OWNER,OTHER,request as http_request,db_rows
from tests.native_teacher_work_private_materials import material_db,request,approval_body
from tests.test_teacher_work_private_materials import lesson,slides
from migrations.v20261006_teacher_work_exports_mysql import apply_teacher_work_exports_mysql
from migrations.v20261006_teacher_work_proposals_mysql import apply_teacher_work_proposals_mysql


def now():return datetime.now(timezone.utc)


@pytest.fixture
def proposal_db(material_db,monkeypatch):
    db=material_db
    monkeypatch.setattr(db.settings,'TEACHER_WORK_PRIVATE_CHAT_ENABLED',True)
    monkeypatch.setattr(db.settings,'TEACHER_WORK_PRIVATE_MATERIAL_PROPOSALS_ENABLED',True)
    with db.engine.connect() as c:assert apply_teacher_work_exports_mysql(c,db.identity).completed
    with db.engine.connect() as c:assert apply_teacher_work_proposals_mysql(c,db.identity).completed
    print('FIRST_REAL_SQL_CONFIRMED',json.dumps(vars(db.identity)),flush=True)
    return db


@contextmanager
def binding(db,mode='write',operation=None,owner=OWNER,clock=now):
    from app.services.teacher_work.bootstrap import build_request_dependencies
    from app.services.teaching.sessions import open_teaching_session
    operation=operation or ('private_proposal_read' if mode=='read' else 'private_proposal_write')
    with open_teaching_session(db.engine) as session:
        yield build_request_dependencies(session,authorization='Bearer '+db.tokens[owner],mode=mode,
            operation=operation,clock=clock,new_uuid=uuid4)


def op(db,name,*args,mode='write',owner=OWNER,**kwargs):
    with binding(db,mode,owner=owner) as b:
        value=getattr(b.proposals,name)(owner,*args,**kwargs)
        return b.finish_proposal_outcome(value,mode=mode)


def seed_chat(db,task_id):
    process=uuid4()
    command=ChatCommand.model_validate_json(json.dumps(dict(kind='chat',skill_ref=None,input_revision=1,
        payload=dict(text='Synthetic saved chat request',client_message_key='chat-message'))))
    with binding(db,operation='private_chat_write') as b:
        admission=b.repository.admit_chat(OWNER,task_id,command,'synthetic-chat',process_instance=process,configured_timeout_seconds=90)
        admission=b.finish_chat_outcome(admission,mode='write')
    with binding(db,operation='private_chat_write') as b:
        call=b.repository.reserve_chat_call(OWNER,task_id,admission.state.run.run_id,process_instance=process,
            configured_output_tokens=8192,configured_timeout_seconds=90)
        call=b.finish_chat_outcome(call,mode='write')
    with binding(db,operation='private_chat_write') as b:
        result=ChatResult(type='answer',plain_text='Synthetic classified persisted reply',result_refs=(),omitted_context=False)
        complete=b.repository.complete_chat_call(call.context,call.token,result,allowed_result_refs=frozenset(),omitted_context=False)
        return b.finish_chat_outcome(complete,mode='write').completion.message_id


def setup(db):
    task=create(db,body=create_body(resource_ids=[db.resource_id]))
    task_id=UUID(task['task_id'])
    message_id=seed_chat(db,task_id)
    command=ProposalCommand(skill_ref='lesson_outline@1',input_revision=1,expected_revision=1,source_message_id=message_id)
    return task_id,command,uuid4()


def admit(db,task_id,command,process,key='proposal'):
    return op(db,'admit',task_id,command,key,process_instance=process,configured_timeout_seconds=90)


def reserve(db,task_id,run_id,process):
    return op(db,'reserve',task_id,run_id,process_instance=process,configured_output_tokens=8192,configured_timeout_seconds=90)


def prepared(call,body=None):
    proposal=parse_material_proposal(json.dumps(body or dict(lesson=lesson(),slides=slides())),
        frozen=call.state.frozen,created_at=now())
    return PreparedProposal(call.context,call.token,call.state.frozen,proposal)


def complete(db,p):
    with binding(db) as b:
        value=b.proposals.complete(p)
        return b.finish_proposal_outcome(value,mode='write')


def completed(db):
    task_id,c,process=setup(db)
    a=admit(db,task_id,c,process)
    call=reserve(db,task_id,a.state.run.run_id,process)
    return task_id,c,complete(db,prepared(call))


def immutable_rows(db):
    with db.engine.connect() as c:
        connection_id=c.scalar(text("SELECT CONNECTION_ID()"))
        rows=tuple([dict(r) for r in c.execute(select(model.__table__)).mappings()] for model in
            (MaterialProposalRecord,OutlineSnapshot,WorkRun,OwnerRunLease))
        db.row_observations.append({'fresh_connection_id':connection_id,'proposal_immutable_run_lease_rows':rows})
        return rows


def test_admit_exact_replay_reserve_once_cancel_readonly_reopen(proposal_db):
    db=proposal_db;task_id,c,process=setup(db)
    before=db_rows(db)
    assert op(db,'list_runs',task_id,mode='read').runs.runs==()
    assert op(db,'inspect',task_id,c,'proposal',mode='read').admission is None
    a=admit(db,task_id,c,process);run_id=a.state.run.run_id
    assert a.created and a.state.run.deadline-now()<=timedelta(seconds=90)
    assert db_rows(db)[:2]==before[:2]
    replay=admit(db,task_id,c,process)
    assert not replay.created and replay.state==a.state
    with pytest.raises(Exception) as error:admit(db,task_id,c.model_copy(update={'expected_revision':2}),process)
    assert error.value.code=='IDEMPOTENCY_CONFLICT'
    assert op(db,'list_runs',task_id,mode='read').runs.runs==(public_run(a),)
    call=reserve(db,task_id,run_id,process)
    with pytest.raises(Exception):reserve(db,task_id,run_id,process)
    cancelled=op(db,'cancel',task_id,run_id)
    assert cancelled.state.run.stage=='CANCELLED' and cancelled.state.active_call==call.token and cancelled.lease.active_run_id==run_id
    sql=[]
    def trace(conn,cursor,statement,params,ctx,many):sql.append(statement)
    event.listen(db.engine,'before_cursor_execute',trace)
    try:
        opened=op(db,'list_runs',task_id,mode='read')
        read=op(db,'read_proposal',task_id,run_id,mode='read')
    finally:event.remove(db.engine,'before_cursor_execute',trace)
    assert read.read.proposal is None and read.read.freshness.reason=='PROPOSAL_NOT_READY'
    assert all(s.lstrip().upper().startswith(('SELECT','SHOW')) or s.strip().upper()=='DO 0' for s in sql)
    with binding(db) as b:
        settled=b.proposals.fail(call.context,call.token,'WORK_AI_TIMEOUT')
        settled=b.finish_proposal_outcome(settled,mode='write')
    assert settled.state.run.stage=='CANCELLED' and settled.state.active_call is None and settled.lease.active_run_id is None
    db.row_observations.append({'proposal_readonly_sql':sql,'reopen_cancelled':opened.runs.model_dump(mode='json')})


@pytest.mark.parametrize('case',['missing','foreign','unclassified','stale'])
def test_selected_owned_completion_required(proposal_db,case):
    db=proposal_db;task_id,c,process=setup(db)
    if case=='missing':c=c.model_copy(update={'source_message_id':uuid4()})
    if case=='foreign':
        other=create(db,owner=OTHER,body=create_body(resource_ids=[db.resource_id]),key='other-task')
        task_id=UUID(other['task_id'])
        with pytest.raises(Exception) as error:admit(db,task_id,c,process)
        assert error.value.code=='NOT_FOUND';return
    if case=='unclassified':
        with db.engine.begin() as conn:conn.execute(update(WorkMessage).where(WorkMessage.message_id==str(c.source_message_id)).values(result_type=None,omitted_context=None,completion_run_id=None))
    if case=='stale':c=c.model_copy(update={'input_revision':2})
    before=immutable_rows(db)
    with pytest.raises(Exception) as error:admit(db,task_id,c,process)
    assert error.value.code==('NOT_FOUND' if case=='missing' else 'STALE_INPUT_REVISION' if case=='stale' else 'SOURCE_MESSAGE_INELIGIBLE')
    assert immutable_rows(db)==before


def save_body(result):
    return dict(expected_revision=1,input_revision=1,expected_outline_revision=0,origin_proposal_run_id=str(result.state.run.run_id),
        lesson={**lesson(),'summary':'Teacher edited candidate'},slides=slides(9))


def test_complete_edited_manual_save_approve_and_historical_origin_replay(proposal_db):
    db=proposal_db;task_id,c,result=completed(db)
    read=op(db,'read_proposal',task_id,result.state.run.run_id,mode='read')
    assert read.read.freshness.adoptable and db_rows(db)[0][0]['input_revision']==1
    path=f'/api/teacher/work/tasks/{task_id}/materials';body=save_body(result)
    response=request(db,'POST',path,key='edited-adoption',body=body)
    assert response.status_code==200,response.text
    state=response.json()['data'];assert state['input_revision']==2 and state['outline']['skill_versions']==[] and len(state['outline']['slides'])==9
    rows=immutable_rows(db);assert [r['record_type'] for r in rows[0]].count('lineage')==1
    replay=request(db,'POST',path,key='edited-adoption',body=body)
    assert replay.status_code==200,replay.text
    assert replay.json()['data']['receipt']=={**state['receipt'],'replayed':True} and immutable_rows(db)==rows
    approved=request(db,'POST',path+'/approve',key='manual-approval',body=approval_body(state))
    assert approved.status_code==200 and approved.json()['data']['approval_current']
    patch=http_request(db,'PATCH',f'/api/teacher/work/tasks/{task_id}/working',body=dict(expected_revision=3,changes=dict(requirements='later requirements')))
    assert patch.status_code==200,patch.text
    db.source_file.write_bytes(b'synthetic-source-version-B')
    after=immutable_rows(db)
    replay=request(db,'POST',path,key='edited-adoption',body=body)
    assert replay.status_code==200,replay.text
    assert replay.json()['data']['receipt']=={**state['receipt'],'replayed':True} and immutable_rows(db)==after
    fresh=op(db,'read_proposal',task_id,result.state.run.run_id,mode='read')
    assert not fresh.read.freshness.adoptable and fresh.read.proposal==result.proposal
    changed=request(db,'POST',path,key='new-stale-origin',body={**body,'expected_revision':4,'input_revision':3,'expected_outline_revision':1})
    assert changed.status_code==409 and changed.json()['message']=='STALE_INPUT_REVISION'


def test_completed_source_change_viewable_new_adoption_rejected(proposal_db):
    db=proposal_db;task_id,_,result=completed(db)
    db.source_file.write_bytes(b'changed source bytes')
    assert op(db,'read_proposal',task_id,result.state.run.run_id,mode='read').read.freshness.reason=='SOURCE_CHANGED'
    response=request(db,'POST',f'/api/teacher/work/tasks/{task_id}/materials',key='changed-origin',body=save_body(result))
    assert response.status_code==409 and response.json()['message']=='SOURCE_CHANGED'


def test_actual_lineage_trigger_failure_rolls_back_entire_save(proposal_db):
    db=proposal_db;task_id,_,result=completed(db)
    before=db_rows(db),immutable_rows(db)
    with db.engine.begin() as c:c.execute(text("CREATE TRIGGER native_proposal_lineage_fail BEFORE INSERT ON teacher_work_material_proposal_records FOR EACH ROW BEGIN IF NEW.record_type='lineage' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='synthetic lineage failure'; END IF; END"))
    response=request(db,'POST',f'/api/teacher/work/tasks/{task_id}/materials',key='rollback-origin',body=save_body(result))
    assert response.status_code==503 and (db_rows(db),immutable_rows(db))==before


@pytest.mark.parametrize('ack',['before','after'])
def test_unknown_actual_save_commit_preserves_exact_receipt_lineage(proposal_db,monkeypatch,ack):
    import pymysql
    db=proposal_db;task_id,_,result=completed(db)
    target={};original=pymysql.connections.Connection.commit
    def trace(conn,cursor,statement,params,ctx,many):
        if statement.lstrip().upper().startswith('INSERT INTO TEACHER_WORK_OUTLINE_SNAPSHOTS'):target['connection']=conn.connection.driver_connection
    def lose(connection):
        if connection is target.get('connection'):
            if ack=='after':original(connection);target['committed']=True
            raise pymysql.OperationalError(2013,'synthetic unknown save commit')
        return original(connection)
    event.listen(db.engine,'before_cursor_execute',trace)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(pymysql.connections.Connection,'commit',lose)
            response=request(db,'POST',f'/api/teacher/work/tasks/{task_id}/materials',key='unknown-origin',body=save_body(result))
    finally:event.remove(db.engine,'before_cursor_execute',trace)
    assert response.status_code==503 and response.json()['message']=='COMMIT_OUTCOME_UNKNOWN'
    before=immutable_rows(db)
    observed=request(db,'GET',f'/api/teacher/work/tasks/{task_id}/materials')
    assert observed.status_code==200
    if ack=='after':
        assert target['committed'] and observed.json()['data']['outline'] is not None
        replay=request(db,'POST',f'/api/teacher/work/tasks/{task_id}/materials',key='unknown-origin',body=save_body(result))
        assert replay.status_code==200 and replay.json()['data']['receipt']['replayed'] and immutable_rows(db)==before
    else:
        assert observed.json()['data']['outline'] is None and not any(r['record_type']=='lineage' for r in before[0])
    db.row_observations.append({'actual_save_commit_ack':ack,'unknown_status':response.json(),'fresh_observation':observed.json()})


def test_large_typed_candidate_fails_original_text_boundary_without_material_writes(proposal_db):
    db=proposal_db;task_id,c,process=setup(db);a=admit(db,task_id,c,process);call=reserve(db,task_id,a.state.run.run_id,process)
    data=dict(lesson={**lesson(),'objectives':['x'*2000]*20,'key_points':['y'*2000]*20},slides=slides())
    p=prepared(call,data);assert len(p.proposal.model_dump_json().encode())<131072
    value=complete(db,p)
    assert value.state.run.stage=='FAILED' and value.state.run.error_code=='PROPOSAL_DRAFT_TOO_LARGE'
    assert value.state.active_call is None and value.lease.active_run_id is None
    rows=immutable_rows(db)
    assert not rows[1] and not any(r['record_type']=='result' for r in rows[0]) and db_rows(db)[0][0]['input_revision']==1


def test_deadline_final_fence_and_expired_call_retains_lease(proposal_db):
    db=proposal_db;task_id,c,process=setup(db);a=admit(db,task_id,c,process);call=reserve(db,task_id,a.state.run.run_id,process)
    p=prepared(call)
    with binding(db,clock=lambda:call.state.run.deadline) as b:
        with pytest.raises(Exception) as error:b.proposals.complete(p)
        assert error.value.code=='PROPOSAL_DEADLINE_EXPIRED'
    with binding(db,clock=lambda:call.state.run.deadline) as b:
        value=b.proposals.expire(call.context,call.token);value=b.finish_proposal_outcome(value,mode='write')
    assert value.state.run.stage=='FAILED' and value.state.active_call==call.token and value.lease.active_run_id==call.token.run_id
    with binding(db) as b:
        settled=b.proposals.fail(call.context,call.token,'WORK_AI_TIMEOUT');settled=b.finish_proposal_outcome(settled,mode='write')
    assert settled.state.run.error_code=='PROPOSAL_DEADLINE_EXPIRED' and settled.lease.active_run_id is None


def test_pending_cancel_and_known_pending_failure_process_bound(proposal_db):
    db=proposal_db;task_id,c,process=setup(db);a=admit(db,task_id,c,process)
    with pytest.raises(Exception) as error:op(db,'fail_pending',task_id,a.state.run.run_id,process_instance=uuid4(),error_code='WORK_AI_UNAVAILABLE')
    assert error.value.code=='OWNER_LEASE_LOST'
    cancelled=op(db,'cancel',task_id,a.state.run.run_id)
    assert cancelled.state.run.stage=='CANCELLED' and cancelled.lease.active_run_id is None
    assert op(db,'cancel',task_id,a.state.run.run_id)==cancelled
    b=admit(db,task_id,c,process,key='second-pending')
    failed=op(db,'fail_pending',task_id,b.state.run.run_id,process_instance=process,error_code='WORK_AI_UNAVAILABLE')
    assert failed.state.run.stage=='FAILED' and failed.state.run.provider_call_count==0 and failed.lease.active_run_id is None
    assert op(db,'cancel',task_id,b.state.run.run_id)==failed


def test_final_completion_deadline_check_after_final_flush(proposal_db,monkeypatch):
    from app.services.teacher_work.bootstrap import _SessionWorkTransport
    db=proposal_db;task_id,c,process=setup(db);a=admit(db,task_id,c,process);call=reserve(db,task_id,a.state.run.run_id,process)
    p=prepared(call);clock={'current':now()};original=_SessionWorkTransport.flush
    def advance(transport):
        original(transport)
        clock['current']=call.state.run.deadline
    with binding(db,clock=lambda:clock['current']) as b:
        value=b.proposals.complete(p)
        with monkeypatch.context() as patch:
            patch.setattr(_SessionWorkTransport,'flush',advance)
            with pytest.raises(Exception) as error:b.finish_proposal_outcome(value,mode='write')
            assert error.value.code=='PROPOSAL_DEADLINE_EXPIRED'
    read=op(db,'get',task_id,a.state.run.run_id,mode='read')
    assert read.state.run.stage=='OUTLINE_RUNNING' and read.proposal is None and read.lease.active_run_id==a.state.run.run_id


@pytest.mark.parametrize('stage',['admission','reservation','completion'])
@pytest.mark.parametrize('ack',['before','after'])
def test_unknown_proposal_commit_observation_never_redispatches(proposal_db,monkeypatch,stage,ack):
    import pymysql
    db=proposal_db;task_id,c,process=setup(db)
    admission=None;call=None
    if stage!='admission':admission=admit(db,task_id,c,process)
    if stage=='completion':call=reserve(db,task_id,admission.state.run.run_id,process)
    target={};original=pymysql.connections.Connection.commit
    prefix='INSERT INTO TEACHER_WORK_RUNS' if stage=='admission' else 'UPDATE TEACHER_WORK_RUNS'
    def trace(conn,cursor,statement,params,ctx,many):
        if statement.lstrip().upper().startswith(prefix):target['connection']=conn.connection.driver_connection
    def lose(connection):
        if connection is target.get('connection'):
            if ack=='after':original(connection);target['committed']=True
            raise pymysql.OperationalError(2013,'synthetic proposal commit reply unknown')
        return original(connection)
    event.listen(db.engine,'before_cursor_execute',trace)
    try:
        with monkeypatch.context() as patch,binding(db) as b:
            patch.setattr(pymysql.connections.Connection,'commit',lose)
            if stage=='admission':value=b.proposals.admit(OWNER,task_id,c,'unknown-proposal',process_instance=process,configured_timeout_seconds=90)
            elif stage=='reservation':value=b.proposals.reserve(OWNER,task_id,admission.state.run.run_id,process_instance=process,configured_output_tokens=8192,configured_timeout_seconds=90)
            else:value=b.proposals.complete(prepared(call))
            run_id=value.state.run.run_id
            with pytest.raises(Exception) as error:b.finish_proposal_outcome(value,mode='write')
            assert error.value.code=='COMMIT_OUTCOME_UNKNOWN'
    finally:event.remove(db.engine,'before_cursor_execute',trace)
    before=immutable_rows(db)
    if stage=='admission' and ack=='before':
        with pytest.raises(Exception) as error:op(db,'get',task_id,run_id,mode='read')
        assert error.value.code=='NOT_FOUND'
        assert op(db,'inspect',task_id,c,'unknown-proposal',mode='read').admission is None
    else:
        observed=op(db,'get',task_id,run_id,mode='read')
        expected={'admission':'PENDING','reservation':'OUTLINE_RUNNING' if ack=='after' else 'PENDING',
            'completion':'COMPLETE' if ack=='after' else 'OUTLINE_RUNNING'}[stage]
        assert observed.state.run.stage==expected
        assert observed.state.run.provider_call_count==(0 if expected=='PENDING' else 1)
        if stage=='admission':assert not op(db,'inspect',task_id,c,'unknown-proposal',mode='read').admission.created
    assert immutable_rows(db)==before
    db.row_observations.append({'unknown_proposal_stage':stage,'ack':ack,'run_id':str(run_id),'rows_unchanged_after_observation':True,'provider_invocations':0})


def test_reopen_list_completed_stale_foreign_and_corrupt_missing_input(proposal_db):
    db=proposal_db;task_id,_,result=completed(db)
    assert op(db,'list_runs',task_id,mode='read').runs.runs==(public_run(result),)
    with pytest.raises(Exception) as error:op(db,'list_runs',task_id,mode='read',owner=OTHER)
    assert error.value.code=='NOT_FOUND'
    http_request(db,'PATCH',f'/api/teacher/work/tasks/{task_id}/working',body=dict(expected_revision=1,changes=dict(requirements='next input')))
    stale=op(db,'list_runs',task_id,mode='read')
    assert stale.runs.runs[0].proposal_available and stale.runs.runs[0].input_revision==1
    # Direct administrative SQL is outside the official INSERT-only boundary.
    with db.engine.begin() as conn:conn.execute(text("DELETE FROM teacher_work_material_proposal_records WHERE record_type='input'"))
    with pytest.raises(Exception) as error:op(db,'list_runs',task_id,mode='read')
    assert error.value.code=='MATERIAL_PROPOSAL_STATE_UNAVAILABLE'


def test_retained_twenty_run_cap_and_sorted_reopen_list(proposal_db):
    db=proposal_db;task_id,c,process=setup(db)
    ids=[]
    for i in range(20):
        a=admit(db,task_id,c,process,key=f'proposal-{i}')
        ids.append(a.state.run.run_id)
        op(db,'cancel',task_id,a.state.run.run_id)
    listed=op(db,'list_runs',task_id,mode='read')
    assert [r.run_id for r in listed.runs.runs]==list(reversed(ids))
    with pytest.raises(Exception) as error:admit(db,task_id,c,process,key='twenty-first')
    assert error.value.code=='PROPOSAL_RUN_LIMIT'
    assert len(immutable_rows(db)[0])==20
    # Administrative synthetic overflow is outside official admission; reopen
    # must fail closed rather than hide the twenty-first retained record.
    with db.engine.begin() as conn:
        run=dict(conn.execute(select(WorkRun.__table__).where(WorkRun.kind=='outline')).mappings().first())
        record=dict(conn.execute(select(MaterialProposalRecord.__table__).where(MaterialProposalRecord.record_type=='input')).mappings().first())
        new_id=str(uuid4())
        run.update(run_id=new_id,idempotency_key=b'admin-overflow')
        record.update(run_id=new_id,record_key=new_id)
        conn.execute(insert(WorkRun).values(**run))
        conn.execute(insert(MaterialProposalRecord).values(**record))
    with pytest.raises(Exception) as error:op(db,'list_runs',task_id,mode='read')
    assert error.value.code=='MATERIAL_PROPOSAL_STATE_UNAVAILABLE'


@pytest.mark.parametrize('gate',['materials','sources'])
def test_read_cancel_do_not_require_material_configuration(proposal_db,monkeypatch,gate):
    db=proposal_db;task_id,c,process=setup(db);a=admit(db,task_id,c,process)
    if gate=='materials':monkeypatch.setattr(db.settings,'TEACHER_WORK_PRIVATE_MATERIALS_ENABLED',False)
    else:monkeypatch.setattr(db.settings,'COURSEWARE_FRONTEND_ROOT',str(db.source_file.parent/'absent'))
    assert op(db,'get',task_id,a.state.run.run_id,mode='read').state.run.stage=='PENDING'
    assert op(db,'list_runs',task_id,mode='read').runs.runs[0].run_id==a.state.run.run_id
    assert op(db,'cancel',task_id,a.state.run.run_id).state.run.stage=='CANCELLED'
    assert not admit(db,task_id,c,process).created
    with pytest.raises(Exception) as error:admit(db,task_id,c,process,key='requires-materials')
    assert error.value.code==('PRIVATE_MATERIALS_DISABLED' if gate=='materials' else 'MATERIAL_SOURCES_UNAVAILABLE')


def test_origin_flag_disabled_only_affects_explicit_origin(proposal_db,monkeypatch):
    db=proposal_db;task_id,_,result=completed(db)
    monkeypatch.setattr(db.settings,'TEACHER_WORK_PRIVATE_MATERIAL_PROPOSALS_ENABLED',False)
    body=save_body(result);path=f'/api/teacher/work/tasks/{task_id}/materials'
    response=request(db,'POST',path,key='origin-off',body=body)
    assert response.status_code==503 and response.json()['message']=='PRIVATE_MATERIAL_PROPOSALS_DISABLED'
    body['origin_proposal_run_id']=None
    manual=request(db,'POST',path,key='manual-null-off',body=body)
    assert manual.status_code==200,manual.text


def test_extension_absent_refuses_proposals_while_null_manual_origin_survives(proposal_db):
    db=proposal_db;task_id,_,result=completed(db)
    with db.engine.begin() as c:c.execute(text("DELETE FROM teacher_work_schema_versions WHERE component='teacher_work_material_proposals'"))
    with pytest.raises(Exception) as error:op(db,'get',task_id,result.state.run.run_id,mode='read')
    assert error.value.code=='PROPOSAL_SCHEMA_UNAVAILABLE'
    path=f'/api/teacher/work/tasks/{task_id}/materials';body=save_body(result)
    response=request(db,'POST',path,key='origin-extension-absent',body=body)
    assert response.status_code==503 and response.json()['message']=='PROPOSAL_SCHEMA_UNAVAILABLE'
    body.pop('origin_proposal_run_id')
    assert request(db,'POST',path,key='manual-extension-absent',body=body).status_code==200


def test_current_account_demotion_retains_unsettled_lease(proposal_db):
    db=proposal_db;task_id,c,process=setup(db);a=admit(db,task_id,c,process);call=reserve(db,task_id,a.state.run.run_id,process)
    with db.engine.begin() as conn:conn.execute(update(db.user).where(db.user.username==OWNER).values(role='student'))
    before=immutable_rows(db)
    with pytest.raises(Exception) as error:
        with binding(db) as b:b.proposals.fail(call.context,call.token,'WORK_AI_TIMEOUT')
    assert error.value.code=='CURRENT_TEACHER_REQUIRED' and immutable_rows(db)==before
    exact_run=next(row for row in before[2] if row['run_id']==str(call.token.run_id))
    assert before[3][0]['active_run_id']==str(call.token.run_id) and exact_run['active_call_no']==1


def test_official_record_duplicate_refusal_and_native_pk_check_fk(proposal_db):
    from sqlalchemy.exc import IntegrityError,DBAPIError
    db=proposal_db;task_id,c,process=setup(db);a=admit(db,task_id,c,process)
    with binding(db) as b:
        o=b.proposals.get(OWNER,task_id,a.state.run.run_id)
        with pytest.raises(Exception) as error:b.proposals._append(OWNER,task_id,o.state.run.run_id,'input',o.state.input_record.payload(),created_at=now())
        assert error.value.code=='MATERIAL_PROPOSAL_STATE_UNAVAILABLE'
    with db.engine.connect() as conn:original=dict(conn.execute(select(MaterialProposalRecord.__table__)).mappings().one())
    for defect in ('duplicate','check','foreign_key'):
        data=deepcopy(original)
        if defect=='check':data['record_key']=str(uuid4())
        if defect=='foreign_key':data['run_id']=data['record_key']=str(uuid4())
        with db.engine.connect() as conn:
            with pytest.raises(DBAPIError):conn.execute(insert(MaterialProposalRecord).values(**data))
            conn.rollback()
    assert len(immutable_rows(db)[0])==1


def test_final_completion_source_change_after_flush_rolls_back(proposal_db,monkeypatch):
    from app.services.teacher_work.bootstrap import _SessionWorkTransport
    db=proposal_db;task_id,c,process=setup(db);a=admit(db,task_id,c,process);call=reserve(db,task_id,a.state.run.run_id,process)
    original=_SessionWorkTransport.flush
    def change(transport):
        original(transport)
        db.source_file.write_bytes(b'synthetic bytes changed during final flush')
    with binding(db) as b:
        value=b.proposals.complete(prepared(call))
        with monkeypatch.context() as patch:
            patch.setattr(_SessionWorkTransport,'flush',change)
            with pytest.raises(Exception) as error:b.finish_proposal_outcome(value,mode='write')
            assert error.value.code=='SOURCE_CHANGED'
    read=op(db,'get',task_id,a.state.run.run_id,mode='read')
    assert read.state.run.stage=='OUTLINE_RUNNING' and read.proposal is None and read.lease.active_run_id==a.state.run.run_id
