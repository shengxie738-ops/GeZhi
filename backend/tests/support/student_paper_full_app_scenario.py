"""Owned schema + actual startup/lifespan/auth/SQL; only HTTP transports synthetic."""
import asyncio
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import socket
import sys
import time
from urllib.parse import urlencode


ROOT = Path(os.environ["GEZHI_FULL_APP_EVIDENCE"]).resolve()
SCHEMA = os.environ["GEZHI_FULL_APP_SCHEMA"]
SOCKET = Path(os.environ["GEZHI_FULL_APP_SOCKET"]).resolve()
SERVER_UUID = os.environ["GEZHI_FULL_APP_SERVER_UUID"]
assert re.fullmatch(r"tw_native_[0-9a-f]{32}", SCHEMA)
assert SOCKET.name == "mysql.sock" and str(SOCKET).startswith("/tmp/gezhi-tw-native-")
assert Path.cwd() == ROOT / "blank-cwd"
os.environ.update(APP_SECRET_KEY="synthetic-student-paper-signing", ENVIRONMENT="test",
    DB_HOST="localhost", DB_USER="root", DB_PASS="",
    DB_NAME=SCHEMA + "?" + urlencode(dict(unix_socket=str(SOCKET), connect_timeout=2, read_timeout=5, write_timeout=5)),
    GIT_COACH_WORKER_ENABLED="false", GITEA_ENABLED="false",
    RAGFLOW_API_KEY="synthetic-unused", RAGFLOW_BASE_URL="http://synthetic.invalid",
    RAGFLOW_AGENT_ID="synthetic-unused", RAGFLOW_CHAT_ID="synthetic-unused",
    RAGFLOW_DATASET_ID="synthetic-unused", RAGFLOW_PUBLIC_DATASET_IDS="",
    OPENAI_API_KEY="synthetic-unused", OPENAI_API_BASE="http://synthetic.invalid/v1",
    AI_LESSON_PREP_API_KEY="synthetic-unused", COURSEWARE_FRONTEND_ROOT=str(ROOT / "sources"),
    TEACHER_WORK_STORAGE_ROOT=str(ROOT / "private-storage"))
GUARDS = dict(env_reads_denied=0, dns_denied=0, tcp_connections_denied=0, unix_connects=0)
def audit(event, args):
    if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)) and Path(os.fsdecode(args[0])).name.startswith(".env"):
        GUARDS["env_reads_denied"] += 1
        raise PermissionError("native student acceptance refuses .env reads")
    if event == "socket.getaddrinfo":
        GUARDS["dns_denied"] += 1
        raise PermissionError("native student acceptance refuses DNS")
    if event == "socket.connect":
        sock, address = args
        if sock.family != socket.AF_UNIX or os.fsdecode(address) != str(SOCKET):
            GUARDS["tcp_connections_denied"] += 1
            raise PermissionError("only the owned MySQL Unix socket is allowed")
        GUARDS["unix_connects"] += 1
sys.addaudithook(audit)

import httpx
import pytest
from sqlalchemy import delete, event, insert, select, text
from sqlalchemy.orm import Session

from app.main import app
from app.core import database
from app.core.crypto import encrypt_secret
from app.core.security import create_access_token, get_password_hash
from app.models.user_account import UserAccount
from app.models.user_custom_ai_model import UserCustomAIModel
from app.models.chat_message import ChatMessage
from app.services import student_paper_reading as paper
from app.services.teacher_work.schema_mysql import DatabaseIdentity
from tests.support.student_paper_transport import PaperTransport, CONTENT
from tests.support.student_paper_asgi import dispatch, response_text


ALICE, BOB, TEACHER = "paper-native-alice", "paper-native-bob", "paper-native-teacher"
PASSWORD = "synthetic-paper-password"
DOI = "10.9999/synthetic-paper"


class Scenario(PaperTransport):
    def __init__(self, name):
        super().__init__()
        self.name, self.tokens, self.checked = name, {}, set()
        self.sources, self.exchanges, self.observations = [], [], []
        self.patches = pytest.MonkeyPatch()
        self.facts = dict(scenario=name, completed=False, dependency_overrides=len(app.dependency_overrides),
            live_provider_verified=False, http_exchanges=self.exchanges, provider_calls=self.calls,
            academic_calls=self.sources, observations=self.observations)
        assert not app.dependency_overrides
        with database.engine.connect() as connection:
            identity = DatabaseIdentity(*connection.execute(text("SELECT DATABASE(), @@server_uuid, @@datadir, @@socket")).one())
            assert identity.schema_name == SCHEMA and identity.server_uuid == SERVER_UUID
            assert connection.scalar(text("SELECT @@skip_networking")) == 1
            self.facts["identity"] = vars(identity)
            self.facts["startup_tables"] = connection.execute(text("SHOW TABLES")).scalars().all()
        with database.engine.begin() as connection:
            connection.execute(insert(UserAccount).values([dict(username=name, role=role,
                password_hash=get_password_hash(PASSWORD)) for name, role in ((ALICE, "student"), (BOB, "student"), (TEACHER, "teacher"))]))
            connection.execute(insert(UserCustomAIModel).values([dict(id="model-" + owner, user_id=owner,
                base_url="http://synthetic.invalid/v1", encrypted_api_key=encrypt_secret("synthetic-key-" + owner),
                model_ids=["glm-5.1"], is_active=True) for owner in (ALICE, BOB)]))
        event.listen(database.engine, "checkout", self.checkout)
        event.listen(database.engine, "checkin", self.checkin)
        self.sql_checkouts = lambda: len(self.checked)
        self.install(self.patches)

    def checkout(self, _connection, record, *_): self.checked.add(id(record))
    def checkin(self, _connection, record): self.checked.discard(id(record))

    async def handle_async(self, request, *, http_module=httpx):
        if request.method == "GET":
            assert request.url.host == "api.crossref.org"
            self.sources.append(dict(url=str(request.url), synthetic=True))
            return http_module.Response(200, request=request, json=dict(message={"DOI": DOI,
                "title": ["Synthetic metadata paper"], "author": [{"given": "Synthetic", "family": "Author"}],
                "published": {"date-parts": [[2026]]}, "type": "journal-article", "abstract": "Synthetic supplied abstract"}))
        assert request.url.host == "synthetic.invalid", "unexpected model/profile/RAG request"
        assert self.sql_checkouts() == 0, "model await retains a real MySQL checkout"
        assert request.headers["authorization"] in {"Bearer synthetic-key-" + owner for owner in (ALICE, BOB)}
        assert "tools" not in json.loads(request.content)
        return await super().handle_async(request, http_module=http_module)

    def handle_sync(self, request, *, http_module=httpx):
        raise AssertionError("paper invoked synchronous graph/profile HTTP")

    async def call(self, method, path, *, owner=ALICE, body=None, token=None, auth=True, **kwargs):
        headers = {"Authorization": "Bearer " + (token if token is not None else self.tokens[owner])} if auth else {}
        response = await self.client.request(method, path, json=body, headers=headers, **kwargs)
        if path.endswith("/login"):
            public = response.json()
            if isinstance(public.get("data"), dict):
                public["data"].pop("token", None)
            record = dict(method=method, path=path, status=response.status_code,
                request={k: v for k, v in (body or {}).items() if k != "password"}, response=public,
                encoding="normalized login JSON; password/token omitted")
        else:
            record = dict(method=method, path=path, status=response.status_code, request=body,
                response_utf8=response.text, encoding="original response UTF-8; authorization omitted")
        self.exchanges.append(record)
        return response

    async def login(self):
        for owner, role in ((ALICE, "student"), (BOB, "student"), (TEACHER, "teacher")):
            response = await self.call("POST", "/api/" + role + "/login", owner=owner, auth=False,
                body=dict(username=owner, role=role, password=PASSWORD))
            assert response.status_code == 200 and response.json()["success"] is True
            self.tokens[owner] = response.json()["data"]["token"]

    def rows(self, task=None):
        with database.engine.connect() as connection:
            query = select(ChatMessage.__table__).order_by(ChatMessage.id)
            if task:
                query = query.where(ChatMessage.conversation_id == task)
            return [dict(row) for row in connection.execute(query).mappings()]

    def completion(self, response, path):
        assert response.status_code == 200, response.text
        if path == "/api/chat":
            return response.json()
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        assert all("沙箱" not in event.get("status", "") for event in events)
        return next(e for e in reversed(events) if e["type"] == "complete")

    async def dialog(self, path, task, **changes):
        before = len(self.calls)
        response = await self.call("POST", path, body=dict(message="Explain the supplied abstract", agent_mode="paper",
            agent_model="glm-5.1", conversation_id=task, sessionId=BOB, thread_id=BOB, **changes))
        result = self.completion(response, path)
        assert len(self.calls) - before <= 1
        return result

    async def lifecycle(self):
        searched = await self.call("GET", "/api/academic/crossref/search", params=dict(query="https://doi.org/" + DOI))
        assert searched.status_code == 200
        item = searched.json()["items"][0]
        assert item["DOI"] == DOI
        snapshot = dict(kind="paper_search", query=DOI, results=[dict(id="synthetic-paper", title=item["title"][0],
            doi=DOI, abstract=item["abstract"], authors=["Synthetic Author"], year=2026, officialUrl="https://doi.org/" + DOI)])
        body = dict(user_id=ALICE, agent_mode="paper", conversation_id="search-task", client_request_id="synthetic-search-request",
            messages=[dict(role="user", content=DOI), dict(role="assistant", content="Saved synthetic search", payload=snapshot)])
        saved = await self.call("POST", "/api/chat/history/batch", body=body)
        replay = await self.call("POST", "/api/chat/history/batch", body=body)
        assert saved.json()["data"] == replay.json()["data"] and len(self.rows("search-task")) == 2
        changed = {**body, "messages": [dict(role="user", content="different"), body["messages"][1]]}
        assert (await self.call("POST", "/api/chat/history/batch", body=changed)).status_code == 409
        for path in ("/api/chat", "/api/chat/stream"):
            result = await self.dialog(path, "search-task")
            assert result["history_saved"] and result["model_completion_status"] == "complete"
            assert all(row["user_id"] == ALICE for row in self.rows("search-task"))
            messages = self.calls[-1]["body"]["messages"]
            text = json.dumps(messages, ensure_ascii=False)
            assert "Synthetic metadata paper" in text and "Synthetic supplied abstract" in text
            assert "full_text_not_read" in text
        selected = await self.dialog("/api/chat/stream", "review-task", skill_ids=["academic-review"], agent_prompt="CLIENT OVERRIDE")
        assert selected["history_saved"]
        assert "academic-review" in self.calls[-1]["body"]["messages"][0]["content"]
        assert "CLIENT OVERRIDE" not in self.calls[-1]["body"]["messages"][0]["content"]
        read = await self.call("GET", "/api/chat/history", params=dict(session_id=ALICE, agent_mode="paper", conversation_id="search-task"))
        assert read.status_code == 200 and len(read.json()["data"]) == 6
        for owner in (BOB, TEACHER):
            foreign = await self.call("GET", "/api/chat/history", owner=owner, params=dict(session_id=ALICE, agent_mode="paper"))
            assert foreign.status_code == 403
            overwrite = await self.call("POST", "/api/chat/history/batch", owner=owner, body=body)
            assert overwrite.status_code == 403
        for token in ("synthetic-invalid", create_access_token(ALICE, "student", expires_in=-1), create_access_token("deleted-account", "student")):
            before = len(self.calls)
            invalid = await self.call("POST", "/api/chat", token=token,
                body=dict(message="Forbidden", agent_mode="paper"))
            assert invalid.status_code == 401 and len(self.calls) == before
        identifier = self.rows("search-task")[-1]["id"]
        assert (await self.call("DELETE", "/api/chat/history/" + str(identifier), params=dict(session_id=ALICE))).json()["status"] == "success"
        self.observations.append(dict(kind="lifecycle", rows=self.rows(), duplicate_search_receipt_confirmed=True))

    async def failures(self):
        paths = ("/api/chat", "/api/chat/stream")
        for path in paths:
            for reason in ("length", "content_filter", "tool_calls", None, "unknown"):
                self.reason = reason
                task = "failure-" + str(len(self.exchanges))
                result = await self.dialog(path, task)
                assert not result["history_saved"] and result["error"] == "incomplete_response"
                assert [r["role"] for r in self.rows(task)] == ["user"]
            self.reason, self.content = "stop", ""
            assert (await self.dialog(path, "empty-" + str(len(self.exchanges))))["error"] == "empty_response"
            self.content, self.status = CONTENT, 500
            assert (await self.dialog(path, "upstream-" + str(len(self.exchanges))))["error"] == "model_error"
            self.status = 200
            self.tool_calls = [dict(id="synthetic-tool", type="function", function=dict(name="execute_python_code", arguments='{"code":"print(1)"}'))]
            result = await self.dialog(path, "unsolicited-tool-" + str(len(self.exchanges)))
            assert not result["history_saved"] and result["error"] == "incomplete_response"
            self.tool_calls[0]["function"]["arguments"] = "not valid json"
            result = await self.dialog(path, "invalid-tool-" + str(len(self.exchanges)))
            assert not result["history_saved"] and result["error"] == "incomplete_response"
            self.tool_calls = None
            self.function_call = dict(name="execute_python_code", arguments='{"code":"print(1)"}')
            result = await self.dialog(path, "legacy-tool-" + str(len(self.exchanges)))
            assert not result["history_saved"] and result["error"] == "incomplete_response"
            self.function_call = None
            for field, value in (("force_rag", True), ("repository_id", "repo"), ("course_dataset_ids", ["course"]),
                    ("is_diagnosis", True), ("problem_id", "problem"), ("problem_title", "title"), ("user_code", "code")):
                before, count = len(self.calls), len(self.rows())
                response = await self.call("POST", path, body=dict(message="Conflict", agent_mode="paper", **{field: value}))
                assert response.status_code == 422 and len(self.calls) == before and len(self.rows()) == count
        with database.engine.begin() as connection:
            connection.execute(UserCustomAIModel.__table__.update().where(UserCustomAIModel.user_id == ALICE).values(encrypted_api_key="synthetic-broken-ciphertext"))
        for path in paths:
            before = len(self.calls)
            result = await self.dialog(path, "credentials-" + str(len(self.exchanges)))
            assert not result["history_saved"] and len(self.calls) == before
        self.observations.append(dict(kind="failures", rows=self.rows()))

    async def lifetime(self):
        for path in ("/api/chat", "/api/chat/stream"):
            async def clear(_request):
                result = await self.call("DELETE", "/api/chat/history", params=dict(session_id=ALICE, agent_mode="paper"))
                assert result.json()["status"] == "success"
            self.on_request = clear
            result = await self.dialog(path, "cleared-" + str(len(self.exchanges)))
            assert not result["history_saved"] and result["history_invalidated"]
            self.on_request = None
            paper.PAPER_REQUEST_TIMEOUT_SECONDS, self.delay = .15, .35
            result = await self.dialog(path, "timeout-" + str(len(self.exchanges)), timeout=100000, _paper_deadline=1e30)
            assert not result["history_saved"] and result["error"] == "timeout"
            self.delay = 0
            paper.PAPER_REQUEST_TIMEOUT_SECONDS = 90
            async def revise(_request):
                with database.engine.begin() as connection:
                    connection.execute(ChatMessage.__table__.update().where(ChatMessage.conversation_id == task).values(payload={"_request_token": "synthetic-replaced-revision"}))
            task = "revised-" + str(len(self.exchanges))
            self.on_request = revise
            result = await self.dialog(path, task)
            assert not result["history_saved"] and result["history_invalidated"]
            assert [r["role"] for r in self.rows(task)] == ["user"]
            async def delete_origin(_request):
                origin = self.rows(task)[-1]
                result = await self.call("DELETE", "/api/chat/history/" + str(origin["id"]), params=dict(session_id=ALICE))
                assert result.json()["status"] == "success"
            task = "deleted-" + str(len(self.exchanges))
            self.on_request = delete_origin
            result = await self.dialog(path, task)
            assert not result["history_saved"] and result["history_invalidated"] and self.rows(task) == []
            self.on_request = None
            self.release, self.entered = asyncio.Event(), asyncio.Event()
            task = "disconnect-" + str(len(self.exchanges))
            disconnect = asyncio.Event()
            operation = asyncio.create_task(dispatch(app, path, dict(message="Cancel synthetic paper", agent_mode="paper", agent_model="glm-5.1", conversation_id=task), self.tokens[ALICE], disconnect=disconnect))
            await asyncio.wait_for(self.entered.wait(), 1)
            assert not self.checked
            disconnect.set()
            output = await asyncio.wait_for(operation, 1)
            assert [r["role"] for r in self.rows(task)] == ["user"]
            assert '"history_saved": true' not in response_text(output)
            self.observations.append(dict(kind="disconnect", path=path, task=task, asgi_messages=output, rows=self.rows(task)))
            self.release = None
            paper.PAPER_REQUEST_TIMEOUT_SECONDS = .08
            delayed = {"done": False}
            def sql_delay(_conn, _cursor, statement, *_):
                if not delayed["done"] and statement.lstrip().upper().startswith("SELECT") and "chat_messages" in statement and "ORDER BY" in statement:
                    delayed["done"] = True
                    time.sleep(.12)
            event.listen(database.engine, "before_cursor_execute", sql_delay)
            try:
                before = len(self.calls)
                result = await self.dialog(path, "slow-context-" + str(len(self.exchanges)))
                assert delayed["done"] and result["error"] == "timeout" and not result["history_saved"] and len(self.calls) == before
                self.observations.append(dict(kind="synchronous_context_delay", path=path, no_provider_started=True, result=result))
            finally:
                event.remove(database.engine, "before_cursor_execute", sql_delay)
            before = len(self.calls)
            delayed = {"done": False}
            def fence_delay(_conn, _cursor, statement, *_):
                if not delayed["done"] and len(self.calls) > before and statement.lstrip().upper().startswith("SELECT") and "chat_messages" in statement:
                    delayed["done"] = True
                    time.sleep(.12)
            event.listen(database.engine, "before_cursor_execute", fence_delay)
            try:
                task = "expired-fence-" + str(len(self.exchanges))
                result = await self.dialog(path, task)
                assert delayed["done"] and result["error"] == "timeout" and not result["history_saved"]
                assert [r["role"] for r in self.rows(task)] == ["user"]
                self.observations.append(dict(kind="expired_locked_save_read", path=path, rows=self.rows(task), result=result))
            finally:
                event.remove(database.engine, "before_cursor_execute", fence_delay)
            paper.PAPER_REQUEST_TIMEOUT_SECONDS = .1
            def commit_delay(session):
                if any(isinstance(r, ChatMessage) and r.role == "assistant" for r in session.new): time.sleep(.15)
            event.listen(Session, "before_commit", commit_delay)
            try:
                task = "slow-commit-" + str(len(self.exchanges))
                result = await self.dialog(path, task)
                assert not result["history_saved"] and result["history_confirmation_status"] == "unknown" and result["error"] == "timeout"
                assert [r["role"] for r in self.rows(task)] == ["user", "assistant"]
                self.observations.append(dict(kind="synchronous_commit_delay", path=path, rows=self.rows(task), result=result))
            finally:
                event.remove(Session, "before_commit", commit_delay)
                paper.PAPER_REQUEST_TIMEOUT_SECONDS = 90
        paper.PAPER_REQUEST_TIMEOUT_SECONDS = .05
        async def slow_header(message):
            if message["type"] == "http.response.start": await asyncio.sleep(.2)
        before, attempts = len(self.rows()), len(self.calls)
        output = await asyncio.wait_for(dispatch(app, "/api/chat/stream", dict(message="Blocked header", agent_mode="paper", agent_model="glm-5.1", conversation_id="headers-task"), self.tokens[ALICE], send_hook=slow_header), .5)
        assert len(self.rows()) == before and len(self.calls) == attempts and not self.checked
        self.observations.append(dict(kind="header_deadline", asgi_messages=output, provider_attempts=0, writes=0))
        paper.PAPER_REQUEST_TIMEOUT_SECONDS = 90
        from app.services.chat_context import _task_locks
        for reason in ("timeout", "disconnect"):
            paper.PAPER_REQUEST_TIMEOUT_SECONDS = .2 if reason == "timeout" else 90
            disconnect, token_started, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
            async def blocked_token(message):
                if message["type"] == "http.response.body" and b'"type": "token"' in message.get("body", b""):
                    token_started.set()
                    await release.wait()
            task = "blocked-token-" + reason
            operation = asyncio.create_task(dispatch(app, "/api/chat/stream", dict(message="Synthetic blocked token", agent_mode="paper", agent_model="glm-5.1", conversation_id=task), self.tokens[ALICE], disconnect=disconnect, send_hook=blocked_token))
            try:
                await asyncio.wait_for(token_started.wait(), 1)
                lock = _task_locks[(ALICE, "paper", task)]
                assert lock.locked() and not self.checked
                if reason == "disconnect": disconnect.set()
                output = await asyncio.wait_for(operation, 1)
                assert not lock.locked() and [r["role"] for r in self.rows(task)] == ["user"]
                self.observations.append(dict(kind="blocked_token_send", reason=reason, task_lock_released=True, asgi_messages=output, rows=self.rows(task)))
            finally:
                operation.cancel()
                await asyncio.gather(operation, return_exceptions=True)
                paper.PAPER_REQUEST_TIMEOUT_SECONDS = 90
        paper.PAPER_REQUEST_TIMEOUT_SECONDS = .5
        self.release = asyncio.Event()
        self.entered = asyncio.Event()
        first = asyncio.create_task(self.dialog("/api/chat", "queue-task"))
        await asyncio.wait_for(self.entered.wait(), 1)
        paper.PAPER_REQUEST_TIMEOUT_SECONDS = .12
        second = asyncio.create_task(self.dialog("/api/chat", "queue-task"))
        await asyncio.sleep(.03)
        assert not self.checked, "queued identity read retains MySQL checkout"
        values = await asyncio.gather(first, second)
        assert all(v["error"] == "timeout" for v in values)
        assert [r["role"] for r in self.rows("queue-task")] == ["user"]
        self.release = None
        paper.PAPER_REQUEST_TIMEOUT_SECONDS = 90
        self.observations.append(dict(kind="lifetime", rows=self.rows(), queued_checkout_count=0))

    async def ack(self):
        for path in ("/api/chat", "/api/chat/stream"):
            for role in ("user", "assistant"):
                for point in ("before", "after"):
                    task = "ack-" + str(len(self.exchanges))
                    armed = {"done": False}
                    def before(session):
                        if not armed["done"] and any(isinstance(r, ChatMessage) and r.role == role for r in session.new):
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
                        result = await self.dialog(path, task)
                        assert not result["history_saved"] and result["history_confirmation_status"] == "unknown"
                        expected = [] if (role, point) == ("user", "before") else ["user"]
                        if (role, point) == ("assistant", "after"):
                            expected += ["assistant"]
                        actual = self.rows(task)
                        assert [r["role"] for r in actual] == expected
                        self.observations.append(dict(kind="commit_ack", role=role, point=point, rows=actual))
                    finally:
                        event.remove(Session, "before_commit", before)
                        event.remove(Session, "after_commit", after)

    async def run(self):
        try:
            async with app.router.lifespan_context(app):
                assert app.state.git_coach_worker is None
                self.facts["real_lifespan_entered"] = True
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://synthetic.local") as self.client:
                    await self.login()
                    await getattr(self, self.name)()
            assert not self.checked
            assert GUARDS["env_reads_denied"] == GUARDS["dns_denied"] == GUARDS["tcp_connections_denied"] == 0
            self.facts["pool_checkouts_at_model_request"] = [c["sql_checkouts"] for c in self.calls]
            self.facts["real_lifespan_exited"] = True
            self.facts["completed"] = True
        finally:
            self.patches.undo()
            event.remove(database.engine, "checkout", self.checkout)
            event.remove(database.engine, "checkin", self.checkin)
            database.engine.dispose()
            storage = ROOT / "private-storage"
            if storage.exists(): shutil.rmtree(storage)
            self.facts["private_storage_removed"] = not storage.exists()
            self.facts["guards"] = dict(GUARDS)
            (ROOT / "scenario.json").write_text(json.dumps(self.facts, ensure_ascii=False, indent=2, default=str) + "\n")


asyncio.run(Scenario(sys.argv[1]).run())
