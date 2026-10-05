"""Standalone narrow executor AST regression; not the full runtime/integration gate.

Only the exact hash-reviewed source nodes are executed. Synthetic finalized
port facts replace DTO/persistence dependencies, without repository workflows.
Both cases stop execution at context_source.load or earlier. No app imports,
SQLAlchemy/Pydantic/third-party extensions, provider, DB, server or browser.
"""
from __future__ import annotations

import argparse
import ast
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from uuid import UUID


NOW = datetime(2026, 10, 5, tzinfo=timezone.utc)
TASK_ID = UUID("20000000-0000-0000-0000-000000000001")
RUN_ID = UUID("30000000-0000-0000-0000-000000000001")
PROCESS = UUID("40000000-0000-0000-0000-000000000001")
NAMESPACE = UUID("50000000-0000-0000-0000-000000000001")
CASES = ("preentry_cancel", "supervisor_entry", "preentry_charged",
         "preentry_denied", "preentry_replacement_lease", "preentry_unknown_pending")


@dataclass(frozen=True)
class RunFact:
    owner: str = "A"
    task_id: UUID = TASK_ID
    run_id: UUID = RUN_ID
    deadline: datetime = NOW + timedelta(seconds=60)
    stage: str = "PENDING"
    attempt: int = 1
    provider_call_count: int = 0
    input_revision: int = 1
    kind: str = "chat"
    skill_ref: object = None
    cancelled_at: object = None
    error_code: object = None
    request_digest: str = "0" * 64
    idempotency_key: str = "unit-run"


@dataclass(frozen=True)
class StateFact:
    run: RunFact
    repair_count: int = 0
    active_call: object = None


@dataclass(frozen=True)
class ChatRunAdmission:
    task: object
    context: object
    state: StateFact
    user_message: object
    lease: object
    created: bool = True

    def __post_init__(self):
        # Structural synthetic fact check, not authorization or transition logic.
        assert type(self.state) is StateFact and type(self.created) is bool
        assert self.state.run.run_id == RUN_ID


@dataclass(frozen=True)
class ChatRequestObservation:
    admission: object = None

    def __post_init__(self):
        assert self.admission is None


@dataclass(frozen=True)
class ChatRunOutcome:
    task: object
    state: StateFact
    lease: object
    completion: object = None

    def __post_init__(self):
        assert type(self.state) is StateFact and self.state.run.run_id == RUN_ID


def load_actual_source(manifest):
    module = ModuleType("teacher_executor_unit")
    sys.modules[module.__name__] = module
    namespace = module.__dict__
    boundary_calls = []

    def forbidden_boundary(*args, **kwargs):
        boundary_calls.append("prompt_result_provider_boundary")
        raise AssertionError("unit scope must never reach prompt/result/provider work")

    namespace.update(asyncio=asyncio, dataclass=dataclass, datetime=datetime,
        timezone=timezone, math=math, UUID=UUID,
        ChatRunAdmission=ChatRunAdmission, ChatRequestObservation=ChatRequestObservation,
        ChatRunOutcome=ChatRunOutcome, RunDTO=RunFact,
        ChatExecutionContext=type("UnusedContextType", (), {}),
        ChatCallReservation=type("UnusedReservationType", (), {}),
        prepare_chat_prompt=forbidden_boundary, parse_chat_result=forbidden_boundary,
        chat_request_digest=forbidden_boundary, validate_chat_completion=forbidden_boundary,
        boundary_calls=boundary_calls)
    for source in manifest["extraction_sources"]:
        raw = Path(source["path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == source["sha256"], "reviewed product source changed"
        tree = ast.parse(raw)
        selected = []
        for expected in source["nodes"]:
            matches = [node for node in tree.body if
                (isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == expected["name"])
                or (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name) and node.targets[0].id == expected["name"])]
            assert len(matches) == 1, "exact source node missing/ambiguous"
            node = matches[0]
            dumped = ast.dump(node, include_attributes=False).encode()
            assert hashlib.sha256(dumped).hexdigest() == expected["AST_sha256"], "reviewed source node changed"
            assert not any(isinstance(item, (ast.Import, ast.ImportFrom)) for item in ast.walk(node)), "extracted source may not import anything"
            selected.append(node)
        future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
        exact_module = ast.fix_missing_locations(ast.Module(body=[future, *selected], type_ignores=[]))
        # No method rewrite, wrapper, monkeypatch, or import of the source module.
        exec(compile(exact_module, source["path"], "exec", dont_inherit=True), namespace)
    return module


class FixedPortFacts:
    """Fixed predeclared replies and call recording, no durable workflow policy."""
    def __init__(self, actual, mode="uncharged"):
        self.calls = []
        self.task = SimpleNamespace(owner_subject="A", owner_storage_id=NAMESPACE,
            task_id=TASK_ID, institution_id=None, offering_id=None,
            input_revision=1, working_revision=1)
        self.context = SimpleNamespace(actor_subject="A", owner_storage_id=NAMESPACE,
            task_id=TASK_ID, institution_id=None, offering_id=None,
            input_revision=1, working_revision=1)
        self.lease = SimpleNamespace(owner="A", owner_storage_id=NAMESPACE,
            active_run_id=RUN_ID, process_instance=PROCESS, revision=1,
            expires_at=NOW + timedelta(seconds=60))
        self.admission = ChatRunAdmission(self.task, self.context, StateFact(RunFact()),
            SimpleNamespace(plain_text="synthetic", client_message_key="unit-message"), self.lease)
        # These are fixture facts, not outputs of a substitute run state machine.
        self.pending = ChatRunOutcome(self.task, StateFact(RunFact()), self.lease)
        self.terminal = ChatRunOutcome(self.task,
            StateFact(RunFact(stage="FAILED", error_code="WORK_EXECUTION_UNAVAILABLE")),
            SimpleNamespace(owner="A", owner_storage_id=NAMESPACE, active_run_id=None,
                            process_instance=None, revision=2, expires_at=None))
        self.cleanup_error = None
        self.read_error = None
        if mode == "charged":
            self.pending = ChatRunOutcome(self.task,
                StateFact(RunFact(stage="CHAT_RUNNING", provider_call_count=1), active_call=object()), self.lease)
            self.cleanup_error = actual.WorkRunError("RUN_NOT_PENDING", 409)
        elif mode == "denied":
            self.cleanup_error = self.read_error = actual.WorkAuthorizationError("CURRENT_TEACHER_REQUIRED", 403)
        elif mode == "replacement":
            self.pending = ChatRunOutcome(self.task,
                StateFact(RunFact(stage="CANCELLED", cancelled_at=NOW)),
                SimpleNamespace(owner="A", owner_storage_id=NAMESPACE,
                    active_run_id=UUID("30000000-0000-0000-0000-000000000002"),
                    process_instance=PROCESS, revision=3, expires_at=NOW + timedelta(seconds=60)))
            self.cleanup_error = actual.WorkRunError("OWNER_LEASE_LOST", 409)
        elif mode == "unknown_pending":
            self.cleanup_error = actual.ChatExecutionError("COMMIT_OUTCOME_UNKNOWN")
        else:
            assert mode == "uncharged"

    def inspect_chat_request(self, *args, **kwargs):
        self.calls.append(("inspect_chat_request", args, kwargs))
        return ChatRequestObservation()

    def admit_chat(self, *args, **kwargs):
        self.calls.append(("admit_chat", args, kwargs))
        return self.admission

    def fail_pending_chat(self, *args, **kwargs):
        self.calls.append(("fail_pending_chat", args, kwargs))
        if self.cleanup_error is not None:
            raise self.cleanup_error
        return self.terminal

    def get_chat_run(self, *args, **kwargs):
        self.calls.append(("get_chat_run", args, kwargs))
        if self.read_error is not None:
            raise self.read_error
        return self.pending

    def __getattr__(self, name):
        def blocked(*args, **kwargs):
            self.calls.append(("FORBIDDEN:" + name, args, kwargs))
            raise AssertionError("unit scope may not charge/dispatch/complete a provider call")
        return blocked


class StopAtPreparation:
    def __init__(self, actual):
        self.actual = actual
        self.calls = []

    def load(self, admission):
        self.calls.append((admission, asyncio.current_task()))
        raise self.actual.ChatExecutionError("WORK_EXECUTION_UNAVAILABLE")


class NoProvider:
    def __init__(self):
        self.calls = []

    def complete(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        raise AssertionError("provider calls are outside this unit proof")


class FixedClock:
    def utc_now(self):
        return NOW

    def monotonic(self):
        return 1000.0

    async def wait_until(self, deadline):
        raise AssertionError("product timer is outside this unit proof")


class UnitHarness:
    def __init__(self, actual, *, cancel_before_entry=False, mode="uncharged"):
        self.actual = actual
        self.ports = FixedPortFacts(actual, mode)
        self.context = StopAtPreparation(actual)
        self.ai = NoProvider()
        self.tasks = []
        self.gate = asyncio.get_running_loop().create_future()
        self.cancel_before_entry = cancel_before_entry
        self.execution = actual.TeacherChatExecution(transactions=self.ports, ai=self.ai,
            context_source=self.context, process_instance=PROCESS, clock=FixedClock(),
            new_uuid=lambda: RUN_ID, configured_output_tokens=1,
            configured_timeout_seconds=60, capacity=4, schedule=self.schedule)

    async def gated_entry(self, coroutine):
        entered = False
        try:
            await self.gate
            entered = True
            return await coroutine
        finally:
            if not entered:
                coroutine.close()

    def schedule(self, coroutine):
        if self.cancel_before_entry:
            task = asyncio.create_task(coroutine)
            task.cancel()  # No event-loop yield since task creation.
        else:
            task = asyncio.create_task(self.gated_entry(coroutine))
        self.tasks.append(task)
        return task

    async def start(self):
        return await asyncio.wait_for(self.execution.start_chat("A", TASK_ID,
            SimpleNamespace(unit_only=True), "unit-run"), timeout=1)

    async def close(self):
        if not self.gate.done():
            self.gate.set_result(None)
        for task in self.tasks:
            if not task.done():
                task.cancel()
        await asyncio.wait_for(asyncio.gather(*self.tasks, return_exceptions=True), timeout=1)
        assert all(task.done() for task in self.tasks), "owned unit tasks did not settle"
        assert len(asyncio.all_tasks()) <= 2, "an unowned unit task escaped"
        assert not self.ai.calls and not self.actual.boundary_calls, "provider/prompt boundary was crossed"
        assert not any(name.startswith("FORBIDDEN:") for name, _, _ in self.ports.calls), "charge/dispatch boundary was crossed"


async def turns(count=8):
    for _ in range(count):
        future = asyncio.get_running_loop().create_future()
        asyncio.get_running_loop().call_soon(future.set_result, None)
        await future


async def preentry_cancel(actual):
    h = UnitHarness(actual, cancel_before_entry=True)
    try:
        run = await h.start()
        await turns()
        matching = [(args, kwargs) for name, args, kwargs in h.ports.calls if name == "fail_pending_chat"]
        assert matching == [(("A", TASK_ID, RUN_ID), {"process_instance": PROCESS,
            "error_code": "WORK_EXECUTION_UNAVAILABLE"})], "pre-entry cancellation must request exact uncharged pending cleanup"
        assert len(h.execution._slots) == 0, "pre-entry cancellation must reclaim unused local capacity"
        assert run.run_id not in h.execution._runs, "finished pre-entry supervisor must not remain locally owned"
        assert not h.context.calls and h.tasks[0].cancelled(), "cancelled pre-entry task must never prepare or dispatch"
    finally:
        await h.close()


async def supervisor_entry(actual):
    h = UnitHarness(actual)
    competitor = None
    try:
        await h.start()
        competitor = asyncio.create_task(h.execution.execute_first_chat(h.ports.admission))
        h.tasks.append(competitor)
        outcome = await asyncio.wait_for(asyncio.gather(competitor, return_exceptions=True), timeout=1)
        assert not h.context.calls, "competing Task must be refused before context preparation"
        assert isinstance(outcome[0], actual.ChatExecutionError) and outcome[0].code == "WORK_EXECUTION_UNAVAILABLE", "competing Task must report a controlled ownership refusal"
        assert [name for name, _, _ in h.ports.calls] == ["inspect_chat_request", "admit_chat"], "competing Task must perform no transaction operation"
        assert not h.execution._runs[RUN_ID].started, "competing Task must not consume genuine supervisor entry"
        h.gate.set_result(None)
        await asyncio.wait_for(asyncio.gather(h.tasks[0], return_exceptions=True), timeout=1)
        assert len(h.context.calls) == 1 and h.context.calls[0][1] is h.tasks[0], "only the genuine scheduled supervisor may prepare"
        assert [name for name, _, _ in h.ports.calls].count("fail_pending_chat") == 1
    finally:
        await h.close()


async def held_preentry_case(actual, mode):
    h = UnitHarness(actual, cancel_before_entry=True, mode=mode)
    observed_lease = h.ports.pending.lease
    try:
        await h.start()
        await turns()
        assert len(h.execution._slots) == 1 and RUN_ID in h.execution._runs, "charged/denied/unknown entry must retain its local blocker"
        assert h.ports.pending.lease is observed_lease, "unit executor must not replace observed durable lease facts"
        assert not h.context.calls and not h.ai.calls
        assert all(name in {"inspect_chat_request", "admit_chat", "fail_pending_chat", "get_chat_run"}
                   for name, _, _ in h.ports.calls), "pre-entry cleanup must not use force/cancel/charge/dispatch operations"
    finally:
        await h.close()


async def preentry_charged(actual):
    await held_preentry_case(actual, "charged")


async def preentry_denied(actual):
    await held_preentry_case(actual, "denied")


async def preentry_unknown_pending(actual):
    await held_preentry_case(actual, "unknown_pending")


async def preentry_replacement_lease(actual):
    h = UnitHarness(actual, cancel_before_entry=True, mode="replacement")
    observed_lease = h.ports.pending.lease
    before = vars(observed_lease).copy()
    try:
        await h.start()
        await turns()
        assert len(h.execution._slots) == 0 and RUN_ID not in h.execution._runs, "terminal uncharged old run must release only its local capacity"
        assert h.ports.pending.lease is observed_lease and vars(observed_lease) == before, "replacement run lease must remain untouched"
        assert observed_lease.active_run_id != RUN_ID and not h.context.calls and not h.ai.calls
        assert all(name in {"inspect_chat_request", "admit_chat", "fail_pending_chat", "get_chat_run"}
                   for name, _, _ in h.ports.calls), "replacement lease cleanup must never cancel/charge/release another run"
    finally:
        await h.close()


def repository_manifest():
    """Portable standalone regression input; compile only selected current AST."""
    backend = Path(__file__).resolve().parents[1]
    wanted = {
        "app/services/teacher_work/runs.py": ["WorkRunError", "require_chat_slot"],
        "app/repositories/teacher_work.py": ["WorkRepositoryError"],
        "app/services/teacher_work/authorization.py": ["WorkAuthorizationError"],
        "app/services/teacher_work/chat.py": ["ChatPreparationError"],
        "app/services/teacher_work/chat_execution.py": ["ChatExecutionError", "_LocalChat", "_CONTROLLED", "_AI_ERRORS", "TeacherChatExecution"],
    }
    extraction = []
    for relative, names in wanted.items():
        path = backend / relative
        raw = path.read_bytes()
        tree = ast.parse(raw)
        nodes = []
        for name in names:
            matches = [node for node in tree.body if
                (isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name)
                or (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name) and node.targets[0].id == name)]
            assert len(matches) == 1, "exact source node missing/ambiguous"
            nodes.append({"name": name,
                "AST_sha256": hashlib.sha256(ast.dump(matches[0], include_attributes=False).encode()).hexdigest()})
        extraction.append({"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "nodes": nodes})
    return {"extraction_sources": extraction, "selected_cases": list(CASES),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "python_executable": sys.executable,
        "python_executable_sha256": hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest")
    parser.add_argument("--manifest-sha256")
    args = parser.parse_args()
    assert bool(args.manifest) == bool(args.manifest_sha256), "provide both manifest arguments or neither"
    if args.manifest:
        raw = Path(args.manifest).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == args.manifest_sha256, "unit manifest changed"
        manifest = json.loads(raw)
    else:
        manifest = repository_manifest()
        args.manifest_sha256 = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    assert hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == manifest["runner_sha256"], "unit runner changed"
    assert manifest["selected_cases"] == list(CASES), "unit case selection changed"
    assert Path(sys.executable).resolve() == Path(manifest["python_executable"]).resolve(), "unit interpreter changed"
    assert hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest() == manifest["python_executable_sha256"]
    actual = load_actual_source(manifest)
    outcomes = []
    for case in CASES:
        async def bounded_case():
            await asyncio.wait_for(globals()[case](actual), timeout=4)
        try:
            asyncio.run(bounded_case())
        except AssertionError as error:
            outcomes.append({"case": case, "status": "ASSERTION_FAILURE", "assertion": str(error)})
        except BaseException as error:
            outcomes.append({"case": case, "status": "ENVIRONMENT_BLOCKED", "error_type": type(error).__name__})
        else:
            outcomes.append({"case": case, "status": "PASS"})
    forbidden = sorted(name for name in sys.modules if name == "app" or name.startswith(("app.", "sqlalchemy", "pydantic", "httpx", "httpcore")))
    assert not forbidden, "excluded application/dependency module loaded"
    status = "ENVIRONMENT_BLOCKED" if any(item["status"] == "ENVIRONMENT_BLOCKED" for item in outcomes) else "ASSERTION_FAILURES" if any(item["status"] == "ASSERTION_FAILURE" for item in outcomes) else "PASS"
    print(json.dumps({"scope": "NARROW_ACTUAL_EXECUTOR_AST_UNIT_ONLY_NOT_FULL_RUNTIME_GATE",
        "manifest_sha256": args.manifest_sha256, "status": status,
        "outcomes": outcomes, "excluded_modules_loaded": forbidden,
        "boundary_calls": actual.boundary_calls, "cases": list(CASES)}, sort_keys=True), flush=True)
    return 2 if status == "ENVIRONMENT_BLOCKED" else 1 if status == "ASSERTION_FAILURES" else 0


if __name__ == "__main__":
    raise SystemExit(main())
