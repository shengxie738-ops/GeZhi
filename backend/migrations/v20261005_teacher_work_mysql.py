"""Explicit identity/hash-checked fresh Teacher Work v2 preparation only.

Caller supplies an already authorized MySQL connection. No engine, settings,
startup, CLI, v1 upgrade, backfill, ALTER, DROP or resume is provided. MySQL DDL
auto-commits: failure reports attempted/confirmed steps, never atomic rollback.
Any subsequent partial schema requires a separately reviewed recovery design.
"""
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.sql.ddl import CreateTable

from app.services.teacher_work.schema import (
    TEACHER_WORK_COMPONENT, TEACHER_WORK_CONTRACT_HASH, TEACHER_WORK_SCHEMA_CONTRACT,
    TEACHER_WORK_SCHEMA_VERSION,
)
from app.services.teacher_work.schema_mysql import (
    DatabaseIdentity, MysqlSchemaError, MysqlSchemaIssue, observe_teacher_work_mysql,
    teacher_work_mysql_tables,
)
from app.services.teacher_work.types import canonical_digest


@dataclass(frozen=True)
class MysqlMigrationPlan:
    mode: str
    identity: DatabaseIdentity
    contract_hash: str
    tables: tuple[str, ...]


@dataclass(frozen=True)
class MysqlMigrationReport:
    identity: DatabaseIdentity
    contract_hash: str
    attempted_tables: tuple[str, ...]
    confirmed_tables: tuple[str, ...]
    completed: bool
    ledger_written: bool | None
    ledger_commit_state: str = "NOT_ATTEMPTED"


class MysqlMigrationError(MysqlSchemaError):
    def __init__(self, code, issues, *, attempted_tables=(), confirmed_tables=(), failed_table=None, ledger_written=False, ledger_commit_state="NOT_ATTEMPTED"):
        self.attempted_tables, self.confirmed_tables = tuple(attempted_tables), tuple(confirmed_tables)
        self.failed_table, self.ledger_written, self.completed = failed_table, ledger_written, False
        self.ledger_commit_state = ledger_commit_state
        super().__init__(code, issues)


def _fail(code, kind, detail, *, table="teacher_work"):
    raise MysqlMigrationError(code, (MysqlSchemaIssue(table, kind, detail),))


def _hash(contract_hash):
    if type(contract_hash) is not str or contract_hash != TEACHER_WORK_CONTRACT_HASH or canonical_digest(TEACHER_WORK_SCHEMA_CONTRACT) != TEACHER_WORK_CONTRACT_HASH:
        _fail("teacher_work_contract_hash_mismatch", "contract", "exact reviewed unchanged v2 hash required")
    names = tuple(TEACHER_WORK_SCHEMA_CONTRACT["tables"])
    if tuple(t.name for t in teacher_work_mysql_tables()) != names:
        _fail("teacher_work_contract_hash_mismatch", "allowlist", "explicit v2 table allowlist changed")


def _identity(connection, expected):
    if type(expected) is not DatabaseIdentity or getattr(getattr(connection, "dialect", None), "name", None) != "mysql":
        _fail("teacher_work_identity_mismatch", "identity", "complete exact MySQL identity required", table="database")
    try:
        DatabaseIdentity.__post_init__(expected)
        row = connection.execute(text("SELECT DATABASE() AS schema_name, @@server_uuid AS server_uuid, @@datadir AS datadir, @@socket AS socket, @@skip_networking AS skip_networking")).mappings().first()
    except Exception:
        _fail("teacher_work_identity_mismatch", "identity", "live database identity unavailable", table="database")
    if row is None or any(row.get(field) != getattr(expected, field) for field in ("schema_name", "server_uuid", "datadir", "socket")) or str(row.get("skip_networking")).upper() not in {"1", "ON"}:
        _fail("teacher_work_identity_mismatch", "identity", "live database identity differs from approved manifest", table="database")


def _fresh_connection(connection):
    """Refuse prior caller transactions without committing or rolling them back."""
    try: fresh = connection.in_transaction() is False
    except Exception: fresh = False
    if not fresh:
        _fail("teacher_work_fresh_connection_required", "connection", "dedicated connection with no active caller transaction required", table="database")


def _inspect_step(connection, confirmed):
    report = observe_teacher_work_mysql(connection)
    names = tuple(TEACHER_WORK_SCHEMA_CONTRACT["tables"])
    present = tuple(name for name in names if name not in report.missing_tables)
    if report.issues or present != tuple(confirmed) or report.ledger_present:
        _fail("teacher_work_schema_step_incompatible", "shape", "physical shape or fresh-step inventory changed")
    return report


def plan_teacher_work_mysql(connection, expected_identity: DatabaseIdentity, *, contract_hash: str) -> MysqlMigrationPlan:
    _hash(contract_hash)
    _fresh_connection(connection)
    _identity(connection, expected_identity)
    report = observe_teacher_work_mysql(connection)
    if report.ready:
        return MysqlMigrationPlan("exact_v2", expected_identity, TEACHER_WORK_CONTRACT_HASH, ())
    names = tuple(TEACHER_WORK_SCHEMA_CONTRACT["tables"])
    if report.issues or report.missing_tables != names or report.ledger_present:
        _fail("teacher_work_schema_incompatible", "shape", "partial, incompatible, v1 or unledgered existing schema refused")
    return MysqlMigrationPlan("fresh_v2", expected_identity, TEACHER_WORK_CONTRACT_HASH, names)


def apply_teacher_work_mysql(connection, expected_identity: DatabaseIdentity, *, contract_hash: str) -> MysqlMigrationReport:
    """Fresh-only apply; exact fully completed v2 is the sole existing no-op."""
    attempted, confirmed = [], []
    failed_table, ledger_commit_state = None, "NOT_ATTEMPTED"
    try:
        plan = plan_teacher_work_mysql(connection, expected_identity, contract_hash=contract_hash)
        if plan.mode == "exact_v2":
            return MysqlMigrationReport(expected_identity, TEACHER_WORK_CONTRACT_HASH, (), (), True, False)
        for table in teacher_work_mysql_tables():
            _hash(contract_hash)
            _identity(connection, expected_identity)
            _inspect_step(connection, confirmed)
            failed_table = table.name
            attempted.append(table.name)
            connection.execute(CreateTable(table))
            _inspect_step(connection, (*confirmed, table.name))
            confirmed.append(table.name)
            failed_table = None
        _hash(contract_hash)
        _identity(connection, expected_identity)
        verified = _inspect_step(connection, confirmed)
        if not verified.physical_valid:
            _fail("teacher_work_schema_incompatible", "shape", "full physical verification required before ledger")
        failed_table = "teacher_work_schema_versions"
        completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        # An INSERT acknowledgement can be lost even in DBAPI AUTOCOMMIT mode.
        # Once attempted, receipt absence is unknown until commit is acknowledged.
        ledger_commit_state = "UNKNOWN"
        connection.execute(text("INSERT INTO teacher_work_schema_versions (component, version, contract_hash, completed_at) VALUES (:component, :version, :contract_hash, :completed_at)"),
            {"component": TEACHER_WORK_COMPONENT, "version": TEACHER_WORK_SCHEMA_VERSION,
             "contract_hash": TEACHER_WORK_CONTRACT_HASH, "completed_at": completed_at})
        connection.commit()
        ledger_commit_state = "ACKNOWLEDGED"
        final = observe_teacher_work_mysql(connection)
        if not final.ready:
            _fail("teacher_work_schema_completion_failed", "ledger", "completion ledger did not physically verify")
        return MysqlMigrationReport(expected_identity, TEACHER_WORK_CONTRACT_HASH, tuple(attempted), tuple(confirmed), True, True, ledger_commit_state)
    except Exception as exc:
        if isinstance(exc, MysqlMigrationError): code, issues = exc.code, exc.issues
        else: code, issues = "teacher_work_schema_step_failed", (MysqlSchemaIssue(failed_table or "teacher_work", "execution", "explicit MySQL preparation step failed; partial DDL may persist"),)
        ledger_written = {"NOT_ATTEMPTED": False, "UNKNOWN": None, "ACKNOWLEDGED": True}[ledger_commit_state]
        raise MysqlMigrationError(code, issues, attempted_tables=attempted, confirmed_tables=confirmed,
            failed_table=failed_table, ledger_written=ledger_written, ledger_commit_state=ledger_commit_state) from None
