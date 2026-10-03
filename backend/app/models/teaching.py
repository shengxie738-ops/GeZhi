"""B1 declarations only. Importing this module performs no schema DDL."""
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Column, DateTime, ForeignKeyConstraint, Index, Integer, JSON, PrimaryKeyConstraint, String, UniqueConstraint, event
from sqlalchemy.dialects.mysql import DATETIME

from app.core.database import Base

UTC_DATETIME = DateTime().with_variant(DATETIME(fsp=6), "mysql")


def constraint_name(kind, table, *parts):
    name = f"{kind}_{table}" + ("__" + "__".join(parts) if parts else "")
    return name if len(name) <= 64 else name[:55] + "_" + sha256(name.encode()).hexdigest()[:8]


def _pk(table, *columns):
    return PrimaryKeyConstraint(*columns, name=constraint_name("pk", table))


def _uq(table, *columns):
    return UniqueConstraint(*columns, name=constraint_name("uq", table, "_".join(columns)))


def _fk(table, parent, *columns):
    targets = [f"{parent}.{('id' if c.endswith('_id') and c != 'institution_id' else c)}" for c in columns]
    return ForeignKeyConstraint(columns, targets, name=constraint_name("fk", table, parent, "_".join(columns)))


def _ck(table, invariant, expression):
    return CheckConstraint(expression, name=constraint_name("ck", table, invariant))


def _ix(table, *columns):
    return Index(constraint_name("ix", table, "_".join(columns)), *columns)


def explicit_table_options():
    return {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_bin", "info": {"explicit_migration_only": True}}


def _id():
    return Column(String(36), nullable=False, default=lambda: str(uuid4()))


def _time(nullable=False):
    return Column(UTC_DATETIME, nullable=nullable)


def _revision(default=1):
    return Column(BigInteger, nullable=False, default=default, server_default=str(default))


def validate_relationship_interval(effective_from, effective_until):
    """Validate supplied UTC instants before persistence; intervals are half-open."""
    for value in (effective_from, effective_until):
        if value is not None and (not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value)):
            raise ValueError("relationship times must be timezone-aware UTC instants")
    if effective_from is None or (effective_until is not None and effective_until <= effective_from):
        raise ValueError("effective_until must be strictly after effective_from")


class Course(Base):
    __tablename__ = "teaching_courses"
    id = _id()
    institution_id = Column(String(64), nullable=False)
    source_teacher_id = Column(String(255), nullable=False)
    title = Column(String(200), nullable=False)
    code = Column(String(64), nullable=False, default="")
    description = Column(String(4000), nullable=False, default="")
    timezone = Column(String(64), nullable=False)
    revision = _revision()
    created_at = _time()
    updated_at = _time()
    __table_args__ = (_pk(__tablename__, "id"), _uq(__tablename__, "id", "institution_id"), _ix(__tablename__, "institution_id", "source_teacher_id", "id"), _ck(__tablename__, "revision_positive", "revision >= 1"), _ck(__tablename__, "title_nonempty", "title <> ''"), _ck(__tablename__, "timezone_nonempty", "timezone <> ''"), explicit_table_options())


class Offering(Base):
    __tablename__ = "teaching_offerings"
    id = _id()
    institution_id = Column(String(64), nullable=False)
    course_id = Column(String(36), nullable=False)
    title = Column(String(200), nullable=False)
    term = Column(String(64), nullable=False)
    timezone = Column(String(64), nullable=False)
    state = Column(String(32), nullable=False, default="draft")
    revision = _revision()
    roster_revision = _revision(0)
    created_at = _time()
    updated_at = _time()
    archived_at = _time(True)
    __table_args__ = (_pk(__tablename__, "id"), _uq(__tablename__, "id", "institution_id"), _fk(__tablename__, "teaching_courses", "course_id", "institution_id"), _ix(__tablename__, "course_id", "institution_id"), _ix(__tablename__, "course_id", "state", "id"), _ck(__tablename__, "state_enum", "state IN ('draft', 'active', 'archived')"), _ck(__tablename__, "revision_positive", "revision >= 1"), _ck(__tablename__, "roster_revision_nonnegative", "roster_revision >= 0"), _ck(__tablename__, "title_nonempty", "title <> ''"), _ck(__tablename__, "term_nonempty", "term <> ''"), _ck(__tablename__, "timezone_nonempty", "timezone <> ''"), explicit_table_options())


class Enrollment(Base):
    __tablename__ = "teaching_enrollments"
    id = _id()
    institution_id = Column(String(64), nullable=False)
    offering_id = Column(String(36), nullable=False)
    student_id = Column(String(255), nullable=False)
    status = Column(String(32), nullable=False, default="active")
    effective_from = _time()
    effective_until = _time(True)
    withdrawn_at = _time(True)
    revision = _revision()
    source_kind = Column(String(32), nullable=False, default="deployment_roster", server_default="deployment_roster")
    source_teacher_id = Column(String(255), nullable=False)
    source_policy_digest = Column(String(64), nullable=False)
    created_at = _time()
    updated_at = _time()
    __table_args__ = (_pk(__tablename__, "id"), _uq(__tablename__, "offering_id", "student_id"), _fk(__tablename__, "teaching_offerings", "offering_id", "institution_id"), _ix(__tablename__, "offering_id", "institution_id"), _ix(__tablename__, "student_id", "status", "offering_id"), _ix(__tablename__, "offering_id", "status", "student_id"), _ck(__tablename__, "status_enum", "status IN ('active', 'withdrawn')"), _ck(__tablename__, "revision_positive", "revision >= 1"), _ck(__tablename__, "interval_strict", "effective_until IS NULL OR effective_until > effective_from"), _ck(__tablename__, "source_kind", "source_kind = 'deployment_roster'"), explicit_table_options())


class TeachingRole(Base):
    __tablename__ = "teaching_roles"
    id = _id()
    institution_id = Column(String(64), nullable=False)
    offering_id = Column(String(36), nullable=False)
    subject_id = Column(String(255), nullable=False)
    granted_account_role = Column(String(32), nullable=False)
    label = Column(String(32), nullable=False)
    permissions = Column(JSON, nullable=False)
    scope = Column(String(32), nullable=False)
    status = Column(String(32), nullable=False, default="active")
    effective_from = _time()
    effective_until = _time(True)
    revoked_at = _time(True)
    revision = _revision()
    source_policy_digest = Column(String(64), nullable=False)
    created_at = _time()
    updated_at = _time()
    __table_args__ = (_pk(__tablename__, "id"), _uq(__tablename__, "offering_id", "subject_id"), _fk(__tablename__, "teaching_offerings", "offering_id", "institution_id"), _ix(__tablename__, "offering_id", "institution_id"), _ix(__tablename__, "subject_id", "status", "offering_id"), _ck(__tablename__, "granted_account_role_enum", "granted_account_role IN ('student', 'teacher')"), _ck(__tablename__, "label_enum", "label IN ('teacher', 'assistant')"), _ck(__tablename__, "student_assistant_label", "granted_account_role <> 'student' OR label = 'assistant'"), _ck(__tablename__, "scope_enum", "scope IN ('offering', 'assigned')"), _ck(__tablename__, "status_enum", "status IN ('active', 'revoked')"), _ck(__tablename__, "revision_positive", "revision >= 1"), _ck(__tablename__, "interval_strict", "effective_until IS NULL OR effective_until > effective_from"), explicit_table_options())


class RosterPreview(Base):
    __tablename__ = "teaching_roster_previews"
    id = _id()
    institution_id = Column(String(64), nullable=False)
    offering_id = Column(String(36), nullable=False)
    actor_id = Column(String(255), nullable=False)
    actor_role_id = Column(String(36), nullable=False)
    actor_role_revision = _revision()
    expected_roster_revision = _revision(0)
    offering_revision = _revision()
    mode = Column(String(32), nullable=False)
    canonical_command = Column(JSON, nullable=False)
    command_hash = Column(String(64), nullable=False)
    source_policy_digest = Column(String(64), nullable=False)
    target_ids = Column(JSON, nullable=False)
    add_ids = Column(JSON, nullable=False)
    keep_ids = Column(JSON, nullable=False)
    update_ids = Column(JSON, nullable=False)
    withdraw_ids = Column(JSON, nullable=False)
    validation_issues = Column(JSON, nullable=False)
    target_digest = Column(String(64), nullable=False)
    withdrawals_digest = Column(String(64), nullable=False)
    withdrawals_count = Column(BigInteger, nullable=False)
    can_apply = Column(Boolean, nullable=False)
    created_at = _time()
    expires_at = _time()
    __table_args__ = (_pk(__tablename__, "id"), _fk(__tablename__, "teaching_offerings", "offering_id", "institution_id"), _ix(__tablename__, "offering_id", "institution_id"), _ix(__tablename__, "offering_id", "actor_id", "created_at"), _ck(__tablename__, "mode_enum", "mode IN ('merge', 'replace')"), _ck(__tablename__, "actor_role_revision_positive", "actor_role_revision >= 1"), _ck(__tablename__, "offering_revision_positive", "offering_revision >= 1"), _ck(__tablename__, "expected_roster_revision_nonnegative", "expected_roster_revision >= 0"), _ck(__tablename__, "withdrawals_count_nonnegative", "withdrawals_count >= 0"), _ck(__tablename__, "expiry_strict", "expires_at > created_at"), explicit_table_options())


class WriteReceipt(Base):
    __tablename__ = "teaching_write_receipts"
    id = _id()
    institution_id = Column(String(64), nullable=False)
    actor_id = Column(String(255), nullable=False)
    action = Column(String(64), nullable=False)
    scope_type = Column(String(32), nullable=False)
    scope_id = Column(String(64), nullable=False)
    target_type = Column(String(64), nullable=False)
    target_id = Column(String(36), nullable=False)
    idempotency_key = Column(String(128), nullable=False)
    canonicalization_version = Column(Integer, nullable=False, default=1, server_default="1")
    request_hash = Column(String(64), nullable=False)
    result_type = Column(String(64), nullable=False)
    result_id = Column(String(36), nullable=False)
    accepted_at = _time()
    http_status = Column(Integer, nullable=False)
    original_result = Column(JSON, nullable=False)
    __table_args__ = (_pk(__tablename__, "id"), _uq(__tablename__, "actor_id", "action", "scope_type", "scope_id", "idempotency_key"), _ix(__tablename__, "actor_id", "id"), _ck(__tablename__, "scope_type_enum", "scope_type IN ('institution', 'course', 'offering')"), _ck(__tablename__, "canonicalization_version", "canonicalization_version = 1"), _ck(__tablename__, "http_status", "http_status >= 200 AND http_status < 300"), explicit_table_options())


class AccessEvent(Base):
    __tablename__ = "teaching_access_events"
    id = _id()
    institution_id = Column(String(64), nullable=False)
    receipt_id = Column(String(36), nullable=False)
    actor_id = Column(String(255), nullable=False)
    actor_role = Column(String(32), nullable=False)
    action = Column(String(64), nullable=False)
    scope_type = Column(String(32), nullable=False)
    scope_id = Column(String(64), nullable=False)
    target_type = Column(String(64), nullable=False)
    target_id = Column(String(36), nullable=False)
    revision_kind = Column(String(32), nullable=False)
    before_revision = _revision(0)
    after_revision = _revision()
    reason = Column(String(1000), nullable=False, default="")
    occurred_at = _time()
    effect_metadata = Column(JSON, nullable=False)
    __table_args__ = (_pk(__tablename__, "id"), _uq(__tablename__, "receipt_id"), _fk(__tablename__, "teaching_write_receipts", "receipt_id"), _ix(__tablename__, "scope_type", "scope_id", "occurred_at", "id"), _ck(__tablename__, "actor_role_enum", "actor_role IN ('student', 'teacher')"), _ck(__tablename__, "scope_type_enum", "scope_type IN ('institution', 'course', 'offering')"), _ck(__tablename__, "revision_kind_enum", "revision_kind IN ('course', 'offering', 'roster', 'role', 'preview')"), _ck(__tablename__, "before_revision_nonnegative", "before_revision >= 0"), _ck(__tablename__, "after_revision_positive", "after_revision >= 1"), explicit_table_options())


# SQL checks are not sufficient on every vendor. These local validations duplicate
# the essential boundaries without loading accounts or creating authority.
_ENUMS = {Offering: {"state": {"draft", "active", "archived"}}, Enrollment: {"status": {"active", "withdrawn"}, "source_kind": {"deployment_roster"}}, TeachingRole: {"granted_account_role": {"student", "teacher"}, "label": {"teacher", "assistant"}, "scope": {"offering", "assigned"}, "status": {"active", "revoked"}}, RosterPreview: {"mode": {"merge", "replace"}}, WriteReceipt: {"scope_type": {"institution", "course", "offering"}}, AccessEvent: {"actor_role": {"student", "teacher"}, "scope_type": {"institution", "course", "offering"}, "revision_kind": {"course", "offering", "roster", "role", "preview"}}}


def validate_teaching_row(row):
    for field, allowed in _ENUMS.get(type(row), {}).items():
        value = getattr(row, field)
        default = row.__table__.c[field].default
        if value is None and default is not None and default.is_scalar:
            value = default.arg
        if value not in allowed:
            raise ValueError(f"invalid {field}")
    for column in row.__table__.columns:
        value = getattr(row, column.name)
        if value is None:
            continue  # server/default and NOT NULL enforcement happen at flush
        if isinstance(column.type, String) and (not isinstance(value, str) or len(value) > column.type.length):
            raise ValueError(f"invalid {column.name} length")
        if column.name.endswith("revision"):
            minimum = 0 if column.name in {"roster_revision", "expected_roster_revision", "before_revision"} else 1
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"invalid {column.name}")
        if column.name.endswith("_digest") or column.name.endswith("_hash"):
            if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise ValueError(f"invalid {column.name}")
    for field in ("institution_id", "title", "timezone", "term"):
        if hasattr(row, field) and not getattr(row, field):
            raise ValueError(f"{field} must be nonempty")
    if isinstance(row, (Enrollment, TeachingRole)):
        if row.effective_from is None or (row.effective_until is not None and row.effective_until <= row.effective_from):
            raise ValueError("effective_until must be strictly after effective_from")
    if isinstance(row, TeachingRole):
        if row.granted_account_role == "student" and row.label != "assistant":
            raise ValueError("student role binding requires assistant label")
        values = row.permissions
        if not isinstance(values, list) or any(not isinstance(p, str) or not p or len(p) > 64 for p in values) or values != sorted(set(values)):
            raise ValueError("permissions must be a canonical sorted unique array")


def _validate_before_write(mapper, connection, row):
    validate_teaching_row(row)


for _model in (Course, Offering, Enrollment, TeachingRole, RosterPreview, WriteReceipt, AccessEvent):
    event.listen(_model, "before_insert", _validate_before_write)
    event.listen(_model, "before_update", _validate_before_write)
