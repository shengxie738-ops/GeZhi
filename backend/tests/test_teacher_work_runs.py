"""Seven finite pure chat-run decisions; no executor, provider, lease store or workflow."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import importlib
from pathlib import Path
from uuid import UUID

import pytest

from app.schemas.teacher_work import ChatCommand, RunDTO
from app.services.teacher_work.types import WorkContext, canonical_digest


BACKEND = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 5, tzinfo=timezone.utc)
TASK = UUID("60000000-0000-0000-0000-000000000001")
OTHER = UUID("60000000-0000-0000-0000-000000000002")
RUN = UUID("70000000-0000-0000-0000-000000000001")
RUN2 = UUID("70000000-0000-0000-0000-000000000002")
PROCESS = UUID("80000000-0000-0000-0000-000000000001")
PROCESS2 = UUID("80000000-0000-0000-0000-000000000002")
NAMESPACE = UUID("10000000-0000-0000-0000-000000000001")
NAMESPACE2 = UUID("10000000-0000-0000-0000-000000000002")
CTX = WorkContext("A", NAMESPACE, TASK, None, None, 1, 1)


def _module():
    assert (BACKEND / "app/services/teacher_work/runs.py").is_file(), "Task4a pure run decisions are missing"
    return importlib.import_module("app.services.teacher_work.runs")


def command(text="实际合成请求", *, revision=1, client_key="消息键 "):
    return ChatCommand(kind="chat", input_revision=revision, skill_ref=None,
        payload={"text": text, "client_message_key": client_key})


def run(**changes):
    values = dict(run_id=RUN, owner="A", task_id=TASK, kind="chat", skill_ref=None, input_revision=1,
        idempotency_key="幂等é ", request_digest=canonical_digest(command().model_dump(mode="json")),
        stage="CHAT_RUNNING", attempt=1, provider_call_count=1, deadline=NOW + timedelta(seconds=90))
    values.update(changes)
    return RunDTO(**values)


def lease(module, **changes):
    values = dict(owner="A", owner_storage_id=NAMESPACE, active_run_id=RUN, process_instance=PROCESS,
                  expires_at=NOW + timedelta(seconds=120), revision=1)
    values.update(changes)
    return module.OwnerLeaseFacts(**values)


def failure(module, code, operation):
    with pytest.raises(module.WorkRunError) as caught:
        operation()
    assert caught.value.code == code
    return caught.value


def test_chat_request_exact_key_digest_decision():
    module = _module()
    original = command()
    stored = run()
    digest = module.chat_request_digest(original)
    assert digest == canonical_digest(original.model_dump(mode="json")) == stored.request_digest
    assert module.match_chat_replay(CTX, original, "幂等é ", stored) is stored
    assert module.match_chat_replay(CTX, original, "另一键", None) is None
    for changed in (command("新请求"), command(revision=2), command(client_key="消息键")):
        assert failure(module, "IDEMPOTENCY_CONFLICT", lambda: module.match_chat_replay(CTX, changed, "幂等é ", stored)).status_code == 409
    for header in ("幂等é", "幂等e\u0301 "):
        failure(module, "RUN_RECEIPT_MISMATCH", lambda: module.match_chat_replay(CTX, original, header, stored))
    for wrong in (run(owner="B"), run(task_id=OTHER), run(kind="outline", skill_ref="lesson_outline@1")):
        failure(module, "RUN_SCOPE_MISMATCH", lambda: module.match_chat_replay(CTX, original, "幂等é ", wrong))
    failure(module, "INVALID_MESSAGE_KEY", lambda: module.match_chat_replay(CTX, original, "\n", None))
    assert module.chat_request_digest(original) == digest  # The separate header is never injected into the command.


def test_chat_budget_attempts_calls_and_repair():
    module = _module()
    budget = module.WorkBudget()
    budget.consume_ai_call()  # A reservation is charged before any later dispatch/outcome exists.
    assert (budget.attempt, budget.provider_call_count, budget.repair_count) == (1, 1, 0)
    budget.advance_attempt()
    assert (budget.attempt, budget.provider_call_count, budget.repair_count) == (2, 1, 0)
    budget.consume_ai_call(repair=True)
    before = (budget.attempt, budget.provider_call_count, budget.repair_count)
    failure(module, "REPAIR_BUDGET_EXHAUSTED", lambda: budget.consume_ai_call(repair=True))
    assert (budget.attempt, budget.provider_call_count, budget.repair_count) == before
    budget.consume_ai_call()
    before = (budget.attempt, budget.provider_call_count, budget.repair_count)
    failure(module, "AI_CALL_BUDGET_EXHAUSTED", budget.consume_ai_call)
    failure(module, "ATTEMPT_BUDGET_EXHAUSTED", budget.advance_attempt)
    assert (budget.attempt, budget.provider_call_count, budget.repair_count) == before == (2, 3, 1)
    for invalid in (dict(attempt=True), dict(attempt=0), dict(attempt=3), dict(provider_call_count=-1),
                    dict(provider_call_count=4), dict(provider_call_count=True), dict(repair_count=2),
                    dict(repair_count=-1), dict(repair_count=True), dict(repair_count=1, provider_call_count=0)):
        failure(module, "INVALID_BUDGET", lambda: module.WorkBudget(**invalid))


def test_chat_transport_limit_decisions():
    module = _module()
    low = module.chat_call_limits(512, 5, deadline=NOW + timedelta(seconds=100), now=NOW)
    assert (low.max_output_tokens, low.timeout_seconds) == (512, 5)
    high = module.chat_call_limits(10000, 200, deadline=NOW + timedelta(seconds=100), now=NOW)
    assert (high.max_output_tokens, high.timeout_seconds) == (8192, 90)
    short = module.chat_call_limits(10000, 200, deadline=NOW + timedelta(seconds=1, microseconds=900000), now=NOW)
    assert short.timeout_seconds == 1
    for seconds in (0, 0.99, -1):
        failure(module, "CHAT_DEADLINE_EXPIRED", lambda: module.chat_call_limits(100, 5, deadline=NOW + timedelta(seconds=seconds), now=NOW))
    for tokens, timeout in ((0, 5), (-1, 5), (True, 5), (100, 0), (100, -1), (100, True)):
        failure(module, "INVALID_CALL_LIMITS", lambda: module.chat_call_limits(tokens, timeout, deadline=NOW + timedelta(seconds=100), now=NOW))
    failure(module, "INVALID_CALL_LIMITS", lambda: module.chat_call_limits(100, 5, deadline=NOW + timedelta(seconds=100), now=NOW.replace(tzinfo=None)))


def test_chat_cancel_holds_inflight_lease():
    module = _module()
    original = run()
    cancelled = module.cancel_chat_run(original, now=NOW)
    assert cancelled.stage == "CANCELLED" and cancelled.cancelled_at == NOW
    assert cancelled.run_id == original.run_id and cancelled.request_digest == original.request_digest
    assert (cancelled.attempt, cancelled.provider_call_count, cancelled.deadline) == (original.attempt, original.provider_call_count, original.deadline)
    assert module.cancel_chat_run(cancelled, now=NOW + timedelta(seconds=5)) is cancelled
    assert module.can_release_chat_lease(cancelled, call_in_flight=True) is False
    assert module.can_release_chat_lease(cancelled, call_in_flight=False) is True
    assert module.can_release_chat_lease(original, call_in_flight=False) is False
    complete = run(stage="COMPLETE")
    assert module.cancel_chat_run(complete, now=NOW) is complete
    assert module.can_release_chat_lease(complete, call_in_flight=True) is False
    assert module.can_release_chat_lease(complete, call_in_flight=False) is True


def test_chat_commit_rejects_stale_or_missing_authority():
    module = _module()
    original, active = run(), lease(module)
    fresh = replace(CTX, working_revision=2)
    assert module.check_chat_commit(CTX, original, active, fresh, process_instance=PROCESS, now=NOW) is fresh
    variants = [(run(cancelled_at=NOW), active, fresh, PROCESS, NOW, "RUN_CANCELLED"),
        (run(stage="COMPLETE"), active, fresh, PROCESS, NOW, "RUN_NOT_ACTIVE"),
        (original, active, fresh, PROCESS, original.deadline, "RUN_DEADLINE_EXPIRED"),
        (original, lease(module, expires_at=NOW), fresh, PROCESS, NOW, "OWNER_LEASE_LOST"),
        (original, lease(module, active_run_id=RUN2), fresh, PROCESS, NOW, "OWNER_LEASE_LOST"),
        (original, active, fresh, PROCESS2, NOW, "OWNER_LEASE_LOST"),
        (original, lease(module, owner_storage_id=NAMESPACE2), fresh, PROCESS, NOW, "OWNER_LEASE_LOST"),
        (run(input_revision=2), active, fresh, PROCESS, NOW, "STALE_INPUT_REVISION"),
        (original, active, replace(fresh, input_revision=2), PROCESS, NOW, "STALE_INPUT_REVISION"),
        (original, active, replace(fresh, institution_id="institution-1", offering_id=OTHER), PROCESS, NOW, "CURRENT_SCOPE_CHANGED"),
        (original, active, replace(fresh, actor_subject="B"), PROCESS, NOW, "CURRENT_SCOPE_CHANGED"),
        (original, active, replace(fresh, owner_storage_id=NAMESPACE2), PROCESS, NOW, "CURRENT_SCOPE_CHANGED"),
        (original, active, replace(fresh, task_id=OTHER), PROCESS, NOW, "CURRENT_SCOPE_CHANGED"),
        (original, active, None, PROCESS, NOW, "CURRENT_AUTHORITY_UNAVAILABLE")]
    for candidate, observed_lease, current, process, now, code in variants:
        failure(module, code, lambda: module.check_chat_commit(CTX, candidate, observed_lease, current, process_instance=process, now=now))


def test_chat_owner_lease_and_instance_busy():
    module = _module()
    inactive = lease(module, active_run_id=None, process_instance=None, expires_at=None)
    assert module.require_owner_lease_available(CTX, inactive) is None
    for observed in (lease(module, active_run_id=RUN2), lease(module, active_run_id=RUN2, expires_at=NOW - timedelta(seconds=1))):
        assert failure(module, "OWNER_RUN_BUSY", lambda: module.require_owner_lease_available(CTX, observed)).status_code == 409
    failure(module, "OWNER_NAMESPACE_UNAVAILABLE", lambda: module.require_owner_lease_available(CTX, None))
    for observed in (lease(module, owner="B"), lease(module, owner_storage_id=NAMESPACE2)):
        failure(module, "OWNER_NAMESPACE_MISMATCH", lambda: module.require_owner_lease_available(CTX, observed))
    failure(module, "INVALID_LEASE", lambda: lease(module, active_run_id=None))
    assert module.require_chat_slot(3) is None
    assert failure(module, "INSTANCE_BUSY", lambda: module.require_chat_slot(4)).status_code == 429
    for count, limit in ((-1, 4), (True, 4), (0, 0), (0, True)):
        failure(module, "INVALID_SLOT_FACTS", lambda: module.require_chat_slot(count, limit=limit))


def test_chat_restart_interrupts_expired_dead_process_only():
    module = _module()
    original, expired = run(), lease(module, expires_at=NOW - timedelta(seconds=1))
    interrupted = module.interrupt_expired_chat_run(original, expired, now=NOW, process_alive=False)
    assert interrupted.stage == "INTERRUPTED" and interrupted.error_code == "PROCESS_INTERRUPTED"
    assert interrupted.model_dump(exclude={"stage", "error_code"}) == original.model_dump(exclude={"stage", "error_code"})
    assert expired.owner_storage_id == NAMESPACE and expired.active_run_id == RUN and expired.revision == 1
    assert module.interrupt_expired_chat_run(original, expired, now=NOW, process_alive=True) is original
    assert module.interrupt_expired_chat_run(original, lease(module), now=NOW, process_alive=False) is original
    for stage in ("COMPLETE", "FAILED", "CANCELLED", "INTERRUPTED"):
        terminal = run(stage=stage)
        assert module.interrupt_expired_chat_run(terminal, expired, now=NOW, process_alive=False) is terminal
    failure(module, "OWNER_LEASE_LOST", lambda: module.interrupt_expired_chat_run(original,
        lease(module, active_run_id=RUN2, expires_at=NOW - timedelta(seconds=1)), now=NOW, process_alive=False))
