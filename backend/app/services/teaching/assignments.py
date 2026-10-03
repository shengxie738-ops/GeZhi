"""Task3 draft, private snapshot, immutable freeze and teacher rediscovery.

The accepted engine owns current authority, finite locks, append identities,
final time, receipts and events. Services never commit or activate B2 writes.
"""
from collections.abc import Mapping
from typing import Literal

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func

from app.models.teaching_assessment import Assignment, AssignmentDraftPrivate, AssignmentVersion, PrivateSpec
from app.schemas import teaching_assessment as dto
from app.services.teaching import access, assessment_access
from app.services.teaching.assessment_pagination import decode_cursor, encode_cursor
from app.services.teaching.assessment_types import (
    AssignmentCreateShape, AssignmentUpdateShape, PrivateDraftUpdateShape, VersionCreateShape,
)
from app.services.teaching.assessment_writes import (
    ASSESSMENT_RESULTS, assessment_lock_plan, collect_assessment_spec, _plain, _digest,
)
from app.services.teaching.types import MutationResult, ObjectRef, Permission, ScopeRef, TeachingAction, exact_identifier
from app.services.teaching.writes import make_write_intent

_PURPOSES = {
    'create':(TeachingAction.ASSIGNMENT_CREATE,dto.CreateAssignmentCommand,AssignmentCreateShape),
    'replace_public':(TeachingAction.ASSIGNMENT_UPDATE,dto.ReplaceAssignmentDraftCommand,AssignmentUpdateShape),
    'replace_private':(TeachingAction.ASSIGNMENT_PRIVATE_UPDATE,dto.ReplacePrivateDraftCommand,PrivateDraftUpdateShape),
    'freeze':(TeachingAction.ASSIGNMENT_FREEZE,dto.FreezeAssignmentCommand,VersionCreateShape),
}


def _error(status,reason):
    raise HTTPException(status,reason)


def _command(command, model):
    if isinstance(command,model):
        return command.model_dump()
    if not isinstance(command,Mapping):
        _error(422,'validation_error')
    try:
        return model.model_validate(_plain(command)).model_dump()
    except (ValidationError,ValueError,TypeError,RecursionError):
        _error(422,'validation_error')


def _saved(value, model):
    try:
        return model.model_validate(_plain(value))
    except (ValidationError,ValueError,TypeError,RecursionError):
        _error(503,'invalid_assessment_state')


class _AssignmentOperation:
    def __init__(self,purpose):
        self.purpose = purpose
        self.action, _, self.shape_type = _PURPOSES[purpose]

    def collect_locks(self,session,intent,roots,preview_footprint=None):
        if intent.action != self.action or preview_footprint is not None:
            _error(503,'invalid_lock_footprint')
        return assessment_lock_plan(roots,intent,collect_assessment_spec(session,intent,roots))

    def validate_new(self,context,command,at):
        # The engine already checks lifecycle/revision/duplicate freeze/current
        # private conflicts before this method. Only loaded saved text is read.
        if type(context.assessment_shape) is not self.shape_type:
            _error(503,'invalid_lock_footprint')
        if self.purpose == 'freeze':
            base = context.pre_mutation['assessment_baseline']
            _saved(base['assignment']['public_draft'],dto.PublicSpec)
            _saved(base['draft_private']['private_draft'],dto.PrivateSpecCommand)

    def apply_new(self,context,command,at):
        shape, rows = context.assessment_shape, context.assessment
        scope = {'institution_id':shape.institution_id,'offering_id':shape.offering_id}
        if self.purpose == 'create':
            context.session.add(Assignment(id=shape.assignment_id,**scope,
                public_draft=_plain(command['public_spec']),draft_revision=1,next_version_number=1,
                created_by=context.authorization.actor_id,created_at=at,updated_at=at))
            context.session.add(AssignmentDraftPrivate(assignment_id=shape.assignment_id,**scope,
                private_draft={'answer_text':'','private_test_notes':''},updated_at=at))
            before = 0
            original = dto.AssignmentAcceptanceDTO(assignment_id=shape.assignment_id,draft_revision=1,accepted_at=at).model_dump()
        elif self.purpose in {'replace_public','replace_private'}:
            before = shape.before_revision
            rows.assignment.draft_revision = before+1
            rows.assignment.updated_at = at
            if self.purpose == 'replace_public':
                rows.assignment.public_draft = _plain(command['public_spec'])
                model = dto.AssignmentAcceptanceDTO
            else:
                rows.draft_private.private_draft = _plain(command['private_spec'])
                rows.draft_private.updated_at = at
                model = dto.PrivateDraftAcceptanceDTO
            original = model(assignment_id=shape.assignment_id,draft_revision=before+1,accepted_at=at).model_dump()
        else:
            base = context.pre_mutation['assessment_baseline']
            public = _plain(base['assignment']['public_draft'])
            private = _plain(base['draft_private']['private_draft'])
            public_hash = _digest(public)
            context.session.add(AssignmentVersion(id=shape.version_id,assignment_id=shape.assignment_id,**scope,
                version_number=shape.version_number,source_draft_revision=shape.source_draft_revision,
                public_spec=public,public_spec_hash=public_hash,frozen_by=context.authorization.actor_id,frozen_at=at))
            context.session.add(PrivateSpec(version_id=shape.version_id,assignment_id=shape.assignment_id,**scope,
                private_spec=private,private_spec_hash=_digest(private)))
            rows.assignment.next_version_number = shape.version_number+1
            before = shape.version_number-1
            original = dto.VersionAcceptanceDTO(assignment_id=shape.assignment_id,version_id=shape.version_id,
                version_number=shape.version_number,source_draft_revision=shape.source_draft_revision,
                public_spec_hash=public_hash,frozen_at=at).model_dump()
        contract = ASSESSMENT_RESULTS[self.action]
        effects = {field:original[field] for field in contract.effect_fields}
        return MutationResult(contract.result_type,original[contract.id_field],original,
            contract.revision_kind,before,before+1,effects,201 if self.purpose in {'create','freeze'} else 200)


def prepare_assignment_write(session,actor_id,offering_id:str|None,assignment_id:str|None,
                             purpose:Literal['create','replace_public','replace_private','freeze'],command,key):
    """Bind an exact route and strict command, without business mutation."""
    if purpose not in _PURPOSES:
        _error(422,'validation_error')
    action, model, _ = _PURPOSES[purpose]
    payload = _command(command,model)
    if purpose == 'create':
        if assignment_id is not None or not exact_identifier(offering_id,36):
            _error(422,'validation_error')
        inputs = access._inputs(session)
        reason = access._availability(inputs)
        if reason:
            _error(503,reason)
        assessment_access.require_assessment_available(session,inputs)
        scope = ScopeRef(inputs.institution_id,'offering',offering_id)
    else:
        if offering_id is not None or not exact_identifier(assignment_id,36):
            _error(422,'validation_error')
        scope, _ = assessment_access.resolve_assessment_object(session,actor_id,'assignment',assignment_id)
    intent = make_write_intent(actor_id,action,scope,assignment_id,key,payload)
    return intent, _AssignmentOperation(purpose)


def _read(session,actor_id,action,kind,identifier):
    _, ref = assessment_access.resolve_assessment_object(session,actor_id,kind,identifier)
    return assessment_access.authorize_assessment_read(session,actor_id,action,ref)


def _version(row):
    public = _saved(row.public_spec,dto.PublicSpec)
    if row.public_spec_hash != _digest(public.model_dump()):
        _error(503,'invalid_assessment_state')
    return dto.AssignmentVersionDTO(id=row.id,assignment_id=row.assignment_id,offering_id=row.offering_id,
        version_number=row.version_number,source_draft_revision=row.source_draft_revision,
        public_spec=public,public_spec_hash=row.public_spec_hash,frozen_at=access._utc(row.frozen_at))


def get_assignment_draft(session,actor_id,assignment_id):
    _, rows = _read(session,actor_id,TeachingAction.ASSIGNMENT_READ,'assignment',assignment_id)
    row = rows.assignment
    return dto.AssignmentDraftDTO(id=row.id,offering_id=row.offering_id,draft_revision=row.draft_revision,
        public_spec=_saved(row.public_draft,dto.PublicSpec),updated_at=access._utc(row.updated_at))


def get_assignment_version(session,actor_id,assignment_id,version_id):
    if not exact_identifier(assignment_id,36):
        _error(404,'not_found')
    _, rows = _read(session,actor_id,TeachingAction.ASSIGNMENT_VERSION_READ,'version',version_id)
    if rows.assignment.id != assignment_id:
        _error(404,'not_found')
    return _version(rows.version)


def get_private_spec(session,actor_id,assignment_id,version_id:str|None):
    if not exact_identifier(assignment_id,36):
        _error(404,'not_found')
    _, rows = _read(session,actor_id,TeachingAction.ASSIGNMENT_PRIVATE_READ,
        'assignment' if version_id is None else 'version',assignment_id if version_id is None else version_id)
    if rows.assignment.id != assignment_id:
        _error(404,'not_found')
    saved = rows.draft_private.private_draft if version_id is None else rows.private_spec.private_spec
    return dto.PrivateSpecDTO(assignment_id=rows.assignment.id,version_id=version_id,
        private_spec=_saved(saved,dto.PrivateSpecCommand))


def _query(query):
    try:
        return dto.AssessmentPageQuery.model_validate(query)
    except (ValidationError,ValueError,TypeError):
        _error(422,'validation_error')


def _catalog_authority(session,actor_id,offering_id):
    actor, inputs = access._begin_read(session,actor_id)
    assessment_access.require_assessment_available(session,inputs)
    if not exact_identifier(offering_id,36):
        _error(404,'not_found')
    scope = ScopeRef(inputs.institution_id,'offering',offering_id)
    context = access._load_context(session,actor,scope)
    if context.offering.id != offering_id:
        _error(404,'not_found')
    ref = ObjectRef('offering',offering_id,scope.institution_id,context.course.id,offering_id)
    decision, _ = assessment_access.authorize_assessment_read(session,actor_id,TeachingAction.ASSIGNMENT_LIST,ref)
    return decision


def list_assignments(session,actor_id,offering_id,query:dto.AssessmentPageQuery):
    query = _query(query)
    decision = _catalog_authority(session,actor_id,offering_id)
    author = Permission.AUTHOR in decision.permissions
    kind = 'assignment_catalog_author' if author else 'assignment_catalog_release'
    position = decode_cursor(query.cursor,kind,offering_id,decision.actor_id)
    scope = decision.scope
    predicates = [Assignment.institution_id==scope.institution_id,Assignment.offering_id==scope.id]
    if position is not None:
        predicates.append(Assignment.id>position['after_id'])
    if author:
        rows = session.query(Assignment).filter(*predicates).populate_existing().order_by(Assignment.id).limit(query.limit+1).all()
        items = [dto.AuthorAssignmentSummaryDTO(id=row.id,offering_id=row.offering_id,
            title=_saved(row.public_draft,dto.PublicSpec).title,draft_revision=row.draft_revision,
            updated_at=access._utc(row.updated_at)) for row in rows[:query.limit]]
    else:
        latest = session.query(AssignmentVersion.assignment_id.label('assignment_id'),
            func.max(AssignmentVersion.version_number).label('version_number')).filter(
            AssignmentVersion.institution_id==scope.institution_id,AssignmentVersion.offering_id==scope.id
            ).group_by(AssignmentVersion.assignment_id).subquery()
        rows = session.query(AssignmentVersion).join(latest,
            (AssignmentVersion.assignment_id==latest.c.assignment_id)&(AssignmentVersion.version_number==latest.c.version_number)
            ).join(Assignment,(Assignment.id==AssignmentVersion.assignment_id)&
                (Assignment.institution_id==AssignmentVersion.institution_id)&(Assignment.offering_id==AssignmentVersion.offering_id)
            ).filter(*predicates,AssignmentVersion.institution_id==scope.institution_id,AssignmentVersion.offering_id==scope.id
            ).populate_existing().order_by(Assignment.id).limit(query.limit+1).all()
        items = [dto.ReleaseAssignmentSummaryDTO(id=row.assignment_id,offering_id=row.offering_id,
            title=_version(row).public_spec.title,latest_version_id=row.id,latest_version_number=row.version_number,
            frozen_at=access._utc(row.frozen_at)) for row in rows[:query.limit]]
    cursor = encode_cursor(kind,offering_id,decision.actor_id,after_id=items[-1].id) if len(rows)>query.limit else None
    return dto.AssignmentPageDTO(items=items,next_cursor=cursor,as_of=decision.checked_at)


def list_assignment_versions(session,actor_id,assignment_id,query:dto.AssessmentPageQuery):
    query = _query(query)
    decision, locked = _read(session,actor_id,TeachingAction.ASSIGNMENT_VERSIONS_LIST,'assignment',assignment_id)
    position = decode_cursor(query.cursor,'assignment_versions',assignment_id,decision.actor_id)
    predicates = [AssignmentVersion.institution_id==decision.scope.institution_id,
        AssignmentVersion.offering_id==decision.scope.id,AssignmentVersion.assignment_id==locked.assignment.id]
    if position is not None:
        predicates.append(AssignmentVersion.version_number>position['after_version_number'])
    rows = session.query(AssignmentVersion).filter(*predicates).populate_existing().order_by(
        AssignmentVersion.version_number).limit(query.limit+1).all()
    items = [dto.AssignmentVersionSummaryDTO(id=row.id,assignment_id=row.assignment_id,
        version_number=row.version_number,source_draft_revision=row.source_draft_revision,title=_version(row).public_spec.title,
        public_spec_hash=row.public_spec_hash,frozen_at=access._utc(row.frozen_at)) for row in rows[:query.limit]]
    cursor = encode_cursor('assignment_versions',assignment_id,decision.actor_id,
        after_version_number=items[-1].version_number) if len(rows)>query.limit else None
    return dto.AssignmentVersionPageDTO(items=items,next_cursor=cursor,as_of=decision.checked_at)
