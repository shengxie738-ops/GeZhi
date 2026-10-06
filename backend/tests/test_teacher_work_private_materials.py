"""Pure canonical/manual snapshot checks; no engine/config/provider imports."""
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
from uuid import UUID
from hashlib import sha256

import pytest
from app.schemas.teacher_work import LessonSnapshot, OutlineSnapshotDTO, SlideSnapshot
from app.services.teacher_work.types import canonical_digest, canonical_json_bytes


def lesson():
    return {"title": "合成标题", "topic": "合成主题", "audience": "合成对象", "course_name": "", "duration_minutes": 45,
        "objectives": ["合成目标"], "key_points": [], "difficulties": [], "questions": [], "exercises": [], "homework": [],
        "summary": "合成总结", "teaching_flow": [{"stage": "讲授", "minutes": 45, "content": "合成课堂内容"}], "citations": []}


def slides(count=8):
    return [{"layout": "bullets", "title": "合成页 " + str(i), "body": ["合成内容"], "columns": [],
        "notes": "合成备注", "source_note": "", "evidence_refs": []} for i in range(count)]


def module():
    path = Path(__file__).resolve().parents[1] / "app/services/teacher_work/materials.py"
    assert path.is_file(), "bounded material helpers missing"
    return importlib.import_module("app.services.teacher_work.materials")


def test_outline_digest_covers_exact_snapshot_projection():
    helpers = module()
    snapshot = OutlineSnapshotDTO(outline_id=UUID(int=1), task_id=UUID(int=2), input_revision=2, outline_revision=1,
        lesson=LessonSnapshot.model_validate(lesson()), slides=tuple(SlideSnapshot.model_validate(s) for s in slides()),
        source_digest="b" * 64, outline_digest="a" * 64, skill_versions=(), created_at=datetime(2026, 10, 6, tzinfo=timezone.utc))
    assert helpers.outline_digest(snapshot) == canonical_digest(snapshot.model_dump(mode="json", exclude={"outline_id", "outline_digest", "created_at"}))
    modified = snapshot.model_copy(update={"source_digest": "c" * 64})
    assert helpers.outline_digest(modified) != helpers.outline_digest(snapshot)


def test_manual_approval_refuses_known_text_loss_and_slide_overflow():
    helpers = module()
    model = LessonSnapshot.model_validate(lesson())
    pages = tuple(SlideSnapshot.model_validate(s) for s in slides())
    helpers.check_manual_approval_content(model, pages)
    with pytest.raises(ValueError):
        helpers.check_manual_approval_content(model.model_copy(update={"summary": " 前后空白 "}), pages)
    overflowing = pages[0].model_copy(update={"body": ("\n" * 80,)})
    with pytest.raises(ValueError):
        helpers.check_manual_approval_content(model, (overflowing,) + pages[1:])


def test_manual_save_request_enforces_combined_utf8_budget():
    from app.schemas.teacher_work import PrivateMaterialSaveRequest
    body = {"expected_revision": 1, "input_revision": 1, "expected_outline_revision": 0,
        "lesson": {**lesson(), "objectives": ["字" * 2000] * 20, "key_points": ["字" * 2000] * 20}, "slides": slides()}
    with pytest.raises(ValueError):
        PrivateMaterialSaveRequest.model_validate_json(json.dumps(body, ensure_ascii=False))


def test_material_sources_refuses_unbounded_directory_enumeration(tmp_path, monkeypatch):
    from app.services.teacher_work import material_sources as source
    from app.repositories.teacher_work import WorkRepositoryError
    root = tmp_path / "synthetic"
    course = root / "AI_technology"
    course.mkdir(parents=True)
    for index in range(5):
        (course / f"synthetic{index}.pdf").write_bytes(b"owned synthetic bytes")
    monkeypatch.setattr(source, "configured_root", lambda: root)
    assert hasattr(source, "ENTRY_LIMIT"), "source enumeration lacks a hard entry bound"
    monkeypatch.setattr(source, "ENTRY_LIMIT", 4)
    with pytest.raises(WorkRepositoryError) as error:
        source.MaterialSources().observe(["unknown"])
    assert error.value.code == "MATERIAL_SOURCES_UNAVAILABLE"


def test_material_sources_matches_catalog_ids_and_refuses_alias_collisions(tmp_path, monkeypatch):
    from app.services.teacher_work import material_sources as source
    from app.services.teacher_lesson_prep.courseware_catalog import CoursewareCatalog, DEFAULT_COURSE_DIRECTORIES
    from app.repositories.teacher_work import WorkRepositoryError
    root = tmp_path / "synthetic"
    for name in DEFAULT_COURSE_DIRECTORIES:
        (root / name).mkdir(parents=True)
    owned = root / DEFAULT_COURSE_DIRECTORIES[0] / "Synthetic.pdf"
    owned.write_bytes(b"synthetic-A")
    monkeypatch.setattr(source, "configured_root", lambda: root)
    key = CoursewareCatalog(frontend_root=root).scan(refresh=True)[0].id
    assert source.MaterialSources().observe([key]) == ((key, sha256(b"synthetic-A").hexdigest()),)
    owned.with_name("synthetic.pdf").write_bytes(b"synthetic-B")
    with pytest.raises(WorkRepositoryError) as error:
        source.MaterialSources().observe([key])
    assert error.value.code == "MATERIAL_SOURCES_UNAVAILABLE"


def test_material_sources_refuses_linked_files_and_excess_bytes(tmp_path, monkeypatch):
    from app.services.teacher_work import material_sources as source
    from app.repositories.teacher_work import WorkRepositoryError
    root = tmp_path / "synthetic"
    course = root / "AI_technology"
    course.mkdir(parents=True)
    owned = course / "synthetic.pdf"
    key = "courseware-" + sha256(b"ai_technology/synthetic.pdf").hexdigest()[:24]
    monkeypatch.setattr(source, "configured_root", lambda: root)
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"synthetic")
    owned.symlink_to(outside)
    with pytest.raises(WorkRepositoryError):
        source.MaterialSources().observe([key])
    owned.unlink()
    owned.write_bytes(b"12345")
    monkeypatch.setattr(source, "FILE_LIMIT", 4)
    with pytest.raises(WorkRepositoryError):
        source.MaterialSources().observe([key])


def test_original_draft_utf8_budget_counts_exact_json_encoding():
    from app.repositories import teacher_work_materials as repository
    from app.repositories.teacher_work import WorkRepositoryError
    assert hasattr(repository, "check_original_payload_size"), "existing MySQL TEXT draft needs an explicit byte check"
    # Include precisely the compact JSON encoding used by SqlOriginalDrafts.
    payload = {"x": "x" * (65535 - len(canonical_json_bytes({"x": ""})))}
    repository.check_original_payload_size(payload)
    with pytest.raises(WorkRepositoryError) as error:
        repository.check_original_payload_size({"x": payload["x"] + "字"})
    assert error.value.code == "PRIVATE_DRAFT_TOO_LARGE" and error.value.status_code == 422


def test_native_material_wire_fixture_matches_frozen_public_contract():
    outline_digest = module().outline_digest
    path = Path(__file__).with_name("fixtures") / "teacher_work_private_materials_http_contract.native.json"
    fixture = json.loads(path.read_text())
    assert fixture["provenance"]["synthetic_only"] and fixture["provenance"]["mysql_version"] == "8.4.10"
    names = {example["name"] for example in fixture["examples"]}
    assert {"empty", "saved", "approved", "stale_input", "source_changed", "save_replay", "approval_replay",
        "receipt_limit_error", "reconciled_save_commit", "reconciled_approve_commit", "large_unicode_saved"} <= names
    fields = {"task_id", "input_revision", "working_revision", "last_outline_revision", "current_outline_id", "outline", "approval",
        "source_status", "current_source_digest", "needs_normalization_fields", "approval_eligible", "approval_current", "approval_blocker", "receipt"}
    for example in fixture["examples"]:
        response, literal = example["response"], example["request"]
        envelope, status = response["body"], response["status"]
        assert set(envelope) == {"code", "message", "data"} and envelope["code"] == status
        encoded = json.dumps(envelope, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
        assert len(encoded) == example["response_utf8_bytes"] <= 262144
        if status != 200:
            assert envelope["data"] is None
            continue
        assert envelope["message"] == "ok"
        state = envelope["data"]
        if literal["path"].endswith("/capabilities"):
            assert set(state) == {"save", "read", "approve", "source_configured", "files", "reasons"}
            assert state["files"] is False and state["reasons"]["files"] == "files_not_enabled"
            assert set(state["reasons"]) == {key for key in ("save", "read", "approve", "source_configured", "files") if state[key] is False}
            continue
        if literal["method"] == "PATCH":
            continue  # The fixture preserves the actual stale-input trigger.
        assert set(state) == fields
        outline = state["outline"]
        assert (state["source_status"] == "unavailable") == (state["current_source_digest"] is None)
        if outline is None:
            assert state["last_outline_revision"] == 0 and state["approval"] is None and not state["approval_eligible"]
        else:
            model = OutlineSnapshotDTO.model_validate_json(json.dumps(outline))
            assert outline_digest(model) == outline["outline_digest"] and outline["skill_versions"] == []
            if state["source_status"] in ("current", "changed"):
                assert (state["current_source_digest"] == outline["source_digest"]) == (state["source_status"] == "current")
        approval = state["approval"]
        if approval is not None:
            assert set(approval) == {"approval_id", "task_id", "outline_id", "input_revision", "outline_revision", "outline_digest", "source_digest", "confirmed_at"}
            assert all(approval[key] == outline[key] for key in ("task_id", "outline_id", "input_revision", "outline_revision", "outline_digest", "source_digest"))
        receipt = state["receipt"]
        if receipt is not None:
            assert set(receipt) == {"operation", "outline_id", "approval_id", "input_revision", "working_revision", "replayed"}
            assert (receipt["operation"] == "save") == (receipt["approval_id"] is None)
            assert receipt["working_revision"] <= state["working_revision"]
