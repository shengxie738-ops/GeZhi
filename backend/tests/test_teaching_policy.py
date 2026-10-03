"""Task2 pure immutable-policy regressions; no Settings or runtime activation."""
import dataclasses
import importlib
import json

import pytest


def feature(name):
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        pytest.fail(f"Task2 feature absent: {name}: {exc}")


def inputs(*, roster=None, delegations=None, generation="g1", **kw):
    types = feature("app.services.teaching.types")
    return types.TeachingPolicyInputs(
        institution_id="school", enabled=True, generation=generation,
        trusted_roster_json=json.dumps(roster if roster is not None else {"owner": ["learner", "assistant", "teacherlearner"], "co": ["learner"], "other": []}),
        trusted_delegations_json=json.dumps(delegations if delegations is not None else {"owner": {"co": {"account_role": "teacher", "permissions": ["ROSTER_MANAGE", "ROLES_MANAGE", "REVIEW"], "scope": "offering"}, "assistant": {"account_role": "student", "permissions": ["AUTHOR"], "scope": "assigned"}}}), **kw)


def policy(value=None, actor="co", target=None):
    return feature("app.services.teaching.policy").read_teaching_policy(value or inputs(), "owner", actor_id=actor, target_subject_id=target)


def test_source_owner_and_exact_delegated_ceilings():
    p = policy(actor="owner")
    assert p.source_roster.valid and p.source_roster.present
    assert p.actor_ceiling.account_role == "teacher" and p.actor_ceiling.scope == "offering"
    assert len(p.actor_ceiling.permissions) == 9
    p = policy()
    assert p.learner_ceiling == frozenset({"learner"})
    assert p.actor_ceiling.account_role == "teacher"
    assert policy(actor="assistant").learner_ceiling == frozenset({"learner", "assistant", "teacherlearner"})


@pytest.mark.parametrize("roster", [{}, {"Owner": ["learner"]}, {"owner": "learner"}, {"owner": [""]}, {"owner": [" learner"]}, {"owner": [None]}, {"owner": ["a\n"]}])
def test_source_roster_missing_malformed_or_noncanonical_denies(roster):
    p = policy(inputs(roster=roster), actor="owner")
    assert not p.source_roster.valid
    assert p.actor_ceiling is None


def test_explicit_empty_source_roster_is_valid_and_distinct_from_missing():
    empty = policy(inputs(roster={"owner": []}), actor="owner")
    absent = policy(inputs(roster={}), actor="owner")
    assert empty.source_roster.valid and empty.source_roster.members == frozenset()
    assert empty.actor_ceiling is not None
    assert empty.digest != absent.digest


@pytest.mark.parametrize("entry", [
    {"account_role": "admin", "permissions": ["REVIEW"], "scope": "offering"},
    {"account_role": "student", "permissions": ["BOGUS"], "scope": "offering"},
    {"account_role": "student", "permissions": ["ROSTER_MANAGE"], "scope": "assigned"},
    {"account_role": "student", "permissions": ["AUTHOR"], "scope": "assigned", "assigned": True},
    {"account_role": "student", "permissions": "AUTHOR", "scope": "assigned"},
])
def test_bad_delegation_is_not_a_ceiling(entry):
    assert policy(inputs(delegations={"owner": {"assistant": entry}}), actor="assistant").actor_ceiling is None


def test_duplicate_json_keys_and_duplicate_identical_members_are_distinguished():
    value = inputs(roster={"owner": ["learner", "learner"]})
    assert policy(value, actor="owner").source_roster.members == frozenset({"learner"})
    duplicate = dataclasses.replace(value, trusted_roster_json='{"owner": ["learner"], "owner": ["assistant"]}')
    assert not policy(duplicate, actor="owner").source_roster.valid


def test_coherent_policy_digest_covers_coteacher_roster_and_never_mixes_generations():
    first = inputs()
    second = inputs(roster={"owner": ["assistant"], "co": ["assistant"], "other": []}, generation="g2")
    p1, p2 = policy(first), policy(second)
    assert p1.learner_ceiling == frozenset({"learner"})
    assert p2.learner_ceiling == frozenset({"assistant"})
    only_actor_changed = inputs(roster={"owner": ["learner", "assistant", "teacherlearner"], "co": ["assistant"], "other": []})
    assert p1.digest != policy(only_actor_changed).digest
    unrelated = inputs(roster={"owner": ["learner", "assistant", "teacherlearner"], "co": ["learner"], "other": ["someone"]}, generation="g99")
    assert p1.digest == policy(unrelated).digest
    assert p1.generation == "g1" and policy(unrelated).generation == "g99"
    with pytest.raises(dataclasses.FrozenInstanceError):
        first.generation = "mixed"
    with pytest.raises(dataclasses.FrozenInstanceError):
        p1.digest = "mixed"


def test_target_delegation_and_coteacher_roster_participate_in_digest():
    before = policy(target="co", actor="owner")
    changed = inputs(roster={"owner": ["learner", "assistant", "teacherlearner"], "co": [], "other": []})
    assert before.digest != policy(changed, actor="owner", target="co").digest
    assert policy().digest != policy(inputs(delegations={}), actor="co").digest


def test_unknown_permissions_and_scope_are_typed_errors():
    t = feature("app.services.teaching.types")
    with pytest.raises(ValueError):
        t.Permission("ASSIGNMENT_PUBLISH")
    with pytest.raises(ValueError):
        t.ScopeRef("school", "assignment", "a")
    with pytest.raises(TypeError):
        t.ObjectRef("assignment", "a", "school", "c", "o", assigned=True)


@pytest.mark.parametrize("field,value", [("account_role", []), ("account_role", {}), ("scope", []), ("scope", {})])
def test_unhashable_delegation_fields_fail_closed(field, value):
    entry = {"account_role": "student", "permissions": ["AUTHOR"], "scope": "assigned"}
    entry[field] = value
    parsed = policy(inputs(delegations={"owner": {"assistant": entry}}), actor="assistant")
    assert parsed.actor_ceiling is None and parsed.learner_ceiling == frozenset()
