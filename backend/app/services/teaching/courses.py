"""Task4 server-owned course/offering mutations; never commit or activate B1.

All SQL discovery and authority remain in the accepted write engine. These
operations consume its declared locked rows at its final authorization clock.
"""
from collections.abc import Mapping
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError

from app.models.teaching import Course, Offering, TeachingRole
from app.schemas.teaching import (
    CreateCourseCommand, UpdateCourseCommand, CreateOfferingCommand,
    UpdateOfferingCommand, TransitionOfferingCommand, CourseWriteResultDTO,
    OfferingWriteResultDTO, TransitionWriteResultDTO,
)
from app.services.teaching import access
from app.services.teaching.types import (
    LockPlan, MutationResult, Permission, ReceiptLookup, ScopeRef,
    TeachingAction, exact_identifier,
)
from app.services.teaching.writes import execute_write, make_write_intent


BOOTSTRAP_PERMISSIONS = tuple(sorted(permission.value for permission in Permission))
_ALLOWED_EDGES = frozenset({("draft", "active"), ("draft", "archived"),
                            ("active", "archived"), ("archived", "draft")})


def _error(status, reason):
    raise HTTPException(status, reason)


def normalise_command(command, dto, *, patch=False):
    """Use one strict DTO boundary for direct service and HTTP callers alike."""
    if isinstance(command, dto):
        value = command
    elif isinstance(command, Mapping):
        try:
            value = dto.model_validate(dict(command))
        except ValidationError:
            _error(422, "validation_error")
    else:
        _error(422, "validation_error")
    result = value.model_dump(mode="python", exclude_unset=patch)
    if "permissions" in result:
        result["permissions"] = [permission.value for permission in result["permissions"]]
    return result


def _scope(session, kind, identifier=None):
    inputs = access._inputs(session)
    reason = access._availability(inputs)
    if reason:
        _error(503, reason)
    identifier = inputs.institution_id if kind == "institution" else identifier
    if not exact_identifier(identifier, 64 if kind == "institution" else 36):
        _error(404, "not_found")
    return ScopeRef(inputs.institution_id, kind, identifier)


def role_metadata(row):
    """Minimal complete relationship revision, without account/profile data."""
    if row is None:
        return None
    fields = ("id", "institution_id", "offering_id", "subject_id", "granted_account_role",
              "label", "permissions", "scope", "status", "revision", "source_policy_digest")
    result = {field: list(getattr(row, field)) if field == "permissions" else getattr(row, field) for field in fields}
    for field in ("effective_from", "effective_until", "revoked_at", "created_at", "updated_at"):
        result[field] = access._utc(getattr(row, field))
    return result


class _CourseOperation:
    """Purpose is selected by the server, never by a client request field."""
    def __init__(self, purpose):
        self.purpose = purpose

    def collect_locks(self, session, intent, roots, preview_footprint=None):
        return LockPlan(root_course_id=roots.course.id if roots.course else None,
                        root_offering_id=roots.offering.id if roots.offering else None,
                        receipt_lookup=ReceiptLookup.from_intent(intent),
                        course_visibility_offering_ids=roots.course_visibility_offering_ids)

    def validate_new(self, context, command, at):
        if self.purpose in {"offering_update", "offering_transition"}:
            if self.purpose == "offering_update" and context.offering.state not in {"draft", "active"}:
                _error(409, "lifecycle_conflict")
            if self.purpose == "offering_transition" and (context.offering.state, command["target_state"]) not in _ALLOWED_EDGES:
                _error(409, "lifecycle_conflict")
            if context.offering.revision != command["expected_revision"]:
                _error(409, "revision_conflict")
        elif self.purpose == "course_update" and context.course.revision != command["expected_revision"]:
            _error(409, "revision_conflict")

    def apply_new(self, context, command, at):
        if self.purpose == "course_create":
            row = Course(id=str(uuid4()), institution_id=context.scope.institution_id,
                source_teacher_id=context.authorization.actor_id, title=command["title"],
                code=command["code"], description=command["description"], timezone=command["timezone"],
                revision=1, created_at=at, updated_at=at)
            context.session.add(row)
            result = CourseWriteResultDTO(course_id=row.id, revision=1).model_dump()
            return MutationResult("course", row.id, result, "course", 0, 1,
                                  {"created": True}, 201)
        if self.purpose == "offering_create":
            row = Offering(id=str(uuid4()), institution_id=context.scope.institution_id,
                course_id=context.course.id, title=command["title"], term=command["term"],
                timezone=command["timezone"] or context.course.timezone, state="draft", revision=1,
                roster_revision=0, created_at=at, updated_at=at, archived_at=None)
            bootstrap = TeachingRole(id=str(uuid4()), institution_id=context.scope.institution_id,
                offering_id=row.id, subject_id=context.authorization.actor_id,
                granted_account_role=context.actor_account.role, label="teacher",
                permissions=list(BOOTSTRAP_PERMISSIONS), scope="offering", status="active",
                effective_from=at, effective_until=None, revoked_at=None, revision=1,
                source_policy_digest=context.policy.digest, created_at=at, updated_at=at)
            context.session.add_all([row, bootstrap])
            result = OfferingWriteResultDTO(offering_id=row.id, revision=1).model_dump()
            return MutationResult("offering", row.id, result, "offering", 0, 1,
                                  {"state": "draft", "roster_revision": 0, "bootstrap_role": role_metadata(bootstrap)}, 201)
        row = context.course if self.purpose == "course_update" else context.offering
        before = row.revision
        if self.purpose == "offering_transition":
            previous = row.state
            row.state = command["target_state"]
            row.archived_at = at if row.state == "archived" else None
            effects = {"before_state": previous, "after_state": row.state}
        else:
            fields = ("title", "code", "description", "timezone") if self.purpose == "course_update" else ("title", "term", "timezone")
            changed = []
            for field in fields:
                if field in command:
                    if getattr(row, field) != command[field]:
                        changed.append(field)
                    setattr(row, field, command[field])
            effects = {"changed": changed}
        row.revision += 1
        row.updated_at = at
        if self.purpose == "course_update":
            result = CourseWriteResultDTO(course_id=row.id, revision=row.revision).model_dump()
            return MutationResult("course", row.id, result, "course", before, row.revision, effects, 200)
        result = TransitionWriteResultDTO(offering_id=row.id, revision=row.revision, state=row.state).model_dump() if self.purpose == "offering_transition" else OfferingWriteResultDTO(offering_id=row.id, revision=row.revision).model_dump()
        return MutationResult("offering", row.id, result, "offering", before, row.revision, effects, 200)


_COMMANDS = {
    "course_create": (CreateCourseCommand, TeachingAction.CREATE_COURSE, "institution", False),
    "course_update": (UpdateCourseCommand, TeachingAction.UPDATE_COURSE, "course", True),
    "offering_create": (CreateOfferingCommand, TeachingAction.CREATE_OFFERING, "course", False),
    "offering_update": (UpdateOfferingCommand, TeachingAction.COURSE_MANAGE, "offering", True),
    "offering_transition": (TransitionOfferingCommand, TeachingAction.COURSE_MANAGE, "offering", False),
}


def prepare_course_write(session, actor_id, purpose, command, key, target_id=None):
    """Internal adapter preparation, with no business SQL, flush or commit."""
    if purpose not in _COMMANDS:
        raise ValueError("unknown server-owned course operation")
    dto, action, kind, patch = _COMMANDS[purpose]
    payload = normalise_command(command, dto, patch=patch)
    # Distinguish metadata updates and transitions sharing COURSE_MANAGE.
    payload["operation"] = purpose
    scope = _scope(session, kind, target_id)
    intent = make_write_intent(actor_id, action, scope, target_id, key, payload)
    return intent, _CourseOperation(purpose)


def _execute(session, actor_id, purpose, command, key, target_id=None):
    intent, operation = prepare_course_write(session, actor_id, purpose, command, key, target_id)
    return execute_write(session, intent, intent.scope, operation)


def create_course(session, actor_id, command, key):
    return _execute(session, actor_id, "course_create", command, key)


def update_course(session, actor_id, course_id, command, key):
    return _execute(session, actor_id, "course_update", command, key, course_id)


def create_offering(session, actor_id, course_id, command, key):
    return _execute(session, actor_id, "offering_create", command, key, course_id)


def update_offering(session, actor_id, offering_id, command, key):
    return _execute(session, actor_id, "offering_update", command, key, offering_id)


def transition_offering(session, actor_id, offering_id, command, key):
    return _execute(session, actor_id, "offering_transition", command, key, offering_id)
