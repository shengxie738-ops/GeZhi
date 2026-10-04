"""B1 synthetic metadata contract. Never import startup or application routers."""
import ast
import importlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import MetaData, Table, Column, String, UniqueConstraint, ForeignKeyConstraint, CheckConstraint, create_engine, event
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

BACKEND = Path(__file__).resolve().parents[1]
DOMAIN = ("Course", "Offering", "Enrollment", "TeachingRole", "RosterPreview", "WriteReceipt", "AccessEvent")
PUBLIC_TEACHING_DEFAULTS = {
    "TEACHING_ENABLED": False,
    "TEACHING_ASSIGNMENTS_ENABLED": False,
    "TEACHING_FEEDBACK_ENABLED": False,
    "TEACHING_REVISIONS_ENABLED": False,
    "TEACHING_INSTITUTION_ID": "",
    "TEACHING_TRUSTED_DELEGATIONS": "{}",
}


def assert_public_teaching_configuration(source):
    """Check actual Settings declarations without importing settings or a local manifest."""
    tree = ast.parse(source)
    settings = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Settings"]
    assert len(settings) == 1, "exactly one actual Settings class is required"
    settings = settings[0]
    for name, expected in PUBLIC_TEACHING_DEFAULTS.items():
        declarations = [n for n in settings.body
                        if (isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.target.id == name)
                        or (isinstance(n, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in n.targets))]
        assert len(declarations) == 1, f"{name} must have exactly one declaration"
        declaration = declarations[0]
        assert isinstance(declaration, ast.AnnAssign), f"{name} must be a typed field"
        assert isinstance(declaration.annotation, ast.Name) and declaration.annotation.id == type(expected).__name__, f"{name} has an unexpected type"
        assert isinstance(declaration.value, ast.Constant), f"{name} must have a literal default"
        value = declaration.value.value
        assert type(value) is type(expected) and value == expected, f"{name} has an unsafe default"
    return settings


@pytest.mark.parametrize("defect", ["duplicate_annotation", "plain_reassignment", "missing", "enabled", "wrong_literal_type", "wrong_annotation", "nonliteral", "nested_decoy", "duplicate_class"])
def test_public_teaching_configuration_guard_rejects_unsafe_source(defect):
    source = "class Settings:\n" + "\n".join(
        f"    {name}: {type(value).__name__} = {value!r}" for name, value in PUBLIC_TEACHING_DEFAULTS.items())
    assert_public_teaching_configuration(source)
    first = "TEACHING_ENABLED: bool = False"
    if defect == "duplicate_annotation":
        source += "\n    " + first
    elif defect == "plain_reassignment":
        source += "\n    TEACHING_ENABLED = False"
    elif defect == "missing":
        source = source.replace("    TEACHING_REVISIONS_ENABLED: bool = False", "")
    elif defect == "enabled":
        source = source.replace(first, "TEACHING_ENABLED: bool = True")
    elif defect == "wrong_literal_type":
        source = source.replace(first, "TEACHING_ENABLED: bool = 0")
    elif defect == "wrong_annotation":
        source = source.replace(first, "TEACHING_ENABLED: int = False")
    elif defect == "nonliteral":
        source = source.replace(first, "TEACHING_ENABLED: bool = bool(0)")
    elif defect == "nested_decoy":
        source = source.replace("class Settings:", "class Other:") + "\nclass Settings:\n    pass"
    else:
        source += "\nclass Settings:\n    pass"
    with pytest.raises(AssertionError):
        assert_public_teaching_configuration(source)


def feature(module):
    try:
        return importlib.import_module(module)
    except ModuleNotFoundError as exc:
        assert False, f"B1 feature module is missing: {module}: {exc}"


def tables():
    models = feature("app.models.teaching")
    ledger = feature("app.models.teaching_schema")
    return [getattr(models, name).__table__ for name in DOMAIN] + [ledger.TeachingSchemaVersion.__table__]


def test_flags_default_off_and_capability_disabled_without_tables():
    settings = assert_public_teaching_configuration((BACKEND / "app/core/config.py").read_text())
    defaults = {n.target.id: ast.literal_eval(n.value) for n in settings.body if isinstance(n, ast.AnnAssign) and isinstance(n.value, ast.Constant)}
    assert "ANALYTICS_RECORDED_TIMEZONE" in defaults
    schema = feature("app.services.teaching.schema")
    class ForbiddenSession:
        def connection(self):
            pytest.fail("disabled capability queried the database")
    report = schema.teaching_capability(session=ForbiddenSession())
    assert report.available is False and report.reason == "disabled"
    assert schema.teaching_capability(enabled=True, institution_id="").reason == "institution_required"
    assert schema.teaching_capability(enabled=False, assignments_enabled=True, institution_id="i").reason == "dependency_disabled"
    assert schema.teaching_capability(enabled=True, institution_id="i", assignments_enabled=True).reason == "assignments_unavailable"
    assert schema.teaching_capability(enabled=True, institution_id="i", feedback_enabled=True).reason == "dependency_disabled"
    assert schema.teaching_capability(enabled=True, institution_id="i", revisions_enabled=True).reason == "dependency_disabled"
    assert schema.teaching_capability(enabled=True, institution_id="i", assignments_enabled=True, feedback_enabled=True, revisions_enabled=True).reason == "revisions_unavailable"
    # Task6 mounts the router while flags/startup-DDL remain independent gates.
    # Structural AST only; never import or execute the aggregate/startup.
    for path in (BACKEND / "app/main.py", BACKEND / "app/api/api.py"):
        if path.exists():
            tree = ast.parse(path.read_text())
            if path.name == "api.py":
                imports = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
                           and n.module == "app.api.endpoints"]
                assert sum(alias.name == "teaching" for node in imports for alias in node.names) == 1
                includes = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                            and isinstance(n.func, ast.Attribute) and n.func.attr == "include_router"]
                assert sum(bool(call.args) and ast.unparse(call.args[0]) == "teaching.router" for call in includes) == 1
            else:
                imports = [ast.unparse(n) for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
                assert not any("teaching" in name for name in imports)
                for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
                    if isinstance(call.func, ast.Attribute) and call.func.attr == "include_router":
                        assert "teaching" not in ast.unparse(call)


def test_startup_selector_excludes_registered_teaching_and_future_assessment_tables():
    predicate = feature("app.core.schema_policy").startup_table_allowed
    assert all(not predicate(table) for table in tables())
    metadata = MetaData()
    future = Table("teaching_assignments", metadata, Column("id", String(36), primary_key=True))
    marked = Table("future_assessment", metadata, Column("id", String(36), primary_key=True), info={"explicit_migration_only": True})
    ordinary = Table("ordinary", metadata, Column("id", String(36), primary_key=True))
    assert not predicate(future) and not predicate(marked) and predicate(ordinary)


def capture_actual_selection(source, objects, predicate):
    """Interpret only the audited actual create_all call, never its containing function."""
    tree = ast.parse(source)
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "init_db"]
    assert len(functions) == 1, "actual named init_db function is required"
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "create_all"]
    assert len(calls) == 1, "startup must have exactly one filtered create_all path"
    # A direct statement belongs to startup itself, never to a nested/unused decoy.
    direct = [n.value for n in functions[0].body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Attribute) and n.value.func.attr == "create_all"]
    assert len(direct) == 1 and direct[0] is calls[0], "create_all must be a direct call in actual init_db"
    call = direct[0]
    assert not call.args and {k.arg for k in call.keywords} == {"bind", "tables"}
    assert ast.unparse(call.func) == "Base.metadata.create_all"
    bind = next(k.value for k in call.keywords if k.arg == "bind")
    assert isinstance(bind, ast.Name) and bind.id == "engine"
    selection = next(k.value for k in call.keywords if k.arg == "tables")
    assert isinstance(selection, ast.ListComp) and len(selection.generators) == 1
    allowed_nodes = (ast.ListComp, ast.comprehension, ast.Name, ast.Load, ast.Store, ast.Attribute, ast.Call, ast.BoolOp, ast.And, ast.UnaryOp, ast.Not, ast.Compare, ast.NotEq, ast.Constant)
    assert all(isinstance(n, allowed_nodes) for n in ast.walk(selection)), "unexpected executable selection AST"
    assert ast.unparse(selection.elt) == "table"
    generator = selection.generators[0]
    assert ast.unparse(generator.target) == "table" and ast.unparse(generator.iter) == "Base.metadata.sorted_tables" and not generator.is_async
    for n in ast.walk(selection):
        if isinstance(n, ast.Name):
            assert n.id in {"table", "Base", "startup_table_allowed"}
        if isinstance(n, ast.Attribute):
            assert ast.unparse(n) in {"Base.metadata", "Base.metadata.sorted_tables", "table.name", "table.name.startswith"}
        if isinstance(n, ast.Call):
            assert ast.unparse(n.func) in {"startup_table_allowed", "table.name.startswith"}
            assert not n.keywords and len(n.args) == 1
            if isinstance(n.func, ast.Name):
                assert ast.unparse(n.args[0]) == "table"
            else:
                assert isinstance(n.args[0], ast.Constant) and n.args[0].value == "git_coach_"
    captured = []
    metadata = SimpleNamespace(sorted_tables=objects, create_all=lambda **kwargs: captured.append(kwargs))
    engine = object()
    context = {"__builtins__": {}, "Base": SimpleNamespace(metadata=metadata), "engine": engine, "startup_table_allowed": predicate}
    eval(compile(ast.Expression(call), "<audited-create-all-only>", "eval"), context)
    assert len(captured) == 1 and captured[0]["bind"] is engine
    return captured[0]["tables"]


def test_actual_create_all_argument_is_filtered_without_startup_import():
    predicate = feature("app.core.schema_policy").startup_table_allowed
    metadata = MetaData()
    objects = tables() + [Table(name, metadata, Column("id", String(36), primary_key=True), info=info) for name, info in [
        ("teaching_assignments", {}), ("future_assessment", {"explicit_migration_only": True}),
        ("ordinary", {}), ("git_coach_future", {}), ("team_git_project_identities", {})]]
    source = (BACKEND / "app/core/init_db.py").read_text()
    assert [t.name for t in capture_actual_selection(source, objects, predicate)] == ["ordinary"]
    with pytest.raises(AssertionError):
        capture_actual_selection(source + "\nBase.metadata.create_all(bind=engine)\n", objects, predicate)
    with pytest.raises(AssertionError):
        capture_actual_selection("def init_db():\n Base.metadata.create_all(bind=engine, tables=Base.metadata.sorted_tables)\n", objects, predicate)


def test_stable_relationship_keys_and_microsecond_interval_contract():
    models = feature("app.models.teaching")
    all_tables = tables()
    for table in all_tables:
        assert table.info["explicit_migration_only"] is True
        assert table.dialect_options["mysql"]["engine"] == "InnoDB"
        assert table.dialect_options["mysql"]["charset"] == "utf8mb4"
        assert table.dialect_options["mysql"]["collate"] == "utf8mb4_bin"
        for constraint in table.constraints:
            assert constraint.name and len(constraint.name) <= 64
        for index in table.indexes:
            assert index.name and len(index.name) <= 64
        for column in table.columns:
            if column.name.endswith("_at") or column.name in {"effective_from", "effective_until"}:
                assert column.type.dialect_impl(mysql.dialect()).fsp == 6
    for model, subject in [(models.Enrollment, "student_id"), (models.TeachingRole, "subject_id")]:
        uniques = {tuple(c.columns.keys()) for c in model.__table__.constraints if isinstance(c, UniqueConstraint)}
        assert ("offering_id", subject) in uniques
        fks = [c for c in model.__table__.constraints if isinstance(c, ForeignKeyConstraint)]
        assert any(tuple(c.columns.keys()) == ("offering_id", "institution_id") for c in fks)
        checks = [str(c.sqltext) for c in model.__table__.constraints if isinstance(c, CheckConstraint)]
        assert any("effective_until > effective_from" in c for c in checks)
        assert any("revision >= 1" in c for c in checks)
        now = datetime(2026, 10, 3, 1, 2, 3, 456789, tzinfo=timezone.utc)
        with pytest.raises(ValueError):
            models.validate_relationship_interval(now, now)
        with pytest.raises(ValueError):
            models.validate_relationship_interval(now.replace(tzinfo=None), None)
        assert models.validate_relationship_interval(now, now + timedelta(microseconds=1)) is None
    assert not any(fk.target_fullname.startswith("user_accounts.") for t in all_tables for fk in t.foreign_keys)


def test_synthetic_constraints_and_stable_relationship_identity():
    models = feature("app.models.teaching")
    engine = create_engine("sqlite:///:memory:")
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    try:
        for table in tables():
            table.create(engine)
        now = datetime(2026, 10, 3, 1, 2, 3, 456789)
        with Session(engine) as db:
            course = models.Course(id="course", institution_id="i", source_teacher_id="teacher", title="C", code="", description="", timezone="UTC", revision=1, created_at=now, updated_at=now)
            db.add(course); db.flush()
            db.add(models.Offering(id="offering", institution_id="i", course_id="course", title="O", term="T", timezone="UTC", state="draft", revision=1, roster_revision=0, created_at=now, updated_at=now)); db.commit()
            row = models.Enrollment(id="stable", institution_id="i", offering_id="offering", student_id="student", status="active", effective_from=now, revision=1, source_kind="deployment_roster", source_teacher_id="teacher", source_policy_digest="a" * 64, created_at=now, updated_at=now)
            db.add(row); db.commit()
            row.status = "withdrawn"; row.withdrawn_at = now + timedelta(seconds=1); row.revision = 2; db.commit()
            row.status = "active"; row.withdrawn_at = None; row.revision = 3; db.commit()
            assert row.id == "stable" and row.effective_from.microsecond == 456789
            bad = models.Enrollment(id="bad", institution_id="other", offering_id="offering", student_id="other", status="active", effective_from=now, revision=1, source_kind="deployment_roster", source_teacher_id="teacher", source_policy_digest="b" * 64, created_at=now, updated_at=now)
            db.add(bad)
            with pytest.raises(IntegrityError): db.flush()
            db.rollback()
            with pytest.raises(IntegrityError):
                db.execute(models.Enrollment.__table__.update().where(models.Enrollment.id == "stable").values(revision=0))
            db.rollback()
            with pytest.raises(IntegrityError):
                db.execute(models.Enrollment.__table__.update().where(models.Enrollment.id == "stable").values(effective_until=now))
            db.rollback()
    finally:
        engine.dispose()


def test_full_declared_field_contract_and_account_role_binding():
    expected = {
        "teaching_courses": "id institution_id source_teacher_id title code description timezone revision created_at updated_at",
        "teaching_offerings": "id institution_id course_id title term timezone state revision roster_revision created_at updated_at archived_at",
        "teaching_enrollments": "id institution_id offering_id student_id status effective_from effective_until withdrawn_at revision source_kind source_teacher_id source_policy_digest created_at updated_at",
        "teaching_roles": "id institution_id offering_id subject_id granted_account_role label permissions scope status effective_from effective_until revoked_at revision source_policy_digest created_at updated_at",
        "teaching_roster_previews": "id institution_id offering_id actor_id actor_role_id actor_role_revision expected_roster_revision offering_revision mode canonical_command command_hash source_policy_digest target_ids add_ids keep_ids update_ids withdraw_ids validation_issues target_digest withdrawals_digest withdrawals_count can_apply created_at expires_at",
        "teaching_write_receipts": "id institution_id actor_id action scope_type scope_id target_type target_id idempotency_key canonicalization_version request_hash result_type result_id accepted_at http_status original_result",
        "teaching_access_events": "id institution_id receipt_id actor_id actor_role action scope_type scope_id target_type target_id revision_kind before_revision after_revision reason occurred_at effect_metadata",
        "teaching_schema_versions": "component version contract_hash completed_at",
    }
    actual = tables()
    assert {t.name for t in actual} == set(expected)
    for table in actual:
        assert set(table.columns.keys()) == set(expected[table.name].split())
        assert not any(fk.ondelete for fk in table.foreign_key_constraints)
        for column in table.columns:
            if column.name == "id": assert column.type.length == 36 and callable(column.default.arg)
            if column.name == "institution_id": assert column.type.length == 64
            if column.name in {"source_teacher_id", "student_id", "subject_id", "actor_id"}: assert column.type.length == 255
            if column.name.endswith("_hash") or column.name.endswith("_digest"): assert column.type.length == 64
            if column.name.endswith("revision"): assert str(column.type) == "BIGINT"
    role = next(t for t in actual if t.name == "teaching_roles")
    assert role.c.granted_account_role.nullable is False
    assert any("granted_account_role IN ('student', 'teacher')" in str(c.sqltext) for c in role.constraints if isinstance(c, CheckConstraint))
    receipts = next(t for t in actual if t.name == "teaching_write_receipts")
    assert ("actor_id", "action", "scope_type", "scope_id", "idempotency_key") in {tuple(c.columns.keys()) for c in receipts.constraints if isinstance(c, UniqueConstraint)}
    events = next(t for t in actual if t.name == "teaching_access_events")
    assert ("receipt_id",) in {tuple(c.columns.keys()) for c in events.constraints if isinstance(c, UniqueConstraint)}


def test_uuid_width_contract_for_all_server_generated_references():
    ordinary_accounts = {"actor_id", "subject_id", "student_id", "source_teacher_id"}
    for table in tables():
        for column in table.columns:
            if column.name == "id" or (column.name.endswith("_id") and column.name not in ordinary_accounts | {"institution_id", "scope_id"}):
                assert column.type.length == 36, f"{table.name}.{column.name} must be UUID width"


def test_create_all_ast_helper_requires_actual_init_db_direct_call():
    predicate = feature("app.core.schema_policy").startup_table_allowed
    ordinary = Table("ordinary", MetaData(), Column("id", String(36), primary_key=True))
    filtered = "Base.metadata.create_all(bind=engine, tables=[table for table in Base.metadata.sorted_tables if startup_table_allowed(table)])"
    decoys = [
        "def unused():\n " + filtered + "\ndef init_db():\n pass\n",
        "def init_db():\n def unused():\n  " + filtered + "\n",
        "def unused():\n " + filtered + "\ndef init_db():\n Base.metadata.create_all(bind=engine)\n",
    ]
    for source in decoys:
        with pytest.raises(AssertionError): capture_actual_selection(source, [ordinary], predicate)


@pytest.mark.parametrize("table_name", ["teaching_offerings", "teaching_enrollments", "teaching_roles", "teaching_roster_previews"])
def test_composite_fk_has_explicit_full_left_prefix_support(table_name):
    table = next(table for table in tables() if table.name == table_name)
    keys = [tuple(table.primary_key.columns.keys())]
    keys.extend(tuple(c.columns.keys()) for c in table.constraints if isinstance(c, UniqueConstraint))
    keys.extend(tuple(index.columns.keys()) for index in table.indexes)
    for foreign_key in table.foreign_key_constraints:
        columns = tuple(foreign_key.columns.keys())
        assert any(key[:len(columns)] == columns for key in keys), f"{table.name} FK {columns} needs declared full left-prefix support"
