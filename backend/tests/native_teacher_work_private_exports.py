"""Explicit-only private Office exports: owned actual MySQL/JWT/ASGI/bytes."""
from pathlib import Path
import importlib
import json
import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4
from hashlib import sha256
from dataclasses import asdict
from dataclasses import replace
import pytest
from sqlalchemy import text,event
from sqlalchemy.exc import DBAPIError
from tests.native_teacher_work_mysql import native_server, native_db, prepare
from tests.native_teacher_work_private_http import http_db
from tests.native_teacher_work_private_materials import material_db,setup,request,approval_body


def export_setup(db,monkeypatch):
    task,path,body=setup(db)
    saved=request(db,'POST',path,body=body,key='export-save').json()['data']
    approved=request(db,'POST',path+'/approve',body=approval_body(saved),key='export-approve').json()['data']
    migration=importlib.import_module('migrations.v20261006_teacher_work_exports_mysql')
    with db.engine.connect() as c:assert migration.apply_teacher_work_exports_mysql(c,db.identity).completed
    root=db.evidence/('private-export-'+task['task_id']);root.mkdir(mode=0o700)
    monkeypatch.setattr(db.settings,'TEACHER_WORK_STORAGE_ROOT',str(root))
    monkeypatch.setattr(db.settings,'TEACHER_WORK_PRIVATE_EXPORTS_ENABLED',True)
    url=path.removesuffix('/materials')+'/packages'
    create_body={**approval_body(saved),'approval_id':approved['approval']['approval_id'],'expected_revision':approved['working_revision']}
    return task,url,create_body


@pytest.fixture
def export_db(material_db,monkeypatch):
    db=material_db
    db.export_task,db.export_url,db.export_body=export_setup(db,monkeypatch)
    return db


def package_create(db,key='manual-package'):
    return request(db,'POST',db.export_url,body=db.export_body,key=key)


def package_rows(db):
    with db.engine.connect() as c:
        keys={'teacher_work_runs':'run_id','teacher_work_package_versions':'version_id','teacher_work_artifacts':'artifact_id','teacher_work_owner_run_leases':'owner'}
        result={name:[dict(row) for row in c.execute(text('SELECT * FROM '+name+' ORDER BY '+keys[name])).mappings()] for name in (
            'teacher_work_runs','teacher_work_package_versions','teacher_work_artifacts','teacher_work_owner_run_leases')}
        db.row_observations.append({'package_connection_id':c.scalar(text('SELECT CONNECTION_ID()')),'package_rows':result})
        return result


def test_migrated_v3_preserves_authenticated_cru_materials_and_chat(material_db,monkeypatch):
    """Same actual database before/after migration; provider stays in MockTransport."""
    from tests.native_teacher_work_private_http import create_body,OTHER,STUDENT
    from tests.native_teacher_work_private_chat_http import chat_client,call,chat_command,reply,terminal
    db=material_db;provider_calls=[]
    assert db.settings.TEACHER_WORK_PRIVATE_EXPORTS_ENABLED is False
    async def provider(request):
        provider_calls.append(json.loads(request.content))
        return reply(db)
    async def scenario():
        async with chat_client(db,monkeypatch,provider) as (client,runtime):
            async def captured(method,path,*,body=None,key=None,owner=None):
                kwargs={'body':body,'key':key}
                if owner is not None:kwargs['owner']=owner
                response=await call(db,client,method,path,**kwargs)
                db.material_exchanges.append({'request':{'method':method,'path':path,'body':body,'idempotency_key':key},
                    'response':{'status':response.status_code,'body':response.json()},'response_utf8_bytes':len(response.content)})
                return response
            before=(await captured('GET','/api/teacher/work/capabilities')).json()['data']
            material_before=(await captured('GET','/api/teacher/work/materials/capabilities')).json()['data']
            migration=importlib.import_module('migrations.v20261006_teacher_work_exports_mysql')
            with db.engine.connect() as connection:
                report=migration.apply_teacher_work_exports_mysql(connection,db.identity)
                assert report.completed
            after=(await captured('GET','/api/teacher/work/capabilities')).json()['data']
            assert after==before
            assert after['private_tasks']=={'create':True,'read':True,'update':True}
            assert after['private_chat']=={'send':True,'history':True,'read_run':True,'cancel':True,
                'provider_configured':True,'external_provider_verified':False}
            assert (await captured('GET','/api/teacher/work/materials/capabilities')).json()['data']==material_before
            off=(await captured('GET','/api/teacher/work/packages/capabilities')).json()['data']
            assert off=={**dict.fromkeys(('create','read','retry','download','storage_configured'),False),
                'reasons':dict.fromkeys(('create','read','retry','download','storage_configured'),'private_exports_disabled')}
            created=await captured('POST','/api/teacher/work/tasks',body=create_body(resource_ids=[db.resource_id]),key='v3-cru')
            assert created.status_code==200,created.text
            path='/api/teacher/work/tasks/'+created.json()['data']['task_id']
            assert (await captured('GET',path)).json()['data']==created.json()['data']
            patched=await captured('PATCH',path+'/working',body={'expected_revision':1,'changes':{'requirements':'同库 v3 合成要求'}})
            assert patched.status_code==200 and patched.json()['data']['input_revision']==2
            from tests.test_teacher_work_private_materials import lesson,slides
            saved=await captured('POST',path+'/materials',body={'expected_revision':2,'input_revision':2,
                'expected_outline_revision':0,'lesson':lesson(),'slides':slides()},key='v3-material-save')
            assert saved.status_code==200,saved.text
            approved=await captured('POST',path+'/materials/approve',body=approval_body(saved.json()['data']),key='v3-material-approve')
            assert approved.status_code==200,approved.text
            material=(await captured('GET',path+'/materials')).json()['data']
            task=(await captured('GET',path)).json()['data']
            stale=await captured('POST',path+'/messages',body=chat_command('v3-stale',revision=2),key='v3-stale')
            assert stale.status_code==409 and stale.json()['message']=='STALE_INPUT_REVISION'
            assert not provider_calls
            command=chat_command('v3-chat-message',revision=task['input_revision'])
            admitted=await captured('POST',path+'/messages',body=command,key='v3-chat-send')
            assert admitted.status_code==200,admitted.text
            done=await terminal(db,client,path,admitted.json()['data']['run_id'])
            assert done['stage']=='COMPLETE' and done['provider_call_count']==1
            history=await captured('GET',path+'/messages')
            assert history.status_code==200 and [m['role'] for m in history.json()['data']['messages']]==['user','assistant']
            replay=await captured('POST',path+'/messages',body=command,key='v3-chat-send')
            assert replay.json()['data']==done and len(provider_calls)==1
            assert (await captured('GET',path)).json()['data']==task
            assert (await captured('GET',path+'/materials')).json()['data']==material
            assert (await captured('GET',path+'/messages',owner=OTHER)).status_code==404
            assert (await captured('GET',path+'/messages',owner=STUDENT)).status_code==403
            assert (await captured('GET','/api/teacher/work/capabilities')).json()['data']==before
            with db.engine.connect() as connection:
                from app.services.teacher_work.schema_mysql_v3 import observe_teacher_work_mysql_v3
                observation=observe_teacher_work_mysql_v3(connection)
                assert observation.ready
                assert connection.scalar(text('SELECT COUNT(*) FROM teacher_work_messages'))==2
                assert connection.scalar(text('SELECT active_run_id FROM teacher_work_owner_run_leases')) is None
                db.row_observations.append({'same_migrated_v3_connection_id':connection.scalar(text('SELECT CONNECTION_ID()')),
                    'contract_hash':observation.observation['contract_hash'],'chat_calls':len(provider_calls),'messages':2})
    asyncio.run(scenario())


def test_single_format_failure_retry_keeps_ready_bytes(export_db,monkeypatch):
    from app.services.teacher_work import office_execution
    db=export_db;original=office_execution.build_validated_office
    def fail_one(kind,*args,**kwargs):
        if kind=='pptx':raise ValueError('OFFICE_EXECUTION_FAILED')
        return original(kind,*args,**kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(office_execution,'build_validated_office',fail_one)
        response=package_create(db)
    assert response.status_code==200,response.text
    first=response.json()['data']
    assert first['run']['stage']=='FAILED' and first['retry_available'] is True
    assert [a['state'] for a in first['artifacts']]==['FAILED','READY']
    with monkeypatch.context() as patch:
        patch.setattr(db.settings,'TEACHER_WORK_PRIVATE_MATERIALS_ENABLED',False)
        state=request(db,'GET',db.export_url+'/'+first['version']['version_id']).json()['data']
        assert state['retry_available'] is False
        cap=request(db,'GET','/api/teacher/work/packages/capabilities').json()['data']
        assert cap['read'] is True and cap['retry'] is False and cap['reasons']=={'create':'materials_unavailable','retry':'materials_unavailable'}
    docx=first['artifacts'][1];raw=binary_request(db,db.export_task['task_id'],docx).content
    retry_url=db.export_url.removesuffix('/packages')+'/runs/'+first['run']['run_id']+'/retry'
    retry=request(db,'POST',retry_url,body={'expected_attempt':1})
    assert retry.status_code==200,retry.text
    second=retry.json()['data']
    assert second['run']['stage']=='COMPLETE' and second['run']['attempt']==2
    assert second['run']['deadline']==first['run']['deadline'] and second['receipt']['attempt']==2
    assert second['artifacts'][1]==docx and binary_request(db,db.export_task['task_id'],docx).content==raw
    from tests.native_teacher_work_private_materials import read_only_request
    before=package_rows(db)
    replay=read_only_request(db,'POST',retry_url,body={'expected_attempt':1}).json()['data']
    assert replay=={**second,'receipt':{**second['receipt'],'replayed':True}} and package_rows(db)==before
    create_replay=read_only_request(db,'POST',db.export_url,body=db.export_body,key='manual-package').json()['data']
    assert create_replay['run']['attempt']==2 and create_replay['receipt']['attempt']==1 and package_rows(db)==before
    assert request(db,'POST',retry_url,body={'expected_attempt':2}).status_code==422


def test_concurrent_exact_creation_dispatches_once(export_db,monkeypatch):
    from app.services.teacher_work import office_execution
    from tests.native_teacher_work_private_materials import read_only_request
    db=export_db;started=Event();release=Event();original=office_execution.build_validated_office;calls=[]
    def held(kind,*args,**kwargs):
        calls.append(kind)
        if kind=='pptx':
            started.set();assert release.wait(10)
        return original(kind,*args,**kwargs)
    monkeypatch.setattr(office_execution,'build_validated_office',held)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(package_create,db)
        try:
            assert started.wait(10)
            replay=read_only_request(db,'POST',db.export_url,body=db.export_body,key='manual-package')
            assert replay.status_code==200,replay.text
            value=replay.json()['data']
            assert value['run']['stage']=='FILES_RUNNING' and value['receipt']['replayed'] is True
            different=package_create(db,'different-key')
            assert different.status_code==409 and different.json()['message']=='OWNER_RUN_BUSY'
        finally:release.set()
        done=first.result(timeout=40)
    assert done.status_code==200,done.text
    assert calls==['pptx','docx']
    rows=package_rows(db)
    assert len(rows['teacher_work_runs'])==len(rows['teacher_work_package_versions'])==1 and len(rows['teacher_work_artifacts'])==2


def test_access_flags_tampering_and_historical_download(export_db,monkeypatch):
    from tests.native_teacher_work_private_http import OTHER,STUDENT
    from tests.native_teacher_work_private_materials import read_only_request
    db=export_db;response=package_create(db);assert response.status_code==200,response.text
    value=response.json()['data'];before=package_rows(db)
    cap=request(db,'GET','/api/teacher/work/packages/capabilities').json()['data']
    assert cap=={'create':True,'read':True,'retry':True,'download':True,'storage_configured':True,'reasons':{}}
    for owner,status in ((OTHER,404),(STUDENT,403)):
        assert request(db,'GET',db.export_url+'/'+value['version']['version_id'],owner=owner).status_code==status
        assert binary_request(db,db.export_task['task_id'],value['artifacts'][0],owner=owner).status_code==status
    assert request(db,'POST',db.export_url,body={**db.export_body,'owner':'x'},key='bad').status_code==422
    assert request(db,'POST',db.export_url,body={**db.export_body,'expected_revision':99},key='new').json()['message']=='REVISION_CONFLICT'
    assert request(db,'POST',db.export_url,body={**db.export_body,'outline_digest':'f'*64},key='manual-package').json()['message']=='IDEMPOTENCY_CONFLICT'
    assert package_rows(db)==before
    db.source_file.write_bytes(b'new-synthetic-source')
    path=db.export_url.removesuffix('/packages')
    patch=request(db,'PATCH',path+'/working',body={'expected_revision':4,'changes':{'requirements':'changed synthetic requirements'}})
    assert patch.status_code==200,patch.text
    assert read_only_request(db,'GET',db.export_url+'/'+value['version']['version_id']).json()['data']=={**value,'receipt':None}
    assert binary_request(db,db.export_task['task_id'],value['artifacts'][0]).status_code==200
    key=next(r['storage_key'] for r in package_rows(db)['teacher_work_artifacts'] if r['kind']=='pptx')
    (Path(db.settings.TEACHER_WORK_STORAGE_ROOT)/key).write_bytes(b'tampered')
    failed=binary_request(db,db.export_task['task_id'],value['artifacts'][0])
    assert failed.status_code==503 and failed.json()['message']=='PRIVATE_STORAGE_UNAVAILABLE'
    monkeypatch.setattr(db.settings,'TEACHER_WORK_PRIVATE_EXPORTS_ENABLED',False)
    cap=request(db,'GET','/api/teacher/work/packages/capabilities').json()['data']
    assert set(cap)=={'create','read','retry','download','storage_configured','reasons'} and not any(cap[n] for n in cap if n!='reasons')
    assert request(db,'GET',db.export_url+'/'+value['version']['version_id']).json()['message']=='PRIVATE_EXPORTS_DISABLED'


def test_public_storage_alias_refuses_capability_and_create_without_dml(export_db,monkeypatch):
    from tests.native_teacher_work_private_materials import read_only_request
    db=export_db;root=Path(db.settings.TEACHER_WORK_STORAGE_ROOT)
    public=db.evidence/('synthetic-public-alias-'+db.export_task['task_id'])
    public.symlink_to(root.parent,target_is_directory=True)
    monkeypatch.setattr(db.settings,'COURSEWARE_FRONTEND_ROOT',str(public))
    before=package_rows(db)
    cap=read_only_request(db,'GET','/api/teacher/work/packages/capabilities')
    assert cap.status_code==200,cap.text
    assert cap.json()['data']=={**dict.fromkeys(('create','read','retry','download','storage_configured'),False),
        'reasons':dict.fromkeys(('create','read','retry','download','storage_configured'),'private_storage_unavailable')}
    response=read_only_request(db,'POST',db.export_url,body=db.export_body,key='manual-package')
    assert response.status_code==503 and response.json()['message']=='PRIVATE_STORAGE_UNAVAILABLE'
    assert package_rows(db)==before and not list(root.iterdir())


def test_nonready_claims_enforce_owner_quota(export_db,monkeypatch):
    from app.services.teacher_work import office_execution
    db=export_db
    def fail(*args,**kwargs):raise ValueError('OFFICE_EXECUTION_FAILED')
    monkeypatch.setattr(office_execution,'build_validated_office',fail)
    for number in range(10):
        response=package_create(db,'quota-'+str(number))
        assert response.status_code==200,response.text
        assert response.json()['data']['run']['stage']=='FAILED'
    before=package_rows(db)
    response=package_create(db,'over-quota')
    assert response.status_code==429 and response.json()['message']=='OWNER_STORAGE_QUOTA_EXCEEDED'
    assert package_rows(db)==before and len(before['teacher_work_artifacts'])==20


def test_source_drift_during_build_rejects_publication(export_db,monkeypatch):
    from app.services.teacher_work import office_execution
    db=export_db;original=office_execution.build_validated_office
    def drift(*args,**kwargs):
        value=original(*args,**kwargs)
        db.source_file.write_bytes(b'synthetic-source-drift')
        return value
    monkeypatch.setattr(office_execution,'build_validated_office',drift)
    response=package_create(db)
    assert response.status_code==409 and response.json()['message']=='SOURCE_CHANGED'
    rows=package_rows(db)
    assert rows['teacher_work_runs'][0]['stage']=='FAILED' and rows['teacher_work_owner_run_leases'][0]['active_run_id'] is None
    assert all(a['state']=='FAILED' for a in rows['teacher_work_artifacts'])
    assert not list(Path(db.settings.TEACHER_WORK_STORAGE_ROOT).rglob('*.pptx'))


def test_unknown_draft_fields_during_build_block_ready(export_db,monkeypatch):
    from app.services.teacher_work import office_execution
    db=export_db;original=office_execution.build_validated_office
    def opaque(*args,**kwargs):
        value=original(*args,**kwargs)
        with db.engine.begin() as c:
            row=c.execute(text("SELECT id,payload FROM domain_records WHERE owner_id='native-http-teacher' AND record_type='draft'")).one()
            payload=json.loads(row.payload);payload['content']['opaque_new_field']={'synthetic':'unverified'}
            c.execute(text('UPDATE domain_records SET payload=:payload WHERE id=:id'),{'payload':json.dumps(payload,ensure_ascii=False),'id':row.id})
        return value
    monkeypatch.setattr(office_execution,'build_validated_office',opaque)
    response=package_create(db)
    assert response.status_code==409 and response.json()['message']=='NORMALIZATION_REQUIRED'
    rows=package_rows(db)
    assert rows['teacher_work_runs'][0]['stage']=='FAILED' and all(a['state']=='FAILED' for a in rows['teacher_work_artifacts'])


def test_final_owner_flush_source_drift_rolls_back_complete(export_db,monkeypatch):
    from app.repositories.teacher_work_exports import PrivatePackageRepository
    from app.services.teacher_work.bootstrap import _SessionWorkTransport
    db=export_db;original_finish=PrivatePackageRepository.finish;original_flush=_SessionWorkTransport.flush
    def mark(repository,*args,**kwargs):
        value=original_finish(repository,*args,**kwargs)
        repository.core.uow.session.info['synthetic_package_final']=value.run.stage=='COMPLETE'
        return value
    def drift(transport):
        original_flush(transport)
        if transport.session.info.get('synthetic_package_final'):db.source_file.write_bytes(b'synthetic-final-source-drift')
    monkeypatch.setattr(PrivatePackageRepository,'finish',mark)
    monkeypatch.setattr(_SessionWorkTransport,'flush',drift)
    response=package_create(db)
    assert response.status_code==409 and response.json()['message']=='SOURCE_CHANGED'
    rows=package_rows(db)
    assert rows['teacher_work_runs'][0]['stage']=='FAILED' and rows['teacher_work_runs'][0]['result_version_id'] is None
    assert all(a['state']=='READY' for a in rows['teacher_work_artifacts'])
    assert rows['teacher_work_owner_run_leases'][0]['active_run_id'] is None
    with db.engine.connect() as c:assert c.scalar(text('SELECT latest_version_id FROM teacher_work_tasks')) is None


@pytest.mark.parametrize('phase',['admission_before','admission_after','file_before','file_after','final_before','final_after'])
def test_commit_unknown_reconciles_without_blind_rebuild(export_db,monkeypatch,phase):
    from app.services.teacher_work.bootstrap import _SessionWorkTransport
    from app.services.teacher_work import office_execution
    from tests.native_teacher_work_private_materials import read_only_request
    db=export_db;original=_SessionWorkTransport.commit;counter=0;calls=[];builder=office_execution.build_validated_office
    target={'admission_before':1,'admission_after':1,'file_before':2,'file_after':2,'final_before':4,'final_after':4}[phase]
    def unknown(transport):
        nonlocal counter
        counter+=1
        if counter!=target:return original(transport)
        if phase.endswith('after'):original(transport)
        raise OSError('synthetic lost commit acknowledgement')
    def real(kind,*args,**kwargs):calls.append(kind);return builder(kind,*args,**kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(_SessionWorkTransport,'commit',unknown)
        patch.setattr(office_execution,'build_validated_office',real)
        response=package_create(db)
    assert response.status_code==503 and response.json()['message']=='COMMIT_OUTCOME_UNKNOWN'
    persisted=package_rows(db)
    if phase=='admission_before':
        assert not persisted['teacher_work_runs'] and not calls
        assert package_create(db).json()['data']['run']['stage']=='COMPLETE'
        return
    def files():
        root=Path(db.settings.TEACHER_WORK_STORAGE_ROOT)
        return {str(path.relative_to(root)):(path.stat().st_dev,path.stat().st_ino,sha256(path.read_bytes()).hexdigest())
            for path in root.rglob('*') if path.is_file()}
    retained=files()
    if phase=='file_before':assert len(retained)==1
    count=len(calls)
    with monkeypatch.context() as patch:
        patch.setattr(office_execution,'build_validated_office',real)
        replay=package_create(db)
    assert replay.status_code==200,replay.text
    value=replay.json()['data']
    assert len(calls)==count and value['receipt']['replayed'] is True
    assert files()==retained
    db.row_observations.append({'unknown_commit_files_before':retained,'after_reconciliation':files(),'phase':phase})
    assert value['run']['stage']==('COMPLETE' if phase in ('final_before','final_after') else 'INTERRUPTED')
    assert package_rows(db)['teacher_work_owner_run_leases'][0]['active_run_id'] is None
    if phase in ('admission_after','file_before','file_after'):
        ready=[a for a in value['artifacts'] if a['state']=='READY']
        retry_url=db.export_url.removesuffix('/packages')+'/runs/'+value['run']['run_id']+'/retry'
        retried=request(db,'POST',retry_url,body={'expected_attempt':1})
        assert retried.status_code==200,retried.text
        assert retried.json()['data']['run']['stage']=='COMPLETE'
        for artifact in ready:assert artifact in retried.json()['data']['artifacts']
    else:
        before=package_rows(db)
        assert read_only_request(db,'POST',db.export_url,body=db.export_body,key='manual-package').status_code==200
        assert package_rows(db)==before


def test_expired_restart_fences_publisher_retains_claims(export_db,monkeypatch):
    from app.services.teacher_work.bootstrap import _SessionWorkTransport
    from app.services.teacher_work import private_exports
    db=export_db;original=_SessionWorkTransport.commit
    def lost(transport):original(transport);raise OSError('synthetic lost acknowledgement')
    with monkeypatch.context() as patch:
        patch.setattr(_SessionWorkTransport,'commit',lost)
        assert package_create(db).json()['message']=='COMMIT_OUTCOME_UNKNOWN'
    before=package_rows(db);run=before['teacher_work_runs'][0];lease=before['teacher_work_owner_run_leases'][0]
    # Loss of process-local evidence alone is insufficient before deadline.
    monkeypatch.setattr(private_exports,'stopped_fences',lambda:frozenset())
    replay=package_create(db).json()['data']
    assert replay['run']['stage']=='FILES_RUNNING' and package_rows(db)==before
    expired='2020-01-01 00:00:00.123456'
    with db.engine.begin() as c:
        c.execute(text('UPDATE teacher_work_runs SET deadline=:t WHERE run_id=:id'),{'t':expired,'id':run['run_id']})
        c.execute(text('UPDATE teacher_work_owner_run_leases SET expires_at=:t,process_instance=:p WHERE owner=:o'),{'t':expired,'p':str(uuid4()),'o':lease['owner']})
    replay=package_create(db).json()['data']
    assert replay['run']['stage']=='INTERRUPTED' and replay['run']['error_code']=='PACKAGE_DEADLINE_EXPIRED'
    assert replay['run']['deadline'].startswith('2020-01-01') and not replay['retry_available']
    after=package_rows(db)
    assert after['teacher_work_owner_run_leases'][0]['active_run_id'] is None
    assert after['teacher_work_owner_run_leases'][0]['revision']>lease['revision']
    assert [a['storage_key'] for a in after['teacher_work_artifacts']]==[a['storage_key'] for a in before['teacher_work_artifacts']]
    retry_url=db.export_url.removesuffix('/packages')+'/runs/'+run['run_id']+'/retry'
    assert request(db,'POST',retry_url,body={'expected_attempt':1}).json()['message']=='PACKAGE_DEADLINE_EXPIRED'
    new=package_create(db,'new-explicit-key')
    assert new.status_code==200,new.text
    assert new.json()['data']['run']['run_id']!=run['run_id'] and len(package_rows(db)['teacher_work_artifacts'])==4


def test_private_storage_fsync_failure_retains_claim_then_explicit_retry(export_db,monkeypatch):
    from app.services.teacher_work import private_storage
    db=export_db;original=private_storage.os.fsync;calls=0
    def fault(fd):
        nonlocal calls
        calls+=1
        if calls==2:raise OSError('synthetic fsync failed')
        return original(fd)
    with monkeypatch.context() as patch:
        patch.setattr(private_storage.os,'fsync',fault)
        response=package_create(db)
    assert response.status_code==503 and response.json()['message']=='PRIVATE_STORAGE_UNAVAILABLE'
    rows=package_rows(db)
    assert rows['teacher_work_runs'][0]['stage']=='FAILED' and all(a['storage_key'] for a in rows['teacher_work_artifacts'])
    assert list(Path(db.settings.TEACHER_WORK_STORAGE_ROOT).rglob('*.tmp'))
    url=db.export_url.removesuffix('/packages')+'/runs/'+rows['teacher_work_runs'][0]['run_id']+'/retry'
    retry=request(db,'POST',url,body={'expected_attempt':1})
    assert retry.status_code==200,retry.text
    assert retry.json()['data']['run']['stage']=='COMPLETE' and not list(Path(db.settings.TEACHER_WORK_STORAGE_ROOT).rglob('*.tmp'))


def test_package_list_reopens_and_paginates_historical_ready(export_db):
    from tests.native_teacher_work_private_http import OTHER
    from tests.native_teacher_work_private_materials import read_only_request
    db=export_db
    assert request(db,'GET',db.export_url).json()['data']=={'task_id':db.export_task['task_id'],'items':[],'next_before':None,'truncated':False}
    first=package_create(db).json()['data']
    db.export_body['expected_revision']=4
    second_response=package_create(db,'second-package')
    assert second_response.status_code==200,second_response.text
    second=second_response.json()['data']
    db.source_file.write_bytes(b'later-source')
    before=package_rows(db)
    listing=read_only_request(db,'GET',db.export_url+'?limit=1').json()['data']
    assert set(listing)=={'task_id','items','next_before','truncated'} and listing['truncated'] is True
    item=listing['items'][0]
    assert set(item)=={'version_id','version_no','run_id','approval_id','created_at','stage','attempt','artifacts'}
    assert item['version_id']==second['version']['version_id'] and listing['next_before']==item['version_id']
    assert all(a['download_available'] for a in item['artifacts'])
    historical=read_only_request(db,'GET',db.export_url+'?limit=1&before='+listing['next_before']).json()['data']
    assert historical['next_before'] is None and historical['truncated'] is False and historical['items'][0]['version_id']==first['version']['version_id']
    reopened=request(db,'GET',db.export_url+'/'+historical['items'][0]['version_id']).json()['data']
    assert reopened=={**first,'receipt':None}
    for artifact in reopened['artifacts']:assert binary_request(db,db.export_task['task_id'],artifact).status_code==200
    assert package_rows(db)==before
    assert request(db,'GET',db.export_url,owner=OTHER).status_code==404
    for suffix in ('?limit=0','?limit=21','?before=invalid'):
        assert request(db,'GET',db.export_url+suffix).status_code==422
    assert request(db,'GET',db.export_url+'?before='+str(uuid4())).status_code==404


@pytest.mark.parametrize('fault',['missing','corrupt','empty','symlink'])
def test_history_isolates_owned_missing_or_corrupt_file(export_db,fault):
    from tests.native_teacher_work_private_materials import read_only_request
    db=export_db;first=package_create(db).json()['data']
    task_url=db.export_url.removesuffix('/packages')
    db.export_body['expected_revision']=request(db,'GET',task_url).json()['data']['working_revision']
    response=package_create(db,'healthy-second-version');assert response.status_code==200,response.text
    second=response.json()['data'];before=package_rows(db);bad=second['artifacts'][0];good=second['artifacts'][1]
    rows=before['teacher_work_artifacts']
    key=next(row['storage_key'] for row in rows if row['artifact_id']==bad['artifact_id'])
    bad_path=Path(db.settings.TEACHER_WORK_STORAGE_ROOT)/key
    if fault=='missing':bad_path.unlink()
    elif fault=='corrupt':bad_path.write_bytes(b'isolated-synthetic-corruption')
    elif fault=='empty':bad_path.write_bytes(b'')
    else:
        bad_path.unlink()
        good_key=next(row['storage_key'] for row in rows if row['artifact_id']==good['artifact_id'])
        bad_path.symlink_to(Path(db.settings.TEACHER_WORK_STORAGE_ROOT)/good_key)
    listed=read_only_request(db,'GET',db.export_url+'?limit=1')
    if fault=='symlink':
        assert listed.status_code==503 and listed.json()['message']=='PRIVATE_STORAGE_UNAVAILABLE'
    else:
        assert listed.status_code==200,listed.text
        page=listed.json()['data'];item=page['items'][0]
        assert page['truncated'] is True and page['next_before']==second['version']['version_id']
        assert item['version_id']==second['version']['version_id']
        assert [a['state'] for a in item['artifacts']]==['READY','READY']
        assert [a['download_available'] for a in item['artifacts']]==[False,True]
        older=read_only_request(db,'GET',db.export_url+'?limit=1&before='+page['next_before'])
        assert older.status_code==200,older.text
        historical=older.json()['data']
        assert historical['next_before'] is None and historical['truncated'] is False
        assert historical['items'][0]['version_id']==first['version']['version_id']
        assert all(a['download_available'] for a in historical['items'][0]['artifacts'])
        complete=read_only_request(db,'GET',db.export_url).json()['data']
        assert len(complete['items'])==2 and complete['truncated'] is False
        assert [a['download_available'] for a in complete['items'][0]['artifacts']]==[False,True]
        assert all(a['download_available'] for a in complete['items'][1]['artifacts'])
        assert binary_request(db,db.export_task['task_id'],good).status_code==200
        assert binary_request(db,db.export_task['task_id'],first['artifacts'][0]).status_code==200
    refused=binary_request(db,db.export_task['task_id'],bad)
    assert refused.status_code==503 and refused.json()['message']=='PRIVATE_STORAGE_UNAVAILABLE'
    assert package_rows(db)==before


def test_entry_capacity_is_reserved_before_create(export_db,monkeypatch):
    from app.services.teacher_work import private_storage
    db=export_db
    monkeypatch.setattr(private_storage,'ENTRY_CAP',3)
    before=package_rows(db)
    response=package_create(db)
    assert response.status_code==429 and response.json()['message']=='OWNER_STORAGE_QUOTA_EXCEEDED'
    assert package_rows(db)==before and not list(Path(db.settings.TEACHER_WORK_STORAGE_ROOT).iterdir())


@pytest.mark.parametrize('boundary',['schema_name','server_uuid','datadir','socket','transaction','foreign_keys','unique_checks','temporary_shadow','partial'])
def test_v3_migration_refuses_unsafe_target_before_ddl(native_db,boundary):
    db=native_db;prepare(db)
    migration=importlib.import_module('migrations.v20261006_teacher_work_exports_mysql')
    with db.engine.connect() as c:
        expected=db.identity
        if boundary in ('schema_name','server_uuid','datadir','socket'):expected=replace(expected,**{boundary:getattr(expected,boundary)+'-wrong'})
        if boundary=='transaction':
            original_root=c.begin();c.execute(text('SELECT 1'))
        elif boundary in ('foreign_keys','unique_checks'):
            variable='foreign_key_checks' if boundary=='foreign_keys' else 'unique_checks'
            c.execute(text('SET SESSION '+variable+'=0'));c.commit()
        elif boundary=='temporary_shadow':
            c.execute(text('CREATE TEMPORARY TABLE teacher_work_artifacts (synthetic INT)'));c.commit()
        elif boundary=='partial':
            c.execute(text('ALTER TABLE teacher_work_package_versions ADD COLUMN approval_id VARCHAR(36) NULL'));c.commit()
        statements=[]
        def record(connection,cursor,sql,params,ctx,many):statements.append(sql)
        event.listen(c,'before_cursor_execute',record)
        try:
            with pytest.raises(migration.ExportsMigrationError) as caught:migration.apply_teacher_work_exports_mysql(c,expected)
        finally:event.remove(c,'before_cursor_execute',record)
        assert caught.value.report.attempted_steps==caught.value.report.confirmed_steps==()
        assert not any(sql.lstrip().upper().startswith(('ALTER','CREATE','INSERT','UPDATE','DROP')) for sql in statements)
        if boundary=='transaction':assert c.get_transaction() is original_root and original_root.is_active
        if boundary in ('schema_name','server_uuid','datadir','socket'):assert caught.value.code=='teacher_work_identity_mismatch'
        c.rollback()
    with db.engine.connect() as c:assert c.scalar(text("SELECT version FROM teacher_work_schema_versions WHERE component='teacher_work'"))==2


def test_v3_exact_replay_no_dml_and_database_binding_constraints(export_db):
    db=export_db
    migration=importlib.import_module('migrations.v20261006_teacher_work_exports_mysql')
    statements=[]
    def record(c,cursor,sql,params,ctx,many):statements.append(sql)
    event.listen(db.engine,'before_cursor_execute',record)
    try:
        with db.engine.connect() as c:report=migration.apply_teacher_work_exports_mysql(c,db.identity)
    finally:event.remove(db.engine,'before_cursor_execute',record)
    assert report.completed and report.attempted_steps==report.confirmed_steps==() and all(sql.lstrip().upper().startswith(('SELECT','SHOW')) for sql in statements)
    response=package_create(db);assert response.status_code==200,response.text
    value=response.json()['data'];before=package_rows(db)
    cases=(('UPDATE teacher_work_runs SET provider_call_count=1 WHERE run_id=:id',value['run']['run_id'],3819),
        ('UPDATE teacher_work_package_versions SET approval_id=NULL WHERE version_id=:id',value['version']['version_id'],3819),
        ('UPDATE teacher_work_package_versions SET approval_id=\'00000000-0000-0000-0000-000000000001\' WHERE version_id=:id',value['version']['version_id'],1452),
        ('UPDATE teacher_work_artifacts SET validation_summary=JSON_OBJECT() WHERE artifact_id=:id',value['artifacts'][0]['artifact_id'],3819))
    for query,identifier,number in cases:
        with db.engine.connect() as c:
            with pytest.raises(DBAPIError) as caught:c.execute(text(query),{'id':identifier})
            assert caught.value.orig.args[0]==number
            c.rollback()
    assert package_rows(db)==before
    from tests.native_teacher_work_private_http import create,create_body
    from tests.test_teacher_work_private_materials import lesson,slides
    other=create(db,key='second-composite-task',body=create_body(resource_ids=[db.resource_id]))
    path='/api/teacher/work/tasks/'+other['task_id']+'/materials'
    saved=request(db,'POST',path,key='second-composite-save',body={'expected_revision':1,'input_revision':1,'expected_outline_revision':0,'lesson':lesson(),'slides':slides()}).json()['data']
    approved=request(db,'POST',path+'/approve',key='second-composite-approval',body=approval_body(saved)).json()['data']
    with db.engine.connect() as c:
        with pytest.raises(DBAPIError) as caught:c.execute(text('UPDATE teacher_work_package_versions SET approval_id=:approval WHERE version_id=:version'),
            {'approval':approved['approval']['approval_id'],'version':value['version']['version_id']})
        assert caught.value.orig.args[0]==1452
        c.rollback()


@pytest.mark.parametrize('fault',['source','lease','deadline'])
def test_final_flush_revalidates_recovered_complete(export_db,monkeypatch,fault):
    from app.services.teacher_work.bootstrap import _SessionWorkTransport
    from app.repositories.teacher_work_exports import PrivatePackageRepository
    from app.services.teacher_work import private_exports
    from datetime import datetime,timezone
    db=export_db;original_commit=_SessionWorkTransport.commit;calls=0
    def unknown(transport):
        nonlocal calls
        calls+=1
        if calls==4:raise OSError('synthetic final commit not acknowledged')
        return original_commit(transport)
    with monkeypatch.context() as patch:
        patch.setattr(_SessionWorkTransport,'commit',unknown)
        assert package_create(db).json()['message']=='COMMIT_OUTCOME_UNKNOWN'
    before=package_rows(db)
    original_finish=PrivatePackageRepository.finish;original_flush=_SessionWorkTransport.flush;now=None
    def mark(repository,*args,**kwargs):
        value=original_finish(repository,*args,**kwargs)
        if value.run.stage=='COMPLETE':repository.core.uow.session.info['final_deadline']=value.run.deadline
        return value
    def clock():return now or datetime.now(timezone.utc)
    def tamper(transport):
        nonlocal now
        original_flush(transport)
        deadline=transport.session.info.get('final_deadline')
        if not deadline:return
        if fault=='source':db.source_file.write_bytes(b'synthetic-recovery-final-drift')
        elif fault=='deadline':now=deadline
        else:transport.connection.execute(text("UPDATE teacher_work_owner_run_leases SET revision=revision+1"))
    from app.api.endpoints import teacher_work
    monkeypatch.setattr(teacher_work,'_clock',clock)
    monkeypatch.setattr(PrivatePackageRepository,'finish',mark)
    monkeypatch.setattr(_SessionWorkTransport,'flush',tamper)
    response=package_create(db)
    assert response.status_code==409,response.text
    assert response.json()['message']=={'source':'SOURCE_CHANGED','lease':'PACKAGE_FENCE_CHANGED','deadline':'PACKAGE_DEADLINE_EXPIRED'}[fault]
    rows=package_rows(db)
    assert rows==before
    assert rows['teacher_work_runs'][0]['stage']=='FILES_RUNNING' and rows['teacher_work_runs'][0]['result_version_id'] is None
    assert rows['teacher_work_owner_run_leases'][0]['active_run_id']==rows['teacher_work_runs'][0]['run_id']


def test_uncertain_child_receipt_cannot_authorize_early_retry(export_db,monkeypatch):
    from app.services.teacher_work import office_execution
    from tests.native_teacher_work_private_materials import read_only_request
    db=export_db
    def unknown(*args,**kwargs):raise office_execution.OfficeTerminationUnknown('OFFICE_TERMINATION_UNKNOWN')
    monkeypatch.setattr(office_execution,'build_validated_office',unknown)
    response=package_create(db)
    assert response.status_code==503 and response.json()['message']=='PACKAGE_STATE_UNAVAILABLE'
    before=package_rows(db)
    replay=read_only_request(db,'POST',db.export_url,body=db.export_body,key='manual-package').json()['data']
    assert replay['run']['stage']=='FILES_RUNNING' and not replay['retry_available'] and package_rows(db)==before
    url=db.export_url.removesuffix('/packages')+'/runs/'+replay['run']['run_id']+'/retry'
    assert request(db,'POST',url,body={'expected_attempt':1}).json()['message']=='PACKAGE_RETRY_UNAVAILABLE'


def test_actual_office_timeout_is_persisted_failed_with_ready_peer(export_db,monkeypatch):
    from app.services.teacher_work import office_execution
    db=export_db;original=office_execution.build_validated_office
    def short(kind,version,**kwargs):
        return original(kind,version,timeout_seconds=.001 if kind=='pptx' else kwargs['timeout_seconds'])
    monkeypatch.setattr(office_execution,'build_validated_office',short)
    response=package_create(db)
    assert response.status_code==200,response.text
    data=response.json()['data']
    assert data['run']['stage']=='FAILED' and [a['state'] for a in data['artifacts']]==['FAILED','READY']
    assert data['artifacts'][0]['error_code']=='OFFICE_STAGE_TIMEOUT'
    assert package_rows(db)['teacher_work_owner_run_leases'][0]['active_run_id'] is None


def test_ready_commit_ack_lost_preserves_exact_file_bytes(export_db,monkeypatch):
    from app.services.teacher_work.bootstrap import _SessionWorkTransport
    db=export_db;original=_SessionWorkTransport.commit;counter=0
    def lost(transport):
        nonlocal counter
        counter+=1
        receipt=original(transport)
        if counter==2:raise OSError('synthetic READY ack lost')
        return receipt
    with monkeypatch.context() as patch:
        patch.setattr(_SessionWorkTransport,'commit',lost)
        assert package_create(db).json()['message']=='COMMIT_OUTCOME_UNKNOWN'
    before=package_rows(db)
    pptx=next(a for a in before['teacher_work_artifacts'] if a['kind']=='pptx')
    path=Path(db.settings.TEACHER_WORK_STORAGE_ROOT)/pptx['storage_key'];raw=path.read_bytes();inode=path.stat().st_ino
    assert pptx['state']=='READY' and sha256(raw).hexdigest()==pptx['sha256']
    replay=package_create(db).json()['data']
    assert replay['run']['stage']=='INTERRUPTED' and path.read_bytes()==raw and path.stat().st_ino==inode
    url=db.export_url.removesuffix('/packages')+'/runs/'+replay['run']['run_id']+'/retry'
    assert request(db,'POST',url,body={'expected_attempt':1}).json()['data']['run']['stage']=='COMPLETE'
    assert path.read_bytes()==raw and path.stat().st_ino==inode


def test_expired_recovery_rejects_actual_late_publisher(export_db,monkeypatch):
    from app.services.teacher_work import office_execution,private_exports
    db=export_db;started=Event();release=Event();original=office_execution.build_validated_office;old_version=None
    def held(kind,version,**kwargs):
        nonlocal old_version
        raw=original(kind,version,**kwargs)
        if old_version is None:old_version=version.version_id
        if version.version_id==old_version and kind=='pptx':started.set();assert release.wait(20)
        return raw
    monkeypatch.setattr(office_execution,'build_validated_office',held)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(package_create,db)
        try:
            assert started.wait(10)
            old=package_rows(db);run=old['teacher_work_runs'][0]
            with db.engine.begin() as c:
                c.execute(text("UPDATE teacher_work_runs SET deadline='2020-01-01' WHERE run_id=:r"),{'r':run['run_id']})
                c.execute(text("UPDATE teacher_work_owner_run_leases SET expires_at='2020-01-01'"))
            restored=package_create(db).json()['data']
            assert restored['run']['stage']=='INTERRUPTED'
            newer=package_create(db,'fresh-after-fence')
            assert newer.status_code==200,newer.text
            new_value=newer.json()['data'];before=package_rows(db)
        finally:release.set()
        late=first.result(timeout=30)
    assert late.status_code==409 and late.json()['message']=='PACKAGE_FENCE_CHANGED'
    assert package_rows(db)==before
    assert new_value['run']['stage']=='COMPLETE'
    for row in old['teacher_work_artifacts']:assert not (Path(db.settings.TEACHER_WORK_STORAGE_ROOT)/row['storage_key']).exists()


def test_export_body_and_response_limit_precede_commit(export_db,monkeypatch):
    from app.services.teacher_work.bootstrap import _SessionWorkTransport
    from app.services.teacher_work import private_exports
    db=export_db;before=package_rows(db)
    response=request(db,'POST',db.export_url,raw=b'x'*262145,key='oversize')
    assert response.status_code==413 and response.json()['message']=='REQUEST_BODY_TOO_LARGE' and package_rows(db)==before
    # Reduce only the response budget to exercise the real serialized envelope
    # failure path with an otherwise genuine immutable DTO and SQL admission.
    monkeypatch.setattr(private_exports,'BODY_LIMIT',512)
    response=package_create(db)
    assert response.status_code==503 and response.json()['message']=='PACKAGE_RESPONSE_TOO_LARGE'
    assert package_rows(db)==before and not list(Path(db.settings.TEACHER_WORK_STORAGE_ROOT).iterdir())


@pytest.mark.parametrize('phase',['ddl_before','ddl_after','ledger_before','ledger_after'])
def test_v3_partial_ddl_and_ledger_unknown_never_auto_resume(native_db,monkeypatch,phase):
    from sqlalchemy.engine import Connection
    from app.services.teacher_work.schema_mysql_v3 import observe_teacher_work_mysql_v3
    db=native_db;prepare(db);migration=importlib.import_module('migrations.v20261006_teacher_work_exports_mysql')
    original_execute=Connection.execute;original_commit=Connection.commit;alter_count=0
    def ddl(connection,statement,*args,**kwargs):
        nonlocal alter_count
        if str(statement).startswith('ALTER TABLE'):
            alter_count+=1
            if alter_count==2:
                if phase=='ddl_after':original_execute(connection,statement,*args,**kwargs)
                if phase in ('ddl_before','ddl_after'):raise OSError('synthetic DDL ack failure')
        return original_execute(connection,statement,*args,**kwargs)
    def ledger(connection):
        if phase=='ledger_after':original_commit(connection)
        raise OSError('synthetic ledger acknowledgement failure')
    with db.engine.connect() as c:
        with monkeypatch.context() as patch:
            patch.setattr(Connection,'execute',ddl)
            if phase.startswith('ledger'):patch.setattr(Connection,'commit',ledger)
            with pytest.raises(migration.ExportsMigrationError) as caught:migration.apply_teacher_work_exports_mysql(c,db.identity)
        assert not caught.value.report.completed
        if phase.startswith('ledger'):assert caught.value.report.ledger_commit_state=='UNKNOWN'
        else:assert caught.value.report.attempted_steps==('approval_reference','immutable_binding') and caught.value.report.confirmed_steps==('approval_reference',)
        c.rollback()
    with db.engine.connect() as c:
        observed=observe_teacher_work_mysql_v3(c)
        assert observed.ready is (phase=='ledger_after')
        assert c.scalar(text("SELECT version FROM teacher_work_schema_versions WHERE component='teacher_work'"))==(3 if phase=='ledger_after' else 2)
    with db.engine.connect() as c:
        if phase=='ledger_after':
            replay=migration.apply_teacher_work_exports_mysql(c,db.identity)
            assert replay.completed and replay.attempted_steps==()
        else:
            with pytest.raises(migration.ExportsMigrationError) as caught:migration.apply_teacher_work_exports_mysql(c,db.identity)
            assert caught.value.code=='teacher_work_exports_exact_v2_required' and caught.value.report.attempted_steps==()


def binary_request(db,task_id,artifact,**kwargs):
    from tests.native_teacher_work_private_http import OWNER
    owner=kwargs.get('owner',OWNER)
    path=f'/api/teacher/work/tasks/{task_id}/artifacts/{artifact["artifact_id"]}/download'
    async def send():
        async with db.httpx.AsyncClient(transport=db.httpx.ASGITransport(app=db.app),base_url='http://synthetic.local') as c:
            return await c.get(path,headers={'Authorization':'Bearer '+db.tokens[owner]})
    response=asyncio.run(send())
    record={'request':{'method':'GET','path':path,'body':None},'response':{'status':response.status_code,
        'headers':{k:response.headers.get(k) for k in ('content-type','content-length','content-disposition','cache-control','x-content-type-options')}}}
    if response.status_code==200:record['binary']={'byte_size':len(response.content),'sha256':sha256(response.content).hexdigest(),'zip_magic':response.content[:2].hex()}
    else:record['response']['body']=response.json()
    db.material_exchanges.append(record)
    return response


def test_real_private_package_create_and_download(material_db,monkeypatch):
    db=material_db
    task,url,create_body=export_setup(db,monkeypatch)
    response=request(db,'POST',url,body=create_body,key='manual-package')
    assert response.status_code==200,response.text
    value=response.json()['data']
    assert value['provenance']=='manual' and value['run']['stage']=='COMPLETE'
    assert [a['state'] for a in value['artifacts']]==['READY','READY']
    assert set(value)=={'task_id','run','version','approval','provenance','artifacts','retry_available','receipt'}
    assert len(value['run'])==10 and len(value['version'])==14 and len(value['approval'])==8
    assert value['version']['lesson'] and value['version']['source_snapshots']==value['version']['skill_versions']==[]
    from app.schemas.teacher_work import PackageVersionDTO
    from app.services.teacher_work.exporters.validation import validate_office_bytes
    version=PackageVersionDTO.model_validate_json(json.dumps(value['version']))
    for artifact in value['artifacts']:
        downloaded=binary_request(db,task['task_id'],artifact)
        assert downloaded.status_code==200,downloaded.text[:100]
        assert len(downloaded.content)==artifact['byte_size'] and sha256(downloaded.content).hexdigest()==artifact['sha256']
        assert downloaded.headers['content-type']==artifact['mime'] and downloaded.headers['x-content-type-options']=='nosniff'
        assert downloaded.headers['cache-control']=='no-store' and downloaded.headers['content-length']==str(artifact['byte_size'])
        assert validate_office_bytes(artifact['kind'],downloaded.content,version).valid
    status=request(db,'GET',url+'/'+value['version']['version_id'])
    assert status.json()['data']=={**value,'receipt':None}
    replay=request(db,'POST',url,body=create_body,key='manual-package')
    assert replay.json()['data']=={**value,'receipt':{**value['receipt'],'replayed':True}}


def test_explicit_v2_to_v3_retains_v2_hash(native_db):
    db=native_db
    prepare(db)
    from app.services.teacher_work.schema import TEACHER_WORK_CONTRACT_HASH as old_hash
    path=Path(__file__).resolve().parents[1]/'migrations/v20261006_teacher_work_exports_mysql.py'
    assert path.is_file(), 'MISSING_REVIEWED_V2_TO_V3_MIGRATION'
    migration=importlib.import_module('migrations.v20261006_teacher_work_exports_mysql')
    with db.engine.connect() as connection:
        try: report=migration.apply_teacher_work_exports_mysql(connection,db.identity)
        except migration.ExportsMigrationError:
            from app.services.teacher_work.schema_mysql_v3 import observe_teacher_work_mysql_v3
            observed=observe_teacher_work_mysql_v3(connection)
            (db.evidence/'v3-physical-issues.json').write_text(json.dumps({'issues':[asdict(i) for i in observed.issues],'observation':observed.observation},default=str,indent=2))
            raw=[dict(r) for r in connection.execute(text('SELECT CONSTRAINT_NAME,CHECK_CLAUSE FROM information_schema.check_constraints WHERE CONSTRAINT_SCHEMA=DATABASE()')).mappings()]
            (db.evidence/'v3-raw-checks.json').write_text(json.dumps(raw,indent=2))
            raise
        assert report.completed is True
    from app.services.teacher_work.schema import TEACHER_WORK_CONTRACT_HASH
    assert TEACHER_WORK_CONTRACT_HASH==old_hash
    from app.services.teacher_work.schema_mysql_v3 import observe_teacher_work_mysql_v3
    with db.engine.connect() as connection:
        assert observe_teacher_work_mysql_v3(connection).ready
        assert connection.scalar(text('SELECT version FROM teacher_work_schema_versions WHERE component=\'teacher_work\''))==3


def test_ready_check_rejects_unknown_json_verdict(native_db):
    from app.services.teacher_work.schema_v3 import READY_CHECK
    db=native_db
    with db.engine.begin() as c:
        c.execute(text('CREATE TABLE tw_ready_probe (state VARCHAR(16),storage_key VARCHAR(255),byte_size INT,sha256 VARCHAR(64),validation_summary JSON,error_code VARCHAR(64), CONSTRAINT ck_native_ready CHECK ('+READY_CHECK+')) ENGINE=InnoDB'))
    for summary in ({},{'valid':None},{'valid':'true'}):
        with db.engine.connect() as c:
            with pytest.raises(DBAPIError) as error:
                c.execute(text("INSERT INTO tw_ready_probe VALUES ('READY','synthetic-path',1,:sha,:verdict,NULL)"),{'sha':'a'*64,'verdict':json.dumps(summary)})
            assert error.value.orig.args[0]==3819
            c.rollback()
