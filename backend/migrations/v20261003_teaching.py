"""Explicit identity-checked, additive B1 preparation. Never run on import.

MySQL DDL auto-commits: successful steps are resumable, not whole-migration
rollback. No existing table is altered, dropped, repaired or backfilled.
"""
import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import sys

from sqlalchemy import create_engine, text

from app.services.teaching.schema import B1_COMPONENT, B1_CONTRACT_HASH, B1_SCHEMA_VERSION, DatabaseIdentity, SchemaIssue, TeachingSchemaError, b1_tables, inspect_teaching_schema


@dataclass(frozen=True)
class MigrationPlan:
    identity: DatabaseIdentity
    contract_hash: str
    missing_tables: tuple[str, ...]
    completion_required: bool


@dataclass(frozen=True)
class MigrationReport:
    identity: DatabaseIdentity
    contract_hash: str
    created_tables: tuple[str, ...]
    completed: bool


def _verify_identity(connection, expected):
    if not isinstance(expected, DatabaseIdentity):
        raise TeachingSchemaError("teaching_identity_mismatch", (SchemaIssue("database", "identity", "complete DatabaseIdentity required"),))
    if connection.dialect.name != "mysql":
        raise TeachingSchemaError("teaching_identity_mismatch", (SchemaIssue("database", "identity", "explicit preparation requires MySQL"),))
    row = connection.execute(text("SELECT DATABASE() AS schema_name, @@server_uuid AS server_uuid, @@datadir AS datadir, @@socket AS socket, @@skip_networking AS skip_networking")).mappings().first()
    issues = []
    if row is None:
        issues.append(SchemaIssue("database", "identity", "live identity unavailable"))
    else:
        for field in ("schema_name", "server_uuid", "datadir", "socket"):
            if row.get(field) != getattr(expected, field):
                issues.append(SchemaIssue("database", "identity", f"live {field} differs from approved manifest"))
        if str(row.get("skip_networking")).upper() not in {"1", "ON"}:
            issues.append(SchemaIssue("database", "identity", "skip_networking must be enabled"))
    if issues:
        raise TeachingSchemaError("teaching_identity_mismatch", issues)


def _plan(connection, expected):
    _verify_identity(connection, expected)
    report = inspect_teaching_schema(connection)
    if report.issues:
        raise TeachingSchemaError("teaching_schema_incompatible", report.issues)
    return MigrationPlan(expected, B1_CONTRACT_HASH, report.missing_tables, not report.ledger_present or bool(report.missing_tables))


def plan_b1_schema(engine, expected_identity: DatabaseIdentity) -> MigrationPlan:
    with engine.connect() as connection:
        return _plan(connection, expected_identity)


def _create_table(connection, table):
    table.create(bind=connection, checkfirst=False)


def apply_b1_schema(engine, expected_identity: DatabaseIdentity, *, contract_hash: str) -> MigrationReport:
    if contract_hash != B1_CONTRACT_HASH:
        raise TeachingSchemaError("teaching_contract_hash_mismatch", (SchemaIssue("b1", "contract_hash", "exact reviewed B1 contract hash required"),))
    created = []
    with engine.connect() as connection:
        # Apply independently verifies identity and every existing target shape;
        # a previously returned plan is never an authorization/shape shortcut.
        plan = _plan(connection, expected_identity)
        for table in b1_tables():
            if table.name not in plan.missing_tables:
                continue
            _verify_identity(connection, expected_identity)
            before = inspect_teaching_schema(connection)
            if before.issues:
                raise TeachingSchemaError("teaching_schema_incompatible", before.issues)
            if table.name not in before.missing_tables:
                continue  # another correct additive step is already visible
            _create_table(connection, table)
            created.append(table.name)
            after = inspect_teaching_schema(connection)
            if after.issues or table.name in after.missing_tables:
                raise TeachingSchemaError("teaching_schema_step_failed", after.issues or (SchemaIssue(table.name, "missing", "created table did not verify"),))
        _verify_identity(connection, expected_identity)
        verified = inspect_teaching_schema(connection)
        if verified.issues or verified.missing_tables:
            raise TeachingSchemaError("teaching_schema_incompatible", verified.issues + tuple(SchemaIssue(name, "missing", "full B1 verification required") for name in verified.missing_tables))
        if not verified.ledger_present:
            completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            connection.execute(text("INSERT INTO teaching_schema_versions (component, version, contract_hash, completed_at) VALUES (:component, :version, :contract_hash, :completed_at)"), {"component": B1_COMPONENT, "version": B1_SCHEMA_VERSION, "contract_hash": B1_CONTRACT_HASH, "completed_at": completed_at})
            connection.commit()
        final = inspect_teaching_schema(connection)
        if not final.ready:
            raise TeachingSchemaError("teaching_schema_completion_failed", final.issues or (SchemaIssue("b1", "completion", "completion ledger did not verify"),))
    return MigrationReport(expected_identity, B1_CONTRACT_HASH, tuple(created), True)


def build_argument_parser():
    parser = argparse.ArgumentParser(description="Plan explicit additive B1 schema; applying requires exact reviewed identity/hash")
    parser.add_argument("--url", required=True, help="explicit synthetic/approved MySQL URL; never read from settings")
    parser.add_argument("--schema-name", required=True)
    parser.add_argument("--server-uuid", required=True)
    parser.add_argument("--datadir", required=True)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--apply", action="store_true", help="explicitly apply missing B1 tables")
    parser.add_argument("--contract-hash", default=None)
    return parser


def main(argv=None):
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    if args.apply and not args.contract_hash:
        parser.error("--apply requires --contract-hash")
    expected = DatabaseIdentity(args.schema_name, args.server_uuid, args.datadir, args.socket)
    engine = create_engine(args.url, connect_args={"unix_socket": expected.socket})
    try:
        result = apply_b1_schema(engine, expected, contract_hash=args.contract_hash) if args.apply else plan_b1_schema(engine, expected)
        print(json.dumps(asdict(result), sort_keys=True))
        return 0
    except TeachingSchemaError as exc:
        print(json.dumps({"code": exc.code, "issues": [asdict(i) for i in exc.issues]}, sort_keys=True), file=sys.stderr)
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
