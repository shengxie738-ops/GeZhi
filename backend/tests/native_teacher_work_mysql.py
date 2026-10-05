"""Explicit-only MySQL acceptance: pytest must name this non-test_ file.

Owns a new network-disabled official container and disposable synthetic schemas.
Accepts no database URL, credentials, existing service or production bootstrap.
Normal pytest discovery neither imports this module nor connects to MySQL.
"""
from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path
import subprocess
import tempfile
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, insert, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.pool import NullPool
from sqlalchemy.sql.ddl import CreateTable

from app.models.teacher_work import WorkMessage, WorkRun, WorkTask
from app.services.teacher_work.schema import TEACHER_WORK_CONTRACT_HASH
from app.services.teacher_work.schema_mysql import (
    DatabaseIdentity, observe_teacher_work_mysql, teacher_work_mysql_tables,
)
from migrations.v20261005_teacher_work_mysql import (
    MysqlMigrationError, apply_teacher_work_mysql,
)

IMAGE = "mysql:8.4.10@sha256:8dbcf531a03aade657e181b9cf2f1d1803ce621a1d55610cb44cb531ab7d7db6"
NOW = datetime(2026, 10, 5, 12, 30, 45, 123456)


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True, stderr=subprocess.STDOUT).strip()


def identity(connection):
    return DatabaseIdentity(*connection.execute(text(
        "SELECT DATABASE(), @@server_uuid, @@datadir, @@socket")).one())


def cleanup_container(name, cid, root, baseline):
    """Always attempt exact owned-resource removal, even if evidence fails."""
    exists = None
    stopped, exit_code = None, None
    try:
        exists = docker("ps", "-a", "--filter", f"name=^/{name}$", "--format", "{{.ID}}")
        if exists:
            docker("stop", "--time", "30", name)
            state = json.loads(docker("inspect", name))[0]
            stopped, exit_code = state["State"]["Running"] is False, state["State"]["ExitCode"]
            (root / "mysql.log").write_text(docker("logs", name) + "\n")
    finally:
        # A failed stop/inspection/log write must still remove this test's own
        # container and anonymous data volume. No shared resource is selected.
        if exists != "":  # None is an unknown inventory: still try removal.
            docker("rm", "-f", "-v", name)
        remaining = set(docker("ps", "-q").splitlines())
        (root / "cleanup.json").write_text(json.dumps({"container": name,
            "container_id": cid, "stopped": stopped, "exit_code": exit_code,
            "creation_not_observed": exists == "",
            "removed_with_volumes": True, "baseline_preserved": baseline <= remaining}, indent=2) + "\n")
    if exists:
        assert stopped and exit_code == 0, "MySQL did not stop cleanly"
    assert baseline <= remaining, "a pre-existing container stopped during this run"


@pytest.mark.parametrize("fault", ["log", "inventory"])
def test_owned_container_removed_when_evidence_write_fails(tmp_path, monkeypatch, fault):
    # Created but never started: this tests cleanup without another DB service.
    name = "gezhi-tw-cleanup-" + uuid4().hex
    cid = docker("create", "--name", name, "--network", "none", IMAGE)
    original = Path.write_text
    def fail_log(path, *args, **kwargs):
        if fault == "log" and path.name == "mysql.log":
            raise OSError("synthetic evidence write failure")
        return original(path, *args, **kwargs)
    original_docker = docker
    def fail_inventory(*args):
        if fault == "inventory" and args[:3] == ("ps", "-a", "--filter"):
            raise OSError("synthetic evidence write failure")
        return original_docker(*args)
    monkeypatch.setattr(Path, "write_text", fail_log)
    monkeypatch.setitem(globals(), "docker", fail_inventory)
    try:
        assert "cleanup_container" in globals(), "failure-safe native cleanup helper required"
        with pytest.raises(OSError, match="synthetic evidence write failure"):
            cleanup_container(name, cid, tmp_path, set(docker("ps", "-q").splitlines()))
        assert name not in docker("ps", "-a", "--format", "{{.Names}}").splitlines()
        assert json.loads((tmp_path / "cleanup.json").read_text())["removed_with_volumes"] is True
    finally:
        if name in docker("ps", "-a", "--format", "{{.Names}}").splitlines():
            docker("rm", "-f", "-v", name)


@pytest.fixture(scope="session")
def native_server():
    root = Path(tempfile.mkdtemp(prefix="gezhi-tw-native-"))
    socket_dir = root / "socket"
    socket_dir.mkdir(mode=0o777)
    socket_dir.chmod(0o777)
    name = "gezhi-tw-native-" + uuid4().hex
    baseline = set(docker("ps", "-q").splitlines())
    creation_attempted = False
    cid = None
    admin = None
    print("Native evidence:", root)
    try:
        creation_attempted = True
        cid = docker("run", "-d", "--name", name, "--network", "none",
            "--mount", f"type=bind,src={socket_dir},dst=/run/gezhi-native",
            "-e", "MYSQL_ALLOW_EMPTY_PASSWORD=yes", IMAGE,
            "--skip-networking", "--mysqlx=0", "--socket=/run/gezhi-native/mysql.sock",
            "--character-set-server=utf8mb4", "--collation-server=utf8mb4_bin")
        admin = create_engine("mysql+pymysql://root@localhost",
            connect_args={"unix_socket": str(socket_dir / "mysql.sock"), "connect_timeout": 2},
            poolclass=NullPool)
        deadline = time.monotonic() + 45
        while True:
            try:
                # The entrypoint's bootstrap server also accepts SQL. Wait for
                # its shutdown before testing the final mysqld instance.
                if "MySQL init process done. Ready for start up." not in docker("logs", name):
                    raise RuntimeError("official initialization still running")
                with admin.connect() as c:
                    first = dict(c.execute(text("SELECT 1 AS first_sql, VERSION() AS version, "
                        "CONNECTION_ID() AS connection_id, @@server_uuid AS server_uuid, "
                        "@@datadir AS datadir, @@socket AS socket, @@skip_networking AS skip_networking, "
                        "@@session.sql_mode AS sql_mode, @@session.transaction_isolation AS isolation, "
                        "@@session.foreign_key_checks AS foreign_key_checks, "
                        "@@session.unique_checks AS unique_checks")).mappings().one())
                break
            except Exception:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.25)
        assert first["first_sql"] == first["skip_networking"] == 1
        assert first["version"] == "8.4.10"
        assert first["foreign_key_checks"] == first["unique_checks"] == 1
        assert "STRICT_TRANS_TABLES" in first["sql_mode"]
        state = json.loads(docker("inspect", name))[0]
        assert state["HostConfig"]["NetworkMode"] == "none"
        assert not state["HostConfig"]["PortBindings"]
        (root / "first-sql.json").write_text(json.dumps(first, indent=2) + "\n")
        yield SimpleNamespace(admin=admin, socket=str(socket_dir / "mysql.sock"),
            facts=first, evidence=root)
    finally:
        try:
            if admin is not None:
                admin.dispose()
        finally:
            if creation_attempted:
                cleanup_container(name, cid, root, baseline)


@pytest.fixture
def native_db(native_server):
    name = "tw_native_" + uuid4().hex
    with native_server.admin.connect() as c:
        c.execute(text(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin"))
    engine = create_engine(f"mysql+pymysql://root@localhost/{name}",
        connect_args={"unix_socket": native_server.socket}, poolclass=NullPool)
    try:
        with engine.connect() as c:
            expected = identity(c)
            assert expected.server_uuid == native_server.facts["server_uuid"]
        yield SimpleNamespace(engine=engine, identity=expected, evidence=native_server.evidence)
    finally:
        engine.dispose()
        with native_server.admin.connect() as c:
            assert c.execute(text("SELECT @@server_uuid")).scalar_one() == native_server.facts["server_uuid"]
            c.execute(text(f"DROP DATABASE `{name}`"))


def prepare(db):
    with db.engine.connect() as c:
        return apply_teacher_work_mysql(c, db.identity, contract_hash=TEACHER_WORK_CONTRACT_HASH)


def task_values(**changes):
    values = dict(task_id=str(uuid4()), owner_subject="synthetic-owner", owner_storage_id=str(uuid4()),
        title="合成任务", topic="合成主题", audience="合成对象", duration_minutes=45,
        target_slide_count=8, lesson_draft_id=str(uuid4()), create_idempotency_key=None,
        create_request_digest=None, input_revision=1, working_revision=1,
        skill_refs=["lesson_outline@1"], plugin_ids=[], reference_ids=[], created_at=NOW, updated_at=NOW)
    values.update(changes)
    return values


def test_fresh_v2_persists_receipt_on_independent_connection(native_db):
    db = native_db
    report = prepare(db)
    names = tuple(t.name for t in teacher_work_mysql_tables())
    assert report.completed and report.ledger_written is True
    assert report.ledger_commit_state == "ACKNOWLEDGED"
    assert report.attempted_tables == report.confirmed_tables == names
    with db.engine.connect() as c:
        result = observe_teacher_work_mysql(c)
        assert result.ready, result.issues
        assert len(result.observation["tables"]) == 13
        receipt = dict(c.execute(text("SELECT * FROM teacher_work_schema_versions")).mappings().one())
        assert receipt["version"] == 2 and receipt["contract_hash"] == TEACHER_WORK_CONTRACT_HASH
        assert type(receipt["completed_at"]) is datetime
        checks = [dict(r) for r in c.execute(text("SELECT CONSTRAINT_NAME, CHECK_CLAUSE FROM "
            "information_schema.check_constraints WHERE CONSTRAINT_SCHEMA=DATABASE()")).mappings()]
        indexes = [dict(r) for r in c.execute(text("SELECT TABLE_NAME, INDEX_NAME, NON_UNIQUE, "
            "SEQ_IN_INDEX, COLUMN_NAME, SUB_PART, INDEX_TYPE, IS_VISIBLE FROM "
            "information_schema.statistics WHERE TABLE_SCHEMA=DATABASE()")).mappings()]
        (db.evidence / "checks.json").write_text(json.dumps(checks, indent=2) + "\n")
        (db.evidence / "indexes.json").write_text(json.dumps(indexes, indent=2) + "\n")
        (db.evidence / "receipt.json").write_text(json.dumps(receipt, indent=2, default=str) + "\n")
        columns = [dict(r) for r in c.execute(text("SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, "
            "COLUMN_DEFAULT, DATETIME_PRECISION, CHARACTER_OCTET_LENGTH, CHARACTER_SET_NAME, "
            "COLLATION_NAME FROM information_schema.columns WHERE TABLE_SCHEMA=DATABASE() "
            "AND (DATA_TYPE IN ('json','datetime','varbinary') OR COLUMN_NAME='repair_count')")).mappings()]
        assert sum(r["COLUMN_TYPE"] == "varbinary(512)" and r["CHARACTER_OCTET_LENGTH"] == 512 for r in columns) == 3
        assert all(r["DATETIME_PRECISION"] == 6 for r in columns if r["COLUMN_TYPE"] == "datetime(6)")
        assert next(r for r in columns if r["COLUMN_NAME"] == "repair_count")["COLUMN_DEFAULT"] == "0"
        assert all(r["COLUMN_DEFAULT"] is None for r in columns if r["COLUMN_NAME"] != "repair_count")
        (db.evidence / "physical-columns.json").write_text(json.dumps(columns, indent=2, default=str) + "\n")


def test_exact_v2_replay_has_no_mutating_sql(native_db):
    prepare(native_db)
    statements = []
    def record(c, cursor, statement, parameters, context, many):
        statements.append(statement)
    event.listen(native_db.engine, "before_cursor_execute", record)
    try:
        report = prepare(native_db)
    finally:
        event.remove(native_db.engine, "before_cursor_execute", record)
    assert report.completed and report.ledger_written is False
    assert report.attempted_tables == report.confirmed_tables == ()
    assert statements and all(s.lstrip().upper().startswith(("SELECT", "SHOW")) for s in statements)


@pytest.mark.parametrize("field", ["schema_name", "server_uuid", "datadir", "socket"])
def test_wrong_identity_refuses_before_ddl(native_db, field):
    wrong = replace(native_db.identity, **{field: getattr(native_db.identity, field) + "-wrong"})
    with native_db.engine.connect() as c:
        with pytest.raises(MysqlMigrationError) as error:
            apply_teacher_work_mysql(c, wrong, contract_hash=TEACHER_WORK_CONTRACT_HASH)
        assert error.value.code == "teacher_work_identity_mismatch"
        assert error.value.attempted_tables == ()
        assert c.execute(text("SELECT COUNT(*) FROM information_schema.tables WHERE TABLE_SCHEMA=DATABASE()")).scalar_one() == 0


def test_active_caller_transaction_is_preserved(native_db):
    with native_db.engine.connect() as c:
        root = c.begin()
        c.execute(text("SELECT 1"))
        with pytest.raises(MysqlMigrationError) as error:
            apply_teacher_work_mysql(c, native_db.identity, contract_hash=TEACHER_WORK_CONTRACT_HASH)
        assert error.value.code == "teacher_work_fresh_connection_required"
        assert error.value.attempted_tables == () and c.get_transaction() is root and root.is_active


def test_partial_structure_is_not_resumed(native_db):
    with native_db.engine.connect() as c:
        c.execute(CreateTable(WorkTask.__table__))
    with native_db.engine.connect() as c:
        with pytest.raises(MysqlMigrationError) as error:
            apply_teacher_work_mysql(c, native_db.identity, contract_hash=TEACHER_WORK_CONTRACT_HASH)
        assert error.value.code == "teacher_work_schema_incompatible"
        assert error.value.attempted_tables == ()
        assert c.execute(text("SELECT COUNT(*) FROM information_schema.tables WHERE TABLE_SCHEMA=DATABASE()")).scalar_one() == 1


@pytest.mark.parametrize("setting", ["foreign_key_checks", "unique_checks"])
def test_session_checks_disabled_are_refused(native_db, setting):
    with native_db.engine.connect() as c:
        c.execute(text(f"SET SESSION {setting}=0"))
        c.commit()
        with pytest.raises(MysqlMigrationError) as error:
            apply_teacher_work_mysql(c, native_db.identity, contract_hash=TEACHER_WORK_CONTRACT_HASH)
        assert error.value.attempted_tables == ()
        assert error.value.code == "teacher_work_schema_incompatible"
        assert c.execute(text(f"SELECT @@session.{setting}")).scalar_one() == 0


@pytest.mark.parametrize("persistent", [False, True])
def test_temporary_table_resolution_is_refused(native_db, persistent):
    if persistent:
        prepare(native_db)
    with native_db.engine.connect() as c:
        c.execute(text("CREATE TEMPORARY TABLE teacher_work_tasks (shadow INT)"))
        c.commit()
        report = observe_teacher_work_mysql(c)
        assert not report.ready and any(i.kind == "resolved_table" for i in report.issues)
        c.rollback()
        with pytest.raises(MysqlMigrationError) as error:
            apply_teacher_work_mysql(c, native_db.identity, contract_hash=TEACHER_WORK_CONTRACT_HASH)
        assert error.value.code == "teacher_work_schema_incompatible" and error.value.attempted_tables == ()


def test_independent_commit_rollback_json_datetime_binary(native_db):
    prepare(native_db)
    a = task_values(create_idempotency_key="合成 Key ".encode(), create_request_digest="a" * 64)
    b = task_values(create_idempotency_key="合成 Key".encode(), create_request_digest="a" * 64)
    with native_db.engine.connect() as writer, native_db.engine.connect() as observer:
        assert writer.execute(text("SELECT CONNECTION_ID()")).scalar_one() != observer.execute(text("SELECT CONNECTION_ID()")).scalar_one()
        writer.execute(insert(WorkTask).values(**a))
        assert observer.execute(select(WorkTask.task_id)).all() == []
        observer.rollback()
        writer.commit()
        row = observer.execute(select(WorkTask.__table__)).mappings().one()
        assert row["create_idempotency_key"] == a["create_idempotency_key"]
        assert row["skill_refs"] == ["lesson_outline@1"] and row["created_at"] == NOW
        assert row["created_at"].tzinfo is None and row["created_at"].microsecond == 123456
        observer.rollback()
        writer.execute(insert(WorkTask).values(**b))
        writer.rollback()
        assert observer.execute(select(WorkTask.task_id)).all() == [(a["task_id"],)]
        observer.rollback()
        writer.execute(insert(WorkTask).values(**b))
        writer.commit()
        assert len(observer.execute(select(WorkTask.task_id)).all()) == 2


@pytest.mark.parametrize("constraint,errno,error_type", [
    ("unique", 1062, IntegrityError), ("check", 3819, OperationalError), ("fk", 1452, IntegrityError)])
def test_native_constraints_reject_invalid_writes(native_db, constraint, errno, error_type):
    prepare(native_db)
    a = task_values(create_idempotency_key=b"same", create_request_digest="a" * 64)
    with native_db.engine.begin() as c:
        c.execute(insert(WorkTask).values(**a))
    with native_db.engine.connect() as c:
        with pytest.raises(error_type) as error:
            if constraint == "unique":
                c.execute(insert(WorkTask).values(**task_values(create_idempotency_key=b"same", create_request_digest="a" * 64)))
            elif constraint == "check":
                c.execute(insert(WorkTask).values(**task_values(duration_minutes=0)))
            else:
                c.execute(insert(WorkMessage).values(message_id=str(uuid4()), task_id=str(uuid4()),
                    owner="synthetic-owner", role="user", plain_text="合成消息", result_refs=[], created_at=NOW))
        assert error.value.orig.args[0] == errno
        c.rollback()
    with native_db.engine.connect() as c:
        assert c.execute(select(WorkTask.task_id)).all() == [(a["task_id"],)]
        assert c.execute(select(WorkMessage.message_id)).all() == []


def test_runtime_server_default_and_full_binary_key(native_db):
    prepare(native_db)
    task = task_values(skill_refs=["合成 Unicode", "末尾空格 "], reference_ids=[])
    key = ("😀" * 128).encode("utf-8")
    assert len(key) == 512
    with native_db.engine.begin() as c:
        c.execute(insert(WorkTask).values(**task))
        c.execute(insert(WorkRun).values(run_id=str(uuid4()), owner=task["owner_subject"],
            task_id=task["task_id"], kind="chat", input_revision=1, idempotency_key=key,
            request_digest="a" * 64, stage="PENDING", attempt=1, provider_call_count=0, deadline=NOW))
    with native_db.engine.connect() as c:
        run = c.execute(select(WorkRun.__table__)).mappings().one()
        assert run["repair_count"] == 0 and run["idempotency_key"] == key
        assert c.execute(select(WorkTask.skill_refs)).scalar_one() == task["skill_refs"]
        indexes = list(c.execute(text("SELECT INDEX_NAME, COLUMN_NAME, SEQ_IN_INDEX, SUB_PART "
            "FROM information_schema.statistics WHERE TABLE_SCHEMA=DATABASE() "
            "AND TABLE_NAME='teacher_work_runs' AND INDEX_NAME='uq_tw_run_owner_task_kind_key' "
            "ORDER BY SEQ_IN_INDEX")))
        assert [(r.COLUMN_NAME, r.SUB_PART) for r in indexes] == [(n, None) for n in ("owner", "task_id", "kind", "idempotency_key")]


@pytest.mark.parametrize("defect", ["missing_receipt", "unenforced_check", "changed_literal"])
def test_existing_v2_defects_are_refused(native_db, defect):
    prepare(native_db)
    with native_db.engine.begin() as c:
        if defect == "missing_receipt":
            c.execute(text("DELETE FROM teacher_work_schema_versions"))
        elif defect == "unenforced_check":
            c.execute(text("ALTER TABLE teacher_work_runs ALTER CHECK ck_tw_run_kind NOT ENFORCED"))
        else:
            c.execute(text("ALTER TABLE teacher_work_runs DROP CHECK ck_tw_run_kind, "
                "ADD CONSTRAINT ck_tw_run_kind CHECK (kind IN ('CHAT','outline','package','revise','reference_search'))"))
    with native_db.engine.connect() as c:
        report = observe_teacher_work_mysql(c)
        assert not report.ready
        if defect == "missing_receipt":
            assert report.physical_valid and not report.ledger_valid
        else:
            assert any(i.table == "teacher_work_runs" and i.kind in ("checks", "keys") for i in report.issues)
        c.rollback()
        with pytest.raises(MysqlMigrationError) as error:
            apply_teacher_work_mysql(c, native_db.identity, contract_hash=TEACHER_WORK_CONTRACT_HASH)
        assert error.value.code == "teacher_work_schema_incompatible" and error.value.attempted_tables == ()
