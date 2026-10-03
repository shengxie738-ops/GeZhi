"""Task4 bounded local-role grants/revocations, synthetic accounts only."""
from datetime import timedelta, timezone

import pytest
from sqlalchemy import delete, update

from tests.test_teaching_authorization import dbcase, NOW, snapshot, offering_scope
from tests.test_teaching_receipts import writes_case, counts
from tests.test_teaching_courses import feature, error


def command(**values):
    return {"expected_role_revision": 1, "status": "active", "label": "assistant", "permissions": ["AUTHOR"], "scope": "assigned", "effective_from": None, "effective_until": None, "reason": " Bounded grant ", **values}


def test_explicit_student_assistant_grant_keeps_account_role_and_stable_revision(writes_case):
    db, _, _, m, a = writes_case
    roles = feature("app.services.teaching.roles")
    first = roles.set_role(db, "owner", "o1", "assistant", command(), "assistant-grant:123"); db.commit()
    row = db.get(m.TeachingRole, "r-assistant")
    assert first.result == {"role_id": "r-assistant", "subject_id": "assistant", "revision": 2, "status": "active"}
    assert (row.id, row.revision, row.granted_account_role, row.label) == ("r-assistant", 2, "student", "assistant")
    assert db.get(a.UserAccount, "assistant").role == "student"
    audit = db.query(m.AccessEvent).filter_by(receipt_id=first.receipt.id).one().effect_metadata
    assert audit["before"]["granted_account_role"] == audit["after"]["granted_account_role"] == "student"
    assert audit["before"]["revision"] == 1 and audit["after"]["revision"] == 2
    assert roles.set_role(db, "owner", "o1", "assistant", command(), "assistant-grant:123").receipt.id == first.receipt.id
    assert counts(db, m) == (1, 1)


def test_new_role_creation_zero_revision_and_actor_not_personally_reviewer(writes_case):
    db, _, t, m, _ = writes_case
    roles = feature("app.services.teaching.roles")
    db.info["teaching_policy_provider"] = lambda: snapshot(delegation={"owner": {"co": {"account_role": "teacher", "permissions": ["ROLES_MANAGE"], "scope": "offering"}, "learner": {"account_role": "student", "permissions": ["REVIEW"], "scope": "assigned"}}})
    db.execute(update(m.TeachingRole).where(m.TeachingRole.id == "r-co").values(permissions=["ROLES_MANAGE"])); db.commit()
    accepted = roles.set_role(db, "co", "o1", "learner", command(expected_role_revision=0, permissions=["REVIEW"]), "new-reviewer:123")
    row = db.get(m.TeachingRole, accepted.result["role_id"])
    assert row.revision == 1 and row.subject_id == "learner" and row.granted_account_role == "student"
    audit = db.query(m.AccessEvent).filter_by(receipt_id=accepted.receipt.id).one().effect_metadata
    assert audit["before"] is None and audit["after"]["revision"] == 1
    access = feature("app.services.teaching.access")
    error(lambda: access.authorize_action(db, "co", t.TeachingAction.REVIEW, offering_scope(t)), status=403)


@pytest.mark.parametrize("changes", [{"permissions": ["PUBLISH"]}, {"scope": "offering"}, {"label": "teacher"}])
def test_target_trusted_ceiling_violations_reject_atomically(writes_case, changes):
    db, _, _, m, _ = writes_case
    roles = feature("app.services.teaching.roles")
    error(lambda: roles.set_role(db, "owner", "o1", "assistant", command(**changes), "exceeds-ceiling:123"), "permission_denied", 403)
    assert counts(db, m) == (0, 0) and db.get(m.TeachingRole, "r-assistant").revision == 1


@pytest.mark.parametrize("subject", ["missing", "peer", "other"])
def test_missing_unknown_or_out_of_source_delegation_fails_closed(writes_case, subject):
    db, _, _, m, _ = writes_case
    roles = feature("app.services.teaching.roles")
    error(lambda: roles.set_role(db, "owner", "o1", subject, command(expected_role_revision=0), "no-delegation:123"), status=403)
    assert counts(db, m) == (0, 0)


def test_explicit_binding_revision_required_after_teacher_demotion_policy_replacement(writes_case):
    db, w, t, m, a = writes_case
    roles = feature("app.services.teaching.roles")
    # First establish a co-teacher-local receipt while its current teacher binding is valid.
    first = roles.set_role(db, "co", "o1", "assistant", command(), "co-grant:123"); db.commit()
    db.execute(update(a.UserAccount).where(a.UserAccount.username == "co").values(role="student"))
    db.add(m.Enrollment(id="e-co", institution_id="school", offering_id="o1", student_id="co", status="active", effective_from=NOW-timedelta(days=1), revision=1, source_kind="deployment_roster", source_teacher_id="owner", source_policy_digest="a"*64, created_at=NOW, updated_at=NOW)); db.commit()
    db.info["teaching_policy_provider"] = lambda: snapshot(roster={"owner": ["co", "learner", "assistant"]}, delegation={"owner": {"co": {"account_role": "student", "permissions": ["ROLES_MANAGE", "ROSTER_MANAGE", "REVIEW"], "scope": "offering"}, "assistant": {"account_role": "student", "permissions": ["AUTHOR"], "scope": "assigned"}}})
    error(lambda: w.get_receipt(db, "co", first.receipt.id), "not_found", 404)
    access = feature("app.services.teaching.access")
    error(lambda: access.authorize_action(db, "co", t.TeachingAction.ROLES_MANAGE, offering_scope(t)), status=403)
    assert db.get(m.TeachingRole, "r-co").granted_account_role == "teacher"
    assert access.authorize_action(db, "co", t.TeachingAction.READ_ENROLLMENT, offering_scope(t)).learning
    rebound = roles.set_role(db, "owner", "o1", "co", command(permissions=["ROLES_MANAGE"], scope="offering"), "rebind-co:123"); db.commit()
    assert rebound.result["revision"] == 2 and db.get(m.TeachingRole, "r-co").granted_account_role == "student"
    assert access.authorize_action(db, "co", t.TeachingAction.ROLES_MANAGE, offering_scope(t)).role_revision == 2
    audit = db.query(m.AccessEvent).filter_by(receipt_id=rebound.receipt.id).one().effect_metadata
    assert (audit["before"]["granted_account_role"], audit["after"]["granted_account_role"]) == ("teacher", "student")


@pytest.mark.parametrize("change", ["deleted", "demoted", "out_of_ceiling"])
def test_revocation_cleanup_preserves_interval_binding_and_id_even_on_archive(writes_case, change):
    db, _, _, m, a = writes_case
    roles = feature("app.services.teaching.roles")
    old = db.get(m.TeachingRole, "r-co")
    interval = old.effective_from, old.effective_until
    if change == "deleted":
        db.execute(delete(a.UserAccount).where(a.UserAccount.username == "co"))
    elif change == "demoted":
        db.execute(update(a.UserAccount).where(a.UserAccount.username == "co").values(role="student"))
    else:
        db.info["teaching_policy_provider"] = lambda: snapshot(delegation={})
    db.execute(update(m.Offering).where(m.Offering.id == "o1").values(state="archived")); db.commit()
    accepted = roles.set_role(db, "owner", "o1", "co", command(status="revoked", permissions=[], scope="offering", effective_from=NOW+timedelta(days=1), effective_until=NOW+timedelta(days=2)), "cleanup-role:123"); db.commit()
    row = db.get(m.TeachingRole, "r-co")
    assert accepted.result["role_id"] == "r-co" and row.revision == 2 and row.status == "revoked"
    assert (row.effective_from, row.effective_until) == interval and row.granted_account_role == "teacher"
    assert row.permissions == [] and row.revoked_at.replace(tzinfo=timezone.utc) == NOW
    assert counts(db, m) == (1, 1)


def test_role_interval_update_and_regrant_use_same_id_with_exact_revision(writes_case):
    db, _, _, m, _ = writes_case
    roles = feature("app.services.teaching.roles")
    end = NOW+timedelta(days=1)
    roles.set_role(db, "owner", "o1", "assistant", command(effective_from=NOW, effective_until=end), "role-window:123"); db.commit()
    error(lambda: roles.set_role(db, "owner", "o1", "assistant", command(), "stale-role:123"), "revision_conflict", 409)
    roles.set_role(db, "owner", "o1", "assistant", command(expected_role_revision=2, status="revoked", permissions=[]), "revoke-role:123"); db.commit()
    row = db.get(m.TeachingRole, "r-assistant")
    assert row.revision == 3 and row.effective_until.replace(tzinfo=timezone.utc) == end
    roles.set_role(db, "owner", "o1", "assistant", command(expected_role_revision=3), "regrant-role:123"); db.commit()
    assert row.revision == 4 and row.status == "active" and row.revoked_at is None and row.effective_until is None
    assert counts(db, m) == (3, 3)


@pytest.mark.parametrize("offering", ["draft", "archived"])
def test_role_revision_is_offering_local_and_archived_new_grants_denied(writes_case, offering):
    db, _, _, m, _ = writes_case
    roles = feature("app.services.teaching.roles")
    # Give the owner a synthetic management row in this offering, then verify the
    # assistant's role from o1 is not reused or moved across offerings.
    db.add(m.TeachingRole(id="local-owner", institution_id="school", offering_id=offering, subject_id="owner", granted_account_role="teacher", label="teacher", permissions=["ROLES_MANAGE"], scope="offering", status="active", effective_from=NOW-timedelta(days=1), revision=1, source_policy_digest="a"*64, created_at=NOW, updated_at=NOW)); db.commit()
    if offering == "archived":
        error(lambda: roles.set_role(db, "owner", offering, "assistant", command(expected_role_revision=0), "archive-grant:123"), "lifecycle_conflict", 409)
    else:
        error(lambda: roles.set_role(db, "owner", offering, "assistant", command(), "foreign-role:123"), "revision_conflict", 409)
        accepted = roles.set_role(db, "owner", offering, "assistant", command(expected_role_revision=0), "local-role:123")
        assert accepted.result["role_id"] != "r-assistant" and accepted.result["revision"] == 1
    assert db.get(m.TeachingRole, "r-assistant").revision == 1


def test_self_revocation_removes_mutations_and_teaching_receipt_without_owner_bypass(writes_case):
    db, w, t, m, _ = writes_case
    roles = feature("app.services.teaching.roles")
    first = roles.set_role(db, "owner", "o1", "owner", command(status="revoked", permissions=[], label="teacher", scope="offering"), "self-revoke:123"); db.commit()
    error(lambda: roles.set_role(db, "owner", "o1", "assistant", command(), "after-revoke:123"), status=403)
    error(lambda: w.get_receipt(db, "owner", first.receipt.id), "not_found", 404)
    # Fixed owner still has only the accepted shell-read behavior; it is not a
    # permanent role-management or recovery grant.
    access = feature("app.services.teaching.access")
    assert access.authorize_action(db, "owner", t.TeachingAction.READ_OFFERING, offering_scope(t)).teaching
    assert counts(db, m) == (1, 1)


@pytest.mark.parametrize("point", ["past", "exact_final"])
def test_effective_grant_window_closed_at_final_clock(writes_case, point):
    db, _, _, m, _ = writes_case
    roles = feature("app.services.teaching.roles")
    end = NOW-timedelta(microseconds=1) if point == "past" else NOW
    error(lambda: roles.set_role(db, "owner", "o1", "assistant", command(effective_from=NOW-timedelta(days=1), effective_until=end), "closed-window:123"), "effective_window_closed", 409)
    assert counts(db, m) == (0, 0)
