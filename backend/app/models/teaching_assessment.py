"""Explicit-only B2 declarations. Import registers metadata, never performs DDL.

Historical enrollment/role identifiers are snapshots, not current authority.
Immutable ORM rows reject update/delete; raw SQL/admin protection is not claimed.
The future closed write engine owns mutable-field, receipt-scope and head checks.
"""
from sqlalchemy import BigInteger, Column, ForeignKeyConstraint, JSON, String, event

from app.core.database import Base
from app.models.teaching import _ck, _id, _ix, _pk, _revision, _time, _uq, constraint_name, explicit_table_options


def _lineage_fk(table, parent, columns, referred):
    """Bind every named parent/scope column explicitly, with no cascade actions."""
    return ForeignKeyConstraint(
        columns, [f"{parent}.{name}" for name in referred],
        name=constraint_name("fk", table, parent, "_".join(columns)),
    )


class Assignment(Base):
    __tablename__ = "teaching_assignments"
    id = _id()
    institution_id = Column(String(64), nullable=False)
    offering_id = Column(String(36), nullable=False)
    public_draft = Column(JSON, nullable=False)
    draft_revision = _revision()
    next_version_number = _revision()
    created_by = Column(String(255), nullable=False)
    created_at = _time()
    updated_at = _time()
    __table_args__ = (
        _pk(__tablename__, "id"), _uq(__tablename__, "id", "institution_id", "offering_id"),
        _lineage_fk(__tablename__, "teaching_offerings", ("offering_id", "institution_id"), ("id", "institution_id")),
        _ix(__tablename__, "offering_id", "institution_id"),
        _ix(__tablename__, "offering_id", "created_at", "id"),
        _ck(__tablename__, "draft_revision_positive", "draft_revision >= 1"),
        _ck(__tablename__, "next_version_positive", "next_version_number >= 1"),
        explicit_table_options(),
    )


class AssignmentDraftPrivate(Base):
    __tablename__ = "teaching_assignment_draft_private"
    assignment_id = Column(String(36), nullable=False)
    institution_id = Column(String(64), nullable=False)
    offering_id = Column(String(36), nullable=False)
    private_draft = Column(JSON, nullable=False)
    updated_at = _time()
    __table_args__ = (
        _pk(__tablename__, "assignment_id"),
        _lineage_fk(__tablename__, "teaching_assignments", ("assignment_id", "institution_id", "offering_id"), ("id", "institution_id", "offering_id")),
        _ix(__tablename__, "assignment_id", "institution_id", "offering_id"),
        explicit_table_options(),
    )


class AssignmentVersion(Base):
    __tablename__ = "teaching_assignment_versions"
    id = _id()
    assignment_id = Column(String(36), nullable=False)
    institution_id = Column(String(64), nullable=False)
    offering_id = Column(String(36), nullable=False)
    version_number = Column(BigInteger, nullable=False)
    source_draft_revision = Column(BigInteger, nullable=False)
    public_spec = Column(JSON, nullable=False)
    public_spec_hash = Column(String(64), nullable=False)
    frozen_by = Column(String(255), nullable=False)
    frozen_at = _time()
    __table_args__ = (
        _pk(__tablename__, "id"), _uq(__tablename__, "id", "institution_id", "offering_id", "assignment_id"),
        _uq(__tablename__, "assignment_id", "version_number"),
        _uq(__tablename__, "assignment_id", "source_draft_revision"),
        _lineage_fk(__tablename__, "teaching_assignments", ("assignment_id", "institution_id", "offering_id"), ("id", "institution_id", "offering_id")),
        _ix(__tablename__, "assignment_id", "institution_id", "offering_id"),
        _ck(__tablename__, "version_positive", "version_number >= 1"),
        _ck(__tablename__, "source_draft_positive", "source_draft_revision >= 1"),
        explicit_table_options(),
    )


class PrivateSpec(Base):
    __tablename__ = "teaching_assignment_private_specs"
    version_id = Column(String(36), nullable=False)
    assignment_id = Column(String(36), nullable=False)
    institution_id = Column(String(64), nullable=False)
    offering_id = Column(String(36), nullable=False)
    private_spec = Column(JSON, nullable=False)
    private_spec_hash = Column(String(64), nullable=False)
    __table_args__ = (
        _pk(__tablename__, "version_id"),
        _lineage_fk(__tablename__, "teaching_assignment_versions", ("version_id", "institution_id", "offering_id", "assignment_id"), ("id", "institution_id", "offering_id", "assignment_id")),
        _ix(__tablename__, "version_id", "institution_id", "offering_id", "assignment_id"),
        explicit_table_options(),
    )


class ReleasePreview(Base):
    __tablename__ = "teaching_release_previews"
    id = _id()
    assignment_id = Column(String(36), nullable=False)
    version_id = Column(String(36), nullable=False)
    institution_id = Column(String(64), nullable=False)
    offering_id = Column(String(36), nullable=False)
    actor_id = Column(String(255), nullable=False)
    actor_role_id = Column(String(36), nullable=False)
    actor_role_revision = Column(BigInteger, nullable=False)
    offering_revision = Column(BigInteger, nullable=False)
    roster_revision = Column(BigInteger, nullable=False)
    source_policy_digest = Column(String(64), nullable=False)
    recipient_snapshot = Column(JSON, nullable=False)
    recipient_count = Column(BigInteger, nullable=False)
    recipient_digest = Column(String(64), nullable=False)
    public_spec_hash = Column(String(64), nullable=False)
    due_at = _time(True)
    timezone = Column(String(64), nullable=False)
    late_policy = Column(String(32), nullable=False, default="reject", server_default="reject")
    policy_digest = Column(String(64), nullable=False)
    created_at = _time()
    expires_at = _time()
    __table_args__ = (
        _pk(__tablename__, "id"), _uq(__tablename__, "id", "institution_id", "offering_id", "assignment_id", "version_id"),
        _lineage_fk(__tablename__, "teaching_assignment_versions", ("version_id", "institution_id", "offering_id", "assignment_id"), ("id", "institution_id", "offering_id", "assignment_id")),
        _ix(__tablename__, "version_id", "institution_id", "offering_id", "assignment_id"),
        _ix(__tablename__, "offering_id", "actor_id", "created_at", "id"),
        _ck(__tablename__, "actor_role_revision_positive", "actor_role_revision >= 1"),
        _ck(__tablename__, "offering_revision_positive", "offering_revision >= 1"),
        _ck(__tablename__, "roster_revision_nonnegative", "roster_revision >= 0"),
        _ck(__tablename__, "recipient_count_bounds", "recipient_count >= 1 AND recipient_count <= 1000"),
        _ck(__tablename__, "late_policy", "late_policy = 'reject'"),
        _ck(__tablename__, "timezone_nonempty", "timezone <> ''"),
        _ck(__tablename__, "expiry_strict", "expires_at > created_at"),
        explicit_table_options(),
    )


class Release(Base):
    __tablename__ = "teaching_releases"
    id = _id()
    assignment_id = Column(String(36), nullable=False)
    version_id = Column(String(36), nullable=False)
    institution_id = Column(String(64), nullable=False)
    offering_id = Column(String(36), nullable=False)
    preview_id = Column(String(36), nullable=False)
    public_spec_hash = Column(String(64), nullable=False)
    recipient_count = Column(BigInteger, nullable=False)
    recipient_digest = Column(String(64), nullable=False)
    due_at = _time(True)
    timezone = Column(String(64), nullable=False)
    late_policy = Column(String(32), nullable=False, default="reject", server_default="reject")
    policy_digest = Column(String(64), nullable=False)
    released_by = Column(String(255), nullable=False)
    released_at = _time()
    __table_args__ = (
        _pk(__tablename__, "id"), _uq(__tablename__, "version_id"), _uq(__tablename__, "preview_id"),
        _uq(__tablename__, "id", "institution_id", "offering_id", "version_id"),
        _lineage_fk(__tablename__, "teaching_assignment_versions", ("version_id", "institution_id", "offering_id", "assignment_id"), ("id", "institution_id", "offering_id", "assignment_id")),
        _ix(__tablename__, "version_id", "institution_id", "offering_id", "assignment_id"),
        _lineage_fk(__tablename__, "teaching_release_previews", ("preview_id", "institution_id", "offering_id", "assignment_id", "version_id"), ("id", "institution_id", "offering_id", "assignment_id", "version_id")),
        _ix(__tablename__, "preview_id", "institution_id", "offering_id", "assignment_id", "version_id"),
        _ix(__tablename__, "offering_id", "released_at", "id"),
        _ck(__tablename__, "late_policy", "late_policy = 'reject'"),
        _ck(__tablename__, "recipient_count_bounds", "recipient_count >= 1 AND recipient_count <= 1000"),
        _ck(__tablename__, "timezone_nonempty", "timezone <> ''"),
        explicit_table_options(),
    )


class ReleaseRecipient(Base):
    __tablename__ = "teaching_release_recipients"
    release_id = Column(String(36), nullable=False)
    institution_id = Column(String(64), nullable=False)
    offering_id = Column(String(36), nullable=False)
    version_id = Column(String(36), nullable=False)
    student_id = Column(String(255), nullable=False)
    enrollment_id = Column(String(36), nullable=False)
    enrollment_revision_at_release = Column(BigInteger, nullable=False)
    accepted_policy_digest = Column(String(64), nullable=False)
    __table_args__ = (
        _pk(__tablename__, "release_id", "student_id"),
        _uq(__tablename__, "release_id", "institution_id", "offering_id", "version_id", "student_id"),
        _lineage_fk(__tablename__, "teaching_releases", ("release_id", "institution_id", "offering_id", "version_id"), ("id", "institution_id", "offering_id", "version_id")),
        _ix(__tablename__, "release_id", "institution_id", "offering_id", "version_id"),
        _ix(__tablename__, "student_id", "offering_id", "release_id"),
        _ck(__tablename__, "enrollment_revision_positive", "enrollment_revision_at_release >= 1"),
        explicit_table_options(),
    )


class Submission(Base):
    __tablename__ = "teaching_submissions"
    id = _id()
    institution_id = Column(String(64), nullable=False)
    offering_id = Column(String(36), nullable=False)
    release_id = Column(String(36), nullable=False)
    version_id = Column(String(36), nullable=False)
    student_id = Column(String(255), nullable=False)
    parent_submission_id = Column(String(36), nullable=True)
    sequence = Column(BigInteger, nullable=False)
    content = Column(JSON, nullable=False)
    content_hash = Column(String(64), nullable=False)
    ai_usage_declaration = Column(JSON, nullable=False)
    received_at = _time()
    __table_args__ = (
        _pk(__tablename__, "id"),
        _uq(__tablename__, "id", "institution_id", "offering_id", "release_id", "version_id", "student_id"),
        _uq(__tablename__, "release_id", "student_id", "sequence"), _uq(__tablename__, "parent_submission_id"),
        _lineage_fk(__tablename__, "teaching_release_recipients", ("release_id", "institution_id", "offering_id", "version_id", "student_id"), ("release_id", "institution_id", "offering_id", "version_id", "student_id")),
        _ix(__tablename__, "release_id", "institution_id", "offering_id", "version_id", "student_id"),
        _lineage_fk(__tablename__, __tablename__, ("parent_submission_id", "institution_id", "offering_id", "release_id", "version_id", "student_id"), ("id", "institution_id", "offering_id", "release_id", "version_id", "student_id")),
        _ix(__tablename__, "parent_submission_id", "institution_id", "offering_id", "release_id", "version_id", "student_id"),
        _ck(__tablename__, "sequence_positive", "sequence >= 1"),
        _ck(__tablename__, "parent_sequence", "(sequence = 1 AND parent_submission_id IS NULL) OR (sequence > 1 AND parent_submission_id IS NOT NULL)"),
        explicit_table_options(),
    )


class SubmissionHead(Base):
    __tablename__ = "teaching_submission_heads"
    release_id = Column(String(36), nullable=False)
    institution_id = Column(String(64), nullable=False)
    offering_id = Column(String(36), nullable=False)
    version_id = Column(String(36), nullable=False)
    student_id = Column(String(255), nullable=False)
    submission_id = Column(String(36), nullable=True)
    revision = _revision(0)
    __table_args__ = (
        _pk(__tablename__, "release_id", "student_id"),
        _lineage_fk(__tablename__, "teaching_release_recipients", ("release_id", "institution_id", "offering_id", "version_id", "student_id"), ("release_id", "institution_id", "offering_id", "version_id", "student_id")),
        _ix(__tablename__, "release_id", "institution_id", "offering_id", "version_id", "student_id"),
        _lineage_fk(__tablename__, "teaching_submissions", ("submission_id", "institution_id", "offering_id", "release_id", "version_id", "student_id"), ("id", "institution_id", "offering_id", "release_id", "version_id", "student_id")),
        _ix(__tablename__, "submission_id", "institution_id", "offering_id", "release_id", "version_id", "student_id"),
        _ck(__tablename__, "revision_nonnegative", "revision >= 0"),
        _ck(__tablename__, "null_revision_consistency", "(submission_id IS NULL AND revision = 0) OR (submission_id IS NOT NULL AND revision >= 1)"),
        explicit_table_options(),
    )


class AssessmentEvent(Base):
    __tablename__ = "teaching_assessment_events"
    id = _id()
    receipt_id = Column(String(36), nullable=False)
    institution_id = Column(String(64), nullable=False)
    offering_id = Column(String(36), nullable=False)
    actor_id = Column(String(255), nullable=False)
    actor_role = Column(String(32), nullable=False)
    action = Column(String(64), nullable=False)
    target_type = Column(String(64), nullable=False)
    target_id = Column(String(36), nullable=False)
    revision_kind = Column(String(32), nullable=False)
    before_revision = _revision(0)
    after_revision = _revision()
    occurred_at = _time()
    effect_metadata = Column(JSON, nullable=False)
    __table_args__ = (
        _pk(__tablename__, "id"), _uq(__tablename__, "receipt_id"),
        _lineage_fk(__tablename__, "teaching_write_receipts", ("receipt_id",), ("id",)),
        _lineage_fk(__tablename__, "teaching_offerings", ("offering_id", "institution_id"), ("id", "institution_id")),
        _ix(__tablename__, "offering_id", "institution_id"),
        _ix(__tablename__, "offering_id", "occurred_at", "id"),
        _ck(__tablename__, "actor_role_enum", "actor_role IN ('student', 'teacher')"),
        _ck(__tablename__, "revision_kind_enum", "revision_kind IN ('assignment_draft', 'assignment_version', 'release_preview', 'release', 'submission_head')"),
        _ck(__tablename__, "before_revision_nonnegative", "before_revision >= 0"),
        _ck(__tablename__, "after_revision_positive", "after_revision >= 1"),
        explicit_table_options(),
    )


def _reject_immutable_mutation(mapper, connection, row):
    # Intentionally ignores connection: no query, initialization or authority.
    raise ValueError(f"{type(row).__name__} is immutable; ORM update/delete rejected")


for _immutable_model in (AssignmentVersion, PrivateSpec, ReleasePreview, Release, ReleaseRecipient, Submission, AssessmentEvent):
    event.listen(_immutable_model, "before_update", _reject_immutable_mutation)
    event.listen(_immutable_model, "before_delete", _reject_immutable_mutation)
