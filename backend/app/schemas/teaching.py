"""Strict B1 reader DTOs. No ORM/account/config objects cross this boundary."""
from datetime import datetime, timezone
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import unicodedata

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_serializer, field_validator

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
    configured_permissions: list[Permission]
    available_actions: list[TeachingAction]
    role_scope: Literal["offering", "assigned"] | None


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
    available: bool
    can_create_course: bool
    reason: str
    assignments: StageDTO
    feedback: StageDTO
    revisions: StageDTO


class PreviewIssueDTO(StrictDTO):
    code: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    subject_id: Subject | None = None


class RosterPreviewDTO(StrictDTO):
    id: Id
    offering_id: Id
    mode: Literal["merge", "replace"]
    expected_roster_revision: Count
    offering_revision: Revision
    target_count: Count
    add_count: Count
    keep_count: Count
    update_count: Count
    withdrawals_count: Count
    target_digest: Digest
    withdrawals_digest: Digest
    withdraw_sample: list[Subject] = Field(max_length=20)
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
