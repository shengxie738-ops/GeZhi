"""Task5 DTO/standalone ASGI contract, no aggregate, startup or socket."""
import pytest
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

from tests.test_teaching_authorization import dbcase, NOW
from tests.test_teaching_receipts import writes_case, counts
from tests.test_teaching_courses import feature, error
from tests.test_teaching_course_role_http import app_for, request, sync_asgi
from tests.test_teaching_rosters import command, confirmation


@sync_asgi
async def test_preview_apply_read_and_paging_routes_keep_no_store_original_receipts(writes_case, monkeypatch):
    db, _, _, m, _ = writes_case
    app, _ = app_for(writes_case)
    original, commits = db.commit, []
    def commit():
        original(); commits.append(True)
    monkeypatch.setattr(db, "commit", commit)
    created = await request(app, "POST", "/api/teaching/offerings/o1/roster-previews", json=command([], mode="replace"))
    assert created.status_code == 201, created.text
    data = created.json()["data"]
    pid = data["result"]["id"]
    assert not data["replayed"] and data["result"]["withdrawals_count"] == 4
    saved = await request(app, "GET", f"/api/teaching/offerings/o1/roster-previews/{pid}")
    assert saved.status_code == 200 and saved.json()["data"]["id"] == pid
    page = await request(app, "GET", f"/api/teaching/offerings/o1/roster-previews/{pid}/changes?kind=withdraw&limit=2")
    assert page.status_code == 200 and len(page.json()["data"]["items"]) == 2 and page.json()["data"]["total_count"] == 4
    payload = {"preview_id": pid, "expected_roster_revision": 0,
        "confirmed_withdrawals_digest": data["result"]["withdrawals_digest"], "confirmed_withdrawals_count": 4}
    accepted = await request(app, "POST", "/api/teaching/offerings/o1/roster-applications", key="http-apply:123", json=payload)
    replay = await request(app, "POST", "/api/teaching/offerings/o1/roster-applications", key="http-apply:123", json=payload)
    assert accepted.status_code == replay.status_code == 200
    assert accepted.json()["data"]["result"]["withdrawn_count"] == 4
    assert replay.json()["data"]["replayed"] and replay.json()["data"]["receipt"] == accepted.json()["data"]["receipt"]
    for response in [created, saved, page, accepted, replay]:
        assert response.json()["code"] == response.status_code and response.headers["cache-control"] == "no-store"
        assert "password_hash" not in response.text and "phone" not in response.text and "trusted_roster" not in response.text
    assert counts(db, m) == (2, 2) and len(commits) == 3


@pytest.mark.parametrize("dto,payload", [
    ("RosterPreviewCommand", command(actor_id="other")),
    ("RosterPreviewCommand", command(owner_id="other")),
    ("RosterPreviewCommand", command(institution_id="forged")),
    ("RosterPreviewCommand", command(expected_roster_revision=True)),
    ("RosterPreviewCommand", command(["learner\x00"])),
    ("RosterPreviewCommand", command([" learner"])),
    ("RosterPreviewCommand", command(["x"*256])),
    ("RosterPreviewCommand", command(["learner"]*10001)),
    ("RosterPreviewCommand", command(mode="truncate")),
    ("RosterPreviewCommand", command(period={"effective_from": "2026-10-03T12:00:00", "effective_until": None})),
    ("RosterPreviewCommand", command(period={"effective_from": "2026-10-03T12:00:00+08:00"})),
    ("RosterPreviewCommand", command(period={"effective_from": "2026-10-03T12:00:00Z", "effective_until": "2026-10-03T12:00:00Z"})),
    ("RosterPreviewCommand", command(period={"effective_from": None, "actor_id": "other"})),
    ("RosterApplicationCommand", {"preview_id": "p", "expected_roster_revision": 0, "confirmed_withdrawals_count": True, "confirmed_withdrawals_digest": "a"*64}),
    ("RosterApplicationCommand", {"preview_id": "p", "expected_roster_revision": 0, "confirmed_withdrawals_count": 0, "confirmed_withdrawals_digest": "wrong"}),
    ("RosterApplicationCommand", {"preview_id": "p", "expected_roster_revision": 0, "confirmed_withdrawals_count": 0, "confirmed_withdrawals_digest": "a"*64, "confirmed_withdrawals": []}),
])
def test_strict_roster_commands_reject_authority_extras_and_malformed_input(dto, payload):
    cls = getattr(feature("app.schemas.teaching"), dto, None)
    assert cls is not None, f"Task5 DTO missing: {dto}"
    with pytest.raises(ValidationError):
        cls.model_validate(payload)


@sync_asgi
@pytest.mark.parametrize("suffix,payload", [
    ("roster-previews", command(actor_id="other")),
    ("roster-previews", command(["learner\n"])),
    ("roster-applications", {"preview_id": "p", "expected_roster_revision": 0, "confirmed_withdrawals": []}),
])
async def test_roster_http_422_is_atomic_and_no_store(writes_case, suffix, payload):
    app, _ = app_for(writes_case)
    response = await request(app, "POST", f"/api/teaching/offerings/o1/{suffix}", json=payload)
    assert response.status_code == 422 and response.json() == {"code": 422, "message": "validation_error", "data": None}
    assert response.headers["cache-control"] == "no-store" and counts(writes_case[0], writes_case[3]) == (0, 0)


@sync_asgi
@pytest.mark.parametrize("actor,offering", [("co", "o1"), ("owner", "draft"), ("owner", "missing")])
async def test_roster_preview_reads_hide_actor_and_scope_substitution(writes_case, actor, offering):
    from tests.test_teaching_rosters import preview
    p = preview(writes_case)
    app, _ = app_for(writes_case)
    response = await request(app, "GET", f"/api/teaching/offerings/{offering}/roster-previews/{p.result['id']}", actor=actor)
    assert response.status_code == 404 and response.json() == {"code": 404, "message": "not_found", "data": None}


@sync_asgi
@pytest.mark.parametrize("committed", [False, True])
async def test_roster_commit_ambiguity_preserves_same_intent_recovery(writes_case, monkeypatch, committed):
    db, _, _, m, _ = writes_case
    app, _ = app_for(writes_case)
    original = db.commit
    def uncertain():
        if committed:
            original()
        raise OperationalError("synthetic commit", {}, RuntimeError("private transport"))
    monkeypatch.setattr(db, "commit", uncertain)
    response = await request(app, "POST", "/api/teaching/offerings/o1/roster-previews", json=command())
    assert response.status_code == 503 and response.json()["message"] == "write_outcome_unknown"
    assert response.json()["data"] == {"recovery": {"action": "roster_manage", "scope_type": "offering", "scope_id": "o1", "key": "http-original:123"}}
    assert counts(db, m) == ((1, 1) if committed else (0, 0))


@pytest.mark.parametrize("boundary", ["default_off", "schema", "transaction", "hard_gate"])
def test_real_unpatched_boundary_still_refuses_roster_writes(dbcase, monkeypatch, boundary):
    db, access, _, m, _, readiness = dbcase
    w = feature("app.services.teaching.writes")
    if boundary != "transaction":
        monkeypatch.setattr(w, "_require_transaction", lambda session: None)
    if boundary == "default_off":
        db.info.pop("teaching_policy_provider")
    elif boundary == "schema":
        monkeypatch.setattr(access, "require_teaching_schema", readiness)
    roster = feature("app.services.teaching.rosters")
    reasons = {"default_off": "feature_disabled", "schema": "teaching_schema_incompatible", "transaction": "lock_orchestration_required", "hard_gate": "write_safety_unproven"}
    error(lambda: roster.preview_roster(db, "owner", "o1", command(), "unpatched-gate:123"), reasons[boundary], 503)
    assert counts(db, m) == (0, 0)
