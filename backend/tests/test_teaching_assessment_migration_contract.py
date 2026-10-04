"""Exact fake-identity/DDL migration logic and synthetic SQLite inspection."""
import copy
import importlib
import importlib.util
from datetime import datetime
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects import mysql

BACKEND = Path(__file__).resolve().parents[1]


def feature(name):
    try: return importlib.import_module(name)
    except ModuleNotFoundError as exc: assert False, f"Required B2 feature is missing: {name}: {exc}"


def modules():
    b1 = feature("app.services.teaching.schema")
    b2 = feature("app.services.teaching.assessment_schema")
    path = BACKEND / "migrations/v20261003_teaching_assessment.py"
    assert path.is_file(), "Required B2 migration module is missing"
    name = "migrations.v20261003_teaching_assessment"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return b1, b2, sys.modules[name]


class Rows:
    def __init__(self, row): self.row = row
    def mappings(self): return self
    def first(self): return self.row


class FakeInspector:
    def __init__(self, tables):
        self.shapes = {}
        for table in tables:
            self.shapes[table.name] = {
                "columns": [{"name": c.name, "type": c.type.dialect_impl(mysql.dialect()), "nullable": c.nullable} for c in table.columns],
                "pk": {"name": table.primary_key.name, "constrained_columns": list(table.primary_key.columns.keys())},
                "foreign_keys": [{"name": c.name, "constrained_columns": list(c.columns.keys()), "referred_table": c.referred_table.name, "referred_columns": [e.column.name for e in c.elements], "options": {}} for c in table.foreign_key_constraints],
                "uniques": [{"name": c.name, "column_names": list(c.columns.keys())} for c in table.constraints if c.__class__.__name__ == "UniqueConstraint"],
                "indexes": [{"name": i.name, "column_names": list(i.columns.keys()), "unique": i.unique} for i in table.indexes],
                "checks": [{"name": c.name, "sqltext": str(c.sqltext)} for c in table.constraints if c.__class__.__name__ == "CheckConstraint"],
                "options": {"mysql_engine": "InnoDB", "mysql_default charset": "utf8mb4", "mysql_collate": "utf8mb4_bin"},
            }
    def get_table_names(self): return list(self.shapes)
    def get_columns(self, name): return copy.deepcopy(self.shapes[name]["columns"])
    def get_pk_constraint(self, name): return copy.deepcopy(self.shapes[name]["pk"])
    def get_foreign_keys(self, name): return copy.deepcopy(self.shapes[name]["foreign_keys"])
    def get_unique_constraints(self, name): return copy.deepcopy(self.shapes[name]["uniques"])
    def get_indexes(self, name): return copy.deepcopy(self.shapes[name]["indexes"])
    def get_check_constraints(self, name): return copy.deepcopy(self.shapes[name]["checks"])
    def get_table_options(self, name): return copy.deepcopy(self.shapes[name]["options"])


class FakeConnection:
    dialect = mysql.dialect()
    def __init__(self, inspector, b1):
        self.inspector = inspector
        self.identity = {"schema_name": "b2_synthetic", "server_uuid": "synthetic-server", "datadir": "/synthetic/data/", "socket": "/synthetic/mysql.sock", "skip_networking": 1}
        self.ledgers = {"b1": {"component": "b1", "version": 1, "contract_hash": b1.B1_CONTRACT_HASH, "completed_at": datetime(2026, 10, 3)}}
        self.operations = []
    def execute(self, statement, parameters=None):
        sql = str(statement)
        if "@@server_uuid" in sql: return Rows(dict(self.identity))
        if sql.lstrip().upper().startswith("SELECT") and "teaching_schema_versions" in sql:
            return Rows(copy.deepcopy(self.ledgers.get(parameters["component"])))
        if sql.lstrip().upper().startswith("INSERT") and "teaching_schema_versions" in sql:
            assert parameters["component"] == "b2", "B2 may never write B1 ledger"
            self.operations.append(("ledger", dict(parameters))); self.ledgers["b2"] = dict(parameters); return Rows(None)
        raise AssertionError(f"Unexpected statement: {sql}")
    def commit(self): self.operations.append(("commit", None))
    def __enter__(self): return self
    def __exit__(self, *_): return False


class FakeEngine:
    dialect = mysql.dialect()
    def __init__(self, connection): self.connection = connection
    def connect(self): return self.connection


def _mock_mysql(monkeypatch):
    b1, b2, migration = modules()
    inspector = FakeInspector((*b1.b1_tables(), *b2.b2_tables()))
    connection = FakeConnection(inspector, b1)
    monkeypatch.setattr(b1, "inspect", lambda conn: conn.inspector)
    monkeypatch.setattr(b2, "inspect", lambda conn: conn.inspector)
    full = copy.deepcopy(inspector.shapes)
    def create_table(conn, table):
        assert table in b2.b2_tables(), "B2 DDL must be limited to its ten tables"
        conn.operations.append(("create", table.name)); conn.inspector.shapes[table.name] = copy.deepcopy(full[table.name])
    monkeypatch.setattr(migration, "_create_table", create_table)
    expected = b1.DatabaseIdentity("b2_synthetic", "synthetic-server", "/synthetic/data/", "/synthetic/mysql.sock")
    return b1, b2, migration, inspector, connection, FakeEngine(connection), expected


@pytest.fixture
def mock_mysql(monkeypatch):
    # Delay imports until each test body, so feature absence is assertion RED.
    return lambda: _mock_mysql(monkeypatch)


@pytest.mark.parametrize("failure", ["missing_table", "missing_ledger", "wrong_hash", "wrong_shape"])
def test_b2_requires_compatible_b1(mock_mysql, failure):
    b1, b2, migration, inspector, connection, engine, expected = mock_mysql()
    if failure == "missing_table": del inspector.shapes["teaching_courses"]
    elif failure == "missing_ledger": connection.ledgers.clear()
    elif failure == "wrong_hash": connection.ledgers["b1"]["contract_hash"] = "0" * 64
    else: inspector.shapes["teaching_courses"]["columns"][0]["type"] = mysql.CHAR(36)
    report = b2.inspect_assessment_schema(connection)
    assert not report.ready and not report.b1_ready
    for operation in (lambda: migration.plan_b2_schema(engine, expected), lambda: migration.apply_b2_schema(engine, expected, contract_hash=b2.B2_CONTRACT_HASH)):
        with pytest.raises(b1.TeachingSchemaError): operation()
    assert not connection.operations


@pytest.mark.parametrize("field,value", [("schema_name", "other"), ("server_uuid", "other"), ("datadir", "/other/"), ("socket", "/other.sock"), ("skip_networking", 0)])
def test_identity_mismatch_has_no_ddl(mock_mysql, field, value):
    b1, b2, migration, _, connection, engine, expected = mock_mysql()
    connection.identity[field] = value
    for operation in (lambda: migration.plan_b2_schema(engine, expected), lambda: migration.apply_b2_schema(engine, expected, contract_hash=b2.B2_CONTRACT_HASH)):
        with pytest.raises(b1.TeachingSchemaError) as exc: operation()
        assert exc.value.code == "teaching_identity_mismatch"
    assert not connection.operations


def test_b2_partial_compatible_plan_reenters(mock_mysql):
    _, b2, migration, inspector, connection, engine, expected = mock_mysql()
    missing = tuple(table.name for table in b2.b2_tables()[4:])
    for name in missing: del inspector.shapes[name]
    first = migration.plan_b2_schema(engine, expected)
    assert first.missing_tables == missing and first.completion_required
    assert not connection.operations
    result = migration.apply_b2_schema(engine, expected, contract_hash=b2.B2_CONTRACT_HASH)
    assert result.created_tables == missing and result.completed
    assert b2.inspect_assessment_schema(connection).ready
    count = len(connection.operations)
    second = migration.plan_b2_schema(engine, expected)
    assert not second.missing_tables and not second.completion_required
    assert migration.apply_b2_schema(engine, expected, contract_hash=b2.B2_CONTRACT_HASH).created_tables == ()
    assert len(connection.operations) == count


@pytest.mark.parametrize("change", ["type", "fk_scope", "fk_schema", "unique", "index_prefix", "check_literal", "collation", "ledger"])
def test_incompatible_b2_stops_before_ddl(mock_mysql, change):
    b1, b2, migration, inspector, connection, engine, expected = mock_mysql()
    shape = inspector.shapes["teaching_assignment_versions"]
    if change == "type": shape["columns"][0]["type"] = mysql.CHAR(36)
    elif change == "fk_scope": shape["foreign_keys"][0]["constrained_columns"] = ["assignment_id"]
    elif change == "fk_schema": shape["foreign_keys"][0]["referred_schema"] = "foreign_database"
    elif change == "unique": shape["uniques"].pop()
    elif change == "index_prefix": shape["indexes"][0]["dialect_options"] = {"mysql_length": {"assignment_id": 8}}
    elif change == "check_literal": inspector.shapes["teaching_releases"]["checks"][0]["sqltext"] = "late_policy = 'REJECT'"
    elif change == "collation": shape["options"]["mysql_collate"] = "utf8mb4_general_ci"
    else: connection.ledgers["b2"] = {"component": "b2", "version": 1, "contract_hash": "0" * 64, "completed_at": datetime(2026, 10, 3)}
    del inspector.shapes["teaching_submissions"]
    for operation in (lambda: migration.plan_b2_schema(engine, expected), lambda: migration.apply_b2_schema(engine, expected, contract_hash=b2.B2_CONTRACT_HASH)):
        with pytest.raises(b1.TeachingSchemaError): operation()
    assert not connection.operations


def test_b2_ledger_is_last_and_b1_untouched(mock_mysql):
    b1, b2, migration, inspector, connection, engine, expected = mock_mysql()
    # Raw TypeEngine instances use object identity after deepcopy. Compare the
    # entire exact physical contract, not those incidental Python identities.
    before = {table.name: b1._existing_contract(inspector, table, "mysql") for table in b1.b1_tables()}
    ledger = copy.deepcopy(connection.ledgers["b1"])
    for table in b2.b2_tables(): del inspector.shapes[table.name]
    with pytest.raises(b1.TeachingSchemaError): migration.apply_b2_schema(engine, expected, contract_hash="0" * 64)
    assert not connection.operations
    result = migration.apply_b2_schema(engine, expected, contract_hash=b2.B2_CONTRACT_HASH)
    assert result.created_tables == tuple(table.name for table in b2.b2_tables())
    assert connection.operations[:-2] == [("create", name) for name in result.created_tables]
    assert connection.operations[-2][0] == "ledger" and connection.operations[-1][0] == "commit"
    assert {table.name: b1._existing_contract(inspector, table, "mysql") for table in b1.b1_tables()} == before
    assert connection.ledgers["b1"] == ledger
    report = b2.inspect_assessment_schema(connection)
    assert report.shape_valid and report.b1_ready and report.ready
    # Same declarations/ledgers on SQLite remain vendor-unverified; no readiness shortcut.
    engine_sqlite = create_engine("sqlite:///:memory:")
    try:
        for table in (*b1.b1_tables(), *b2.b2_tables()): table.create(engine_sqlite)
        with engine_sqlite.begin() as conn:
            for value in connection.ledgers.values(): conn.execute(b1.TeachingSchemaVersion.__table__.insert(), value)
        # Remove fake reflection interception only for the independent SQLite read.
        from sqlalchemy import inspect as real_inspect
        old_b1, old_b2 = b1.inspect, b2.inspect
        b1.inspect = b2.inspect = real_inspect
        try:
            with engine_sqlite.connect() as conn:
                report = b2.inspect_assessment_schema(conn)
                assert report.shape_valid and report.ledger_present and not report.mysql_verified and not report.b1_ready and not report.ready
                with pytest.raises(b1.TeachingSchemaError): b2.require_assessment_schema(SimpleNamespace(connection=lambda: conn))
        finally: b1.inspect, b2.inspect = old_b1, old_b2
    finally: engine_sqlite.dispose()
