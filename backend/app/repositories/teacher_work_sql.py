"""Explicit caller-Session Teacher Work SQL primitives, not feature wiring.

The pure coordinator owns command decisions. This module creates no engine,
Session, transaction, schema or default application model. Supplied model/store
bindings and current locked authorization remain trusted bootstrap obligations.
Statement/recording checks cannot certify actual identity or transaction safety.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Callable, Literal
from uuid import UUID

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import SessionTransactionOrigin

from app.repositories.teacher_work import AuthorizedWorkScope, DraftRecord, TaskRecord, TeacherWorkRepository, WorkRepositoryError
from app.schemas.teacher_work import WorkTaskDTO
from app.services.teacher_work.run_persistence import (
    ChatCompletionReceipt, StoredRunState, decode_owner_lease, decode_stored_message,
    decode_stored_run, decode_work_key, encode_work_key, validate_chat_completion,
)
from app.services.teacher_work.runs import OwnerLeaseFacts, WorkRunError
from app.services.teacher_work.types import WorkActor, canonical_json_bytes


@dataclass(frozen=True)
class SqlWorkModels:
    task: type
    owner_run_lease: type
    package_version: type
    domain_record: type


@dataclass(frozen=True)
class SqlRunModels:
    run: type
    message: type


class SqlReservationConflict(WorkRepositoryError):
    """Caller must discard/roll back and authorize a fresh reconciliation.

    No lookup or replay is safe in the Session that raised IntegrityError. This
    outcome does not claim either committed success or a definite DB rollback.
    """
    requires_fresh_transaction = True

    def __init__(self, constraint: str):
        super().__init__("RESERVATION_RECONCILIATION_REQUIRED", 409)
        self.constraint = constraint


def _unavailable() -> WorkRepositoryError:
    return WorkRepositoryError("SQL_PERSISTENCE_UNAVAILABLE", 503)


def _uuid(value: object) -> UUID:
    if type(value) is not str:
        raise _unavailable()
    try:
        result = UUID(value)
    except ValueError:
        raise _unavailable() from None
    if str(result) != value:
        raise _unavailable()
    return result


def _utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise _unavailable()
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _naive_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise _unavailable()
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _active(session) -> None:
    transaction = session.get_transaction()
    if session.in_transaction() is not True or session.in_nested_transaction() is not False or transaction is None or transaction.origin is not SessionTransactionOrigin.BEGIN:
        raise ValueError("explicit active caller transaction required")
    # Real SQLAlchemy leaves a failed root present until caller rollback; its
    # health signal must not be confused with in_transaction's mere presence.
    if (hasattr(session, "is_active") and session.is_active is not True) or (hasattr(transaction, "is_active") and transaction.is_active is not True):
        raise ValueError("failed caller transaction cannot be adopted")


def _one(rows: list):
    if len(rows) > 1:
        raise _unavailable()
    return rows[0] if rows else None


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict:
    """Decode every raw object without silently collapsing original values."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object name")
        result[key] = value
    return result


def _reservation_name(error: IntegrityError, expected: set[str]) -> str | None:
    args = getattr(error.orig, "args", ())
    if len(args) != 2 or type(args[0]) is not int or args[0] != 1062 or type(args[1]) is not str:
        return None
    pieces = args[1].rsplit(" for key ", 1)
    if len(pieces) != 2:
        return None
    token = pieces[1]
    if len(token) < 2 or token[0] not in "\"'" or token[-1] != token[0]:
        return None
    name = token[1:-1].rsplit(".", 1)[-1]
    return name if name in expected else None


class SqlWorkUnitOfWork:
    def __init__(self, session):
        self.session = session
        self._session = session
        self._root = session.get_transaction()
        self._poisoned = False
        self.reservation_constraints: set[str] = set()

    def assert_healthy(self) -> None:
        """Owned health assertion for rows and the later request finalizer.

        Explicit DML failure need not make SQLAlchemy's Session/root inactive.
        This irreversible flag guards the binding, never raw Session operations
        outside it. It performs no I/O and cannot repair or replace a root.
        """
        if self._poisoned:
            raise WorkRepositoryError("SQL_TRANSACTION_POISONED", 503)
        if self.session is not self._session or self.session.get_transaction() is not self._root:
            raise WorkRepositoryError("SQL_BINDING_CHANGED", 503)
        _active(self.session)

    def poison(self) -> None:
        self._poisoned = True

    def execute_write(self, statement):
        self.assert_healthy()
        try:
            return self.session.execute(statement)
        except BaseException:
            self.poison()
            raise

    def in_transaction(self) -> bool:
        try:
            self.assert_healthy()
        except (ValueError, WorkRepositoryError):
            return False
        return True

    def flush(self) -> None:
        self.assert_healthy()
        try:
            self.session.flush()
        except BaseException as error:
            self.poison()
            if isinstance(error, IntegrityError):
                name = _reservation_name(error, self.reservation_constraints)
                if name is not None:
                    raise SqlReservationConflict(name) from None
            raise
        self.reservation_constraints.clear()


class _SqlState:
    def __init__(self, session, mode: Literal["read", "write"]):
        self.session, self.mode = session, mode
        self.actors: dict[str, WorkActor] = {}
        self.leases: dict[str, object] = {}
        self.draft_locks: set[tuple[str, str]] = set()
        self.uow: SqlWorkUnitOfWork | None = None

    def bind_uow(self, uow: SqlWorkUnitOfWork) -> None:
        if (not isinstance(uow, SqlWorkUnitOfWork) or uow.session is not self.session
                or (self.uow is not None and self.uow is not uow)):
            raise ValueError("same caller UoW binding required")
        self.uow = uow

    def owner_locked(self, owner: str, *, write: bool = False) -> WorkActor:
        if self.uow is not None:
            self.uow.assert_healthy()
        _active(self.session)
        actor = self.actors.get(owner)
        if actor is None or owner not in self.leases:
            raise WorkRepositoryError("SQL_LOCK_REQUIRED", 503)
        if write and self.mode != "write":
            raise WorkRepositoryError("READ_ONLY_REPOSITORY", 503)
        return actor


class SqlTaskRows:
    def __init__(self, session, models: SqlWorkModels, uow: SqlWorkUnitOfWork, state: _SqlState):
        self.session, self.models, self.uow, self.state = session, models, uow, state
        state.bind_uow(uow)
        self.locked_tasks: dict[tuple[str, UUID], TaskRecord] = {}

    def _verify(self) -> None:
        self.uow.assert_healthy()
        if (self.uow.session is not self.session or self.state.session is not self.session
                or self.state.uow is not self.uow):
            raise ValueError("same caller task-row binding required")

    def _read(self, statement, *, scalars: bool = True) -> list:
        self._verify()
        with self.session.no_autoflush:
            result = self.session.execute(statement.execution_options(populate_existing=True))
            return result.scalars().all() if scalars else result.all()

    def lock_owner_lease(self, owner: str) -> None:
        self._verify()
        actor = self.state.actors.get(owner)
        if actor is None or actor.subject != owner:
            raise WorkRepositoryError("SQL_LOCK_REQUIRED", 503)
        model = self.models.owner_run_lease
        row = _one(self._read(select(model).where(model.owner == owner).limit(2).with_for_update()))
        if row is None:
            if self.state.mode != "write":
                raise WorkRepositoryError("OWNER_NAMESPACE_UNAVAILABLE", 503)
            # Authorizer has already locked current account/authority. Never
            # generate a request-local namespace or reset any existing run row.
            row = model(owner=owner, owner_storage_id=str(actor.owner_storage_id),
                        active_run_id=None, process_instance=None, expires_at=None, revision=1)
            self.session.add(row)
            self.uow.flush()
        elif row.owner != owner:
            raise _unavailable()
        if _uuid(row.owner_storage_id) != actor.owner_storage_id:
            raise WorkRepositoryError("OWNER_NAMESPACE_MISMATCH", 503)
        self.state.leases[owner] = row

    def owner_storage_ids(self, owner: str) -> tuple[UUID, ...]:
        self.state.owner_locked(owner)
        model = self.models.task
        rows = self._read(select(model.owner_subject, model.owner_storage_id).where(model.owner_subject == owner), scalars=False)
        namespaces = [_uuid(self.state.leases[owner].owner_storage_id)]
        for subject, namespace in rows:
            if subject != owner:
                raise _unavailable()
            namespaces.append(_uuid(namespace))
        return tuple(namespaces)

    def _record(self, row, owner: str) -> TaskRecord | None:
        if row is None:
            return None
        if row.owner_subject != owner:
            raise _unavailable()
        try:
            data = {name: getattr(row, name) for name in WorkTaskDTO.model_fields}
            for name in ("task_id", "owner_storage_id"):
                data[name] = _uuid(data[name])
            for name in ("offering_id", "current_outline_id", "latest_version_id"):
                data[name] = _uuid(data[name]) if data[name] is not None else None
            for name in ("skill_refs", "plugin_ids", "reference_ids"):
                if type(data[name]) is not list:
                    raise _unavailable()
                if len(set(data[name])) != len(data[name]):
                    raise _unavailable()
                data[name] = tuple(_uuid(value) for value in data[name]) if name == "reference_ids" else tuple(data[name])
            data["created_at"], data["updated_at"] = _utc(data["created_at"]), _utc(data["updated_at"])
            key = row.create_idempotency_key
            if key is not None:
                if type(key) is not bytes:
                    raise _unavailable()
                key = key.decode("utf-8", errors="strict")
            return TaskRecord(WorkTaskDTO(**data), key, row.create_request_digest)
        except (AttributeError, TypeError, ValueError):
            raise _unavailable() from None

    def find_task(self, owner: str, task_id: UUID) -> TaskRecord | None:
        model = self.models.task
        return self._record(_one(self._read(select(model).where(model.owner_subject == owner, model.task_id == str(task_id)).limit(2))), owner)

    def find_task_by_draft(self, owner: str, draft_id: str) -> TaskRecord | None:
        model = self.models.task
        return self._record(_one(self._read(select(model).where(model.owner_subject == owner, model.lesson_draft_id == draft_id).limit(2))), owner)

    def find_task_by_create_key(self, owner: str, key: str) -> TaskRecord | None:
        model = self.models.task
        row = _one(self._read(select(model).where(model.owner_subject == owner, model.create_idempotency_key == key.encode("utf-8")).limit(2)))
        record = self._record(row, owner)
        if record is not None and record.create_idempotency_key != key:
            raise _unavailable()
        return record

    def lock_task(self, owner: str, task_id: UUID) -> TaskRecord | None:
        self.state.owner_locked(owner)
        model = self.models.task
        record = self._record(_one(self._read(select(model).where(model.owner_subject == owner, model.task_id == str(task_id)).limit(2).with_for_update())), owner)
        if record is not None:
            if record.task.task_id != task_id:
                raise _unavailable()
            self.locked_tasks[(owner, task_id)] = record
        return record

    @staticmethod
    def _values(row: TaskRecord) -> dict:
        values = row.task.model_dump(mode="json")
        values["created_at"] = _naive_utc(row.task.created_at)
        values["updated_at"] = _naive_utc(row.task.updated_at)
        values["create_idempotency_key"] = row.create_idempotency_key.encode("utf-8") if row.create_idempotency_key is not None else None
        values["create_request_digest"] = row.create_request_digest
        return values

    def insert_task(self, row: TaskRecord) -> None:
        self._verify()
        actor = self.state.owner_locked(row.task.owner_subject, write=True)
        if row.task.owner_storage_id != actor.owner_storage_id:
            raise WorkRepositoryError("OWNER_NAMESPACE_MISMATCH", 503)
        self.session.add(self.models.task(**self._values(row)))
        self.uow.reservation_constraints.add("uq_tw_task_owner_draft")
        if row.create_idempotency_key is not None:
            self.uow.reservation_constraints.add("uq_tw_task_owner_create_key")

    def compare_and_swap_task(self, owner: str, task_id: UUID, expected_revision: int, row: TaskRecord) -> bool:
        self._verify()
        self.state.owner_locked(owner, write=True)
        old = self.locked_tasks.get((owner, task_id))
        if old is None:
            raise WorkRepositoryError("SQL_LOCK_REQUIRED", 503)
        mutable = {"input_revision", "working_revision", "current_outline_id", "latest_version_id", "skill_refs", "plugin_ids", "reference_ids", "target_slide_count", "updated_at"}
        before, after = self._values(old), self._values(row)
        if any(before[name] != after[name] for name in before if name not in mutable):
            raise _unavailable()
        model = self.models.task
        statement = update(model).where(model.owner_subject == owner, model.task_id == str(task_id),
                                        model.working_revision == expected_revision).values(**{name: after[name] for name in mutable}).execution_options(synchronize_session=False)
        result = self.uow.execute_write(statement)
        return type(result.rowcount) is int and result.rowcount == 1

    def version_belongs_to(self, owner: str, task_id: UUID, version_id: UUID) -> bool:
        self.state.owner_locked(owner)
        task, version = self.models.task, self.models.package_version
        statement = select(version.version_id, task.owner_subject, task.task_id).join(task, version.task_id == task.task_id).where(
            task.owner_subject == owner, task.task_id == str(task_id), version.task_id == str(task_id), version.version_id == str(version_id)).limit(2)
        rows = self._read(statement, scalars=False)
        if len(rows) > 1:
            raise _unavailable()
        return bool(rows) and tuple(rows[0]) == (str(version_id), owner, str(task_id))


class SqlOriginalDrafts:
    def __init__(self, session, model: type, state: _SqlState):
        self.session, self.model, self.state = session, model, state
        self.held: dict[tuple[str, str], tuple[object, dict]] = {}

    def _rows(self, owner: str, draft_id: str) -> list:
        model = self.model
        with self.session.no_autoflush:
            return self.session.execute(select(model).where(model.module == "teacher_lesson_prep", model.record_type == "draft",
                model.owner_id == owner, model.record_key == draft_id).limit(2).with_for_update().execution_options(populate_existing=True)).scalars().all()

    @staticmethod
    def _payload(row, owner: str, draft_id: str) -> dict:
        if (row.module, row.record_type, row.owner_id, row.record_key) != ("teacher_lesson_prep", "draft", owner, draft_id) or type(row.payload) is not str:
            raise _unavailable()
        try:
            payload = json.loads(row.payload, object_pairs_hook=_unique_json_object)
            if type(payload) is not dict or payload.get("draft_id") != draft_id:
                raise ValueError("exact draft binding required")
            canonical_json_bytes(payload)
            return payload
        except (TypeError, ValueError):
            raise _unavailable() from None

    def lock_draft(self, owner: str, draft_id: str) -> DraftRecord | None:
        self.state.owner_locked(owner)
        row = _one(self._rows(owner, draft_id))
        if row is None:
            return None
        payload = self._payload(row, owner, draft_id)
        self.held[(owner, draft_id)] = (row, payload)
        self.state.draft_locks.add((owner, draft_id))
        return DraftRecord(owner, draft_id, payload)

    def create_draft(self, draft: DraftRecord) -> None:
        self.state.owner_locked(draft.owner, write=True)
        if _one(self._rows(draft.owner, draft.draft_id)) is not None:
            raise WorkRepositoryError("DRAFT_ALREADY_EXISTS", 409)
        if (draft.module, draft.record_type) != ("teacher_lesson_prep", "draft") or draft.payload.get("draft_id") != draft.draft_id:
            raise _unavailable()
        try:
            created = datetime.fromisoformat(draft.payload["created_at"])
            updated = datetime.fromisoformat(draft.payload["updated_at"])
            row = self.model(module=draft.module, record_type=draft.record_type, record_key=draft.draft_id, owner_id=draft.owner,
                             role="teacher", status="DRAFT", payload=canonical_json_bytes(draft.payload).decode("utf-8"),
                             created_at=_naive_utc(created), updated_at=_naive_utc(updated))
        except (KeyError, TypeError, ValueError):
            raise _unavailable() from None
        self.session.add(row)
        self.held[(draft.owner, draft.draft_id)] = (row, json.loads(row.payload))
        self.state.draft_locks.add((draft.owner, draft.draft_id))

    def write_draft(self, draft: DraftRecord) -> None:
        self.state.owner_locked(draft.owner, write=True)
        held = self.held.get((draft.owner, draft.draft_id))
        if held is None:
            raise WorkRepositoryError("SQL_LOCK_REQUIRED", 503)
        row, prior = held
        self._payload(row, draft.owner, draft.draft_id)
        if (draft.module, draft.record_type) != ("teacher_lesson_prep", "draft") or draft.payload.get("draft_id") != draft.draft_id:
            raise _unavailable()
        encoded = canonical_json_bytes(draft.payload).decode("utf-8")
        updated = row.updated_at
        if draft.payload.get("updated_at") != prior.get("updated_at"):
            try:
                updated = _naive_utc(datetime.fromisoformat(draft.payload["updated_at"]))
            except (KeyError, TypeError, ValueError):
                raise _unavailable() from None
        row.payload, row.status, row.updated_at = encoded, "DRAFT", updated
        self.held[(draft.owner, draft.draft_id)] = (row, json.loads(encoded))


class SqlChatRows:
    """Exact caller-root chat rows; no authority acquisition or business workflow.

    The existing task coordinator must first hold current footprint, owner lease,
    original draft and task. This adapter pins that root and never opens, adopts,
    commits, restarts, repairs or performs a lookup in a failed transaction.
    """
    def __init__(self, session, models: SqlWorkModels, run_models: SqlRunModels,
                 uow: SqlWorkUnitOfWork, state: _SqlState, task_rows: SqlTaskRows):
        _active(session)
        if (not isinstance(models, SqlWorkModels) or not isinstance(run_models, SqlRunModels)
                or not isinstance(uow, SqlWorkUnitOfWork) or not isinstance(state, _SqlState)
                or not isinstance(task_rows, SqlTaskRows) or uow.session is not session
                or state.session is not session or task_rows.session is not session
                or state.uow is not uow
                or task_rows.uow is not uow or task_rows.state is not state or task_rows.models is not models
                or models.task.__table__.name != "teacher_work_tasks"
                or models.owner_run_lease.__table__.name != "teacher_work_owner_run_leases"
                or run_models.run.__table__.name != "teacher_work_runs"
                or run_models.message.__table__.name != "teacher_work_messages"):
            raise ValueError("same caller-root chat collaborators and exact models required")
        self.session, self.models, self.run_models = session, models, run_models
        self.uow, self.state, self.task_rows = uow, state, task_rows
        self._root = session.get_transaction()
        self._runs: dict[tuple[str, UUID, UUID], StoredRunState] = {}
        # ORM snapshots are not dirtied after explicit CAS DML. These detached
        # values track successful statements in this root, never committed facts.
        self._leases: dict[str, OwnerLeaseFacts] = {}
        self._lease_observations: dict[str, OwnerLeaseFacts] = {}

    def _verify(self) -> None:
        self.uow.assert_healthy()
        _active(self.session)
        if (self.session.get_transaction() is not self._root or self.uow.session is not self.session
                or self.state.session is not self.session or self.task_rows.session is not self.session
                or self.task_rows.uow is not self.uow or self.task_rows.state is not self.state
                or self.task_rows.models is not self.models):
            raise ValueError("caller root or chat collaborator binding changed")

    def _owner(self, owner: str, *, write: bool = False) -> WorkActor:
        self._verify()
        actor = self.state.owner_locked(owner, write=write)
        if not isinstance(actor, WorkActor) or actor.subject != owner:
            raise WorkRepositoryError("SQL_LOCK_REQUIRED", 503)
        WorkActor.__post_init__(actor)
        raw = decode_owner_lease(self.state.leases[owner])
        if (raw.owner, raw.owner_storage_id) != (owner, actor.owner_storage_id):
            raise WorkRepositoryError("OWNER_NAMESPACE_MISMATCH", 503)
        return actor

    def _task(self, owner: str, task_id: UUID, *, write: bool = False) -> TaskRecord:
        actor = self._owner(owner, write=write)
        row = self.task_rows.locked_tasks.get((owner, task_id))
        if not isinstance(row, TaskRecord):
            raise WorkRepositoryError("SQL_LOCK_REQUIRED", 503)
        TaskRecord.__post_init__(row)
        if (row.task.owner_subject != owner or row.task.task_id != task_id
                or (owner, row.task.lesson_draft_id) not in self.state.draft_locks
                or row.task.owner_storage_id != actor.owner_storage_id):
            raise WorkRepositoryError("SQL_LOCK_REQUIRED", 503)
        return row

    def _read(self, statement) -> list:
        self._verify()
        with self.session.no_autoflush:
            return self.session.execute(statement.execution_options(populate_existing=True)).scalars().all()

    def lease(self, owner: str) -> OwnerLeaseFacts:
        self._owner(owner)
        observed = decode_owner_lease(self.state.leases[owner])
        original = self._lease_observations.setdefault(owner, observed)
        if observed != original and observed != self._leases.get(owner):
            raise WorkRepositoryError("SQL_LOCK_REQUIRED", 503)
        return self._leases.get(owner, observed)

    @staticmethod
    def _bound_run(state: StoredRunState, owner: str, task_id: UUID, run_id: UUID | None = None) -> StoredRunState:
        if (state.run.owner != owner or state.run.task_id != task_id
                or (run_id is not None and state.run.run_id != run_id)
                or state.run.kind != "chat"):
            raise _unavailable()
        return state

    def find_run_by_key(self, owner: str, task_id: UUID, kind: str, encoded_key: bytes) -> StoredRunState | None:
        decode_work_key(encoded_key)
        self._task(owner, task_id)
        if kind != "chat":
            raise _unavailable()
        model = self.run_models.run
        row = _one(self._read(select(model).where(model.owner == owner, model.task_id == str(task_id),
            model.kind == kind, model.idempotency_key == encoded_key).limit(2).with_for_update()))
        if row is None:
            return None
        state = self._bound_run(decode_stored_run(row), owner, task_id)
        if encode_work_key(state.run.idempotency_key) != encoded_key:
            raise _unavailable()
        self._runs[(owner, task_id, state.run.run_id)] = state
        return state

    def lock_run(self, owner: str, task_id: UUID, run_id: UUID) -> StoredRunState | None:
        self._task(owner, task_id)
        if type(run_id) is not UUID:
            raise _unavailable()
        model = self.run_models.run
        row = _one(self._read(select(model).where(model.owner == owner, model.task_id == str(task_id),
            model.run_id == str(run_id)).limit(2).with_for_update()))
        if row is None:
            return None
        state = self._bound_run(decode_stored_run(row), owner, task_id, run_id)
        self._runs[(owner, task_id, run_id)] = state
        return state

    def find_user_message(self, owner: str, task_id: UUID, encoded_key: bytes):
        decode_work_key(encoded_key)
        self._task(owner, task_id)
        model = self.run_models.message
        row = _one(self._read(select(model).where(model.owner == owner, model.task_id == str(task_id),
            model.role == "user", model.client_message_key == encoded_key).limit(2).with_for_update()))
        if row is None:
            return None
        message, completion = decode_stored_message(row)
        if ((message.owner, message.task_id, message.role) != (owner, task_id, "user")
                or message.client_message_key is None or encode_work_key(message.client_message_key) != encoded_key
                or completion is not None or message.result_type is not None or message.omitted_context is not None):
            raise _unavailable()
        return message

    def _held_run(self, owner: str, task_id: UUID, run_id: UUID) -> StoredRunState:
        state = self._runs.get((owner, task_id, run_id))
        if state is None:
            raise WorkRepositoryError("SQL_LOCK_REQUIRED", 503)
        return self._bound_run(state, owner, task_id, run_id)

    def find_completion(self, owner: str, task_id: UUID, run_id: UUID):
        self._task(owner, task_id)
        state = self._held_run(owner, task_id, run_id)
        model = self.run_models.message
        row = _one(self._read(select(model).where(model.owner == owner, model.task_id == str(task_id),
            model.role == "assistant", model.client_message_key.is_(None),
            model.completion_run_id == str(run_id)).limit(2).with_for_update()))
        if row is None:
            return None
        message, completion = decode_stored_message(row)
        if completion != run_id or message.client_message_key is not None:
            raise _unavailable()
        receipt = validate_chat_completion(state.run, message, completion)
        return receipt, message

    @staticmethod
    def _run_values(state: StoredRunState) -> dict:
        if type(state) is not StoredRunState:
            raise _unavailable()
        StoredRunState.__post_init__(state)
        values = state.run.model_dump(mode="json")
        values["idempotency_key"] = encode_work_key(state.run.idempotency_key)
        values["deadline"] = _naive_utc(state.run.deadline)
        values["cancelled_at"] = _naive_utc(state.run.cancelled_at) if state.run.cancelled_at is not None else None
        values["repair_count"] = state.repair_count
        token = state.active_call
        values.update(active_call_no=token.call_no if token is not None else None,
            active_call_attempt=token.attempt if token is not None else None,
            active_call_lease_revision=token.lease_revision if token is not None else None,
            active_call_process_instance=str(token.process_instance) if token is not None else None)
        return values

    @staticmethod
    def _message_values(message, completion_run_id: UUID | None) -> dict:
        # Revalidate model_copy-produced values, not merely their class identity.
        from app.schemas.teacher_work import WorkMessageDTO
        if not isinstance(message, WorkMessageDTO):
            raise _unavailable()
        try:
            WorkMessageDTO.model_validate(message.model_dump())
        except (TypeError, ValueError):
            raise _unavailable() from None
        values = message.model_dump(mode="json")
        values["client_message_key"] = encode_work_key(message.client_message_key) if message.client_message_key is not None else None
        values["completion_run_id"] = str(completion_run_id) if completion_run_id is not None else None
        values["created_at"] = _naive_utc(message.created_at)
        return values

    def _insert(self, statement, constraints: set[str]) -> None:
        self._verify()
        self.uow.reservation_constraints.update(constraints)
        try:
            with self.session.no_autoflush:
                self.uow.execute_write(statement)
        except IntegrityError as error:
            name = _reservation_name(error, constraints)
            if name is not None:
                raise SqlReservationConflict(name) from None
            raise

    def insert_run(self, state: StoredRunState) -> None:
        values = self._run_values(state)
        self._task(state.run.owner, state.run.task_id, write=True)
        self._bound_run(state, state.run.owner, state.run.task_id)
        self._insert(insert(self.run_models.run).values(**values), {"uq_tw_run_owner_task_kind_key"})
        self._runs[(state.run.owner, state.run.task_id, state.run.run_id)] = state

    def insert_user_message(self, message) -> None:
        values = self._message_values(message, None)
        self._task(message.owner, message.task_id, write=True)
        if (message.role != "user" or message.client_message_key is None or message.run_id is None
                or message.result_type is not None or message.omitted_context is not None or message.result_refs):
            raise _unavailable()
        self._held_run(message.owner, message.task_id, message.run_id)
        self._insert(insert(self.run_models.message).values(**values), {"uq_tw_message_task_client_key"})

    def insert_completion(self, message, receipt: ChatCompletionReceipt) -> None:
        if type(receipt) is not ChatCompletionReceipt:
            raise _unavailable()
        ChatCompletionReceipt.__post_init__(receipt)
        values = self._message_values(message, receipt.run_id)
        self._task(message.owner, message.task_id, write=True)
        state = self._held_run(message.owner, message.task_id, receipt.run_id)
        if message.client_message_key is not None or validate_chat_completion(state.run, message, receipt.run_id) != receipt:
            raise _unavailable()
        self._insert(insert(self.run_models.message).values(**values), {"uq_tw_message_completion_run"})

    def cas_run(self, before: StoredRunState, after: StoredRunState) -> bool:
        old, new = self._run_values(before), self._run_values(after)
        self._task(before.run.owner, before.run.task_id, write=True)
        if self._held_run(before.run.owner, before.run.task_id, before.run.run_id) != before:
            raise WorkRepositoryError("SQL_LOCK_REQUIRED", 503)
        mutable = {"stage", "attempt", "provider_call_count", "repair_count", "cancelled_at", "error_code",
            "active_call_no", "active_call_attempt", "active_call_lease_revision", "active_call_process_instance"}
        if (any(old[name] != new[name] for name in old if name not in mutable)
                or any(new[name] < old[name] for name in ("attempt", "provider_call_count", "repair_count"))):
            raise _unavailable()
        model = self.run_models.run
        expected = {"owner", "task_id", "run_id", "kind", "input_revision", "deadline", "request_digest", "idempotency_key"} | mutable
        predicates = [getattr(model, name).is_(None) if old[name] is None else getattr(model, name) == old[name]
                      for name in sorted(expected)]
        statement = update(model).where(*predicates).values(**{name: new[name] for name in sorted(mutable)}).execution_options(synchronize_session=False)
        with self.session.no_autoflush:
            result = self.uow.execute_write(statement)
        matched = type(getattr(result, "rowcount", None)) is int and result.rowcount == 1
        if matched:
            self._runs[(before.run.owner, before.run.task_id, before.run.run_id)] = after
        return matched

    @staticmethod
    def _lease_values(lease: OwnerLeaseFacts) -> dict:
        if type(lease) is not OwnerLeaseFacts:
            raise _unavailable()
        OwnerLeaseFacts.__post_init__(lease)
        return {"owner": lease.owner, "owner_storage_id": str(lease.owner_storage_id),
            "active_run_id": str(lease.active_run_id) if lease.active_run_id is not None else None,
            "process_instance": str(lease.process_instance) if lease.process_instance is not None else None,
            "expires_at": _naive_utc(lease.expires_at) if lease.expires_at is not None else None,
            "revision": lease.revision}

    def cas_lease(self, before: OwnerLeaseFacts, after: OwnerLeaseFacts) -> bool:
        old, new = self._lease_values(before), self._lease_values(after)
        self._owner(before.owner, write=True)
        if self.lease(before.owner) != before:
            raise WorkRepositoryError("SQL_LOCK_REQUIRED", 503)
        if (new["owner"] != old["owner"] or new["owner_storage_id"] != old["owner_storage_id"]
                or new["revision"] != old["revision"] + 1):
            raise _unavailable()
        # A lease cannot be renewed/swapped under an active call. Reservation
        # and release must bind an actually held or inserted owner/task run.
        if (before.active_run_id is None) == (after.active_run_id is None):
            raise _unavailable()
        target = before.active_run_id if before.active_run_id is not None else after.active_run_id
        held = [state for (owner, _task_id, run_id), state in self._runs.items()
                if owner == before.owner and run_id == target]
        if len(held) != 1:
            raise WorkRepositoryError("SQL_LOCK_REQUIRED", 503)
        self._task(before.owner, held[0].run.task_id, write=True)
        model = self.models.owner_run_lease
        predicates = [getattr(model, name).is_(None) if old[name] is None else getattr(model, name) == old[name]
                      for name in old]
        mutable = ("active_run_id", "process_instance", "expires_at", "revision")
        statement = update(model).where(*predicates).values(**{name: new[name] for name in mutable}).execution_options(synchronize_session=False)
        with self.session.no_autoflush:
            result = self.uow.execute_write(statement)
        matched = type(getattr(result, "rowcount", None)) is int and result.rowcount == 1
        if matched:
            self._leases[before.owner] = after
        return matched


def build_sql_repository(session, *, models: SqlWorkModels, draft_store,
                         authorize_locked: Callable[[str, UUID | None, str | None], AuthorizedWorkScope],
                         clock: Callable[[], datetime], new_uuid: Callable[[], UUID],
                         mode: Literal["read", "write"],
                         run_models: SqlRunModels | None = None) -> TeacherWorkRepository:
    """Bind one fresh explicit caller transaction; never open/adopt/commit one.

    Returned DTOs are uncommitted candidates. T3 owns real current authorization,
    namespace resolution, final admission after all flush/waits and commit-before-
    response. Account reuse and actual MySQL acceptance remain closed gates.
    """
    _active(session)
    if session.new or session.dirty or session.deleted or mode not in ("read", "write"):
        raise ValueError("fresh caller Session and trusted mode required")
    if not isinstance(models, SqlWorkModels) or draft_store.db is not session or draft_store.commit_policy != "caller_owned" or draft_store.record_model is not models.domain_record:
        raise ValueError("same-session caller-owned model/store participation required")
    tables = ((models.task, "teacher_work_tasks"), (models.owner_run_lease, "teacher_work_owner_run_leases"),
              (models.package_version, "teacher_work_package_versions"), (models.domain_record, "domain_records"))
    if any(model.__table__.name != name for model, name in tables) or any(not callable(value) for value in (authorize_locked, clock, new_uuid)):
        raise ValueError("exact supplied model/dependency bindings required")
    uow, state = SqlWorkUnitOfWork(session), _SqlState(session, mode)
    rows, drafts = SqlTaskRows(session, models, uow, state), SqlOriginalDrafts(session, models.domain_record, state)
    def authorize(owner: str, offering_id: UUID | None, institution_id: str | None) -> AuthorizedWorkScope:
        scope = authorize_locked(owner, offering_id, institution_id)
        if not isinstance(scope, AuthorizedWorkScope) or scope.actor.subject != owner:
            raise WorkRepositoryError("NOT_FOUND", 404)
        state.actors[owner] = scope.actor
        return scope
    chat_rows = SqlChatRows(session, models, run_models, uow, state, rows) if run_models is not None else None
    return TeacherWorkRepository(uow=uow, rows=rows, drafts=drafts, authorize_locked=authorize,
        clock=clock, new_uuid=new_uuid, run_rows=chat_rows)
