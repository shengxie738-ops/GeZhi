"""Task5 ordinary roster workflow tests; synthetic SQLite is not vendor proof."""
from datetime import timedelta, timezone

import pytest
from sqlalchemy import delete, event, update

from tests.test_teaching_authorization import dbcase, NOW, snapshot
from tests.test_teaching_receipts import writes_case, counts
from tests.test_teaching_courses import feature, error


def command(ids=None, **values):
    return {"mode": "merge", "expected_roster_revision": 0,
            "student_ids": ["learner"] if ids is None else ids, **values}


def confirmation(preview, **values):
    return {"preview_id": preview.result["id"],
            "expected_roster_revision": preview.result["expected_roster_revision"],
            "confirmed_withdrawals_digest": preview.result["withdrawals_digest"],
            "confirmed_withdrawals_count": preview.result["withdrawals_count"], **values}


def preview(case, payload=None, *, key="preview-intent:123", actor="owner"):
    db = case[0]
    result = feature("app.services.teaching.rosters").preview_roster(db, actor, "o1", payload or command(), key)
    db.commit()
    return result


def apply(case, prepared, *, key="apply-intent:123", actor="owner", **values):
    result = feature("app.services.teaching.rosters").apply_roster(case[0], actor, "o1", confirmation(prepared, **values), key)
    case[0].commit()
    return result


def seed_students(case, total, *, existing=True):
    db, _, _, m, a = case
    ids = [f"synthetic-{index:05d}" for index in range(total)]
    db.add_all([a.UserAccount(username=subject, role="student", password_hash="synthetic-only") for subject in ids])
    if existing:
        db.execute(delete(m.Enrollment).where(m.Enrollment.offering_id == "o1"))
        for index, subject in enumerate(ids):
            start = NOW + timedelta(days=1) if index % 3 == 1 else NOW - timedelta(days=2)
            end = NOW - timedelta(days=1) if index % 3 == 2 else None
            db.add(m.Enrollment(id=f"seed-{index}", institution_id="school", offering_id="o1", student_id=subject,
                status="active", effective_from=start, effective_until=end, revision=1,
                source_kind="deployment_roster", source_teacher_id="owner", source_policy_digest="a"*64,
                created_at=NOW, updated_at=NOW))
    db.commit()
    db.info["teaching_policy_provider"] = lambda: snapshot(roster={"owner": ids})
    return ids


def test_merge_keeps_full_roster_and_noop_has_one_receipt_event_and_revision(writes_case):
    db, w, _, m, _ = writes_case
    before = {row.id: row.revision for row in db.query(m.Enrollment).filter_by(offering_id="o1")}
    p = preview(writes_case)
    assert p.receipt.http_status == 201 and p.result["target_count"] == 4
    assert (p.result["add_count"], p.result["keep_count"], p.result["update_count"], p.result["withdrawals_count"]) == (0, 4, 0, 0)
    assert p.result["can_apply"] and p.result["withdrawals_digest"] == w.digest_id_set("roster_withdrawals", [])
    assert counts(db, m) == (1, 1) and db.get(m.Offering, "o1").roster_revision == 0
    accepted = apply(writes_case, p)
    assert accepted.result["roster_revision"] == 1 and accepted.result["kept_count"] == 4
    assert accepted.result["added_count"] == accepted.result["updated_count"] == accepted.result["withdrawn_count"] == 0
    assert {row.id: row.revision for row in db.query(m.Enrollment).filter_by(offering_id="o1")} == before
    assert counts(db, m) == (2, 2)
    assert "target_ids" not in accepted.receipt.original_result and "student_ids" not in accepted.receipt.original_result


def test_replace_adds_and_withdraws_actual_rows_and_records_revision_metadata(writes_case):
    db, _, _, m, a = writes_case
    db.add(a.UserAccount(username="new", role="student", password_hash="synthetic-only")); db.commit()
    db.info["teaching_policy_provider"] = lambda: snapshot(roster={"owner": ["learner", "new"]})
    p = preview(writes_case, command(["learner", "new"], mode="replace"))
    assert (p.result["target_count"], p.result["add_count"], p.result["keep_count"], p.result["withdrawals_count"]) == (2, 1, 1, 3)
    result = apply(writes_case, p)
    assert (result.result["added_count"], result.result["kept_count"], result.result["withdrawn_count"]) == (1, 1, 3)
    rows = {r.student_id: r for r in db.query(m.Enrollment).filter_by(offering_id="o1")}
    assert rows["new"].revision == 1 and rows["learner"].revision == 1
    assert rows["new"].effective_from.replace(tzinfo=timezone.utc) == NOW
    assert rows["new"].source_teacher_id == "owner" and rows["new"].source_kind == "deployment_roster"
    assert all(rows[x].status == "withdrawn" and rows[x].revision == 2 for x in ["assistant", "teacherlearner", "revoked"])
    audit = db.query(m.AccessEvent).filter_by(receipt_id=result.receipt.id).one().effect_metadata
    assert len(audit["enrollments"]) == 4
    assert {x["after"]["student_id"] for x in audit["enrollments"]} == {"new", "assistant", "teacherlearner", "revoked"}
    assert all("source_policy_digest" in x["after"] and "effective_from" in x["after"] for x in audit["enrollments"])


def test_explicit_empty_replace_preserves_history_and_reenrollment_stable_id(writes_case):
    db, _, _, m, _ = writes_case
    old = db.get(m.Enrollment, "e-o1-learner")
    interval = old.effective_from, old.effective_until
    p = preview(writes_case, command([], mode="replace"))
    assert p.result["can_apply"] and p.result["withdrawals_count"] == 4
    apply(writes_case, p)
    assert (old.id, old.revision, old.status) == ("e-o1-learner", 2, "withdrawn")
    assert (old.effective_from, old.effective_until) == interval
    p2 = preview(writes_case, command(expected_roster_revision=1), key="reenroll-preview:123")
    assert p2.result["add_count"] == 1
    apply(writes_case, p2, key="reenroll-apply:123")
    assert (old.id, old.revision, old.status, old.withdrawn_at) == ("e-o1-learner", 3, "active", None)
    assert db.query(m.Enrollment).filter_by(offering_id="o1", student_id="learner").count() == 1


def test_duplicate_inputs_reported_and_do_not_duplicate_enrollment(writes_case):
    db, _, _, m, _ = writes_case
    p = preview(writes_case, command(["learner", "learner", "teacherlearner"], mode="replace"))
    assert p.result["target_count"] == 2 and p.result["can_apply"]
    assert {x["code"] for x in p.result["validation_issues"]} == {"duplicate_input"}
    apply(writes_case, p)
    assert db.query(m.Enrollment).filter_by(offering_id="o1", status="active").count() == 2


def test_database_alias_duplicates_use_canonical_id_logic_only(writes_case, monkeypatch):
    db, _, _, m, _ = writes_case
    roster = feature("app.services.teaching.rosters")
    # A synthetic alias-resolution boundary only: this does not claim MySQL
    # collation proof. All downstream preview, locking and mutation are real.
    resolver = getattr(roster, "_resolve_requested", None)
    assert resolver is not None, "Task5 scoped canonical resolution missing"
    original = resolver
    def resolve(session, requested, ceiling):
        mapped, issues = original(session, ["learner" if x == "LEARNER" else x for x in requested], ceiling)
        return {raw: mapped["learner" if raw == "LEARNER" else raw] for raw in requested}, issues
    monkeypatch.setattr(roster, "_resolve_requested", resolve)
    p = preview(writes_case, command(["LEARNER", "learner"], mode="replace"))
    assert p.result["target_count"] == 1 and p.result["can_apply"]
    assert "duplicate_alias" in {x["code"] for x in p.result["validation_issues"]}
    apply(writes_case, p)
    assert db.query(m.Enrollment).filter_by(offering_id="o1", status="active").one().student_id == "learner"


@pytest.mark.parametrize("target", ["missing", "peer", "LEARNER"])
def test_unavailable_or_out_of_scope_target_blocks_all_rows_without_existence_detail(writes_case, target):
    db, _, _, m, _ = writes_case
    p = preview(writes_case, command(["learner", target], mode="replace"))
    assert not p.result["can_apply"]
    assert {x["code"] for x in p.result["validation_issues"]} == {"unavailable_or_out_of_scope"}
    error(lambda: apply(writes_case, p), "preview_stale", 409)
    assert counts(db, m) == (1, 1) and db.get(m.Offering, "o1").roster_revision == 0
    assert db.query(m.Enrollment).filter_by(offering_id="o1", status="active").count() == 4


def test_co_teacher_source_and_own_roster_intersection_prevents_new_grant(writes_case):
    p = preview(writes_case, command(["learner", "assistant"], mode="replace"), actor="co")
    assert not p.result["can_apply"]
    assert p.result["target_count"] == 1
    assert p.result["validation_issues"] == [{"code": "unavailable_or_out_of_scope", "subject_id": "assistant"}]


def test_full_withdrawal_digest_covers_more_than_sample(writes_case):
    db, w, _, m, _ = writes_case
    ids = seed_students(writes_case, 137)
    p = preview(writes_case, command([], mode="replace"))
    assert p.result["withdrawals_count"] == 137 and 0 < len(p.result["withdraw_sample"]) <= 50
    assert p.result["withdrawals_digest"] == w.digest_id_set("roster_withdrawals", ids)
    roster = feature("app.services.teaching.rosters")
    query = feature("app.schemas.teaching").PreviewChangesQuery
    seen, cursor = [], None
    while True:
        page = roster.list_roster_preview_changes(db, "owner", "o1", p.result["id"], query(kind="withdraw", cursor=cursor, limit=50))
        assert page.total_count == 137
        seen.extend(page.items); cursor = page.next_cursor
        if cursor is None:
            break
    assert seen == ids
    error(lambda: apply(writes_case, p, confirmed_withdrawals_count=len(p.result["withdraw_sample"]),
        confirmed_withdrawals_digest=w.digest_id_set("roster_withdrawals", p.result["withdraw_sample"])), "withdrawal_confirmation_mismatch", 409)
    assert counts(db, m) == (1, 1) and db.query(m.Enrollment).filter_by(offering_id="o1", status="active").count() == 137
    accepted = apply(writes_case, p)
    assert accepted.result["withdrawn_count"] == 137 and db.get(m.Offering, "o1").roster_revision == 1


@pytest.mark.parametrize("change", ["role", "policy", "source_membership", "roster", "offering", "archive"])
def test_preview_scope_actor_role_source_roster_and_revision_are_bound(writes_case, change):
    db, _, _, m, _ = writes_case
    p = preview(writes_case, command(["learner"], mode="replace"))
    if change == "role":
        db.execute(update(m.TeachingRole).where(m.TeachingRole.id == "r-owner").values(revision=2))
    elif change in {"policy", "source_membership"}:
        db.info["teaching_policy_provider"] = lambda: snapshot(roster={"owner": ["teacherlearner"] if change == "source_membership" else ["learner", "assistant", "teacherlearner", "revoked", "new"]})
    elif change == "roster":
        db.execute(update(m.Offering).where(m.Offering.id == "o1").values(roster_revision=1))
    elif change == "offering":
        db.execute(update(m.Offering).where(m.Offering.id == "o1").values(revision=2))
    else:
        db.execute(update(m.Offering).where(m.Offering.id == "o1").values(state="archived"))
    db.commit()
    error(lambda: apply(writes_case, p), "lifecycle_conflict" if change == "archive" else "preview_stale", 409)
    assert counts(db, m) == (1, 1) and db.query(m.Enrollment).filter_by(offering_id="o1", status="active").count() == 4


@pytest.mark.parametrize("actor,offering,missing", [("co", "o1", False), ("owner", "draft", False), ("owner", "o1", True)])
def test_preview_footprint_is_scope_actor_filtered_before_target_access(writes_case, monkeypatch, actor, offering, missing):
    db, w, _, m, _ = writes_case
    p = preview(writes_case, command(["learner"], mode="replace"))
    captured = []
    original = w._locked_account
    def account(session, subject):
        captured.append(subject)
        return original(session, subject)
    monkeypatch.setattr(w, "_locked_account", account)
    roster = feature("app.services.teaching.rosters")
    error(lambda: roster.apply_roster(db, actor, offering, confirmation(p, preview_id="missing" if missing else p.result["id"]), "foreign-preview:123"), "not_found", 404)
    assert captured == [] and counts(db, m) == (1, 1)


def test_valid_preview_full_footprint_precedes_locks_and_final_clock(writes_case, monkeypatch):
    db, w, _, _, _ = writes_case
    p = preview(writes_case, command([], mode="replace"))
    order = []
    for name in ("_preview_footprint", "_locked_account", "_preview_row", "_server_clock"):
        original = getattr(w, name)
        def traced(*args, _name=name, _original=original, **kwargs):
            result = _original(*args, **kwargs)
            order.append((_name, kwargs.get("lock"), getattr(result, "relationship_subject_ids", None)))
            return result
        monkeypatch.setattr(w, name, traced)
    apply(writes_case, p)
    footprint = next(item for item in order if item[0] == "_preview_footprint")
    assert set(footprint[2]) == {"learner", "assistant", "teacherlearner", "revoked"}
    first_account = next(i for i, item in enumerate(order) if item[0] == "_locked_account")
    assert order.index(footprint) < first_account
    locked_preview = next(i for i, item in enumerate(order) if item[:2] == ("_preview_row", True))
    clock = next(i for i, item in enumerate(order) if item[0] == "_server_clock")
    assert first_account < locked_preview < clock


def test_accepted_application_replays_with_expired_preview_and_deleted_target(writes_case, monkeypatch):
    db, w, _, m, a = writes_case
    p = preview(writes_case, command(["learner"], mode="replace"))
    accepted = apply(writes_case, p)
    db.execute(delete(a.UserAccount).where(a.UserAccount.username == "learner")); db.commit()
    monkeypatch.setattr(w, "_server_clock", lambda session: NOW + timedelta(minutes=11))
    recovered = apply(writes_case, p)
    assert recovered.replayed and recovered.receipt.id == accepted.receipt.id and recovered.result == accepted.result
    error(lambda: apply(writes_case, p, key="new-application:123"), "preview_stale", 409)
    assert db.get(a.UserAccount, "learner") is None and counts(db, m) == (2, 2)


def test_preview_expiry_uses_post_lock_clock_and_same_accepted_key_still_recovers(writes_case, monkeypatch):
    db, w, _, m, _ = writes_case
    p = preview(writes_case)
    monkeypatch.setattr(w, "_server_clock", lambda session: NOW + timedelta(minutes=10))
    error(lambda: apply(writes_case, p), "preview_stale", 409)
    assert counts(db, m) == (1, 1)
    monkeypatch.setattr(w, "_server_clock", lambda session: NOW + timedelta(minutes=9, seconds=59))
    accepted = apply(writes_case, p)
    monkeypatch.setattr(w, "_server_clock", lambda session: NOW + timedelta(minutes=10))
    assert apply(writes_case, p).receipt.id == accepted.receipt.id


@pytest.mark.parametrize("revocation", ["role", "source", "account"])
def test_current_rights_precede_accepted_roster_replay(writes_case, revocation):
    db, _, _, m, a = writes_case
    p = preview(writes_case)
    apply(writes_case, p)
    if revocation == "role":
        db.execute(update(m.TeachingRole).where(m.TeachingRole.id == "r-owner").values(status="revoked"))
    else:
        db.execute(update(a.UserAccount).where(a.UserAccount.username == "owner").values(role="student" if revocation == "source" else "admin"))
    db.commit()
    error(lambda: apply(writes_case, p), status={"role": 403, "source": 404, "account": 401}[revocation])
    assert counts(db, m) == (2, 2)


def test_full_active_status_cap_includes_expired_and_future_periods(writes_case):
    db, _, _, m, a = writes_case
    ids = seed_students(writes_case, 10000)
    db.add(a.UserAccount(username="extra", role="student", password_hash="synthetic-only")); db.commit()
    db.info["teaching_policy_provider"] = lambda: snapshot(roster={"owner": [*ids, "extra"]})
    p = preview(writes_case, command([]))
    assert p.result["target_count"] == 10000 and p.result["can_apply"]
    error(lambda: preview(writes_case, command(["extra"]), key="over-cap:123"), "roster_capacity_exceeded", 422)
    assert counts(db, m) == (1, 1) and db.get(m.Offering, "o1").roster_revision == 0


def test_over_cap_existing_set_can_be_reduced_without_slicing(writes_case):
    db, w, _, m, _ = writes_case
    ids = seed_students(writes_case, 10001)
    p = preview(writes_case, command([], mode="replace"))
    assert p.result["can_apply"] and p.result["withdrawals_count"] == 10001
    assert p.result["withdrawals_digest"] == w.digest_id_set("roster_withdrawals", ids)
    assert len(db.get(m.RosterPreview, p.result["id"]).withdraw_ids) == 10001
    result = apply(writes_case, p)
    assert result.result["withdrawn_count"] == 10001
    assert db.query(m.Enrollment).filter_by(offering_id="o1", status="active").count() == 0


def test_period_changes_list_updates_and_retain_unrequested_merge_periods(writes_case):
    db, _, _, m, _ = writes_case
    end = NOW + timedelta(days=3)
    p = preview(writes_case, command(period={"effective_from": None, "effective_until": end}))
    assert p.result["update_count"] == 1 and p.result["keep_count"] == 4
    result = apply(writes_case, p)
    assert result.result["updated_count"] == 1
    row = db.get(m.Enrollment, "e-o1-learner")
    assert row.revision == 2 and row.effective_from.replace(tzinfo=timezone.utc) == NOW and row.effective_until.replace(tzinfo=timezone.utc) == end
    assert db.get(m.Enrollment, "e-o1-assistant").revision == 1


def test_unchanged_expired_kept_period_is_not_reopened_or_rejected(writes_case):
    db, _, _, m, _ = writes_case
    db.execute(update(m.Enrollment).where(m.Enrollment.id == "e-o1-learner").values(effective_until=NOW)); db.commit()
    p = preview(writes_case)
    result = apply(writes_case, p)
    row = db.get(m.Enrollment, "e-o1-learner")
    assert result.result["updated_count"] == 0 and row.revision == 1
    assert row.effective_until.replace(tzinfo=timezone.utc) == NOW


def test_period_expiring_at_application_final_clock_rejects_all_changes(writes_case, monkeypatch):
    db, w, _, m, _ = writes_case
    p = preview(writes_case, command(period={"effective_from": NOW, "effective_until": NOW + timedelta(seconds=1)}))
    monkeypatch.setattr(w, "_server_clock", lambda session: NOW + timedelta(seconds=1))
    error(lambda: apply(writes_case, p), "effective_window_closed", 409)
    assert counts(db, m) == (1, 1) and db.get(m.Enrollment, "e-o1-learner").revision == 1


def test_changed_complete_withdrawal_set_rejected_even_with_unchanged_roster_revision(writes_case):
    db, _, _, m, _ = writes_case
    p = preview(writes_case, command([], mode="replace"))
    db.execute(update(m.Enrollment).where(m.Enrollment.id == "e-o1-learner").values(status="withdrawn")); db.commit()
    error(lambda: apply(writes_case, p), "preview_stale", 409)
    assert counts(db, m) == (1, 1)


def test_maximum_unicode_subjects_keep_preview_receipt_bounded_and_sets_complete(writes_case):
    import json
    db, w, _, m, a = writes_case
    ids = ["😀" * 252 + f"{index:03d}" for index in range(90)]
    db.add_all([a.UserAccount(username=subject, role="student", password_hash="synthetic-only") for subject in ids])
    db.execute(delete(m.Enrollment).where(m.Enrollment.offering_id == "o1"))
    for index, subject in enumerate(ids[:60]):
        db.add(m.Enrollment(id=f"wide-{index}", institution_id="school", offering_id="o1", student_id=subject,
            status="active", effective_from=NOW-timedelta(days=1), revision=1, source_kind="deployment_roster",
            source_teacher_id="owner", source_policy_digest="a"*64, created_at=NOW, updated_at=NOW))
    db.commit()
    db.info["teaching_policy_provider"] = lambda: snapshot(roster={"owner": ids})
    desired = ids[:30] + ids[60:]
    p = preview(writes_case, command(desired, mode="replace", period={"effective_from": None, "effective_until": None}))
    assert p.receipt.http_status == 201 and p.result["can_apply"]
    assert (p.result["target_count"], p.result["add_count"], p.result["keep_count"], p.result["update_count"], p.result["withdrawals_count"]) == (60, 30, 30, 30, 30)
    assert len(json.dumps(p.receipt.original_result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) <= 65536
    saved = db.get(m.RosterPreview, p.result["id"])
    assert saved.target_ids == sorted(desired) and saved.withdraw_ids == ids[30:60]
    assert p.result["target_digest"] == w.digest_id_set("roster_target", desired)
    assert p.result["withdrawals_digest"] == w.digest_id_set("roster_withdrawals", ids[30:60])
