"""Scoped teacher/student closure and atomicity; actual HTTP + synthetic SQLite."""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.api.endpoints import analytics, dashboard, homework
from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token
from app.models.domain_record import DomainRecord
from app.models.student_profile import StudentProfile
from app.models.user_account import UserAccount
from app.repositories.json_store import JsonStore


@pytest.fixture
def world(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + str(tmp_path / "synthetic.db"))
    for model in (UserAccount, StudentProfile, DomainRecord):
        model.__table__.create(engine)
    sessions = sessionmaker(bind=engine, autoflush=False)
    with sessions() as db:
        for username, role in (("teacher", "teacher"), ("other-teacher", "teacher"),
                               ("20260001", "student"), ("20260002", "student"),
                               ("20269999", "student")):
            db.add(UserAccount(username=username, role=role, password_hash=""))
        db.commit()
    monkeypatch.setattr(settings, "TEACHER_STUDENT_ASSIGNMENTS", json.dumps({
        "teacher": ["20260001", "20260002"], "other-teacher": ["20269999"]}))
    monkeypatch.setattr(homework, "publish_learning_activity_safely", AsyncMock())
    app = FastAPI()
    for module in (analytics, dashboard, homework):
        app.include_router(module.router)

    def isolated_db():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = isolated_db
    yield app, sessions
    engine.dispose()


def headers(user="teacher", role="teacher"):
    return {"Authorization": "Bearer " + create_access_token(user, role)}


def request(app, method, path, *, user="teacher", role="teacher", **kwargs):
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                     base_url="http://synthetic.test") as client:
            return await client.request(method, path, headers=headers(user, role), **kwargs)
    return asyncio.run(run())


def saved(sessions, module, kind, key):
    with sessions() as db:
        return JsonStore(db).get_payload(module, kind, key)


def records(sessions, module, kind):
    with sessions() as db:
        return JsonStore(db).list_payloads(module, kind)


def dispatch(app, recipients=None):
    return request(app, "POST", "/analytics/interactions", json={
        "type": "nudge", "title": "Synthetic follow-up",
        "target": {"studentIds": recipients or ["20260001", "20260002"]},
        "payload": {"desc": "Please review the synthetic task"}})


def fail_write(monkeypatch, kind, at=1):
    original = JsonStore.upsert
    count = 0

    def failing(self, module, record_type, *args, **kwargs):
        nonlocal count
        if record_type == kind:
            count += 1
            if count == at:
                raise RuntimeError("intentional isolated second-write failure")
        return original(self, module, record_type, *args, **kwargs)

    monkeypatch.setattr(JsonStore, "upsert", failing)


def test_dispatch_rolls_back_interaction_and_first_nudge_on_second_nudge_failure(world, monkeypatch):
    app, sessions = world
    fail_write(monkeypatch, "nudge", at=2)
    response = dispatch(app)
    assert response.status_code == 500
    assert records(sessions, "analytics", "interaction") == []
    assert records(sessions, "analytics", "nudge") == []


def test_reminder_rolls_back_patch_if_notification_write_fails(world, monkeypatch):
    app, sessions = world
    iid = dispatch(app).json()["data"]["record"]["id"]
    before = saved(sessions, "analytics", "interaction", iid)
    fail_write(monkeypatch, "notification")
    response = request(app, "PATCH", f"/analytics/interactions/{iid}", json={"unreadCount": 8})
    assert response.status_code == 500
    assert saved(sessions, "analytics", "interaction", iid) == before
    assert records(sessions, "dashboard", "notification") == []


def test_completion_rolls_back_counter_and_retry_counts_exactly_once(world, monkeypatch):
    app, sessions = world
    iid = dispatch(app).json()["data"]["record"]["id"]
    before = saved(sessions, "analytics", "interaction", iid)
    with monkeypatch.context() as patch:
        fail_write(patch, "interaction_completion")
        failed = request(app, "POST", f"/analytics/interactions/{iid}/complete",
                         user="20260001", role="student", json={})
        assert failed.status_code == 500
    assert saved(sessions, "analytics", "interaction", iid) == before
    assert records(sessions, "analytics", "interaction_completion") == []
    first = request(app, "POST", f"/analytics/interactions/{iid}/complete",
                    user="20260001", role="student", json={})
    repeat = request(app, "POST", f"/analytics/interactions/{iid}/complete",
                     user="20260001", role="student", json={})
    assert first.status_code == repeat.status_code == 200
    assert repeat.json()["data"]["alreadyCompleted"] is True
    assert saved(sessions, "analytics", "interaction", iid)["completedCount"] == 1
    assert len(records(sessions, "analytics", "interaction_completion")) == 1


def test_completion_reads_parent_and_receipt_under_atomic_row_lock(world):
    app, sessions = world
    iid = dispatch(app).json()["data"]["record"]["id"]
    observations = []

    def observe(state):
        text = str(state.statement)
        # Observe scoped record-key reads, not db.refresh primary-key reads.
        if state.is_select and "WHERE domain_records.module" in text:
            observations.append((bool(state.session.info.get("atomic_json_store")),
                                 state.statement._for_update_arg is not None))

    event.listen(sessions.class_, "do_orm_execute", observe)
    try:
        result = request(app, "POST", f"/analytics/interactions/{iid}/complete",
                         user="20260001", role="student", json={})
    finally:
        event.remove(sessions.class_, "do_orm_execute", observe)
    assert result.status_code == 200
    assert observations
    assert all(atomic and locked for atomic, locked in observations)


def test_dispatch_complete_teacher_projection_and_student_read_agree(world):
    app, sessions = world
    iid = dispatch(app, ["20260001"]).json()["data"]["record"]["id"]
    mine = request(app, "GET", "/dashboard/student/20260001/interactions", user="20260001", role="student")
    assert mine.json()["data"]["interactions"][0]["id"] == iid
    assert len(mine.json()["data"]["nudges"]) == 1
    peer = request(app, "GET", "/dashboard/student/20260002/interactions", user="20260002", role="student")
    assert peer.json()["data"]["interactions"] == []
    denied = request(app, "POST", f"/analytics/interactions/{iid}/complete", user="20260002", role="student", json={})
    assert denied.status_code == 403
    assert request(app, "POST", f"/analytics/interactions/{iid}/complete", user="20260001", role="student", json={}).status_code == 200
    teacher = request(app, "GET", "/analytics/interactions").json()["data"]
    item = next(item for item in teacher if item["id"] == iid)
    assert item["completedCount"] == item["completionRecordCount"] == 1
    assert item["recipientCount"] == 1 and item["completionRate"] == 100
    mine = request(app, "GET", "/dashboard/student/20260001/interactions", user="20260001", role="student")
    assert mine.json()["data"]["interactions"][0]["completedCount"] == 1


def test_reminder_is_visible_only_to_recipient_and_foreign_teacher_cannot_write(world):
    app, sessions = world
    iid = dispatch(app, ["20260001"]).json()["data"]["record"]["id"]
    assert request(app, "PATCH", f"/analytics/interactions/{iid}",
                   user="other-teacher", json={"unreadCount": 1}).status_code == 404
    assert request(app, "PATCH", f"/analytics/interactions/{iid}",
                   user="20260001", role="teacher", json={"unreadCount": 1}).status_code == 403
    response = request(app, "PATCH", f"/analytics/interactions/{iid}",
                       json={"unreadCount": 1, "message": "Synthetic reminder"})
    assert response.status_code == 200
    for student, expected in (("20260001", 1), ("20260002", 0), ("20269999", 0)):
        view = request(app, "GET", f"/dashboard/student/{student}", user=student, role="student")
        assert view.status_code == 200
        assert len(view.json()["data"]["notifications"]) == expected
    assert len(records(sessions, "dashboard", "notification")) == 1


def test_completion_of_two_recipients_is_bounded_and_duplicate_is_noop(world):
    app, sessions = world
    iid = dispatch(app).json()["data"]["record"]["id"]
    for student in ("20260001", "20260002", "20260001", "20260002"):
        assert request(app, "POST", f"/analytics/interactions/{iid}/complete",
                       user=student, role="student", json={}).status_code == 200
    row = saved(sessions, "analytics", "interaction", iid)
    assert row["completedCount"] == 2 and row["pendingCount"] == row["unreadCount"] == 0
    assert row["completionRate"] == 100 and row["status"] == "completed"
    assert len(records(sessions, "analytics", "interaction_completion")) == 2


def test_final_commit_failure_rolls_back_entire_dispatch(world, monkeypatch):
    app, sessions = world
    original = sessions.class_.commit

    def fail_atomic_commit(db):
        if db.info.get("atomic_json_store"):
            raise RuntimeError("intentional commit failure before durable commit")
        return original(db)

    monkeypatch.setattr(sessions.class_, "commit", fail_atomic_commit)
    response = dispatch(app)
    assert response.status_code == 500
    assert records(sessions, "analytics", "interaction") == []
    assert records(sessions, "analytics", "nudge") == []


def test_actual_homework_publish_submit_grade_zero_and_fresh_student_reads(world):
    app, sessions = world
    created = request(app, "POST", "/homework", json={
        "id": "synthetic-hw", "title": "Synthetic homework", "studentIds": ["20260001"],
        "deadline": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        "questions": [{"id": "q1", "type": "choice", "title": "Q", "correctAnswer": "secret-answer"}]})
    assert created.status_code == 200
    student_kwargs = dict(user="20260001", role="student")
    detail = request(app, "GET", "/homework/synthetic-hw", **student_kwargs)
    assert detail.status_code == 200 and "correctAnswer" not in detail.text and "secret-answer" not in detail.text
    assert request(app, "GET", "/homework/synthetic-hw", user="20260002", role="student").status_code == 403
    assert request(app, "GET", "/homework/student/list", user="20260002", role="student").json()["data"] == []
    submitted = request(app, "POST", "/homework/synthetic-hw/submit", json={
        "studentId": "20260002", "answers": {"q1": "A"}}, **student_kwargs)
    assert submitted.status_code == 200
    attempt_id = submitted.json()["data"]["attemptId"]
    assert attempt_id == "synthetic-hw:20260001"
    row = saved(sessions, "homework", "submission", attempt_id)
    assert row["studentId"] == "20260001" and row["answers"] == {"q1": "A"}
    for view in (request(app, "GET", "/homework/synthetic-hw", **student_kwargs).json()["data"],
                 request(app, "GET", "/homework/student/list", **student_kwargs).json()["data"][0]):
        assert view["status"] == "pending" and view["submittedAnswers"] == {"q1": "A"}
    submissions = request(app, "GET", "/homework/teacher/submissions?homeworkId=synthetic-hw")
    assert submissions.status_code == 200 and submissions.json()["data"][0]["id"] == attempt_id
    grade_path = f"/homework/attempts/{attempt_id}/grade"
    assert request(app, "POST", grade_path, json={"grade": 90}, user="other-teacher").status_code == 403
    assert request(app, "POST", grade_path, json={"grade": 90}, user="20260001", role="teacher").status_code == 403
    for bad in ("A", True, -1, 101):
        assert request(app, "POST", grade_path, json={"grade": bad}).status_code == 422
    graded = request(app, "POST", grade_path, json={"grade": 0, "comment": "Please review q1"})
    assert graded.status_code == 200
    for view in (request(app, "GET", "/homework/synthetic-hw", **student_kwargs).json()["data"],
                 request(app, "GET", "/homework/student/list", **student_kwargs).json()["data"][0]):
        assert view["status"] == "graded" and view["grade"] == 0
        assert view["teacherComment"] == "Please review q1"
    repeat = request(app, "POST", "/homework/synthetic-hw/submit", json={"answers": {"q1": "B"}}, **student_kwargs)
    assert repeat.status_code == 409
    assert saved(sessions, "homework", "submission", attempt_id)["grade"] == 0
