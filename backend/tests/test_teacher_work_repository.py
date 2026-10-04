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
               "app.schemas.teacher_work", "app.services.teacher_work.types", "app.services.teacher_work.legacy"}
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
