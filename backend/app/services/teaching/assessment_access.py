"""Current B2 object authority over a complete typed, server-loaded footprint."""
from dataclasses import replace

from fastapi import HTTPException

from app.models.teaching import Offering
from app.models.teaching_assessment import Assignment, AssignmentVersion, ReleasePreview, Release, Submission
from app.schemas.teaching_assessment import PrivateSpecCommand
from app.services.teaching import access
from app.services.teaching.assessment_schema import require_assessment_schema
from app.services.teaching.schema import TeachingSchemaError
from app.services.teaching.types import (
    ASSESSMENT_ACTIONS, ASSESSMENT_WRITE_ACTIONS, TeachingAction, Permission, ScopeRef, ObjectRef, LockedContext, exact_identifier,
)


def _error(status,reason):
    raise HTTPException(status,reason)


def require_assessment_available(session, inputs):
    if not inputs.assignments_enabled: _error(503,'assessment_disabled')
    try: require_assessment_schema(session)
    except TeachingSchemaError as exc: _error(503,exc.code)


def resolve_assessment_object(session, actor_id, kind, object_id):
    actor,inputs=access._begin_read(session,actor_id)
    require_assessment_available(session,inputs)
    if not exact_identifier(object_id,36): _error(404,'not_found')
    if kind=='assignment': query=session.query(Assignment)
    elif kind=='version': query=session.query(AssignmentVersion)
    elif kind=='release_preview': query=session.query(ReleasePreview)
    elif kind=='release': query=session.query(Release)
    elif kind=='submission': query=session.query(Submission)
    else: _error(404,'not_found')
    model=query.column_descriptions[0]['entity']
    row=query.filter(model.id==object_id,model.institution_id==inputs.institution_id).populate_existing().first()
    if row is None or row.id!=object_id or row.institution_id!=inputs.institution_id: _error(404,'not_found')
    scope=ScopeRef(row.institution_id,'offering',row.offering_id)
    context=access._load_context(session,actor,scope)
    try: access._evaluate(context,access._policy(context,inputs),TeachingAction.READ_OFFERING,access.utcnow())
    except HTTPException as exc:
        if exc.status_code in {401,403,404}: _error(404,'not_found')
        raise
    # Resolution never returns content or permission. The read path locks and
    # rechecks the full chain and current actor before any projection is made.
    return scope,ObjectRef(kind,row.id,row.institution_id,context.course.id,row.offering_id)


def authorize_assessment_read(session,actor_id,action,object_ref):
    from app.services.teaching.writes import _lock_context
    if action not in ASSESSMENT_ACTIONS or action in ASSESSMENT_WRITE_ACTIONS: _error(403,'permission_denied')
    if not isinstance(object_ref,ObjectRef) or object_ref.offering_id is None: _error(404,'not_found')
    context=_lock_context(session,actor_id,action,ScopeRef(object_ref.institution_id,'offering',object_ref.offering_id),object_ref=object_ref)
    return context.authorization,context.assessment


def _chain(context):
    rows=context.assessment; spec=context.lock_plan.assessment
    if rows is None or spec is None or context.scope.kind!='offering': _error(503,'invalid_lock_footprint')
    assignment=rows.assignment; version=rows.version; release=rows.release; preview=rows.release_preview
    for row in (assignment,rows.draft_private,version,rows.private_spec,preview,release,*rows.recipients,rows.head,rows.parent_submission,rows.target_submission):
        if row is None: continue
        if row.institution_id!=context.scope.institution_id or row.offering_id!=context.scope.id: _error(404,'not_found')
        if hasattr(row,'assignment_id') and (assignment is None or row.assignment_id!=assignment.id): _error(404,'not_found')
        if hasattr(row,'version_id') and (version is None or row.version_id!=version.id): _error(404,'not_found')
        if hasattr(row,'release_id') and (release is None or row.release_id!=release.id): _error(404,'not_found')
    for identifier,row in ((spec.assignment_id,assignment),(spec.version_id,version),(spec.release_preview_id,preview),(spec.release_id,release)):
        if identifier is not None and (row is None or row.id!=identifier): _error(404,'not_found')
    ref=context.object_ref
    if ref is not None:
        expected={'assignment':assignment,'version':version,'release_preview':preview,'release':release,'submission':rows.target_submission,'offering':context.offering}.get(ref.kind)
        if (expected is None or expected.id!=ref.id or ref.institution_id!=context.scope.institution_id
                or ref.course_id!=context.course.id or ref.offering_id!=context.offering.id): _error(404,'not_found')
    for row in (rows.head,rows.parent_submission,rows.target_submission):
        if row is not None and row.student_id!=spec.student_id: _error(404,'not_found')
    return rows


def _private_nonempty(row,attribute):
    if row is None: _error(503,'invalid_assessment_state')
    try: spec=PrivateSpecCommand.model_validate(getattr(row,attribute))
    except ValueError: _error(503,'invalid_assessment_state')
    return bool(spec.answer_text or spec.private_test_notes)


def authorize_assessment_locked(context,policy,action,at):
    if not isinstance(context,LockedContext) or action not in ASSESSMENT_ACTIONS: _error(503,'lock_orchestration_required')
    if not policy.inputs.assignments_enabled: _error(503,'assessment_disabled')
    rows=_chain(context)
    expected_kinds = {
        TeachingAction.ASSIGNMENT_READ: {'assignment'},
        TeachingAction.ASSIGNMENT_LIST: {'offering'},
        TeachingAction.ASSIGNMENT_VERSIONS_LIST: {'assignment'},
        TeachingAction.ASSIGNMENT_VERSION_READ: {'version'},
        TeachingAction.ASSIGNMENT_PRIVATE_READ: {'assignment','version'},
        TeachingAction.RELEASE_READ: {'release'},
        TeachingAction.RELEASE_PREVIEW_READ: {'release_preview'},
        TeachingAction.SUBMISSION_READ: {'submission'},
        TeachingAction.SUBMISSION_LIST: {'release'},
    }
    if action in expected_kinds and (context.object_ref is None or context.object_ref.kind not in expected_kinds[action]):
        _error(404,'not_found')
    if action not in {TeachingAction.ASSIGNMENT_CREATE,TeachingAction.ASSIGNMENT_LIST} and rows.assignment is None:
        _error(404,'not_found')
    if action in {TeachingAction.RELEASE_PREVIEW,TeachingAction.RELEASE_CREATE,TeachingAction.ASSIGNMENT_VERSION_READ} and rows.version is None:
        _error(404,'not_found')
    if action in {TeachingAction.RELEASE_READ,TeachingAction.SUBMISSION_CREATE,TeachingAction.SUBMISSION_READ,TeachingAction.SUBMISSION_LIST} and rows.release is None:
        _error(404,'not_found')
    # Reuse exact B1 current-account/source/role/enrollment semantics without
    # granting reserved AUTHOR/RELEASE generic entry points.
    decision=access._evaluate(replace(context,object_ref=None),policy,TeachingAction.READ_OFFERING,at)
    permissions=decision.permissions if decision.role_scope=='offering' else frozenset()
    actor=decision.actor_id
    recipient=any(row.student_id==actor and rows.release is not None and row.release_id==rows.release.id for row in rows.recipients)
    learning=decision.learning and recipient
    recovery=context.assessment_receipt is not None and context.assessment_receipt.mode=='existing'
    private=False
    if action in {TeachingAction.ASSIGNMENT_CREATE,TeachingAction.ASSIGNMENT_UPDATE,TeachingAction.ASSIGNMENT_READ}:
        allowed=Permission.AUTHOR in permissions
    elif action==TeachingAction.ASSIGNMENT_PRIVATE_UPDATE:
        allowed={Permission.AUTHOR,Permission.PRIVATE_SPEC_VIEW}<=permissions; private=True
    elif action==TeachingAction.ASSIGNMENT_FREEZE:
        private=_private_nonempty(rows.private_spec,'private_spec') if recovery else _private_nonempty(rows.draft_private,'private_draft')
        allowed=Permission.AUTHOR in permissions and (not private or Permission.PRIVATE_SPEC_VIEW in permissions)
    elif action in {TeachingAction.ASSIGNMENT_LIST,TeachingAction.ASSIGNMENT_VERSIONS_LIST,TeachingAction.ASSIGNMENT_VERSION_READ}:
        allowed=bool(permissions & {Permission.AUTHOR,Permission.RELEASE})
    elif action==TeachingAction.ASSIGNMENT_PRIVATE_READ:
        private=True; allowed=Permission.PRIVATE_SPEC_VIEW in permissions
    elif action in {TeachingAction.RELEASE_PREVIEW,TeachingAction.RELEASE_CREATE,TeachingAction.RELEASE_PREVIEW_READ}:
        allowed=Permission.RELEASE in permissions
        if rows.release_preview is not None and (action in {TeachingAction.RELEASE_CREATE,TeachingAction.RELEASE_PREVIEW_READ} or recovery and action==TeachingAction.RELEASE_PREVIEW):
            allowed=allowed and rows.release_preview.actor_id==actor
        if action==TeachingAction.RELEASE_PREVIEW_READ:
            from app.services.teaching.assessment_writes import _saved_audience
            allowed=allowed and all(value.student_id in decision.learner_ceiling for value in _saved_audience(rows.release_preview))
    elif action==TeachingAction.RELEASE_READ:
        allowed=learning or bool(permissions & {Permission.RELEASE,Permission.SUBMISSION_VIEW})
    elif action==TeachingAction.SUBMISSION_CREATE:
        allowed=learning and context.lock_plan.assessment.student_id==actor
        if recovery: allowed=allowed and rows.target_submission is not None and rows.target_submission.student_id==actor
    elif action in {TeachingAction.SUBMISSION_READ,TeachingAction.SUBMISSION_LIST}:
        target=rows.target_submission.student_id if rows.target_submission is not None else context.lock_plan.assessment.student_id
        allowed=(learning and (target is None or target==actor)) or Permission.SUBMISSION_VIEW in permissions and (target is None or target in decision.learner_ceiling)
    else: allowed=False
    if not allowed:
        _error(404 if not decision.teaching and not decision.learning or action==TeachingAction.SUBMISSION_CREATE or action==TeachingAction.RELEASE_READ and not permissions else 403,'permission_denied')
    if private:
        # Original frozen private status for freeze recovery; mutable private
        # draft status cannot reinterpret an old acceptance's target.
        frozen=rows.version is not None and (action==TeachingAction.ASSIGNMENT_PRIVATE_READ or recovery)
        if frozen and recipient or not frozen and access._active(context.enrollment,at): _error(403,'private_conflict')
    return decision
