"""One-way Teacher Work v2 preparation descriptions, never executable DDL.

This module only compares supplied schema/data facts. Empty v1 facts do not prove
physical emptiness or quiescence. A later separately authorized inspection/DDL
must preserve unrelated data, recover interrupted nontransactional MySQL DDL and
record the v2 ledger only after complete physical reinspection. Nonempty v1 has
no historical repair/result backfill in this slice and is deliberately refused.
"""
from dataclasses import dataclass
from typing import Literal

from app.services.teacher_work.schema import (
    SchemaReport, TEACHER_WORK_COMPONENT, TEACHER_WORK_CONTRACT_HASH,
    TEACHER_WORK_SCHEMA_CONTRACT, TEACHER_WORK_SCHEMA_VERSION,
    inspect_teacher_work_schema,
)
from app.services.teacher_work.schema_v1 import (
    TEACHER_WORK_CONTRACT_HASH as V1_CONTRACT_HASH,
    TEACHER_WORK_SCHEMA_VERSION as V1_SCHEMA_VERSION,
    inspect_teacher_work_schema as inspect_v1_schema,
)


@dataclass(frozen=True)
class WorkUpgradeDataFacts:
    run_rows: int
    message_rows: int
    active_leases: int

    def __post_init__(self):
        if any(type(value) is not int or value < 0 for value in (self.run_rows, self.message_rows, self.active_leases)):
            raise ValueError("strict nonnegative supplied Work upgrade counts required")


@dataclass(frozen=True)
class SchemaV2Preparation:
    component: str
    mode: Literal["fresh_v2", "empty_v1_upgrade", "exact_v2"]
    from_version: int | None
    from_hash: str | None
    to_version: Literal[2]
    to_hash: str
    missing_tables: tuple[str, ...]
    upgrade_tables: tuple[str, ...]
    required_changes: tuple[str, ...]
    completion_ledger_required: bool
    additive_only: bool
    executable: Literal[False] = False


_EMPTY_V1_CHANGES = (
    "teacher_work_runs: change idempotency_key to exact VARBINARY(512)",
    "teacher_work_runs: add repair_count NOT NULL DEFAULT 0 and cumulative budget check",
    "teacher_work_runs: add four nullable active-call components and all-or-none matching check",
    "teacher_work_messages: change client_message_key to nullable exact VARBINARY(512)",
    "teacher_work_messages: add nullable completion_run_id with run foreign key and unique receipt",
    "teacher_work_messages: add nullable actual result_type and omitted_context without historical defaults",
    "teacher_work_messages: add paired assistant completion metadata check",
    "teacher_work_schema_versions: replace v1 ledger only after full physical v2 reinspection",
)


def _plan(mode, *, from_version, from_hash, missing_tables=(), upgrade_tables=(),
          required_changes=(), completion_ledger_required, additive_only) -> SchemaV2Preparation:
    return SchemaV2Preparation(component=TEACHER_WORK_COMPONENT, mode=mode,
        from_version=from_version, from_hash=from_hash, to_version=TEACHER_WORK_SCHEMA_VERSION,
        to_hash=TEACHER_WORK_CONTRACT_HASH, missing_tables=missing_tables,
        upgrade_tables=upgrade_tables, required_changes=required_changes,
        completion_ledger_required=completion_ledger_required, additive_only=additive_only)


def prepare_teacher_work_v2_schema(observation: dict, *, target_contract_hash: str,
                                   upgrade_data_facts: WorkUpgradeDataFacts | None = None) -> SchemaV2Preparation:
    """Describe exactly fresh v2, exact v2, or supplied-empty exact v1 upgrade."""
    if type(target_contract_hash) is not str or target_contract_hash != TEACHER_WORK_CONTRACT_HASH:
        raise ValueError("exact reviewed v2 Teacher Work contract hash required")
    if (type(observation) is not dict or observation.get("dialect") != "mysql"
            or type(observation.get("tables")) is not dict):
        raise ValueError("compatible supplied MySQL schema observations required")
    report = inspect_teacher_work_schema(observation)
    if "internal_contract_changed" in report.reasons:
        raise ValueError("reviewed v2 Teacher Work contract changed")
    targets = tuple(TEACHER_WORK_SCHEMA_CONTRACT["tables"])
    present = tuple(name for name in targets if name in observation["tables"])
    if not present:
        if report.ledger_present:
            raise ValueError("fresh v2 cannot replace an existing Work ledger")
        changes = tuple("prepare exact missing table: " + name for name in targets) + (
            "record exact v2 completion ledger only after full physical reinspection",
        )
        return _plan("fresh_v2", from_version=None, from_hash=None, missing_tables=targets,
                     required_changes=changes, completion_ledger_required=True, additive_only=True)
    if report.ready:
        return _plan("exact_v2", from_version=TEACHER_WORK_SCHEMA_VERSION,
                     from_hash=TEACHER_WORK_CONTRACT_HASH, completion_ledger_required=False, additive_only=True)
    old = inspect_v1_schema(observation)
    if not old.ready:
        raise ValueError("partial, mixed or incompatible Work schema/ledger refused")
    if type(upgrade_data_facts) is not WorkUpgradeDataFacts:
        raise ValueError("strict supplied v1 upgrade counts required")
    WorkUpgradeDataFacts.__post_init__(upgrade_data_facts)
    if (upgrade_data_facts.run_rows, upgrade_data_facts.message_rows, upgrade_data_facts.active_leases) != (0, 0, 0):
        raise ValueError("nonempty or active v1 Work upgrade requires a separate migration design")
    return _plan("empty_v1_upgrade", from_version=V1_SCHEMA_VERSION, from_hash=V1_CONTRACT_HASH,
                 upgrade_tables=("teacher_work_runs", "teacher_work_messages"), required_changes=_EMPTY_V1_CHANGES,
                 completion_ledger_required=True, additive_only=False)


def check_teacher_work_v2_schema(observation: dict | None) -> SchemaReport:
    """Compare supplied v2 facts; never perform physical schema inspection."""
    return inspect_teacher_work_schema(observation)
