"""Finite T3a pure decisions/request-owner/legacy workflow, tests first.

Recording primitives supply scalar facts and event logs only. No actual identity,
teaching, ORM, Session, service, HTTP, database, callbacks/replay or side effects.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import importlib
from pathlib import Path
from uuid import UUID

import pytest

from app.schemas.teacher_work import WorkTaskDTO
from app.services.teacher_work.types import WorkActor


BACKEND = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 5, tzinfo=timezone.utc)
LATER = NOW + timedelta(seconds=120)
NS_A = UUID("10000000-0000-0000-0000-000000000001")
NS_B = UUID("10000000-0000-0000-0000-000000000002")
TASK = UUID("60000000-0000-0000-0000-000000000001")
OFFERING = UUID("40000000-0000-0000-0000-000000000001")
OTHER = UUID("40000000-0000-0000-0000-000000000002")
NEW_DRAFT = UUID("60000000-0000-0000-0000-000000000002")


def _module():
    assert (BACKEND / "app/services/teacher_work/authorization.py").is_file(), "T3a authorization/request owner is missing"
    return importlib.import_module("app.services.teacher_work.authorization")


def _legacy():
    _module()
    module = importlib.import_module("app.services.teacher_work.legacy")
    assert hasattr(module, "prepare_legacy_save"), "T3a production legacy preparation is missing"
    return module


def task(**changes):
    return WorkTaskDTO(task_id=TASK, owner_subject="A", owner_storage_id=NS_A, title="合成任务", topic="合成主题",
                       audience="合成对象", duration_minutes=45, target_slide_count=8, lesson_draft_id="legacy-1",
                       input_revision=1, working_revision=1, created_at=NOW, updated_at=NOW, **changes)


def failure(code, operation):
    with pytest.raises(Exception) as caught:
        operation()
    assert caught.value.code == code
    return caught.value


def authority(module, *, offering=False, footprint=None):
    return module.HeldWorkAuthority(subject="A", institution_id="institution-1" if offering else None,
        offering_id=OFFERING if offering else None, footprint_token=footprint if footprint is not None else object(),
        policy=module.PolicySnapshot(generation="policy-1", institution_id="institution-1" if offering else None))


class RecordingRequestTransport:
    def __init__(self, module):
        self.module = module
        self.session_token, self.root_token = object(), object()
        self.active = True
        self.events = []
        self.flush_error = self.commit_error = None
        self.confirm_commit = True
        self.pending = False
        self.change_root_on_flush = False

    def session_identity(self):
        return self.session_token

    def root_identity(self):
        return self.root_token

    def in_transaction(self):
        return self.active

    def has_pending_writes(self):
        return self.pending

    def flush(self):
        self.events.append("flush")
        if self.flush_error is not None:
            raise self.flush_error
        if self.change_root_on_flush:
            self.root_token = object()
        self.pending = False

    def commit(self):
        self.events.append("commit")
        if self.commit_error is not None:
            raise self.commit_error
        return self.module.CommitReceipt(confirmed=self.confirm_commit)

    def rollback(self):
        self.events.append("rollback")
        self.active = False

    def close(self):
        self.events.append("close")
        self.active = False


def owner_fixture(*, mode="write", offering=True):
    module = _module()
    held = authority(module, offering=offering)
    transport = RecordingRequestTransport(module)
    actor = WorkActor("A", "teacher", NS_A)
    namespace = module.NamespaceReceipt(subject="A", namespace_id=NS_A, provisional=False, mode=mode,
                                        footprint_token=held.footprint_token)
    state = {"policy": held.policy, "time": LATER, "allow": True, "namespace": module.NamespaceObservation("A", NS_A), "evaluations": []}
    def policy():
        transport.events.append("policy")
        return state["policy"]
    def clock():
        transport.events.append("clock")
        return state["time"]
    def namespace_observer():
        transport.events.append("namespace.verify")
        return state["namespace"]
    def evaluate(footprint, policy_snapshot, now):
        transport.events.append("evaluate")
        state["evaluations"].append((footprint, policy_snapshot, now))
        return module.HeldAdmissionReceipt(subject="A", institution_id=held.institution_id, offering_id=held.offering_id,
            footprint_token=held.footprint_token, policy_generation=policy_snapshot.generation, at=now, allowed=state["allow"])
    owner = module.TeacherWorkRequestOwner(transport=transport, mode=mode, actor=actor, namespace_receipt=namespace,
        authority=held, clock=clock, policy_provider=policy, namespace_observer=namespace_observer, evaluate_held=evaluate)
    candidate = module.BoundCandidate(value={"candidate": "原始结果"}, subject="A", owner_storage_id=NS_A,
                                     institution_id=held.institution_id, offering_id=held.offering_id)
    return module, owner, transport, held, state, candidate


def test_t3_current_role_and_exact_signed_subject():
    module = _module()
    teacher = module.CurrentAccountFacts(username="A", role="teacher")
    assert module.require_current_teacher_facts("A", teacher) == "A"
    for signed, current in ((None, teacher), ("", teacher), ("A", None),
                            ("a", teacher), ("A ", teacher), ("A", module.CurrentAccountFacts("a", "teacher")),
                            ("A", module.CurrentAccountFacts("A", "invalid"))):
        assert failure("INVALID_CURRENT_IDENTITY", lambda: module.require_current_teacher_facts(signed, current)).status_code == 401
    old_teacher_claim = WorkActor("A", "teacher", NS_A)
    assert failure("CURRENT_TEACHER_REQUIRED", lambda: module.require_current_teacher_facts(old_teacher_claim.subject,
        module.CurrentAccountFacts("A", "student"))).status_code == 403


def test_t3_exact_task_owner_namespace_and_scope():
    module = _module()
    actor = WorkActor("A", "teacher", NS_A)
    assert module.authorize_task(actor, task()).actor_subject == "A"
    assert failure("NOT_FOUND", lambda: module.authorize_task(WorkActor("B", "teacher", NS_B), task())).status_code == 404
    assert failure("OWNER_NAMESPACE_MISMATCH", lambda: module.authorize_task(WorkActor("A", "teacher", NS_B), task())).status_code == 503
    bound = task(institution_id="institution-1", offering_id=OFFERING)
    for decision in (None, module.OfferingDecision("A", "institution-2", OFFERING, "READ_OFFERING", True, True),
                     module.OfferingDecision("A", "institution-1", OTHER, "READ_OFFERING", True, True),
                     module.OfferingDecision("B", "institution-1", OFFERING, "READ_OFFERING", True, True)):
        assert failure("OFFERING_AUTHORITY_REQUIRED", lambda: module.authorize_task(actor, bound, decision)).status_code == 403
    good = module.OfferingDecision("A", "institution-1", OFFERING, "READ_OFFERING", True, True)
    context = module.authorize_task(actor, bound, good)
    assert (context.institution_id, context.offering_id, context.task_id) == ("institution-1", OFFERING, TASK)


def test_t3_namespace_first_write_and_read_absence():
    module = _module()
    held = authority(module)
    calls = []
    def new_uuid():
        calls.append("uuid")
        return NS_A
    receipt = module.prepare_namespace_receipt("A", mode="write", authority=held, observation=None,
                                               task_namespace_ids=(), new_uuid=new_uuid)
    assert receipt.provisional is True and receipt.namespace_id == NS_A and calls == ["uuid"]
    again = module.prepare_namespace_receipt("A", mode="write", authority=held, observation=None,
        task_namespace_ids=(), new_uuid=new_uuid, prior=receipt)
    assert again == receipt and calls == ["uuid"]
    assert module.bind_work_actor("A", receipt) == WorkActor("A", "teacher", NS_A)
    existing = module.prepare_namespace_receipt("A", mode="read", authority=held,
        observation=module.NamespaceObservation("A", NS_A), task_namespace_ids=(NS_A,), new_uuid=new_uuid)
    assert existing.provisional is False and calls == ["uuid"]
    failure("OWNER_NAMESPACE_UNAVAILABLE", lambda: module.prepare_namespace_receipt("A", mode="read", authority=held,
        observation=None, task_namespace_ids=(), new_uuid=new_uuid))
    failure("OWNER_NAMESPACE_MISMATCH", lambda: module.prepare_namespace_receipt("A", mode="write", authority=held,
        observation=module.NamespaceObservation("A", NS_A), task_namespace_ids=(NS_B,), new_uuid=new_uuid))
    failure("OWNER_NAMESPACE_MISMATCH", lambda: module.prepare_namespace_receipt("A", mode="read", authority=held,
        observation=module.NamespaceObservation("B", NS_A), task_namespace_ids=(), new_uuid=new_uuid))
    assert calls == ["uuid"]  # This helper never writes a registry or run row.


def test_t3_private_and_offering_authority_split():
    module = _module()
    actor = WorkActor("A", "teacher", NS_A)
    unavailable = module.OfferingDecision("A", "institution-1", OFFERING, "READ_OFFERING", False, False)
    assert module.authorize_task(actor, task(), unavailable).offering_id is None
    bound = task(institution_id="institution-1", offering_id=OFFERING)
    for readable, teaching, action in ((True, False, "READ_OFFERING"), (False, True, "READ_OFFERING"), (True, True, "WRITE_COURSE")):
        failure("OFFERING_AUTHORITY_REQUIRED", lambda: module.authorize_task(actor, bound,
            module.OfferingDecision("A", "institution-1", OFFERING, action, readable, teaching)))
    good = module.OfferingDecision("A", "institution-1", OFFERING, "READ_OFFERING", True, True)
    assert module.authorize_task(actor, bound, good).owner_storage_id == NS_A


def test_t3_final_admission_uses_later_clock_and_held_footprint():
    module, owner, transport, held, state, candidate = owner_fixture()
    assert owner.finish_write(candidate) == candidate.value
    assert state["evaluations"] == [(held, held.policy, LATER)]
    assert transport.events == ["flush", "namespace.verify", "policy", "clock", "evaluate", "commit", "close"]
    module, owner, transport, held, state, candidate = owner_fixture()
    state["allow"] = False  # Supplied later-time authority/expiry denial.
    assert failure("CURRENT_AUTHORITY_DENIED", lambda: owner.finish_write(candidate)).status_code == 403
    assert state["evaluations"][0][2] == LATER and "commit" not in transport.events
    assert transport.events[-2:] == ["rollback", "close"]
    module, owner, transport, held, state, candidate = owner_fixture()
    state["policy"] = module.PolicySnapshot("policy-2", "institution-1")
    failure("POLICY_CHANGED", lambda: owner.finish_write(candidate))
    assert not state["evaluations"] and "commit" not in transport.events
    module, owner, transport, held, state, candidate = owner_fixture()
    transport.change_root_on_flush = True
    failure("REQUEST_BINDING_CHANGED", lambda: owner.finish_write(candidate))
    assert "policy" not in transport.events and "commit" not in transport.events


def test_t3_response_requires_committed_outcome():
    module, owner, transport, held, state, candidate = owner_fixture()
    assert owner.state == "open" and "commit" not in transport.events
    assert owner.finish_write(candidate) is candidate.value and owner.state == "committed"
    failure("REQUEST_FINISHED", lambda: owner.finish_write(candidate))
    module, owner, transport, held, state, candidate = owner_fixture()
    transport.flush_error = RuntimeError("synthetic flush error")
    failure("WRITE_ABORTED", lambda: owner.finish_write(candidate))
    assert owner.state == "aborted" and "commit" not in transport.events
    for commit_error, confirmed in ((RuntimeError("synthetic lost commit acknowledgement"), True), (None, False)):
        module, owner, transport, held, state, candidate = owner_fixture()
        transport.commit_error, transport.confirm_commit = commit_error, confirmed
        error = failure("COMMIT_OUTCOME_UNKNOWN", lambda: owner.finish_write(candidate))
        assert error.status_code == 503 and owner.state == "unknown"
        assert transport.events[-3:] == ["commit", "rollback", "close"]
    module, owner, transport, held, state, candidate = owner_fixture(mode="read")
    assert owner.finish_read(candidate) is candidate.value and owner.state == "read_closed"
    assert "flush" not in transport.events and "commit" not in transport.events
    assert transport.events[-2:] == ["rollback", "close"]


@dataclass(frozen=True)
class SuppliedDraft:
    owner: str
    draft_id: str
    payload: dict
    module: str = "teacher_lesson_prep"
    record_type: str = "draft"


class RecordingLegacyPrimitives:
    """Only supplied observations/row operations, never a legacy feature method."""
    def __init__(self, module, *, linked=False, changed_scope=False, missing=False):
        self.events, self.writes, self.link_reads = [], [], []
        self.active = True
        self.uow = self.rows = self.drafts = self
        self.payload = {"draft_id": "legacy-1", "title": "旧标题", "topic": "旧主题", "duration_minutes": 45,
            "resource_ids": ["resource-1"], "content": {"audience": "对象", "unknown": {"text": ["原文"]}},
            "status": "DRAFT", "created_at": "2026-09-30T00:00:00+00:00", "updated_at": "2026-09-30T00:00:00+00:00"}
        self.original = None if missing else SuppliedDraft("A", "legacy-1", deepcopy(self.payload))
        class Row:
            def __init__(self, value):
                self.task = value
        private, bound = Row(task()), Row(task(institution_id="institution-1", offering_id=OFFERING))
        self.link_reads = [private, private] if linked else [None, bound if changed_scope else None]
        self.locked_task = private if linked else bound
        self.module = module

    def in_transaction(self):
        return self.active

    def flush(self):
        self.events.append("flush")

    def authorize_locked(self, owner, offering_id, institution_id):
        self.events.append("footprint")
        class Scope:
            actor = WorkActor("A", "teacher", NS_A)
        result = Scope()
        result.institution_id, result.offering_id = institution_id, offering_id
        return result

    def lock_owner_lease(self, owner):
        self.events.append("lease")

    def owner_storage_ids(self, owner):
        self.events.append("namespace.check")
        return (NS_A,)

    def find_task_by_draft(self, owner, draft_id):
        self.events.append("link.lookup")
        return self.link_reads.pop(0)

    def lock_task(self, owner, task_id):
        self.events.append("task")
        return self.locked_task

    def lock_draft(self, owner, draft_id):
        self.events.append("draft")
        return self.original

    def create_draft(self, row):
        self.events.append("draft.create")
        self.writes.append(deepcopy(row))

    def write_draft(self, row):
        self.events.append("draft.write")
        self.writes.append(deepcopy(row))


def legacy_request(module, *, new=False):
    return module.LegacySaveInput(draft_id="" if new else "legacy-1", title="修改标题", topic="主题", duration_minutes=45,
        resource_ids=("resource-1",), content={"audience": "对象", "unknown": {"text": ["原文"]}})


def test_t3_legacy_check_and_save_share_ordered_owner():
    module = _legacy()
    repository = RecordingLegacyPrimitives(module)
    calls = []
    def old_save(owner, request):
        calls.append("legacy.fallback")
        return {}
    request = legacy_request(module)
    saved = module.prepare_legacy_save("A", request, registry=module.LegacyRegistryObservation("compatible", True),
        repository=repository, legacy_save=old_save, clock=lambda: NOW, new_uuid=lambda: NEW_DRAFT)
    assert repository.events == ["link.lookup", "footprint", "lease", "namespace.check", "draft", "link.lookup", "draft.write", "flush"]
    assert saved["draft_id"] == "legacy-1" and len(repository.writes) == 1 and not calls
    for linked, changed, code in ((True, False, "LINKED_LEGACY_WRITE_CONFLICT"), (False, True, "LEGACY_SCOPE_CHANGED")):
        repository = RecordingLegacyPrimitives(module, linked=linked, changed_scope=changed)
        error = failure(code, lambda: module.prepare_legacy_save("A", request,
            registry=module.LegacyRegistryObservation("compatible", True), repository=repository,
            legacy_save=old_save, clock=lambda: NOW, new_uuid=lambda: NEW_DRAFT))
        assert error.status_code == 409 and not repository.writes and "flush" not in repository.events and not calls


def test_t3_legacy_registry_modes_preserve_original_payload():
    module = _legacy()
    request = legacy_request(module)
    repository = RecordingLegacyPrimitives(module)
    calls = []
    def old_save(owner, received):
        calls.append((owner, received))
        return deepcopy(repository.payload)
    absent = module.prepare_legacy_save("A", request, registry=module.LegacyRegistryObservation("absent", True),
        repository=repository, legacy_save=old_save, clock=lambda: NOW, new_uuid=lambda: NEW_DRAFT)
    assert absent == repository.payload and calls == [("A", request)] and repository.events == []
    for state, confirmed in (("unknown", False), ("partial", True), ("incompatible", True), ("unavailable", True), ("absent", False)):
        failure("WORK_REGISTRY_UNAVAILABLE", lambda: module.prepare_legacy_save("A", request,
            registry=module.LegacyRegistryObservation(state, confirmed), repository=repository,
            legacy_save=old_save, clock=lambda: NOW, new_uuid=lambda: NEW_DRAFT))
    assert len(calls) == 1 and repository.events == []
    repository = RecordingLegacyPrimitives(module)
    saved = module.prepare_legacy_save("A", request, registry=module.LegacyRegistryObservation("compatible", True),
        repository=repository, legacy_save=old_save, clock=lambda: NOW, new_uuid=lambda: NEW_DRAFT)
    assert saved["created_at"] == repository.payload["created_at"] and saved["content"] == repository.payload["content"]
    assert set(saved) == {"draft_id", "title", "topic", "duration_minutes", "resource_ids", "content", "status", "created_at", "updated_at"}
    repository = RecordingLegacyPrimitives(module, missing=True)
    repository.link_reads = [None]
    new = module.prepare_legacy_save("A", legacy_request(module, new=True), registry=module.LegacyRegistryObservation("compatible", True),
        repository=repository, legacy_save=old_save, clock=lambda: NOW, new_uuid=lambda: NEW_DRAFT)
    assert new["draft_id"] == str(NEW_DRAFT) and new["created_at"] == NOW.isoformat()
    assert repository.events == ["footprint", "lease", "namespace.check", "draft", "link.lookup", "draft.create", "flush"]


def test_t3_preserves_typed_precommit_conflict():
    module, owner, transport, held, state, candidate = owner_fixture()
    base = importlib.import_module("app.repositories.teacher_work").WorkRepositoryError
    class ControlledConflict(base):
        requires_fresh_transaction = True
    conflict = ControlledConflict("RESERVATION_RECONCILIATION_REQUIRED", 409)
    transport.flush_error = conflict
    with pytest.raises(Exception) as caught:
        owner.finish_write(candidate)
    assert owner.state == "aborted" and transport.events == ["flush", "rollback", "close"]
    assert not state["evaluations"] and "commit" not in transport.events
    assert caught.value is conflict and isinstance(caught.value, base)
    assert caught.value.code == "RESERVATION_RECONCILIATION_REQUIRED" and caught.value.status_code == 409
    assert caught.value.requires_fresh_transaction is True
    failure("REQUEST_FINISHED", lambda: owner.finish_write(candidate))
