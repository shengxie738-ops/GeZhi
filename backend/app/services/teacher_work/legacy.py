"""Pure legacy preservation and save gating, without legacy-service wiring.

Normalization is an inspection of detached content, never an automatic upgrade
to LessonSnapshot. The existing editor remains available for drafts requiring
metadata normalization. Caller-owned transactional integration is a later gate.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID

from app.services.teacher_work.types import WorkActor, canonical_digest, canonical_json_bytes


@dataclass(frozen=True)
class LegacyImport:
    content: dict
    needs_normalization_fields: list[str]


def _json_value(value: object) -> None:
    """Reject non-JSON objects instead of coercing or losing original keys."""
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise ValueError("legacy content requires exact JSON string keys")
        for item in value.values():
            _json_value(item)
    elif type(value) is list:
        for item in value:
            _json_value(item)
    elif value is not None and type(value) not in (str, int, float, bool):
        raise ValueError("legacy content must be JSON-compatible")


def _text(value: object, maximum: int, *, required: bool = False) -> bool:
    return type(value) is str and len(value) <= maximum and (not required or bool(value.strip()))


def normalize_legacy(content: dict) -> LegacyImport:
    """Preserve every original JSON value and return sorted field-path markers.

    Citation provenance and the old model label remain compatible metadata.
    Unknown paragraphs are retained and marked. No minute, audience, citation,
    outline, version or validated lesson is invented.
    """
    if type(content) is not dict:
        raise ValueError("legacy content must be a JSON object")
    _json_value(content)
    canonical_json_bytes(content)  # Also rejects non-finite JSON numbers.
    result = deepcopy(content)
    markers: set[str] = set()
    lists = {"objectives", "key_points", "difficulties", "questions", "exercises", "homework"}
    known = lists | {"title", "topic", "audience", "course_name", "duration_minutes", "summary", "teaching_flow", "citations", "model"}
    markers.update(set(content) - known)
    for name in ("title", "topic", "audience"):
        if not _text(content.get(name), 200, required=True):
            markers.add(name)
    for name, limit in (("course_name", 200), ("summary", 8000)):
        if name in content and not _text(content[name], limit):
            markers.add(name)
    duration = content.get("duration_minutes")
    if type(duration) is not int or not 1 <= duration <= 600:
        markers.add("duration_minutes")
    for name in lists:
        if name not in content:
            continue
        values = content[name]
        if type(values) is not list or len(values) > 20:
            markers.add(name)
            continue
        for index, value in enumerate(values):
            if not _text(value, 2000, required=True):
                markers.add(f"{name}[{index}]")
    flow = content.get("teaching_flow")
    if type(flow) is not list or not 1 <= len(flow) <= 20:
        markers.add("teaching_flow")
    if type(flow) is list:
        minutes = 0
        valid_minutes = True
        for index, stage in enumerate(flow):
            prefix = f"teaching_flow[{index}]"
            if type(stage) is not dict:
                markers.add(prefix)
                valid_minutes = False
                continue
            markers.update(f"{prefix}.{name}" for name in set(stage) - {"stage", "minutes", "content"})
            for name, limit in (("stage", 200), ("content", 2000)):
                if not _text(stage.get(name), limit, required=True):
                    markers.add(f"{prefix}.{name}")
            value = stage.get("minutes")
            if type(value) is not int or not 1 <= value <= 600:
                markers.add(f"{prefix}.minutes")
                valid_minutes = False
            else:
                minutes += value
        if not valid_minutes or minutes != duration:
            markers.add("teaching_flow")
    citations = content.get("citations", [])
    if type(citations) is not list or len(citations) > 20:
        markers.add("citations")
    else:
        provenance = {"name", "page", "excerpt", "resource_id", "score", "course", "frontend_url"}
        for index, citation in enumerate(citations):
            prefix = f"citations[{index}]"
            if type(citation) is not dict:
                markers.add(prefix)
                continue
            markers.update(f"{prefix}.{name}" for name in set(citation) - provenance)
            for name, limit in (("name", 200), ("excerpt", 4000)):
                if name in citation and not _text(citation[name], limit):
                    markers.add(f"{prefix}.{name}")
            page = citation.get("page", 0)
            if type(page) is not int or page < 0:
                markers.add(f"{prefix}.page")
    return LegacyImport(result, sorted(markers))


def normalize_legacy_for_task(content: dict, duration_minutes: int) -> LegacyImport:
    """Inspect raw legacy content against the actual Task duration as well.

    Keep the original minutes/flow unchanged. The same relative content paths
    remain marked on import and every later metadata-only/no-op Work save.
    """
    if type(duration_minutes) is not int or not 1 <= duration_minutes <= 600:
        raise ValueError("validated Task duration required")
    result = normalize_legacy(content)
    if type(content.get("duration_minutes")) is not int or content["duration_minutes"] != duration_minutes:
        return LegacyImport(result.content, sorted(set(result.needs_normalization_fields) | {"duration_minutes", "teaching_flow"}))
    return result


class LegacyLessonPreservationError(ValueError):
    def __init__(self, fields: tuple[str, ...]):
        super().__init__("legacy lesson requires explicit normalization")
        self.fields = fields


def preserve_legacy_lesson(content: dict, lesson: dict) -> dict:
    """Apply a validated known-field lesson without deleting opaque old values.

    Unknown root fields/model metadata stay in the sole original draft. For
    stage/citation extras, only a unique exact match of representable fields
    establishes an association. Removal, changed identity or ambiguous matches
    with opaque extras require explicit normalization before any command write.
    This is preservation of raw legacy data, not a validated snapshot upgrade.
    """
    try:
        original = normalize_legacy(content).content
    except (TypeError, ValueError):
        raise LegacyLessonPreservationError(("content",)) from None
    merged = {**original, **deepcopy(lesson)}
    shapes = (("teaching_flow", {"stage": None, "minutes": None, "content": None}),
              ("citations", {"name": "", "page": 0, "excerpt": ""}))
    for name, defaults in shapes:
        if name not in original:
            continue
        old_items = original[name]
        if type(old_items) is not list:
            raise LegacyLessonPreservationError((f"content.{name}",))
        new_items = merged[name]  # Caller supplies the full strict lesson dump.
        occupied: set[int] = set()
        for index, item in enumerate(old_items):
            path = f"content.{name}[{index}]"
            if type(item) is not dict:
                raise LegacyLessonPreservationError((path,))
            extras = {key: value for key, value in item.items() if key not in defaults}
            if not extras:
                continue
            identity = canonical_digest({key: item.get(key, default) for key, default in defaults.items()})
            matches = [position for position, candidate in enumerate(new_items)
                       if canonical_digest({key: candidate.get(key, default) for key, default in defaults.items()}) == identity]
            if len(matches) != 1 or matches[0] in occupied:
                raise LegacyLessonPreservationError((path,))
            occupied.add(matches[0])
            new_items[matches[0]].update(deepcopy(extras))
    return merged


class LegacySaveError(Exception):
    """Controlled public outcome; no underlying registry exception is exposed."""
    def __init__(self, code: str, status_code: int):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def guarded_legacy_save(*, transaction_active: bool, footprint_locked: bool,
                        lease_locked: bool, draft_locked: bool,
                        registry_state: str, save: Callable[[], dict]) -> dict:
    """Delegate only an explicitly confirmed unlinked save under caller locks.

    Facts must come from the trusted same-transaction adapter, including an
    absent/new draft reservation. Unknown/schema-error states are unavailable,
    never unlinked. This helper neither establishes locks nor owns a transaction.
    It is deliberately not wired into the old service until T2b participation.
    """
    if any(value is not True for value in (transaction_active, footprint_locked, lease_locked, draft_locked)):
        raise LegacySaveError("LEGACY_TRANSACTION_REQUIRED", 503)
    if registry_state == "linked":
        raise LegacySaveError("LINKED_LEGACY_WRITE_CONFLICT", 409)
    if registry_state != "unlinked":
        raise LegacySaveError("WORK_REGISTRY_UNAVAILABLE", 503)
    return save()


@dataclass(frozen=True)
class LegacySaveInput:
    draft_id: str
    title: str
    topic: str
    duration_minutes: int
    resource_ids: tuple[str, ...]
    content: dict


@dataclass(frozen=True)
class LegacyRegistryObservation:
    state: str
    confirmed: bool


@dataclass(frozen=True)
class PreparedLegacyDraft:
    """The existing original-draft primitive's structural write carrier."""
    owner: str
    draft_id: str
    payload: dict
    module: str = "teacher_lesson_prep"
    record_type: str = "draft"


def _save_input(subject: str, request: LegacySaveInput) -> None:
    if (type(subject) is not str or not subject or subject != subject.strip() or len(subject) > 255
            or not isinstance(request, LegacySaveInput) or not _text(request.draft_id, 255)
            or not _text(request.title, 200, required=True) or not _text(request.topic, 200, required=True)
            or type(request.duration_minutes) is not int or not 1 <= request.duration_minutes <= 600
            or type(request.resource_ids) is not tuple or len(request.resource_ids) > 10
            or any(not _text(value, 255, required=True) for value in request.resource_ids)
            or type(request.content) is not dict):
        raise LegacySaveError("INVALID_LEGACY_SAVE", 422)
    try:
        _json_value(request.content)
        canonical_json_bytes(request.content)
    except (TypeError, ValueError):
        raise LegacySaveError("INVALID_LEGACY_SAVE", 422) from None


def _linked_task(row, subject: str, draft_id: str):
    if row is None:
        return None
    task = row.task
    if task.owner_subject != subject or task.lesson_draft_id != draft_id or not isinstance(task.task_id, UUID):
        raise LegacySaveError("NOT_FOUND", 404)
    return task


def prepare_legacy_save(subject: str, request: LegacySaveInput, *, registry: LegacyRegistryObservation,
                        repository, legacy_save: Callable[[str, LegacySaveInput], dict],
                        clock: Callable[[], datetime], new_uuid: Callable[[], UUID]) -> dict:
    """Prepare one original draft under the coordinator's ordered lock protocol.

    This is a candidate write plus caller flush, never commit/response ownership.
    Compatible registries use the guard irrespective of feature flags. Confirmed
    physical absence alone may delegate the old save. Actual service wiring and
    its real registry/request-owner producers are deliberately still separate.
    """
    _save_input(subject, request)
    if not isinstance(registry, LegacyRegistryObservation) or registry.confirmed is not True:
        raise LegacySaveError("WORK_REGISTRY_UNAVAILABLE", 503)
    if registry.state == "absent":
        return legacy_save(subject, request)
    if registry.state != "compatible":
        raise LegacySaveError("WORK_REGISTRY_UNAVAILABLE", 503)
    if repository.uow.in_transaction() is not True:
        raise LegacySaveError("LEGACY_TRANSACTION_REQUIRED", 503)
    new = not request.draft_id
    provisional = None if new else _linked_task(repository.rows.find_task_by_draft(subject, request.draft_id), subject, request.draft_id)
    institution = provisional.institution_id if provisional is not None else None
    offering = provisional.offering_id if provisional is not None else None
    scope = repository.authorize_locked(subject, offering, institution)
    if (not isinstance(scope.actor, WorkActor) or scope.actor.subject != subject
            or (scope.institution_id, scope.offering_id) != (institution, offering)):
        raise LegacySaveError("NOT_FOUND", 404)
    repository.rows.lock_owner_lease(subject)
    if any(value != scope.actor.owner_storage_id for value in repository.rows.owner_storage_ids(subject)):
        raise LegacySaveError("OWNER_NAMESPACE_MISMATCH", 503)
    if new:
        generated = new_uuid()
        if not isinstance(generated, UUID):
            raise LegacySaveError("LEGACY_STORAGE_UNAVAILABLE", 503)
        draft_id = str(generated)
    else:
        draft_id = request.draft_id
    original = repository.drafts.lock_draft(subject, draft_id)
    if original is not None:
        if (original.owner != subject or original.draft_id != draft_id or original.module != "teacher_lesson_prep"
                or original.record_type != "draft" or type(original.payload) is not dict
                or original.payload.get("draft_id") != draft_id):
            raise LegacySaveError("NOT_FOUND", 404)
        if new:
            raise LegacySaveError("LEGACY_DRAFT_ID_CONFLICT", 409)
    elif not new:
        raise LegacySaveError("NOT_FOUND", 404)
    current = _linked_task(repository.rows.find_task_by_draft(subject, draft_id), subject, draft_id)
    if current is not None:
        if ((current.institution_id, current.offering_id) != (institution, offering)
                or (provisional is not None and current.task_id != provisional.task_id)):
            raise LegacySaveError("LEGACY_SCOPE_CHANGED", 409)
        current_id = current.task_id
        current = _linked_task(repository.rows.lock_task(subject, current_id), subject, draft_id)
        if current is None or current.task_id != current_id or (current.institution_id, current.offering_id) != (institution, offering):
            raise LegacySaveError("LEGACY_SCOPE_CHANGED", 409)
        if current.owner_storage_id != scope.actor.owner_storage_id:
            raise LegacySaveError("OWNER_NAMESPACE_MISMATCH", 503)
    elif provisional is not None:
        raise LegacySaveError("LEGACY_SCOPE_CHANGED", 409)

    def prepare() -> dict:
        now = clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise LegacySaveError("LEGACY_STORAGE_UNAVAILABLE", 503)
        instant = now.astimezone(timezone.utc).isoformat()
        data = deepcopy(original.payload) if original is not None else {}
        if original is not None and not _text(data.get("created_at"), 100, required=True):
            raise LegacySaveError("LEGACY_STORAGE_UNAVAILABLE", 503)
        data.update({"draft_id": draft_id, "title": request.title, "topic": request.topic,
                     "duration_minutes": request.duration_minutes, "resource_ids": list(request.resource_ids),
                     "content": deepcopy(request.content), "status": "DRAFT",
                     "created_at": data["created_at"] if original is not None else instant, "updated_at": instant})
        try:
            _json_value(data)
            canonical_json_bytes(data)
        except (TypeError, ValueError):
            raise LegacySaveError("LEGACY_STORAGE_UNAVAILABLE", 503) from None
        row = PreparedLegacyDraft(subject, draft_id, data)
        if new:
            repository.drafts.create_draft(row)
        else:
            repository.drafts.write_draft(row)
        if repository.uow.in_transaction() is not True:
            raise LegacySaveError("LEGACY_TRANSACTION_REQUIRED", 503)
        repository.uow.flush()
        return deepcopy(data)

    return guarded_legacy_save(transaction_active=repository.uow.in_transaction(), footprint_locked=True,
        lease_locked=True, draft_locked=True, registry_state="linked" if current is not None else "unlinked", save=prepare)
