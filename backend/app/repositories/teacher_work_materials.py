"""Private manual outline commands on the existing exact caller root."""
from copy import deepcopy
import json
from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy import insert, select

from app.repositories.teacher_work import DraftRecord, TaskRecord, WorkRepositoryError
from app.repositories.teacher_work_sql import SqlChatRows, _utc
from app.schemas.teacher_work import (ApprovalReceipt, FrozenPackageContent, MaterialWriteReceipt, MessageKey,
    OutlineSnapshotDTO, PrivateMaterialState, WorkTaskDTO)
from app.services.teacher_work.legacy import preserve_legacy_lesson, normalize_legacy_for_task, LegacyLessonPreservationError
from app.services.teacher_work.materials import outline_digest, source_digest, check_manual_approval_content
from app.services.teacher_work.types import canonical_digest, canonical_json_bytes


def unavailable():
    return WorkRepositoryError("MATERIAL_STATE_UNAVAILABLE", 503)


def check_original_payload_size(payload):
    # The unchanged DomainRecord ORM uses MySQL TEXT, not a larger text type.
    # Match SqlOriginalDrafts.write_draft's actual compact canonical encoding.
    if len(canonical_json_bytes(payload)) > 65535:
        raise WorkRepositoryError("PRIVATE_DRAFT_TOO_LARGE", 422)


class SqlMaterialRows:
    def __init__(self, guard, outline_model, approval_model):
        if (type(guard) is not SqlChatRows or outline_model.__table__.name != "teacher_work_outline_snapshots"
                or approval_model.__table__.name != "teacher_work_outline_approvals"):
            raise ValueError("same caller-root guard and exact models required")
        self.guard, self.outline_model, self.approval_model = guard, outline_model, approval_model

    def _outline(self, row, task_id):
        if row is None:
            return None
        try:
            data = {name: getattr(row, name) for name in OutlineSnapshotDTO.model_fields}
            data["created_at"] = _utc(data["created_at"]).isoformat()
            value = OutlineSnapshotDTO.model_validate_json(json.dumps(data, ensure_ascii=False, allow_nan=False))
            FrozenPackageContent(lesson=value.lesson, slides=value.slides)
            if (value.task_id != task_id or value.skill_versions or any(slide.evidence_refs for slide in value.slides)
                    or outline_digest(value) != value.outline_digest):
                raise ValueError("exact manual snapshot required")
            return value
        except (TypeError, ValueError, AttributeError):
            raise unavailable() from None

    def latest(self, owner, task_id):
        self.guard._task(owner, task_id)
        model = self.outline_model
        rows = self.guard._read(select(model).where(model.task_id == str(task_id)).order_by(model.outline_revision.desc()).limit(1))
        return self._outline(rows[0], task_id) if rows else None

    def get_outline(self, owner, task_id, outline_id):
        self.guard._task(owner, task_id)
        model = self.outline_model
        rows = self.guard._read(select(model).where(model.task_id == str(task_id), model.outline_id == str(outline_id)).limit(2))
        if len(rows) != 1:
            raise unavailable()
        return self._outline(rows[0], task_id)

    def approval(self, owner, snapshot):
        self.guard._task(owner, snapshot.task_id)
        model = self.approval_model
        rows = self.guard._read(select(model).where(model.owner == owner, model.task_id == str(snapshot.task_id),
            model.outline_id == str(snapshot.outline_id)).limit(2))
        if len(rows) > 1:
            raise unavailable()
        if not rows:
            return None
        try:
            data = {name: getattr(rows[0], name) for name in ApprovalReceipt.model_fields}
            data["confirmed_at"] = _utc(data["confirmed_at"]).isoformat()
            value = ApprovalReceipt.model_validate_json(json.dumps(data, ensure_ascii=False, allow_nan=False))
            if value.owner != owner or (value.task_id, value.outline_id, value.input_revision, value.outline_revision,
                value.outline_digest, value.source_digest) != (snapshot.task_id, snapshot.outline_id, snapshot.input_revision,
                snapshot.outline_revision, snapshot.outline_digest, snapshot.source_digest):
                raise ValueError("exact owned approval required")
            return value
        except (ValueError, TypeError, AttributeError):
            raise unavailable() from None

    def append_outline(self, owner, snapshot):
        self.guard._task(owner, snapshot.task_id, write=True)
        data = snapshot.model_dump(mode="json")
        data["created_at"] = snapshot.created_at.replace(tzinfo=None)
        self.guard.uow.execute_write(insert(self.outline_model).values(**data))

    def append_approval(self, value):
        self.guard._task(value.owner, value.task_id, write=True)
        data = value.model_dump(mode="json")
        data["confirmed_at"] = value.confirmed_at.replace(tzinfo=None)
        self.guard.uow.execute_write(insert(self.approval_model).values(**data))


class PrivateMaterialRepository:
    def __init__(self, repository, rows, sources):
        if repository.run_rows is not rows.guard or repository.uow is not rows.guard.uow:
            raise ValueError("one caller root required")
        self.core, self.rows, self.sources = repository, rows, sources

    def _locked(self, owner, task_id):
        row, draft = self.core._locked_task(owner, task_id)
        self.core._metadata(draft.payload)
        return row, draft

    def _records(self, metadata):
        records = metadata.get("private_material_receipts", [])
        try:
            if type(records) is not list or len(records) > 64 or len(canonical_json_bytes(records)) > 32768:
                raise ValueError("bounded exact receipts required")
            keys = set()
            for record in records:
                if type(record) is not dict or set(record) != {"operation", "key", "request_digest", "outline_id", "approval_id", "input_revision", "working_revision"}:
                    raise ValueError("exact stored receipt required")
                key = TypeAdapter(MessageKey).validate_python(record["key"])
                digest = record["request_digest"]
                if type(digest) is not str or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                    raise ValueError("stored request digest required")
                value = MaterialWriteReceipt.model_validate_json(json.dumps({k:v for k,v in record.items() if k not in ("key", "request_digest")} | {"replayed": True}))
                if (value.operation == "save") != (value.approval_id is None) or (value.operation, key) in keys:
                    raise ValueError("distinct coherent receipts required")
                keys.add((value.operation, key))
            return deepcopy(records)
        except (TypeError, ValueError):
            raise unavailable() from None

    def _replay(self, owner, task_id, metadata, operation, key, request):
        TypeAdapter(MessageKey).validate_python(key)
        digest = canonical_digest(request.model_dump(mode="json"))
        records = self._records(metadata)
        for record in records:
            if (record["operation"], record["key"]) != (operation, key):
                continue
            if record["request_digest"] != digest:
                raise WorkRepositoryError("IDEMPOTENCY_CONFLICT", 409)
            snapshot = self.rows.get_outline(owner, task_id, UUID(record["outline_id"]))
            if snapshot.input_revision != record["input_revision"]:
                raise unavailable()
            if operation == "approve":
                approval = self.rows.approval(owner, snapshot)
                if approval is None or str(approval.approval_id) != record["approval_id"]:
                    raise unavailable()
            receipt = MaterialWriteReceipt.model_validate_json(json.dumps({k:v for k,v in record.items() if k not in ("key", "request_digest")} | {"replayed": True}))
            return records, digest, receipt
        return records, digest, None

    def _source(self, task, payload):
        return source_digest(task, self.core._metadata(payload)["requirements"], self.sources.observe(payload["resource_ids"]))

    def get(self, owner, task_id, *, receipt=None):
        row, draft = self._locked(owner, task_id)
        task, payload = row.task, draft.payload
        records = self._records(self.core._metadata(payload))
        if any(record["input_revision"] > task.input_revision or record["working_revision"] > task.working_revision for record in records):
            raise unavailable()
        if receipt is not None and not any(receipt.model_dump(mode="json", exclude={"replayed"}) ==
                {key: value for key, value in record.items() if key not in ("key", "request_digest")} for record in records):
            raise unavailable()
        try:
            markers = tuple(normalize_legacy_for_task(payload["content"], task.duration_minutes).needs_normalization_fields)
        except (ValueError, TypeError, KeyError):
            raise unavailable() from None
        snapshot = self.rows.latest(owner, task_id)
        if task.current_outline_id is not None and (snapshot is None or task.current_outline_id != snapshot.outline_id):
            raise unavailable()
        if snapshot is not None and snapshot.input_revision > task.input_revision:
            raise unavailable()
        if snapshot is not None and task.current_outline_id == snapshot.outline_id and task.input_revision == snapshot.input_revision:
            try:
                # Every representable field must still match the sole draft.
                # Compatible opaque extras remain in the original, untouched.
                preserved = preserve_legacy_lesson(payload["content"], snapshot.lesson.model_dump(mode="json"))
                if canonical_json_bytes(preserved) != canonical_json_bytes(payload["content"]):
                    raise ValueError("original lesson differs from immutable snapshot")
            except (ValueError, TypeError, KeyError):
                raise unavailable() from None
        approval = self.rows.approval(owner, snapshot) if snapshot else None
        try:
            current_digest = self._source(task, payload)
        except WorkRepositoryError as error:
            if error.code != "MATERIAL_SOURCES_UNAVAILABLE":
                raise
            current_digest = None
        status = ("unavailable" if current_digest is None else "unprepared" if snapshot is None else
                  "current" if current_digest == snapshot.source_digest else "changed")
        if snapshot is None:
            blocker = "NO_OUTLINE"
        elif current_digest is None:
            blocker = "MATERIAL_SOURCES_UNAVAILABLE"
        elif snapshot.input_revision != task.input_revision or task.current_outline_id != snapshot.outline_id:
            blocker = "STALE_INPUT_REVISION"
        elif status != "current":
            blocker = "SOURCE_CHANGED"
        elif self.rows.guard.lease(owner).active_run_id is not None:
            blocker = "OWNER_RUN_BUSY"
        elif markers:
            blocker = "NORMALIZATION_REQUIRED"
        else:
            try:
                check_manual_approval_content(snapshot.lesson, snapshot.slides)
                blocker = None
            except ValueError:
                blocker = "MATERIAL_TEXT_UNREPRESENTABLE"
        return PrivateMaterialState(task=task, last_outline_revision=snapshot.outline_revision if snapshot else 0,
            outline=snapshot, approval=approval, source_status=status, current_source_digest=current_digest,
            needs_normalization_fields=markers, approval_eligible=blocker is None, approval_current=approval is not None and blocker is None,
            approval_blocker=blocker, receipt=receipt)

    def verify_source(self, value):
        current = self.get(value.task.owner_subject, value.task.task_id, receipt=value.receipt)
        if current.task != value.task:
            raise WorkRepositoryError("REVISION_CONFLICT", 409)
        if current.current_source_digest != value.current_source_digest:
            raise WorkRepositoryError("SOURCE_CHANGED", 409)
        if current != value:
            if current.approval_blocker is not None:
                raise WorkRepositoryError(current.approval_blocker, 503 if current.approval_blocker == "MATERIAL_SOURCES_UNAVAILABLE" else 409)
            raise unavailable()

    def _journal(self, metadata, records, digest, receipt, key):
        data = receipt.model_dump(mode="json", exclude={"replayed"}) | {"key": key, "request_digest": digest}
        records.append(data)
        if len(records) > 64 or len(canonical_json_bytes(records)) > 32768:
            raise WorkRepositoryError("MATERIAL_RECEIPT_LIMIT", 409)
        metadata["private_material_receipts"] = records

    def _save_root(self, row, payload, saved):
        self.core.drafts.write_draft(DraftRecord(saved.owner_subject, saved.lesson_draft_id, payload))
        if self.core.rows.compare_and_swap_task(saved.owner_subject, saved.task_id, row.task.working_revision,
            TaskRecord(saved, row.create_idempotency_key, row.create_request_digest)) is not True:
            raise WorkRepositoryError("REVISION_CONFLICT", 409)
        self.core._flush()

    def save(self, owner, task_id, request, key):
        row, draft = self._locked(owner, task_id)
        payload, task = deepcopy(draft.payload), row.task
        metadata = self.core._metadata(payload)
        records, digest, replay = self._replay(owner, task_id, metadata, "save", key, request)
        if replay is not None:
            return self.get(owner, task_id, receipt=replay)
        if (request.expected_revision, request.input_revision) != (task.working_revision, task.input_revision):
            raise WorkRepositoryError("REVISION_CONFLICT", 409)
        latest = self.rows.latest(owner, task_id)
        if request.expected_outline_revision != (latest.outline_revision if latest else 0):
            raise WorkRepositoryError("OUTLINE_REVISION_CONFLICT", 409)
        if self.rows.guard.lease(owner).active_run_id is not None:
            raise WorkRepositoryError("OWNER_RUN_BUSY", 409)
        if request.lesson.duration_minutes != task.duration_minutes:
            raise WorkRepositoryError("LESSON_DURATION_MISMATCH", 422)
        if any(s.evidence_refs for s in request.slides):
            # Manual citation/source_note text is retained teacher input; it
            # does not certify retrieved page/excerpt evidence.
            raise WorkRepositoryError("MATERIAL_EVIDENCE_NOT_ENABLED", 422)
        FrozenPackageContent(lesson=request.lesson, slides=request.slides)
        try:
            payload["content"] = preserve_legacy_lesson(payload.get("content"), request.lesson.model_dump(mode="json"))
        except LegacyLessonPreservationError:
            raise WorkRepositoryError("NORMALIZATION_REQUIRED", 422) from None
        markers = normalize_legacy_for_task(payload["content"], task.duration_minutes).needs_normalization_fields
        metadata["needs_normalization_fields"] = markers
        now, outline_id = self.core._instant(), self.core._uuid()
        saved = WorkTaskDTO.model_validate({**task.model_dump(), "input_revision": task.input_revision + 1,
            "working_revision": task.working_revision + 1, "target_slide_count": len(request.slides),
            "current_outline_id": outline_id, "updated_at": now})
        snapshot = OutlineSnapshotDTO(outline_id=outline_id, task_id=task_id, input_revision=saved.input_revision,
            outline_revision=request.expected_outline_revision + 1, lesson=request.lesson, slides=request.slides,
            source_digest=self._source(saved, payload), outline_digest="0" * 64, skill_versions=(), created_at=now)
        snapshot = snapshot.model_copy(update={"outline_digest": outline_digest(snapshot)})
        receipt = MaterialWriteReceipt(operation="save", outline_id=outline_id, approval_id=None,
            input_revision=saved.input_revision, working_revision=saved.working_revision, replayed=False)
        self._journal(metadata, records, digest, receipt, key)
        payload["updated_at"] = now.isoformat()
        check_original_payload_size(payload)
        self.rows.append_outline(owner, snapshot)
        self._save_root(row, payload, saved)
        return self.get(owner, task_id, receipt=receipt)

    def approve(self, owner, task_id, request, key):
        row, draft = self._locked(owner, task_id)
        payload = deepcopy(draft.payload)
        metadata = self.core._metadata(payload)
        records, digest, replay = self._replay(owner, task_id, metadata, "approve", key, request)
        if replay is not None:
            return self.get(owner, task_id, receipt=replay)
        state = self.get(owner, task_id)
        snapshot = state.outline
        if snapshot is None or request.model_dump() != {name: getattr(snapshot, name) for name in ("input_revision", "outline_revision", "outline_digest", "source_digest")}:
            raise WorkRepositoryError("OUTLINE_APPROVAL_CONFLICT", 409)
        if not state.approval_eligible:
            raise WorkRepositoryError(state.approval_blocker, 503 if state.approval_blocker == "MATERIAL_SOURCES_UNAVAILABLE" else 409)
        now = self.core._instant()
        approval = state.approval
        new_approval = approval is None
        if approval is None:
            approval = ApprovalReceipt(approval_id=self.core._uuid(), owner=owner, task_id=task_id, outline_id=snapshot.outline_id,
                **request.model_dump(), confirmed_at=now)
        saved = WorkTaskDTO.model_validate({**row.task.model_dump(), "working_revision": row.task.working_revision + 1, "updated_at": now})
        receipt = MaterialWriteReceipt(operation="approve", outline_id=snapshot.outline_id, approval_id=approval.approval_id,
            input_revision=saved.input_revision, working_revision=saved.working_revision, replayed=False)
        self._journal(metadata, records, digest, receipt, key)
        payload["updated_at"] = now.isoformat()
        check_original_payload_size(payload)
        if new_approval:
            self.rows.append_approval(approval)
        self._save_root(row, payload, saved)
        return self.get(owner, task_id, receipt=receipt)
