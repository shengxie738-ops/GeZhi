"""Sixteen finite fresh-v2 compiler/catalog-port cases, initially UNEXECUTED.

These call the production observer and migration against explicitly supplied
catalog rows and record emitted statements. The port never evaluates SQL,
creates a database, or updates the catalog in response to DDL. This is control
flow/compilation evidence only, never physical MySQL or transaction evidence.
No Engine, Session, Inspector, DBAPI, socket, service, provider or browser exists.
"""
from __future__ import annotations

import ast
import copy
from datetime import datetime
import importlib
import re
from pathlib import Path
from types import SimpleNamespace


BACKEND = Path(__file__).resolve().parents[1]
SCHEMA_MEMBER = "app/services/teacher_work/schema_mysql.py"
MIGRATION_MEMBER = "migrations/v20261005_teacher_work_mysql.py"
NOW = datetime(2026, 10, 5, 20, 0, 0)
IDENTITY = {"schema_name": "teacher_work_synthetic", "server_uuid": "11111111-2222-3333-4444-555555555555",
            "datadir": "/synthetic/mysql/data/", "socket": "/synthetic/mysql/mysql.sock", "skip_networking": 1}
UNIQUE_NAMES = {
    "teacher_work_tasks": {"uq_tw_task_owner_draft": ("owner_subject", "lesson_draft_id"),
                           "uq_tw_task_owner_create_key": ("owner_subject", "create_idempotency_key")},
    "teacher_work_runs": {"uq_tw_run_owner_task_kind_key": ("owner", "task_id", "kind", "idempotency_key")},
    "teacher_work_messages": {"uq_tw_message_task_client_key": ("task_id", "client_message_key"),
                              "uq_tw_message_completion_run": ("completion_run_id",)},
    "teacher_work_outline_snapshots": {"uq_tw_outline_task_revision": ("task_id", "outline_revision")},
    "teacher_work_package_versions": {"uq_tw_version_task_number": ("task_id", "version_no"), "uq_tw_version_run": ("run_id",)},
    "teacher_work_artifacts": {"uq_tw_artifact_version_kind": ("version_id", "kind")},
    "teacher_work_preview_states": {"uq_tw_preview_version_format_kind": ("version_id", "artifact_kind", "kind")},
    "teacher_work_owner_run_leases": {"uq_tw_lease_storage_namespace": ("owner_storage_id",)},
}


def _load():
    # The frozen RED run must fail for the missing production slice before any
    # SQLAlchemy/product import, rather than treating a loader denial as RED.
    assert (BACKEND / SCHEMA_MEMBER).is_file(), "Teacher Work physical MySQL observer is missing"
    assert (BACKEND / MIGRATION_MEMBER).is_file(), "Teacher Work fresh-v2 MySQL migration is missing"
    return SimpleNamespace(
        schema=importlib.import_module("app.services.teacher_work.schema_mysql"),
        migration=importlib.import_module("migrations.v20261005_teacher_work_mysql"),
        contract=importlib.import_module("app.services.teacher_work.schema"),
        models=importlib.import_module("app.models.teacher_work"),
        mysql=importlib.import_module("sqlalchemy.dialects.mysql"),
        sql=importlib.import_module("sqlalchemy"),
        ddl=importlib.import_module("sqlalchemy.sql.ddl"),
        exceptions=importlib.import_module("sqlalchemy.exc"),
    )


def _identity(modules):
    return modules.schema.DatabaseIdentity(**{k: IDENTITY[k] for k in ("schema_name", "server_uuid", "datadir", "socket")})


def test_mysql_check_serializer_between_parentheses():
    schema = _load().schema
    assert schema._check("(`active_call_no` between 1 and 3) AND enabled = 1") == schema._check("active_call_no BETWEEN 1 AND 3 AND enabled = 1")
    assert schema._check("(a = 1 OR b = 2) AND c = 3") != schema._check("a = 1 OR (b = 2 AND c = 3)")
    assert schema._check("(n between 1 and 3) AND enabled = 1") != schema._check("(n between 1 and 4) AND enabled = 1")


def test_mysql_catalog_escaped_literal_serializer():
    m = _load()
    catalog = _catalog(m)
    for row in catalog["checks"]:
        row["check_clause"] = row["check_clause"].replace("'", "\\'")
        # The server prints an introducer before each opening delimiter.
        row["check_clause"] = re.sub(r"\\'([^'\\]*)\\'", r"_utf8mb4\\'\1\\'", row["check_clause"])
    port = RecordingCatalogPort([(catalog, _ledger(m))], exceptions=m.exceptions)
    assert m.schema.observe_teacher_work_mysql(port).ready
    changed = copy.deepcopy(catalog)
    next(r for r in changed["checks"] if r["constraint_name"] == "ck_tw_run_kind")["check_clause"] = r"kind IN (_utf8mb4\'CHAT\',_utf8mb4\'outline\',_utf8mb4\'package\',_utf8mb4\'revise\',_utf8mb4\'reference_search\')"
    assert not m.schema.observe_teacher_work_mysql(RecordingCatalogPort([(changed, _ledger(m))], exceptions=m.exceptions)).ready


def _ledger(modules):
    return {"component": "teacher_work", "version": 2,
            "contract_hash": modules.contract.TEACHER_WORK_CONTRACT_HASH, "completed_at": NOW}


def _catalog(modules, names=None):
    """Translate the unchanged v2 contract into raw supplied catalog rows.

    Unique names, physical defaults, key lengths, enforcement and storage facts
    are pinned independently here. No production observer helper is used.
    """
    contracts = modules.contract.TEACHER_WORK_SCHEMA_CONTRACT["tables"]
    names = tuple(contracts) if names is None else tuple(names)
    result = {k: [] for k in ("tables", "columns", "constraints", "keys", "references", "checks", "indexes")}
    result["resolved"] = {name: {"Table": name, "Create Table": "CREATE TABLE `" + name + "` (`synthetic_only` int)"} for name in names}
    for table_name in names:
        shape = contracts[table_name]
        result["tables"].append({"table_name": table_name, "table_type": "BASE TABLE", "engine": "InnoDB",
                                 "table_collation": "utf8mb4_bin", "character_set_name": "utf8mb4"})
        for ordinal, (column_name, column) in enumerate(shape["columns"].items(), 1):
            kind = column["type"]
            family = kind.split("(", 1)[0]
            length = int(kind.split("(", 1)[1].rstrip(")")) if "(" in kind else None
            character = family in {"varchar", "text", "mediumtext"}
            result["columns"].append({
                "table_name": table_name, "column_name": column_name, "ordinal_position": ordinal,
                "data_type": "int" if family == "integer" else family,
                "column_type": "int" if family == "integer" else kind,
                "is_nullable": "YES" if column["nullable"] else "NO",
                "column_default": "0" if (table_name, column_name) == ("teacher_work_runs", "repair_count") else None,
                "character_maximum_length": length if family in {"varchar", "varbinary"} else None,
                "character_octet_length": length * 4 if family == "varchar" else length if family == "varbinary" else None,
                "datetime_precision": 6 if family == "datetime" else None,
                "character_set_name": "utf8mb4" if character else None,
                "collation_name": "utf8mb4_bin" if character else None,
                "extra": "", "generation_expression": "",
            })
        def key(name, columns, unique):
            result["constraints"].append({"table_name": table_name, "constraint_name": name,
                                           "constraint_type": "PRIMARY KEY" if name == "PRIMARY" else "UNIQUE", "enforced": "YES"})
            for position, column_name in enumerate(columns, 1):
                result["keys"].append({"table_name": table_name, "constraint_name": name, "column_name": column_name,
                                      "ordinal_position": position, "referenced_table_schema": None,
                                      "referenced_table_name": None, "referenced_column_name": None})
                result["indexes"].append({"table_name": table_name, "index_name": name, "non_unique": 0,
                                         "seq_in_index": position, "column_name": column_name, "sub_part": None,
                                         "index_type": "BTREE", "collation": "A", "is_visible": "YES", "expression": None})
        key("PRIMARY", shape["primary_key"], True)
        for name, columns in UNIQUE_NAMES.get(table_name, {}).items():
            key(name, columns, True)
        covered = [shape["primary_key"], *UNIQUE_NAMES.get(table_name, {}).values()]
        for number, (column_name, target) in enumerate(shape["foreign_keys"].items(), 1):
            target_table, target_column = target.split(".")
            name = f"{table_name}_ibfk_{number}"
            result["constraints"].append({"table_name": table_name, "constraint_name": name, "constraint_type": "FOREIGN KEY", "enforced": "YES"})
            result["keys"].append({"table_name": table_name, "constraint_name": name, "column_name": column_name,
                                  "ordinal_position": 1, "referenced_table_schema": IDENTITY["schema_name"],
                                  "referenced_table_name": target_table, "referenced_column_name": target_column})
            result["references"].append({"table_name": table_name, "constraint_name": name,
                                        "unique_constraint_schema": IDENTITY["schema_name"], "match_option": "NONE",
                                        "update_rule": "RESTRICT", "delete_rule": "RESTRICT"})
            if not any(columns[0] == column_name for columns in covered):
                result["indexes"].append({"table_name": table_name, "index_name": column_name, "non_unique": 1,
                                         "seq_in_index": 1, "column_name": column_name, "sub_part": None,
                                         "index_type": "BTREE", "collation": "A", "is_visible": "YES", "expression": None})
        for name, expression in shape["checks"].items():
            result["constraints"].append({"table_name": table_name, "constraint_name": name, "constraint_type": "CHECK", "enforced": "YES"})
            result["checks"].append({"table_name": table_name, "constraint_name": name,
                                     "check_clause": expression, "enforced": "YES"})
    return result


class CatalogRows:
    def __init__(self, rows): self.rows = copy.deepcopy(rows)
    def mappings(self): return self
    def all(self): return copy.deepcopy(self.rows)
    def first(self): return copy.deepcopy(self.rows[0]) if self.rows else None


class RecordingCatalogPort:
    """Consume finite supplied snapshots; never compute DDL/DML effects."""
    dialect = SimpleNamespace(name="mysql")

    def __init__(self, frames, *, identities=None, fail_table=None, active_transaction=False, commit_error=None, insert_error=None, session_checks=None, exceptions=None):
        self.frames = list(frames)
        self.current = None
        self.identity_rows = list(identities or [copy.deepcopy(IDENTITY)])
        self.last_identity = None
        self.fail_table = fail_table
        self.active_transaction = active_transaction
        self.commit_error = commit_error
        self.insert_error = insert_error
        self.session_checks = {"foreign_key_checks": 1, "unique_checks": 1} if session_checks is None else session_checks
        self.exceptions = exceptions
        self.events = []

    def in_transaction(self): return self.active_transaction

    def execute(self, statement, parameters=None):
        if statement.__class__.__name__ == "CreateTable":
            name = statement.element.name
            self.events.append(("ddl", name, statement))
            if name == self.fail_table:
                raise RuntimeError("synthetic DDL acknowledgement failure")
            return CatalogRows([])
        query = str(statement)
        upper = query.upper()
        self.events.append(("sql", query, copy.deepcopy(parameters)))
        self.active_transaction = True  # Mirrors SQLAlchemy's SELECT autobegin fact.
        if "@@SESSION.FOREIGN_KEY_CHECKS" in upper:
            return CatalogRows([self.session_checks])
        if upper.startswith("SHOW CREATE TABLE "):
            assert self.current is not None
            name = next((name for name in self.current[0]["resolved"] if query.endswith("`" + name + "`")), None)
            if name is None:
                # Finite synthetic SQLAlchemy/DBAPIError value; never a driver.
                raise self.exceptions.ProgrammingError(query, parameters, RuntimeError(1146, "synthetic missing table"))
            value = self.current[0]["resolved"][name]
            if isinstance(value, Exception): raise value
            return CatalogRows([value])
        if "@@SERVER_UUID" in upper:
            if self.identity_rows:
                self.last_identity = self.identity_rows.pop(0)
            assert self.last_identity is not None, "finite supplied identity missing"
            return CatalogRows([self.last_identity])
        if "INFORMATION_SCHEMA.TABLES" in upper:
            assert self.frames, "each production catalog inspection needs an explicit snapshot"
            self.current = self.frames.pop(0)
        families = (("INFORMATION_SCHEMA.CHECK_CONSTRAINTS", "checks"),
                    ("INFORMATION_SCHEMA.TABLE_CONSTRAINTS", "constraints"),
                    ("INFORMATION_SCHEMA.KEY_COLUMN_USAGE", "keys"),
                    ("INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS", "references"),
                    ("INFORMATION_SCHEMA.STATISTICS", "indexes"),
                    ("INFORMATION_SCHEMA.COLUMNS", "columns"),
                    ("INFORMATION_SCHEMA.TABLES", "tables"))
        for token, family in families:
            if token in upper:
                assert self.current is not None
                return CatalogRows(self.current[0][family])
        if upper.lstrip().startswith("SELECT") and "TEACHER_WORK_SCHEMA_VERSIONS" in upper:
            assert self.current is not None
            return CatalogRows([] if self.current[1] is None else [self.current[1]])
        if upper.lstrip().startswith("INSERT") and "TEACHER_WORK_SCHEMA_VERSIONS" in upper:
            self.events.append(("ledger_insert", query, copy.deepcopy(parameters)))
            if self.insert_error is not None: raise self.insert_error
            return CatalogRows([])
        if "DATABASE()" in upper:
            return CatalogRows([{"schema_name": IDENTITY["schema_name"]}])
        raise AssertionError(f"unexpected production statement: {query}")

    def commit(self):
        self.events.append(("commit",))
        if self.commit_error is not None: raise self.commit_error
        self.active_transaction = False


def _column(raw, table_name, column_name):
    return next(r for r in raw["columns"] if (r["table_name"], r["column_name"]) == (table_name, column_name))


def _observe(modules, raw, ledger=None):
    port = RecordingCatalogPort([(raw, ledger)], exceptions=modules.exceptions)
    return modules.schema.observe_teacher_work_mysql(port), port


def _refused_apply(modules, port, *, contract_hash=None, expected=None):
    port.exceptions = modules.exceptions
    try:
        modules.migration.apply_teacher_work_mysql(port, expected or _identity(modules),
            contract_hash=modules.contract.TEACHER_WORK_CONTRACT_HASH if contract_hash is None else contract_hash)
    except modules.migration.MysqlMigrationError as error:
        assert error.code and error.completed is False
        return error
    assert False, "unsafe or incomplete Teacher Work preparation must fail closed"


def _fresh_frames(modules, *, final_ledger=True):
    names = tuple(modules.contract.TEACHER_WORK_SCHEMA_CONTRACT["tables"])
    frames = [(_catalog(modules, ()), None)]
    for number in range(len(names)):
        frames.append((_catalog(modules, names[:number]), None))
        frames.append((_catalog(modules, names[:number + 1]), None))
    frames.append((_catalog(modules), None))
    if final_ledger:
        frames.append((_catalog(modules), _ledger(modules)))
    return frames


def test_mysql_metadata_ddl_pins_fresh_v2():
    m = _load()
    tables = m.schema.teacher_work_mysql_tables()
    assert tuple(t.name for t in tables) == tuple(m.contract.TEACHER_WORK_SCHEMA_CONTRACT["tables"])
    assert len(tables) == 13 and len({id(t.metadata) for t in tables}) == 1
    assert tables[0].metadata is m.models.TeacherWorkBase.metadata
    for table in tables:
        ddl = str(m.ddl.CreateTable(table).compile(dialect=m.mysql.dialect()))
        assert ddl.startswith("\nCREATE TABLE " + table.name)
        for fragment in ("ENGINE=InnoDB", "CHARSET=utf8mb4", "COLLATE utf8mb4_bin"):
            assert fragment in ddl, (table.name, fragment, ddl)
        for name, columns in UNIQUE_NAMES.get(table.name, {}).items():
            assert f"CONSTRAINT {name} UNIQUE" in ddl
            assert tuple(table.constraints and next(c for c in table.constraints if c.name == name).columns.keys()) == columns
        for name in m.contract.TEACHER_WORK_SCHEMA_CONTRACT["tables"][table.name]["checks"]:
            assert f"CONSTRAINT {name} CHECK" in ddl
    for table_name, column_name in (("teacher_work_tasks", "create_idempotency_key"),
                                    ("teacher_work_runs", "idempotency_key"),
                                    ("teacher_work_messages", "client_message_key")):
        table = next(t for t in tables if t.name == table_name)
        assert table.c[column_name].type.compile(dialect=m.mysql.dialect()) == "VARBINARY(512)"
    run = next(t for t in tables if t.name == "teacher_work_runs")
    assert str(run.c.repair_count.server_default.arg) == "0"


def test_mysql_observer_read_only_schema_scoped():
    m = _load()
    report, port = _observe(m, _catalog(m), _ledger(m))
    assert report.physical_valid and report.ready and report.ledger_present and report.ledger_valid, report.issues
    assert m.contract.inspect_teacher_work_schema(report.observation).ready
    assert not port.frames
    assert all(event[0] == "sql" and event[1].lstrip().upper().startswith(("SELECT", "SHOW CREATE TABLE ")) for event in port.events)
    for _, query, bindings in port.events:
        if "INFORMATION_SCHEMA." in query.upper():
            assert bindings and IDENTITY["schema_name"] in bindings.values()
            assert "TABLE_SCHEMA" in query.upper() or "CONSTRAINT_SCHEMA" in query.upper()
        if query.startswith("SHOW CREATE TABLE "):
            assert query.startswith("SHOW CREATE TABLE `" + IDENTITY["schema_name"] + "`.")


def test_mysql_observer_rejects_column_drift():
    m = _load()
    mutations = [
        ("teacher_work_tasks", "task_id", "column_type", "char(36)"),
        ("teacher_work_runs", "attempt", "column_type", "int unsigned"),
        ("teacher_work_runs", "attempt", "column_type", "bigint"),
        ("teacher_work_runs", "deadline", "column_type", "timestamp(6)"),
        ("teacher_work_runs", "deadline", "datetime_precision", 0),
        ("teacher_work_messages", "plain_text", "column_type", "text"),
        ("teacher_work_messages", "omitted_context", "column_type", "tinyint(2)"),
        ("teacher_work_tasks", "title", "is_nullable", "YES"),
        ("teacher_work_tasks", "title", "collation_name", "utf8mb4_general_ci"),
        ("teacher_work_tasks", "title", "character_set_name", "utf8"),
        ("teacher_work_tasks", "title", "extra", "VIRTUAL GENERATED"),
        ("teacher_work_tasks", "title", "generation_expression", "'fabricated'"),
    ]
    for table, column in (("teacher_work_tasks", "create_idempotency_key"), ("teacher_work_runs", "idempotency_key"), ("teacher_work_messages", "client_message_key")):
        mutations += [(table, column, "column_type", "varbinary(128)"), (table, column, "character_octet_length", 511)]
    for table, column, field, bad in mutations:
        raw = _catalog(m)
        _column(raw, table, column)[field] = bad
        report, _ = _observe(m, raw, _ledger(m))
        assert not report.physical_valid and not report.ready and report.issues, (table, column, field)
    for remove in (True, False):
        raw = _catalog(m)
        if remove:
            raw["columns"].pop()
        else:
            extra = copy.deepcopy(raw["columns"][0]); extra["column_name"] = "unreviewed_column"; raw["columns"].append(extra)
        assert not _observe(m, raw, _ledger(m))[0].ready


def test_mysql_observer_rejects_default_drift():
    m = _load()
    for table, column, value in (("teacher_work_runs", "repair_count", None),
                                 ("teacher_work_runs", "repair_count", "1"),
                                 ("teacher_work_messages", "result_type", "answer"),
                                 ("teacher_work_messages", "omitted_context", "0"),
                                 ("teacher_work_tasks", "input_revision", "1"),
                                 ("teacher_work_tasks", "created_at", "CURRENT_TIMESTAMP(6)")):
        raw = _catalog(m); _column(raw, table, column)["column_default"] = value
        report, _ = _observe(m, raw, _ledger(m))
        assert not report.ready and not report.physical_valid, (table, column)


def test_mysql_observer_pins_unique_names_and_full_keys():
    m = _load()
    for defect in ("name", "missing", "order", "prefix", "expression", "non_unique", "method"):
        raw = _catalog(m)
        name = "uq_tw_run_owner_task_kind_key"
        if defect == "name":
            for family, field in (("constraints", "constraint_name"), ("keys", "constraint_name"), ("indexes", "index_name")):
                for row in raw[family]:
                    if row.get(field) == name: row[field] = "renamed_unreviewed_receipt"
        elif defect == "missing":
            raw["constraints"] = [r for r in raw["constraints"] if r["constraint_name"] != name]
        elif defect == "order":
            for row in raw["keys"]:
                if row["constraint_name"] == name: row["ordinal_position"] = 5 - row["ordinal_position"]
        else:
            row = next(r for r in raw["indexes"] if r["index_name"] == name)
            row[{"prefix": "sub_part", "expression": "expression", "non_unique": "non_unique", "method": "index_type"}[defect]] = {"prefix": 8, "expression": "lower(owner)", "non_unique": 1, "method": "HASH"}[defect]
        report, _ = _observe(m, raw, _ledger(m))
        assert not report.ready and not report.physical_valid, defect
    raw = _catalog(m)
    row = next(r for r in raw["keys"] if r["constraint_name"] == "PRIMARY")
    row["column_name"] = "owner_subject"
    assert not _observe(m, raw, _ledger(m))[0].ready


def test_mysql_observer_rejects_fk_drift():
    m = _load()
    for family, field, bad in (("keys", "referenced_table_schema", "another_database"),
                                ("keys", "referenced_column_name", "owner_subject"),
                                ("references", "delete_rule", "CASCADE"),
                                ("references", "update_rule", "SET NULL"),
                                ("references", "unique_constraint_schema", "another_database")):
        raw = _catalog(m)
        row = next(r for r in raw[family] if r["table_name"] == "teacher_work_runs" and (family == "references" or r["referenced_table_name"] is not None))
        row[field] = bad
        report, _ = _observe(m, raw, _ledger(m))
        assert not report.ready and not report.physical_valid, (family, field)
    raw = _catalog(m)
    raw["references"] = [r for r in raw["references"] if r["table_name"] != "teacher_work_runs"]
    assert not _observe(m, raw, _ledger(m))[0].ready
    for checks in ({"foreign_key_checks": 0, "unique_checks": 1}, {"foreign_key_checks": 1, "unique_checks": 0}, {}):
        port = RecordingCatalogPort([(_catalog(m), _ledger(m))], session_checks=checks, exceptions=m.exceptions)
        report = m.schema.observe_teacher_work_mysql(port)
        assert not report.ready and report.issues, "disabled or unknown session enforcement must fail closed"
        port = RecordingCatalogPort([(_catalog(m, ()), None)], session_checks=checks, exceptions=m.exceptions)
        _refused_apply(m, port)
        assert not any(e[0] in {"ddl", "ledger_insert", "commit"} for e in port.events)


def test_mysql_observer_requires_enforced_exact_checks():
    m = _load()
    for defect in ("not_enforced", "missing_enforcement", "literal_case", "missing_check", "wrong_expression"):
        raw = _catalog(m); name = "ck_tw_message_role"
        if defect in {"not_enforced", "missing_enforcement"}:
            for family in ("checks", "constraints"):
                row = next(r for r in raw[family] if r["constraint_name"] == name)
                if defect == "not_enforced": row["enforced"] = "NO"
                else: row.pop("enforced")
        elif defect == "missing_check":
            raw["checks"] = [r for r in raw["checks"] if r["constraint_name"] != name]
        else:
            row = next(r for r in raw["checks"] if r["constraint_name"] == name)
            row["check_clause"] = row["check_clause"].replace("'assistant'", "'ASSISTANT'") if defect == "literal_case" else "1 = 1"
        assert not _observe(m, raw, _ledger(m))[0].ready, defect
    raw = _catalog(m)
    row = next(r for r in raw["checks"] if r["constraint_name"] == "ck_tw_message_role")
    row["check_clause"] = "((`role` in (_utf8mb4'user', _utf8mb4'assistant', _utf8mb4'tool')))"
    assert _observe(m, raw, _ledger(m))[0].ready


def test_mysql_observer_rejects_storage_options():
    m = _load()
    for field, bad in (("engine", "MyISAM"), ("table_collation", "utf8mb4_general_ci"),
                       ("character_set_name", "utf8"), ("table_type", "VIEW")):
        raw = _catalog(m); raw["tables"][0][field] = bad
        report, _ = _observe(m, raw, _ledger(m))
        assert not report.physical_valid and not report.ready, field
    raw = _catalog(m, ())
    name = "teacher_work_tasks"
    raw["resolved"][name] = {"Table": name, "Create Table": "CREATE TEMPORARY TABLE `" + name + "` (`id` int)"}
    report, _ = _observe(m, raw)
    assert report.issues, "a temporary-only target is not a verified fresh inventory"
    port = RecordingCatalogPort([(raw, None)], exceptions=m.exceptions)
    _refused_apply(m, port)
    assert not any(e[0] in {"ddl", "ledger_insert", "commit"} for e in port.events)
    for code in (1142, 1044):
        raw = _catalog(m)
        raw["resolved"][name] = m.exceptions.ProgrammingError("synthetic SHOW", None, RuntimeError(code, "synthetic denied"))
        assert _observe(m, raw, _ledger(m))[0].issues, "a permission failure cannot count as an absent target"


def test_mysql_observer_validates_completion_ledger():
    m = _load()
    for field, bad in (("version", 1), ("version", True), ("contract_hash", "0" * 64),
                       ("component", "b1"), ("completed_at", None)):
        ledger = _ledger(m); ledger[field] = bad
        report, _ = _observe(m, _catalog(m), ledger)
        assert report.physical_valid and not report.ready and report.ledger_present and not report.ledger_valid, field
    report, _ = _observe(m, _catalog(m))
    assert report.physical_valid and not report.ready and not report.ledger_present
    port = RecordingCatalogPort([(_catalog(m), None)])
    try: m.schema.require_teacher_work_mysql(port)
    except m.schema.MysqlSchemaError: pass
    else: assert False, "unledgered physical shape cannot satisfy schema readiness"
    for name in ("teacher_work_schema_versions", "teacher_work_tasks", "teacher_work_messages"):
        raw = _catalog(m)
        raw["resolved"][name]["Create Table"] = "CREATE TEMPORARY TABLE `" + name + "` (`id` int)"
        report, _ = _observe(m, raw, _ledger(m))
        assert not report.ready and report.issues, "temporary shadow must not certify a persistent receipt/target"
        port = RecordingCatalogPort([(raw, _ledger(m))], exceptions=m.exceptions)
        _refused_apply(m, port)
        assert not any(e[0] in {"ddl", "ledger_insert", "commit"} for e in port.events)


def test_mysql_plan_refuses_partial_v1_or_unledgered_v2():
    m = _load()
    names = tuple(m.contract.TEACHER_WORK_SCHEMA_CONTRACT["tables"])
    for raw, ledger in ((_catalog(m, names[:1]), None), (_catalog(m), None), (_catalog(m), {**_ledger(m), "version": 1})):
        port = RecordingCatalogPort([(raw, ledger)], exceptions=m.exceptions)
        try: m.migration.plan_teacher_work_mysql(port, _identity(m), contract_hash=m.contract.TEACHER_WORK_CONTRACT_HASH)
        except m.migration.MysqlMigrationError as error: assert not error.completed
        else: assert False, "partial, v1 or exact-but-unledgered schemas need a separate migration design"
        assert not any(e[0] in {"ddl", "ledger_insert", "commit"} for e in port.events)
    port = RecordingCatalogPort([(_catalog(m, ()), None)], exceptions=m.exceptions)
    plan = m.migration.plan_teacher_work_mysql(port, _identity(m), contract_hash=m.contract.TEACHER_WORK_CONTRACT_HASH)
    assert plan.mode == "fresh_v2" and plan.tables == names and plan.contract_hash == m.contract.TEACHER_WORK_CONTRACT_HASH
    assert not any(e[0] != "sql" for e in port.events)


def test_mysql_apply_checks_hash_and_identity_before_ddl():
    m = _load()
    port = RecordingCatalogPort([])
    _refused_apply(m, port, contract_hash="0" * 64)
    assert not port.events
    for operation in (m.migration.plan_teacher_work_mysql, m.migration.apply_teacher_work_mysql):
        port = RecordingCatalogPort([], active_transaction=True)
        try: operation(port, _identity(m), contract_hash=m.contract.TEACHER_WORK_CONTRACT_HASH)
        except m.migration.MysqlMigrationError as error:
            assert error.code == "teacher_work_fresh_connection_required", "existing caller transactions need an explicit entry refusal"
        else: assert False, "an existing caller transaction must be refused"
        assert not port.events, "entry transaction refusal must precede every SQL and identity query"
    for field in (*IDENTITY, "dialect"):
        row = copy.deepcopy(IDENTITY)
        if field != "dialect": row[field] = 0 if field == "skip_networking" else "wrong"
        port = RecordingCatalogPort([], identities=[row])
        if field == "dialect": port.dialect = SimpleNamespace(name="sqlite")
        error = _refused_apply(m, port)
        assert "identity" in error.code or "mysql" in error.code
        assert not any(e[0] != "sql" for e in port.events)
        assert not any("INFORMATION_SCHEMA." in e[1].upper() for e in port.events if e[0] == "sql")


def test_mysql_fresh_apply_records_ledger_after_full_verification():
    m = _load()
    port = RecordingCatalogPort(_fresh_frames(m), exceptions=m.exceptions)
    report = m.migration.apply_teacher_work_mysql(port, _identity(m), contract_hash=m.contract.TEACHER_WORK_CONTRACT_HASH)
    names = tuple(m.contract.TEACHER_WORK_SCHEMA_CONTRACT["tables"])
    assert report.completed and report.ledger_written and report.attempted_tables == report.confirmed_tables == names
    assert not port.frames
    assert tuple(e[1] for e in port.events if e[0] == "ddl") == names
    inserts = [i for i, e in enumerate(port.events) if e[0] == "ledger_insert"]
    assert len(inserts) == 1
    insert_position = inserts[0]
    assert all(i < insert_position for i, e in enumerate(port.events) if e[0] == "ddl")
    assert any("INFORMATION_SCHEMA.CHECK_CONSTRAINTS" in e[1].upper() for e in port.events[:insert_position] if e[0] == "sql")
    ledger = port.events[insert_position][2]
    assert ledger["component"] == "teacher_work" and ledger["version"] == 2 and ledger["contract_hash"] == m.contract.TEACHER_WORK_CONTRACT_HASH
    assert type(ledger["completed_at"]) is datetime
    assert sum(e[0] == "commit" for e in port.events) == 1
    for event in port.events:
        if event[0] == "sql":
            assert not any(token in event[1].upper() for token in ("ALTER ", "DROP ", "REPLACE ", "UPDATE ", "DELETE "))


def test_mysql_exact_completed_v2_is_noop():
    m = _load()
    port = RecordingCatalogPort([(_catalog(m), _ledger(m))], exceptions=m.exceptions)
    report = m.migration.apply_teacher_work_mysql(port, _identity(m), contract_hash=m.contract.TEACHER_WORK_CONTRACT_HASH)
    assert report.completed and not report.ledger_written and report.attempted_tables == report.confirmed_tables == ()
    assert all(e[0] == "sql" for e in port.events) and not port.frames
    port = RecordingCatalogPort([(_catalog(m), _ledger(m))], exceptions=m.exceptions)
    plan = m.migration.plan_teacher_work_mysql(port, _identity(m), contract_hash=m.contract.TEACHER_WORK_CONTRACT_HASH)
    assert plan.mode == "exact_v2" and plan.tables == ()


def test_mysql_ddl_failure_has_incomplete_journal_and_refuses_retry():
    m = _load()
    names = tuple(m.contract.TEACHER_WORK_SCHEMA_CONTRACT["tables"])
    frames = [(_catalog(m, ()), None), (_catalog(m, ()), None), (_catalog(m, names[:1]), None), (_catalog(m, names[:1]), None)]
    port = RecordingCatalogPort(frames, fail_table=names[1])
    error = _refused_apply(m, port)
    assert error.attempted_tables == names[:2] and error.confirmed_tables == names[:1]
    assert error.failed_table == names[1] and not error.ledger_written and not error.completed
    assert getattr(error, "ledger_commit_state", None) == "NOT_ATTEMPTED", "definitely absent completion commit needs an explicit journal state"
    assert not any(e[0] in {"ledger_insert", "commit"} for e in port.events)
    retry = RecordingCatalogPort([(_catalog(m, names[:1]), None)])
    error = _refused_apply(m, retry)
    assert error.attempted_tables == error.confirmed_tables == ()
    assert not any(e[0] != "sql" for e in retry.events)
    for field in ("commit_error", "insert_error"):
        port = RecordingCatalogPort(_fresh_frames(m, final_ledger=False), exceptions=m.exceptions,
                                    **{field: RuntimeError("synthetic completion acknowledgement lost")})
        error = _refused_apply(m, port)
        assert error.attempted_tables == error.confirmed_tables == names and not error.completed
        assert getattr(error, "ledger_commit_state", None) == "UNKNOWN", "lost acknowledgement cannot certify receipt absence"
        assert error.ledger_written is None, "completion receipt outcome is unknown after an unacknowledged attempt"
        assert sum(e[0] == "ledger_insert" for e in port.events) == 1
        assert sum(e[0] == "commit" for e in port.events) == (1 if field == "commit_error" else 0)
        assert not port.frames, "uncertain receipt must stop without any automatic retry or completion claim"


def test_mysql_mid_apply_identity_or_shape_drift_stops():
    m = _load()
    names = tuple(m.contract.TEACHER_WORK_SCHEMA_CONTRACT["tables"])
    wrong = {**IDENTITY, "server_uuid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"}
    port = RecordingCatalogPort([(_catalog(m, ()), None)], identities=[IDENTITY, wrong])
    error = _refused_apply(m, port)
    assert not error.attempted_tables and not any(e[0] != "sql" for e in port.events)
    bad = _catalog(m, names[:1]); _column(bad, names[0], "title")["is_nullable"] = "YES"
    port = RecordingCatalogPort([(_catalog(m, ()), None), (_catalog(m, ()), None), (bad, None)])
    error = _refused_apply(m, port)
    assert error.attempted_tables == names[:1] and not error.confirmed_tables
    assert not any(e[0] in {"ledger_insert", "commit"} for e in port.events)
    appeared = _catalog(m, names[:1])
    port = RecordingCatalogPort([(_catalog(m, ()), None), (appeared, None)])
    error = _refused_apply(m, port)
    assert not error.attempted_tables, "a concurrent table must not be silently adopted"


def test_mysql_imports_do_not_construct_runtime():
    m = _load()
    forbidden = {"app.main", "app.core.config", "app.core.database", "app.models.domain_record", "app.services.teaching.schema"}
    for relative in (SCHEMA_MEMBER, MIGRATION_MEMBER):
        tree = ast.parse((BACKEND / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import): assert not {a.name for a in node.names} & forbidden
            if isinstance(node, ast.ImportFrom): assert node.module not in forbidden
            if isinstance(node, ast.Call):
                target = ast.unparse(node.func)
                assert target.rsplit(".", 1)[-1] not in {"create_engine", "create_all", "drop_all", "sessionmaker", "Session", "connect", "begin", "begin_nested", "reflect"}, target
        for node in tree.body:
            if isinstance(node, (ast.Expr, ast.Assign, ast.AnnAssign)):
                assert not any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr in {"execute", "commit", "create", "create_all"} for c in ast.walk(node))
    assert m.schema.teacher_work_mysql_tables()[0].metadata is m.models.TeacherWorkBase.metadata
