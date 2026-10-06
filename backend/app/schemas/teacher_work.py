"""Strict Teacher Work commands and immutable, JSON-array-compatible snapshots.

This module is pure. An HTTP adapter must check raw body bytes before parsing.
Requests contain no server owner/status/path/approval flags or arbitrary handlers.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, computed_field, field_validator, model_validator

from app.services.teacher_work.types import canonical_json_bytes


BODY_LIMIT = 256 * 1024
FROZEN_CONTENT_LIMIT = 128 * 1024
SkillRef = Literal["lesson_outline@1", "lesson_package@1", "classroom_exercises@1", "reference_search@1"]
ProviderID = Literal["arxiv", "openalex", "crossref"]
ChatResultType = Literal["answer", "outline_proposal", "revision_proposal", "skill_suggestion"]
Revision = Annotated[int, Field(strict=True, ge=1)]
Digest = Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]
ShortText = Annotated[str, Field(strict=True, min_length=1, max_length=200)]
OptionalShortText = Annotated[str, Field(strict=True, max_length=200)]
IDText = Annotated[str, Field(strict=True, min_length=1, max_length=255)]
ErrorCode = Annotated[str, Field(strict=True, pattern=r"^[A-Z][A-Z0-9_]{0,63}$")]


def validate_teacher_work_body_size(raw: bytes) -> None:
    if type(raw) is not bytes:
        raise ValueError("raw request bytes are required")
    if len(raw) > BODY_LIMIT:
        raise ValueError("teacher Work body exceeds 256 KiB")


def validate_teacher_work_frozen_content_size(raw: bytes) -> None:
    if type(raw) is not bytes:
        raise ValueError("canonical frozen content bytes are required")
    if len(raw) > FROZEN_CONTENT_LIMIT:
        raise ValueError("teacher Work frozen content exceeds 128 KiB")


def _array(value: object) -> tuple:
    # JSON arrays become standard immutable tuples; no scalar or generator coercion.
    if not isinstance(value, (list, tuple)):
        raise ValueError("an array is required")
    return tuple(value)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone-aware UTC instant required")
    return value.astimezone(timezone.utc)


def _key(value: str) -> str:
    if not value or len(value) > 128 or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value):
        raise ValueError("key must contain 1–128 characters without controls")
    return value


def _slide_text(value: str) -> str:
    if re.search(r"<[A-Za-z!/][^>]*>|(?:javascript|vbscript|data)\s*:", value, re.IGNORECASE):
        raise ValueError("slide content must be plain text, without HTML or script URLs")
    return value


UTCDateTime = Annotated[datetime, AfterValidator(_utc)]
MessageKey = Annotated[str, Field(strict=True, min_length=1, max_length=128), AfterValidator(_key)]
BodyItem = Annotated[str, Field(strict=True, max_length=90), AfterValidator(_slide_text)]
BodyItems = Annotated[tuple[BodyItem, ...], BeforeValidator(_array), Field(max_length=5)]
UUIDRefs = Annotated[tuple[UUID, ...], BeforeValidator(_array), Field(max_length=10)]
SelectionRefs = Annotated[tuple[IDText, ...], BeforeValidator(_array), Field(max_length=10)]
SkillRefs = Annotated[tuple[SkillRef, ...], BeforeValidator(_array), Field(max_length=4)]
ProviderRefs = Annotated[tuple[ProviderID, ...], BeforeValidator(_array), Field(max_length=3)]
LessonItem = Annotated[str, Field(strict=True, min_length=1, max_length=2000)]
LessonItems = Annotated[tuple[LessonItem, ...], BeforeValidator(_array), Field(max_length=20)]


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class FrozenDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class CreateTaskRequest(StrictRequest):
    title: ShortText
    topic: ShortText
    audience: ShortText
    duration_minutes: int = Field(default=45, ge=1, le=600)
    target_slide_count: int = Field(default=8, ge=6, le=12)
    resource_ids: list[IDText] = Field(min_length=1, max_length=10)
    scope: Literal["private", "offering"]
    offering_id: UUID | None = None

    @model_validator(mode="after")
    def valid_scope(self) -> CreateTaskRequest:
        if (self.scope == "private") != (self.offering_id is None):
            raise ValueError("private scope has no offering; offering scope requires one")
        if len(set(self.resource_ids)) != len(self.resource_ids):
            raise ValueError("resource IDs must be distinct")
        return self


class TeachingStageSnapshot(FrozenDTO):
    stage: ShortText
    minutes: int = Field(ge=1, le=600)
    content: Annotated[str, Field(min_length=1, max_length=2000)]


class CitationSnapshot(FrozenDTO):
    name: OptionalShortText = ""
    page: int = Field(default=0, ge=0)
    excerpt: str = Field(default="", max_length=4000)


class LessonSnapshot(FrozenDTO):
    """Existing export field names, with stricter bounded Work content."""
    title: ShortText
    topic: OptionalShortText = ""
    course_name: OptionalShortText = ""
    audience: OptionalShortText = ""
    duration_minutes: int = Field(default=45, ge=1, le=600)
    objectives: LessonItems = ()
    key_points: LessonItems = ()
    difficulties: LessonItems = ()
    questions: LessonItems = ()
    exercises: LessonItems = ()
    homework: LessonItems = ()
    summary: str = Field(default="", max_length=8000)
    teaching_flow: Annotated[tuple[TeachingStageSnapshot, ...], BeforeValidator(_array), Field(min_length=1, max_length=20)]
    citations: Annotated[tuple[CitationSnapshot, ...], BeforeValidator(_array), Field(max_length=20)] = ()

    @model_validator(mode="after")
    def exact_duration(self) -> LessonSnapshot:
        if sum(stage.minutes for stage in self.teaching_flow) != self.duration_minutes:
            raise ValueError("teaching-flow minutes must equal lesson duration")
        return self


class SlideSnapshot(FrozenDTO):
    layout: Literal["title", "section", "bullets", "two_column", "question", "summary"]
    title: Annotated[str, Field(min_length=1, max_length=60), AfterValidator(_slide_text)]
    body: BodyItems = ()
    columns: Annotated[tuple[BodyItems, ...], BeforeValidator(_array), Field(max_length=2)] = ()
    notes: Annotated[str, Field(max_length=1200), AfterValidator(_slide_text)] = ""
    source_note: Annotated[str, Field(max_length=120), AfterValidator(_slide_text)] = ""
    evidence_refs: UUIDRefs = ()

    @model_validator(mode="after")
    def body_density(self) -> SlideSnapshot:
        if self.layout == "two_column":
            if len(self.columns) != 2 or self.body:
                raise ValueError("two_column requires exactly two columns and no body")
            items = tuple(item for column in self.columns for item in column)
        else:
            if self.columns:
                raise ValueError("columns are only supported by two_column")
            items = self.body
        if len(items) > 5 or sum(len(item) for item in items) > 360:
            raise ValueError("slide body exceeds five items or 360 characters")
        return self


Slides = Annotated[tuple[SlideSnapshot, ...], BeforeValidator(_array), Field(min_length=6, max_length=12)]


class SlideModel(FrozenDTO):
    slides: Slides


class WorkingChanges(StrictRequest):
    requirements: str | None = Field(default=None, max_length=4000)
    lesson: LessonSnapshot | None = None
    resource_ids: list[IDText] | None = Field(default=None, min_length=1, max_length=10)
    reference_ids: list[UUID] | None = Field(default=None, max_length=10)
    skill_refs: list[SkillRef] | None = Field(default=None, max_length=4)
    plugin_ids: list[ProviderID] | None = Field(default=None, max_length=3)
    target_slide_count: int | None = Field(default=None, ge=6, le=12)

    @model_validator(mode="after")
    def explicit_changes(self) -> WorkingChanges:
        for name in self.model_fields_set:
            value = getattr(self, name)
            if value is None:
                raise ValueError("explicit changes cannot be null; omit to preserve or use empty selections/requirements")
            if name in {"resource_ids", "reference_ids", "skill_refs", "plugin_ids"} and len(set(value)) != len(value):
                raise ValueError("selection IDs must be distinct")
        return self


class WorkingPatchRequest(StrictRequest):
    expected_revision: Revision
    changes: WorkingChanges
    base_version_id: UUID | None = None


class OutlineApprovalRequest(StrictRequest):
    input_revision: Revision
    outline_revision: Revision
    outline_digest: Digest
    source_digest: Digest


class ChatInput(StrictRequest):
    text: str = Field(min_length=1, max_length=4000)
    client_message_key: MessageKey


class OutlineInput(StrictRequest):
    pass


class PackageInput(StrictRequest):
    approval_id: UUID


class ReviseInput(StrictRequest):
    base_version_id: UUID | None = None
    text: str = Field(min_length=1, max_length=4000)


class ReferenceSearchInput(StrictRequest):
    query: str = Field(min_length=1, max_length=200)
    provider_ids: list[ProviderID] = Field(min_length=1, max_length=3)
    limit: int = Field(ge=1, le=50)


class ChatCommand(StrictRequest):
    kind: Literal["chat"]
    input_revision: Revision
    skill_ref: None
    payload: ChatInput


class OutlineCommand(StrictRequest):
    kind: Literal["outline"]
    input_revision: Revision
    skill_ref: Literal["lesson_outline@1"]
    payload: OutlineInput


class PackageCommand(StrictRequest):
    kind: Literal["package"]
    input_revision: Revision
    skill_ref: Literal["lesson_package@1"]
    payload: PackageInput


class ReviseCommand(StrictRequest):
    kind: Literal["revise"]
    input_revision: Revision
    skill_ref: Literal["classroom_exercises@1"] | None
    payload: ReviseInput


class ReferenceSearchCommand(StrictRequest):
    kind: Literal["reference_search"]
    input_revision: Revision
    skill_ref: Literal["reference_search@1"]
    payload: ReferenceSearchInput


RunCommand = Annotated[ChatCommand | OutlineCommand | PackageCommand | ReviseCommand | ReferenceSearchCommand, Field(discriminator="kind")]


class WorkTaskDTO(FrozenDTO):
    task_id: UUID
    owner_subject: IDText
    owner_storage_id: UUID
    institution_id: Annotated[str, Field(min_length=1, max_length=64)] | None = None
    offering_id: UUID | None = None
    title: ShortText
    topic: ShortText
    audience: ShortText
    duration_minutes: int = Field(ge=1, le=600)
    target_slide_count: int = Field(ge=6, le=12)
    lesson_draft_id: IDText
    input_revision: Revision
    working_revision: Revision
    current_outline_id: UUID | None = None
    latest_version_id: UUID | None = None
    skill_refs: SkillRefs = ()
    plugin_ids: ProviderRefs = ()
    reference_ids: UUIDRefs = ()
    created_at: UTCDateTime
    updated_at: UTCDateTime

    @model_validator(mode="after")
    def paired_scope(self) -> WorkTaskDTO:
        if (self.institution_id is None) != (self.offering_id is None):
            raise ValueError("institution and offering scope must be paired")
        return self


class PrivateWorkingSnapshot(FrozenDTO):
    requirements: Annotated[str, Field(max_length=4000)]
    resource_ids: Annotated[tuple[IDText, ...], BeforeValidator(_array), Field(min_length=1, max_length=10)]
    needs_normalization_fields: Annotated[tuple[Annotated[str, Field(min_length=1, max_length=255,
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*(?:\[[0-9]+\])?(?:\.[A-Za-z_][A-Za-z0-9_]*(?:\[[0-9]+\])?)*$")], ...], BeforeValidator(_array), Field(max_length=1000)]

    @model_validator(mode="after")
    def distinct_resources(self):
        if len(set(self.resource_ids)) != len(self.resource_ids):
            raise ValueError("distinct resource IDs required")
        return self


class PrivateTaskSnapshot(FrozenDTO):
    """Full internal authorization anchor, plus an explicit public projection."""
    task: WorkTaskDTO
    working: PrivateWorkingSnapshot

    @model_validator(mode="after")
    def private_scope(self):
        if self.task.institution_id is not None or self.task.offering_id is not None:
            raise ValueError("private task required")
        return self

    def public_data(self) -> dict:
        names = {"task_id", "title", "topic", "audience", "duration_minutes", "target_slide_count",
            "input_revision", "working_revision", "created_at", "updated_at"}
        return {**self.task.model_dump(mode="json", include=names), "scope": "private",
            "working": self.working.model_dump(mode="json")}


class WorkMessageDTO(FrozenDTO):
    message_id: UUID
    task_id: UUID
    owner: IDText
    client_message_key: MessageKey | None = None
    role: Literal["user", "assistant", "tool"]
    plain_text: str = Field(max_length=32768)
    run_id: UUID | None = None
    result_refs: UUIDRefs = ()
    result_type: ChatResultType | None = None
    omitted_context: bool | None = None
    created_at: UTCDateTime

    @model_validator(mode="after")
    def actual_result_metadata(self) -> WorkMessageDTO:
        if self.result_type is None and self.omitted_context is None:
            return self  # Historical messages remain explicitly unclassified.
        if (self.result_type is None or self.omitted_context is None
                or self.role != "assistant" or self.run_id is None or not self.plain_text.strip()):
            raise ValueError("classified messages require an actual linked assistant result")
        ChatResult.model_validate({"type": self.result_type, "plain_text": self.plain_text,
                                   "result_refs": self.result_refs, "omitted_context": self.omitted_context})
        return self


class ChatTaskBrief(FrozenDTO):
    task_id: UUID
    input_revision: Revision
    title: ShortText
    topic: ShortText
    audience: ShortText
    requirements: Annotated[str, Field(max_length=4000)]


class PrivateChatHistory(FrozenDTO):
    """Detached bounded rows with a full request-owner authorization anchor."""
    task: WorkTaskDTO
    messages: Annotated[tuple[WorkMessageDTO, ...], BeforeValidator(_array), Field(max_length=50)]
    has_more: bool
    next_before: UUID | None

    @model_validator(mode="after")
    def coherent(self):
        if self.task.offering_id is not None or self.task.institution_id is not None:
            raise ValueError("private history required")
        if any((m.owner, m.task_id) != (self.task.owner_subject, self.task.task_id) for m in self.messages):
            raise ValueError("history scope mismatch")
        order = [(m.created_at, str(m.message_id)) for m in self.messages]
        if order != sorted(set(order)):
            raise ValueError("distinct stable chronological history required")
        cursor = self.messages[0].message_id if self.has_more and self.messages else None
        if self.next_before != cursor or self.has_more and not self.messages:
            raise ValueError("exact older cursor required")
        return self

    def public_data(self):
        return {"task_id": str(self.task.task_id), "messages": [m.model_dump(mode="json", exclude={"owner"}) for m in self.messages],
                "has_more": self.has_more, "next_before": str(self.next_before) if self.next_before else None}


class OutlineSnapshotDTO(FrozenDTO):
    outline_id: UUID
    task_id: UUID
    input_revision: Revision
    outline_revision: Revision
    lesson: LessonSnapshot
    slides: Slides
    source_digest: Digest
    outline_digest: Digest
    skill_versions: SkillRefs
    created_at: UTCDateTime


class ApprovalReceipt(FrozenDTO):
    approval_id: UUID
    owner: IDText
    task_id: UUID
    outline_id: UUID
    input_revision: Revision
    outline_revision: Revision
    outline_digest: Digest
    source_digest: Digest
    confirmed_at: UTCDateTime


class EvidenceSnapshotDTO(FrozenDTO):
    evidence_id: UUID
    task_id: UUID
    resource_id: IDText | None = None
    ref_id: UUID | None = None
    name: ShortText
    page: int | None = Field(default=None, ge=1)
    external_id: Annotated[str, Field(min_length=1, max_length=255)] | None = None
    excerpt: str = Field(min_length=1, max_length=4000)
    resource_content_digest: Digest
    acquired_at: UTCDateTime
    evidence_type: Literal["courseware", "reference"]

    @model_validator(mode="after")
    def evidence_origin(self) -> EvidenceSnapshotDTO:
        if self.evidence_type == "courseware":
            if self.resource_id is None or self.page is None or self.ref_id is not None or self.external_id is not None:
                raise ValueError("courseware evidence requires an actual resource and page")
        elif self.ref_id is None or self.resource_id is not None or self.page is not None:
            raise ValueError("external reference evidence has no invented courseware page")
        return self


class RunDTO(FrozenDTO):
    run_id: UUID
    owner: IDText
    task_id: UUID
    kind: Literal["chat", "outline", "package", "revise", "reference_search"]
    skill_ref: SkillRef | None
    input_revision: Revision
    outline_revision: Revision | None = None
    idempotency_key: MessageKey
    request_digest: Digest
    stage: Literal["PENDING", "CHAT_RUNNING", "OUTLINE_RUNNING", "REVISION_RUNNING", "REFERENCE_SEARCH_RUNNING", "CONTENT_RUNNING", "CONTENT_VALIDATED", "FILES_RUNNING", "PACKAGE_READY", "COMPLETE", "FAILED", "CANCELLED", "INTERRUPTED"]
    attempt: int = Field(ge=1, le=2)
    provider_call_count: int = Field(ge=0, le=3)
    deadline: UTCDateTime
    cancelled_at: UTCDateTime | None = None
    error_code: ErrorCode | None = None
    result_version_id: UUID | None = None

    @model_validator(mode="after")
    def registered_route(self) -> RunDTO:
        permitted = {"chat": {None}, "outline": {"lesson_outline@1"}, "package": {"lesson_package@1"}, "revise": {None, "classroom_exercises@1"}, "reference_search": {"reference_search@1"}}
        if self.skill_ref not in permitted[self.kind]:
            raise ValueError("run kind and Skill version do not match")
        return self


class FrozenPackageContent(FrozenDTO):
    lesson: LessonSnapshot
    slides: Slides
    source_snapshots: Annotated[tuple[EvidenceSnapshotDTO, ...], BeforeValidator(_array), Field(max_length=10)] = ()

    @model_validator(mode="after")
    def bounded_frozen_content(self) -> FrozenPackageContent:
        content = self.model_dump(mode="json", include={"lesson", "slides", "source_snapshots"})
        validate_teacher_work_frozen_content_size(canonical_json_bytes(content))
        return self


class PackageVersionDTO(FrozenPackageContent):
    version_id: UUID
    task_id: UUID
    version_no: Revision
    base_version_id: UUID | None = None
    run_id: UUID
    content_digest: Digest
    model_id: ShortText
    skill_versions: SkillRefs
    exporter_versions: Annotated[tuple[ShortText, ...], BeforeValidator(_array), Field(max_length=2)]
    template_version: ShortText
    created_at: UTCDateTime


class ValidationSummary(FrozenDTO):
    valid: bool
    checks: Annotated[tuple[ShortText, ...], BeforeValidator(_array), Field(max_length=20)] = ()
    warnings: Annotated[tuple[ShortText, ...], BeforeValidator(_array), Field(max_length=20)] = ()


class ArtifactDTO(FrozenDTO):
    """Private storage keys belong only in persistence, never in API DTOs."""
    artifact_id: UUID
    version_id: UUID
    kind: Literal["pptx", "docx"]
    state: Literal["PENDING", "BUILDING", "VALIDATING", "READY", "FAILED"]
    download_name: ShortText
    mime: Literal["application/vnd.openxmlformats-officedocument.presentationml.presentation", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"]
    byte_size: int = Field(default=0, ge=0, le=10 * 1024 * 1024)
    sha256: Digest | None = None
    exporter_version: ShortText
    validation_summary: ValidationSummary | None = None
    error_code: ErrorCode | None = None

    @model_validator(mode="after")
    def file_contract(self) -> ArtifactDTO:
        if any(ord(char) < 32 or ord(char) == 127 or char in "/\\" for char in self.download_name):
            raise ValueError("download name must be a safe basename")
        expected = {"pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
        if self.mime != expected[self.kind] or not self.download_name.lower().endswith("." + self.kind):
            raise ValueError("file format, MIME and extension must match")
        if self.state == "READY" and (self.byte_size == 0 or self.sha256 is None or self.validation_summary is None or not self.validation_summary.valid or self.error_code is not None):
            raise ValueError("READY requires validated, nonempty bytes and digest")
        return self


class PreviewDTO(FrozenDTO):
    version_id: UUID
    artifact_kind: Literal["pptx", "docx"]
    kind: Literal["structural", "rendered"]
    state: Literal["PENDING", "READY", "FAILED", "UNSUPPORTED"]
    source_content_digest: Digest
    source_file_digest: Digest | None = None
    error_code: ErrorCode | None = None

    @model_validator(mode="after")
    def separate_rendering(self) -> PreviewDTO:
        if self.kind == "rendered" and self.state != "UNSUPPORTED":
            raise ValueError("rendered preview is unsupported in the first release")
        return self


class ReviewDTO(FrozenDTO):
    review_id: UUID
    task_id: UUID
    version_id: UUID
    owner: IDText
    content_digest: Digest
    pptx_sha256: Digest
    docx_sha256: Digest
    reviewed_at: UTCDateTime


class ChatResult(FrozenDTO):
    type: ChatResultType
    plain_text: str = Field(max_length=32768)
    result_refs: UUIDRefs = ()
    omitted_context: bool = False


class FrozenWorkingChanges(FrozenDTO):
    requirements: str | None = Field(default=None, max_length=4000)
    lesson: LessonSnapshot | None = None
    resource_ids: Annotated[tuple[IDText, ...], BeforeValidator(_array), Field(min_length=1, max_length=10)] | None = None
    reference_ids: UUIDRefs | None = None
    skill_refs: SkillRefs | None = None
    plugin_ids: ProviderRefs | None = None
    target_slide_count: int | None = Field(default=None, ge=6, le=12)


class RevisionProposal(FrozenDTO):
    base_version_id: UUID | None = None
    proposed_changes: FrozenWorkingChanges
    evidence_refs: UUIDRefs = ()


class PrivateTaskCapabilities(FrozenDTO):
    create: bool = False
    read: bool = False
    update: bool = False


class PrivateChatCapabilities(FrozenDTO):
    send: bool = False
    history: bool = False
    read_run: bool = False
    cancel: bool = False
    provider_configured: bool = False
    external_provider_verified: Literal[False] = False


class WorkCapabilities(FrozenDTO):
    chat: bool
    task_write: bool
    generate: bool
    storage: bool
    structural_preview: bool
    rendered_preview: Literal[False] = False
    publish: Literal[False] = False
    private_tasks: PrivateTaskCapabilities = Field(default_factory=PrivateTaskCapabilities)
    private_chat: PrivateChatCapabilities = Field(default_factory=PrivateChatCapabilities)
    reason_pairs: tuple[tuple[str, str], ...] = Field(default=(), exclude=True, repr=False)

    @computed_field
    @property
    def reasons(self) -> dict[str, str]:
        # A fresh JSON mapping cannot mutate the frozen stored reason pairs.
        return dict(self.reason_pairs)
