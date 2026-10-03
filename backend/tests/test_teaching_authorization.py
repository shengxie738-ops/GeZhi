"""Task2 synthetic SQLAlchemy access decisions, never MySQL lock evidence."""
import dataclasses
import importlib
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, delete, update
from sqlalchemy.orm import Session

NOW = datetime(2026, 10, 3, 12, 0, 0, 123456, tzinfo=timezone.utc)


def feature(name):
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        pytest.fail(f"Task2 feature absent: {name}: {exc}")


def snapshot(*, roster=None, delegation=None, enabled=True, generation="g1"):
    return feature("app.services.teaching.types").TeachingPolicyInputs(
        institution_id="school", enabled=enabled, generation=generation,
        trusted_roster_json=json.dumps(roster if roster is not None else {"owner": ["learner", "assistant", "teacherlearner", "revoked"], "co": ["learner"], "other": ["peer"]}),
        trusted_delegations_json=json.dumps(delegation if delegation is not None else {"owner": {"co": {"account_role": "teacher", "permissions": ["ROSTER_MANAGE", "ROLES_MANAGE", "REVIEW"], "scope": "offering"}, "assistant": {"account_role": "student", "permissions": ["AUTHOR"], "scope": "assigned"}}}))


@pytest.fixture
def dbcase(monkeypatch):
    access = feature("app.services.teaching.access")
    types = feature("app.services.teaching.types")
    models = feature("app.models.teaching")
    accounts = feature("app.models.user_account")
    # Runtime-owner-approved synthetic logic boundary ONLY. Schema refusal below
    # calls the unpatched original; SQLite never establishes vendor readiness.
    original_readiness = access.require_teaching_schema
    monkeypatch.setattr(access, "require_teaching_schema", lambda session: None)
    monkeypatch.setattr(access, "utcnow", lambda: NOW)
    engine = create_engine("sqlite:///:memory:")
    ledger = feature("app.models.teaching_schema")
    schema = feature("app.services.teaching.schema")
    selected = [accounts.UserAccount.__table__, ledger.TeachingSchemaVersion.__table__] + [getattr(models, name).__table__ for name in ("Course", "Offering", "Enrollment", "TeachingRole", "RosterPreview", "WriteReceipt", "AccessEvent")]
    accounts.UserAccount.metadata.create_all(engine, tables=selected)
    session = Session(engine, autoflush=False)
    session.add(ledger.TeachingSchemaVersion(component="b1", version=1, contract_hash=schema.B1_CONTRACT_HASH, completed_at=NOW))
    for name, role in [("owner", "teacher"), ("other", "teacher"), ("co", "teacher"), ("teacherlearner", "teacher"), ("learner", "student"), ("assistant", "student"), ("peer", "student"), ("revoked", "student")]:
        session.add(accounts.UserAccount(username=name, role=role, password_hash="synthetic-only", phone="private", class_name="forged", teacher_id="owner", student_id="learner"))
    for id_, owner, institution in [("c1", "owner", "school"), ("c2", "other", "school"), ("c0", "owner", "school"), ("foreign", "owner", "foreign")]:
        session.add(models.Course(id=id_, institution_id=institution, source_teacher_id=owner, title=f"Persisted {id_}", code="C", description="real synthetic description", timezone="UTC", revision=1, created_at=NOW, updated_at=NOW))
    session.flush()
    for id_, course, state, institution in [("o1", "c1", "active", "school"), ("draft", "c1", "draft", "school"), ("archived", "c1", "archived", "school"), ("other", "c2", "active", "school"), ("foreign", "foreign", "active", "foreign")]:
        session.add(models.Offering(id=id_, institution_id=institution, course_id=course, title=f"Persisted {id_}", term="2026", timezone="UTC", state=state, revision=1, roster_revision=0, created_at=NOW, updated_at=NOW))
    session.flush()
    for offering, subject in [("o1", "learner"), ("draft", "learner"), ("archived", "learner"), ("o1", "teacherlearner"), ("o1", "assistant"), ("o1", "revoked"), ("other", "peer")]:
        session.add(models.Enrollment(id=f"e-{offering}-{subject}", institution_id="school", offering_id=offering, student_id=subject, status="active", effective_from=NOW-timedelta(days=1), revision=1, source_kind="deployment_roster", source_teacher_id="other" if offering == "other" else "owner", source_policy_digest="a"*64, created_at=NOW, updated_at=NOW))
    for subject, bound, label, permissions, scope in [("owner", "teacher", "teacher", [p.value for p in types.Permission], "offering"), ("co", "teacher", "assistant", ["ROSTER_MANAGE", "ROLES_MANAGE", "REVIEW"], "offering"), ("assistant", "student", "assistant", ["AUTHOR"], "assigned")]:
        session.add(models.TeachingRole(id=f"r-{subject}", institution_id="school", offering_id="o1", subject_id=subject, granted_account_role=bound, label=label, permissions=sorted(permissions), scope=scope, status="active", effective_from=NOW-timedelta(days=1), revision=1, source_policy_digest="a"*64, created_at=NOW, updated_at=NOW))
    session.commit()
    session.info["teaching_policy_provider"] = lambda: snapshot()
    yield session, access, types, models, accounts, original_readiness
    session.close()
    engine.dispose()


def offering_scope(types, id_="o1"):
    return types.ScopeRef("school", "offering", id_)


def deny(call, code=None, status=None):
    with pytest.raises(HTTPException) as error:
        call()
    if status is not None:
        assert error.value.status_code == status
    if code is not None:
        assert error.value.detail == code


def test_source_owner_eligibility_and_unrelated_teacher_no_management(dbcase):
    db, a, t, m, _, _ = dbcase
    assert a.authorize_action(db, "owner", t.TeachingAction.CREATE_COURSE, t.ScopeRef("school", "institution", "school")).actor_id == "owner"
    own = a.authorize_action(db, "owner", t.TeachingAction.ROSTER_MANAGE, offering_scope(t))
    assert t.Permission.ROSTER_MANAGE in own.permissions
    deny(lambda: a.authorize_action(db, "other", t.TeachingAction.ROSTER_MANAGE, offering_scope(t)), status=404)
    # Ownership grants shell reads but mutations still require the local role.
    db.execute(update(m.TeachingRole).where(m.TeachingRole.subject_id == "owner").values(status="revoked"))
    assert a.authorize_action(db, "owner", t.TeachingAction.READ_OFFERING, offering_scope(t)).teaching
    deny(lambda: a.authorize_action(db, "owner", t.TeachingAction.ROSTER_MANAGE, offering_scope(t)), status=403)


def test_deleted_account_and_invalid_current_role_deny_cached_token_and_receipt(dbcase):
    db, a, t, m, accounts, _ = dbcase
    identity = feature("app.services.current_identity")
    security = feature("app.core.security")
    token = security.create_access_token("co", "teacher")
    cached = identity.resolve_current_account(f"Bearer {token}", db)
    assert cached.username == "co"
    receipt = m.WriteReceipt(institution_id="school", actor_id="co", action=t.TeachingAction.ROSTER_MANAGE.value, scope_type="offering", scope_id="o1", target_type="offering", target_id="o1", idempotency_key="synthetic", request_hash="b"*64, result_type="roster", result_id="o1", accepted_at=NOW, http_status=200, original_result={"id": "o1"})
    db.add(receipt); db.commit()
    assert a.authorize_receipt_access(db, "co", receipt).actor_id == "co"
    db.execute(update(accounts.UserAccount).where(accounts.UserAccount.username == "co").values(role="admin").execution_options(synchronize_session=False))
    deny(lambda: a.authorize_receipt_access(db, "co", receipt), status=401)
    deny(lambda: identity.resolve_current_account(f"Bearer {token}", db), status=401)
    db.execute(delete(accounts.UserAccount).where(accounts.UserAccount.username == "co").execution_options(synchronize_session=False))
    deny(lambda: a.authorize_action(db, "co", t.TeachingAction.READ_OFFERING, offering_scope(t)), status=401)
    deny(lambda: a.authorize_receipt_access(db, "co", receipt), status=401)


def test_current_demotion_removes_teacher_authority_without_rejecting_valid_student_login(dbcase):
    db, a, t, m, accounts, _ = dbcase
    token = feature("app.core.security").create_access_token("teacherlearner", "teacher")
    db.execute(update(accounts.UserAccount).where(accounts.UserAccount.username == "teacherlearner").values(role="student"))
    current = feature("app.services.current_identity").resolve_current_account(f"Bearer {token}", db)
    assert current.role == "student"
    decision = a.authorize_action(db, current.username, t.TeachingAction.READ_OFFERING, offering_scope(t))
    assert decision.learning and not decision.teaching and not decision.permissions
    deny(lambda: a.authorize_action(db, current.username, t.TeachingAction.REVIEW, offering_scope(t)), status=403)
    db.execute(update(accounts.UserAccount).where(accounts.UserAccount.username == "owner").values(role="student"))
    deny(lambda: a.authorize_action(db, "owner", t.TeachingAction.CREATE_COURSE, t.ScopeRef("school", "institution", "school")), status=403)
    deny(lambda: a.authorize_action(db, "learner", t.TeachingAction.READ_OFFERING, offering_scope(t)), status=404)


def test_teacher_labelled_assistant_demotion_cannot_rebind_old_grant(dbcase):
    db, a, t, m, accounts, _ = dbcase
    assert a.authorize_action(db, "co", t.TeachingAction.ROSTER_MANAGE, offering_scope(t)).role_revision == 1
    receipt = m.WriteReceipt(institution_id="school", actor_id="co", action=t.TeachingAction.ROSTER_MANAGE.value, scope_type="offering", scope_id="o1", target_type="offering", target_id="o1", idempotency_key="d", request_hash="b"*64, result_type="roster", result_id="o1", accepted_at=NOW, http_status=200, original_result={"id": "o1"})
    db.add(receipt)
    db.add(m.Enrollment(id="e-co", institution_id="school", offering_id="o1", student_id="co", source_teacher_id="owner", source_policy_digest="a"*64, status="active", effective_from=NOW-timedelta(days=1), created_at=NOW, updated_at=NOW))
    db.commit()
    db.execute(update(accounts.UserAccount).where(accounts.UserAccount.username == "co").values(role="student"))
    db.info["teaching_policy_provider"] = lambda: snapshot(roster={"owner": ["co", "learner"], "co": ["learner"]}, delegation={"owner": {"co": {"account_role": "student", "permissions": ["ROSTER_MANAGE", "ROLES_MANAGE", "REVIEW"], "scope": "offering"}}})
    decision = a.authorize_action(db, "co", t.TeachingAction.READ_OFFERING, offering_scope(t))
    assert decision.learning and not decision.teaching
    deny(lambda: a.authorize_receipt_access(db, "co", receipt), status=403)
    # Synthetic explicit revision represents a later authorized local role write;
    # Task2 neither implements nor claims to execute the role-writing protocol.
    db.execute(update(m.TeachingRole).where(m.TeachingRole.subject_id == "co").values(granted_account_role="student", revision=2))
    assert a.authorize_action(db, "co", t.TeachingAction.ROSTER_MANAGE, offering_scope(t)).role_revision == 2


def test_canonical_actor_uses_stored_username_not_token_case_or_profile_ids(dbcase):
    db, a, t, _, _, _ = dbcase
    own = a.authorize_action(db, "learner", t.TeachingAction.READ_OFFERING, offering_scope(t))
    assert own.actor_id == "learner" and own.learning
    deny(lambda: a.authorize_action(db, "peer", t.TeachingAction.READ_OFFERING, offering_scope(t)), status=404)
    # SQLite binary-key behavior only; actual MySQL alias resolution is deferred.
    deny(lambda: a.authorize_action(db, "LEARNER", t.TeachingAction.READ_OFFERING, offering_scope(t)), status=401)


def test_source_roster_removal_denies_learner_and_assistant_but_allows_authorized_withdrawal_cleanup(dbcase):
    db, a, t, _, _, _ = dbcase
    db.info["teaching_policy_provider"] = lambda: snapshot(roster={"owner": ["teacherlearner"], "co": ["teacherlearner"]})
    deny(lambda: a.authorize_action(db, "learner", t.TeachingAction.READ_OFFERING, offering_scope(t)), status=404)
    deny(lambda: a.authorize_action(db, "assistant", t.TeachingAction.READ_OFFERING, offering_scope(t)), status=404)
    manager = a.authorize_action(db, "owner", t.TeachingAction.ROSTER_MANAGE, offering_scope(t))
    assert a.authorize_roster_target(manager, "learner", withdrawal=True) is None
    deny(lambda: a.authorize_roster_target(manager, "learner"), status=403)
    co = a.authorize_action(db, "co", t.TeachingAction.ROSTER_MANAGE, offering_scope(t))
    assert co.learner_ceiling == frozenset({"teacherlearner"})


@pytest.mark.parametrize("relationship", ["role", "enrollment"])
@pytest.mark.parametrize("point,allowed", [("start", True), ("future", False), ("end", False), ("before_end", True)])
def test_relationship_interval_start_inclusive_end_exclusive(dbcase, relationship, point, allowed):
    db, a, t, m, _, _ = dbcase
    subject = "co" if relationship == "role" else "learner"
    model = m.TeachingRole if relationship == "role" else m.Enrollment
    key = model.subject_id if relationship == "role" else model.student_id
    start = NOW if point != "future" else NOW+timedelta(microseconds=1)
    end = NOW if point == "end" else NOW+timedelta(microseconds=2 if point == "future" else 1)
    if point in {"end", "before_end"}: start = NOW-timedelta(days=1)
    db.execute(update(model).where(key == subject).values(effective_from=start, effective_until=end, revision=2))
    if allowed:
        decision = a.authorize_action(db, subject, t.TeachingAction.READ_OFFERING, offering_scope(t))
        assert (decision.role_revision if relationship == "role" else decision.enrollment_revision) == 2
    else:
        deny(lambda: a.authorize_action(db, subject, t.TeachingAction.READ_OFFERING, offering_scope(t)), status=404)


def test_permissions_are_independent_and_assigned_scope_has_no_offering_grant(dbcase):
    db, a, t, m, _, _ = dbcase
    db.execute(update(m.TeachingRole).where(m.TeachingRole.subject_id == "co").values(permissions=["ROLES_MANAGE"]))
    assert a.authorize_action(db, "co", t.TeachingAction.ROLES_MANAGE, offering_scope(t)).permissions == frozenset({t.Permission.ROLES_MANAGE})
    for action in [t.TeachingAction.REVIEW, t.TeachingAction.PUBLISH, t.TeachingAction.ROSTER_MANAGE]:
        deny(lambda: a.authorize_action(db, "co", action, offering_scope(t)), status=403)
    assistant = a.authorize_action(db, "assistant", t.TeachingAction.READ_OFFERING, offering_scope(t))
    assert assistant.teaching and assistant.role_scope == "assigned"
    deny(lambda: a.authorize_action(db, "assistant", t.TeachingAction.AUTHOR, offering_scope(t)), status=403)
    deny(lambda: a.authorize_action(db, "owner", t.TeachingAction.REVIEW, offering_scope(t), t.ObjectRef("assignment", "made-up", "school", "c1", "o1")), code="unsupported_object", status=403)
    deny(lambda: a.authorize_action(db, "owner", "BOGUS", offering_scope(t)), status=422)


def test_overbroad_stored_role_is_rejected_atomically_not_intersected(dbcase):
    db, a, t, m, _, _ = dbcase
    db.execute(update(m.TeachingRole).where(m.TeachingRole.subject_id == "co").values(permissions=["PUBLISH", "ROSTER_MANAGE"]))
    deny(lambda: a.authorize_action(db, "co", t.TeachingAction.ROSTER_MANAGE, offering_scope(t)), status=404)
    db.execute(update(m.TeachingRole).where(m.TeachingRole.subject_id == "assistant").values(scope="assigned", permissions=["ROSTER_MANAGE"]))
    deny(lambda: a.authorize_action(db, "assistant", t.TeachingAction.ROSTER_MANAGE, offering_scope(t)), status=403)


def test_locked_decision_uses_final_clock_and_coherent_supplied_policy_only(dbcase):
    db, a, t, m, _, _ = dbcase
    db.execute(update(m.TeachingRole).where(m.TeachingRole.subject_id == "co").values(effective_until=NOW+timedelta(microseconds=1)))
    context = a.load_authorization_context(db, "co", offering_scope(t))
    locked = t.LockedContext(**{field.name: getattr(context, field.name) for field in dataclasses.fields(context)})
    policy = feature("app.services.teaching.policy").read_teaching_policy(snapshot(), "owner", actor_id="co")
    assert a.authorize_locked_action(locked, policy, t.TeachingAction.ROSTER_MANAGE, NOW).actor_id == "co"
    deny(lambda: a.authorize_locked_action(locked, policy, t.TeachingAction.ROSTER_MANAGE, NOW+timedelta(microseconds=1)), status=404)
    deny(lambda: a.authorize_locked_action(context, policy, t.TeachingAction.ROSTER_MANAGE, NOW), code="lock_orchestration_required", status=503)
    deny(lambda: a.authorize_action(db, "co", t.TeachingAction.ROSTER_MANAGE, offering_scope(t), lock=True), code="lock_orchestration_required", status=503)


def test_disabled_unavailable_and_unpatched_schema_failure_are_honest(dbcase, monkeypatch):
    db, a, t, _, _, readiness = dbcase
    db.info["teaching_policy_provider"] = lambda: snapshot(enabled=False)
    deny(lambda: a.authorize_action(db, "owner", t.TeachingAction.READ_OFFERING, offering_scope(t)), code="feature_disabled", status=503)
    schema = feature("app.services.teaching.schema")
    report = schema.inspect_teaching_schema(db.connection())
    assert report.shape_valid and report.ledger_present and not report.mysql_verified
    with pytest.raises(schema.TeachingSchemaError) as error:
        readiness(db)
    assert error.value.code == "teaching_schema_incompatible"

    db.info["teaching_policy_provider"] = lambda: snapshot()
    monkeypatch.setattr(a, "require_teaching_schema", readiness)
    deny(lambda: a.list_courses(db, "owner"), code="teaching_schema_incompatible", status=503)


@pytest.mark.parametrize("shape", ["mismatched_course", "missing_course", "missing_offering"])
def test_locked_context_rejects_unbound_or_missing_roots(dbcase, shape):
    db, a, t, _, _, _ = dbcase
    context = a.load_authorization_context(db, "owner", t.ScopeRef("school", "course", "c1"))
    locked = t.LockedContext(**{field.name: getattr(context, field.name) for field in dataclasses.fields(context)})
    policy = feature("app.services.teaching.policy").read_teaching_policy(snapshot(), "owner", actor_id="owner")
    assert a.authorize_locked_action(locked, policy, t.TeachingAction.UPDATE_COURSE, NOW).scope.id == "c1"
    action = t.TeachingAction.UPDATE_COURSE
    if shape == "mismatched_course":
        malformed = dataclasses.replace(locked, scope=t.ScopeRef("school", "course", "c2"))
    elif shape == "missing_course":
        malformed = dataclasses.replace(locked, course=None, scope=t.ScopeRef("school", "course", "c2"))
    else:
        malformed = dataclasses.replace(locked, scope=t.ScopeRef("school", "offering", "other"))
        action = t.TeachingAction.READ_OFFERING
    with pytest.raises(HTTPException) as error:
        a.authorize_locked_action(malformed, policy, action, NOW)
    assert error.value.status_code in {403, 404, 422}


def test_read_course_rejects_institution_scope_with_typed_denial(dbcase):
    db, a, t, _, _, _ = dbcase
    assert a.authorize_action(db, "owner", t.TeachingAction.READ_COURSE, t.ScopeRef("school", "course", "c1")).scope.id == "c1"
    with pytest.raises(HTTPException) as error:
        a.authorize_action(db, "owner", t.TeachingAction.READ_COURSE, t.ScopeRef("school", "institution", "school"))
    assert error.value.status_code in {403, 404, 422}
