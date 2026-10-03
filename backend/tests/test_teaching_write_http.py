"""Minimal isolated ASGI adapter. No app.main, aggregate router or server."""
import importlib
import asyncio
from functools import wraps

import httpx
import pytest
from fastapi import Depends, FastAPI, Header
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError

from tests.test_teaching_authorization import dbcase
from tests.test_teaching_receipts import writes_case, intent, SyntheticOperation, counts


def sync_asgi(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))
    return run


def feature(name):
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        pytest.fail(f"Task3 feature absent: {name}: {exc}")


def app_for(case):
    db, w, t, m, accounts = case
    adapter = feature("app.api.endpoints.teaching")
    app = FastAPI()
    app.include_router(adapter.router, prefix="/api")
    async def fixture_db():
        return db
    async def fixture_account(authorization: str | None = Header(default=None), session: Session = Depends(adapter.get_teaching_db)):
        return adapter.get_teaching_account(authorization, session)
    app.dependency_overrides[adapter.get_teaching_db] = fixture_db
    app.dependency_overrides[adapter.get_teaching_account] = fixture_account
    @app.post("/api/synthetic-write")
    async def synthetic(payload: dict, key: str = Header(alias="Idempotency-Key"),
                  account=Depends(adapter.get_teaching_account), session: Session=Depends(adapter.get_teaching_db)):
        command = intent(w, t, key=key, payload=payload, actor=account.username)
        return adapter.commit_write(session, command, command.scope, SyntheticOperation(t))
    return app, adapter


async def request(app, method, path, **kwargs):
    token = feature("app.core.security").create_access_token("owner", "teacher")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://isolated-asgi") as client:
        return await client.request(method, path, headers={"Authorization": "Bearer " + token, "Idempotency-Key": "original:123"}, **kwargs)


@sync_asgi
async def test_router_commits_before_success_and_never_uses_depends_as_session(writes_case, monkeypatch):
    db, w, t, m, _ = writes_case
    app, adapter = app_for(writes_case)
    original = db.commit
    commits = []
    def commit():
        commits.append("commit"); original()
    monkeypatch.setattr(db, "commit", commit)
    response = await request(app, "POST", "/api/synthetic-write", json={"title": "Accepted", "expected_revision": 1})
    assert response.status_code == 201 and response.json()["code"] == 201
    assert response.headers["cache-control"] == "no-store" and commits == ["commit"]
    assert counts(db, m) == (1, 1)
    data = response.json()["data"]
    recovery = await request(app, "GET", "/api/teaching/receipts/" + data["receipt"]["id"])
    assert recovery.status_code == 200 and recovery.json()["data"]["replayed"]
    assert recovery.json()["data"]["result"] == data["result"]
    assert "password_hash" not in recovery.text and "phone" not in recovery.text
    assert recovery.headers["cache-control"] == "no-store"
    by_key = await request(app, "GET", "/api/teaching/receipts?action=course_manage&scope_type=offering&scope_id=o1&key=original:123")
    assert by_key.status_code == 200 and by_key.json()["data"]["receipt"]["id"] == data["receipt"]["id"]


@sync_asgi
async def test_same_key_changed_payload_has_real_409_and_replay_200(writes_case):
    app, _ = app_for(writes_case)
    first = await request(app, "POST", "/api/synthetic-write", json={"title": "Accepted", "expected_revision": 1})
    replay = await request(app, "POST", "/api/synthetic-write", json={"title": "Accepted", "expected_revision": 1})
    conflict = await request(app, "POST", "/api/synthetic-write", json={"title": "Changed", "expected_revision": 2})
    assert first.status_code == 201 and replay.status_code == 200
    assert replay.json()["data"]["replayed"] and replay.json()["data"]["receipt"]["http_status"] == 201
    assert conflict.status_code == 409 and conflict.json() == {"code": 409, "message": "idempotency_conflict", "data": None}
    assert counts(writes_case[0], writes_case[3]) == (1, 1)


@sync_asgi
@pytest.mark.parametrize("committed", [False, True])
async def test_commit_failure_is_never_success_or_false_no_effect_promise(writes_case, monkeypatch, committed):
    db, _, _, m, _ = writes_case
    app, _ = app_for(writes_case)
    original = db.commit
    def fail_commit():
        if committed:
            original()
        raise OperationalError("synthetic commit", {}, RuntimeError("connection disappeared"))
    monkeypatch.setattr(db, "commit", fail_commit)
    response = await request(app, "POST", "/api/synthetic-write", json={"title": "Accepted", "expected_revision": 1})
    assert response.status_code == 503 and response.json()["message"] == "write_outcome_unknown"
    assert response.json()["data"] == {"recovery": {"action": "course_manage", "scope_type": "offering", "scope_id": "o1", "key": "original:123"}}
    assert counts(db, m) == ((1, 1) if committed else (0, 0))
    assert "connection disappeared" not in response.text


@sync_asgi
async def test_recovery_errors_are_uniform_and_strict(writes_case):
    app, _ = app_for(writes_case)
    missing = await request(app, "GET", "/api/teaching/receipts/missing")
    assert missing.status_code == 404 and missing.json() == {"code":404, "message":"not_found", "data":None}
    invalid = await request(app, "GET", "/api/teaching/receipts?action=bogus&scope_type=offering&scope_id=o1&key=original:123")
    assert invalid.status_code == 422
    extra = await request(app, "GET", "/api/teaching/receipts?action=course_manage&scope_type=offering&scope_id=o1&key=original:123&actor=co")
    assert extra.status_code == 422


def test_direct_dependency_requires_explicit_real_session(writes_case, monkeypatch):
    db = writes_case[0]
    adapter = feature("app.api.endpoints.teaching")
    seen = []
    monkeypatch.setattr(adapter, "resolve_current_account", lambda authorization, session: seen.append(session) or "resolved")
    assert adapter.get_teaching_account("Bearer synthetic", db) == "resolved"
    assert seen == [db]
    with pytest.raises(TypeError):
        adapter.get_teaching_account("Bearer synthetic")


@sync_asgi
async def test_default_off_recovery_by_key_preserves_feature_disabled(writes_case):
    db = writes_case[0]
    db.info.pop("teaching_policy_provider")
    app, _ = app_for(writes_case)
    response = await request(app, "GET", "/api/teaching/receipts?action=course_manage&scope_type=offering&scope_id=o1&key=original:123")
    assert response.status_code == 503
    assert response.json() == {"code":503, "message":"feature_disabled", "data":None}


@sync_asgi
async def test_database_unavailable_write_has_safe_original_recovery_tuple(writes_case, monkeypatch):
    from fastapi import HTTPException
    app, adapter = app_for(writes_case)
    def unavailable(*args, **kwargs):
        raise HTTPException(503, "database_unavailable")
    monkeypatch.setattr(adapter, "execute_write", unavailable)
    response = await request(app, "POST", "/api/synthetic-write", json={"title": "Private request text", "expected_revision": 1})
    assert response.status_code == 503
    assert response.json() == {"code": 503, "message": "database_unavailable", "data": {
        "recovery": {"action": "course_manage", "scope_type": "offering", "scope_id": "o1", "key": "original:123"}}}
    assert "Private request text" not in response.text
    assert counts(writes_case[0], writes_case[3]) == (0, 0)
