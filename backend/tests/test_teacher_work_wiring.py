"""Finite T3b1 source-only contracts. AST/data reads never import production.

These checks establish wiring/source boundaries, not live authorization,
transaction, schema inspection, HTTP behavior or feature readiness.
"""
from __future__ import annotations

import ast
from hashlib import sha256
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
BOOTSTRAP = "app/services/teacher_work/bootstrap.py"
ENDPOINT = "app/api/endpoints/teacher_work.py"
WRITES = "app/services/teaching/writes.py"
API = "app/api/api.py"
OLD_SERVICE = "app/services/teacher_lesson_prep/service.py"
OLD_ENDPOINT = "app/api/endpoints/teacher_lesson_prep.py"


def _bytes(relative):
    path = BACKEND / relative
    assert path.is_file(), f"T3b1 source feature is missing: {relative}"
    return path.read_bytes()


def _tree(relative):
    return ast.parse(_bytes(relative), filename=relative)


def _function(node, name):
    found = [item for item in node.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name]
    assert len(found) == 1, f"exact source function is missing: {name}"
    return found[0]


def _class(node, name):
    found = [item for item in node.body if isinstance(item, ast.ClassDef) and item.name == name]
    assert len(found) == 1, f"exact request-local source class is missing: {name}"
    return found[0]


def _name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return _name(node.value) + "." + node.attr
    return ""


def _calls(node):
    return {_name(item.func) for item in ast.walk(node) if isinstance(item, ast.Call)}


def _body(node):
    items = node.body
    return items[1:] if items and isinstance(items[0], ast.Expr) and isinstance(items[0].value, ast.Constant) and isinstance(items[0].value.value, str) else items


def _first_guard(node):
    first = _body(node)[0]
    assert isinstance(first, ast.Expr) and isinstance(first.value, ast.Call)
    assert _name(first.value.func) == "_require_live_admission"


def test_t3_bootstrap_is_lazy_request_scoped_and_closed():
    tree = _tree(BOOTSTRAP)  # Missing feature assertion precedes any AST inspection.
    forbidden = ("sqlalchemy", "fastapi", "app.core", "app.models", "app.services.current_identity",
                 "app.services.teaching", "app.repositories.teacher_work_sql", "app.repositories.json_store")
    for item in tree.body:
        if isinstance(item, ast.ImportFrom):
            assert not (item.module or "").startswith(forbidden)
        if isinstance(item, ast.Import):
            assert not any(alias.name.startswith(forbidden) for alias in item.names)
        if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom)):
            assert not _calls(item), "bootstrap cannot construct production state at import time"
    guard = _function(tree, "_require_live_admission")
    body = _body(guard)
    assert len(body) == 1 and isinstance(body[0], ast.Raise)
    assert _name(body[0].exc.func) == "WorkAuthorizationError"
    assert [value.value for value in body[0].exc.args] == ["TEACHER_WORK_LIVE_GATES_UNVERIFIED", 503]
    for name in ("open_teacher_work_request", "build_request_dependencies"):
        _first_guard(_function(tree, name))
    imports = {item.module for item in ast.walk(tree) if isinstance(item, ast.ImportFrom)}
    assert {"app.core.database", "app.core.security", "app.services.current_identity", "app.models.teacher_work",
            "app.models.domain_record", "app.repositories.json_store", "app.repositories.teacher_work_sql",
            "app.services.teaching.sessions", "app.services.teaching.writes", "app.services.teaching.access",
            "app.services.teaching.policy", "app.services.teaching.types", "sqlalchemy.orm", "sqlalchemy.engine"} <= imports
    bindings = _class(tree, "_WorkRequestBindings")
    constructor = _function(bindings, "__init__")
    assert {"_SessionWorkTransport", "decode_access_token", "resolve_current_account", "require_current_teacher_facts",
            "JsonStore", "SqlWorkModels", "build_sql_repository", "WorkDependencies"} <= _calls(constructor)
    assert "commit_policy='caller_owned'" in ast.unparse(constructor)
    authorizer = _function(bindings, "authorize_locked")
    assert {"load_current_account", "lock_offering_read_context", "require_current_teacher_facts",
            "prepare_namespace_receipt", "bind_work_actor", "AuthorizedWorkScope"} <= _calls(authorizer)
    assert {"populate_existing", "with_for_update"} <= {name.rsplit(".", 1)[-1] for name in _calls(_function(bindings, "_namespace_observation"))}
    assert "OwnerRunLease.owner == self.subject" in ast.unparse(_function(bindings, "_namespace_observation"))
    assert "WorkTask.owner_subject == self.subject" in ast.unparse(_function(bindings, "_task_namespace_ids"))
    assert not {name.rsplit(".", 1)[-1] for name in _calls(tree)} & {"add", "delete", "upsert", "atomic_store", "create_all", "inspect"}
    finish = _function(bindings, "_finish")
    assert {"TeacherWorkRequestOwner", "owner.finish_write", "owner.finish_read"} <= _calls(finish)
    assert "lock_offering_read_context" not in _calls(finish), "finalization must reuse the retained footprint"
    evaluator = _function(bindings, "_evaluate_held")
    assert {"authorize_locked_action", "require_current_teacher_facts", "HeldAdmissionReceipt"} <= _calls(evaluator)
    assert "TeachingAction.READ_OFFERING" in ast.unparse(evaluator)
    commit = _function(_class(tree, "_SessionWorkTransport"), "commit")
    statements = _body(commit)
    assert any(isinstance(item, ast.Expr) and isinstance(item.value, ast.Call) and _name(item.value.func) == "self.session.commit" for item in statements[:-1])
    assert isinstance(statements[-1], ast.Return) and _name(statements[-1].value.func) == "CommitReceipt"
    assert [(item.arg, item.value.value) for item in statements[-1].value.keywords] == [("confirmed", True)]


def test_t3_read_footprint_export_is_read_only():
    raw, tree = _bytes(WRITES), _tree(WRITES)
    function = _function(tree, "lock_offering_read_context")
    assert [item.arg for item in function.args.args] == ["session", "subject", "scope"]
    assert not function.args.kwonlyargs and function.args.vararg is None and function.args.kwarg is None
    body = _body(function)
    assert len(body) == 1 and isinstance(body[0], ast.Return) and isinstance(body[0].value, ast.Call)
    call = body[0].value
    assert _name(call.func) == "_lock_context"
    assert [_name(item) for item in call.args] == ["session", "subject", "TeachingAction.READ_OFFERING", "scope"]
    assert [(item.arg, item.value.value) for item in call.keywords] == [("write", False)]
    assert raw[:56173] and sha256(raw[:56173]).hexdigest() == "929897d25d36205198ef604aa169a9d0d14747a9d1d55a7eef04b85a7d4a9d7f"
    assert tree.body[-1] is function, "only append the narrow public read-footprint export"
    assert len(tree.body) == len(ast.parse(raw[:56173]).body) + 1


def test_t3_legacy_service_and_endpoint_remain_unwired():
    assert sha256(_bytes(OLD_SERVICE)).hexdigest() == "b3e99cac3229f055127541c4bf9a4e7ce6a1b280931cc4919c36624f1df5f01d"
    assert sha256(_bytes(OLD_ENDPOINT)).hexdigest() == "6136059d9ca042fb01cb7108594a7fdb7127613b803d1f3f6c614c7d19810416"
    assert "prepare_legacy_save" not in _calls(_tree(OLD_SERVICE))
    assert "open_teacher_work_request" not in _calls(_tree(OLD_ENDPOINT))


def test_t3_router_registration_has_no_startup_or_student_mutation():
    tree = _tree(ENDPOINT)
    factory = _function(tree, "build_teacher_work_router")
    assert not factory.args.args and [item.arg for item in factory.args.kwonlyargs] == ["request_owner_factory", "dependencies_factory"]
    assert {"APIRouter", "request_owner_factory", "dependencies_factory"} <= _calls(factory)
    assert [keyword.value.value for item in ast.walk(factory) if isinstance(item, ast.Call) and _name(item.func) == "APIRouter" for keyword in item.keywords if keyword.arg == "prefix"] == ["/teacher/work"]
    route_calls = [item for item in ast.walk(factory) if isinstance(item, ast.Call) and _name(item.func).startswith("router.")]
    assert len(route_calls) == 1 and _name(route_calls[0].func) == "router.get"
    assert route_calls[0].args[0].value == "/capabilities", "unsupplied task/list/read routes must remain absent"
    assert "TEACHER_WORK_UNAVAILABLE" in ast.unparse(factory) and "503" in ast.unparse(factory)
    assert "Cache-Control" in ast.unparse(tree) and "no-store" in ast.unparse(tree)
    assignments = [item for item in tree.body if isinstance(item, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "router" for target in item.targets)]
    assert len(assignments) == 1 and _name(assignments[0].value.func) == "build_teacher_work_router"
    assert {_name(item.value) for item in assignments[0].value.keywords} == {"open_teacher_work_request", "build_request_dependencies"}
    for item in tree.body:
        if isinstance(item, ast.ImportFrom):
            assert not (item.module or "").startswith(("app.core", "app.models", "app.services.current_identity", "app.services.teaching", "sqlalchemy"))
    assert not {name.rsplit(".", 1)[-1] for name in _calls(tree)} & {"create_all", "connect", "begin", "submit", "publish", "execute_write", "create_task", "get_task", "patch_working", "from_legacy"}
    raw, api = _bytes(API), _tree(API)
    assert sha256(raw[:2607]).hexdigest() == "16b532420e27e110136e6c9b96825248ac38bd760484bc085b410046f409c7a0"
    assert len(api.body) == len(ast.parse(raw[:2607]).body) + 2
    imports = [item for item in api.body if isinstance(item, ast.ImportFrom) and item.module == "app.api.endpoints" and any(alias.name == "teacher_work" for alias in item.names)]
    assert len(imports) == 1
    includes = [item for item in ast.walk(api) if isinstance(item, ast.Call) and _name(item.func) == "api_router.include_router" and item.args and _name(item.args[0]) == "teacher_work.router"]
    assert len(includes) == 1
