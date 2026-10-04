"""Pure legacy preservation and save gating, without legacy-service wiring.

Normalization is an inspection of detached content, never an automatic upgrade
to LessonSnapshot. The existing editor remains available for drafts requiring
metadata normalization. Caller-owned transactional integration is a later gate.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Callable

from app.services.teacher_work.types import canonical_digest, canonical_json_bytes


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
