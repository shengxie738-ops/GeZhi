"""B2 metadata and in-memory SQLite evidence only; never import startup."""
import ast
import importlib
from datetime import datetime
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import CheckConstraint, JSON, String, UniqueConstraint, create_engine, event
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

BACKEND = Path(__file__).resolve().parents[1]
MODEL_NAMES = (
    "Assignment", "AssignmentDraftPrivate", "AssignmentVersion", "PrivateSpec",
    "ReleasePreview", "Release", "ReleaseRecipient", "Submission", "SubmissionHead", "AssessmentEvent",
)
TABLE_NAMES = (
    "teaching_assignments", "teaching_assignment_draft_private", "teaching_assignment_versions",
    "teaching_assignment_private_specs", "teaching_release_previews", "teaching_releases",
    "teaching_release_recipients", "teaching_submissions", "teaching_submission_heads", "teaching_assessment_events",
)
B1_TABLE_NAMES = (
    "teaching_courses", "teaching_offerings", "teaching_enrollments", "teaching_roles",
    "teaching_roster_previews", "teaching_write_receipts", "teaching_access_events", "teaching_schema_versions",
)
B1_HASH = "1b1c73a6578614b3990395660f3fe51ce8f58e32ae9c6c4ed2533dc5586a9e7e"
NOW = datetime(2026, 10, 3, 1, 2, 3, 456789)


def feature(name):
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        assert False, f"Required B2 feature is missing: {name}: {exc}"


def modules():
    return feature("app.models.teaching_assessment"), feature("app.services.teaching.assessment_schema")


def uniques(table):
    return {tuple(c.columns.keys()) for c in table.constraints if isinstance(c, UniqueConstraint)}


def checks(table):
    return {str(c.sqltext) for c in table.constraints if isinstance(c, CheckConstraint)}


def fk_shapes(table):
    return {(tuple(c.columns.keys()), c.referred_table.name, tuple(e.column.name for e in c.elements))
            for c in table.foreign_key_constraints}


def test_b2_tables_are_explicit_only():
    models, schema = modules()
    tables = schema.b2_tables()
    assert tuple(t.name for t in tables) == TABLE_NAMES
    assert tuple(getattr(models, name).__table__ for name in MODEL_NAMES) == tables
    expected = {
        "Assignment": "id institution_id offering_id public_draft draft_revision next_version_number created_by created_at updated_at",
        "AssignmentDraftPrivate": "assignment_id institution_id offering_id private_draft updated_at",
        "AssignmentVersion": "id assignment_id institution_id offering_id version_number source_draft_revision public_spec public_spec_hash frozen_by frozen_at",
        "PrivateSpec": "version_id assignment_id institution_id offering_id private_spec private_spec_hash",
        "ReleasePreview": "id assignment_id version_id institution_id offering_id actor_id actor_role_id actor_role_revision offering_revision roster_revision source_policy_digest recipient_snapshot recipient_count recipient_digest public_spec_hash due_at timezone late_policy policy_digest created_at expires_at",
        "Release": "id assignment_id version_id institution_id offering_id preview_id public_spec_hash recipient_count recipient_digest due_at timezone late_policy policy_digest released_by released_at",
        "ReleaseRecipient": "release_id institution_id offering_id version_id student_id enrollment_id enrollment_revision_at_release accepted_policy_digest",
        "Submission": "id institution_id offering_id release_id version_id student_id parent_submission_id sequence content content_hash ai_usage_declaration received_at",
        "SubmissionHead": "release_id institution_id offering_id version_id student_id submission_id revision",
        "AssessmentEvent": "id receipt_id institution_id offering_id actor_id actor_role action target_type target_id revision_kind before_revision after_revision occurred_at effect_metadata",
    }
    predicate = feature("app.core.schema_policy").startup_table_allowed
    for name, table in zip(MODEL_NAMES, tables):
        assert set(table.columns.keys()) == set(expected[name].split())
        assert table.info["explicit_migration_only"] is True and not predicate(table)
        assert dict(table.dialect_options["mysql"])["engine"] == "InnoDB"
        assert table.dialect_options["mysql"]["charset"] == "utf8mb4"
        assert table.dialect_options["mysql"]["collate"] == "utf8mb4_bin"
        assert all(c.name and len(c.name) <= 64 for c in table.constraints)
        assert all(i.name and len(i.name) <= 64 for i in table.indexes)
        assert not any(f.ondelete or f.onupdate for f in table.foreign_key_constraints)
        assert not any(f.target_fullname.startswith("user_accounts.") for f in table.foreign_keys)
        for column in table.columns:
            if column.name.endswith("_at"):
                assert column.type.dialect_impl(mysql.dialect()).fsp == 6
            if column.name in {"id", "assignment_id", "version_id", "release_id", "preview_id", "submission_id", "parent_submission_id", "enrollment_id", "actor_role_id", "receipt_id", "target_id"}:
                assert isinstance(column.type, String) and column.type.length == 36
            if column.name == "institution_id": assert column.type.length == 64
            if column.name in {"student_id", "actor_id", "created_by", "frozen_by", "released_by"}: assert column.type.length == 255
            if column.name.endswith("_digest") or column.name.endswith("_hash"): assert column.type.length == 64
            if column.name.endswith("revision") or column.name in {"next_version_number", "version_number", "sequence", "recipient_count", "enrollment_revision_at_release"}:
                assert str(column.type) == "BIGINT"
            if column.name == "id": assert callable(column.default.arg)
            if column.name in {"public_draft", "private_draft", "public_spec", "private_spec", "recipient_snapshot", "content", "ai_usage_declaration", "effect_metadata"}:
                assert isinstance(column.type, JSON)
        # Every composite FK has a declared left-prefix supporting index/key.
        support = {tuple(i.columns.keys()) for i in table.indexes} | uniques(table) | {tuple(table.primary_key.columns.keys())}
        for fk in table.foreign_key_constraints:
            columns = tuple(fk.columns.keys())
            assert any(key[:len(columns)] == columns for key in support), (table.name, columns)
    # Read source only. Ordinary startup is never imported or run.
    for path in (BACKEND / "app/main.py", BACKEND / "app/core/init_db.py", BACKEND / "app/api/api.py"):
        imports = [ast.unparse(n) for n in ast.walk(ast.parse(path.read_text())) if isinstance(n, (ast.Import, ast.ImportFrom))]
        assert not any("teaching_assessment" in name or "assessment_schema" in name for name in imports)
    assert "late_policy = 'reject'" in checks(models.ReleasePreview.__table__)
    assert "late_policy = 'reject'" in checks(models.Release.__table__)
    assert "expires_at > created_at" in checks(models.ReleasePreview.__table__)
    assert "source_draft_revision >= 1" in checks(models.AssignmentVersion.__table__)
    assert "revision_kind IN ('assignment_draft', 'assignment_version', 'release_preview', 'release', 'submission_head')" in checks(models.AssessmentEvent.__table__)


def test_b1_contract_and_table_allowlist_unchanged():
    _, schema = modules()
    b1 = feature("app.services.teaching.schema")
    assert b1.B1_COMPONENT == "b1" and b1.B1_SCHEMA_VERSION == 1 and b1.B1_CONTRACT_HASH == B1_HASH
    assert tuple(t.name for t in b1.b1_tables()) == B1_TABLE_NAMES
    assert not set(b1.b1_tables()) & set(schema.b2_tables())
    assert schema.B2_COMPONENT == "b2" and schema.B2_SCHEMA_VERSION == 1
    assert len(schema.B2_CONTRACT_HASH) == 64 and schema.B2_CONTRACT_HASH != B1_HASH


def test_lineage_foreign_keys_bind_scope_and_student():
    models, _ = modules()
    scope = ("institution_id", "offering_id")
    expected = {
        "Assignment": {(("offering_id", "institution_id"), "teaching_offerings", ("id", "institution_id"))},
        "AssignmentDraftPrivate": {(("assignment_id", *scope), "teaching_assignments", ("id", *scope))},
        "AssignmentVersion": {(("assignment_id", *scope), "teaching_assignments", ("id", *scope))},
        "PrivateSpec": {(("version_id", *scope, "assignment_id"), "teaching_assignment_versions", ("id", *scope, "assignment_id"))},
        "ReleasePreview": {(("version_id", *scope, "assignment_id"), "teaching_assignment_versions", ("id", *scope, "assignment_id"))},
        "Release": {
            (("version_id", *scope, "assignment_id"), "teaching_assignment_versions", ("id", *scope, "assignment_id")),
            (("preview_id", *scope, "assignment_id", "version_id"), "teaching_release_previews", ("id", *scope, "assignment_id", "version_id")),
        },
        "ReleaseRecipient": {(("release_id", *scope, "version_id"), "teaching_releases", ("id", *scope, "version_id"))},
        "Submission": {
            (("release_id", *scope, "version_id", "student_id"), "teaching_release_recipients", ("release_id", *scope, "version_id", "student_id")),
            (("parent_submission_id", *scope, "release_id", "version_id", "student_id"), "teaching_submissions", ("id", *scope, "release_id", "version_id", "student_id")),
        },
        "SubmissionHead": {
            (("release_id", *scope, "version_id", "student_id"), "teaching_release_recipients", ("release_id", *scope, "version_id", "student_id")),
            (("submission_id", *scope, "release_id", "version_id", "student_id"), "teaching_submissions", ("id", *scope, "release_id", "version_id", "student_id")),
        },
        "AssessmentEvent": {(("receipt_id",), "teaching_write_receipts", ("id",)), (("offering_id", "institution_id"), "teaching_offerings", ("id", "institution_id"))},
    }
    for name, shapes in expected.items():
        assert fk_shapes(getattr(models, name).__table__) == shapes
    assert not models.Submission.__table__.foreign_keys & models.SubmissionHead.__table__.foreign_keys
    assert not any(f.target_fullname.startswith("teaching_enrollments.") or f.target_fullname.startswith("teaching_roles.")
                   for name in MODEL_NAMES for f in getattr(models, name).__table__.foreign_keys)


def row_values(table, **overrides):
    values = {}
    for column in table.columns:
        name = column.name
        if column.nullable: values[name] = None
        elif isinstance(column.type, JSON): values[name] = {}
        elif name.endswith("_at"): values[name] = NOW
        elif isinstance(column.type, String): values[name] = "a" * 64 if name.endswith(("_digest", "_hash")) else "x"
        else: values[name] = 1
    values.update(institution_id="i", offering_id="offering")
    values.update({k: v for k, v in dict(id="x", assignment_id="assignment", version_id="version", release_id="release", preview_id="preview", student_id="student", receipt_id="receipt").items() if k in table.c})
    values.update(overrides)
    return {k: v for k, v in values.items() if k in table.c}


@contextmanager
def _synthetic_graph():
    models, schema = modules()
    b1 = feature("app.services.teaching.schema")
    engine = create_engine("sqlite:///:memory:")
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _): connection.execute("PRAGMA foreign_keys=ON")
    try:
        for table in (*b1.b1_tables(), *schema.b2_tables()): table.create(engine)
        with engine.begin() as connection:
            core = feature("app.models.teaching")
            connection.execute(core.Course.__table__.insert(), row_values(core.Course.__table__, id="course", title="Course", timezone="UTC"))
            connection.execute(core.Offering.__table__.insert(), row_values(core.Offering.__table__, id="offering", course_id="course", title="Offering", term="term", timezone="UTC", state="active"))
            connection.execute(core.WriteReceipt.__table__.insert(), row_values(core.WriteReceipt.__table__, id="receipt", scope_type="offering", scope_id="offering", canonicalization_version=1, http_status=201))
            settings = {
                "Assignment": dict(id="assignment"), "AssignmentVersion": dict(id="version"),
                "ReleasePreview": dict(id="preview", timezone="UTC", late_policy="reject", recipient_count=1, expires_at=NOW.replace(hour=2)),
                "Release": dict(id="release", timezone="UTC", late_policy="reject", recipient_count=1),
                "SubmissionHead": dict(submission_id=None, revision=0),
                "AssessmentEvent": dict(id="assessment-event", actor_role="teacher", revision_kind="release"),
            }
            for name in MODEL_NAMES:
                if name == "Submission": continue
                table = getattr(models, name).__table__
                connection.execute(table.insert(), row_values(table, **settings.get(name, {})))
        yield models, schema, engine
    finally:
        engine.dispose()


@pytest.fixture
def synthetic_graph():
    managers = []
    def load():
        manager = _synthetic_graph()
        result = manager.__enter__()
        managers.append(manager)
        return result
    try:
        yield load
    finally:
        for manager in reversed(managers): manager.__exit__(None, None, None)


def test_unique_sequence_prevents_two_null_parent_roots(synthetic_graph):
    models, _, engine = synthetic_graph()
    table = models.Submission.__table__
    assert ("release_id", "student_id", "sequence") in uniques(table)
    assert ("parent_submission_id",) in uniques(table)
    assert "(sequence = 1 AND parent_submission_id IS NULL) OR (sequence > 1 AND parent_submission_id IS NOT NULL)" in checks(table)
    with engine.begin() as connection:
        connection.execute(table.insert(), row_values(table, id="root", sequence=1))
        with pytest.raises(IntegrityError): connection.execute(table.insert(), row_values(table, id="root-two", sequence=1))
        connection.execute(table.insert(), row_values(table, id="child", sequence=2, parent_submission_id="root"))
        with pytest.raises(IntegrityError): connection.execute(table.insert(), row_values(table, id="fork", sequence=3, parent_submission_id="root"))
        with pytest.raises(IntegrityError): connection.execute(table.insert(), row_values(table, id="bad-root", sequence=2))
        with pytest.raises(IntegrityError): connection.execute(table.insert(), row_values(table, id="wrong-student", student_id="other", sequence=2, parent_submission_id="root"))


def test_one_release_per_version_and_one_head_per_recipient(synthetic_graph):
    models, _, engine = synthetic_graph()
    assert {("version_id",), ("preview_id",)} <= uniques(models.Release.__table__)
    assert {("assignment_id", "version_number"), ("assignment_id", "source_draft_revision")} <= uniques(models.AssignmentVersion.__table__)
    assert tuple(models.ReleaseRecipient.__table__.primary_key.columns.keys()) == ("release_id", "student_id")
    assert tuple(models.SubmissionHead.__table__.primary_key.columns.keys()) == ("release_id", "student_id")
    with engine.begin() as connection:
        with pytest.raises(IntegrityError): connection.execute(models.Release.__table__.insert(), row_values(models.Release.__table__, id="other", timezone="UTC", late_policy="reject", recipient_count=1))
        with pytest.raises(IntegrityError): connection.execute(models.SubmissionHead.__table__.insert(), row_values(models.SubmissionHead.__table__, submission_id=None, revision=0))
        with pytest.raises(IntegrityError): connection.execute(models.AssignmentVersion.__table__.insert(), row_values(models.AssignmentVersion.__table__, id="other"))


@pytest.mark.parametrize("model_name", ["AssignmentVersion", "PrivateSpec", "ReleasePreview", "Release", "ReleaseRecipient", "Submission", "AssessmentEvent"])
@pytest.mark.parametrize("operation", ["update", "delete"])
def test_frozen_rows_reject_orm_update_delete(synthetic_graph, model_name, operation):
    models, _, engine = synthetic_graph()
    if model_name == "Submission":
        with engine.begin() as connection: connection.execute(models.Submission.__table__.insert(), row_values(models.Submission.__table__, id="root", sequence=1))
    model = getattr(models, model_name)
    with Session(engine) as session:
        row = session.query(model).one()
        if operation == "delete": session.delete(row)
        else:
            field = {"AssignmentVersion": "public_spec", "PrivateSpec": "private_spec", "ReleasePreview": "recipient_snapshot", "Release": "public_spec_hash", "ReleaseRecipient": "accepted_policy_digest", "Submission": "content", "AssessmentEvent": "effect_metadata"}[model_name]
            setattr(row, field, {"changed": True} if isinstance(model.__table__.c[field].type, JSON) else "b" * 64)
        with pytest.raises(ValueError, match="immutable"): session.flush()
        session.rollback()
        assert session.query(model).count() == 1


def test_head_null_revision_consistency(synthetic_graph):
    models, _, engine = synthetic_graph()
    table = models.SubmissionHead.__table__
    assert "(submission_id IS NULL AND revision = 0) OR (submission_id IS NOT NULL AND revision >= 1)" in checks(table)
    with engine.begin() as connection:
        with pytest.raises(IntegrityError): connection.execute(table.update().values(revision=1))
        connection.execute(models.Submission.__table__.insert(), row_values(models.Submission.__table__, id="root", sequence=1))
        with pytest.raises(IntegrityError): connection.execute(table.update().values(submission_id="root", revision=0))
        connection.execute(table.update().values(submission_id="root", revision=1))
        with pytest.raises(IntegrityError): connection.execute(table.update().values(student_id="other"))
