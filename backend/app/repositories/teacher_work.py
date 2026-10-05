"""Teacher Work command coordinator with an explicit caller-owned transaction.

    This is the pure T2a production command logic, not a SQL persistence adapter.
    Exact rows and original-draft adapters must share the supplied active UoW.
    T2b SQL/JsonStore participation and T3 current identity/namespace resolution
    remain separate integration gates. Nothing here opens, commits or rolls back
    a transaction, starts providers, activates settings or changes the old service.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol
from uuid import UUID

from pydantic import TypeAdapter

from app.schemas.teacher_work import CreateTaskRequest, MessageKey, WorkTaskDTO, WorkingPatchRequest
from app.services.teacher_work.legacy import LegacyLessonPreservationError, normalize_legacy, normalize_legacy_for_task, preserve_legacy_lesson
from app.services.teacher_work.types import WorkActor, canonical_digest


class WorkRepositoryError(Exception):
    """Stable controlled outcome for the later HTTP adapter."""
    def __init__(self, code: str, status_code: int, fields: tuple[str, ...] = ()):
        super().__init__(code)
        self.code = code
        self.status_code = status_code
        self.fields = fields


@dataclass(frozen=True)
class AuthorizedWorkScope:
    """Trusted current authorization returned after locking its footprint."""
    actor: WorkActor
    institution_id: str | None
    offering_id: UUID | None

    def __post_init__(self) -> None:
        if not isinstance(self.actor, WorkActor):
            raise ValueError("a current WorkActor is required")
        if (self.institution_id is None) != (self.offering_id is None):
            raise ValueError("resolved institution and offering must be paired")
        if self.offering_id is not None:
            if not isinstance(self.offering_id, UUID) or type(self.institution_id) is not str or not self.institution_id.strip() or len(self.institution_id) > 64:
                raise ValueError("exact resolved offering scope is required")


@dataclass(frozen=True)
class TaskRecord:
    """Task metadata and server-only durable receipt; no current lesson copy.

    Keys remain exact Unicode here. The deferred SQL adapter must encode them as
    UTF-8 bytes only at its VARBINARY(512) boundary, including trailing spaces.
    """
    task: WorkTaskDTO
    create_idempotency_key: str | None
    create_request_digest: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.task, WorkTaskDTO):
            raise ValueError("strict task metadata is required")
        if (self.create_idempotency_key is None) != (self.create_request_digest is None):
            raise ValueError("create receipt key and digest must be paired")
        if self.create_idempotency_key is not None:
            TypeAdapter(MessageKey).validate_python(self.create_idempotency_key)
            digest = self.create_request_digest
            if type(digest) is not str or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise ValueError("server-derived SHA-256 create digest is required")


@dataclass(frozen=True)
class DraftRecord:
    owner: str
    draft_id: str
    payload: dict
    module: str = "teacher_lesson_prep"
    record_type: str = "draft"


class WorkUnitOfWork(Protocol):
    def in_transaction(self) -> bool: ...
    def flush(self) -> None: ...


class TaskRows(Protocol):
    """Exact task-row primitives. Lease locking does not claim/release a run.

    The owner lease serializes receipt/link/namespace reservations. The SQL
    adapter must enforce the schema uniques as well, without early commits.
    """
    def lock_owner_lease(self, owner: str) -> None: ...
    def owner_storage_ids(self, owner: str) -> tuple[UUID, ...]: ...
    def find_task(self, owner: str, task_id: UUID) -> TaskRecord | None: ...
    def find_task_by_draft(self, owner: str, draft_id: str) -> TaskRecord | None: ...
    def find_task_by_create_key(self, owner: str, key: str) -> TaskRecord | None: ...
    def lock_task(self, owner: str, task_id: UUID) -> TaskRecord | None: ...
    def insert_task(self, row: TaskRecord) -> None: ...
    def compare_and_swap_task(self, owner: str, task_id: UUID, expected_revision: int, row: TaskRecord) -> bool: ...
    def version_belongs_to(self, owner: str, task_id: UUID, version_id: UUID) -> bool: ...


class OriginalDrafts(Protocol):
    """Exact owner/module/type/key reads; create-only reservation, flush writes.

    The adapter must share this UoW and must never call legacy upsert/atomic_store
    in a mode that commits. An absent draft reservation is protected by the
    locked owner lease plus the actual persistence constraints, not this protocol.
    """
    def lock_draft(self, owner: str, draft_id: str) -> DraftRecord | None: ...
    def create_draft(self, row: DraftRecord) -> None: ...
    def write_draft(self, row: DraftRecord) -> None: ...


class TeacherWorkRepository:
    """Implements the four original WorkRepository signatures, structurally.

    authorize_locked is mandatory: it locks current account/offering authority
    and returns the current actor/scope. Its owner namespace must come from a
    stable persisted server resolver; this coordinator only checks consistency
    with existing tasks. No username hash or per-request namespace is generated.
    The caller must roll back the entire UoW after any command exception.
    """
    def __init__(self, *, uow: WorkUnitOfWork, rows: TaskRows, drafts: OriginalDrafts,
                 authorize_locked: Callable[[str, UUID | None, str | None], AuthorizedWorkScope],
                 clock: Callable[[], datetime], new_uuid: Callable[[], UUID],
                 resolve_reference: Callable[[str, UUID, UUID], bool] | None = None):
        self.uow = uow
        self.rows = rows
        self.drafts = drafts
        self.authorize_locked = authorize_locked
        self.clock = clock
        self.new_uuid = new_uuid
        self.resolve_reference = resolve_reference

    def _active(self) -> None:
        if self.uow.in_transaction() is not True:
            raise WorkRepositoryError("TRANSACTION_REQUIRED", 503)

    def _authorize(self, owner: str, offering_id: UUID | None, institution_id: str | None) -> AuthorizedWorkScope:
        scope = self.authorize_locked(owner, offering_id, institution_id)
        if not isinstance(scope, AuthorizedWorkScope) or scope.actor.subject != owner:
            raise WorkRepositoryError("NOT_FOUND", 404)
        if scope.offering_id != offering_id or (institution_id is not None and scope.institution_id != institution_id):
            raise WorkRepositoryError("NOT_FOUND", 404)
        self.rows.lock_owner_lease(owner)
        if any(namespace != scope.actor.owner_storage_id for namespace in self.rows.owner_storage_ids(owner)):
            raise WorkRepositoryError("OWNER_NAMESPACE_MISMATCH", 503)
        return scope

    def _instant(self) -> datetime:
        now = self.clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("trusted timezone-aware UTC clock required")
        return now.astimezone(timezone.utc)

    def _uuid(self) -> UUID:
        value = self.new_uuid()
        if not isinstance(value, UUID):
            raise ValueError("trusted server UUID source required")
        return value

    @staticmethod
    def _draft(draft: DraftRecord | None, owner: str, draft_id: str) -> DraftRecord:
        if draft is None or draft.owner != owner or draft.draft_id != draft_id or draft.module != "teacher_lesson_prep" or draft.record_type != "draft":
            raise WorkRepositoryError("NOT_FOUND", 404)
        if type(draft.payload) is not dict or draft.payload.get("draft_id") != draft_id:
            raise WorkRepositoryError("DRAFT_METADATA_UNAVAILABLE", 503)
        return draft

    @staticmethod
    def _bound(row: TaskRecord | None, owner: str, draft_id: str, scope: AuthorizedWorkScope) -> TaskRecord:
        if row is None or row.task.owner_subject != owner or row.task.lesson_draft_id != draft_id:
            raise WorkRepositoryError("NOT_FOUND", 404)
        task = row.task
        if task.owner_storage_id != scope.actor.owner_storage_id:
            raise WorkRepositoryError("OWNER_NAMESPACE_MISMATCH", 503)
        if (task.institution_id, task.offering_id) != (scope.institution_id, scope.offering_id):
            raise WorkRepositoryError("NOT_FOUND", 404)
        return row

    def _locked_task(self, owner: str, task_id: UUID) -> tuple[TaskRecord, DraftRecord]:
        self._active()
        provisional = self.rows.find_task(owner, task_id)  # Discovery only, no task lock before the footprint.
        if provisional is None or provisional.task.owner_subject != owner or provisional.task.task_id != task_id:
            raise WorkRepositoryError("NOT_FOUND", 404)
        scope = self._authorize(owner, provisional.task.offering_id, provisional.task.institution_id)
        draft_id = provisional.task.lesson_draft_id
        draft = self._draft(self.drafts.lock_draft(owner, draft_id), owner, draft_id)
        row = self._bound(self.rows.lock_task(owner, task_id), owner, draft_id, scope)
        if row.task.task_id != task_id:
            raise WorkRepositoryError("NOT_FOUND", 404)
        return row, draft

    def _flush(self) -> None:
        self._active()
        self.uow.flush()

    def create_task(self, owner: str, request: CreateTaskRequest, idempotency_key: str) -> WorkTaskDTO:
        self._active()
        key = TypeAdapter(MessageKey).validate_python(idempotency_key)
        scope = self._authorize(owner, request.offering_id, None)
        digest = canonical_digest({"request": request.model_dump(mode="json"),
                                   "institution_id": scope.institution_id,
                                   "offering_id": str(scope.offering_id) if scope.offering_id is not None else None})
        receipt = self.rows.find_task_by_create_key(owner, key)
        if receipt is not None:
            if receipt.create_request_digest != digest:
                raise WorkRepositoryError("IDEMPOTENCY_CONFLICT", 409)
            draft_id = receipt.task.lesson_draft_id
            self._draft(self.drafts.lock_draft(owner, draft_id), owner, draft_id)
            locked = self._bound(self.rows.lock_task(owner, receipt.task.task_id), owner, draft_id, scope)
            if locked.create_idempotency_key != key or locked.create_request_digest != digest:
                raise WorkRepositoryError("IDEMPOTENCY_CONFLICT", 409)
            return locked.task
        invalid = tuple(name for name in ("title", "topic", "audience") if not getattr(request, name).strip())
        if invalid:
            raise WorkRepositoryError("INVALID_TASK_METADATA", 422, invalid)
        now = self._instant()
        task_id, draft_id = self._uuid(), str(self._uuid())
        content = {"title": request.title, "topic": request.topic, "audience": request.audience,
                   "course_name": "", "duration_minutes": request.duration_minutes}
        normalization = normalize_legacy(content)
        payload = {"draft_id": draft_id, "title": request.title, "topic": request.topic,
                   "duration_minutes": request.duration_minutes, "resource_ids": list(request.resource_ids),
                   "content": content, "status": "DRAFT", "created_at": now.isoformat(), "updated_at": now.isoformat(),
                   "teacher_work": {"requirements": "", "base_version_id": None,
                                    "needs_normalization_fields": normalization.needs_normalization_fields}}
        task = WorkTaskDTO(task_id=task_id, owner_subject=owner, owner_storage_id=scope.actor.owner_storage_id,
                           institution_id=scope.institution_id, offering_id=scope.offering_id,
                           title=request.title, topic=request.topic, audience=request.audience,
                           duration_minutes=request.duration_minutes, target_slide_count=request.target_slide_count,
                           lesson_draft_id=draft_id, input_revision=1, working_revision=1,
                           created_at=now, updated_at=now)
        self.drafts.create_draft(DraftRecord(owner, draft_id, payload))
        self.rows.insert_task(TaskRecord(task, key, digest))
        self._flush()
        return task

    def from_legacy(self, owner: str, draft_id: str) -> WorkTaskDTO:
        self._active()
        provisional = self.rows.find_task_by_draft(owner, draft_id)
        scope = self._authorize(owner, provisional.task.offering_id if provisional else None,
                                provisional.task.institution_id if provisional else None)
        draft = self._draft(self.drafts.lock_draft(owner, draft_id), owner, draft_id)
        existing = self.rows.find_task_by_draft(owner, draft_id)
        if existing is not None:
            return self._bound(self.rows.lock_task(owner, existing.task.task_id), owner, draft_id, scope).task
        payload = deepcopy(draft.payload)
        content = payload.get("content")
        try:
            normalization = normalize_legacy(content)
        except (TypeError, ValueError):
            raise WorkRepositoryError("NORMALIZATION_REQUIRED", 422, ("content",)) from None
        fields = []
        for name in ("title", "topic"):
            value = payload.get(name)
            if type(value) is not str or not value.strip() or len(value) > 200:
                fields.append(name)
        audience = content.get("audience")
        if type(audience) is not str or not audience.strip() or len(audience) > 200:
            fields.append("content.audience")
        duration = payload.get("duration_minutes")
        if type(duration) is not int or not 1 <= duration <= 600:
            fields.append("duration_minutes")
        resources = payload.get("resource_ids")
        if type(resources) is not list or not 1 <= len(resources) <= 10 or any(type(value) is not str or not 1 <= len(value) <= 255 for value in resources) or len(set(resources)) != len(resources):
            fields.append("resource_ids")
        if fields:
            raise WorkRepositoryError("NORMALIZATION_REQUIRED", 422, tuple(sorted(fields)))
        normalization = normalize_legacy_for_task(content, duration)
        now = self._instant()
        task = WorkTaskDTO(task_id=self._uuid(), owner_subject=owner, owner_storage_id=scope.actor.owner_storage_id,
                           institution_id=scope.institution_id, offering_id=scope.offering_id,
                           title=payload["title"], topic=payload["topic"], audience=audience,
                           duration_minutes=duration, target_slide_count=8, lesson_draft_id=draft_id,
                           input_revision=1, working_revision=1, created_at=now, updated_at=now)
        payload["teacher_work"] = {"requirements": "", "base_version_id": None,
                                   "needs_normalization_fields": normalization.needs_normalization_fields}
        # Linking preserves original content, ID and timestamps; only the server
        # working metadata envelope is added, never an outline/version/approval.
        self.rows.insert_task(TaskRecord(task, None, None))
        self.drafts.write_draft(DraftRecord(owner, draft_id, payload))
        self._flush()
        return task

    def get_task(self, owner: str, task_id: UUID) -> WorkTaskDTO:
        row, _draft = self._locked_task(owner, task_id)
        return row.task

    @staticmethod
    def _metadata(payload: dict) -> dict:
        metadata = payload.get("teacher_work")
        if type(metadata) is not dict or type(metadata.get("requirements")) is not str or len(metadata["requirements"]) > 4000:
            raise WorkRepositoryError("DRAFT_METADATA_UNAVAILABLE", 503)
        base = metadata.get("base_version_id")
        if base is not None:
            try:
                if type(base) is not str or str(UUID(base)) != base:
                    raise ValueError("exact base UUID required")
            except ValueError:
                raise WorkRepositoryError("DRAFT_METADATA_UNAVAILABLE", 503) from None
        return metadata

    def patch_working(self, owner: str, task_id: UUID, request: WorkingPatchRequest) -> WorkTaskDTO:
        row, draft = self._locked_task(owner, task_id)
        task = row.task
        if task.working_revision != request.expected_revision:
            raise WorkRepositoryError("REVISION_CONFLICT", 409)
        payload = deepcopy(draft.payload)
        metadata = self._metadata(payload)
        updates = {}
        input_changed = False
        changes = request.changes
        for name in changes.model_fields_set:
            value = getattr(changes, name)
            if value is None:
                raise WorkRepositoryError("INVALID_WORKING_CHANGE", 422, (name,))
            if name == "requirements":
                input_changed |= metadata["requirements"] != value
                metadata["requirements"] = value
            elif name == "lesson":
                if value.duration_minutes != task.duration_minutes:
                    raise WorkRepositoryError("LESSON_DURATION_MISMATCH", 422)
                try:
                    lesson = preserve_legacy_lesson(payload.get("content"), value.model_dump(mode="json"))
                except LegacyLessonPreservationError as error:
                    raise WorkRepositoryError("NORMALIZATION_REQUIRED", 422, error.fields) from None
                input_changed |= payload.get("content") != lesson
                payload["content"] = lesson
            elif name == "resource_ids":
                input_changed |= payload.get("resource_ids") != value
                payload["resource_ids"] = list(value)
            else:
                if name == "reference_ids" and value:
                    if self.resolve_reference is None:
                        raise WorkRepositoryError("REFERENCE_UNAVAILABLE", 503)
                    if any(self.resolve_reference(owner, task_id, reference_id) is not True for reference_id in value):
                        raise WorkRepositoryError("REFERENCE_NOT_FOUND", 404)
                selected = tuple(value) if name in {"skill_refs", "plugin_ids", "reference_ids"} else value
                input_changed |= getattr(task, name) != selected
                updates[name] = selected
        if "base_version_id" in request.model_fields_set:
            base = request.base_version_id
            if base is not None and self.rows.version_belongs_to(owner, task_id, base) is not True:
                raise WorkRepositoryError("BASE_VERSION_NOT_FOUND", 404)
            stored_base = str(base) if base is not None else None
            input_changed |= metadata.get("base_version_id") != stored_base
            metadata["base_version_id"] = stored_base
        try:
            metadata["needs_normalization_fields"] = normalize_legacy_for_task(payload["content"], task.duration_minutes).needs_normalization_fields
        except (KeyError, TypeError, ValueError):
            raise WorkRepositoryError("DRAFT_METADATA_UNAVAILABLE", 503) from None
        now = self._instant()
        payload["updated_at"] = now.isoformat()
        updates.update(working_revision=task.working_revision + 1, updated_at=now)
        if input_changed:
            updates.update(input_revision=task.input_revision + 1, current_outline_id=None)
        saved = WorkTaskDTO(**{**task.model_dump(), **updates})
        # Draft write and exact-owner/task/revision CAS share the caller's UoW.
        # A failed CAS/flush must propagate; only the caller may roll back.
        self.drafts.write_draft(DraftRecord(owner, task.lesson_draft_id, payload))
        if self.rows.compare_and_swap_task(owner, task_id, request.expected_revision,
                                           TaskRecord(saved, row.create_idempotency_key, row.create_request_digest)) is not True:
            raise WorkRepositoryError("REVISION_CONFLICT", 409)
        self._flush()
        return saved
