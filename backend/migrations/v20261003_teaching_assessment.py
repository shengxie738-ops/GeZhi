"""Explicit additive B2 migration logic. No target/engine creation or CLI.

Requires exact identity and accepted B1. MySQL DDL auto-commits, so verified
partial progress is resumable, not transactionally rolled back. No ALTER/repair.
Actual database migration needs separate authorization; imports do no DDL.
"""
from datetime import datetime, timezone

from sqlalchemy import text

from app.services.teaching.schema import DatabaseIdentity, SchemaIssue, TeachingSchemaError
from app.services.teaching.assessment_schema import B2_COMPONENT, B2_CONTRACT_HASH, B2_SCHEMA_VERSION, _b1_readiness_issues, b2_tables, inspect_assessment_schema
from migrations.v20261003_teaching import MigrationPlan, MigrationReport, _verify_identity


def _plan(connection, expected):
    _verify_identity(connection, expected)
    report = inspect_assessment_schema(connection)
    if not report.b1_ready:
        raise TeachingSchemaError("teaching_schema_incompatible", _b1_readiness_issues(report))
    if report.issues:
        raise TeachingSchemaError("assessment_schema_incompatible", report.issues)
    return MigrationPlan(expected, B2_CONTRACT_HASH, report.missing_tables, not report.ledger_present or bool(report.missing_tables))


def plan_b2_schema(engine, expected_identity: DatabaseIdentity) -> MigrationPlan:
    with engine.connect() as connection:
        return _plan(connection, expected_identity)


def _create_table(connection, table):
    table.create(bind=connection, checkfirst=False)


def _require_compatible(report):
    if not report.b1_ready:
        raise TeachingSchemaError("teaching_schema_incompatible", _b1_readiness_issues(report))
    if report.issues:
        raise TeachingSchemaError("assessment_schema_incompatible", report.issues)


def apply_b2_schema(engine, expected_identity: DatabaseIdentity, *, contract_hash: str) -> MigrationReport:
    if contract_hash != B2_CONTRACT_HASH:
        raise TeachingSchemaError("assessment_contract_hash_mismatch", (SchemaIssue("b2", "contract_hash", "exact reviewed B2 contract hash required"),))
    created = []
    with engine.connect() as connection:
        plan = _plan(connection, expected_identity)
        for table in b2_tables():
            if table.name not in plan.missing_tables: continue
            _verify_identity(connection, expected_identity)
            before = inspect_assessment_schema(connection)
            _require_compatible(before)
            if table.name not in before.missing_tables: continue
            _create_table(connection, table)
            created.append(table.name)
            after = inspect_assessment_schema(connection)
            _require_compatible(after)
            if table.name in after.missing_tables:
                raise TeachingSchemaError("assessment_schema_step_failed", (SchemaIssue(table.name, "missing", "created table did not verify"),))
        _verify_identity(connection, expected_identity)
        verified = inspect_assessment_schema(connection)
        _require_compatible(verified)
        if verified.missing_tables:
            raise TeachingSchemaError("assessment_schema_incompatible", tuple(SchemaIssue(name, "missing", "full B2 verification required") for name in verified.missing_tables))
        if not verified.ledger_present:
            completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            connection.execute(text("INSERT INTO teaching_schema_versions (component, version, contract_hash, completed_at) VALUES (:component, :version, :contract_hash, :completed_at)"), {"component": B2_COMPONENT, "version": B2_SCHEMA_VERSION, "contract_hash": B2_CONTRACT_HASH, "completed_at": completed_at})
            connection.commit()
        final = inspect_assessment_schema(connection)
        if not final.ready:
            raise TeachingSchemaError("assessment_schema_completion_failed", final.issues or _b1_readiness_issues(final) or (SchemaIssue("b2", "completion", "completion ledger did not verify"),))
    return MigrationReport(expected_identity, B2_CONTRACT_HASH, tuple(created), True)
