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

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import SessionTransactionOrigin

from app.repositories.teacher_work import AuthorizedWorkScope, DraftRecord, TaskRecord, TeacherWorkRepository, WorkRepositoryError
from app.schemas.teacher_work import WorkTaskDTO
from app.services.teacher_work.types import WorkActor, canonical_json_bytes


@dataclass(frozen=True)
class SqlWorkModels:
    task: type
    owner_run_lease: type
    package_version: type
    domain_record: type


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
        self.reservation_constraints: set[str] = set()

    def in_transaction(self) -> bool:
        try:
            _active(self.session)
        except ValueError:
            return False
        return True

    def flush(self) -> None:
        _active(self.session)
        try:
            self.session.flush()
        except IntegrityError as error:
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

    def owner_locked(self, owner: str, *, write: bool = False) -> WorkActor:
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
        self.locked_tasks: dict[tuple[str, UUID], TaskRecord] = {}

    def _read(self, statement, *, scalars: bool = True) -> list:
        _active(self.session)
        with self.session.no_autoflush:
            result = self.session.execute(statement.execution_options(populate_existing=True))
            return result.scalars().all() if scalars else result.all()

    def lock_owner_lease(self, owner: str) -> None:
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
        actor = self.state.owner_locked(row.task.owner_subject, write=True)
        if row.task.owner_storage_id != actor.owner_storage_id:
            raise WorkRepositoryError("OWNER_NAMESPACE_MISMATCH", 503)
        self.session.add(self.models.task(**self._values(row)))
        self.uow.reservation_constraints.add("uq_tw_task_owner_draft")
        if row.create_idempotency_key is not None:
            self.uow.reservation_constraints.add("uq_tw_task_owner_create_key")

    def compare_and_swap_task(self, owner: str, task_id: UUID, expected_revision: int, row: TaskRecord) -> bool:
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
        result = self.session.execute(statement)
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


def build_sql_repository(session, *, models: SqlWorkModels, draft_store,
                         authorize_locked: Callable[[str, UUID | None, str | None], AuthorizedWorkScope],
                         clock: Callable[[], datetime], new_uuid: Callable[[], UUID],
                         mode: Literal["read", "write"]) -> TeacherWorkRepository:
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
    return TeacherWorkRepository(uow=uow, rows=rows, drafts=drafts, authorize_locked=authorize, clock=clock, new_uuid=new_uuid)
