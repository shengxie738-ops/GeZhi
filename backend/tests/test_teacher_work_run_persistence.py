"""Task4b1 seven pure and three AST cases, UNEXECUTED.

Only an independently reviewed finite profile may execute these cases. The pure
contracts use supplied synthetic values; model/bootstrap/startup reads are AST
or source-text only. No ORM, SQLAlchemy, rows, transactions, identity, settings,
provider, actual clock, dispatch, physical inspection or migration execution.
"""
from __future__ import annotations

import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import importlib
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.schemas.teacher_work import RunDTO, WorkMessageDTO
from app.services.teacher_work.types import canonical_digest


BACKEND = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 5, tzinfo=timezone.utc)
TASK = UUID("60000000-0000-0000-0000-000000000001")
OTHER = UUID("60000000-0000-0000-0000-000000000002")
RUN = UUID("70000000-0000-0000-0000-000000000001")
RUN2 = UUID("70000000-0000-0000-0000-000000000002")
PROCESS = UUID("80000000-0000-0000-0000-000000000001")
PROCESS2 = UUID("80000000-0000-0000-0000-000000000002")
MESSAGE = UUID("90000000-0000-0000-0000-000000000001")
V1_BYTES_HASH = "3a6e98397e2ba9d7c8879437d3698ded8c455d45f155a6edc8871cf7df2351cd"


def _module(name="app.services.teacher_work.run_persistence", relative="app/services/teacher_work/run_persistence.py"):
    assert (BACKEND / relative).is_file(), f"Task4b1 pure contract is missing: {relative}"
    return importlib.import_module(name)


def run(**changes):
    values = dict(run_id=RUN, owner="A", task_id=TASK, kind="chat", skill_ref=None, input_revision=1,
        idempotency_key="实际键 ", request_digest="a" * 64, stage="CHAT_RUNNING", attempt=2,
        provider_call_count=2, deadline=NOW + timedelta(seconds=270))
    values.update(changes)
    return RunDTO(**values)


def message(**changes):
    values = dict(message_id=MESSAGE, owner="A", task_id=TASK, role="assistant", plain_text="实际候选\n原文",
                  client_message_key=None, run_id=RUN, result_refs=(OTHER,), created_at=NOW)
    values.update(changes)
    return WorkMessageDTO(**values)


def token(module, **changes):
    values = dict(run_id=RUN, attempt=2, call_no=2, lease_revision=4, process_instance=PROCESS)
    values.update(changes)
    return module.ProviderCallToken(**values)


def _observation(schema):
    return {"dialect": "mysql", "tables": deepcopy(schema.TEACHER_WORK_SCHEMA_CONTRACT["tables"]),
            "version": schema.TEACHER_WORK_SCHEMA_VERSION, "contract_hash": schema.TEACHER_WORK_CONTRACT_HASH}


def _tree(relative):
    path = BACKEND / relative
    assert path.is_file(), f"Task4b1 source contract is missing: {relative}"
    return ast.parse(path.read_text(encoding="utf-8"))


def _class(tree, name):
    return next(item for item in tree.body if isinstance(item, ast.ClassDef) and item.name == name)


def _columns(cls):
    return {target.id: item.value for item in cls.body if isinstance(item, ast.Assign)
            for target in item.targets if isinstance(target, ast.Name) and isinstance(item.value, ast.Call)
            and isinstance(item.value.func, ast.Name) and item.value.func.id == "Column"}


def _keyword(call, name):
    return next(item.value for item in call.keywords if item.arg == name)


def _constraints(cls):
    declaration = next(item.value for item in cls.body if isinstance(item, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == "__table_args__" for target in item.targets))
    return {ast.literal_eval(_keyword(item, "name")): item for item in declaration.elts
            if isinstance(item, ast.Call) and any(keyword.arg == "name" for keyword in item.keywords)}


def test_work_key_exact_utf8_roundtrip():
    module = _module()
    keys = (" ", "中文 ", " Key", "Key", "key", "é", "e\u0301", "𠀀" * 128)
    encoded = tuple(module.encode_work_key(key) for key in keys)
    assert len(set(encoded)) == len(keys) and len(encoded[-1]) == 512
    assert tuple(module.decode_work_key(raw) for raw in encoded) == keys
    for key in ("", "a\nb", "a\x00b", "a\x7fb", "a\x80b", "a\x9fb", "a" * 129, "\ud800", None, True, b"key"):
        with pytest.raises(module.WorkRunError) as caught:
            module.encode_work_key(key)
        assert caught.value.status_code == 422
        if type(key) is str and key:
            assert key not in str(caught.value)
    for raw in (b"", b"\xff", b"\xc0\xaf", b"a\x00b", b"a" * 129, b"a" * 513, bytearray(b"a"), None):
        with pytest.raises(module.WorkRunError) as caught:
            module.decode_work_key(raw)
        assert caught.value.status_code == 503


def test_stored_run_repair_and_active_call_bounds():
    module = _module()
    original = run(stage="CANCELLED", cancelled_at=NOW)
    active = token(module)
    state = module.StoredRunState(run=original, repair_count=1, active_call=active)
    assert state.run is original and state.active_call is active and state.repair_count == 1
    for value, field, replacement in ((state, "repair_count", 0), (active, "call_no", 3)):
        with pytest.raises(FrozenInstanceError):
            setattr(value, field, replacement)
    assert module.StoredRunState(run=run(), repair_count=0, active_call=None).active_call is None
    with pytest.raises(TypeError):
        module.StoredRunState(run=original, active_call=active)
    for repair in (True, -1, 2):
        with pytest.raises(module.WorkRunError):
            module.StoredRunState(run=original, repair_count=repair, active_call=active)
    with pytest.raises(module.WorkRunError):
        module.StoredRunState(run=run(provider_call_count=0), repair_count=1, active_call=None)
    for invalid in (dict(attempt=True), dict(attempt=3), dict(call_no=0), dict(call_no=4), dict(lease_revision=True),
                    dict(lease_revision=0), dict(process_instance=None), dict(process_instance=str(PROCESS)),
                    dict(call_no=None), dict(run_id="not-uuid"), dict(run_id=str(RUN))):
        with pytest.raises(module.WorkRunError) as caught:
            token(module, **invalid)
        assert caught.value.status_code == 503
    for changed in (dict(run_id=RUN2), dict(attempt=1), dict(call_no=1)):
        with pytest.raises(module.WorkRunError):
            module.StoredRunState(run=original, repair_count=1, active_call=token(module, **changed))


def test_call_token_cannot_settle_newer_call():
    module = _module()
    active = token(module)
    state = module.StoredRunState(run=run(), repair_count=1, active_call=active)
    assert module.matches_active_call(state, active) is True
    for changed in (dict(run_id=RUN2), dict(attempt=1), dict(call_no=1), dict(lease_revision=5), dict(process_instance=PROCESS2)):
        assert module.matches_active_call(state, replace(active, **changed)) is False
    absent = module.StoredRunState(run=run(), repair_count=1, active_call=None)
    assert module.matches_active_call(absent, active) is False
    assert state.active_call is active and state.repair_count == 1 and state.run.provider_call_count == 2


def test_message_result_metadata_backward_compatible():
    module = _module()
    for role in ("user", "tool", "assistant"):
        old = message(role=role, run_id=None)
        assert old.result_type is None and old.omitted_context is None
        assert module.chat_result_from_message(old) is None and old.plain_text == "实际候选\n原文" and old.result_refs == (OTHER,)
    for index, kind in enumerate(("answer", "outline_proposal", "revision_proposal", "skill_suggestion")):
        omitted = index % 2 == 0
        classified = message(result_type=kind, omitted_context=omitted)
        result = module.chat_result_from_message(classified)
        assert result.type == kind and result.plain_text == classified.plain_text and result.omitted_context is omitted
    for changes in (dict(result_type="answer"), dict(omitted_context=False),
                    dict(result_type="answer", omitted_context=False, role="user"),
                    dict(result_type="answer", omitted_context=False, run_id=None),
                    dict(result_type="answer", omitted_context=False, plain_text=" \n "),
                    dict(result_type="answer", omitted_context=0)):
        with pytest.raises(ValidationError):
            message(**changes)


def test_chat_completion_receipt_preserves_actual_result():
    module = _module()
    candidate = message(result_type="revision_proposal", omitted_context=True)
    original = run()
    receipt = module.validate_chat_completion(original, candidate, RUN)
    assert receipt.run_id == RUN and receipt.message_id == MESSAGE
    with pytest.raises(FrozenInstanceError):
        receipt.message_id = OTHER
    result = module.chat_result_from_message(candidate)
    assert (result.type, result.plain_text, result.result_refs, result.omitted_context) == ("revision_proposal", "实际候选\n原文", (OTHER,), True)
    for observed_run, observed_message, completion in (
        (run(owner="B"), candidate, RUN), (run(task_id=OTHER), candidate, RUN), (original, candidate, RUN2),
        (original, message(run_id=RUN2, result_type="answer", omitted_context=False), RUN),
        (run(kind="outline", skill_ref="lesson_outline@1"), candidate, RUN), (original, message(), RUN)):
        with pytest.raises(module.WorkRunError):
            module.validate_chat_completion(observed_run, observed_message, completion)


def test_chat_absolute_deadline_three_calls_never_renews():
    module = _module()
    runs = _module("app.services.teacher_work.runs", "app/services/teacher_work/runs.py")
    assert hasattr(runs, "chat_absolute_deadline"), "Task4b1 absolute deadline policy is missing"
    short = runs.chat_absolute_deadline(NOW, 30)
    maximum = runs.chat_absolute_deadline(NOW, 200)
    assert short == NOW + timedelta(seconds=90) and maximum == NOW + timedelta(seconds=270)
    assert runs.chat_absolute_deadline(NOW, 90) == maximum
    for invalid in (0, -1, True, "30", 30.0):
        with pytest.raises(runs.WorkRunError):
            runs.chat_absolute_deadline(NOW, invalid)
    with pytest.raises(runs.WorkRunError):
        runs.chat_absolute_deadline(NOW.replace(tzinfo=None), 30)
    budget = runs.WorkBudget(provider_call_count=1)
    budget.advance_attempt()
    budget.consume_ai_call(repair=True)
    assert (budget.attempt, budget.provider_call_count, budget.repair_count) == (2, 2, 1)
    original = run(deadline=maximum)
    cancelled = runs.cancel_chat_run(original, now=NOW + timedelta(seconds=100))
    assert original.deadline == cancelled.deadline == maximum
    assert runs.chat_call_limits(8192, 90, deadline=maximum, now=NOW + timedelta(seconds=268, microseconds=100000)).timeout_seconds == 1
    with pytest.raises(runs.WorkRunError):
        runs.chat_call_limits(8192, 90, deadline=maximum, now=NOW + timedelta(seconds=269, microseconds=100000))


def test_v2_preparation_one_way_closed_compatibility():
    _module()
    v1 = _module("app.services.teacher_work.schema_v1", "app/services/teacher_work/schema_v1.py")
    v2 = _module("app.services.teacher_work.schema", "app/services/teacher_work/schema.py")
    migration = _module("migrations.v20261005_teacher_work_v2", "migrations/v20261005_teacher_work_v2.py")
    prepare = migration.prepare_teacher_work_v2_schema
    empty = {"dialect": "mysql", "tables": {}}
    fresh = prepare(empty, target_contract_hash=v2.TEACHER_WORK_CONTRACT_HASH)
    assert fresh.mode == "fresh_v2" and fresh.additive_only and not fresh.executable and fresh.completion_ledger_required
    assert fresh.missing_tables == tuple(v2.TEACHER_WORK_SCHEMA_CONTRACT["tables"]) and fresh.upgrade_tables == ()
    assert fresh.component == "teacher_work" and fresh.from_version is None and fresh.from_hash is None
    assert fresh.to_version == 2 and fresh.to_hash == v2.TEACHER_WORK_CONTRACT_HASH
    assert type(fresh.required_changes) is tuple and fresh.required_changes and all(type(change) is str and change for change in fresh.required_changes)
    current = _observation(v2)
    exact = prepare(current, target_contract_hash=v2.TEACHER_WORK_CONTRACT_HASH)
    assert exact.mode == "exact_v2" and not exact.executable and not exact.completion_ledger_required
    assert exact.from_version == exact.to_version == 2 and exact.from_hash == exact.to_hash == v2.TEACHER_WORK_CONTRACT_HASH
    assert exact.missing_tables == exact.upgrade_tables == exact.required_changes == () and exact.additive_only
    assert migration.check_teacher_work_v2_schema(current).ready is True
    old = _observation(v1)
    zero = migration.WorkUpgradeDataFacts(run_rows=0, message_rows=0, active_leases=0)
    upgrade = prepare(old, target_contract_hash=v2.TEACHER_WORK_CONTRACT_HASH, upgrade_data_facts=zero)
    assert upgrade.mode == "empty_v1_upgrade" and not upgrade.additive_only and not upgrade.executable
    assert upgrade.upgrade_tables == ("teacher_work_runs", "teacher_work_messages") and upgrade.completion_ledger_required
    assert upgrade.from_version == 1 and upgrade.from_hash == v1.TEACHER_WORK_CONTRACT_HASH
    assert upgrade.to_version == 2 and upgrade.to_hash == v2.TEACHER_WORK_CONTRACT_HASH and upgrade.missing_tables == ()
    assert type(upgrade.required_changes) is tuple and upgrade.required_changes and all(type(change) is str and change for change in upgrade.required_changes)
    for frozen in (fresh, exact, upgrade, zero):
        field = "mode" if frozen is not zero else "run_rows"
        with pytest.raises(FrozenInstanceError):
            setattr(frozen, field, None)
    assert migration.check_teacher_work_v2_schema(old).ready is False
    for facts in (None, {"run_rows": 0, "message_rows": 0, "active_leases": 0},
                  migration.WorkUpgradeDataFacts(1, 0, 0), migration.WorkUpgradeDataFacts(0, 1, 0), migration.WorkUpgradeDataFacts(0, 0, 1)):
        with pytest.raises(ValueError):
            prepare(old, target_contract_hash=v2.TEACHER_WORK_CONTRACT_HASH, upgrade_data_facts=facts)
    for invalid in (dict(run_rows=True, message_rows=0, active_leases=0), dict(run_rows=0, message_rows=-1, active_leases=0),
                    dict(run_rows=0, message_rows=0, active_leases="0"), dict(run_rows=0, message_rows=0, active_leases=False)):
        with pytest.raises(ValueError):
            migration.WorkUpgradeDataFacts(**invalid)
    partial = deepcopy(current)
    del partial["tables"]["teacher_work_messages"]
    mixed = deepcopy(old)
    mixed["tables"]["teacher_work_runs"] = deepcopy(current["tables"]["teacher_work_runs"])
    no_ledger = {"dialect": "mysql", "tables": deepcopy(current["tables"])}
    for observation in (partial, mixed, no_ledger, {**old, "version": True}, {**old, "contract_hash": "0" * 64},
                        {**current, "dialect": "sqlite"}, {**empty, "version": 1}, {"dialect": "mysql", "tables": []}):
        with pytest.raises(ValueError):
            prepare(observation, target_contract_hash=v2.TEACHER_WORK_CONTRACT_HASH, upgrade_data_facts=zero)
    with pytest.raises(ValueError):
        prepare(current, target_contract_hash=v1.TEACHER_WORK_CONTRACT_HASH)
    assert old == _observation(v1) and current == _observation(v2) and empty == {"dialect": "mysql", "tables": {}}


def test_model_run_message_binary_and_internal_constraints():
    tree = _tree("app/models/teacher_work.py")
    run_class, msg_class = _class(tree, "WorkRun"), _class(tree, "WorkMessage")
    rc, mc = _columns(run_class), _columns(msg_class)
    assert {"repair_count", "active_call_no", "active_call_attempt", "active_call_lease_revision", "active_call_process_instance"} <= set(rc)
    assert {"completion_run_id", "result_type", "omitted_context"} <= set(mc)
    for call, nullable in ((rc["idempotency_key"], False), (mc["client_message_key"], True)):
        assert isinstance(call.args[0], ast.Call) and isinstance(call.args[0].func, ast.Name) and call.args[0].func.id == "VARBINARY"
        assert ast.literal_eval(call.args[0].args[0]) == 512 and ast.literal_eval(_keyword(call, "nullable")) is nullable
    assert ast.literal_eval(_keyword(rc["repair_count"], "nullable")) is False
    assert ast.literal_eval(_keyword(rc["repair_count"], "server_default")) == "0"
    active_names = {"active_call_no", "active_call_attempt", "active_call_lease_revision", "active_call_process_instance"}
    assert all(ast.literal_eval(_keyword(rc[name], "nullable")) is True for name in active_names)
    for name in ("repair_count", "active_call_no", "active_call_attempt", "active_call_lease_revision"):
        assert isinstance(rc[name].args[0], ast.Name) and rc[name].args[0].id == "Integer"
    assert isinstance(rc["active_call_process_instance"].args[0], ast.Call)
    assert rc["active_call_process_instance"].args[0].func.id == "String" and ast.literal_eval(rc["active_call_process_instance"].args[0].args[0]) == 36
    constraints = _constraints(run_class)
    assert [ast.literal_eval(value) for value in constraints["uq_tw_run_owner_task_kind_key"].args] == ["owner", "task_id", "kind", "idempotency_key"]
    budget = ast.literal_eval(constraints["ck_tw_run_budget"].args[0])
    assert "repair_count >= 0" in budget and "repair_count <= 1" in budget and "repair_count <= provider_call_count" in budget
    active = ast.literal_eval(constraints["ck_tw_run_active_call"].args[0])
    for name in active_names:
        assert name + " IS NULL" in active and name + " IS NOT NULL" in active
    assert "active_call_no = provider_call_count" in active and "active_call_attempt = attempt" in active
    assert "active_call_no >= 1" in active or "active_call_no BETWEEN 1 AND 3" in active
    assert "active_call_no <= 3" in active or "active_call_no BETWEEN 1 AND 3" in active
    assert "active_call_attempt >= 1" in active or "active_call_attempt BETWEEN 1 AND 2" in active
    assert "active_call_attempt <= 2" in active or "active_call_attempt BETWEEN 1 AND 2" in active
    assert "active_call_lease_revision >= 1" in active
    assert "stage" not in active
    for name in ("completion_run_id", "result_type", "omitted_context"):
        assert ast.literal_eval(_keyword(mc[name], "nullable")) is True
        assert not any(keyword.arg in {"default", "server_default"} for keyword in mc[name].keywords)
    assert mc["completion_run_id"].args[0].func.id == "String" and ast.literal_eval(mc["completion_run_id"].args[0].args[0]) == 36
    assert mc["result_type"].args[0].func.id == "String" and ast.literal_eval(mc["result_type"].args[0].args[0]) == 32
    assert isinstance(mc["omitted_context"].args[0], ast.Name) and mc["omitted_context"].args[0].id == "Boolean"
    constraints = _constraints(msg_class)
    unique = constraints["uq_tw_message_completion_run"]
    assert [ast.literal_eval(value) for value in unique.args] == ["completion_run_id"]
    assert any(isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name) and arg.func.id == "ForeignKey" and ast.literal_eval(arg.args[0]) == "teacher_work_runs.run_id" for arg in mc["completion_run_id"].args)
    check = ast.literal_eval(constraints["ck_tw_message_completion_metadata"].args[0])
    for name in ("completion_run_id", "result_type", "omitted_context"):
        assert name + " IS NULL" in check and name + " IS NOT NULL" in check
    assert "run_id IS NOT NULL" in check and "run_id = completion_run_id" in check and "role = 'assistant'" in check
    assert "omitted_context IN (0,1)" in check or "omitted_context IN (0, 1)" in check
    assert all("'" + kind + "'" in check for kind in ("answer", "outline_proposal", "revision_proposal", "skill_suggestion"))
    assert [ast.literal_eval(value) for value in constraints["uq_tw_message_task_client_key"].args] == ["task_id", "client_message_key"]


def test_v1_contract_frozen_v2_hash_changes_once():
    path = BACKEND / "app/services/teacher_work/schema_v1.py"
    assert path.is_file(), "Task4b1 frozen v1 schema is missing"
    assert sha256(path.read_bytes()).hexdigest() == V1_BYTES_HASH
    v1 = _module("app.services.teacher_work.schema_v1", "app/services/teacher_work/schema_v1.py")
    v2 = _module("app.services.teacher_work.schema", "app/services/teacher_work/schema.py")
    assert v1.TEACHER_WORK_SCHEMA_VERSION == 1 and v2.TEACHER_WORK_SCHEMA_VERSION == 2
    assert canonical_digest(v1.TEACHER_WORK_SCHEMA_CONTRACT) == v1.TEACHER_WORK_CONTRACT_HASH
    assert canonical_digest(v2.TEACHER_WORK_SCHEMA_CONTRACT) == v2.TEACHER_WORK_CONTRACT_HASH != v1.TEACHER_WORK_CONTRACT_HASH
    assert v1.TEACHER_WORK_SCHEMA_CONTRACT["tables"]["teacher_work_runs"]["columns"]["idempotency_key"]["type"] == "varchar(128)"
    assert v2.TEACHER_WORK_SCHEMA_CONTRACT["tables"]["teacher_work_runs"]["columns"]["idempotency_key"]["type"] == "varbinary(512)"
    old_tables, new_tables = v1.TEACHER_WORK_SCHEMA_CONTRACT["tables"], v2.TEACHER_WORK_SCHEMA_CONTRACT["tables"]
    assert set(new_tables) == set(old_tables)
    assert all(new_tables[name] == shape for name, shape in old_tables.items() if name not in {"teacher_work_runs", "teacher_work_messages"})
    old_run, new_run = old_tables["teacher_work_runs"], new_tables["teacher_work_runs"]
    added_run = {"repair_count": ("integer", False), "active_call_no": ("integer", True), "active_call_attempt": ("integer", True),
                 "active_call_lease_revision": ("integer", True), "active_call_process_instance": ("varchar(36)", True)}
    assert set(new_run["columns"]) == set(old_run["columns"]) | set(added_run)
    for name, (kind, nullable) in added_run.items():
        assert new_run["columns"][name] == {"type": kind, "nullable": nullable}
    assert all(new_run["columns"][name] == shape for name, shape in old_run["columns"].items() if name != "idempotency_key")
    assert all(new_run[name] == old_run[name] for name in ("primary_key", "unique", "foreign_keys", "options"))
    assert set(new_run["checks"]) == set(old_run["checks"]) | {"ck_tw_run_active_call"}
    assert all(new_run["checks"][name] == check for name, check in old_run["checks"].items() if name != "ck_tw_run_budget")
    assert all(term in new_run["checks"]["ck_tw_run_budget"] for term in ("repair_count >= 0", "repair_count <= 1", "repair_count <= provider_call_count"))
    old_message, new_message = old_tables["teacher_work_messages"], new_tables["teacher_work_messages"]
    added_message = {"completion_run_id": "varchar(36)", "result_type": "varchar(32)", "omitted_context": "tinyint(1)"}
    assert set(new_message["columns"]) == set(old_message["columns"]) | set(added_message)
    assert new_message["columns"]["client_message_key"] == {"type": "varbinary(512)", "nullable": True}
    for name, kind in added_message.items():
        assert new_message["columns"][name] == {"type": kind, "nullable": True}
    assert all(new_message["columns"][name] == shape for name, shape in old_message["columns"].items() if name != "client_message_key")
    assert new_message["unique"] == (*old_message["unique"], ("completion_run_id",))
    assert new_message["foreign_keys"] == {**old_message["foreign_keys"], "completion_run_id": "teacher_work_runs.run_id"}
    assert all(new_message[name] == old_message[name] for name in ("primary_key", "options"))
    assert set(new_message["checks"]) == set(old_message["checks"]) | {"ck_tw_message_completion_metadata"}
    assert all(new_message["checks"][name] == check for name, check in old_message["checks"].items())
    run_constraints = _constraints(_class(_tree("app/models/teacher_work.py"), "WorkRun"))
    message_constraints = _constraints(_class(_tree("app/models/teacher_work.py"), "WorkMessage"))
    for name in ("ck_tw_run_budget", "ck_tw_run_active_call"):
        assert new_run["checks"][name] == ast.literal_eval(run_constraints[name].args[0])
    assert new_message["checks"]["ck_tw_message_completion_metadata"] == ast.literal_eval(message_constraints["ck_tw_message_completion_metadata"].args[0])
    old_migration = _tree("migrations/v20261005_teacher_work.py")
    imports = {item.module for item in ast.walk(old_migration) if isinstance(item, ast.ImportFrom)}
    assert "app.services.teacher_work.schema_v1" in imports and "app.services.teacher_work.schema" not in imports
    pinned = _module("migrations.v20261005_teacher_work", "migrations/v20261005_teacher_work.py")
    with pytest.raises(ValueError):
        pinned.prepare_teacher_work_schema(_observation(v2), contract_hash=v2.TEACHER_WORK_CONTRACT_HASH)


def test_contract_slice_keeps_runtime_gates_closed():
    bootstrap = _tree("app/services/teacher_work/bootstrap.py")
    guard = next(item for item in bootstrap.body if isinstance(item, ast.FunctionDef) and item.name == "_require_live_admission")
    body = guard.body[1:] if isinstance(guard.body[0], ast.Expr) and isinstance(guard.body[0].value, ast.Constant) else guard.body
    assert ast.literal_eval(body[0].value) == {"private_create": "write", "private_read": "read", "private_update": "write",
        "private_chat_read": "read", "private_chat_write": "write",
        "private_material_read": "read", "private_material_save": "write", "private_material_approve": "write",
        "private_package_read":"read","private_package_create":"write","private_package_retry":"write","private_package_file":"write"}
    assert ast.unparse(body[1].test) == "operation not in expected or mode != expected[operation]"
    assert isinstance(body[1].body[0], ast.Raise)
    assert body[1].body[0].exc.args[0].value == "TEACHER_WORK_LIVE_GATES_UNVERIFIED" and body[1].body[0].exc.args[1].value == 503
    assert guard.args.defaults[0].value is None
    assert "settings.TEACHER_WORK_PRIVATE_TASKS_ENABLED is not True" in ast.unparse(guard)
    config = _class(_tree("app/core/config.py"), "Settings")
    switch = next(n for n in config.body if isinstance(n, ast.AnnAssign) and n.target.id == "TEACHER_WORK_PRIVATE_TASKS_ENABLED")
    assert switch.value.value is False
    bindings = _class(bootstrap, "_WorkRequestBindings")
    finish_chat = next(n for n in bindings.body if isinstance(n, ast.FunctionDef) and n.name == "finish_chat_outcome")
    assert "self.operation not in (None, 'private_chat_read', 'private_chat_write')" in ast.unparse(finish_chat) and "TEACHER_WORK_LIVE_GATES_UNVERIFIED" in ast.unparse(finish_chat)
    closed = _class(bootstrap, "_ClosedLaterOperations")
    expected_errors = {"complete": "WORK_AI_UNAVAILABLE", "collect": "WORK_EVIDENCE_UNAVAILABLE",
                       "read_verified": "WORK_ARTIFACT_UNAVAILABLE", "submit": "WORK_EXECUTION_UNAVAILABLE"}
    for method in closed.body:
        if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert method.name in expected_errors and len(method.body) == 1 and isinstance(method.body[0], ast.Raise)
            assert method.body[0].exc.args[0].value == expected_errors[method.name] and method.body[0].exc.args[1].value == 503
    schema = _tree("app/schemas/teacher_work.py")
    fields = {item.target.id for item in _class(schema, "RunDTO").body if isinstance(item, ast.AnnAssign)}
    assert fields == {"run_id", "owner", "task_id", "kind", "skill_ref", "input_revision", "outline_revision", "idempotency_key", "request_digest", "stage", "attempt", "provider_call_count", "deadline", "cancelled_at", "error_code", "result_version_id"}
    expected = {"kind", "input_revision", "skill_ref", "payload"}
    for name in ("ChatCommand", "OutlineCommand", "PackageCommand", "ReviseCommand", "ReferenceSearchCommand"):
        assert {item.target.id for item in _class(schema, name).body if isinstance(item, ast.AnnAssign)} == expected
    message_fields = {item.target.id for item in _class(schema, "WorkMessageDTO").body if isinstance(item, ast.AnnAssign)}
    assert not {"completion_run_id", "repair_count", "active_call", "process_instance", "lease_revision"} & message_fields
    pure_sources = ("app/services/teacher_work/run_persistence.py", "app/services/teacher_work/runs.py",
                    "app/services/teacher_work/schema.py", "app/services/teacher_work/schema_v1.py",
                    "migrations/v20261005_teacher_work.py", "migrations/v20261005_teacher_work_v2.py")
    app_imports = {"app.schemas.teacher_work", "app.services.teacher_work.types", "app.services.teacher_work.runs",
                   "app.services.teacher_work.schema", "app.services.teacher_work.schema_v1"}
    pure_roots = {"__future__", "collections", "dataclasses", "datetime", "enum", "hashlib", "json", "math", "re", "typing", "types", "uuid", "pydantic"}
    forbidden_calls = {"create_engine", "Session", "sessionmaker", "connect", "execute", "executemany", "create_all",
                       "drop_all", "dispatch", "submit", "complete", "answer_chat", "now", "utcnow", "sleep"}
    for relative in pure_sources:
        for node in ast.walk(_tree(relative)):
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                assert node.level == 0, "Task4b1 pure dependency closure must be explicit"
                imports = [node.module]
            else:
                imports = []
            assert all(name in app_imports or name.split(".", 1)[0] in pure_roots for name in imports)
            if isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
                assert name not in forbidden_calls
    main = (BACKEND / "app/main.py").read_text(encoding="utf-8")
    assert "v20261005_teacher_work_v2" not in main and "run_persistence" not in main


def test_v2_server_defaults_are_explicit_observed_facts():
    """P2: normalized default facts are versioned supplied data, never inferred."""
    v1 = _module("app.services.teacher_work.schema_v1", "app/services/teacher_work/schema_v1.py")
    v2 = _module("app.services.teacher_work.schema", "app/services/teacher_work/schema.py")
    migration = _module("migrations.v20261005_teacher_work_v2", "migrations/v20261005_teacher_work_v2.py")
    tables = v2.TEACHER_WORK_SCHEMA_CONTRACT["tables"]
    defaults = {"teacher_work_runs": {"repair_count": "0"},
                "teacher_work_messages": {"completion_run_id": None, "result_type": None, "omitted_context": None}}
    for table, expected in defaults.items():
        assert "server_defaults" in tables[table], "Task4b1 v2 normalized server-default facts are missing"
        assert tables[table]["server_defaults"] == expected
        assert "server_defaults" not in v1.TEACHER_WORK_SCHEMA_CONTRACT["tables"][table]
    assert canonical_digest(v2.TEACHER_WORK_SCHEMA_CONTRACT) == v2.TEACHER_WORK_CONTRACT_HASH
    tree = _tree("app/models/teacher_work.py")
    rc, mc = _columns(_class(tree, "WorkRun")), _columns(_class(tree, "WorkMessage"))
    assert ast.literal_eval(_keyword(rc["repair_count"], "server_default")) == defaults["teacher_work_runs"]["repair_count"]
    for name, value in defaults["teacher_work_messages"].items():
        assert value is None and not any(keyword.arg in {"default", "server_default"} for keyword in mc[name].keywords)
    good = _observation(v2)
    assert v2.inspect_teacher_work_schema(good).ready is True
    assert migration.check_teacher_work_v2_schema(good).ready is True
    assert migration.prepare_teacher_work_v2_schema(good, target_contract_hash=v2.TEACHER_WORK_CONTRACT_HASH).mode == "exact_v2"
    invalid = []
    for table, expected in defaults.items():
        missing_map = deepcopy(good)
        del missing_map["tables"][table]["server_defaults"]
        invalid.append(missing_map)
        extra_entry = deepcopy(good)
        extra_entry["tables"][table]["server_defaults"]["unreviewed_default"] = None
        invalid.append(extra_entry)
        for column, value in expected.items():
            missing_entry = deepcopy(good)
            del missing_entry["tables"][table]["server_defaults"][column]
            invalid.append(missing_entry)
            for wrong in ((0, "1") if value == "0" else ("NULL", False)):
                altered = deepcopy(good)
                altered["tables"][table]["server_defaults"][column] = wrong
                invalid.append(altered)
    assert len(invalid) == 16
    for observed in invalid:
        assert v2.inspect_teacher_work_schema(observed).ready is False
        assert migration.check_teacher_work_v2_schema(observed).ready is False
        with pytest.raises(ValueError):
            migration.prepare_teacher_work_v2_schema(observed, target_contract_hash=v2.TEACHER_WORK_CONTRACT_HASH)
    assert good == _observation(v2) and sha256((BACKEND / "app/services/teacher_work/schema_v1.py").read_bytes()).hexdigest() == V1_BYTES_HASH
