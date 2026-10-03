"""Strict B2 inert-text commands and detached projections. No ORM serialization."""
from datetime import datetime, timezone
import re
import unicodedata
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_serializer, field_validator, model_validator

from app.schemas.teaching import Id, Subject, Digest, Revision
from app.services.teaching.types import exact_identifier

_POSITIVE = Annotated[int, Field(ge=1, le=9223372036854775807)]
_COUNT = Annotated[int, Field(ge=1, le=1000)]
_CURSOR = Annotated[str, StringConstraints(min_length=1, max_length=8192)]
_UTC = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)\Z', re.ASCII)
_TEXT = frozenset({'instructions','rubric','answer_text','private_test_notes','text','description'})


def parse_assessment_utc(value):
    """Explicit UTC wire grammar; never silently truncate fractional precision."""
    if value is None:
        return None
    if isinstance(value, str):
        if not _UTC.fullmatch(value):
            raise ValueError('UTC instant required')
        value = datetime.fromisoformat(value.replace('Z','+00:00'))
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValueError('UTC instant required')
    return value.astimezone(timezone.utc)


class AssessmentDTO(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)

    @field_validator('*')
    @classmethod
    def safe_scalar(cls, value, info):
        if isinstance(value, str):
            if any(unicodedata.category(char).startswith('C') and not (info.field_name in _TEXT and char in '\r\n\t') for char in value):
                raise ValueError('control characters are forbidden')
            if (info.field_name=='id' or info.field_name.endswith('_id')) and not exact_identifier(value, 255 if info.field_name in {'student_id','actor_id','subject_id'} else 36):
                raise ValueError('exact identifier required')
        if isinstance(value, datetime):
            return parse_assessment_utc(value)
        return value

    @field_serializer('*', when_used='json')
    def wire_scalar(self, value):
        if isinstance(value, datetime):
            return value.isoformat(timespec='microseconds').replace('+00:00','Z')
        return value

    @field_validator('timezone', check_fields=False)
    @classmethod
    def known_timezone(cls, value):
        if not exact_identifier(value,64):
            raise ValueError('exact timezone required')
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError,ValueError) as exc:
            raise ValueError('unknown timezone') from exc
        return value


def _byte_limit(value, limit):
    if len(value.encode('utf-8')) > limit:
        raise ValueError('UTF-8 byte limit exceeded')
    return value


class PublicSpec(AssessmentDTO):
    title: Annotated[str,StringConstraints(min_length=1,max_length=200)]
    instructions: str
    rubric: str
    ai_policy: Literal['prohibited','declaration_required','allowed']

    @field_validator('title')
    @classmethod
    def nonblank(cls,value):
        if not value.strip(): raise ValueError('nonblank title required')
        return value

    @field_validator('instructions','rubric')
    @classmethod
    def byte_size(cls,value,info):
        return _byte_limit(value,32768 if info.field_name=='instructions' else 16384)


class PrivateSpecCommand(AssessmentDTO):
    answer_text: str
    private_test_notes: str
    _size = field_validator('answer_text','private_test_notes')(lambda value:_byte_limit(value,32768))


class CreateAssignmentCommand(AssessmentDTO):
    public_spec: PublicSpec


class ReplaceAssignmentDraftCommand(CreateAssignmentCommand):
    expected_revision: _POSITIVE


class ReplacePrivateDraftCommand(AssessmentDTO):
    expected_revision: _POSITIVE
    private_spec: PrivateSpecCommand


class FreezeAssignmentCommand(AssessmentDTO):
    expected_revision: _POSITIVE


class ReleasePreviewCommand(AssessmentDTO):
    version_id: Id
    student_ids: list[Subject] = Field(min_length=1,max_length=1000)
    due_at: datetime | None
    late_policy: Literal['reject']
    _due = field_validator('due_at',mode='before')(parse_assessment_utc)

    @field_validator('student_ids')
    @classmethod
    def exact_unique_subjects(cls,value):
        if any(not exact_identifier(subject) for subject in value):
            raise ValueError('exact subject required')
        if len(set(value)) != len(value):
            raise ValueError('duplicate_recipient')
        return value


class ConfirmReleaseCommand(AssessmentDTO):
    preview_id: Id
    version_id: Id
    public_spec_hash: Digest
    recipient_count: _COUNT
    recipient_digest: Digest
    policy_digest: Digest
    confirmed: Literal[True]

    @field_validator('confirmed',mode='before')
    @classmethod
    def exact_true(cls,value):
        if value is not True: raise ValueError('explicit confirmation required')
        return value


class SubmissionContent(AssessmentDTO):
    kind: Literal['text','code']
    language: Annotated[str,StringConstraints(min_length=1,max_length=32)] | None
    text: Annotated[str,StringConstraints(min_length=1)]
    _size = field_validator('text')(lambda value:_byte_limit(value,262144))

    @model_validator(mode='after')
    def language_binding(self):
        if self.kind=='text' and self.language is not None or self.kind=='code' and not exact_identifier(self.language,32):
            raise ValueError('content language mismatch')
        return self


class AIUsageDeclaration(AssessmentDTO):
    used_ai: bool
    description: Annotated[str,StringConstraints(max_length=4000)]

    @model_validator(mode='after')
    def declaration(self):
        if self.used_ai and not self.description.strip(): raise ValueError('AI usage description required')
        return self


class CreateSubmissionCommand(AssessmentDTO):
    expected_parent_id: Id | None
    content: SubmissionContent
    ai_usage_declaration: AIUsageDeclaration


class RecipientIssueDTO(AssessmentDTO):
    code: Literal['unavailable_or_out_of_scope','duplicate_recipient']
    subject_id: Subject


class RecipientSnapshotDTO(AssessmentDTO):
    student_id: Subject
    enrollment_id: Id
    enrollment_revision: _POSITIVE


class AssessmentPageQuery(AssessmentDTO):
    limit: int = Field(default=50,ge=1,le=100)
    cursor: _CURSOR | None = None


class RecipientPageQuery(AssessmentPageQuery): pass
class SubmissionHistoryQuery(AssessmentPageQuery): pass


class TeacherSubmissionQuery(AssessmentPageQuery):
    student_id: Subject | None = None


class AssignmentDraftDTO(AssessmentDTO):
    id: Id
    offering_id: Id
    draft_revision: _POSITIVE
    public_spec: PublicSpec
    updated_at: datetime


class AuthorAssignmentSummaryDTO(AssessmentDTO):
    projection: Literal['author_draft'] = 'author_draft'
    id: Id
    offering_id: Id
    title: Annotated[str,StringConstraints(min_length=1,max_length=200)]
    draft_revision: _POSITIVE
    updated_at: datetime


class ReleaseAssignmentSummaryDTO(AssessmentDTO):
    projection: Literal['release_frozen'] = 'release_frozen'
    id: Id
    offering_id: Id
    title: Annotated[str,StringConstraints(min_length=1,max_length=200)]
    latest_version_id: Id
    latest_version_number: _POSITIVE
    frozen_at: datetime


class AssignmentPageDTO(AssessmentDTO):
    items: list[AuthorAssignmentSummaryDTO | ReleaseAssignmentSummaryDTO]
    next_cursor: _CURSOR | None
    as_of: datetime


class AssignmentVersionSummaryDTO(AssessmentDTO):
    id: Id
    assignment_id: Id
    version_number: _POSITIVE
    source_draft_revision: _POSITIVE
    title: Annotated[str,StringConstraints(min_length=1,max_length=200)]
    public_spec_hash: Digest
    frozen_at: datetime


class AssignmentVersionPageDTO(AssessmentDTO):
    items: list[AssignmentVersionSummaryDTO]
    next_cursor: _CURSOR | None
    as_of: datetime


class AssignmentVersionDTO(AssessmentDTO):
    id: Id
    assignment_id: Id
    offering_id: Id
    version_number: _POSITIVE
    source_draft_revision: _POSITIVE
    public_spec: PublicSpec
    public_spec_hash: Digest
    frozen_at: datetime


class PrivateSpecDTO(AssessmentDTO):
    assignment_id: Id
    version_id: Id | None
    private_spec: PrivateSpecCommand


class RecipientPageDTO(AssessmentDTO):
    items: list[Subject]
    next_cursor: _CURSOR | None
    as_of: datetime

    @field_validator('items')
    @classmethod
    def subjects(cls,value):
        if any(not exact_identifier(item) for item in value): raise ValueError('exact subject required')
        return value


class ReleasePreviewDTO(AssessmentDTO):
    id: Id
    assignment_id: Id
    version_id: Id
    public_spec_hash: Digest
    recipient_count: _COUNT
    recipient_digest: Digest
    due_at: datetime | None
    timezone: str
    late_policy: Literal['reject']
    policy_digest: Digest
    expires_at: datetime
    first_recipient_page: RecipientPageDTO


class ReleaseDTO(AssessmentDTO):
    id: Id
    assignment_id: Id
    version: AssignmentVersionDTO
    due_at: datetime | None
    timezone: str
    late_policy: Literal['reject']
    released_at: datetime


class ReleaseManagementDTO(ReleaseDTO):
    recipient_count: _COUNT
    recipient_digest: Digest


class SubmissionHistoryItemDTO(AssessmentDTO):
    id: Id
    release_id: Id
    version_id: Id
    parent_submission_id: Id | None
    sequence: _POSITIVE
    content_hash: Digest
    received_at: datetime
    execution_status: Literal['not_available'] = 'not_available'
    assessment_status: Literal['not_implemented'] = 'not_implemented'


class SubmissionDTO(SubmissionHistoryItemDTO):
    content: SubmissionContent
    ai_usage_declaration: AIUsageDeclaration


class TeacherSubmissionDTO(SubmissionDTO):
    student_id: Subject


class SubmissionHistoryDTO(AssessmentDTO):
    items: list[SubmissionHistoryItemDTO]
    current_head_id: Id | None
    next_cursor: _CURSOR | None
    as_of: datetime


class AssignmentAcceptanceDTO(AssessmentDTO):
    assignment_id: Id
    draft_revision: _POSITIVE
    accepted_at: datetime
    _at = field_validator('accepted_at',mode='before')(parse_assessment_utc)


class PrivateDraftAcceptanceDTO(AssignmentAcceptanceDTO): pass


class VersionAcceptanceDTO(AssessmentDTO):
    assignment_id: Id
    version_id: Id
    version_number: _POSITIVE
    source_draft_revision: _POSITIVE
    public_spec_hash: Digest
    frozen_at: datetime
    _at = field_validator('frozen_at',mode='before')(parse_assessment_utc)


class _ReleaseAcceptance(AssessmentDTO):
    assignment_id: Id
    version_id: Id
    public_spec_hash: Digest
    recipient_count: _COUNT
    recipient_digest: Digest
    due_at: datetime | None
    timezone: str
    late_policy: Literal['reject']
    policy_digest: Digest
    _due = field_validator('due_at',mode='before')(parse_assessment_utc)


class ReleasePreviewAcceptanceDTO(_ReleaseAcceptance):
    preview_id: Id
    expires_at: datetime
    accepted_at: datetime
    _at = field_validator('expires_at','accepted_at',mode='before')(parse_assessment_utc)


class ReleaseAcceptanceDTO(_ReleaseAcceptance):
    release_id: Id
    released_at: datetime
    _at = field_validator('released_at',mode='before')(parse_assessment_utc)


class SubmissionAcceptanceDTO(AssessmentDTO):
    submission_id: Id
    release_id: Id
    version_id: Id
    parent_submission_id: Id | None
    sequence: _POSITIVE
    content_hash: Digest
    received_at: datetime
    _at = field_validator('received_at',mode='before')(parse_assessment_utc)
