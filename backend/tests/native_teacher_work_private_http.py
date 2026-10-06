"""Explicit-only actual security/current identity/ASGI/MySQL private-task CRU.

Configuration is synthetic in a blank working directory. Only the database
engine is bound to the owned native fixture; authority/schema paths are real.
No app.main, listener, provider or production database is used.
"""
import asyncio
from contextlib import contextmanager
import json
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event, func, insert, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql.ddl import CreateTable

from app.models.teacher_work import OwnerRunLease, WorkTask
from tests.native_teacher_work_mysql import native_db, native_server, prepare

OWNER = "native-http-teacher"
OTHER = "native-http-other-teacher"
STUDENT = "native-http-student"
NEW = "native-http-new-teacher"


@pytest.fixture
def http_db(native_db, monkeypatch, tmp_path, request):
    # All settings imports occur after chdir; never reads a repository .env.
    monkeypatch.chdir(tmp_path)
    for name in ("RAGFLOW_API_KEY", "RAGFLOW_BASE_URL", "RAGFLOW_AGENT_ID", "RAGFLOW_CHAT_ID",
            "RAGFLOW_DATASET_ID", "RAGFLOW_PUBLIC_DATASET_IDS", "OPENAI_API_KEY", "OPENAI_API_BASE"):
        monkeypatch.setenv(name, "synthetic-unused")
    monkeypatch.setenv("APP_SECRET_KEY", "synthetic-native-http-test-only")
    monkeypatch.setenv("DB_PASS", "")
    from app.core import database
    from app.core.config import settings
    from app.core.security import create_access_token
    from app.models.domain_record import DomainRecord
    from app.models.user_account import UserAccount
    from app.api.endpoints import teacher_work, teacher_lesson_prep
    from fastapi import FastAPI
    import httpx
    db = native_db
    if getattr(request, "param", None) != "absent":
        prepare(db)
    with db.engine.connect() as connection:
        connection.execute(CreateTable(DomainRecord.__table__))
        connection.execute(CreateTable(UserAccount.__table__))
        connection.execute(insert(UserAccount).values([{"username": name, "role": role, "password_hash": ""}
            for name, role in ((OWNER, "teacher"), (OTHER, "teacher"), (NEW, "teacher"), (STUDENT, "student"))]))
        connection.commit()
    monkeypatch.setattr(database, "engine", db.engine)
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=db.engine, autoflush=False))
    if hasattr(settings, "TEACHER_WORK_PRIVATE_TASKS_ENABLED"):
        monkeypatch.setattr(settings, "TEACHER_WORK_PRIVATE_TASKS_ENABLED", True)
    app = FastAPI()
    app.include_router(teacher_work.router, prefix="/api")
    app.include_router(teacher_lesson_prep.router, prefix="/api")
    db.domain, db.user, db.settings, db.app = DomainRecord, UserAccount, settings, app
    db.tokens = {name: create_access_token(name, "teacher") for name in (OWNER, OTHER, NEW, STUDENT)}
    db.httpx, db.sign = httpx, create_access_token
    db.responses = []
    db.row_observations = []
    try:
        yield db
    finally:
        try:
            payload = {"selector": request.node.nodeid, "identity": vars(db.identity), "responses": db.responses,
                "independent_row_observations": db.row_observations}
            (db.evidence / (request.node.name + ".json")).write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n")
        finally:
            database.engine.dispose()  # Own fixture engine; never disposes an existing service.


def request(db, method, path, *, owner=OWNER, token=None, body=None, key=None, raw=None):
    headers = {"Authorization": "Bearer " + (token if token is not None else db.tokens[owner])}
    if key is not None:
        headers["Idempotency-Key"] = key
    async def send():
        async with db.httpx.AsyncClient(transport=db.httpx.ASGITransport(app=db.app), base_url="http://synthetic.local") as client:
            kwargs = {"content": raw, "headers": {**headers, "Content-Type": "application/json"}} if raw is not None else {"json": body, "headers": headers}
            return await client.request(method, path, **kwargs)
    response = asyncio.run(send())
    db.responses.append({"method": method, "path": path, "status": response.status_code, "body": response.json()})
    return response


def create_body(**changes):
    return {"title": "合成标题", "topic": "合成主题", "audience": "合成对象", "resource_ids": ["synthetic-resource"], "scope": "private", **changes}


def create(db, *, key="synthetic-create", owner=OWNER, body=None):
    response = request(db, "POST", "/api/teacher/work/tasks", owner=owner, body=body or create_body(), key=key)
    assert response.status_code == 200, response.text
    assert response.json()["code"] == 200
    return response.json()["data"]


def db_rows(db):
    with db.engine.connect() as connection:
        identifier = connection.scalar(text("SELECT CONNECTION_ID()"))
        rows = tuple([dict(row) for row in connection.execute(select(model.__table__)).mappings()]
            for model in (WorkTask, db.domain, OwnerRunLease))
        db.row_observations.append({"connection_id": identifier, "tasks_drafts_leases": rows})
        return rows


def test_private_http_create_read_patch_persists_on_new_connection(http_db):
    db = http_db
    saved = create(db)
    assert set(saved) == {"task_id", "scope", "title", "topic", "audience", "duration_minutes", "target_slide_count",
        "input_revision", "working_revision", "created_at", "updated_at", "working"}
    assert set(saved["working"]) == {"requirements", "resource_ids", "needs_normalization_fields"}
    assert saved["scope"] == "private" and saved["duration_minutes"] == 45 and saved["target_slide_count"] == 8
    assert saved["created_at"].endswith("Z") and saved["updated_at"].endswith("Z")
    assert saved["working"]["needs_normalization_fields"] == ["teaching_flow"]
    path = "/api/teacher/work/tasks/" + saved["task_id"]
    response = request(db, "GET", path)
    assert response.status_code == 200 and response.json()["data"] == saved
    response = request(db, "PATCH", path + "/working", body={"expected_revision": 1,
        "changes": {"requirements": "合成编辑", "resource_ids": ["synthetic-next"], "target_slide_count": 9}})
    assert response.status_code == 200, response.text
    updated = response.json()["data"]
    assert updated["working_revision"] == updated["input_revision"] == 2
    assert updated["working"]["requirements"] == "合成编辑" and updated["working"]["resource_ids"] == ["synthetic-next"]
    assert updated["target_slide_count"] == 9
    assert request(db, "GET", path).json()["data"] == updated
    tasks, drafts, leases = db_rows(db)
    assert len(tasks) == len(drafts) == len(leases) == 1
    payload = json.loads(drafts[0]["payload"])
    assert payload["teacher_work"]["requirements"] == "合成编辑" and tasks[0]["working_revision"] == 2


def test_current_identity_rejects_invalid_expired_student_and_cross_teacher(http_db):
    db = http_db
    for token in ("invalid", db.sign(OWNER, "teacher", expires_in=-10)):
        response = request(db, "POST", "/api/teacher/work/tasks", token=token, body=create_body(), key="key")
        assert response.status_code == response.json()["code"] == 401
    assert request(db, "POST", "/api/teacher/work/tasks", owner=STUDENT, body=create_body(), key="key").status_code == 403
    saved = create(db)
    path = "/api/teacher/work/tasks/" + saved["task_id"]
    assert request(db, "GET", path, owner=OTHER).status_code == 404
    assert request(db, "PATCH", path + "/working", owner=OTHER,
        body={"expected_revision": 1, "changes": {"requirements": "cross-owner"}}).status_code == 404
    before = db_rows(db)
    with db.engine.begin() as connection:
        connection.execute(text("UPDATE user_accounts SET role='student' WHERE username=:owner"), {"owner": OWNER})
    assert request(db, "GET", path).status_code == 403  # Old signed teacher claim is irrelevant.
    assert request(db, "GET", "/api/teacher/work/capabilities").status_code == 403
    assert db_rows(db) == before


def test_private_capabilities_and_get_are_read_only_and_default_closed(http_db, monkeypatch):
    db = http_db
    saved = create(db)
    before, statements = db_rows(db), []
    def record(c, cursor, statement, params, ctx, many):
        statements.append(statement)
    event.listen(db.engine, "before_cursor_execute", record)
    try:
        for owner in (OWNER, NEW):
            response = request(db, "GET", "/api/teacher/work/capabilities", owner=owner)
            assert response.status_code == 200, response.text
            caps = response.json()["data"]
            assert set(caps) == {"chat", "task_write", "generate", "storage", "structural_preview", "rendered_preview", "publish", "reasons", "private_tasks", "private_chat"}
            assert caps["private_tasks"] == {"create": True, "read": True, "update": True}
            assert caps["task_write"] is True
            assert caps["private_chat"] == dict.fromkeys(("send", "history", "read_run", "cancel", "provider_configured", "external_provider_verified"), False)
            assert caps["reasons"] == {**{name: "private_teacher_work_only" for name in ("generate", "storage", "structural_preview")}, "chat": "private_chat_disabled",
                "rendered_preview": "rendered_preview_unsupported", "publish": "private_teacher_work_only"}
            assert all(caps[name] is False for name in ("chat", "generate", "storage",
                "structural_preview", "rendered_preview", "publish"))
        assert request(db, "GET", "/api/teacher/work/tasks/" + saved["task_id"]).json()["data"] == saved
    finally:
        event.remove(db.engine, "before_cursor_execute", record)
    assert statements and all(s.lstrip().upper().startswith(("SELECT", "SHOW")) or s.strip().upper() == "DO 0" for s in statements)
    assert db_rows(db) == before and before[2][0]["owner"] == OWNER  # NEW has no namespace/lease.
    from app.services.teacher_work.bootstrap import open_teacher_work_request
    from app.services.teacher_work.authorization import WorkAuthorizationError
    with pytest.raises(WorkAuthorizationError) as error:
        with open_teacher_work_request("Bearer " + db.tokens[OWNER], mode="write"):
            pytest.fail("ordinary operation must remain closed")
    assert error.value.code == "TEACHER_WORK_LIVE_GATES_UNVERIFIED"
    monkeypatch.setattr(db.settings, "TEACHER_WORK_PRIVATE_TASKS_ENABLED", False)
    assert request(db, "POST", "/api/teacher/work/tasks", body=create_body(), key="off").status_code == 503
    assert request(db, "GET", "/api/teacher/work/capabilities").status_code == 503
    assert db_rows(db) == before


def test_http_idempotency_cas_and_requirements_clear(http_db):
    db = http_db
    saved = create(db)
    before = db_rows(db)
    assert create(db) == saved and db_rows(db) == before
    response = request(db, "POST", "/api/teacher/work/tasks", key="synthetic-create", body=create_body(title="不同"))
    assert response.status_code == 409 and response.json()["message"] == "IDEMPOTENCY_CONFLICT"
    assert db_rows(db) == before
    path = "/api/teacher/work/tasks/" + saved["task_id"] + "/working"
    response = request(db, "PATCH", path, body={"expected_revision": 1, "changes": {"requirements": "changed"}})
    assert response.status_code == 200
    before = db_rows(db)
    response = request(db, "PATCH", path, body={"expected_revision": 1, "changes": {"requirements": "stale"}})
    assert response.status_code == 409 and response.json()["message"] == "REVISION_CONFLICT" and db_rows(db) == before
    response = request(db, "PATCH", path, body={"expected_revision": 2, "changes": {"requirements": ""}})
    assert response.status_code == 200 and response.json()["data"]["working"]["requirements"] == ""


def test_http_private_validation_and_actual_body_byte_limit(http_db):
    db = http_db
    before = db_rows(db)
    invalid = [create_body(scope="offering", offering_id=str(uuid4())), create_body(offering_id=str(uuid4())),
        create_body(title=" "), create_body(title="字" * 201), create_body(duration_minutes=True),
        create_body(duration_minutes=0), create_body(duration_minutes=601), create_body(target_slide_count=5),
        create_body(resource_ids=[]), create_body(resource_ids=["same", "same"]),
        create_body(resource_ids=["x" * 256]), create_body(owner="forged"), create_body(status="COMPLETE")]
    for body in invalid:
        response = request(db, "POST", "/api/teacher/work/tasks", body=body, key="invalid")
        assert response.status_code == response.json()["code"] == 422, response.text
    for key in (None, "control\nkey", "x" * 129):
        assert request(db, "POST", "/api/teacher/work/tasks", body=create_body(), key=key).status_code == 422
    raw = json.dumps(create_body(), ensure_ascii=False).encode()
    exact = raw + b" " * (256 * 1024 - len(raw))
    assert request(db, "POST", "/api/teacher/work/tasks", raw=exact + b" ", key="too-large").status_code == 413
    assert db_rows(db) == before
    response = request(db, "POST", "/api/teacher/work/tasks", raw=exact, key="exact-limit")
    assert response.status_code == 200, response.text
    saved = response.json()["data"]
    path = "/api/teacher/work/tasks/" + saved["task_id"] + "/working"
    before = db_rows(db)
    patches = [{"expected_revision": True, "changes": {"requirements": "x"}},
        {"expected_revision": 1, "changes": {}}, {"expected_revision": 1, "changes": {"requirements": None}},
        {"expected_revision": 1, "changes": {"requirements": "x" * 4001}},
        {"expected_revision": 1, "changes": {"resource_ids": ["same", "same"]}},
        {"expected_revision": 1, "changes": {"lesson": None}},
        {"expected_revision": 1, "changes": {"reference_ids": []}},
        {"expected_revision": 1, "changes": {"requirements": "x"}, "base_version_id": None}]
    for body in patches:
        response = request(db, "PATCH", path, body=body)
        assert response.status_code == response.json()["code"] == 422, response.text
    assert db_rows(db) == before


def legacy_body(draft_id=None):
    return {**({"draft_id": draft_id} if draft_id is not None else {}), "title": "旧合成标题", "topic": "旧合成主题", "duration_minutes": 45,
        "resource_ids": ["legacy-synthetic"], "content": {"audience": "合成对象"}}


def test_native_session_probe_after_real_current_identity(http_db):
    from app.services.teacher_work.bootstrap import open_teacher_work_request
    from app.services.current_identity import resolve_current_account
    from app.services.teacher_work.schema_mysql import observe_teacher_work_mysql
    db = http_db
    with open_teacher_work_request("Bearer " + db.tokens[OWNER], mode="read", operation="private_read") as session:
        assert resolve_current_account("Bearer " + db.tokens[OWNER], session).username == OWNER
        connection = session.connection()
        report = observe_teacher_work_mysql(connection)
        assert report.ready, report.issues
        isolation, autocommit = connection.execute(text(
            "SELECT @@session.transaction_isolation, @@session.autocommit")).one()
        connection.execute(text("DO 0"))
        from pymysql.constants.SERVER_STATUS import SERVER_STATUS_IN_TRANS
        assert (isolation, autocommit) == ("READ-COMMITTED", 0)
        status = connection.connection.driver_connection.server_status
        assert status & SERVER_STATUS_IN_TRANS
        facts = dict(connection.execute(text("SELECT CONNECTION_ID() AS connection_id, @@session.sql_mode AS sql_mode, "
            "@@session.foreign_key_checks AS foreign_key_checks, @@session.unique_checks AS unique_checks")).mappings().one())
        (db.evidence / "physical-request-session.json").write_text(json.dumps({"identity": vars(db.identity),
            **facts, "isolation": isolation, "autocommit": autocommit, "server_status": status,
            "server_status_in_trans": True}, indent=2) + "\n")


def test_linked_old_save_conflict_zero_writes_and_unlinked_legacy_behavior(http_db):
    db = http_db
    saved = create(db)
    tasks, _, _ = db_rows(db)
    before = db_rows(db)
    response = request(db, "POST", "/api/teacher/lesson-prep/drafts", body=legacy_body(tasks[0]["lesson_draft_id"]))
    assert response.status_code == 409 and "LINKED_LEGACY_WRITE_CONFLICT" in response.text
    assert db_rows(db) == before
    response = request(db, "POST", "/api/teacher/lesson-prep/drafts", owner=NEW, body=legacy_body())
    assert response.status_code == 200, response.text
    legacy = response.json()["data"]
    assert legacy["content"] == {"audience": "合成对象"} and "teacher_work" not in legacy
    response = request(db, "POST", "/api/teacher/lesson-prep/drafts", owner=NEW,
        body={**legacy_body(legacy["draft_id"]), "title": "旧合成编辑"})
    assert response.status_code == 200 and response.json()["data"]["title"] == "旧合成编辑"
    assert len(db_rows(db)[2]) == 1 and db_rows(db)[2][0]["owner"] == OWNER


def test_case_insensitive_legacy_draft_alias_cannot_overwrite_linked_work(http_db, monkeypatch):
    from itertools import count
    from uuid import UUID
    db = http_db
    identifiers = count(0xabcdef)
    monkeypatch.setattr("app.api.endpoints.teacher_work.uuid4", lambda: UUID(int=next(identifiers)))
    with db.engine.connect() as connection:
        connection.execute(text("ALTER TABLE domain_records MODIFY record_key VARCHAR(255) "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL"))
    saved = create(db)
    before = db_rows(db)
    stored_key = before[0][0]["lesson_draft_id"]
    alias = stored_key.upper()
    assert alias != stored_key
    with db.engine.connect() as connection:
        assert connection.scalar(select(db.domain.record_key).where(db.domain.record_key == alias)) == stored_key
        assert connection.scalar(select(WorkTask.task_id).where(WorkTask.lesson_draft_id == alias)) is None
    response = request(db, "POST", "/api/teacher/lesson-prep/drafts", body=legacy_body(alias))
    assert response.status_code == 409 and response.json()["message"] == "LINKED_LEGACY_WRITE_CONFLICT"
    assert db_rows(db) == before
    assert request(db, "GET", "/api/teacher/work/tasks/" + saved["task_id"]).json()["data"] == saved
    # Preserve the old editor's alias behavior for an actually unlinked draft.
    response = request(db, "POST", "/api/teacher/lesson-prep/drafts", owner=NEW, body=legacy_body())
    assert response.status_code == 200
    alias = response.json()["data"]["draft_id"].upper()
    response = request(db, "POST", "/api/teacher/lesson-prep/drafts", owner=NEW, body=legacy_body(alias))
    assert response.status_code == 200 and response.json()["data"]["draft_id"] == alias


@pytest.mark.parametrize("http_db", ["absent"], indirect=True)
def test_absent_work_registry_preserves_original_legacy_save(http_db):
    db = http_db
    response = request(db, "POST", "/api/teacher/lesson-prep/drafts", body=legacy_body())
    assert response.status_code == 200 and "teacher_work" not in response.json()["data"]
    with db.engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(db.domain)) == 1
    assert request(db, "POST", "/api/teacher/work/tasks", body=create_body(), key="unprepared").status_code == 503


def test_schema_drift_and_corrupt_draft_are_controlled(http_db):
    db = http_db
    saved = create(db)
    path = "/api/teacher/work/tasks/" + saved["task_id"]
    with db.engine.begin() as connection:
        connection.execute(text("UPDATE domain_records SET payload=JSON_REMOVE(payload,'$.teacher_work')"))
    before = db_rows(db)
    assert request(db, "GET", path).status_code == 503 and db_rows(db) == before
    with db.engine.connect() as connection:
        connection.execute(text("DROP TABLE teacher_work_catalog_selections"))
    before = db_rows(db)
    assert request(db, "GET", path).status_code == 503
    assert request(db, "GET", "/api/teacher/work/capabilities").status_code == 503
    assert request(db, "POST", "/api/teacher/lesson-prep/drafts", body=legacy_body()).status_code == 503
    assert db_rows(db) == before


def test_actual_flush_failure_and_unknown_commit_never_return_success(http_db, monkeypatch):
    db = http_db
    with db.engine.connect() as connection:
        connection.execute(text("CREATE TRIGGER tw_native_flush_fail BEFORE INSERT ON teacher_work_tasks "
            "FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='synthetic flush failure'"))
    errors = []
    def observe_error(ctx):
        errors.append(ctx.original_exception.args[0])
    event.listen(db.engine, "handle_error", observe_error)
    try:
        response = request(db, "POST", "/api/teacher/work/tasks", body=create_body(), key="flush-fail")
    finally:
        event.remove(db.engine, "handle_error", observe_error)
    assert errors == [1644] and response.status_code == 503 and db_rows(db) == ([], [], [])
    with db.engine.connect() as connection:
        connection.execute(text("DROP TRIGGER tw_native_flush_fail"))
    import pymysql
    original, target = pymysql.connections.Connection.commit, {}
    def mark(c, cursor, statement, params, ctx, many):
        if statement.lstrip().upper().startswith("INSERT INTO TEACHER_WORK_TASKS"):
            target["connection"] = c.connection.driver_connection
    def lose_reply(connection):
        original(connection)
        if connection is target.get("connection"):
            target["physical_commit"] = True
            raise pymysql.OperationalError(2013, "synthetic reply loss after physical commit")
    event.listen(db.engine, "before_cursor_execute", mark)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(pymysql.connections.Connection, "commit", lose_reply)
            response = request(db, "POST", "/api/teacher/work/tasks", body=create_body(), key="unknown-commit")
    finally:
        event.remove(db.engine, "before_cursor_execute", mark)
    assert target.get("physical_commit") is True and response.status_code == 503 and response.json()["message"] == "COMMIT_OUTCOME_UNKNOWN"
    assert all(len(group) == 1 for group in db_rows(db))  # Real commit persisted; response cannot claim success.
    saved = create(db, key="unknown-commit")
    assert all(len(group) == 1 for group in db_rows(db)) and saved["working_revision"] == 1


def test_physical_checks_and_external_root_cannot_be_self_certified(http_db):
    db = http_db
    from app.services.teacher_work.bootstrap import _SessionWorkTransport, open_teacher_work_request
    from app.services.teacher_work.authorization import WorkAuthorizationError
    with db.engine.connect().execution_options(isolation_level="READ COMMITTED") as connection:
        root = connection.begin()
        with Session(bind=connection) as session:
            session.begin()
            session.info["teaching_transaction"] = "READ COMMITTED"
            session.info["schema_ready"] = True
            session.info["commit_confirmed"] = True
            with pytest.raises(WorkAuthorizationError) as error:
                _SessionWorkTransport(session)
            assert error.value.code == "REQUEST_BINDING_CHANGED"
        assert root.is_active
        root.rollback()
    before = db_rows(db)
    def disabled(dbapi, record):
        with dbapi.cursor() as cursor:
            cursor.execute("SET SESSION foreign_key_checks=0")
    event.listen(db.engine, "connect", disabled)
    try:
        response = request(db, "GET", "/api/teacher/work/capabilities", owner=NEW)
        assert response.status_code == 503 and response.json()["message"] == "TEACHER_WORK_SCHEMA_UNAVAILABLE"
    finally:
        event.remove(db.engine, "connect", disabled)
    assert db_rows(db) == before
    for operation in ("chat", "package", "storage", "preview", "publish", "private_delete"):
        with pytest.raises(WorkAuthorizationError):
            with open_teacher_work_request("Bearer " + db.tokens[OWNER], mode="write", operation=operation):
                pytest.fail("later operation cannot be opened by private flag")


@pytest.mark.parametrize("table", ["domain_records", "user_accounts"])
def test_nontransactional_existing_participants_refuse_before_writes(http_db, table):
    db = http_db
    with db.engine.connect() as connection:
        # Keep MyISAM's 1000-byte index limit; all synthetic identity keys are ASCII.
        if table == "domain_records":
            connection.execute(text("ALTER TABLE domain_records MODIFY record_key VARCHAR(255) "
                "CHARACTER SET ascii COLLATE ascii_bin NOT NULL, MODIFY owner_id VARCHAR(255) "
                "CHARACTER SET ascii COLLATE ascii_bin DEFAULT ''"))
        else:
            connection.execute(text("ALTER TABLE user_accounts MODIFY username VARCHAR(255) "
                "CHARACTER SET ascii COLLATE ascii_bin NOT NULL"))
        connection.execute(text("ALTER TABLE " + table + " ENGINE=MyISAM"))
        assert connection.execute(text("SELECT ENGINE FROM information_schema.tables "
            "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=:name"), {"name": table}).scalar_one() == "MyISAM"
    before = db_rows(db)
    for method, path, kwargs in (("GET", "/api/teacher/work/capabilities", {}),
            ("POST", "/api/teacher/work/tasks", {"body": create_body(), "key": "nontransactional"}),
            ("POST", "/api/teacher/lesson-prep/drafts", {"body": legacy_body()})):
        response = request(db, method, path, **kwargs)
        assert response.status_code == 503 and response.json()["message"] == "TEACHER_WORK_SCHEMA_UNAVAILABLE"
        assert db_rows(db) == before


def test_old_save_waits_for_work_update_and_preserves_linked_metadata(http_db):
    db = http_db
    saved = create(db)
    tasks, _, _ = db_rows(db)
    path = "/api/teacher/work/tasks/" + saved["task_id"] + "/working"
    held, contender, release = Event(), Event(), Event()
    identifiers, locks = {}, []
    def limit(dbapi, record):
        with dbapi.cursor() as cursor:
            cursor.execute("SET SESSION innodb_lock_wait_timeout=3")
    def before(c, cursor, statement, params, ctx, many):
        upper = statement.upper()
        if "FOR UPDATE" in upper and "USER_ACCOUNTS" in upper and held.is_set() and not release.is_set():
            identifier = c.connection.driver_connection.thread_id()
            if identifier != identifiers["winner"]:
                identifiers["loser"] = identifier
                contender.set()
        if "FOR UPDATE" in upper:
            for table in ("user_accounts", "teacher_work_owner_run_leases", "domain_records", "teacher_work_tasks"):
                if table.upper() in upper:
                    locks.append((c.connection.driver_connection.thread_id(), table))
                    break
    def after(c, cursor, statement, params, ctx, many):
        if "FOR UPDATE" in statement.upper() and "USER_ACCOUNTS" in statement.upper() and not held.is_set():
            identifiers["winner"] = c.connection.driver_connection.thread_id()
            held.set()
            assert release.wait(6), "bounded lock release required"
    event.listen(db.engine, "connect", limit)
    event.listen(db.engine, "before_cursor_execute", before)
    event.listen(db.engine, "after_cursor_execute", after)
    pool = ThreadPoolExecutor(max_workers=2)
    try:
        winning = pool.submit(request, db, "PATCH", path,
            body={"expected_revision": 1, "changes": {"requirements": "并发合成修改"}})
        assert held.wait(3)
        losing = pool.submit(request, db, "POST", "/api/teacher/lesson-prep/drafts",
            body=legacy_body(tasks[0]["lesson_draft_id"]))
        assert contender.wait(3)
        deadline, observed = time.monotonic() + 2, None
        while time.monotonic() < deadline:
            with db.engine.connect() as connection:
                observed = connection.execute(text("SELECT requesting.OBJECT_NAME, requester.PROCESSLIST_ID, blocker.PROCESSLIST_ID "
                    "FROM performance_schema.data_lock_waits waits "
                    "JOIN performance_schema.data_locks requesting ON requesting.ENGINE_LOCK_ID=waits.REQUESTING_ENGINE_LOCK_ID "
                    "JOIN performance_schema.threads requester ON requester.THREAD_ID=waits.REQUESTING_THREAD_ID "
                    "JOIN performance_schema.threads blocker ON blocker.THREAD_ID=waits.BLOCKING_THREAD_ID "
                    "WHERE requesting.OBJECT_SCHEMA=:schema AND requester.PROCESSLIST_ID=:loser "
                    "AND blocker.PROCESSLIST_ID=:winner"), {"schema": db.identity.schema_name,
                        "loser": identifiers["loser"], "winner": identifiers["winner"]}).first()
            if observed:
                break
            time.sleep(.02)
        assert observed == ("user_accounts", identifiers["loser"], identifiers["winner"])
        release.set()
        winner, loser = winning.result(timeout=8), losing.result(timeout=8)
        assert winner.status_code == 200, winner.text
        assert loser.status_code == 409 and loser.json()["message"] == "LINKED_LEGACY_WRITE_CONFLICT"
        assert [table for identifier, table in locks if identifier == identifiers["loser"]] == [
            "user_accounts", "teacher_work_owner_run_leases", "domain_records", "teacher_work_tasks"]
        tasks, drafts, leases = db_rows(db)
        assert len(tasks) == len(drafts) == len(leases) == 1 and tasks[0]["working_revision"] == 2
        assert json.loads(drafts[0]["payload"])["teacher_work"]["requirements"] == "并发合成修改"
        assert request(db, "GET", path.removesuffix("/working")).json()["data"] == winner.json()["data"]
        (db.evidence / "private-legacy-lock-race.json").write_text(json.dumps({"database": db.identity.schema_name,
            "connection_ids": identifiers, "observed_lock_wait": list(observed), "lock_order": locks,
            "work_status": winner.status_code, "legacy_status": loser.status_code}, indent=2) + "\n")
    finally:
        release.set()
        pool.shutdown(wait=True, cancel_futures=True)
        event.remove(db.engine, "connect", limit)
        event.remove(db.engine, "before_cursor_execute", before)
        event.remove(db.engine, "after_cursor_execute", after)
