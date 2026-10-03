"""Strict source-rooted parsing from exactly one immutable supplied generation.

Digests cover relevant values, including participating co-teacher rosters. They
are provenance/change detection, not a distributed revocation mechanism.
"""
from dataclasses import dataclass
from hashlib import sha256
import json

from app.services.teaching.types import ASSESSMENT_PERMISSIONS, Permission, TeachingPolicyInputs, exact_identifier


@dataclass(frozen=True)
class RosterEntry:
    present: bool
    valid: bool
    members: frozenset[str] = frozenset()
    document_valid: bool = True


@dataclass(frozen=True)
class TrustedCeiling:
    account_role: str
    permissions: frozenset[Permission]
    scope: str


@dataclass(frozen=True)
class TeachingPolicy:
    inputs: TeachingPolicyInputs
    source_teacher_id: str | None
    actor_id: str | None
    target_subject_id: str | None
    source_roster: RosterEntry
    actor_roster: RosterEntry | None
    target_roster: RosterEntry | None
    actor_ceiling: TrustedCeiling | None
    target_ceiling: TrustedCeiling | None
    learner_ceiling: frozenset[str]
    digest: str
    generation: str


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("ambiguous duplicate policy key")
        result[key] = value
    return result


def _document(raw):
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=lambda value: (_ for _ in ()).throw(ValueError("non-JSON number")))
        return value if isinstance(value, dict) else None
    except (ValueError, TypeError, RecursionError):
        return None


def _roster(document, subject):
    if document is None:
        return RosterEntry(False, False, document_valid=False)
    if subject is None or subject not in document:
        return RosterEntry(False, False)
    values = document[subject]
    if not isinstance(values, list) or not all(exact_identifier(value) for value in values):
        return RosterEntry(True, False)
    return RosterEntry(True, True, frozenset(values))


def _delegation(document, source, subject):
    if document is None:
        return None, "document_invalid", None
    if source not in document:
        return None, "missing", None
    entries = document[source]
    if not isinstance(entries, dict):
        return None, "source_invalid", entries
    if subject not in entries:
        return None, "missing", None
    raw = entries[subject]
    if not isinstance(raw, dict) or set(raw) != {"account_role", "permissions", "scope"}:
        return None, "invalid", raw
    if not isinstance(raw["account_role"], str) or not isinstance(raw["scope"], str):
        return None, "invalid", raw
    if raw["account_role"] not in {"student", "teacher"} or raw["scope"] not in {"assigned", "offering"} or not isinstance(raw["permissions"], list):
        return None, "invalid", raw
    try:
        permissions = frozenset(Permission(value) for value in raw["permissions"])
    except (ValueError, TypeError):
        return None, "invalid", raw
    if raw["scope"] == "assigned" and not permissions <= ASSESSMENT_PERMISSIONS:
        return None, "invalid", raw
    ceiling = TrustedCeiling(raw["account_role"], permissions, raw["scope"])
    return ceiling, "valid", {"account_role": ceiling.account_role, "permissions": sorted(p.value for p in permissions), "scope": ceiling.scope}


def _roster_value(entry, document, subject):
    if entry is None:
        return None
    result = {"present": entry.present, "valid": entry.valid, "document_valid": entry.document_valid, "members": sorted(entry.members)}
    if entry.present and not entry.valid:
        result["invalid_value"] = document.get(subject) if document is not None else None
    return result


def read_teaching_policy(inputs: TeachingPolicyInputs, source_teacher_id: str | None = None, *, actor_id: str | None = None, target_subject_id: str | None = None) -> TeachingPolicy:
    if not isinstance(inputs, TeachingPolicyInputs):
        raise TypeError("one immutable TeachingPolicyInputs generation required")
    source = source_teacher_id if source_teacher_id is not None else actor_id
    for value in (source, actor_id, target_subject_id):
        if value is not None and not exact_identifier(value):
            raise ValueError("exact canonical policy subject required")
    roster_document = _document(inputs.trusted_roster_json)
    delegation_document = _document(inputs.trusted_delegations_json)
    source_roster = _roster(roster_document, source)

    def participant(subject):
        if subject is None:
            return None, None, {"subject": None}
        if subject == source:
            ceiling = TrustedCeiling("teacher", frozenset(Permission), "offering") if source_roster.valid else None
            return ceiling, None, {"subject": subject, "owner": True}
        ceiling, state, relevant = _delegation(delegation_document, source, subject)
        own_roster = _roster(roster_document, subject) if ceiling is not None and ceiling.account_role == "teacher" else None
        participant_value = {"subject": subject, "delegation_state": state, "delegation": relevant, "teacher_roster": _roster_value(own_roster, roster_document, subject)}
        if not source_roster.valid or ceiling is None:
            return None, own_roster, participant_value
        if ceiling.account_role == "student" and subject not in source_roster.members:
            return None, own_roster, participant_value
        if ceiling.account_role == "teacher" and (own_roster is None or not own_roster.valid):
            return None, own_roster, participant_value
        return ceiling, own_roster, participant_value

    actor_ceiling, actor_roster, actor_value = participant(actor_id)
    target_ceiling, target_roster, target_value = participant(target_subject_id)
    learners = source_roster.members if actor_ceiling is not None else frozenset()
    if actor_roster is not None:
        learners = learners & actor_roster.members
    relevant = {"version": 1, "institution_id": inputs.institution_id, "enabled": inputs.enabled,
                "stages": [inputs.assignments_enabled, inputs.feedback_enabled, inputs.revisions_enabled],
                "source": source, "source_roster": _roster_value(source_roster, roster_document, source),
                "actor": actor_value, "target": target_value}
    if roster_document is None:
        relevant["invalid_roster_document_hash"] = sha256(inputs.trusted_roster_json.encode()).hexdigest()
    if delegation_document is None and (actor_id != source or target_subject_id is not None and target_subject_id != source):
        relevant["invalid_delegation_document_hash"] = sha256(inputs.trusted_delegations_json.encode()).hexdigest()
    digest = sha256(json.dumps(relevant, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return TeachingPolicy(inputs, source, actor_id, target_subject_id, source_roster, actor_roster, target_roster, actor_ceiling, target_ceiling, learners, digest, inputs.generation)
