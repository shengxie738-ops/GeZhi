"""Actual paper router/auth/SQLite and provider HTTP protocol regressions.

No app.main startup; native full-app/MySQL acceptance has a separate selector.
Only the upstream HTTP transport is synthetic. No permission/model/save mock.
"""
import asyncio
import json
import time

from fastapi import FastAPI
import httpx
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.endpoints import chat
from app.core.crypto import encrypt_secret
from app.core.database import get_db
from app.core.security import create_access_token
from app.models.chat_message import ChatMessage
from app.models.user_account import UserAccount
from app.models.user_custom_ai_model import UserCustomAIModel
from tests.support.student_paper_transport import PaperTransport, CONTENT
from tests.support.student_paper_asgi import dispatch, response_text


PATHS = ("/api/chat", "/api/chat/stream")


@pytest.fixture
def harness(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for table in (UserAccount.__table__, ChatMessage.__table__, UserCustomAIModel.__table__):
        table.create(engine)
    with Session(engine) as db:
        db.add_all([UserAccount(username=name, role="student", password_hash="synthetic-unused")
                    for name in ("alice", "bob")])
        db.add(UserCustomAIModel(user_id="alice", base_url="http://synthetic.invalid/v1",
            encrypted_api_key=encrypt_secret("synthetic-model-key"), model_ids=["glm-5.1"]))
        db.commit()
    app = FastAPI()
    app.include_router(chat.router, prefix="/api")
    def owned_db():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_db] = owned_db
    transport = PaperTransport()
    checked = set()
    def checkout(_connection, record, *_): checked.add(id(record))
    def checkin(_connection, record): checked.discard(id(record))
    event.listen(engine, "checkout", checkout)
    event.listen(engine, "checkin", checkin)
    transport.sql_checkouts = lambda: len(checked)
    transport.install(monkeypatch)
    data = dict(app=app, engine=engine, provider=transport,
                headers={"Authorization": "Bearer " + create_access_token("alice", "teacher")},
                checkouts=lambda: len(checked))
    yield data
    assert not checked
    engine.dispose()


def payload(**changes):
    return {"message": "Explain the supplied abstract", "agent_mode": "paper", "agent_model": "glm-5.1",
            "sessionId": "bob", "thread_id": "bob", "conversation_id": "paper-task", **changes}


async def request(harness, path, **changes):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=harness["app"], raise_app_exceptions=False),
                                 base_url="http://in-process.invalid") as client:
        response = await client.post(path, headers=harness["headers"], json=payload(**changes))
        await asyncio.sleep(0)
        return response


def completion(response, path):
    if path == "/api/chat":
        return response.json()
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    return next(event for event in reversed(events) if event["type"] == "complete")


def rows(harness):
    with Session(harness["engine"]) as db:
        return [dict(id=r.id, user=r.user_id, role=r.role, content=r.content)
                for r in db.query(ChatMessage).order_by(ChatMessage.id)]


@pytest.mark.parametrize("path", PATHS)
def test_paper_stop_uses_one_tool_free_provider_and_owned_durable_pair(harness, path):
    response = asyncio.run(request(harness, path))
    assert response.status_code == 200
    result = completion(response, path)
    assert result["history_saved"] is True
    assert [r["role"] for r in rows(harness)] == ["user", "assistant"]
    assert all(r["user"] == "alice" for r in rows(harness))
    assert result.get("content", result.get("reply")) == CONTENT
    assert len(harness["provider"].calls) == 1
    assert "tools" not in harness["provider"].calls[0]["body"]
    assert harness["provider"].calls[0]["sql_checkouts"] == 0
    assert "沙箱" not in response.text


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("reason", ["length", "content_filter", "tool_calls", None, "unknown"])
def test_paper_non_stop_never_saves_partial_assistant(harness, path, reason):
    harness["provider"].reason = reason
    response = asyncio.run(request(harness, path))
    result = completion(response, path)
    assert result["history_saved"] is False
    assert result["delivery_status"] == "failed"
    assert result["history_receipt"]["assistant_message_id"] is None
    assert [r["role"] for r in rows(harness)] == ["user"]
    assert len(harness["provider"].calls) == 1


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("changes", [{"force_rag": True}, {"repository_id": "repo"},
    {"course_dataset_ids": ["course"]}, {"is_diagnosis": True}, {"problem_id": "problem"},
    {"problem_title": "title"}, {"user_code": "print(1)"}])
def test_paper_conflicts_rejected_before_any_write_or_provider(harness, path, changes):
    response = asyncio.run(request(harness, path, **changes))
    assert response.status_code == 422
    assert rows(harness) == []
    assert harness["provider"].calls == []


@pytest.mark.parametrize("path", PATHS)
def test_paper_accepts_empty_defaults(harness, path):
    response = asyncio.run(request(harness, path, force_rag=False, repository_id="",
        course_dataset_ids=[], is_diagnosis=None, problem_id=None, problem_title="", user_code=""))
    assert response.status_code == 200
    assert completion(response, path)["history_saved"] is True


@pytest.mark.parametrize("path", PATHS)
def test_paper_empty_stop_is_unsaved(harness, path):
    harness["provider"].content = ""
    result = completion(asyncio.run(request(harness, path)), path)
    assert result["history_saved"] is False
    assert result["error"] == "empty_response"
    assert [r["role"] for r in rows(harness)] == ["user"]


@pytest.mark.parametrize("path", PATHS)
def test_paper_http_500_is_one_actual_sdk_attempt_without_private_error(harness, path):
    harness["provider"].status = 500
    response = asyncio.run(request(harness, path))
    result = completion(response, path)
    assert result["history_saved"] is False
    assert result["error"] == "model_error"
    assert "SYNTHETIC PRIVATE UPSTREAM DETAIL" not in response.text
    assert len(harness["provider"].calls) == 1
    assert [r["role"] for r in rows(harness)] == ["user"]


@pytest.mark.parametrize("path", PATHS)
def test_paper_server_deadline_cancels_slow_transport_without_partial_save(harness, monkeypatch, path):
    from app.services import student_paper_reading as paper
    monkeypatch.setattr(paper, "PAPER_REQUEST_TIMEOUT_SECONDS", .08)
    harness["provider"].delay = .2
    result = completion(asyncio.run(request(harness, path, timeout=100000, _paper_deadline=1e30)), path)
    assert result["error"] == "timeout"
    assert result["history_saved"] is False
    assert [r["role"] for r in rows(harness)] == ["user"]
    assert len(harness["provider"].calls) == 1
    assert all(value <= .08 for value in harness["provider"].calls[0]["timeout"].values())


@pytest.mark.asyncio
async def test_paper_queued_request_releases_auth_connection_and_consumes_original_deadline(harness, monkeypatch):
    from app.services import student_paper_reading as paper
    monkeypatch.setattr(paper, "PAPER_REQUEST_TIMEOUT_SECONDS", .5)
    harness["provider"].release = asyncio.Event()
    first = asyncio.create_task(request(harness, "/api/chat"))
    await asyncio.wait_for(harness["provider"].entered.wait(), .5)
    monkeypatch.setattr(paper, "PAPER_REQUEST_TIMEOUT_SECONDS", .12)
    second = asyncio.create_task(request(harness, "/api/chat"))
    try:
        await asyncio.sleep(.03)
        assert harness["checkouts"]() == 0
        replies = await asyncio.gather(first, second)
        assert all(response.json()["error"] == "timeout" for response in replies)
        assert len(harness["provider"].calls) == 1
        assert [r["role"] for r in rows(harness)] == ["user"]
    finally:
        first.cancel(); second.cancel()
        await asyncio.gather(first, second, return_exceptions=True)


@pytest.mark.parametrize("path", PATHS)
def test_paper_clear_during_actual_provider_await_keeps_sql_fence(harness, path):
    async def clear(_request):
        assert harness["checkouts"]() == 0
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=harness["app"]),
                base_url="http://in-process.invalid") as client:
            response = await client.delete("/api/chat/history", params={"session_id": "alice", "agent_mode": "paper"},
                headers=harness["headers"])
            assert response.status_code == 200
    harness["provider"].on_request = clear
    result = completion(asyncio.run(request(harness, path)), path)
    assert result["history_saved"] is False
    assert result["history_invalidated"] is True
    assert rows(harness) == []


@pytest.mark.parametrize("path", PATHS)
def test_paper_changed_origin_token_cannot_save_stale_revision(harness, path):
    async def revise(_request):
        with Session(harness["engine"]) as db:
            origin = db.query(ChatMessage).one()
            origin.payload = {"_request_token": "synthetic-replaced-revision"}
            db.commit()
    harness["provider"].on_request = revise
    result = completion(asyncio.run(request(harness, path)), path)
    assert result["history_saved"] is False
    assert result["history_invalidated"] is True
    assert [r["role"] for r in rows(harness)] == ["user"]


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("role", ["user", "assistant"])
@pytest.mark.parametrize("point", ["before", "after"])
def test_paper_uncertain_commit_ack_never_claims_saved_success(harness, path, role, point):
    armed = {"done": False}
    def before(session):
        if not armed["done"] and any(isinstance(row, ChatMessage) and row.role == role for row in session.new):
            session.info["synthetic-paper-ack"] = True
            if point == "before":
                armed["done"] = True
                raise RuntimeError("SYNTHETIC PRIVATE COMMIT ACK")
    def after(session):
        if session.info.pop("synthetic-paper-ack", False) and point == "after":
            armed["done"] = True
            raise RuntimeError("SYNTHETIC PRIVATE COMMIT ACK")
    event.listen(Session, "before_commit", before)
    event.listen(Session, "after_commit", after)
    try:
        response = asyncio.run(request(harness, path))
        assert response.status_code == 200
        result = completion(response, path)
        assert result["history_saved"] is False
        assert result["history_confirmation_status"] == "unknown"
        assert "SYNTHETIC PRIVATE COMMIT ACK" not in response.text
        expected = [] if (role, point) == ("user", "before") else ["user"]
        if (role, point) == ("assistant", "after"):
            expected += ["assistant"]
        assert [r["role"] for r in rows(harness)] == expected
        assert len(harness["provider"].calls) == (1 if role == "assistant" else 0)
    finally:
        event.remove(Session, "before_commit", before)
        event.remove(Session, "after_commit", after)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", PATHS)
async def test_paper_actual_asgi_disconnect_cancels_provider_without_save(harness, path):
    disconnect = asyncio.Event()
    harness["provider"].release = asyncio.Event()
    token = harness["headers"]["Authorization"].split(" ", 1)[1]
    task = asyncio.create_task(dispatch(harness["app"], path, payload(), token, disconnect=disconnect))
    await asyncio.wait_for(harness["provider"].entered.wait(), 1)
    assert harness["checkouts"]() == 0
    disconnect.set()
    output = await asyncio.wait_for(task, 1)
    assert [r["role"] for r in rows(harness)] == ["user"]
    assert len(harness["provider"].calls) == 1
    assert '"history_saved": true' not in response_text(output)


@pytest.mark.asyncio
async def test_paper_blocked_stream_headers_consume_deadline_before_provider_or_write(harness, monkeypatch):
    from app.services import student_paper_reading as paper
    monkeypatch.setattr(paper, "PAPER_REQUEST_TIMEOUT_SECONDS", .05)
    async def delay(message):
        if message["type"] == "http.response.start": await asyncio.sleep(.2)
    token = harness["headers"]["Authorization"].split(" ", 1)[1]
    await asyncio.wait_for(dispatch(harness["app"], "/api/chat/stream", payload(), token, send_hook=delay), .5)
    assert rows(harness) == [] and harness["provider"].calls == []


@pytest.mark.parametrize("path", PATHS)
def test_paper_synchronous_context_delay_does_not_start_provider_after_deadline(harness, monkeypatch, path):
    from app.services import student_paper_reading as paper
    monkeypatch.setattr(paper, "PAPER_REQUEST_TIMEOUT_SECONDS", .04)
    delayed = {"done": False}
    def sql_delay(_conn, _cursor, statement, *_):
        if not delayed["done"] and statement.lstrip().upper().startswith("SELECT") and "chat_messages" in statement and "ORDER BY" in statement:
            delayed["done"] = True
            time.sleep(.08)  # Actual SQL executes; synchronous latency cannot be cancelled.
    event.listen(harness["engine"], "before_cursor_execute", sql_delay)
    try:
        response = asyncio.run(request(harness, path))
        result = completion(response, path)
        assert delayed["done"] and result["error"] == "timeout" and not result["history_saved"]
        assert [r["role"] for r in rows(harness)] == ["user"] and harness["provider"].calls == []
    finally:
        event.remove(harness["engine"], "before_cursor_execute", sql_delay)


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("arguments", ['{"code":"print(1)"}', 'not valid json'])
def test_paper_unsolicited_http_tool_call_even_with_stop_is_unsaved(harness, path, arguments):
    harness["provider"].tool_calls = [dict(id="synthetic-tool", type="function", function=dict(name="execute_python_code", arguments=arguments))]
    response = asyncio.run(request(harness, path))
    result = completion(response, path)
    assert not result["history_saved"] and result["error"] == "incomplete_response"
    assert [r["role"] for r in rows(harness)] == ["user"] and len(harness["provider"].calls) == 1


@pytest.mark.parametrize("path", PATHS)
def test_paper_slow_real_assistant_commit_reports_unknown_without_success(harness, monkeypatch, path):
    from app.services import student_paper_reading as paper
    monkeypatch.setattr(paper, "PAPER_REQUEST_TIMEOUT_SECONDS", .08)
    def delay(session):
        if any(isinstance(row, ChatMessage) and row.role == "assistant" for row in session.new):
            time.sleep(.12)
    event.listen(Session, "before_commit", delay)
    try:
        response = asyncio.run(request(harness, path))
        result = completion(response, path)
        assert result["error"] == "timeout" and not result["history_saved"]
        assert result["history_confirmation_status"] == "unknown"
        assert [r["role"] for r in rows(harness)] == ["user", "assistant"]
        assert len(harness["provider"].calls) == 1
    finally:
        event.remove(Session, "before_commit", delay)


@pytest.mark.parametrize("path", PATHS)
def test_paper_legacy_http_function_call_even_with_stop_is_unsaved(harness, path):
    harness["provider"].function_call = dict(name="execute_python_code", arguments='{"code":"print(1)"}')
    result = completion(asyncio.run(request(harness, path)), path)
    assert not result["history_saved"] and result["error"] == "incomplete_response"
    assert [r["role"] for r in rows(harness)] == ["user"] and len(harness["provider"].calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["timeout", "disconnect"])
async def test_paper_blocked_token_send_closes_context_and_task_lock_in_owner_task(harness, monkeypatch, reason):
    from app.services import student_paper_reading as paper
    from app.services.chat_context import _task_locks
    monkeypatch.setattr(paper, "PAPER_REQUEST_TIMEOUT_SECONDS", .1 if reason == "timeout" else 90)
    disconnect, token_started, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def send_hook(message):
        if message["type"] == "http.response.body" and b'"type": "token"' in message.get("body", b""):
            token_started.set()
            await release.wait()
    token = harness["headers"]["Authorization"].split(" ", 1)[1]
    operation = asyncio.create_task(dispatch(harness["app"], "/api/chat/stream", payload(), token,
        disconnect=disconnect, send_hook=send_hook))
    try:
        await asyncio.wait_for(token_started.wait(), .5)
        lock = _task_locks[("alice", "paper", "paper-task")]
        assert lock.locked() and harness["checkouts"]() == 0
        if reason == "disconnect": disconnect.set()
        output = await asyncio.wait_for(operation, .5)
        assert not lock.locked()
        assert [r["role"] for r in rows(harness)] == ["user"]
        assert len(harness["provider"].calls) == 1 and '"history_saved": true' not in response_text(output)
    finally:
        operation.cancel()
        await asyncio.gather(operation, return_exceptions=True)


@pytest.mark.parametrize("path", PATHS)
def test_paper_expired_locked_save_fence_read_never_begins_assistant_write(harness, monkeypatch, caplog, path):
    from app.services import student_paper_reading as paper
    monkeypatch.setattr(paper, "PAPER_REQUEST_TIMEOUT_SECONDS", .08)
    delayed = {"done": False}
    def delay(_conn, _cursor, statement, *_):
        if not delayed["done"] and harness["provider"].calls and statement.lstrip().upper().startswith("SELECT") and "chat_messages" in statement:
            delayed["done"] = True
            time.sleep(.12)
    event.listen(harness["engine"], "before_cursor_execute", delay)
    try:
        result = completion(asyncio.run(request(harness, path)), path)
        assert delayed["done"] and result["error"] == "timeout" and not result["history_saved"]
        assert [r["role"] for r in rows(harness)] == ["user"] and len(harness["provider"].calls) == 1
        assert "Task exception was never retrieved" not in caplog.text
    finally:
        event.remove(harness["engine"], "before_cursor_execute", delay)
