"""Teacher Work T1 contract preparation. EVERY CASE IS UNEXECUTED.

This file is a bounded selection inventory, not a runner. Do not execute it until
the approved guarded project verification entry is restored and selects a case.
No application/main, ORM, settings, database, migration, provider or native imports.

Synthetic fixtures only: one private task, fixed UUIDs, strict run payloads,
UTF-8 JSON bytes, bounded slide/lesson text, trusted capability facts, and the AST
of exactly app/models/teacher_work.py. No real teacher/student data or files.

Sources: implementation plan Global Constraints, Shared Contracts and Task 1;
design spec sections 5, 7.1-7.3, 8, 11 and 14.2. Exact case mapping and unresolved
acceptance gates are in the out-of-repository preparation brief.
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Annotated
from uuid import UUID

import pytest
from pydantic import TypeAdapter, ValidationError


BACKEND = Path(__file__).resolve().parents[1]
BODY_LIMIT = 256 * 1024
FIXTURE_UUID = UUID("10000000-0000-4000-8000-000000000001")
SKILL_REFS = (
    "lesson_outline@1", "lesson_package@1", "classroom_exercises@1",
    "reference_search@1",
)
PURE_MODULES = {
    "app.schemas.teacher_work": "app/schemas/teacher_work.py",
    "app.services.teacher_work.types": "app/services/teacher_work/types.py",
    "app.services.teacher_work.capabilities": "app/services/teacher_work/capabilities.py",
    "app.services.teacher_work.schema": "app/services/teacher_work/schema.py",
    "migrations.v20261005_teacher_work": "migrations/v20261005_teacher_work.py",
}
PURE_IMPORT_ROOTS = {
    "__future__", "collections", "dataclasses", "datetime", "enum", "hashlib",
    "json", "math", "re", "typing", "types", "uuid", "pydantic",
}
PURE_APP_IMPORTS = set(PURE_MODULES) | {"app.schemas.teacher_lesson_prep"}
FORBIDDEN_INPUT_FIELDS = (
    "owner", "owner_subject", "owner_storage_id", "role", "handler", "url",
    "status", "reviewed", "approved", "path", "model_endpoint", "api_key",
    "student_ids", "roster", "submissions", "grades", "student_profiles",
    "reference_answers", "private_tests", "grading_results",
)


def _feature(module_name):
    """Only known pure contracts may load, and only in a selected future case.

    A missing feature is an assertion failure. A missing dependency or unsafe
    import is a preparation/environment blocker, not an observed feature RED.
    This AST import boundary is a regression assertion, not a security sandbox.
    """
    assert module_name in PURE_MODULES, "Unapproved contract import requested"
    path = BACKEND / PURE_MODULES[module_name]
    assert path.is_file(), f"T1 pure feature is missing: {PURE_MODULES[module_name]}"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package = module_name.rsplit(".", 1)[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = package.split(".")
                base = ".".join(parts[:len(parts) - node.level + 1])
                if node.module:
                    base += "." + node.module
            names = [base]
        else:
            continue
        for name in names:
            assert name.split(".", 1)[0] in PURE_IMPORT_ROOTS or name in PURE_APP_IMPORTS, (
                f"T1 pure module has an unreviewed import: {module_name} -> {name}"
            )
    return importlib.import_module(module_name)


def _symbol(module_name, name):
    module = _feature(module_name)
    assert hasattr(module, name), f"T1 required interface is missing: {module_name}.{name}"
    return getattr(module, name)


def _schema(name):
    return _symbol("app.schemas.teacher_work", name)


def _reject(model, payload):
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def _field_adapter(model_name, field_name):
    """Use public DTO field annotations; do not name private implementation types."""
    model = _schema(model_name)
    assert field_name in model.model_fields, f"{model_name}.{field_name} is required"
    field = model.model_fields[field_name]
    annotation = field.annotation
    if field.metadata:
        annotation = Annotated.__class_getitem__((annotation, *field.metadata))
    return TypeAdapter(annotation)


@pytest.fixture
def task_payload():
    return {
        "title": "合成教师任务", "topic": "教学主题", "audience": "合成授课对象",
        "resource_ids": ["synthetic-courseware-1"], "scope": "private",
        "offering_id": None,
    }


def test_strict_limits(task_payload):
    """Plan T1: task dimensions, teacher text limits and forbidden input fields."""
    create = _schema("CreateTaskRequest")
    default = create.model_validate(task_payload)
    assert default.duration_minutes == 45
    assert default.target_slide_count == 8
    for count in (6, 12):
        assert create.model_validate({**task_payload, "target_slide_count": count}).target_slide_count == count
    for minutes in (1, 600):
        assert create.model_validate({**task_payload, "duration_minutes": minutes}).duration_minutes == minutes
    for field, invalid in (
        ("target_slide_count", 5), ("target_slide_count", 13),
        ("duration_minutes", 0), ("duration_minutes", 601),
        ("title", "教" * 201), ("topic", "教" * 201), ("audience", "教" * 201),
        ("resource_ids", []), ("resource_ids", [f"resource-{i}" for i in range(11)]),
    ):
        _reject(create, {**task_payload, field: invalid})
    for field in ("title", "topic", "audience"):
        assert getattr(create.model_validate({**task_payload, field: "教" * 200}), field) == "教" * 200
    assert len(create.model_validate({**task_payload, "resource_ids": [f"resource-{i}" for i in range(10)]}).resource_ids) == 10
    chat = _schema("ChatInput")
    assert chat.model_validate({"text": "教" * 4000, "client_message_key": "message-1"}).text == "教" * 4000
    _reject(chat, {"text": "教" * 4001, "client_message_key": "message-1"})
    changes = _schema("WorkingChanges")
    assert changes.model_validate({"requirements": "教" * 4000}).requirements == "教" * 4000
    _reject(changes, {"requirements": "教" * 4001})
    for field in FORBIDDEN_INPUT_FIELDS:
        _reject(create, {**task_payload, field: "untrusted"})
        _reject(changes, {field: "untrusted"})
    guard = _schema("validate_teacher_work_body_size")
    with pytest.raises(ValueError):
        guard(b" " * (BODY_LIMIT + 1))


def test_multibyte_body_limit(task_payload):
    """Wire bytes are measured before parsing, including otherwise valid padding."""
    guard = _schema("validate_teacher_work_body_size")
    task_payload["topic"] = "教" * 200
    encoded = json.dumps(task_payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    exact = encoded + b" " * (BODY_LIMIT - len(encoded))
    oversized = exact + b" "
    assert len(exact) == BODY_LIMIT
    assert len(oversized.decode("utf-8")) < BODY_LIMIT
    assert json.loads(exact)["topic"] == "教" * 200
    assert guard(exact) is None
    with pytest.raises(ValueError):
        guard(oversized)


def test_strict_scalar_and_scope_contract(task_payload):
    create = _schema("CreateTaskRequest")
    for field, value in (("duration_minutes", "45"), ("duration_minutes", True),
                         ("target_slide_count", "8"), ("title", 7)):
        _reject(create, {**task_payload, field: value})
    _reject(create, {**task_payload, "scope": "offering", "offering_id": None})
    _reject(create, {**task_payload, "scope": "private", "offering_id": FIXTURE_UUID})
    assert create.model_validate({**task_payload, "scope": "offering", "offering_id": FIXTURE_UUID}).offering_id == FIXTURE_UUID


def test_working_patch_and_approval_contracts():
    changes = _schema("WorkingChanges")
    assert set(changes.model_fields) == {
        "requirements", "lesson", "resource_ids", "reference_ids", "skill_refs",
        "plugin_ids", "target_slide_count",
    }
    patch = _schema("WorkingPatchRequest")
    good = {"expected_revision": 1, "changes": {"requirements": "合成要求"}, "base_version_id": None}
    assert patch.model_validate(good).expected_revision == 1
    for revision in (0, -1, "1", True):
        _reject(patch, {**good, "expected_revision": revision})
    for field in ("owner", "offering_id", "institution_id", "input_revision", "status"):
        _reject(changes, {field: "untrusted"})
    approval = _schema("OutlineApprovalRequest")
    expected = {"input_revision", "outline_revision", "outline_digest", "source_digest"}
    assert set(approval.model_fields) == expected
    good = {"input_revision": 1, "outline_revision": 1, "outline_digest": "a" * 64, "source_digest": "b" * 64}
    assert approval.model_validate(good).input_revision == 1
    for revision_field in ("input_revision", "outline_revision"):
        _reject(approval, {**good, revision_field: 0})
    for field in ("outline_id", "owner", "approved", "reviewed", "handler"):
        _reject(approval, {**good, field: "untrusted"})


def test_client_message_key_contract():
    chat = _schema("ChatInput")
    assert chat.model_validate({"text": "合成消息", "client_message_key": "k" * 128}).client_message_key == "k" * 128
    for key in ("", "k" * 129, "a\nb", "a\rb", "a\x00b", "a\x1fb", "a\x7fb"):
        _reject(chat, {"text": "合成消息", "client_message_key": key})


def test_run_command_discriminated_union():
    adapter = TypeAdapter(_schema("RunCommand"))
    commands = (
        ("chat", None, {"text": "合成问题", "client_message_key": "message-1"}),
        ("outline", "lesson_outline@1", {}),
        ("package", "lesson_package@1", {"approval_id": FIXTURE_UUID}),
        ("revise", None, {"base_version_id": None, "text": "合成修改"}),
        ("revise", "classroom_exercises@1", {"base_version_id": FIXTURE_UUID, "text": "合成练习"}),
        ("reference_search", "reference_search@1", {"query": "synthetic topic", "provider_ids": ["arxiv"], "limit": 1}),
    )
    for kind, skill_ref, payload in commands:
        command = {"kind": kind, "input_revision": 1, "skill_ref": skill_ref, "payload": payload}
        parsed = adapter.validate_python(command)
        assert parsed.kind == kind
        assert parsed.skill_ref == skill_ref
        for invalid_skill in ("unknown@1", "lesson_outline@2"):
            with pytest.raises(ValidationError):
                adapter.validate_python({**command, "skill_ref": invalid_skill})
        with pytest.raises(ValidationError):
            adapter.validate_python({**command, "payload": {**payload, "handler": "untrusted"}})
    for command in (
        {"kind": "chat", "input_revision": 1, "skill_ref": "lesson_outline@1", "payload": commands[0][2]},
        {"kind": "outline", "input_revision": 1, "skill_ref": None, "payload": {}},
        {"kind": "package", "input_revision": 1, "skill_ref": "lesson_package@1", "payload": {}},
        {"kind": "unknown", "input_revision": 1, "skill_ref": None, "payload": {}},
        {"kind": "outline", "input_revision": 0, "skill_ref": "lesson_outline@1", "payload": {}},
    ):
        with pytest.raises(ValidationError):
            adapter.validate_python(command)


def test_slide_layout_and_limits():
    slides = _field_adapter("OutlineSnapshotDTO", "slides")
    base = {"layout": "bullets", "title": "合成页面", "body": ["合成要点"],
            "columns": [], "notes": "合成讲者备注", "source_note": "合成来源",
            "evidence_refs": []}
    for count in (6, 12):
        assert len(slides.validate_python([deepcopy(base) for _ in range(count)])) == count
    for count in (5, 13):
        with pytest.raises(ValidationError):
            slides.validate_python([deepcopy(base) for _ in range(count)])
    for layout in ("title", "section", "bullets", "two_column", "question", "summary"):
        slide = {**base, "layout": layout, "body": []}
        if layout == "two_column":
            slide["columns"] = [["合成左栏"], ["合成右栏"]]
        slides.validate_python([deepcopy(slide) for _ in range(6)])
    boundary = {**base, "title": "教" * 60, "body": ["教" * 90] * 4,
                "notes": "教" * 1200, "source_note": "教" * 120}
    accepted = slides.validate_python([deepcopy(boundary) for _ in range(6)])
    assert tuple(accepted[0].body) == tuple(["教" * 90] * 4), "Content must not be truncated"
    for field, invalid in (("title", "教" * 61), ("body", ["教" * 91]),
                           ("body", ["教"] * 6), ("body", ["教" * 73] * 5),
                           ("notes", "教" * 1201), ("source_note", "教" * 121),
                           ("layout", "freeform"), ("title", "<script>alert(1)</script>")):
        with pytest.raises(ValidationError):
            slides.validate_python([{**base, field: invalid}] + [deepcopy(base) for _ in range(5)])
    for columns in ((["教"] * 3, ["教"] * 3), (["教" * 90] * 3, ["教" * 91])):
        with pytest.raises(ValidationError):
            slides.validate_python([{**base, "layout": "two_column", "body": [], "columns": list(columns)}] + [deepcopy(base) for _ in range(5)])
    for field in ("html", "javascript", "style", "image_url", "media_url", "path", "handler"):
        with pytest.raises(ValidationError):
            slides.validate_python([{**base, field: "untrusted"}] + [deepcopy(base) for _ in range(5)])


def test_frozen_strict_dtos_and_no_second_current_lesson():
    types = _feature("app.services.teacher_work.types")
    actor = types.WorkActor(subject="synthetic-owner", role="teacher", owner_storage_id=FIXTURE_UUID)
    assert actor.subject == "synthetic-owner"
    with pytest.raises((ValueError, TypeError, ValidationError)):
        types.WorkActor(subject="synthetic-owner", role="student", owner_storage_id=FIXTURE_UUID)
    context = types.WorkContext(actor_subject="synthetic-owner", owner_storage_id=FIXTURE_UUID,
                                task_id=FIXTURE_UUID, institution_id=None, offering_id=None,
                                input_revision=1, working_revision=1)
    assert context.input_revision == 1
    with pytest.raises((ValueError, TypeError, ValidationError)):
        types.WorkContext(actor_subject="synthetic-owner", owner_storage_id=FIXTURE_UUID,
                          task_id=FIXTURE_UUID, institution_id=None, offering_id=None,
                          input_revision=True, working_revision=1)
    with pytest.raises((TypeError, AttributeError, ValidationError)):
        context.input_revision = 2
    assert set(types.WorkDependencies.__annotations__) == {
        "repository", "identity", "offering_access", "ai", "evidence", "artifacts", "executor", "clock",
    }
    assert {"create_task", "from_legacy", "get_task", "patch_working"} <= set(vars(types.WorkRepository))
    for name in ("WorkTaskDTO", "WorkMessageDTO", "OutlineSnapshotDTO", "EvidenceSnapshotDTO",
                 "RunDTO", "PackageVersionDTO", "ArtifactDTO", "PreviewDTO", "ReviewDTO"):
        model = _schema(name)
        assert model.model_config.get("extra") == "forbid", f"{name} must reject extra fields"
        assert model.model_config.get("frozen") is True, f"{name} must be frozen"
    fields = {
        "WorkTaskDTO": {"task_id", "owner_subject", "owner_storage_id", "institution_id", "offering_id", "title", "topic", "audience", "duration_minutes", "target_slide_count", "lesson_draft_id", "input_revision", "working_revision", "current_outline_id", "latest_version_id", "created_at", "updated_at", "skill_refs", "plugin_ids", "reference_ids"},
        "WorkMessageDTO": {"message_id", "task_id", "owner", "client_message_key", "role", "plain_text", "run_id", "result_refs", "created_at"},
        "OutlineSnapshotDTO": {"outline_id", "task_id", "input_revision", "outline_revision", "lesson", "slides", "source_digest", "outline_digest", "skill_versions", "created_at"},
        "EvidenceSnapshotDTO": {"evidence_id", "task_id", "resource_id", "ref_id", "name", "page", "external_id", "excerpt", "resource_content_digest", "acquired_at", "evidence_type"},
        "RunDTO": {"run_id", "owner", "task_id", "kind", "skill_ref", "input_revision", "outline_revision", "idempotency_key", "request_digest", "stage", "attempt", "provider_call_count", "deadline", "cancelled_at", "error_code", "result_version_id"},
        "PackageVersionDTO": {"version_id", "task_id", "version_no", "base_version_id", "run_id", "lesson", "slides", "source_snapshots", "content_digest", "model_id", "skill_versions", "exporter_versions", "template_version", "created_at"},
        "ArtifactDTO": {"artifact_id", "version_id", "kind", "state", "download_name", "mime", "byte_size", "sha256", "exporter_version", "validation_summary", "error_code"},
        "PreviewDTO": {"version_id", "artifact_kind", "kind", "state", "source_content_digest", "source_file_digest", "error_code"},
        "ReviewDTO": {"review_id", "task_id", "version_id", "owner", "content_digest", "pptx_sha256", "docx_sha256", "reviewed_at"},
    }
    for name, required in fields.items():
        assert required <= set(_schema(name).model_fields), f"{name} lacks required public metadata"
        assert not {"storage_key", "path", "api_key", "model_endpoint"} & set(_schema(name).model_fields)
    task_fields = set(_schema("WorkTaskDTO").model_fields)
    assert {"lesson_draft_id", "input_revision", "working_revision"} <= task_fields
    assert not {"lesson", "content", "current_lesson", "resource_ids"} & task_fields
    assert {"skill_refs", "plugin_ids", "reference_ids"} <= task_fields
    for name in ("ChatResult", "RevisionProposal"):
        model = _schema(name)
        assert not {"approved", "reviewed", "handler"} & set(model.model_fields)
        assert model.model_config.get("extra") == "forbid"


def test_canonical_digest_utf8_sorted_compact_json():
    digest = _symbol("app.services.teacher_work.types", "canonical_digest")
    value = {"kind": "outline", "input_revision": 1, "skill_ref": "lesson_outline@1",
             "payload": {"topic": "合成主题", "resource_ids": ["resource-1"]}}
    expected = hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                        separators=(",", ":")).encode("utf-8")).hexdigest()
    assert digest(value) == expected
    assert digest(dict(reversed(tuple(value.items())))) == expected
    assert digest({**value, "input_revision": 2}) != expected
    # This value intentionally contains neither server timestamps nor header keys.
    # Filtering HTTP headers/server fields belongs to the later command adapter.


def test_closed_capabilities():
    facts_model = _symbol("app.services.teacher_work.types", "CapabilityFacts")
    project = _symbol("app.services.teacher_work.capabilities", "project_capabilities")
    trusted = {"enabled": True, "schema_ready": True, "transaction_ready": True,
               "storage_ready": True, "ai_ready": True, "skill_handlers": set(SKILL_REFS),
               "exporters_ready": True, "current_teacher_allowed": True}
    ready = project(facts_model(**trusted))
    for field in ("chat", "task_write", "generate", "storage", "structural_preview"):
        assert getattr(ready, field) is True, f"All trusted prerequisites must permit {field}"
    for gate, affected in (
        ("enabled", ("chat", "task_write", "generate", "storage", "structural_preview")),
        ("schema_ready", ("task_write", "generate")),
        ("transaction_ready", ("task_write", "generate")),
        ("storage_ready", ("storage", "generate")),
        ("ai_ready", ("chat", "generate")),
        ("current_teacher_allowed", ("chat", "task_write", "generate", "storage", "structural_preview")),
        ("exporters_ready", ("generate",)),
    ):
        actual = project(facts_model(**{**trusted, gate: False}))
        for field in affected:
            assert getattr(actual, field) is False, f"Missing {gate} must close {field}"
            assert actual.reasons.get(field), f"Closed {field} needs an explanatory reason"
        assert actual.publish is False
        assert actual.rendered_preview is False
    for skill in ("lesson_outline@1", "lesson_package@1"):
        actual = project(facts_model(**{**trusted, "skill_handlers": set(SKILL_REFS) - {skill}}))
        assert actual.generate is False, f"Missing {skill} handler must close generation"
        assert actual.reasons.get("generate")
    assert ready.publish is False
    assert ready.rendered_preview is False
    assert isinstance(ready.reasons, dict)
    for field in ("chat", "task_write", "generate", "storage", "structural_preview", "rendered_preview", "publish"):
        assert type(getattr(ready, field)) is bool


def _call_name(call):
    return call.func.id if isinstance(call.func, ast.Name) else getattr(call.func, "attr", "")


def _literal_columns(call):
    return tuple(arg.value for arg in call.args if isinstance(arg, ast.Constant) and isinstance(arg.value, str))


def _declared_unique_keys(class_node):
    """Read concrete declarative metadata without importing SQLAlchemy/models.

    Supports explicit UniqueConstraint, unique Index, single-column unique=True,
    and declarative primary keys. It cannot prove transaction enforcement.
    """
    unique = set()
    primary = []
    for statement in class_node.body:
        target = None
        value = getattr(statement, "value", None)
        if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            target = statement.target.id
        elif isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name):
            target = statement.targets[0].id
        if target and isinstance(value, ast.Call) and _call_name(value) in {"Column", "mapped_column"}:
            explicit = _literal_columns(value)
            column_name = explicit[0] if explicit else target
            flags = {keyword.arg: keyword.value for keyword in value.keywords}
            if isinstance(flags.get("unique"), ast.Constant) and flags["unique"].value is True:
                unique.add((column_name,))
            if isinstance(flags.get("primary_key"), ast.Constant) and flags["primary_key"].value is True:
                primary.append(column_name)
        if target != "__table_args__":
            continue
        for node in ast.walk(value):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node)
            if name == "UniqueConstraint":
                unique.add(_literal_columns(node))
            elif name == "Index" and any(keyword.arg == "unique" and isinstance(keyword.value, ast.Constant)
                                           and keyword.value.value is True for keyword in node.keywords):
                unique.add(_literal_columns(node)[1:])
    if primary:
        unique.add(tuple(primary))
    return {frozenset(columns) for columns in unique}


def test_metadata_unique_contract():
    """Plan T1 exact static metadata inventory; no model import, engine or DDL."""
    path = BACKEND / "app/models/teacher_work.py"
    assert path.is_file(), "T1 dedicated metadata feature is missing: app/models/teacher_work.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    expected = {
        "WorkTask": (("owner_subject", "lesson_draft_id"),),
        "WorkMessage": (("task_id", "client_message_key"),),
        "WorkRun": (("owner", "task_id", "kind", "idempotency_key"),),
        "PackageVersion": (("task_id", "version_no"), ("run_id",)),
        "Artifact": (("version_id", "kind"),),
        "PreviewState": (("version_id", "artifact_kind", "kind"),),
        "OwnerRunLease": (("owner",),),
        "CatalogSelection": (("owner",),),
    }
    required_tables = set(expected) | {"OutlineSnapshot", "OutlineApproval", "EvidenceSnapshot", "VersionReview"}
    assert required_tables <= classes.keys(), f"Missing dedicated records: {required_tables - classes.keys()}"
    for name, keys in expected.items():
        actual = _declared_unique_keys(classes[name])
        for columns in keys:
            assert frozenset(columns) in actual, f"{name} must uniquely constrain {columns}"



def _lesson_payload():
    return {"title": "合成教案", "topic": "合成主题", "course_name": "",
            "audience": "合成对象", "duration_minutes": 45,
            "objectives": ["合成目标"], "key_points": [], "difficulties": [],
            "questions": [], "exercises": [], "homework": [], "summary": "",
            "teaching_flow": [{"stage": "合成阶段", "minutes": 45, "content": "合成正文"}],
            "citations": []}


def _slide_payload():
    return {"layout": "bullets", "title": "合成页面", "body": ["合成要点"],
            "columns": [], "notes": "", "source_note": "", "evidence_refs": []}


def test_lesson_limits_and_duration():
    """Missing bounded lesson shape or silently retained invalid content is RED."""
    lesson = _schema("LessonSnapshot")
    base = _lesson_payload()
    parsed = lesson.model_validate(base)
    assert parsed.teaching_flow[0].minutes == parsed.duration_minutes
    twenty = {**base, "duration_minutes": 20,
              "teaching_flow": [{"stage": "合成阶段", "minutes": 1, "content": "教" * 2000} for _ in range(20)]}
    assert len(lesson.model_validate(twenty).teaching_flow) == 20
    _reject(lesson, {**twenty, "duration_minutes": 21,
                     "teaching_flow": twenty["teaching_flow"] + [{"stage": "多余", "minutes": 1, "content": "教"}]})
    _reject(lesson, {**base, "teaching_flow": [{"stage": "阶段", "minutes": 45, "content": "教" * 2001}]})
    _reject(lesson, {**base, "teaching_flow": [{"stage": "阶段", "minutes": 44, "content": "教"}]})
    _reject(lesson, {**base, "duration_minutes": "45"})
    for field in ("objectives", "key_points", "difficulties", "questions", "exercises", "homework", "citations"):
        item = {"name": "合成来源", "page": 1, "excerpt": "合成片段"} if field == "citations" else "合成条目"
        assert len(getattr(lesson.model_validate({**base, field: [deepcopy(item) for _ in range(20)]}), field)) == 20
        _reject(lesson, {**base, field: [deepcopy(item) for _ in range(21)]})
    for forbidden in ("reference_answers", "private_tests", "grading_results", "students", "handler"):
        _reject(lesson, {**base, forbidden: []})


def test_frozen_content_byte_limit():
    """Missing complete-content UTF-8 size check is RED, not transport padding."""
    frozen = _schema("FrozenPackageContent")
    base = {"lesson": _lesson_payload(), "slides": [_slide_payload() for _ in range(6)], "source_snapshots": []}
    assert len(frozen.model_validate(base).slides) == 6
    large_lesson = {**_lesson_payload(), "duration_minutes": 20,
                    "teaching_flow": [{"stage": "阶段", "minutes": 1, "content": "教" * 2000} for _ in range(20)]}
    _schema("LessonSnapshot").model_validate(large_lesson)
    large = {"lesson": large_lesson,
             "slides": [{**_slide_payload(), "notes": "教" * 1200} for _ in range(12)],
             "source_snapshots": []}
    assert len(json.dumps(large, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")) > 128 * 1024
    _reject(frozen, large)
    guard = _schema("validate_teacher_work_frozen_content_size")
    assert guard(b"x" * (128 * 1024)) is None
    with pytest.raises(ValueError):
        guard(b"x" * (128 * 1024 + 1))


def test_utc_and_deep_immutable_dtos():
    """UTC normalization and nested immutability must hold after input mutation."""
    from datetime import datetime, timedelta, timezone
    message = _schema("WorkMessageDTO")
    payload = {"message_id": FIXTURE_UUID, "task_id": FIXTURE_UUID, "owner": "synthetic-owner",
               "client_message_key": "message-1", "role": "user", "plain_text": "合成消息",
               "run_id": None, "result_refs": [],
               "created_at": datetime(2026, 10, 5, 9, tzinfo=timezone(timedelta(hours=8)))}
    dto = message.model_validate(payload)
    assert dto.created_at.utcoffset() == timedelta(0)
    assert dto.created_at.hour == 1
    _reject(message, {**payload, "created_at": datetime(2026, 10, 5, 1)})
    with pytest.raises((ValidationError, TypeError, AttributeError)):
        dto.plain_text = "changed"
    with pytest.raises((TypeError, AttributeError)):
        dto.result_refs.append(FIXTURE_UUID)
    base = {"lesson": _lesson_payload(), "slides": [_slide_payload() for _ in range(6)], "source_snapshots": []}
    frozen = _schema("FrozenPackageContent").model_validate(base)
    base["slides"][0]["body"].append("changed")
    assert len(frozen.slides[0].body) == 1
    with pytest.raises((TypeError, AttributeError)):
        frozen.slides[0].body.append("changed")
    with pytest.raises((TypeError, AttributeError)):
        frozen.lesson.teaching_flow.append(frozen.lesson.teaching_flow[0])
    _schema("FrozenPackageContent").model_validate_json(frozen.model_dump_json())


def test_catalog_enum_contract():
    """Unknown catalog states must not acquire ready/executable meanings."""
    expected = {
        "CatalogCapabilityState": {"IMPLEMENTED", "UNIMPLEMENTED", "DISABLED"},
        "CatalogConnectionState": {"NOT_REQUIRED", "OPERATIONS_READY", "CONFIG_MISSING", "UNSUPPORTED"},
        "CatalogPermissionState": {"READ_ONLY_ALLOWED", "AUTHORIZATION_REQUIRED", "UNAVAILABLE"},
        "CatalogExecutionState": {"NOT_RUN", "SUCCESS", "EMPTY", "PARTIAL_FAILURE", "FAILED", "CANCELLED"},
    }
    for name, values in expected.items():
        enum = _symbol("app.services.teacher_work.types", name)
        assert {item.value for item in enum} == values
        with pytest.raises(ValueError):
            enum("READY_BY_CLIENT")


def test_schema_readiness_contract():
    """Readiness needs exact supplied shape/version/hash; it opens no connection."""
    module = _feature("app.services.teacher_work.schema")
    assert module.TEACHER_WORK_SCHEMA_VERSION == 1
    assert module.TEACHER_WORK_CONTRACT_HASH == _symbol("app.services.teacher_work.types", "canonical_digest")(module.TEACHER_WORK_SCHEMA_CONTRACT)
    inspect = module.inspect_teacher_work_schema
    missing = inspect(None)
    assert missing.ready is False
    assert missing.reasons
    good = {"dialect": "mysql", "tables": deepcopy(module.TEACHER_WORK_SCHEMA_CONTRACT["tables"]),
            "version": module.TEACHER_WORK_SCHEMA_VERSION, "contract_hash": module.TEACHER_WORK_CONTRACT_HASH}
    assert inspect(good).ready is True
    for field, value in (("dialect", "sqlite"), ("version", 0), ("version", True), ("contract_hash", "0" * 64)):
        assert inspect({**good, field: value}).ready is False
    table = next(iter(good["tables"]))
    wrong = deepcopy(good)
    wrong["tables"][table]["columns"] = {}
    assert inspect(wrong).ready is False
    absent = deepcopy(good)
    del absent["tables"][table]
    assert inspect(absent).ready is False
    assert inspect(absent).missing_tables == (table,)


def test_default_config_declarations():
    """AST/template only: defaults do not activate configuration or load Settings."""
    path = BACKEND / "app/core/config.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Settings")
    declarations = {node.target.id: node.value for node in cls.body if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)}
    expected = {"TEACHER_WORK_ENABLED": False, "TEACHER_WORK_STORAGE_ROOT": "",
                "TEACHER_WORK_MAX_ACTIVE_RUNS": 4, "TEACHER_WORK_PACKAGE_TIMEOUT_SECONDS": 300,
                "TEACHER_WORK_REFERENCE_TIMEOUT_SECONDS": 45, "TEACHER_WORK_FILE_TIMEOUT_SECONDS": 30,
                "TEACHER_WORK_MAX_FILE_BYTES": 10 * 1024 * 1024,
                "TEACHER_WORK_OWNER_QUOTA_BYTES": 200 * 1024 * 1024}
    for name, value in expected.items():
        assert name in declarations, f"Missing default declaration: {name}"
        assert ast.literal_eval(declarations[name]) == value
    template = (BACKEND / ".env.example").read_text(encoding="utf-8")
    assert "TEACHER_WORK_ENABLED=false" in template
    assert "TEACHER_WORK_STORAGE_ROOT=\n" in template


def test_additive_migration_and_no_startup_ddl():
    """Static new-module boundary: no implicit SQL/startup/import work is allowed."""
    migration_path = BACKEND / "migrations/v20261005_teacher_work.py"
    assert migration_path.is_file(), "Missing explicit additive prepare/check contract"
    sources = [migration_path, BACKEND / "app/services/teacher_work/schema.py", BACKEND / "app/models/teacher_work.py"]
    for path in sources:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                assert _call_name(node) not in {"create_all", "drop_all", "create_engine", "SessionLocal", "execute", "connect", "commit"}, f"Unapproved DDL/connection call in {path.name}"
            if isinstance(node, ast.ImportFrom):
                assert node.module not in {"app.main", "app.core.config", "app.core.database"}, f"Implicit startup/settings/database import in {path.name}"
    tree = ast.parse(migration_path.read_text(encoding="utf-8"))
    symbols = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert {"prepare_teacher_work_schema", "check_teacher_work_schema"} <= symbols
    main = (BACKEND / "app/main.py").read_text(encoding="utf-8")
    assert "v20261005_teacher_work" not in main
    assert "models.teacher_work" not in main


def test_key_rejects_c1_controls():
    """P2-1: shared client/header keys preserve ordinary text and reject C1."""
    chat = _schema("ChatInput")
    shared_key = TypeAdapter(_schema("MessageKey"))
    for key in ("k", "k" * 128, "é合成"):
        assert shared_key.validate_python(key) == key
        assert chat.model_validate({"text": "合成", "client_message_key": key}).client_message_key == key
    with pytest.raises(ValidationError):
        shared_key.validate_python("k" * 129)
    for codepoint in range(0x80, 0xA0):
        key = "a" + chr(codepoint) + "b"
        with pytest.raises(ValidationError):
            shared_key.validate_python(key)
        _reject(chat, {"text": "合成", "client_message_key": key})


def _mysql_message_storage_declaration():
    """Independent AST-only capacity, not imported ORM or schema-generated facts."""
    path = BACKEND / "app/models/teacher_work.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "WorkMessage")
    declaration = next(node.value for node in cls.body if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == "plain_text" for target in node.targets))
    assert isinstance(declaration, ast.Call) and _call_name(declaration) == "Column"
    assert any(keyword.arg == "nullable" and isinstance(keyword.value, ast.Constant)
               and keyword.value.value is False for keyword in declaration.keywords)
    physical = declaration.args[0]
    if isinstance(physical, ast.Call) and isinstance(physical.func, ast.Attribute) and physical.func.attr == "with_variant":
        assert len(physical.args) == 2 and isinstance(physical.args[1], ast.Constant) and physical.args[1].value == "mysql"
        physical = physical.args[0]
    family = physical.id if isinstance(physical, ast.Name) else _call_name(physical) if isinstance(physical, ast.Call) else ""
    # MySQL byte capacities are independent fixed constants, never app observations.
    capacities = {"Text": ("text", 65535), "TEXT": ("text", 65535),
                  "MEDIUMTEXT": ("mediumtext", 16777215), "LONGTEXT": ("longtext", 4294967295)}
    assert family in capacities, "Message storage must declare a recognized MySQL text family"
    if family in {"MEDIUMTEXT", "LONGTEXT"}:
        assert any(isinstance(node, ast.ImportFrom) and node.module == "sqlalchemy.dialects.mysql"
                   and any(alias.name == family for alias in node.names) for node in tree.body)
    return capacities[family]


def test_multibyte_message_storage_capacity():
    """P2-2: every admitted max-length reply must fit independent storage bytes."""
    from datetime import datetime, timezone
    ai_result = _schema("ChatResult")
    message = _schema("WorkMessageDTO")
    family, capacity = _mysql_message_storage_declaration()
    shape = _feature("app.services.teacher_work.schema").TEACHER_WORK_SCHEMA_CONTRACT["tables"]["teacher_work_messages"]["columns"]["plain_text"]
    assert shape == {"type": family, "nullable": False}, "Physical schema contract must align with independent ORM AST"
    for character in ("教", "𠀀"):
        text = character * 32768
        result = ai_result.model_validate({"type": "answer", "plain_text": text})
        dto = message.model_validate({"message_id": FIXTURE_UUID, "task_id": FIXTURE_UUID,
                                      "owner": "synthetic-owner", "client_message_key": None,
                                      "role": "assistant", "plain_text": text, "run_id": None,
                                      "result_refs": [], "created_at": datetime(2026, 10, 5, tzinfo=timezone.utc)})
        assert result.plain_text == dto.plain_text == text, "Replies must not be silently truncated"
        assert len(text.encode("utf-8")) <= capacity, "Admitted UTF-8 reply exceeds declared MySQL message capacity"
        _reject(ai_result, {"type": "answer", "plain_text": character * 32769})


def test_preparation_rejects_malformed_present_ledger():
    """P2-3: missing ledger allows completion proposal; malformed presence fails."""
    schema = _feature("app.services.teacher_work.schema")
    migration = _feature("migrations.v20261005_teacher_work")
    prepare = migration.prepare_teacher_work_schema
    good = {"dialect": "mysql", "tables": deepcopy(schema.TEACHER_WORK_SCHEMA_CONTRACT["tables"]),
            "version": schema.TEACHER_WORK_SCHEMA_VERSION, "contract_hash": schema.TEACHER_WORK_CONTRACT_HASH}
    exact = prepare(good, contract_hash=schema.TEACHER_WORK_CONTRACT_HASH)
    assert exact.additive_only is True and exact.executable is False
    assert exact.completion_ledger_required is False
    absent = {"dialect": "mysql", "tables": deepcopy(good["tables"])}
    missing = prepare(absent, contract_hash=schema.TEACHER_WORK_CONTRACT_HASH)
    assert missing.completion_ledger_required is True
    assert missing.additive_only is True and missing.executable is False
    assert migration.check_teacher_work_schema(absent).ready is False
    for invalid in ({**good, "version": True}, {**good, "version": "2"},
                    {**good, "version": None}, {**good, "contract_hash": 7},
                    {**good, "contract_hash": None}, {**absent, "version": 1},
                    {**absent, "contract_hash": schema.TEACHER_WORK_CONTRACT_HASH},
                    {**good, "version": 2}, {**good, "contract_hash": "0" * 64}):
        assert migration.check_teacher_work_schema(invalid).ready is False
        with pytest.raises(ValueError):
            prepare(invalid, contract_hash=schema.TEACHER_WORK_CONTRACT_HASH)
