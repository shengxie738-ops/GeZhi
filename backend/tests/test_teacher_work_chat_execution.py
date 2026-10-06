"""Task4b2B C14-C17: four finite, synthetic execution selectors, UNEXECUTED.

The first source assertion precedes product/dependency/async imports. A later
released GREEN profile uses the actual repository, SQL UoW health assertion
and pure request owner over fresh recording roots. Bootstrap/Session transport
integration is inspected only as source AST, never constructed or executed.
Ports below supply rows, exact CAS, current scalar facts and transaction effects;
they contain no admission, charge, completion, cancellation or replay workflow.
No real Session, Engine, Connection, SQL execution, provider or wall timer exists.
"""
from __future__ import annotations

import ast
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import importlib
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID


BACKEND = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 5, tzinfo=timezone.utc)
PROCESS = UUID("30000000-0000-0000-0000-000000000001")
REF = UUID("40000000-0000-0000-0000-000000000001")
OFFERING = UUID("50000000-0000-0000-0000-000000000001")
ACTUAL_TEXT = "实际模型候选\nUnicode café e\u0301 与末尾空格 "


def _load():
    # Missing feature is the intended baseline RED, before every product import,
    # dependency import, fixture construction, asyncio.run or event operation.
    path = BACKEND / "app/services/teacher_work/chat_execution.py"
    assert path.is_file(), "Task4b2B detached first-call chat executor is missing"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    assert {"TeacherChatExecution", "ChatTransactionOperations", "ChatExecutionContext"} <= classes.keys(), "Task4b2B server-only execution interfaces are missing"
    methods = {node.name for node in classes["TeacherChatExecution"].body
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert {"start_chat", "cancel_chat", "execute_first_chat", "get_chat_run"} <= methods, "Task4b2B first-call execution methods are missing"
    binding_tree = ast.parse((BACKEND / "app/services/teacher_work/bootstrap.py").read_text(encoding="utf-8"))
    binding = next(node for node in binding_tree.body if isinstance(node, ast.ClassDef)
                   and node.name == "_WorkRequestBindings")
    assert any(isinstance(node, ast.FunctionDef) and node.name == "finish_chat_outcome"
               for node in binding.body), "Task4b2B scope-bound chat finalization is missing"
    _bootstrap_source_contract(binding_tree, binding)
    records = ast.parse((BACKEND / "app/services/teacher_work/run_persistence.py").read_text(encoding="utf-8"))
    assert any(isinstance(node, ast.ClassDef) and node.name == "PreparedChatCompletion"
               for node in records.body), "Task4b2B immutable prepared completion is missing"
    repository_tree = ast.parse((BACKEND / "app/repositories/teacher_work.py").read_text(encoding="utf-8"))
    repository = next(node for node in repository_tree.body if isinstance(node, ast.ClassDef)
                      and node.name == "TeacherWorkRepository")
    assert any(isinstance(node, ast.FunctionDef) and node.name == "complete_prepared_chat_call"
               for node in repository.body), "Task4b2B exact prepared completion writer is missing"
    return SimpleNamespace(
        execution=importlib.import_module("app.services.teacher_work.chat_execution"),
        authorization=importlib.import_module("app.services.teacher_work.authorization"),
        repository=importlib.import_module("app.repositories.teacher_work"),
        sql=importlib.import_module("app.repositories.teacher_work_sql"),
        persistence=importlib.import_module("app.services.teacher_work.run_persistence"),
        chat=importlib.import_module("app.services.teacher_work.chat"),
        runs=importlib.import_module("app.services.teacher_work.runs"),
        schema=importlib.import_module("app.schemas.teacher_work"),
        types=importlib.import_module("app.services.teacher_work.types"),
        asyncio=importlib.import_module("asyncio"),
        json=importlib.import_module("json"))


def _bootstrap_source_contract(tree, binding):
    """Source-only production wiring checks, never transport/binding execution.

    The selected internal wiring is transport.uow = repository.uow. Actual
    assert_healthy may occur directly or through transport._verify, but must
    precede both final Session.flush and Session.commit on every such path.
    """
    transport = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                     and node.name == "_SessionWorkTransport")
    methods = {node.name: node for node in transport.body if isinstance(node, ast.FunctionDef)}

    def expanded_calls(method, seen=()):
        result = []
        for call in sorted((node for node in ast.walk(method) if isinstance(node, ast.Call)),
                           key=lambda node: (node.lineno, node.col_offset)):
            target = ast.unparse(call.func)
            if target.startswith("self.") and target[5:] in methods and target[5:] not in seen:
                result.extend(expanded_calls(methods[target[5:]], seen + (target[5:],)))
            result.append(target)
        return result

    for operation in ("flush", "commit"):
        calls = expanded_calls(methods[operation], (operation,))
        assert "self.uow.assert_healthy" in calls, "production transport must check its owned UoW health"
        assert calls.index("self.uow.assert_healthy") < calls.index("self.session." + operation), "owned health must precede final Session " + operation
    constructor = next(node for node in binding.body if isinstance(node, ast.FunctionDef) and node.name == "__init__")
    assert any(isinstance(node, ast.Assign)
               and any(ast.unparse(target) == "self.transport.uow" for target in node.targets)
               and ast.unparse(node.value) == "self.repository.uow"
               for node in ast.walk(constructor)), "production transport must share exactly the repository UoW"
    finalizer = next(node for node in binding.body if isinstance(node, ast.FunctionDef)
                     and node.name == "finish_chat_outcome")
    assert "mode" in {arg.arg for arg in finalizer.args.kwonlyargs}, "chat finalization mode must remain server-bound"
    names = {node.id for node in ast.walk(binding) if isinstance(node, ast.Name)}
    assert {"ChatRequestObservation", "ChatRunAdmission", "ChatCallReservation", "ChatRunOutcome",
            "BoundCandidate", "TeacherWorkRequestOwner", "authorize_task"} <= names, "production chat finalization must retain exact candidate/owner binding"
    guard = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_require_live_admission")
    statements = [node for node in guard.body if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))]
    assert ast.literal_eval(statements[0].value) == {"private_create": "write", "private_read": "read", "private_update": "write",
        "private_chat_read": "read", "private_chat_write": "write",
        "private_material_read": "read", "private_material_save": "write", "private_material_approve": "write",
        "private_package_read":"read","private_package_create":"write","private_package_retry":"write","private_package_file":"write"}
    assert ast.unparse(statements[1].test) == "operation not in expected or mode != expected[operation]"
    assert isinstance(statements[1].body[0], ast.Raise), "ordinary/chat admission must remain closed"
    def rejection(branch):
        assert not branch.orelse and len(branch.body) == 1 and isinstance(branch.body[0], ast.Raise)
        assert ast.unparse(branch.body[0]) == "raise WorkAuthorizationError('TEACHER_WORK_LIVE_GATES_UNVERIFIED', 503)"
    rejection(statements[1])
    assert guard.args.defaults[0].value is None
    rejection(statements[-4])
    assert ast.unparse(statements[-4].test) == "settings.TEACHER_WORK_PRIVATE_TASKS_ENABLED is not True"
    assert ast.unparse(statements[-3].test) == "operation in ('private_chat_read', 'private_chat_write') and settings.TEACHER_WORK_PRIVATE_CHAT_ENABLED is not True"
    assert not statements[-3].orelse and len(statements[-3].body) == 1
    assert ast.unparse(statements[-3].body[0]) == "raise WorkAuthorizationError('PRIVATE_CHAT_DISABLED', 503)"
    assert ast.unparse(statements[-2].test) == "operation in ('private_material_read', 'private_material_save', 'private_material_approve') and settings.TEACHER_WORK_PRIVATE_MATERIALS_ENABLED is not True"
    assert not statements[-2].orelse and len(statements[-2].body) == 1
    assert ast.unparse(statements[-2].body[0]) == "raise WorkAuthorizationError('PRIVATE_MATERIALS_DISABLED', 503)"
    assert ast.unparse(statements[-1].test) == "operation in ('private_package_read', 'private_package_create', 'private_package_retry', 'private_package_file') and settings.TEACHER_WORK_PRIVATE_EXPORTS_ENABLED is not True"
    assert not statements[-1].orelse and len(statements[-1].body)==1
    assert ast.unparse(statements[-1].body[0]) == "raise WorkAuthorizationError('PRIVATE_EXPORTS_DISABLED', 503)"
    first_chat = next(node for node in finalizer.body if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)))
    assert isinstance(first_chat, ast.If) and ast.unparse(first_chat.test) == "self.operation not in (None, 'private_chat_read', 'private_chat_write')"
    assert not first_chat.orelse and len(first_chat.body) == 2
    assert ast.unparse(first_chat.body[0]) == "self._cleanup()"
    assert isinstance(first_chat.body[1], ast.Raise)
    assert ast.unparse(first_chat.body[1]) == "raise WorkAuthorizationError('TEACHER_WORK_LIVE_GATES_UNVERIFIED', 503)"
    for factory_name in ("open_teacher_work_request", "build_request_dependencies"):
        factory = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == factory_name)
        first = next(node for node in factory.body if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)))
        assert isinstance(first, ast.Expr) and isinstance(first.value, ast.Call)
        assert ast.unparse(first.value.func) == "_require_live_admission", "production factory must refuse before setup"
        assert [ast.unparse(arg) for arg in first.value.args] == ["mode", "operation"] and not first.value.keywords
    closed = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "_ClosedLaterOperations")
    for method in (node for node in closed.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))):
        assert len(method.body) == 1 and isinstance(method.body[0], ast.Raise), "later production operations must remain unavailable"


def _uid(prefix, ordinal):
    return UUID(int=(prefix << 120) + ordinal)


class SyntheticCommitFault(Exception):
    pass


class SyntheticFlushFault(Exception):
    pass


class ManualExecutionClock:
    """Explicit UTC/monotonic scalars and finite in-memory deadline futures."""
    def __init__(self, modules, events):
        self.m, self.events = modules, events
        self.utc, self.mono = NOW, 1000.0
        self.waiters = []

    def utc_now(self):
        return self.utc

    def monotonic(self):
        return self.mono

    async def wait_until(self, deadline):
        assert type(deadline) in (int, float) and deadline >= 0
        future = self.m.asyncio.get_running_loop().create_future()
        entry = (deadline, future)
        self.waiters.append(entry)
        self.events.append(("clock.arm", deadline))
        if self.mono >= deadline:
            future.set_result(None)
        try:
            await future
        finally:
            self.waiters.remove(entry)
            self.events.append(("clock.disarm", deadline))

    def advance(self, seconds, *, utc_seconds=None):
        assert seconds >= 0
        self.mono += seconds
        self.utc += timedelta(seconds=seconds if utc_seconds is None else utc_seconds)
        for deadline, future in tuple(self.waiters):
            if self.mono >= deadline and not future.done():
                future.set_result(None)


class RecordingStore:
    """Committed synthetic rows only; a root edits its independent copied view."""
    def __init__(self, modules):
        self.m = modules
        self.tables = {name: {} for name in ("tasks", "drafts", "runs", "messages", "completions", "leases")}
        self.accounts = {}
        self.open_roots = set()
        self.events = []
        self.uuid_no = 0
        for ordinal, owner in enumerate(("A", "B", "C", "D", "E"), 1):
            namespace = _uid(0x10, ordinal)
            self.accounts[owner] = SimpleNamespace(username=owner, role="teacher", namespace=namespace,
                                                   offering_allowed=True)
            self.tables["leases"][owner] = modules.runs.OwnerLeaseFacts(owner, namespace, None, None, None, 1)
            self.seed_task(owner, ordinal)
        self.seed_task("A", 6)

    def seed_task(self, owner, ordinal, *, offering=False):
        task_id, draft_id = _uid(0x20, ordinal), "synthetic-draft-" + str(ordinal)
        task = self.m.schema.WorkTaskDTO(task_id=task_id, owner_subject=owner,
            owner_storage_id=self.accounts[owner].namespace,
            institution_id="synthetic-institution" if offering else None,
            offering_id=OFFERING if offering else None, title="合成任务", topic="合成主题",
            audience="合成对象", duration_minutes=45, target_slide_count=8,
            lesson_draft_id=draft_id, input_revision=1, working_revision=1,
            created_at=NOW, updated_at=NOW)
        self.tables["tasks"][task_id] = self.m.repository.TaskRecord(task, None, None)
        self.tables["drafts"][(owner, draft_id)] = self.m.repository.DraftRecord(owner, draft_id,
            {"draft_id": draft_id, "content": {"title": "原草稿"}, "resource_ids": ["public-1"]})
        return task

    def new_uuid(self):
        self.uuid_no += 1
        return _uid(0x60, self.uuid_no)


class RecordingRoot:
    """Session-shaped data primitive; never a SQLAlchemy Session or connection."""
    def __init__(self, store, operation, mode, fault):
        self.store, self.operation, self.mode, self.fault = store, operation, mode, fault
        self.view = deepcopy(store.tables)
        self.root = SimpleNamespace(origin=store.m.sql.SessionTransactionOrigin.BEGIN, is_active=True)
        self.active = self.is_active = True
        self.pending = self.committed = False
        self.at_finalization = False
        self.new, self.dirty, self.deleted = (), (), ()
        store.open_roots.add(self)
        store.events.append((operation, "begin", self.root))

    def get_transaction(self):
        return self.root if self.active else None

    def in_transaction(self):
        return self.active

    def in_nested_transaction(self):
        return False

    def flush(self):
        assert self.active and self.root.is_active
        if self.at_finalization:
            self.store.events.append((self.operation, "owner.flush", self.root))
        self.store.events.append((self.operation, "root.flush", self.root))
        if self.fault == "repository_flush":
            self.fault = None
            raise SyntheticFlushFault("synthetic flush fault")
        self.pending = False
        self.new, self.dirty, self.deleted = (), (), ()

    def publish(self):
        self.store.tables = deepcopy(self.view)
        self.committed = True

    def commit(self):
        assert self.active and self.root.is_active
        self.store.events.append((self.operation, "commit", self.root))
        if self.fault in ("unknown_unapplied", "unknown_applied", "unknown_applied_deny_read"):
            if self.fault != "unknown_unapplied":
                self.publish()
            if self.fault == "unknown_applied_deny_read":
                self.store.accounts["A"].role = "student"
            raise SyntheticCommitFault("synthetic commit fault")
        self.publish()
        self.active = self.root.is_active = False

    def rollback(self):
        self.store.events.append((self.operation, "rollback", self.root))
        # The committed view is unaffected, including commit-unknown-applied.
        self.active = self.root.is_active = False

    def close(self):
        self.store.events.append((self.operation, "close", self.root))
        self.active = self.root.is_active = False
        self.store.open_roots.discard(self)


class RecordingOwnerTransport:
    """Explicit synthetic owner transport, never the production Session binding.

    The actual UoW's health method is checked before these finite primitives.
    Separate AST inspection must show production wires that same UoW and makes
    both checks. This fixture does not certify real Session transport behavior.
    """
    def __init__(self, root, uow):
        self.session, self.root, self.uow = root, root.root, uow

    def session_identity(self):
        return self.session

    def root_identity(self):
        return self.session.get_transaction()

    def in_transaction(self):
        return self.session.active and self.session.root.is_active

    def has_pending_writes(self):
        return self.session.pending

    def flush(self):
        self.uow.assert_healthy()
        self.session.flush()

    def commit(self):
        self.uow.assert_healthy()
        self.session.commit()
        return self.session.store.m.authorization.CommitReceipt(confirmed=True)

    def rollback(self):
        self.session.rollback()

    def close(self):
        self.session.close()


class RecordingRows:
    """Scoped row reads and exact whole-record CAS; no transition policy."""
    def __init__(self, root):
        self.root = root

    def _event(self, name, *, write=False):
        assert self.root.active
        self.root.store.events.append((self.root.operation, name, self.root.root))
        if write:
            assert self.root.mode == "write"
            self.root.pending = True
            self.root.new = (object(),)

    def find_task(self, owner, task_id):
        self._event("task.discover")
        row = self.root.view["tasks"].get(task_id)
        return row if row is not None and row.task.owner_subject == owner else None

    def lock_owner_lease(self, owner):
        self._event("lease.lock")

    def owner_storage_ids(self, owner):
        return (self.root.view["leases"][owner].owner_storage_id,)

    def lock_draft(self, owner, draft_id):
        self._event("draft.lock")
        return self.root.view["drafts"].get((owner, draft_id))

    def lock_task(self, owner, task_id):
        self._event("task.lock")
        return self.find_task(owner, task_id)

    def lease(self, owner):
        self._event("lease.read")
        return self.root.view["leases"][owner]

    def find_run_by_key(self, owner, task_id, kind, encoded_key):
        self._event("run.receipt")
        assert type(encoded_key) is bytes
        return next((state for state in self.root.view["runs"].values()
            if (state.run.owner, state.run.task_id, state.run.kind, state.run.idempotency_key.encode("utf-8"))
            == (owner, task_id, kind, encoded_key)), None)

    def lock_run(self, owner, task_id, run_id):
        self._event("run.lock")
        state = self.root.view["runs"].get(run_id)
        return state if state is not None and (state.run.owner, state.run.task_id) == (owner, task_id) else None

    def find_user_message(self, owner, task_id, encoded_key):
        self._event("message.user.read")
        assert type(encoded_key) is bytes
        return next((message for message in self.root.view["messages"].values()
            if (message.owner, message.task_id, message.role) == (owner, task_id, "user")
            and message.client_message_key is not None
            and message.client_message_key.encode("utf-8") == encoded_key), None)

    def find_completion(self, owner, task_id, run_id):
        self._event("message.completion.read")
        pair = self.root.view["completions"].get(run_id)
        return pair if pair is not None and (pair[1].owner, pair[1].task_id) == (owner, task_id) else None

    def insert_run(self, state):
        self._event("run.insert", write=True)
        assert state.run.run_id not in self.root.view["runs"]
        self.root.view["runs"][state.run.run_id] = state

    def insert_user_message(self, message):
        self._event("message.user.insert", write=True)
        assert message.message_id not in self.root.view["messages"]
        self.root.view["messages"][message.message_id] = message

    def insert_completion(self, message, receipt):
        self._event("message.completion.insert", write=True)
        assert message.message_id not in self.root.view["messages"]
        assert receipt.run_id not in self.root.view["completions"]
        self.root.view["messages"][message.message_id] = message
        self.root.view["completions"][receipt.run_id] = (receipt, message)

    def cas_run(self, before, after):
        self._event("run.cas", write=True)
        if self.root.view["runs"].get(before.run.run_id) != before:
            return False
        self.root.view["runs"][before.run.run_id] = after
        return True

    def cas_lease(self, before, after):
        self._event("lease.cas", write=True)
        if self.root.view["leases"].get(before.owner) != before:
            return False
        self.root.view["leases"][before.owner] = after
        return True


class ActualCommandTransactions:
    """Synchronous server composition of real commands and real finalization."""
    def __init__(self, modules, store, clock):
        self.m, self.store, self.clock = modules, store, clock
        self.scripts = {}
        self.prepared_attempts = []
        self.candidates = []
        self.roots = []
        self.gap_after_reserve = 0

    def _call(self, name, mode, *args, **kwargs):
        script = self.scripts.get(name, [])
        fault = script.pop(0) if script else None
        root = RecordingRoot(self.store, name, mode, fault)
        self.roots.append(root)
        uow = self.m.sql.SqlWorkUnitOfWork(root)
        rows = RecordingRows(root)
        transport = RecordingOwnerTransport(root, uow)
        facts = SimpleNamespace(actor=None, held=None, namespace=None, account=None, decision=None)

        def authorize_locked(owner, offering_id, institution_id):
            self.store.events.append((name, "footprint", root.root))
            account = self.store.accounts.get(owner)
            if account is None:
                raise self.m.repository.WorkRepositoryError("NOT_FOUND", 404)
            self.m.authorization.require_current_teacher_facts(owner,
                self.m.authorization.CurrentAccountFacts(account.username, account.role))
            if offering_id is not None and account.offering_allowed is not True:
                raise self.m.repository.WorkRepositoryError("OFFERING_AUTHORITY_REQUIRED", 403)
            if facts.held is None:
                policy = self.m.authorization.PolicySnapshot("synthetic-policy", institution_id)
                facts.held = self.m.authorization.HeldWorkAuthority(owner, institution_id, offering_id, object(), policy)
                facts.namespace = self.m.authorization.NamespaceReceipt(owner, account.namespace, False,
                    mode, facts.held.footprint_token)
                facts.actor = self.m.authorization.bind_work_actor(owner, facts.namespace)
                facts.account = account
                if offering_id is not None:
                    facts.decision = self.m.authorization.OfferingDecision(owner, institution_id,
                        offering_id, "READ_OFFERING", True, True)
            return self.m.repository.AuthorizedWorkScope(facts.actor, institution_id, offering_id)

        def namespace_observer():
            self.store.events.append((name, "namespace.verify", root.root))
            if root.at_finalization and fault == "poison_before_commit":
                uow.poison()
            return self.m.authorization.NamespaceObservation(facts.actor.subject,
                root.view["leases"][facts.actor.subject].owner_storage_id)

        def evaluate_held(held, policy, at):
            account = facts.account
            self.m.authorization.require_current_teacher_facts(facts.actor.subject,
                self.m.authorization.CurrentAccountFacts(account.username, account.role))
            return self.m.authorization.HeldAdmissionReceipt(held.subject, held.institution_id,
                held.offering_id, held.footprint_token, policy.generation, at,
                account.offering_allowed if held.offering_id is not None else True)

        repository = self.m.repository.TeacherWorkRepository(uow=uow, rows=rows, drafts=rows,
            run_rows=rows, authorize_locked=authorize_locked, clock=self.clock.utc_now,
            new_uuid=self.store.new_uuid)
        try:
            if name == "complete_prepared_chat_call":
                self.prepared_attempts.append(args[0])
            value = getattr(repository, name)(*args, **kwargs)
            self.candidates.append((name, value, root))
            # Candidates have not escaped as committed results at this point.
            if name == "admit_chat" and value.created:
                assert value.state.run.run_id not in self.store.tables["runs"]
            elif name == "reserve_chat_call":
                assert self.store.tables["runs"][value.state.run.run_id].run.provider_call_count + 1 == value.state.run.provider_call_count
            elif name == "complete_prepared_chat_call" and root.pending:
                assert value.completion.message_id not in self.store.tables["messages"]
            self.store.events.append((name, "candidate.uncommitted", root.root))
            root.at_finalization = True
            if fault == "poison_final":
                uow.poison()
            elif fault == "demote_final":
                self.store.accounts[facts.actor.subject].role = "student"
            context = self.m.authorization.authorize_task(facts.actor, value.task, facts.decision)
            candidate = self.m.authorization.BoundCandidate(value, context.actor_subject,
                context.owner_storage_id, context.institution_id, context.offering_id)
            request_owner = self.m.authorization.TeacherWorkRequestOwner(transport=transport, mode=mode,
                actor=facts.actor, namespace_receipt=facts.namespace, authority=facts.held,
                clock=self.clock.utc_now, policy_provider=lambda: facts.held.policy,
                namespace_observer=namespace_observer, evaluate_held=evaluate_held)
            result = request_owner.finish_write(candidate) if mode == "write" else request_owner.finish_read(candidate)
            assert result is value, "owner finalization must return the exact validated candidate"
            assert root not in self.store.open_roots and root.active is False
            self.store.events.append((name, "return.closed", root.root))
            if name == "reserve_chat_call" and self.gap_after_reserve:
                self.clock.advance(self.gap_after_reserve)
            return result
        except BaseException:
            if root in self.store.open_roots:
                transport.rollback()
                transport.close()
            raise

    def inspect_chat_request(self, owner, task_id, command, key):
        return self._call("inspect_chat_request", "read", owner, task_id, command, key)

    def admit_chat(self, owner, task_id, command, key, *, process_instance, configured_timeout_seconds):
        return self._call("admit_chat", "write", owner, task_id, command, key,
            process_instance=process_instance, configured_timeout_seconds=configured_timeout_seconds)

    def reserve_chat_call(self, owner, task_id, run_id, *, process_instance,
                          configured_output_tokens, configured_timeout_seconds, repair=False):
        return self._call("reserve_chat_call", "write", owner, task_id, run_id,
            process_instance=process_instance, configured_output_tokens=configured_output_tokens,
            configured_timeout_seconds=configured_timeout_seconds, repair=repair)

    def complete_prepared_chat_call(self, prepared):
        return self._call("complete_prepared_chat_call", "write", prepared)

    def fail_chat_call(self, original_ctx, token, error_code):
        return self._call("fail_chat_call", "write", original_ctx, token, error_code)

    def expire_chat_call(self, original_ctx, token):
        return self._call("expire_chat_call", "write", original_ctx, token)

    def fail_pending_chat(self, owner, task_id, run_id, *, process_instance, error_code):
        return self._call("fail_pending_chat", "write", owner, task_id, run_id,
            process_instance=process_instance, error_code=error_code)

    def cancel_chat(self, owner, task_id, run_id):
        return self._call("cancel_chat", "write", owner, task_id, run_id)

    def get_chat_run(self, owner, task_id, run_id):
        return self._call("get_chat_run", "read", owner, task_id, run_id)


class ServerSelectedContext:
    """Only explicit synthetic server-owned command/history/evidence snapshots."""
    def __init__(self, modules, store):
        self.m, self.store = modules, store
        self.commands, self.histories, self.evidence = {}, {}, {}
        self.unavailable = False

    def load(self, admission):
        assert not self.store.open_roots, "context preparation must be detached"
        self.store.events.append(("context.prepare", admission.state.run.run_id))
        if self.unavailable:
            raise self.m.authorization.WorkAuthorizationError("WORK_EVIDENCE_UNAVAILABLE", 503)
        task_id = admission.task.task_id
        return self.m.execution.ChatExecutionContext(command=self.commands[task_id],
            history=self.histories.get(task_id, ()), evidence=self.evidence.get(task_id, ()))


class SyntheticProviderCall:
    def __init__(self, modules, store, raw, ignore_cancel):
        self.m, self.store, self.raw, self.ignore_cancel = modules, store, raw, ignore_cancel
        self.gate = modules.asyncio.get_running_loop().create_future()
        self.task = None
        self.cancel_requests = 0
        self.terminal = False

    def release(self):
        if not self.gate.done():
            self.gate.set_result(None)


class ExplicitSyntheticWorkAI:
    """Actual awaited tasks with controlled terminal events; no httpx/client."""
    def __init__(self, modules, store):
        self.m, self.store = modules, store
        self.calls = []
        self.raw = modules.json.dumps({"type": "revision_proposal", "plain_text": ACTUAL_TEXT,
                                      "result_refs": [str(REF)]}, ensure_ascii=False)
        self.ignore_cancel = True

    async def complete(self, prompt, *, max_output_tokens, timeout_seconds):
        assert not self.store.open_roots, "provider await must hold no caller root"
        assert 1 <= max_output_tokens <= 8192 and 1 <= timeout_seconds <= 90
        call = SyntheticProviderCall(self.m, self.store, self.raw, self.ignore_cancel)
        call.task = self.m.asyncio.current_task()
        call.prompt, call.tokens, call.timeout = prompt, max_output_tokens, timeout_seconds
        self.calls.append(call)
        self.store.events.append(("provider.enter", call))
        try:
            while not call.gate.done():
                try:
                    await self.m.asyncio.shield(call.gate)
                except self.m.asyncio.CancelledError:
                    call.cancel_requests += 1
                    self.store.events.append(("provider.cancel_requested", call))
                    if not call.ignore_cancel:
                        raise
            return call.raw
        finally:
            call.terminal = True
            self.store.events.append(("provider.terminal", call))


class Harness:
    def __init__(self, modules):
        self.m = modules
        self.store = RecordingStore(modules)
        self.clock = ManualExecutionClock(modules, self.store.events)
        self.transactions = ActualCommandTransactions(modules, self.store, self.clock)
        self.context = ServerSelectedContext(modules, self.store)
        self.ai = ExplicitSyntheticWorkAI(modules, self.store)
        self.supervisors = []
        self.schedule_failure = False
        self.failed_coroutine = None
        self.execution = modules.execution.TeacherChatExecution(transactions=self.transactions,
            ai=self.ai, context_source=self.context, process_instance=PROCESS, clock=self.clock,
            new_uuid=self.store.new_uuid, configured_output_tokens=12000,
            configured_timeout_seconds=200, capacity=4, schedule=self.schedule)

    def schedule(self, coroutine):
        assert not self.store.open_roots, "supervisor starts only after admission close"
        self.store.events.append(("supervisor.schedule", coroutine))
        if self.schedule_failure:
            self.failed_coroutine = coroutine
            raise RuntimeError("synthetic scheduling fault")
        task = self.m.asyncio.create_task(coroutine)
        self.supervisors.append(task)
        return task

    def command(self, ordinal=1, *, text="当前教师输入", key=None):
        command = self.m.schema.ChatCommand(kind="chat", input_revision=1, skill_ref=None,
            payload=self.m.schema.ChatInput(text=text, client_message_key=key or "用户 Key " + str(ordinal)))
        task_id = _uid(0x20, ordinal)
        self.context.commands[task_id] = command
        self.context.evidence[task_id] = (self.m.schema.EvidenceSnapshotDTO(evidence_id=REF,
            task_id=task_id, resource_id="public-1", name="合成证据", page=1,
            excerpt="合成公开内容", resource_content_digest="a" * 64,
            acquired_at=NOW, evidence_type="courseware"),)
        return command

    async def start(self, owner="A", ordinal=1, *, command=None, key=None):
        return await _finite_result(self.m, self.execution.start_chat(owner, _uid(0x20, ordinal),
            command or self.command(ordinal), key or "运行 Key " + str(ordinal)))

    async def cancel(self, run):
        return await _finite_result(self.m, self.execution.cancel_chat(run.owner, run.task_id, run.run_id))

    def state(self, run):
        return self.store.tables["runs"][run.run_id]

    def assistant_messages(self):
        return tuple(message for message in self.store.tables["messages"].values() if message.role == "assistant")

    async def turns(self, count=32):
        # Finite event-loop turns, with no sleep, timer or real elapsed time.
        for _ in range(count):
            future = self.m.asyncio.get_running_loop().create_future()
            self.m.asyncio.get_running_loop().call_soon(future.set_result, None)
            await future

    async def drain(self):
        await self.turns(48)
        assert all(task.done() for task in self.supervisors), "finite supervisor did not reach its expected endpoint"
        for task in self.supervisors:
            if not task.cancelled():
                error = task.exception()
                assert error is None or hasattr(error, "code"), "detached task leaked an uncontrolled error"

    async def cleanup(self):
        for call in self.ai.calls:
            call.release()
        self.clock.advance(10000)
        await self.turns(48)
        for call in self.ai.calls:
            call.release()
        await self.turns(32)
        pending = tuple(task for task in self.m.asyncio.all_tasks()
                        if task is not self.m.asyncio.current_task() and not task.done())
        for task in pending:
            task.cancel()
        await self.turns(32)
        assert all(task.done() for task in pending), "synthetic provider/timer tasks did not settle"
        assert not self.store.open_roots, "a caller transaction escaped its operation"
        assert not self.clock.waiters, "a deterministic deadline waiter escaped cleanup"


async def _finite_result(modules, coroutine):
    """A finite-turn watchdog, not a wall-clock timeout or production timer.

    A capacity queue, provider wait inside start, or blocking cancel cannot hang
    this test indefinitely. The operation must finish within the fixed synthetic
    scheduling window; on failure only that operation receives cancellation.
    """
    task = modules.asyncio.create_task(coroutine)
    for _ in range(48):
        if task.done():
            return task.result()
        future = modules.asyncio.get_running_loop().create_future()
        modules.asyncio.get_running_loop().call_soon(future.set_result, None)
        await future
    task.cancel()
    for _ in range(32):
        if task.done():
            break
        future = modules.asyncio.get_running_loop().create_future()
        modules.asyncio.get_running_loop().call_soon(future.set_result, None)
        await future
    raise AssertionError("immediate start/cancel operation remained pending in the finite event window")


async def _expect_async_code(code, operation):
    try:
        await operation
    except Exception as error:
        assert getattr(error, "code", None) == code, (code, type(error).__name__, getattr(error, "code", None))
        return error
    raise AssertionError("expected controlled " + code)


def _expect_code(code, operation):
    try:
        operation()
    except Exception as error:
        assert getattr(error, "code", None) == code, (code, type(error).__name__, getattr(error, "code", None))
        return error
    raise AssertionError("expected controlled " + code)


def _positions(events, operation, event):
    return [index for index, entry in enumerate(events) if len(entry) == 3 and entry[:2] == (operation, event)]


async def _c14(modules):
    # C14-01: real finalized admission/charge/completion, detached preparation,
    # chronological history suffix, exact actual Unicode/refs/omission metadata.
    h = Harness(modules)
    try:
        command = h.command()
        history = tuple(modules.schema.WorkMessageDTO(message_id=_uid(0x70, index + 1),
            task_id=_uid(0x20, 1), owner="A", role="assistant", plain_text="历史 " + str(index),
            created_at=NOW + timedelta(microseconds=index)) for index in range(12))
        h.context.histories[_uid(0x20, 1)] = history
        run = await h.start(command=command)
        await h.turns()
        assert len(h.ai.calls) == 1 and h.state(run).run.provider_call_count == 1
        call = h.ai.calls[0]
        prompt = modules.json.loads(call.prompt)
        assert prompt["current_input"] == command.payload.text
        assert prompt["history"] == [{"role": item.role, "plain_text": item.plain_text} for item in history[-11:]]
        assert call.tokens == 8192 and call.timeout == 90
        assert h.assistant_messages() == ()
        assert h.state(run).active_call is not None
        call.release()
        await h.drain()
        state = h.state(run)
        message, = h.assistant_messages()
        assert state.run.stage == "COMPLETE" and state.active_call is None
        assert state.run.provider_call_count == 1 and state.repair_count == 0 and state.run.attempt == 1
        assert message.plain_text == ACTUAL_TEXT and message.result_type == "revision_proposal"
        assert message.result_refs == (REF,) and message.omitted_context is True and message.client_message_key is None
        assert h.store.tables["leases"]["A"].active_run_id is None
        result = h.execution.get_chat_run("A", run.task_id, run.run_id)
        assert result.stage == "COMPLETE" and len(h.ai.calls) == 1
        events = h.store.events
        provider_enter = next(i for i, entry in enumerate(events) if entry[0] == "provider.enter")
        assert _positions(events, "admit_chat", "commit")[0] < _positions(events, "admit_chat", "close")[0]
        assert _positions(events, "admit_chat", "close")[0] < next(i for i, e in enumerate(events) if e[0] == "context.prepare")
        assert _positions(events, "reserve_chat_call", "commit")[0] < _positions(events, "reserve_chat_call", "close")[0] < provider_enter
        assert provider_enter < _positions(events, "complete_prepared_chat_call", "begin")[0]
        assert _positions(events, "complete_prepared_chat_call", "commit")[0] < _positions(events, "complete_prepared_chat_call", "close")[0] < _positions(events, "complete_prepared_chat_call", "return.closed")[0]
        assert len({id(root.root) for root in h.transactions.roots}) == len(h.transactions.roots)
        assert all(not root.active for root in h.transactions.roots)
    finally:
        await h.cleanup()

    # C14-02..05: unknown admission and unknown charge, both physical outcomes.
    # No new dispatch can be inferred from a committed-looking observation.
    for operation in ("admit_chat", "reserve_chat_call"):
        for fault in ("unknown_applied", "unknown_unapplied"):
            h = Harness(modules)
            try:
                h.transactions.scripts[operation] = [fault]
                if operation == "admit_chat":
                    await _expect_async_code("COMMIT_OUTCOME_UNKNOWN", h.start())
                else:
                    run = await h.start()
                    await h.drain()
                    assert h.state(run).run.provider_call_count == (1 if fault == "unknown_applied" else 0)
                    assert h.state(run).run.stage == ("CHAT_RUNNING" if fault == "unknown_applied" else "PENDING")
                    assert (h.state(run).active_call is not None) is (fault == "unknown_applied")
                    assert h.store.tables["leases"]["A"].active_run_id == run.run_id
                assert h.ai.calls == [] and h.assistant_messages() == ()
                if fault == "unknown_applied" and operation == "admit_chat":
                    stored, = h.store.tables["runs"].values()
                    observed = h.execution.get_chat_run("A", stored.run.task_id, stored.run.run_id)
                    assert observed.run_id == stored.run.run_id and h.ai.calls == []
                assert not h.store.open_roots
            finally:
                await h.cleanup()

    # C14-06..07: completion unknown is reconciled in a fresh authorized root.
    # Unapplied write retries the very same message/result/time/token object;
    # applied write observes its exact receipt, with no second model call/row.
    for fault, attempts in (("unknown_unapplied", 2), ("unknown_applied", 1)):
        h = Harness(modules)
        try:
            h.transactions.scripts["complete_prepared_chat_call"] = [fault]
            run = await h.start()
            await h.turns()
            h.ai.calls[0].release()
            await h.drain()
            assert len(h.ai.calls) == 1 and h.state(run).run.stage == "COMPLETE"
            assert len(h.assistant_messages()) == 1
            prepared = h.transactions.prepared_attempts
            assert len(prepared) == attempts and all(value is prepared[0] for value in prepared)
            assert prepared[0].message == h.assistant_messages()[0]
            assert prepared[0].receipt == h.store.tables["completions"][run.run_id][0]
            assert prepared[0].message.created_at == NOW
            assert type(prepared[0]) is modules.persistence.PreparedChatCompletion
            assert type(prepared[0].allowed_result_refs) is frozenset
            assert type(prepared[0].result.result_refs) is tuple and type(prepared[0].message.result_refs) is tuple
            assert _positions(h.store.events, "get_chat_run", "begin"), "unknown completion needs fresh observation"
            for value, attribute in ((prepared[0], "message"), (prepared[0].message, "plain_text"),
                                     (prepared[0].result, "plain_text"), (prepared[0].token, "call_no")):
                original = getattr(value, attribute)
                try:
                    setattr(value, attribute, original)
                except (AttributeError, TypeError, ValueError):
                    pass
                else:
                    raise AssertionError("prepared completion payload must be immutable in substance")
        finally:
            await h.cleanup()

    # C14-08..09: actual shared UoW poison prevents owner flush/commit, for both
    # an admission candidate and a proposed assistant completion candidate.
    for operation in ("admit_chat", "complete_prepared_chat_call"):
        h = Harness(modules)
        try:
            h.transactions.scripts[operation] = ["poison_final"]
            if operation == "admit_chat":
                await _expect_async_code("SQL_TRANSACTION_POISONED", h.start())
                assert not h.store.tables["runs"] and not h.store.tables["messages"] and h.ai.calls == []
            else:
                run = await h.start()
                await h.turns()
                h.ai.calls[0].release()
                await h.drain()
                assert h.state(run).run.stage != "COMPLETE" and h.assistant_messages() == ()
            assert not _positions(h.store.events, operation, "owner.flush")
            assert not _positions(h.store.events, operation, "commit")
            assert _positions(h.store.events, operation, "rollback") and _positions(h.store.events, operation, "close")
        finally:
            await h.cleanup()

    # C14-10: health is checked again before the final commit primitive, even
    # if the root becomes poisoned during final held admission after flush.
    h = Harness(modules)
    try:
        h.transactions.scripts["admit_chat"] = ["poison_before_commit"]
        await _expect_async_code("COMMIT_OUTCOME_UNKNOWN", h.start())
        assert _positions(h.store.events, "admit_chat", "owner.flush")
        assert not _positions(h.store.events, "admit_chat", "commit")
        assert not h.store.tables["runs"] and not h.store.tables["messages"] and h.ai.calls == []
    finally:
        await h.cleanup()

    # C14-11: a repository flush failure never reaches final commit/scheduling.
    h = Harness(modules)
    try:
        h.transactions.scripts["admit_chat"] = ["repository_flush"]
        try:
            await h.start()
        except Exception as error:
            assert getattr(error, "code", None) in {"WRITE_ABORTED", "WORK_EXECUTION_UNAVAILABLE"}, "primitive admission failure must be sanitized"
        else:
            raise AssertionError("a failed admission flush cannot return a run")
        assert h.ai.calls == [] and not h.supervisors and not h.store.tables["runs"]
        assert not _positions(h.store.events, "admit_chat", "commit")
    finally:
        await h.cleanup()



async def _c15(modules):
    # C15-01..03: four immediate slots, fifth zero-write reject, exact authorized
    # replay when full returns stored receipt without scheduling or another call.
    h = Harness(modules)
    try:
        runs = [await h.start(owner, ordinal) for ordinal, owner in enumerate(("A", "B", "C", "D"), 1)]
        await h.turns()
        assert len(h.ai.calls) == 4 and len(h.supervisors) == 4
        before = deepcopy(h.store.tables)
        error = await _expect_async_code("INSTANCE_BUSY", h.start("E", 5))
        assert error.status_code == 429 and h.store.tables == before
        replay = await h.start("A", 1)
        assert replay.run_id == runs[0].run_id and len(h.supervisors) == 4 and len(h.ai.calls) == 4
        assert h.store.tables == before
        # C15-04: same key/different digest is still a conflict at full capacity.
        await _expect_async_code("IDEMPOTENCY_CONFLICT", h.start("A", 1,
            command=h.command(text="不同教师输入")))
        assert h.store.tables == before
        # C15-05: full-capacity replay still requires current authority.
        h.store.accounts["A"].role = "student"
        await _expect_async_code("CURRENT_TEACHER_REQUIRED", h.start("A", 1))
        assert h.store.tables == before and len(h.ai.calls) == 4
        h.store.accounts["A"].role = "teacher"
    finally:
        await h.cleanup()

    # C15-06: scheduling failure follows actual no-call repository settlement;
    # closed coroutine, zero provider calls and truthful real run locator.
    h = Harness(modules)
    try:
        h.schedule_failure = True
        error = await _expect_async_code("WORK_EXECUTION_UNAVAILABLE", h.start())
        stored, = h.store.tables["runs"].values()
        assert getattr(error, "run_id", None) == stored.run.run_id
        assert stored.run.stage == "FAILED" and stored.run.provider_call_count == 0 and stored.active_call is None
        assert h.store.tables["leases"]["A"].active_run_id is None and h.ai.calls == []
        assert h.failed_coroutine is not None and h.failed_coroutine.cr_frame is None
        h.schedule_failure = False
        run = await h.start("A", 6)
        await h.turns()
        assert len(h.ai.calls) == 1 and h.state(run).run.provider_call_count == 1
    finally:
        await h.cleanup()

    # C15-07: failed admission releases only its local reservation; later four
    # independent owners can still start, proving no leaked fifth-slot queue.
    h = Harness(modules)
    try:
        h.transactions.scripts["admit_chat"] = ["demote_final"]
        await _expect_async_code("CURRENT_TEACHER_REQUIRED", h.start())
        h.store.accounts["A"].role = "teacher"
        runs = [await h.start(owner, ordinal) for ordinal, owner in enumerate(("A", "B", "C", "D"), 1)]
        await h.turns()
        assert len(runs) == len(h.ai.calls) == 4
    finally:
        await h.cleanup()

    # C15-08: cross-task owner conflict is an actual durable coordinator decision
    # and must not consume a second local reservation or charged call.
    h = Harness(modules)
    try:
        await h.start()
        await h.turns()
        before = deepcopy(h.store.tables)
        await _expect_async_code("OWNER_RUN_BUSY", h.start("A", 6))
        assert h.store.tables == before and len(h.ai.calls) == 1
        for ordinal, owner in enumerate(("B", "C", "D"), 2):
            await h.start(owner, ordinal)
        await h.turns()
        assert len(h.ai.calls) == 4
    finally:
        await h.cleanup()


async def _c16(modules):
    # C16-01..03: durable cancel first, ignored Task.cancel remains nonterminal,
    # owner token/lease and all four local slots persist until real settlement.
    h = Harness(modules)
    try:
        runs = [await h.start(owner, ordinal) for ordinal, owner in enumerate(("A", "B", "C", "D"), 1)]
        await h.turns()
        before = h.state(runs[0])
        lease = h.store.tables["leases"]["A"]
        cancelled = await h.cancel(runs[0])
        await h.turns()
        assert cancelled.stage == "CANCELLED" and h.state(runs[0]).active_call == before.active_call
        assert h.store.tables["leases"]["A"] == lease
        call = h.ai.calls[0]
        assert call.cancel_requests >= 1 and not call.task.done() and not call.terminal
        await _expect_async_code("INSTANCE_BUSY", h.start("E", 5))
        events = h.store.events
        assert _positions(events, "cancel_chat", "close")[0] < next(i for i, e in enumerate(events) if e[0] == "provider.cancel_requested")
        call.release()
        await h.turns()
        assert call.terminal and h.state(runs[0]).run.stage == "CANCELLED"
        assert h.state(runs[0]).active_call is None and h.store.tables["leases"]["A"].active_run_id is None
        assert h.assistant_messages() == ()
        assert h.state(runs[0]).run.provider_call_count == 1 and h.state(runs[0]).run.deadline == before.run.deadline
        await h.start("E", 5)
        await h.turns()
        assert len(h.ai.calls) == 5
    finally:
        await h.cleanup()

    # C16-04: persisted absolute deadline, logical failure and best-effort stop
    # cannot clear token/lease or local capacity before ignored call settles.
    h = Harness(modules)
    try:
        run = await h.start()
        await h.turns()
        state, lease = h.state(run), h.store.tables["leases"]["A"]
        h.clock.advance(270)
        await h.turns()
        assert h.ai.calls[0].cancel_requests >= 1 and not h.ai.calls[0].terminal
        assert h.state(run).run.stage == "FAILED" and h.state(run).run.error_code == "WORK_AI_TIMEOUT"
        assert h.state(run).active_call == state.active_call and h.store.tables["leases"]["A"] == lease
        for ordinal, owner in enumerate(("B", "C", "D"), 2):
            await h.start(owner, ordinal)
        await _expect_async_code("INSTANCE_BUSY", h.start("E", 5))
        h.ai.calls[0].release()
        await h.turns()
        assert h.state(run).run.stage == "FAILED" and h.state(run).active_call is None
        assert h.assistant_messages() == () and h.state(run).run.deadline == state.run.deadline
    finally:
        await h.cleanup()

    # C16-05: local monotonic deadline never renews when wall UTC goes backward;
    # late success remains forbidden even while UTC is before the stored deadline.
    h = Harness(modules)
    try:
        run = await h.start()
        await h.turns()
        h.clock.advance(270, utc_seconds=-3600)
        await h.turns()
        assert h.clock.utc_now() < NOW and h.ai.calls[0].cancel_requests >= 1
        assert not h.ai.calls[0].terminal and h.state(run).active_call is not None
        h.ai.calls[0].release()
        await h.drain()
        assert h.state(run).run.stage == "FAILED" and h.state(run).run.error_code == "WORK_AI_TIMEOUT"
        assert h.state(run).active_call is None and h.assistant_messages() == ()
    finally:
        await h.cleanup()

    # C16-06: elapsed preparation/claim gap consumes the same local budget;
    # confirmed charge is never refunded and transport must never start late.
    h = Harness(modules)
    try:
        h.transactions.gap_after_reserve = 270
        run = await h.start()
        await h.drain()
        assert h.ai.calls == [] and h.assistant_messages() == ()
        assert h.state(run).run.provider_call_count == 1 and h.state(run).run.stage == "FAILED"
        assert h.state(run).active_call is None and h.store.tables["leases"]["A"].active_run_id is None
    finally:
        await h.cleanup()

    # C16-07: cancellation that really terminates the awaited provider releases
    # after that terminal event, with no assistant, rather than retaining forever.
    h = Harness(modules)
    try:
        h.ai.ignore_cancel = False
        run = await h.start()
        await h.turns()
        await h.cancel(run)
        await h.drain()
        assert h.ai.calls[0].terminal and h.ai.calls[0].task.done()
        assert h.state(run).run.stage == "CANCELLED" and h.state(run).active_call is None
        assert h.store.tables["leases"]["A"].active_run_id is None and h.assistant_messages() == ()
        terminal = next(i for i, e in enumerate(h.store.events) if e[0] == "provider.terminal")
        assert terminal < _positions(h.store.events, "fail_chat_call", "begin")[0]
    finally:
        await h.cleanup()


    # C16-08: the 90-second first-call limit is an outer local bound as well as
    # a supplied WorkAI option. A nonterminal cancellation at that limit cannot
    # erase the later absolute deadline or release the still-live handle.
    h = Harness(modules)
    try:
        run = await h.start()
        await h.turns()
        state, lease = h.state(run), h.store.tables["leases"]["A"]
        h.clock.advance(90)
        await h.turns()
        assert h.clock.utc_now() < state.run.deadline
        assert h.ai.calls[0].cancel_requests >= 1 and not h.ai.calls[0].terminal
        assert h.state(run).active_call == state.active_call and h.store.tables["leases"]["A"] == lease
        assert h.assistant_messages() == ()
        h.ai.calls[0].release()
        await h.drain()
        assert h.state(run).run.stage == "FAILED" and h.state(run).run.error_code == "WORK_AI_TIMEOUT"
        assert h.state(run).active_call is None and h.state(run).run.deadline == state.run.deadline
    finally:
        await h.cleanup()


async def _c17(modules):
    # C17-01..04: raw parser rejects duplicate names, fences, tool authority and
    # unknown refs. One cumulative billed call, no repair, no assistant success.
    invalid = (
        '{"type":"answer","plain_text":"first","plain_text":"second"}',
        '```json\n{"type":"answer","plain_text":"candidate"}\n```',
        '{"type":"answer","plain_text":"candidate","approved":true,"handler":"publish"}',
        '{"type":"answer","plain_text":"candidate","result_refs":["40000000-0000-0000-0000-000000000002"]}',
    )
    for raw in invalid:
        h = Harness(modules)
        try:
            h.ai.raw = raw
            run = await h.start()
            await h.turns()
            h.ai.calls[0].release()
            await h.drain()
            state = h.state(run)
            assert state.run.stage == "FAILED" and state.run.error_code == "WORK_AI_INVALID_RESPONSE"
            assert state.run.provider_call_count == 1 and state.repair_count == 0 and state.run.attempt == 1
            assert len(h.ai.calls) == 1 and state.active_call is None and h.assistant_messages() == ()
            assert h.store.tables["leases"]["A"].active_run_id is None
        finally:
            await h.cleanup()

    # C17-05..07: freshly changed account/offering/revision blocks content.
    # Current authority denial retains the durable token/lease; stale revision
    # permits exact no-content settlement under current authorized task locks.
    for denial in ("demotion", "offering", "revision"):
        h = Harness(modules)
        try:
            if denial == "offering":
                h.store.seed_task("A", 1, offering=True)
            run = await h.start()
            await h.turns()
            state, lease = h.state(run), h.store.tables["leases"]["A"]
            if denial == "demotion":
                h.store.accounts["A"].role = "student"
            elif denial == "offering":
                h.store.accounts["A"].offering_allowed = False
            else:
                row = h.store.tables["tasks"][run.task_id]
                h.store.tables["tasks"][run.task_id] = replace(row,
                    task=row.task.model_copy(update={"input_revision": 2, "working_revision": 2}))
            h.ai.calls[0].release()
            await h.drain()
            assert len(h.ai.calls) == 1 and h.assistant_messages() == () and h.state(run).run.stage != "COMPLETE"
            if denial == "revision":
                assert h.state(run).active_call is None and h.store.tables["leases"]["A"].active_run_id is None
            else:
                assert h.state(run).active_call == state.active_call and h.store.tables["leases"]["A"] == lease
            assert h.state(run).run.provider_call_count == 1 and h.state(run).run.deadline == state.run.deadline
        finally:
            await h.cleanup()

    # C17-08: source readiness failure occurs before a charged call; no silently
    # empty evidence fallback, canned content or provider request is acceptable.
    h = Harness(modules)
    try:
        h.context.unavailable = True
        run = await h.start()
        await h.drain()
        assert h.ai.calls == [] and h.assistant_messages() == ()
        assert h.state(run).run.stage == "FAILED" and h.state(run).run.provider_call_count == 0
        assert h.store.tables["leases"]["A"].active_run_id is None
    finally:
        await h.cleanup()

    # C17-09: unknown completed write followed by current denial cannot publish
    # a positive outcome from detached equality or release as confirmed success.
    h = Harness(modules)
    try:
        h.transactions.scripts["complete_prepared_chat_call"] = ["unknown_applied_deny_read"]
        run = await h.start()
        await h.turns()
        h.ai.calls[0].release()
        await h.drain()
        assert len(h.ai.calls) == 1 and len(h.transactions.prepared_attempts) == 1
        assert not _positions(h.store.events, "complete_prepared_chat_call", "return.closed")
        assert _positions(h.store.events, "get_chat_run", "begin")
        _expect_code("CURRENT_TEACHER_REQUIRED", lambda: h.execution.get_chat_run("A", run.task_id, run.run_id))
        for ordinal, owner in enumerate(("B", "C", "D"), 2):
            await h.start(owner, ordinal)
        await _expect_async_code("INSTANCE_BUSY", h.start("E", 5))
        # The database may have committed the real row; it must never be
        # fabricated as a rollback or treated as a currently authorized result.
        assert h.state(run).run.stage == "COMPLETE" and len(h.assistant_messages()) == 1
    finally:
        await h.cleanup()


    # C17-10..14: all five original token components are rechecked by the actual
    # prepared writer, after provider settlement but before content insertion.
    # Restore current authority only to run these exact non-dispatch writes.
    h = Harness(modules)
    try:
        run = await h.start()
        await h.turns()
        h.store.accounts["A"].role = "student"
        h.ai.calls[0].release()
        await h.drain()
        h.store.accounts["A"].role = "teacher"
        prepared = h.transactions.prepared_attempts[0]
        before = deepcopy(h.store.tables)
        for field, replacement in (("run_id", _uid(0x61, 999)), ("attempt", 2),
                                   ("call_no", 2), ("lease_revision", prepared.token.lease_revision + 1),
                                   ("process_instance", _uid(0x30, 2))):
            token = replace(prepared.token, **{field: replacement})
            changes = {"token": token}
            if field == "run_id":
                changes["message"] = prepared.message.model_copy(update={"run_id": replacement})
                changes["receipt"] = replace(prepared.receipt, run_id=replacement)
            forged = replace(prepared, **changes)
            _expect_code("NOT_FOUND" if field == "run_id" else "CALL_TOKEN_MISMATCH",
                lambda: h.transactions.complete_prepared_chat_call(forged))
            assert h.store.tables == before and h.assistant_messages() == () and len(h.ai.calls) == 1

        # C17-15..20: six exact active-lease fields independently block success.
        original_lease = h.store.tables["leases"]["A"]
        for field, replacement, code in (
            ("revision", original_lease.revision + 1, "CALL_TOKEN_MISMATCH"),
            ("active_run_id", _uid(0x61, 998), "OWNER_LEASE_LOST"),
            ("process_instance", _uid(0x30, 2), "OWNER_LEASE_LOST"),
            ("expires_at", NOW, "OWNER_LEASE_LOST"),
            ("owner_storage_id", _uid(0x10, 99), "OWNER_NAMESPACE_MISMATCH"),
            ("owner", "B", "OWNER_NAMESPACE_MISMATCH"),
        ):
            h.store.tables["leases"]["A"] = replace(original_lease, **{field: replacement})
            before = deepcopy(h.store.tables)
            _expect_code(code, lambda: h.transactions.complete_prepared_chat_call(prepared))
            assert h.store.tables == before and h.assistant_messages() == () and len(h.ai.calls) == 1
            h.store.tables["leases"]["A"] = original_lease
    finally:
        await h.cleanup()


    # C17-21: identical answer text cannot reconcile a different message UUID
    # as the original completion. Exact receipt/message identity is required.
    h = Harness(modules)
    try:
        run = await h.start()
        await h.turns()
        h.ai.calls[0].release()
        await h.drain()
        prepared = h.transactions.prepared_attempts[0]
        different_message = prepared.message.model_copy(update={"message_id": _uid(0x62, 999)})
        different_receipt = replace(prepared.receipt, message_id=different_message.message_id)
        forged = replace(prepared, message=different_message, receipt=different_receipt)
        before = deepcopy(h.store.tables)
        _expect_code("COMPLETION_CONFLICT", lambda: h.transactions.complete_prepared_chat_call(forged))
        assert h.store.tables == before and len(h.ai.calls) == 1 and len(h.assistant_messages()) == 1
    finally:
        await h.cleanup()


def test_chat_execution_waits_outside_transaction_after_durable_charge():
    modules = _load()
    modules.asyncio.run(_c14(modules))


def test_chat_execution_capacity_replay_and_schedule_failure():
    modules = _load()
    modules.asyncio.run(_c15(modules))


def test_chat_execution_cancel_deadline_and_late_result_hold_lease():
    modules = _load()
    modules.asyncio.run(_c16(modules))


def test_chat_execution_invalid_json_and_current_denial_never_succeed():
    modules = _load()
    modules.asyncio.run(_c17(modules))
