"""Finite server-created B2 footprints; no model registry or append callbacks."""
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from app.schemas.teaching_assessment import RecipientIssueDTO
from app.services.teaching.types import ASSESSMENT_ACTIONS, exact_identifier

if TYPE_CHECKING:
    from app.models.teaching_assessment import Assignment, AssignmentDraftPrivate, AssignmentVersion, PrivateSpec, ReleasePreview, Release, ReleaseRecipient, SubmissionHead, Submission


@dataclass(frozen=True)
class AssessmentLockSpec:
    purpose: str
    assignment_id: str | None = None
    version_id: str | None = None
    release_preview_id: str | None = None
    release_id: str | None = None
    student_id: str | None = None
    recipient_ids: tuple[str,...] = ()
    audience_issues: tuple[RecipientIssueDTO,...] = ()

    def __post_init__(self):
        if self.purpose not in {action.value for action in ASSESSMENT_ACTIONS}:
            raise ValueError('finite assessment purpose required')
        for value in (self.assignment_id,self.version_id,self.release_preview_id,self.release_id):
            if value is not None and not exact_identifier(value,36): raise ValueError('exact target required')
        if self.student_id is not None and not exact_identifier(self.student_id): raise ValueError('exact student required')
        if not isinstance(self.recipient_ids,tuple) or self.recipient_ids != tuple(sorted(set(self.recipient_ids))) or any(not exact_identifier(item) for item in self.recipient_ids):
            raise ValueError('immutable sorted recipients required')
        if not isinstance(self.audience_issues,tuple) or any(type(item) is not RecipientIssueDTO for item in self.audience_issues):
            raise ValueError('typed audience issues required')


@dataclass(frozen=True)
class AssessmentReceiptDiscovery:
    mode: Literal['absent','existing']
    receipt_id: str | None = None
    result_type: str | None = None
    result_id: str | None = None
    fingerprint: str | None = None

    def __post_init__(self):
        values=(self.receipt_id,self.result_type,self.result_id,self.fingerprint)
        if self.mode=='absent' and any(item is not None for item in values): raise ValueError('absent receipt has no target')
        if self.mode=='existing' and any(item is None for item in values): raise ValueError('existing receipt target required')
        if self.mode not in {'absent','existing'}: raise ValueError('finite discovery mode required')


@dataclass(frozen=True)
class AssessmentLockedRows:
    assignment: 'Assignment | None' = None
    draft_private: 'AssignmentDraftPrivate | None' = None
    version: 'AssignmentVersion | None' = None
    private_spec: 'PrivateSpec | None' = None
    release_preview: 'ReleasePreview | None' = None
    release: 'Release | None' = None
    recipients: tuple['ReleaseRecipient',...] = ()
    head: 'SubmissionHead | None' = None
    parent_submission: 'Submission | None' = None
    target_submission: 'Submission | None' = None


@dataclass(frozen=True)
class RecipientIdentity:
    student_id: str
    enrollment_id: str
    enrollment_revision: int


@dataclass(frozen=True)
class _ScopeShape:
    institution_id: str
    offering_id: str


@dataclass(frozen=True)
class AssignmentCreateShape(_ScopeShape):
    assignment_id: str


@dataclass(frozen=True)
class AssignmentUpdateShape(_ScopeShape):
    assignment_id: str
    before_revision: int


@dataclass(frozen=True)
class PrivateDraftUpdateShape(_ScopeShape):
    assignment_id: str
    before_revision: int


@dataclass(frozen=True)
class VersionCreateShape(_ScopeShape):
    assignment_id: str
    version_id: str
    version_number: int
    source_draft_revision: int


@dataclass(frozen=True)
class ReleasePreviewCreateShape(_ScopeShape):
    assignment_id: str
    version_id: str
    preview_id: str
    audience: tuple[RecipientIdentity,...]


@dataclass(frozen=True)
class ReleaseCreateShape(_ScopeShape):
    assignment_id: str
    version_id: str
    preview_id: str
    release_id: str
    audience: tuple[RecipientIdentity,...]


@dataclass(frozen=True)
class SubmissionCreateShape(_ScopeShape):
    release_id: str
    version_id: str
    student_id: str
    submission_id: str
    parent_submission_id: str | None
    sequence: int


@dataclass(frozen=True)
class RecoveryOnlyShape:
    pass


AssessmentMutationShape = AssignmentCreateShape | AssignmentUpdateShape | PrivateDraftUpdateShape | VersionCreateShape | ReleasePreviewCreateShape | ReleaseCreateShape | SubmissionCreateShape | RecoveryOnlyShape
