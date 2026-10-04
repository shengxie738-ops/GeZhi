"""Pure Teacher Work types. No settings, database, provider or startup imports."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from hashlib import sha256
import json
from typing import TYPE_CHECKING, Callable, Literal, Protocol
from uuid import UUID

if TYPE_CHECKING:
    from app.schemas.teacher_work import CreateTaskRequest, WorkTaskDTO, WorkingPatchRequest


SKILL_REFS = frozenset({"lesson_outline@1", "lesson_package@1", "classroom_exercises@1", "reference_search@1"})
PROVIDER_IDS = frozenset({"arxiv", "openalex", "crossref"})


def canonical_json_bytes(value: object) -> bytes:
    """Encode a JSON value; callers supply content, excluding headers/server times.

    No implicit field filtering, stringification, truncation or non-finite numbers.
    Validated models must first use model_dump(mode="json") with explicit fields.
    """
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def canonical_digest(value: object) -> str:
    return sha256(canonical_json_bytes(value)).hexdigest()


class CatalogCapabilityState(str, Enum):
    IMPLEMENTED = "IMPLEMENTED"
    UNIMPLEMENTED = "UNIMPLEMENTED"
    DISABLED = "DISABLED"


class CatalogConnectionState(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    OPERATIONS_READY = "OPERATIONS_READY"
    CONFIG_MISSING = "CONFIG_MISSING"
    UNSUPPORTED = "UNSUPPORTED"


class CatalogPermissionState(str, Enum):
    READ_ONLY_ALLOWED = "READ_ONLY_ALLOWED"
    AUTHORIZATION_REQUIRED = "AUTHORIZATION_REQUIRED"
    UNAVAILABLE = "UNAVAILABLE"


class CatalogExecutionState(str, Enum):
    NOT_RUN = "NOT_RUN"
    SUCCESS = "SUCCESS"
    EMPTY = "EMPTY"
    PARTIAL_FAILURE = "PARTIAL_FAILURE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


def _subject(value: str) -> None:
    if type(value) is not str or not value or value != value.strip() or len(value) > 255:
        raise ValueError("a nonempty exact server subject is required")


def _uuid(value: UUID) -> None:
    if not isinstance(value, UUID):
        raise ValueError("a server UUID is required")


def _revision(value: int) -> None:
    if type(value) is not int or value < 1:
        raise ValueError("revision must be a positive integer")


@dataclass(frozen=True)
class WorkActor:
    subject: str
    role: Literal["teacher"]
    owner_storage_id: UUID

    def __post_init__(self) -> None:
        _subject(self.subject)
        _uuid(self.owner_storage_id)
        if self.role != "teacher":
            raise ValueError("current teacher identity is required")


@dataclass(frozen=True)
class WorkContext:
    actor_subject: str
    owner_storage_id: UUID
    task_id: UUID
    institution_id: str | None
    offering_id: UUID | None
    input_revision: int
    working_revision: int

    def __post_init__(self) -> None:
        _subject(self.actor_subject)
        _uuid(self.owner_storage_id)
        _uuid(self.task_id)
        _revision(self.input_revision)
        _revision(self.working_revision)
        if (self.institution_id is None) != (self.offering_id is None):
            raise ValueError("offering and institution scope must be paired")
        if self.offering_id is not None:
            _uuid(self.offering_id)
            if type(self.institution_id) is not str or not self.institution_id or len(self.institution_id) > 64:
                raise ValueError("exact institution scope is required")


@dataclass(frozen=True)
class CapabilityFacts:
    """Trusted observations only; no setting or client flag certifies readiness."""
    enabled: bool = False
    schema_ready: bool = False
    transaction_ready: bool = False
    storage_ready: bool = False
    ai_ready: bool = False
    skill_handlers: frozenset[str] = frozenset()
    exporters_ready: bool = False
    current_teacher_allowed: bool = False

    def __post_init__(self) -> None:
        for name in ("enabled", "schema_ready", "transaction_ready", "storage_ready", "ai_ready", "exporters_ready", "current_teacher_allowed"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be a trusted boolean")
        if not isinstance(self.skill_handlers, (set, frozenset)) or not self.skill_handlers <= SKILL_REFS:
            raise ValueError("skill_handlers must contain registered fixed-version references")
        object.__setattr__(self, "skill_handlers", frozenset(self.skill_handlers))


class WorkRepository(Protocol):
    """Commands use a caller-owned transaction; adapters never commit early."""
    def create_task(self, owner: str, request: CreateTaskRequest, idempotency_key: str) -> WorkTaskDTO: ...
    def from_legacy(self, owner: str, draft_id: str) -> WorkTaskDTO: ...
    def get_task(self, owner: str, task_id: UUID) -> WorkTaskDTO: ...
    def patch_working(self, owner: str, task_id: UUID, request: WorkingPatchRequest) -> WorkTaskDTO: ...


class IdentityAccess(Protocol):
    def resolve(self, subject: str) -> WorkActor | None: ...


class OfferingAccess(Protocol):
    def require(self, subject: str, institution_id: str, offering_id: UUID) -> None: ...


class WorkAI(Protocol):
    async def complete(self, prompt: str, *, max_output_tokens: int, timeout_seconds: int) -> str: ...


class WorkEvidence(Protocol):
    def collect(self, ctx: WorkContext, resource_ids: tuple[str, ...]) -> tuple[object, ...]: ...


class WorkArtifacts(Protocol):
    def read_verified(self, ctx: WorkContext, artifact_id: UUID) -> bytes: ...


class WorkExecutor(Protocol):
    def submit(self, run_id: UUID, work: Callable[[], object]) -> None: ...


class WorkClock(Protocol):
    def now(self) -> datetime: ...


@dataclass(frozen=True)
class WorkDependencies:
    repository: WorkRepository
    identity: IdentityAccess
    offering_access: OfferingAccess
    ai: WorkAI
    evidence: WorkEvidence
    artifacts: WorkArtifacts
    executor: WorkExecutor
    clock: WorkClock
