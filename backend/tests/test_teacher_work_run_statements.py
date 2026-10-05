"""Task4b1 four isolated metadata/MySQL-compilation cases, UNEXECUTED.

These statement shapes are examples over the dedicated model declarations, not
tests of an implemented CAS writer. This separately reviewed profile may import
SQLAlchemy and isolated Teacher Work metadata only. No engine, Session, DBAPI,
recording transport, statement execution, DDL or physical observations exist here.
"""
from __future__ import annotations

import importlib
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID


BACKEND = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 5, tzinfo=timezone.utc)
TASK = UUID("60000000-0000-0000-0000-000000000001")
RUN = UUID("70000000-0000-0000-0000-000000000001")
PROCESS = UUID("80000000-0000-0000-0000-000000000001")
MESSAGE = UUID("90000000-0000-0000-0000-000000000001")
REFERENCE = UUID("90000000-0000-0000-0000-000000000002")


def _metadata():
    path = BACKEND / "app/models/teacher_work.py"
    assert path.is_file(), "Task4b1 isolated metadata is missing"
    sql = importlib.import_module("sqlalchemy")
    mysql = importlib.import_module("sqlalchemy.dialects.mysql")
    work = importlib.import_module("app.models.teacher_work")
    return sql, mysql.dialect(paramstyle="named"), work


def _codec():
    assert (BACKEND / "app/services/teacher_work/run_persistence.py").is_file(), "Task4b1 exact-key codec is missing"
    return importlib.import_module("app.services.teacher_work.run_persistence")


def _binary(column, dialect):
    assert column.type.compile(dialect=dialect) == "VARBINARY(512)", "Task4b1 exact binary key declaration is missing"


def _uniques(table, sql):
    return {constraint.name: tuple(column.name for column in constraint.columns)
            for constraint in table.constraints if isinstance(constraint, sql.UniqueConstraint)}


def test_mysql_run_key_bind_is_exact_binary():
    sql, dialect, work = _metadata()
    table = work.WorkRun.__table__
    _binary(table.c.idempotency_key, dialect)
    codec = _codec()
    key = codec.encode_work_key("课题 Key ")
    statement = sql.select(table.c.run_id).where(
        table.c.owner == sql.bindparam("run_owner", "A"),
        table.c.task_id == sql.bindparam("run_task", str(TASK)),
        table.c.kind == sql.bindparam("run_kind", "chat"),
        table.c.idempotency_key == sql.bindparam("run_key", key, type_=table.c.idempotency_key.type),
    )
    compiled = statement.compile(dialect=dialect)
    assert compiled.params == {"run_owner": "A", "run_task": str(TASK), "run_kind": "chat", "run_key": "课题 Key ".encode("utf-8")}
    assert type(compiled.params["run_key"]) is bytes
    assert compiled.binds["run_key"].type.compile(dialect=dialect) == "VARBINARY(512)"
    query = str(compiled)
    for column, binding in (("owner", "run_owner"), ("task_id", "run_task"), ("kind", "run_kind"), ("idempotency_key", "run_key")):
        assert f"teacher_work_runs.{column} = :{binding}" in query
    assert not any(fragment in query.upper() for fragment in ("TRIM(", "LOWER(", "COLLATE", "CAST("))
    assert _uniques(table, sql)["uq_tw_run_owner_task_kind_key"] == ("owner", "task_id", "kind", "idempotency_key")


def test_mysql_message_key_bind_and_completion_namespace():
    sql, dialect, work = _metadata()
    table = work.WorkMessage.__table__
    _binary(table.c.client_message_key, dialect)
    assert {"completion_run_id", "result_type", "omitted_context"} <= set(table.c.keys()), "Task4b1 completion namespace is missing"
    key = _codec().encode_work_key("中文键 ")
    statement = sql.select(table.c.message_id).where(
        table.c.owner == sql.bindparam("message_owner", "A"),
        table.c.task_id == sql.bindparam("message_task", str(TASK)),
        table.c.role == sql.bindparam("message_role", "user"),
        table.c.client_message_key == sql.bindparam("message_key", key, type_=table.c.client_message_key.type),
    )
    compiled = statement.compile(dialect=dialect)
    assert compiled.params == {"message_owner": "A", "message_task": str(TASK), "message_role": "user", "message_key": "中文键 ".encode("utf-8")}
    assert compiled.binds["message_key"].type.compile(dialect=dialect) == "VARBINARY(512)"
    query = str(compiled)
    for column, binding in (("owner", "message_owner"), ("task_id", "message_task"), ("role", "message_role"), ("client_message_key", "message_key")):
        # MySQL reserves ROLE; the pinned dialect correctly quotes it.
        expected_column = "`role`" if column == "role" else column
        assert f"teacher_work_messages.{expected_column} = :{binding}" in query
    assert not any(fragment in query.upper() for fragment in ("TRIM(", "LOWER(", "COLLATE", "CAST("))
    uniques = _uniques(table, sql)
    assert uniques["uq_tw_message_task_client_key"] == ("task_id", "client_message_key")
    assert uniques["uq_tw_message_completion_run"] == ("completion_run_id",)
    assert table.c.client_message_key.nullable is True and table.c.completion_run_id.nullable is True
    assert {foreign.target_fullname for foreign in table.c.completion_run_id.foreign_keys} == {"teacher_work_runs.run_id"}
    receipt = sql.select(table.c.message_id).where(
        table.c.owner == sql.bindparam("receipt_owner", "A"),
        table.c.task_id == sql.bindparam("receipt_task", str(TASK)),
        table.c.role == sql.bindparam("receipt_role", "assistant"),
        table.c.client_message_key.is_(None),
        table.c.completion_run_id == sql.bindparam("completion_run", str(RUN)),
    ).compile(dialect=dialect)
    assert receipt.params == {"receipt_owner": "A", "receipt_task": str(TASK), "receipt_role": "assistant", "completion_run": str(RUN)}
    assert "teacher_work_messages.client_message_key IS NULL" in str(receipt)
    assert "teacher_work_messages.completion_run_id = :completion_run" in str(receipt)


def test_mysql_call_token_predicate_contains_every_component():
    sql, dialect, work = _metadata()
    table = work.WorkRun.__table__
    active = ("active_call_no", "active_call_attempt", "active_call_lease_revision", "active_call_process_instance")
    assert set(active) <= set(table.c.keys()), "Task4b1 composite active-call metadata is missing"
    observed = {"owner": "A", "task_id": str(TASK), "run_id": str(RUN), "attempt": 2,
                "provider_call_count": 3, "active_call_no": 3, "active_call_attempt": 2,
                "active_call_lease_revision": 4, "active_call_process_instance": str(PROCESS)}
    statement = sql.update(table).where(*(
        table.c[column] == sql.bindparam(f"observed_{column}", value)
        for column, value in observed.items()
    )).values(**{column: None for column in active})
    compiled = statement.compile(dialect=dialect)
    assert compiled.params == {**{f"observed_{column}": value for column, value in observed.items()}, **{column: None for column in active}}
    update_clause, predicates = str(compiled).split(" WHERE ", 1)
    assignments = update_clause.split(" SET ", 1)[1].split(", ")
    assert {assignment.split("=", 1)[0] for assignment in assignments} == set(active)
    for column in active:
        assert f"{column}=:{column}" in update_clause
    for column in observed:
        assert f"teacher_work_runs.{column} = :observed_{column}" in predicates
    assert "teacher_work_owner_run_leases" not in str(compiled)


def test_mysql_completion_insert_preserves_metadata():
    sql, dialect, work = _metadata()
    table = work.WorkMessage.__table__
    required = {"completion_run_id", "result_type", "omitted_context"}
    assert required <= set(table.c.keys()), "Task4b1 actual-result metadata is missing"
    values = {"message_id": str(MESSAGE), "owner": "A", "task_id": str(TASK), "role": "assistant",
              "client_message_key": None, "run_id": str(RUN), "completion_run_id": str(RUN),
              "plain_text": "实际候选\n保留 Unicode 与末尾空格 ", "result_refs": [str(REFERENCE)],
              "result_type": "revision_proposal", "omitted_context": True, "created_at": NOW}
    compiled = sql.insert(table).values(**values).compile(dialect=dialect)
    assert compiled.params == values
    assert compiled.params["client_message_key"] is None and type(compiled.params["omitted_context"]) is bool
    assert table.c.omitted_context.type.compile(dialect=dialect) == "BOOL"
    insert = str(compiled)
    assert insert.startswith("INSERT INTO teacher_work_messages (")
    assert not any(fragment in insert.upper() for fragment in ("ON DUPLICATE KEY", "UPDATE", "REPLACE", "IGNORE"))
    assert required <= set(compiled.params)
    assert not {"repair_count", "active_call_no", "active_call_attempt", "active_call_lease_revision",
                "active_call_process_instance", "process_instance", "lease_revision", "request_digest",
                "idempotency_key", "input_revision"} & set(compiled.params)
    for column in required:
        assert table.c[column].nullable is True and table.c[column].default is None and table.c[column].server_default is None
