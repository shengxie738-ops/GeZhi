"""Persisted B1 own-scope readers and current authority evaluation.

No commits, writes, HTTP router, startup, policy activation, or implicit Session.
Task3 owns READ COMMITTED opening and full lock orchestration. These ordinary
reads are fresh transaction-local decisions, not lock-protected receipt replay.
"""
from dataclasses import replace
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.teaching import Course, Enrollment, Offering, RosterPreview, TeachingRole, WriteReceipt
from app.services.current_identity import load_current_account
from app.services.teaching.policy import TeachingPolicy, read_teaching_policy
from app.services.teaching.schema import TeachingSchemaError, require_teaching_schema
from app.services.teaching.types import (
    ACTION_PERMISSION, ASSESSMENT_PERMISSIONS, DEFAULT_POLICY_INPUTS,
    AuthorizationContext, AuthorizationSnapshot, LockedContext, ObjectRef,
    Permission, ScopeRef, TeachingAction, TeachingPolicyInputs, exact_identifier,
)
from app.schemas.teaching import (
    CapabilityDTO, CourseDTO, CoursePageDTO, CourseQuery, EnrollmentDTO,
    OfferingAccessDTO, OfferingDTO, OfferingPageDTO, OfferingQuery, PageQuery,
    PreviewChangesDTO, PreviewChangesQuery, PreviewIssueDTO, RoleDTO, RoleListDTO,
    RosterEntryDTO, RosterPageDTO, RosterPreviewDTO, StageDTO,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _deny(status, reason):
    raise HTTPException(status_code=status, detail=reason)


def _utc(value):
    # B1 SQL DATETIME columns are UTC by contract; drivers may return naive UTC.
    return None if value is None else value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _inputs(session: Session) -> TeachingPolicyInputs:
    provider = session.info.get("teaching_policy_provider")
    if provider is None:
        return DEFAULT_POLICY_INPUTS
    if not callable(provider):
        _deny(503, "policy_snapshot_unavailable")
    value = provider()
    if not isinstance(value, TeachingPolicyInputs):
        _deny(503, "policy_snapshot_unavailable")
    return value


def _availability(inputs):
    if not inputs.enabled:
        return "feature_disabled"
    if not exact_identifier(inputs.institution_id, 64):
        return "institution_required"
    return None


def _gate(session, inputs):
    reason = _availability(inputs)
    if reason:
        _deny(503, reason)
    try:
        require_teaching_schema(session)
    except TeachingSchemaError as exc:
        _deny(503, exc.code)


def _begin_read(session, actor_id):
    actor = load_current_account(session, actor_id)
    inputs = _inputs(session)
    _gate(session, inputs)
    return actor, inputs


def _final_inputs(session, initial):
    inputs = _inputs(session)
    reason = _availability(inputs)
    if reason:
        _deny(503, reason)
    if inputs.institution_id != initial.institution_id:
        _deny(503, "policy_institution_changed")
    return inputs


def _optional_account(session, subject):
    try:
        account = load_current_account(session, subject)
    except HTTPException as exc:
        if exc.status_code != 401:
            raise
        return None
    # SQL collation aliases must not reinterpret persisted/configured subjects.
    return account if account.username == subject else None


def _load_context(session, actor, scope, object_ref=None):
    course = offering = role = enrollment = None
    if scope.kind == "institution":
        return AuthorizationContext(actor, scope, source_account=actor, object_ref=object_ref)
    if scope.kind == "offering":
        offering = session.query(Offering).filter(Offering.id == scope.id, Offering.institution_id == scope.institution_id).populate_existing().first()
        if offering is None:
            _deny(404, "scope_not_found")
        course_id = offering.course_id
    else:
        course_id = scope.id
    course = session.query(Course).filter(Course.id == course_id, Course.institution_id == scope.institution_id).populate_existing().first()
    if course is None:
        _deny(404, "scope_not_found")
    source_account = actor if actor.username == course.source_teacher_id else _optional_account(session, course.source_teacher_id)
    if offering is not None:
        role = session.query(TeachingRole).filter(TeachingRole.institution_id == scope.institution_id, TeachingRole.offering_id == offering.id, TeachingRole.subject_id == actor.username).populate_existing().first()
        enrollment = session.query(Enrollment).filter(Enrollment.institution_id == scope.institution_id, Enrollment.offering_id == offering.id, Enrollment.student_id == actor.username).populate_existing().first()
    return AuthorizationContext(actor, scope, source_account, course, offering, role, enrollment, object_ref)


def load_authorization_context(session: Session, actor_id: str, scope: ScopeRef) -> AuthorizationContext:
    """Internal footprint loader, not a permission decision or public DTO reader.

    No locks are acquired. Task3 must refresh/lock its complete footprint itself;
    converting this read context to LockedContext does not establish SQL locks.
    """
    return _load_context(session, load_current_account(session, actor_id), scope)


def _active(row, at):
    if row is None or row.status != "active" or type(row.revision) is not int or row.revision < 1:
        return False
    start, end = _utc(row.effective_from), _utc(row.effective_until)
    return start is not None and (end is None or end > start) and start <= at and (end is None or at < end)


def _permissions(row):
    if row is None or not isinstance(row.permissions, list):
        return None
    try:
        permissions = frozenset(Permission(value) for value in row.permissions)
    except (TypeError, ValueError):
        return None
    if row.permissions != sorted(permission.value for permission in permissions):
        return None
    if row.scope not in {"offering", "assigned"} or row.scope == "assigned" and not permissions <= ASSESSMENT_PERMISSIONS:
        return None
    return permissions


def _role_effect(row, account, ceiling, at):
    if not _active(row, at):
        return None, "role_inactive"
    if account is None or account.role not in {"student", "teacher"} or account.username != row.subject_id:
        return None, "account_unavailable"
    if ceiling is None:
        return None, "trusted_ceiling_unavailable"
    if account.role != row.granted_account_role or account.role != ceiling.account_role:
        return None, "account_role_binding_changed"
    if row.label not in {"teacher", "assistant"} or account.role == "student" and row.label != "assistant":
        return None, "invalid_role_label"
    permissions = _permissions(row)
    if permissions is None:
        return None, "invalid_permissions"
    if not permissions <= ceiling.permissions or row.scope == "offering" and ceiling.scope != "offering":
        return None, "role_exceeds_trusted_ceiling"
    return permissions, "effective"


def _source_live(context, policy):
    account = context.source_account
    return (policy.source_roster.valid and account is not None and account.role == "teacher"
            and account.username == policy.source_teacher_id)


def _object_scope(context):
    ref = context.object_ref
    if ref is None:
        return
    if ref.kind not in {"course", "offering", "enrollment"}:
        _deny(403, "unsupported_object")
    if ref.institution_id != context.scope.institution_id:
        _deny(404, "scope_not_found")
    course, offering = context.course, context.offering
    if course is None or ref.course_id != course.id or offering is not None and ref.offering_id != offering.id:
        _deny(404, "scope_not_found")
    expected = {"course": course, "offering": offering, "enrollment": context.enrollment}[ref.kind]
    if expected is None or ref.id != expected.id:
        _deny(404, "scope_not_found")


def _action(value):
    try:
        return TeachingAction(value)
    except (TypeError, ValueError):
        _deny(422, "unknown_action")


def _validate_action_scope(action, scope):
    if not isinstance(scope, ScopeRef):
        _deny(403, "action_scope_mismatch")
    expected = "institution" if action == TeachingAction.CREATE_COURSE else "course" if action in {
        TeachingAction.UPDATE_COURSE, TeachingAction.CREATE_OFFERING, TeachingAction.READ_COURSE,
    } else "offering"
    if scope.kind != expected:
        _deny(403, "action_scope_mismatch")


def _validate_roots(context):
    scope, course, offering = context.scope, context.course, context.offering
    if scope.kind == "institution":
        if course is not None or offering is not None or context.role is not None or context.enrollment is not None:
            _deny(403, "row_scope_mismatch")
        return
    if course is None or scope.kind == "offering" and offering is None:
        _deny(404, "scope_not_found")
    if course.institution_id != scope.institution_id:
        _deny(403, "row_scope_mismatch")
    if scope.kind == "course":
        if course.id != scope.id or offering is not None:
            _deny(403, "row_scope_mismatch")
    elif offering.id != scope.id or offering.institution_id != scope.institution_id or offering.course_id != course.id:
        _deny(403, "row_scope_mismatch")


def _evaluate(context, policy, action, at):
    action = _action(action)
    _validate_action_scope(action, context.scope)
    _validate_roots(context)
    if not isinstance(at, datetime) or at.tzinfo is None or at.utcoffset() != timezone.utc.utcoffset(at):
        _deny(503, "invalid_authorization_clock")
    actor, scope = context.actor_account, context.scope
    if actor is None or actor.role not in {"student", "teacher"} or not exact_identifier(actor.username):
        _deny(401, "invalid_current_account")
    if policy.actor_id != actor.username or policy.inputs.institution_id != scope.institution_id:
        _deny(403, "policy_scope_mismatch")
    reason = _availability(policy.inputs)
    if reason:
        _deny(503, reason)
    if context.course is not None and (context.course.institution_id != scope.institution_id or context.course.source_teacher_id != policy.source_teacher_id):
        _deny(403, "policy_scope_mismatch")
    if context.offering is not None and (context.course is None or context.offering.institution_id != scope.institution_id or context.offering.course_id != context.course.id or scope.kind != "offering" or scope.id != context.offering.id):
        _deny(403, "row_scope_mismatch")
    if context.role is not None and (context.offering is None or context.role.institution_id != scope.institution_id or context.role.offering_id != context.offering.id or context.role.subject_id != actor.username):
        _deny(403, "row_scope_mismatch")
    if context.enrollment is not None and (context.offering is None or context.enrollment.institution_id != scope.institution_id or context.enrollment.offering_id != context.offering.id or context.enrollment.student_id != actor.username):
        _deny(403, "row_scope_mismatch")
    _object_scope(context)
    source_live = _source_live(context, policy)
    owner = source_live and actor.role == "teacher" and actor.username == policy.source_teacher_id
    permissions, _ = _role_effect(context.role, actor, policy.actor_ceiling, at) if source_live else (None, "source_unavailable")
    teaching = owner or permissions is not None
    enrollment = context.enrollment
    learning = (source_live and context.offering is not None and context.offering.state in {"active", "archived"}
                and _active(enrollment, at) and enrollment.source_kind == "deployment_roster"
                and enrollment.source_teacher_id == policy.source_teacher_id and actor.username in policy.source_roster.members)
    if action == TeachingAction.CREATE_COURSE:
        if scope.kind != "institution" or not owner:
            _deny(403, "source_owner_required")
    elif action in {TeachingAction.UPDATE_COURSE, TeachingAction.CREATE_OFFERING}:
        if scope.kind != "course" or not owner:
            _deny(403, "source_owner_required")
    elif action == TeachingAction.READ_COURSE:
        if scope.kind != "course" or not owner:
            _deny(404, "scope_not_found")
    elif action == TeachingAction.READ_OFFERING:
        if scope.kind != "offering" or not (teaching or learning):
            _deny(404, "scope_not_found")
    elif action == TeachingAction.READ_ENROLLMENT:
        if scope.kind != "offering" or not learning:
            _deny(404, "scope_not_found")
    else:
        required = ACTION_PERMISSION.get(action)
        if scope.kind != "offering" or permissions is None or required not in permissions or context.role.scope != "offering":
            _deny(403, "permission_denied")
        if required in ASSESSMENT_PERMISSIONS:
            _deny(403, "assessment_stage_unavailable")
    return AuthorizationSnapshot(actor.username, actor.role, policy.source_teacher_id, scope,
                                 teaching, bool(learning), permissions or frozenset(),
                                 context.role.scope if permissions is not None else None,
                                 context.role.id if permissions is not None else None,
                                 context.role.revision if permissions is not None else None,
                                 enrollment.id if learning else None, enrollment.revision if learning else None,
                                 policy.learner_ceiling if permissions is not None else frozenset(),
                                 policy.digest, policy.generation, at)


def authorize_locked_action(context: LockedContext, policy: TeachingPolicy, action: TeachingAction, at: datetime) -> AuthorizationSnapshot:
    """Evaluate rows/policy at the final post-lock time; no SQL or cached grant.

    The future orchestrator owns row refreshing, all locks and generation capture.
    This pure evaluator is not proof of live lock/isolation behavior.
    """
    if not isinstance(context, LockedContext):
        _deny(503, "lock_orchestration_required")
    return _evaluate(context, policy, action, at)


def _policy(context, inputs):
    source_id = context.course.source_teacher_id if context.course is not None else context.actor_account.username
    return read_teaching_policy(inputs, source_id, actor_id=context.actor_account.username)


def authorize_action(session: Session, actor_id: str, action: TeachingAction, scope: ScopeRef, object_ref: ObjectRef | None = None, *, lock: bool = False) -> AuthorizationSnapshot:
    if lock:
        _deny(503, "lock_orchestration_required")
    action = _action(action)
    actor, initial = _begin_read(session, actor_id)
    if not isinstance(scope, ScopeRef) or scope.institution_id != initial.institution_id:
        _deny(404, "scope_not_found")
    _validate_action_scope(action, scope)
    context = _load_context(session, actor, scope, object_ref)
    if action == TeachingAction.READ_COURSE and context.course.source_teacher_id != actor.username:
        contexts = _offering_contexts(session, actor, initial, course_id=scope.id)
        inputs, at = _final_inputs(session, initial), utcnow()
        _object_scope(context)
        visible = _visible(contexts, inputs, at, "all")
        if not visible:
            _deny(404, "scope_not_found")
        return replace(visible[0][1], scope=scope)
    inputs = _final_inputs(session, initial)
    return _evaluate(context, _policy(context, inputs), action, utcnow())


def authorize_roster_target(snapshot: AuthorizationSnapshot, target_subject_id: str, *, withdrawal: bool = False) -> None:
    """Within-transaction target ceiling check; not a reusable user credential.

    Cleanup can withdraw source-revoked historical rows. Task5 still resolves
    existing rows/current target accounts and validates commands under locks.
    """
    if not exact_identifier(target_subject_id):
        _deny(422, "invalid_subject")
    if Permission.ROSTER_MANAGE not in snapshot.permissions or snapshot.role_scope != "offering":
        _deny(403, "permission_denied")
    if not withdrawal and target_subject_id not in snapshot.learner_ceiling:
        _deny(403, "target_outside_trusted_ceiling")


def authorize_receipt_access(session: Session, actor_id: str, receipt: WriteReceipt) -> AuthorizationSnapshot:
    """Current-rights helper only. No replay, receipt mutation or lock protocol.

    Reload the supplied persisted ID and filter the original actor and scope;
    never treat caller-edited receipt fields or its historical digest as authority.
    """
    actor = load_current_account(session, actor_id)
    if receipt.id is None:
        _deny(404, "receipt_not_found")
    row = session.query(WriteReceipt).filter(WriteReceipt.id == receipt.id, WriteReceipt.actor_id == actor.username).populate_existing().first()
    if row is None:
        _deny(404, "receipt_not_found")
    try:
        scope = ScopeRef(row.institution_id, row.scope_type, row.scope_id)
    except ValueError:
        _deny(403, "unsupported_receipt_scope")
    return authorize_action(session, actor.username, _action(row.action), scope)


def _offering_contexts(session, actor, inputs, course_id=None):
    institution = inputs.institution_id
    enrolled = session.query(Enrollment.id).filter(Enrollment.institution_id == institution, Enrollment.offering_id == Offering.id, Enrollment.student_id == actor.username).exists()
    granted = session.query(TeachingRole.id).filter(TeachingRole.institution_id == institution, TeachingRole.offering_id == Offering.id, TeachingRole.subject_id == actor.username).exists()
    query = session.query(Offering).join(Course, and_(Course.id == Offering.course_id, Course.institution_id == Offering.institution_id)).filter(Offering.institution_id == institution, or_(Course.source_teacher_id == actor.username, enrolled, granted))
    if course_id is not None:
        query = query.filter(Offering.course_id == course_id)
    rows = query.populate_existing().order_by(Offering.id).all()
    return [_load_context(session, actor, ScopeRef(institution, "offering", row.id)) for row in rows]


def _visible(contexts, inputs, at, membership):
    result = []
    for context in contexts:
        try:
            decision = _evaluate(context, _policy(context, inputs), TeachingAction.READ_OFFERING, at)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            continue
        if membership == "all" or membership == "teaching" and decision.teaching or membership == "learning" and decision.learning:
            result.append((context, decision))
    return result


def _enrollment_dto(row, eligible):
    return EnrollmentDTO(id=row.id, offering_id=row.offering_id, student_id=row.student_id,
                         status=row.status, effective_from=_utc(row.effective_from), effective_until=_utc(row.effective_until), revision=row.revision, access_eligible=eligible)


def _offering_dto(context, decision):
    row = context.offering
    actions = sorted((action for action, permission in ACTION_PERMISSION.items() if permission in decision.permissions and permission not in ASSESSMENT_PERMISSIONS and decision.role_scope == "offering"), key=lambda action: action.value)
    access = OfferingAccessDTO(teaching=decision.teaching, learning=decision.learning,
                               configured_permissions=sorted(decision.permissions, key=lambda permission: permission.value),
                               available_actions=actions, role_scope=decision.role_scope)
    return OfferingDTO(id=row.id, course_id=row.course_id, title=row.title, term=row.term, timezone=row.timezone,
                       state=row.state, revision=row.revision,
                       roster_revision=row.roster_revision if Permission.ROSTER_MANAGE in decision.permissions and decision.role_scope == "offering" else None,
                       created_at=_utc(row.created_at), updated_at=_utc(row.updated_at), archived_at=_utc(row.archived_at),
                       access=access, enrollment=_enrollment_dto(context.enrollment, True) if decision.learning else None)


def _page(items, query, key=lambda item: item.id):
    remaining = [item for item in items if query.cursor is None or key(item) > query.cursor]
    values = remaining[:query.limit]
    return values, key(values[-1]) if len(remaining) > query.limit else None


def list_offerings(session: Session, actor_id: str, query: OfferingQuery | None = None) -> OfferingPageDTO:
    query = query or OfferingQuery()
    actor, initial = _begin_read(session, actor_id)
    contexts = _offering_contexts(session, actor, initial, query.course_id)
    inputs, at = _final_inputs(session, initial), utcnow()
    items = [_offering_dto(context, decision) for context, decision in _visible(contexts, inputs, at, query.membership)]
    values, cursor = _page(items, query)
    return OfferingPageDTO(items=values, next_cursor=cursor, as_of=at)


def _course_dto(row, memberships, count):
    return CourseDTO(id=row.id, institution_id=row.institution_id, source_teacher_id=row.source_teacher_id,
                     title=row.title, code=row.code, description=row.description, timezone=row.timezone,
                     revision=row.revision, created_at=_utc(row.created_at), updated_at=_utc(row.updated_at),
                     memberships=sorted(memberships), visible_offering_count=count)


def _courses(session, actor, initial, membership):
    contexts = _offering_contexts(session, actor, initial)
    owned = session.query(Course).filter(Course.institution_id == initial.institution_id, Course.source_teacher_id == actor.username).populate_existing().order_by(Course.id).all()
    inputs, at = _final_inputs(session, initial), utcnow()
    visible = _visible(contexts, inputs, at, membership)
    data = {}
    for context, decision in visible:
        row, modes, count = data.get(context.course.id, (context.course, set(), 0))
        if decision.teaching: modes.add("teaching")
        if decision.learning: modes.add("learning")
        data[row.id] = row, modes, count+1
    if membership != "learning":
        for row in owned:
            context = AuthorizationContext(actor, ScopeRef(inputs.institution_id, "course", row.id), actor, row)
            policy = _policy(context, inputs)
            if actor.role == "teacher" and _source_live(context, policy):
                existing = data.get(row.id, (row, set(), 0))
                data[row.id] = row, existing[1] | {"teaching"}, existing[2]
    return [_course_dto(row, modes, count) for id_, (row, modes, count) in sorted(data.items())], at


def list_courses(session: Session, actor_id: str, query: CourseQuery | None = None) -> CoursePageDTO:
    query = query or CourseQuery()
    actor, initial = _begin_read(session, actor_id)
    items, at = _courses(session, actor, initial, query.membership)
    values, cursor = _page(items, query)
    return CoursePageDTO(items=values, next_cursor=cursor, as_of=at)


def get_course(session: Session, actor_id: str, course_id: str) -> CourseDTO:
    actor, initial = _begin_read(session, actor_id)
    if not exact_identifier(course_id, 36):
        _deny(404, "scope_not_found")
    items, _ = _courses(session, actor, initial, "all")
    for item in items:
        if item.id == course_id:
            return item
    _deny(404, "scope_not_found")


def _detail(session, actor_id, offering_id, action):
    actor, initial = _begin_read(session, actor_id)
    if not exact_identifier(offering_id, 36):
        _deny(404, "scope_not_found")
    context = _load_context(session, actor, ScopeRef(initial.institution_id, "offering", offering_id))
    inputs, at = _final_inputs(session, initial), utcnow()
    decision = _evaluate(context, _policy(context, inputs), action, at)
    return context, inputs, decision


def get_offering(session: Session, actor_id: str, offering_id: str) -> OfferingDTO:
    context, _, decision = _detail(session, actor_id, offering_id, TeachingAction.READ_OFFERING)
    return _offering_dto(context, decision)


def get_own_enrollment(session: Session, actor_id: str, offering_id: str) -> EnrollmentDTO:
    context, _, _ = _detail(session, actor_id, offering_id, TeachingAction.READ_ENROLLMENT)
    return _enrollment_dto(context.enrollment, True)


def get_roster(session: Session, actor_id: str, offering_id: str, query: PageQuery | None = None) -> RosterPageDTO:
    query = query or PageQuery()
    actor, initial = _begin_read(session, actor_id)
    context = _load_context(session, actor, ScopeRef(initial.institution_id, "offering", offering_id))
    rows = session.query(Enrollment).filter(Enrollment.institution_id == initial.institution_id, Enrollment.offering_id == offering_id).populate_existing().order_by(Enrollment.id).all()
    accounts = {row.student_id: _optional_account(session, row.student_id) for row in rows}
    inputs, at = _final_inputs(session, initial), utcnow()
    policy = _policy(context, inputs)
    _evaluate(context, policy, TeachingAction.ROSTER_MANAGE, at)
    values, cursor = _page(rows, query)
    items = []
    for row in values:
        available = row.source_kind == "deployment_roster" and row.source_teacher_id == policy.source_teacher_id and row.student_id in policy.source_roster.members
        state = "source_revoked" if not available else "account_unavailable" if accounts[row.student_id] is None else "available"
        eligible = available and accounts[row.student_id] is not None and context.offering.state in {"active", "archived"} and _active(row, at)
        items.append(RosterEntryDTO(**_enrollment_dto(row, bool(eligible)).model_dump(), source_availability=state))
    return RosterPageDTO(items=items, next_cursor=cursor, as_of=at)


def get_roles(session: Session, actor_id: str, offering_id: str) -> RoleListDTO:
    actor, initial = _begin_read(session, actor_id)
    context = _load_context(session, actor, ScopeRef(initial.institution_id, "offering", offering_id))
    rows = session.query(TeachingRole).filter(TeachingRole.institution_id == initial.institution_id, TeachingRole.offering_id == offering_id).populate_existing().order_by(TeachingRole.id).all()
    accounts = {row.subject_id: _optional_account(session, row.subject_id) for row in rows}
    inputs, at = _final_inputs(session, initial), utcnow()
    policy = _policy(context, inputs)
    _evaluate(context, policy, TeachingAction.ROLES_MANAGE, at)
    items = []
    for row in rows:
        target_policy = read_teaching_policy(inputs, context.course.source_teacher_id, actor_id=actor.username, target_subject_id=row.subject_id)
        effective, reason = _role_effect(row, accounts[row.subject_id], target_policy.target_ceiling, at)
        configured = _permissions(row)
        items.append(RoleDTO(id=row.id, subject_id=row.subject_id, granted_account_role=row.granted_account_role, label=row.label,
                             configured_permissions=sorted(configured or (), key=lambda p: p.value), scope=row.scope,
                             status=row.status, effective_from=_utc(row.effective_from), effective_until=_utc(row.effective_until), revision=row.revision,
                             effective_permissions=sorted(effective or (), key=lambda p: p.value), effective_scope=row.scope if effective is not None else None, reason=reason))
    return RoleListDTO(items=items, as_of=at)


def get_capabilities(session: Session, actor_id: str) -> CapabilityDTO:
    actor = load_current_account(session, actor_id)
    inputs = _inputs(session)
    reason = _availability(inputs)
    if reason is None:
        try:
            require_teaching_schema(session)
        except TeachingSchemaError as exc:
            reason = exc.code
    policy = read_teaching_policy(inputs, actor.username, actor_id=actor.username)
    available = reason is None
    def stage(configured, dependency):
        return StageDTO(configured=configured, installed=False, available=False,
                        reason="feature_disabled" if not configured else "dependency_disabled" if not dependency else "stage_unavailable")
    return CapabilityDTO(account_role=actor.role, configured=inputs.enabled, available=available,
                         can_create_course=available and actor.role == "teacher" and policy.source_roster.valid,
                         reason=reason or "available",
                         assignments=stage(inputs.assignments_enabled, available),
                         feedback=stage(inputs.feedback_enabled, available and inputs.assignments_enabled),
                         revisions=stage(inputs.revisions_enabled, available and inputs.assignments_enabled and inputs.feedback_enabled))


def _preview_read(session, actor_id, offering_id, preview_id):
    actor, initial = _begin_read(session, actor_id)
    context = _load_context(session, actor, ScopeRef(initial.institution_id, "offering", offering_id))
    row = session.query(RosterPreview).filter(RosterPreview.id == preview_id, RosterPreview.institution_id == initial.institution_id,
                                             RosterPreview.offering_id == offering_id, RosterPreview.actor_id == actor.username).populate_existing().first()
    inputs, at = _final_inputs(session, initial), utcnow()
    _evaluate(context, _policy(context, inputs), TeachingAction.ROSTER_MANAGE, at)
    if row is None:
        _deny(404, "preview_not_found")
    sets = {}
    for kind in ("target", "add", "keep", "update", "withdraw"):
        values = getattr(row, f"{kind}_ids")
        if not isinstance(values, list) or not all(exact_identifier(value) for value in values) or len(set(values)) != len(values):
            _deny(503, "preview_incompatible")
        sets[kind] = sorted(values)
    if row.withdrawals_count != len(sets["withdraw"]):
        _deny(503, "preview_incompatible")
    return row, sets, at


def get_roster_preview(session: Session, actor_id: str, offering_id: str, preview_id: str) -> RosterPreviewDTO:
    row, sets, at = _preview_read(session, actor_id, offering_id, preview_id)
    # Project known machine-readable validation fields, never raw command/config.
    issues = []
    for issue in row.validation_issues:
        if not isinstance(issue, dict) or not isinstance(issue.get("code"), str):
            _deny(503, "preview_incompatible")
        issues.append(PreviewIssueDTO(code=issue["code"], subject_id=issue.get("subject_id")))
    return RosterPreviewDTO(id=row.id, offering_id=row.offering_id, mode=row.mode,
                            expected_roster_revision=row.expected_roster_revision, offering_revision=row.offering_revision,
                            target_count=len(sets["target"]), add_count=len(sets["add"]), keep_count=len(sets["keep"]), update_count=len(sets["update"]),
                            withdrawals_count=len(sets["withdraw"]), target_digest=row.target_digest, withdrawals_digest=row.withdrawals_digest,
                            withdraw_sample=sets["withdraw"][:20], validation_issues=issues, can_apply=row.can_apply,
                            expired=at >= _utc(row.expires_at), created_at=_utc(row.created_at), expires_at=_utc(row.expires_at))


def get_roster_preview_changes(session: Session, actor_id: str, offering_id: str, preview_id: str, query: PreviewChangesQuery) -> PreviewChangesDTO:
    row, sets, at = _preview_read(session, actor_id, offering_id, preview_id)
    values, cursor = _page(sets[query.kind], query, key=lambda value: value)
    return PreviewChangesDTO(kind=query.kind, items=values, total_count=len(sets[query.kind]), next_cursor=cursor, as_of=at)
