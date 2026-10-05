"""Explicit-only bounded private-task SQL acceptance; no HTTP/auth/AI admission.

Uses real Sessions, current Work ORM and production repository code with a
caller-owned JsonStore binding (its mutation methods are outside this slice).
The supplied private actor is a synthetic trusted fact, not real authorization.
DomainRecord declarations execute unchanged with a test-owned Base so importing
core.database cannot load settings, credentials or the application engine.
"""
import ast
from contextlib import contextmanager
from dataclasses import replace
from datetime import timezone
import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, func, insert, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, declarative_base
from sqlalchemy.sql.ddl import CreateTable

from app.models.teacher_work import OwnerRunLease, PackageVersion, WorkTask
from app.repositories.json_store import JsonStore
from app.repositories.teacher_work import AuthorizedWorkScope, TaskRecord, WorkRepositoryError
from app.repositories.teacher_work_sql import (
    SqlReservationConflict, SqlWorkModels, build_sql_repository,
)
from app.schemas.teacher_work import CreateTaskRequest, WorkingPatchRequest
from app.services.teacher_work.types import WorkActor
from tests.native_teacher_work_mysql import NOW, native_db, native_server, prepare, task_values

OWNER = "native-synthetic-teacher"
NAMESPACE = UUID("10000000-0000-0000-0000-000000000001")


def domain_model():
    path = Path(__file__).resolve().parents[1] / "app/models/domain_record.py"
    tree = ast.parse(path.read_bytes(), filename=str(path))
    base_imports = [n for n in tree.body if isinstance(n, ast.ImportFrom) and n.module == "app.core.database"]
    assert len(base_imports) == 1 and [(n.name, n.asname) for n in base_imports[0].names] == [("Base", None)]
    assert all(isinstance(n, ast.ImportFrom) or isinstance(n, ast.ClassDef) and n.name == "DomainRecord" for n in tree.body)
    assert all(n.module in ("sqlalchemy", "app.core.database") for n in tree.body if isinstance(n, ast.ImportFrom))
    tree.body.remove(base_imports[0])
    namespace = {"Base": declarative_base(), "__name__": __name__}
    exec(compile(tree, str(path), "exec"), namespace)
    return namespace["DomainRecord"]


@pytest.fixture
def repository_db(native_db):
    prepare(native_db)
    domain = domain_model()
    with native_db.engine.connect() as c:
        c.execute(CreateTable(domain.__table__))
    native_db.domain = domain
    return native_db


@contextmanager
def caller(db):
    with db.engine.connect().execution_options(isolation_level="READ COMMITTED") as connection:
        with Session(bind=connection, autoflush=False, expire_on_commit=False) as session:
            session.begin()
            def authorize(owner, offering_id, institution_id):
                assert (owner, offering_id, institution_id) == (OWNER, None, None)
                return AuthorizedWorkScope(WorkActor(OWNER, "teacher", NAMESPACE), None, None)
            repository = build_sql_repository(session,
                models=SqlWorkModels(WorkTask, OwnerRunLease, PackageVersion, db.domain),
                draft_store=JsonStore(session, commit_policy="caller_owned", record_model=db.domain),
                authorize_locked=authorize, clock=lambda: NOW.replace(tzinfo=timezone.utc),
                new_uuid=uuid4, mode="write")
            yield session, repository


def command():
    return CreateTaskRequest(title="合成任务", topic="合成主题", audience="合成对象",
        resource_ids=["synthetic-resource"], scope="private")


def patch(revision, requirements):
    return WorkingPatchRequest.model_validate({"expected_revision": revision,
        "changes": {"requirements": requirements}})


def counts(db):
    with db.engine.connect() as c:
        return tuple(c.execute(select(func.count()).select_from(model)).scalar_one()
            for model in (WorkTask, db.domain, OwnerRunLease))


def snapshot(db):
    with db.engine.connect() as c:
        task = dict(c.execute(select(WorkTask.__table__)).mappings().one())
        draft = dict(c.execute(select(db.domain.__table__)).mappings().one())
        return task, draft


def committed_task(db):
    with caller(db) as (session, repository):
        task = repository.create_task(OWNER, command(), "合成 Key ")
        assert counts(db) == (0, 0, 0), "flushed candidate must not be committed"
        session.commit()
    assert counts(db) == (1, 1, 1)
    return task


def test_private_create_replay_and_conflicting_digest(repository_db):
    db = repository_db
    task = committed_task(db)
    before = snapshot(db)
    statements = []
    def record(c, cursor, statement, params, context, many):
        statements.append(statement)
    event.listen(db.engine, "before_cursor_execute", record)
    try:
        with caller(db) as (session, repository):
            replay = repository.create_task(OWNER, command(), "合成 Key ")
            assert replay == task
            session.commit()
    finally:
        event.remove(db.engine, "before_cursor_execute", record)
    assert statements and all(s.lstrip().upper().startswith("SELECT") for s in statements)
    with caller(db) as (session, repository):
        with pytest.raises(WorkRepositoryError) as error:
            repository.create_task(OWNER, command().model_copy(update={"title": "不同标题"}), "合成 Key ")
        assert error.value.code == "IDEMPOTENCY_CONFLICT" and error.value.status_code == 409
        session.rollback()
    assert snapshot(db) == before and counts(db) == (1, 1, 1)
    assert before[0]["create_idempotency_key"] == "合成 Key ".encode()


def test_private_patch_cas_commit_and_stale_revision(repository_db):
    db = repository_db
    task = committed_task(db)
    updates = []
    def record(c, cursor, statement, params, context, many):
        if statement.lstrip().upper().startswith("UPDATE TEACHER_WORK_TASKS"):
            updates.append(cursor.rowcount)
    event.listen(db.engine, "after_cursor_execute", record)
    try:
        with caller(db) as (session, repository):
            saved = repository.patch_working(OWNER, task.task_id, patch(1, "合成修改"))
            assert (saved.working_revision, saved.input_revision) == (2, 2)
            assert snapshot(db)[0]["working_revision"] == 1
            session.commit()
        assert updates == [1]
        before = snapshot(db)
        assert before[0]["working_revision"] == before[0]["input_revision"] == 2
        assert json.loads(before[1]["payload"])["teacher_work"]["requirements"] == "合成修改"
        with caller(db) as (session, repository):
            with pytest.raises(WorkRepositoryError) as error:
                repository.patch_working(OWNER, task.task_id, patch(1, "陈旧修改"))
            assert error.value.code == "REVISION_CONFLICT"
            session.rollback()
        assert updates == [1] and snapshot(db) == before
    finally:
        event.remove(db.engine, "after_cursor_execute", record)


def test_private_create_rollback_discards_task_draft_and_lease(repository_db):
    db = repository_db
    with caller(db) as (session, repository):
        task = repository.create_task(OWNER, command(), "rolled-back")
        assert session.execute(select(WorkTask.task_id)).all() == [(str(task.task_id),)]
        assert counts(db) == (0, 0, 0)
        session.rollback()
    assert counts(db) == (0, 0, 0)


def test_private_patch_rollback_restores_both_rows(repository_db):
    db = repository_db
    task = committed_task(db)
    before = snapshot(db)
    with caller(db) as (session, repository):
        saved = repository.patch_working(OWNER, task.task_id, patch(1, "回滚修改"))
        assert saved.working_revision == 2
        assert session.execute(select(WorkTask.working_revision)).scalar_one() == 2
        draft = session.execute(select(db.domain.payload)).scalar_one()
        assert json.loads(draft)["teacher_work"]["requirements"] == "回滚修改"
        assert snapshot(db) == before
        session.rollback()
    assert snapshot(db) == before and counts(db) == (1, 1, 1)


def test_native_cas_predicate_miss_returns_false(repository_db):
    db = repository_db
    task = committed_task(db)
    before = snapshot(db)
    with caller(db) as (session, repository):
        repository.get_task(OWNER, task.task_id)
        locked = repository.rows.locked_tasks[(OWNER, task.task_id)]
        changed = replace(locked, task=locked.task.model_copy(update={"working_revision": 2}))
        assert repository.rows.compare_and_swap_task(OWNER, task.task_id, 99, changed) is False
        session.commit()
    assert snapshot(db) == before


def test_late_check_failure_poison_requires_rollback(repository_db):
    db = repository_db
    task = committed_task(db)
    before = snapshot(db)
    with caller(db) as (session, repository):
        repository.patch_working(OWNER, task.task_id, patch(1, "失败前修改"))
        with pytest.raises(OperationalError) as error:
            repository.uow.execute_write(insert(WorkTask).values(**task_values(duration_minutes=0)))
        assert error.value.orig.args[0] == 3819
        assert repository.uow.in_transaction() is False
        with pytest.raises(WorkRepositoryError) as poisoned:
            repository.get_task(OWNER, task.task_id)
        assert poisoned.value.code == "TRANSACTION_REQUIRED"
        session.rollback()
    assert snapshot(db) == before and counts(db) == (1, 1, 1)


def test_real_duplicate_receipt_requires_fresh_reconciliation(repository_db):
    db = repository_db
    task = committed_task(db)
    before = snapshot(db)
    with caller(db) as (session, repository):
        repository.get_task(OWNER, task.task_id)
        locked = repository.rows.locked_tasks[(OWNER, task.task_id)]
        duplicate = TaskRecord(locked.task.model_copy(update={"task_id": uuid4(), "lesson_draft_id": str(uuid4())}),
            locked.create_idempotency_key, locked.create_request_digest)
        repository.rows.insert_task(duplicate)
        with pytest.raises(SqlReservationConflict) as error:
            repository.uow.flush()
        assert error.value.constraint == "uq_tw_task_owner_create_key"
        assert error.value.requires_fresh_transaction is True and repository.uow.in_transaction() is False
        session.rollback()
    assert snapshot(db) == before and counts(db) == (1, 1, 1)
