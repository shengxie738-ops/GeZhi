"""Finite T2a pure legacy helper checks; old service integration is deferred."""
from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import importlib
from pathlib import Path

import pytest


BACKEND = Path(__file__).resolve().parents[1]
LEGACY_SERVICE_SHA256 = "b3e99cac3229f055127541c4bf9a4e7ce6a1b280931cc4919c36624f1df5f01d"


def _module():
    assert (BACKEND / "app/services/teacher_work/legacy.py").is_file(), "T2a production legacy helper is missing"
    return importlib.import_module("app.services.teacher_work.legacy")


def compatible():
    return {"title": "  原教案  ", "topic": "主题", "course_name": "课程", "audience": "对象",
            "duration_minutes": 45, "objectives": ["  原目标  "], "key_points": ["要点"],
            "difficulties": ["难点"], "questions": ["问题"], "exercises": ["练习"],
            "homework": ["作业"], "summary": "摘要", "teaching_flow": [{"stage": "讲解", "minutes": 45, "content": "正文"}],
            "citations": [{"name": "课件", "page": 3, "excerpt": " 引文 ", "resource_id": "resource-1", "score": 0.9,
                           "course": "课程", "frontend_url": "/courseware/resource-1"}], "model": "old-model"}


def test_normalize_legacy_preserves_compatible_content():
    result = _module().normalize_legacy(compatible())
    assert result.content == compatible()
    assert result.needs_normalization_fields == []
    assert type(result.content) is dict and type(result.needs_normalization_fields) is list


def test_normalize_legacy_preserves_unknown_paragraphs():
    raw = {**compatible(), "unknown_scalar": "旧段落", "unknown_list": ["旧列表"], "unknown_object": {"text": "旧对象"}}
    result = _module().normalize_legacy(raw)
    assert result.content == raw
    assert result.needs_normalization_fields == ["unknown_list", "unknown_object", "unknown_scalar"]
    assert not {"outline", "version", "approval"} & set(result.content)


def test_normalize_legacy_marks_invalid_fields():
    module = _module()
    cases = (
        ({"objectives": {"invalid": "list"}}, ["objectives"]),
        ({"teaching_flow": [{"stage": "讲解", "minutes": 0, "content": "正文"}]}, ["teaching_flow", "teaching_flow[0].minutes"]),
        ({"teaching_flow": [{"stage": "讲解", "minutes": 1, "content": "正文"}] * 21}, ["teaching_flow"]),
        ({"teaching_flow": [{"stage": "讲解", "minutes": 45, "content": "字" * 2001}]}, ["teaching_flow[0].content"]),
        ({"audience": " "}, ["audience"]),
    )
    for changes, expected in cases:
        raw = {**compatible(), **changes}
        result = module.normalize_legacy(raw)
        assert result.content == raw and result.needs_normalization_fields == expected


def test_normalize_legacy_is_deterministic_nonmutating():
    raw = {**compatible(), "unknown": {"paragraphs": [{"text": "原文"}]}}
    before = deepcopy(raw)
    first = _module().normalize_legacy(raw)
    second = _module().normalize_legacy(raw)
    assert first == second and raw == before
    first.content["unknown"]["paragraphs"][0]["text"] = "局部编辑"
    assert raw == before and second.content == before


def test_linked_legacy_write_conflicts():
    module = _module()
    calls = []
    def save():
        calls.append("save")
        return {"draft_id": "legacy-1"}
    for state, code, status in (("linked", "LINKED_LEGACY_WRITE_CONFLICT", 409),
                                ("unavailable", "WORK_REGISTRY_UNAVAILABLE", 503),
                                ("unknown", "WORK_REGISTRY_UNAVAILABLE", 503)):
        with pytest.raises(module.LegacySaveError) as caught:
            module.guarded_legacy_save(transaction_active=True, footprint_locked=True, lease_locked=True,
                                       draft_locked=True, registry_state=state, save=save)
        assert caught.value.code == code and caught.value.status_code == status
    for missing in ("transaction_active", "footprint_locked", "lease_locked", "draft_locked"):
        flags = {"transaction_active": True, "footprint_locked": True, "lease_locked": True, "draft_locked": True}
        with pytest.raises(module.LegacySaveError):
            module.guarded_legacy_save(**{**flags, missing: False}, registry_state="unlinked", save=save)
    assert calls == []


def test_unlinked_legacy_save_preserves_contract():
    module = _module()
    original = {"draft_id": "legacy-1", "created_at": "2026-10-05T00:00:00+00:00", "content": compatible(), "status": "DRAFT"}
    stored = deepcopy(original)
    events = ["footprint", "lease", "draft", "task.lookup"]
    def save():
        events.append("delegated.save")
        return deepcopy(stored)
    saved = module.guarded_legacy_save(transaction_active=True, footprint_locked=True, lease_locked=True,
                                      draft_locked=True, registry_state="unlinked", save=save)
    assert saved == original and stored == original
    assert events == ["footprint", "lease", "draft", "task.lookup", "delegated.save"]
    assert not {"outline", "version", "artifact", "teacher_work"} & set(saved)
    # Read primitives are supplied observations, never the legacy service import.
    get_result, list_result = deepcopy(stored), [deepcopy(stored)]
    assert get_result == original and list_result == [original] and stored == original


def test_legacy_service_is_unchanged_and_unwired():
    path = BACKEND / "app/services/teacher_lesson_prep/service.py"
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == LEGACY_SERVICE_SHA256
    tree = ast.parse(raw.decode("utf-8"))
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert "app.services.teacher_work.legacy" not in imports
    service = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "TeacherLessonPrepService")
    for name in ("get_draft", "list_drafts"):
        method = next(node for node in service.body if isinstance(node, ast.FunctionDef) and node.name == name)
        calls = [node for node in ast.walk(method) if isinstance(node, ast.Call)]
        assert any(any(keyword.arg == "owner_id" and isinstance(keyword.value, ast.Name)
                       and keyword.value.id == "teacher_id" for keyword in call.keywords) for call in calls)
    assert not any(isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "guarded_legacy_save" for node in ast.walk(tree))
