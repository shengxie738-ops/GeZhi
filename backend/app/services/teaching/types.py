"""B1 authority values. Snapshots are transaction-local, never bearer grants.

The process owner supplies/replaces one complete immutable policy generation.
Default construction is disabled; this module never reads mutable Settings.
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Mapping, Protocol
import unicodedata

if TYPE_CHECKING:
    from app.models.teaching import Course, Enrollment, Offering, TeachingRole, WriteReceipt
    from app.models.user_account import UserAccount


def exact_identifier(value: str, maximum: int = 255) -> bool:
    return (isinstance(value, str) and 0 < len(value) <= maximum and value == value.strip()
            and not any(unicodedata.category(char).startswith("C") for char in value))


class Permission(str, Enum):
    COURSE_MANAGE = "COURSE_MANAGE"
    ROSTER_MANAGE = "ROSTER_MANAGE"
    ROLES_MANAGE = "ROLES_MANAGE"
    AUTHOR = "AUTHOR"
    RELEASE = "RELEASE"
    SUBMISSION_VIEW = "SUBMISSION_VIEW"
    PRIVATE_SPEC_VIEW = "PRIVATE_SPEC_VIEW"
    REVIEW = "REVIEW"
    PUBLISH = "PUBLISH"


MANAGEMENT_PERMISSIONS = frozenset({Permission.COURSE_MANAGE, Permission.ROSTER_MANAGE, Permission.ROLES_MANAGE})
ASSESSMENT_PERMISSIONS = frozenset(Permission) - MANAGEMENT_PERMISSIONS


class TeachingAction(str, Enum):
    CREATE_COURSE = "course_create"
    UPDATE_COURSE = "course_update"
    CREATE_OFFERING = "offering_create"
    READ_COURSE = "course_read"
    READ_OFFERING = "offering_read"
    READ_ENROLLMENT = "enrollment_read"
    COURSE_MANAGE = "course_manage"
    ROSTER_MANAGE = "roster_manage"
    ROLES_MANAGE = "roles_manage"
    AUTHOR = "author"
    RELEASE = "release"
    SUBMISSION_VIEW = "submission_view"
    PRIVATE_SPEC_VIEW = "private_spec_view"
    REVIEW = "review"
    PUBLISH = "publish"


ACTION_PERMISSION = {
    TeachingAction.COURSE_MANAGE: Permission.COURSE_MANAGE,
    TeachingAction.ROSTER_MANAGE: Permission.ROSTER_MANAGE,
    TeachingAction.ROLES_MANAGE: Permission.ROLES_MANAGE,
    TeachingAction.AUTHOR: Permission.AUTHOR,
    TeachingAction.RELEASE: Permission.RELEASE,
    TeachingAction.SUBMISSION_VIEW: Permission.SUBMISSION_VIEW,
    TeachingAction.PRIVATE_SPEC_VIEW: Permission.PRIVATE_SPEC_VIEW,
    TeachingAction.REVIEW: Permission.REVIEW,
    TeachingAction.PUBLISH: Permission.PUBLISH,
}


@dataclass(frozen=True)
class TeachingPolicyInputs:
    institution_id: str = ""
    enabled: bool = False
    assignments_enabled: bool = False
    feedback_enabled: bool = False
    revisions_enabled: bool = False
    trusted_roster_json: str = "{}"
    trusted_delegations_json: str = "{}"
    generation: str = "default-off"

    def __post_init__(self):
        for name in ("enabled", "assignments_enabled", "feedback_enabled", "revisions_enabled"):
            if type(getattr(self, name)) is not bool:
                raise ValueError("feature states must be booleans")
        if not isinstance(self.institution_id, str):
            raise ValueError("institution must be a string")
        if not exact_identifier(self.generation, 255):
            raise ValueError("exact generation identifier required")
        if not isinstance(self.trusted_roster_json, str) or not isinstance(self.trusted_delegations_json, str):
            raise ValueError("policy documents must be immutable JSON strings")


DEFAULT_POLICY_INPUTS = TeachingPolicyInputs()


@dataclass(frozen=True)
class ScopeRef:
    institution_id: str
    kind: str
    id: str

    def __post_init__(self):
        if self.kind not in {"institution", "course", "offering"}:
            raise ValueError("unsupported scope")
        if not exact_identifier(self.institution_id, 64) or not exact_identifier(self.id, 64 if self.kind == "institution" else 36):
            raise ValueError("exact stable scope required")
        if self.kind == "institution" and self.id != self.institution_id:
            raise ValueError("institution scope must name its institution")


@dataclass(frozen=True)
class ObjectRef:
    """Server-created loaded-row reference; no assigned/client-authority field."""
    kind: str
    id: str
    institution_id: str
    course_id: str | None = None
    offering_id: str | None = None

    def __post_init__(self):
        if not exact_identifier(self.kind, 64) or not exact_identifier(self.id, 36) or not exact_identifier(self.institution_id, 64):
            raise ValueError("exact object reference required")
        for value in (self.course_id, self.offering_id):
            if value is not None and not exact_identifier(value, 36):
                raise ValueError("exact object scope required")


@dataclass(frozen=True)
class AuthorizationContext:
    """Internal refreshed row footprint; never serialize this object to a client."""
    actor_account: "UserAccount"
    scope: ScopeRef
    source_account: "UserAccount | None" = None
    course: "Course | None" = None
    offering: "Offering | None" = None
    role: "TeachingRole | None" = None
    enrollment: "Enrollment | None" = None
    object_ref: ObjectRef | None = None
    receipt: "WriteReceipt | None" = None


@dataclass(frozen=True)
class LockedContext(AuthorizationContext):
    """Complete refreshed footprint; construction alone is never lock proof."""
    accounts: Mapping[str, Any] = field(default_factory=dict)
    roles: Mapping[str, Any] = field(default_factory=dict)
    enrollments: Mapping[str, Any] = field(default_factory=dict)
    preview: Any = None
    preview_footprint: "PreviewFootprint | None" = None
    lock_plan: "LockPlan | None" = None
    pre_mutation: Mapping[str, Any] = field(default_factory=dict)
    session: Any = field(default=None, repr=False, compare=False)
    authorization: "AuthorizationSnapshot | None" = None
    policy: Any = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class AuthorizationSnapshot:
    actor_id: str
    account_role: str
    source_teacher_id: str | None
    scope: ScopeRef
    teaching: bool
    learning: bool
    permissions: frozenset[Permission]
    role_scope: str | None
    role_id: str | None
    role_revision: int | None
    enrollment_id: str | None
    enrollment_revision: int | None
    learner_ceiling: frozenset[str]
    policy_digest: str
    policy_generation: str
    checked_at: datetime


@dataclass(frozen=True)
class WriteIntent:
    actor_id: str
    action: TeachingAction
    scope: ScopeRef
    target_id: str | None
    idempotency_key: str
    canonical_payload: Mapping[str, Any]
    canonicalization_version: int
    request_hash: str


@dataclass(frozen=True)
class ReceiptLookup:
    actor_id: str
    action: TeachingAction
    scope: ScopeRef
    idempotency_key: str

    @classmethod
    def from_intent(cls, intent: WriteIntent):
        return cls(intent.actor_id, intent.action, intent.scope, intent.idempotency_key)


@dataclass(frozen=True)
class LockPlan:
    root_course_id: str | None = None
    root_offering_id: str | None = None
    account_ids: tuple[str, ...] = ()
    role_subject_ids: tuple[str, ...] = ()
    enrollment_subject_ids: tuple[str, ...] = ()
    preview_id: str | None = None
    receipt_lookup: ReceiptLookup | None = None
    target_subject_id: str | None = None


@dataclass(frozen=True)
class PreviewFootprint:
    preview_id: str
    institution_id: str
    offering_id: str
    actor_id: str
    content_fingerprint: str
    target_ids: tuple[str, ...]
    relationship_subject_ids: tuple[str, ...]


@dataclass(frozen=True)
class MutationResult:
    result_type: str
    result_id: str
    original_result: Mapping[str, Any]
    revision_kind: str
    before_revision: int
    after_revision: int
    effect_metadata: Mapping[str, Any]
    http_status: int


@dataclass(frozen=True)
class WriteResult:
    """Provisional until the owning HTTP adapter commits successfully.

    Both projections are detached copies, never live mutable ORM state.
    """
    receipt: Any
    result: dict[str, Any]
    replayed: bool


class WriteOperation(Protocol):
    """Server-owned implementation, never selected or supplied by a client.

    Collect only the complete declared footprint. validate_new/apply_new use
    loaded rows and context.session.add, never queries, external calls, commits,
    another scope, or extra locks. New mutation bodies belong to later tasks.
    """
    def collect_locks(self, session, intent: WriteIntent, locked_roots: LockedContext,
                      preview_footprint: PreviewFootprint | None = None) -> LockPlan: ...
    def validate_new(self, context: LockedContext, command: Mapping[str, Any], at: datetime) -> None: ...
    def apply_new(self, context: LockedContext, command: Mapping[str, Any], at: datetime) -> MutationResult: ...
