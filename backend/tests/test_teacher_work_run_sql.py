"""Task4b2A profile B: five actual SqlChatRows primitive cases, UNEXECUTED.

The Session-shaped port below records statements and returns a finite supplied
row/count response. It is not a SQLAlchemy Session/Connection/DBAPI or database;
it never evaluates SQL. MySQL compilation is only of production-emitted DML.
No example queries, SQLite, schema execution, owner workflow or provider exists.
"""
from __future__ import annotations

import ast
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import importlib
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest


BACKEND = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 5, tzinfo=timezone.utc)
NAIVE_NOW = NOW.replace(tzinfo=None)
TASK = UUID("20000000-0000-0000-0000-000000000001")
NS = UUID("10000000-0000-0000-0000-000000000001")
RUN = UUID("70000000-0000-0000-0000-000000000001")
PROCESS = UUID("30000000-0000-0000-0000-000000000001")
MESSAGE = UUID("80000000-0000-0000-0000-000000000001")
REF = UUID("40000000-0000-0000-0000-000000000001")


def _load():
    # Intended missing-operation assertion precedes every product/SQL import.
    source = (BACKEND / "app/repositories/teacher_work_sql.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
    assert {"SqlChatRows", "SqlRunModels"} <= names, "Task4b2A production ordinary-chat SQL primitives are missing"
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "SqlChatRows")
    methods = {node.name for node in cls.body if isinstance(node, ast.FunctionDef)}
    assert {"lease", "find_run_by_key", "lock_run", "find_user_message", "find_completion",
            "insert_run", "insert_user_message", "insert_completion", "cas_run", "cas_lease"} <= methods, "Task4b2A exact SQL row operations are missing"
    builder = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "build_sql_repository")
    assert "run_models" in {arg.arg for arg in builder.args.kwonlyargs}, "Task4b2A optional run-model binding is missing"
    return SimpleNamespace(
        adapter=importlib.import_module("app.repositories.teacher_work_sql"),
        repository=importlib.import_module("app.repositories.teacher_work"),
        persistence=importlib.import_module("app.services.teacher_work.run_persistence"),
        runs=importlib.import_module("app.services.teacher_work.runs"),
        schema=importlib.import_module("app.schemas.teacher_work"),
        types=importlib.import_module("app.services.teacher_work.types"),
        models=importlib.import_module("app.models.teacher_work"),
        sql=importlib.import_module("sqlalchemy"),
        orm=importlib.import_module("sqlalchemy.orm"),
        mysql=importlib.import_module("sqlalchemy.dialects.mysql"),
        exceptions=importlib.import_module("sqlalchemy.exc"),
        visitors=importlib.import_module("sqlalchemy.sql.visitors"))


class RecordedResult:
    def __init__(self, rows, rowcount):
        self.rows, self.rowcount = rows, rowcount

    def scalars(self):
        return self

    def all(self):
        return self.rows


class RecordedRoot:
    def __init__(self, origin):
        self.origin = origin
        self.is_active = True


class RecordingStatementPort:
    """No SQL evaluation; each operation consumes one explicitly queued reply."""
    def __init__(self, begin_origin):
        self.root = RecordedRoot(begin_origin)
        self.active = True
        self.nested = False
        self.is_active = True
        self.new, self.dirty, self.deleted = (), (), ()
        self.statements = []
        self.responses = []
        self.added = []
        self.events = []
        self.no_autoflush_depth = 0
        self.flush_error = None
        self.execute_error = None

    def get_transaction(self):
        return self.root

    def in_transaction(self):
        return self.active

    def in_nested_transaction(self):
        return self.nested

    @property
    @contextmanager
    def no_autoflush(self):
        self.no_autoflush_depth += 1
        try:
            yield
        finally:
            self.no_autoflush_depth -= 1

    def queue(self, *, rows=(), rowcount=1):
        self.responses.append(RecordedResult(list(rows), rowcount))

    def execute(self, statement):
        assert self.active and self.is_active and self.root.is_active
        if statement.is_select:
            assert self.no_autoflush_depth > 0
            assert statement.get_execution_options().get("populate_existing") is True
        self.statements.append(statement)
        self.events.append("select" if statement.is_select else "dml")
        if self.execute_error is not None:
            error, self.execute_error = self.execute_error, None
            self.is_active = self.root.is_active = False
            raise error
        assert self.responses, "each production SQL operation needs a finite recorded reply"
        return self.responses.pop(0)

    def add(self, row):
        assert self.active and self.is_active
        self.added.append(row)

    def flush(self):
        assert self.active and self.is_active
        self.events.append("flush")
        if self.flush_error is not None:
            error, self.flush_error = self.flush_error, None
            self.is_active = self.root.is_active = False
            raise error

    def begin(self):
        raise AssertionError("the adapter must never begin or replace a root")

    def begin_nested(self):
        raise AssertionError("the adapter must never start a savepoint")

    def commit(self):
        raise AssertionError("the adapter must never finalize its caller root")


def _domain_model(modules):
    # Isolated synthetic declaration for the existing task/draft binding only.
    # No engine/DDL, global core.database import or application DomainRecord.
    sql = modules.sql
    registry = modules.orm.registry()
    table = sql.Table("domain_records", registry.metadata,
        sql.Column("id", sql.Integer, primary_key=True),
        *(sql.Column(name, sql.String) for name in
          ("module", "record_type", "owner_id", "record_key", "role", "status", "payload")),
        sql.Column("created_at", sql.DateTime), sql.Column("updated_at", sql.DateTime))
    class SyntheticDomain:
        pass
    registry.map_imperatively(SyntheticDomain, table)
    return SyntheticDomain


def _task_row(modules):
    return modules.models.WorkTask(task_id=str(TASK), owner_subject="A", owner_storage_id=str(NS),
        institution_id=None, offering_id=None, title="合成任务", topic="合成主题", audience="合成对象",
        duration_minutes=45, target_slide_count=8, lesson_draft_id="draft-1", input_revision=1,
        working_revision=1, current_outline_id=None, latest_version_id=None, skill_refs=[],
        plugin_ids=[], reference_ids=[], created_at=NAIVE_NOW, updated_at=NAIVE_NOW,
        create_idempotency_key=None, create_request_digest=None)


def _run_row(modules, **changes):
    values = dict(run_id=str(RUN), owner="A", task_id=str(TASK), kind="chat", skill_ref=None,
        input_revision=1, outline_revision=None, idempotency_key="运行 Key ".encode("utf-8"),
        request_digest="a" * 64, stage="CHAT_RUNNING", attempt=2, provider_call_count=2,
        repair_count=1, active_call_no=2, active_call_attempt=2, active_call_lease_revision=4,
        active_call_process_instance=str(PROCESS), deadline=NAIVE_NOW + timedelta(seconds=270),
        cancelled_at=None, error_code=None, result_version_id=None)
    values.update(changes)
    return modules.models.WorkRun(**values)


def _message_row(modules, **changes):
    values = dict(message_id=str(MESSAGE), owner="A", task_id=str(TASK), role="assistant",
        client_message_key=None, run_id=str(RUN), completion_run_id=str(RUN),
        plain_text="实际候选\n保留 Unicode 与末尾空格 ", result_refs=[str(REF)],
        result_type="revision_proposal", omitted_context=True, created_at=NAIVE_NOW)
    values.update(changes)
    return modules.models.WorkMessage(**values)


def _setup(*, ready=True, mode="write"):
    m = _load()
    session = RecordingStatementPort(m.orm.SessionTransactionOrigin.BEGIN)
    domain = _domain_model(m)
    models = m.adapter.SqlWorkModels(m.models.WorkTask, m.models.OwnerRunLease,
                                    m.models.PackageVersion, domain)
    run_models = m.adapter.SqlRunModels(m.models.WorkRun, m.models.WorkMessage)
    uow, state = m.adapter.SqlWorkUnitOfWork(session), m.adapter._SqlState(session, mode)
    tasks = m.adapter.SqlTaskRows(session, models, uow, state)
    drafts = m.adapter.SqlOriginalDrafts(session, domain, state)
    chat = m.adapter.SqlChatRows(session, models, run_models, uow, state, tasks)
    fixture = SimpleNamespace(m=m, session=session, models=models, run_models=run_models,
                             uow=uow, state=state, tasks=tasks, drafts=drafts, chat=chat)
    if ready:
        _lock_task(fixture)
    return fixture


def _lock_task(fixture):
    m, session = fixture.m, fixture.session
    session.events.append("synthetic.current.footprint")
    fixture.state.actors["A"] = m.types.WorkActor("A", "teacher", NS)
    session.queue(rows=[m.models.OwnerRunLease(owner="A", owner_storage_id=str(NS),
        active_run_id=str(RUN), process_instance=str(PROCESS),
        expires_at=NAIVE_NOW + timedelta(seconds=270), revision=4)])
    fixture.tasks.lock_owner_lease("A")
    session.queue(rows=[fixture.models.domain_record(id=1, module="teacher_lesson_prep",
        record_type="draft", owner_id="A", record_key="draft-1", role="teacher", status="DRAFT",
        payload='{"draft_id":"draft-1","content":{"title":"原草稿"}}',
        created_at=NAIVE_NOW, updated_at=NAIVE_NOW)])
    fixture.drafts.lock_draft("A", "draft-1")
    session.queue(rows=[_task_row(m)])
    fixture.tasks.lock_task("A", TASK)


def _lock_run(fixture, **changes):
    fixture.session.queue(rows=[_run_row(fixture.m, **changes)])
    return fixture.chat.lock_run("A", TASK, RUN)


def _compile(fixture, statement):
    return statement.compile(dialect=fixture.m.mysql.dialect(paramstyle="named"))


def _where_values(fixture, statement):
    # Observe actual production predicates; never build a comparison statement.
    values = {}
    for node in fixture.m.visitors.iterate(statement.whereclause):
        if getattr(node, "__visit_name__", None) != "binary":
            continue
        column = getattr(node.left, "name", None)
        if column is not None:
            if getattr(node.right, "__visit_name__", None) == "null":
                value = None
            else:
                value = getattr(node.right, "value", None)
            values[column] = value
    return values


def _assigned_values(statement):
    return {getattr(column, "name", column): value.value
            for column, value in statement._values.items()}


def _controlled_error(action, *, code=None):
    with pytest.raises(Exception) as caught:
        action()
    assert getattr(caught.value, "status_code", None) in (404, 409, 503)
    if code is not None:
        assert caught.value.code == code
    return caught.value


def test_chat_sql_rows_require_ordered_same_caller_root():
    # Catches stale/adopted roots, collaborator mismatch and reads before ordered task locks.
    f = _setup(ready=False)
    _controlled_error(lambda: f.chat.lock_run("A", TASK, RUN), code="SQL_LOCK_REQUIRED")
    assert f.session.statements == []
    _lock_task(f)
    state = _lock_run(f)
    assert state.run.run_id == RUN
    tables = [statement.get_final_froms()[0].name for statement in f.session.statements]
    assert tables == ["teacher_work_owner_run_leases", "domain_records", "teacher_work_tasks", "teacher_work_runs"]
    assert f.session.events[0] == "synthetic.current.footprint"
    where = _where_values(f, f.session.statements[-1])
    assert {"owner": "A", "task_id": str(TASK), "run_id": str(RUN)}.items() <= where.items()
    assert f.session.statements[-1]._for_update_arg is not None
    for corruption in ("different_uow", "different_state", "different_tasks", "different_models"):
        f = _setup(ready=False)
        other = RecordingStatementPort(f.m.orm.SessionTransactionOrigin.BEGIN)
        uow = f.m.adapter.SqlWorkUnitOfWork(other) if corruption == "different_uow" else f.uow
        state = f.m.adapter._SqlState(other, "write") if corruption == "different_state" else f.state
        models = replace(f.models, task=f.m.models.WorkRun) if corruption == "different_models" else f.models
        tasks = f.m.adapter.SqlTaskRows(other, f.models, f.uow, f.state) if corruption == "different_tasks" else f.tasks
        with pytest.raises((ValueError, f.m.repository.WorkRepositoryError)):
            f.m.adapter.SqlChatRows(f.session, models, f.run_models, uow, state, tasks)
        assert f.session.statements == [] and other.statements == []
    for invalid in ("inactive", "nested", "autobegin", "failed", "restarted"):
        f = _setup()
        count = len(f.session.statements)
        if invalid == "inactive":
            f.session.active = False
        elif invalid == "nested":
            f.session.nested = True
        elif invalid == "autobegin":
            f.session.root.origin = f.m.orm.SessionTransactionOrigin.AUTOBEGIN
        elif invalid == "failed":
            f.session.is_active = f.session.root.is_active = False
        else:
            f.session.root = RecordedRoot(f.m.orm.SessionTransactionOrigin.BEGIN)
        with pytest.raises((ValueError, f.m.repository.WorkRepositoryError)):
            f.chat.lease("A")
        assert len(f.session.statements) == count
    # Actual factory binding, preserving callers that do not supply run models.
    for include_runs in (False, True):
        f = _setup(ready=False)
        store = SimpleNamespace(db=f.session, commit_policy="caller_owned", record_model=f.models.domain_record)
        def authorize(owner, offering_id, institution_id):
            return f.m.repository.AuthorizedWorkScope(f.m.types.WorkActor(owner, "teacher", NS), institution_id, offering_id)
        kwargs = dict(models=f.models, draft_store=store, authorize_locked=authorize,
                      clock=lambda: NOW, new_uuid=lambda: MESSAGE, mode="write")
        if include_runs:
            kwargs["run_models"] = f.run_models
        repository = f.m.adapter.build_sql_repository(f.session, **kwargs)
        assert isinstance(repository, f.m.repository.TeacherWorkRepository)
        assert (repository.run_rows is not None) is include_runs
        assert repository.uow.session is f.session and f.session.statements == []
    f = _setup(mode="read")
    state = _lock_run(f)
    count = len(f.session.statements)
    _controlled_error(lambda: f.chat.cas_run(state, replace(state, active_call=None)), code="READ_ONLY_REPOSITORY")
    assert len(f.session.statements) == count


def test_chat_sql_binary_receipts_and_strict_row_decode():
    # Catches collation/key coercion, partially populated tokens/results and loose row decoding.
    f = _setup()
    key = "运行 Key ".encode("utf-8")
    f.session.queue(rows=[_run_row(f.m)])
    state = f.chat.find_run_by_key("A", TASK, "chat", key)
    statement = f.session.statements[-1]
    compiled = _compile(f, statement)
    assert state.run.idempotency_key == "运行 Key "
    assert {"owner": "A", "task_id": str(TASK), "kind": "chat", "idempotency_key": key}.items() <= _where_values(f, statement).items()
    byte_binds = [bind for bind in compiled.binds.values() if type(bind.value) is bytes]
    assert byte_binds and all(bind.value == key and bind.type.compile(dialect=f.m.mysql.dialect()) == "VARBINARY(512)" for bind in byte_binds)
    assert not any(fragment in str(compiled).upper() for fragment in ("TRIM(", "LOWER(", "COLLATE", "CAST("))
    for invalid_key in ("运行 Key ", bytearray(key), b"\xff", b""):
        count = len(f.session.statements)
        _controlled_error(lambda: f.chat.find_run_by_key("A", TASK, "chat", invalid_key))
        assert len(f.session.statements) == count
    _lock_run(f)
    f.session.queue(rows=[_message_row(f.m, role="user", client_message_key=b"user Key ",
        completion_run_id=None, result_type=None, omitted_context=None, result_refs=[])])
    user = f.chat.find_user_message("A", TASK, b"user Key ")
    assert user.client_message_key == "user Key " and user.result_type is user.omitted_context is None
    assert {"owner": "A", "task_id": str(TASK), "role": "user", "client_message_key": b"user Key "}.items() <= _where_values(f, f.session.statements[-1]).items()
    for boolean, wanted in ((False, False), (True, True), (0, False), (1, True)):
        f.session.queue(rows=[_message_row(f.m, omitted_context=boolean)])
        receipt, message = f.chat.find_completion("A", TASK, RUN)
        assert receipt.run_id == RUN and receipt.message_id == MESSAGE
        assert message.omitted_context is wanted and message.result_refs == (REF,)
        predicate = _where_values(f, f.session.statements[-1])
        assert {"owner": "A", "task_id": str(TASK), "role": "assistant", "client_message_key": None, "completion_run_id": str(RUN)}.items() <= predicate.items()
    for changes in ({"repair_count": None}, {"repair_count": True}, {"repair_count": "1"},
        {"provider_call_count": True}, {"provider_call_count": "2"}, {"attempt": "2"},
        {"idempotency_key": "运行 Key "}, {"idempotency_key": b"\xff"}, {"run_id": RUN.hex},
        {"deadline": "2026-10-05"}, {"active_call_no": None}, {"active_call_process_instance": None},
        {"active_call_no": 1}, {"active_call_attempt": True}, {"active_call_lease_revision": 0},
        {"active_call_process_instance": PROCESS.hex}):
        f = _setup()
        f.session.queue(rows=[_run_row(f.m, **changes)])
        _controlled_error(lambda: f.chat.lock_run("A", TASK, RUN))
    for changes in ({"result_type": None}, {"omitted_context": None}, {"omitted_context": 2},
        {"omitted_context": "1"}, {"result_refs": str(REF)}, {"result_refs": [str(REF), str(REF)]},
        {"result_refs": [REF.hex]}, {"client_message_key": b"fabricated-assistant"},
        {"completion_run_id": None}, {"run_id": None}, {"message_id": MESSAGE.hex}):
        f = _setup()
        _lock_run(f)
        f.session.queue(rows=[_message_row(f.m, **changes)])
        _controlled_error(lambda: f.chat.find_completion("A", TASK, RUN))
    for lease_changes in ({"revision": True}, {"revision": "4"}, {"process_instance": None},
                          {"owner_storage_id": NS.hex}, {"expires_at": "not-datetime"}):
        f = _setup()
        held = f.state.leases["A"]
        for field, value in lease_changes.items():
            setattr(held, field, value)
        _controlled_error(lambda: f.chat.lease("A"))


def test_chat_sql_charge_and_settlement_predicates_are_exact():
    # Catches missing budget/token/stage/cancel predicates and false-positive rowcounts.
    f = _setup()
    before = _lock_run(f, stage="PENDING", attempt=1, provider_call_count=0, repair_count=0,
        active_call_no=None, active_call_attempt=None, active_call_lease_revision=None,
        active_call_process_instance=None)
    active = f.m.persistence.ProviderCallToken(RUN, 1, 1, 4, PROCESS)
    after = f.m.persistence.StoredRunState(before.run.model_copy(update={"stage": "CHAT_RUNNING", "provider_call_count": 1}), 0, active)
    f.session.queue(rowcount=1)
    assert f.chat.cas_run(before, after) is True
    statement = f.session.statements[-1]
    predicate = _where_values(f, statement)
    wanted = {"owner": "A", "task_id": str(TASK), "run_id": str(RUN), "stage": "PENDING",
        "cancelled_at": None, "attempt": 1, "provider_call_count": 0, "repair_count": 0,
        "active_call_no": None, "active_call_attempt": None, "active_call_lease_revision": None,
        "active_call_process_instance": None, "deadline": NAIVE_NOW + timedelta(seconds=270)}
    assert wanted.items() <= predicate.items()
    values = _assigned_values(statement)
    assert {"stage": "CHAT_RUNNING", "provider_call_count": 1, "repair_count": 0,
        "active_call_no": 1, "active_call_attempt": 1, "active_call_lease_revision": 4,
        "active_call_process_instance": str(PROCESS)}.items() <= values.items()
    assert " OR " not in str(_compile(f, statement)).upper()
    f = _setup()
    before = _lock_run(f, stage="CANCELLED", cancelled_at=NAIVE_NOW)
    after = replace(before, active_call=None)
    f.session.queue(rowcount=1)
    assert f.chat.cas_run(before, after) is True
    statement = f.session.statements[-1]
    wanted.update(stage="CANCELLED", cancelled_at=NAIVE_NOW, attempt=2, provider_call_count=2,
        repair_count=1, active_call_no=2, active_call_attempt=2,
        active_call_lease_revision=4, active_call_process_instance=str(PROCESS))
    assert wanted.items() <= _where_values(f, statement).items()
    assert {"active_call_no": None, "active_call_attempt": None, "active_call_lease_revision": None,
            "active_call_process_instance": None}.items() <= _assigned_values(statement).items()
    lease = f.chat.lease("A")
    released = replace(lease, active_run_id=None, process_instance=None, expires_at=None, revision=5)
    f.session.queue(rowcount=1)
    assert f.chat.cas_lease(lease, released) is True
    statement = f.session.statements[-1]
    assert {"owner": "A", "owner_storage_id": str(NS), "active_run_id": str(RUN),
        "process_instance": str(PROCESS), "expires_at": NAIVE_NOW + timedelta(seconds=270),
        "revision": 4}.items() <= _where_values(f, statement).items()
    assert _assigned_values(statement) == {"active_run_id": None, "process_instance": None, "expires_at": None, "revision": 5}
    for rowcount in (0, 2, -1, None, True, False, "1"):
        f = _setup()
        before = _lock_run(f)
        after = replace(before, active_call=None)
        f.session.queue(rowcount=rowcount)
        assert f.chat.cas_run(before, after) is False
        lease = f.chat.lease("A")
        f.session.queue(rowcount=rowcount)
        assert f.chat.cas_lease(lease, replace(lease, active_run_id=None, process_instance=None,
                                             expires_at=None, revision=5)) is False


def test_chat_sql_completion_is_append_only_and_cas_bound():
    # Catches upsert/fabricated assistant key, lost actual metadata and immutable run/namespace edits.
    f = _setup()
    state = _lock_run(f)
    message = f.m.schema.WorkMessageDTO(message_id=MESSAGE, owner="A", task_id=TASK,
        role="assistant", client_message_key=None, run_id=RUN,
        plain_text="实际候选\n保留 Unicode 与末尾空格 ", result_refs=(REF,),
        result_type="revision_proposal", omitted_context=True, created_at=NOW)
    receipt = f.m.persistence.ChatCompletionReceipt(RUN, MESSAGE)
    f.session.queue(rowcount=1)
    f.chat.insert_completion(message, receipt)
    statement = f.session.statements[-1]
    assert statement.is_insert and statement.table.name == "teacher_work_messages"
    values = _compile(f, statement).params
    assert {"message_id": str(MESSAGE), "owner": "A", "task_id": str(TASK), "role": "assistant",
        "client_message_key": None, "run_id": str(RUN), "completion_run_id": str(RUN),
        "plain_text": "实际候选\n保留 Unicode 与末尾空格 ", "result_refs": [str(REF)],
        "result_type": "revision_proposal", "omitted_context": True, "created_at": NAIVE_NOW}.items() <= values.items()
    assert not any(fragment in str(_compile(f, statement)).upper() for fragment in ("ON DUPLICATE KEY", "REPLACE", "IGNORE", "UPDATE"))
    assert "uq_tw_message_completion_run" in f.uow.reservation_constraints
    for changes in ({"idempotency_key": "other key"}, {"request_digest": "b" * 64},
                    {"input_revision": 2}, {"owner": "B"}, {"task_id": REF},
                    {"deadline": NOW + timedelta(seconds=271)}):
        f = _setup()
        state = _lock_run(f)
        wrong = replace(state, run=state.run.model_copy(update=changes))
        count = len(f.session.statements)
        _controlled_error(lambda: f.chat.cas_run(state, wrong))
        assert len(f.session.statements) == count
    f = _setup()
    lease = f.chat.lease("A")
    count = len(f.session.statements)
    _controlled_error(lambda: f.chat.cas_lease(lease, replace(lease, owner_storage_id=REF)))
    assert len(f.session.statements) == count
    # Admission INSERTs emitted by the actual primitive preserve both binary namespaces.
    f = _setup()
    pending = f.m.persistence.StoredRunState(f.m.schema.RunDTO(run_id=RUN, owner="A", task_id=TASK,
        kind="chat", skill_ref=None, input_revision=1, idempotency_key="运行 Key ",
        request_digest="a" * 64, stage="PENDING", attempt=1, provider_call_count=0,
        deadline=NOW + timedelta(seconds=270)), 0, None)
    user = f.m.schema.WorkMessageDTO(message_id=MESSAGE, owner="A", task_id=TASK, role="user",
        client_message_key="用户 Key ", run_id=RUN, plain_text="教师实际输入 ", created_at=NOW)
    for insert, value, table in ((f.chat.insert_run, pending, "teacher_work_runs"),
                                 (f.chat.insert_user_message, user, "teacher_work_messages")):
        f.session.queue(rowcount=1)
        insert(value)
        statement = f.session.statements[-1]
        assert statement.is_insert and statement.table.name == table
        values = _compile(f, statement).params
        if table == "teacher_work_runs":
            assert values["idempotency_key"] == "运行 Key ".encode("utf-8")
            assert (values["repair_count"], values["provider_call_count"], values["attempt"]) == (0, 0, 1)
        else:
            assert values["client_message_key"] == "用户 Key ".encode("utf-8")
            assert values.get("completion_run_id") is None and values.get("result_type") is None
    assert {"uq_tw_run_owner_task_kind_key", "uq_tw_message_task_client_key"} <= f.uow.reservation_constraints


class SyntheticDuplicate(Exception):
    """Only exception args used by MySQL duplicate-name decoding; no DBAPI."""


def _integrity(fixture, constraint):
    return fixture.m.exceptions.IntegrityError("SYNTHETIC INSERT", {},
        SyntheticDuplicate(1062, f"Duplicate entry 'synthetic' for key '{constraint}'"))


def test_chat_sql_integrity_conflict_requires_discard_and_fresh_read():
    # Catches same-failed-root reconciliation, unrecognized-error masking and auto-repeat writes.
    for constraint, operation in (("uq_tw_run_owner_task_kind_key", "run"),
                                  ("uq_tw_message_task_client_key", "user"),
                                  ("uq_tw_message_completion_run", "completion")):
        f = _setup()
        state = _lock_run(f)
        user = f.m.schema.WorkMessageDTO(message_id=MESSAGE, owner="A", task_id=TASK, role="user",
            client_message_key="用户 Key ", run_id=RUN, plain_text="合成输入", created_at=NOW)
        assistant = f.m.schema.WorkMessageDTO(message_id=MESSAGE, owner="A", task_id=TASK,
            role="assistant", client_message_key=None, run_id=RUN, plain_text="合成实际候选",
            result_type="answer", omitted_context=False, created_at=NOW)
        f.session.execute_error = _integrity(f, constraint)
        with pytest.raises(f.m.adapter.SqlReservationConflict) as caught:
            if operation == "run":
                f.chat.insert_run(state)
            elif operation == "user":
                f.chat.insert_user_message(user)
            else:
                f.chat.insert_completion(assistant, f.m.persistence.ChatCompletionReceipt(RUN, MESSAGE))
        assert caught.value.constraint == constraint and caught.value.requires_fresh_transaction is True
        count = len(f.session.statements)
        with pytest.raises((ValueError, f.m.repository.WorkRepositoryError)):
            f.chat.find_run_by_key("A", TASK, "chat", "运行 Key ".encode("utf-8"))
        assert len(f.session.statements) == count and f.session.responses == []
        fresh = _setup(mode="read")
        fresh.session.queue(rows=[_run_row(fresh.m)])
        observed = fresh.chat.find_run_by_key("A", TASK, "chat", "运行 Key ".encode("utf-8"))
        assert observed.run.run_id == RUN and fresh.session is not f.session
        assert all(statement.is_select for statement in fresh.session.statements) and fresh.session.added == []
    f = _setup()
    state = _lock_run(f)
    original = _integrity(f, "unrecognized_unique")
    f.session.execute_error = original
    with pytest.raises(f.m.exceptions.IntegrityError) as caught:
        f.chat.insert_run(state)
    assert caught.value is original
    # A late flush conflict is translated only for the registered exact unique.
    f = _setup()
    state = _lock_run(f)
    f.session.queue(rowcount=1)
    f.chat.insert_run(state)
    f.session.flush_error = _integrity(f, "uq_tw_run_owner_task_kind_key")
    with pytest.raises(f.m.adapter.SqlReservationConflict):
        f.uow.flush()
    assert f.session.is_active is False and f.session.root.is_active is False
