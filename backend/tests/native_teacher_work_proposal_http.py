"""Explicit signed-identity/native SQL/ASGI/actual bridge MockTransport acceptance."""
import asyncio
from contextlib import asynccontextmanager
import json
from uuid import UUID
import pytest
from sqlalchemy import select,event,text,update
from app.models.teacher_work import WorkTask,WorkMessage,WorkRun,OutlineSnapshot,OutlineApproval,PackageVersion,OwnerRunLease
from app.models.teacher_work_proposals import MaterialProposalRecord
from tests.native_teacher_work_mysql import native_server,native_db
from tests.native_teacher_work_private_http import http_db,OWNER,OTHER,STUDENT,create_body
from tests.native_teacher_work_private_materials import material_db
from tests.native_teacher_work_proposal_repository import proposal_db,immutable_rows
from tests.test_teacher_work_private_materials import lesson,slides

@asynccontextmanager
async def client(db,monkeypatch,provider,*,timeout=5,capacity=4):
    from app.services.teacher_work import private_chat,private_proposals,execution_capacity
    from app.services.teacher_work.ai import LessonPrepWorkAI
    from app.services.teacher_lesson_prep.ai_client import LessonPrepAIClient
    monkeypatch.setattr(private_chat,'_runtime',None);monkeypatch.setattr(private_proposals,'_runtime',None)
    monkeypatch.setattr(execution_capacity,'_shared_capacity',None)
    for name,value in [('AI_LESSON_PREP_API_KEY','synthetic-owned-secret'),('AI_LESSON_PREP_BASE_URL','http://synthetic.invalid/chat/completions'),
        ('AI_LESSON_PREP_MODEL','synthetic-model'),('AI_LESSON_PREP_TIMEOUT_SECONDS',timeout),('AI_LESSON_PREP_MAX_OUTPUT_TOKENS',8192),('TEACHER_WORK_MAX_ACTIVE_RUNS',capacity)]:monkeypatch.setattr(db.settings,name,value)
    chat,proposal=private_chat.get_runtime(),private_proposals.get_runtime()
    assert chat.pool is proposal.pool
    checked=set()
    def checkout(conn,*_):checked.add(id(conn))
    def checkin(conn,*_):checked.discard(id(conn))
    event.listen(db.engine,'checkout',checkout);event.listen(db.engine,'checkin',checkin)
    async def transport(request):
        assert not checked,'SQL checkout retained during provider await'
        data=json.loads(request.content)
        db.row_observations.append({'actual_provider_request':data,'sql_checkouts_during_await':len(checked)})
        return await provider(request)
    for runtime in (chat,proposal):
        assert type(runtime.ai) is LessonPrepWorkAI and type(runtime.ai._lesson_client) is LessonPrepAIClient
        runtime.ai._lesson_client.client_factory=lambda **kw:db.httpx.AsyncClient(transport=db.httpx.MockTransport(transport),**kw)
    try:
        async with db.httpx.AsyncClient(transport=db.httpx.ASGITransport(app=db.app),base_url='http://synthetic.local') as http:yield http,chat,proposal
    finally:
        await chat.close();await proposal.close()
        event.remove(db.engine,'checkout',checkout);event.remove(db.engine,'checkin',checkin)

async def call(db,c,method,path,*,body=None,raw=None,key=None,owner=OWNER):
    headers={'Authorization':'Bearer '+db.tokens[owner]}
    if key:headers['Idempotency-Key']=key
    statements=[]
    def trace(conn,cursor,statement,params,ctx,many):statements.append(statement)
    if method=='GET' and 'material-proposals' in path:event.listen(db.engine,'before_cursor_execute',trace)
    try:
        response=await c.request(method,path,headers=headers,**({'content':raw} if raw is not None else {'json':body}))
    finally:
        if method=='GET' and 'material-proposals' in path:event.remove(db.engine,'before_cursor_execute',trace)
    if method=='GET' and 'material-proposals' in path:
        assert all(s.lstrip().upper().startswith(('SELECT','SHOW')) or s.strip().upper()=='DO 0' for s in statements)
        db.row_observations.append({'readonly_proposal_path':path,'sql_statements':statements})
    db.material_exchanges.append({'request':{'method':method,'path':path,'body':body,'raw_utf8':raw.decode() if raw else None,'idempotency_key':key},
        'response':{'status':response.status_code,'body':response.json(),'cache_control':response.headers.get('cache-control')},'response_utf8_bytes':len(response.content)})
    assert response.headers.get('cache-control')=='no-store'
    return response

def reply(db,raw):return db.httpx.Response(200,json={'choices':[{'message':{'content':raw}}]})
async def poll(db,c,path,owner=OWNER):
    for _ in range(200):
        value=await call(db,c,'GET',path,owner=owner)
        assert value.status_code==200,value.text
        if value.json()['data']['stage'] in ('COMPLETE','FAILED','CANCELLED'):return value.json()['data']
        await asyncio.sleep(.01)
    pytest.fail('finite run did not settle')
async def setup(db,c,key='task',owner=OWNER):
    value=await call(db,c,'POST','/api/teacher/work/tasks',key=key,body=create_body(resource_ids=[db.resource_id]),owner=owner)
    assert value.status_code==200,value.text
    path='/api/teacher/work/tasks/'+value.json()['data']['task_id']
    sent=await call(db,c,'POST',path+'/messages',key='chat-'+key,body={'kind':'chat','skill_ref':None,'input_revision':1,'payload':{'text':'Synthetic selected request','client_message_key':'message-'+key}},owner=owner)
    assert sent.status_code==200,sent.text
    assert (await poll(db,c,path+'/runs/'+sent.json()['data']['run_id'],owner=owner))['stage']=='COMPLETE'
    history=await call(db,c,'GET',path+'/messages',owner=owner);source=history.json()['data']['messages'][-1]['message_id']
    return path,dict(skill_ref='lesson_outline@1',input_revision=1,expected_revision=1,source_message_id=source)

def protected_rows(db):
    with db.engine.connect() as conn:
        return tuple([dict(r) for r in conn.execute(select(model.__table__)).mappings()] for model in (WorkTask,db.domain,WorkMessage,OutlineSnapshot,OutlineApproval,PackageVersion))

def test_actual_bridge_chat_then_proposal_receipt_poll_read_and_reopen(proposal_db,monkeypatch):
    db=proposal_db;requests=[]
    async def provider(request):
        data=json.loads(request.content);requests.append(data)
        return reply(db,json.dumps({'type':'revision_proposal','plain_text':'Synthetic classified selected assistant'} if len(requests)==1 else dict(lesson=lesson(),slides=slides())))
    async def run():
        async with client(db,monkeypatch,provider) as (c,chat,runtime):
            path,body=await setup(db,c);before=protected_rows(db)
            caps=await call(db,c,'GET','/api/teacher/work/material-proposals/capabilities')
            assert caps.status_code==200 and caps.json()['data']['generate'] is True,caps.text
            admitted=await call(db,c,'POST',path+'/material-proposals',body=body,key='outline')
            assert admitted.status_code==200,admitted.text
            run=admitted.json()['data'];assert run['stage']=='PENDING' and run['receipt']=={'operation':'generate','replayed':False}
            assert len(run)==17
            run_path=path+'/material-proposals/runs/'+run['run_id'];complete=await poll(db,c,run_path)
            assert complete['stage']=='COMPLETE' and complete['proposal_available'] is True
            result=await call(db,c,'GET',run_path+'/proposal');assert result.status_code==200,result.text
            read=result.json()['data'];assert set(read)=={'task_id','run_id','proposal','freshness'}
            assert read['freshness']==dict(adoptable=True,reason=None) and len(read['proposal'])==9
            assert read['proposal']['lesson']['citations']==[] and all(s['source_note']=='' and s['evidence_refs']==[] for s in read['proposal']['slides'])
            assert len(read['proposal']['slides'])==8 and read['proposal']['lesson']['duration_minutes']==45
            assert protected_rows(db)==before
            monkeypatch.setattr(db.settings,'AI_LESSON_PREP_API_KEY','');monkeypatch.setattr(db.settings,'TEACHER_WORK_PRIVATE_MATERIALS_ENABLED',False)
            replay=await call(db,c,'POST',path+'/material-proposals',body=body,key='outline')
            assert replay.status_code==200 and replay.json()['data']=={**complete,'receipt':{'operation':'generate','replayed':True}},replay.text
            changed=await call(db,c,'POST',path+'/material-proposals',body={**body,'expected_revision':2},key='outline')
            assert changed.status_code==409 and changed.json()['message']=='IDEMPOTENCY_CONFLICT'
            await runtime.close()
            cancel=await call(db,c,'POST',run_path+'/cancel',body={});assert cancel.status_code==200 and cancel.json()['data']==complete,cancel.text
            monkeypatch.setattr(__import__('app.services.teacher_work.private_proposals',fromlist=['_runtime']),'_runtime',None)
            reopened=await call(db,c,'GET',path+'/material-proposals/runs')
            assert reopened.status_code==200 and reopened.json()['data']=={'task_id':run['task_id'],'runs':[complete]},reopened.text
            assert len(requests)==2
            from app.services.teacher_work.proposals import PROPOSAL_SYSTEM_PROMPT_V1
            assert requests[1]['messages'][0]['content']==PROPOSAL_SYSTEM_PROMPT_V1
            assert json.loads(requests[1]['messages'][1]['content'])['transcript'][-1]['message_id']==body['source_message_id']
            immutable_rows(db)
    asyncio.run(run())

@pytest.mark.parametrize('defect',['duplicate','unknown','nonfinite','uuid','cancel','bodylimit','origin_duplicate'])
def test_strict_request_refusal_preserves_native_rows(proposal_db,monkeypatch,defect):
    db=proposal_db
    async def provider(request):return reply(db,json.dumps(dict(type='answer',plain_text='Synthetic reply')))
    async def run():
        async with client(db,monkeypatch,provider) as (c,chat,runtime):
            path,body=await setup(db,c);before=protected_rows(db);old=immutable_rows(db)
            raw=json.dumps(body).encode();url=path+'/material-proposals';message='INVALID_MATERIAL_PROPOSAL_REQUEST';status=422
            if defect=='duplicate':raw=raw[:-1]+b',"input_revision":1}'
            if defect=='unknown':raw=raw[:-1]+b',"model":"bad"}'
            if defect=='nonfinite':raw=raw[:-1]+b',"x":NaN}'
            if defect=='uuid':raw=json.dumps({**body,'source_message_id':body['source_message_id'].replace('-','')}).encode()
            if defect=='cancel':url+='/runs/'+str(UUID(int=99))+'/cancel';raw=b'{"unknown":1}';message='INVALID_MATERIAL_PROPOSAL_CANCEL_REQUEST'
            if defect=='bodylimit':raw=b' '*262145;message='REQUEST_BODY_TOO_LARGE';status=413
            if defect=='origin_duplicate':
                url=path+'/materials';raw=json.dumps(dict(expected_revision=1,input_revision=1,expected_outline_revision=0,lesson=lesson(),slides=slides(),origin_proposal_run_id=None)).encode()[:-1]+b',"origin_proposal_run_id":null}'
                message='INVALID_PRIVATE_MATERIAL_REQUEST'
            result=await call(db,c,'POST',url,raw=raw,key='invalid')
            assert result.status_code==status and result.json()==dict(code=status,message=message,data=None),result.text
            assert protected_rows(db)==before and immutable_rows(db)==old
    asyncio.run(run())


def test_capabilities_closed_extension_absent_factual_config_and_authority(proposal_db,monkeypatch):
    db=proposal_db
    async def provider(request):return reply(db,json.dumps(dict(type='answer',plain_text='Synthetic reply')))
    async def run():
        async with client(db,monkeypatch,provider) as (c,chat,runtime):
            path='/api/teacher/work/material-proposals/capabilities'
            monkeypatch.setattr(db.settings,'TEACHER_WORK_PRIVATE_MATERIAL_PROPOSALS_ENABLED',False)
            before=protected_rows(db)
            closed=await call(db,c,'GET',path);assert closed.status_code==200,closed.text
            data=closed.json()['data'];assert set(data)=={'skill_ref','generate','read','cancel','provider_configured','external_provider_verified','reasons','limits'}
            assert data['provider_configured'] is True and data['external_provider_verified'] is False
            assert data['reasons']=={x:'private_material_proposals_disabled' for x in ('generate','read','cancel')}
            monkeypatch.setattr(db.settings,'TEACHER_WORK_PRIVATE_MATERIAL_PROPOSALS_ENABLED',True)
            with db.engine.begin() as conn:conn.execute(text("DELETE FROM teacher_work_schema_versions WHERE component='teacher_work_material_proposals'"))
            absent=await call(db,c,'GET',path);assert absent.status_code==200,absent.text
            assert absent.json()['data']['reasons']=={x:'proposal_schema_unavailable' for x in ('generate','read','cancel')}
            denied=await call(db,c,'GET',path,owner=STUDENT);assert denied.status_code==403 and denied.json()['message']=='CURRENT_TEACHER_REQUIRED'
            assert protected_rows(db)==before
    asyncio.run(run())


def test_missing_key_and_noncanonical_path_are_controlled_native_http(proposal_db,monkeypatch):
    db=proposal_db
    async def provider(request):return reply(db,json.dumps(dict(type='answer',plain_text='Synthetic reply')))
    async def run():
        async with client(db,monkeypatch,provider) as (c,chat,runtime):
            path,body=await setup(db,c);old=immutable_rows(db)
            for key in (None,' ', 'x'*129):
                result=await call(db,c,'POST',path+'/material-proposals',key=key,body=body)
                assert result.status_code==422 and result.json()['message']=='INVALID_MATERIAL_PROPOSAL_REQUEST',result.text
            for task_id in ('not-uuid',path.rsplit('/',1)[1].replace('-',''),path.rsplit('/',1)[1].upper()):
                base='/api/teacher/work/tasks/'+task_id+'/material-proposals'
                result=await call(db,c,'POST',base,key='path',body=body)
                assert result.status_code==422 and result.json()['message']=='INVALID_MATERIAL_PROPOSAL_REQUEST'
                result=await call(db,c,'POST',base+'/runs/'+str(UUID(int=8))+'/cancel',body={})
                assert result.status_code==422 and result.json()['message']=='INVALID_MATERIAL_PROPOSAL_CANCEL_REQUEST'
            assert immutable_rows(db)==old
    asyncio.run(run())


@pytest.mark.parametrize('failure,code',[('rate','WORK_AI_RATE_LIMITED'),('upstream','WORK_AI_UPSTREAM_FAILED'),
    ('malformed','WORK_AI_INVALID_RESPONSE'),('duplicate','INVALID_MATERIAL_PROPOSAL_RESPONSE'),('duration','INVALID_MATERIAL_PROPOSAL_RESPONSE')])
def test_actual_provider_failure_is_single_attempt_controlled_and_unchanged(proposal_db,monkeypatch,failure,code):
    db=proposal_db;calls=[]
    async def provider(request):
        data=json.loads(request.content)
        from app.services.teacher_work.proposals import PROPOSAL_SYSTEM_PROMPT_V1
        if data['messages'][0]['content']!=PROPOSAL_SYSTEM_PROMPT_V1:return reply(db,json.dumps(dict(type='answer',plain_text='Synthetic selected reply')))
        calls.append(data)
        if failure in ('rate','upstream'):return db.httpx.Response(429 if failure=='rate' else 502,text='private upstream diagnostic')
        if failure=='malformed':return db.httpx.Response(200,content=b'not JSON')
        if failure=='duplicate':return reply(db,'{"lesson":{},"lesson":{},"slides":[]}')
        content=dict(lesson=lesson(),slides=slides());content['lesson']['duration_minutes']=44;content['lesson']['teaching_flow'][0]['minutes']=44
        return reply(db,json.dumps(content))
    async def run():
        async with client(db,monkeypatch,provider) as (c,chat,runtime):
            path,body=await setup(db,c);old=protected_rows(db)
            admitted=await call(db,c,'POST',path+'/material-proposals',body=body,key='failure');assert admitted.status_code==200,admitted.text
            run_path=path+'/material-proposals/runs/'+admitted.json()['data']['run_id']
            terminal=await poll(db,c,run_path)
            assert terminal['stage']=='FAILED' and terminal['error_code']==code and terminal['provider_call_count']==1,terminal
            read=await call(db,c,'GET',run_path+'/proposal');assert read.json()['data']['proposal'] is None
            replay=await call(db,c,'POST',path+'/material-proposals',body=body,key='failure');assert replay.status_code==200
            assert len(calls)==1 and protected_rows(db)==old and not runtime.execution._slots
            assert 'private upstream diagnostic' not in json.dumps(db.material_exchanges)
            immutable_rows(db)
    asyncio.run(run())


@pytest.mark.parametrize('change',['source','input','role'])
def test_current_freshness_authority_and_foreign_ownership(proposal_db,monkeypatch,change):
    db=proposal_db
    async def provider(request):
        from app.services.teacher_work.proposals import PROPOSAL_SYSTEM_PROMPT_V1
        candidate=json.loads(request.content)['messages'][0]['content']==PROPOSAL_SYSTEM_PROMPT_V1
        return reply(db,json.dumps(dict(lesson=lesson(),slides=slides()) if candidate else dict(type='answer',plain_text='Synthetic selected')))
    async def run():
        async with client(db,monkeypatch,provider) as (c,chat,runtime):
            path,body=await setup(db,c)
            admitted=await call(db,c,'POST',path+'/material-proposals',body=body,key='freshness');assert admitted.status_code==200,admitted.text
            run_path=path+'/material-proposals/runs/'+admitted.json()['data']['run_id'];assert (await poll(db,c,run_path))['stage']=='COMPLETE'
            for url in (path+'/material-proposals/runs',run_path,run_path+'/proposal'):
                denied=await call(db,c,'GET',url,owner=OTHER);assert denied.status_code==404 and denied.json()['data'] is None
            if change=='source':db.source_file.write_bytes(b'synthetic changed bytes')
            if change=='input':
                changed=await call(db,c,'PATCH',path+'/working',body=dict(expected_revision=1,changes=dict(requirements='Current changed input')))
                assert changed.status_code==200
            if change=='role':
                with db.engine.begin() as conn:conn.execute(update(db.user).where(db.user.username==OWNER).values(role='student'))
            old=immutable_rows(db)
            result=await call(db,c,'GET',run_path+'/proposal')
            if change=='role':assert result.status_code==403 and result.json()['message']=='CURRENT_TEACHER_REQUIRED'
            else:
                assert result.status_code==200 and result.json()['data']['proposal'] is not None
                assert result.json()['data']['freshness']==dict(adoptable=False,reason='SOURCE_CHANGED' if change=='source' else 'STALE_INPUT_REVISION')
            assert immutable_rows(db)==old
    asyncio.run(run())


def is_proposal(request):
    from app.services.teacher_work.proposals import PROPOSAL_SYSTEM_PROMPT_V1
    return json.loads(request.content)['messages'][0]['content']==PROPOSAL_SYSTEM_PROMPT_V1


@pytest.mark.parametrize('trigger',['cancel','timeout'])
@pytest.mark.parametrize('stubborn',[False,True])
def test_actual_bridge_cancel_timeout_stubborn_late_result(proposal_db,monkeypatch,trigger,stubborn):
    db=proposal_db
    async def run():
        entered=asyncio.Event();cancelled=asyncio.Event();release=asyncio.Event();terminated=asyncio.Event();calls=[]
        async def provider(request):
            if not is_proposal(request):return reply(db,json.dumps(dict(type='answer',plain_text='Synthetic selected')))
            calls.append(1);entered.set()
            try:
                try:await release.wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    if not stubborn:raise
                    await release.wait()
                return reply(db,json.dumps(dict(lesson=lesson(),slides=slides())))
            finally:terminated.set()
        async with client(db,monkeypatch,provider,timeout=3 if trigger=='timeout' else 10) as (c,chat,runtime):
            path,body=await setup(db,c);old=protected_rows(db)
            admitted=await call(db,c,'POST',path+'/material-proposals',body=body,key='cancel-or-timeout');assert admitted.status_code==200,admitted.text
            run_id=admitted.json()['data']['run_id'];url=path+'/material-proposals/runs/'+run_id
            await asyncio.wait_for(entered.wait(),10)
            local=runtime.execution._runs[UUID(run_id)]
            if trigger=='cancel':
                response=await call(db,c,'POST',url+'/cancel',body={})
                assert response.status_code==200 and response.json()['data']['stage']=='CANCELLED',response.text
            await asyncio.wait_for(cancelled.wait(),10)
            if stubborn:
                assert runtime.execution._slots and not terminated.is_set()
                rows=immutable_rows(db);exact=next(r for r in rows[2] if r['run_id']==run_id)
                assert exact['active_call_no']==1 and rows[3][0]['active_run_id']==run_id
                assert not any(r['record_type']=='result' for r in rows[0])
            release.set();await asyncio.wait_for(asyncio.shield(local.supervisor),10)
            terminal=await poll(db,c,url)
            assert terminal['stage']==('CANCELLED' if trigger=='cancel' else 'FAILED') and terminal['proposal_available'] is False
            if trigger=='timeout':assert terminal['error_code']=='WORK_AI_TIMEOUT'
            assert calls==[1] and terminated.is_set() and not runtime.execution._slots and protected_rows(db)==old
            if trigger=='cancel':
                repeated=await call(db,c,'POST',url+'/cancel',body={});assert repeated.json()['data']==terminal
            rows=immutable_rows(db);assert rows[3][0]['active_run_id'] is None
    asyncio.run(run())


def test_shared_native_chat_proposal_capacity_both_directions(proposal_db,monkeypatch):
    db=proposal_db
    async def run():
        block={'proposal':False,'chat':False};entered=asyncio.Event();release=asyncio.Event();counts={'proposal':0,'chat':0}
        async def provider(request):
            kind='proposal' if is_proposal(request) else 'chat';counts[kind]+=1
            if block[kind]:
                entered.set();await release.wait()
            return reply(db,json.dumps(dict(lesson=lesson(),slides=slides()) if kind=='proposal' else dict(type='answer',plain_text='Synthetic reply')))
        async with client(db,monkeypatch,provider,capacity=1,timeout=20) as (c,chat,runtime):
            path,body=await setup(db,c,key='owner');other,other_body=await setup(db,c,key='other',owner=OTHER)
            block['proposal']=True
            admitted=await call(db,c,'POST',path+'/material-proposals',body=body,key='hold');assert admitted.status_code==200,admitted.text
            await entered.wait();assert len(chat.execution._slots)==1
            blocked=await call(db,c,'POST',other+'/messages',owner=OTHER,key='blocked-chat',body={'kind':'chat','skill_ref':None,'input_revision':1,'payload':{'text':'Blocked','client_message_key':'blocked'}})
            assert blocked.status_code==429 and blocked.json()['message']=='INSTANCE_BUSY',blocked.text
            replay=await call(db,c,'POST',path+'/material-proposals',body=body,key='hold');assert replay.status_code==200 and replay.json()['data']['receipt']['replayed'] is True
            local=runtime.execution._runs[UUID(admitted.json()['data']['run_id'])];release.set();await local.supervisor
            assert counts==dict(proposal=1,chat=2) and not runtime.execution._slots
            block['chat']=True;entered.clear();release.clear()
            sent=await call(db,c,'POST',other+'/messages',owner=OTHER,key='holding-chat',body={'kind':'chat','skill_ref':None,'input_revision':1,'payload':{'text':'Held','client_message_key':'held'}})
            assert sent.status_code==200,sent.text
            await entered.wait()
            blocked=await call(db,c,'POST',path+'/material-proposals',body=body,key='blocked-proposal')
            assert blocked.status_code==429 and blocked.json()['message']=='INSTANCE_BUSY',blocked.text
            release.set();await poll(db,c,other+'/runs/'+sent.json()['data']['run_id'],owner=OTHER)
            assert not runtime.execution._slots and counts==dict(proposal=1,chat=3)
            immutable_rows(db)
    asyncio.run(run())


@pytest.mark.parametrize('stage',['admission','reservation','completion'])
@pytest.mark.parametrize('ack',['before','after'])
def test_actual_dbapi_unknown_ack_no_redispatch_or_write_retry(proposal_db,monkeypatch,stage,ack):
    import pymysql
    db=proposal_db
    async def run():
        calls=[]
        async def provider(request):
            if not is_proposal(request):return reply(db,json.dumps(dict(type='answer',plain_text='Synthetic selected')))
            calls.append(1);return reply(db,json.dumps(dict(lesson=lesson(),slides=slides())))
        async with client(db,monkeypatch,provider,timeout=30) as (c,chat,runtime):
            path,body=await setup(db,c);old=protected_rows(db)
            target={};original=pymysql.connections.Connection.commit
            prefix='INSERT INTO TEACHER_WORK_RUNS' if stage=='admission' else 'UPDATE TEACHER_WORK_RUNS' if stage=='reservation' else 'INSERT INTO TEACHER_WORK_MATERIAL_PROPOSAL_RECORDS'
            def trace(conn,cursor,statement,params,ctx,many):
                if statement.lstrip().upper().startswith(prefix) and (stage!='completion' or (isinstance(params,dict) and params.get('record_type')=='result')):
                    target['connection']=conn.connection.driver_connection
            def lose(connection):
                if connection is target.get('connection'):
                    target['faults']=target.get('faults',0)+1
                    if ack=='after':original(connection);target['committed']=True
                    raise pymysql.OperationalError(2013,'synthetic private unknown ack')
                return original(connection)
            event.listen(db.engine,'before_cursor_execute',trace)
            try:
                with monkeypatch.context() as patch:
                    patch.setattr(pymysql.connections.Connection,'commit',lose)
                    admitted=await call(db,c,'POST',path+'/material-proposals',body=body,key='unknown')
                    if stage=='admission':
                        assert admitted.status_code==503 and admitted.json()['message']=='COMMIT_OUTCOME_UNKNOWN',admitted.text
                        assert set(admitted.json()['data'])=={'run_id'}
                        run_id=admitted.json()['data']['run_id']
                    else:
                        assert admitted.status_code==200,admitted.text
                        run_id=admitted.json()['data']['run_id'];local=runtime.execution._runs[UUID(run_id)]
                        await local.supervisor
            finally:event.remove(db.engine,'before_cursor_execute',trace)
            assert target['faults']==1
            expected_calls=1 if stage=='completion' else 0
            assert len(calls)==expected_calls and protected_rows(db)==old
            before=immutable_rows(db)
            observed=await call(db,c,'GET',path+'/material-proposals/runs/'+run_id)
            if stage=='admission' and ack=='before':assert observed.status_code==404
            else:
                assert observed.status_code==200,observed.text
                expected='PENDING' if stage=='admission' or stage=='reservation' and ack=='before' else 'COMPLETE' if stage=='completion' and ack=='after' else 'OUTLINE_RUNNING'
                assert observed.json()['data']['stage']==expected
                replay=await call(db,c,'POST',path+'/material-proposals',body=body,key='unknown')
                assert replay.status_code==200 and replay.json()['data']['receipt']['replayed'] is True
                assert len(calls)==expected_calls
            assert immutable_rows(db)==before
            assert bool(runtime.execution._slots)==(stage!='completion' or ack=='before')
            db.row_observations.append({'unknown_stage':stage,'ack':ack,'actual_dbapi_commit_faults':target['faults'],'provider_invocations':len(calls),'fresh_get_rows_unchanged':True})
    asyncio.run(run())


def test_final_monotonic_deadline_with_utc_rewind_rolls_back_candidate(proposal_db,monkeypatch):
    db=proposal_db
    async def run():
        calls=[]
        async def provider(request):
            if not is_proposal(request):return reply(db,json.dumps(dict(type='answer',plain_text='Synthetic selected')))
            calls.append(1);return reply(db,json.dumps(dict(lesson=lesson(),slides=slides())))
        async with client(db,monkeypatch,provider,timeout=30) as (c,chat,runtime):
            path,body=await setup(db,c);before=protected_rows(db)
            from app.services.teacher_work.bootstrap import _SessionWorkTransport
            from app.services.teacher_work import private_proposals
            from datetime import datetime,timezone,timedelta
            original_flush=_SessionWorkTransport.flush;original_monotonic=runtime.execution.clock.monotonic
            value={'advance':False};utc=datetime.now(timezone.utc)
            def trace(conn,cursor,statement,params,ctx,many):
                if statement.lstrip().upper().startswith('INSERT INTO TEACHER_WORK_MATERIAL_PROPOSAL_RECORDS') and isinstance(params,dict) and params.get('record_type')=='result':
                    value['result_inserted']=True
            def advance(transport):
                original_flush(transport)
                if value.get('result_inserted'):value['advance']=True
            event.listen(db.engine,'before_cursor_execute',trace)
            try:
                with monkeypatch.context() as patch:
                    patch.setattr(_SessionWorkTransport,'flush',advance)
                    patch.setattr(runtime.execution.clock,'monotonic',lambda:original_monotonic()+100 if value['advance'] else original_monotonic())
                    patch.setattr(private_proposals,'_now',lambda:utc-timedelta(days=1) if value['advance'] else datetime.now(timezone.utc))
                    admitted=await call(db,c,'POST',path+'/material-proposals',body=body,key='monotonic-final');assert admitted.status_code==200,admitted.text
                    local=runtime.execution._runs[UUID(admitted.json()['data']['run_id'])];await local.supervisor
            finally:event.remove(db.engine,'before_cursor_execute',trace)
            assert value['advance'] and calls==[1]
            result=await call(db,c,'GET',path+'/material-proposals/runs/'+admitted.json()['data']['run_id'])
            assert result.status_code==200 and result.json()['data']['stage']=='FAILED' and result.json()['data']['error_code']=='PROPOSAL_DEADLINE_EXPIRED',result.text
            assert protected_rows(db)==before and not runtime.execution._slots
            rows=immutable_rows(db);assert not any(r['record_type']=='result' for r in rows[0]) and rows[3][0]['active_run_id'] is None
            db.row_observations.append({'monotonic_advanced_after_final_flush':True,'utc_rewound_days':1,'result_rolled_back':True,'provider_invocations':1})
    asyncio.run(run())


def test_duplicate_http_admission_and_twenty_retained_run_limit(proposal_db,monkeypatch):
    db=proposal_db
    async def run():
        calls=[]
        async def provider(request):
            if not is_proposal(request):return reply(db,json.dumps(dict(type='answer',plain_text='Synthetic selected')))
            calls.append(1);return db.httpx.Response(429,text='synthetic private upstream')
        async with client(db,monkeypatch,provider,timeout=30) as (c,chat,runtime):
            path,body=await setup(db,c);old=protected_rows(db)
            first,second=await asyncio.gather(call(db,c,'POST',path+'/material-proposals',body=body,key='duplicate'),call(db,c,'POST',path+'/material-proposals',body=body,key='duplicate'))
            assert first.status_code==second.status_code==200
            assert first.json()['data']['run_id']==second.json()['data']['run_id']
            assert {first.json()['data']['receipt']['replayed'],second.json()['data']['receipt']['replayed']}=={False,True}
            local=runtime.execution._runs[UUID(first.json()['data']['run_id'])];await local.supervisor
            for i in range(1,20):
                admitted=await call(db,c,'POST',path+'/material-proposals',body=body,key='retained-'+str(i))
                assert admitted.status_code==200,admitted.text
                local=runtime.execution._runs[UUID(admitted.json()['data']['run_id'])];await local.supervisor
            listed=await call(db,c,'GET',path+'/material-proposals/runs');assert listed.status_code==200 and len(listed.json()['data']['runs'])==20
            assert all(r['receipt'] is None and r['stage']=='FAILED' for r in listed.json()['data']['runs'])
            before=immutable_rows(db)
            rejected=await call(db,c,'POST',path+'/material-proposals',body=body,key='twenty-first')
            assert rejected.status_code==409 and rejected.json()['message']=='PROPOSAL_RUN_LIMIT',rejected.text
            assert len(calls)==20 and immutable_rows(db)==before and protected_rows(db)==old
            assert not runtime.execution._slots
    asyncio.run(run())


def test_actual_manual_draft_projection_rejects_oversized_provider_candidate(proposal_db,monkeypatch):
    db=proposal_db
    async def run():
        calls=[];candidate=dict(lesson=lesson(),slides=slides())
        candidate['lesson']['objectives']=['x'*2000]*20;candidate['lesson']['key_points']=['y'*2000]*20
        async def provider(request):
            if not is_proposal(request):return reply(db,json.dumps(dict(type='answer',plain_text='Synthetic selected')))
            calls.append(1);return reply(db,json.dumps(candidate))
        async with client(db,monkeypatch,provider,timeout=30) as (c,chat,runtime):
            path,body=await setup(db,c);before=protected_rows(db)
            admitted=await call(db,c,'POST',path+'/material-proposals',body=body,key='oversized-draft');assert admitted.status_code==200,admitted.text
            terminal=await poll(db,c,path+'/material-proposals/runs/'+admitted.json()['data']['run_id'])
            assert terminal['stage']=='FAILED' and terminal['error_code']=='PROPOSAL_DRAFT_TOO_LARGE',terminal
            assert calls==[1] and protected_rows(db)==before and not runtime.execution._slots
            rows=immutable_rows(db);assert not any(r['record_type']=='result' for r in rows[0])
    asyncio.run(run())


@pytest.mark.parametrize('setting,value',[('TEACHER_WORK_MAX_ACTIVE_RUNS',1),('TEACHER_WORK_MAX_ACTIVE_RUNS',0),
    ('AI_LESSON_PREP_TIMEOUT_SECONDS',4),('AI_LESSON_PREP_MAX_OUTPUT_TOKENS',8191)])
def test_existing_runtime_current_config_change_fails_new_post_but_replay_survives(proposal_db,monkeypatch,setting,value):
    db=proposal_db
    async def run():
        calls=[]
        async def provider(request):
            if not is_proposal(request):return reply(db,json.dumps(dict(type='answer',plain_text='Synthetic selected')))
            calls.append(1);return reply(db,json.dumps(dict(lesson=lesson(),slides=slides())))
        async with client(db,monkeypatch,provider,timeout=5,capacity=4) as (c,chat,runtime):
            path,body=await setup(db,c)
            admitted=await call(db,c,'POST',path+'/material-proposals',body=body,key='original');assert admitted.status_code==200,admitted.text
            url=path+'/material-proposals/runs/'+admitted.json()['data']['run_id'];complete=await poll(db,c,url)
            assert complete['stage']=='COMPLETE'
            pool=runtime.pool;old=immutable_rows(db);monkeypatch.setattr(db.settings,setting,value)
            replay=await call(db,c,'POST',path+'/material-proposals',body=body,key='original')
            assert replay.status_code==200 and replay.json()['data']=={**complete,'receipt':{'operation':'generate','replayed':True}},replay.text
            new=await call(db,c,'POST',path+'/material-proposals',body=body,key='new-config')
            assert new.status_code==503 and new.json()==dict(code=503,message='PROPOSAL_RUNTIME_UNAVAILABLE',data=None),new.text
            caps=await call(db,c,'GET','/api/teacher/work/material-proposals/capabilities')
            assert caps.status_code==200 and caps.json()['data']['reasons']==dict(generate='proposal_runtime_unavailable'),caps.text
            assert caps.json()['data']['read'] is True and caps.json()['data']['cancel'] is True
            cancelled=await call(db,c,'POST',url+'/cancel',body={})
            assert cancelled.status_code==200 and cancelled.json()['data']==complete
            if setting=='TEACHER_WORK_MAX_ACTIVE_RUNS':
                sent=await call(db,c,'POST',path+'/messages',key='chat-config',body=dict(kind='chat',skill_ref=None,input_revision=1,payload=dict(text='Current changed capacity',client_message_key='config')))
                assert sent.status_code==503 and sent.json()['message']=='CHAT_RUNTIME_UNAVAILABLE',sent.text
            assert immutable_rows(db)==old and calls==[1] and runtime.pool is chat.pool is pool and not pool.slots
    asyncio.run(run())
