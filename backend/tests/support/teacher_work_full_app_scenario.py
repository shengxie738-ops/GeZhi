"""Fresh-process app.main scenarios, invoked only by the owned native controller."""
import asyncio
from copy import deepcopy
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import re
import shutil
import socket
import sys
from urllib.parse import urlencode
import zipfile


OWNER, OTHER, STUDENT = "full-app-teacher", "full-app-other", "full-app-student"
PASSWORD = "synthetic-password-only"
ROOT = Path(os.environ["GEZHI_FULL_APP_EVIDENCE"]).resolve()
SCHEMA = os.environ["GEZHI_FULL_APP_SCHEMA"]
SOCKET = Path(os.environ["GEZHI_FULL_APP_SOCKET"]).resolve()
SERVER_UUID = os.environ["GEZHI_FULL_APP_SERVER_UUID"]
assert re.fullmatch(r"tw_native_[0-9a-f]{32}", SCHEMA)
assert SOCKET.name == "mysql.sock" and str(SOCKET).startswith("/tmp/gezhi-tw-native-")
assert Path.cwd().name == "blank-cwd" and Path.cwd().parent == ROOT

# Keep the real Settings, create_engine, SessionLocal, get_db and startup intact.
# The existing DSN property passes the query suffix to SQLAlchemy/PyMySQL.
os.environ.update({
    "APP_SECRET_KEY": "synthetic-full-app-signing-only", "ENVIRONMENT": "test",
    "DB_HOST": "localhost", "DB_USER": "root", "DB_PASS": "",
    "DB_NAME": SCHEMA + "?" + urlencode({"unix_socket": str(SOCKET),
        "connect_timeout": 2, "read_timeout": 5, "write_timeout": 5}),
    "GIT_COACH_WORKER_ENABLED": "false", "GITEA_ENABLED": "false",
    "RAGFLOW_API_KEY": "synthetic-unused", "RAGFLOW_BASE_URL": "http://synthetic.invalid",
    "RAGFLOW_AGENT_ID": "synthetic-unused", "RAGFLOW_CHAT_ID": "synthetic-unused",
    "RAGFLOW_DATASET_ID": "synthetic-unused", "RAGFLOW_PUBLIC_DATASET_IDS": "",
    "OPENAI_API_KEY": "synthetic-unused", "OPENAI_API_BASE": "http://synthetic.invalid/v1",
    "AI_LESSON_PREP_API_KEY": "synthetic-provider-only",
    "AI_LESSON_PREP_BASE_URL": "http://synthetic.invalid/chat/completions",
    "AI_LESSON_PREP_MODEL": "synthetic-model", "AI_LESSON_PREP_TIMEOUT_SECONDS": "5",
    "AI_LESSON_PREP_MAX_OUTPUT_TOKENS": "8192",
    "TEACHER_WORK_PRIVATE_TASKS_ENABLED": "true", "TEACHER_WORK_PRIVATE_CHAT_ENABLED": "true",
    "TEACHER_WORK_PRIVATE_MATERIALS_ENABLED": "true",
    "TEACHER_WORK_PRIVATE_MATERIAL_PROPOSALS_ENABLED": "true",
    "TEACHER_WORK_PRIVATE_EXPORTS_ENABLED": "true",
    "TEACHER_WORK_STORAGE_ROOT": str(ROOT / "private-storage"),
    "COURSEWARE_FRONTEND_ROOT": str(ROOT / "sources"),
})

GUARDS = {"env_reads_denied": 0, "tcp_connections_denied": 0, "unix_connects": 0}


def isolation_audit(event, args):
    if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
        if Path(os.fsdecode(args[0])).name.startswith(".env"):
            GUARDS["env_reads_denied"] += 1
            raise PermissionError("acceptance refuses all .env reads")
    if event == "socket.connect":
        sock, address = args
        if sock.family != socket.AF_UNIX or os.fsdecode(address) != str(SOCKET):
            GUARDS["tcp_connections_denied"] += 1
            raise PermissionError("acceptance permits only the owned MySQL Unix socket")
        GUARDS["unix_connects"] += 1


sys.addaudithook(isolation_audit)

import httpx
from sqlalchemy import event, insert, select, text, update, delete

# This is the real complete application import, including its real init_db().
from app.main import app
from app.core import database
from app.core.config import settings
from app.core.security import create_access_token, get_password_hash
from app.models.user_account import UserAccount
from app.models.teacher_work import WorkTask, WorkMessage, WorkRun, OutlineSnapshot, OutlineApproval
from app.models.teacher_work_proposals import MaterialProposalRecord
from app.services.teacher_work import private_chat, private_proposals
from app.services.teacher_work.ai import LessonPrepWorkAI
from app.services.teacher_lesson_prep.ai_client import LessonPrepAIClient
from app.services.teacher_lesson_prep.courseware_catalog import CoursewareCatalog, DEFAULT_COURSE_DIRECTORIES
from app.services.teacher_work.proposals import PROPOSAL_SYSTEM_PROMPT_V1
from app.services.teacher_work.schema import TEACHER_WORK_CONTRACT_HASH
from app.services.teacher_work.schema_mysql import DatabaseIdentity
from app.services.teacher_work.schema_mysql_v3 import observe_teacher_work_mysql_v3
from app.services.teacher_work.proposal_schema import observe_teacher_work_proposals_mysql
from app.services.teacher_work.exporters.validation import validate_office_bytes
from app.schemas.teacher_work import PackageVersionDTO
from migrations.v20261005_teacher_work_mysql import apply_teacher_work_mysql
from migrations.v20261006_teacher_work_exports_mysql import apply_teacher_work_exports_mysql
from migrations.v20261006_teacher_work_proposals_mysql import apply_teacher_work_proposals_mysql
from tests.test_teacher_work_private_materials import lesson, slides


class Scenario:
    def __init__(self, name):
        self.name = name
        self.tokens, self.exchanges, self.observations, self.provider_calls = {}, [], [], []
        self.checked = set()
        self.facts = {"scenario": name, "completed": False, "external_provider_verified": False,
                      "dependency_overrides": len(app.dependency_overrides),
                      "http_exchanges": self.exchanges, "observations": self.observations,
                      "provider_calls": self.provider_calls}
        assert not app.dependency_overrides
        assert database.SessionLocal.kw["bind"] is database.engine
        with database.engine.connect() as connection:
            identity = DatabaseIdentity(*connection.execute(text(
                "SELECT DATABASE(), @@server_uuid, @@datadir, @@socket")).one())
            assert identity.schema_name == SCHEMA and identity.server_uuid == SERVER_UUID
            self.facts["identity"] = vars(identity)
            self.facts["startup_tables"] = connection.execute(text("SHOW TABLES")).scalars().all()
            assert "user_accounts" in self.facts["startup_tables"]
            assert "teacher_work_tasks" not in self.facts["startup_tables"]
            assert connection.scalar(text("SELECT @@skip_networking")) == 1
        self.facts["migration_receipts"] = []
        for apply, acknowledged in (
            (lambda c: apply_teacher_work_mysql(c, identity, contract_hash=TEACHER_WORK_CONTRACT_HASH), "ACKNOWLEDGED"),
            (lambda c: apply_teacher_work_exports_mysql(c, identity), "CONFIRMED"),
            (lambda c: apply_teacher_work_proposals_mysql(c, identity), "ACKNOWLEDGED"),
        ):
            with database.engine.connect() as connection:
                report = apply(connection)
                assert report.completed and report.ledger_commit_state == acknowledged
                from dataclasses import asdict
                self.facts["migration_receipts"].append(asdict(report))
        with database.engine.begin() as connection:
            assert observe_teacher_work_mysql_v3(connection).ready
            assert observe_teacher_work_proposals_mysql(connection).ready
            connection.execute(insert(UserAccount).values([
                dict(username=name, role=role, password_hash=get_password_hash(PASSWORD))
                for name, role in ((OWNER, "teacher"), (OTHER, "teacher"), (STUDENT, "student"))]))
        sources = ROOT / "sources"
        for directory in DEFAULT_COURSE_DIRECTORIES:
            (sources / directory).mkdir(parents=True)
        source = sources / DEFAULT_COURSE_DIRECTORIES[0] / "synthetic.pdf"
        source.write_bytes(b"synthetic source fingerprint only; no claimed document text\n")
        self.resource = CoursewareCatalog(frontend_root=sources).scan(refresh=True)[0].id
        (ROOT / "private-storage").mkdir(mode=0o700)
        event.listen(database.engine, "checkout", self.checkout)
        event.listen(database.engine, "checkin", self.checkin)

    def checkout(self, conn, record, *_):
        self.checked.add(id(record))

    def checkin(self, conn, record):
        # An invalidated DBAPI connection checks in as None. The real pool
        # record still identifies its checkout and must be released here.
        self.checked.discard(id(record))

    async def provider(self, request):
        assert not self.checked, "real SQL connection retained during provider await"
        assert str(request.url) == "http://synthetic.invalid/chat/completions"
        assert request.headers["authorization"] == "Bearer synthetic-provider-only"
        body = json.loads(request.content)
        assert body["model"] == "synthetic-model" and 0 < body["max_tokens"] <= 8192
        assert all(0 < v <= 5 for v in request.extensions["timeout"].values())
        kind = "proposal" if body["messages"][0]["content"] == PROPOSAL_SYSTEM_PROMPT_V1 else "chat"
        self.provider_calls.append({"kind": kind, "synthetic": True, "sql_checkouts": len(self.checked)})
        content = dict(lesson=lesson(), slides=slides()) if kind == "proposal" else dict(
            type="revision_proposal", plain_text="Synthetic persisted teacher reply")
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content)}}]})

    def wire_transport(self):
        chat, proposal = private_chat.get_runtime(), private_proposals.get_runtime()
        assert chat.pool is proposal.pool
        for runtime in (chat, proposal):
            assert type(runtime.ai) is LessonPrepWorkAI
            assert type(runtime.ai._lesson_client) is LessonPrepAIClient
            # Only the provider HTTP transport is synthetic. Actual bridge,
            # prompts, strict parsers, runtime and transactions remain intact.
            runtime.ai._lesson_client.client_factory = lambda **kw: httpx.AsyncClient(
                transport=httpx.MockTransport(self.provider), **kw)

    async def call(self, method, path, *, body=None, key=None, owner=OWNER, token=None, auth=True):
        headers = {"Authorization": "Bearer " + (token if token is not None else self.tokens[owner])} if auth else {}
        if key is not None:
            headers["Idempotency-Key"] = key
        response = await self.client.request(method, path, json=body, headers=headers)
        record = {"method": method, "path": path, "status": response.status_code,
                  "actor": owner if auth else "anonymous", "idempotency_key": key}
        if response.headers.get("content-type", "").startswith("application/json"):
            public = response.json()
            if path.endswith("/login"):
                public = deepcopy(public)
                if isinstance(public.get("data"), dict):
                    public["data"].pop("token", None)
                record["body_encoding"] = "normalized JSON; login token and request password omitted"
            else:
                record["request_utf8"] = response.request.content.decode()
                record["response_utf8"] = response.content.decode()
                record["body_encoding"] = "actual request/response UTF8"
                if "/teacher/work/" in path:
                    assert response.headers.get("cache-control") == "no-store"
            record["body"] = public
        else:
            record["binary"] = {"byte_size": len(response.content), "sha256": sha256(response.content).hexdigest(),
                                "raw_bytes": "omitted; actual downloaded bytes validated"}
            record["headers"] = dict(response.headers)
        self.exchanges.append(record)
        return response

    async def login(self):
        bad = await self.call("POST", "/api/teacher/login", auth=False,
                              body=dict(username=OWNER, role="teacher", password="synthetic-wrong"))
        assert bad.status_code == 401 and bad.json()["success"] is False
        for name, role in ((OWNER, "teacher"), (OTHER, "teacher"), (STUDENT, "student")):
            response = await self.call("POST", "/api/" + role + "/login", auth=False,
                                       body=dict(username=name, role=role, password=PASSWORD))
            assert response.status_code == 200 and response.json()["success"] is True, response.text
            self.tokens[name] = response.json()["data"]["token"]
            assert response.json()["data"]["user"]["role"] == role
        me = await self.call("GET", "/api/auth/me")
        assert me.status_code == 200 and me.json()["data"]["username"] == OWNER, me.text

    def rows(self):
        with database.engine.connect() as connection:
            names = connection.execute(text("SHOW TABLES LIKE 'teacher_work_%'")).scalars().all()
            result = {name: sorted([dict(row) for row in connection.execute(text("SELECT * FROM `" + name + "`")).mappings()],
                                   key=lambda row: json.dumps(row, sort_keys=True, default=str)) for name in names}
            self.observations.append({"independent_connection": connection.scalar(text("SELECT CONNECTION_ID()")),
                                      "row_counts": {name: len(rows) for name, rows in result.items()}})
            return result

    async def poll(self, path):
        for _ in range(200):
            response = await self.call("GET", path)
            assert response.status_code == 200, response.text
            state = response.json()["data"]
            if state["stage"] in ("COMPLETE", "FAILED", "CANCELLED"):
                assert state["stage"] == "COMPLETE" and state["provider_call_count"] == 1, state
                return state
            await asyncio.sleep(.01)
        raise AssertionError("bounded real runtime did not settle")

    async def candidate(self):
        create = dict(title="合成教师任务", topic="合成主题", audience="合成对象", scope="private", resource_ids=[self.resource])
        response = await self.call("POST", "/api/teacher/work/tasks", body=create, key="create")
        assert response.status_code == 200, response.text
        task = response.json()["data"]
        path = "/api/teacher/work/tasks/" + task["task_id"]
        before = self.rows()
        replay = await self.call("POST", "/api/teacher/work/tasks", body=create, key="create")
        assert replay.json()["data"] == task and self.rows() == before
        conflict = await self.call("POST", "/api/teacher/work/tasks", body={**create, "title": "different"}, key="create")
        assert conflict.status_code == 409 and conflict.json()["message"] == "IDEMPOTENCY_CONFLICT"
        chat_body = dict(kind="chat", skill_ref=None, input_revision=1,
                         payload=dict(text="Synthetic teacher selected request", client_message_key="message"))
        sent = await self.call("POST", path + "/messages", body=chat_body, key="chat")
        assert sent.status_code == 200, sent.text
        chat = await self.poll(path + "/runs/" + sent.json()["data"]["run_id"])
        before = self.rows()
        replay = await self.call("POST", path + "/messages", body=chat_body, key="chat")
        assert replay.json()["data"] == chat and self.rows() == before
        history = (await self.call("GET", path + "/messages")).json()["data"]["messages"]
        assert [m["role"] for m in history] == ["user", "assistant"]
        proposal_body = dict(skill_ref="lesson_outline@1", input_revision=1, expected_revision=1,
                             source_message_id=history[-1]["message_id"])
        generated = await self.call("POST", path + "/material-proposals", body=proposal_body, key="proposal")
        assert generated.status_code == 200, generated.text
        url = path + "/material-proposals/runs/" + generated.json()["data"]["run_id"]
        proposal_run = await self.poll(url)
        before = self.rows()
        replay = await self.call("POST", path + "/material-proposals", body=proposal_body, key="proposal")
        assert replay.json()["data"] == {**proposal_run, "receipt": dict(operation="generate", replayed=True)}
        assert self.rows() == before
        candidate = (await self.call("GET", url + "/proposal")).json()["data"]
        assert candidate["freshness"] == dict(adoptable=True, reason=None)
        for name in ("teacher_work_outline_snapshots", "teacher_work_outline_approvals", "teacher_work_package_versions"):
            assert not before[name], "provider candidate cannot automatically adopt/approve/export"
        original = dict(expected_revision=1, input_revision=1, expected_outline_revision=0,
                        origin_proposal_run_id=proposal_run["run_id"], lesson=deepcopy(candidate["proposal"]["lesson"]),
                        slides=deepcopy(candidate["proposal"]["slides"]))
        original["lesson"]["summary"] = "Teacher explicitly edited candidate A"
        return dict(path=path, create=create, chat_body=chat_body, chat_run=chat,
                    proposal_body=proposal_body, proposal_run=proposal_run, proposal_url=url, save_a=original)

    @staticmethod
    def approval_body(state):
        return {key: state["outline"][key] for key in (
            "input_revision", "outline_revision", "outline_digest", "source_digest")}

    async def lifecycle(self):
        context = await self.candidate()
        path, original = context["path"], context["save_a"]
        saved = await self.call("POST", path + "/materials", body=original, key="save-A")
        assert saved.status_code == 200, saved.text
        state_a = saved.json()["data"]
        manual = dict(expected_revision=2, input_revision=2, expected_outline_revision=1,
                      lesson=deepcopy(original["lesson"]), slides=deepcopy(original["slides"]))
        manual["lesson"]["summary"] = "Teacher newer manual save B"
        saved = await self.call("POST", path + "/materials", body=manual, key="save-B")
        assert saved.status_code == 200, saved.text
        state_b = saved.json()["data"]
        assert state_b["input_revision"] == state_b["working_revision"] == 3
        assert state_b["current_outline_id"] != state_a["current_outline_id"]
        before = self.rows()
        replay = await self.call("POST", path + "/materials", body=original, key="save-A")
        assert replay.json()["data"] == {**state_b, "receipt": {**state_a["receipt"], "replayed": True}}
        assert self.rows() == before
        assert len([r for r in before["teacher_work_material_proposal_records"] if r["record_type"] == "lineage"]) == 1
        approval_body = self.approval_body(state_b)
        approved = await self.call("POST", path + "/materials/approve", body=approval_body, key="approve")
        assert approved.status_code == 200, approved.text
        approval = approved.json()["data"]
        assert approval["approval_current"] and approval["working_revision"] == 4
        before = self.rows()
        replay = await self.call("POST", path + "/materials/approve", body=approval_body, key="approve")
        assert replay.json()["data"] == {**approval, "receipt": {**approval["receipt"], "replayed": True}}
        assert self.rows() == before
        export_body = {**approval_body, "approval_id": approval["approval"]["approval_id"], "expected_revision": 4}
        exported = await self.call("POST", path + "/packages", body=export_body, key="export")
        assert exported.status_code == 200, exported.text
        package = exported.json()["data"]
        assert package["run"]["stage"] == "COMPLETE" and package["provenance"] == "manual", package
        assert package["version"]["lesson"] == manual["lesson"]
        assert package["version"]["skill_versions"] == package["version"]["source_snapshots"] == []
        before = self.rows()
        replay = await self.call("POST", path + "/packages", body=export_body, key="export")
        assert replay.status_code == 200 and replay.json()["data"]["receipt"]["replayed"] is True
        assert self.rows() == before
        version = PackageVersionDTO.model_validate_json(json.dumps(package["version"]))
        assert {a["kind"] for a in package["artifacts"]} == {"docx", "pptx"}
        for artifact in package["artifacts"]:
            download = await self.call("GET", path + "/artifacts/" + artifact["artifact_id"] + "/download")
            assert download.status_code == 200 and artifact["state"] == "READY"
            raw = download.content
            assert len(raw) == artifact["byte_size"] and sha256(raw).hexdigest() == artifact["sha256"]
            assert download.headers["content-type"] == artifact["mime"]
            assert download.headers["cache-control"] == "no-store" and download.headers["x-content-type-options"] == "nosniff"
            assert download.headers["content-length"] == str(len(raw))
            assert validate_office_bytes(artifact["kind"], raw, version).valid
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                assert archive.testzip() is None
        metadata = await self.call("GET", path + "/packages/" + package["version"]["version_id"])
        assert metadata.json()["data"] == {**package, "receipt": None}
        assert [c["kind"] for c in self.provider_calls] == ["chat", "proposal"]
        context.update(state=approval, approval_body=approval_body, export_body=export_body, package=package)
        self.facts["lifecycle"] = dict(save_a=state_a["current_outline_id"], save_b=state_b["current_outline_id"],
                                       historical_replay_preserved=True, office_formats=["docx", "pptx"])
        return context

    async def identity(self):
        ctx = await self.lifecycle()
        path, package = ctx["path"], ctx["package"]
        routes = [
            ("GET", path, None), ("GET", path + "/messages", None),
            ("GET", path + "/runs/" + ctx["chat_run"]["run_id"], None),
            ("GET", path + "/material-proposals/runs", None),
            ("GET", ctx["proposal_url"] + "/proposal", None),
            ("GET", path + "/materials", None),
            ("GET", path + "/packages/" + package["version"]["version_id"], None),
            ("PATCH", path + "/working", dict(expected_revision=4, changes=dict(requirements="denied"))),
            ("POST", path + "/messages", {**ctx["chat_body"], "input_revision": 3}),
            ("POST", path + "/material-proposals", {**ctx["proposal_body"], "input_revision": 3, "expected_revision": 4}),
            ("POST", path + "/materials", {**ctx["save_a"], "input_revision": 3, "expected_revision": 4, "expected_outline_revision": 2}),
            ("POST", path + "/materials/approve", ctx["approval_body"]),
            ("POST", path + "/packages", ctx["export_body"]),
        ] + [("GET", path + "/artifacts/" + a["artifact_id"] + "/download", None) for a in package["artifacts"]]
        before = self.rows()
        for owner, status in ((OTHER, 404), (STUDENT, 403)):
            for index, (method, url, body) in enumerate(routes):
                response = await self.call(method, url, body=body, key="denied-" + str(index), owner=owner)
                assert response.status_code == status and response.json()["data"] is None, response.text
        for token in ("invalid", create_access_token(OWNER, "teacher", expires_in=-10),
                      create_access_token("nonexistent-subject", "teacher")):
            assert (await self.call("GET", "/api/auth/me", token=token)).status_code == 401
            for index, (method, url, body) in enumerate(routes):
                response = await self.call(method, url, body=body, key="invalid-" + str(index), token=token)
                assert response.status_code == 401, response.text
        assert (await self.call("GET", path, auth=False)).status_code == 401
        forged_claim = create_access_token(STUDENT, "teacher")
        assert (await self.call("GET", path, token=forged_claim)).status_code == 403
        with database.engine.begin() as connection:
            connection.execute(update(UserAccount).where(UserAccount.username == OWNER).values(role="student"))
        me = await self.call("GET", "/api/auth/me")
        assert me.json()["data"]["role"] == "student"
        for index, (method, url, body) in enumerate(routes):
            response = await self.call(method, url, body=body, key="changed-role-" + str(index))
            assert response.status_code == 403, response.text
        with database.engine.begin() as connection:
            connection.execute(delete(UserAccount).where(UserAccount.username == OWNER))
        assert (await self.call("GET", "/api/auth/me")).status_code == 401
        for index, (method, url, body) in enumerate(routes):
            response = await self.call(method, url, body=body, key="deleted-" + str(index))
            assert response.status_code == 401, response.text
        assert self.rows() == before and len(self.provider_calls) == 2
        self.facts["identity_denials"] = dict(foreign_teacher=404, student=403, invalid_subject=401,
                                             token_role_not_authority=True, changed_account_rechecked=True)

    async def gates(self):
        ctx = await self.lifecycle()
        path, package = ctx["path"], ctx["package"]
        gates = {
            "gate_tasks": ("TEACHER_WORK_PRIVATE_TASKS_ENABLED", "TEACHER_WORK_LIVE_GATES_UNVERIFIED", [
                ("GET", path, None), ("POST", "/api/teacher/work/tasks", ctx["create"])]),
            "gate_chat": ("TEACHER_WORK_PRIVATE_CHAT_ENABLED", "PRIVATE_CHAT_DISABLED", [
                ("GET", path + "/messages", None), ("POST", path + "/messages", ctx["chat_body"])]),
            "gate_proposals": ("TEACHER_WORK_PRIVATE_MATERIAL_PROPOSALS_ENABLED", "PRIVATE_MATERIAL_PROPOSALS_DISABLED", [
                ("GET", ctx["proposal_url"] + "/proposal", None), ("POST", path + "/material-proposals", ctx["proposal_body"])]),
            "gate_materials": ("TEACHER_WORK_PRIVATE_MATERIALS_ENABLED", "PRIVATE_MATERIALS_DISABLED", [
                ("GET", path + "/materials", None), ("POST", path + "/materials", ctx["save_a"]),
                ("POST", path + "/materials/approve", ctx["approval_body"])]),
            "gate_exports": ("TEACHER_WORK_PRIVATE_EXPORTS_ENABLED", "PRIVATE_EXPORTS_DISABLED", [
                ("GET", path + "/packages/" + package["version"]["version_id"], None),
                ("POST", path + "/packages", ctx["export_body"]),
                ("GET", path + "/artifacts/" + package["artifacts"][0]["artifact_id"] + "/download", None)]),
        }
        setting, code, routes = gates[self.name]
        before = self.rows()
        setattr(settings, setting, False)
        try:
            for index, (method, url, body) in enumerate(routes):
                response = await self.call(method, url, body=body, key="closed-" + str(index))
                assert response.status_code == 503 and response.json() == dict(code=503, message=code, data=None), response.text
        finally:
            setattr(settings, setting, True)
        assert self.rows() == before and len(self.provider_calls) == 2
        self.facts["gate_refusal"] = dict(setting=setting, code=code, unchanged_rows=True)

    async def ack_loss(self):
        import pymysql
        ctx = await self.candidate()
        target = {}
        original_commit = pymysql.connections.Connection.commit
        after = self.name == "ack_after"
        def trace(conn, cursor, statement, params, context, many):
            if statement.lstrip().upper().startswith("INSERT INTO TEACHER_WORK_OUTLINE_SNAPSHOTS"):
                target["connection"] = conn.connection.driver_connection
        def lose(connection):
            if connection is target.get("connection"):
                target["faults"] = target.get("faults", 0) + 1
                if after:
                    original_commit(connection)
                raise pymysql.OperationalError(2013, "synthetic owned commit acknowledgement loss")
            return original_commit(connection)
        event.listen(database.engine, "before_cursor_execute", trace)
        pymysql.connections.Connection.commit = lose
        try:
            unknown = await self.call("POST", ctx["path"] + "/materials", body=ctx["save_a"], key="unknown-save")
        finally:
            pymysql.connections.Connection.commit = original_commit
            event.remove(database.engine, "before_cursor_execute", trace)
        assert unknown.status_code == 503 and unknown.json() == dict(code=503, message="COMMIT_OUTCOME_UNKNOWN", data=None)
        assert target["faults"] == 1
        before = self.rows()
        state = (await self.call("GET", ctx["path"] + "/materials")).json()["data"]
        if after:
            assert state["outline"] is not None and len(before["teacher_work_outline_snapshots"]) == 1
            replay = await self.call("POST", ctx["path"] + "/materials", body=ctx["save_a"], key="unknown-save")
            assert replay.status_code == 200 and replay.json()["data"]["receipt"]["replayed"] is True
            assert replay.json()["data"]["current_outline_id"] == state["current_outline_id"]
            assert len([r for r in before["teacher_work_material_proposal_records"] if r["record_type"] == "lineage"]) == 1
        else:
            assert state["outline"] is None and state["receipt"] is None
            assert not before["teacher_work_outline_snapshots"]
            assert not any(r["record_type"] == "lineage" for r in before["teacher_work_material_proposal_records"])
        assert self.rows() == before and len(self.provider_calls) == 2
        self.facts["ack_loss"] = dict(position="after" if after else "before", faults=target["faults"],
                                      real_commit_called=after, unknown_has_no_receipt=True, confirmed_replay=after)

    async def task_history(self):
        from datetime import datetime
        from uuid import UUID, uuid4
        from app.models.teacher_work import OwnerRunLease
        root = "/api/teacher/work/tasks"
        before = self.rows()
        empty = await self.call("GET", root)
        assert empty.status_code == 200, empty.text
        assert empty.json()["data"] == dict(items=[], has_more=False, next_before=None)
        assert self.rows() == before  # No implicit namespace/lease initialization.
        create = dict(title="合成历史入口", topic="合成主题", audience="合成对象",
                      scope="private", resource_ids=[self.resource])
        created = await self.call("POST", root, body=create, key="history-owner")
        assert created.status_code == 200, created.text
        task = created.json()["data"]
        foreign = await self.call("POST", root, body=create, key="history-other", owner=OTHER)
        assert foreign.status_code == 200, foreign.text
        fixed = datetime(2026, 10, 6, 12, 0, 0, 123456)
        with database.engine.begin() as connection:
            exemplar = dict(connection.execute(select(WorkTask.__table__).where(
                WorkTask.task_id == task["task_id"])).mappings().one())
            connection.execute(update(WorkTask).where(WorkTask.task_id == task["task_id"]).values(created_at=fixed))
            fixture = []
            for number in range(1, 53):
                fixture.append({**exemplar, "task_id": str(UUID(int=number)), "lesson_draft_id": "history-fixture-" + str(number),
                    "create_idempotency_key": None, "create_request_digest": None,
                    "title": "只读分页合成任务 " + str(number), "created_at": fixed, "updated_at": fixed})
            connection.execute(insert(WorkTask), fixture)
            offering_id = str(uuid4())
            connection.execute(insert(WorkTask).values({**exemplar, "task_id": offering_id,
                "lesson_draft_id": "history-offering-fixture", "create_idempotency_key": None,
                "create_request_digest": None, "institution_id": str(uuid4()), "offering_id": str(uuid4()),
                "created_at": fixed, "updated_at": fixed}))
            # Display timestamps cannot move a task across immutable pages.
            connection.execute(update(WorkTask).where(WorkTask.task_id == str(UUID(int=1))).values(
                updated_at=datetime(2027, 1, 1)))
        baseline = self.rows()
        statements, commits = [], []
        def trace(conn, cursor, statement, params, context, many):
            statements.append(statement)
        def commit(conn):
            commits.append(True)
        event.listen(database.engine, "before_cursor_execute", trace)
        event.listen(database.engine, "commit", commit)
        try:
            first = await self.call("GET", root + "?limit=20")
            assert first.status_code == 200, first.text
            page = first.json()["data"]
            assert len(page["items"]) == 20 and page["has_more"]
            assert page["next_before"] == page["items"][-1]["task_id"]
            assert all(set(item) == {"task_id", "title", "created_at", "updated_at"} for item in page["items"])
            assert (await self.call("GET", root + "?limit=20")).json()["data"] == page
            maximum = await self.call("GET", root + "?limit=50")
            assert len(maximum.json()["data"]["items"]) == 50 and maximum.json()["data"]["has_more"]
            ids = [item["task_id"] for item in page["items"]]
            while page["has_more"]:
                response = await self.call("GET", root + "?limit=20&before=" + page["next_before"])
                assert response.status_code == 200, response.text
                page = response.json()["data"]
                ids.extend(item["task_id"] for item in page["items"])
            assert page["next_before"] is None
            expected = sorted([task["task_id"], *(str(UUID(int=n)) for n in range(1, 53))], reverse=True)
            assert ids == expected and len(set(ids)) == 53
            for anchor in (foreign.json()["data"]["task_id"], str(uuid4()), offering_id):
                refused = await self.call("GET", root + "?before=" + anchor)
                assert refused.status_code == 404 and refused.json()["data"] is None, refused.text
            for query in ("limit=0", "limit=51", "limit=1.2", "limit=true", "before=bad", "limit=1&limit=2", "unknown=yes"):
                refused = await self.call("GET", root + "?" + query)
                assert refused.status_code == 422, refused.text
            assert (await self.call("GET", root + "?before=ABCDEFAB-0000-0000-0000-000000000001")).status_code == 422
            assert (await self.call("GET", root, owner=STUDENT)).status_code == 403
            for token in ("invalid", create_access_token(OWNER, "teacher", expires_in=-10),
                          create_access_token("missing-history-teacher", "teacher")):
                assert (await self.call("GET", root, token=token)).status_code == 401
            assert (await self.call("GET", root, auth=False)).status_code == 401
            assert (await self.call("GET", root, token=create_access_token(STUDENT, "teacher"))).status_code == 403
            assert (await self.call("GET", root, token=create_access_token(OWNER, "student"))).status_code == 200
            settings.TEACHER_WORK_PRIVATE_TASKS_ENABLED = False
            try:
                assert (await self.call("GET", root)).status_code == 503
            finally:
                settings.TEACHER_WORK_PRIVATE_TASKS_ENABLED = True
        finally:
            event.remove(database.engine, "before_cursor_execute", trace)
            event.remove(database.engine, "commit", commit)
        assert not commits
        assert not any(re.match(r"\s*(INSERT|UPDATE|DELETE|REPLACE|CREATE|ALTER|DROP|TRUNCATE)\b", s, re.I) for s in statements)
        task_queries = [s for s in statements if "FROM teacher_work_tasks" in s]
        assert task_queries and all("LIMIT" in s.upper() for s in task_queries)
        assert self.rows() == baseline and not self.provider_calls
        opened = await self.call("GET", root + "/" + task["task_id"])
        assert opened.status_code == 200 and opened.json()["data"]["task_id"] == task["task_id"]
        denied = await self.call("GET", root + "/" + task["task_id"], owner=OTHER)
        assert denied.status_code == 404
        assert (await self.call("GET", root + "/" + offering_id)).status_code == 404
        # A namespace mismatch refuses rather than hiding corrupted ownership.
        with database.engine.begin() as connection:
            connection.execute(update(WorkTask).where(WorkTask.task_id == str(UUID(int=1))).values(owner_storage_id=str(uuid4())))
        assert (await self.call("GET", root)).status_code == 503
        with database.engine.begin() as connection:
            connection.execute(update(WorkTask).where(WorkTask.task_id == str(UUID(int=1))).values(owner_storage_id=exemplar["owner_storage_id"]))
            connection.execute(delete(OwnerRunLease).where(OwnerRunLease.owner == OWNER))
        assert (await self.call("GET", root)).status_code == 503
        with database.engine.begin() as connection:
            connection.execute(update(UserAccount).where(UserAccount.username == OWNER).values(role="student"))
        assert (await self.call("GET", root)).status_code == 403
        with database.engine.begin() as connection:
            connection.execute(delete(UserAccount).where(UserAccount.username == OWNER))
        assert (await self.call("GET", root)).status_code == 401
        self.facts["task_history"] = dict(owner_rows=53, same_timestamp_stable=True,
            read_dml_count=0, read_commit_count=0, bounded_task_queries=len(task_queries),
            namespace_corruption_refused=True, list_provider_calls=0, summary_grants_no_authority=True)

    async def isolation(self):
        try:
            Path(".env").open()
        except PermissionError:
            pass
        else:
            raise AssertionError(".env guard ineffective")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.connect(("127.0.0.1", 9))
            except PermissionError:
                pass
            else:
                raise AssertionError("TCP guard ineffective")
        # Probes never reach either the filesystem read or the network service.
        assert GUARDS["env_reads_denied"] == GUARDS["tcp_connections_denied"] == 1
        response = await self.call("GET", "/")
        assert response.status_code == 200 and response.json()["status"] == "running"

    async def run(self):
        self.wire_transport()
        chat, proposal = private_chat.get_runtime(create=False), private_proposals.get_runtime(create=False)
        try:
            async with app.router.lifespan_context(app):
                assert app.state.git_coach_worker is None
                self.facts["real_lifespan_entered"] = True
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://synthetic.local") as self.client:
                    await self.login()
                    if self.name == "lifecycle":
                        await self.lifecycle()
                    elif self.name == "identity":
                        await self.identity()
                    elif self.name.startswith("gate_"):
                        await self.gates()
                    elif self.name.startswith("ack_"):
                        await self.ack_loss()
                    elif self.name == "task_history":
                        await self.task_history()
                    elif self.name == "isolation":
                        await self.isolation()
                    else:
                        raise AssertionError("unknown scenario")
            assert chat.closed and proposal.closed, "real merged router lifespan did not close runtimes"
            assert not chat.execution._slots and not proposal.execution._slots
            assert not self.checked
            expected = 1 if self.name == "isolation" else 0
            assert GUARDS["env_reads_denied"] == GUARDS["tcp_connections_denied"] == expected
            self.facts["real_lifespan_closed_runtimes"] = True
            self.facts["completed"] = True
        finally:
            # Failure cleanup also closes owned runtimes; this cannot satisfy the
            # assertion above that the production lifespan did so on success.
            await chat.close()
            await proposal.close()
            event.remove(database.engine, "checkout", self.checkout)
            event.remove(database.engine, "checkin", self.checkin)
            database.engine.dispose()
            storage = ROOT / "private-storage"
            if storage.exists():
                shutil.rmtree(storage)
            self.facts["private_storage_removed"] = not storage.exists()
            self.facts["guards"] = dict(GUARDS)
            (ROOT / "scenario.json").write_text(json.dumps(self.facts, ensure_ascii=False, indent=2, default=str) + "\n")


if __name__ == "__main__":
    asyncio.run(Scenario(sys.argv[1]).run())
