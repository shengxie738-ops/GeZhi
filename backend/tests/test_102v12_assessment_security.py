"""Actual routers and isolated SQLite; never imports application startup."""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.endpoints import exams, homework, auth, learning_diagnosis
from app.api.deps import ensure_self_or_teacher
from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token
from app.models.domain_record import DomainRecord
from app.repositories.json_store import JsonStore


@pytest.fixture
def world(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    DomainRecord.__table__.create(engine)
    db = sessionmaker(bind=engine)()
    app = FastAPI()
    for module in (exams, homework, auth, learning_diagnosis):
        app.include_router(module.router)
    app.dependency_overrides[get_db] = lambda: db
    object.__setattr__(settings, 'TEACHER_STUDENT_ASSIGNMENTS', json.dumps({'teacher': ['alice']}))
    monkeypatch.setattr(exams, 'publish_learning_activity_safely', AsyncMock())
    monkeypatch.setattr(homework, 'publish_learning_activity_safely', AsyncMock())
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, JsonStore(db)
    db.close()
    engine.dispose()


def headers(user='alice', role='student'):
    return {'Authorization': 'Bearer ' + create_access_token(user, role)}


def seed(store, **patch):
    exam = {'id': 'exam1', 'teacherId': 'teacher', 'status': 'running', 'title': 'Exam',
            'startsAt': (datetime.now(timezone.utc)-timedelta(minutes=5)).isoformat(), 'durationMinutes': 60,
            'objectiveQuestions': [{'id': 'q1', 'type': 'choice', 'title': 'Q', 'correctAnswer': 'A', 'score': 4, 'explanation': 'secret'}],
            'programmingProblems': [{'id': 'p1', 'score': 20, 'testCases': [{'input': 'private', 'expected': 'secret'}], 'samples': [{'input': 'public', 'output': 'sample'}]}], **patch}
    store.upsert('exams', 'exam', 'exam1', exam)
    return exam


def start(client):
    return client.post('/exams/exam1/attempts', json={'userId': 'alice'}, headers=headers())


def test_teacher_cannot_read_unassigned_student(world):
    client, store = world
    seed(store)
    assert client.get('/exams/student/bob/overview', headers=headers('teacher', 'teacher')).status_code == 403


@pytest.mark.parametrize('method,path,body', [
    ('get','/homework/teacher/overview',None), ('get','/homework/teacher/submissions?homeworkId=hw1',None),
    ('post','/homework/attempts/a1/grade',{'grade':100}), ('post','/homework',{'title':'Injected'}),
    ('get','/homework/hw1?userId=alice',None), ('post','/homework/hw1/diagnose',{'userId':'alice'}),
])
def test_homework_requires_authentication(world, method, path, body):
    client, _ = world
    assert client.request(method,path,json=body).status_code == 401


def test_exam_student_payload_redaction(world):
    client, store = world
    seed(store)
    for path in ('/exams/exam1?user_id=alice','/exams/student/alice/overview'):
        response=client.get(path, headers=headers())
        assert response.status_code == 200
        serialized=response.text
        assert 'correctAnswer' not in serialized and 'secret' not in serialized and 'private' not in serialized
        assert 'public' in serialized


@pytest.mark.parametrize('status', ['draft', 'completed'])
def test_cannot_start_unavailable_exam(world,status):
    client,store=world;seed(store,status=status)
    assert start(client).status_code == 409


def test_missing_and_future_exam(world):
    client,store=world
    assert start(client).status_code == 404
    seed(store,startsAt=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())
    assert start(client).status_code == 409


def test_restart_resumes_and_submit_is_immutable(world):
    client,store=world;seed(store)
    assert start(client).status_code == 200
    attempt_id='exam1:alice'
    assert client.put(f'/exams/attempts/{attempt_id}/answers',json={'answers':{'q1':'B'}},headers=headers()).status_code == 200
    response=start(client)
    assert response.json()['data']['answers'] == {'q1':'B'}
    first=client.post(f'/exams/attempts/{attempt_id}/submit',json={},headers=headers())
    second=client.post(f'/exams/attempts/{attempt_id}/submit',json={'answers':{'q1':'A'}},headers=headers())
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert len(store.list_payloads('exams','mistake')) == 1
    assert store.get_payload('exams','attempt',attempt_id)['answers']['q1']=='B'
    assert client.put(f'/exams/attempts/{attempt_id}/answers',json={'answers':{'q1':'A'}},headers=headers()).status_code == 409


def test_judge_requires_owner_and_final_attempt(world):
    client,store=world;seed(store);start(client)
    path='/exams/attempts/exam1:alice/judge-programming'
    assert client.post(path,json={},headers=headers('bob')).status_code == 403
    assert client.post(path,json={},headers=headers()).status_code == 409


def test_late_finalize_uses_saved_answers(world):
    client,store=world;seed(store);start(client)
    client.put('/exams/attempts/exam1:alice/answers',json={'answers':{'q1':'B'}},headers=headers())
    seed(store, startsAt=(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat())
    assert client.put('/exams/attempts/exam1:alice/answers',json={'answers':{'q1':'A'}},headers=headers()).status_code == 403
    response=client.post('/exams/attempts/exam1:alice/submit',json={'answers':{'q1':'A'}},headers=headers())
    assert response.status_code==200
    assert store.get_payload('exams','attempt','exam1:alice')['answers']['q1']=='B'


def test_activity_requires_configured_token(world):
    client,_=world
    body={'student_id':'alice','source_module':'exams','content_type':'EXAM','content_id':'exam1','attempt_id':'a1','status':'COMPLETED'}
    assert client.post('/learning-diagnosis/internal/activity',json=body).status_code == 503


def test_teacher_self_registration_is_closed(world):
    client,_=world
    response=client.post('/teacher/register',json={'username':'newteacher','password':'pass123','role':'teacher','teacher_id':'anything'})
    assert response.status_code == 403


def test_internal_activity_authorized_and_timestamp_once(world, monkeypatch):
    client,_=world
    monkeypatch.setattr(settings,'LEARNING_DIAGNOSIS_INTERNAL_TOKEN','unit-test-token')
    handler=AsyncMock(return_value={'status':'IGNORED'})
    monkeypatch.setattr(learning_diagnosis.ActivityListener,'handle',handler)
    body={'student_id':'alice','source_module':'exams','content_type':'EXAM','content_id':'exam1','attempt_id':'a1','status':'COMPLETED'}
    assert client.post('/learning-diagnosis/internal/activity',json=body).status_code==401
    response=client.post('/learning-diagnosis/internal/activity',json=body,headers={'X-Learning-Diagnosis-Internal':'unit-test-token'})
    assert response.status_code==200
    assert handler.await_args.args[0].occurred_at


def test_judge_unavailable_is_not_final_zero(world, monkeypatch):
    client,store=world;seed(store);start(client)
    client.post('/exams/attempts/exam1:alice/submit',json={'answers':{'q1':'A','p1':'print(1)'}},headers=headers())
    monkeypatch.setattr(exams.CodeSandbox,'run',lambda *args,**kwargs: {'status':'unavailable','available':False,'passed':0,'total':1,'error':'execution disabled'})
    response=client.post('/exams/attempts/exam1:alice/judge-programming',json={},headers=headers())
    assert response.status_code==200
    assert response.json()['data']['status']=='unavailable'
    attempt=store.get_payload('exams','attempt','exam1:alice')
    assert attempt.get('programmingScore') is None
    assert attempt.get('totalScore') is None
    assert attempt['programmingStatus']=='pending_judge'


def test_homework_teacher_class_and_resource_scope(world):
    client,store=world
    store.upsert('homework','homework','hw1',{'id':'hw1','teacherId':'teacher','title':'HW'})
    store.upsert('homework','submission','hw1:alice',{'id':'hw1:alice','homeworkId':'hw1','studentId':'alice','answers':{'q1':'private'}},owner_id='alice')
    assert client.get('/homework/hw1?userId=alice',headers=headers('bob')).status_code==403
    assert client.get('/homework/teacher/submissions?homeworkId=hw1',headers=headers('other-teacher','teacher')).status_code==403
    assert client.post('/homework/attempts/hw1:alice/grade',json={'grade':90},headers=headers()).status_code==403
    assert client.post('/homework/attempts/hw1:alice/grade',json={'grade':90},headers=headers('teacher','teacher')).status_code==200
    result=client.get('/homework/hw1?userId=alice',headers=headers()).json()['data']
    assert result['grade']==90


def test_student_cannot_access_other_teachers_exam(world):
    client,store=world;seed(store,teacherId='other-teacher')
    assert start(client).status_code==403
    assert client.get('/exams/exam1?user_id=alice',headers=headers()).status_code==403
    assert client.get('/exams/student/alice/overview',headers=headers()).json()['data']['exams']==[]


def test_exam_transaction_rolls_back_related_records(world):
    from app.repositories.json_store import atomic_store
    _,store=world
    with pytest.raises(RuntimeError):
        with atomic_store(store.db):
            store.upsert('exams','attempt','rollback',{'studentId':'alice'},owner_id='alice')
            raise RuntimeError('intentional rollback')
    assert store.get_payload('exams','attempt','rollback') is None


def test_targeted_homework_cannot_leak_to_roster_peer(world,monkeypatch):
    client,store=world
    monkeypatch.setattr(settings,'TEACHER_STUDENT_ASSIGNMENTS',json.dumps({'teacher':['alice','bob']}))
    store.upsert('homework','homework','targeted',{'id':'targeted','teacherId':'teacher','studentIds':['alice']})
    assert client.get('/homework/targeted?userId=bob',headers=headers('bob')).status_code==403
    assert client.get('/homework/student/list',headers=headers('bob')).json()['data']==[]


def test_homework_resubmit_cannot_erase_grade(world):
    client,store=world
    store.upsert('homework','homework','hw1',{'id':'hw1','teacherId':'teacher'})
    store.upsert('homework','submission','hw1:alice',{'id':'hw1:alice','homeworkId':'hw1','studentId':'alice','status':'graded','grade':90},owner_id='alice')
    response=client.post('/homework/hw1/submit',json={'answers':{'q':'changed'}},headers=headers())
    assert response.status_code==409
    assert store.get_payload('homework','submission','hw1:alice')['grade']==90


def test_review_task_scope_and_persistence(world):
    client,store=world
    result=client.post('/exams/questions/q1/review-task',json={'studentIds':['bob']},headers=headers('teacher','teacher'))
    assert result.status_code==403
    result=client.post('/exams/questions/q1/review-task',json={'title':'Review','studentIds':['alice']},headers=headers('teacher','teacher'))
    assert result.status_code==200
    assert len(client.get('/exams/student/alice/review-tasks',headers=headers()).json()['data']['tasks'])==1
    assert client.get('/exams/student/bob/review-tasks',headers=headers('bob')).json()['data']['tasks']==[]


def test_homework_diagnosis_failure_has_no_fabricated_score(world,monkeypatch):
    client,store=world
    store.upsert('homework','homework','hw1',{'id':'hw1','teacherId':'teacher','questions':[]})
    def unavailable(*args,**kwargs):
        raise RuntimeError('offline test')
    monkeypatch.setattr(homework,'build_chat_model',unavailable)
    response=client.post('/homework/hw1/diagnose',json={'answers':{'q':'long answer'*30}},headers=headers())
    assert response.status_code==503
    assert store.list_payloads('homework','diagnosis')==[]


def test_homework_class_size_uses_assigned_roster(world):
    client,store=world
    store.upsert('homework','homework','hw1',{'id':'hw1','teacherId':'teacher','questions':[]})
    result=client.get('/homework/teacher/analysis?homeworkId=hw1',headers=headers('teacher','teacher')).json()['data']
    assert result['classSize']==1


def test_mistake_patch_cannot_replace_identity_or_claim_verified_score(world):
    client,store=world
    store.upsert('exams','mistake','mine',{'id':'mine','studentId':'alice','questionId':'q','examId':'exam1'},owner_id='alice')
    response=client.patch('/exams/mistakes/mine',json={'studentId':'bob','questionId':'other','mastered':True},headers=headers())
    assert response.status_code==200
    saved=store.get_payload('exams','mistake','mine')
    assert saved['studentId']=='alice' and saved['questionId']=='q'
    event=exams.publish_learning_activity_safely.await_args.args[1]
    assert event['student_id']=='alice'
    assert 'score' not in event['result_payload'] and 'passed' not in event['result_payload']


def test_student_dashboard_hides_other_roster_resources(world):
    from app.api.endpoints import dashboard
    client,store=world
    store.upsert('homework','homework','other-hw',{'id':'other-hw','teacherId':'other-teacher','title':'PRIVATE'})
    seed(store,teacherId='other-teacher')
    now=datetime.now(timezone.utc)
    assert dashboard._build_homework_dashboard('alice',store,now)['homeworkList']==[]
    assert dashboard._build_exam_dashboard('alice',store,now)['examAlerts']==[]


@pytest.mark.parametrize('patch',[
    {'status':'unknown'}, {'status':'running','durationMinutes':0},
    {'status':'scheduled','startsAt':'not-a-date'}, {'status':'running','durationMinutes':'NaN'},
    {'status':'scheduled','startsAt':'2026-10-02T10:00:00+08:00','endsAt':'2026-10-02T09:00:00+08:00'},
])
def test_exam_creation_validates_publication(world,patch):
    client,store=world
    response=client.post('/exams',json={'id':'bad','title':'Invalid','startsAt':'2026-10-02T10:00:00+08:00',**patch},headers=headers('teacher','teacher'))
    assert response.status_code==422
    assert store.get_payload('exams','exam','bad') is None


def test_publish_transition_validates_window(world):
    client,store=world
    seed(store,status='draft',durationMinutes=-1)
    response=client.patch('/exams/exam1/status',json={'status':'scheduled'},headers=headers('teacher','teacher'))
    assert response.status_code==422
    assert store.get_payload('exams','exam','exam1')['status']=='draft'
