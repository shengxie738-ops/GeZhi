"""Mocked MySQL inspection/DDL planning plus synthetic SQLite shape only."""
import copy
import importlib
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.dialects import mysql


def feature(name):
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        assert False, f"B1 feature module is missing: {name}: {exc}"


def modules():
    schema = feature("app.services.teaching.schema")
    migration = feature("migrations.v20261003_teaching")
    return schema, migration


class Rows:
    def __init__(self, row): self.row = row
    def mappings(self): return self
    def first(self): return self.row


class FakeInspector:
    def __init__(self, schema):
        self.shapes = {}
        for table in schema.b1_tables():
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
    def __init__(self, inspector, contract_hash):
        self.inspector = inspector
        self.identity = {"schema_name": "b1_synthetic", "server_uuid": "synthetic-server", "datadir": "/synthetic/data/", "socket": "/synthetic/mysql.sock", "skip_networking": 1}
        self.ledger = {"component": "b1", "version": 1, "contract_hash": contract_hash, "completed_at": datetime(2026, 10, 3)}
        self.writes = []
    def execute(self, statement, parameters=None):
        sql = str(statement)
        if "@@server_uuid" in sql: return Rows(dict(self.identity))
        if sql.lstrip().upper().startswith("SELECT") and "teaching_schema_versions" in sql: return Rows(copy.deepcopy(self.ledger))
        if sql.lstrip().upper().startswith("INSERT") and "teaching_schema_versions" in sql:
            self.writes.append((sql, parameters)); self.ledger = dict(parameters); return Rows(None)
        raise AssertionError(f"Unexpected statement: {sql}")
    def commit(self): pass
    def __enter__(self): return self
    def __exit__(self, *_): return False


class FakeEngine:
    dialect = mysql.dialect()
    def __init__(self, connection): self.connection = connection
    def connect(self): return self.connection


@pytest.fixture
def mock_mysql(monkeypatch):
    schema, migration = modules()
    inspector = FakeInspector(schema)
    connection = FakeConnection(inspector, schema.B1_CONTRACT_HASH)
    monkeypatch.setattr(schema, "inspect", lambda conn: conn.inspector)
    created = []
    full = copy.deepcopy(inspector.shapes)
    def create_table(conn, table):
        created.append(table.name)
        conn.inspector.shapes[table.name] = copy.deepcopy(full[table.name])
    monkeypatch.setattr(migration, "_create_table", create_table)
    expected = schema.DatabaseIdentity(schema_name="b1_synthetic", server_uuid="synthetic-server", datadir="/synthetic/data/", socket="/synthetic/mysql.sock")
    return schema, migration, inspector, connection, FakeEngine(connection), expected, created


def test_schema_inspection_and_requirement_are_read_only(mock_mysql):
    schema, _, _, connection, _, _, created = mock_mysql
    report = schema.inspect_teaching_schema(connection)
    assert report.ready and report.mysql_verified and report.version == 1
    session = SimpleNamespace(connection=lambda: connection)
    assert schema.require_teaching_schema(session) is None
    assert not created and not connection.writes


def test_correct_full_shape_is_noop(mock_mysql, capsys):
    schema, migration, _, connection, engine, expected, created = mock_mysql
    with capsys.disabled():
        print("B1_CONTRACT_HASH=" + schema.B1_CONTRACT_HASH)
    plan = migration.plan_b1_schema(engine, expected)
    assert plan.missing_tables == () and plan.contract_hash == schema.B1_CONTRACT_HASH
    report = migration.apply_b1_schema(engine, expected, contract_hash=schema.B1_CONTRACT_HASH)
    assert report.completed and report.created_tables == () and not created and not connection.writes


def test_missing_additive_tables_and_correct_partial_schema_resume(mock_mysql):
    schema, migration, inspector, connection, engine, expected, created = mock_mysql
    del inspector.shapes["teaching_roles"]
    del inspector.shapes["teaching_access_events"]
    connection.ledger = None
    plan = migration.plan_b1_schema(engine, expected)
    assert set(plan.missing_tables) == {"teaching_roles", "teaching_access_events"}
    assert not created and not connection.writes
    report = migration.apply_b1_schema(engine, expected, contract_hash=schema.B1_CONTRACT_HASH)
    assert report.completed and set(created) == set(plan.missing_tables)
    assert len(connection.writes) == 1 and connection.ledger["component"] == "b1"
    assert all("ALTER" not in sql.upper() and "DROP" not in sql.upper() for sql, _ in connection.writes)
    second = migration.apply_b1_schema(engine, expected, contract_hash=schema.B1_CONTRACT_HASH)
    assert second.created_tables == () and len(connection.writes) == 1


@pytest.mark.parametrize("defect", ["pk", "index", "fk", "nullable", "type", "check", "engine", "collation", "column", "unique", "ledger_hash", "ledger_version"])
def test_incompatible_existing_shape_stops_before_ddl(mock_mysql, defect):
    schema, migration, inspector, connection, engine, expected, created = mock_mysql
    course = inspector.shapes["teaching_courses"]
    if defect == "pk": course["pk"]["constrained_columns"] = ["institution_id"]
    elif defect == "index": course["indexes"] = []
    elif defect == "fk": inspector.shapes["teaching_offerings"]["foreign_keys"] = []
    elif defect == "nullable": next(c for c in course["columns"] if c["name"] == "title")["nullable"] = True
    elif defect == "type": next(c for c in course["columns"] if c["name"] == "id")["type"] = mysql.VARCHAR(255)
    elif defect == "check": course["checks"] = []
    elif defect == "engine": course["options"]["mysql_engine"] = "MyISAM"
    elif defect == "collation": course["options"]["mysql_collate"] = "utf8mb4_general_ci"
    elif defect == "column": course["columns"] = course["columns"][:-1]
    elif defect == "unique": course["uniques"] = []
    elif defect == "ledger_hash": connection.ledger["contract_hash"] = "0" * 64
    else: connection.ledger["version"] = 2
    del inspector.shapes["teaching_roles"]  # incompatibility must win before additive DDL
    with pytest.raises(schema.TeachingSchemaError) as exc:
        migration.apply_b1_schema(engine, expected, contract_hash=schema.B1_CONTRACT_HASH)
    assert exc.value.issues and not created and not connection.writes


@pytest.mark.parametrize("field", ["schema_name", "server_uuid", "datadir", "socket", "skip_networking"])
def test_wrong_live_identity_stops_before_plan_or_ddl(mock_mysql, field):
    schema, migration, _, connection, engine, expected, created = mock_mysql
    connection.identity[field] = 0 if field == "skip_networking" else "wrong"
    for operation in [lambda: migration.plan_b1_schema(engine, expected), lambda: migration.apply_b1_schema(engine, expected, contract_hash=schema.B1_CONTRACT_HASH)]:
        with pytest.raises(schema.TeachingSchemaError) as exc: operation()
        assert "identity" in str(exc.value).lower()
    assert not created and not connection.writes


def test_exact_contract_hash_required_and_sqlite_not_mysql_readiness(mock_mysql):
    schema, migration, _, connection, engine, expected, created = mock_mysql
    with pytest.raises(schema.TeachingSchemaError):
        migration.apply_b1_schema(engine, expected, contract_hash="0" * 64)
    assert not created and not connection.writes
    # Actual synthetic SQLite shape is useful, never vendor-readiness proof.
    sqlite = create_engine("sqlite:///:memory:")
    try:
        with sqlite.begin() as conn:
            for table in schema.b1_tables(): table.create(conn)
            conn.execute(schema.b1_tables()[-1].insert(), {"component": "b1", "version": 1, "contract_hash": schema.B1_CONTRACT_HASH, "completed_at": datetime(2026, 10, 3)})
            # Temporarily bypass the mock inspector for the real synthetic connection.
            original = schema.inspect
            schema.inspect = inspect
            try:
                report = schema.inspect_teaching_schema(conn)
                assert report.shape_valid and not report.mysql_verified and not report.ready
                with pytest.raises(schema.TeachingSchemaError): schema.require_teaching_schema(SimpleNamespace(connection=lambda: conn))
            finally: schema.inspect = original
    finally: sqlite.dispose()


def test_missing_schema_typed_error_without_ddl(mock_mysql):
    schema, _, inspector, connection, _, _, created = mock_mysql
    inspector.shapes.clear(); connection.ledger = None
    report = schema.inspect_teaching_schema(connection)
    assert not report.ready and len(report.missing_tables) == 8
    with pytest.raises(schema.TeachingSchemaError) as exc:
        schema.require_teaching_schema(SimpleNamespace(connection=lambda: connection))
    assert exc.value.code == "teaching_schema_missing" and not created and not connection.writes


def test_cli_requires_explicit_target_identity_and_defaults_plan_only():
    _, migration = modules()
    parser = migration.build_argument_parser()
    with pytest.raises(SystemExit): parser.parse_args([])
    args = parser.parse_args(["--url", "mysql+pymysql://synthetic@localhost/b1_synthetic", "--schema-name", "b1_synthetic", "--server-uuid", "synthetic-server", "--datadir", "/synthetic/data/", "--socket", "/synthetic/mysql.sock"])
    assert args.apply is False
    source = Path(migration.__file__).read_text()
    assert "app.core.config" not in source and "DATABASE_URL" not in source

# Expectations describe the required contract;
# failures establish defects on frozen candidate 49401750, not production outcomes.
def test_review_mysql_reflected_primary_key_name(mock_mysql):
    schema, _, inspector, connection, _, _, _ = mock_mysql
    # Official SQLAlchemy MySQL get_pk_constraint returns name=None.
    for shape in inspector.shapes.values():
        shape["pk"]["name"] = None
    report = schema.inspect_teaching_schema(connection)
    assert report.ready, report.issues


def test_review_mysql_reflected_unique_indexes(mock_mysql):
    schema, _, inspector, connection, _, _, _ = mock_mysql
    # Official SQLAlchemy MySQL reflects UNIQUE in both interfaces, with the
    # duplicate marker on the unique constraint rather than the index.
    for shape in inspector.shapes.values():
        for unique in shape["uniques"]:
            unique["duplicates_index"] = unique["name"]
            shape["indexes"].append({"name": unique["name"], "column_names": unique["column_names"], "unique": True})
    report = schema.inspect_teaching_schema(connection)
    assert report.ready, report.issues


def test_review_foreign_schema_fk_rejected_before_ddl(mock_mysql):
    schema, migration, inspector, connection, engine, expected, created = mock_mysql
    inspector.shapes["teaching_offerings"]["foreign_keys"][0]["referred_schema"] = "other_institution_database"
    del inspector.shapes["teaching_roles"]
    with pytest.raises(schema.TeachingSchemaError):
        migration.apply_b1_schema(engine, expected, contract_hash=schema.B1_CONTRACT_HASH)
    assert not created and not connection.writes


def test_review_case_sensitive_enum_check_rejected_before_ddl(mock_mysql):
    schema, migration, inspector, connection, engine, expected, created = mock_mysql
    check = next(c for c in inspector.shapes["teaching_offerings"]["checks"] if "state IN" in c["sqltext"])
    check["sqltext"] = check["sqltext"].replace("'draft'", "'DRAFT'").replace("'active'", "'ACTIVE'").replace("'archived'", "'ARCHIVED'")
    del inspector.shapes["teaching_roles"]
    with pytest.raises(schema.TeachingSchemaError):
        migration.apply_b1_schema(engine, expected, contract_hash=schema.B1_CONTRACT_HASH)
    assert not created and not connection.writes


@pytest.mark.parametrize("table_name,column_name,replacement", [
    ("teaching_courses", "id", mysql.CHAR(36)),
    ("teaching_courses", "created_at", mysql.TIMESTAMP(fsp=6)),
    ("teaching_write_receipts", "http_status", mysql.SMALLINT()),
])
def test_review_distinct_mysql_type_rejected_before_ddl(mock_mysql, table_name, column_name, replacement):
    schema, migration, inspector, connection, engine, expected, created = mock_mysql
    next(c for c in inspector.shapes[table_name]["columns"] if c["name"] == column_name)["type"] = replacement
    del inspector.shapes["teaching_roles"]
    with pytest.raises(schema.TeachingSchemaError):
        migration.apply_b1_schema(engine, expected, contract_hash=schema.B1_CONTRACT_HASH)
    assert not created and not connection.writes


def test_review_prefix_index_rejected_before_ddl(mock_mysql):
    schema, migration, inspector, connection, engine, expected, created = mock_mysql
    index = inspector.shapes["teaching_courses"]["indexes"][0]
    index["dialect_options"] = {"mysql_length": {"source_teacher_id": 10}}
    del inspector.shapes["teaching_roles"]
    with pytest.raises(schema.TeachingSchemaError):
        migration.apply_b1_schema(engine, expected, contract_hash=schema.B1_CONTRACT_HASH)
    assert not created and not connection.writes


def test_mysql_pk_normalization_does_not_hide_wrong_name_or_columns(mock_mysql):
    schema, _, inspector, connection, _, _, _ = mock_mysql
    shape = inspector.shapes["teaching_courses"]
    shape["pk"]["name"] = "wrong_primary_name"
    assert not schema.inspect_teaching_schema(connection).shape_valid
    shape["pk"]["name"] = None
    shape["pk"]["constrained_columns"] = ["institution_id"]
    assert not schema.inspect_teaching_schema(connection).shape_valid


def test_local_explicit_fk_schema_and_reflection_check_wrappers_accepted(mock_mysql):
    schema, _, inspector, connection, _, _, _ = mock_mysql
    inspector.default_schema_name = "b1_synthetic"
    inspector.shapes["teaching_offerings"]["foreign_keys"][0]["referred_schema"] = "b1_synthetic"
    check = next(c for c in inspector.shapes["teaching_offerings"]["checks"] if "state IN" in c["sqltext"])
    check["sqltext"] = "((`state` IN (_utf8mb4'draft', _utf8mb4'active', _utf8mb4'archived')))"
    assert schema.inspect_teaching_schema(connection).ready


def test_reflected_duplicate_unique_prefix_or_columns_never_suppressed(mock_mysql):
    schema, migration, inspector, connection, engine, expected, created = mock_mysql
    shape = inspector.shapes["teaching_courses"]
    unique = shape["uniques"][0]
    unique["duplicates_index"] = unique["name"]
    index = {"name": unique["name"], "column_names": list(unique["column_names"]), "unique": True, "dialect_options": {"mysql_length": {"institution_id": 8}}}
    shape["indexes"].append(index)
    del inspector.shapes["teaching_roles"]
    with pytest.raises(schema.TeachingSchemaError): migration.apply_b1_schema(engine, expected, contract_hash=schema.B1_CONTRACT_HASH)
    assert not created and not connection.writes
    index["dialect_options"] = {}
    index["column_names"] = ["institution_id"]
    with pytest.raises(schema.TeachingSchemaError): migration.apply_b1_schema(engine, expected, contract_hash=schema.B1_CONTRACT_HASH)
    assert not created and not connection.writes


def test_quoted_charset_introducer_text_is_not_discarded_before_ddl(mock_mysql):
    schema, migration, inspector, connection, engine, expected, created = mock_mysql
    check = next(c for c in inspector.shapes["teaching_courses"]["checks"] if "title <> ''" in c["sqltext"])
    check["sqltext"] = "title <> '_utf8mb4'"
    del inspector.shapes["teaching_roles"]
    with pytest.raises(schema.TeachingSchemaError):
        migration.apply_b1_schema(engine, expected, contract_hash=schema.B1_CONTRACT_HASH)
    assert not created and not connection.writes
