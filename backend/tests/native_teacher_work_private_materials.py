"""Explicit-only manual private materials with real ASGI/current identity/MySQL."""
import json
import os
from datetime import datetime, timezone, timedelta
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from uuid import uuid4
from threading import Event
import time
import pytest
from sqlalchemy import select, text, event, insert, update
from sqlalchemy.exc import IntegrityError, OperationalError, DataError
from app.models.teacher_work import OutlineSnapshot, OutlineApproval, WorkRun, OwnerRunLease, WorkTask
from app.schemas.teacher_work import OutlineSnapshotDTO
from app.services.teacher_work.materials import outline_digest
from tests.native_teacher_work_mysql import native_db, native_server
from tests.native_teacher_work_private_http import http_db, request as http_request, create, create_body, db_rows, OWNER, OTHER, STUDENT
from tests.test_teacher_work_private_materials import lesson, slides


@pytest.fixture
def material_db(http_db, monkeypatch, tmp_path, request):
    from app.services.teacher_lesson_prep.courseware_catalog import CoursewareCatalog, DEFAULT_COURSE_DIRECTORIES
    db = http_db
    root = tmp_path / "owned-synthetic-courseware"
    for name in DEFAULT_COURSE_DIRECTORIES:
        (root / name).mkdir(parents=True)
    db.source_file = root / DEFAULT_COURSE_DIRECTORIES[0] / "synthetic.pdf"
    # Fingerprints only: these bytes deliberately claim no PDF text/evidence.
    db.source_file.write_bytes(b"synthetic-source-version-A\n")
    monkeypatch.setattr(db.settings, "COURSEWARE_FRONTEND_ROOT", str(root))
    monkeypatch.setattr(db.settings, "TEACHER_WORK_PRIVATE_MATERIALS_ENABLED", True)
    db.resource_id = CoursewareCatalog(frontend_root=root).scan(refresh=True)[0].id
    db.material_exchanges = []
    try:
        yield db
    finally:
        (db.evidence / (request.node.name + ".exchanges.json")).write_text(json.dumps({"selector": request.node.nodeid,
            "identity": vars(db.identity), "exchanges": db.material_exchanges}, ensure_ascii=False, indent=2) + "\n")


def request(db, method, path, **kwargs):
    literals = {"method": method, "path": path, "body": deepcopy(kwargs.get("body")), "idempotency_key": kwargs.get("key")}
    if kwargs.get("raw") is not None:
        literals["raw_utf8"] = kwargs["raw"].decode("utf-8")
    response = http_request(db, method, path, **kwargs)
    db.material_exchanges.append({"request": literals, "response": {"status": response.status_code, "body": response.json()},
        "response_utf8_bytes": len(response.content)})
    return response


def setup(db):
    task = create(db, body=create_body(resource_ids=[db.resource_id]))
    path = "/api/teacher/work/tasks/" + task["task_id"] + "/materials"
    body = {"expected_revision": 1, "input_revision": 1, "expected_outline_revision": 0,
        "lesson": lesson(), "slides": slides()}
    return task, path, body


def approval_body(state):
    return {name: state["outline"][name] for name in ("input_revision", "outline_revision", "outline_digest", "source_digest")}


def rows(db):
    with db.engine.connect() as connection:
        identifier = connection.scalar(text("SELECT CONNECTION_ID()"))
        found = tuple([dict(row) for row in connection.execute(select(model.__table__).order_by(
            model.outline_revision if model is OutlineSnapshot else model.approval_id)).mappings()]
            for model in (OutlineSnapshot, OutlineApproval))
        db.row_observations.append({"connection_id": identifier, "immutable_outlines_approvals": found})
        return db_rows(db), found


def read_only_request(db, method, path, **kwargs):
    statements = []
    def record(c, cursor, statement, params, ctx, many):
        statements.append(statement)
    event.listen(db.engine, "before_cursor_execute", record)
    try:
        response = request(db, method, path, **kwargs)
    finally:
        event.remove(db.engine, "before_cursor_execute", record)
    assert statements and all(s.lstrip().upper().startswith(("SELECT", "SHOW")) or s.strip().upper() == "DO 0" for s in statements)
    db.row_observations.append({"read_only_sql": statements})
    return response


def test_manual_save_reopen_and_approve(material_db):
    db = material_db
    task, path, body = setup(db)
    empty = request(db, "GET", path).json()["data"]
    assert empty["outline"] is None and empty["last_outline_revision"] == 0 and empty["approval_blocker"] == "NO_OUTLINE"
    response = request(db, "POST", path, key="manual-save", body=body)
    assert response.status_code == 200, response.text
    state = response.json()["data"]
    assert set(state) == {"task_id", "input_revision", "working_revision", "last_outline_revision", "current_outline_id", "outline", "approval", "source_status", "current_source_digest", "needs_normalization_fields", "approval_eligible", "approval_current", "approval_blocker", "receipt"}
    assert state["input_revision"] == state["working_revision"] == 2 and state["last_outline_revision"] == 1
    assert state["outline"]["lesson"] == body["lesson"] and state["outline"]["slides"] == body["slides"]
    assert state["outline"]["outline_digest"] == outline_digest(OutlineSnapshotDTO.model_validate_json(json.dumps(state["outline"])))
    assert state["approval_eligible"] is True and state["approval_current"] is False and state["needs_normalization_fields"] == []
    assert read_only_request(db, "GET", path).json()["data"] == {**state, "receipt": None}
    before = rows(db)
    replay = read_only_request(db, "POST", path, key="manual-save", body=body).json()["data"]
    assert replay == {**state, "receipt": {**state["receipt"], "replayed": True}} and rows(db) == before
    response = request(db, "POST", path + "/approve", key="manual-approve", body=approval_body(state))
    assert response.status_code == 200, response.text
    approved = response.json()["data"]
    assert approved["approval_current"] is True and approved["working_revision"] == 3 and approved["input_revision"] == 2
    assert "owner" not in approved["approval"] and approved["approval"]["outline_id"] == state["current_outline_id"]
    assert read_only_request(db, "GET", path).json()["data"] == {**approved, "receipt": None}
    before = rows(db)
    replay = read_only_request(db, "POST", path + "/approve", key="manual-approve", body=approval_body(state)).json()["data"]
    assert replay == {**approved, "receipt": {**approved["receipt"], "replayed": True}} and rows(db) == before
    (_, immutable) = before
    assert len(immutable[0]) == len(immutable[1]) == 1


def test_material_capabilities_flag_and_unavailable_sources(material_db, monkeypatch):
    db = material_db
    task, path, body = setup(db)
    before = rows(db)
    cap = "/api/teacher/work/materials/capabilities"
    value = request(db, "GET", cap).json()["data"]
    assert value == {"save": True, "read": True, "approve": True, "source_configured": True, "files": False, "reasons": {"files": "files_not_enabled"}}
    old_cap = request(db, "GET", "/api/teacher/work/capabilities").json()["data"]
    assert len(old_cap) == 10 and all(old_cap[k] is False for k in ("generate", "storage", "structural_preview", "rendered_preview", "publish"))
    monkeypatch.setattr(db.settings, "TEACHER_WORK_PRIVATE_MATERIALS_ENABLED", False)
    value = request(db, "GET", cap).json()["data"]
    assert value == {**dict.fromkeys(("save", "read", "approve", "source_configured", "files"), False), "reasons": {**dict.fromkeys(("save", "read", "approve", "source_configured"), "private_materials_disabled"), "files": "files_not_enabled"}}
    for method, kwargs in (("GET", {}), ("POST", {"body": body, "key": "disabled"})):
        response = request(db, method, path, **kwargs)
        assert response.status_code == 503 and response.json()["message"] == "PRIVATE_MATERIALS_DISABLED"
    assert request(db, "GET", "/api/teacher/work/capabilities").json()["data"] == old_cap
    monkeypatch.setattr(db.settings, "TEACHER_WORK_PRIVATE_MATERIALS_ENABLED", True)
    monkeypatch.setattr(db.settings, "COURSEWARE_FRONTEND_ROOT", str(db.source_file.parent / "absent"))
    value = request(db, "GET", cap).json()["data"]
    assert value == {"save": False, "read": True, "approve": False, "source_configured": False, "files": False,
        "reasons": {**dict.fromkeys(("save", "approve", "source_configured"), "sources_unavailable"), "files": "files_not_enabled"}}
    assert request(db, "GET", path).json()["data"]["source_status"] == "unavailable"
    response = request(db, "POST", path, body=body, key="absent")
    assert response.status_code == 503 and response.json()["message"] == "MATERIAL_SOURCES_UNAVAILABLE" and rows(db) == before


def test_material_current_identity_owner_and_role_changes(material_db):
    db = material_db
    task, path, body = setup(db)
    state = request(db, "POST", path, body=body, key="owned-save").json()["data"]
    before = rows(db)
    for method, url, kwargs in (("GET", path, {}), ("POST", path, {"body": body, "key": "cross-save"}),
            ("POST", path + "/approve", {"body": approval_body(state), "key": "cross-approve"})):
        assert request(db, method, url, owner=OTHER, **kwargs).status_code == 404
        assert request(db, method, url, owner=STUDENT, **kwargs).status_code == 403
        assert request(db, method, url, token="invalid", **kwargs).status_code == 401
    with db.engine.begin() as connection:
        connection.execute(text("UPDATE user_accounts SET role='student' WHERE username=:owner"), {"owner": OWNER})
    assert request(db, "POST", path + "/approve", body=approval_body(state), key="role-changed").status_code == 403
    assert request(db, "GET", "/api/teacher/work/materials/capabilities").status_code == 403
    assert rows(db) == before


@pytest.mark.parametrize("count", [6, 12])
def test_material_cas_immutable_revisions_and_exact_approval(material_db, count):
    db = material_db
    task, path, body = setup(db)
    body["slides"] = slides(count)
    first = request(db, "POST", path, body=body, key="first").json()["data"]
    before = rows(db)
    for changes, code in (({"expected_revision": 1}, "REVISION_CONFLICT"), ({"input_revision": 1}, "REVISION_CONFLICT"),
            ({"expected_outline_revision": 0}, "OUTLINE_REVISION_CONFLICT")):
        next_body = {**body, "expected_revision": 2, "input_revision": 2, "expected_outline_revision": 1, **changes}
        response = request(db, "POST", path, body=next_body, key="stale")
        assert response.status_code == 409 and response.json()["message"] == code and rows(db) == before
    response = request(db, "POST", path, body={**body, "lesson": {**body["lesson"], "title": "different"}}, key="first")
    assert response.status_code == 409 and response.json()["message"] == "IDEMPOTENCY_CONFLICT" and rows(db) == before
    for field in ("input_revision", "outline_revision", "outline_digest", "source_digest"):
        changes = {field: 9 if "revision" in field else "0" * 64}
        response = request(db, "POST", path + "/approve", body={**approval_body(first), **changes}, key="bad-tuple")
        assert response.status_code == 409 and response.json()["message"] == "OUTLINE_APPROVAL_CONFLICT" and rows(db) == before
    approved = request(db, "POST", path + "/approve", body=approval_body(first), key="approved").json()["data"]
    second_body = {**body, "expected_revision": 3, "input_revision": 2, "expected_outline_revision": 1,
        "lesson": {**body["lesson"], "title": "新合成标题"}}
    second = request(db, "POST", path, body=second_body, key="second").json()["data"]
    assert second["working_revision"] == 4 and second["input_revision"] == 3 and second["last_outline_revision"] == 2
    assert second["approval"] is None and second["approval_current"] is False
    immutable = rows(db)[1]
    assert len(immutable[0]) == 2 and len(immutable[1]) == 1 and immutable[0][0] == before[1][0][0]
    before = rows(db)
    response = request(db, "POST", path + "/approve", body=approval_body(first), key="stale-old-outline")
    assert response.status_code == 409 and rows(db) == before
    replay = request(db, "POST", path, body=body, key="first").json()["data"]
    assert replay["outline"] == second["outline"] and replay["receipt"]["outline_id"] == first["outline"]["outline_id"]
    assert replay["receipt"]["working_revision"] == 2 and replay["working_revision"] == 4 and rows(db) == before
    task_state = request(db, "GET", path.removesuffix("/materials")).json()["data"]
    assert task_state["target_slide_count"] == count


def test_source_digest_uses_file_bytes_and_revokes_historical_approval(material_db):
    from app.services.teacher_work.types import canonical_digest
    db = material_db
    task, path, body = setup(db)
    state = request(db, "POST", path, body=body, key="source-save").json()["data"]
    actual = canonical_digest({"task_id": task["task_id"], "input_revision": 2, "title": task["title"], "topic": task["topic"],
        "audience": task["audience"], "duration_minutes": 45, "target_slide_count": 8, "requirements": "",
        "resources": [{"resource_id": db.resource_id, "sha256": sha256(db.source_file.read_bytes()).hexdigest()}], "reference_ids": []})
    assert state["current_source_digest"] == state["outline"]["source_digest"] == actual
    approved = request(db, "POST", path + "/approve", body=approval_body(state), key="source-approve").json()["data"]
    before = rows(db)
    original = db.source_file.stat()
    db.source_file.write_bytes(b"synthetic-source-version-B\n")
    os.utime(db.source_file, ns=(original.st_atime_ns, original.st_mtime_ns))
    assert db.source_file.stat().st_size == original.st_size and db.source_file.stat().st_mtime_ns == original.st_mtime_ns
    changed = request(db, "GET", path).json()["data"]
    assert changed["source_status"] == "changed" and changed["approval_blocker"] == "SOURCE_CHANGED"
    assert changed["approval"] == approved["approval"] and changed["approval_current"] is False
    response = request(db, "POST", path + "/approve", body=approval_body(state), key="source-new-approve")
    assert response.status_code == 409 and response.json()["message"] == "SOURCE_CHANGED" and rows(db) == before
    replay = request(db, "POST", path + "/approve", body=approval_body(state), key="source-approve").json()["data"]
    assert replay["receipt"]["replayed"] is True and replay["approval_current"] is False and rows(db) == before
    response = request(db, "PATCH", path.removesuffix("/materials") + "/working", body={"expected_revision": 3, "changes": {"requirements": "新要求"}})
    assert response.status_code == 200
    stale = request(db, "GET", path).json()["data"]
    assert stale["current_outline_id"] is None and stale["outline"] == state["outline"]
    assert stale["approval_blocker"] == "STALE_INPUT_REVISION" and stale["approval_current"] is False


@pytest.mark.parametrize("operation", ["save", "approve"])
def test_source_drift_during_final_owner_flush_rolls_back_all_writes(material_db, monkeypatch, operation):
    from app.services.teacher_work.bootstrap import _SessionWorkTransport
    db = material_db
    task, path, body = setup(db)
    if operation == "approve":
        state = request(db, "POST", path, body=body, key="prepare-drift").json()["data"]
        path, body = path + "/approve", approval_body(state)
    before = rows(db)
    original = _SessionWorkTransport.flush
    def drift(transport):
        original(transport)
        db.source_file.write_bytes(b"synthetic-source-version-B\n")
    with monkeypatch.context() as patch:
        patch.setattr(_SessionWorkTransport, "flush", drift)
        response = request(db, "POST", path, body=body, key="final-drift")
    assert response.status_code == 409 and response.json()["message"] == "SOURCE_CHANGED" and rows(db) == before


@pytest.mark.parametrize("change", ["opaque", "known_lesson", "lease"])
def test_final_material_state_rechecked_after_owner_flush(material_db, monkeypatch, change):
    from app.services.teacher_work.bootstrap import _SessionWorkTransport
    db = material_db
    task, path, body = setup(db)
    state = request(db, "POST", path, body=body, key="prepare-final-state").json()["data"]
    run_id = str(uuid4())
    if change == "lease":
        with db.engine.begin() as connection:
            connection.execute(insert(WorkRun).values(run_id=run_id, owner=OWNER, task_id=task["task_id"], kind="chat",
                input_revision=2, idempotency_key=b"synthetic-held-run", request_digest="a" * 64, stage="admit",
                deadline=(datetime.now(timezone.utc) + timedelta(seconds=60)).replace(tzinfo=None)))
    before = rows(db)
    draft = before[0][1][0]
    original = _SessionWorkTransport.flush
    def alter(transport):
        original(transport)
        if change == "lease":
            transport.session.execute(update(OwnerRunLease).where(OwnerRunLease.owner == OWNER).values(active_run_id=run_id,
                process_instance=str(uuid4()), expires_at=(datetime.now(timezone.utc) + timedelta(seconds=60)).replace(tzinfo=None), revision=2))
        else:
            payload = json.loads(draft["payload"])
            if change == "opaque":
                payload["content"]["unknown_after_flush"] = "合成未知段落"
            else:
                payload["content"]["summary"] = "未进入不可变快照的合成改动"
            # Preserve the newly written approval operation's draft metadata.
            current = transport.session.execute(select(db.domain.payload).where(db.domain.id == draft["id"])).scalar_one()
            metadata = json.loads(current)
            metadata["content"] = payload["content"]
            transport.session.execute(update(db.domain).where(db.domain.id == draft["id"]).values(payload=json.dumps(metadata, ensure_ascii=False)))
    with monkeypatch.context() as patch:
        patch.setattr(_SessionWorkTransport, "flush", alter)
        response = request(db, "POST", path + "/approve", body=approval_body(state), key="final-state")
    # A lease changed inside the held root is a broken prior SQL observation,
    # distinct from a consistently observed preexisting active owner lease.
    expected = {"opaque": (409, "NORMALIZATION_REQUIRED"), "known_lesson": (503, "MATERIAL_STATE_UNAVAILABLE"), "lease": (503, "SQL_LOCK_REQUIRED")}[change]
    assert (response.status_code, response.json()["message"]) == expected, response.text
    assert rows(db) == before


@pytest.mark.parametrize("operation", ["save", "approve"])
def test_unknown_material_commit_reconciles_exact_persisted_receipt(material_db, monkeypatch, operation):
    import pymysql
    db = material_db
    task, path, body = setup(db)
    if operation == "approve":
        state = request(db, "POST", path, body=body, key="prepare").json()["data"]
        path, body = path + "/approve", approval_body(state)
    original, target = pymysql.connections.Connection.commit, {}
    table = "TEACHER_WORK_OUTLINE_SNAPSHOTS" if operation == "save" else "TEACHER_WORK_OUTLINE_APPROVALS"
    def mark(c, cursor, statement, params, ctx, many):
        if statement.lstrip().upper().startswith("INSERT INTO " + table):
            target["connection"] = c.connection.driver_connection
    def lose_reply(connection):
        original(connection)
        if connection is target.get("connection"):
            target["physical_commit"] = True
            raise pymysql.OperationalError(2013, "synthetic material reply loss after physical commit")
    event.listen(db.engine, "before_cursor_execute", mark)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(pymysql.connections.Connection, "commit", lose_reply)
            response = request(db, "POST", path, body=body, key="unknown-material")
    finally:
        event.remove(db.engine, "before_cursor_execute", mark)
    assert target.get("physical_commit") is True and response.status_code == 503 and response.json()["message"] == "COMMIT_OUTCOME_UNKNOWN"
    before = rows(db)
    response = request(db, "POST", path, body=body, key="unknown-material")
    assert response.status_code == 200, response.text
    assert response.json()["data"]["receipt"]["replayed"] is True and rows(db) == before
    assert len(before[1][0]) == 1 and len(before[1][1]) == (operation == "approve")


def test_material_database_insert_failure_rolls_back_original_draft(material_db):
    db = material_db
    task, path, body = setup(db)
    state = request(db, "POST", path, body=body, key="prepare").json()["data"]
    before, errors = rows(db), []
    with db.engine.connect() as connection:
        connection.execute(text("CREATE TRIGGER native_material_fail BEFORE UPDATE ON teacher_work_tasks FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='synthetic material CAS failure'"))
    def observe(ctx):
        errors.append(ctx.original_exception.args[0])
    event.listen(db.engine, "handle_error", observe)
    try:
        response = request(db, "POST", path + "/approve", body=approval_body(state), key="fail-approve")
    finally:
        event.remove(db.engine, "handle_error", observe)
    assert errors == [1644] and response.status_code == 503 and rows(db) == before
    with db.engine.connect() as connection:
        connection.execute(text("DROP TRIGGER native_material_fail"))
    assert request(db, "POST", path + "/approve", body=approval_body(state), key="fail-approve").status_code == 200


def test_material_invalid_requests_and_content_limits_never_write(material_db):
    db = material_db
    task, path, body = setup(db)
    before = rows(db)
    invalid = [{**body, "expected_revision": True}, {**body, "expected_outline_revision": -1}, {**body, "reviewed": True},
        {**body, "slides": slides(5)}, {**body, "slides": slides(13)},
        {**body, "lesson": {**lesson(), "duration_minutes": 46, "teaching_flow": [{"stage": "讲授", "minutes": 46, "content": "合成"}]}},
        {**body, "lesson": {**lesson(), "objectives": ["字" * 2000] * 20, "key_points": ["字" * 2000] * 20}}]
    for value in invalid:
        response = request(db, "POST", path, body=value, key="invalid-material")
        assert response.status_code == 422, response.text
    for key in (None, "\n", "x" * 129):
        assert request(db, "POST", path, body=body, key=key).status_code == 422
    raw = json.dumps(body, ensure_ascii=False).encode()
    assert request(db, "POST", path, raw=raw + b" " * (262145 - len(raw)), key="over-http").status_code == 413
    assert rows(db) == before
    state = request(db, "POST", path, body=body, key="prepare").json()["data"]
    before = rows(db)
    assert request(db, "POST", path + "/approve", body={**approval_body(state), "reviewed": True}, key="forged-reviewed").status_code == 422
    assert rows(db) == before


def test_opaque_legacy_data_and_manual_citations_are_preserved(material_db):
    db = material_db
    task, path, body = setup(db)
    before = db_rows(db)
    draft = before[1][0]
    payload = json.loads(draft["payload"])
    payload["content"] = {**lesson(), "opaque_paragraph": "原始未知段落", "citations": [{"name": "人工引用", "page": 2, "excerpt": "合成摘录", "resource_id": db.resource_id}],
        "teaching_flow": [{**lesson()["teaching_flow"][0], "opaque_stage": "保留阶段备注"}]}
    body["lesson"]["citations"] = [{"name": "人工引用", "page": 2, "excerpt": "合成摘录"}]
    with db.engine.begin() as connection:
        connection.execute(update(db.domain).where(db.domain.id == draft["id"]).values(payload=json.dumps(payload, ensure_ascii=False)))
    state = request(db, "POST", path, body=body, key="preserve").json()["data"]
    assert state["approval_blocker"] == "NORMALIZATION_REQUIRED"
    assert "opaque_paragraph" in state["needs_normalization_fields"] and "teaching_flow[0].opaque_stage" in state["needs_normalization_fields"]
    stored = json.loads(db_rows(db)[1][0]["payload"])
    assert stored["content"] == payload["content"]
    before = rows(db)
    response = request(db, "POST", path + "/approve", body=approval_body(state), key="opaque-approve")
    assert response.status_code == 409 and response.json()["message"] == "NORMALIZATION_REQUIRED" and rows(db) == before
    edited = deepcopy(body)
    edited.update(expected_revision=2, input_revision=2, expected_outline_revision=1)
    edited["lesson"]["teaching_flow"][0]["content"] = "无法关联旧阶段的编辑"
    response = request(db, "POST", path, body=edited, key="unsafe-preservation")
    assert response.status_code == 422 and response.json()["message"] == "NORMALIZATION_REQUIRED" and rows(db) == before


@pytest.mark.parametrize("loss", ["summary", "slide", "xml"])
def test_material_known_export_text_loss_cannot_be_approved(material_db, loss):
    db = material_db
    task, path, body = setup(db)
    if loss == "summary":
        body["lesson"]["summary"] = " 首尾空白 "
    elif loss == "slide":
        body["slides"][0]["body"] = ["\n" * 80]
    else:
        body["lesson"]["summary"] = "合成\u0001控制符"
    state = request(db, "POST", path, body=body, key="save-loss").json()["data"]
    assert state["outline"]["lesson"] == body["lesson"] and state["outline"]["slides"] == body["slides"]
    assert state["approval_blocker"] == "MATERIAL_TEXT_UNREPRESENTABLE" and state["approval_eligible"] is False
    before = rows(db)
    response = request(db, "POST", path + "/approve", body=approval_body(state), key="approve-loss")
    assert response.status_code == 409 and response.json()["message"] == "MATERIAL_TEXT_UNREPRESENTABLE" and rows(db) == before


def contend(db, monkeypatch, path, first_body, second_body, first_key, second_key):
    from app.services.teacher_work.bootstrap import _SessionWorkTransport
    held, contender, release = Event(), Event(), Event()
    physical, original = {}, _SessionWorkTransport.flush
    def hold(transport):
        original(transport)
        identifier = transport.connection.connection.driver_connection.thread_id()
        if "winner" not in physical:
            physical["winner"] = identifier
            held.set()
            assert release.wait(6), "bounded winner release required"
    def observe(c, cursor, statement, params, ctx, many):
        identifier = c.connection.driver_connection.thread_id()
        if held.is_set() and not release.is_set() and identifier != physical["winner"] and "USER_ACCOUNTS" in statement.upper() and "FOR UPDATE" in statement.upper():
            physical["loser"] = identifier
            contender.set()
    event.listen(db.engine, "before_cursor_execute", observe)
    try:
        with monkeypatch.context() as patch, ThreadPoolExecutor(max_workers=2) as workers:
            patch.setattr(_SessionWorkTransport, "flush", hold)
            winner = workers.submit(request, db, "POST", path, body=first_body, key=first_key)
            assert held.wait(3), "first physical transaction must be held"
            loser = workers.submit(request, db, "POST", path, body=second_body, key=second_key)
            try:
                assert contender.wait(3), "second request must reach account lock"
                waits, deadline = [], time.monotonic() + 3
                while not waits and time.monotonic() < deadline:
                    with db.engine.connect() as connection:
                        waits = [dict(row) for row in connection.execute(text("SELECT requesting.PROCESSLIST_ID AS waiting_connection, blocking.PROCESSLIST_ID AS blocking_connection FROM performance_schema.data_lock_waits waits JOIN performance_schema.threads requesting ON requesting.THREAD_ID=waits.REQUESTING_THREAD_ID JOIN performance_schema.threads blocking ON blocking.THREAD_ID=waits.BLOCKING_THREAD_ID WHERE requesting.PROCESSLIST_ID=:loser AND blocking.PROCESSLIST_ID=:winner"), physical).mappings()]
                    if not waits:
                        time.sleep(.01)
                assert waits and not loser.done(), "actual MySQL lock wait required"
                db.row_observations.append({"material_account_lock_wait": waits})
            finally:
                release.set()
            return winner.result(timeout=5), loser.result(timeout=5)
    finally:
        release.set()
        event.remove(db.engine, "before_cursor_execute", observe)


def test_concurrent_same_key_save_and_approval_have_one_immutable_row(material_db, monkeypatch):
    db = material_db
    task, path, body = setup(db)
    responses = contend(db, monkeypatch, path, body, body, "concurrent-save", "concurrent-save")
    assert [r.status_code for r in responses] == [200, 200]
    assert [r.json()["data"]["receipt"]["replayed"] for r in responses] == [False, True]
    state = request(db, "GET", path).json()["data"]
    responses = contend(db, monkeypatch, path + "/approve", approval_body(state), approval_body(state), "concurrent-approve", "concurrent-approve")
    assert [r.status_code for r in responses] == [200, 200]
    assert sorted(r.json()["data"]["receipt"]["replayed"] for r in responses) == [False, True]
    observed = rows(db)
    assert len(observed[1][0]) == len(observed[1][1]) == 1 and observed[0][0][0]["working_revision"] == 3


def test_concurrent_distinct_keys_preserve_material_cas(material_db, monkeypatch):
    db = material_db
    task, path, body = setup(db)
    responses = contend(db, monkeypatch, path, body, {**body, "lesson": {**body["lesson"], "title": "竞争标题"}}, "winner", "loser")
    assert [r.status_code for r in responses] == [200, 409]
    assert responses[1].json()["message"] == "REVISION_CONFLICT"
    observed = rows(db)
    assert len(observed[1][0]) == 1 and observed[0][0][0]["working_revision"] == 2


def test_material_physical_unique_check_and_foreign_key_reject_invalid_rows(material_db):
    db = material_db
    task, path, body = setup(db)
    assert request(db, "POST", path, body=body, key="constraints").status_code == 200
    original = rows(db)[1][0][0]
    for changes, code in (({}, 1062), ({"outline_revision": 2, "input_revision": 0}, 3819),
            ({"outline_revision": 2, "task_id": str(uuid4())}, 1452)):
        values = {**original, "outline_id": str(uuid4()), **changes}
        with db.engine.connect() as connection:
            with pytest.raises(OperationalError if code == 3819 else IntegrityError) as error:
                connection.execute(insert(OutlineSnapshot).values(**values))
            assert error.value.orig.args[0] == code
            connection.rollback()
    assert len(rows(db)[1][0]) == 1


def test_material_receipt_limit_never_evicts_replay(material_db):
    db = material_db
    task, path, first_body = setup(db)
    current = None
    for index in range(64):
        body = {**first_body, "expected_revision": index + 1, "input_revision": index + 1, "expected_outline_revision": index}
        response = request(db, "POST", path, body=body, key="bounded-" + str(index))
        assert response.status_code == 200, response.text
        current = response.json()["data"]
    before = rows(db)
    response = request(db, "POST", path, body={**body, "expected_revision": 65, "input_revision": 65, "expected_outline_revision": 64}, key="bounded-full")
    assert response.status_code == 409 and response.json()["message"] == "MATERIAL_RECEIPT_LIMIT" and rows(db) == before
    replay = request(db, "POST", path, body=first_body, key="bounded-0").json()["data"]
    assert replay["outline"] == current["outline"] and replay["receipt"]["working_revision"] == 2 and replay["receipt"]["replayed"] is True
    assert rows(db) == before and len(before[1][0]) == 64


@pytest.mark.parametrize("operation", ["save", "approve"])
def test_active_owner_lease_rejects_material_mutation(material_db, operation):
    db = material_db
    task, path, body = setup(db)
    revision = 1
    if operation == "approve":
        state = request(db, "POST", path, body=body, key="prepare-busy").json()["data"]
        path, body, revision = path + "/approve", approval_body(state), 2
    run_id = str(uuid4())
    with db.engine.begin() as connection:
        connection.execute(insert(WorkRun).values(run_id=run_id, owner=OWNER, task_id=task["task_id"], kind="chat", input_revision=revision,
            idempotency_key=b"synthetic-busy", request_digest="a" * 64, stage="admit", deadline=datetime.now(timezone.utc).replace(tzinfo=None)))
        connection.execute(update(OwnerRunLease).where(OwnerRunLease.owner == OWNER).values(active_run_id=run_id,
            process_instance=str(uuid4()), expires_at=(datetime.now(timezone.utc) + timedelta(seconds=60)).replace(tzinfo=None), revision=2))
    before = rows(db)
    response = request(db, "POST", path, body=body, key="busy-material")
    assert response.status_code == 409 and response.json()["message"] == "OWNER_RUN_BUSY" and rows(db) == before


def test_persisted_nonmanual_evidence_refs_are_unavailable(material_db):
    db = material_db
    task, path, body = setup(db)
    state = request(db, "POST", path, body=body, key="prepare-poison").json()["data"]
    snapshot = deepcopy(state["outline"])
    snapshot["slides"][0]["evidence_refs"] = [str(uuid4())]
    digest = outline_digest(OutlineSnapshotDTO.model_validate_json(json.dumps(snapshot)))
    with db.engine.begin() as connection:
        connection.execute(update(OutlineSnapshot).where(OutlineSnapshot.outline_id == snapshot["outline_id"]).values(slides=snapshot["slides"], outline_digest=digest))
    before = rows(db)
    for method, url, kwargs in (("GET", path, {}), ("POST", path + "/approve", {"body": approval_body(state), "key": "poison-approve"})):
        response = request(db, method, url, **kwargs)
        assert response.status_code == 503 and response.json()["message"] == "MATERIAL_STATE_UNAVAILABLE" and rows(db) == before


def test_persisted_approval_tuple_mismatch_is_unavailable(material_db):
    db = material_db
    task, path, body = setup(db)
    state = request(db, "POST", path, body=body, key="prepare-tuple").json()["data"]
    approved = request(db, "POST", path + "/approve", body=approval_body(state), key="approve-tuple").json()["data"]
    with db.engine.begin() as connection:
        connection.execute(update(OutlineApproval).where(OutlineApproval.approval_id == approved["approval"]["approval_id"]).values(source_digest="0" * 64))
    before = rows(db)
    response = request(db, "GET", path)
    assert response.status_code == 503 and response.json()["message"] == "MATERIAL_STATE_UNAVAILABLE" and rows(db) == before


def test_new_approval_key_reuses_tuple_and_retains_original_receipts(material_db):
    db = material_db
    task, path, body = setup(db)
    state = request(db, "POST", path, body=body, key="save-repeat").json()["data"]
    first = request(db, "POST", path + "/approve", body=approval_body(state), key="approve-first").json()["data"]
    second = request(db, "POST", path + "/approve", body=approval_body(state), key="approve-second").json()["data"]
    assert first["approval"] == second["approval"] and second["working_revision"] == 4 and second["input_revision"] == 2
    before = rows(db)
    replay = read_only_request(db, "POST", path + "/approve", body=approval_body(state), key="approve-first").json()["data"]
    assert replay["working_revision"] == 4 and replay["receipt"]["working_revision"] == 3 and replay["receipt"]["replayed"] is True
    assert rows(db) == before and len(before[1][1]) == 1


def test_large_material_response_keeps_complete_unicode_content(material_db):
    db = material_db
    task, path, body = setup(db)
    body["slides"] = slides(12)
    for slide in body["slides"]:
        slide["notes"] = "字" * 1200
        slide["body"] = ["字" * 90] * 4
        slide["source_note"] = "字" * 120
    # Keep the sole legacy TEXT lesson+metadata within 65535 bytes, while
    # immutable slide JSON supplies the rest of the >120KiB wire payload.
    body["lesson"].update(objectives=["字" * 2000] * 6, key_points=["字" * 2000] * 3, summary="字" * 3000)
    response = request(db, "POST", path, body=body, key="large-unicode")
    assert response.status_code == 200, response.text
    assert len(response.content) < 262144 and len(response.content) > 120000
    assert response.json()["data"]["outline"]["lesson"] == body["lesson"]
    assert response.json()["data"]["outline"]["slides"] == body["slides"]
    reopened = read_only_request(db, "GET", path)
    assert reopened.json()["data"] == {**response.json()["data"], "receipt": None}


def test_final_current_role_is_reloaded_after_owner_flush(material_db, monkeypatch):
    from app.services.teacher_work.bootstrap import _SessionWorkTransport
    db = material_db
    task, path, body = setup(db)
    state = request(db, "POST", path, body=body, key="prepare-final-role").json()["data"]
    before, original = rows(db), _SessionWorkTransport.flush
    def alter_role(transport):
        original(transport)
        # Physical same-root mutation deliberately leaves the cached ORM
        # account untouched; admission must reload the already-held row.
        transport.connection.execute(text("UPDATE user_accounts SET role='student' WHERE username=:owner"), {"owner": OWNER})
    with monkeypatch.context() as patch:
        patch.setattr(_SessionWorkTransport, "flush", alter_role)
        response = request(db, "POST", path + "/approve", body=approval_body(state), key="final-role")
    assert response.status_code == 403, response.text
    assert rows(db) == before
    with db.engine.connect() as connection:
        assert connection.scalar(select(db.user.role).where(db.user.username == OWNER)) == "teacher"


def test_original_draft_text_limit_is_controlled_before_mysql_write(material_db):
    from app.services.teacher_work.types import canonical_json_bytes
    db = material_db
    task, path, body = setup(db)
    body["lesson"].update(objectives=["字" * 2000] * 6, key_points=["字" * 2000] * 4, summary="字" * 8000)
    with db.engine.connect() as connection:
        capacity = connection.execute(text("SELECT DATA_TYPE, CHARACTER_MAXIMUM_LENGTH FROM information_schema.columns WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='domain_records' AND COLUMN_NAME='payload'")).one()
        assert tuple(capacity) == ("text", 65535)
        boundary_key = str(uuid4())
        boundary = canonical_json_bytes({"x": "x" * (65535 - len(canonical_json_bytes({"x": ""})))})
        assert len(boundary) == 65535
        connection.execute(insert(db.domain).values(module="teacher_lesson_prep", record_type="draft", record_key=boundary_key,
            owner_id=OWNER, payload=boundary.decode("utf-8")))
        assert connection.scalar(text("SELECT OCTET_LENGTH(payload) FROM domain_records WHERE record_key=:key"), {"key": boundary_key}) == 65535
        connection.rollback()
        with pytest.raises(DataError) as error:
            connection.execute(insert(db.domain).values(module="teacher_lesson_prep", record_type="draft", record_key=str(uuid4()),
                owner_id=OWNER, payload=json.dumps(body["lesson"], ensure_ascii=False)))
        assert error.value.orig.args[0] == 1406
        connection.rollback()
        db.row_observations.append({"original_payload_column": tuple(capacity), "physical_exact_boundary_bytes": len(boundary), "physical_overflow_error": 1406})
    before, errors, statements = rows(db), [], []
    def observe_error(ctx):
        errors.append(ctx.original_exception.args[0])
    def observe_sql(c, cursor, statement, params, ctx, many):
        statements.append(statement)
    event.listen(db.engine, "handle_error", observe_error)
    event.listen(db.engine, "before_cursor_execute", observe_sql)
    try:
        response = request(db, "POST", path, body=body, key="legacy-text-capacity")
    finally:
        event.remove(db.engine, "handle_error", observe_error)
        event.remove(db.engine, "before_cursor_execute", observe_sql)
    assert response.status_code == 422 and response.json()["message"] == "PRIVATE_DRAFT_TOO_LARGE", response.text
    assert not errors and all(s.lstrip().upper().startswith(("SELECT", "SHOW")) or s.strip().upper() == "DO 0" for s in statements)
    assert rows(db) == before


def test_http_original_draft_exact_capacity_and_one_byte_over(material_db, monkeypatch):
    from app.repositories import teacher_work_materials as repository
    from app.services.teacher_work.types import canonical_json_bytes
    db = material_db
    monkeypatch.setattr("app.api.endpoints.teacher_work._clock", lambda: datetime(2026, 10, 6, 12, 0, 0, 123456, tzinfo=timezone.utc))
    task, path, body = setup(db)
    body["lesson"].update(objectives=["字" * 1000] * 20, summary="x" * 8000)
    measured, original = [], repository.check_original_payload_size
    def observe_size(payload):
        measured.append(len(canonical_json_bytes(payload)))
        return original(payload)  # Preserve every production decision.
    monkeypatch.setattr(repository, "check_original_payload_size", observe_size)
    before = rows(db)
    probe = read_only_request(db, "POST", path, body=body, key="capacity_probe_1")
    assert probe.status_code == 422 and probe.json()["message"] == "PRIVATE_DRAFT_TOO_LARGE"
    assert measured[-1] > 65535 and rows(db) == before
    # The known pre-DML refusal measures the actual candidate without guessing
    # the metadata shape, UUID values or operation journal's serialized size.
    body["lesson"]["summary"] = "x" * (8000 - (measured[-1] - 65535))
    assert 1 <= len(body["lesson"]["summary"]) <= 8000
    response = request(db, "POST", path, body=body, key="capacity_exact_1")
    assert response.status_code == 200, response.text
    assert measured[-1] == 65535
    saved = response.json()["data"]
    assert saved["outline"]["lesson"] == body["lesson"] and saved["outline"]["slides"] == body["slides"]
    assert read_only_request(db, "GET", path).json()["data"] == {**saved, "receipt": None}
    with db.engine.connect() as connection:
        draft_id = connection.scalar(select(WorkTask.lesson_draft_id).where(WorkTask.task_id == task["task_id"]))
        actual_bytes = connection.scalar(text("SELECT OCTET_LENGTH(payload) FROM domain_records WHERE record_key=:key AND owner_id=:owner"), {"key": draft_id, "owner": OWNER})
        assert actual_bytes == 65535
    second = create(db, key="capacity_second_task", body=create_body(resource_ids=[db.resource_id]))
    second_path = "/api/teacher/work/tasks/" + second["task_id"] + "/materials"
    above = deepcopy(body)
    above["lesson"]["summary"] += "x"  # Exactly one UTF-8 byte.
    before = rows(db)
    refused = read_only_request(db, "POST", second_path, body=above, key="capacity_above_1")
    assert measured[-1] == 65536
    assert refused.status_code == 422 and refused.json()["message"] == "PRIVATE_DRAFT_TOO_LARGE"
    assert rows(db) == before
    unchanged = read_only_request(db, "GET", second_path).json()["data"]
    assert unchanged["outline"] is None and unchanged["input_revision"] == unchanged["working_revision"] == 1
    db.row_observations.append({"http_exact_original_payload_bytes": actual_bytes, "http_one_byte_over_candidate_bytes": measured[-1],
        "one_byte_over_no_dml": True, "complete_lesson_and_slides_retained": True})
