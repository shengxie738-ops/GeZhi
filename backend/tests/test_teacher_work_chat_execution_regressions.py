"""Finite Task4b2B supervisor-ownership supplement, UNEXECUTED.

This source supplements, rather than edits, the four frozen C14-C17 selectors.
It reuses their exact reviewed recording primitives and actual coordinator/UoW/
pure-owner composition. The schedulers below only control real in-memory task
entry and actual repository race operations; they contain no Work decisions.
No product correction, async/timer/socket/network/DB operation is authorized by
writing this file. A separate parent-reviewed finite runtime release is required.
"""
from __future__ import annotations

from copy import deepcopy
import ast
import hashlib
import importlib
from pathlib import Path


# Only the source-only bootstrap guard contract was updated for private CRU.
# The original four selectors and every runtime fixture remain pinned below.
SUPPORT_SHA = "67917ee4e2190ff28031c41512df14bfc967eabd61006ebaf80a023fcf68af5f"
RUNTIME_AST_SHA = "3d345760c79c1ae7b35f68b8742c5d6208ada68b7ecdb903e2578c5975530209"


def _support():
    # Source identity checks precede support/product/async dependency imports,
    # fixture construction and asyncio.run. No candidate implementation detail
    # is asserted here: RED must come from the actual behavioral regression.
    path = Path(__file__).with_name("test_teacher_work_chat_execution.py")
    assert path.is_file(), "Task4b2B frozen execution fixture is missing"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == SUPPORT_SHA, "Task4b2B original four-selector fixture changed"
    # Only the exact named admission guard expanded; all four original
    # behavioral fixtures and remaining support bytes stay independently pinned.
    raw=path.read_bytes(); lines=raw.splitlines(keepends=True)
    guard=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='_bootstrap_source_contract')
    behavior=b''.join(lines[:guard.lineno-1]+lines[guard.end_lineno:])
    assert hashlib.sha256(behavior).hexdigest() == "8af43eda07dd8e618bb7e1b884934f789adf1cc46a5ef77e6bd4967efce64de7"
    tree = ast.parse(path.read_bytes())
    tree.body = [n for n in tree.body if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) or n.name != "_bootstrap_source_contract"]
    assert hashlib.sha256(ast.dump(tree, include_attributes=False).encode()).hexdigest() == RUNTIME_AST_SHA
    support = importlib.import_module("tests.test_teacher_work_chat_execution")
    assert Path(support.__file__).resolve() == path.resolve(), "Task4b2B fixture import resolved outside the pinned test package"
    return support._load(), support


def _install_scheduler(h, scheduler):
    # An explicit server constructor dependency, never an HTTP-selected callback.
    h.execution = h.m.execution.TeacherChatExecution(transactions=h.transactions,
        ai=h.ai, context_source=h.context, process_instance=h.execution.process_instance,
        clock=h.clock, new_uuid=h.store.new_uuid, configured_output_tokens=12000,
        configured_timeout_seconds=200, capacity=4, schedule=scheduler)


def _confirmed_admission(h):
    for operation, value, root in h.transactions.candidates:
        if operation == "admit_chat":
            assert root.committed is True and root.active is False and root not in h.store.open_roots
            return value
    raise AssertionError("the actual owner must have finalized an admission")


class PreEntryCancellationScheduler:
    """Finite actual task creation/cancellation and real primitive race scripts."""
    def __init__(self, h, support, mode):
        self.h, self.support, self.mode = h, support, mode
        self.enabled = True
        self.original_run_id = None
        self.replacement = None
        self.raced_snapshot = None

    def __call__(self, coroutine):
        assert not self.h.store.open_roots
        task = self.h.m.asyncio.create_task(coroutine)
        self.h.supervisors.append(task)
        if not self.enabled:
            return task
        self.enabled = False
        admission = _confirmed_admission(self.h)
        run = admission.state.run
        self.original_run_id = run.run_id
        if self.mode in ("charged", "charge_unknown"):
            if self.mode == "charge_unknown":
                self.h.transactions.scripts["reserve_chat_call"] = ["unknown_applied"]
            try:
                self.h.transactions.reserve_chat_call(run.owner, run.task_id, run.run_id,
                    process_instance=self.support.PROCESS, configured_output_tokens=12000,
                    configured_timeout_seconds=200, repair=False)
            except Exception as error:
                assert self.mode == "charge_unknown" and getattr(error, "code", None) == "COMMIT_OUTCOME_UNKNOWN"
        elif self.mode == "replacement_lease":
            # Real cancelled no-call cleanup, then a distinct real admission.
            # The cancelled supervisor cannot release this newer run's lease.
            self.h.transactions.cancel_chat(run.owner, run.task_id, run.run_id)
            command = self.h.command(6)
            self.replacement = self.h.transactions.admit_chat("A", self.support._uid(0x20, 6),
                command, "replacement run", process_instance=self.support.PROCESS,
                configured_timeout_seconds=200)
        else:
            assert self.mode == "uncharged"
        self.raced_snapshot = deepcopy(self.h.store.tables)
        # No event-loop turn has occurred since create_task: the production
        # coroutine body and its finally have definitely never entered.
        assert self.h.ai.calls == [] and not task.done()
        task.cancel()
        return task


class GatedEntryScheduler:
    """The returned actual supervisor waits on one explicit in-memory future."""
    def __init__(self, h):
        self.h = h
        self.gate = h.m.asyncio.get_running_loop().create_future()

    async def _launch(self, coroutine):
        entered = False
        try:
            await self.gate
            entered = True
            return await coroutine
        finally:
            if not entered:
                coroutine.close()

    def __call__(self, coroutine):
        assert not self.h.store.open_roots
        task = self.h.m.asyncio.create_task(self._launch(coroutine))
        self.h.supervisors.append(task)
        return task

    def release(self):
        if not self.gate.done():
            self.gate.set_result(None)


async def _close(h, *, scheduler=None, extra=()):
    if scheduler is not None and isinstance(scheduler, GatedEntryScheduler):
        scheduler.release()
    for call in h.ai.calls:
        call.release()
    await h.cleanup()
    for task in (*h.supervisors, *extra):
        if task.done() and not task.cancelled():
            task.exception()  # Consume controlled rejected entries; never log repr.


async def _preentry_cases(modules, support):
    # R20-01: cancellation before the first turn must atomically fail only the
    # matching definitely uncharged run and release its actual owner lease.
    h = support.Harness(modules)
    scheduler = PreEntryCancellationScheduler(h, support, "uncharged")
    _install_scheduler(h, scheduler)
    try:
        before_namespaces = {owner: lease.owner_storage_id for owner, lease in h.store.tables["leases"].items()}
        run = await h.start()
        await h.turns(48)
        state = h.state(run)
        assert state.run.stage == "FAILED", "pre-entry cancellation must settle the matching no-call run"
        assert state.run.error_code == "WORK_EXECUTION_UNAVAILABLE"
        assert state.run.provider_call_count == 0 and state.repair_count == 0 and state.active_call is None
        assert h.store.tables["leases"]["A"].active_run_id is None
        assert h.ai.calls == [] and h.assistant_messages() == ()
        assert {owner: lease.owner_storage_id for owner, lease in h.store.tables["leases"].items()} == before_namespaces
        assert all(h.store.tables["leases"][owner].active_run_id is None for owner in ("B", "C", "D", "E"))
        assert all(root.active is False for root in h.transactions.roots)

        # R20-02: definitely unused local capacity is reclaimed too; four other
        # owners can start immediately, with no accidental fifth-slot queue.
        runs = [await h.start(owner, ordinal) for ordinal, owner in enumerate(("B", "C", "D", "E"), 2)]
        await h.turns()
        assert len(runs) == len(h.ai.calls) == 4
    finally:
        await _close(h, scheduler=scheduler)

    # R20-03: a newer legitimate run/lease is never touched by the cancelled
    # original supervisor. The race uses actual repository/owner operations.
    h = support.Harness(modules)
    scheduler = PreEntryCancellationScheduler(h, support, "replacement_lease")
    _install_scheduler(h, scheduler)
    try:
        run = await h.start()
        await h.turns(48)
        replacement = scheduler.replacement
        assert replacement is not None and replacement.state.run.run_id != run.run_id
        assert h.store.tables == scheduler.raced_snapshot
        assert h.state(run).run.stage == "CANCELLED" and h.state(run).run.provider_call_count == 0
        assert h.store.tables["leases"]["A"] == replacement.lease
        assert h.store.tables["leases"]["A"].active_run_id == replacement.state.run.run_id
        assert h.ai.calls == [] and h.assistant_messages() == ()
    finally:
        await _close(h, scheduler=scheduler)

    # R20-04..05: an old admission snapshot cannot certify current zero charge.
    # Charged/commit-unknown active token and matching lease remain unchanged;
    # local capacity cannot be released as if transport settlement were known.
    for mode in ("charged", "charge_unknown"):
        h = support.Harness(modules)
        scheduler = PreEntryCancellationScheduler(h, support, mode)
        _install_scheduler(h, scheduler)
        try:
            run = await h.start()
            await h.turns(48)
            assert h.store.tables == scheduler.raced_snapshot
            state = h.state(run)
            assert state.run.stage == "CHAT_RUNNING" and state.run.provider_call_count == 1
            assert state.active_call is not None and h.store.tables["leases"]["A"].active_run_id == run.run_id
            assert h.ai.calls == [] and h.assistant_messages() == ()
            for ordinal, owner in enumerate(("B", "C", "D"), 2):
                await h.start(owner, ordinal)
            await support._expect_async_code("INSTANCE_BUSY", h.start("E", 5))
            assert h.state(run) == state and h.store.tables["leases"]["A"] == scheduler.raced_snapshot["leases"]["A"]
        finally:
            await _close(h, scheduler=scheduler)


async def _entry_cases(modules, support):
    # R21-01: a direct competing task cannot adopt the exact admission while
    # the genuine scheduled supervisor has not entered. No writes or dispatch.
    h = support.Harness(modules)
    scheduler = GatedEntryScheduler(h)
    _install_scheduler(h, scheduler)
    competitor = None
    try:
        run = await h.start()
        admission = _confirmed_admission(h)
        before = deepcopy(h.store.tables)
        competitor = modules.asyncio.create_task(h.execution.execute_first_chat(admission))
        await h.turns(48)
        assert competitor.done() and h.store.tables == before and h.ai.calls == [], "a competing task must be refused before any write or dispatch"
        assert not competitor.cancelled()
        error = competitor.exception()
        assert getattr(error, "code", None) == "WORK_EXECUTION_UNAVAILABLE"
        assert h.state(run).run.stage == "PENDING" and h.state(run).run.provider_call_count == 0
        assert h.store.tables["leases"]["A"] == admission.lease

        # R21-02: rejecting that competitor must preserve the original owner;
        # its actual supervisor later performs exactly one charged real reply.
        scheduler.release()
        await h.turns(48)
        assert len(h.ai.calls) == 1 and h.state(run).run.provider_call_count == 1
        h.ai.calls[0].release()
        await h.drain()
        assert h.state(run).run.stage == "COMPLETE" and h.state(run).active_call is None
        assert len(h.assistant_messages()) == 1 and h.assistant_messages()[0].plain_text == support.ACTUAL_TEXT
        assert h.store.tables["leases"]["A"].active_run_id is None
    finally:
        await _close(h, scheduler=scheduler, extra=() if competitor is None else (competitor,))

    # R21-03..05: after genuine charge, another entry still cannot touch the
    # reservation; cancelling its supervisor cannot clear an ignored provider.
    # Only actual local terminal settlement permits exact no-content cleanup.
    h = support.Harness(modules)
    competitor = None
    try:
        run = await h.start()
        await h.turns()
        admission = _confirmed_admission(h)
        before = deepcopy(h.store.tables)
        competitor = modules.asyncio.create_task(h.execution.execute_first_chat(admission))
        await h.turns(32)
        assert competitor.done() and not competitor.cancelled()
        assert getattr(competitor.exception(), "code", None) == "WORK_EXECUTION_UNAVAILABLE"
        assert h.store.tables == before and len(h.ai.calls) == 1
        state, lease = h.state(run), h.store.tables["leases"]["A"]
        h.supervisors[0].cancel()
        await h.turns(48)
        assert h.ai.calls[0].cancel_requests >= 1 and not h.ai.calls[0].terminal
        assert not h.supervisors[0].done()
        assert h.state(run) == state and h.store.tables["leases"]["A"] == lease
        for ordinal, owner in enumerate(("B", "C", "D"), 2):
            await h.start(owner, ordinal)
        await support._expect_async_code("INSTANCE_BUSY", h.start("E", 5))
        h.ai.calls[0].release()
        await h.turns(48)
        assert h.ai.calls[0].terminal and h.supervisors[0].done()
        assert h.state(run).run.stage == "FAILED" and h.state(run).active_call is None
        assert h.state(run).run.provider_call_count == 1 and h.state(run).run.deadline == state.run.deadline
        assert h.store.tables["leases"]["A"].active_run_id is None and h.assistant_messages() == ()
    finally:
        await _close(h, extra=() if competitor is None else (competitor,))


def test_chat_supervisor_preentry_cancel_cleans_only_uncharged_admission():
    modules, support = _support()
    modules.asyncio.run(_preentry_cases(modules, support))


def test_chat_execution_entry_belongs_to_scheduled_supervisor():
    modules, support = _support()
    modules.asyncio.run(_entry_cases(modules, support))
