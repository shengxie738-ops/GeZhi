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

from app.schemas.teacher_work import ChatCommand, ChatResult, CreateTaskRequest, MessageKey, RunDTO, WorkMessageDTO, WorkTaskDTO, WorkingPatchRequest
from app.services.teacher_work.run_persistence import (
    ChatCallReservation, ChatCompletionReceipt, ChatRequestObservation, ChatRunAdmission,
    ChatRunOutcome, PreparedChatCompletion, ProviderCallToken, StoredRunState, chat_result_from_message,
    encode_work_key, matches_active_call, validate_chat_completion,
)
from app.services.teacher_work.runs import (
    OwnerLeaseFacts, WorkBudget, WorkRunError, cancel_chat_run, chat_absolute_deadline,
    chat_call_limits, chat_request_digest, check_chat_commit, match_chat_replay,
    require_owner_lease_available,
)
from app.services.teacher_work.legacy import LegacyLessonPreservationError, normalize_legacy, normalize_legacy_for_task, preserve_legacy_lesson
from app.services.teacher_work.types import WorkActor, WorkContext, canonical_digest


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


class ChatRows(Protocol):
    """Same caller-root row primitives; no dispatch or commit permission."""
    def lease(self, owner: str) -> OwnerLeaseFacts: ...
    def find_run_by_key(self, owner: str, task_id: UUID, kind: str, encoded_key: bytes) -> StoredRunState | None: ...
    def lock_run(self, owner: str, task_id: UUID, run_id: UUID) -> StoredRunState | None: ...
    def find_user_message(self, owner: str, task_id: UUID, encoded_key: bytes) -> WorkMessageDTO | None: ...
    def find_completion(self, owner: str, task_id: UUID, run_id: UUID) -> tuple[ChatCompletionReceipt, WorkMessageDTO] | None: ...
    def insert_run(self, state: StoredRunState) -> None: ...
    def insert_user_message(self, message: WorkMessageDTO) -> None: ...
    def insert_completion(self, message: WorkMessageDTO, receipt: ChatCompletionReceipt) -> None: ...
    def cas_run(self, before: StoredRunState, after: StoredRunState) -> bool: ...
    def cas_lease(self, before: OwnerLeaseFacts, after: OwnerLeaseFacts) -> bool: ...


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
                 resolve_reference: Callable[[str, UUID, UUID], bool] | None = None,
                 run_rows: ChatRows | None = None):
        self.uow = uow
        self.rows = rows
        self.drafts = drafts
        self.authorize_locked = authorize_locked
        self.clock = clock
        self.new_uuid = new_uuid
        self.resolve_reference = resolve_reference
        self.run_rows = run_rows

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

    def get_private_snapshot(self, owner: str, task_id: UUID):
        from app.schemas.teacher_work import PrivateTaskSnapshot, PrivateWorkingSnapshot
        row, draft = self._locked_task(owner, task_id)
        metadata = self._metadata(draft.payload)
        try:
            return PrivateTaskSnapshot(task=WorkTaskDTO.model_validate(row.task.model_dump()),
                working=PrivateWorkingSnapshot(requirements=metadata["requirements"],
                    resource_ids=deepcopy(draft.payload["resource_ids"]),
                    needs_normalization_fields=deepcopy(metadata["needs_normalization_fields"])))
        except (KeyError, TypeError, ValueError):
            raise WorkRepositoryError("DRAFT_METADATA_UNAVAILABLE", 503) from None

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

    # Chat operations produce uncommitted candidates. The dedicated request
    # owner, never this coordinator, performs final current admission and commit.
    _CHAT_ERRORS = frozenset({"WORK_AI_UNAVAILABLE", "WORK_AI_TIMEOUT", "WORK_AI_RATE_LIMITED",
        "WORK_AI_UPSTREAM_FAILED", "WORK_AI_INVALID_RESPONSE", "WORK_EVIDENCE_UNAVAILABLE",
        "WORK_EXECUTION_UNAVAILABLE"})

    def _chat_rows(self) -> ChatRows:
        self._active()
        if self.run_rows is None:
            raise WorkRepositoryError("RUN_PERSISTENCE_UNAVAILABLE", 503)
        return self.run_rows

    def _chat_task(self, owner: str, task_id: UUID) -> tuple[WorkTaskDTO, WorkContext]:
        self._chat_rows()
        row, _draft = self._locked_task(owner, task_id)
        task = row.task
        try:
            WorkTaskDTO.model_validate(task.model_dump())
        except (TypeError, ValueError):
            raise WorkRunError("INVALID_STORED_TASK", 503) from None
        return task, WorkContext(task.owner_subject, task.owner_storage_id, task.task_id,
            task.institution_id, task.offering_id, task.input_revision, task.working_revision)

    @staticmethod
    def _chat_state(owner: str, task_id: UUID, state: StoredRunState | None) -> StoredRunState:
        if state is None:
            raise WorkRepositoryError("NOT_FOUND", 404)
        if type(state) is not StoredRunState:
            raise WorkRunError("INVALID_STORED_RUN", 503)
        StoredRunState.__post_init__(state)
        run = state.run
        if (run.owner, run.task_id) != (owner, task_id):
            raise WorkRepositoryError("NOT_FOUND", 404)
        if run.kind != "chat" or run.stage not in {"PENDING", "CHAT_RUNNING", "COMPLETE", "FAILED", "CANCELLED", "INTERRUPTED"}:
            raise WorkRunError("INVALID_STORED_RUN", 503)
        return state

    def _chat_lease(self, ctx: WorkContext) -> OwnerLeaseFacts:
        lease = self._chat_rows().lease(ctx.actor_subject)
        if type(lease) is not OwnerLeaseFacts:
            raise WorkRunError("INVALID_LEASE", 503)
        OwnerLeaseFacts.__post_init__(lease)
        if (lease.owner, lease.owner_storage_id) != (ctx.actor_subject, ctx.owner_storage_id):
            raise WorkRunError("OWNER_NAMESPACE_MISMATCH", 503)
        return lease

    def _chat_receipt(self, task: WorkTaskDTO, ctx: WorkContext, command: ChatCommand, key: str) -> ChatRunAdmission | None:
        rows = self._chat_rows()
        state = rows.find_run_by_key(ctx.actor_subject, ctx.task_id, "chat", encode_work_key(key))
        if state is None:
            return None
        state = self._chat_state(ctx.actor_subject, ctx.task_id, state)
        match_chat_replay(ctx, command, key, state.run)
        user = rows.find_user_message(ctx.actor_subject, ctx.task_id, encode_work_key(command.payload.client_message_key))
        try:
            if not isinstance(user, WorkMessageDTO):
                raise ValueError("missing user receipt")
            WorkMessageDTO.model_validate(user.model_dump())
            if ((user.owner, user.task_id, user.role, user.run_id, user.client_message_key, user.plain_text)
                    != (ctx.actor_subject, ctx.task_id, "user", state.run.run_id, command.payload.client_message_key, command.payload.text)
                    or user.result_type is not None or user.omitted_context is not None or user.result_refs):
                raise ValueError("inconsistent user receipt")
        except (TypeError, ValueError):
            raise WorkRunError("RUN_RECEIPT_MISMATCH", 503) from None
        return ChatRunAdmission(task, ctx, state, user, self._chat_lease(ctx), False)

    def inspect_chat_request(self, owner: str, task_id: UUID, command: ChatCommand, key: str) -> ChatRequestObservation:
        chat_request_digest(command)
        encode_work_key(key)
        task, ctx = self._chat_task(owner, task_id)
        return ChatRequestObservation(task, ctx, self._chat_receipt(task, ctx, command, key))

    def admit_chat(self, owner: str, task_id: UUID, command: ChatCommand, key: str, *,
                   process_instance: UUID, configured_timeout_seconds: int) -> ChatRunAdmission:
        digest = chat_request_digest(command)
        encode_work_key(key)
        if type(process_instance) is not UUID:
            raise WorkRunError("INVALID_CALL_TOKEN", 503)
        task, ctx = self._chat_task(owner, task_id)
        replay = self._chat_receipt(task, ctx, command, key)
        if replay is not None:
            return replay
        if command.input_revision != task.input_revision:
            raise WorkRunError("STALE_INPUT_REVISION", 409)
        rows, lease = self._chat_rows(), self._chat_lease(ctx)
        require_owner_lease_available(ctx, lease)
        if rows.find_user_message(owner, task_id, encode_work_key(command.payload.client_message_key)) is not None:
            raise WorkRunError("MESSAGE_KEY_CONFLICT", 409)
        now = self._instant()
        run = RunDTO(run_id=self._uuid(), owner=owner, task_id=task_id, kind="chat", skill_ref=None,
            input_revision=command.input_revision, idempotency_key=key, request_digest=digest,
            stage="PENDING", attempt=1, provider_call_count=0,
            deadline=chat_absolute_deadline(now, configured_timeout_seconds))
        state = StoredRunState(run, 0, None)
        message = WorkMessageDTO(message_id=self._uuid(), task_id=task_id, owner=owner,
            client_message_key=command.payload.client_message_key, role="user", plain_text=command.payload.text,
            run_id=run.run_id, created_at=now)
        reserved = OwnerLeaseFacts(owner, ctx.owner_storage_id, run.run_id, process_instance, run.deadline, lease.revision + 1)
        # Run FK target first; all three writes remain inside the supplied root.
        rows.insert_run(state)
        rows.insert_user_message(message)
        if rows.cas_lease(lease, reserved) is not True:
            raise WorkRunError("OWNER_LEASE_LOST", 409)
        self._flush()
        return ChatRunAdmission(task, ctx, state, message, reserved, True)

    def _chat_completion(self, state: StoredRunState) -> tuple[ChatCompletionReceipt, WorkMessageDTO] | None:
        run = state.run
        pair = self._chat_rows().find_completion(run.owner, run.task_id, run.run_id)
        if pair is None:
            if run.stage == "COMPLETE":
                raise WorkRunError("INVALID_CHAT_COMPLETION", 503)
            return None
        if type(pair) is not tuple or len(pair) != 2 or type(pair[0]) is not ChatCompletionReceipt:
            raise WorkRunError("INVALID_CHAT_COMPLETION", 503)
        receipt, message = pair
        if validate_chat_completion(run, message, receipt.run_id) != receipt or run.stage != "COMPLETE" or state.active_call is not None:
            raise WorkRunError("INVALID_CHAT_COMPLETION", 503)
        return receipt, message

    def get_chat_run(self, owner: str, task_id: UUID, run_id: UUID) -> ChatRunOutcome:
        task, ctx = self._chat_task(owner, task_id)
        state = self._chat_state(owner, task_id, self._chat_rows().lock_run(owner, task_id, run_id))
        lease = self._chat_lease(ctx)
        pair = self._chat_completion(state)
        if pair is not None and lease.active_run_id == run_id:
            raise WorkRunError("INVALID_CHAT_COMPLETION", 503)
        return ChatRunOutcome(task, state, lease, pair[0] if pair is not None else None)

    @staticmethod
    def _chat_linked_lease(ctx: WorkContext, state: StoredRunState, lease: OwnerLeaseFacts, process_instance: UUID) -> None:
        if (type(process_instance) is not UUID or lease.owner != ctx.actor_subject
                or lease.owner_storage_id != ctx.owner_storage_id or lease.active_run_id != state.run.run_id
                or lease.process_instance != process_instance):
            raise WorkRunError("OWNER_LEASE_LOST", 409)

    def reserve_chat_call(self, owner: str, task_id: UUID, run_id: UUID, *, process_instance: UUID,
                          configured_output_tokens: int, configured_timeout_seconds: int,
                          repair: bool = False) -> ChatCallReservation:
        task, ctx = self._chat_task(owner, task_id)
        rows = self._chat_rows()
        before = self._chat_state(owner, task_id, rows.lock_run(owner, task_id, run_id))
        lease = self._chat_lease(ctx)
        self._chat_linked_lease(ctx, before, lease, process_instance)
        if before.run.input_revision != ctx.input_revision:
            raise WorkRunError("STALE_INPUT_REVISION", 409)
        if before.run.cancelled_at is not None:
            raise WorkRunError("RUN_CANCELLED", 409)
        if before.run.stage not in {"PENDING", "CHAT_RUNNING"} or before.active_call is not None:
            raise WorkRunError("RUN_NOT_ACTIVE", 409)
        now = self._instant()
        limits = chat_call_limits(configured_output_tokens, configured_timeout_seconds, deadline=before.run.deadline, now=now)
        if now >= lease.expires_at:
            raise WorkRunError("OWNER_LEASE_LOST", 409)
        budget = WorkBudget(before.run.attempt, before.run.provider_call_count, before.repair_count)
        budget.consume_ai_call(repair=repair)
        token = ProviderCallToken(run_id, before.run.attempt, budget.provider_call_count, lease.revision, process_instance)
        run = before.run.model_copy(update={"stage": "CHAT_RUNNING", "provider_call_count": budget.provider_call_count})
        after = StoredRunState(run, budget.repair_count, token)
        if rows.cas_run(before, after) is not True:
            raise WorkRunError("CALL_TOKEN_MISMATCH", 409)
        self._flush()
        # This is a proposed durable charge, not authorization to dispatch.
        return ChatCallReservation(task, ctx, after, lease, token, limits)

    def _chat_current(self, original: WorkContext, *, positive: bool) -> tuple[WorkTaskDTO, WorkContext]:
        if type(original) is not WorkContext:
            raise WorkRunError("RUN_SCOPE_MISMATCH", 404)
        WorkContext.__post_init__(original)
        task, current = self._chat_task(original.actor_subject, original.task_id)
        identity = ("actor_subject", "owner_storage_id", "task_id", "institution_id", "offering_id")
        if any(getattr(original, name) != getattr(current, name) for name in identity):
            raise WorkRunError("CURRENT_SCOPE_CHANGED", 403)
        if positive and original.input_revision != current.input_revision:
            raise WorkRunError("STALE_INPUT_REVISION", 409)
        return task, current

    def _chat_exact_call(self, ctx: WorkContext, state: StoredRunState, lease: OwnerLeaseFacts,
                         token: ProviderCallToken) -> None:
        if type(token) is not ProviderCallToken:
            raise WorkRunError("INVALID_CALL_TOKEN", 503)
        ProviderCallToken.__post_init__(token)
        if not matches_active_call(state, token) or lease.revision != token.lease_revision:
            raise WorkRunError("CALL_TOKEN_MISMATCH", 409)
        self._chat_linked_lease(ctx, state, lease, token.process_instance)
        if state.run.stage not in {"CHAT_RUNNING", "FAILED", "CANCELLED"}:
            raise WorkRunError("RUN_NOT_ACTIVE", 409)

    @staticmethod
    def _chat_result(result: ChatResult, allowed_result_refs: frozenset[UUID], omitted_context: bool) -> ChatResult:
        try:
            if (not isinstance(result, ChatResult) or type(allowed_result_refs) is not frozenset
                    or any(type(ref) is not UUID for ref in allowed_result_refs) or type(omitted_context) is not bool):
                raise ValueError("strict result metadata required")
            strict = ChatResult.model_validate(result.model_dump())
            if not strict.plain_text.strip() or strict.omitted_context is not omitted_context or not set(strict.result_refs) <= allowed_result_refs:
                raise ValueError("invalid result metadata")
            return strict
        except (TypeError, ValueError):
            raise WorkRunError("INVALID_CHAT_RESULT", 422) from None

    @staticmethod
    def _chat_release(lease: OwnerLeaseFacts) -> OwnerLeaseFacts:
        return OwnerLeaseFacts(lease.owner, lease.owner_storage_id, None, None, None, lease.revision + 1)

    def complete_chat_call(self, original_ctx: WorkContext, token: ProviderCallToken, result: ChatResult, *,
                           allowed_result_refs: frozenset[UUID], omitted_context: bool) -> ChatRunOutcome:
        strict = self._chat_result(result, allowed_result_refs, omitted_context)
        if type(token) is not ProviderCallToken:
            raise WorkRunError("INVALID_CALL_TOKEN", 503)
        ProviderCallToken.__post_init__(token)
        task, current = self._chat_current(original_ctx, positive=True)
        rows = self._chat_rows()
        state = self._chat_state(current.actor_subject, current.task_id, rows.lock_run(current.actor_subject, current.task_id, token.run_id))
        lease = self._chat_lease(current)
        existing = self._chat_completion(state)
        if existing is not None:
            if (chat_result_from_message(existing[1]) != strict or lease.active_run_id == token.run_id
                    or state.run.attempt != token.attempt or state.run.provider_call_count != token.call_no):
                raise WorkRunError("COMPLETION_CONFLICT", 409)
            return ChatRunOutcome(task, state, lease, existing[0])
        self._chat_exact_call(current, state, lease, token)
        now = self._instant()
        check_chat_commit(original_ctx, state.run, lease, current, process_instance=token.process_instance, now=now)
        message = WorkMessageDTO(message_id=self._uuid(), owner=current.actor_subject, task_id=current.task_id,
            client_message_key=None, role="assistant", plain_text=strict.plain_text, run_id=token.run_id,
            result_refs=strict.result_refs, result_type=strict.type, omitted_context=strict.omitted_context, created_at=now)
        receipt = validate_chat_completion(state.run, message, token.run_id)
        prepared = PreparedChatCompletion(original_ctx, token, strict, allowed_result_refs,
            omitted_context, message, receipt)
        return self._complete_chat_locked(task, current, state, lease, prepared)

    def complete_prepared_chat_call(self, prepared: PreparedChatCompletion) -> ChatRunOutcome:
        """Revalidate and write exactly the server-prepared candidate, once.

        An unknown outcome can be reconciled with this same value, never by
        generating another UUID/time or dispatching another model call.
        """
        if type(prepared) is not PreparedChatCompletion:
            raise WorkRunError("INVALID_CHAT_COMPLETION", 503)
        PreparedChatCompletion.__post_init__(prepared)
        task, current = self._chat_current(prepared.original_ctx, positive=True)
        rows, token = self._chat_rows(), prepared.token
        state = self._chat_state(current.actor_subject, current.task_id,
            rows.lock_run(current.actor_subject, current.task_id, token.run_id))
        lease = self._chat_lease(current)
        existing = self._chat_completion(state)
        if existing is not None:
            if (existing != (prepared.receipt, prepared.message) or lease.active_run_id == token.run_id
                    or state.run.attempt != token.attempt or state.run.provider_call_count != token.call_no):
                raise WorkRunError("COMPLETION_CONFLICT", 409)
            return ChatRunOutcome(task, state, lease, existing[0])
        return self._complete_chat_locked(task, current, state, lease, prepared)

    def _complete_chat_locked(self, task: WorkTaskDTO, current: WorkContext, state: StoredRunState,
                              lease: OwnerLeaseFacts, prepared: PreparedChatCompletion) -> ChatRunOutcome:
        PreparedChatCompletion.__post_init__(prepared)
        token, rows = prepared.token, self._chat_rows()
        self._chat_exact_call(current, state, lease, token)
        check_chat_commit(prepared.original_ctx, state.run, lease, current,
            process_instance=token.process_instance, now=self._instant())
        receipt = validate_chat_completion(state.run, prepared.message, token.run_id)
        if receipt != prepared.receipt:
            raise WorkRunError("INVALID_CHAT_COMPLETION", 503)
        after = StoredRunState(state.run.model_copy(update={"stage": "COMPLETE", "error_code": None}), state.repair_count, None)
        released = self._chat_release(lease)
        rows.insert_completion(prepared.message, receipt)
        if rows.cas_run(state, after) is not True:
            raise WorkRunError("CALL_TOKEN_MISMATCH", 409)
        if rows.cas_lease(lease, released) is not True:
            raise WorkRunError("OWNER_LEASE_LOST", 409)
        self._flush()
        return ChatRunOutcome(task, after, released, receipt)

    @classmethod
    def _chat_error(cls, code: str) -> str:
        if type(code) is not str or code not in cls._CHAT_ERRORS:
            raise WorkRunError("INVALID_WORK_ERROR", 503)
        return code

    def fail_chat_call(self, original_ctx: WorkContext, token: ProviderCallToken, error_code: str) -> ChatRunOutcome:
        """Only a caller observing actual local transport settlement may call this.

        Token equality cannot prove settlement. No recovery authorizer or force-
        release path is created when current role/offering admission denies.
        """
        code = self._chat_error(error_code)
        if type(token) is not ProviderCallToken:
            raise WorkRunError("INVALID_CALL_TOKEN", 503)
        ProviderCallToken.__post_init__(token)
        task, current = self._chat_current(original_ctx, positive=False)
        rows = self._chat_rows()
        state = self._chat_state(current.actor_subject, current.task_id, rows.lock_run(current.actor_subject, current.task_id, token.run_id))
        lease = self._chat_lease(current)
        self._chat_exact_call(current, state, lease, token)
        stage = state.run.stage if state.run.stage in {"FAILED", "CANCELLED"} else "FAILED"
        error = state.run.error_code if state.run.stage in {"FAILED", "CANCELLED"} else code
        after = StoredRunState(state.run.model_copy(update={"stage": stage, "error_code": error}), state.repair_count, None)
        released = self._chat_release(lease)
        if rows.cas_run(state, after) is not True:
            raise WorkRunError("CALL_TOKEN_MISMATCH", 409)
        if rows.cas_lease(lease, released) is not True:
            raise WorkRunError("OWNER_LEASE_LOST", 409)
        self._flush()
        return ChatRunOutcome(task, after, released, None)

    def expire_chat_call(self, original_ctx: WorkContext, token: ProviderCallToken) -> ChatRunOutcome:
        if type(token) is not ProviderCallToken:
            raise WorkRunError("INVALID_CALL_TOKEN", 503)
        ProviderCallToken.__post_init__(token)
        task, current = self._chat_current(original_ctx, positive=False)
        rows = self._chat_rows()
        state = self._chat_state(current.actor_subject, current.task_id, rows.lock_run(current.actor_subject, current.task_id, token.run_id))
        lease = self._chat_lease(current)
        self._chat_exact_call(current, state, lease, token)
        if self._instant() < state.run.deadline:
            raise WorkRunError("RUN_NOT_EXPIRED", 409)
        if state.run.stage in {"FAILED", "CANCELLED"}:
            return ChatRunOutcome(task, state, lease, None)
        after = StoredRunState(state.run.model_copy(update={"stage": "FAILED", "error_code": "WORK_AI_TIMEOUT"}), state.repair_count, state.active_call)
        if rows.cas_run(state, after) is not True:
            raise WorkRunError("CALL_TOKEN_MISMATCH", 409)
        self._flush()
        return ChatRunOutcome(task, after, lease, None)

    def fail_pending_chat(self, owner: str, task_id: UUID, run_id: UUID, *,
                          process_instance: UUID, error_code: str) -> ChatRunOutcome:
        code = self._chat_error(error_code)
        task, ctx = self._chat_task(owner, task_id)
        rows = self._chat_rows()
        state = self._chat_state(owner, task_id, rows.lock_run(owner, task_id, run_id))
        lease = self._chat_lease(ctx)
        self._chat_linked_lease(ctx, state, lease, process_instance)
        if (state.run.stage != "PENDING" or state.run.cancelled_at is not None or state.active_call is not None
                or state.run.provider_call_count != 0 or state.repair_count != 0):
            raise WorkRunError("RUN_NOT_PENDING", 409)
        after = StoredRunState(state.run.model_copy(update={"stage": "FAILED", "error_code": code}), 0, None)
        released = self._chat_release(lease)
        if rows.cas_run(state, after) is not True:
            raise WorkRunError("RUN_CONFLICT", 409)
        if rows.cas_lease(lease, released) is not True:
            raise WorkRunError("OWNER_LEASE_LOST", 409)
        self._flush()
        return ChatRunOutcome(task, after, released, None)

    def cancel_chat(self, owner: str, task_id: UUID, run_id: UUID) -> ChatRunOutcome:
        task, ctx = self._chat_task(owner, task_id)
        rows = self._chat_rows()
        state = self._chat_state(owner, task_id, rows.lock_run(owner, task_id, run_id))
        lease = self._chat_lease(ctx)
        if state.run.stage in {"COMPLETE", "FAILED", "CANCELLED", "INTERRUPTED"}:
            pair = self._chat_completion(state)
            return ChatRunOutcome(task, state, lease, pair[0] if pair is not None else None)
        if state.active_call is not None:
            self._chat_exact_call(ctx, state, lease, state.active_call)
        else:
            self._chat_linked_lease(ctx, state, lease, lease.process_instance)
        after = StoredRunState(cancel_chat_run(state.run, now=self._instant()), state.repair_count, state.active_call)
        if rows.cas_run(state, after) is not True:
            raise WorkRunError("RUN_CONFLICT", 409)
        # Absence of a token on an already charged run is not settlement proof.
        released = lease
        if state.active_call is None and state.run.provider_call_count == 0:
            released = self._chat_release(lease)
            if rows.cas_lease(lease, released) is not True:
                raise WorkRunError("OWNER_LEASE_LOST", 409)
        self._flush()
        return ChatRunOutcome(task, after, released, None)
