"""Read-only explicit B2 physical-contract inspection with supplied connection.

B1 readiness is required independently. SQLite remains vendor-unverified.
No settings, engine, session, startup, repair or capability activation lives here.
"""
from dataclasses import dataclass
from hashlib import sha256
import json

from sqlalchemy import inspect, text

from app.models.teaching_assessment import Assignment, AssignmentDraftPrivate, AssignmentVersion, PrivateSpec, ReleasePreview, Release, ReleaseRecipient, Submission, SubmissionHead, AssessmentEvent
from app.models.teaching_schema import TeachingSchemaVersion
from app.services.teaching.schema import SchemaIssue, SchemaReport, TeachingSchemaError, _existing_contract, _table_contract, inspect_teaching_schema

B2_COMPONENT = "b2"
B2_SCHEMA_VERSION = 1


def b2_tables():
    """The ten B2 tables only, explicitly ordered by parent dependencies."""
    return (
        Assignment.__table__, AssignmentDraftPrivate.__table__, AssignmentVersion.__table__, PrivateSpec.__table__,
        ReleasePreview.__table__, Release.__table__, ReleaseRecipient.__table__, Submission.__table__,
        SubmissionHead.__table__, AssessmentEvent.__table__,
    )


B2_CONTRACT_HASH = sha256(json.dumps({
    "component": B2_COMPONENT, "version": B2_SCHEMA_VERSION,
    "tables": {table.name: _table_contract(table, "mysql") for table in b2_tables()},
}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class AssessmentSchemaReport:
    dialect: str
    missing_tables: tuple[str, ...]
    issues: tuple[SchemaIssue, ...]
    version: int | None
    contract_hash: str | None
    ledger_present: bool
    mysql_verified: bool
    b1_report: SchemaReport

    @property
    def shape_valid(self):
        return not self.missing_tables and not self.issues

    @property
    def b1_ready(self):
        return self.b1_report.ready

    @property
    def ready(self):
        return (self.shape_valid and self.mysql_verified and self.b1_ready and self.ledger_present
                and self.version == B2_SCHEMA_VERSION and self.contract_hash == B2_CONTRACT_HASH)


def inspect_assessment_schema(connection) -> AssessmentSchemaReport:
    """Inspect only declared shape/ledgers; never create, alter or repair tables."""
    b1_report = inspect_teaching_schema(connection)
    dialect_name = connection.dialect.name
    if dialect_name not in {"mysql", "sqlite"}:
        return AssessmentSchemaReport(dialect_name, (), (SchemaIssue("b2", "dialect", "unsupported dialect"),), None, None, False, False, b1_report)
    inspector = inspect(connection)
    existing_names = set(inspector.get_table_names())
    missing, issues = [], []
    for table in b2_tables():
        if table.name not in existing_names:
            missing.append(table.name)
            continue
        expected = _table_contract(table, dialect_name)
        actual = _existing_contract(inspector, table, dialect_name)
        if dialect_name != "mysql": expected.pop("mysql")
        for kind, contract in expected.items():
            observed = actual[kind]
            # Exactly the existing B1 physical reflection equivalences; no new
            # suppression of type, index, FK, check, schema or collation changes.
            if kind == "pk" and dialect_name == "mysql":
                contract = (observed[0], contract[1]) if observed[0] in {None, "PRIMARY"} else contract
            if kind == "columns" and dialect_name == "mysql":
                observed = {name: dict(value) for name, value in observed.items()}
                for value in observed.values():
                    key = value["type"]
                    if key[0] == "varchar":
                        normalized = list(key)
                        if normalized[2] == "utf8mb4": normalized[2] = None
                        if normalized[3] == "utf8mb4_bin": normalized[3] = None
                        value["type"] = tuple(normalized)
            if observed != contract:
                issues.append(SchemaIssue(table.name, kind, "existing shape differs from B2 contract"))
    version, contract_hash, ledger_present = None, None, False
    ledger_name = TeachingSchemaVersion.__tablename__
    # Reuse B1's independent ledger shape verdict, never query a malformed one.
    ledger_valid = ledger_name in existing_names and not any(issue.table == ledger_name for issue in b1_report.issues)
    if ledger_valid:
        row = connection.execute(text("SELECT component, version, contract_hash, completed_at FROM teaching_schema_versions WHERE component = :component"), {"component": B2_COMPONENT}).mappings().first()
        if row is not None:
            ledger_present = True
            version, contract_hash = row["version"], row["contract_hash"]
            if row["component"] != B2_COMPONENT or version != B2_SCHEMA_VERSION or contract_hash != B2_CONTRACT_HASH or row["completed_at"] is None:
                issues.append(SchemaIssue(ledger_name, "ledger", "B2 ledger version/hash/completion mismatch"))
    return AssessmentSchemaReport(dialect_name, tuple(missing), tuple(issues), version, contract_hash, ledger_present, dialect_name == "mysql", b1_report)


def _b1_readiness_issues(report):
    """Explain existing B1 verdict without changing its readiness semantics."""
    if report.b1_ready: return ()
    b1 = report.b1_report
    issues = list(b1.issues)
    issues.extend(SchemaIssue(name, "missing", "accepted B1 migration required before B2") for name in b1.missing_tables)
    if not b1.mysql_verified:
        issues.append(SchemaIssue("b1", "vendor_unverified", "MySQL verification required; SQLite is synthetic evidence only"))
    if not b1.ledger_present:
        issues.append(SchemaIssue(TeachingSchemaVersion.__tablename__, "b1_ledger_missing", "verified B1 completion ledger required before B2"))
    return tuple(issues) or (SchemaIssue("b1", "readiness", "accepted B1 readiness required before B2"),)


def require_assessment_schema(session) -> None:
    report = inspect_assessment_schema(session.connection())
    if report.ready: return
    issues = list(report.issues) + list(_b1_readiness_issues(report))
    issues.extend(SchemaIssue(name, "missing", "explicit B2 migration required") for name in report.missing_tables)
    if not report.mysql_verified:
        issues.append(SchemaIssue("b2", "vendor_unverified", "MySQL verification required; SQLite is synthetic evidence only"))
    if not report.ledger_present:
        issues.append(SchemaIssue(TeachingSchemaVersion.__tablename__, "b2_ledger_missing", "verified B2 completion ledger required"))
    code = "assessment_schema_incompatible" if report.issues or not report.b1_ready or not report.mysql_verified else "assessment_schema_missing"
    raise TeachingSchemaError(code, issues)
