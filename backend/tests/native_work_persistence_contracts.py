"""Explicit-only bounded Work persistence contracts with fresh real SQL Sessions.

Chat handlers are extracted unchanged from production source, rather than
importing the LangChain/tool stack. Student capabilities uses the actual router.
Teacher repository uses actual ORM/coordinator, with a test-owned trusted actor
namespace/current-account adapter, never a bypass of production MySQL gates.
"""
import ast
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
from threading import Barrier
from uuid import UUID, uuid4, uuid5, NAMESPACE_DNS
from typing import List, Optional, Literal

import httpx
import pytest
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, event, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import get_auth_payload
from app.core.database import get_db
from app.core.security import create_access_token
from app.core.miniprogram_response import api_response, is_miniprogram_client, page_items
from app.models.chat_message import ChatMessage
from app.models.domain_record import DomainRecord
from app.models.user_account import UserAccount
from app.models.teacher_work import WorkTask, WorkRun, WorkMessage, OwnerRunLease, PackageVersion
from app.repositories.json_store import JsonStore
from app.repositories.teacher_work import AuthorizedWorkScope, WorkRepositoryError
from app.repositories.teacher_work_sql import SqlWorkModels, SqlRunModels, build_sql_repository
from app.schemas.chat import ChatRequest
from app.schemas.teacher_work import CreateTaskRequest, WorkingPatchRequest, ChatCommand, ChatResult, WorkMessageDTO
from app.services.chat_history import save_chat_messages_batch, list_chat_history_page, normalize_agent_mode
from app.services.current_identity import resolve_current_account
from app.services.student_work_skills import resolve_student_work_skill
from app.services.teacher_work.authorization import CurrentAccountFacts, require_current_teacher_facts, WorkAuthorizationError
from app.services.teacher_work.types import WorkActor
from app.services.teacher_work.run_persistence import PreparedChatCompletion, validate_chat_completion
from app.services.teacher_work.runs import WorkRunError

ROOT = Path(os.environ.get('GEZHI_WORK_AUDIT_SOURCE',Path(__file__).resolve().parents[1])).resolve()
NOW = datetime(2026,10,7,5,0,tzinfo=timezone.utc)
PROCESS = UUID('11111111-1111-4111-8111-111111111111')


def extracted_chat():
    names={'_ensure_self','ChatHistoryItem','SaveChatHistoryBatchRequest','create_chat_history_batch','get_chat_history',
           '_resolve_student_work_skill','_validate_task_identity','resolve_agent_mode','clean_message_content','chat','remove_chat_history_message','clear_chat_history_endpoint'}
    tree=ast.parse((ROOT/'app/api/endpoints/chat.py').read_bytes())
    nodes=[node for node in tree.body if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)) and node.name in names]
    assert {node.name for node in nodes}==names
    for node in nodes: node.decorator_list=[]
    async def forbidden_dispatch(*args,**kwargs):
        raise AssertionError('Provider path must never run in invalid selection tests')
    ns=dict(Session=Session,Depends=Depends,Header=Header,HTTPException=HTTPException,Request=Request,
        get_db=get_db,get_auth_payload=get_auth_payload,BaseModel=BaseModel,Field=Field,List=List,Optional=Optional,Literal=Literal,
        ChatRequest=ChatRequest,resolve_student_work_skill=resolve_student_work_skill,normalize_agent_mode=normalize_agent_mode,
        save_chat_messages_batch=save_chat_messages_batch,list_chat_history_page=list_chat_history_page,
        delete_chat_message=__import__('app.services.chat_history',fromlist=['delete_chat_message']).delete_chat_message,
        clear_chat_history=__import__('app.services.chat_history',fromlist=['clear_chat_history']).clear_chat_history,
        api_response=api_response,is_miniprogram_client=is_miniprogram_client,page_items=page_items,
        re=re,logger=logging.getLogger('work-audit'),_run_chat_request=forbidden_dispatch)
    if (ROOT/'app/services/chat_batch_receipts.py').is_file():
        from app.services.chat_batch_receipts import ChatBatchUnavailable
        ns['ChatBatchUnavailable']=ChatBatchUnavailable
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(ROOT/'app/api/endpoints/chat.py'),'exec'),ns)
    return ns


@pytest.fixture
def world(tmp_path):
    engine=create_engine('sqlite:///'+str(tmp_path/'synthetic.db'),connect_args={'timeout':10})
    @event.listens_for(engine,'connect')
    def enforce_foreign_keys(connection,record):
        connection.execute('PRAGMA foreign_keys=ON')
    for model in (UserAccount,DomainRecord,ChatMessage): model.__table__.create(engine)
    for model in (WorkTask,OwnerRunLease,WorkRun,WorkMessage,PackageVersion): model.__table__.create(engine)
    if (ROOT/'app/models/chat_batch_receipt.py').is_file():
        from app.models.chat_batch_receipt import ChatBatchReceipt
        ChatBatchReceipt.__table__.create(engine)
    sessions=sessionmaker(bind=engine,autoflush=False,expire_on_commit=False)
    with sessions() as db:
        db.add_all([UserAccount(username=name,role=role,password_hash='') for name,role in
            [('student','student'),('peer','student'),('teacher','teacher'),('other-teacher','teacher')]])
        db.commit()
    ns=extracted_chat(); app=FastAPI()
    for path,name,method in [('/chat/history/batch','create_chat_history_batch','POST'),('/chat/history','get_chat_history','GET'),('/chat','chat','POST'),('/chat/history/{message_id}','remove_chat_history_message','DELETE'),
        ('/chat/history','clear_chat_history_endpoint','DELETE')]:
        app.add_api_route(path,ns[name],methods=[method])
    from app.api.endpoints.student_work import router
    app.include_router(router)
    def isolated_db():
        with sessions() as db: yield db
    app.dependency_overrides[get_db]=isolated_db
    yield app,sessions,engine,ns
    engine.dispose()


def request(world,method,path,*,actor='student',role='student',key=None,**kwargs):
    app=world[0]
    async def send():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,raise_app_exceptions=False),base_url='http://synthetic.local') as client:
            headers={'Authorization':'Bearer '+create_access_token(actor,role)}
            if key is not None: headers['Idempotency-Key']=key
            return await client.request(method,path,headers=headers,**kwargs)
    return asyncio.run(send())


def batch(*,owner='student',key='paper-request',conversation='paper-one',query='synthetic query'):
    # Same two-message wire shape as production buildPaperSyncBody.
    return {'user_id':owner,'agent_mode':'paper','client_request_id':key,'conversation_id':conversation,'project_id':'project-one',
        'messages':[{'role':'user','content':query,'agent_mode':'paper','sender_id':None,
            'conversation_id':conversation,'project_id':'project-one'},
            {'role':'assistant','content':'Synthetic search report: metadata and abstract only','agent_mode':'paper','sender_id':'agent_paper',
                'conversation_id':conversation,'project_id':'project-one','payload':{'kind':'paper_search','query':query,'status':'success',
                    'results':[{'title':'Synthetic paper','abstract':'Supplied abstract only','ordinal':1}],
                    'summary':{'totalAfterMerge':1,'snapshotCount':1,'snapshotComplete':True},
                    'statuses':[{'key':'arxiv','status':'success','count':1}]}}]}


def count(world,model=ChatMessage):
    with world[1]() as db: return db.scalar(select(func.count()).select_from(model))


def test_paper_pair_atomic_fresh_read_and_exact_sequential_replay(world):
    first=request(world,'POST','/chat/history/batch',json=batch())
    assert first.status_code==200 and first.json()['status']=='success'
    rows=first.json()['data']; ids=[r['id'] for r in rows]
    assert len(ids)==2 and len(set(ids))==2 and all(i>0 for i in ids)
    repeat=request(world,'POST','/chat/history/batch',json=batch())
    assert repeat.json()['data']==rows and count(world)==2
    fresh=request(world,'GET','/chat/history?session_id=student&agent_mode=paper&conversation_id=paper-one')
    actual=fresh.json()['data']
    assert [r['id'] for r in actual]==ids
    for saved,read in zip(rows,actual):
        for field in ('user_id','agent_mode','role','content','sender_id','conversation_id','project_id','payload'):
            assert read[field]==saved[field]
    assert actual[0]['content']==actual[1]['payload']['query']=='synthetic query'
    assert actual[1]['payload']['results'][0]['abstract']=='Supplied abstract only'
    assert actual[1]['payload']['summary']['snapshotComplete'] is True


@pytest.mark.parametrize('changes',[{'query':'different'}, {'conversation':'paper-two'}])
def test_same_owner_key_different_body_conflicts_without_mixing(world,changes):
    assert request(world,'POST','/chat/history/batch',json=batch()).json()['status']=='success'
    conflict=request(world,'POST','/chat/history/batch',json=batch(**changes))
    assert conflict.status_code==409 and count(world)==2


def test_same_key_other_owner_separate_and_foreign_selector_denied(world):
    first=request(world,'POST','/chat/history/batch',json=batch()).json()['data']
    second=request(world,'POST','/chat/history/batch',json=batch(owner='peer'),actor='peer').json()['data']
    assert set(r['id'] for r in first).isdisjoint(r['id'] for r in second)
    denied=request(world,'POST','/chat/history/batch',json=batch(owner='peer',key='forged'))
    assert denied.status_code==403 and count(world)==4
    assert request(world,'GET','/chat/history?session_id=student&agent_mode=paper',actor='teacher',role='teacher').status_code==403


def test_paper_second_insert_failure_rolls_back_both_and_retry_persists(world):
    engine=world[2]; calls=0
    def fail_second(conn,cursor,statement,parameters,context,many):
        nonlocal calls
        if statement.lstrip().upper().startswith('INSERT INTO CHAT_MESSAGES'):
            calls+=1
            if calls==2: raise RuntimeError('synthetic second insert failure')
    event.listen(engine,'before_cursor_execute',fail_second)
    try:
        failed=request(world,'POST','/chat/history/batch',json=batch())
        assert failed.status_code==503 and failed.json()['detail']=='CHAT_BATCH_UNAVAILABLE'
    finally: event.remove(engine,'before_cursor_execute',fail_second)
    assert count(world)==0
    assert request(world,'POST','/chat/history/batch',json=batch()).json()['status']=='success' and count(world)==2


def test_partial_deleted_pair_cannot_replay_as_saved_pair(world):
    rows=request(world,'POST','/chat/history/batch',json=batch()).json()['data']
    with world[1]() as db:
        db.delete(db.get(ChatMessage,rows[0]['id'])); db.commit()
    replay=request(world,'POST','/chat/history/batch',json=batch())
    assert replay.status_code==409 and count(world)==1


@pytest.mark.parametrize('selection', [['plugin_python_sandbox'],['plugin_chart_renderer'],['academic-review','academic-review'],'academic-review',[None]])
def test_unknown_or_malformed_selection_fails_before_any_origin(world,selection):
    result=request(world,'POST','/chat',json={'message':'review','agent_mode':'chat','skill_ids':selection})
    assert result.status_code==422 and count(world)==0


@pytest.mark.parametrize('options',[{'agent_mode':'tutor'},{'agent_mode':'rag'},{'agent_mode':'chat','force_rag':True},{'agent_mode':'chat','repository_id':'r'},{'agent_mode':'chat','is_diagnosis':True}])
def test_selected_skill_disallowed_context_fails_before_any_origin(world,options):
    result=request(world,'POST','/chat',json={'message':'review','skill_ids':['academic-review'],**options})
    assert result.status_code==422 and count(world)==0


def test_capabilities_are_static_truthful_and_current_account_authenticated(world):
    response=request(world,'GET','/student/work/capabilities')
    assert response.status_code==200 and response.headers['cache-control']=='private, no-store'
    items={v['plugin_id']:v for v in response.json()['items']}
    assert items['plugin_peer_review']['implementation']=='prompt-only'
    assert items['plugin_peer_review']['skill_id']=='academic-review'
    assert items['plugin_peer_review']['configuration_status']=='checked_on_execution'
    for key in ('plugin_python_sandbox','plugin_chart_renderer','plugin_zotero','plugin_semanticscholar'):
        assert items[key]['implemented'] is False and items[key]['implementation']=='metadata-only'
    assert all(v['live_verified'] is False for v in items.values())
    assert request(world,'GET','/student/work/capabilities',actor='deleted').status_code==401
    assert count(world)==0


@contextmanager
def teacher_repository(world,actor='teacher',*,mode='write',now=NOW):
    # This is a trusted test adapter, not the production MySQL request owner.
    with world[1]() as db:
        db.begin()
        def authorize(owner,offering,institution):
            account=resolve_current_account('Bearer '+create_access_token(actor,'teacher'),db)
            subject=require_current_teacher_facts(actor,CurrentAccountFacts(account.username,account.role))
            if owner!=subject or offering is not None or institution is not None:
                raise WorkRepositoryError('NOT_FOUND',404)
            return AuthorizedWorkScope(WorkActor(subject,'teacher',uuid5(NAMESPACE_DNS,'synthetic:'+subject)),None,None)
        repo=build_sql_repository(db,models=SqlWorkModels(WorkTask,OwnerRunLease,PackageVersion,DomainRecord),
            run_models=SqlRunModels(WorkRun,WorkMessage), draft_store=JsonStore(db,commit_policy='caller_owned',record_model=DomainRecord),
            authorize_locked=authorize,clock=lambda:now,new_uuid=uuid4,mode=mode)
        yield db,repo


def invoke(world,name,*args,actor='teacher',owner=None,now=NOW,**kwargs):
    with teacher_repository(world,actor,now=now) as (db,repo):
        result=getattr(repo,name)(owner or actor,*args,**kwargs); repo.uow.assert_healthy(); db.commit()
        return result


def task_body(title='Synthetic private task'):
    return CreateTaskRequest(title=title,topic='Synthetic topic',audience='Synthetic audience',resource_ids=['synthetic-resource'],scope='private')


def task(world,*,actor='teacher',key='task-key'):
    return invoke(world,'create_task',task_body(),key,actor=actor)


def command(key='message-key',text='Synthetic question',revision=1):
    return ChatCommand(kind='chat',input_revision=revision,skill_ref=None,payload={'text':text,'client_message_key':key})


def admit(world,saved,*,key='run-key',body=None):
    return invoke(world,'admit_chat',saved.task_id,body or command(),key,process_instance=PROCESS,configured_timeout_seconds=10)


def reserve(world,admission):
    return invoke(world,'reserve_chat_call',admission.task.task_id,admission.state.run.run_id,process_instance=PROCESS,
        configured_output_tokens=128,configured_timeout_seconds=10)


def test_teacher_private_create_replay_revision_fresh_read_and_rollback(world):
    saved=task(world); assert task(world)==saved
    assert count(world,WorkTask)==count(world,DomainRecord)==count(world,OwnerRunLease)==1
    with pytest.raises(WorkRepositoryError,match='IDEMPOTENCY_CONFLICT'):
        invoke(world,'create_task',task_body('Changed title'),'task-key')
    patch=WorkingPatchRequest.model_validate({'expected_revision':1,'changes':{'requirements':'Saved requirement','resource_ids':['new-resource'],'target_slide_count':9}})
    updated=invoke(world,'patch_working',saved.task_id,patch)
    snapshot=invoke(world,'get_private_snapshot',saved.task_id)
    assert snapshot.task==updated and updated.input_revision==updated.working_revision==2
    assert snapshot.working.requirements=='Saved requirement' and snapshot.working.resource_ids==('new-resource',)
    with pytest.raises(WorkRepositoryError,match='REVISION_CONFLICT'):
        invoke(world,'patch_working',saved.task_id,patch)
    with teacher_repository(world) as (db,repo):
        repo.patch_working('teacher',saved.task_id,WorkingPatchRequest.model_validate({'expected_revision':2,'changes':{'requirements':'Rollback'}}))
        db.rollback()
    assert invoke(world,'get_private_snapshot',saved.task_id)==snapshot


def test_teacher_private_cross_owner_and_current_role_rejected(world):
    saved=task(world); task(world,actor='other-teacher')
    with pytest.raises(WorkRepositoryError,match='NOT_FOUND'):
        invoke(world,'get_private_snapshot',saved.task_id,actor='other-teacher')
    with pytest.raises(WorkRepositoryError,match='NOT_FOUND'):
        invoke(world,'patch_working',saved.task_id,WorkingPatchRequest.model_validate({'expected_revision':1,'changes':{'requirements':'foreign'}}),actor='other-teacher')
    with world[1]() as db:
        db.execute(update(UserAccount).where(UserAccount.username=='teacher').values(role='student')); db.commit()
    with pytest.raises(WorkAuthorizationError): invoke(world,'get_private_snapshot',saved.task_id)
    assert count(world,WorkTask)==2


def test_teacher_chat_admission_replay_conflict_atomic_rollback_and_scopes(world):
    saved=task(world)
    with teacher_repository(world) as (db,repo):
        repo.admit_chat('teacher',saved.task_id,command(),'rollback',process_instance=PROCESS,configured_timeout_seconds=10)
        db.rollback()
    assert count(world,WorkRun)==count(world,WorkMessage)==0
    admission=admit(world,saved)
    assert admission.state.run.stage=='PENDING' and admission.state.run.provider_call_count==0
    replay=admit(world,saved)
    assert replay.state==admission.state and replay.user_message==admission.user_message and replay.created is False
    with pytest.raises(WorkRunError,match='IDEMPOTENCY_CONFLICT'): admit(world,saved,body=command(text='Different'))
    with pytest.raises(WorkRunError,match='OWNER_RUN_BUSY'): admit(world,saved,key='another-run')
    foreign=task(world,actor='other-teacher')
    with pytest.raises(WorkRepositoryError,match='NOT_FOUND'):
        invoke(world,'get_chat_run',saved.task_id,admission.state.run.run_id,actor='other-teacher')
    with pytest.raises(WorkRepositoryError,match='NOT_FOUND'):
        invoke(world,'get_chat_run',foreign.task_id,admission.state.run.run_id,actor='other-teacher')
    assert count(world,WorkRun)==count(world,WorkMessage)==1


def prepared(reservation):
    result=ChatResult(type='answer',plain_text='Synthetic completed answer',result_refs=(),omitted_context=False)
    message=WorkMessageDTO(message_id=uuid4(),owner='teacher',task_id=reservation.task.task_id,client_message_key=None,role='assistant',
        plain_text=result.plain_text,run_id=reservation.token.run_id,result_type=result.type,result_refs=(),omitted_context=False,created_at=NOW)
    receipt=validate_chat_completion(reservation.state.run,message,reservation.token.run_id)
    return PreparedChatCompletion(reservation.context,reservation.token,result,frozenset(),False,message,receipt)


def test_teacher_chat_completion_receipt_replay_fresh_history_and_terminal_cancel(world):
    saved=task(world); admission=admit(world,saved); reservation=reserve(world,admission); payload=prepared(reservation)
    with teacher_repository(world) as (db,repo):
        completion=repo.complete_prepared_chat_call(payload); db.commit()
    assert completion.state.run.stage=='COMPLETE' and completion.completion is not None
    read=invoke(world,'get_chat_run',saved.task_id,admission.state.run.run_id)
    assert read==completion and read.lease.active_run_id is None and read.state.run.provider_call_count==1
    history=invoke(world,'get_private_chat_history',saved.task_id)
    # Equal synthetic timestamps are intentionally ordered by UUID, not role.
    roles={m.role:m for m in history.messages}
    assert set(roles)=={'user','assistant'} and len(history.messages)==2
    assert roles['assistant'].message_id==completion.completion.message_id
    assert roles['assistant'].plain_text=='Synthetic completed answer'
    assert invoke(world,'cancel_chat',saved.task_id,admission.state.run.run_id)==read
    assert admit(world,saved).state==read.state and count(world,WorkMessage)==2
    with teacher_repository(world) as (db,repo):
        repeat=repo.complete_prepared_chat_call(payload); db.commit()
    assert repeat==read and count(world,WorkMessage)==2


def test_teacher_pending_cancel_releases_lease_and_late_reserved_cancel_discards_result(world):
    saved=task(world); first=admit(world,saved)
    cancelled=invoke(world,'cancel_chat',saved.task_id,first.state.run.run_id)
    assert cancelled.state.run.stage=='CANCELLED' and cancelled.lease.active_run_id is None
    assert count(world,WorkMessage)==1
    second=admit(world,saved,key='run-two',body=command(key='message-two'))
    reservation=reserve(world,second)
    running_cancel=invoke(world,'cancel_chat',saved.task_id,second.state.run.run_id)
    assert running_cancel.state.run.stage=='CANCELLED' and running_cancel.state.active_call is not None
    assert running_cancel.lease.active_run_id==second.state.run.run_id
    with pytest.raises(WorkRunError,match='RUN_CANCELLED'):
        with teacher_repository(world) as (db,repo): repo.complete_prepared_chat_call(prepared(reservation))
    # This test owns the synthetic terminal provider outcome. Only settlement
    # may release the charged cancelled lease, never the cancellation request.
    with teacher_repository(world) as (db,repo):
        settled=repo.fail_chat_call(reservation.context,reservation.token,'WORK_EXECUTION_UNAVAILABLE'); db.commit()
    assert settled.state.run.stage=='CANCELLED' and settled.completion is None and settled.lease.active_run_id is None
    assert count(world,WorkMessage)==2


def test_concurrent_paper_replay_returns_one_pair(world):
    """Pause both Sessions before their first reservation/message INSERT."""
    import threading
    barrier=Barrier(2); seen=set()
    def synchronize(conn,cursor,statement,parameters,context,many):
        upper=statement.lstrip().upper()
        if upper.startswith(('INSERT INTO CHAT_MESSAGES','INSERT INTO CHAT_BATCH_RECEIPTS')):
            identity=threading.get_ident()
            if identity not in seen:
                seen.add(identity); barrier.wait(timeout=5)
    event.listen(world[2],'before_cursor_execute',synchronize)
    payload=world[3]['SaveChatHistoryBatchRequest'].model_validate(batch())
    def save():
        with world[1]() as db:
            return [r.id for r in save_chat_messages_batch(db,user_id=payload.user_id,agent_mode=payload.agent_mode,
                items=payload.messages,conversation_id=payload.conversation_id,project_id=payload.project_id,client_request_id=payload.client_request_id)]
    try:
        with ThreadPoolExecutor(max_workers=2) as pool: pairs=list(pool.map(lambda _:save(),range(2)))
    finally: event.remove(world[2],'before_cursor_execute',synchronize)
    assert pairs[0]==pairs[1], {'pairs':pairs,'persisted_rows':count(world)}
    assert count(world)==2


def test_assembled_teacher_router_refuses_sqlite_without_mutation(world,monkeypatch):
    from app.api.endpoints.teacher_work import router
    from app.core import database
    from app.core.config import settings
    monkeypatch.setattr(database,'engine',world[2])
    monkeypatch.setattr(settings,'TEACHER_WORK_PRIVATE_TASKS_ENABLED',True)
    monkeypatch.setattr(settings,'TEACHER_WORK_PRIVATE_CHAT_ENABLED',True)
    world[0].include_router(router)
    for method,path,body in [('GET','/teacher/work/capabilities',None),
        ('POST','/teacher/work/tasks',task_body().model_dump(mode='json')),
        ('GET','/teacher/work/tasks/'+str(uuid4())+'/messages',None)]:
        response=request(world,method,path,actor='teacher',role='teacher',key='closed-gate',json=body)
        assert response.status_code==503  # The actual MySQL request owner refuses SQLite.
    assert count(world,WorkTask)==count(world,WorkMessage)==0


@pytest.mark.parametrize('outcome',['complete','invalid','cancel'])
def test_real_teacher_executor_controlled_provider_reaches_truthful_terminal(world,outcome):
    import time
    from app.schemas.teacher_work import ChatTaskBrief
    from app.services.teacher_work.chat_execution import TeacherChatExecution, ChatExecutionContext
    saved=task(world)
    calls=[]; checked_out=set(); ready=asyncio.Event()
    def checkout(connection,*args): checked_out.add(id(connection))
    def checkin(connection,*args): checked_out.discard(id(connection))
    event.listen(world[2],'checkout',checkout); event.listen(world[2],'checkin',checkin)
    class Transactions:
        def __getattr__(self,name):
            def operation(*args,**kwargs):
                with teacher_repository(world,now=datetime.now(timezone.utc)) as (db,repo):
                    value=getattr(repo,name)(*args,**kwargs); repo.uow.assert_healthy(); db.commit()
                    return value
            return operation
    class Context:
        def load(self,admission):
            snapshot=invoke(world,'get_private_snapshot',saved.task_id)
            return ChatExecutionContext(command=command(),history=(),evidence=(),task_brief=ChatTaskBrief(
                task_id=saved.task_id,input_revision=1,title=saved.title,topic=saved.topic,audience=saved.audience,requirements=snapshot.working.requirements))
    class Clock:
        utc_now=staticmethod(lambda:datetime.now(timezone.utc))
        monotonic=staticmethod(time.monotonic)
        async def wait_until(self,deadline): await asyncio.sleep(max(0,deadline-time.monotonic()))
    class Provider:
        async def complete(self,prompt,*,max_output_tokens,timeout_seconds):
            assert not checked_out, 'Real SQL connection held during provider await'
            calls.append(prompt); ready.set()
            if outcome=='cancel': await asyncio.Event().wait()
            if outcome=='invalid': return 'malformed synthetic provider response'
            return json.dumps({'type':'answer','plain_text':'Synthetic executor answer'})
    async def scenario():
        execution=TeacherChatExecution(transactions=Transactions(),ai=Provider(),context_source=Context(),
            process_instance=PROCESS,clock=Clock(),new_uuid=uuid4,configured_output_tokens=128,configured_timeout_seconds=10)
        run=await execution.start_chat('teacher',saved.task_id,command(),'executor-key')
        assert run.stage=='PENDING' and run.provider_call_count==0
        supervisors=[entry.supervisor for entry in execution._runs.values()]
        await asyncio.wait_for(ready.wait(),timeout=2)
        if outcome=='cancel':
            cancelled=await execution.cancel_chat('teacher',saved.task_id,run.run_id)
            assert cancelled.stage=='CANCELLED'
        await asyncio.wait_for(asyncio.gather(*supervisors),timeout=3)
        read=invoke(world,'get_chat_run',saved.task_id,run.run_id)
        expected={'complete':'COMPLETE','invalid':'FAILED','cancel':'CANCELLED'}[outcome]
        assert read.state.run.stage==expected and read.state.run.provider_call_count==1
        assert read.state.active_call is None and read.lease.active_run_id is None
        history=invoke(world,'get_private_chat_history',saved.task_id)
        assert len(history.messages)==(2 if outcome=='complete' else 1)
        if outcome=='complete':
            assert read.completion is not None and history.messages[-1].plain_text=='Synthetic executor answer'
        else: assert read.completion is None
        replay=await execution.start_chat('teacher',saved.task_id,command(),'executor-key')
        assert replay==read.state.run and len(calls)==1
        assert not execution._runs and not execution._slots
    try: asyncio.run(scenario())
    finally:
        event.remove(world[2],'checkout',checkout); event.remove(world[2],'checkin',checkin)


def test_paper_commit_ack_loss_reports_unknown_and_explicit_retry_recovers_same_pair(world,monkeypatch):
    original=Session.commit
    def lose_ack(db):
        original(db)
        raise RuntimeError('synthetic acknowledged server commit, lost client acknowledgement')
    with monkeypatch.context() as patch:
        patch.setattr(Session,'commit',lose_ack)
        failure=request(world,'POST','/chat/history/batch',json=batch())
    assert failure.status_code==503 and count(world)==2
    with world[1]() as db: ids=list(db.scalars(select(ChatMessage.id).order_by(ChatMessage.id)))
    recovered=request(world,'POST','/chat/history/batch',json=batch())
    assert recovered.json()['status']=='success'
    assert [row['id'] for row in recovered.json()['data']]==ids and count(world)==2


def test_teacher_foreign_chat_history_cancel_and_run_task_scope_are_closed(world):
    saved=task(world); foreign=task(world,actor='other-teacher'); admission=admit(world,saved)
    for operation,args in [('get_private_chat_history',(saved.task_id,)),
                           ('cancel_chat',(saved.task_id,admission.state.run.run_id)),
                           ('admit_chat',(saved.task_id,command(),'foreign-run'))]:
        kwargs={'process_instance':PROCESS,'configured_timeout_seconds':10} if operation=='admit_chat' else {}
        with pytest.raises(WorkRepositoryError,match='NOT_FOUND'):
            invoke(world,operation,*args,actor='other-teacher',**kwargs)
    with pytest.raises(WorkRepositoryError,match='NOT_FOUND'):
        invoke(world,'get_chat_run',foreign.task_id,admission.state.run.run_id,actor='other-teacher')
    assert count(world,WorkMessage)==1


def test_teacher_completion_late_write_failure_rolls_back_and_fresh_retry_succeeds(world):
    saved=task(world); reservation=reserve(world,admit(world,saved)); completion=prepared(reservation)
    def fail_release(conn,cursor,statement,parameters,context,many):
        if statement.lstrip().upper().startswith('UPDATE TEACHER_WORK_OWNER_RUN_LEASES'):
            raise RuntimeError('synthetic final lease write failure')
    event.listen(world[2],'before_cursor_execute',fail_release)
    try:
        with pytest.raises(RuntimeError,match='final lease'):
            with teacher_repository(world) as (db,repo):
                repo.complete_prepared_chat_call(completion); db.commit()
    finally: event.remove(world[2],'before_cursor_execute',fail_release)
    assert count(world,WorkMessage)==1
    fresh=invoke(world,'get_chat_run',saved.task_id,reservation.token.run_id)
    assert fresh.state==reservation.state and fresh.completion is None
    with teacher_repository(world) as (db,repo):
        result=repo.complete_prepared_chat_call(completion); db.commit()
    assert result.state.run.stage=='COMPLETE' and count(world,WorkMessage)==2


def test_deleted_paper_key_never_recreates_deleted_history(world):
    """Explicit negative proof: deleting both messages destroys today's receipt."""
    from app.services.chat_history import clear_chat_history
    first=request(world,'POST','/chat/history/batch',json=batch())
    assert first.json()['status']=='success' and count(world)==2
    with world[1]() as db:
        assert clear_chat_history(db,user_id='student',agent_mode='paper')==2
    assert count(world)==0
    replay=request(world,'POST','/chat/history/batch',json=batch())
    assert replay.status_code==409, {'response':replay.json(),'resurrected_rows':count(world)}
    assert count(world)==0


def test_receipt_schema_missing_refuses_keyed_pair_without_append(world):
    from sqlalchemy import inspect
    if 'chat_batch_receipts' in inspect(world[2]).get_table_names():
        with world[2].begin() as connection: connection.exec_driver_sql('DROP TABLE chat_batch_receipts')
    response=request(world,'POST','/chat/history/batch',json=batch())
    assert response.status_code==503 and count(world)==0


def test_receipt_schema_incompatible_refuses_without_append(world):
    from sqlalchemy import inspect
    with world[2].begin() as connection:
        if 'chat_batch_receipts' in inspect(connection).get_table_names(): connection.exec_driver_sql('DROP TABLE chat_batch_receipts')
        connection.exec_driver_sql('CREATE TABLE chat_batch_receipts (owner_key BLOB, request_key BLOB)')
    response=request(world,'POST','/chat/history/batch',json=batch())
    assert response.status_code==503 and count(world)==0


def test_receipt_model_exact_keys_minimal_metadata_and_explicit_migration_only(world):
    model_path=ROOT/'app/models/chat_batch_receipt.py'
    assert model_path.is_file(), 'Additive durable receipt model is missing'
    from app.models.chat_batch_receipt import ChatBatchReceipt
    from app.core.schema_policy import startup_table_allowed
    from sqlalchemy.dialects.mysql import dialect
    from sqlalchemy.schema import CreateTable
    table=ChatBatchReceipt.__table__
    assert [c.name for c in table.primary_key]==['owner_key','request_key']
    assert startup_table_allowed(table) is False
    sql=str(CreateTable(table).compile(dialect=dialect()))
    assert 'VARBINARY(1020)' in sql and 'VARBINARY(512)' in sql and 'ENGINE=InnoDB' in sql
    assert not {'content','query','payload','request_body'} & set(table.columns.keys())
    for key in ('é','e\u0301','key','key '):
        assert request(world,'POST','/chat/history/batch',json=batch(key=key)).json()['status']=='success'
    assert count(world)==8
    with world[1]() as db:
        receipts=list(db.scalars(select(ChatBatchReceipt)))
        assert {r.request_key for r in receipts}=={key.encode() for key in ('é','e\u0301','key','key ')}
        assert all(r.owner_key==b'student' and r.state=='committed' for r in receipts)


def test_explicit_migration_preflight_apply_and_identity_refusal_on_owned_sqlite(world):
    path=ROOT/'migrations/v20261007_chat_batch_receipts.py'
    assert path.is_file(), 'Explicit receipt installer/preflight is missing'
    import importlib.util
    spec=importlib.util.spec_from_file_location('receipt_migration',path)
    migration=importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name]=migration
    spec.loader.exec_module(migration)
    from app.models.chat_batch_receipt import ChatBatchReceipt
    from app.services.chat_batch_schema import CONTRACT_HASH
    ChatBatchReceipt.__table__.drop(world[2])
    with world[2].connect() as connection:
        identity=migration.observe_database_identity(connection)
        connection.rollback()
        with pytest.raises(ValueError,match='identity'):
            migration.apply_chat_batch_receipts(connection,expected_identity={'dialect':'sqlite','database':'wrong'},contract_hash=CONTRACT_HASH)
        connection.rollback()
        plan=migration.preflight_chat_batch_receipts(connection,expected_identity=identity,contract_hash=CONTRACT_HASH)
        assert plan['mode']=='fresh' and plan['automatic_startup'] is False
        connection.rollback()
        result=migration.apply_chat_batch_receipts(connection,expected_identity=identity,contract_hash=CONTRACT_HASH)
        assert result['completed'] and result['created']
        connection.rollback()
        assert migration.apply_chat_batch_receipts(connection,expected_identity=identity,contract_hash=CONTRACT_HASH)['created'] is False
    assert request(world,'POST','/chat/history/batch',json=batch()).json()['status']=='success'


def legacy_pair(world,*,copies=1,partial=False):
    import hashlib
    payload=world[3]['SaveChatHistoryBatchRequest'].model_validate(batch())
    body={'agent_mode':'paper','conversation_id':payload.conversation_id,'project_id':payload.project_id,
        'items':[item.model_dump() for item in payload.messages]}
    digest=hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    ids=[]
    with world[1]() as db:
        for _ in range(copies):
            for index,item in enumerate(payload.messages[:1] if partial else payload.messages):
                row=ChatMessage(user_id='student',agent_mode='paper',role=item.role,content=item.content,
                    sender_id=item.sender_id,conversation_id=payload.conversation_id,project_id=payload.project_id,
                    payload={**(item.payload or {}),'_sync':{'client_request_id':payload.client_request_id,'digest':digest,'index':index,'count':2}})
                db.add(row); db.flush(); ids.append(row.id)
        db.commit()
    return ids,digest


def test_legacy_pair_adoption_preserves_ids_and_fingerprint_without_append(world):
    from app.models.chat_batch_receipt import ChatBatchReceipt
    ids,digest=legacy_pair(world)
    response=request(world,'POST','/chat/history/batch',json=batch())
    assert response.status_code==200 and [v['id'] for v in response.json()['data']]==ids and count(world)==2
    with world[1]() as db:
        receipt=db.scalars(select(ChatBatchReceipt)).one()
        assert receipt.request_digest==digest and [receipt.user_message_id,receipt.assistant_message_id]==ids
    different=request(world,'POST','/chat/history/batch',json=batch(query='Changed'))
    assert different.status_code==409 and count(world)==2


@pytest.mark.parametrize('options',[{'copies':2},{'partial':True}])
def test_legacy_ambiguous_or_partial_pair_conflicts_without_new_receipt_or_append(world,options):
    from app.models.chat_batch_receipt import ChatBatchReceipt
    ids,digest=legacy_pair(world,**options)
    response=request(world,'POST','/chat/history/batch',json=batch())
    assert response.status_code==409 and count(world)==len(ids) and count(world,ChatBatchReceipt)==0


def test_receipt_rolls_back_with_pair_and_corrupt_receipt_never_overwritten(world):
    from app.models.chat_batch_receipt import ChatBatchReceipt
    def fail_pair(conn,cursor,statement,parameters,context,many):
        if statement.lstrip().upper().startswith('INSERT INTO CHAT_MESSAGES'):
            raise RuntimeError('synthetic pair persistence fault')
    event.listen(world[2],'before_cursor_execute',fail_pair)
    try:
        assert request(world,'POST','/chat/history/batch',json=batch()).status_code==503
    finally: event.remove(world[2],'before_cursor_execute',fail_pair)
    assert count(world)==count(world,ChatBatchReceipt)==0
    assert request(world,'POST','/chat/history/batch',json=batch()).status_code==200
    with world[1]() as db:
        receipt=db.scalars(select(ChatBatchReceipt)).one()
        digest=receipt.request_digest
        receipt.state='deleted'; db.commit()
    assert request(world,'POST','/chat/history/batch',json=batch()).status_code==409 and count(world)==2
    with world[1]() as db: assert db.scalars(select(ChatBatchReceipt)).one().request_digest==digest


def test_single_delete_tombstone_fences_pair_replay_and_peer_cannot_delete(world):
    from app.models.chat_batch_receipt import ChatBatchReceipt
    response=request(world,'POST','/chat/history/batch',json=batch())
    target=response.json()['data'][0]['id']
    peer=request(world,'DELETE',f'/chat/history/{target}?session_id=student',actor='peer')
    assert peer.status_code==403 and count(world)==2
    deleted=request(world,'DELETE',f'/chat/history/{target}?session_id=student')
    assert deleted.json()['status']=='success' and count(world)==1
    assert request(world,'POST','/chat/history/batch',json=batch()).status_code==409
    with world[1]() as db: assert db.scalars(select(ChatBatchReceipt)).one().state=='deleted'


def test_absent_schema_legacy_delete_allowed_and_corrupt_schema_paper_delete_explicitly_blocked(world):
    from app.models.chat_batch_receipt import ChatBatchReceipt
    from app.services.chat_history import save_chat_message
    with world[1]() as db:
        row=save_chat_message(db,user_id='student',agent_mode='paper',role='user',content='Legacy unkeyed row')
        target=row.id
    ChatBatchReceipt.__table__.drop(world[2])
    assert request(world,'DELETE',f'/chat/history/{target}?session_id=student').json()['status']=='success'
    with world[1]() as db:
        save_chat_message(db,user_id='student',agent_mode='paper',role='user',content='Another old row')
    with world[2].begin() as connection: connection.exec_driver_sql('CREATE TABLE chat_batch_receipts (owner_key BLOB, request_key BLOB)')
    blocked=request(world,'DELETE','/chat/history?session_id=student&agent_mode=paper')
    assert blocked.status_code==503 and blocked.json()['detail']=='CHAT_BATCH_SCHEMA_UNAVAILABLE' and count(world)==1


def test_corrupt_receipt_schema_does_not_block_other_modes(world):
    from app.models.chat_batch_receipt import ChatBatchReceipt
    from app.services.chat_history import save_chat_message
    ChatBatchReceipt.__table__.drop(world[2])
    with world[2].begin() as connection: connection.exec_driver_sql('CREATE TABLE chat_batch_receipts (owner_key BLOB, request_key BLOB)')
    with world[1]() as db:
        row=save_chat_message(db,user_id='student',agent_mode='chat',role='user',content='Unrelated chat')
        target=row.id
    assert request(world,'DELETE',f'/chat/history/{target}?session_id=student').json()['status']=='success'
    with world[1]() as db: save_chat_message(db,user_id='student',agent_mode='tutor',role='user',content='Unrelated tutor')
    assert request(world,'DELETE','/chat/history?session_id=student&agent_mode=tutor').json()['status']=='success'


def test_readiness_header_keeps_exact_capability_body_and_revision(world):
    from app.models.chat_batch_receipt import ChatBatchReceipt
    from app.services.student_work_capabilities import student_work_capabilities
    ready=request(world,'GET','/student/work/capabilities')
    assert ready.json()==student_work_capabilities()
    assert ready.headers['x-gezhi-paper-batch-available']=='true'
    ChatBatchReceipt.__table__.drop(world[2])
    unavailable=request(world,'GET','/student/work/capabilities')
    assert unavailable.json()==ready.json() and unavailable.headers['x-gezhi-paper-batch-available']=='false'
    assert count(world)==0


def test_receipt_committed_pair_requires_two_nonnull_distinct_positive_ids(world):
    from app.models.chat_batch_receipt import ChatBatchReceipt
    from sqlalchemy.exc import IntegrityError
    with world[1]() as db:
        db.add(ChatBatchReceipt(owner_key=b'student',request_key=b'bad-ids',request_digest='a'*64,
            agent_mode='paper',state='committed',user_message_id=None,assistant_message_id=None))
        with pytest.raises(IntegrityError): db.commit()
        db.rollback()
    assert count(world,ChatBatchReceipt)==0


def test_keyed_paper_refuses_dirty_caller_and_never_commits_unrelated_row(world):
    from app.services.chat_batch_receipts import ChatBatchUnavailable
    payload=world[3]['SaveChatHistoryBatchRequest'].model_validate(batch())
    with world[1]() as db:
        db.add(ChatMessage(user_id='peer',agent_mode='chat',role='user',content='Unrelated pending caller write'))
        pending=next(iter(db.new))
        with pytest.raises(ChatBatchUnavailable):
            save_chat_messages_batch(db,user_id='student',agent_mode='paper',items=payload.messages,
                conversation_id=payload.conversation_id,project_id=payload.project_id,client_request_id=payload.client_request_id)
        assert pending in db.new, 'Refusal must preserve unrelated caller work'
        db.rollback()
    assert count(world)==0


def test_reserved_or_unknown_receipt_never_creates_messages_or_overwrites_digest(world):
    from app.models.chat_batch_receipt import ChatBatchReceipt
    payload=world[3]['SaveChatHistoryBatchRequest'].model_validate(batch())
    body={'agent_mode':'paper','conversation_id':payload.conversation_id,'project_id':payload.project_id,
        'items':[item.model_dump() for item in payload.messages]}
    import hashlib
    digest=hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    with world[1]() as db:
        db.add(ChatBatchReceipt(owner_key=b'student',request_key=b'paper-request',request_digest=digest,
            agent_mode='paper',conversation_id='paper-one',project_id='project-one',state='reserved'))
        db.commit()
    response=request(world,'POST','/chat/history/batch',json=batch())
    assert response.status_code==503 and count(world)==0
    with world[1]() as db:
        original=db.scalars(select(ChatBatchReceipt)).one()
        assert original.request_digest==digest and original.state=='reserved'


def test_commit_unknown_is_not_masked_by_cleanup_failure(world,monkeypatch):
    original=Session.commit
    def lose_ack(db):
        original(db)
        raise RuntimeError('synthetic commit acknowledgement lost')
    def rollback_fails(db): raise RuntimeError('synthetic cleanup connection unavailable')
    with monkeypatch.context() as patch:
        patch.setattr(Session,'commit',lose_ack)
        patch.setattr(Session,'rollback',rollback_fails)
        response=request(world,'POST','/chat/history/batch',json=batch())
    assert response.status_code==503 and response.json()['detail']=='CHAT_BATCH_COMMIT_UNKNOWN'
    assert count(world)==2


@pytest.mark.parametrize('defect',[None,'mysql8039-reflection','mysql8039-weaker-check','fixed-width-key','prefix-primary-key','latin1-column','wrong-table-collation','column-default','generated-column','unsigned-integer'])
def test_mysql_schema_adapter_rejects_non_exact_identity_keys(world,monkeypatch,defect):
    """Supplied MySQL observations only, not a native MySQL execution claim."""
    from types import SimpleNamespace
    from sqlalchemy import Integer, String, BINARY, VARBINARY
    from app.services import chat_batch_schema as schema
    from app.services.teacher_work import schema_mysql
    columns=[]
    for name,(kind,length,nullable) in schema.CONTRACT['columns'].items():
        value=VARBINARY(length) if kind=='binary' else String(length) if kind=='string' else Integer()
        if defect=='fixed-width-key' and name=='request_key': value=BINARY(length)
        columns.append({'name':name,'type':value,'nullable':nullable})
    class Observer:
        def get_table_names(self): return ['chat_batch_receipts','chat_messages']
        def get_columns(self,name): return columns
        def get_pk_constraint(self,name): return {'constrained_columns':['owner_key','request_key']}
        def get_unique_constraints(self,name): return []
        def get_foreign_keys(self,name): return []
        def get_indexes(self,name): return []
        def get_check_constraints(self,name):
            values=schema.CONTRACT['checks']
            if defect in ('mysql8039-reflection','mysql8039-weaker-check'):
                values=json.loads((ROOT/'tests/fixtures/chat_batch_mysql8039_checks.json').read_text())['reflection']
                if defect=='mysql8039-weaker-check':
                    values={**values,'ck_chat_batch_pair':values['ck_chat_batch_pair'].replace('`user_message_id` > 0','`user_message_id` >= 0')}
            return [{'name':k,'sqltext':v} for k,v in values.items()]
        def get_table_options(self,name): return {'mysql_engine':'InnoDB'}
    class Result:
        def __init__(self,value): self.value=value
        def mappings(self): return self
        def one(self): return self.value
        def scalar_one(self): return self.value
        def all(self): return self.value
    class Connection:
        dialect=SimpleNamespace(name='mysql')
        def execute(self,statement):
            sql=str(statement)
            if '@@session.autocommit' in sql: return Result({'autocommit':0,'unique_checks':1})
            if 'SELECT DATABASE()' in sql: return Result('synthetic-schema')
            if 'TABLE_CONSTRAINTS' in sql: return Result([(name,'YES') for name in schema.CONTRACT['checks']])
            if 'STATISTICS' in sql: return Result([('owner_key',None,0,1,'BTREE'),('request_key',4 if defect=='prefix-primary-key' else None,0,2,'BTREE')])
            if 'INFORMATION_SCHEMA.COLUMNS' in sql:
                rows=[]
                for name,(kind,length,nullable) in schema.CONTRACT['columns'].items():
                    family={'binary':'varbinary','string':'varchar','integer':'int'}[kind]
                    row={'column_name':name,'column_type':family+(f'({length})' if length else ''),'data_type':family,
                        'is_nullable':'YES' if nullable else 'NO','column_default':None,'extra':'','generation_expression':'',
                        'character_maximum_length':length,'character_octet_length':length*(4 if kind=='string' else 1) if length else None,
                        'character_set_name':'utf8mb4' if kind=='string' else None,'collation_name':'utf8mb4_bin' if kind=='string' else None}
                    if name=='request_digest':
                        if defect=='latin1-column': row.update(character_set_name='latin1',collation_name='latin1_swedish_ci',character_octet_length=64)
                        if defect=='column-default': row['column_default']='changed'
                        if defect=='generated-column': row.update(extra='STORED GENERATED',generation_expression="'changed'")
                    if name=='user_message_id' and defect=='unsigned-integer': row['column_type']='int unsigned'
                    rows.append(row)
                return Result(rows)
            if 'INFORMATION_SCHEMA.TABLES' in sql:
                return Result([{'table_type':'BASE TABLE','engine':'InnoDB','table_collation':'latin1_swedish_ci' if defect=='wrong-table-collation' else 'utf8mb4_bin',
                    'character_set_name':'latin1' if defect=='wrong-table-collation' else 'utf8mb4'}])
            return Result([])
    monkeypatch.setattr(schema,'inspect',lambda _:Observer())
    monkeypatch.setattr(schema_mysql,'_resolved_table_issues',lambda *args:[])
    assert schema.inspect_receipt_schema(Connection())==('ready' if defect in (None,'mysql8039-reflection') else 'incompatible')


def test_keyed_paper_never_commits_flushed_caller_write(world):
    from app.services.chat_batch_receipts import ChatBatchUnavailable
    payload=world[3]['SaveChatHistoryBatchRequest'].model_validate(batch())
    with world[1]() as db:
        unrelated=ChatMessage(user_id='peer',agent_mode='chat',role='user',content='Flushed caller row')
        db.add(unrelated); db.flush()
        try:
            save_chat_messages_batch(db,user_id='student',agent_mode='paper',items=payload.messages,
                conversation_id=payload.conversation_id,project_id=payload.project_id,client_request_id=payload.client_request_id)
        except ChatBatchUnavailable:
            pass
        with world[1]() as independent:
            assert independent.scalar(select(func.count()).select_from(ChatMessage).where(ChatMessage.user_id=='peer'))==0, 'Caller write was committed by batch helper'
        assert db.in_transaction() and db.get(ChatMessage,unrelated.id) is unrelated
        db.rollback()
    assert count(world)==0


def test_keyed_paper_refuses_external_connection_root_without_adopting_or_rolling_back(world):
    from app.services.chat_batch_receipts import ChatBatchUnavailable
    payload=world[3]['SaveChatHistoryBatchRequest'].model_validate(batch())
    with world[2].connect() as connection:
        root=connection.begin()
        with Session(bind=connection,autoflush=False) as db:
            with pytest.raises(ChatBatchUnavailable):
                save_chat_messages_batch(db,user_id='student',agent_mode='paper',items=payload.messages,
                    conversation_id=payload.conversation_id,project_id=payload.project_id,client_request_id=payload.client_request_id)
            assert root.is_active and connection.get_transaction() is root
        root.rollback()
    assert count(world)==0


def test_known_receipt_backed_paper_delete_refuses_missing_schema_without_resurrection(world):
    from app.models.chat_batch_receipt import ChatBatchReceipt
    response=request(world,'POST','/chat/history/batch',json=batch())
    assert response.json()['status']=='success'
    ChatBatchReceipt.__table__.drop(world[2])
    deletion=request(world,'DELETE','/chat/history?session_id=student&agent_mode=paper')
    assert deletion.status_code==503 and count(world)==2
    ChatBatchReceipt.__table__.create(world[2])
    replay=request(world,'POST','/chat/history/batch',json=batch())
    assert replay.status_code==200 and count(world)==2


def test_foreign_pair_association_refuses_mutation_while_digest_only_corruption_allows_owned_delete(world):
    from app.models.chat_batch_receipt import ChatBatchReceipt
    own=request(world,'POST','/chat/history/batch',json=batch()).json()['data']
    peer=request(world,'POST','/chat/history/batch',actor='peer',json=batch(owner='peer')).json()['data']
    with world[1]() as db:
        receipt=db.get(ChatBatchReceipt,(b'student',b'paper-request'))
        receipt.assistant_message_id=peer[1]['id'];db.commit()
    refused=request(world,'DELETE',f"/chat/history/{own[0]['id']}?session_id=student")
    assert refused.status_code==503 and count(world)==4
    with world[1]() as db:
        receipt=db.get(ChatBatchReceipt,(b'student',b'paper-request'))
        receipt.assistant_message_id=own[1]['id'];receipt.request_digest='b'*64;db.commit()
    allowed=request(world,'DELETE',f"/chat/history/{own[0]['id']}?session_id=student")
    assert allowed.json()['status']=='success' and count(world)==3
    assert request(world,'POST','/chat/history/batch',json=batch()).status_code==409
    assert len(request(world,'GET','/chat/history?session_id=peer&agent_mode=paper',actor='peer').json()['data'])==2


def test_pair_response_materializes_server_defaults_without_returning(world,monkeypatch):
    for name in ('insert_returning','insert_executemany_returning','use_insertmanyvalues'):
        monkeypatch.setattr(world[2].dialect,name,False)
    monkeypatch.setattr(ChatMessage.__table__,'implicit_returning',False)
    result=request(world,'POST','/chat/history/batch',json=batch())
    assert result.status_code==200 and result.json()['status']=='success', result.json()
    assert all(row['created_at'] for row in result.json()['data']) and count(world)==2
    assert request(world,'POST','/chat/history/batch',json=batch()).json()['data']==result.json()['data']


@pytest.mark.parametrize('operation',['single','clear'])
def test_paper_mutation_preserves_case_distinct_owner_under_nocase_transcript_collation(world,operation):
    from sqlalchemy.schema import CreateTable
    with world[2].begin() as connection:
        ChatMessage.__table__.drop(connection)
        sql=str(CreateTable(ChatMessage.__table__).compile(dialect=world[2].dialect))
        assert 'user_id VARCHAR(255) NOT NULL' in sql
        connection.exec_driver_sql(sql.replace('user_id VARCHAR(255) NOT NULL','user_id VARCHAR(255) COLLATE NOCASE NOT NULL'))
    with world[1]() as db:
        db.add(UserAccount(username='Student',role='student',password_hash=''));db.commit()
    victim=request(world,'POST','/chat/history/batch',actor='Student',json=batch(owner='Student')).json()['data']
    if operation=='single':
        result=request(world,'DELETE',f"/chat/history/{victim[0]['id']}?session_id=student")
        assert result.json()['status']=='error'
    else:
        result=request(world,'DELETE','/chat/history?session_id=student&agent_mode=paper')
        assert result.json()['data']['deleted_count']==0
    assert count(world)==2
    from app.models.chat_batch_receipt import ChatBatchReceipt
    with world[1]() as db:
        assert db.get(ChatBatchReceipt,(b'Student',b'paper-request')).state=='committed'


def test_owned_history_page_excludes_nocase_peer_rows_ids_counts_and_cursors(world):
    from sqlalchemy.schema import CreateTable
    with world[2].begin() as connection:
        ChatMessage.__table__.drop(connection)
        sql=str(CreateTable(ChatMessage.__table__).compile(dialect=world[2].dialect))
        connection.exec_driver_sql(sql.replace('user_id VARCHAR(255) NOT NULL','user_id VARCHAR(255) COLLATE NOCASE NOT NULL'))
    with world[1]() as db:
        db.add(UserAccount(username='Student',role='student',password_hash=''));db.commit()
    foreign=request(world,'POST','/chat/history/batch',actor='Student',json=batch(owner='Student')).json()['data']
    empty=request(world,'GET','/chat/history?session_id=student&agent_mode=paper&limit=1').json()
    assert empty['data']==[] and empty['pagination']['snapshot_max_id']==0 and empty['pagination']['next_cursor'] is None
    own=request(world,'POST','/chat/history/batch',json=batch()).json()['data']
    first=request(world,'GET','/chat/history?session_id=student&agent_mode=paper&limit=1').json()
    assert first['pagination']['snapshot_max_id']==max(row['id'] for row in own) and {row['id'] for row in first['data']}<={row['id'] for row in own}
    before=first['pagination']['next_cursor']
    assert before and first['pagination']['has_more']
    next_page=request(world,'GET','/chat/history?session_id=student&agent_mode=paper&limit=1&before='+before).json()
    assert next_page['pagination']['snapshot_max_id']==max(row['id'] for row in own) and next_page['pagination']['complete']
    combined=first['data']+next_page['data']
    assert {row['id'] for row in combined}=={row['id'] for row in own}
    assert {row['id'] for row in combined}.isdisjoint({row['id'] for row in foreign})


def test_native_mysql8039_reflection_matches_pinned_receipt_constraints():
    """Captured native syntax, not a dot/MySQL execution claim."""
    from app.services.chat_batch_schema import CONTRACT, _normalized_check
    captured=json.loads((ROOT/'tests/fixtures/chat_batch_mysql8039_checks.json').read_text())
    for name,expression in captured['reflection'].items():
        assert _normalized_check(expression)==_normalized_check(CONTRACT['checks'][name]), name
    assert _normalized_check(captured['reflection']['ck_chat_batch_pair'])==captured['expected_normalized_pair']


@pytest.mark.parametrize('left,right',[
    ('user_message_id != assistant_message_id','`user_message_id` <> `assistant_message_id`'),
    ("state <> 'reserved'","state != 'reserved'"),
])
def test_receipt_normalizer_accepts_equivalent_unquoted_not_equal_operators(left,right):
    from app.services.chat_batch_schema import _normalized_check
    assert _normalized_check(left)==_normalized_check(right)


@pytest.mark.parametrize('left,right',[
    ("label = '<>'","label = '!='"),
    ("label = 'x<>y'","label = 'x!=y'"),
    ('label = "<>"','label = "!="'),
    ('label = "it""s <>"','label = "it""s !="'),
    ("label = 'it''s <>'","label = 'it''s !='"),
    (r"label = 'it\'s <>'",r"label = 'it\'s !='"),
    ('user_message_id != assistant_message_id','user_message_id = assistant_message_id'),
    ('user_message_id != assistant_message_id','user_message_id <=> assistant_message_id'),
    ('user_message_id != assistant_message_id','user_message_id <= assistant_message_id'),
    ('(a=1 and b=2) or c=3','a=1 and (b=2 or c=3)'),
])
def test_receipt_normalizer_preserves_literal_operator_and_boolean_distinctions(left,right):
    from app.services.chat_batch_schema import _normalized_check
    assert _normalized_check(left)!=_normalized_check(right)
