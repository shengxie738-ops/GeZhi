"""Task3 synthetic transaction tests. SQLite is never isolation/lock proof."""
import dataclasses
import importlib
import json
from datetime import datetime, timedelta, timezone
from hashlib import sha256

import pytest
from fastapi import HTTPException
from sqlalchemy import event, update, delete

from tests.test_teaching_authorization import dbcase, NOW, snapshot


def feature(name):
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        pytest.fail(f"Task3 feature absent: {name}: {exc}")


@pytest.fixture
def writes_case(dbcase, monkeypatch):
    db, access, types, models, accounts, readiness = dbcase
    writes = feature("app.services.teaching.writes")
    # Explicit synthetic-only boundaries; no production readiness/isolation claim.
    monkeypatch.setattr(writes, "_require_transaction", lambda session: None)
    monkeypatch.setattr(writes, "_require_write_safety", lambda session: None)
    monkeypatch.setattr(writes, "_server_clock", lambda session: NOW)
    yield db, writes, types, models, accounts


def intent(w, t, *, key="original:123", payload=None, actor="owner", target="o1"):
    return w.make_write_intent(actor, t.TeachingAction.COURSE_MANAGE,
                               t.ScopeRef("school", "offering", "o1"), target, key,
                               payload if payload is not None else {"expected_revision": 1, "title": "Accepted"})


class SyntheticOperation:
    """Server-owned synthetic mutation; no future production course operation."""
    def __init__(self, types, *, fail=None, accounts=(), roles=(), enrollments=()):
        self.types, self.fail = types, fail
        self.accounts, self.roles, self.enrollments = accounts, roles, enrollments
        self.seen = None

    def collect_locks(self, session, intent, locked_roots, preview_footprint=None):
        self.seen = preview_footprint
        return self.types.LockPlan(root_course_id=locked_roots.course.id,
            root_offering_id=locked_roots.offering.id, account_ids=self.accounts,
            role_subject_ids=self.roles, enrollment_subject_ids=self.enrollments,
            preview_id=preview_footprint.preview_id if preview_footprint else None,
            receipt_lookup=self.types.ReceiptLookup.from_intent(intent))

    def validate_new(self, context, command, at):
        if context.offering.state == "archived":
            raise HTTPException(409, "lifecycle_conflict")
        if context.offering.revision != command["expected_revision"]:
            raise HTTPException(409, "revision_conflict")
        if context.preview is not None and context.preview.expires_at.replace(tzinfo=timezone.utc) <= at:
            raise HTTPException(409, "preview_stale")
        if self.fail == "validate":
            raise ValueError("synthetic validation failure")

    def apply_new(self, context, command, at):
        before = context.offering.revision
        context.offering.title = command["title"]
        context.offering.revision += 1
        context.offering.updated_at = at
        if self.fail == "business":
            raise ValueError("synthetic business failure")
        return self.types.MutationResult("offering", context.offering.id,
            {"id": context.offering.id, "revision": context.offering.revision,
             "title": context.offering.title, "state": context.offering.state},
            "offering", before, context.offering.revision, {"changed": ["title"]}, 201)


def execute(case, command=None, op=None):
    db, w, t, _, _ = case
    command = command or intent(w, t)
    return w.execute_write(db, command, command.scope, op or SyntheticOperation(t))


def counts(db, m):
    return tuple(db.query(cls).count() for cls in (m.WriteReceipt, m.AccessEvent))


def test_same_key_same_payload_returns_same_original_receipt_after_newer_state(writes_case):
    db, w, t, m, _ = writes_case
    first = execute(writes_case); db.commit()
    db.execute(update(m.Offering).where(m.Offering.id == "o1").values(title="Newer", revision=6)); db.commit()
    replay = execute(writes_case)
    assert replay.replayed and replay.receipt.id == first.receipt.id
    assert replay.receipt.accepted_at == first.receipt.accepted_at
    assert replay.result == first.result == {"id": "o1", "revision": 2, "title": "Accepted", "state": "active"}
    assert replay.receipt.http_status == 201 and counts(db, m) == (1, 1)
    assert db.get(m.Offering, "o1").revision == 6
    replay.result["revision"] = 999
    assert w.get_receipt(db, "owner", first.receipt.id).result["revision"] == 2


def test_same_key_changed_payload_conflicts_without_side_effects(writes_case):
    db, w, t, m, _ = writes_case
    execute(writes_case); db.commit()
    with pytest.raises(HTTPException) as error:
        execute(writes_case, intent(w, t, payload={"title": "Changed", "expected_revision": 2}))
    assert error.value.status_code == 409 and error.value.detail == "idempotency_conflict"
    assert counts(db, m) == (1, 1) and db.get(m.Offering, "o1").title == "Accepted"


@pytest.mark.parametrize("revocation", ["role", "source", "account", "policy"])
def test_current_permission_precedes_receipt_existence_and_hash_conflict(writes_case, revocation):
    db, w, t, m, a = writes_case
    first = execute(writes_case); db.commit()
    if revocation == "role":
        db.execute(update(m.TeachingRole).where(m.TeachingRole.subject_id == "owner").values(status="revoked"))
    elif revocation in {"source", "account"}:
        db.execute(update(a.UserAccount).where(a.UserAccount.username == "owner").values(role="student" if revocation == "source" else "admin"))
    else:
        db.info["teaching_policy_provider"] = lambda: snapshot(roster={})
    db.commit()
    for command in (intent(w, t), intent(w, t, payload={"title": "Changed"}), intent(w, t, key="missing:123")):
        with pytest.raises(HTTPException) as error:
            execute(writes_case, command)
        assert error.value.status_code in {401, 403, 404} and error.value.detail != "idempotency_conflict"
    for receipt_id in (first.receipt.id, "missing"):
        with pytest.raises(HTTPException) as error:
            w.get_receipt(db, "owner", receipt_id)
        assert (error.value.status_code, error.value.detail) == (404, "not_found")
    assert counts(db, m) == (1, 1)


def test_another_actor_cannot_distinguish_receipt_or_missing(writes_case):
    db, w, t, _, _ = writes_case
    first = execute(writes_case); db.commit()
    for receipt_id in (first.receipt.id, "missing"):
        with pytest.raises(HTTPException) as error:
            w.get_receipt(db, "co", receipt_id)
        assert (error.value.status_code, error.value.detail) == (404, "not_found")
    with pytest.raises(HTTPException) as error:
        w.find_receipt(db, "co", t.TeachingAction.COURSE_MANAGE, t.ScopeRef("school", "offering", "o1"), "original:123")
    assert (error.value.status_code, error.value.detail) == (404, "not_found")


def test_new_write_lifecycle_checks_follow_accepted_replay(writes_case):
    db, w, t, m, _ = writes_case
    original = execute(writes_case); db.commit()
    db.execute(update(m.Offering).where(m.Offering.id == "o1").values(state="archived", revision=8)); db.commit()
    assert execute(writes_case).receipt.id == original.receipt.id
    with pytest.raises(HTTPException) as error:
        execute(writes_case, intent(w, t, key="new-key:123"))
    assert error.value.detail == "lifecycle_conflict"
    assert counts(db, m) == (1, 1)


@pytest.mark.parametrize("stage", ["business", "receipt", "event"])
def test_business_receipt_event_failures_roll_back_every_effect(writes_case, stage):
    db, w, t, m, _ = writes_case
    def failure(mapper, connection, target):
        raise ValueError("synthetic flush failure")
    model = m.WriteReceipt if stage == "receipt" else m.AccessEvent
    if stage != "business":
        event.listen(model, "before_insert", failure)
    try:
        with pytest.raises(ValueError):
            execute(writes_case, op=SyntheticOperation(t, fail="business" if stage == "business" else None))
    finally:
        if stage != "business":
            event.remove(model, "before_insert", failure)
    assert counts(db, m) == (0, 0)
    assert db.get(m.Offering, "o1").revision == 1


def test_services_flush_but_never_commit_and_scope_mismatch_rolls_back(writes_case, monkeypatch):
    db, w, t, m, _ = writes_case
    monkeypatch.setattr(db, "commit", lambda: pytest.fail("service committed"))
    first = execute(writes_case)
    assert not first.replayed and db.in_transaction()
    db.rollback()
    assert counts(db, m) == (0, 0)
    with pytest.raises(HTTPException):
        w.execute_write(db, intent(w, t), t.ScopeRef("school", "offering", "other"), SyntheticOperation(t))
    assert counts(db, m) == (0, 0)


def preview(db, m, *, actor="owner", offering="o1", expiry=None):
    row = m.RosterPreview(id="p1", institution_id="school", offering_id=offering, actor_id=actor,
        actor_role_id="r-owner", actor_role_revision=1, expected_roster_revision=0, offering_revision=1,
        mode="replace", canonical_command={"student_ids": ["learner"]}, command_hash="a"*64,
        source_policy_digest="a"*64, target_ids=["learner"], add_ids=[], keep_ids=["learner"],
        update_ids=[], withdraw_ids=["revoked"], validation_issues=[], target_digest="a"*64,
        withdrawals_digest="b"*64, withdrawals_count=1, can_apply=True, created_at=NOW-timedelta(minutes=5),
        expires_at=expiry or NOW+timedelta(minutes=5))
    db.add(row); db.commit()
    return row


def test_preview_footprint_is_scoped_complete_and_expiry_is_after_replay(writes_case):
    db, w, t, m, a = writes_case
    preview(db, m)
    command = intent(w, t, payload={"expected_revision": 1, "title": "Accepted", "preview_id": "p1"})
    op = SyntheticOperation(t)
    first = execute(writes_case, command, op); db.commit()
    assert op.seen.target_ids == ("learner",) and op.seen.relationship_subject_ids == ("learner", "revoked")
    db.execute(delete(a.UserAccount).where(a.UserAccount.username == "learner")); db.commit()
    # Clock advancement simulates expiry only, not a MySQL blocking wait.
    original_clock = w._server_clock
    w._server_clock = lambda session: NOW+timedelta(hours=1)
    try:
        assert execute(writes_case, command).receipt.id == first.receipt.id
    finally:
        w._server_clock = original_clock
    assert counts(db, m) == (1, 1)


@pytest.mark.parametrize("actor,offering", [("other", "o1"), ("owner", "other")])
def test_preview_wrong_actor_or_scope_never_supplies_a_footprint(writes_case, actor, offering):
    db, w, t, m, _ = writes_case
    preview(db, m, actor=actor, offering=offering)
    command = intent(w, t, payload={"expected_revision": 1, "title": "Accepted", "preview_id": "p1"})
    op = SyntheticOperation(t)
    with pytest.raises(HTTPException) as error:
        execute(writes_case, command, op)
    assert (error.value.status_code, error.value.detail) == (404, "not_found")
    assert op.seen is None and counts(db, m) == (0, 0)


def test_preview_content_changed_before_final_lock_fails_closed(writes_case):
    db, w, t, m, _ = writes_case
    preview(db, m)
    class ChangesPreview(SyntheticOperation):
        def collect_locks(self, session, command, roots, preview_footprint=None):
            plan = super().collect_locks(session, command, roots, preview_footprint)
            session.execute(update(m.RosterPreview).where(m.RosterPreview.id == "p1").values(target_ids=["assistant"]))
            return plan
    command = intent(w, t, payload={"expected_revision": 1, "title": "Accepted", "preview_id": "p1"})
    with pytest.raises(HTTPException) as error:
        execute(writes_case, command, ChangesPreview(t))
    assert error.value.status_code == 503 and counts(db, m) == (0, 0)


def test_declared_locks_precede_policy_clock_and_no_sql_reads_follow_clock(writes_case):
    db, w, t, m, _ = writes_case
    preview(db, m)
    trace = []
    def observe(connection, cursor, statement, parameters, context, executemany):
        trace.append(statement)
    event.listen(db.bind, "before_cursor_execute", observe)
    original_clock = w._server_clock
    original_provider = db.info["teaching_policy_provider"]
    w._server_clock = lambda session: trace.append("FINAL_CLOCK") or NOW
    db.info["teaching_policy_provider"] = lambda: trace.append("POLICY") or original_provider()
    try:
        execute(writes_case, intent(w, t, payload={"expected_revision": 1, "title": "Accepted", "preview_id": "p1"}), SyntheticOperation(t, accounts=("co",), roles=("co",), enrollments=("learner",)))
    finally:
        event.remove(db.bind, "before_cursor_execute", observe)
        w._server_clock = original_clock
    last_clock = trace.index("FINAL_CLOCK")
    assert trace[last_clock-1] == "POLICY"
    assert not any(item.lstrip().upper().startswith("SELECT") for item in trace[last_clock+1:])
    selects = [item for item in trace[:last_clock] if item.startswith("SELECT")]
    positions = {name: max(i for i, sql in enumerate(selects) if "FROM " + name in sql) for name in (
        "teaching_courses", "teaching_offerings", "user_accounts", "teaching_roles", "teaching_enrollments", "teaching_roster_previews", "teaching_write_receipts")}
    assert positions["teaching_courses"] < positions["user_accounts"]
    assert positions["teaching_offerings"] < positions["user_accounts"] < positions["teaching_roles"] < positions["teaching_enrollments"] < positions["teaching_roster_previews"] < positions["teaching_write_receipts"]


def test_role_expiry_and_policy_swap_at_last_receipt_read_are_rechecked(writes_case):
    db, w, t, m, _ = writes_case
    execute(writes_case); db.commit()
    db.execute(update(m.TeachingRole).where(m.TeachingRole.subject_id == "owner").values(effective_until=NOW+timedelta(seconds=1))); db.commit()
    original_clock = w._server_clock
    w._server_clock = lambda session: NOW+timedelta(seconds=1)
    try:
        with pytest.raises(HTTPException) as error:
            execute(writes_case)
        assert error.value.status_code == 403
    finally:
        w._server_clock = original_clock
    assert counts(db, m) == (1, 1)


def test_canonical_hash_v1_vectors_and_exact_null_case_and_unicode():
    w = feature("app.services.teaching.writes")
    t = feature("app.services.teaching.types")
    scope = t.ScopeRef("school", "offering", "o1")
    command = {"title": "课程é", "expected_revision": 1, "period": None, "student_ids": ["Z", "a", "Z"]}
    canonical = '{"action":"course_manage","command":{"expected_revision":1,"period":null,"student_ids":["Z","a"],"title":"课程é"},"scope_id":"o1","scope_type":"offering","target_id":"o1","version":1}'
    h = w.canonical_request_hash(t.TeachingAction.COURSE_MANAGE, scope, "o1", command)
    assert h == sha256(canonical.encode("utf-8")).hexdigest()
    assert h == w.canonical_request_hash(t.TeachingAction.COURSE_MANAGE, scope, "o1", dict(reversed(list(command.items()))))
    assert h != w.canonical_request_hash(t.TeachingAction.COURSE_MANAGE, scope, "O1", command)
    assert h != w.canonical_request_hash(t.TeachingAction.COURSE_MANAGE, scope, "o1", {k:v for k,v in command.items() if k != "period"})
    instant = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert w.canonical_request_hash(t.TeachingAction.COURSE_MANAGE, scope, "o1", {"at": instant}) == w.canonical_request_hash(t.TeachingAction.COURSE_MANAGE, scope, "o1", {"at": instant.astimezone(timezone(timedelta(hours=8)))})
    assert w.digest_id_set("roster_target", ["a", "A", "a"]) == sha256(b'{"ids":["A","a"],"kind":"roster_target","version":1}').hexdigest()
    assert w.digest_id_set("roster_target", []) != w.digest_id_set("roster_withdrawals", [])


@pytest.mark.parametrize("payload", [{"x": 1.1}, {"x": float("nan")}, {"expected_revision": True}, {"at": datetime(2026, 1, 1)}])
def test_invalid_canonical_values_are_validation_errors(payload):
    w, t = feature("app.services.teaching.writes"), feature("app.services.teaching.types")
    with pytest.raises(HTTPException) as error:
        intent(w, t, payload=payload)
    assert error.value.status_code == 422


@pytest.mark.parametrize("key", ["short", "a"*129, "has space", "控制字符key", "bad\nkeyx"])
def test_invalid_keys_are_rejected(key):
    w, t = feature("app.services.teaching.writes"), feature("app.services.teaching.types")
    with pytest.raises(HTTPException) as error:
        intent(w, t, key=key)
    assert error.value.status_code == 422


def test_maximum_key_immutable_command_and_forged_hash(writes_case):
    db, w, t, m, _ = writes_case
    payload = {"title": "Accepted", "expected_revision": 1}
    command = intent(w, t, key="a"*128, payload=payload)
    payload["title"] = "Caller mutated"
    assert execute(writes_case, command).result["title"] == "Accepted"
    db.rollback()
    with pytest.raises(HTTPException) as error:
        execute(writes_case, dataclasses.replace(command, request_hash="0"*64))
    assert error.value.status_code == 422 and counts(db, m) == (0, 0)


def test_unpatched_sqlite_readiness_and_transaction_gate_still_refuse(dbcase):
    db, access, t, m, a, real_readiness = dbcase
    w = feature("app.services.teaching.writes")
    with pytest.raises(Exception) as error:
        real_readiness(db)
    assert getattr(error.value, "code", None) == "teaching_schema_incompatible"
    with pytest.raises(HTTPException) as error:
        w._require_transaction(db)
    assert error.value.status_code == 503


def test_unpatched_write_safety_gate_has_no_session_info_bypass(dbcase):
    db = dbcase[0]
    w = feature("app.services.teaching.writes")
    db.info.update(teaching_write_safety_verified=True, teaching_synthetic=True, teaching_transaction="READ COMMITTED")
    with pytest.raises(HTTPException) as error:
        w._require_write_safety(db)
    assert (error.value.status_code, error.value.detail) == (503, "write_safety_unproven")


def test_direct_connection_read_after_final_clock_fails_closed(writes_case):
    db, w, t, m, _ = writes_case
    from sqlalchemy import text
    class ReadsAfterClock(SyntheticOperation):
        def apply_new(self, context, command, at):
            context.session.connection().execute(text("SELECT 1")).scalar_one()
            return super().apply_new(context, command, at)
    with pytest.raises(HTTPException) as error:
        execute(writes_case, op=ReadsAfterClock(t))
    assert (error.value.status_code, error.value.detail) == (503, "post_clock_query_forbidden")
    assert counts(db, m) == (0, 0) and db.get(m.Offering, "o1").revision == 1


@pytest.mark.parametrize("other", ["course", "account"])
def test_mutation_cannot_flush_undeclared_or_account_rows(writes_case, other):
    db, w, t, m, accounts = writes_case
    class MutatesOutsideFootprint(SyntheticOperation):
        def collect_locks(self, session, command, roots, preview_footprint=None):
            self.outside = session.get(m.Course, "c2") if other == "course" else session.get(accounts.UserAccount, "owner")
            return super().collect_locks(session, command, roots, preview_footprint)
        def apply_new(self, context, command, at):
            if other == "course":
                self.outside.title = "Outside authorized root"
            else:
                self.outside.role = "student"
            context.session.flush()
            return super().apply_new(context, command, at)
    with pytest.raises(HTTPException) as error:
        execute(writes_case, op=MutatesOutsideFootprint(t))
    assert (error.value.status_code, error.value.detail) == (503, "undeclared_mutation")
    assert counts(db, m) == (0, 0) and db.get(m.Offering, "o1").revision == 1
    assert db.get(accounts.UserAccount, "owner").role == "teacher"
    assert db.get(m.Course, "c2").title == "Persisted c2"


def test_service_operation_cannot_commit_before_receipt(writes_case):
    db, w, t, m, _ = writes_case
    class Commits(SyntheticOperation):
        def apply_new(self, context, command, at):
            context.session.commit()
            return super().apply_new(context, command, at)
    with pytest.raises(HTTPException) as error:
        execute(writes_case, op=Commits(t))
    assert (error.value.status_code, error.value.detail) == (503, "service_commit_forbidden")
    assert counts(db, m) == (0, 0)


def test_final_policy_is_resampled_after_receipt_query(writes_case):
    db, w, t, m, _ = writes_case
    execute(writes_case); db.commit()
    def swap(connection, cursor, statement, parameters, context, executemany):
        if "FROM teaching_write_receipts" in statement:
            db.info["teaching_policy_provider"] = lambda: snapshot(roster={})
    event.listen(db.bind, "after_cursor_execute", swap)
    try:
        with pytest.raises(HTTPException) as error:
            execute(writes_case)
    finally:
        event.remove(db.bind, "after_cursor_execute", swap)
    assert error.value.status_code == 403
    assert counts(db, m) == (1, 1)
