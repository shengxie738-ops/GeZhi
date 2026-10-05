"""Task4b2A profile A: eight production-coordinator cases, UNEXECUTED.

Only a separately released finite snapshot may execute this source. The ports
below record exact row operations; they contain no chat workflow, provider,
request-owner finalizer or admission/replay side-effect probes. Snapshot restore
is a recording caller transaction, not evidence of physical SQL atomicity.
"""
from __future__ import annotations

import ast
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import fields, replace
from datetime import datetime, timedelta, timezone
import importlib
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest


BACKEND = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 5, tzinfo=timezone.utc)
NS = UUID("10000000-0000-0000-0000-000000000001")
OTHER_NS = UUID("10000000-0000-0000-0000-000000000002")
TASK = UUID("20000000-0000-0000-0000-000000000001")
OTHER_TASK = UUID("20000000-0000-0000-0000-000000000002")
PROCESS = UUID("30000000-0000-0000-0000-000000000001")
OTHER_PROCESS = UUID("30000000-0000-0000-0000-000000000002")
REF = UUID("40000000-0000-0000-0000-000000000001")
OTHER_REF = UUID("40000000-0000-0000-0000-000000000002")
OFFERING = UUID("50000000-0000-0000-0000-000000000001")
METHODS = frozenset({"inspect_chat_request", "admit_chat", "get_chat_run",
    "reserve_chat_call", "complete_chat_call", "fail_chat_call",
    "expire_chat_call", "fail_pending_chat", "cancel_chat"})


def _load():
    # This assertion is intentionally before every product/dependency import.
    # Missing feature, not an absent import or a database/environment error, is RED.
    tree = ast.parse((BACKEND / "app/repositories/teacher_work.py").read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef)
               and node.name == "TeacherWorkRepository")
    present = {node.name for node in cls.body if isinstance(node, ast.FunctionDef)}
    assert METHODS <= present, "Task4b2A durable ordinary-chat repository commands are missing"
    persistence = ast.parse((BACKEND / "app/services/teacher_work/run_persistence.py").read_text(encoding="utf-8"))
    names = {node.name for node in persistence.body if isinstance(node, ast.ClassDef)}
    assert {"ChatRunAdmission", "ChatRequestObservation", "ChatCallReservation", "ChatRunOutcome"} <= names, "Task4b2A uncommitted chat records are missing"
    return SimpleNamespace(
        repository=importlib.import_module("app.repositories.teacher_work"),
        persistence=importlib.import_module("app.services.teacher_work.run_persistence"),
        runs=importlib.import_module("app.services.teacher_work.runs"),
        schema=importlib.import_module("app.schemas.teacher_work"),
        types=importlib.import_module("app.services.teacher_work.types"))


class PrimitiveFailure(Exception):
    """Allowlisted synthetic primitive fault; never a provider response."""


class RecordingChatPorts:
    """Exact task/draft/run/message/lease primitives plus caller UoW.

    CAS compares complete supplied records, not business transition rules.
    Authorize returns synthetic current facts or a controlled denial. Each
    transaction explicitly starts, owns and restores its own recording state.
    """
    def __init__(self, modules, *, offering=False):
        self.m = modules
        self.active = False
        self.now = NOW
        self.role = "teacher"
        self.subject = "A"
        self.namespace = NS
        self.offering_allowed = True
        self.events = []
        self.writes = 0
        self.fail_at = None
        self.uuid_no = 1
        self.tasks = {}
        self.drafts = {}
        self.run_states = {}
        self.messages = {}
        self.completions = {}
        self.leases = {"A": modules.runs.OwnerLeaseFacts("A", NS, None, None, None, 1)}
        for task_id, draft_id in ((TASK, "draft-1"), (OTHER_TASK, "draft-2")):
            task = modules.schema.WorkTaskDTO(task_id=task_id, owner_subject="A", owner_storage_id=NS,
                institution_id="institution-1" if offering else None,
                offering_id=OFFERING if offering else None, title="合成任务", topic="合成主题",
                audience="合成对象", duration_minutes=45, target_slide_count=8,
                lesson_draft_id=draft_id, input_revision=1, working_revision=1,
                created_at=NOW, updated_at=NOW)
            self.tasks[task_id] = modules.repository.TaskRecord(task, None, None)
            self.drafts[("A", draft_id)] = modules.repository.DraftRecord("A", draft_id,
                {"draft_id": draft_id, "content": {"title": "原草稿"}, "resource_ids": ["public-1"]})

    def snapshot(self):
        return deepcopy((self.tasks, self.drafts, self.run_states, self.messages,
                         self.completions, self.leases, self.writes))

    @contextmanager
    def transaction(self):
        assert self.active is False
        saved = self.snapshot()
        self.active = True
        self.events.append("caller.begin")
        try:
            yield self
        except BaseException:
            (self.tasks, self.drafts, self.run_states, self.messages,
             self.completions, self.leases, self.writes) = saved
            self.events.append("caller.rollback")
            raise
        else:
            self.events.append("caller.commit")
        finally:
            self.active = False
            self.events.append("caller.close")

    def in_transaction(self):
        return self.active

    def commit(self):
        raise AssertionError("the repository must never finalize the caller root")

    def flush(self):
        assert self.active
        self.events.append("flush")
        if self.fail_at == "flush":
            raise PrimitiveFailure("synthetic flush failure")

    def clock(self):
        return self.now

    def new_uuid(self):
        value = UUID(int=0x60000000000000000000000000000000 + self.uuid_no)
        self.uuid_no += 1
        return value

    def authorize_locked(self, owner, offering_id, institution_id):
        assert self.active
        self.events.append("footprint")
        if owner != self.subject:
            raise self.m.repository.WorkRepositoryError("NOT_FOUND", 404)
        if self.role != "teacher":
            raise self.m.repository.WorkRepositoryError("CURRENT_TEACHER_REQUIRED", 403)
        if offering_id is not None and not self.offering_allowed:
            raise self.m.repository.WorkRepositoryError("OFFERING_AUTHORITY_REQUIRED", 403)
        actor = self.m.types.WorkActor(self.subject, "teacher", self.namespace)
        return self.m.repository.AuthorizedWorkScope(actor, institution_id, offering_id)

    def lock_owner_lease(self, owner):
        assert self.active
        self.events.append("lease.lock")

    def owner_storage_ids(self, owner):
        return (self.leases[owner].owner_storage_id,)

    def find_task(self, owner, task_id):
        self.events.append("task.discover")
        row = self.tasks.get(task_id)
        return row if row is not None and row.task.owner_subject == owner else None

    def lock_draft(self, owner, draft_id):
        self.events.append("draft.lock")
        return self.drafts.get((owner, draft_id))

    def lock_task(self, owner, task_id):
        self.events.append("task.lock")
        row = self.tasks.get(task_id)
        return row if row is not None and row.task.owner_subject == owner else None

    def lease(self, owner):
        self.events.append("lease.read")
        return self.leases[owner]

    def find_run_by_key(self, owner, task_id, kind, encoded_key):
        assert type(encoded_key) is bytes
        self.events.append("run.receipt")
        return next((state for state in self.run_states.values()
            if (state.run.owner, state.run.task_id, state.run.kind,
                state.run.idempotency_key.encode("utf-8")) == (owner, task_id, kind, encoded_key)), None)

    def lock_run(self, owner, task_id, run_id):
        self.events.append("run.lock")
        state = self.run_states.get(run_id)
        return state if state is not None and (state.run.owner, state.run.task_id) == (owner, task_id) else None

    def find_user_message(self, owner, task_id, encoded_key):
        assert type(encoded_key) is bytes
        self.events.append("message.user.read")
        return next((message for message in self.messages.values()
            if (message.owner, message.task_id, message.role) == (owner, task_id, "user")
            and message.client_message_key is not None
            and message.client_message_key.encode("utf-8") == encoded_key), None)

    def find_completion(self, owner, task_id, run_id):
        self.events.append("message.completion.read")
        pair = self.completions.get(run_id)
        return pair if pair is not None and (pair[1].owner, pair[1].task_id) == (owner, task_id) else None

    def insert_run(self, state):
        assert self.active and state.run.run_id not in self.run_states
        self.events.append("run.insert")
        self.run_states[state.run.run_id] = deepcopy(state)
        self.writes += 1

    def insert_user_message(self, message):
        assert self.active and message.message_id not in self.messages
        self.events.append("message.user.insert")
        self.messages[message.message_id] = deepcopy(message)
        self.writes += 1

    def insert_completion(self, message, receipt):
        assert self.active and receipt.run_id not in self.completions
        assert message.message_id not in self.messages
        self.events.append("message.completion.insert")
        self.messages[message.message_id] = deepcopy(message)
        self.completions[receipt.run_id] = deepcopy((receipt, message))
        self.writes += 1
        if self.fail_at == "message.completion.insert":
            raise PrimitiveFailure("synthetic completion insert failure")

    def cas_run(self, before, after):
        assert self.active
        self.events.append("run.cas")
        if self.fail_at == "run.cas" or self.run_states.get(before.run.run_id) != before:
            return False
        self.run_states[before.run.run_id] = deepcopy(after)
        self.writes += 1
        return True

    def cas_lease(self, before, after):
        assert self.active
        self.events.append("lease.cas")
        if self.fail_at == "lease.cas" or self.leases.get(before.owner) != before:
            return False
        self.leases[before.owner] = deepcopy(after)
        self.writes += 1
        return True


def _setup(*, offering=False, run_rows=True):
    modules = _load()
    ports = RecordingChatPorts(modules, offering=offering)
    kwargs = dict(uow=ports, rows=ports, drafts=ports, authorize_locked=ports.authorize_locked,
                  clock=ports.clock, new_uuid=ports.new_uuid)
    if run_rows:
        kwargs["run_rows"] = ports
    return modules, modules.repository.TeacherWorkRepository(**kwargs), ports


def _command(modules, *, text="教师输入\n保留 Unicode 与末尾空格 ", client_key="用户 Key ", revision=1):
    return modules.schema.ChatCommand(kind="chat", input_revision=revision, skill_ref=None,
        payload=modules.schema.ChatInput(text=text, client_message_key=client_key))


def _admit(modules, repository, ports, *, task_id=TASK, key="运行 Key ", command=None):
    with ports.transaction():
        return repository.admit_chat("A", task_id, command or _command(modules), key,
                                    process_instance=PROCESS, configured_timeout_seconds=90)


def _reserve(repository, ports, admission, *, repair=False, tokens=12000, timeout=200):
    with ports.transaction():
        return repository.reserve_chat_call("A", admission.task.task_id, admission.state.run.run_id,
            process_instance=PROCESS, configured_output_tokens=tokens,
            configured_timeout_seconds=timeout, repair=repair)


def _result(modules, **changes):
    return modules.schema.ChatResult(**{"type": "revision_proposal",
        "plain_text": "实际模型候选\nUnicode 内容与末尾空格 ", "result_refs": (REF,),
        "omitted_context": True, **changes})


def _complete(modules, repository, ports, reservation, *, result=None):
    with ports.transaction():
        return repository.complete_chat_call(reservation.context, reservation.token,
            result or _result(modules), allowed_result_refs=frozenset({REF}), omitted_context=True)


def _reject(ports, action, *, code=None, statuses=(403, 404, 409, 422, 503)):
    before = ports.snapshot()
    with pytest.raises(Exception) as caught:
        with ports.transaction():
            action()
    assert getattr(caught.value, "status_code", None) in statuses
    if code is not None:
        assert caught.value.code == code
    assert ports.snapshot() == before
    return caught.value


def test_chat_admission_one_user_run_lease_and_exact_replay():
    # Catches allocation before authorized receipt lookup, key normalization and duplicate rows.
    m, repository, ports = _setup()
    command = _command(m)
    admitted = _admit(m, repository, ports, command=command)
    state, user, lease = admitted.state, admitted.user_message, admitted.lease
    assert admitted.created is True and isinstance(admitted, m.persistence.ChatRunAdmission)
    assert len(ports.run_states) == len(ports.messages) == 1
    assert (state.run.stage, state.run.attempt, state.run.provider_call_count, state.repair_count, state.active_call) == ("PENDING", 1, 0, 0, None)
    assert state.run.deadline == NOW + timedelta(seconds=270)
    # Independently hand-derived SHA-256 of the literal strict command fixture.
    assert state.run.request_digest == "dc8c6a858d865fc6ef01f290b998a62386a40fdd21cf9ffd1fdd02af59a9dc4c"
    assert (user.role, user.plain_text, user.client_message_key, user.run_id) == ("user", command.payload.text, "用户 Key ", state.run.run_id)
    assert user.result_type is user.omitted_context is None and ports.completions == {}
    assert (lease.owner_storage_id, lease.active_run_id, lease.process_instance, lease.revision, lease.expires_at) == (NS, state.run.run_id, PROCESS, 2, state.run.deadline)
    assert ports.events.index("footprint") < ports.events.index("lease.lock") < ports.events.index("draft.lock") < ports.events.index("task.lock") < ports.events.index("run.receipt")
    writes = ports.writes
    # Revision drift permits exact receipt observation, never a restarted call.
    original = ports.tasks[TASK]
    ports.tasks[TASK] = replace(original, task=original.task.model_copy(update={"input_revision": 2}))
    with ports.transaction():
        observed = repository.inspect_chat_request("A", TASK, command, "运行 Key ")
    replay = _admit(m, repository, ports, command=command)
    assert observed.admission.state == replay.state == state
    assert replay.created is False and ports.writes == writes
    for distinct in ("运行 Key", "运行 key ", "é", "e\u0301"):
        with ports.transaction():
            assert repository.inspect_chat_request("A", TASK, command, distinct).admission is None
    _reject(ports, lambda: repository.admit_chat("A", TASK, _command(m, text="不同内容"), "运行 Key ",
        process_instance=PROCESS, configured_timeout_seconds=90), code="IDEMPOTENCY_CONFLICT")
    ports.role = "student"
    _reject(ports, lambda: repository.inspect_chat_request("A", TASK, command, "运行 Key "), code="CURRENT_TEACHER_REQUIRED")


def test_chat_owner_and_client_key_conflicts_before_writes():
    # Catches cross-task lease bypass, client-key reuse, stale revision and corrupt replay linkage.
    m, repository, ports = _setup()
    admitted = _admit(m, repository, ports)
    _reject(ports, lambda: repository.admit_chat("A", OTHER_TASK, _command(m, client_key="other-user"), "other-run",
        process_instance=PROCESS, configured_timeout_seconds=90), code="OWNER_RUN_BUSY")
    with ports.transaction():
        repository.cancel_chat("A", TASK, admitted.state.run.run_id)
    for command in (_command(m), _command(m, text="changed input")):
        _reject(ports, lambda: repository.admit_chat("A", TASK, command, "different-run",
            process_instance=PROCESS, configured_timeout_seconds=90), code="MESSAGE_KEY_CONFLICT")
    _reject(ports, lambda: repository.admit_chat("A", TASK, _command(m, client_key="new-user", revision=2), "new-run",
        process_instance=PROCESS, configured_timeout_seconds=90), code="STALE_INPUT_REVISION")
    user = admitted.user_message
    ports.messages[user.message_id] = user.model_copy(update={"plain_text": "corrupt stored input"})
    _reject(ports, lambda: repository.inspect_chat_request("A", TASK, _command(m), "运行 Key "))
    _reject(ports, lambda: repository.get_chat_run("B", TASK, admitted.state.run.run_id), code="NOT_FOUND")
    _reject(ports, lambda: repository.get_chat_run("A", OTHER_TASK, admitted.state.run.run_id), code="NOT_FOUND")


def test_chat_call_charge_persists_cumulative_budget_and_token():
    # Catches missing durable charge/token, renewing deadline, reset budgets or upward timeout rounding.
    m, repository, ports = _setup()
    admitted = _admit(m, repository, ports)
    claimed = _reserve(repository, ports, admitted)
    assert claimed.state == ports.run_states[admitted.state.run.run_id]
    assert (claimed.state.run.stage, claimed.state.run.attempt, claimed.state.run.provider_call_count, claimed.state.repair_count) == ("CHAT_RUNNING", 1, 1, 0)
    assert claimed.token == m.persistence.ProviderCallToken(admitted.state.run.run_id, 1, 1, 2, PROCESS)
    assert claimed.state.active_call == claimed.token and claimed.lease == admitted.lease
    assert claimed.state.run.deadline == admitted.state.run.deadline
    assert (claimed.limits.max_output_tokens, claimed.limits.timeout_seconds) == (8192, 90)
    _reject(ports, lambda: repository.reserve_chat_call("A", TASK, admitted.state.run.run_id,
        process_instance=PROCESS, configured_output_tokens=8192, configured_timeout_seconds=90))
    # Supplied historical state tests the general writer; this is no retry endpoint/executor.
    for calls, repairs, attempt, repair, wanted in ((2, 0, 2, True, (3, 1, 2)), (3, 1, 2, False, None), (2, 1, 2, True, None)):
        m, repository, ports = _setup()
        admission = _admit(m, repository, ports)
        prior = admission.state.run.model_copy(update={"stage": "CHAT_RUNNING", "attempt": attempt, "provider_call_count": calls})
        ports.run_states[prior.run_id] = m.persistence.StoredRunState(prior, repairs, None)
        ports.now = prior.deadline - timedelta(seconds=1, microseconds=900000)
        if wanted is None:
            _reject(ports, lambda: repository.reserve_chat_call("A", TASK, prior.run_id,
                process_instance=PROCESS, configured_output_tokens=10, configured_timeout_seconds=90, repair=repair),
                code="AI_CALL_BUDGET_EXHAUSTED" if calls == 3 else "REPAIR_BUDGET_EXHAUSTED")
        else:
            reservation = _reserve(repository, ports, admission, repair=repair, tokens=10, timeout=20)
            assert (reservation.state.run.provider_call_count, reservation.state.repair_count, reservation.state.run.attempt) == wanted
            assert reservation.limits.timeout_seconds == 1 and reservation.limits.max_output_tokens == 10
            assert reservation.token.call_no == 3 and reservation.token.attempt == 2
            assert reservation.state.run.deadline == prior.deadline
    for tokens, timeout in ((0, 90), (True, 90), (8192, 0), (8192, True)):
        m, repository, ports = _setup()
        admission = _admit(m, repository, ports)
        _reject(ports, lambda: repository.reserve_chat_call("A", TASK, admission.state.run.run_id,
            process_instance=PROCESS, configured_output_tokens=tokens,
            configured_timeout_seconds=timeout), code="INVALID_CALL_LIMITS", statuses=(503,))


def test_chat_completion_actual_result_and_receipt_are_atomic():
    # Catches manufactured/default result metadata or partial completion on primitive failures.
    m, repository, ports = _setup()
    admission = _admit(m, repository, ports)
    reservation = _reserve(repository, ports, admission)
    outcome = _complete(m, repository, ports, reservation)
    receipt, message = ports.completions[reservation.token.run_id]
    assert outcome.completion == receipt and receipt.message_id == message.message_id
    assert (message.role, message.client_message_key, message.run_id, message.result_type,
            message.plain_text, message.result_refs, message.omitted_context) == (
        "assistant", None, reservation.token.run_id, "revision_proposal",
        "实际模型候选\nUnicode 内容与末尾空格 ", (REF,), True)
    assert outcome.state.run.stage == "COMPLETE" and outcome.state.active_call is None
    assert (outcome.state.run.provider_call_count, outcome.state.repair_count, outcome.state.run.deadline) == (1, 0, admission.state.run.deadline)
    assert (outcome.lease.owner_storage_id, outcome.lease.active_run_id, outcome.lease.process_instance,
            outcome.lease.expires_at, outcome.lease.revision) == (NS, None, None, None, 3)
    assert len(ports.messages) == 2 and ports.drafts[("A", "draft-1")].payload["content"] == {"title": "原草稿"}
    for failure in ("message.completion.insert", "run.cas", "lease.cas", "flush"):
        m, repository, ports = _setup()
        reservation = _reserve(repository, ports, _admit(m, repository, ports))
        before = ports.snapshot()
        ports.fail_at = failure
        with pytest.raises(Exception):
            _complete(m, repository, ports, reservation)
        assert ports.snapshot() == before
        assert ports.completions == {} and len(ports.messages) == 1
        assert ports.run_states[reservation.token.run_id].active_call == reservation.token


def test_chat_completion_rechecks_current_scope_revision_and_token():
    # Catches stale context authority, individual token omissions and result authority bypass.
    for denial in ("student", "namespace", "offering", "revision", "cancel", "deadline", "lease_revision"):
        m, repository, ports = _setup(offering=True)
        reservation = _reserve(repository, ports, _admit(m, repository, ports))
        if denial == "student":
            ports.role = "student"
        elif denial == "namespace":
            ports.namespace = OTHER_NS
        elif denial == "offering":
            ports.offering_allowed = False
        elif denial == "revision":
            row = ports.tasks[TASK]
            ports.tasks[TASK] = replace(row, task=row.task.model_copy(update={"input_revision": 2, "working_revision": 2}))
        elif denial == "cancel":
            with ports.transaction():
                repository.cancel_chat("A", TASK, reservation.token.run_id)
        elif denial == "deadline":
            ports.now = reservation.state.run.deadline
        else:
            ports.leases["A"] = replace(ports.leases["A"], revision=3)
        _reject(ports, lambda: repository.complete_chat_call(reservation.context, reservation.token,
            _result(m), allowed_result_refs=frozenset({REF}), omitted_context=True))
        assert ports.completions == {} and len(ports.messages) == 1
    m, repository, ports = _setup()
    reservation = _reserve(repository, ports, _admit(m, repository, ports))
    for changes in ({"run_id": OTHER_TASK}, {"attempt": 2}, {"call_no": 2},
                    {"lease_revision": 3}, {"process_instance": OTHER_PROCESS}):
        wrong = replace(reservation.token, **changes)
        _reject(ports, lambda: repository.complete_chat_call(reservation.context, wrong,
            _result(m), allowed_result_refs=frozenset({REF}), omitted_context=True))
    for result, allowed, omitted in ((_result(m), frozenset({OTHER_REF}), True),
                                     (_result(m), frozenset({REF}), False)):
        _reject(ports, lambda: repository.complete_chat_call(reservation.context, reservation.token,
            result, allowed_result_refs=allowed, omitted_context=omitted))


def test_chat_cancel_keeps_unsettled_token_and_namespace():
    # Catches releasing an in-flight or expired token, namespace deletion and content after cancel.
    m, repository, ports = _setup()
    admission = _admit(m, repository, ports)
    reservation = _reserve(repository, ports, admission)
    ports.now = reservation.state.run.deadline + timedelta(seconds=1)
    with ports.transaction():
        cancelled = repository.cancel_chat("A", TASK, reservation.token.run_id)
    assert cancelled.state.run.stage == "CANCELLED" and cancelled.state.run.cancelled_at == ports.now
    assert cancelled.state.active_call == reservation.token and cancelled.lease == reservation.lease
    first_cancelled = cancelled.state.run.cancelled_at
    ports.now += timedelta(seconds=10)
    with ports.transaction():
        repeated = repository.cancel_chat("A", TASK, reservation.token.run_id)
    assert repeated.state.run.cancelled_at == first_cancelled
    # A legitimate content revision may not prevent exact non-content settlement.
    row = ports.tasks[TASK]
    ports.tasks[TASK] = replace(row, task=row.task.model_copy(update={"input_revision": 2, "working_revision": 2}))
    with ports.transaction():
        settled = repository.fail_chat_call(reservation.context, reservation.token, "WORK_AI_TIMEOUT")
    assert settled.state.run.stage == "CANCELLED" and settled.state.run.cancelled_at == first_cancelled
    assert settled.state.active_call is None and settled.lease.active_run_id is None
    assert settled.lease.owner_storage_id == NS and settled.lease.revision == 3
    assert settled.state.run.provider_call_count == 1 and ports.completions == {}
    m, repository, ports = _setup()
    admission = _admit(m, repository, ports)
    with ports.transaction():
        pending = repository.cancel_chat("A", TASK, admission.state.run.run_id)
    assert pending.state.run.stage == "CANCELLED" and pending.state.active_call is None
    assert pending.lease.active_run_id is None and pending.lease.owner_storage_id == NS and pending.lease.revision == 3
    m, repository, ports = _setup()
    reservation = _reserve(repository, ports, _admit(m, repository, ports))
    _reject(ports, lambda: repository.expire_chat_call(reservation.context, reservation.token))
    ports.now = reservation.state.run.deadline
    with ports.transaction():
        expired = repository.expire_chat_call(reservation.context, reservation.token)
    assert (expired.state.run.stage, expired.state.run.error_code) == ("FAILED", "WORK_AI_TIMEOUT")
    assert expired.state.active_call == reservation.token and expired.lease == reservation.lease
    with ports.transaction():
        settled = repository.fail_chat_call(reservation.context, reservation.token, "WORK_AI_TIMEOUT")
    assert settled.state.run.stage == "FAILED" and settled.state.active_call is None
    assert settled.lease.active_run_id is None and settled.lease.owner_storage_id == NS


def test_chat_settlement_cannot_clear_another_call():
    # Catches stale/absent token settlement and a process-mismatched pending cleanup.
    m, repository, ports = _setup()
    admission = _admit(m, repository, ports)
    reservation = _reserve(repository, ports, admission)
    _reject(ports, lambda: repository.fail_chat_call(reservation.context, reservation.token,
        "UNREVIEWED_UPSTREAM_DETAIL"), statuses=(422, 503))
    for changes in ({"run_id": OTHER_TASK}, {"attempt": 2}, {"call_no": 2},
                    {"lease_revision": 3}, {"process_instance": OTHER_PROCESS}):
        token = replace(reservation.token, **changes)
        _reject(ports, lambda: repository.fail_chat_call(reservation.context, token, "WORK_AI_INVALID_RESPONSE"))
    ports.role = "student"
    _reject(ports, lambda: repository.fail_chat_call(reservation.context, reservation.token, "WORK_AI_TIMEOUT"))
    assert ports.leases["A"].active_run_id == reservation.token.run_id
    ports.role = "teacher"
    with ports.transaction():
        failed = repository.fail_chat_call(reservation.context, reservation.token, "WORK_AI_INVALID_RESPONSE")
    assert failed.state.run.stage == "FAILED" and failed.state.active_call is None
    assert (failed.state.run.attempt, failed.state.run.provider_call_count, failed.state.repair_count,
            failed.state.run.deadline) == (1, 1, 0, admission.state.run.deadline)
    newer = _admit(m, repository, ports, task_id=OTHER_TASK, key="new-run", command=_command(m, client_key="new-user"))
    _reject(ports, lambda: repository.fail_chat_call(reservation.context, reservation.token, "WORK_AI_TIMEOUT"))
    assert ports.leases["A"] == newer.lease
    _reject(ports, lambda: repository.fail_pending_chat("A", OTHER_TASK, newer.state.run.run_id,
        process_instance=OTHER_PROCESS, error_code="WORK_AI_UNAVAILABLE"))
    with ports.transaction():
        pending = repository.fail_pending_chat("A", OTHER_TASK, newer.state.run.run_id,
            process_instance=PROCESS, error_code="WORK_AI_UNAVAILABLE")
    assert pending.state.run.stage == "FAILED" and pending.state.run.provider_call_count == 0
    assert pending.lease.active_run_id is None and pending.lease.owner_storage_id == NS
    assert ports.completions == {}


def test_chat_candidates_require_caller_commit_and_receipt_reconciliation():
    # Catches internal finalization/certification, partial receipts or a second completion row.
    # Owner commit-unknown publication/dispatch is intentionally reserved for Task4b2B.
    m, repository, ports = _setup()
    with ports.transaction():
        admission = repository.admit_chat("A", TASK, _command(m), "运行 Key ",
            process_instance=PROCESS, configured_timeout_seconds=90)
        assert "caller.commit" not in ports.events
        assert "committed" not in {field.name for field in fields(admission)}
    reservation = _reserve(repository, ports, admission)
    before = ports.snapshot()
    with pytest.raises(PrimitiveFailure):
        with ports.transaction():
            candidate = repository.complete_chat_call(reservation.context, reservation.token, _result(m),
                allowed_result_refs=frozenset({REF}), omitted_context=True)
            assert candidate.state.run.stage == "COMPLETE"
            assert "committed" not in {field.name for field in fields(candidate)}
            raise PrimitiveFailure("caller aborts an uncommitted candidate")
    assert ports.snapshot() == before
    with ports.transaction():
        original = repository.get_chat_run("A", TASK, reservation.token.run_id)
    assert original.state.active_call == reservation.token and original.completion is None
    complete = _complete(m, repository, ports, reservation)
    writes = ports.writes
    with ports.transaction():
        observed = repository.get_chat_run("A", TASK, reservation.token.run_id)
    repeated = _complete(m, repository, ports, reservation)
    assert observed.completion == repeated.completion == complete.completion
    assert observed.state == repeated.state == complete.state and ports.writes == writes
    assert len(ports.completions) == 1 and len(ports.messages) == 2
    _reject(ports, lambda: repository.complete_chat_call(reservation.context, reservation.token,
        _result(m, plain_text="different candidate"), allowed_result_refs=frozenset({REF}), omitted_context=True))
    # Optional dependency must not break original task callers; run operations fail controlled.
    m, task_only, empty = _setup(run_rows=False)
    _reject(empty, lambda: task_only.inspect_chat_request("A", TASK, _command(m), "new-run"), statuses=(503,))
