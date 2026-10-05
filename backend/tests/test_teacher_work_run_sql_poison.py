"""Task4b2A P1 supplement, UNEXECUTED; original A8/B5 bytes stay pinned.

Explicit Core INSERT failure may leave Session/root health flags active. This
recording port preserves those flags and exercises real SqlChatRows/UoW. The
exact dotted helper module is a frozen executable fixture dependency, never an
additional pytest collection target. No SQL is evaluated or sent to a database.
"""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

import tests.test_teacher_work_run_sql as helper


class ActiveRootWriteFailurePort(helper.RecordingStatementPort):
    def __init__(self, origin):
        super().__init__(origin)
        self.write_failure = None
        self.active_flush_failure = None

    def execute(self, statement):
        if self.write_failure is None:
            return super().execute(statement)
        assert statement.is_insert or statement.is_update
        assert self.active is self.is_active is self.root.is_active is True
        self.statements.append(statement)
        self.events.append("dml")
        error, self.write_failure = self.write_failure, None
        # Deliberately do not mutate Session/root health signals. The production
        # adapter must remember its own failed write, rather than infer rollback.
        raise error

    def flush(self):
        if self.active_flush_failure is None:
            return super().flush()
        assert self.active is self.is_active is self.root.is_active is True
        self.events.append("flush")
        error, self.active_flush_failure = self.active_flush_failure, None
        raise error


def _setup():
    m = helper._load()
    session = ActiveRootWriteFailurePort(m.orm.SessionTransactionOrigin.BEGIN)
    domain = helper._domain_model(m)
    models = m.adapter.SqlWorkModels(m.models.WorkTask, m.models.OwnerRunLease,
                                    m.models.PackageVersion, domain)
    run_models = m.adapter.SqlRunModels(m.models.WorkRun, m.models.WorkMessage)
    uow, state = m.adapter.SqlWorkUnitOfWork(session), m.adapter._SqlState(session, "write")
    tasks = m.adapter.SqlTaskRows(session, models, uow, state)
    drafts = m.adapter.SqlOriginalDrafts(session, domain, state)
    chat = m.adapter.SqlChatRows(session, models, run_models, uow, state, tasks)
    fixture = SimpleNamespace(m=m, session=session, models=models, run_models=run_models,
                             uow=uow, state=state, tasks=tasks, drafts=drafts, chat=chat)
    helper._lock_task(fixture)
    return fixture


def test_chat_sql_active_write_failure_poison_is_binding_owned():
    # Catches relying on Session/root inactivity after explicit INSERT failure,
    # and reusing any part of the failed caller binding for reads/writes/flush.
    scenarios = (("uq_tw_run_owner_task_kind_key", "run"),
                 ("uq_tw_message_task_client_key", "user"),
                 ("uq_tw_message_completion_run", "completion"),
                 ("unrecognized_unique", "run"),
                 ("unrecognized_unique", "cas_run"),
                 ("unrecognized_unique", "cas_lease"),
                 ("uq_tw_run_owner_task_kind_key", "flush"),
                 ("unrecognized_unique", "flush"))
    for constraint, operation in scenarios:
        f = _setup()
        stored = helper._lock_run(f)
        lease = f.chat.lease("A")
        user = f.m.schema.WorkMessageDTO(message_id=helper.MESSAGE, owner="A", task_id=helper.TASK,
            role="user", client_message_key="用户 Key ", run_id=helper.RUN,
            plain_text="合成输入", created_at=helper.NOW)
        assistant = f.m.schema.WorkMessageDTO(message_id=helper.MESSAGE, owner="A", task_id=helper.TASK,
            role="assistant", client_message_key=None, run_id=helper.RUN,
            plain_text="合成实际候选", result_type="answer", omitted_context=False, created_at=helper.NOW)
        receipt = f.m.persistence.ChatCompletionReceipt(helper.RUN, helper.MESSAGE)
        original_error = helper._integrity(f, constraint)
        if operation == "flush":
            f.session.queue(rowcount=1)
            f.chat.insert_run(stored)
            f.session.active_flush_failure = original_error
        else:
            f.session.write_failure = original_error
        wanted = f.m.exceptions.IntegrityError if constraint == "unrecognized_unique" else f.m.adapter.SqlReservationConflict
        with pytest.raises(wanted) as caught:
            if operation == "run":
                f.chat.insert_run(stored)
            elif operation == "user":
                f.chat.insert_user_message(user)
            elif operation == "completion":
                f.chat.insert_completion(assistant, receipt)
            elif operation == "cas_run":
                f.chat.cas_run(stored, replace(stored, active_call=None))
            elif operation == "cas_lease":
                f.chat.cas_lease(lease, replace(lease, active_run_id=None,
                    process_instance=None, expires_at=None, revision=lease.revision + 1))
            else:
                f.uow.flush()
        if constraint == "unrecognized_unique":
            assert caught.value is original_error
        else:
            assert caught.value.constraint == constraint
            assert caught.value.requires_fresh_transaction is True
        assert f.session.active is f.session.is_active is f.session.root.is_active is True
        assert f.uow.in_transaction() is False, "Task4b2A write failure must poison its caller binding even while Session/root flags stay active"
        statements, events = len(f.session.statements), len(f.session.events)
        actions = (
            lambda: f.chat.lease("A"),
            lambda: f.chat.find_run_by_key("A", helper.TASK, "chat", "运行 Key ".encode("utf-8")),
            lambda: f.chat.lock_run("A", helper.TASK, helper.RUN),
            lambda: f.chat.find_user_message("A", helper.TASK, b"user Key "),
            lambda: f.chat.find_completion("A", helper.TASK, helper.RUN),
            lambda: f.chat.insert_run(stored),
            lambda: f.chat.insert_user_message(user),
            lambda: f.chat.insert_completion(assistant, receipt),
            lambda: f.chat.cas_run(stored, replace(stored, active_call=None)),
            lambda: f.chat.cas_lease(lease, replace(lease, active_run_id=None,
                process_instance=None, expires_at=None, revision=lease.revision + 1)),
            lambda: f.tasks.find_task("A", helper.TASK),
            lambda: f.tasks.lock_task("A", helper.TASK),
            lambda: f.tasks.lock_owner_lease("A"),
            lambda: f.drafts.lock_draft("A", "draft-1"),
            lambda: f.uow.flush(),
        )
        for action in actions:
            with pytest.raises((ValueError, f.m.repository.WorkRepositoryError)):
                action()
            assert len(f.session.statements) == statements
            assert len(f.session.events) == events
        # Only a distinct newly authorized root is usable. It observes; no new
        # run/write/provider work is attempted as a result of reconciliation.
        fresh = helper._setup(mode="read")
        fresh.session.queue(rows=[helper._run_row(fresh.m)])
        observed = fresh.chat.find_run_by_key("A", helper.TASK, "chat", "运行 Key ".encode("utf-8"))
        assert observed.run.run_id == helper.RUN and fresh.session is not f.session
        assert all(statement.is_select for statement in fresh.session.statements)
