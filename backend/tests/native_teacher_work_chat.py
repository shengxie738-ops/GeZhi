"""Explicit-only native chat slice; synthetic authority and fixed local answer.

Uses current ORM, SqlChatRows, coordinator, strict row decoders and executor.
The finite transaction adapter below is test-owned, not production admission or
request-owner certification. One container per batch; no external AI/HTTP app.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, contextmanager
from datetime import timedelta, timezone
import json
from threading import Event
import time
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models.teacher_work import OwnerRunLease, WorkMessage, WorkRun
from app.repositories.teacher_work import WorkRepositoryError
from app.repositories.teacher_work_sql import SqlReservationConflict, SqlRunModels
from app.schemas.teacher_work import ChatCommand, ChatResult, WorkMessageDTO
from app.services.teacher_work.chat_execution import ChatExecutionContext, TeacherChatExecution
from app.services.teacher_work.run_persistence import (
    PreparedChatCompletion, decode_owner_lease, decode_stored_message,
    decode_stored_run, validate_chat_completion,
)
from app.services.teacher_work.runs import WorkRunError
from tests.native_teacher_work_mysql import NOW, native_db, native_server
from tests.native_teacher_work_repository import OWNER, caller, command, committed_task, repository_db

UTC_NOW = NOW.replace(tzinfo=timezone.utc)
PROCESS = UUID("30000000-0000-0000-0000-000000000001")
REF = UUID("40000000-0000-0000-0000-000000000001")
ANSWER = "固定合成回答\nUnicode café e\u0301 与末尾空格 "


@contextmanager
def chat_caller(db, *, now=UTC_NOW):
    with caller(db, run_models=SqlRunModels(WorkRun, WorkMessage), clock=lambda: now) as bindings:
        yield bindings


def invoke(db, operation, *args, now=UTC_NOW, **kwargs):
    # Only explicit test calls select operations. Each return follows a real
    # commit and both Session/Connection closure; failed roots are discarded.
    with chat_caller(db, now=now) as (session, repository):
        result = getattr(repository, operation)(*args, **kwargs)
        repository.uow.assert_healthy()
        session.commit()
    return result


def chat_command(*, message_key="合成 Message ", content="合成提问", revision=1):
    return ChatCommand.model_validate({"kind": "chat", "input_revision": revision, "skill_ref": None,
        "payload": {"text": content, "client_message_key": message_key}})


def admit(db, task, *, key="合成 Run ", request=None):
    return invoke(db, "admit_chat", OWNER, task.task_id, request or chat_command(), key,
        process_instance=PROCESS, configured_timeout_seconds=10)


def reserve(db, admission):
    return invoke(db, "reserve_chat_call", OWNER, admission.task.task_id, admission.state.run.run_id,
        process_instance=PROCESS, configured_output_tokens=128, configured_timeout_seconds=10)


def prepared(reservation, *, answer=ANSWER):
    result = ChatResult(type="answer", plain_text=answer, result_refs=(REF,), omitted_context=False)
    message = WorkMessageDTO(message_id=uuid4(), owner=OWNER, task_id=reservation.task.task_id,
        client_message_key=None, role="assistant", plain_text=result.plain_text,
        run_id=reservation.token.run_id, result_refs=result.result_refs, result_type=result.type,
        omitted_context=False, created_at=UTC_NOW)
    receipt = validate_chat_completion(reservation.state.run, message, reservation.token.run_id)
    return PreparedChatCompletion(reservation.context, reservation.token, result,
        frozenset({REF}), False, message, receipt)


def rows(db):
    with db.engine.connect() as connection:
        return tuple([dict(row) for row in connection.execute(select(model.__table__).order_by(
            model.__table__.primary_key.columns.values()[0])).mappings()]
            for model in (WorkRun, WorkMessage, OwnerRunLease))


def decoded(db):
    # Fresh ORM Session and production decoders, not DTOs returned by writers.
    with Session(db.engine) as session:
        messages = []
        for row in session.scalars(select(WorkMessage)).all():
            message, completion_run_id = decode_stored_message(row)
            assert completion_run_id == (message.run_id if message.role == "assistant" else None)
            messages.append(message)
        return (tuple(decode_stored_run(row) for row in session.scalars(select(WorkRun)).all()),
            tuple(messages),
            tuple(decode_owner_lease(row) for row in session.scalars(select(OwnerRunLease)).all()))


def read_only(db, action):
    statements = []
    def record(c, cursor, statement, params, context, many):
        statements.append(statement)
    event.listen(db.engine, "before_cursor_execute", record)
    try:
        result = action()
    finally:
        event.remove(db.engine, "before_cursor_execute", record)
    assert statements and all(s.lstrip().upper().startswith("SELECT") for s in statements)
    return result


def serial(value):
    if isinstance(value, bytes):
        return {"hex": value.hex()}
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


@asynccontextmanager
async def held_fixed_call(db, reservation):
    """A charged local Task held until the test observes cancel/expiry."""
    entered, release = asyncio.Event(), asyncio.Event()
    async def complete():
        runs, _, _ = decoded(db)
        assert runs == (reservation.state,) and runs[0].active_call == reservation.token
        entered.set()
        await release.wait()
        return ANSWER
    provider = asyncio.create_task(complete())
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        yield provider, release
    finally:
        if not provider.done():
            provider.cancel()
        await asyncio.gather(provider, return_exceptions=True)


@pytest.fixture(autouse=True)
def chat_evidence(repository_db, request):
    db = repository_db
    yield
    payload = {"selector": request.node.nodeid, "database_identity": vars(db.identity),
        "rows": rows(db)}
    (db.evidence / (request.node.name + ".json")).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=serial) + "\n")


def test_admission_commit_and_rollback_are_atomic(repository_db):
    db = repository_db
    task = committed_task(db)
    before = rows(db)
    with chat_caller(db) as (session, repository):
        candidate = repository.admit_chat(OWNER, task.task_id, chat_command(), "合成 Run ",
            process_instance=PROCESS, configured_timeout_seconds=10)
        assert candidate.created is True
        assert session.scalar(select(func.count()).select_from(WorkRun)) == 1
        assert session.scalar(select(func.count()).select_from(WorkMessage)) == 1
        assert rows(db) == before
        session.rollback()
    assert rows(db) == before
    admission = admit(db, task)
    runs, messages, leases = decoded(db)
    assert runs == (admission.state,) and messages == (admission.user_message,) and leases == (admission.lease,)
    assert runs[0].run.stage == "PENDING" and runs[0].run.provider_call_count == 0
    assert messages[0].created_at == UTC_NOW
    assert rows(db)[0][0]["idempotency_key"] == "合成 Run ".encode()
    assert rows(db)[1][0]["client_message_key"] == "合成 Message ".encode()


def test_admission_replay_conflicts_and_no_duplicate_writes(repository_db):
    db = repository_db
    task = committed_task(db)
    admission = admit(db, task)
    before = rows(db)
    replay = read_only(db, lambda: admit(db, task))
    assert replay.created is False and replay.state == admission.state and replay.user_message == admission.user_message
    with pytest.raises(WorkRunError) as conflict:
        admit(db, task, request=chat_command(content="不同合成提问"))
    assert conflict.value.code == "IDEMPOTENCY_CONFLICT" and conflict.value.status_code == 409
    assert rows(db) == before
    invoke(db, "cancel_chat", OWNER, task.task_id, admission.state.run.run_id)
    before = rows(db)
    with pytest.raises(WorkRunError) as conflict:
        admit(db, task, key="second-key")
    assert conflict.value.code == "MESSAGE_KEY_CONFLICT" and conflict.value.status_code == 409
    assert rows(db) == before


def test_reservation_rollback_then_committed_charge(repository_db):
    db = repository_db
    admission = admit(db, committed_task(db))
    before = rows(db)
    with chat_caller(db) as (session, repository):
        candidate = repository.reserve_chat_call(OWNER, admission.task.task_id, admission.state.run.run_id,
            process_instance=PROCESS, configured_output_tokens=128, configured_timeout_seconds=10)
        assert candidate.token.call_no == 1
        assert session.scalar(select(WorkRun.provider_call_count)) == 1
        assert rows(db) == before
        session.rollback()
    assert rows(db) == before
    reservation = reserve(db, admission)
    runs, _, leases = decoded(db)
    assert runs == (reservation.state,) and runs[0].active_call == reservation.token
    assert runs[0].run.provider_call_count == 1 and runs[0].repair_count == 0
    assert leases == (reservation.lease,)
    before = rows(db)
    with pytest.raises(WorkRunError) as error:
        reserve(db, admission)
    assert error.value.code == "RUN_NOT_ACTIVE"
    assert rows(db) == before


def test_completion_commit_rollback_replay_and_conflict(repository_db):
    db = repository_db
    reservation = reserve(db, admit(db, committed_task(db)))
    value = prepared(reservation)
    before = rows(db)
    with chat_caller(db) as (session, repository):
        outcome = repository.complete_prepared_chat_call(value)
        assert outcome.state.run.stage == "COMPLETE"
        assert session.scalar(select(func.count()).select_from(WorkMessage)) == 2
        assert session.scalar(select(WorkRun.stage)) == "COMPLETE"
        assert session.scalar(select(OwnerRunLease.active_run_id)) is None
        assert rows(db) == before
        session.rollback()
    assert rows(db) == before
    saved = invoke(db, "complete_prepared_chat_call", value)
    runs, messages, leases = decoded(db)
    assert runs == (saved.state,) and saved.state.active_call is None
    assistant = next(m for m in messages if m.role == "assistant")
    assert assistant == value.message and validate_chat_completion(runs[0].run, assistant, runs[0].run.run_id) == saved.completion
    assert assistant.result_refs == (REF,) and assistant.omitted_context is False
    assert assistant.created_at == UTC_NOW and assistant.plain_text == ANSWER
    assert leases == (saved.lease,) and saved.lease.active_run_id is None
    assert saved.lease.revision == reservation.lease.revision + 1
    before = rows(db)
    replay = read_only(db, lambda: invoke(db, "complete_prepared_chat_call", value))
    assert replay == saved and rows(db) == before
    replay = read_only(db, lambda: invoke(db, "complete_chat_call", value.original_ctx, value.token,
        value.result, allowed_result_refs=value.allowed_result_refs, omitted_context=False))
    assert replay == saved
    with pytest.raises(WorkRunError) as error:
        invoke(db, "complete_prepared_chat_call", prepared(reservation, answer="不同固定回答"))
    assert error.value.code == "COMPLETION_CONFLICT" and rows(db) == before
    assert read_only(db, lambda: invoke(db, "cancel_chat", OWNER, reservation.task.task_id, value.token.run_id)) == saved


def test_completion_unique_constraint_poison_and_fresh_reread(repository_db):
    db = repository_db
    reservation = reserve(db, admit(db, committed_task(db)))
    value = prepared(reservation)
    saved = invoke(db, "complete_prepared_chat_call", value)
    before = rows(db)
    with chat_caller(db) as (session, repository):
        repository.get_chat_run(OWNER, reservation.task.task_id, value.token.run_id)
        duplicate = value.message.model_copy(update={"message_id": uuid4()})
        receipt = validate_chat_completion(saved.state.run, duplicate, value.token.run_id)
        with pytest.raises(SqlReservationConflict) as error:
            repository.run_rows.insert_completion(duplicate, receipt)
        assert error.value.constraint == "uq_tw_message_completion_run"
        assert error.value.requires_fresh_transaction is True and repository.uow.in_transaction() is False
        with pytest.raises(WorkRepositoryError) as poisoned:
            repository.get_chat_run(OWNER, reservation.task.task_id, value.token.run_id)
        assert poisoned.value.code == "TRANSACTION_REQUIRED"
        session.rollback()
    assert rows(db) == before
    assert invoke(db, "get_chat_run", OWNER, reservation.task.task_id, value.token.run_id) == saved


def test_late_native_sql_failure_rolls_back_completion_and_requires_new_root(repository_db):
    db = repository_db
    reservation = reserve(db, admit(db, committed_task(db)))
    value = prepared(reservation)
    before = rows(db)
    with db.engine.connect() as connection:
        connection.execute(text("CREATE TRIGGER tw_native_fail_release BEFORE UPDATE ON teacher_work_owner_run_leases "
            "FOR EACH ROW BEGIN IF OLD.active_run_id IS NOT NULL AND NEW.active_run_id IS NULL THEN "
            "SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'synthetic release fault'; END IF; END"))
    try:
        with chat_caller(db) as (session, repository):
            with pytest.raises(OperationalError) as error:
                repository.complete_prepared_chat_call(value)
            assert error.value.orig.args == (1644, "synthetic release fault")
            assert repository.uow.in_transaction() is False
            # MySQL rolls back the failed statement, not the preceding writes.
            assert session.scalar(select(func.count()).select_from(WorkMessage)) == 2
            assert session.scalar(select(WorkRun.stage)) == "COMPLETE"
            assert session.scalar(select(OwnerRunLease.active_run_id)) == str(value.token.run_id)
            assert rows(db) == before
            for rolled_back in (False, True):
                if rolled_back:
                    session.rollback()
                    session.begin()
                with pytest.raises(WorkRepositoryError) as poisoned:
                    repository.get_chat_run(OWNER, reservation.task.task_id, value.token.run_id)
                assert poisoned.value.code == "TRANSACTION_REQUIRED"
            session.rollback()
        assert rows(db) == before
        reread = invoke(db, "get_chat_run", OWNER, reservation.task.task_id, value.token.run_id)
        assert reread.state == reservation.state and reread.completion is None
    finally:
        with db.engine.connect() as connection:
            connection.execute(text("DROP TRIGGER tw_native_fail_release"))
    saved = invoke(db, "complete_prepared_chat_call", value)
    assert saved.completion == value.receipt and len(rows(db)[1]) == 2


@pytest.mark.parametrize("charged", [False, True])
def test_cancel_replay_and_settlement_keep_no_assistant(repository_db, charged):
    db = repository_db
    admission = admit(db, committed_task(db))
    reservation = reserve(db, admission) if charged else None
    def cancel_and_replay():
        cancelled = invoke(db, "cancel_chat", OWNER, admission.task.task_id, admission.state.run.run_id)
        assert cancelled.state.run.stage == "CANCELLED" and cancelled.state.run.cancelled_at == UTC_NOW
        assert cancelled.lease.active_run_id == (admission.state.run.run_id if charged else None)
        assert cancelled.state.active_call == (reservation.token if charged else None)
        before = rows(db)
        assert read_only(db, lambda: invoke(db, "cancel_chat", OWNER, admission.task.task_id,
            admission.state.run.run_id, now=UTC_NOW + timedelta(seconds=1))) == cancelled
        assert rows(db) == before
        return cancelled
    if charged:
        async def scenario():
            async with held_fixed_call(db, reservation) as (provider, release):
                cancel_and_replay()
                assert not provider.done()
                with pytest.raises(WorkRunError) as error:
                    invoke(db, "complete_prepared_chat_call", prepared(reservation))
                assert error.value.code == "RUN_CANCELLED"
                release.set()
                assert await asyncio.wait_for(provider, timeout=1) == ANSWER and provider.done()
                final = invoke(db, "fail_chat_call", reservation.context, reservation.token, "WORK_AI_UPSTREAM_FAILED")
                assert final.state.run.stage == "CANCELLED" and final.state.active_call is None
                assert final.lease.active_run_id is None
                runs, _, leases = decoded(db)
                assert runs == (final.state,) and leases == (final.lease,)
        asyncio.run(scenario())
    else:
        cancelled = cancel_and_replay()
        runs, _, leases = decoded(db)
        assert runs == (cancelled.state,) and leases == (cancelled.lease,)
    runs, messages, _ = decoded(db)
    assert len(runs) == len(messages) == 1 and messages[0].role == "user"


def test_expiry_replay_and_settlement_keep_no_assistant(repository_db):
    db = repository_db
    reservation = reserve(db, admit(db, committed_task(db)))
    before = rows(db)
    with pytest.raises(WorkRunError) as error:
        invoke(db, "expire_chat_call", reservation.context, reservation.token)
    assert error.value.code == "RUN_NOT_EXPIRED" and rows(db) == before
    deadline = reservation.state.run.deadline
    async def scenario():
        async with held_fixed_call(db, reservation) as (provider, release):
            expired = invoke(db, "expire_chat_call", reservation.context, reservation.token, now=deadline)
            assert expired.state.run.stage == "FAILED" and expired.state.run.error_code == "WORK_AI_TIMEOUT"
            assert expired.state.active_call == reservation.token and expired.lease == reservation.lease
            before = rows(db)
            assert read_only(db, lambda: invoke(db, "expire_chat_call", reservation.context,
                reservation.token, now=deadline + timedelta(seconds=1))) == expired
            assert not provider.done()
            with pytest.raises(WorkRunError) as error:
                invoke(db, "complete_prepared_chat_call", prepared(reservation), now=deadline)
            assert error.value.code == "RUN_NOT_ACTIVE" and rows(db) == before
            release.set()
            assert await asyncio.wait_for(provider, timeout=1) == ANSWER and provider.done()
            final = invoke(db, "fail_chat_call", reservation.context, reservation.token, "WORK_AI_TIMEOUT", now=deadline)
            assert final.state.active_call is None and final.lease.active_run_id is None
            assert final.state.run.stage == "FAILED" and final.state.run.error_code == "WORK_AI_TIMEOUT"
            runs, _, leases = decoded(db)
            assert runs == (final.state,) and leases == (final.lease,)
    asyncio.run(scenario())
    assert len(rows(db)[1]) == 1


class TestTransactions:
    __test__ = False
    operations = frozenset({"inspect_chat_request", "admit_chat", "reserve_chat_call", "complete_prepared_chat_call",
        "fail_chat_call", "expire_chat_call", "fail_pending_chat", "cancel_chat", "get_chat_run"})

    def __init__(self, db):
        self.db, self.open_roots, self.completed = db, 0, []

    def __getattr__(self, operation):
        if operation not in self.operations:
            raise AttributeError(operation)
        def execute(*args, **kwargs):
            self.open_roots += 1
            try:
                result = invoke(self.db, operation, *args, **kwargs)
            finally:
                self.open_roots -= 1
            self.completed.append(operation)
            return result
        return execute


def test_real_executor_calls_fixed_provider_only_after_committed_charge(repository_db):
    db = repository_db
    task = committed_task(db)
    request = chat_command()
    transactions = TestTransactions(db)
    calls, tasks = [], []
    class Clock:
        def utc_now(self):
            return UTC_NOW
        def monotonic(self):
            return time.monotonic()
        async def wait_until(self, deadline):
            await asyncio.sleep(max(0, deadline - self.monotonic()))
    class Context:
        def load(self, admission):
            # Current input is supplied by command, not duplicated in history.
            return ChatExecutionContext(command=request, history=(), evidence=())
    class FixedProvider:
        async def complete(self, prompt, *, max_output_tokens, timeout_seconds):
            assert transactions.open_roots == 0 and transactions.completed[-1] == "reserve_chat_call"
            runs, messages, leases = decoded(db)
            assert len(runs) == len(messages) == len(leases) == 1
            assert runs[0].run.stage == "CHAT_RUNNING" and runs[0].run.provider_call_count == 1
            assert runs[0].active_call is not None and runs[0].active_call.call_no == 1
            assert leases[0].active_run_id == runs[0].run.run_id
            # The executor caps by the remaining monotonic deadline and floors
            # to whole seconds, never exceeding the reserved 10-second limit.
            assert max_output_tokens == 128 and type(timeout_seconds) is int and 1 <= timeout_seconds <= 10
            (db.evidence / "provider-entry.json").write_text(json.dumps({
                "database": db.identity.schema_name, "open_roots": transactions.open_roots,
                "last_committed_operation": transactions.completed[-1],
                "run_id": str(runs[0].run.run_id), "stage": runs[0].run.stage,
                "provider_call_count": runs[0].run.provider_call_count,
                "token": vars(runs[0].active_call), "max_output_tokens": max_output_tokens,
                "timeout_seconds": timeout_seconds}, indent=2, default=serial) + "\n")
            calls.append(runs[0].active_call)
            return json.dumps({"type": "answer", "plain_text": ANSWER, "result_refs": []}, ensure_ascii=False)
    def schedule(coroutine):
        task = asyncio.create_task(coroutine)
        tasks.append(task)
        return task
    execution = TeacherChatExecution(transactions=transactions, ai=FixedProvider(), context_source=Context(),
        process_instance=PROCESS, clock=Clock(), new_uuid=uuid4, configured_output_tokens=128,
        configured_timeout_seconds=10, schedule=schedule)
    async def scenario():
        try:
            run = await execution.start_chat(OWNER, task.task_id, request, "execution-key")
            assert run.stage == "PENDING" and len(tasks) == 1
            await asyncio.wait_for(asyncio.shield(tasks[0]), timeout=8)
            await asyncio.sleep(0)
            observed = execution.get_chat_run(OWNER, task.task_id, run.run_id)
            outcome = transactions.get_chat_run(OWNER, task.task_id, run.run_id)
            assert observed == outcome.state.run
            assert outcome.state.run.stage == "COMPLETE" and outcome.completion is not None
            assert outcome.state.run.provider_call_count == 1 and outcome.lease.active_run_id is None
            assert not execution._runs and not execution._slots
            before = rows(db)
            replay = await execution.start_chat(OWNER, task.task_id, request, "execution-key")
            assert replay == outcome.state.run and rows(db) == before
            assert len(tasks) == len(calls) == 1
        finally:
            for pending_task in tasks:
                if not pending_task.done():
                    pending_task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    asyncio.run(scenario())
    runs, messages, _ = decoded(db)
    assert runs[0].run.stage == "COMPLETE" and [m.plain_text for m in messages if m.role == "assistant"] == [ANSWER]


def test_two_connections_cannot_admit_two_active_runs_for_one_owner(repository_db):
    db = repository_db
    first = committed_task(db)
    with caller(db) as (session, repository):
        second = repository.create_task(OWNER, command(), "second-task")
        session.commit()
    held, contender, release = Event(), Event(), Event()
    connections = {}
    def winner():
        with chat_caller(db) as (session, repository):
            session.execute(text("SET SESSION innodb_lock_wait_timeout = 3"))
            connections["winner"] = session.scalar(text("SELECT CONNECTION_ID()"))
            admission = repository.admit_chat(OWNER, first.task_id, chat_command(), "winner-key",
                process_instance=PROCESS, configured_timeout_seconds=10)
            held.set()
            assert release.wait(5), "test must release the held transaction"
            session.commit()
            return admission
    def loser():
        assert held.wait(3)
        with chat_caller(db) as (session, repository):
            session.execute(text("SET SESSION innodb_lock_wait_timeout = 3"))
            connections["loser"] = session.scalar(text("SELECT CONNECTION_ID()"))
            contender.set()
            with pytest.raises(WorkRunError) as error:
                repository.admit_chat(OWNER, second.task_id, chat_command(message_key="second-message"), "loser-key",
                    process_instance=uuid4(), configured_timeout_seconds=10)
            assert error.value.code == "OWNER_RUN_BUSY"
            session.rollback()
            return error.value.code
    pool = ThreadPoolExecutor(max_workers=2)
    try:
        winning = pool.submit(winner)
        assert held.wait(3)
        losing = pool.submit(loser)
        assert contender.wait(3)
        deadline, observed = time.monotonic() + 2, None
        while time.monotonic() < deadline:
            with db.engine.connect() as connection:
                observed = connection.execute(text("SELECT requesting.OBJECT_NAME, requester.PROCESSLIST_ID, blocker.PROCESSLIST_ID "
                    "FROM performance_schema.data_lock_waits waits "
                    "JOIN performance_schema.data_locks requesting ON requesting.ENGINE_LOCK_ID = waits.REQUESTING_ENGINE_LOCK_ID "
                    "JOIN performance_schema.threads requester ON requester.THREAD_ID = waits.REQUESTING_THREAD_ID "
                    "JOIN performance_schema.threads blocker ON blocker.THREAD_ID = waits.BLOCKING_THREAD_ID "
                    "WHERE requesting.OBJECT_SCHEMA = :schema AND requester.PROCESSLIST_ID = :loser "
                    "AND blocker.PROCESSLIST_ID = :winner"), {"schema": db.identity.schema_name,
                        "loser": connections["loser"], "winner": connections["winner"]}).first()
            if observed:
                break
            time.sleep(.02)
        assert observed == ("teacher_work_owner_run_leases", connections["loser"], connections["winner"])
        (db.evidence / "owner-race.json").write_text(json.dumps({"database": db.identity.schema_name,
            "connection_ids": connections, "observed_lock_wait": list(observed)}, indent=2) + "\n")
        release.set()
        admission = winning.result(timeout=6)
        assert losing.result(timeout=6) == "OWNER_RUN_BUSY"
        runs, messages, leases = decoded(db)
        assert runs == (admission.state,) and messages == (admission.user_message,) and leases == (admission.lease,)
    finally:
        release.set()
        pool.shutdown(wait=True, cancel_futures=True)
