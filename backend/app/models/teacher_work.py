"""Dedicated additive Teacher Work declarations, never startup DDL.

An isolated metadata registry avoids core.database's settings/engine side effects.
Append-only content and READY bytes are also enforced by the future repository;
these declarations alone do not establish transactions or runtime immutability.
"""
from uuid import uuid4

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import DATETIME, MEDIUMTEXT, VARBINARY
from sqlalchemy.orm import declarative_base


TeacherWorkBase = declarative_base()
UTC_DATETIME = DateTime(timezone=True).with_variant(DATETIME(fsp=6), "mysql")
TABLE_OPTIONS = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_bin", "info": {"explicit_migration_only": True}}


def _new_uuid() -> str:
    return str(uuid4())


class WorkTask(TeacherWorkBase):
    __tablename__ = "teacher_work_tasks"
    task_id = Column(String(36), primary_key=True, default=_new_uuid)
    owner_subject = Column(String(255), nullable=False)
    owner_storage_id = Column(String(36), nullable=False)
    institution_id = Column(String(64), nullable=True)
    offering_id = Column(String(36), nullable=True)
    title = Column(String(200), nullable=False)
    topic = Column(String(200), nullable=False)
    audience = Column(String(200), nullable=False)
    duration_minutes = Column(Integer, nullable=False, default=45)
    target_slide_count = Column(Integer, nullable=False, default=8)
    lesson_draft_id = Column(String(255), nullable=False)
    # Exact UTF-8 receipt bytes at the SQL boundary; VARCHAR padding/collation
    # must not collapse Unicode keys or keys differing only in trailing spaces.
    create_idempotency_key = Column(VARBINARY(512), nullable=True)
    create_request_digest = Column(String(64), nullable=True)
    input_revision = Column(Integer, nullable=False, default=1)
    working_revision = Column(Integer, nullable=False, default=1)
    current_outline_id = Column(String(36), nullable=True)
    latest_version_id = Column(String(36), nullable=True)
    skill_refs = Column(JSON, nullable=False)
    plugin_ids = Column(JSON, nullable=False)
    reference_ids = Column(JSON, nullable=False)
    created_at = Column(UTC_DATETIME, nullable=False)
    updated_at = Column(UTC_DATETIME, nullable=False)
    __table_args__ = (
        UniqueConstraint("owner_subject", "lesson_draft_id", name="uq_tw_task_owner_draft"),
        UniqueConstraint("owner_subject", "create_idempotency_key", name="uq_tw_task_owner_create_key"),
        CheckConstraint("(create_idempotency_key IS NULL AND create_request_digest IS NULL) OR (create_idempotency_key IS NOT NULL AND create_request_digest IS NOT NULL)", name="ck_tw_task_create_receipt"),
        CheckConstraint("input_revision >= 1 AND working_revision >= 1", name="ck_tw_task_revisions"),
        CheckConstraint("duration_minutes >= 1 AND duration_minutes <= 600", name="ck_tw_task_duration"),
        CheckConstraint("target_slide_count >= 6 AND target_slide_count <= 12", name="ck_tw_task_slides"),
        CheckConstraint("(institution_id IS NULL AND offering_id IS NULL) OR (institution_id IS NOT NULL AND offering_id IS NOT NULL)", name="ck_tw_task_scope"),
        TABLE_OPTIONS,
    )


class WorkRun(TeacherWorkBase):
    __tablename__ = "teacher_work_runs"
    run_id = Column(String(36), primary_key=True, default=_new_uuid)
    owner = Column(String(255), nullable=False)
    task_id = Column(String(36), ForeignKey("teacher_work_tasks.task_id"), nullable=False)
    kind = Column(String(32), nullable=False)
    skill_ref = Column(String(64), nullable=True)
    input_revision = Column(Integer, nullable=False)
    outline_revision = Column(Integer, nullable=True)
    idempotency_key = Column(String(128), nullable=False)
    request_digest = Column(String(64), nullable=False)
    stage = Column(String(32), nullable=False)
    attempt = Column(Integer, nullable=False, default=1)
    provider_call_count = Column(Integer, nullable=False, default=0)
    deadline = Column(UTC_DATETIME, nullable=False)
    cancelled_at = Column(UTC_DATETIME, nullable=True)
    error_code = Column(String(64), nullable=True)
    result_version_id = Column(String(36), nullable=True)
    __table_args__ = (
        UniqueConstraint("owner", "task_id", "kind", "idempotency_key", name="uq_tw_run_owner_task_kind_key"),
        CheckConstraint("input_revision >= 1 AND (outline_revision IS NULL OR outline_revision >= 1)", name="ck_tw_run_revisions"),
        CheckConstraint("attempt >= 1 AND attempt <= 2 AND provider_call_count >= 0 AND provider_call_count <= 3", name="ck_tw_run_budget"),
        CheckConstraint("kind IN ('chat','outline','package','revise','reference_search')", name="ck_tw_run_kind"),
        TABLE_OPTIONS,
    )


class WorkMessage(TeacherWorkBase):
    __tablename__ = "teacher_work_messages"
    message_id = Column(String(36), primary_key=True, default=_new_uuid)
    task_id = Column(String(36), ForeignKey("teacher_work_tasks.task_id"), nullable=False)
    owner = Column(String(255), nullable=False)
    client_message_key = Column(String(128), nullable=True)
    role = Column(String(16), nullable=False)
    plain_text = Column(Text().with_variant(MEDIUMTEXT(), "mysql"), nullable=False)
    run_id = Column(String(36), ForeignKey("teacher_work_runs.run_id"), nullable=True)
    result_refs = Column(JSON, nullable=False)
    created_at = Column(UTC_DATETIME, nullable=False)
    __table_args__ = (
        UniqueConstraint("task_id", "client_message_key", name="uq_tw_message_task_client_key"),
        CheckConstraint("role IN ('user','assistant','tool')", name="ck_tw_message_role"),
        TABLE_OPTIONS,
    )


class EvidenceSnapshot(TeacherWorkBase):
    __tablename__ = "teacher_work_evidence_snapshots"
    evidence_id = Column(String(36), primary_key=True, default=_new_uuid)
    task_id = Column(String(36), ForeignKey("teacher_work_tasks.task_id"), nullable=False)
    resource_id = Column(String(255), nullable=True)
    ref_id = Column(String(36), nullable=True)
    name = Column(String(200), nullable=False)
    page = Column(Integer, nullable=True)
    external_id = Column(String(255), nullable=True)
    excerpt = Column(Text, nullable=False)
    resource_content_digest = Column(String(64), nullable=False)
    acquired_at = Column(UTC_DATETIME, nullable=False)
    evidence_type = Column(String(16), nullable=False)
    __table_args__ = (
        CheckConstraint("evidence_type IN ('courseware','reference')", name="ck_tw_evidence_type"),
        CheckConstraint("page IS NULL OR page >= 1", name="ck_tw_evidence_page"),
        TABLE_OPTIONS,
    )


class OutlineSnapshot(TeacherWorkBase):
    __tablename__ = "teacher_work_outline_snapshots"
    outline_id = Column(String(36), primary_key=True, default=_new_uuid)
    task_id = Column(String(36), ForeignKey("teacher_work_tasks.task_id"), nullable=False)
    input_revision = Column(Integer, nullable=False)
    outline_revision = Column(Integer, nullable=False)
    lesson = Column(JSON, nullable=False)
    slides = Column(JSON, nullable=False)
    source_digest = Column(String(64), nullable=False)
    outline_digest = Column(String(64), nullable=False)
    skill_versions = Column(JSON, nullable=False)
    created_at = Column(UTC_DATETIME, nullable=False)
    __table_args__ = (
        UniqueConstraint("task_id", "outline_revision", name="uq_tw_outline_task_revision"),
        CheckConstraint("input_revision >= 1 AND outline_revision >= 1", name="ck_tw_outline_revisions"),
        TABLE_OPTIONS,
    )


class OutlineApproval(TeacherWorkBase):
    __tablename__ = "teacher_work_outline_approvals"
    approval_id = Column(String(36), primary_key=True, default=_new_uuid)
    owner = Column(String(255), nullable=False)
    task_id = Column(String(36), ForeignKey("teacher_work_tasks.task_id"), nullable=False)
    outline_id = Column(String(36), ForeignKey("teacher_work_outline_snapshots.outline_id"), nullable=False)
    input_revision = Column(Integer, nullable=False)
    outline_revision = Column(Integer, nullable=False)
    outline_digest = Column(String(64), nullable=False)
    source_digest = Column(String(64), nullable=False)
    confirmed_at = Column(UTC_DATETIME, nullable=False)
    __table_args__ = (CheckConstraint("input_revision >= 1 AND outline_revision >= 1", name="ck_tw_approval_revisions"), TABLE_OPTIONS)


class PackageVersion(TeacherWorkBase):
    __tablename__ = "teacher_work_package_versions"
    version_id = Column(String(36), primary_key=True, default=_new_uuid)
    task_id = Column(String(36), ForeignKey("teacher_work_tasks.task_id"), nullable=False)
    version_no = Column(Integer, nullable=False)
    base_version_id = Column(String(36), ForeignKey("teacher_work_package_versions.version_id"), nullable=True)
    run_id = Column(String(36), ForeignKey("teacher_work_runs.run_id"), nullable=False)
    lesson = Column(JSON, nullable=False)
    slides = Column(JSON, nullable=False)
    source_snapshots = Column(JSON, nullable=False)
    content_digest = Column(String(64), nullable=False)
    model_id = Column(String(200), nullable=False)
    skill_versions = Column(JSON, nullable=False)
    exporter_versions = Column(JSON, nullable=False)
    template_version = Column(String(200), nullable=False)
    created_at = Column(UTC_DATETIME, nullable=False)
    __table_args__ = (
        UniqueConstraint("task_id", "version_no", name="uq_tw_version_task_number"),
        UniqueConstraint("run_id", name="uq_tw_version_run"),
        CheckConstraint("version_no >= 1", name="ck_tw_version_number"),
        TABLE_OPTIONS,
    )


class Artifact(TeacherWorkBase):
    __tablename__ = "teacher_work_artifacts"
    artifact_id = Column(String(36), primary_key=True, default=_new_uuid)
    version_id = Column(String(36), ForeignKey("teacher_work_package_versions.version_id"), nullable=False)
    kind = Column(String(4), nullable=False)
    state = Column(String(16), nullable=False)
    download_name = Column(String(200), nullable=False)
    storage_key = Column(String(255), nullable=True)
    mime = Column(String(128), nullable=False)
    byte_size = Column(Integer, nullable=False, default=0)
    sha256 = Column(String(64), nullable=True)
    exporter_version = Column(String(200), nullable=False)
    validation_summary = Column(JSON, nullable=True)
    error_code = Column(String(64), nullable=True)
    __table_args__ = (
        UniqueConstraint("version_id", "kind", name="uq_tw_artifact_version_kind"),
        CheckConstraint("kind IN ('pptx','docx')", name="ck_tw_artifact_kind"),
        CheckConstraint("state IN ('PENDING','BUILDING','VALIDATING','READY','FAILED')", name="ck_tw_artifact_state"),
        CheckConstraint("byte_size >= 0 AND byte_size <= 10485760", name="ck_tw_artifact_size"),
        TABLE_OPTIONS,
    )


class PreviewState(TeacherWorkBase):
    __tablename__ = "teacher_work_preview_states"
    version_id = Column(String(36), ForeignKey("teacher_work_package_versions.version_id"), primary_key=True)
    artifact_kind = Column(String(4), primary_key=True)
    kind = Column(String(16), primary_key=True)
    state = Column(String(16), nullable=False)
    source_content_digest = Column(String(64), nullable=False)
    source_file_digest = Column(String(64), nullable=True)
    error_code = Column(String(64), nullable=True)
    __table_args__ = (
        UniqueConstraint("version_id", "artifact_kind", "kind", name="uq_tw_preview_version_format_kind"),
        CheckConstraint("artifact_kind IN ('pptx','docx') AND kind IN ('structural','rendered')", name="ck_tw_preview_kind"),
        CheckConstraint("state IN ('PENDING','READY','FAILED','UNSUPPORTED')", name="ck_tw_preview_state"),
        CheckConstraint("kind <> 'rendered' OR state = 'UNSUPPORTED'", name="ck_tw_rendered_unsupported"),
        TABLE_OPTIONS,
    )


class VersionReview(TeacherWorkBase):
    __tablename__ = "teacher_work_version_reviews"
    review_id = Column(String(36), primary_key=True, default=_new_uuid)
    task_id = Column(String(36), ForeignKey("teacher_work_tasks.task_id"), nullable=False)
    version_id = Column(String(36), ForeignKey("teacher_work_package_versions.version_id"), nullable=False)
    owner = Column(String(255), nullable=False)
    content_digest = Column(String(64), nullable=False)
    pptx_sha256 = Column(String(64), nullable=False)
    docx_sha256 = Column(String(64), nullable=False)
    reviewed_at = Column(UTC_DATETIME, nullable=False)
    __table_args__ = (TABLE_OPTIONS,)


class CatalogSelection(TeacherWorkBase):
    __tablename__ = "teacher_work_catalog_selections"
    owner = Column(String(255), primary_key=True)
    catalog_revision = Column(Integer, nullable=False, default=1)
    plugin_ids = Column(JSON, nullable=False)
    __table_args__ = (CheckConstraint("catalog_revision >= 1", name="ck_tw_catalog_revision"), TABLE_OPTIONS)


class OwnerRunLease(TeacherWorkBase):
    __tablename__ = "teacher_work_owner_run_leases"
    owner = Column(String(255), primary_key=True)
    active_run_id = Column(String(36), ForeignKey("teacher_work_runs.run_id"), nullable=True)
    process_instance = Column(String(36), nullable=True)
    expires_at = Column(UTC_DATETIME, nullable=True)
    revision = Column(Integer, nullable=False, default=1)
    __table_args__ = (CheckConstraint("revision >= 1", name="ck_tw_lease_revision"), TABLE_OPTIONS)


class TeacherWorkSchemaVersion(TeacherWorkBase):
    __tablename__ = "teacher_work_schema_versions"
    component = Column(String(32), primary_key=True)
    version = Column(Integer, nullable=False)
    contract_hash = Column(String(64), nullable=False)
    completed_at = Column(UTC_DATETIME, nullable=False)
    __table_args__ = (CheckConstraint("version >= 1", name="ck_tw_schema_version"), TABLE_OPTIONS)
