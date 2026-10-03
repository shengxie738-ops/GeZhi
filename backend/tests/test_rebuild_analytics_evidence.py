"""Explicit A4 selection: guarded minimal analytics ASGI and synthetic SQLite only."""
import json
import asyncio
from functools import wraps
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import httpx
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.endpoints import analytics as a
from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token
from app.models.domain_record import DomainRecord
from app.models.student_profile import StudentProfile
from app.models.user_account import UserAccount
from app.repositories.json_store import JsonStore

def sync_asgi(fn):
    @wraps(fn)
    def run(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return run

NOW = datetime(2026, 10, 3, 7, 11, 54, tzinfo=timezone.utc)
OWNERS = {'20260001', '20260002'}


def helper(name):
    result = getattr(a, name, None)
    assert callable(result), f'Missing evidence contract: {name}'
    return result


def source(records=None, **extra):
    return dict(available=True, source='homework/submission', records=records or [], reason=None,
                recordedTimezone=timezone.utc, recordedTimezoneDeclaration='UTC', **extra)


def record(key='one', owner='20260001', created='2026-09-26T09:00:00Z', **extra):
    return dict(dbId=1, module='homework', recordType='submission', recordKey=key, ownerId=owner,
                role='student', status='', createdAt=created, updatedAt='2026-10-03T00:00:00Z',
                payload={'studentId':'outsider', 'verified':True}, decodeError=False, **extra)


@pytest.fixture
def harness(monkeypatch):
    engine = create_engine('sqlite:///:memory:', connect_args={'check_same_thread':False}, poolclass=StaticPool)
    for model in [UserAccount, StudentProfile, DomainRecord]: model.__table__.create(engine)
    sessions = sessionmaker(bind=engine, autoflush=False)
    with sessions() as db:
        for username, role in [('teacher','teacher'), ('20260001','student'), ('20260002','student'), ('20269999','student')]:
            db.add(UserAccount(username=username, role=role, real_name='Duplicate name', password_hash=''))
        db.add(StudentProfile(user_id='20260001', knowledge=0, pace=50))
        db.commit()
    monkeypatch.setattr(settings, 'TEACHER_STUDENT_ASSIGNMENTS', json.dumps({'teacher':sorted(OWNERS)}))
    monkeypatch.setitem(settings.__dict__, 'ANALYTICS_RECORDED_TIMEZONE', '')
    app = FastAPI(); app.include_router(a.router)
    def isolated_db():
        with sessions() as db: yield db
    app.dependency_overrides[get_db] = isolated_db
    yield app, sessions
    engine.dispose()


def insert(sessions, module='homework', kind='submission', key='one', owner='20260001', data=None,
           created=datetime(2026,9,26,9), updated=None, role='student', raw=None):
    with sessions() as db:
        row = DomainRecord(module=module, record_type=kind, record_key=key, owner_id=owner, role=role,
            payload=raw if raw is not None else json.dumps(data or {}), created_at=created, updated_at=updated or created)
        db.add(row); db.commit(); return row.id


def headers(username='teacher', role='teacher', **extra):
    return {'Authorization':'Bearer '+create_access_token(username, role), **extra}


async def request(app, method='GET', path='/analytics/overview', **kwargs):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://synthetic.test') as client:
        return await client.request(method, path, headers=kwargs.pop('headers',headers()), **kwargs)


@pytest.mark.parametrize('values,expected', [([0],0),([0,100],50),([],None),([None,'',False,True,float('nan'),float('inf'),-1,101,'50'],None)])
def test_mean_accepts_only_finite_scale_numbers(values, expected):
    assert helper('_observed_mean')(values) == expected


@pytest.mark.parametrize('value,minutes', [('UTC',0),(' +08:00 ',480),('-05:30',-330),('+14:00',840),('-14:00',-840),('+00:00',0),('',None),(' ',None),(None,None),(True,None),(8,None),('Asia/Shanghai',None),('UTC+8',None),('+14:01',None),('+15:00',None),('+8:00',None),('+01:60',None)])
def test_recorded_timezone_declaration(value, minutes):
    tz=helper('_parse_recorded_timezone_declaration')(value)
    assert (None if tz is None else int(tz.utcoffset(None).total_seconds()/60)) == minutes


def test_recorded_timezone_settings_and_example_empty_defaults():
    field = type(settings).model_fields.get('ANALYTICS_RECORDED_TIMEZONE')
    assert field is not None and field.default == ''
    manifest = json.loads((Path(__file__).resolve().parents[2] / 'stage-manifest.json').read_text())
    contract = manifest['public_configuration_contract']
    assert contract['total_declarations'] == 1
    assert contract['empty_declarations'] == 1
    assert contract['nonempty_declarations'] == 0


def test_record_adapter_scope_decode_dedup_and_stable_failure(harness):
    _,sessions=harness
    insert(sessions,key='duplicate',data={'studentId':'20269999','verified':True},updated=datetime(2026,9,26,10))
    newest=insert(sessions,key='duplicate',data={'studentId':'20269999','verified':True},updated=datetime(2026,9,26,11))
    insert(sessions,key='foreign',owner='20269999'); insert(sessions,key='ownerless',owner='')
    insert(sessions,key='broken',raw='{')
    with sessions() as db:
        read=helper('_read_metric_records')(db,'homework','submission',owner_ids=OWNERS)
        assert read['available'] is True and len(read['records'])==2
        row=next(r for r in read['records'] if r['recordKey']=='duplicate')
        assert row['dbId']==newest and row['ownerId']=='20260001'
        assert next(r for r in read['records'] if r['recordKey']=='broken')['decodeError'] is True
        assert helper('_read_metric_records')(db,'homework','submission',owner_ids=set())['records']==[]
    class Broken:
        def query(self,*args): raise SQLAlchemyError('private SQL must not leak')
    failed=helper('_read_metric_records')(Broken(),'homework','submission',owner_ids=OWNERS)
    assert failed['available'] is False and failed['reason']=='source_unavailable'


def test_evidence_unavailable_null_and_raw_zero():
    evidence=helper('_metric_evidence')(evidence_status='measured',provenance_status='legacy_unknown',source='inventory',label='saved',sample_count=1,raw_mean=0)
    assert evidence['rawMean']==0 and evidence['reason'] is None and evidence['window'] is None


def test_window_exact_completed_utc_days():
    window=helper('_activity_window')(now=NOW)
    assert window['timezone']=='UTC' and window['startInclusive']=='2026-09-26T00:00:00Z' and window['endExclusive']=='2026-10-03T00:00:00Z'
    assert window['asOf']=='2026-10-03T07:11:54Z'
    with pytest.raises(ValueError): helper('_activity_window')(now=NOW,tz=timezone(timedelta(hours=8)))


def test_activity_envelope_owners_and_distinct_date_hour_window():
    rows=[record('A1'),record('A2'),record('B',owner='20260002'),record('A-next',created='2026-09-27T09:00:00Z'),
          record('old',created='2026-09-25T23:59:59Z'),record('end',created='2026-10-03T00:00:00Z'),record('future',created='2026-10-05T00:00:00Z'),record('foreign',owner='20269999')]
    out=helper('_activity_series')([{'username':v} for v in OWNERS],[source(rows),source()],now=NOW)
    assert out['weeklyActivityDates']==['2026-09-'+str(i) for i in range(26,31)]+['2026-10-01','2026-10-02']
    assert out['weeklyActivityCounts']==[2,1,0,0,0,0,0] and out['weeklyActivityRates']==[100,50,0,0,0,0,0]
    assert out['hourlyActiveData'][9]==2 and sum(out['hourlyActiveData'])==2
    assert out['weeklyActivityEvidence']['verifiedSampleCount']==0 and out['weeklyActivityEvidence']['provenanceStatus']=='legacy_unknown'
    assert out['recordedSubmissionCount']==7


@pytest.mark.parametrize('fault', ['naive','malformed','missing','unavailable'])
def test_activity_incomplete_not_zero_and_exact_inventory(fault):
    rows=[record('valid')]; src=source(rows)
    if fault=='naive': rows.append(record('bad',created=datetime(2026,9,26,9))); src['recordedTimezone']=None;src['recordedTimezoneDeclaration']=None
    if fault=='malformed': rows.append({**record('bad'),'decodeError':True})
    if fault=='missing': rows.append(record('bad',created=None))
    if fault=='unavailable': src['available']=False;src['reason']='source_unavailable'
    out=helper('_activity_series')([{'username':'20260001'}],[src,source()],now=NOW)
    assert out['weeklyActivityRates']==[None]*7 and out['hourlyActiveData']==[None]*24
    assert out['weeklyActivityEvidence']['coverageComplete'] is False
    assert out['recordedSubmissionCount']==(None if fault=='unavailable' else 2)


def test_activity_complete_empty_true_zero_empty_roster_and_offset_boundaries():
    fn=helper('_activity_series'); students=[{'username':'20260001'}]
    out=fn(students,[source(),source()],now=NOW)
    assert out['weeklyActivityRates']==[0]*7 and out['hourlyActiveData']==[0]*24
    assert out['weeklyActivityEvidence']['reason']=='complete_record_read'
    assert fn([],[source(),source()],now=NOW)['weeklyActivityRates']==[None]*7
    for decl,created in [('+08:00',datetime(2026,9,26,8)),('-05:30',datetime(2026,9,25,18,30))]:
        src=source([record(created=created)]);src['recordedTimezone']=helper('_parse_recorded_timezone_declaration')(decl);src['recordedTimezoneDeclaration']=decl
        out=fn(students,[src,source()],now=NOW)
        assert out['weeklyActivityCounts'][0]==1 and out['hourlyActiveData'][0]==1
        assert out['weeklyActivityEvidence']['recordedTimezone']==decl


@sync_asgi
async def test_overview_http_read_only_null_metrics_and_current_identity(harness, monkeypatch):
    app,sessions=harness
    def forbidden(*args,**kwargs): raise AssertionError('Read attempted write')
    monkeypatch.setattr(JsonStore,'upsert',forbidden)
    for _ in range(2):
        response=await request(app); assert response.status_code==200, response.text
        data=response.json()['data']; assert data['summary']['averageProgress'] is None and data['summary']['averageFocus'] is None
        assert data['classRadarValues']==[None]*6 and data['aiAdvices']==[] and data['actionQueue']==[]
    assert (await request(app,headers=headers('20260001','teacher'))).status_code==403
    assert (await request(app,headers=headers('deleted'))).status_code==401
    with sessions() as db: db.get(UserAccount,'teacher').role='student'; db.commit()
    assert (await request(app)).status_code==403


@sync_asgi
async def test_students_details_zero_diagnosis_missing_and_scope(harness):
    app,sessions=harness
    insert(sessions,data={'diagnosis':{'scores':{'alina':0,'codeninja':'bad','profx':False}},'grade':'A','verified':True})
    insert(sessions,module='exams',kind='mistake',key='mistake',data={'studentId':'wrong','wrongCount':0,'title':'Saved title'})
    data=(await request(app,path='/analytics/students/20260001')).json()['data']
    assert data['progress'] is None and data['focus'] is None and data['radarValues']==[0,None,None,None,None,None]
    assert data['radarEvidence']['规划一致性']['evidenceStatus']=='inferred'
    assert data['errors'][0]['count']==0 and data['timeline']==[]
    assert (await request(app,path='/analytics/students/20269999')).status_code==403
    settings.TEACHER_STUDENT_ASSIGNMENTS=json.dumps({'teacher':sorted(OWNERS|{'20268888'})})
    assert (await request(app,path='/analytics/students/20268888')).status_code==404
    mine=(await request(app,path='/analytics/students/me?user_id=20260001',headers=headers('20260001'))).json()['data']
    assert mine['classRadarValues']==[None]*6


@sync_asgi
async def test_generation_unavailable_before_reads_writes_and_manual_records_preserved(harness,monkeypatch):
    app,sessions=harness
    original=a._student_cards
    def forbidden(*args,**kwargs): raise AssertionError('generation performed work')
    monkeypatch.setattr(a,'_student_cards',forbidden); monkeypatch.setattr(JsonStore,'upsert',forbidden)
    for path in ['/analytics/advices/generate','/analytics/action-queue/generate']:
        res=await request(app,'POST',path,json={}); assert res.status_code==503 and res.json()['detail']=='analytics_generation_unavailable'
    monkeypatch.undo()
    settings.TEACHER_STUDENT_ASSIGNMENTS=json.dumps({'teacher':sorted(OWNERS)})
    res=await request(app,'POST','/analytics/interactions',json={'type':'nudge','title':'Manual','target':{'studentIds':['20260001']},'payload':{'desc':'Saved reminder'}})
    assert res.status_code==200 and res.json()['data']['record']['id']
    with sessions() as db: assert db.query(DomainRecord).filter_by(module='analytics',record_type='interaction').count()==1


@sync_asgi
@pytest.mark.parametrize('decl,expected_hour', [('',None),('bad',None),('UTC',9),('+08:00',1)])
async def test_http_storage_timezone_operator_only_exact_total(harness,monkeypatch,decl,expected_hour):
    app,sessions=harness; insert(sessions,data={'submittedAt':'2026-09-27T22:00:00Z','createdAt':'2026-09-27T22:00:00Z'})
    monkeypatch.setitem(settings.__dict__,'ANALYTICS_RECORDED_TIMEZONE',decl)
    monkeypatch.setattr(a,'_analytics_now',lambda:NOW,raising=False)
    res=await request(app,path='/analytics/overview?recordedTimezone=+08:00',headers=headers(**{'X-Recorded-Timezone':'UTC'}))
    assert res.status_code==200,res.text
    data=res.json()['data']; assert data['summary']['recordedSubmissionCount']==1
    if expected_hour is None: assert data['hourlyActiveData']==[None]*24
    else: assert data['hourlyActiveData'][expected_hour]==1 and sum(data['hourlyActiveData'])==1
    assert data['weeklyActivityEvidence']['verifiedSampleCount']==0


@sync_asgi
async def test_forum_envelope_and_valid_sidecar_counts_no_name_spoof(harness):
    app,sessions=harness
    insert(sessions,module='forum',kind='post',key='post',data={'id':'post','replies':[{'id':'reply','authorId':'20260002'},{'id':'spoof','author':'Duplicate name','authorRole':'student','provenance':'verified_account'}]})
    insert(sessions,module='forum',kind='post',key='foreign',owner='20269999',data={'authorUsername':'20260001','author':'Duplicate name'})
    insert(sessions,module='forum',kind='reply_identity',key='reply',owner='20260002',data={'postId':'post','replyId':'reply','authorId':'20260002','authorRole':'student'})
    cards=(await request(app,path='/analytics/students')).json()['data']; cards={v['username']:v for v in cards}
    assert cards['20260001']['forumCount']==1 and cards['20260002']['forumCount']==0 and cards['20260002']['replyCount']==1
    assert cards['20260001']['radarEvidence']['学术论坛活跃度']['evidenceStatus']=='inferred'


@sync_asgi
async def test_interaction_completion_projection_weighted_dedup_outsiders_and_history(harness):
    app,sessions=harness
    for key,recipients in [('i1',['20260001','20260002']),('i2',['20260001'])]:
        insert(sessions,module='analytics',kind='interaction',key=key,owner='teacher',role='teacher',data={'id':key,'studentIds':recipients,'completionRate':99,'status':'running'})
    for key,owner,iid in [('c1','20260001','i1'),('c2','20260001','i1'),('foreign','20269999','i1'),('c3','20260001','i2')]:
        insert(sessions,module='analytics',kind='interaction_completion',key=key,owner=owner,data={'interactionId':iid,'userId':'forged'})
    insert(sessions,module='analytics',kind='action',key='action',owner='teacher',data={'id':'action','studentIds':['20260001'],'recordEvidence':{'evidenceStatus':'measured','provenanceStatus':'verified_server'}})
    out=(await request(app)).json()['data']; records=out['interactionRecords']
    assert [v['completionRate'] for v in records]==[50,100]
    assert out['summary']['responseRate']==67
    assert records[0]['completionEvidence']['evidenceStatus']=='self_reported'
    assert out['actionQueue'][0]['recordEvidence']['evidenceStatus']=='unavailable'

def test_record_adapter_latest_aware_update_uses_instant_not_lexical():
    common = dict(module='homework', record_type='submission', record_key='same', owner_id='20260001', role='', status='', payload='{}', created_at=NOW)
    older = SimpleNamespace(**common,id=1,updated_at=datetime(2026,9,26,11,tzinfo=timezone(timedelta(hours=8))))
    newer = SimpleNamespace(**common,id=2,updated_at=datetime(2026,9,26,9,tzinfo=timezone.utc))
    class Query:
        def filter(self,*args): return self
        def all(self): return [older,newer]
    class DB:
        def query(self,*args): return Query()
    read=helper('_read_metric_records')(DB(),'homework','submission',owner_ids=OWNERS)
    assert len(read['records'])==1 and read['records'][0]['dbId']==2


def test_activity_rejects_unrelated_storage_types_and_offset_aware_first_save():
    rows=[record('included',created='2026-09-26T08:00:00+08:00'),{**record('wrong-kind'),'module':'forum','recordType':'post'},
          record('before',created='2026-09-25T18:29:59-05:30'),record('start',owner='20260002',created='2026-09-25T18:30:00-05:30')]
    out=helper('_activity_series')([{'username':v} for v in OWNERS],[source(rows),source()],now=NOW)
    assert out['recordedSubmissionCount']==3
    assert out['weeklyActivityCounts']==[2,0,0,0,0,0,0] and out['hourlyActiveData'][0]==2
    assert out['hourlyActiveData'][9]==0


@sync_asgi
async def test_http_single_operator_resolution_no_writes_inventory_and_invalid_reason(harness,monkeypatch):
    app,sessions=harness
    insert(sessions)
    before=[]
    with sessions() as db:
        before=[(r.id,r.payload,r.created_at,r.updated_at) for r in db.query(DomainRecord).all()]
    original=a._recorded_policy; calls=[]
    def once(): calls.append(True); return original()
    monkeypatch.setattr(a,'_recorded_policy',once)
    monkeypatch.setitem(settings.__dict__,'ANALYTICS_RECORDED_TIMEZONE','America/New_York')
    monkeypatch.setenv('TZ','Asia/Shanghai')
    monkeypatch.setattr(a,'_analytics_now',lambda:NOW)
    response=await request(app,path='/analytics/overview?recordedTimezone=UTC')
    assert response.status_code==200,response.text
    data=response.json()['data']
    assert len(calls)==1 and data['summary']['recordedSubmissionCount']==1
    assert data['weeklyActivityEvidence']['reason']=='invalid_recorded_timezone_declaration'
    assert data['weeklyActivityEvidence']['recordedTimezone'] is None
    with sessions() as db:
        assert [(r.id,r.payload,r.created_at,r.updated_at) for r in db.query(DomainRecord).all()]==before


@sync_asgi
async def test_http_recorded_grade_facts_preserve_letters_raw_limits_and_zero(harness):
    app,sessions=harness
    insert(sessions,data={'grade':'A','aiScore':'invalid','diagnosis':{'scores':{'alina':0}}})
    insert(sessions,module='exams',kind='attempt',key='exam-good',data={'objectiveScore':0,'maxObjectiveScore':20,'programmingScore':35,'totalScore':40})
    insert(sessions,module='exams',kind='attempt',key='exam-bad',data={'objectiveScore':25,'maxObjectiveScore':20,'programmingScore':False})
    data=(await request(app,path='/analytics/students/20260001')).json()['data']
    facts=data['recordedGrades']
    assert any(v['kind']=='letter_grade' and v['value']=='A' for v in facts)
    assert any(v['kind']=='objective_percentage' and v['value']==0 for v in facts)
    assert not any(v['kind']=='objective_percentage' and v['value']>100 for v in facts)
    assert data['progress'] is None and data['radarValues'][1:3]==[None,None]


@sync_asgi
async def test_http_contract_fixture_export(harness,monkeypatch,tmp_path):
    """Frozen downstream fixtures are actual HTTP JSON, never helper DTO copies."""
    app,sessions=harness
    monkeypatch.setattr(a,'_analytics_now',lambda:NOW)
    fixture={'metadata':{'synthetic':True,'accounts':'synthetic canonical accounts only','records':'synthetic in-memory SQLite only','timezoneDeclarations':['','UTC','+08:00','invalid'],'windowClock':'2026-10-03T07:11:54Z'}}
    async def capture(key,path='/analytics/overview',method='GET',**kwargs):
        response=await request(app,method,path,**kwargs)
        fixture[key]={'status':response.status_code,'request':{'method':method,'path':path},**response.json()}
        return fixture[key]
    fixture['empty_overview']=await capture('empty_overview')
    insert(sessions,key='A',data={'diagnosis':{'scores':{'alina':0}},'grade':'A'})
    insert(sessions,key='B',owner='20260002',data={'verified':True,'studentId':'20269999'})
    await capture('overview')
    assert fixture['overview']['data']['summary']['recordedSubmissionCount']==2
    assert fixture['overview']['data']['weeklyActivityRates']==[None]*7
    monkeypatch.setitem(settings.__dict__,'ANALYTICS_RECORDED_TIMEZONE','UTC')
    await capture('utc_overview')
    assert fixture['utc_overview']['data']['weeklyActivityCounts']==[2,0,0,0,0,0,0]
    assert fixture['utc_overview']['data']['hourlyActiveData'][9]==2
    monkeypatch.setitem(settings.__dict__,'ANALYTICS_RECORDED_TIMEZONE','+08:00')
    await capture('offset_overview')
    assert fixture['offset_overview']['data']['hourlyActiveData'][1]==2
    monkeypatch.setitem(settings.__dict__,'ANALYTICS_RECORDED_TIMEZONE','invalid')
    await capture('invalid_overview')
    assert fixture['invalid_overview']['data']['weeklyActivityEvidence']['reason']=='invalid_recorded_timezone_declaration'
    await capture('student_detail','/analytics/students/20260001')
    await capture('students','/analytics/students')
    insert(sessions,module='analytics',kind='action',key='historical-action',owner='teacher',role='teacher',data={'id':'spoofed-id','title':'Historical reminder','reason':'Unverified saved explanation','studentIds':['20260002','20260001'],'recordEvidence':{'evidenceStatus':'measured','provenanceStatus':'verified_server'}})
    await capture('action_queue','/analytics/action-queue')
    insert(sessions,module='analytics',kind='interaction',key='interaction-A',owner='teacher',role='teacher',data={'id':'spoofed-id','title':'Manual saved interaction','studentIds':['20260001','20260002'],'completionRate':99,'status':'running'})
    insert(sessions,module='analytics',kind='interaction_completion',key='completion-A',data={'interactionId':'interaction-A','userId':'forged'})
    await capture('interactions','/analytics/interactions')
    await capture('advice_generation','/analytics/advices/generate','POST',json={})
    await capture('action_generation','/analytics/action-queue/generate','POST',json={})
    assert fixture['advice_generation']['status']==503 and fixture['advice_generation']['detail']=='analytics_generation_unavailable'
    assert fixture['action_queue']['data'][0]['recordEvidence']['evidenceStatus']=='unavailable'
    assert fixture['interactions']['data'][0]['completionRate']==50
    path=tmp_path/'analytics-http-fixtures.json'
    path.write_text(json.dumps(fixture,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
    print(f'A4_HTTP_FIXTURE_EXPORT={path}')
# Append to the unchanged frozen backend selected file in a runtime-owned overlay.
# No new imports, fixture changes, source edits, services or capabilities.

@sync_asgi
@pytest.mark.parametrize('reply_id', [[], {}])
@pytest.mark.parametrize('path', ['/analytics/students', '/analytics/overview'])
async def test_review_malformed_foreign_reply_id_retains_roster(harness, reply_id, path):
    app, sessions = harness
    insert(sessions, module='forum', kind='post', key='foreign-bad-reply', owner='20269999',
           data={'replies': [{'id': reply_id}]})
    response = await request(app, path=path)
    assert response.status_code == 200, response.text
    data = response.json()['data']
    if path == '/analytics/students':
        assert {item['username'] for item in data} == OWNERS
        assert all(item['replyCount'] in (None, 0) for item in data)
    else:
        assert data['summary']['studentCount'] == 2


@sync_asgi
async def test_review_malformed_mistake_payload_preserves_storage_inventory(harness):
    app, sessions = harness
    insert(sessions, module='exams', kind='mistake', key='valid-mistake', data={'title':'Saved text', 'wrongCount':0})
    insert(sessions, module='exams', kind='mistake', key='malformed-mistake', raw='{')
    response = await request(app, path='/analytics/students/20260001')
    assert response.status_code == 200, response.text
    data = response.json()['data']
    assert data['errorCount'] == 2, data['errorCountEvidence']
    assert data['errorCountEvidence']['evidenceStatus'] == 'measured'
    assert data['errorCountEvidence']['provenanceStatus'] == 'legacy_unknown'
    assert data['errors'][0]['count'] == 0
