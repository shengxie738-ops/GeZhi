"""Full-set roster previews/applications under the accepted write engine.

No service commits, no runtime bypass, and no SQL after the final clock. Full
immutable sets are authority; bounded display samples never authorize writes.
MySQL collation/lock/isolation safety is unproved and production remains gated.
"""
from collections import Counter
from datetime import datetime, timedelta
from hashlib import sha256
import json
from uuid import uuid4

from fastapi import HTTPException

from app.models.teaching import Enrollment, RosterPreview
from app.models.user_account import UserAccount
from app.schemas.teaching import (
    PreviewChangesQuery, PreviewIssueDTO, RosterApplicationCommand,
    RosterApplicationDTO, RosterPreviewCommand, RosterPreviewDTO,
)
from app.services.teaching import access
from app.services.teaching.courses import _scope, normalise_command
from app.services.teaching.policy import read_teaching_policy
from app.services.teaching.types import LockPlan, MutationResult, ReceiptLookup, TeachingAction, exact_identifier
from app.services.teaching.writes import _json, digest_id_set, execute_write, make_write_intent

MAX_ACTIVE = 10000
# Four change samples plus issue samples stay bounded even at 255 Unicode
# characters / four UTF-8 bytes each under the unchanged 64 KiB receipt cap.
DISPLAY_SAMPLE = 10


def _error(status, reason):
    raise HTTPException(status, reason)


def _instant(value):
    return None if value is None else datetime.fromisoformat(value.replace("Z", "+00:00"))


def _plain(value):
    return json.loads(_json(value))


def _command_digest(command):
    return sha256(_json(command).encode("utf-8")).hexdigest()


def _resolve_requested(session, requested, ceiling):
    """Resolve only inside the trusted canonical ceiling, without case folding.

    The SQL predicate constrains every candidate to trusted usernames; no raw
    out-of-scope account is fetched to distinguish unknown from unavailable.
    Exact matches are batched. Potential DB aliases use that same constrained
    candidate query and reject ambiguity rather than picking a first result.
    Actual vendor alias semantics still require independent MySQL evidence.
    """
    requested, ceiling = sorted(set(requested)), frozenset(ceiling)
    if not requested or not ceiling:
        return {}, [{"code": "unavailable_or_out_of_scope", "subject_id": value} for value in requested]
    query = session.query(UserAccount.username).filter(UserAccount.username.in_(sorted(ceiling)))
    matches = query.filter(UserAccount.username.in_(requested)).all()
    canonical = {row[0] for row in matches if row[0] in ceiling}
    resolved, issues = {}, []
    for value in requested:
        if value in canonical:
            resolved[value] = value
            continue
        candidates = query.filter(UserAccount.username == value).limit(2).all()
        if len(candidates) == 1 and candidates[0][0] in ceiling:
            resolved[value] = candidates[0][0]
        else:
            issues.append({"code": "unavailable_or_out_of_scope", "subject_id": value})
    return resolved, issues


def _active_rows(context):
    return {subject: row for subject, row in context.enrollments.items()
            if row is not None and row.status == "active"}


def _period_changed(row, period):
    if period is None:
        return False
    # Null start means application acceptance time, not the preview's clock.
    return (period["effective_from"] is None
            or access._utc(row.effective_from) != _instant(period["effective_from"])
            or access._utc(row.effective_until) != _instant(period["effective_until"]))


def _diff(context, mode, desired, period):
    active = _active_rows(context)
    desired = set(desired)
    targets = desired | set(active) if mode == "merge" else desired
    adds = targets - set(active)
    keeps = targets & set(active)
    updates = {subject for subject in desired & keeps if _period_changed(active[subject], period)}
    return {"target": sorted(targets), "add": sorted(adds), "keep": sorted(keeps),
            "update": sorted(updates), "withdraw": sorted(set(active) - targets)}


def _valid_target(context, subject):
    row = context.accounts.get(subject)
    return (subject in context.authorization.learner_ceiling and row is not None
            and row.username == subject and row.role in {"student", "teacher"})


def _validate_period(period, affected, at):
    if period is None or not affected:
        return
    start, end = _instant(period["effective_from"]) or at, _instant(period["effective_until"])
    if end is not None:
        if end <= at:
            _error(409, "effective_window_closed")
        if end <= start:
            _error(422, "validation_error")


def _projection(row, sets, at):
    # The complete issues and membership arrays stay in the immutable preview.
    # This compact projection remains below the accepted receipt size boundary.
    issues = [PreviewIssueDTO(code=issue["code"], subject_id=issue.get("subject_id"))
              for issue in row.validation_issues[:DISPLAY_SAMPLE]]
    period = row.canonical_command.get("period")
    return RosterPreviewDTO(id=row.id, offering_id=row.offering_id, mode=row.mode,
        expected_roster_revision=row.expected_roster_revision, offering_revision=row.offering_revision,
        target_count=len(sets["target"]), add_count=len(sets["add"]), keep_count=len(sets["keep"]),
        update_count=len(sets["update"]), withdrawals_count=len(sets["withdraw"]),
        target_digest=row.target_digest, withdrawals_digest=row.withdrawals_digest,
        withdraw_sample=sets["withdraw"][:DISPLAY_SAMPLE], add_sample=sets["add"][:DISPLAY_SAMPLE],
        keep_sample=sets["keep"][:DISPLAY_SAMPLE], update_sample=sets["update"][:DISPLAY_SAMPLE],
        validation_issue_count=len(row.validation_issues), validation_issues=issues,
        period=period, period_target_count=len(row.canonical_command.get("student_ids", [])) if period is not None else 0,
        can_apply=row.can_apply, expired=at >= access._utc(row.expires_at),
        created_at=access._utc(row.created_at), expires_at=access._utc(row.expires_at))


def enrollment_metadata(row):
    """Every changed relationship revision, without private account profiles."""
    if row is None:
        return None
    fields = ("id", "institution_id", "offering_id", "student_id", "status", "revision",
              "source_kind", "source_teacher_id", "source_policy_digest")
    result = {field: getattr(row, field) for field in fields}
    for field in ("effective_from", "effective_until", "withdrawn_at", "created_at", "updated_at"):
        result[field] = access._utc(getattr(row, field))
    return result


class _PreviewOperation:
    def __init__(self, duplicates):
        self.duplicates = duplicates

    def collect_locks(self, session, intent, roots, preview_footprint=None):
        policy = read_teaching_policy(access._inputs(session), roots.course.source_teacher_id,
                                      actor_id=roots.actor_account.username)
        self.resolved, self.issues = _resolve_requested(session, intent.canonical_payload["student_ids"], policy.learner_ceiling)
        self.discovery_policy_digest = policy.digest
        # Entire status-active set, independent of effective interval/cap. Never
        # limit this query: a reducing replacement must see inconsistent excess.
        active = tuple(row[0] for row in session.query(Enrollment.student_id).filter(
            Enrollment.institution_id == roots.scope.institution_id,
            Enrollment.offering_id == roots.offering.id, Enrollment.status == "active").all())
        subjects = tuple(sorted(set(active) | set(self.resolved.values())))
        return LockPlan(root_course_id=roots.course.id, root_offering_id=roots.offering.id,
            account_ids=tuple(sorted(set(self.resolved.values()))), enrollment_subject_ids=subjects,
            receipt_lookup=ReceiptLookup.from_intent(intent))

    def validate_new(self, context, command, at):
        if context.offering.state not in {"draft", "active"}:
            _error(409, "lifecycle_conflict")
        if context.offering.roster_revision != command["expected_roster_revision"]:
            _error(409, "revision_conflict")
        if context.policy.digest != self.discovery_policy_digest:
            _error(409, "preview_stale")
        desired = sorted(set(self.resolved.values()))
        self.sets = _diff(context, command["mode"], desired, command["period"])
        if len(self.sets["target"]) > MAX_ACTIVE:
            _error(422, "roster_capacity_exceeded")
        issues = [*self.issues, *({"code": "duplicate_input", "subject_id": value} for value in self.duplicates)]
        for subject, count in sorted(Counter(self.resolved.values()).items()):
            if count > 1:
                issues.append({"code": "duplicate_alias", "subject_id": subject})
        for subject in desired:
            if not _valid_target(context, subject):
                issues.append({"code": "unavailable_or_out_of_scope", "subject_id": subject})
        self.validation_issues = issues
        self.desired = desired
        _validate_period(command["period"], self.sets["add"] or self.sets["update"], at)

    def apply_new(self, context, command, at):
        saved_command = _plain(command)
        saved_command["student_ids"] = self.desired
        row = RosterPreview(id=str(uuid4()), institution_id=context.scope.institution_id,
            offering_id=context.offering.id, actor_id=context.authorization.actor_id,
            actor_role_id=context.authorization.role_id, actor_role_revision=context.authorization.role_revision,
            expected_roster_revision=context.offering.roster_revision, offering_revision=context.offering.revision,
            mode=command["mode"], canonical_command=saved_command, command_hash=_command_digest(saved_command),
            source_policy_digest=context.policy.digest,
            target_ids=self.sets["target"], add_ids=self.sets["add"], keep_ids=self.sets["keep"],
            update_ids=self.sets["update"], withdraw_ids=self.sets["withdraw"],
            validation_issues=self.validation_issues,
            target_digest=digest_id_set("roster_target", self.sets["target"]),
            withdrawals_digest=digest_id_set("roster_withdrawals", self.sets["withdraw"]),
            withdrawals_count=len(self.sets["withdraw"]),
            can_apply=not any(issue["code"] == "unavailable_or_out_of_scope" for issue in self.validation_issues),
            created_at=at, expires_at=at + timedelta(minutes=10))
        context.session.add(row)
        result = _projection(row, self.sets, at).model_dump(mode="python")
        return MutationResult("roster_preview", row.id, result, "preview", 0, 1,
            {"target_count": len(row.target_ids), "withdrawals_count": row.withdrawals_count,
             "target_digest": row.target_digest, "withdrawals_digest": row.withdrawals_digest,
             "can_apply": row.can_apply}, 201)


class _ApplyOperation:
    def collect_locks(self, session, intent, roots, preview_footprint=None):
        # The engine has already filtered the immutable footprint by original
        # actor/scope. Current full membership additionally detects changed sets.
        active = tuple(row[0] for row in session.query(Enrollment.student_id).filter(
            Enrollment.institution_id == roots.scope.institution_id,
            Enrollment.offering_id == roots.offering.id, Enrollment.status == "active").all())
        return LockPlan(root_course_id=roots.course.id, root_offering_id=roots.offering.id,
            enrollment_subject_ids=active, preview_id=preview_footprint.preview_id,
            receipt_lookup=ReceiptLookup.from_intent(intent))

    def validate_new(self, context, command, at):
        row = context.preview
        if context.offering.state not in {"draft", "active"}:
            _error(409, "lifecycle_conflict")
        if (context.authorization.role_id != row.actor_role_id
                or context.authorization.role_revision != row.actor_role_revision
                or context.offering.revision != row.offering_revision
                or context.offering.roster_revision != row.expected_roster_revision
                or command["expected_roster_revision"] != row.expected_roster_revision
                or context.policy.digest != row.source_policy_digest or not row.can_apply
                or at >= access._utc(row.expires_at)
                or _command_digest(row.canonical_command) != row.command_hash):
            _error(409, "preview_stale")
        desired, period = row.canonical_command["student_ids"], row.canonical_command["period"]
        if any(not _valid_target(context, subject) for subject in desired):
            _error(409, "preview_stale")
        sets = _diff(context, row.mode, desired, period)
        if len(sets["target"]) > MAX_ACTIVE:
            _error(422, "roster_capacity_exceeded")
        if (any(sets[kind] != sorted(getattr(row, kind + "_ids")) for kind in sets)
                or digest_id_set("roster_target", sets["target"]) != row.target_digest
                or digest_id_set("roster_withdrawals", sets["withdraw"]) != row.withdrawals_digest
                or len(sets["withdraw"]) != row.withdrawals_count):
            _error(409, "preview_stale")
        if (command["confirmed_withdrawals_digest"] != row.withdrawals_digest
                or command["confirmed_withdrawals_count"] != row.withdrawals_count):
            _error(409, "withdrawal_confirmation_mismatch")
        _validate_period(period, sets["add"] or sets["update"], at)
        self.sets = sets

    def apply_new(self, context, command, at):
        preview, sets, effects = context.preview, self.sets, []
        period = preview.canonical_command["period"]
        withdrawals = set(sets["withdraw"])
        for subject in sorted(set(sets["add"]) | set(sets["update"]) | withdrawals):
            row = context.enrollments[subject]
            before = enrollment_metadata(row)
            revision = row.revision if row is not None else 0
            if subject in withdrawals:
                row.status, row.withdrawn_at = "withdrawn", at
                # Preserve old effective interval and source provenance for cleanup.
            else:
                if row is None:
                    row = Enrollment(id=str(uuid4()), institution_id=context.scope.institution_id,
                        offering_id=context.offering.id, student_id=subject, created_at=at)
                    context.session.add(row)
                row.status, row.withdrawn_at = "active", None
                row.effective_from = (_instant(period["effective_from"]) or at) if period is not None else at
                row.effective_until = _instant(period["effective_until"]) if period is not None else None
                row.source_kind, row.source_teacher_id = "deployment_roster", context.course.source_teacher_id
                row.source_policy_digest = context.policy.digest
            row.revision, row.updated_at = revision + 1, at
            effects.append({"before": before, "after": enrollment_metadata(row)})
        before_revision = context.offering.roster_revision
        context.offering.roster_revision += 1
        context.offering.updated_at = at
        result = RosterApplicationDTO(offering_id=context.offering.id, preview_id=preview.id,
            roster_revision=context.offering.roster_revision, target_count=len(sets["target"]),
            added_count=len(sets["add"]), kept_count=len(sets["keep"]) - len(sets["update"]),
            updated_count=len(sets["update"]), withdrawn_count=len(sets["withdraw"]),
            target_digest=preview.target_digest, withdrawals_digest=preview.withdrawals_digest).model_dump()
        return MutationResult("roster", context.offering.id, result, "roster", before_revision,
            context.offering.roster_revision, {"preview_id": preview.id, "counts": result, "enrollments": effects}, 200)


def prepare_roster_write(session, actor_id, offering_id, purpose, command, key):
    if purpose == "preview":
        payload = normalise_command(command, RosterPreviewCommand)
        duplicates = sorted(value for value, count in Counter(payload["student_ids"]).items() if count > 1)
        operation, target = _PreviewOperation(duplicates), None
    elif purpose == "apply":
        payload = normalise_command(command, RosterApplicationCommand)
        operation, target = _ApplyOperation(), payload["preview_id"]
    else:
        raise ValueError("unknown server roster operation")
    scope = _scope(session, "offering", offering_id)
    intent = make_write_intent(actor_id, TeachingAction.ROSTER_MANAGE, scope, target, key, payload)
    return intent, operation


def preview_roster(session, actor_id, offering_id, command, key):
    intent, operation = prepare_roster_write(session, actor_id, offering_id, "preview", command, key)
    return execute_write(session, intent, intent.scope, operation)


def apply_roster(session, actor_id, offering_id, command, key):
    intent, operation = prepare_roster_write(session, actor_id, offering_id, "apply", command, key)
    return execute_write(session, intent, intent.scope, operation)


def _read_preview(session, actor_id, offering_id, preview_id):
    if not exact_identifier(offering_id, 36) or not exact_identifier(preview_id, 36):
        _error(404, "not_found")
    # Scope/original-actor filtering precedes permission-specific detail errors.
    # Reuse the accepted current-authority helper; do not invent permission rules.
    actor, inputs = access._begin_read(session, actor_id)
    exists = session.query(RosterPreview.id).filter(RosterPreview.id == preview_id,
        RosterPreview.institution_id == inputs.institution_id, RosterPreview.offering_id == offering_id,
        RosterPreview.actor_id == actor.username).first()
    if exists is None:
        _error(404, "not_found")
    try:
        return access._preview_read(session, actor.username, offering_id, preview_id)
    except HTTPException as exc:
        if exc.status_code == 404:
            _error(404, "not_found")
        raise


def get_roster_preview(session, actor_id, offering_id, preview_id):
    row, sets, at = _read_preview(session, actor_id, offering_id, preview_id)
    return _projection(row, sets, at)


def list_roster_preview_changes(session, actor_id, offering_id, preview_id, query: PreviewChangesQuery):
    _read_preview(session, actor_id, offering_id, preview_id)
    try:
        return access.get_roster_preview_changes(session, actor_id, offering_id, preview_id, query)
    except HTTPException as exc:
        if exc.status_code == 404:
            _error(404, "not_found")
        raise
