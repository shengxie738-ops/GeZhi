"""Strict B1 reader DTOs. No ORM/account/config objects cross this boundary."""
from datetime import datetime, timezone
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import unicodedata

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_serializer, field_validator, model_validator

from app.services.teaching.types import Permission, TeachingAction

Id = Annotated[str, StringConstraints(min_length=1, max_length=36)]
Subject = Annotated[str, StringConstraints(min_length=1, max_length=255)]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Revision = Annotated[int, Field(ge=1)]
Count = Annotated[int, Field(ge=0)]


class StrictDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    @field_validator("*")
    @classmethod
    def safe_scalar(cls, value, info):
        if isinstance(value, str) and any(unicodedata.category(char).startswith("C")
                                         and not (info.field_name == "description" and char in "\r\n\t") for char in value):
            # Descriptions preserve authored newlines; all identifier/query and
            # machine-code fields remain control-free.
            raise ValueError("control characters are forbidden")
        if isinstance(value, datetime) and (value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value)):
            raise ValueError("UTC instant required")
        return value

    @field_serializer("*", when_used="json")
    def wire_scalar(self, value):
        if isinstance(value, datetime):
            return value.isoformat().replace("+00:00", "Z")
        return value


class PageQuery(StrictDTO):
    cursor: Id | None = None
    limit: int = Field(default=50, ge=1, le=100)


class CourseQuery(PageQuery):
    membership: Literal["teaching", "learning", "all"] = "all"


class OfferingQuery(CourseQuery):
    course_id: Id | None = None


class PreviewChangesQuery(StrictDTO):
    kind: Literal["add", "keep", "update", "withdraw"]
    cursor: Subject | None = None
    limit: int = Field(default=50, ge=1, le=100)


class EnrollmentDTO(StrictDTO):
    id: Id
    offering_id: Id
    student_id: Subject
    status: Literal["active", "withdrawn"]
    effective_from: datetime
    effective_until: datetime | None
    revision: Revision
    access_eligible: bool


class OfferingAccessDTO(StrictDTO):
    teaching: bool
    learning: bool
    configured_permissions: list[Permission] = Field(description="Current configured authority; does not establish operational write safety")
    available_actions: list[TeachingAction] = Field(description="Operational actions only; HTTP adapters expose no write actions while the hard safety gate is closed")
    role_scope: Literal["offering", "assigned"] | None
    writes_available: Literal[False] = Field(default=False, description="B1 production writes remain unconditionally unavailable")
    write_reason: Literal["write_safety_unproven"] = "write_safety_unproven"


class CourseDTO(StrictDTO):
    id: Id
    institution_id: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    source_teacher_id: Subject
    title: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    code: Annotated[str, StringConstraints(max_length=64)]
    description: Annotated[str, StringConstraints(max_length=4000)]
    timezone: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    revision: Revision
    created_at: datetime
    updated_at: datetime
    memberships: list[Literal["teaching", "learning"]]
    visible_offering_count: Count

    @field_validator("description", mode="before")
    @classmethod
    def preserve_description(cls, value):
        # Preserve description text rather than trimming/case-folding it.
        return value

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("unknown timezone") from exc
        return value


class OfferingDTO(StrictDTO):
    id: Id
    course_id: Id
    title: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    term: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    timezone: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    state: Literal["draft", "active", "archived"]
    revision: Revision
    roster_revision: Count | None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    access: OfferingAccessDTO
    enrollment: EnrollmentDTO | None

    _known_timezone = field_validator("timezone")(CourseDTO.known_timezone.__func__)


class CoursePageDTO(StrictDTO):
    items: list[CourseDTO]
    next_cursor: Id | None
    as_of: datetime


class OfferingPageDTO(StrictDTO):
    items: list[OfferingDTO]
    next_cursor: Id | None
    as_of: datetime


class RosterEntryDTO(EnrollmentDTO):
    source_availability: Literal["available", "source_revoked", "account_unavailable"]


class RosterPageDTO(StrictDTO):
    items: list[RosterEntryDTO]
    next_cursor: Id | None
    as_of: datetime


class RoleDTO(StrictDTO):
    id: Id
    subject_id: Subject
    granted_account_role: Literal["student", "teacher"]
    label: Literal["teacher", "assistant"]
    configured_permissions: list[Permission]
    scope: Literal["offering", "assigned"]
    status: Literal["active", "revoked"]
    effective_from: datetime
    effective_until: datetime | None
    revision: Revision
    effective_permissions: list[Permission]
    effective_scope: Literal["offering", "assigned"] | None
    reason: str


class RoleListDTO(StrictDTO):
    items: list[RoleDTO]
    as_of: datetime


class StageDTO(StrictDTO):
    configured: bool
    installed: bool
    available: bool
    reason: str


class CapabilityDTO(StrictDTO):
    account_role: Literal["student", "teacher"]
    configured: bool
    available: bool = Field(description="B1 read readiness only; independent of write safety")
    can_create_course: bool = Field(description="Operational course creation; the public adapter returns false while write safety is unproven")
    reason: str
    assignments: StageDTO
    feedback: StageDTO
    revisions: StageDTO
    writes_available: Literal[False] = Field(default=False, description="B1 production writes remain unconditionally unavailable")
    write_reason: Literal["write_safety_unproven"] = "write_safety_unproven"


class PreviewIssueDTO(StrictDTO):
    code: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    subject_id: Subject | None = None


class RosterPeriodCommand(StrictDTO):
    effective_from: datetime | None = None
    effective_until: datetime | None = None

    @field_validator("effective_from", "effective_until", mode="before")
    @classmethod
    def utc_wire_time(cls, value):
        if isinstance(value, str):
            if "T" not in value or not value.endswith(("Z", "+00:00")):
                raise ValueError("UTC timestamp required")
            try:
                value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("UTC timestamp required") from exc
        return value

    @model_validator(mode="after")
    def ordered_period(self):
        if self.effective_from is not None and self.effective_until is not None and self.effective_until <= self.effective_from:
            raise ValueError("effective interval must be strictly increasing")
        return self



class RosterPreviewDTO(StrictDTO):
    id: Id
    offering_id: Id
    mode: Literal["merge", "replace"]
    expected_roster_revision: Count
    offering_revision: Revision
    target_count: Count = Field(description="Complete proposed status-active set: add_count + keep_count")
    add_count: Count = Field(description="New or re-enabled target rows")
    keep_count: Count = Field(description="All retained status-active rows; includes the update_count subset")
    update_count: Count = Field(description="Explicit period-change subset of keep_count; do not add it again to target_count")
    withdrawals_count: Count
    target_digest: Digest
    withdrawals_digest: Digest
    withdraw_sample: list[Subject] = Field(max_length=20)
    add_sample: list[Subject] = Field(default_factory=list, max_length=20)
    keep_sample: list[Subject] = Field(default_factory=list, max_length=20)
    update_sample: list[Subject] = Field(default_factory=list, max_length=20)
    validation_issue_count: Count = 0
    period: RosterPeriodCommand | None = None
    period_target_count: Count = 0
    validation_issues: list[PreviewIssueDTO]
    can_apply: bool
    expired: bool
    created_at: datetime
    expires_at: datetime


class PreviewChangesDTO(StrictDTO):
    kind: Literal["add", "keep", "update", "withdraw"]
    items: list[Subject]
    total_count: Count
    next_cursor: Subject | None
    as_of: datetime


# Only original receipt/recovery projections are released here. Mutation input
# DTOs and the wider teaching HTTP surface belong to subsequent tasks.
IdempotencyKey = Annotated[str, StringConstraints(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")]
WriteActionName = Literal["course_create", "course_update", "offering_create", "course_manage", "roster_manage", "roles_manage"]


class ReceiptQuery(StrictDTO):
    action: WriteActionName
    scope_type: Literal["institution", "course", "offering"]
    scope_id: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    key: IdempotencyKey


class WriteReceiptDTO(StrictDTO):
    id: Id
    action: TeachingAction
    scope_type: Literal["institution", "course", "offering"]
    scope_id: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    target_type: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    target_id: Id
    result_type: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    result_id: Id
    canonicalization_version: Literal[1]
    request_hash: Digest
    accepted_at: datetime
    http_status: int = Field(ge=200, lt=300)
    original_result: dict


class WriteResultDTO(StrictDTO):
    receipt: WriteReceiptDTO
    result: dict
    replayed: bool


# Task4 command and immutable acceptance DTOs. These do not supply authority.
Title = Annotated[str, StringConstraints(min_length=1, max_length=200)]
TimeZoneName = Annotated[str, StringConstraints(min_length=1, max_length=64)]
Reason = Annotated[str, StringConstraints(min_length=1, max_length=1000)]


class Task4Command(StrictDTO):
    @field_validator("*", mode="before")
    @classmethod
    def trim_metadata(cls, value, info):
        if isinstance(value, str) and info.field_name in {"title", "code", "term", "reason"}:
            if any(unicodedata.category(char).startswith("C") for char in value):
                raise ValueError("control characters are forbidden")
            return value.strip()
        return value

    @field_validator("*", mode="after")
    @classmethod
    def command_timezone(cls, value, info):
        if info.field_name == "timezone" and value is not None:
            return CourseDTO.known_timezone(value)
        return value


class CreateCourseCommand(Task4Command):
    title: Title
    code: Annotated[str, StringConstraints(max_length=64)] = ""
    description: Annotated[str, StringConstraints(max_length=4000)] = ""
    timezone: TimeZoneName


class UpdateCourseCommand(Task4Command):
    expected_revision: Revision
    title: Title | None = None
    code: Annotated[str, StringConstraints(max_length=64)] | None = None
    description: Annotated[str, StringConstraints(max_length=4000)] | None = None
    timezone: TimeZoneName | None = None

    @model_validator(mode="after")
    def meaningful_update(self):
        supplied = self.model_fields_set - {"expected_revision"}
        if not supplied or any(getattr(self, name) is None for name in supplied):
            raise ValueError("at least one non-null mutable field required")
        return self


class CreateOfferingCommand(Task4Command):
    title: Title
    term: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    timezone: TimeZoneName | None = None


class UpdateOfferingCommand(Task4Command):
    expected_revision: Revision
    title: Title | None = None
    term: Annotated[str, StringConstraints(min_length=1, max_length=64)] | None = None
    timezone: TimeZoneName | None = None

    @model_validator(mode="after")
    def meaningful_update(self):
        supplied = self.model_fields_set - {"expected_revision"}
        if not supplied or any(getattr(self, name) is None for name in supplied):
            raise ValueError("at least one non-null mutable field required")
        return self


class TransitionOfferingCommand(Task4Command):
    expected_revision: Revision
    target_state: Literal["draft", "active", "archived"]
    reason: Reason


class SetRoleCommand(Task4Command):
    expected_role_revision: Count
    status: Literal["active", "revoked"]
    label: Literal["teacher", "assistant"]
    permissions: list[Permission] = Field(max_length=len(Permission))
    scope: Literal["offering", "assigned"]
    effective_from: datetime | None = None
    effective_until: datetime | None = None
    reason: Reason

    @field_validator("permissions", mode="before")
    @classmethod
    def permission_values(cls, values):
        if not isinstance(values, list) or any(not isinstance(value, (str, Permission)) for value in values):
            raise ValueError("permission array required")
        try:
            return sorted({Permission(value) for value in values}, key=lambda value: value.value)
        except (TypeError, ValueError) as exc:
            raise ValueError("unknown permission") from exc

    @field_validator("effective_from", "effective_until", mode="before")
    @classmethod
    def utc_wire_time(cls, value):
        if isinstance(value, str):
            # Accept RFC3339 UTC strings only; no local/naive interpretation.
            if "T" not in value or not value.endswith(("Z", "+00:00")):
                raise ValueError("UTC timestamp required")
            try:
                value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("UTC timestamp required") from exc
        return value

    @model_validator(mode="after")
    def bounded_role(self):
        from app.services.teaching.types import MANAGEMENT_PERMISSIONS
        if self.scope == "assigned" and set(self.permissions) & MANAGEMENT_PERMISSIONS:
            raise ValueError("assigned scope cannot manage offering")
        if self.status == "revoked" and self.permissions:
            raise ValueError("revocation requires empty permissions")
        if self.effective_from is not None and self.effective_until is not None and self.effective_until <= self.effective_from:
            raise ValueError("effective interval must be strictly increasing")
        return self


class CourseWriteResultDTO(StrictDTO):
    course_id: Id
    revision: Revision


class OfferingWriteResultDTO(StrictDTO):
    offering_id: Id
    revision: Revision


class TransitionWriteResultDTO(OfferingWriteResultDTO):
    state: Literal["draft", "active", "archived"]


class RoleWriteResultDTO(StrictDTO):
    role_id: Id
    subject_id: Subject
    revision: Revision
    status: Literal["active", "revoked"]


# Task5 strict full-set roster commands. These never carry authority claims.
class RosterPreviewCommand(StrictDTO):
    mode: Literal["merge", "replace"]
    expected_roster_revision: Count
    student_ids: list[Subject] = Field(max_length=10000)
    period: RosterPeriodCommand | None = None

    @field_validator("student_ids")
    @classmethod
    def exact_subjects(cls, values):
        from app.services.teaching.types import exact_identifier
        if any(not exact_identifier(value) for value in values):
            raise ValueError("exact account identifiers required")
        return values

    @field_validator("period", mode="before")
    @classmethod
    def supplied_period_is_object(cls, value):
        if value is None:
            raise ValueError("omit period to retain existing intervals")
        return value


class RosterApplicationCommand(StrictDTO):
    preview_id: Id
    expected_roster_revision: Count
    confirmed_withdrawals_digest: Digest
    confirmed_withdrawals_count: Count

    @field_validator("preview_id")
    @classmethod
    def exact_preview(cls, value):
        from app.services.teaching.types import exact_identifier
        if not exact_identifier(value, 36):
            raise ValueError("exact preview identifier required")
        return value


class RosterApplicationDTO(StrictDTO):
    offering_id: Id
    preview_id: Id
    roster_revision: Revision
    target_count: Count = Field(description="Complete accepted target set: added_count + kept_count + updated_count")
    added_count: Count = Field(description="Actual new or re-enabled rows")
    kept_count: Count = Field(description="Unchanged retained rows; excludes updated_count")
    updated_count: Count = Field(description="Actual changed retained rows; disjoint from kept_count")
    withdrawn_count: Count
    target_digest: Digest
    withdrawals_digest: Digest
