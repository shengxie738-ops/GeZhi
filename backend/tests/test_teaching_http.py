"""Task6A signed-token ASGI evidence only; no startup, sockets or MySQL proof.

Only the dedicated DB dependency is overridden. The exact signed-token decoder
and current-account resolver run against persisted synthetic UserAccount rows.
Hypothetical writes reuse the reviewed fixture-local readiness/transaction/
safety/clock substitutions, separately from genuine closed-boundary tests.
"""
import ast
import asyncio
import dataclasses
from functools import wraps
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy import delete, event, update
from sqlalchemy.exc import OperationalError

from tests.test_teaching_authorization import dbcase, feature, NOW, snapshot
from tests.test_teaching_receipts import writes_case, counts


def sync_asgi(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))
    return run


def app_for(case):
    adapter = feature("app.api.endpoints.teaching")
    app = FastAPI()
    app.include_router(adapter.router, prefix="/api")
    async def fixture_db():
        return case[0]
    app.dependency_overrides[adapter.get_teaching_db] = fixture_db
    assert adapter.get_teaching_account not in app.dependency_overrides
    return app, adapter


async def request(app, method, path, *, actor="owner", token_role="teacher",
                  key="signed-http:123", authorization="signed", **kwargs):
    headers = {"Idempotency-Key": key}
    if authorization == "signed":
        token = feature("app.core.security").create_access_token(actor, token_role)
        headers["Authorization"] = "Bearer " + token
    elif authorization is not None:
        headers["Authorization"] = authorization
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://synthetic-asgi") as client:
        return await client.request(method, path, headers=headers, **kwargs)


def data(response, status=200):
    assert response.status_code == status, response.text
    assert response.json()["code"] == status
    assert response.headers["cache-control"] == "no-store"
    for private in ("password_hash", "phone", "class_name", "trusted_roster_json", "trusted_delegations_json", "source_policy_digest"):
        assert private not in response.text
    return response.json()["data"]


def confirmation(preview, revision=0):
    return {"preview_id": preview["id"], "expected_roster_revision": revision,
            "confirmed_withdrawals_digest": preview["withdrawals_digest"],
            "confirmed_withdrawals_count": preview["withdrawals_count"]}


def role_command(revision=0, *, status="active", permissions=None, scope="assigned", label="assistant"):
    return {"expected_role_revision": revision, "status": status, "label": label,
            "permissions": permissions if permissions is not None else ["AUTHOR"],
            "scope": scope, "effective_from": None, "effective_until": None,
            "reason": "Synthetic bounded delegation"}


def test_aggregate_mount_is_structural_only():
    # Read/AST only: aggregate imports contain unrelated paused modules and may
    # never execute here. app.main/init_db are never imported.
    path = Path(__file__).parents[1] / "app/api/api.py"
    tree = ast.parse(path.read_text())
    imports = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
               and node.module == "app.api.endpoints"]
    assert any(alias.name == "teaching" for node in imports for alias in node.names)
    includes = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute) and node.func.attr == "include_router"]
    assert sum(bool(node.args) and ast.unparse(node.args[0]) == "teaching.router" for node in includes) == 1


def test_deployment_capture_is_immutable_seven_field_default_off():
    policy = feature("app.services.teaching.policy")
    settings = SimpleNamespace(TEACHING_INSTITUTION_ID="school", TEACHING_ENABLED=True,
        TEACHING_ASSIGNMENTS_ENABLED=False, TEACHING_FEEDBACK_ENABLED=False,
        TEACHING_REVISIONS_ENABLED=False, TEACHER_STUDENT_ASSIGNMENTS='{"owner":["learner"]}',
        TEACHING_TRUSTED_DELEGATIONS="{}")
    first = policy.capture_deployment_policy(settings)
    settings.TEACHING_ENABLED = False
    settings.TEACHER_STUDENT_ASSIGNMENTS = "{}"
    assert first.enabled and first.trusted_roster_json == '{"owner":["learner"]}'
    with pytest.raises(dataclasses.FrozenInstanceError):
        first.enabled = False
    off = policy.capture_deployment_policy(SimpleNamespace())
    assert not off.enabled and off.institution_id == ""
    assert off.trusted_roster_json == off.trusted_delegations_json == "{}"
    class SevenFieldsOnly:
        def __getattr__(self, name):
            assert name in {"TEACHING_INSTITUTION_ID", "TEACHING_ENABLED", "TEACHING_ASSIGNMENTS_ENABLED",
                "TEACHING_FEEDBACK_ENABLED", "TEACHING_REVISIONS_ENABLED", "TEACHER_STUDENT_ASSIGNMENTS",
                "TEACHING_TRUSTED_DELEGATIONS"}
            return getattr(settings, name)
    assert policy.capture_deployment_policy(SevenFieldsOnly()) == policy.capture_deployment_policy(settings)


def test_dedicated_sessions_bind_same_process_snapshot_without_sql(monkeypatch):
    sessions = feature("app.services.teaching.sessions")
    config = feature("app.core.config")
    captured = sessions._DEPLOYMENT_POLICY_INPUTS
    monkeypatch.setattr(config.settings, "TEACHING_ENABLED", not captured.enabled)
    trace = []
    class Connection:
        def in_transaction(self): return False
        def execution_options(self, **values):
            trace.append(values); return self
        def close(self): trace.append("connection_close")
    class FakeSession:
        def __init__(self, **values): self.info = {}; self.active = False
        def begin(self): self.active = True
        def in_transaction(self): return self.active
        def rollback(self): self.active = False
        def close(self): trace.append("session_close")
    monkeypatch.setattr(sessions, "Session", FakeSession)
    engine = SimpleNamespace(dialect=SimpleNamespace(name="mysql"), connect=lambda: Connection())
    for _ in range(2):
        with sessions.open_teaching_session(engine) as db:
            assert db.info["teaching_policy_provider"]() is captured
            assert db.info["teaching_transaction"] == "READ COMMITTED"
    assert trace.count({"isolation_level": "READ COMMITTED"}) == 2


@sync_asgi
async def test_signed_teacher_reads_and_truthful_closed_write_capability(dbcase):
    app, _ = app_for(dbcase)
    capability = data(await request(app, "GET", "/api/teaching/capabilities"))
    assert capability["available"] and capability["account_role"] == "teacher"
    assert not capability["can_create_course"] and not capability["writes_available"]
    assert capability["write_reason"] == "write_safety_unproven"
    courses = data(await request(app, "GET", "/api/teaching/courses?membership=teaching&limit=1"))
    assert len(courses["items"]) == 1 and courses["next_cursor"] == courses["items"][-1]["id"]
    own = data(await request(app, "GET", "/api/teaching/courses/c1"))
    assert own["visible_offering_count"] == 3 and own["source_teacher_id"] == "owner"
    offerings = data(await request(app, "GET", "/api/teaching/offerings?course_id=c1&membership=teaching"))
    assert {row["id"] for row in offerings["items"]} == {"o1", "draft", "archived"}
    detail = data(await request(app, "GET", "/api/teaching/offerings/o1"))
    assert "ROSTER_MANAGE" in detail["access"]["configured_permissions"]
    for row in [detail] + offerings["items"]:
        assert row["access"]["available_actions"] == []
        assert not row["access"]["writes_available"] and row["access"]["write_reason"] == "write_safety_unproven"


@sync_asgi
async def test_signed_learner_reads_only_persisted_own_courses_offerings_enrollment(dbcase):
    app, _ = app_for(dbcase)
    courses = data(await request(app, "GET", "/api/teaching/courses?membership=learning", actor="learner"))
    assert [(row["id"], row["visible_offering_count"]) for row in courses["items"]] == [("c1", 2)]
    detail = data(await request(app, "GET", "/api/teaching/courses/c1", actor="learner"))
    assert detail["memberships"] == ["learning"]
    offering = data(await request(app, "GET", "/api/teaching/offerings/o1", actor="learner"))
    assert offering["access"]["learning"] and not offering["access"]["teaching"]
    assert offering["roster_revision"] is None and offering["access"]["configured_permissions"] == []
    own = data(await request(app, "GET", "/api/teaching/offerings/o1/enrollment", actor="learner"))
    assert own["id"] == "e-o1-learner" and own["student_id"] == "learner" and own["access_eligible"]


@sync_asgi
@pytest.mark.parametrize("path", [
    "/courses?actor_id=other", "/courses?membership=admin", "/courses?limit=0", "/courses?limit=101",
    "/courses?limit=true", "/courses?limit=01", "/courses?limit=1&limit=2", "/courses?cursor=a%0A",
    "/offerings?scope=offering", "/offerings?student_id=peer", "/offerings?course_id=c1&course_id=c2",
    "/courses/c1?limit=1", "/offerings/o1?actor_id=other", "/offerings/o1/enrollment?student_id=peer",
    "/offerings/o1/roster?limit=1000", "/offerings/o1/roles?scope=offering", "/capabilities?write_enabled=true",
])
async def test_signed_get_queries_are_strict_and_cannot_supply_authority(dbcase, path):
    app, _ = app_for(dbcase)
    response = await request(app, "GET", "/api/teaching" + path)
    assert response.status_code == 422
    assert response.json() == {"code": 422, "message": "validation_error", "data": None}
    assert response.headers["cache-control"] == "no-store" and counts(dbcase[0], dbcase[3]) == (0, 0)


@sync_asgi
@pytest.mark.parametrize("visible,missing", [
    ("/courses/c2", "/courses/missing"), ("/courses/foreign", "/courses/missing"),
    ("/offerings/other", "/offerings/missing"), ("/offerings/foreign", "/offerings/missing"),
    ("/offerings/draft/enrollment", "/offerings/missing/enrollment"),
])
async def test_signed_missing_hidden_and_foreign_scope_have_identical_404(dbcase, visible, missing):
    app, _ = app_for(dbcase)
    first = await request(app, "GET", "/api/teaching" + visible, actor="learner")
    second = await request(app, "GET", "/api/teaching" + missing, actor="learner")
    assert first.status_code == second.status_code == 404
    assert first.json() == second.json() == {"code": 404, "message": "not_found", "data": None}
    assert first.headers["cache-control"] == second.headers["cache-control"] == "no-store"


@sync_asgi
@pytest.mark.parametrize("credential", ["absent", "tampered", "expired", "missing_account", "invalid_account"])
async def test_actual_signed_token_and_current_account_refusals(dbcase, credential):
    db, _, _, _, accounts, _ = dbcase
    security = feature("app.core.security")
    token = security.create_access_token("owner", "teacher", expires_in=-30 if credential == "expired" else 300)
    authorization = "Bearer " + token
    if credential == "absent": authorization = None
    if credential == "tampered": authorization = "Bearer " + token + "broken"
    if credential == "missing_account": authorization = "Bearer " + security.create_access_token("missing", "teacher")
    if credential == "invalid_account":
        db.execute(update(accounts.UserAccount).where(accounts.UserAccount.username == "owner").values(role="admin")); db.commit()
    app, _ = app_for(dbcase)
    response = await request(app, "GET", "/api/teaching/courses", authorization=authorization)
    assert response.status_code == 401 and response.json()["message"] == "unauthenticated"
    assert response.json()["data"] is None and response.headers["cache-control"] == "no-store"


@sync_asgi
async def test_stale_teacher_claim_is_revalidated_as_current_student_then_deleted(dbcase):
    db, _, _, _, accounts, _ = dbcase
    app, _ = app_for(dbcase)
    token = feature("app.core.security").create_access_token("teacherlearner", "teacher")
    db.execute(update(accounts.UserAccount).where(accounts.UserAccount.username == "teacherlearner").values(role="student")); db.commit()
    own = data(await request(app, "GET", "/api/teaching/offerings/o1/enrollment", authorization="Bearer " + token))
    assert own["student_id"] == "teacherlearner"
    cap = data(await request(app, "GET", "/api/teaching/capabilities", authorization="Bearer " + token))
    assert cap["account_role"] == "student" and not cap["can_create_course"]
    db.execute(delete(accounts.UserAccount).where(accounts.UserAccount.username == "teacherlearner")); db.commit()
    response = await request(app, "GET", "/api/teaching/courses", authorization="Bearer " + token)
    assert response.status_code == 401


@sync_asgi
@pytest.mark.parametrize("actor,status", [("co", 200), ("learner", 403), ("assistant", 403), ("other", 404)])
async def test_roster_and_roles_gets_require_independent_current_permissions(dbcase, actor, status):
    app, _ = app_for(dbcase)
    for suffix in ("roster?limit=2", "roles"):
        response = await request(app, "GET", "/api/teaching/offerings/o1/" + suffix, actor=actor)
        projection = data(response, status)
        if status == 200:
            assert projection["items"]
            if suffix.startswith("roster"):
                assert len(projection["items"]) == 2 and projection["next_cursor"]
            else:
                assert {row["subject_id"] for row in projection["items"]} == {"owner", "co", "assistant"}


@sync_asgi
async def test_unpatched_default_off_capability_and_get_do_not_query_teaching(dbcase):
    db = dbcase[0]
    db.info.pop("teaching_policy_provider")
    statements = []
    event.listen(db.bind, "before_cursor_execute", lambda conn, cursor, statement, parameters, context, many: statements.append(statement))
    app, _ = app_for(dbcase)
    cap = data(await request(app, "GET", "/api/teaching/capabilities"))
    assert not cap["available"] and cap["reason"] == "feature_disabled"
    assert not cap["writes_available"] and not cap["can_create_course"]
    refusal = await request(app, "GET", "/api/teaching/courses")
    assert refusal.status_code == 503 and refusal.json()["message"] == "feature_disabled"
    assert not any("teaching_" in sql.lower() for sql in statements)


@sync_asgi
async def test_capabilities_preserve_stage_dependency_and_uninstalled_distinctions(dbcase):
    db = dbcase[0]
    db.info["teaching_policy_provider"] = lambda: dataclasses.replace(snapshot(), feedback_enabled=True, revisions_enabled=True)
    app, _ = app_for(dbcase)
    cap = data(await request(app, "GET", "/api/teaching/capabilities"))
    assert cap["available"] and cap["assignments"]["reason"] == "feature_disabled"
    assert cap["feedback"]["reason"] == cap["revisions"]["reason"] == "dependency_disabled"
    db.info["teaching_policy_provider"] = lambda: dataclasses.replace(snapshot(), assignments_enabled=True, feedback_enabled=True, revisions_enabled=True)
    cap = data(await request(app, "GET", "/api/teaching/capabilities"))
    assert not cap["assignments"]["installed"] and not cap["assignments"]["available"] and cap["assignments"]["reason"] == "assessment_schema_missing"
    assert all(not cap[stage]["installed"] and not cap[stage]["available"] and cap[stage]["reason"] == "stage_unavailable" for stage in ("feedback", "revisions"))
    assert not cap["can_create_course"] and not cap["writes_available"]


@sync_asgi
@pytest.mark.parametrize("reason", ["teaching_schema_missing", "teaching_schema_incompatible"])
async def test_typed_schema_error_dispatch_is_sanitized_not_vendor_proof(dbcase, monkeypatch, reason):
    db, access, _, _, _, _ = dbcase
    schema = feature("app.services.teaching.schema")
    def refusal(session):
        raise schema.TeachingSchemaError(reason, [schema.SchemaIssue("private_table", "private_kind", "private SQL")])
    monkeypatch.setattr(access, "require_teaching_schema", refusal)
    app, _ = app_for(dbcase)
    cap = data(await request(app, "GET", "/api/teaching/capabilities"))
    assert not cap["available"] and cap["reason"] == reason
    response = await request(app, "GET", "/api/teaching/courses")
    assert response.status_code == 503 and response.json() == {"code": 503, "message": reason, "data": None}
    assert "private" not in response.text


@sync_asgi
@pytest.mark.parametrize("boundary", ["schema", "transaction", "hard_gate"])
async def test_genuine_closed_schema_transaction_and_write_safety_http(dbcase, monkeypatch, boundary):
    db, access, _, models, _, readiness = dbcase
    writes = feature("app.services.teaching.writes")
    if boundary != "transaction": monkeypatch.setattr(writes, "_require_transaction", lambda session: None)
    if boundary == "schema": monkeypatch.setattr(access, "require_teaching_schema", readiness)
    app, _ = app_for(dbcase)
    response = await request(app, "POST", "/api/teaching/courses", json={"title": "Closed", "timezone": "UTC"})
    expected = {"schema": "teaching_schema_incompatible", "transaction": "lock_orchestration_required", "hard_gate": "write_safety_unproven"}[boundary]
    assert response.status_code == 503 and response.json()["message"] == expected
    assert counts(db, models) == (0, 0)
    if boundary == "schema":
        cap = data(await request(app, "GET", "/api/teaching/capabilities"))
        assert not cap["available"] and cap["reason"] == expected


@sync_asgi
@pytest.mark.parametrize("failure,status,message", [("disconnect", 503, "database_unavailable"), ("unexpected", 500, "internal_error")])
async def test_database_disconnect_and_unexpected_error_are_distinct_private_responses(dbcase, failure, status, message):
    app, adapter = app_for(dbcase)
    async def unavailable():
        if failure == "disconnect":
            raise OperationalError("private SQL", {}, RuntimeError("private transport"))
        raise RuntimeError("private programming detail")
    app.dependency_overrides[adapter.get_teaching_db] = unavailable
    response = await request(app, "GET", "/api/teaching/courses")
    assert response.status_code == status and response.json()["message"] == message
    assert "private" not in response.text and response.headers["cache-control"] == "no-store"
    assert response.json()["data"] is None if status == 503 else set(response.json()["data"]) == {"correlation_id"}


@sync_asgi
async def test_hypothetical_signed_course_roster_activation_and_independent_role_workflow(writes_case):
    db, _, _, models, accounts = writes_case
    app, _ = app_for(writes_case)
    course = data(await request(app, "POST", "/api/teaching/courses", json={"title": "Signed course", "timezone": "UTC"}), 201)
    cid = course["result"]["course_id"]
    offering = data(await request(app, "POST", f"/api/teaching/courses/{cid}/offerings", key="signed-offering:123", json={"title": "Signed cohort", "term": "Fall"}), 201)
    oid = offering["result"]["offering_id"]
    preview = data(await request(app, "POST", f"/api/teaching/offerings/{oid}/roster-previews", key="signed-preview:123", json={"mode": "replace", "expected_roster_revision": 0, "student_ids": ["learner"]}), 201)["result"]
    applied = data(await request(app, "POST", f"/api/teaching/offerings/{oid}/roster-applications", key="signed-apply:123", json=confirmation(preview)))
    assert applied["result"]["added_count"] == 1 and applied["result"]["target_count"] == 1
    data(await request(app, "POST", f"/api/teaching/offerings/{oid}/transitions", key="signed-active:123", json={"expected_revision": 1, "target_state": "active", "reason": "Synthetic acceptance"}))
    learner = data(await request(app, "GET", f"/api/teaching/offerings/{oid}/enrollment", actor="learner"))
    assert learner["student_id"] == "learner"
    assert data(await request(app, "GET", f"/api/teaching/courses/{cid}", actor="learner"))["visible_offering_count"] == 1
    data(await request(app, "PUT", f"/api/teaching/offerings/{oid}/roles/co", key="signed-manager:123", json=role_command(permissions=["ROLES_MANAGE"], scope="offering", label="teacher")))
    granted = data(await request(app, "PUT", f"/api/teaching/offerings/{oid}/roles/assistant", key="signed-assistant:123", actor="co", json=role_command()))
    assert granted["result"]["revision"] == 1
    roles = data(await request(app, "GET", f"/api/teaching/offerings/{oid}/roles", actor="co"))
    assistant = next(row for row in roles["items"] if row["subject_id"] == "assistant")
    assert assistant["granted_account_role"] == "student" and assistant["effective_permissions"] == ["AUTHOR"]
    denied = await request(app, "PATCH", f"/api/teaching/offerings/{oid}", actor="assistant", json={"expected_revision": 2, "title": "Forbidden"})
    assert denied.status_code == 403
    hidden = await request(app, "GET", f"/api/teaching/offerings/{oid}", actor="other")
    assert hidden.status_code == 404
    data(await request(app, "PUT", f"/api/teaching/offerings/{oid}/roles/assistant", key="signed-revoke:123", actor="co", json=role_command(1, status="revoked", permissions=[])))
    assert (await request(app, "GET", f"/api/teaching/offerings/{oid}", actor="assistant")).status_code == 404
    original = data(await request(app, "GET", "/api/teaching/receipts/" + granted["receipt"]["id"], actor="co"))
    assert original["receipt"] == granted["receipt"] and original["result"] == granted["result"] and original["replayed"]
    assert db.get(accounts.UserAccount, "assistant").role == "student" and counts(db, models) == (8, 8)


@sync_asgi
async def test_hypothetical_count_contract_preview_keep_includes_updates_application_excludes(writes_case):
    db, _, _, models, accounts = writes_case
    db.add(accounts.UserAccount(username="newlearner", role="student", password_hash="synthetic")); db.commit()
    db.info["teaching_policy_provider"] = lambda: snapshot(roster={"owner": ["learner", "assistant", "teacherlearner", "revoked", "newlearner"], "co": ["learner"]})
    app, _ = app_for(writes_case)
    preview = data(await request(app, "POST", "/api/teaching/offerings/o1/roster-previews", key="count-preview:123", json={"mode": "merge", "expected_roster_revision": 0, "student_ids": ["learner", "assistant", "teacherlearner", "revoked", "newlearner"], "period": {"effective_from": None, "effective_until": None}}), 201)["result"]
    assert preview["target_count"] == preview["add_count"] + preview["keep_count"] == 5
    assert preview["keep_count"] == preview["update_count"] == 4
    result = data(await request(app, "POST", "/api/teaching/offerings/o1/roster-applications", key="count-apply:123", json=confirmation(preview)))["result"]
    assert result["target_count"] == result["added_count"] + result["kept_count"] + result["updated_count"] == 5
    assert result["added_count"] == 1 and result["kept_count"] == 0 and result["updated_count"] == 4
    schemas = feature("app.schemas.teaching")
    assert "includes" in schemas.RosterPreviewDTO.model_fields["keep_count"].description
    assert "excludes" in schemas.RosterApplicationDTO.model_fields["kept_count"].description
    assert counts(db, models) == (2, 2)


@sync_asgi
async def test_hypothetical_delayed_http_response_and_recovery_keep_original_receipt(writes_case):
    app, _ = app_for(writes_case)
    committed, release = asyncio.Event(), asyncio.Event()
    class DelayAcceptedResponse:
        def __init__(self, app): self.app = app
        async def __call__(self, scope, receive, send):
            delay = (scope["type"] == "http" and dict(scope["headers"]).get(b"idempotency-key") == b"delay-first:123")
            async def controlled_send(message):
                if delay and message["type"] == "http.response.start":
                    assert message["status"] == 200
                    committed.set()
                    await asyncio.wait_for(release.wait(), 5)
                await send(message)
            await self.app(scope, receive, controlled_send)
    app.add_middleware(DelayAcceptedResponse)
    first_task = asyncio.create_task(request(app, "PATCH", "/api/teaching/offerings/o1", key="delay-first:123", json={"expected_revision": 1, "title": "First accepted"}))
    try:
        await asyncio.wait_for(committed.wait(), 5)
        second = data(await request(app, "PATCH", "/api/teaching/offerings/o1", key="delay-second:123", json={"expected_revision": 2, "title": "Second accepted"}))
        current = data(await request(app, "GET", "/api/teaching/offerings/o1"))
        assert current["title"] == "Second accepted" and current["revision"] == second["result"]["revision"] == 3
    finally:
        release.set()
    first = data(await first_task)
    assert first["result"] == {"offering_id": "o1", "revision": 2}
    assert first["receipt"]["original_result"] == first["result"]
    recovery = data(await request(app, "GET", "/api/teaching/receipts/" + first["receipt"]["id"]))
    assert recovery["receipt"] == first["receipt"] and recovery["result"] == first["result"]
    by_key = data(await request(app, "GET", "/api/teaching/receipts?action=course_manage&scope_type=offering&scope_id=o1&key=delay-first:123"))
    assert by_key == recovery and counts(writes_case[0], writes_case[3]) == (2, 2)


def test_public_capability_and_access_dtos_cannot_claim_write_readiness():
    schemas = feature("app.schemas.teaching")
    with pytest.raises(ValidationError):
        schemas.OfferingAccessDTO(teaching=True, learning=False, configured_permissions=[], available_actions=[], role_scope="offering", writes_available=True)
    assert schemas.CapabilityDTO.model_fields["writes_available"].default is False
    assert schemas.OfferingAccessDTO.model_fields["writes_available"].default is False


@sync_asgi
@pytest.mark.parametrize("offering_id", ["xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", "bad%00id", "%20o1"])
@pytest.mark.parametrize("suffix", ["roster", "roles"])
async def test_signed_management_get_path_ids_are_uniformly_hidden(dbcase, offering_id, suffix):
    app, _ = app_for(dbcase)
    response = await request(app, "GET", f"/api/teaching/offerings/{offering_id}/{suffix}")
    assert response.status_code == 404
    assert response.json() == {"code": 404, "message": "not_found", "data": None}
    assert response.headers["cache-control"] == "no-store"
    assert counts(dbcase[0], dbcase[3]) == (0, 0)
