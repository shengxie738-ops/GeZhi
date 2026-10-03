"""Read-only structure and capability inspection with supplied dependencies.

No settings, sessions or engines are constructed here. SQLite inspections are
synthetic evidence only and cannot satisfy the runtime MySQL requirement.
"""
from dataclasses import dataclass
from hashlib import sha256
import json
import re

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Integer, JSON, String, UniqueConstraint, inspect, text
from sqlalchemy.dialects import mysql, sqlite

from app.models.teaching import AccessEvent, Course, Enrollment, Offering, RosterPreview, TeachingRole, WriteReceipt
from app.models.teaching_schema import TeachingSchemaVersion

B1_SCHEMA_VERSION = 1
B1_COMPONENT = "b1"


def b1_tables():
    """Explicit, FK-ordered B1 allowlist; metadata registration never widens it."""
    return (Course.__table__, Offering.__table__, Enrollment.__table__, TeachingRole.__table__, RosterPreview.__table__, WriteReceipt.__table__, AccessEvent.__table__, TeachingSchemaVersion.__table__)


@dataclass(frozen=True)
class DatabaseIdentity:
    schema_name: str
    server_uuid: str
    datadir: str
    socket: str

    def __post_init__(self):
        for name in ("schema_name", "server_uuid", "datadir", "socket"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"complete exact database identity required: {name}")
        if not self.datadir.startswith("/") or not self.socket.startswith("/"):
            raise ValueError("datadir and socket must be absolute manifest paths")


@dataclass(frozen=True)
class SchemaIssue:
    table: str
    kind: str
    detail: str


@dataclass(frozen=True)
class SchemaReport:
    dialect: str
    missing_tables: tuple[str, ...]
    issues: tuple[SchemaIssue, ...]
    version: int | None
    contract_hash: str | None
    ledger_present: bool
    mysql_verified: bool

    @property
    def shape_valid(self):
        return not self.missing_tables and not self.issues

    @property
    def ready(self):
        return self.shape_valid and self.mysql_verified and self.ledger_present and self.version == B1_SCHEMA_VERSION and self.contract_hash == B1_CONTRACT_HASH


class TeachingSchemaError(RuntimeError):
    def __init__(self, code, issues):
        self.code = code
        self.issues = tuple(issues)
        super().__init__(code + ": " + "; ".join(f"{i.table}/{i.kind}: {i.detail}" for i in self.issues))


@dataclass(frozen=True)
class TeachingCapability:
    available: bool
    reason: str
    schema_version: int | None = None


def teaching_capability(*, enabled=False, institution_id="", assignments_enabled=False, feedback_enabled=False, revisions_enabled=False, session=None):
    """Task1 capability boundary. HTTP routing/response contracts belong to Task6."""
    if (revisions_enabled and not feedback_enabled) or (feedback_enabled and not assignments_enabled) or (assignments_enabled and not enabled):
        return TeachingCapability(False, "dependency_disabled")
    if not enabled:
        return TeachingCapability(False, "disabled")
    if not isinstance(institution_id, str) or not institution_id.strip() or len(institution_id) > 64:
        return TeachingCapability(False, "institution_required")
    if revisions_enabled:
        return TeachingCapability(False, "revisions_unavailable")
    if feedback_enabled:
        return TeachingCapability(False, "feedback_unavailable")
    if assignments_enabled:
        return TeachingCapability(False, "assignments_unavailable")
    if session is None:
        return TeachingCapability(False, "schema_unverified")
    try:
        require_teaching_schema(session)
    except TeachingSchemaError as exc:
        return TeachingCapability(False, exc.code)
    return TeachingCapability(True, "available", B1_SCHEMA_VERSION)


def _dialect(name):
    return mysql.dialect() if name == "mysql" else sqlite.dialect()


def _type_contract(column_type, dialect_name):
    """Exact physical family/options, not a SQLAlchemy superclass equivalence."""
    dialect = _dialect(dialect_name)
    resolved = column_type.dialect_impl(dialect)
    compiled = str(resolved.compile(dialect=dialect))
    match = re.match(r"[A-Za-z]+", compiled)
    family = match.group(0).lower() if match else "unsupported"
    if family in {"bool", "boolean"}:
        return ("boolean",)
    # Only the documented unsigned-free BOOLEAN/TINYINT(1) equivalence.
    if dialect_name == "mysql" and family == "tinyint" and getattr(resolved, "display_width", None) == 1 and not getattr(resolved, "unsigned", False) and not getattr(resolved, "zerofill", False):
        return ("boolean",)
    if family in {"bigint", "integer", "int", "smallint", "mediumint", "tinyint"}:
        if family == "int": family = "integer"
        return (family, bool(getattr(resolved, "unsigned", False)), bool(getattr(resolved, "zerofill", False)))
    if isinstance(resolved, String):
        return (family, resolved.length, getattr(resolved, "charset", None), getattr(resolved, "collation", None), bool(getattr(resolved, "ascii", False)), bool(getattr(resolved, "binary", False)), bool(getattr(resolved, "national", False)))
    if family == "json" and isinstance(resolved, JSON):
        return ("json",)
    if isinstance(resolved, DateTime):
        return (family, getattr(resolved, "fsp", 0) if dialect_name == "mysql" else None, bool(getattr(resolved, "timezone", False)))
    return ("unsupported", compiled)


def _strip_outer_parentheses(value):
    while value.startswith("(") and value.endswith(")"):
        depth = 0
        quoted = False
        wrapped = True
        for index, char in enumerate(value):
            if char == "'": quoted = not quoted
            if quoted: continue
            if char == "(": depth += 1
            if char == ")": depth -= 1
            if depth == 0 and index < len(value) - 1:
                wrapped = False; break
        if not wrapped: break
        value = value[1:-1].strip()
    return value


def _check_contract(expression):
    """Normalize reflection syntax without changing any quoted literal bytes."""
    literals = []
    def protect_literal(match):
        literals.append(match.group(0))
        return f"__literal_{len(literals) - 1}__"
    value = str(expression)
    # Protect quoted bytes first, including escaped/doubled quotes. Remove only
    # charset introducers outside those tokens; quoted '_utf8mb4' is actual data.
    value = re.sub(r"'(?:''|\\.|[^'])*'", protect_literal, value)
    value = re.sub(r"\b_utf8mb4(?=\s*__literal_\d+__)", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value.replace("`", "").lower()).strip()
    value = _strip_outer_parentheses(value)
    previous = None
    while previous != value:
        previous = value
        def atomic(match):
            content = match.group(1)
            return match.group(0) if re.search(r"\b(?:and|or)\b", content) else content.strip()
        value = re.sub(r"(?<![a-z0-9_])\(([^()]*)\)", atomic, value)
        value = _strip_outer_parentheses(value)
    value = re.sub(r"\s*([=<>!,])\s*", r"\1", value)
    return re.sub(r"__literal_(\d+)__", lambda match: literals[int(match.group(1))], value)


def _table_contract(table, dialect_name):
    return {
        "columns": {c.name: {"type": _type_contract(c.type, dialect_name), "nullable": c.nullable} for c in table.columns},
        "pk": (table.primary_key.name, tuple(table.primary_key.columns.keys())),
        "foreign_keys": sorted((c.name, tuple(c.columns.keys()), c.referred_table.name, tuple(e.column.name for e in c.elements), None, None, None) for c in table.foreign_key_constraints),
        "uniques": sorted((c.name, tuple(c.columns.keys())) for c in table.constraints if isinstance(c, UniqueConstraint)),
        "indexes": sorted((i.name, tuple(i.columns.keys()), bool(i.unique)) for i in table.indexes),
        "index_options": {},
        "checks": sorted((c.name, _check_contract(c.sqltext)) for c in table.constraints if isinstance(c, CheckConstraint)),
        "mysql": {"engine": "InnoDB", "charset": "utf8mb4", "collation": "utf8mb4_bin"},
    }


B1_CONTRACT_HASH = sha256(json.dumps({"component": B1_COMPONENT, "version": B1_SCHEMA_VERSION, "tables": {t.name: _table_contract(t, "mysql") for t in b1_tables()}}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _existing_contract(inspector, table, dialect_name):
    columns = inspector.get_columns(table.name)
    pk = inspector.get_pk_constraint(table.name)
    raw_indexes = inspector.get_indexes(table.name)
    uniques = inspector.get_unique_constraints(table.name)
    duplicate_pairs = {(u.get("duplicates_index"), tuple(u.get("column_names") or ())) for u in uniques if u.get("duplicates_index") == u.get("name")}
    indexes = []
    index_options = {}
    for index in raw_indexes:
        name = index.get("name")
        column_names = tuple(index.get("column_names") or ())
        options = dict(index.get("dialect_options") or {})
        # Ordinary BTREE is the only implicit index-method equivalence. Prefix,
        # parser, FULLTEXT and other physical changes must never be suppressed.
        if str(options.get("mysql_using", "")).upper() == "BTREE": options.pop("mysql_using")
        options = {key: value for key, value in options.items() if value is not None and value != {}}
        if options: index_options[name] = options
        paired = bool(index.get("unique")) and (name, column_names) in duplicate_pairs
        if not paired:
            indexes.append(index)
    default_schema = getattr(inspector, "default_schema_name", None)
    def local_reference(foreign_key):
        referred = foreign_key.get("referred_schema")
        return None if referred is None or (default_schema is not None and referred == default_schema) else referred
    foreign_keys = inspector.get_foreign_keys(table.name)
    table_options = inspector.get_table_options(table.name) if dialect_name == "mysql" else {}
    return {
        "columns": {c["name"]: {"type": _type_contract(c["type"], dialect_name), "nullable": c["nullable"]} for c in columns},
        "pk": (pk.get("name"), tuple(pk.get("constrained_columns") or ())),
        "foreign_keys": sorted((f.get("name"), tuple(f.get("constrained_columns") or ()), f.get("referred_table"), tuple(f.get("referred_columns") or ()), (f.get("options") or {}).get("ondelete"), (f.get("options") or {}).get("onupdate"), local_reference(f)) for f in foreign_keys),
        "uniques": sorted((u.get("name"), tuple(u.get("column_names") or ())) for u in uniques),
        "indexes": sorted((i.get("name"), tuple(i.get("column_names") or ()), bool(i.get("unique"))) for i in indexes),
        "index_options": index_options,
        "checks": sorted((c.get("name"), _check_contract(c.get("sqltext", ""))) for c in inspector.get_check_constraints(table.name)),
        **({"mysql": {"engine": table_options.get("mysql_engine"), "charset": table_options.get("mysql_default charset") or table_options.get("mysql_charset"), "collation": table_options.get("mysql_collate")}} if dialect_name == "mysql" else {}),
    }


def inspect_teaching_schema(connection) -> SchemaReport:
    """Compare only explicit B1 declarations; no DDL, repair or fake empty data."""
    dialect_name = connection.dialect.name
    if dialect_name not in {"mysql", "sqlite"}:
        return SchemaReport(dialect_name, (), (SchemaIssue("b1", "dialect", "unsupported dialect"),), None, None, False, False)
    inspector = inspect(connection)
    existing_names = set(inspector.get_table_names())
    missing = []
    issues = []
    for table in b1_tables():
        if table.name not in existing_names:
            missing.append(table.name)
            continue
        expected = _table_contract(table, dialect_name)
        actual = _existing_contract(inspector, table, dialect_name)
        if dialect_name != "mysql": expected.pop("mysql")
        for kind, contract in expected.items():
            observed = actual[kind]
            if kind == "pk" and dialect_name == "mysql":
                # MySQL reflection uses None/PRIMARY rather than metadata PK names.
                contract = (observed[0], contract[1]) if observed[0] in {None, "PRIMARY"} else contract
            if kind == "columns" and dialect_name == "mysql":
                # Per-column collation inherited from the exact table collation
                # is equivalent; any explicit incompatible override is rejected.
                observed = {name: dict(value) for name, value in observed.items()}
                for name, value in observed.items():
                    key = value["type"]
                    if key[0] == "varchar":
                        normalized = list(key)
                        if normalized[2] == "utf8mb4": normalized[2] = None
                        if normalized[3] == "utf8mb4_bin": normalized[3] = None
                        value["type"] = tuple(normalized)
            if observed != contract:
                issues.append(SchemaIssue(table.name, kind, "existing shape differs from B1 contract"))
    version = None
    contract_hash = None
    ledger_present = False
    ledger_name = TeachingSchemaVersion.__tablename__
    if ledger_name in existing_names and not any(i.table == ledger_name for i in issues):
        row = connection.execute(text("SELECT component, version, contract_hash, completed_at FROM teaching_schema_versions WHERE component = :component"), {"component": B1_COMPONENT}).mappings().first()
        if row is not None:
            ledger_present = True
            version, contract_hash = row["version"], row["contract_hash"]
            if row["component"] != B1_COMPONENT or version != B1_SCHEMA_VERSION or contract_hash != B1_CONTRACT_HASH or row["completed_at"] is None:
                issues.append(SchemaIssue(ledger_name, "ledger", "B1 ledger version/hash/completion mismatch"))
    return SchemaReport(dialect_name, tuple(missing), tuple(issues), version, contract_hash, ledger_present, dialect_name == "mysql")


def require_teaching_schema(session) -> None:
    report = inspect_teaching_schema(session.connection())
    if report.ready: return
    issues = list(report.issues)
    issues.extend(SchemaIssue(name, "missing", "explicit B1 migration required") for name in report.missing_tables)
    if not report.mysql_verified:
        issues.append(SchemaIssue("b1", "vendor_unverified", "MySQL verification required; SQLite is synthetic evidence only"))
    if not report.ledger_present:
        issues.append(SchemaIssue(TeachingSchemaVersion.__tablename__, "ledger_missing", "verified B1 completion ledger required"))
    code = "teaching_schema_incompatible" if report.issues or not report.mysql_verified else "teaching_schema_missing"
    raise TeachingSchemaError(code, issues)
