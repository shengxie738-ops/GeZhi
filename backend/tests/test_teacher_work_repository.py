"""Finite T2a pure coordinator checks; recording primitives are not SQL evidence.

Only the exact reviewed offline snapshot may execute this file. No application,
ORM, database, settings, service startup, providers or external fixtures.
"""
from __future__ import annotations

import ast
from copy import deepcopy
from datetime import datetime, timezone
import importlib
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.schemas.teacher_work import CreateTaskRequest, WorkingPatchRequest
from app.services.teacher_work.types import WorkActor, canonical_digest


BACKEND = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 5, tzinfo=timezone.utc)
NS_A = UUID("10000000-0000-0000-0000-000000000001")
NS_B = UUID("10000000-0000-0000-0000-000000000002")
OWN_VERSION = UUID("20000000-0000-0000-0000-000000000001")
OTHER_VERSION = UUID("20000000-0000-0000-0000-000000000002")
MISSING = UUID("20000000-0000-0000-0000-000000000003")
REFERENCE = UUID("30000000-0000-0000-0000-000000000001")
OFFERING = UUID("40000000-0000-0000-0000-000000000001")


def _module():
    assert (BACKEND / "app/repositories/teacher_work.py").is_file(), "T2a production coordinator is missing"
    return importlib.import_module("app.repositories.teacher_work")


def lesson(minutes=45):
    return {"title": "合成教案", "topic": "合成主题", "audience": "合成对象",
            "course_name": "合成课程", "duration_minutes": minutes,
            "objectives": ["目标"], "key_points": [], "difficulties": [],
            "questions": [], "exercises": [], "homework": [], "summary": "摘要",
            "teaching_flow": [{"stage": "讲解", "minutes": minutes, "content": "正文"}],
            "citations": [{"name": "课件", "page": 1, "excerpt": "原文"}]}


def request(**changes):
    return CreateTaskRequest.model_validate({"title": "合成任务", "topic": "合成主题",
        "audience": "合成对象", "resource_ids": ["resource-1", "resource-2"],
        "scope": "private", **changes})


def patch(revision, changes, **extra):
    return WorkingPatchRequest.model_validate({"expected_revision": revision, "changes": changes, **extra})


class RecordingRowsDraftsUoW:
    """Exact data primitives used by the production command coordinator.

    No create/import/patch feature logic lives here. Snapshot restoration is a
    caller-owned recording transaction, not a claim of real database rollback.
    """
    def __init__(self, module):
        self.module = module
        self.tasks = {}
        self.drafts = {}
        self.versions = {}
        self.approvals = [{"approval_id": "old-approval", "input_revision": 1}]
        self.events = []
        self.active = False
        self.commits = 0
        self.rollbacks = 0
        self.writes = 0
        self.fail_at = None
        self.counter = 1
        self.actors = {"A": WorkActor("A", "teacher", NS_A), "B": WorkActor("B", "teacher", NS_B)}
        self.institution = "institution-1"
        self.reference_owners = {}
        self.catalog_writes = self.run_writes = self.provider_calls = 0

    def __enter__(self):
        assert not self.active
        self.active = True
        self.snapshot = deepcopy((self.tasks, self.drafts, self.versions, self.approvals, self.writes))
        self.events.append("caller.begin")
        return self

    def __exit__(self, kind, value, traceback):
        if kind is None:
            self.commits += 1
            self.events.append("caller.commit")
        else:
            self.tasks, self.drafts, self.versions, self.approvals, self.writes = self.snapshot
            self.rollbacks += 1
            self.events.append("caller.rollback")
        self.active = False

    def in_transaction(self):
        return self.active

    def flush(self):
        self.events.append("flush")

    def authorize_locked(self, owner, offering_id, institution_id):
        self.events.append("footprint")
        actor = self.actors[owner]
        resolved = self.institution if offering_id is not None else None
        return self.module.AuthorizedWorkScope(actor, resolved, offering_id)

    def new_uuid(self):
        value = UUID(int=0x50000000000000000000000000000000 + self.counter)
        self.counter += 1
        return value

    def lock_owner_lease(self, owner):
        self.events.append("lease")

    def owner_storage_ids(self, owner):
        return tuple(row.task.owner_storage_id for row in self.tasks.values() if row.task.owner_subject == owner)

    def find_task(self, owner, task_id):
        row = self.tasks.get(task_id)
        return row if row and row.task.owner_subject == owner else None

    def find_task_by_draft(self, owner, draft_id):
        return next((row for row in self.tasks.values()
                     if row.task.owner_subject == owner and row.task.lesson_draft_id == draft_id), None)

    def find_task_by_create_key(self, owner, key):
        return next((row for row in self.tasks.values()
                     if row.task.owner_subject == owner and row.create_idempotency_key == key), None)

    def lock_task(self, owner, task_id):
        self.events.append("task")
        return self.find_task(owner, task_id)

    def insert_task(self, row):
        self.events.append("task")
        assert row.task.task_id not in self.tasks
        self.tasks[row.task.task_id] = deepcopy(row)
        self.writes += 1

    def compare_and_swap_task(self, owner, task_id, expected_revision, row):
        self.events.append("task.cas")
        old = self.find_task(owner, task_id)
        if old is None or old.task.working_revision != expected_revision:
            return False
        self.tasks[task_id] = deepcopy(row)
        self.writes += 1
        if self.fail_at == "task.cas":
            raise RuntimeError("synthetic task CAS failure")
        return True

    def version_belongs_to(self, owner, task_id, version_id):
        return self.versions.get(version_id, {}).get("binding") == (owner, task_id)

    def lock_draft(self, owner, draft_id):
        self.events.append("draft")
        return self.drafts.get((owner, draft_id))

    def create_draft(self, row):
        self.events.append("draft")
        assert (row.owner, row.draft_id) not in self.drafts
        self.drafts[(row.owner, row.draft_id)] = deepcopy(row)
        self.writes += 1

    def write_draft(self, row):
        self.events.append("draft.write")
        assert (row.owner, row.draft_id) in self.drafts
        self.drafts[(row.owner, row.draft_id)] = deepcopy(row)
        self.writes += 1
        if self.fail_at == "draft.write":
            raise RuntimeError("synthetic draft write failure")

    def resolve_reference(self, owner, task_id, reference_id):
        return self.reference_owners.get(reference_id) == (owner, task_id)

    def seed_draft(self, owner="A", draft_id="legacy-1", content=None):
        payload = {"draft_id": draft_id, "title": "旧任务", "topic": "旧主题", "duration_minutes": 45,
                   "resource_ids": ["resource-1"], "content": deepcopy(content if content is not None else lesson()),
                   "status": "DRAFT", "created_at": NOW.isoformat(), "updated_at": NOW.isoformat()}
        self.drafts[(owner, draft_id)] = self.module.DraftRecord(owner, draft_id, payload)
        return deepcopy(payload)


def setup_repository(*, references=True):
    module = _module()
    memory = RecordingRowsDraftsUoW(module)
    repository = module.TeacherWorkRepository(uow=memory, rows=memory, drafts=memory,
        authorize_locked=memory.authorize_locked, clock=lambda: NOW, new_uuid=memory.new_uuid,
        resolve_reference=memory.resolve_reference if references else None)
    return repository, memory


def create(repository, memory, owner="A", key="create-1", **changes):
    with memory:
        return repository.create_task(owner, request(**changes), key)


def rejection(code, action):
    with pytest.raises(Exception) as caught:
        action()
    assert getattr(caught.value, "code", None) == code
    return caught.value


def test_create_task_has_one_current_draft():
    repository, memory = setup_repository()
    task = create(repository, memory)
    assert len(memory.tasks) == len(memory.drafts) == 1
    row = memory.tasks[task.task_id]
    draft = memory.drafts[("A", task.lesson_draft_id)]
    assert task.owner_storage_id == NS_A and task.input_revision == task.working_revision == 1
    assert task.current_outline_id is task.latest_version_id is None
    assert task.skill_refs == task.plugin_ids == task.reference_ids == ()
    assert draft.module == "teacher_lesson_prep" and draft.record_type == "draft"
    assert draft.payload["status"] == "DRAFT" and draft.payload["resource_ids"] == ["resource-1", "resource-2"]
    assert draft.payload["content"]["audience"] == "合成对象"
    assert draft.payload["teacher_work"]["requirements"] == ""
    assert draft.payload["teacher_work"]["base_version_id"] is None
    assert row.create_idempotency_key == "create-1"
    assert row.create_request_digest == canonical_digest({"request": request().model_dump(mode="json"),
                                                         "institution_id": None, "offering_id": None})
    assert not {"lesson", "resource_ids", "requirements"} & set(vars(row))
    assert memory.versions == {} and memory.approvals == [{"approval_id": "old-approval", "input_revision": 1}]


def test_create_task_same_key_replays():
    repository, memory = setup_repository()
    first = create(repository, memory, key="课题 Key ")
    writes = memory.writes
    second = create(repository, memory, key="课题 Key ")
    assert second == first and memory.writes == writes and len(memory.drafts) == 1
    assert memory.tasks[first.task_id].create_idempotency_key == "课题 Key "
    third = create(repository, memory, key="课题 Key")
    assert third.task_id != first.task_id
    for key in ("", "x\n", "x\x85", "x" * 129):
        with pytest.raises(ValidationError):
            with memory:
                repository.create_task("A", request(), key)
    memory.actors["A"] = WorkActor("B", "teacher", NS_A)
    with memory:
        rejection("NOT_FOUND", lambda: repository.create_task("A", request(), "课题 Key "))


def test_create_task_key_digest_conflicts():
    repository, memory = setup_repository()
    create(repository, memory)
    original = deepcopy((memory.tasks, memory.drafts, memory.writes))
    for changed in ({"topic": "新主题"}, {"resource_ids": ["resource-2", "resource-1"]}):
        with memory:
            error = rejection("IDEMPOTENCY_CONFLICT", lambda: repository.create_task("A", request(**changed), "create-1"))
            assert error.status_code == 409
    assert (memory.tasks, memory.drafts, memory.writes) == original
    assert create(repository, memory, "B").owner_subject == "B"
    scoped = create(repository, memory, key="offering", scope="offering", offering_id=OFFERING)
    assert scoped.institution_id == "institution-1"
    memory.institution = "institution-2"
    with memory:
        rejection("IDEMPOTENCY_CONFLICT", lambda: repository.create_task("A", request(scope="offering", offering_id=OFFERING), "offering"))


def test_owner_namespace_is_trusted_and_stable():
    repository, memory = setup_repository()
    first = create(repository, memory)
    assert create(repository, memory, key="create-2").owner_storage_id == first.owner_storage_id == NS_A
    memory.actors["A"] = WorkActor("A", "teacher", NS_B)
    before = memory.writes
    with memory:
        rejection("OWNER_NAMESPACE_MISMATCH", lambda: repository.create_task("A", request(), "create-3"))
    assert memory.writes == before
    memory.actors["A"] = WorkActor("A", "teacher", NS_A)
    with memory:
        assert repository.get_task("A", first.task_id) == first


def test_from_legacy_returns_same_task():
    repository, memory = setup_repository()
    raw = memory.seed_draft(content={**lesson(), "unknown_paragraph": {"text": ["原文"]}})
    with memory:
        first = repository.from_legacy("A", "legacy-1")
    writes = memory.writes
    with memory:
        assert repository.from_legacy("A", "legacy-1") == first
    stored = memory.drafts[("A", "legacy-1")].payload
    assert stored["draft_id"] == first.lesson_draft_id == "legacy-1"
    assert stored["content"] == raw["content"] and stored["created_at"] == raw["created_at"] and stored["updated_at"] == raw["updated_at"]
    assert "unknown_paragraph" in stored["teacher_work"]["needs_normalization_fields"]
    assert memory.writes == writes and len(memory.tasks) == 1 and memory.versions == {}
    assert memory.tasks[first.task_id].create_idempotency_key is None
    assert memory.tasks[first.task_id].create_request_digest is None
    blank = memory.seed_draft(draft_id="legacy-blank", content={**lesson(), "audience": " "})
    before = memory.writes
    with memory:
        error = rejection("NORMALIZATION_REQUIRED", lambda: repository.from_legacy("A", "legacy-blank"))
    assert error.fields == ("content.audience",)
    assert memory.writes == before and memory.drafts[("A", "legacy-blank")].payload == blank


def test_task_and_draft_cross_owner_not_found():
    repository, memory = setup_repository()
    task = create(repository, memory, "B")
    memory.seed_draft("B", "legacy-B")
    for draft_id in ("legacy-B", "missing"):
        with memory:
            assert rejection("NOT_FOUND", lambda: repository.from_legacy("A", draft_id)).status_code == 404
    for task_id in (task.task_id, MISSING):
        with memory:
            rejection("NOT_FOUND", lambda: repository.get_task("A", task_id))
            rejection("NOT_FOUND", lambda: repository.patch_working("A", task_id, patch(1, {})))


def test_working_cas_rolls_back_draft():
    repository, memory = setup_repository()
    task = create(repository, memory)
    row = memory.tasks[task.task_id]
    memory.tasks[task.task_id] = _module().TaskRecord(row.task.model_copy(update={"current_outline_id": OWN_VERSION}),
                                                   row.create_idempotency_key, row.create_request_digest)
    original = deepcopy((memory.tasks, memory.drafts, memory.approvals, memory.writes))
    for failure in (None, "draft.write", "task.cas"):
        memory.fail_at = failure
        with pytest.raises(Exception) as caught:
            with memory:
                repository.patch_working("A", task.task_id, patch(2 if failure is None else 1, {"requirements": "改变"}))
        if failure is None:
            assert caught.value.code == "REVISION_CONFLICT"
        else:
            assert isinstance(caught.value, RuntimeError)
        assert (memory.tasks, memory.drafts, memory.approvals, memory.writes) == original
        assert memory.commits == 1 and memory.rollbacks >= 1


def test_working_revision_and_input_revision():
    repository, memory = setup_repository()
    task = create(repository, memory)
    memory.reference_owners[REFERENCE] = ("A", task.task_id)
    row = memory.tasks[task.task_id]
    memory.tasks[task.task_id] = _module().TaskRecord(row.task.model_copy(update={"current_outline_id": OWN_VERSION}),
                                                   row.create_idempotency_key, row.create_request_digest)
    for changes in ({"requirements": "要求"}, {"lesson": lesson()}, {"resource_ids": ["resource-2"]},
                    {"skill_refs": ["lesson_outline@1"]}, {"plugin_ids": ["arxiv"]},
                    {"reference_ids": [REFERENCE]}, {"target_slide_count": 9}):
        with memory:
            saved = repository.patch_working("A", task.task_id, patch(task.working_revision, changes))
        assert saved.working_revision == task.working_revision + 1
        assert saved.input_revision == task.input_revision + 1 and saved.current_outline_id is None
        task = saved
    payload = deepcopy(memory.drafts[("A", task.lesson_draft_id)].payload)
    for changes in ({}, {"requirements": "要求"}):
        with memory:
            saved = repository.patch_working("A", task.task_id, patch(task.working_revision, changes))
        assert saved.working_revision == task.working_revision + 1 and saved.input_revision == task.input_revision
        task = saved
    with memory:
        saved = repository.patch_working("A", task.task_id, patch(task.working_revision, {"requirements": "", "skill_refs": [], "plugin_ids": [], "reference_ids": []}))
    stored = memory.drafts[("A", task.lesson_draft_id)].payload
    assert stored["content"] == payload["content"] and stored["resource_ids"] == payload["resource_ids"]
    assert stored["teacher_work"]["requirements"] == "" and "requirements" not in stored["content"]
    before = deepcopy((memory.tasks, memory.drafts, memory.writes))
    with memory:
        assert repository.get_task("A", saved.task_id) == saved
    assert (memory.tasks, memory.drafts, memory.writes) == before
    for changes in ({"lesson": None}, {"resource_ids": None}, {"collapsed": True}, {"view_epoch": 2}):
        with pytest.raises(ValidationError):
            patch(saved.working_revision, changes)
    assert memory.approvals == [{"approval_id": "old-approval", "input_revision": 1}]


def test_working_lesson_matches_task_duration():
    repository, memory = setup_repository()
    task = create(repository, memory)
    with memory:
        task = repository.patch_working("A", task.task_id, patch(1, {"lesson": lesson()}))
    before = deepcopy((memory.tasks, memory.drafts, memory.writes))
    with memory:
        rejection("LESSON_DURATION_MISMATCH", lambda: repository.patch_working("A", task.task_id, patch(2, {"lesson": lesson(30)})))
    assert (memory.tasks, memory.drafts, memory.writes) == before


def test_working_base_version_ancestry():
    repository, memory = setup_repository()
    task = create(repository, memory)
    row = memory.tasks[task.task_id]
    memory.tasks[task.task_id] = _module().TaskRecord(row.task.model_copy(update={"current_outline_id": OWN_VERSION}),
                                                   row.create_idempotency_key, row.create_request_digest)
    memory.versions[OWN_VERSION] = {"binding": ("A", task.task_id), "lesson": {"text": "历史"}, "review": "旧审阅"}
    memory.versions[OTHER_VERSION] = {"binding": ("B", task.task_id), "lesson": {"text": "B历史"}}
    original_history = deepcopy(memory.versions)
    with memory:
        task = repository.patch_working("A", task.task_id, patch(1, {}, base_version_id=OWN_VERSION))
    assert memory.drafts[("A", task.lesson_draft_id)].payload["teacher_work"]["base_version_id"] == str(OWN_VERSION)
    assert task.input_revision == 2 and task.current_outline_id is None
    before = deepcopy((memory.tasks, memory.drafts, memory.writes))
    for version in (OTHER_VERSION, MISSING):
        with memory:
            rejection("BASE_VERSION_NOT_FOUND", lambda: repository.patch_working("A", task.task_id, patch(2, {}, base_version_id=version)))
    memory.versions[OTHER_VERSION]["binding"] = ("A", MISSING)
    with memory:
        rejection("BASE_VERSION_NOT_FOUND", lambda: repository.patch_working("A", task.task_id, patch(2, {}, base_version_id=OTHER_VERSION)))
    assert (memory.tasks, memory.drafts, memory.writes) == before
    assert memory.versions[OWN_VERSION] == original_history[OWN_VERSION]
    with memory:
        task = repository.patch_working("A", task.task_id, patch(2, {}))
    assert memory.drafts[("A", task.lesson_draft_id)].payload["teacher_work"]["base_version_id"] == str(OWN_VERSION)


def test_task_selection_is_bounded_metadata():
    repository, memory = setup_repository(references=False)
    task = create(repository, memory)
    with memory:
        task = repository.patch_working("A", task.task_id, patch(1, {"skill_refs": ["lesson_package@1"], "plugin_ids": ["openalex", "crossref"]}))
    before = deepcopy((memory.tasks, memory.drafts, memory.writes))
    with memory:
        rejection("REFERENCE_UNAVAILABLE", lambda: repository.patch_working("A", task.task_id, patch(2, {"reference_ids": [REFERENCE]})))
    for changes in ({"skill_refs": ["lesson_outline@2"]}, {"plugin_ids": ["europepmc"]},
                    {"skill_refs": ["lesson_outline@1", "lesson_outline@1"]}, {"plugin_ids": ["arxiv", "arxiv"]},
                    {"reference_ids": [REFERENCE, REFERENCE]}, {"resource_ids": ["resource-1", "resource-1"]}):
        with pytest.raises(ValidationError):
            patch(2, changes)
    assert (memory.tasks, memory.drafts, memory.writes) == before
    assert memory.catalog_writes == memory.run_writes == memory.provider_calls == 0
    repository, memory = setup_repository()
    task = create(repository, memory)
    memory.reference_owners[REFERENCE] = ("B", task.task_id)
    with memory:
        rejection("REFERENCE_NOT_FOUND", lambda: repository.patch_working("A", task.task_id, patch(1, {"reference_ids": [REFERENCE]})))


def test_repository_lock_order_and_transaction_ownership():
    repository, memory = setup_repository()
    rejection("TRANSACTION_REQUIRED", lambda: repository.create_task("A", request(), "x"))
    assert memory.events == [] and memory.writes == memory.commits == memory.rollbacks == 0
    with memory:
        task = repository.create_task("A", request(), "x")
        assert memory.commits == 0 and memory.events[:5] == ["caller.begin", "footprint", "lease", "draft", "task"]
    memory.events.clear()
    memory.seed_draft()
    with memory:
        imported = repository.from_legacy("A", "legacy-1")
        assert memory.events[:5] == ["caller.begin", "footprint", "lease", "draft", "task"]
    memory.events.clear()
    with memory:
        repository.patch_working("A", imported.task_id, patch(1, {"requirements": "要求"}))
        assert memory.events[:5] == ["caller.begin", "footprint", "lease", "draft", "task"]
        assert memory.commits == 2
    assert memory.commits == 3 and memory.rollbacks == 0
    rejection("TRANSACTION_REQUIRED", lambda: repository.get_task("A", task.task_id))


def test_t2_pure_import_boundary():
    allowed = {"__future__", "copy", "dataclasses", "datetime", "json", "typing", "uuid", "pydantic",
               "app.schemas.teacher_work", "app.services.teacher_work.types", "app.services.teacher_work.legacy",
               "app.services.teacher_work.run_persistence", "app.services.teacher_work.runs"}
    for relative in ("app/repositories/teacher_work.py", "app/services/teacher_work/legacy.py"):
        path = BACKEND / relative
        assert path.is_file(), "T2a pure source is missing"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module in allowed
            elif isinstance(node, ast.Import):
                assert all(alias.name in allowed for alias in node.names)
        calls = {getattr(node.func, "attr", getattr(node.func, "id", "")) for node in ast.walk(tree) if isinstance(node, ast.Call)}
        assert not {"commit", "rollback", "begin", "create_engine", "Session", "SessionLocal", "atomic_store", "upsert"} & calls


def test_task_has_no_second_current_lesson():
    model = ast.parse((BACKEND / "app/models/teacher_work.py").read_text(encoding="utf-8"))
    task_node = next(node for node in model.body if isinstance(node, ast.ClassDef) and node.name == "WorkTask")
    fields = {target.id for node in task_node.body if isinstance(node, ast.Assign) for target in node.targets if isinstance(target, ast.Name)}
    assert not {"lesson", "content", "resource_ids", "requirements", "base_version_id"} & fields
    repository, memory = setup_repository()
    task = create(repository, memory)
    assert not {"lesson", "content", "resource_ids", "requirements", "base_version_id"} & set(task.model_fields)
    assert set(vars(memory.tasks[task.task_id])) == {"task", "create_idempotency_key", "create_request_digest"}


def test_working_lesson_preserves_opaque_legacy_fields():
    repository, memory = setup_repository()
    provenance = {"resource_id": "resource-1", "score": 0.9, "course": "课程", "frontend_url": "/courseware/resource-1"}
    raw = {**lesson(), "unknown_paragraph": {"text": ["原文"]}, "model": "old-model",
           "citations": [{**lesson()["citations"][0], **provenance}]}
    memory.seed_draft(content=raw)
    with memory:
        task = repository.from_legacy("A", "legacy-1")
    row = memory.tasks[task.task_id]
    memory.tasks[task.task_id] = _module().TaskRecord(row.task.model_copy(update={"current_outline_id": OWN_VERSION}),
                                                   row.create_idempotency_key, row.create_request_digest)
    before = deepcopy((memory.tasks, memory.drafts, memory.approvals, memory.writes))
    known = {**lesson(), "summary": "只编辑已知摘要"}
    try:
        with memory:
            saved = repository.patch_working("A", task.task_id, patch(1, {"lesson": known}))
    except _module().WorkRepositoryError as error:
        assert error.code == "NORMALIZATION_REQUIRED" and error.status_code == 422
        assert (memory.tasks, memory.drafts, memory.approvals, memory.writes) == before
        return
    stored = memory.drafts[("A", task.lesson_draft_id)].payload
    assert stored["content"].get("unknown_paragraph") == raw["unknown_paragraph"]
    assert stored["content"].get("model") == "old-model"
    assert {key: stored["content"]["citations"][0].get(key) for key in provenance} == provenance
    assert stored["content"]["summary"] == "只编辑已知摘要"
    assert "unknown_paragraph" in stored["teacher_work"]["needs_normalization_fields"]
    assert saved.input_revision == saved.working_revision == 2 and saved.current_outline_id is None
    assert memory.approvals == before[2] and memory.versions == {}
    # A changed citation cannot silently discard provenance it cannot represent.
    unsafe = {**known, "citations": [{**known["citations"][0], "name": "另一来源"}]}
    before = deepcopy((memory.tasks, memory.drafts, memory.approvals, memory.writes))
    with pytest.raises(_module().WorkRepositoryError) as caught:
        with memory:
            repository.patch_working("A", task.task_id, patch(2, {"lesson": unsafe}))
    assert caught.value.code == "NORMALIZATION_REQUIRED" and caught.value.status_code == 422
    assert (memory.tasks, memory.drafts, memory.approvals, memory.writes) == before


def test_legacy_duration_mismatch_is_marked_on_import_and_save():
    repository, memory = setup_repository()
    original = memory.seed_draft(content=lesson(30))  # Outer envelope remains45.
    with memory:
        task = repository.from_legacy("A", "legacy-1")
    stored = memory.drafts[("A", "legacy-1")].payload
    assert task.duration_minutes == 45 and stored["content"] == original["content"]
    assert stored["created_at"] == original["created_at"] and stored["updated_at"] == original["updated_at"]
    assert stored["teacher_work"]["needs_normalization_fields"] == ["duration_minutes", "teaching_flow"]
    for changes in ({"requirements": "保持原始分钟数"}, {}):
        with memory:
            task = repository.patch_working("A", task.task_id, patch(task.working_revision, changes))
        stored = memory.drafts[("A", "legacy-1")].payload
        assert stored["content"] == original["content"] and stored["draft_id"] == "legacy-1"
        assert stored["teacher_work"]["needs_normalization_fields"] == ["duration_minutes", "teaching_flow"]
        assert stored["content"]["duration_minutes"] == stored["content"]["teaching_flow"][0]["minutes"] == 30
    assert memory.versions == {} and memory.approvals == [{"approval_id": "old-approval", "input_revision": 1}]


# T2b: exact statement/metadata/recording-transport selection, initially RED only.
# This does not authorize SQLAlchemy imports until its separate closure release.
def _sql_module():
    assert (BACKEND / "app/repositories/teacher_work_sql.py").is_file(), "T2b SQL adapter is missing"
    return importlib.import_module("app.repositories.teacher_work_sql")


class RecordingSqlResult:
    def __init__(self, values=(), rowcount=0):
        self.values = list(values)
        self.rowcount = rowcount

    def scalars(self):
        return self

    def all(self):
        return list(self.values)

    def first(self):
        return self.values[0] if self.values else None


class RecordingSqlQuery:
    """Only the existing JsonStore query transport DSL, not feature behavior."""
    def __init__(self, session, statement):
        self.session, self.statement = session, statement

    def filter(self, *predicates):
        self.statement = self.statement.where(*predicates)
        return self

    def order_by(self, *columns):
        self.statement = self.statement.order_by(*columns)
        return self

    def with_for_update(self):
        self.statement = self.statement.with_for_update()
        return self

    def first(self):
        return self.session.execute(self.statement.limit(1)).scalars().first()

    def all(self):
        return self.session.execute(self.statement).scalars().all()


class RecordingSqlTransport:
    """Supplied rows/statements only. Never a SQLAlchemy Session or database."""
    def __init__(self, sql, origin):
        self.sql = sql
        self.origin = origin
        self.active = True
        self.nested = False
        self.info = {}
        self.new, self.dirty, self.deleted = [], [], []
        self.added, self.statements, self.events, self.batches = [], [], [], []
        self.update_rowcount = 1
        self.flush_error = None
        self.failed = False
        self.tracked = []

    def in_transaction(self):
        return self.active

    def in_nested_transaction(self):
        return self.nested

    def get_transaction(self):
        return self if self.active else None

    @property
    def no_autoflush(self):
        return self

    def __enter__(self):
        self.events.append("no_autoflush.enter")
        return self

    def __exit__(self, kind, value, traceback):
        self.events.append("no_autoflush.exit")

    def execute(self, statement):
        assert not self.failed, "no query/replay in a failed transport"
        self.statements.append(statement)
        self.events.append("execute")
        if statement.is_update:
            return RecordingSqlResult(rowcount=self.update_rowcount)
        assert self.batches, "unexpected SQL transport read"
        return RecordingSqlResult(self.batches.pop(0))

    def query(self, model):
        return RecordingSqlQuery(self, self.sql.select(model))

    def add(self, row):
        self.events.append("add")
        self.added.append(row)
        self.new.append(row)

    def flush(self):
        self.events.append("flush")
        if self.flush_error is not None:
            self.failed = True
            raise self.flush_error
        self.new.clear()
        self.dirty.clear()

    def refresh(self, row):
        self.events.append("refresh")

    def begin(self, *args, **kwargs):
        raise AssertionError("adapter must not begin a transaction")

    def begin_nested(self, *args, **kwargs):
        raise AssertionError("adapter must not start a savepoint")

    def commit(self):
        raise AssertionError("adapter must not commit")

    def rollback(self):
        raise AssertionError("adapter must not roll back")


def _sql_fixture(mode="write"):
    module = _sql_module()  # Feature assertion precedes every SQLAlchemy import.
    store_tree = ast.parse((BACKEND / "app/repositories/json_store.py").read_text(encoding="utf-8"))
    store_class = next(node for node in store_tree.body if isinstance(node, ast.ClassDef) and node.name == "JsonStore")
    store_init = next(node for node in store_class.body if isinstance(node, ast.FunctionDef) and node.name == "__init__")
    assert {"commit_policy", "record_model"} <= {argument.arg for argument in store_init.args.kwonlyargs}, "T2b safe caller-owned store seam is missing"
    sql = importlib.import_module("sqlalchemy")
    orm = importlib.import_module("sqlalchemy.orm")
    mysql = importlib.import_module("sqlalchemy.dialects.mysql.base")
    work = importlib.import_module("app.models.teacher_work")
    base = orm.declarative_base()

    class DomainRecordFixture(base):
        __tablename__ = "domain_records"
        id = sql.Column(sql.Integer, primary_key=True, index=True, autoincrement=True)
        module = sql.Column(sql.String(64), index=True, nullable=False)
        record_type = sql.Column(sql.String(64), index=True, nullable=False)
        record_key = sql.Column(sql.String(255), index=True, nullable=False)
        owner_id = sql.Column(sql.String(255), index=True, default="")
        role = sql.Column(sql.String(32), default="")
        status = sql.Column(sql.String(64), default="")
        payload = sql.Column(sql.Text, nullable=False)
        created_at = sql.Column(sql.TIMESTAMP)
        updated_at = sql.Column(sql.TIMESTAMP)

    models = module.SqlWorkModels(task=work.WorkTask, owner_run_lease=work.OwnerRunLease,
                                  package_version=work.PackageVersion, domain_record=DomainRecordFixture)
    session = RecordingSqlTransport(sql, orm.SessionTransactionOrigin.BEGIN)
    store_module = importlib.import_module("app.repositories.json_store")
    store = store_module.JsonStore(session, commit_policy="caller_owned", record_model=DomainRecordFixture)
    task_id = UUID("60000000-0000-0000-0000-000000000001")
    payload = {"draft_id": "legacy-1", "title": "旧任务", "topic": "旧主题", "duration_minutes": 45,
               "resource_ids": ["resource-1"], "content": lesson(), "status": "DRAFT",
               "created_at": NOW.isoformat(), "updated_at": NOW.isoformat(),
               "teacher_work": {"requirements": "", "base_version_id": None, "needs_normalization_fields": []}}
    draft = DomainRecordFixture(id=1, module="teacher_lesson_prep", record_type="draft", record_key="legacy-1",
                               owner_id="A", role="teacher", status="DRAFT", payload=importlib.import_module("json").dumps(payload, ensure_ascii=False),
                               created_at=NOW.replace(tzinfo=None), updated_at=NOW.replace(tzinfo=None))
    task = work.WorkTask(task_id=str(task_id), owner_subject="A", owner_storage_id=str(NS_A), institution_id=None,
                        offering_id=None, title="旧任务", topic="旧主题", audience="合成对象", duration_minutes=45,
                        target_slide_count=8, lesson_draft_id="legacy-1", input_revision=1, working_revision=1,
                        current_outline_id=None, latest_version_id=None, skill_refs=[], plugin_ids=[], reference_ids=[],
                        create_idempotency_key="课题 Key ".encode("utf-8"), create_request_digest="a" * 64,
                        created_at=NOW.replace(tzinfo=None), updated_at=NOW.replace(tzinfo=None))
    lease = work.OwnerRunLease(owner="A", owner_storage_id=str(NS_A), active_run_id=str(OWN_VERSION),
                               process_instance=str(OTHER_VERSION), expires_at=NOW.replace(tzinfo=None), revision=3)
    session.tracked = [draft, task, lease]
    def authorize(owner, offering_id, institution_id):
        session.events.append("footprint")
        return _module().AuthorizedWorkScope(WorkActor(owner, "teacher", NS_A), None, None)
    repository = module.build_sql_repository(session, models=models, draft_store=store,
                                             authorize_locked=authorize, clock=lambda: NOW,
                                             new_uuid=lambda: UUID("60000000-0000-0000-0000-000000000002"), mode=mode)
    return {"module": module, "sql": sql, "orm": orm, "dialect": mysql.MySQLDialect(), "models": models,
            "session": session, "store": store, "repository": repository, "task": task, "draft": draft,
            "lease": lease, "task_id": task_id, "payload": payload, "authorize": authorize}


def _compiled(fixture, statement):
    compiled = statement.compile(dialect=fixture["dialect"])
    return str(compiled), compiled.params


def _sql_task_batches(fixture, drafts=None):
    return [[fixture["task"]], [fixture["lease"]], [("A", str(NS_A))],
            [fixture["draft"]] if drafts is None else drafts, [fixture["task"]]]


def _sql_locked_owner(fixture):
    repository, session = fixture["repository"], fixture["session"]
    repository.authorize_locked("A", None, None)
    session.batches = [[fixture["lease"]]]
    repository.rows.lock_owner_lease("A")


def test_sql_task_owner_draft_and_lock_predicates():
    fixture = _sql_fixture("read")
    repository, session = fixture["repository"], fixture["session"]
    session.batches = _sql_task_batches(fixture)
    task = repository.get_task("A", fixture["task_id"])
    assert task.owner_subject == "A" and task.owner_storage_id == NS_A and task.created_at.tzinfo == timezone.utc
    assert len(session.statements) == 5
    statements = [_compiled(fixture, statement) for statement in session.statements]
    assert "FOR UPDATE" not in statements[0][0] and "FOR UPDATE" in statements[1][0]
    assert "domain_records" in statements[3][0] and "FOR UPDATE" in statements[3][0]
    assert "teacher_work_tasks" in statements[4][0] and "FOR UPDATE" in statements[4][0]
    for index in (0, 1, 3, 4):
        assert "A" in statements[index][1].values()
        assert session.statements[index].get_execution_options().get("populate_existing") is True
    assert str(fixture["task_id"]) in statements[0][1].values()
    assert {"teacher_lesson_prep", "draft", "legacy-1"} <= set(statements[3][1].values())
    assert session.events.index("footprint") < session.events.index("execute", session.events.index("footprint"))
    assert not session.added and "flush" not in session.events
    session.batches = [[fixture["task"]], [fixture["lease"]], [("A", str(NS_A))], [fixture["draft"], fixture["draft"]]]
    error = rejection("SQL_PERSISTENCE_UNAVAILABLE", lambda: repository.get_task("A", fixture["task_id"]))
    assert error.status_code == 503


def test_sql_working_cas_expected_revision_predicate():
    fixture = _sql_fixture()
    repository, session = fixture["repository"], fixture["session"]
    session.batches = _sql_task_batches(fixture)
    saved = repository.patch_working("A", fixture["task_id"], patch(1, {"requirements": "SQL合成要求"}))
    assert saved.working_revision == saved.input_revision == 2
    update = next(statement for statement in session.statements if statement.is_update)
    text, params = _compiled(fixture, update)
    assert "teacher_work_tasks.owner_subject" in text and "teacher_work_tasks.task_id" in text
    assert "teacher_work_tasks.working_revision" in text and "WHERE" in text
    assert params["owner_subject_1"] == "A" and params["task_id_1"] == str(fixture["task_id"])
    assert params["working_revision_1"] == 1 and params["working_revision"] == 2
    assert "create_idempotency_key" not in text.split("WHERE")[0] and "owner_storage_id" not in text.split("WHERE")[0]
    assert session.events.count("flush") == 1
    fixture = _sql_fixture()
    repository, session = fixture["repository"], fixture["session"]
    session.batches = _sql_task_batches(fixture)
    session.update_rowcount = 0
    before = fixture["draft"].payload
    error = rejection("REVISION_CONFLICT", lambda: repository.patch_working("A", fixture["task_id"], patch(1, {"requirements": "失败候选"})))
    assert error.status_code == 409 and "flush" not in session.events
    # Caller-only supplied restoration, not a real rollback/commit assertion.
    fixture["draft"].payload = before
    assert fixture["draft"].payload == before


def test_sql_create_receipt_unique_and_pair_contract():
    fixture = _sql_fixture()
    repository, session, models = fixture["repository"], fixture["session"], fixture["models"]
    assert models.owner_run_lease.__table__.c.owner_storage_id.nullable is False
    assert any(tuple(constraint.columns.keys()) == ("owner_storage_id",)
               for constraint in models.owner_run_lease.__table__.constraints if isinstance(constraint, fixture["sql"].UniqueConstraint))
    _sql_locked_owner(fixture)
    session.batches = [[fixture["task"]]]
    row = repository.rows.find_task("A", fixture["task_id"])
    assert row.create_idempotency_key == "课题 Key " and row.create_request_digest == "a" * 64
    repository.rows.insert_task(row)
    inserted = session.added[-1]
    assert inserted.create_idempotency_key == "课题 Key ".encode("utf-8")
    assert inserted.create_request_digest == "a" * 64
    assert not {"lesson", "content", "resource_ids", "requirements"} & set(models.task.__table__.c.keys())
    session.batches = [[fixture["task"]]]
    repository.rows.find_task_by_create_key("A", "课题 Key ")
    assert "课题 Key ".encode("utf-8") in _compiled(fixture, session.statements[-1])[1].values()
    imported = _module().TaskRecord(row.task, None, None)
    repository.rows.insert_task(imported)
    assert session.added[-1].create_idempotency_key is session.added[-1].create_request_digest is None
    fixture["task"].create_idempotency_key = b"\xff"
    session.batches = [[fixture["task"]]]
    rejection("SQL_PERSISTENCE_UNAVAILABLE", lambda: repository.rows.find_task("A", fixture["task_id"]))
    fixture = _sql_fixture()
    fixture["repository"].authorize_locked("A", None, None)
    fixture["session"].batches = [[]]
    fixture["repository"].rows.lock_owner_lease("A")
    initialized = fixture["session"].added[-1]
    assert initialized.owner == "A" and initialized.owner_storage_id == str(NS_A)
    assert initialized.active_run_id is initialized.process_instance is initialized.expires_at is None
    assert initialized.revision == 1 and fixture["session"].events.index("footprint") < fixture["session"].events.index("add")
    fixture = _sql_fixture()
    fixture["lease"].owner_storage_id = str(NS_B)
    fixture["repository"].authorize_locked("A", None, None)
    fixture["session"].batches = [[fixture["lease"]]]
    rejection("OWNER_NAMESPACE_MISMATCH", lambda: fixture["repository"].rows.lock_owner_lease("A"))
    assert not fixture["session"].added and "flush" not in fixture["session"].events


def test_sql_duplicate_receipt_replay_is_constraint_specific():
    fixture = _sql_fixture()
    integrity_error = importlib.import_module("sqlalchemy.exc").IntegrityError
    cases = ((1062, "uq_tw_task_owner_create_key", True), (1062, "uq_tw_task_owner_draft", True),
             (1452, "foreign_key", False), (1062, "uq_tw_lease_storage_namespace", False),
             (1062, "other_constraint", False))
    for errno, constraint, expected in cases:
        fixture = _sql_fixture()
        repository, session = fixture["repository"], fixture["session"]
        _sql_locked_owner(fixture)
        session.batches = [[fixture["task"]]]
        row = repository.rows.find_task("A", fixture["task_id"])
        repository.rows.insert_task(row)
        original = Exception(errno, f"Duplicate entry 'uq_tw_task_owner_create_key' for key 'teacher_work_tasks.{constraint}'")
        error = integrity_error("synthetic INSERT", {}, original)
        session.flush_error = error
        before_queries = len(session.statements)
        with pytest.raises(Exception) as caught:
            repository.uow.flush()
        if expected:
            assert isinstance(caught.value, fixture["module"].SqlReservationConflict)
            assert caught.value.constraint == constraint and caught.value.requires_fresh_transaction is True
        else:
            assert caught.value is error
        assert len(session.statements) == before_queries and session.failed
    # No failed-session lookup/replay or new transaction is performed here.


def test_sql_json_store_caller_owned_flush_only():
    fixture = _sql_fixture()
    session, store = fixture["session"], fixture["store"]
    session.batches = [[]]
    saved = store.upsert("teacher_lesson_prep", "draft", "legacy-new", {"draft_id": "legacy-new", "status": "DRAFT"}, owner_id="A", role="teacher", status="DRAFT")
    assert saved["draft_id"] == "legacy-new" and session.events[-3:] == ["add", "flush", "refresh"]
    assert store.db is session and store.commit_policy == "caller_owned" and store.record_model is fixture["models"].domain_record
    session.active = False
    before = list(session.events)
    with pytest.raises(ValueError):
        store.upsert("teacher_lesson_prep", "draft", "legacy-new", {"status": "DRAFT"}, owner_id="A")
    assert session.events == before
    session.active = True
    build = fixture["module"].build_sql_repository
    arguments = {"models": fixture["models"], "draft_store": store, "authorize_locked": fixture["authorize"],
                 "clock": lambda: NOW, "new_uuid": lambda: MISSING, "mode": "write"}
    for attribute, invalid, valid in (("active", False, True), ("nested", True, False),
                                     ("origin", fixture["orm"].SessionTransactionOrigin.AUTOBEGIN, fixture["orm"].SessionTransactionOrigin.BEGIN)):
        setattr(session, attribute, invalid)
        with pytest.raises(ValueError):
            build(session, **arguments)
        setattr(session, attribute, valid)
    session.new.append(object())
    with pytest.raises(ValueError):
        build(session, **arguments)
    session.new.clear()
    other = RecordingSqlTransport(fixture["sql"], fixture["orm"].SessionTransactionOrigin.BEGIN)
    with pytest.raises(ValueError):
        build(other, **arguments)
    assert session.events == before
    tree = ast.parse((BACKEND / "app/repositories/json_store.py").read_text(encoding="utf-8"))
    atomic = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "atomic_store")
    calls = {getattr(node.func, "attr", "") for node in ast.walk(atomic) if isinstance(node, ast.Call)}
    assert {"commit", "rollback"} <= calls  # Existing outer legacy owner remains source-aligned, never executed here.
    constructor = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "JsonStore")
    init = next(node for node in constructor.body if isinstance(node, ast.FunctionDef) and node.name == "__init__")
    assert any(isinstance(value, ast.Constant) and value.value == "legacy" for value in init.args.kw_defaults)


def test_sql_original_draft_strict_binding_and_preservation():
    fixture = _sql_fixture()
    _sql_locked_owner(fixture)
    repository, session, draft = fixture["repository"], fixture["session"], fixture["draft"]
    failures = (("owner_id", "B"), ("module", "another"), ("record_type", "another"),
                ("record_key", "another"), ("payload", "{"), ("payload", "[]"),
                ("payload", '{"draft_id":"another"}'))
    for name, value in failures:
        old = getattr(draft, name)
        setattr(draft, name, value)
        session.batches = [[draft]]
        with pytest.raises(_module().WorkRepositoryError) as caught:
            repository.drafts.lock_draft("A", "legacy-1")
        assert caught.value.status_code in (404, 503)
        setattr(draft, name, old)
    session.batches = [[draft]]
    error = rejection("DRAFT_ALREADY_EXISTS", lambda: repository.drafts.create_draft(_module().DraftRecord("A", "legacy-1", fixture["payload"])))
    assert error.status_code == 409 and not session.added
    fixture = _sql_fixture()
    repository, session, draft = fixture["repository"], fixture["session"], fixture["draft"]
    json = importlib.import_module("json")
    original = {**fixture["payload"], "created_at": "2026-09-30T00:00:00+00:00", "updated_at": "2026-09-30T00:00:00+00:00",
                "content": {**lesson(), "unknown_paragraph": {"text": ["原文"]}, "model": "old-model"}}
    draft.payload = json.dumps(original, ensure_ascii=False)
    physical_before = (draft.created_at, draft.updated_at)
    session.batches = [[], [fixture["lease"]], [], [draft], []]
    task = repository.from_legacy("A", "legacy-1")
    stored = json.loads(draft.payload)
    assert stored["content"] == original["content"] and stored["created_at"] == stored["updated_at"] == original["created_at"]
    assert (draft.created_at, draft.updated_at) == physical_before
    assert task.lesson_draft_id == "legacy-1" and "unknown_paragraph" in stored["teacher_work"]["needs_normalization_fields"]
    assert len(session.added) == 1 and isinstance(session.added[0], fixture["models"].task)
    declared = ast.parse((BACKEND / "app/models/domain_record.py").read_text(encoding="utf-8"))
    model = next(node for node in declared.body if isinstance(node, ast.ClassDef) and node.name == "DomainRecord")
    fields = {node.targets[0].id for node in model.body if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)}
    assert fields == set(fixture["models"].domain_record.__table__.c.keys())


def test_sql_read_does_not_initialize_owner():
    fixture = _sql_fixture("read")
    repository, session = fixture["repository"], fixture["session"]
    session.batches = [[fixture["task"]], []]
    error = rejection("OWNER_NAMESPACE_UNAVAILABLE", lambda: repository.get_task("A", fixture["task_id"]))
    assert error.status_code == 503 and not session.added and "flush" not in session.events
    assert all(not statement.is_update for statement in session.statements)
    fixture = _sql_fixture("read")
    repository, session, lease = fixture["repository"], fixture["session"], fixture["lease"]
    original = (lease.owner_storage_id, lease.active_run_id, lease.process_instance, lease.expires_at, lease.revision)
    session.batches = _sql_task_batches(fixture)
    task = repository.get_task("A", fixture["task_id"])
    assert (lease.owner_storage_id, lease.active_run_id, lease.process_instance, lease.expires_at, lease.revision) == original
    assert task.working_revision == task.input_revision == 1 and not session.added and "flush" not in session.events


def test_sql_original_draft_rejects_duplicate_json_keys():
    fixture = _sql_fixture()
    _sql_locked_owner(fixture)
    json = importlib.import_module("json")
    outer = json.dumps(fixture["payload"], ensure_ascii=False)[:-1] + ',"draft_id":"legacy-1"}'
    content = json.dumps(lesson(), ensure_ascii=False)[:-1] + ',"unknown_paragraph":{"text":["first"]},"unknown_paragraph":{"text":["second"]}}'
    envelope = {key: value for key, value in fixture["payload"].items() if key != "content"}
    nested = json.dumps(envelope, ensure_ascii=False)[:-1] + ',"content":' + content + '}'
    for raw in (outer, nested):
        fixture["draft"].payload = raw
        fixture["session"].batches = [[fixture["draft"]]]
        error = rejection("SQL_PERSISTENCE_UNAVAILABLE", lambda: fixture["repository"].drafts.lock_draft("A", "legacy-1"))
        assert error.status_code == 503 and fixture["draft"].payload == raw
        assert not fixture["session"].added and "flush" not in fixture["session"].events


def test_sql_caller_owned_store_rejects_non_json_structures():
    for opaque in ({1: "first", "1": "second"}, (1, 2)):
        fixture = _sql_fixture()
        session = fixture["session"]
        payload = {"draft_id": "legacy-new", "opaque": opaque}
        original = deepcopy(payload)
        session.batches = [[]]  # A broken serializer would attempt this read.
        with pytest.raises((TypeError, ValueError)):
            fixture["store"].upsert("teacher_lesson_prep", "draft", "legacy-new", payload, owner_id="A", role="teacher", status="DRAFT")
        assert payload == original and session.events == session.statements == session.added == []
    fixture = _sql_fixture()
    fixture["session"].batches = [[]]
    payload = {"draft_id": "legacy-new", "opaque": {"1": [1, 2, None, True, "原文"]}}
    saved = fixture["store"].upsert("teacher_lesson_prep", "draft", "legacy-new", payload, owner_id="A", role="teacher", status="DRAFT")
    assert saved["opaque"] == payload["opaque"]
    assert fixture["session"].events[-3:] == ["add", "flush", "refresh"]
