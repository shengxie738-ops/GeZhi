"""Offline HTTP regression tests. Routers only; never import application startup."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.endpoints import agents, chat, evaluator
from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.models.user_account import UserAccount
from app.repositories.json_store import JsonStore


@pytest.fixture
def client(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    for username, role, class_name in [('alice', 'student', 'A'), ('bob', 'student', 'B'), ('ann', 'student', 'A'), ('teacher', 'teacher', 'A')]:
        db.add(UserAccount(username=username, role=role, class_name=class_name, password_hash='unused'))
    db.commit()
    app = FastAPI()
    for module in (agents, chat, evaluator):
        app.include_router(module.router)
    app.dependency_overrides[get_db] = lambda: db
    monkeypatch.setattr(chat, 'agent_graph', SimpleNamespace(ainvoke=AsyncMock(return_value={'messages': [SimpleNamespace(content='safe reply')]})))
    monkeypatch.setattr(chat, 'retrieve_chunks_for_user', lambda *a, **k: [])
    monkeypatch.setattr(chat, 'upload_document_to_default_repository', lambda *a, **k: {'dataset_id': 'fake', 'rag_document_id': 'fake'})
    import app.services.profile_extractor as profiles
    monkeypatch.setattr(profiles, 'extract_and_update_profile', AsyncMock())
    with TestClient(app) as http:
        yield http, db
    db.close()
    engine.dispose()


def auth(name='alice', role='student'):
    return {'Authorization': 'Bearer ' + create_access_token(name, role)}


PRIVATE_ROUTES = [
    ('post', '/chat', {'message': 'hello'}),
    ('post', '/chat/stream', {'message': 'hello'}),
    ('post', '/v1/chat/completions', {'model': 'agent_tutor', 'messages': []}),
    ('post', '/chat/completions', {'model': 'agent_tutor', 'messages': [], 'stream': True}),
    ('get', '/diagnosis/history?user_id=alice', None),
    ('get', '/chat/history?session_id=alice', None),
    ('post', '/chat/history', {'user_id': 'alice', 'content': 'test'}),
    ('post', '/chat/history/batch', {'user_id': 'alice', 'messages': [{'content': 'test'}]}),
    ('delete', '/chat/history?session_id=alice', None),
    ('delete', '/chat/history/1?session_id=alice', None),
    ('get', '/agents', None),
    ('put', '/agents/test', {'prompt': 'test'}),
    ('delete', '/agents/test', None),
    ('post', '/evaluator/attempts', {'quizId': 'quiz_001', 'userId': 'alice'}),
    ('get', '/evaluator/attempts/a', None),
    ('post', '/evaluator/attempts/a/submit', {'answers': {}}),
    ('get', '/evaluator/attempts/a/result', None),
]


@pytest.mark.parametrize('method,path,body', PRIVATE_ROUTES)
@pytest.mark.parametrize('headers', [{}, {'Authorization': 'Bearer invalid'}])
def test_private_routes_require_valid_identity(client, method, path, body, headers):
    http, _ = client
    assert http.request(method, path, json=body, headers=headers).status_code == 401


@pytest.mark.parametrize('method,path,body', PRIVATE_ROUTES[4:10])
def test_history_cannot_target_other_student(client, method, path, body):
    http, _ = client
    assert http.request(method, path.replace('alice', 'bob'), json={**body, 'user_id': 'bob'} if body else None, headers=auth()).status_code == 403


@pytest.mark.parametrize('method', ['put', 'delete'])
def test_student_cannot_change_global_agents(client, method):
    http, _ = client
    assert http.request(method, '/agents/test', json={'prompt': 'test'} if method == 'put' else None, headers=auth()).status_code == 403


def test_evaluator_cannot_create_for_other_identity(client):
    http, _ = client
    assert http.post('/evaluator/attempts', json={'quizId': 'quiz_001', 'userId': 'bob'}, headers=auth()).status_code == 403


@pytest.mark.parametrize('suffix,method,body', [('', 'get', None), ('/submit', 'post', {'answers': {}}), ('/result', 'get', None)])
def test_evaluator_attempt_ownership(client, suffix, method, body):
    http, db = client
    JsonStore(db).upsert('evaluator', 'attempt', 'a', {'id': 'a', 'quizId': 'quiz_001', 'userId': 'bob', 'status': 'in_progress', 'result': {'score': 100}}, owner_id='bob')
    assert http.request(method, '/evaluator/attempts/a' + suffix, json=body, headers=auth()).status_code == 403


def test_evaluator_submission_is_immutable(client):
    http, db = client
    created = http.post('/evaluator/attempts', json={'quizId': 'quiz_001'}, headers=auth())
    assert created.status_code == 200
    attempt_id = created.json()['data']['id']
    url = '/evaluator/attempts/' + attempt_id + '/submit'
    first = http.post(url, json={'answers': {'q_001': 'A', 'q_002': True}}, headers=auth())
    assert first.status_code == 200
    retry = http.post(url, json={'answers': {'q_001': 'A', 'q_002': True}}, headers=auth())
    assert retry.json() == first.json()
    assert http.post(url, json={'answers': {}}, headers=auth()).status_code == 409
    assert JsonStore(db).get_payload('evaluator', 'attempt', attempt_id)['result']['score'] == 100


def test_upload_requires_owner_identity_before_any_file_processing(client):
    http, _ = client
    response = http.post('/user/upload', data={'user_id': 'bob'}, files={'file': ('a.txt', b'safe')}, headers=auth())
    assert response.status_code == 403


def test_teacher_can_change_global_config(client, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, 'AGENT_CONFIG_WRITERS', '["teacher"]')
    http, _ = client
    response = http.put('/agents/custom_test', json={'prompt': 'safe prompt'}, headers=auth('teacher', 'teacher'))
    assert response.status_code == 200
    assert next(item for item in http.get('/agents', headers=auth()).json()['data'] if item['id'] == 'custom_test')['prompt'] == 'safe prompt'


def test_owner_history_roundtrip(client):
    http, _ = client
    response = http.post('/chat/history', json={'user_id': 'alice', 'content': 'my note', 'agent_mode': 'tutor'}, headers=auth())
    assert response.status_code == 200
    message_id = response.json()['data']['id']
    listing = http.get('/chat/history?session_id=alice', headers=auth()).json()['data']
    assert listing[0]['content'] == 'my note'
    assert http.delete(f'/chat/history/{message_id}?session_id=alice', headers=auth()).json()['status'] == 'success'
    assert http.get('/chat/history?session_id=alice', headers=auth()).json()['data'] == []


@pytest.mark.parametrize('stream', [False, True])
def test_chat_uses_verified_identity_for_credentials_and_thread(client, monkeypatch, stream):
    http, db = client
    seen = []
    def credentials(_db, user_id, model_id):
        seen.append(user_id)
        return None
    monkeypatch.setattr(chat, 'find_user_custom_model_credentials', credentials)
    async def events(*args, **kwargs):
        assert kwargs['config']['configurable']['thread_id'].startswith('alice:')
        if False:
            yield None
    monkeypatch.setattr(chat.agent_graph, 'astream_events', events, raising=False)
    response = http.post('/chat/stream' if stream else '/chat', headers=auth(), json={'message': 'hello', 'sessionId': 'bob', 'thread_id': 'bob', 'agent_model': 'private-model'})
    assert response.status_code == 200
    assert seen == ['alice']
    from app.models.chat_message import ChatMessage
    assert {m.user_id for m in db.query(ChatMessage).all()} == {'alice'}


@pytest.mark.parametrize('stream', [False, True])
def test_openai_retrieval_uses_authenticated_owner(client, monkeypatch, stream):
    http, _ = client
    seen = []
    monkeypatch.setattr(chat, 'retrieve_chunks_for_user', lambda *a, **kw: seen.append(kw['user_id']) or [])
    async def events(*args, **kwargs):
        assert kwargs['config']['configurable']['thread_id'].startswith('alice:openai:')
        if False:
            yield None
    monkeypatch.setattr(chat.agent_graph, 'astream_events', events, raising=False)
    response = http.post('/v1/chat/completions', headers=auth(), json={'model': 'agent_tutor', 'messages': [{'role': 'user', 'content': 'Explain binary search trees'}], 'stream': stream})
    assert response.status_code == 200
    assert seen == ['alice']


@pytest.mark.parametrize('path', ['/diagnosis/history?user_id=', '/chat/history?session_id='])
@pytest.mark.parametrize('target,expected', [('ann', 200), ('bob', 403)])
def test_teacher_history_reads_are_roster_scoped(client, monkeypatch, path, target, expected):
    from app.core.config import settings
    monkeypatch.setattr(settings, 'TEACHER_STUDENT_ASSIGNMENTS', '{"teacher":["ann"]}')
    http, _ = client
    assert http.get(path + target, headers=auth('teacher', 'teacher')).status_code == expected


@pytest.mark.parametrize('method,path,body', PRIVATE_ROUTES[6:10])
def test_teacher_cannot_modify_student_history(client, monkeypatch, method, path, body):
    from app.core.config import settings
    monkeypatch.setattr(settings, 'TEACHER_STUDENT_ASSIGNMENTS', '{"teacher":["alice"]}')
    http, _ = client
    assert http.request(method, path, json=body, headers=auth('teacher', 'teacher')).status_code == 403


@pytest.mark.parametrize('suffix', ['', '/result'])
@pytest.mark.parametrize('target,expected', [('ann', 200), ('bob', 403)])
def test_teacher_attempt_reads_are_roster_scoped(client, monkeypatch, suffix, target, expected):
    from app.core.config import settings
    monkeypatch.setattr(settings, 'TEACHER_STUDENT_ASSIGNMENTS', '{"teacher":["ann"]}')
    http, db = client
    JsonStore(db).upsert('evaluator', 'attempt', 'a', {'id': 'a', 'quizId': 'quiz_001', 'userId': target, 'status': 'submitted', 'result': {'score': 100}}, owner_id=target)
    assert http.get('/evaluator/attempts/a' + suffix, headers=auth('teacher', 'teacher')).status_code == expected


def test_teacher_cannot_submit_assigned_student_attempt(client, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, 'TEACHER_STUDENT_ASSIGNMENTS', '{"teacher":["ann"]}')
    http, db = client
    JsonStore(db).upsert('evaluator', 'attempt', 'a', {'id': 'a', 'quizId': 'quiz_001', 'userId': 'ann', 'status': 'in_progress'}, owner_id='ann')
    assert http.post('/evaluator/attempts/a/submit', json={'answers': {}}, headers=auth('teacher', 'teacher')).status_code == 403


def test_unapproved_teacher_cannot_write_global_agent_config(client):
    http, _ = client
    assert http.put('/agents/custom_test', json={'prompt': 'unsafe'}, headers=auth('teacher', 'teacher')).status_code == 403
    assert http.delete('/agents/custom_test', headers=auth('teacher', 'teacher')).status_code == 403


@pytest.mark.parametrize('allowlist', ['', 'broken', '{}', '"teacher"', '["someone_else"]'])
def test_global_agent_writer_allowlist_fails_closed(client, monkeypatch, allowlist):
    from app.core.config import settings
    monkeypatch.setattr(settings, 'AGENT_CONFIG_WRITERS', allowlist)
    http, _ = client
    assert http.put('/agents/custom_test', json={'prompt': 'unsafe'}, headers=auth('teacher', 'teacher')).status_code == 403


def test_allowlisted_student_still_cannot_change_global_agents(client, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, 'AGENT_CONFIG_WRITERS', '["alice"]')
    http, _ = client
    assert http.put('/agents/custom_test', json={'prompt': 'unsafe'}, headers=auth()).status_code == 403


@pytest.mark.parametrize('headers', [{}, {'Authorization': 'Bearer invalid'}])
def test_upload_requires_authentication(client, headers):
    http, _ = client
    assert http.post('/user/upload', data={'user_id': 'alice'}, files={'file': ('a.txt', b'safe')}, headers=headers).status_code == 401
