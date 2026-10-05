"""Explicit additive preparation/check contract, with no executable DDL.

Import and calls only compare supplied observations and return a preparation plan.
This is not a database installer. A separately authorized, identity-checked real
MySQL preparation must verify every existing target table, create only missing
additive tables, then record the exact version/hash after complete inspection.
No existing tables, old drafts, deployment settings or ledger rows are modified.
MySQL DDL is not promised to roll back atomically; retries must re-inspect shapes.
"""
from dataclasses import dataclass

from app.services.teacher_work.schema_v1 import TEACHER_WORK_COMPONENT, TEACHER_WORK_CONTRACT_HASH, TEACHER_WORK_SCHEMA_VERSION, inspect_teacher_work_schema


@dataclass(frozen=True)
class SchemaPreparation:
    component: str
    version: int
    contract_hash: str
    missing_tables: tuple[str, ...]
    completion_ledger_required: bool
    additive_only: bool = True
    executable: bool = False


def prepare_teacher_work_schema(observation: dict, *, contract_hash: str) -> SchemaPreparation:
    """Only propose missing additive tables; a plan grants no apply authority."""
    if contract_hash != TEACHER_WORK_CONTRACT_HASH:
        raise ValueError("exact reviewed teacher Work contract hash required")
    report = inspect_teacher_work_schema(observation)
    if "mysql_schema_required" in report.reasons or "schema_observation_required" in report.reasons or "internal_contract_changed" in report.reasons or report.incompatible_tables:
        raise ValueError("teacher Work preparation requires compatible supplied MySQL observations")
    # Existing incompatible completion ledgers cannot be overwritten or repaired.
    if report.ledger_present and not report.ledger_valid:
        raise ValueError("existing teacher Work ledger is malformed or incompatible")
    return SchemaPreparation(TEACHER_WORK_COMPONENT, TEACHER_WORK_SCHEMA_VERSION, TEACHER_WORK_CONTRACT_HASH, report.missing_tables, not report.ready)


def check_teacher_work_schema(observation: dict | None):
    return inspect_teacher_work_schema(observation)
