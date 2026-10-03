"""Task4 ordinary synthetic lifecycle tests; no vendor-lock/readiness claim."""
import importlib
from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import event, update

from tests.test_teaching_authorization import dbcase, NOW, snapshot
from tests.test_teaching_receipts import writes_case, counts


def feature(name):
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        pytest.fail(f"Task4 feature absent: {name}: {exc}")


def error(call, reason=None, status=None):
    with pytest.raises(HTTPException) as caught:
        call()
    if reason:
        assert caught.value.detail == reason
    if status:
        assert caught.value.status_code == status


def course_command(**values):
    return {"title": "  New course  ", "timezone": "UTC", **values}


def test_source_course_creation_draft_offering_bootstrap_and_original_replay(writes_case):
    db, _, t, m, a = writes_case
    courses = feature("app.services.teaching.courses")
    first = courses.create_course(db, "owner", course_command(description="  line\ntext  "), "create-course:123")
    db.commit()
    row = db.get(m.Course, first.result["course_id"])
    assert (row.title, row.description, row.source_teacher_id, row.institution_id, row.revision) == ("New course", "  line\ntext  ", "owner", "school", 1)
    before_enrollments = db.query(m.Enrollment).count()
    offering = courses.create_offering(db, "owner", row.id, {"title": " Cohort ", "term": " Fall "}, "create-offering:123")
    db.commit()
    shell = db.get(m.Offering, offering.result["offering_id"])
    role = db.query(m.TeachingRole).filter_by(offering_id=shell.id).one()
    assert (shell.state, shell.revision, shell.roster_revision, shell.timezone) == ("draft", 1, 0, "UTC")
    assert (role.subject_id, role.granted_account_role, role.status, role.revision, role.scope) == ("owner", "teacher", "active", 1, "offering")
    assert role.permissions == sorted(p.value for p in t.Permission)
    audit = db.query(m.AccessEvent).filter_by(receipt_id=offering.receipt.id).one().effect_metadata["bootstrap_role"]
    for field in ("id", "subject_id", "granted_account_role", "label", "permissions", "scope", "status", "revision", "effective_from", "effective_until", "revoked_at", "source_policy_digest"):
        assert field in audit
    assert audit["id"] == role.id and audit["revision"] == 1 and audit["granted_account_role"] == "teacher"
    assert audit["effective_from"] == NOW.isoformat(timespec="microseconds").replace("+00:00", "Z")
    replay = courses.create_offering(db, "owner", row.id, {"title": "Cohort", "term": "Fall"}, "create-offering:123")
    assert replay.replayed and replay.receipt.id == offering.receipt.id and replay.result == offering.result
    assert db.query(m.TeachingRole).filter_by(offering_id=shell.id).count() == 1
    assert db.query(m.Enrollment).count() == before_enrollments and db.get(a.UserAccount, "owner").role == "teacher"
    assert counts(db, m) == (2, 2)


@pytest.mark.parametrize("actor,method", [("learner", "create"), ("other", "update"), ("other", "offering")])
def test_course_writes_require_current_source_owner(writes_case, actor, method):
    db, _, _, m, _ = writes_case
    c = feature("app.services.teaching.courses")
    operation = lambda: c.create_course(db, actor, course_command(), "denied-course:123") if method == "create" else c.update_course(db, actor, "c1", {"expected_revision": 1, "title": "Attempt"}, "denied-course:123") if method == "update" else c.create_offering(db, actor, "c1", {"title": "Attempt", "term": "Fall"}, "denied-course:123")
    error(operation, status=403 if method == "create" else 404)
    assert counts(db, m) == (0, 0)


def test_creation_missing_source_mapping_denied_but_empty_trusted_mapping_valid(writes_case):
    db, _, _, m, _ = writes_case
    c = feature("app.services.teaching.courses")
    db.info["teaching_policy_provider"] = lambda: snapshot(roster={})
    error(lambda: c.create_course(db, "owner", course_command(), "missing-source:123"), status=403)
    db.info["teaching_policy_provider"] = lambda: snapshot(roster={"owner": []})
    assert c.create_course(db, "owner", course_command(), "empty-source:123").result["revision"] == 1
    assert counts(db, m) == (1, 1)


@pytest.mark.parametrize("start,end", [("draft", "active"), ("draft", "archived"), ("active", "archived"), ("archived", "draft")])
def test_all_allowed_lifecycle_edges_preserve_relationships_and_replay(writes_case, start, end):
    db, _, _, m, _ = writes_case
    c = feature("app.services.teaching.courses")
    db.execute(update(m.Offering).where(m.Offering.id == "o1").values(state=start)); db.commit()
    before = (db.query(m.TeachingRole).count(), db.query(m.Enrollment).count())
    command = {"expected_revision": 1, "target_state": end, "reason": "  term change  "}
    first = c.transition_offering(db, "owner", "o1", command, "transition:123"); db.commit()
    row = db.get(m.Offering, "o1")
    assert first.result == {"offering_id": "o1", "revision": 2, "state": end}
    assert (row.state, row.revision) == (end, 2)
    assert (row.archived_at is not None) == (end == "archived")
    assert c.transition_offering(db, "owner", "o1", command, "transition:123").replayed
    assert before == (db.query(m.TeachingRole).count(), db.query(m.Enrollment).count()) and counts(db, m) == (1, 1)


@pytest.mark.parametrize("start,end", [("active", "draft"), ("archived", "active"), ("draft", "draft"), ("active", "active"), ("archived", "archived")])
def test_forbidden_lifecycle_edges_reject_without_receipts(writes_case, start, end):
    db, _, _, m, _ = writes_case
    c = feature("app.services.teaching.courses")
    db.execute(update(m.Offering).where(m.Offering.id == "o1").values(state=start)); db.commit()
    error(lambda: c.transition_offering(db, "owner", "o1", {"expected_revision": 1, "target_state": end, "reason": "No shortcut"}, "forbidden:123"), "lifecycle_conflict", 409)
    assert counts(db, m) == (0, 0)


def test_metadata_revision_archive_restriction_and_original_replay(writes_case):
    db, _, _, m, _ = writes_case
    c = feature("app.services.teaching.courses")
    first = c.update_offering(db, "owner", "o1", {"expected_revision": 1, "title": "Updated", "timezone": "Asia/Shanghai"}, "update-shell:123"); db.commit()
    error(lambda: c.update_offering(db, "owner", "o1", {"expected_revision": 1, "term": "New"}, "stale-shell:123"), "revision_conflict", 409)
    c.transition_offering(db, "owner", "o1", {"expected_revision": 2, "target_state": "archived", "reason": "Close"}, "archive-shell:123"); db.commit()
    assert c.update_offering(db, "owner", "o1", {"expected_revision": 1, "title": "Updated", "timezone": "Asia/Shanghai"}, "update-shell:123").receipt.id == first.receipt.id
    error(lambda: c.update_offering(db, "owner", "o1", {"expected_revision": 3, "title": "After archive"}, "archived-edit:123"), "lifecycle_conflict", 409)
    assert counts(db, m) == (2, 2)


def test_course_metadata_update_owner_immutable_and_service_never_commits(writes_case, monkeypatch):
    db, _, _, m, _ = writes_case
    c = feature("app.services.teaching.courses")
    monkeypatch.setattr(db, "commit", lambda: pytest.fail("service committed"))
    result = c.update_course(db, "owner", "c1", {"expected_revision": 1, "code": " NEW ", "description": "  preserved  "}, "update-course:123")
    assert result.result == {"course_id": "c1", "revision": 2}
    row = db.get(m.Course, "c1")
    assert (row.source_teacher_id, row.code, row.description) == ("owner", "NEW", "  preserved  ")
    db.rollback()
    assert counts(db, m) == (0, 0) and db.get(m.Course, "c1").revision == 1


def test_expired_manager_denies_new_write_and_original_receipt_recovery(writes_case, monkeypatch):
    db, w, _, m, _ = writes_case
    c = feature("app.services.teaching.courses")
    first = c.update_offering(db, "owner", "o1", {"expected_revision": 1, "title": "Accepted"}, "manager-edit:123"); db.commit()
    db.execute(update(m.TeachingRole).where(m.TeachingRole.id == "r-owner").values(effective_until=NOW+timedelta(seconds=1))); db.commit()
    monkeypatch.setattr(w, "_server_clock", lambda session: NOW+timedelta(seconds=1))
    error(lambda: c.update_offering(db, "owner", "o1", {"expected_revision": 1, "title": "Accepted"}, "manager-edit:123"), status=403)
    error(lambda: w.get_receipt(db, "owner", first.receipt.id), "not_found", 404)


def test_offering_bootstrap_flush_failure_is_atomic(writes_case):
    db, _, _, m, _ = writes_case
    c = feature("app.services.teaching.courses")
    before = db.query(m.Offering).count(), db.query(m.TeachingRole).count()
    def fail(mapper, connection, target):
        raise ValueError("synthetic bootstrap failure")
    event.listen(m.TeachingRole, "before_insert", fail)
    try:
        with pytest.raises(ValueError):
            c.create_offering(db, "owner", "c1", {"title": "Atomic", "term": "Fall"}, "atomic-offering:123")
    finally:
        event.remove(m.TeachingRole, "before_insert", fail)
    assert before == (db.query(m.Offering).count(), db.query(m.TeachingRole).count()) and counts(db, m) == (0, 0)


@pytest.mark.parametrize("operation", ["course_update", "offering_create"])
@pytest.mark.parametrize("actor,expected", [("other", 404), ("learner", 403), ("assistant", 403)])
def test_course_write_denials_distinguish_final_visible_shell_from_hidden_root(writes_case, operation, actor, expected):
    db, _, _, m, _ = writes_case
    c = feature("app.services.teaching.courses")
    def attempt(course_id):
        if operation == "course_update":
            return c.update_course(db, actor, course_id, {"expected_revision": 1, "title": "Denied"}, "course-visibility:123")
        return c.create_offering(db, actor, course_id, {"title": "Denied", "term": "Fall"}, "course-visibility:123")
    error(lambda: attempt("c1"), "not_found" if expected == 404 else "permission_denied", expected)
    error(lambda: attempt("missing"), "not_found", 404)
    assert counts(db, m) == (0, 0)


@pytest.mark.parametrize("point,expected", [("effective", 403), ("expired", 404), ("future", 404), ("future_started", 403)])
def test_course_visibility_uses_final_clock_for_actor_relationships(writes_case, monkeypatch, point, expected):
    db, w, _, m, _ = writes_case
    c = feature("app.services.teaching.courses")
    # co has a role but no independent enrollment. Include its role candidate
    # even when its interval starts after the fixture's initial time.
    start = NOW+timedelta(seconds=2) if point in {"future", "future_started"} else NOW-timedelta(days=1)
    db.execute(update(m.TeachingRole).where(m.TeachingRole.id == "r-co").values(effective_from=start, effective_until=NOW+timedelta(seconds=3) if point in {"future", "future_started"} else NOW+timedelta(seconds=1))); db.commit()
    monkeypatch.setattr(w, "_server_clock", lambda session: NOW+timedelta(seconds=1) if point == "expired" else NOW+timedelta(seconds=2) if point == "future_started" else NOW)
    error(lambda: c.update_course(db, "co", "c1", {"expected_revision": 1, "title": "Denied"}, "course-final-time:123"), "not_found" if expected == 404 else "permission_denied", expected)
    assert counts(db, m) == (0, 0)


def test_course_visibility_accepts_any_current_same_course_candidate_only(writes_case):
    db, _, _, m, _ = writes_case
    c = feature("app.services.teaching.courses")
    # The first role candidate is expired; a later learner candidate in this
    # same course still makes the course shell visible.
    db.execute(update(m.TeachingRole).where(m.TeachingRole.id == "r-co").values(effective_until=NOW))
    db.add(m.Offering(id="z-visible", institution_id="school", course_id="c1", title="Visible cohort", term="Fall", timezone="UTC", state="active", revision=1, roster_revision=0, created_at=NOW, updated_at=NOW)); db.flush()
    db.add(m.Enrollment(id="e-co-visible", institution_id="school", offering_id="z-visible", student_id="co", status="active", effective_from=NOW-timedelta(days=1), revision=1, source_kind="deployment_roster", source_teacher_id="owner", source_policy_digest="a"*64, created_at=NOW, updated_at=NOW)); db.commit()
    db.info["teaching_policy_provider"] = lambda: snapshot(roster={"owner": ["co", "learner"], "co": ["learner"]})
    error(lambda: c.update_course(db, "co", "c1", {"expected_revision": 1, "title": "Denied"}, "any-visible:123"), "permission_denied", 403)
    # Visibility in c1 cannot broaden c2 or disclose it.
    error(lambda: c.update_course(db, "co", "c2", {"expected_revision": 1, "title": "Denied"}, "other-course:123"), "not_found", 404)
    assert counts(db, m) == (0, 0)
