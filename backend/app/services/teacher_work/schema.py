"""Pure, read-only comparison of explicitly supplied Teacher Work observations.

This module never opens a connection, imports ORM metadata or probes a database.
A production inspector must supply exact physical column/constraint observations
and the completion-ledger version/hash. Synthetic inputs prove this comparison
only, and never certify actual schema preparation or transaction safety.
"""
from dataclasses import dataclass

from app.services.teacher_work.types import canonical_digest


TEACHER_WORK_COMPONENT = "teacher_work"
TEACHER_WORK_SCHEMA_VERSION = 1
OPTIONS = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_bin"}


def _columns(required: dict[str, str], optional: dict[str, str] | None = None) -> dict:
    return {**{name: {"type": kind, "nullable": False} for name, kind in required.items()},
            **{name: {"type": kind, "nullable": True} for name, kind in (optional or {}).items()}}


def _table(columns: dict, primary_key: tuple[str, ...], *, unique: tuple = (), foreign_keys: dict | None = None, checks: dict | None = None) -> dict:
    return {"columns": columns, "primary_key": primary_key, "unique": unique,
            "foreign_keys": foreign_keys or {}, "checks": checks or {}, "options": dict(OPTIONS)}


TEACHER_WORK_SCHEMA_CONTRACT = {
    "component": TEACHER_WORK_COMPONENT,
    "version": TEACHER_WORK_SCHEMA_VERSION,
    "tables": {
        "teacher_work_tasks": _table(_columns({
            "task_id": "varchar(36)", "owner_subject": "varchar(255)", "owner_storage_id": "varchar(36)",
            "title": "varchar(200)", "topic": "varchar(200)", "audience": "varchar(200)",
            "duration_minutes": "integer", "target_slide_count": "integer", "lesson_draft_id": "varchar(255)",
            "input_revision": "integer", "working_revision": "integer", "skill_refs": "json", "plugin_ids": "json", "reference_ids": "json",
            "created_at": "datetime(6)", "updated_at": "datetime(6)",
        }, {"institution_id": "varchar(64)", "offering_id": "varchar(36)", "current_outline_id": "varchar(36)", "latest_version_id": "varchar(36)",
            "create_idempotency_key": "varbinary(512)", "create_request_digest": "varchar(64)"}),
            ("task_id",), unique=(("owner_subject", "lesson_draft_id"), ("owner_subject", "create_idempotency_key")), checks={
                "ck_tw_task_create_receipt": "(create_idempotency_key IS NULL AND create_request_digest IS NULL) OR (create_idempotency_key IS NOT NULL AND create_request_digest IS NOT NULL)",
                "ck_tw_task_revisions": "input_revision >= 1 AND working_revision >= 1",
                "ck_tw_task_duration": "duration_minutes >= 1 AND duration_minutes <= 600",
                "ck_tw_task_slides": "target_slide_count >= 6 AND target_slide_count <= 12",
                "ck_tw_task_scope": "(institution_id IS NULL AND offering_id IS NULL) OR (institution_id IS NOT NULL AND offering_id IS NOT NULL)",
            }),
        "teacher_work_runs": _table(_columns({
            "run_id": "varchar(36)", "owner": "varchar(255)", "task_id": "varchar(36)", "kind": "varchar(32)",
            "input_revision": "integer", "idempotency_key": "varchar(128)", "request_digest": "varchar(64)", "stage": "varchar(32)",
            "attempt": "integer", "provider_call_count": "integer", "deadline": "datetime(6)",
        }, {"skill_ref": "varchar(64)", "outline_revision": "integer", "cancelled_at": "datetime(6)", "error_code": "varchar(64)", "result_version_id": "varchar(36)"}),
            ("run_id",), unique=(("owner", "task_id", "kind", "idempotency_key"),), foreign_keys={"task_id": "teacher_work_tasks.task_id"}, checks={
                "ck_tw_run_revisions": "input_revision >= 1 AND (outline_revision IS NULL OR outline_revision >= 1)",
                "ck_tw_run_budget": "attempt >= 1 AND attempt <= 2 AND provider_call_count >= 0 AND provider_call_count <= 3",
                "ck_tw_run_kind": "kind IN ('chat','outline','package','revise','reference_search')",
            }),
        "teacher_work_messages": _table(_columns({
            "message_id": "varchar(36)", "task_id": "varchar(36)", "owner": "varchar(255)", "role": "varchar(16)",
            "plain_text": "mediumtext", "result_refs": "json", "created_at": "datetime(6)",
        }, {"client_message_key": "varchar(128)", "run_id": "varchar(36)"}), ("message_id",), unique=(("task_id", "client_message_key"),),
            foreign_keys={"task_id": "teacher_work_tasks.task_id", "run_id": "teacher_work_runs.run_id"},
            checks={"ck_tw_message_role": "role IN ('user','assistant','tool')"}),
        "teacher_work_evidence_snapshots": _table(_columns({
            "evidence_id": "varchar(36)", "task_id": "varchar(36)", "name": "varchar(200)", "excerpt": "text",
            "resource_content_digest": "varchar(64)", "acquired_at": "datetime(6)", "evidence_type": "varchar(16)",
        }, {"resource_id": "varchar(255)", "ref_id": "varchar(36)", "page": "integer", "external_id": "varchar(255)"}), ("evidence_id",),
            foreign_keys={"task_id": "teacher_work_tasks.task_id"}, checks={
                "ck_tw_evidence_type": "evidence_type IN ('courseware','reference')", "ck_tw_evidence_page": "page IS NULL OR page >= 1",
            }),
        "teacher_work_outline_snapshots": _table(_columns({
            "outline_id": "varchar(36)", "task_id": "varchar(36)", "input_revision": "integer", "outline_revision": "integer",
            "lesson": "json", "slides": "json", "source_digest": "varchar(64)", "outline_digest": "varchar(64)", "skill_versions": "json", "created_at": "datetime(6)",
        }), ("outline_id",), unique=(("task_id", "outline_revision"),), foreign_keys={"task_id": "teacher_work_tasks.task_id"},
            checks={"ck_tw_outline_revisions": "input_revision >= 1 AND outline_revision >= 1"}),
        "teacher_work_outline_approvals": _table(_columns({
            "approval_id": "varchar(36)", "owner": "varchar(255)", "task_id": "varchar(36)", "outline_id": "varchar(36)",
            "input_revision": "integer", "outline_revision": "integer", "outline_digest": "varchar(64)", "source_digest": "varchar(64)", "confirmed_at": "datetime(6)",
        }), ("approval_id",), foreign_keys={"task_id": "teacher_work_tasks.task_id", "outline_id": "teacher_work_outline_snapshots.outline_id"},
            checks={"ck_tw_approval_revisions": "input_revision >= 1 AND outline_revision >= 1"}),
        "teacher_work_package_versions": _table(_columns({
            "version_id": "varchar(36)", "task_id": "varchar(36)", "version_no": "integer", "run_id": "varchar(36)",
            "lesson": "json", "slides": "json", "source_snapshots": "json", "content_digest": "varchar(64)", "model_id": "varchar(200)",
            "skill_versions": "json", "exporter_versions": "json", "template_version": "varchar(200)", "created_at": "datetime(6)",
        }, {"base_version_id": "varchar(36)"}), ("version_id",), unique=(("task_id", "version_no"), ("run_id",)),
            foreign_keys={"task_id": "teacher_work_tasks.task_id", "base_version_id": "teacher_work_package_versions.version_id", "run_id": "teacher_work_runs.run_id"},
            checks={"ck_tw_version_number": "version_no >= 1"}),
        "teacher_work_artifacts": _table(_columns({
            "artifact_id": "varchar(36)", "version_id": "varchar(36)", "kind": "varchar(4)", "state": "varchar(16)",
            "download_name": "varchar(200)", "mime": "varchar(128)", "byte_size": "integer", "exporter_version": "varchar(200)",
        }, {"storage_key": "varchar(255)", "sha256": "varchar(64)", "validation_summary": "json", "error_code": "varchar(64)"}), ("artifact_id",), unique=(("version_id", "kind"),),
            foreign_keys={"version_id": "teacher_work_package_versions.version_id"}, checks={
                "ck_tw_artifact_kind": "kind IN ('pptx','docx')",
                "ck_tw_artifact_state": "state IN ('PENDING','BUILDING','VALIDATING','READY','FAILED')",
                "ck_tw_artifact_size": "byte_size >= 0 AND byte_size <= 10485760",
            }),
        "teacher_work_preview_states": _table(_columns({
            "version_id": "varchar(36)", "artifact_kind": "varchar(4)", "kind": "varchar(16)", "state": "varchar(16)", "source_content_digest": "varchar(64)",
        }, {"source_file_digest": "varchar(64)", "error_code": "varchar(64)"}), ("version_id", "artifact_kind", "kind"), unique=(("version_id", "artifact_kind", "kind"),),
            foreign_keys={"version_id": "teacher_work_package_versions.version_id"}, checks={
                "ck_tw_preview_kind": "artifact_kind IN ('pptx','docx') AND kind IN ('structural','rendered')",
                "ck_tw_preview_state": "state IN ('PENDING','READY','FAILED','UNSUPPORTED')",
                "ck_tw_rendered_unsupported": "kind <> 'rendered' OR state = 'UNSUPPORTED'",
            }),
        "teacher_work_version_reviews": _table(_columns({
            "review_id": "varchar(36)", "task_id": "varchar(36)", "version_id": "varchar(36)", "owner": "varchar(255)",
            "content_digest": "varchar(64)", "pptx_sha256": "varchar(64)", "docx_sha256": "varchar(64)", "reviewed_at": "datetime(6)",
        }), ("review_id",), foreign_keys={"task_id": "teacher_work_tasks.task_id", "version_id": "teacher_work_package_versions.version_id"}),
        "teacher_work_catalog_selections": _table(_columns({"owner": "varchar(255)", "catalog_revision": "integer", "plugin_ids": "json"}), ("owner",),
            checks={"ck_tw_catalog_revision": "catalog_revision >= 1"}),
        "teacher_work_owner_run_leases": _table(_columns({"owner": "varchar(255)", "revision": "integer"},
            {"active_run_id": "varchar(36)", "process_instance": "varchar(36)", "expires_at": "datetime(6)"}), ("owner",), foreign_keys={"active_run_id": "teacher_work_runs.run_id"},
            checks={"ck_tw_lease_revision": "revision >= 1"}),
        "teacher_work_schema_versions": _table(_columns({"component": "varchar(32)", "version": "integer", "contract_hash": "varchar(64)", "completed_at": "datetime(6)"}), ("component",),
            checks={"ck_tw_schema_version": "version >= 1"}),
    },
}
TEACHER_WORK_CONTRACT_HASH = canonical_digest(TEACHER_WORK_SCHEMA_CONTRACT)


@dataclass(frozen=True)
class SchemaReport:
    ready: bool
    missing_tables: tuple[str, ...]
    incompatible_tables: tuple[str, ...]
    reasons: tuple[str, ...]
    version: int | None
    contract_hash: str | None
    ledger_present: bool = False
    ledger_valid: bool = False


def inspect_teacher_work_schema(observation: dict | None) -> SchemaReport:
    """Compare supplied physical/ledger facts without reading or changing state."""
    expected = TEACHER_WORK_SCHEMA_CONTRACT["tables"]
    if observation is None or type(observation) is not dict:
        return SchemaReport(False, tuple(expected), (), ("schema_observation_required",), None, None)
    reasons = []
    if observation.get("dialect") != "mysql":
        reasons.append("mysql_schema_required")
    if canonical_digest(TEACHER_WORK_SCHEMA_CONTRACT) != TEACHER_WORK_CONTRACT_HASH:
        reasons.append("internal_contract_changed")
    tables = observation.get("tables")
    if type(tables) is not dict:
        tables = {}
    missing = tuple(name for name in expected if name not in tables)
    incompatible = []
    for name, shape in expected.items():
        if name not in tables:
            continue
        try:
            same = canonical_digest(tables[name]) == canonical_digest(shape)
        except (TypeError, ValueError):
            same = False
        if not same:
            incompatible.append(name)
    if missing:
        reasons.append("schema_tables_missing")
    if incompatible:
        reasons.append("schema_shape_incompatible")
    version = observation.get("version")
    if type(version) is not int or version != TEACHER_WORK_SCHEMA_VERSION:
        reasons.append("schema_version_unverified")
    contract_hash = observation.get("contract_hash")
    if type(contract_hash) is not str or contract_hash != TEACHER_WORK_CONTRACT_HASH:
        reasons.append("schema_hash_unverified")
    ledger_present = "version" in observation or "contract_hash" in observation
    ledger_valid = (ledger_present and type(version) is int and version == TEACHER_WORK_SCHEMA_VERSION
                    and type(contract_hash) is str and contract_hash == TEACHER_WORK_CONTRACT_HASH)
    return SchemaReport(not reasons, missing, tuple(incompatible), tuple(reasons), version if type(version) is int else None, contract_hash if type(contract_hash) is str else None, ledger_present, ledger_valid)


def require_teacher_work_schema(observation: dict | None) -> None:
    report = inspect_teacher_work_schema(observation)
    if not report.ready:
        raise ValueError("teacher_work_schema_unverified: " + ",".join(report.reasons))
