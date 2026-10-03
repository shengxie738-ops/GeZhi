"""Persisted positive own-scope DTOs and exact denial/projection boundaries."""
import dataclasses
import json
from datetime import timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import update

from tests.test_teaching_authorization import NOW, dbcase, deny, feature, offering_scope, snapshot


def test_positive_scoped_offerings_are_real_persisted_records(dbcase):
    db, a, t, m, _, _ = dbcase
    dto = a.list_offerings(db, "learner")
    assert {row.id for row in dto.items} == {"o1", "archived"}
    assert dto.as_of == NOW
    assert all(row.title.startswith("Persisted ") and row.access.learning for row in dto.items)
    assert not any(row.access.teaching for row in dto.items)
    assert a.list_offerings(db, "learner", feature("app.schemas.teaching").OfferingQuery(course_id="c2")).items == []
    own = a.get_offering(db, "learner", "o1")
    assert own.enrollment.id == "e-o1-learner" and own.enrollment.student_id == "learner"
    assert own.roster_revision is None  # No management projection for learners.
    deny(lambda: a.get_offering(db, "learner", "draft"), status=404)
    deny(lambda: a.get_offering(db, "learner", "other"), status=404)
    deny(lambda: a.get_offering(db, "learner", "foreign"), status=404)


def test_source_owned_zero_offering_course_and_real_visible_counts(dbcase):
    db, a, t, _, _, _ = dbcase
    own = a.list_courses(db, "owner")
    assert {row.id for row in own.items} == {"c0", "c1"}
    counts = {row.id: row.visible_offering_count for row in own.items}
    assert counts == {"c0": 0, "c1": 3}
    learner = a.list_courses(db, "learner")
    assert [(row.id, row.visible_offering_count, row.memberships) for row in learner.items] == [("c1", 2, ["learning"])]
    assert a.get_course(db, "owner", "c0").title == "Persisted c0"
    deny(lambda: a.get_course(db, "learner", "c0"), status=404)
    deny(lambda: a.get_course(db, "learner", "c2"), status=404)


def test_membership_filters_deduplicate_dual_teacher_learner_and_stable_cursor(dbcase):
    db, a, t, _, _, _ = dbcase
    schema = feature("app.schemas.teaching")
    both = a.get_offering(db, "assistant", "o1")
    assert both.access.teaching and both.access.learning
    assert a.list_offerings(db, "assistant", schema.OfferingQuery(membership="teaching")).items[0].id == "o1"
    assert len(a.list_courses(db, "assistant").items) == 1
    first = a.list_offerings(db, "owner", schema.OfferingQuery(limit=1))
    assert first.next_cursor == first.items[-1].id
    second = a.list_offerings(db, "owner", schema.OfferingQuery(limit=1, cursor=first.next_cursor))
    assert second.items[0].id > first.items[0].id
    teacher_learner = a.get_offering(db, "teacherlearner", "o1")
    assert teacher_learner.access.learning and not teacher_learner.access.teaching
    assert teacher_learner.access.configured_permissions == [] and teacher_learner.access.available_actions == []


def test_own_enrollment_cannot_select_another_subject(dbcase):
    db, a, _, _, _, _ = dbcase
    own = a.get_own_enrollment(db, "learner", "o1")
    assert own.student_id == "learner" and own.access_eligible
    deny(lambda: a.get_own_enrollment(db, "owner", "o1"), status=404)
    with pytest.raises(TypeError):
        a.get_own_enrollment(db, "learner", "o1", student_id="peer")


def test_roster_requires_independent_right_and_labels_source_revoked(dbcase):
    db, a, t, _, _, _ = dbcase
    deny(lambda: a.get_roster(db, "learner", "o1"), status=403)
    db.info["teaching_policy_provider"] = lambda: snapshot(roster={"owner": ["learner", "assistant", "teacherlearner"], "co": ["learner"]})
    roster = a.get_roster(db, "co", "o1")
    assert {row.student_id for row in roster.items} == {"learner", "assistant", "teacherlearner", "revoked"}
    assert next(row for row in roster.items if row.student_id == "revoked").source_availability == "source_revoked"
    assert next(row for row in roster.items if row.student_id == "assistant").source_availability == "available"
    text = roster.model_dump_json()
    assert all(secret not in text for secret in ["password_hash", "private", "class_name", "teacher_id", "real_name", "source_policy_digest"])


def test_roles_inspection_reports_effectiveness_not_global_profiles(dbcase):
    db, a, t, m, _, _ = dbcase
    deny(lambda: a.get_roles(db, "assistant", "o1"), status=403)
    db.execute(update(m.TeachingRole).where(m.TeachingRole.subject_id == "assistant").values(status="revoked"))
    roles = a.get_roles(db, "co", "o1")
    assert len(roles.items) == 3
    assistant = next(row for row in roles.items if row.subject_id == "assistant")
    assert assistant.configured_permissions == [t.Permission.AUTHOR] and assistant.effective_permissions == []
    assert assistant.effective_scope is None and assistant.reason == "role_inactive"
    assert "password_hash" not in roles.model_dump_json()


def test_assessment_flags_or_permissions_never_look_like_installed_endpoints(dbcase):
    db, a, t, _, _, _ = dbcase
    db.info["teaching_policy_provider"] = lambda: dataclasses.replace(snapshot(), assignments_enabled=True, feedback_enabled=True, revisions_enabled=True)
    dto = a.get_offering(db, "owner", "o1")
    assert t.Permission.REVIEW in dto.access.configured_permissions
    assert set(dto.access.available_actions) == {t.TeachingAction.COURSE_MANAGE, t.TeachingAction.ROSTER_MANAGE, t.TeachingAction.ROLES_MANAGE}
    capability = a.get_capabilities(db, "owner")
    assert capability.available and capability.can_create_course
    assert capability.assignments.reason == "stage_unavailable" and not capability.assignments.available
    assert not capability.feedback.available and not capability.revisions.available


def test_disabled_capability_queries_no_teaching_tables(dbcase):
    db, a, _, _, _, _ = dbcase
    db.info["teaching_policy_provider"] = lambda: snapshot(enabled=False)
    from sqlalchemy import event
    statements = []
    event.listen(db.bind, "before_cursor_execute", lambda conn, cursor, statement, parameters, context, executemany: statements.append(statement))
    cap = a.get_capabilities(db, "owner")
    assert not cap.available and cap.reason == "feature_disabled" and not cap.can_create_course
    assert not any("teaching_" in sql.lower() for sql in statements)
    deny(lambda: a.list_courses(db, "owner"), code="feature_disabled", status=503)


def test_strict_dtos_query_bounds_and_utc_serialization(dbcase):
    db, a, _, _, _, _ = dbcase
    schema = feature("app.schemas.teaching")
    for invalid in [{"user_id": "peer"}, {"limit": 101}, {"limit": 0}, {"membership": "admin"}, {"cursor": "a\n"}, {"limit": "5"}]:
        with pytest.raises(ValidationError):
            schema.OfferingQuery(**invalid)
    dto = a.get_offering(db, "learner", "o1")
    assert json.loads(dto.model_dump_json())["created_at"].endswith("Z")
    with pytest.raises(ValidationError):
        type(dto).model_validate({**dto.model_dump(), "password_hash": "leak"})
    with pytest.raises(ValidationError):
        dto.title = "mutated"


def test_persisted_preview_actor_scoped_full_counts_and_change_pages(dbcase):
    db, a, t, m, _, _ = dbcase
    ids = [f"student-{i:03d}" for i in range(130)]
    preview = m.RosterPreview(id="p1", institution_id="school", offering_id="o1", actor_id="owner", actor_role_id="r-owner", actor_role_revision=1, expected_roster_revision=0, offering_revision=1, mode="replace", canonical_command={}, command_hash="b"*64, source_policy_digest="a"*64, target_ids=[], add_ids=[], keep_ids=[], update_ids=[], withdraw_ids=ids, validation_issues=[], target_digest="c"*64, withdrawals_digest="d"*64, withdrawals_count=130, can_apply=True, created_at=NOW-timedelta(minutes=20), expires_at=NOW-timedelta(minutes=10))
    db.add(preview); db.commit()
    dto = a.get_roster_preview(db, "owner", "o1", "p1")
    assert dto.withdrawals_count == 130 and len(dto.withdraw_sample) <= 20
    assert dto.expired and dto.withdrawals_digest == "d"*64
    schema = feature("app.schemas.teaching")
    first = a.get_roster_preview_changes(db, "owner", "o1", "p1", schema.PreviewChangesQuery(kind="withdraw", limit=100))
    second = a.get_roster_preview_changes(db, "owner", "o1", "p1", schema.PreviewChangesQuery(kind="withdraw", limit=100, cursor=first.next_cursor))
    assert first.items+second.items == ids and second.next_cursor is None
    deny(lambda: a.get_roster_preview(db, "co", "o1", "p1"), status=404)
    deny(lambda: a.get_roster_preview(db, "owner", "other", "p1"), status=403)
    db.execute(update(m.TeachingRole).where(m.TeachingRole.subject_id == "owner").values(status="revoked"))
    deny(lambda: a.get_roster_preview(db, "owner", "o1", "p1"), status=403)


def test_course_description_preserves_authored_whitespace_and_newlines(dbcase):
    db, a, _, m, _, _ = dbcase
    description = "  First line\nSecond line\twith spacing  "
    db.execute(update(m.Course).where(m.Course.id == "c1").values(description=description))
    dto = a.get_course(db, "owner", "c1")
    assert dto.description == description
    assert json.loads(dto.model_dump_json())["description"] == description
