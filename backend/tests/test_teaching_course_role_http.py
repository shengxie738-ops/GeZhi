"""Task4 strict DTO and minimal ASGI routes, never aggregate/startup/network."""
import asyncio
from functools import wraps

import httpx
import pytest
from fastapi import Depends, FastAPI, Header
from pydantic import ValidationError
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError

from tests.test_teaching_authorization import dbcase, NOW, snapshot
from tests.test_teaching_receipts import writes_case, counts
from tests.test_teaching_courses import feature, error
from tests.test_teaching_roles import command


def sync_asgi(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))
    return run


def app_for(case):
    db = case[0]
    adapter = feature("app.api.endpoints.teaching")
    app = FastAPI()
    app.include_router(adapter.router, prefix="/api")
    async def fixture_db():
        return db
    async def fixture_account(authorization: str | None = Header(default=None), session: Session = Depends(adapter.get_teaching_db)):
        return adapter.get_teaching_account(authorization, session)
    app.dependency_overrides[adapter.get_teaching_db] = fixture_db
    app.dependency_overrides[adapter.get_teaching_account] = fixture_account
    return app, adapter


async def request(app, method, path, *, key="http-original:123", actor="owner", **kwargs):
    token = feature("app.core.security").create_access_token(actor, "teacher")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://isolated-asgi") as client:
        return await client.request(method, path, headers={"Authorization": "Bearer " + token, "Idempotency-Key": key}, **kwargs)


@sync_asgi
async def test_all_six_task4_routes_commit_and_return_strict_original_results(writes_case, monkeypatch):
    db, _, _, m, _ = writes_case
    app, _ = app_for(writes_case)
    original = db.commit
    commits = []
    def commit():
        original(); commits.append("commit")
    monkeypatch.setattr(db, "commit", commit)
    course = await request(app, "POST", "/api/teaching/courses", json={"title": "Created", "timezone": "UTC"})
    assert course.status_code == 201
    cid = course.json()["data"]["result"]["course_id"]
    offering = await request(app, "POST", f"/api/teaching/courses/{cid}/offerings", json={"title": "Draft", "term": "Fall"})
    assert offering.status_code == 201
    oid = offering.json()["data"]["result"]["offering_id"]
    update_course = await request(app, "PATCH", f"/api/teaching/courses/{cid}", key="http-course-update:123", json={"expected_revision": 1, "title": "New name"})
    update_offering = await request(app, "PATCH", f"/api/teaching/offerings/{oid}", key="http-offering-update:123", json={"expected_revision": 1, "term": "Autumn"})
    transition = await request(app, "POST", f"/api/teaching/offerings/{oid}/transitions", key="http-transition:123", json={"expected_revision": 2, "target_state": "active", "reason": "Open empty cohort"})
    role = await request(app, "PUT", f"/api/teaching/offerings/{oid}/roles/assistant", json=command(expected_role_revision=0, effective_from=NOW.isoformat().replace("+00:00", "Z")))
    for response in [course, offering, update_course, update_offering, transition, role]:
        assert response.status_code in {200, 201}, response.text
        assert response.json()["code"] == response.status_code and response.headers["cache-control"] == "no-store"
        assert not response.json()["data"]["replayed"]
        assert "password_hash" not in response.text and "phone" not in response.text and "trusted_roster" not in response.text
    assert len(commits) == 6 and counts(db, m) == (6, 6)
    assert db.query(m.Enrollment).filter_by(offering_id=oid).count() == 0
    replay = await request(app, "POST", "/api/teaching/courses", json={"title": "Created", "timezone": "UTC"})
    assert replay.status_code == 200 and replay.json()["data"]["replayed"]
    assert replay.json()["data"]["receipt"]["http_status"] == 201 and replay.json()["data"]["result"] == course.json()["data"]["result"]
    assert counts(db, m) == (6, 6)


@pytest.mark.parametrize("dto,payload", [
    ("CreateCourseCommand", {"title": "C", "timezone": "UTC", "owner_id": "other"}),
    ("CreateCourseCommand", {"title": "C", "timezone": "UTC", "institution_id": "forged"}),
    ("CreateCourseCommand", {"title": " ", "timezone": "UTC"}),
    ("CreateCourseCommand", {"title": "C", "timezone": "Not/AZone"}),
    ("CreateCourseCommand", {"title": "C\x00", "timezone": "UTC"}),
    ("UpdateCourseCommand", {"expected_revision": 1}),
    ("UpdateCourseCommand", {"expected_revision": True, "title": "C"}),
    ("UpdateOfferingCommand", {"expected_revision": 1, "title": None}),
    ("TransitionOfferingCommand", {"expected_revision": 1, "target_state": "active", "reason": " "}),
    ("SetRoleCommand", command(permissions=["UNKNOWN"])),
    ("SetRoleCommand", command(permissions=["ROLES_MANAGE"], scope="assigned")),
    ("SetRoleCommand", command(granted_account_role="teacher")),
    ("SetRoleCommand", command(account_role="teacher")),
    ("SetRoleCommand", command(effective_from="2026-10-03T12:00:00", effective_until=None)),
    ("SetRoleCommand", command(effective_from="2026-10-03T12:00:00+08:00")),
    ("SetRoleCommand", command(effective_from="2026-10-03T12:00:00Z", effective_until="2026-10-03T12:00:00Z")),
    ("SetRoleCommand", command(status="revoked", permissions=["AUTHOR"])),
])
def test_strict_command_dtos_reject_client_authority_and_invalid_values(dto, payload):
    schemas = feature("app.schemas.teaching")
    cls = getattr(schemas, dto, None)
    assert cls is not None, f"Task4 DTO missing: {dto}"
    with pytest.raises(ValidationError):
        cls.model_validate(payload)


@sync_asgi
@pytest.mark.parametrize("path,payload", [
    ("/api/teaching/courses", {"title": "C", "timezone": "UTC", "actor_id": "other"}),
    ("/api/teaching/offerings/o1/roles/assistant", command(permissions=["UNKNOWN"])),
    ("/api/teaching/offerings/o1/transitions", {"expected_revision": 1, "target_state": "active", "reason": " "}),
])
async def test_http_422_no_mutation_no_store(writes_case, path, payload):
    app, _ = app_for(writes_case)
    response = await request(app, "PUT" if "/roles/" in path else "POST", path, json=payload)
    assert response.status_code == 422 and response.json() == {"code":422, "message":"validation_error", "data":None}
    assert response.headers["cache-control"] == "no-store" and counts(writes_case[0], writes_case[3]) == (0, 0)


@sync_asgi
@pytest.mark.parametrize("committed", [False, True])
async def test_task4_commit_ambiguity_retains_original_recovery_tuple(writes_case, monkeypatch, committed):
    db, _, _, m, _ = writes_case
    app, _ = app_for(writes_case)
    original = db.commit
    def fail_commit():
        if committed:
            original()
        raise OperationalError("synthetic commit", {}, RuntimeError("private transport text"))
    monkeypatch.setattr(db, "commit", fail_commit)
    response = await request(app, "POST", "/api/teaching/courses", json={"title": "C", "timezone": "UTC"})
    assert response.status_code == 503 and response.json()["message"] == "write_outcome_unknown"
    assert response.json()["data"] == {"recovery": {"action": "course_create", "scope_type": "institution", "scope_id": "school", "key": "http-original:123"}}
    assert "private transport text" not in response.text and counts(db, m) == ((1, 1) if committed else (0, 0))


@sync_asgi
async def test_current_account_overrides_stale_token_role_for_student_denial(writes_case):
    app, _ = app_for(writes_case)
    response = await request(app, "POST", "/api/teaching/courses", actor="learner", json={"title": "C", "timezone": "UTC"})
    assert response.status_code == 403 and counts(writes_case[0], writes_case[3]) == (0, 0)


def test_unmodified_write_gate_still_refuses_task4_operation(dbcase, monkeypatch):
    db, _, _, m, _, _ = dbcase
    w = feature("app.services.teaching.writes")
    monkeypatch.setattr(w, "_require_transaction", lambda session: None)
    c = feature("app.services.teaching.courses")
    error(lambda: c.create_course(db, "owner", {"title": "C", "timezone": "UTC"}, "production-gate:123"), "write_safety_unproven", 503)
    assert counts(db, m) == (0, 0)


@pytest.mark.parametrize("boundary", ["default_off", "schema_refusal"])
def test_real_default_off_and_schema_refusal_precede_task4_mutation(dbcase, monkeypatch, boundary):
    db, access, _, m, _, readiness = dbcase
    w = feature("app.services.teaching.writes")
    monkeypatch.setattr(w, "_require_transaction", lambda session: None)
    if boundary == "default_off":
        db.info.pop("teaching_policy_provider")
    else:
        monkeypatch.setattr(access, "require_teaching_schema", readiness)
    c = feature("app.services.teaching.courses")
    error(lambda: c.create_course(db, "owner", {"title": "C", "timezone": "UTC"}, "closed-boundary:123"), "feature_disabled" if boundary == "default_off" else "teaching_schema_incompatible", 503)
    assert counts(db, m) == (0, 0)


@sync_asgi
@pytest.mark.parametrize("actor,offering,expected", [("other", "o1", 404), ("other", "missing", 404), ("learner", "o1", 403), ("assistant", "o1", 403)])
async def test_offering_write_denial_has_uniform_hidden_404_and_visible_403(writes_case, actor, offering, expected):
    app, _ = app_for(writes_case)
    response = await request(app, "PATCH", f"/api/teaching/offerings/{offering}", actor=actor, json={"expected_revision": 1, "title": "Denied"})
    assert response.status_code == expected
    assert response.json() == {"code":expected, "message":"not_found" if expected == 404 else "permission_denied", "data":None}
    assert response.headers["cache-control"] == "no-store" and counts(writes_case[0], writes_case[3]) == (0, 0)


@sync_asgi
@pytest.mark.parametrize("relationship", ["role", "enrollment"])
async def test_offering_visibility_expiring_at_final_time_is_hidden(writes_case, monkeypatch, relationship):
    from datetime import timedelta
    from sqlalchemy import update
    db, w, _, m, _ = writes_case
    subject = "co" if relationship == "role" else "learner"
    model = m.TeachingRole if relationship == "role" else m.Enrollment
    column = model.subject_id if relationship == "role" else model.student_id
    db.execute(update(model).where(column == subject).values(effective_until=NOW+timedelta(seconds=1))); db.commit()
    monkeypatch.setattr(w, "_server_clock", lambda session: NOW+timedelta(seconds=1))
    app, _ = app_for(writes_case)
    response = await request(app, "PATCH", "/api/teaching/offerings/o1", actor=subject, json={"expected_revision": 1, "title": "Denied"})
    assert response.status_code == 404 and response.json() == {"code":404, "message":"not_found", "data":None}
    assert counts(db, m) == (0, 0)
