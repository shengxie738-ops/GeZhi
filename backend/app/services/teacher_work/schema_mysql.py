"""Read-only physical Teacher Work v2 inspection on a supplied MySQL connection.

No engine, session, settings, application startup, DDL or repair is constructed.
The unchanged v2 content hash is necessary but insufficient: physical defaults,
named receipt constraints, complete binary indexes and CHECK enforcement are
independently verified. A recording catalog port is synthetic evidence only.
"""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import re

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.models.teacher_work import (
    Artifact, CatalogSelection, EvidenceSnapshot, OutlineApproval, OutlineSnapshot,
    OwnerRunLease, PackageVersion, PreviewState, TeacherWorkSchemaVersion,
    VersionReview, WorkMessage, WorkRun, WorkTask,
)
from app.services.teacher_work.schema import (
    TEACHER_WORK_COMPONENT, TEACHER_WORK_CONTRACT_HASH, TEACHER_WORK_SCHEMA_CONTRACT,
    TEACHER_WORK_SCHEMA_VERSION, inspect_teacher_work_schema,
)
from app.services.teacher_work.types import canonical_digest


def teacher_work_mysql_tables():
    """Explicit FK-ordered allowlist; later metadata registration cannot widen it."""
    return (WorkTask.__table__, WorkRun.__table__, WorkMessage.__table__,
            EvidenceSnapshot.__table__, OutlineSnapshot.__table__, OutlineApproval.__table__,
            PackageVersion.__table__, Artifact.__table__, PreviewState.__table__,
            VersionReview.__table__, CatalogSelection.__table__, OwnerRunLease.__table__,
            TeacherWorkSchemaVersion.__table__)


UNIQUE_CONSTRAINTS = {
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


@dataclass(frozen=True)
class DatabaseIdentity:
    schema_name: str
    server_uuid: str
    datadir: str
    socket: str

    def __post_init__(self):
        for field in ("schema_name", "server_uuid", "datadir", "socket"):
            value = getattr(self, field)
            if type(value) is not str or not value or value != value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise ValueError("complete exact database identity required: " + field)
        if not self.datadir.startswith("/") or not self.socket.startswith("/"):
            raise ValueError("absolute manifest datadir/socket paths required")


@dataclass(frozen=True)
class MysqlSchemaIssue:
    table: str
    kind: str
    detail: str


class MysqlSchemaError(RuntimeError):
    def __init__(self, code, issues):
        self.code, self.issues = code, tuple(issues)
        super().__init__(code + ": " + "; ".join(i.table + "/" + i.kind + ": " + i.detail for i in self.issues))


@dataclass(frozen=True)
class MysqlSchemaReport:
    dialect: str
    missing_tables: tuple[str, ...]
    issues: tuple[MysqlSchemaIssue, ...]
    observation: dict
    ledger_present: bool
    ledger_valid: bool

    @property
    def physical_valid(self):
        return self.dialect == "mysql" and not self.missing_tables and not self.issues

    @property
    def ready(self):
        return self.physical_valid and self.ledger_valid and inspect_teacher_work_schema(self.observation).ready


def _check(expression, *, catalog=False):
    """Normalize serializer syntax while preserving every quoted literal byte."""
    value = str(expression)
    if catalog:
        # MySQL 8.4 CHECK_CLAUSE exposes introduced, escaped delimiters.
        # Only the plain enum literals in the pinned v2 contract are supported;
        # embedded escapes/quotes and other introducers remain unequal.
        value = re.sub(r"\b_utf8mb4\\'([A-Za-z_]+)\\'", lambda m: "'" + m[1] + "'", value)
    literals = []
    def protect(match):
        literals.append(match.group(0))
        return "__tw_literal_" + str(len(literals) - 1) + "__"
    value = re.sub(r"'(?:''|\\.|[^'])*'", protect, value)
    value = re.sub(r"\b_utf8mb4(?=\s*__tw_literal_\d+__)", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value.replace("`", "").lower()).strip()
    def outer(value):
        while value.startswith("(") and value.endswith(")"):
            depth, wrapped = 0, True
            for position, char in enumerate(value):
                depth += (char == "(") - (char == ")")
                if depth == 0 and position < len(value) - 1:
                    wrapped = False; break
            if not wrapped: break
            value = value[1:-1].strip()
        return value
    previous = None
    while previous != value:
        previous = value
        value = re.sub(r"(?<![a-z0-9_])\(([^()]*)\)",
            lambda m: m.group(0) if re.search(r"\b(?:and|or)\b", m[1])
            and not re.fullmatch(r"[a-z_][a-z0-9_]* between [0-9]+ and [0-9]+", m[1].strip())
            else m[1].strip(), value)
        value = outer(value)
    value = re.sub(r"\s*([=<>!,])\s*", r"\1", value)
    return re.sub(r"__tw_literal_(\d+)__", lambda m: literals[int(m.group(1))], value)


def _type(row):
    value = str(row.get("column_type", "")).lower()
    # Integer display width is nonsemantic; signedness/zerofill remain exact.
    if re.fullmatch(r"(?:int|integer)(?:\([0-9]+\))?", value): return "integer"
    return value


def _column_valid(row, expected, *, repair_default):
    kind = expected["type"]
    family = kind.split("(", 1)[0]
    actual_family = row.get("data_type")
    if _type(row) != kind or actual_family not in ({"int", "integer"} if family == "integer" else {family}): return False
    if row.get("is_nullable") != ("YES" if expected["nullable"] else "NO"): return False
    if row.get("column_default") != ("0" if repair_default else None): return False
    if row.get("extra") != "" or row.get("generation_expression") != "": return False
    if family in {"varchar", "varbinary"}:
        length = int(kind.split("(", 1)[1].rstrip(")"))
        if row.get("character_maximum_length") != length or row.get("character_octet_length") != length * (4 if family == "varchar" else 1): return False
    if family == "datetime" and row.get("datetime_precision") != 6: return False
    pair = (row.get("character_set_name"), row.get("collation_name"))
    if family in {"varchar", "text", "mediumtext"}: return pair == ("utf8mb4", "utf8mb4_bin")
    # Native JSON has its fixed binary Unicode semantics; versions may expose
    # those internal properties or report no string-column charset properties.
    if family == "json": return pair in {(None, None), ("utf8mb4", "utf8mb4_bin")}
    return pair == (None, None)


def _ordered(rows, ordinal, column):
    positions = [r.get(ordinal) for r in rows]
    if any(type(p) is not int for p in positions) or sorted(positions) != list(range(1, len(rows) + 1)):
        raise ValueError("incomplete or duplicate key positions")
    return tuple(r.get(column) for r in sorted(rows, key=lambda r: r[ordinal]))


def _keys_valid(table, shape, raw, schema_name):
    constraints = raw["constraints"]
    names = [r.get("constraint_name") for r in constraints]
    if len(set(names)) != len(names) or any(r.get("enforced") != "YES" for r in constraints): return False
    named = {r["constraint_name"]: r["constraint_type"] for r in constraints}
    expected_uniques = UNIQUE_CONSTRAINTS.get(table, {})
    if {n for n, kind in named.items() if kind == "PRIMARY KEY"} != {"PRIMARY"}: return False
    if {n for n, kind in named.items() if kind == "UNIQUE"} != set(expected_uniques): return False
    if {n for n, kind in named.items() if kind == "CHECK"} != set(shape["checks"]): return False
    if any(kind not in {"PRIMARY KEY", "UNIQUE", "CHECK", "FOREIGN KEY"} for kind in named.values()): return False
    key_groups = {}
    for row in raw["keys"]: key_groups.setdefault(row.get("constraint_name"), []).append(row)
    expected_key_names = {n for n, kind in named.items() if kind != "CHECK"}
    if set(key_groups) != expected_key_names: return False
    column_keys = {n: _ordered(rows, "ordinal_position", "column_name") for n, rows in key_groups.items()}
    if column_keys["PRIMARY"] != shape["primary_key"]: return False
    if any(column_keys[n] != columns for n, columns in expected_uniques.items()): return False
    for name, rows in key_groups.items():
        if named[name] != "FOREIGN KEY" and any(r.get("referenced_table_schema") is not None or r.get("referenced_table_name") is not None or r.get("referenced_column_name") is not None for r in rows): return False
    fk_names = {n for n, kind in named.items() if kind == "FOREIGN KEY"}
    references = {r.get("constraint_name"): r for r in raw["references"]}
    if len(references) != len(raw["references"]) or set(references) != fk_names: return False
    fks = {}
    for name in fk_names:
        rows = key_groups[name]
        if len(rows) != 1: return False
        row, reference = rows[0], references[name]
        if row.get("referenced_table_schema") != schema_name or reference.get("unique_constraint_schema") != schema_name: return False
        if reference.get("delete_rule") not in {"RESTRICT", "NO ACTION"} or reference.get("update_rule") not in {"RESTRICT", "NO ACTION"} or reference.get("match_option") != "NONE": return False
        column = row.get("column_name")
        if column in fks: return False
        fks[column] = str(row.get("referenced_table_name")) + "." + str(row.get("referenced_column_name"))
    if fks != shape["foreign_keys"]: return False
    indexes = {}
    for row in raw["indexes"]:
        if row.get("sub_part") is not None or row.get("expression") is not None or row.get("index_type") != "BTREE" or row.get("collation") != "A" or row.get("is_visible") != "YES" or type(row.get("non_unique")) is not int or row["non_unique"] not in {0, 1}: return False
        indexes.setdefault(row.get("index_name"), []).append(row)
    expected_unique_indexes = {"PRIMARY": shape["primary_key"], **expected_uniques}
    actual_unique_indexes = {}
    nonunique_columns = []
    for name, rows in indexes.items():
        if len({r["non_unique"] for r in rows}) != 1: return False
        columns = _ordered(rows, "seq_in_index", "column_name")
        if rows[0]["non_unique"] == 0: actual_unique_indexes[name] = columns
        else:
            # Only full one-column indexes supporting declared FKs are implicit
            # MySQL additions. Prefix, expression and unreviewed indexes fail.
            if len(columns) != 1 or columns[0] not in fks: return False
            nonunique_columns.append(columns)
    if actual_unique_indexes != expected_unique_indexes or len(set(nonunique_columns)) != len(nonunique_columns): return False
    full_indexes = list(actual_unique_indexes.values()) + nonunique_columns
    return all(any(columns[0] == column for columns in full_indexes) for column in fks)


def _table_issues(table, shape, raw, schema_name):
    issues = []
    options = raw["tables"]
    if len(options) != 1 or any(options[0].get(k) != v for k, v in {"table_type": "BASE TABLE", "engine": "InnoDB", "table_collation": "utf8mb4_bin", "character_set_name": "utf8mb4"}.items()):
        issues.append(MysqlSchemaIssue(table, "options", "exact InnoDB/utf8mb4/utf8mb4_bin base table required"))
    rows = raw["columns"]
    columns = {r.get("column_name"): r for r in rows}
    if len(columns) != len(rows) or set(columns) != set(shape["columns"]):
        issues.append(MysqlSchemaIssue(table, "columns", "exact columns required"))
    for name, expected in shape["columns"].items():
        if name in columns and not _column_valid(columns[name], expected, repair_default=(table, name) == ("teacher_work_runs", "repair_count")):
            issues.append(MysqlSchemaIssue(table, "column", "physical type/nullability/default/charset differs: " + name))
    try: keys_valid = _keys_valid(table, shape, raw, schema_name)
    except (KeyError, TypeError, ValueError): keys_valid = False
    if not keys_valid: issues.append(MysqlSchemaIssue(table, "keys", "exact PK/FK/named unique/full binary index facts required"))
    checks = {r.get("constraint_name"): r for r in raw["checks"]}
    if len(checks) != len(raw["checks"]) or set(checks) != set(shape["checks"]) or any(checks.get(n, {}).get("enforced") != "YES" or _check(checks.get(n, {}).get("check_clause", ""), catalog=True) != _check(expression) for n, expression in shape["checks"].items()):
        issues.append(MysqlSchemaIssue(table, "checks", "exact enforced checks required"))
    return issues


def _resolved_table_issues(connection, schema_name, names, present):
    """Detect session-local temporary shadows, including temporary-only names.

    INFORMATION_SCHEMA describes persistent tables, not temporary resolution.
    SHOW is read-only. Only a native integer1146 inside a SQLAlchemy DBAPIError
    proves a missing name; denied/unavailable/malformed observations fail closed.
    """
    issues = []
    schema = "`" + schema_name.replace("`", "``") + "`"
    for name in names:
        query = "SHOW CREATE TABLE " + schema + ".`" + name + "`"
        try:
            row = connection.execute(text(query)).mappings().first()
        except DBAPIError as exc:
            args = getattr(exc.orig, "args", ())
            absent = bool(args) and type(args[0]) is int and args[0] == 1146
            if absent and name not in present: continue
            issues.append(MysqlSchemaIssue(name, "resolved_table", "resolved table unavailable or differs from persistent inventory"))
            continue
        except Exception:
            issues.append(MysqlSchemaIssue(name, "resolved_table", "resolved table observation unavailable"))
            continue
        statement = row.get("Create Table") if row else None
        prefix = r"^CREATE\s+TABLE\s+(?:`" + re.escape(name) + "`|" + re.escape(name) + r")\s*\("
        valid = (row is not None and set(row) == {"Table", "Create Table"} and row.get("Table") == name
                 and type(statement) is str and re.match(prefix, statement, flags=re.IGNORECASE) is not None)
        if name not in present or not valid:
            issues.append(MysqlSchemaIssue(name, "resolved_table", "exact persistent target required; temporary shadow refused"))
    return issues


def observe_teacher_work_mysql(connection) -> MysqlSchemaReport:
    """Read only schema-scoped catalogs and the verified target ledger shape."""
    dialect = getattr(getattr(connection, "dialect", None), "name", "unknown")
    expected = TEACHER_WORK_SCHEMA_CONTRACT["tables"]
    observation = {"dialect": dialect, "tables": {}}
    issues = []
    if dialect != "mysql":
        return MysqlSchemaReport(dialect, tuple(expected), (MysqlSchemaIssue("database", "dialect", "MySQL required"),), observation, False, False)
    if canonical_digest(TEACHER_WORK_SCHEMA_CONTRACT) != TEACHER_WORK_CONTRACT_HASH:
        return MysqlSchemaReport(dialect, tuple(expected), (MysqlSchemaIssue("teacher_work", "contract", "reviewed v2 contract changed"),), observation, False, False)
    try:
        enforcement = connection.execute(text("SELECT @@session.foreign_key_checks AS foreign_key_checks, @@session.unique_checks AS unique_checks")).mappings().first()
        if enforcement is None or any(type(enforcement.get(name)) is not int or enforcement[name] != 1 for name in ("foreign_key_checks", "unique_checks")):
            return MysqlSchemaReport(dialect, tuple(expected), (MysqlSchemaIssue("database", "session_checks", "enabled session FK and unique checks required"),), observation, False, False)
        row = connection.execute(text("SELECT DATABASE() AS schema_name")).mappings().first()
        schema_name = row.get("schema_name") if row else None
        if type(schema_name) is not str or not schema_name: raise ValueError("database unavailable")
        parameters = {"schema_name": schema_name, **{"tw" + str(i): name for i, name in enumerate(expected)}}
        names = ",".join(":tw" + str(i) for i in range(len(expected)))
        queries = {
            "tables": "SELECT t.TABLE_NAME AS table_name, t.TABLE_TYPE AS table_type, t.ENGINE AS engine, t.TABLE_COLLATION AS table_collation, c.CHARACTER_SET_NAME AS character_set_name FROM INFORMATION_SCHEMA.TABLES t LEFT JOIN INFORMATION_SCHEMA.COLLATION_CHARACTER_SET_APPLICABILITY c ON c.COLLATION_NAME=t.TABLE_COLLATION WHERE t.TABLE_SCHEMA=:schema_name AND t.TABLE_NAME IN (" + names + ")",
            "columns": "SELECT TABLE_NAME AS table_name, COLUMN_NAME AS column_name, ORDINAL_POSITION AS ordinal_position, DATA_TYPE AS data_type, COLUMN_TYPE AS column_type, IS_NULLABLE AS is_nullable, COLUMN_DEFAULT AS column_default, CHARACTER_MAXIMUM_LENGTH AS character_maximum_length, CHARACTER_OCTET_LENGTH AS character_octet_length, DATETIME_PRECISION AS datetime_precision, CHARACTER_SET_NAME AS character_set_name, COLLATION_NAME AS collation_name, EXTRA AS extra, GENERATION_EXPRESSION AS generation_expression FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=:schema_name AND TABLE_NAME IN (" + names + ")",
            "constraints": "SELECT TABLE_NAME AS table_name, CONSTRAINT_NAME AS constraint_name, CONSTRAINT_TYPE AS constraint_type, ENFORCED AS enforced FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS WHERE TABLE_SCHEMA=:schema_name AND TABLE_NAME IN (" + names + ")",
            "keys": "SELECT TABLE_NAME AS table_name, CONSTRAINT_NAME AS constraint_name, COLUMN_NAME AS column_name, ORDINAL_POSITION AS ordinal_position, REFERENCED_TABLE_SCHEMA AS referenced_table_schema, REFERENCED_TABLE_NAME AS referenced_table_name, REFERENCED_COLUMN_NAME AS referenced_column_name FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA=:schema_name AND TABLE_NAME IN (" + names + ")",
            "references": "SELECT TABLE_NAME AS table_name, CONSTRAINT_NAME AS constraint_name, UNIQUE_CONSTRAINT_SCHEMA AS unique_constraint_schema, MATCH_OPTION AS match_option, UPDATE_RULE AS update_rule, DELETE_RULE AS delete_rule FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS WHERE CONSTRAINT_SCHEMA=:schema_name AND TABLE_NAME IN (" + names + ")",
            "checks": "SELECT tc.TABLE_NAME AS table_name, cc.CONSTRAINT_NAME AS constraint_name, cc.CHECK_CLAUSE AS check_clause, tc.ENFORCED AS enforced FROM INFORMATION_SCHEMA.CHECK_CONSTRAINTS cc JOIN INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc ON tc.CONSTRAINT_SCHEMA=cc.CONSTRAINT_SCHEMA AND tc.CONSTRAINT_NAME=cc.CONSTRAINT_NAME WHERE tc.TABLE_SCHEMA=:schema_name AND tc.CONSTRAINT_TYPE='CHECK' AND tc.TABLE_NAME IN (" + names + ")",
            "indexes": "SELECT TABLE_NAME AS table_name, INDEX_NAME AS index_name, NON_UNIQUE AS non_unique, SEQ_IN_INDEX AS seq_in_index, COLUMN_NAME AS column_name, SUB_PART AS sub_part, INDEX_TYPE AS index_type, COLLATION AS collation, IS_VISIBLE AS is_visible, EXPRESSION AS expression FROM INFORMATION_SCHEMA.STATISTICS WHERE TABLE_SCHEMA=:schema_name AND TABLE_NAME IN (" + names + ")",
        }
        raw = {family: list(connection.execute(text(query), parameters).mappings().all()) for family, query in queries.items()}
        present = {r.get("table_name") for r in raw["tables"]}
        missing = tuple(name for name in expected if name not in present)
        issues.extend(_resolved_table_issues(connection, schema_name, expected, present))
        for table, shape in expected.items():
            if table not in present: continue
            table_raw = {family: [r for r in rows if r.get("table_name") == table] for family, rows in raw.items()}
            table_issues = _table_issues(table, shape, table_raw, schema_name)
            issues.extend(table_issues)
            if not table_issues:
                # Serialize the existing hash vocabulary only after the actual
                # independently richer physical facts have all matched it.
                observation["tables"][table] = deepcopy(shape)
        ledger_present, ledger_valid = False, False
        ledger_name = TeacherWorkSchemaVersion.__tablename__
        if ledger_name in observation["tables"] and not any(i.kind == "resolved_table" for i in issues):
            rows = list(connection.execute(text("SELECT component, version, contract_hash, completed_at FROM teacher_work_schema_versions WHERE component=:component LIMIT 2"), {"component": TEACHER_WORK_COMPONENT}).mappings().all())
            ledger_present = bool(rows)
            if len(rows) == 1:
                receipt = rows[0]
                version, digest = receipt.get("version"), receipt.get("contract_hash")
                observation.update(version=version, contract_hash=digest)
                ledger_valid = (receipt.get("component") == TEACHER_WORK_COMPONENT and type(version) is int and version == TEACHER_WORK_SCHEMA_VERSION and type(digest) is str and digest == TEACHER_WORK_CONTRACT_HASH and type(receipt.get("completed_at")) is datetime)
        return MysqlSchemaReport(dialect, missing, tuple(issues), observation, ledger_present, ledger_valid)
    except Exception:
        # No raw driver text, identifiers, credentials or partial certification.
        return MysqlSchemaReport(dialect, tuple(expected), (MysqlSchemaIssue("teacher_work", "observation", "physical MySQL inspection unavailable"),), {"dialect": dialect, "tables": {}}, False, False)


def require_teacher_work_mysql(connection) -> None:
    report = observe_teacher_work_mysql(connection)
    if report.ready: return
    issues = report.issues + tuple(MysqlSchemaIssue(name, "missing", "explicit fresh-v2 preparation required") for name in report.missing_tables)
    if not report.ledger_valid: issues += (MysqlSchemaIssue("teacher_work_schema_versions", "ledger", "exact completed v2 ledger required"),)
    raise MysqlSchemaError("teacher_work_mysql_unverified", issues)
