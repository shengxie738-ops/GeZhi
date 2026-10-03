"""Task4 bounded course-local roles. Global accounts are never modified."""
from datetime import datetime
from uuid import uuid4

from fastapi import HTTPException

from app.models.teaching import TeachingRole
from app.models.user_account import UserAccount
from app.schemas.teaching import RoleWriteResultDTO, SetRoleCommand
from app.services.teaching.courses import _scope, normalise_command, role_metadata
from app.services.teaching.types import LockPlan, MutationResult, ReceiptLookup, TeachingAction, exact_identifier
from app.services.teaching.writes import execute_write, make_write_intent


def _error(status, reason):
    raise HTTPException(status, reason)


def _instant(value):
    # The write engine canonicalizes validated UTC datetimes to these strings.
    return None if value is None else datetime.fromisoformat(value.replace("Z", "+00:00"))


class _SetRoleOperation:
    def collect_locks(self, session, intent, roots, preview_footprint=None):
        # Preserve the syntactic route target in the intent hash. Resolve its
        # canonical account key only here, before account/role locks and clock.
        account = session.query(UserAccount).filter(UserAccount.username == intent.target_id).populate_existing().first()
        subject = account.username if account is not None else intent.target_id
        return LockPlan(root_course_id=roots.course.id, root_offering_id=roots.offering.id,
                        account_ids=(subject,), role_subject_ids=(subject,),
                        receipt_lookup=ReceiptLookup.from_intent(intent), target_subject_id=subject)

    def validate_new(self, context, command, at):
        subject = context.lock_plan.target_subject_id
        row = context.roles[subject]
        if (row.revision if row is not None else 0) != command["expected_role_revision"]:
            _error(409, "revision_conflict")
        if command["status"] == "revoked":
            if row is None:
                _error(409, "revision_conflict")
            # Cleanup is allowed with a missing/demoted/out-of-ceiling target,
            # including on archive. It does not create or rebind a grant.
            return
        if context.offering.state not in {"draft", "active"}:
            _error(409, "lifecycle_conflict")
        account, ceiling = context.accounts[subject], context.policy.target_ceiling
        permissions = frozenset(command["permissions"])
        if (account is None or account.role not in {"student", "teacher"} or ceiling is None
                or account.role != ceiling.account_role
                or account.role == "student" and command["label"] != "assistant"
                or not permissions <= {permission.value for permission in ceiling.permissions}
                or command["scope"] == "offering" and ceiling.scope != "offering"):
            # Identical for unknown and known-but-untrusted target subjects.
            _error(403, "permission_denied")
        start, end = _instant(command["effective_from"]) or at, _instant(command["effective_until"])
        if end is not None:
            if end <= at:
                _error(409, "effective_window_closed")
            if end <= start:
                _error(422, "validation_error")

    def apply_new(self, context, command, at):
        subject = context.lock_plan.target_subject_id
        row = context.roles[subject]
        before = role_metadata(row)
        old_revision = row.revision if row is not None else 0
        if command["status"] == "revoked":
            row.status = "revoked"
            row.permissions = []
            row.revoked_at = at
            # Keep old binding, label/scope, interval and grant-policy provenance.
        else:
            if row is None:
                row = TeachingRole(id=str(uuid4()), institution_id=context.scope.institution_id,
                                   offering_id=context.offering.id, subject_id=subject, created_at=at)
                context.session.add(row)
            row.granted_account_role = context.accounts[subject].role
            row.label = command["label"]
            row.permissions = list(command["permissions"])
            row.scope = command["scope"]
            row.status = "active"
            row.effective_from = _instant(command["effective_from"]) or at
            row.effective_until = _instant(command["effective_until"])
            row.revoked_at = None
            row.source_policy_digest = context.policy.digest
        row.revision = old_revision + 1
        row.updated_at = at
        result = RoleWriteResultDTO(role_id=row.id, subject_id=subject, revision=row.revision, status=row.status).model_dump()
        return MutationResult("role", row.id, result, "role", old_revision, row.revision,
                              {"before": before, "after": role_metadata(row)}, 200)


def prepare_role_write(session, actor_id, offering_id, subject_id, command, key):
    payload = normalise_command(command, SetRoleCommand)
    if not exact_identifier(subject_id):
        _error(422, "validation_error")
    scope = _scope(session, "offering", offering_id)
    intent = make_write_intent(actor_id, TeachingAction.ROLES_MANAGE, scope, subject_id, key, payload)
    return intent, _SetRoleOperation()


def set_role(session, actor_id, offering_id, subject_id, command, key):
    intent, operation = prepare_role_write(session, actor_id, offering_id, subject_id, command, key)
    return execute_write(session, intent, intent.scope, operation)
