"""Full-audience previews, immutable releases and current-authority reads.

The accepted closed engine owns locks, final time, append identities, receipts
and events. This module neither commits nor enables production writes.
"""
from collections.abc import Mapping
from datetime import timedelta
from typing import Literal

from fastapi import HTTPException
from pydantic import ValidationError

from app.models.teaching_assessment import ReleasePreview, Release, ReleaseRecipient, SubmissionHead
from app.schemas import teaching_assessment as dto
from app.services.teaching import access, assessment_access
from app.services.teaching.assessment_pagination import decode_cursor, encode_cursor
from app.services.teaching.assessment_types import ReleasePreviewCreateShape, ReleaseCreateShape
from app.services.teaching.assessment_writes import (
    ASSESSMENT_RESULTS, assessment_lock_plan, collect_assessment_spec, _plain, _digest, _saved_audience,
)
from app.services.teaching.types import MutationResult, Permission, ScopeRef, TeachingAction, exact_identifier
from app.services.teaching.writes import make_write_intent, locked_authorization

_PURPOSES = {
    'preview':(TeachingAction.RELEASE_PREVIEW,dto.ReleasePreviewCommand,ReleasePreviewCreateShape),
    'confirm':(TeachingAction.RELEASE_CREATE,dto.ConfirmReleaseCommand,ReleaseCreateShape),
}
_BOUND_FIELDS = ('assignment_id','version_id','public_spec_hash','recipient_count','recipient_digest',
    'due_at','timezone','late_policy','policy_digest')


def _error(status,reason):
    raise HTTPException(status,reason)


def _command(command,model):
    if isinstance(command,model):
        return command.model_dump()
    if not isinstance(command,Mapping):
        _error(422,'validation_error')
    try:
        return model.model_validate(_plain(command)).model_dump()
    except (ValidationError,ValueError,TypeError,RecursionError):
        _error(422,'validation_error')


def _saved(value,model):
    try:
        return model.model_validate(_plain(value))
    except (ValidationError,ValueError,TypeError,RecursionError):
        _error(503,'invalid_assessment_state')


def _version(row):
    public = _saved(row.public_spec,dto.PublicSpec)
    if row.public_spec_hash != _digest(public.model_dump()):
        _error(503,'invalid_assessment_state')
    return _saved(dict(id=row.id,assignment_id=row.assignment_id,offering_id=row.offering_id,
        version_number=row.version_number,source_draft_revision=row.source_draft_revision,
        public_spec=public,public_spec_hash=row.public_spec_hash,frozen_at=access._utc(row.frozen_at)),
        dto.AssignmentVersionDTO)


def _bound(row):
    fields = {field:getattr(row,field) for field in _BOUND_FIELDS}
    fields['due_at'] = access._utc(row.due_at)
    return fields


def _check_policy(fields):
    if fields['policy_digest'] != _digest({'version':1,'due_at':fields['due_at'],
            'timezone':fields['timezone'],'late_policy':fields['late_policy']}):
        _error(503,'invalid_assessment_state')


def _preview_values(row,version):
    values = _saved(dict(**_bound(row),preview_id=row.id,expires_at=access._utc(row.expires_at),
        accepted_at=access._utc(row.created_at)),dto.ReleasePreviewAcceptanceDTO).model_dump()
    _check_policy(values)
    if (values['public_spec_hash'] != _version(version).public_spec_hash
            or values['expires_at'] != values['accepted_at']+timedelta(minutes=15)):
        _error(503,'invalid_assessment_state')
    return values


class _ReleaseOperation:
    def __init__(self,purpose):
        self.purpose = purpose
        self.action, _, self.shape_type = _PURPOSES[purpose]

    def collect_locks(self,session,intent,roots,preview_footprint=None):
        if intent.action != self.action or preview_footprint is not None:
            _error(503,'invalid_lock_footprint')
        return assessment_lock_plan(roots,intent,collect_assessment_spec(session,intent,roots))

    def validate_new(self,context,command,at):
        # Current eligibility, lifecycle, deadline/expiry and exact bindings
        # have already been checked by the engine, using the one final clock.
        if type(context.assessment_shape) is not self.shape_type:
            _error(503,'invalid_lock_footprint')
        _version(context.assessment.version)
        if self.purpose == 'confirm':
            _preview_values(context.assessment.release_preview,context.assessment.version)

    def apply_new(self,context,command,at):
        shape, rows = context.assessment_shape, context.assessment
        scope = {'institution_id':shape.institution_id,'offering_id':shape.offering_id}
        actor = context.authorization.actor_id
        if self.purpose == 'preview':
            audience = [dict(student_id=member.student_id,enrollment_id=member.enrollment_id,
                enrollment_revision=member.enrollment_revision) for member in shape.audience]
            due = dto.parse_assessment_utc(command['due_at'])
            timezone = context.offering.timezone
            fields = dict(assignment_id=shape.assignment_id,version_id=shape.version_id,
                public_spec_hash=rows.version.public_spec_hash,recipient_count=len(audience),
                recipient_digest=_digest({'version':1,'recipients':audience}),due_at=due,timezone=timezone,
                late_policy='reject',policy_digest=_digest({'version':1,'due_at':due,'timezone':timezone,'late_policy':'reject'}))
            expires = at+timedelta(minutes=15)
            original = dto.ReleasePreviewAcceptanceDTO(**fields,preview_id=shape.preview_id,
                expires_at=expires,accepted_at=at).model_dump()
            context.session.add(ReleasePreview(id=shape.preview_id,**scope,**fields,
                actor_id=actor,actor_role_id=context.authorization.role_id,actor_role_revision=context.authorization.role_revision,
                offering_revision=context.offering.revision,roster_revision=context.offering.roster_revision,
                source_policy_digest=context.policy.digest,recipient_snapshot=audience,created_at=at,expires_at=expires))
        else:
            fields = _bound(rows.release_preview)
            original = dto.ReleaseAcceptanceDTO(**fields,release_id=shape.release_id,released_at=at).model_dump()
            context.session.add(Release(id=shape.release_id,**scope,**fields,preview_id=shape.preview_id,
                released_by=actor,released_at=at))
            for member in shape.audience:
                identity = dict(release_id=shape.release_id,**scope,version_id=shape.version_id,student_id=member.student_id)
                context.session.add(ReleaseRecipient(**identity,enrollment_id=member.enrollment_id,
                    enrollment_revision_at_release=member.enrollment_revision,accepted_policy_digest=context.policy.digest))
                context.session.add(SubmissionHead(**identity,submission_id=None,revision=0))
        contract = ASSESSMENT_RESULTS[self.action]
        effects = {field:original[field] for field in contract.effect_fields}
        return MutationResult(contract.result_type,original[contract.id_field],original,
            contract.revision_kind,0,1,effects,201)


def prepare_release_write(session,actor_id,assignment_id,purpose:Literal['preview','confirm'],command,key):
    """Both intents hash the exact assignment route and original submitted body."""
    if purpose not in _PURPOSES or not exact_identifier(assignment_id,36):
        _error(422,'validation_error')
    action, model, _ = _PURPOSES[purpose]
    payload = _command(command,model)
    # Do not resolve the body audience/version/preview here: the engine first
    # discovers an existing receipt and authorizes its original persisted target.
    scope, _ = assessment_access.resolve_assessment_object(session,actor_id,'assignment',assignment_id)
    return make_write_intent(actor_id,action,scope,assignment_id,key,payload),_ReleaseOperation(purpose)


def _read(session,actor_id,action,kind,identifier):
    _, ref = assessment_access.resolve_assessment_object(session,actor_id,kind,identifier)
    return assessment_access.authorize_assessment_read(session,actor_id,action,ref)


def _query(query,model=dto.AssessmentPageQuery):
    try:
        return model.model_validate(query)
    except (ValidationError,ValueError,TypeError):
        _error(422,'validation_error')


def _preview_read(session,actor_id,assignment_id,preview_id):
    if not exact_identifier(assignment_id,36):
        _error(404,'not_found')
    decision, rows = _read(session,actor_id,TeachingAction.RELEASE_PREVIEW_READ,'release_preview',preview_id)
    if rows.assignment.id != assignment_id:
        _error(404,'not_found')
    _preview_values(rows.release_preview,rows.version)
    return decision, rows.release_preview


def _preview_page(preview,decision,query):
    position = decode_cursor(query.cursor,'preview_recipients',preview.id,decision.actor_id)
    audience = [member.student_id for member in _saved_audience(preview)]
    if position is not None:
        audience = [subject for subject in audience if subject>position['after_student_id']]
    items = audience[:query.limit]
    cursor = encode_cursor('preview_recipients',preview.id,decision.actor_id,
        after_student_id=items[-1]) if len(audience)>query.limit else None
    return dto.RecipientPageDTO(items=items,next_cursor=cursor,as_of=decision.checked_at)


def get_release_preview(session,actor_id,assignment_id,preview_id):
    decision, row = _preview_read(session,actor_id,assignment_id,preview_id)
    return dto.ReleasePreviewDTO(id=row.id,**_bound(row),expires_at=access._utc(row.expires_at),
        first_recipient_page=_preview_page(row,decision,dto.RecipientPageQuery(limit=100)))


def list_release_preview_recipients(session,actor_id,assignment_id,preview_id,query:dto.RecipientPageQuery):
    query = _query(query,dto.RecipientPageQuery)
    decision, row = _preview_read(session,actor_id,assignment_id,preview_id)
    return _preview_page(row,decision,query)


def _teacher(decision):
    return decision.role_scope=='offering' and bool(decision.permissions & {Permission.RELEASE,Permission.SUBMISSION_VIEW})


def _release_projection(decision,rows):
    row = rows.release
    values = _saved(dict(**_bound(row),release_id=row.id,released_at=access._utc(row.released_at)),
        dto.ReleaseAcceptanceDTO).model_dump()
    _check_policy(values)
    preview = _preview_values(rows.release_preview,rows.version)
    if any(values[field] != preview[field] for field in _BOUND_FIELDS):
        _error(503,'invalid_assessment_state')
    own = decision.learning and any(member.student_id==decision.actor_id for member in rows.recipients)
    fields = dict(id=row.id,assignment_id=row.assignment_id,version=_version(rows.version),
        due_at=values['due_at'],timezone=row.timezone,late_policy=row.late_policy,released_at=values['released_at'])
    if own:
        return dto.ReleaseDTO(**fields)
    if not _teacher(decision):
        _error(403,'permission_denied')
    return dto.ReleaseManagementDTO(**fields,recipient_count=row.recipient_count,recipient_digest=row.recipient_digest)


def get_release(session,actor_id,release_id):
    decision, rows = _read(session,actor_id,TeachingAction.RELEASE_READ,'release',release_id)
    return _release_projection(decision,rows)


def _offering_authority(session,actor_id,offering_id):
    _, inputs = access._begin_read(session,actor_id)
    assessment_access.require_assessment_available(session,inputs)
    if not exact_identifier(offering_id,36):
        _error(404,'not_found')
    decision = locked_authorization(session,actor_id,TeachingAction.READ_OFFERING,
        ScopeRef(inputs.institution_id,'offering',offering_id))
    if not _teacher(decision) and not decision.learning:
        _error(403,'permission_denied')
    return decision


def list_releases(session,actor_id,offering_id,query:dto.AssessmentPageQuery):
    query = _query(query)
    decision = _offering_authority(session,actor_id,offering_id)
    position = decode_cursor(query.cursor,'releases',offering_id,decision.actor_id)
    selection = session.query(Release).filter(Release.institution_id==decision.scope.institution_id,
        Release.offering_id==offering_id)
    if not _teacher(decision):
        selection = selection.join(ReleaseRecipient,(ReleaseRecipient.release_id==Release.id)&
            (ReleaseRecipient.version_id==Release.version_id)&(ReleaseRecipient.institution_id==Release.institution_id)&
            (ReleaseRecipient.offering_id==Release.offering_id)).filter(ReleaseRecipient.student_id==decision.actor_id)
    if position is not None:
        selection = selection.filter(Release.id>position['after_id'])
    rows = selection.populate_existing().order_by(Release.id).limit(query.limit+1).all()
    items = [get_release(session,decision.actor_id,row.id) for row in rows[:query.limit]]
    cursor = encode_cursor('releases',offering_id,decision.actor_id,after_id=items[-1].id) if len(rows)>query.limit else None
    return dto.ReleasePageDTO(items=items,next_cursor=cursor,as_of=decision.checked_at)


def list_historical_recipients(session,actor_id,release_id,query:dto.RecipientPageQuery):
    query = _query(query,dto.RecipientPageQuery)
    decision, rows = _read(session,actor_id,TeachingAction.RELEASE_READ,'release',release_id)
    if not _teacher(decision):
        _error(403,'permission_denied')
    _release_projection(decision,rows)
    position = decode_cursor(query.cursor,'historical_recipients',release_id,decision.actor_id)
    selection = session.query(ReleaseRecipient).filter(ReleaseRecipient.institution_id==decision.scope.institution_id,
        ReleaseRecipient.offering_id==decision.scope.id,ReleaseRecipient.release_id==rows.release.id,
        ReleaseRecipient.version_id==rows.version.id,ReleaseRecipient.student_id.in_(sorted(decision.learner_ceiling)))
    # Count the authorized historical subset before applying cursor position;
    # neither this page nor its count substitutes for the complete snapshot.
    count = selection.count()
    if position is not None:
        selection = selection.filter(ReleaseRecipient.student_id>position['after_student_id'])
    recipients = selection.populate_existing().order_by(ReleaseRecipient.student_id).limit(query.limit+1).all()
    items = [row.student_id for row in recipients[:query.limit]]
    cursor = encode_cursor('historical_recipients',release_id,decision.actor_id,
        after_student_id=items[-1]) if len(recipients)>query.limit else None
    return dto.HistoricalRecipientPageDTO(items=items,next_cursor=cursor,as_of=decision.checked_at,
        authorized_recipient_count=count)
