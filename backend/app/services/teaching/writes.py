"""B1 original-receipt infrastructure; services never commit.

MySQL writes are deliberately unavailable until the independent real-vendor
isolation/constraint-contention gate is closed. SQLite fixture substitution
proves control flow/atomicity only, never gap-lock or successful-wait safety.
"""
from collections.abc import Mapping
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from types import MappingProxyType
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import event, text, or_
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.models.teaching import AccessEvent, Course, Enrollment, Offering, RosterPreview, TeachingRole, WriteReceipt
from app.models.user_account import UserAccount
from app.schemas.teaching import WriteReceiptDTO
from app.services.teaching import access
from app.services.teaching.policy import read_teaching_policy
from app.services.teaching.types import (
    LockPlan, LockedContext, MutationResult, PreviewFootprint, ReceiptLookup,
    ScopeRef, TeachingAction, WriteIntent, WriteOperation, WriteResult,
    exact_identifier,
)

WRITE_ACTIONS = frozenset({TeachingAction.CREATE_COURSE, TeachingAction.UPDATE_COURSE,
    TeachingAction.CREATE_OFFERING, TeachingAction.COURSE_MANAGE,
    TeachingAction.ROSTER_MANAGE, TeachingAction.ROLES_MANAGE})
_SET_FIELDS = frozenset({"student_ids", "permissions"})
_KEY = re.compile(r"[A-Za-z0-9._:-]{8,128}\Z", re.ASCII)


def _error(status, reason):
    raise HTTPException(status, reason)


def validate_key(key):
    if not isinstance(key, str) or not _KEY.fullmatch(key):
        _error(422, "validation_error")
    return key


def _canonical(value, field=None):
    if value is None or isinstance(value, str) or type(value) is bool:
        if field and field.endswith("revision") and value is not None and type(value) is not int:
            _error(422, "validation_error")
        return value
    if type(value) is int:
        if field and field.endswith("revision") and value < 0:
            _error(422, "validation_error")
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            _error(422, "validation_error")
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            _error(422, "validation_error")
        return {key: _canonical(item, key) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        values = [_canonical(item) for item in value]
        if field in _SET_FIELDS:
            if any(type(item) is not str for item in values):
                _error(422, "validation_error")
            return sorted(set(values))
        return values
    _error(422, "validation_error")


def _json(value):
    return json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def canonical_request_hash(action, scope: ScopeRef, target_id, command) -> str:
    try:
        action = TeachingAction(action)
    except (ValueError, TypeError):
        _error(422, "validation_error")
    if action not in WRITE_ACTIONS or not isinstance(scope, ScopeRef) or not isinstance(command, Mapping):
        _error(422, "validation_error")
    if target_id is not None and not exact_identifier(target_id):
        _error(422, "validation_error")
    body = {"version": 1, "action": action.value, "scope_type": scope.kind,
            "scope_id": scope.id, "target_id": target_id, "command": command}
    return sha256(_json(body).encode("utf-8")).hexdigest()


def digest_id_set(kind: str, ids) -> str:
    values = list(ids)
    if not exact_identifier(kind, 64) or any(not exact_identifier(value) for value in values):
        _error(422, "validation_error")
    return sha256(_json({"version": 1, "kind": kind, "ids": sorted(set(values))}).encode("utf-8")).hexdigest()


def make_write_intent(actor_id, action, scope, target_id, idempotency_key, command):
    if not exact_identifier(actor_id):
        _error(422, "validation_error")
    validate_key(idempotency_key)
    digest = canonical_request_hash(action, scope, target_id, command)
    return WriteIntent(actor_id, TeachingAction(action), scope, target_id, idempotency_key,
                       _freeze(_canonical(command)), 1, digest)


def _require_write_safety(session):
    """No settings/info/client bypass: a future reviewed implementation replaces it.

    READ COMMITTED alone does not exclude successful post-clock FK/unique waits.
    It is unsafe to turn a mock/SQLite result into production activation.
    """
    _error(503, "write_safety_unproven")


def _require_transaction(session):
    if not isinstance(session, Session) or session.info.get("teaching_transaction") != "READ COMMITTED":
        _error(503, "lock_orchestration_required")
    connection = session.connection()
    if connection.dialect.name != "mysql" or connection.get_isolation_level().replace("-", " ").upper() != "READ COMMITTED":
        _error(503, "lock_orchestration_required")


def _server_clock(session):
    value = session.execute(text("SELECT UTC_TIMESTAMP(6)")).scalar_one()
    if not isinstance(value, datetime):
        _error(503, "invalid_authorization_clock")
    return access._utc(value)


def _fresh(session, model, *filters, lock=False):
    query = session.query(model).filter(*filters).populate_existing()
    if lock:
        query = query.with_for_update()
    return query.first()


def _locked_account(session, subject):
    row = _fresh(session, UserAccount, UserAccount.username == subject, lock=True)
    return row if row is not None and row.username == subject else None


def _roots(session, actor, scope, object_ref):
    course = offering = None
    if scope.kind == "offering":
        discovery = session.query(Offering.course_id).filter(Offering.id == scope.id,
            Offering.institution_id == scope.institution_id).first()
        if discovery is None:
            _error(404, "not_found")
        course_id = discovery[0]
    else:
        course_id = scope.id if scope.kind == "course" else None
    if course_id is not None:
        course = _fresh(session, Course, Course.id == course_id, Course.institution_id == scope.institution_id, lock=True)
        if course is None:
            _error(404, "not_found")
    if scope.kind == "offering":
        offering = _fresh(session, Offering, Offering.id == scope.id, Offering.institution_id == scope.institution_id, lock=True)
        if offering is None:
            _error(404, "not_found")
        if offering.course_id != course.id:
            _error(503, "lock_footprint_changed")
    return LockedContext(actor, scope, course=course, offering=offering, object_ref=object_ref, session=session)


def _course_visibility_candidates(session, roots, action):
    if roots.scope.kind != "course" or action not in {TeachingAction.UPDATE_COURSE, TeachingAction.CREATE_OFFERING}:
        return ()
    actor = roots.actor_account.username
    enrolled = session.query(Enrollment.id).filter(Enrollment.institution_id == roots.scope.institution_id,
        Enrollment.offering_id == Offering.id, Enrollment.student_id == actor).exists()
    granted = session.query(TeachingRole.id).filter(TeachingRole.institution_id == roots.scope.institution_id,
        TeachingRole.offering_id == Offering.id, TeachingRole.subject_id == actor).exists()
    # No status, period or lifecycle filter: only final authority can decide
    # visibility. The held Course mutex protects all of these Offering shells.
    rows = session.query(Offering.id).filter(Offering.institution_id == roots.scope.institution_id,
        Offering.course_id == roots.course.id, or_(enrolled, granted)).order_by(Offering.id).all()
    return tuple(row[0] for row in rows)


def _course_visibility_rows(session, roots, plan):
    ids, actor, institution = plan.course_visibility_offering_ids, roots.actor_account.username, roots.scope.institution_id
    shells = {}
    for identifier in ids:
        shell = _fresh(session, Offering, Offering.id == identifier,
            Offering.institution_id == institution, Offering.course_id == roots.course.id)
        if shell is None or (shell.id, shell.institution_id, shell.course_id) != (identifier, institution, roots.course.id):
            _error(503, "lock_footprint_changed")
        shells[identifier] = shell
    roles = {identifier: _fresh(session, TeachingRole, TeachingRole.institution_id == institution,
        TeachingRole.offering_id == identifier, TeachingRole.subject_id == actor, lock=True) for identifier in ids}
    enrollments = {identifier: _fresh(session, Enrollment, Enrollment.institution_id == institution,
        Enrollment.offering_id == identifier, Enrollment.student_id == actor, lock=True) for identifier in ids}
    snapshots = []
    for identifier in ids:
        role, enrollment = roles[identifier], enrollments[identifier]
        if role is None and enrollment is None:
            _error(503, "lock_footprint_changed")
        for row, subject_field in ((role, "subject_id"), (enrollment, "student_id")):
            if row is not None and (row.institution_id, row.offering_id, getattr(row, subject_field)) != (institution, identifier, actor):
                _error(503, "lock_footprint_changed")
        # Detached frozen value objects remain outside context.roles/enrollments
        # and _post_clock's mutable-row allowance. These locks authorize only
        # denial classification, never mutation of another Offering or relation.
        snapshots.append(access.readonly_course_visibility(shells[identifier], role, enrollment))
    return tuple(snapshots)


def _preview_fingerprint(row):
    values = {column.name: getattr(row, column.name) for column in row.__table__.columns}
    for key, value in values.items():
        if isinstance(value, datetime):
            values[key] = access._utc(value)
    return sha256(_json(values).encode("utf-8")).hexdigest()


def _subjects(values):
    if not isinstance(values, (list, tuple)) or any(not exact_identifier(item) for item in values):
        _error(503, "invalid_lock_footprint")
    return tuple(sorted(set(values)))


def _preview_row(session, roots, preview_id, lock=False):
    if roots.offering is None or not exact_identifier(preview_id, 36):
        _error(404, "not_found")
    row = _fresh(session, RosterPreview, RosterPreview.id == preview_id,
        RosterPreview.institution_id == roots.scope.institution_id,
        RosterPreview.offering_id == roots.offering.id,
        RosterPreview.actor_id == roots.actor_account.username, lock=lock)
    if row is None:
        _error(404, "not_found")
    return row


def _preview_footprint(session, roots, preview_id):
    if preview_id is None:
        return None
    row = _preview_row(session, roots, preview_id)
    target_ids = _subjects(row.target_ids)
    related = _subjects([*row.add_ids, *row.keep_ids, *row.update_ids, *row.withdraw_ids])
    return PreviewFootprint(row.id, row.institution_id, row.offering_id, row.actor_id,
                            _preview_fingerprint(row), target_ids, related)


def _complete_plan(plan, roots, lookup, footprint):
    expected_roots = (roots.course.id if roots.course else None, roots.offering.id if roots.offering else None)
    if not isinstance(plan, LockPlan) or (plan.root_course_id, plan.root_offering_id) != expected_roots or plan.receipt_lookup != lookup:
        _error(503, "invalid_lock_footprint")
    if plan.preview_id != (footprint.preview_id if footprint else None):
        _error(503, "invalid_lock_footprint")
    if (plan.course_visibility_offering_ids != roots.course_visibility_offering_ids
            or any(not exact_identifier(identifier, 36) for identifier in plan.course_visibility_offering_ids)):
        _error(503, "invalid_lock_footprint")
    actor = roots.actor_account.username
    source = roots.course.source_teacher_id if roots.course else actor
    accounts = _subjects(plan.account_ids) + (actor, source) + (footprint.target_ids if footprint else ())
    roles = _subjects(plan.role_subject_ids) + ((actor,) if roots.offering else ())
    enrollments = _subjects(plan.enrollment_subject_ids) + ((actor,) if roots.offering else ()) + (footprint.relationship_subject_ids if footprint else ())
    accounts += roles + enrollments
    if roots.offering is None and (roles or enrollments):
        _error(503, "invalid_lock_footprint")
    if plan.target_subject_id is not None:
        if not exact_identifier(plan.target_subject_id) or plan.target_subject_id not in accounts:
            _error(503, "invalid_lock_footprint")
    return replace(plan, account_ids=tuple(sorted(set(accounts))), role_subject_ids=tuple(sorted(set(roles))),
                   enrollment_subject_ids=tuple(sorted(set(enrollments))))


def _receipt_candidate(session, lookup):
    if lookup is None:
        return None
    return _fresh(session, WriteReceipt, WriteReceipt.institution_id == lookup.scope.institution_id,
        WriteReceipt.actor_id == lookup.actor_id, WriteReceipt.action == lookup.action.value,
        WriteReceipt.scope_type == lookup.scope.kind, WriteReceipt.scope_id == lookup.scope.id,
        WriteReceipt.idempotency_key == lookup.idempotency_key, lock=True)


def require_clean_transaction(session):
    """No queued state may cross a read/replay/commit decision boundary."""
    if session.new or session.dirty or session.deleted:
        _error(503, "unclean_write_transaction")


def _require_same_transaction(connection, transaction):
    if transaction is None or not transaction.is_active or connection.get_transaction() is not transaction:
        _error(503, "transaction_changed")


@contextmanager
def _no_mutation(session):
    """Lock discovery/authorization is read-only, including callback collection.

    Check pending state before each SQL read so populate_existing/autoflush
    cannot erase or persist an accidental queued change before the final guard.
    This defensive invariant has static review; no adversarial replay probe was
    executed for it. The production write-safety gate remains unconditional.
    """
    require_clean_transaction(session)
    connection = session.connection()
    transaction = connection.get_transaction()
    _require_same_transaction(connection, transaction)

    def before_sql(connection, cursor, statement, parameters, execution_context, executemany):
        require_clean_transaction(session)
        _require_same_transaction(connection, transaction)
        if not statement.lstrip().upper().startswith(("SELECT ", "SHOW ", "DESCRIBE ", "EXPLAIN ")):
            _error(503, "lock_collection_mutation_forbidden")

    def reject_flush(session, flush_context, instances):
        _error(503, "lock_collection_mutation_forbidden")

    def reject_commit(connection):
        _error(503, "service_commit_forbidden")

    listeners = ((connection, "before_cursor_execute", before_sql),
                 (connection, "commit", reject_commit), (session, "before_flush", reject_flush))
    for target, name, listener in listeners:
        event.listen(target, name, listener)
    try:
        with session.no_autoflush:
            yield
            require_clean_transaction(session)
            _require_same_transaction(connection, transaction)
    finally:
        for target, name, listener in reversed(listeners):
            event.remove(target, name, listener)


def _lock_context(session, actor_id, action, scope, *, intent=None, mutation=None, lookup=None, object_ref=None, write=False):
    _require_transaction(session)
    # Trusted identity/policy/schema preflight precedes operation collection.
    # Dialect reflection has its own read-only statements (e.g. SQLite PRAGMA);
    # it must conclude the real readiness refusal, not run under the narrower
    # server-operation SQL whitelist. No callback or mutation runs here.
    require_clean_transaction(session)
    connection = session.connection()
    transaction = connection.get_transaction()
    _require_same_transaction(connection, transaction)
    with session.no_autoflush:
        actor, initial = access._begin_read(session, actor_id)
    require_clean_transaction(session)
    _require_same_transaction(connection, transaction)
    with _no_mutation(session):
        return _collect_locked_context(session, action, scope, actor=actor, initial=initial,
            intent=intent, mutation=mutation, lookup=lookup, object_ref=object_ref, write=write)


def _collect_locked_context(session, action, scope, *, actor, initial, intent=None, mutation=None, lookup=None, object_ref=None, write=False):
    if write:
        _require_write_safety(session)
    if not isinstance(scope, ScopeRef) or scope.institution_id != initial.institution_id:
        _error(404, "not_found")
    action = access._action(action)
    access._validate_action_scope(action, scope)
    roots = _roots(session, actor, scope, object_ref)
    roots = replace(roots, course_visibility_offering_ids=_course_visibility_candidates(session, roots, action))
    if intent is not None:
        intent = replace(intent, actor_id=actor.username)
        lookup = ReceiptLookup.from_intent(intent)
    elif lookup is not None:
        lookup = replace(lookup, actor_id=actor.username)
    preview_id = intent.canonical_payload.get("preview_id") if intent else None
    footprint = _preview_footprint(session, roots, preview_id)
    if mutation is None:
        plan = LockPlan(roots.course.id if roots.course else None,
                        roots.offering.id if roots.offering else None, receipt_lookup=lookup,
                        course_visibility_offering_ids=roots.course_visibility_offering_ids)
    else:
        plan = mutation.collect_locks(session, intent, roots, footprint)
        require_clean_transaction(session)
    plan = _complete_plan(plan, roots, lookup, footprint)
    accounts = {subject: _locked_account(session, subject) for subject in plan.account_ids}
    roles, enrollments = {}, {}
    for subject in plan.role_subject_ids:
        roles[subject] = _fresh(session, TeachingRole, TeachingRole.institution_id == scope.institution_id,
            TeachingRole.offering_id == roots.offering.id, TeachingRole.subject_id == subject, lock=True)
    for subject in plan.enrollment_subject_ids:
        enrollments[subject] = _fresh(session, Enrollment, Enrollment.institution_id == scope.institution_id,
            Enrollment.offering_id == roots.offering.id, Enrollment.student_id == subject, lock=True)
    visibility = _course_visibility_rows(session, roots, plan)
    preview = _preview_row(session, roots, footprint.preview_id, lock=True) if footprint else None
    if preview is not None and _preview_fingerprint(preview) != footprint.content_fingerprint:
        _error(503, "lock_footprint_changed")
    receipt = _receipt_candidate(session, lookup)
    source_id = roots.course.source_teacher_id if roots.course else actor.username
    context = replace(roots, actor_account=accounts[actor.username], source_account=accounts[source_id],
        role=roles.get(actor.username), enrollment=enrollments.get(actor.username), receipt=receipt,
        accounts=MappingProxyType(accounts), roles=MappingProxyType(roles), enrollments=MappingProxyType(enrollments),
        preview=preview, preview_footprint=footprint, lock_plan=plan, course_visibility=visibility,
        pre_mutation=MappingProxyType({"course_revision": roots.course.revision if roots.course else None,
            "offering_revision": roots.offering.revision if roots.offering else None,
            "roster_revision": roots.offering.roster_revision if roots.offering else None,
            "state": roots.offering.state if roots.offering else None}))
    inputs = access._final_inputs(session, initial)
    policy = read_teaching_policy(inputs, source_id, actor_id=actor.username, target_subject_id=plan.target_subject_id)
    at = _server_clock(session)
    authorization = access.authorize_locked_action(context, policy, action, at)
    return replace(context, authorization=authorization, policy=policy)


def locked_authorization(session, actor_id, action, scope, object_ref=None):
    return _lock_context(session, actor_id, action, scope, object_ref=object_ref).authorization


def _result(receipt, replayed):
    data = deepcopy(receipt.original_result)
    dto = WriteReceiptDTO(id=receipt.id, action=TeachingAction(receipt.action), scope_type=receipt.scope_type,
        scope_id=receipt.scope_id, target_type=receipt.target_type, target_id=receipt.target_id,
        result_type=receipt.result_type, result_id=receipt.result_id, canonicalization_version=receipt.canonicalization_version,
        request_hash=receipt.request_hash, accepted_at=access._utc(receipt.accepted_at), http_status=receipt.http_status,
        original_result=deepcopy(data))
    return WriteResult(dto, data, replayed)


@contextmanager
def _no_commit(session):
    def reject_commit(session):
        _error(503, "service_commit_forbidden")
    event.listen(session, "before_commit", reject_commit)
    try:
        yield
    finally:
        event.remove(session, "before_commit", reject_commit)


def _stable_row_key(row):
    # Relationship identity and parent binding cannot move under an old lock.
    fields = ("id", "institution_id", "source_teacher_id") if isinstance(row, Course) else (
        ("id", "institution_id", "course_id") if isinstance(row, Offering) else
        ("id", "institution_id", "offering_id", "subject_id") if isinstance(row, TeachingRole) else
        ("id", "institution_id", "offering_id", "student_id"))
    return tuple(getattr(row, field) for field in fields)


def _declared_new_row(row, context, own_appends, new_offerings):
    if id(row) in own_appends:
        return True
    if getattr(row, "institution_id", None) != context.scope.institution_id:
        return False
    if isinstance(row, Course):
        return context.scope.kind == "institution" and row.source_teacher_id == context.authorization.actor_id
    if isinstance(row, Offering):
        return context.scope.kind == "course" and row.course_id == context.course.id
    if isinstance(row, TeachingRole) and context.scope.kind == "course":
        # Offering creation's sole actor bootstrap role uses a new UUID parent.
        return row.offering_id in new_offerings and row.subject_id == context.authorization.actor_id
    if context.offering is None or getattr(row, "offering_id", None) != context.offering.id:
        return False
    if isinstance(row, TeachingRole):
        return row.subject_id in context.lock_plan.role_subject_ids and row.subject_id in context.accounts
    if isinstance(row, Enrollment):
        return row.student_id in context.lock_plan.enrollment_subject_ids and row.student_id in context.accounts
    if isinstance(row, RosterPreview):
        return row.actor_id == context.authorization.actor_id
    return False


@contextmanager
def _post_clock(session, context):
    # Application SQL, including connection.execute(), may not discover targets
    # after the final clock. Only flush-generated DML is permitted. This is NOT
    # proof of database-internal FK/unique wait behavior; production stays gated.
    connection = session.connection()
    transaction = connection.get_transaction()
    _require_same_transaction(connection, transaction)
    protected = [context.course, context.offering, *context.roles.values(), *context.enrollments.values()]
    stable = {id(row): _stable_row_key(row) for row in protected if row is not None}
    state = {"flushing": False}
    own_appends = set()

    def reject_sql(execute_state):
        _error(503, "post_clock_query_forbidden")

    def reject_statement(connection, cursor, statement, parameters, execution_context, executemany):
        _require_same_transaction(connection, transaction)
        if not state["flushing"] or not statement.lstrip().upper().startswith(("INSERT ", "UPDATE ", "DELETE ")):
            _error(503, "post_clock_query_forbidden")

    def reject_commit(connection):
        _error(503, "service_commit_forbidden")

    def before_flush(session, flush_context, instances):
        _require_same_transaction(connection, transaction)
        if session.deleted:
            _error(503, "undeclared_mutation")
        for row in session.dirty:
            if id(row) not in stable or _stable_row_key(row) != stable[id(row)]:
                _error(503, "undeclared_mutation")
        new_offerings = {row.id for row in session.new if isinstance(row, Offering)
                         and context.course is not None and row.course_id == context.course.id
                         and row.institution_id == context.scope.institution_id and row.id is not None}
        if any(not _declared_new_row(row, context, own_appends, new_offerings) for row in session.new):
            _error(503, "undeclared_mutation")
        state["flushing"] = True

    def after_flush(session, flush_context):
        state["flushing"] = False

    listeners = ((session, "do_orm_execute", reject_sql), (session, "before_flush", before_flush),
                 (session, "after_flush_postexec", after_flush),
                 (connection, "before_cursor_execute", reject_statement), (connection, "commit", reject_commit))
    for target, name, listener in listeners:
        event.listen(target, name, listener)
    try:
        yield lambda row: own_appends.add(id(row))
        require_clean_transaction(session)
        _require_same_transaction(connection, transaction)
    finally:
        for target, name, listener in reversed(listeners):
            event.remove(target, name, listener)


def _validate_mutation(result):
    if not isinstance(result, MutationResult) or result.http_status not in {200, 201}:
        _error(503, "invalid_mutation_result")
    if (result.revision_kind not in {"course", "offering", "roster", "role", "preview"}
            or type(result.before_revision) is not int or result.before_revision < 0
            or type(result.after_revision) is not int or result.after_revision < 1
            or not exact_identifier(result.result_id, 36) or not exact_identifier(result.result_type, 64)
            or not isinstance(result.original_result, Mapping) or not isinstance(result.effect_metadata, Mapping)):
        _error(503, "invalid_mutation_result")
    original, effects = _canonical(result.original_result), _canonical(result.effect_metadata)
    if len(_json(original).encode("utf-8")) > 65536:
        _error(503, "invalid_mutation_result")
    return original, effects


def execute_write(session: Session, intent: WriteIntent, authorization_scope: ScopeRef, mutation: WriteOperation) -> WriteResult:
    """Return a provisional detached projection; only the HTTP owner commits."""
    try:
        require_clean_transaction(session)
        if not isinstance(intent, WriteIntent) or intent.scope != authorization_scope or intent.canonicalization_version != 1:
            _error(422, "validation_error")
        validate_key(intent.idempotency_key)
        if canonical_request_hash(intent.action, intent.scope, intent.target_id, intent.canonical_payload) != intent.request_hash:
            _error(422, "validation_error")
        with _no_commit(session):
            context = _lock_context(session, intent.actor_id, intent.action, authorization_scope, intent=intent, mutation=mutation, write=True)
            require_clean_transaction(session)
            at = context.authorization.checked_at
            with _post_clock(session, context) as allow_append:
                if context.receipt is not None:
                    if context.receipt.request_hash != intent.request_hash:
                        _error(409, "idempotency_conflict")
                    result = _result(context.receipt, True)
                    require_clean_transaction(session)
                    return result
                mutation.validate_new(context, intent.canonical_payload, at)
                result = mutation.apply_new(context, intent.canonical_payload, at)
                original, effects = _validate_mutation(result)
                receipt = WriteReceipt(id=str(uuid4()), institution_id=intent.scope.institution_id,
                    actor_id=context.authorization.actor_id, action=intent.action.value, scope_type=intent.scope.kind,
                    scope_id=intent.scope.id, target_type=result.result_type, target_id=result.result_id,
                    idempotency_key=intent.idempotency_key, canonicalization_version=1, request_hash=intent.request_hash,
                    result_type=result.result_type, result_id=result.result_id, accepted_at=at,
                    http_status=result.http_status, original_result=original)
                allow_append(receipt)
                session.add(receipt)
                session.flush()
                access_event = AccessEvent(id=str(uuid4()), institution_id=intent.scope.institution_id,
                    receipt_id=receipt.id, actor_id=context.authorization.actor_id, actor_role=context.authorization.account_role,
                    action=intent.action.value, scope_type=intent.scope.kind, scope_id=intent.scope.id,
                    target_type=result.result_type, target_id=result.result_id, revision_kind=result.revision_kind,
                    before_revision=result.before_revision, after_revision=result.after_revision,
                    reason=intent.canonical_payload.get("reason", ""), occurred_at=at, effect_metadata=effects)
                allow_append(access_event)
                session.add(access_event)
                session.flush()
                accepted = _result(receipt, False)
                require_clean_transaction(session)
                return accepted
    except (OperationalError, IntegrityError):
        session.rollback()
        _error(503, "database_unavailable")
    except Exception:
        session.rollback()
        raise


def _recover(session, actor_id, lookup, receipt_id=None):
    try:
        context = _lock_context(session, actor_id, lookup.action, lookup.scope, lookup=lookup)
        if context.receipt is None or receipt_id is not None and context.receipt.id != receipt_id:
            _error(404, "not_found")
        result = _result(context.receipt, True)
        require_clean_transaction(session)
        return result
    except HTTPException as exc:
        if exc.status_code in {401, 403, 404}:
            _error(404, "not_found")
        raise


def get_receipt(session: Session, actor_id: str, receipt_id: str) -> WriteResult:
    """An inaccessible/missing receipt means outcome unknown, never resubmit."""
    try:
        require_clean_transaction(session)
        actor, inputs = access._begin_read(session, actor_id)
        receipt = _fresh(session, WriteReceipt, WriteReceipt.id == receipt_id,
            WriteReceipt.actor_id == actor.username, WriteReceipt.institution_id == inputs.institution_id)
        if receipt is None:
            _error(404, "not_found")
        action = TeachingAction(receipt.action)
        if action not in WRITE_ACTIONS:
            _error(404, "not_found")
        lookup = ReceiptLookup(actor.username, action, ScopeRef(receipt.institution_id, receipt.scope_type, receipt.scope_id), receipt.idempotency_key)
        return _recover(session, actor.username, lookup, receipt_id)
    except HTTPException as exc:
        if exc.status_code in {401, 403, 404}:
            _error(404, "not_found")
        raise


def find_receipt(session: Session, actor_id: str, action: TeachingAction, scope: ScopeRef, key: str) -> WriteResult:
    validate_key(key)
    try:
        action = TeachingAction(action)
    except (ValueError, TypeError):
        _error(422, "validation_error")
    if action not in WRITE_ACTIONS:
        _error(422, "validation_error")
    return _recover(session, actor_id, ReceiptLookup(actor_id, action, scope, key))
