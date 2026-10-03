"""Immutable inert submissions and current-authority, lineage-scoped history.

The closed engine owns locks, identities, time, shapes, receipts and events.
These services never commit, execute content or enable production writes.
"""
from collections.abc import Mapping
from hashlib import sha256

from fastapi import HTTPException
from pydantic import ValidationError

from app.models.teaching_assessment import Submission, SubmissionHead, ReleaseRecipient
from app.schemas import teaching_assessment as dto
from app.services.teaching import access, assessment_access
from app.services.teaching.assessment_pagination import decode_cursor, encode_cursor
from app.services.teaching.assessment_types import SubmissionCreateShape
from app.services.teaching.assessment_writes import (
    ASSESSMENT_RESULTS, assessment_lock_plan, collect_assessment_spec, _plain, _digest,
)
from app.services.teaching.types import TeachingAction, Permission, MutationResult, exact_identifier
from app.services.teaching.writes import make_write_intent


def _error(status,reason):
    raise HTTPException(status,reason)


def _command(command):
    if isinstance(command,dto.CreateSubmissionCommand):
        return command.model_dump()
    if not isinstance(command,Mapping):
        _error(422,'validation_error')
    try:
        return dto.CreateSubmissionCommand.model_validate(_plain(command)).model_dump()
    except (ValidationError,ValueError,TypeError,RecursionError):
        _error(422,'validation_error')


def _saved(value,model):
    try:
        return model.model_validate(_plain(value))
    except (ValidationError,ValueError,TypeError,RecursionError):
        _error(503,'invalid_assessment_state')


class _SubmissionOperation:
    def collect_locks(self,session,intent,roots,preview_footprint=None):
        if intent.action != TeachingAction.SUBMISSION_CREATE or preview_footprint is not None:
            _error(503,'invalid_lock_footprint')
        return assessment_lock_plan(roots,intent,collect_assessment_spec(session,intent,roots))

    def validate_new(self,context,command,at):
        # The engine has already checked current authority, lifecycle, deadline
        # and locked head/parent. Everything below is pure loaded-row checking.
        shape, rows = context.assessment_shape, context.assessment
        if type(shape) is not SubmissionCreateShape or rows.head is None:
            _error(503,'invalid_lock_footprint')
        if not 1 <= shape.sequence <= 9223372036854775807:
            _error(503,'invalid_assessment_state')
        public = _saved(rows.version.public_spec,dto.PublicSpec)
        if (rows.version.public_spec_hash != _digest(public.model_dump())
                or rows.release.public_spec_hash != rows.version.public_spec_hash
                or rows.release.policy_digest != _digest({'version':1,'due_at':access._utc(rows.release.due_at),
                    'timezone':rows.release.timezone,'late_policy':rows.release.late_policy})):
            _error(503,'invalid_assessment_state')
        try:
            dto.AssessmentDTO.known_timezone(rows.release.timezone)
        except ValueError:
            _error(503,'invalid_assessment_state')

    def apply_new(self,context,command,at):
        shape, rows = context.assessment_shape, context.assessment
        content = _plain(command['content'])
        fields = dict(release_id=shape.release_id,version_id=shape.version_id,
            parent_submission_id=shape.parent_submission_id,sequence=shape.sequence,
            content_hash=sha256(content['text'].encode('utf-8')).hexdigest(),received_at=at)
        context.session.add(Submission(id=shape.submission_id,institution_id=shape.institution_id,
            offering_id=shape.offering_id,student_id=shape.student_id,**fields,content=content,
            ai_usage_declaration=_plain(command['ai_usage_declaration'])))
        rows.head.submission_id = shape.submission_id
        rows.head.revision = shape.sequence
        original = dto.SubmissionAcceptanceDTO(submission_id=shape.submission_id,**fields).model_dump()
        contract = ASSESSMENT_RESULTS[TeachingAction.SUBMISSION_CREATE]
        effects = {field:original[field] for field in contract.effect_fields}
        return MutationResult(contract.result_type,shape.submission_id,original,contract.revision_kind,
            shape.sequence-1,shape.sequence,effects,201)


def prepare_submission_write(session,actor_id,release_id,command:dto.CreateSubmissionCommand,key):
    if not exact_identifier(release_id,36):
        _error(422,'validation_error')
    payload = _command(command)
    actor, _ = access._begin_read(session,actor_id)
    scope, _ = assessment_access.resolve_assessment_object(session,actor.username,'release',release_id)
    return make_write_intent(actor.username,TeachingAction.SUBMISSION_CREATE,scope,release_id,key,payload),_SubmissionOperation()


def _read(session,actor_id,action,kind,identifier):
    _, ref = assessment_access.resolve_assessment_object(session,actor_id,kind,identifier)
    return assessment_access.authorize_assessment_read(session,actor_id,action,ref)


def _query(query,model):
    try:
        return model.model_validate(query)
    except (ValidationError,ValueError,TypeError):
        _error(422,'validation_error')


def _teacher(decision):
    return decision.role_scope=='offering' and Permission.SUBMISSION_VIEW in decision.permissions


def _own(decision,rows):
    return decision.learning and any(row.student_id==decision.actor_id for row in rows.recipients)


def _submission(row):
    result = _saved(dict(id=row.id,release_id=row.release_id,version_id=row.version_id,
        parent_submission_id=row.parent_submission_id,sequence=row.sequence,
        content=row.content,content_hash=row.content_hash,ai_usage_declaration=row.ai_usage_declaration,
        received_at=access._utc(row.received_at)),dto.SubmissionDTO)
    if (result.content_hash != sha256(result.content.text.encode('utf-8')).hexdigest()
            or (result.sequence==1) != (result.parent_submission_id is None)):
        _error(503,'invalid_assessment_state')
    return result


def _history(row,*,teacher=False):
    # Validate immutable content but never place bodies/declarations on lists.
    shown = _submission(row)
    fields = {field:getattr(shown,field) for field in dto.SubmissionHistoryItemDTO.model_fields}
    if teacher:
        return _saved({**fields,'student_id':row.student_id},dto.TeacherSubmissionHistoryItemDTO)
    return dto.SubmissionHistoryItemDTO(**fields)


def get_submission(session,actor_id,submission_id):
    decision, rows = _read(session,actor_id,TeachingAction.SUBMISSION_READ,'submission',submission_id)
    shown = _submission(rows.target_submission)
    if _own(decision,rows) and rows.target_submission.student_id==decision.actor_id:
        return shown
    if not _teacher(decision) or rows.target_submission.student_id not in decision.learner_ceiling:
        _error(403,'permission_denied')
    return _saved({**shown.model_dump(),'student_id':rows.target_submission.student_id},dto.TeacherSubmissionDTO)


def _head_query(session,decision,rows,student):
    return session.query(SubmissionHead).filter(SubmissionHead.institution_id==decision.scope.institution_id,
        SubmissionHead.offering_id==decision.scope.id,SubmissionHead.release_id==rows.release.id,
        SubmissionHead.version_id==rows.version.id,SubmissionHead.student_id==student)


def _submissions_query(session,decision,rows,student):
    return session.query(Submission).filter(Submission.institution_id==decision.scope.institution_id,
        Submission.offering_id==decision.scope.id,Submission.release_id==rows.release.id,
        Submission.version_id==rows.version.id,Submission.student_id==student)


def _check_head(head,current):
    if (type(head.revision) is not int or not 0 <= head.revision <= 9223372036854775807
            or head.submission_id is None and (head.revision!=0 or current is not None)
            or head.submission_id is not None and (current is None or current.id!=head.submission_id
                or current.sequence!=head.revision or current.release_id!=head.release_id
                or current.version_id!=head.version_id or current.student_id!=head.student_id
                or current.institution_id!=head.institution_id or current.offering_id!=head.offering_id)):
        _error(503,'invalid_assessment_state')
    if current is not None:
        _submission(current)


def _head(session,decision,rows,student,*,required=True):
    # The authorization holds offering roots. Current head and current immutable
    # submission use locking reads in that same transaction, never an old ORM
    # identity-map view; history is bounded by this captured head revision.
    head = _head_query(session,decision,rows,student).populate_existing().with_for_update().first()
    if head is None:
        if required:
            _error(503,'invalid_assessment_state')
        return None
    current = None
    if head.submission_id is not None:
        current = _submissions_query(session,decision,rows,student).filter(Submission.id==head.submission_id).populate_existing().with_for_update().first()
    _check_head(head,current)
    return head


def _own_release(session,actor_id,release_id):
    decision, rows = _read(session,actor_id,TeachingAction.SUBMISSION_LIST,'release',release_id)
    if not _own(decision,rows):
        _error(403,'permission_denied')
    return decision, rows


def get_submission_head(session,actor_id,release_id):
    decision, rows = _own_release(session,actor_id,release_id)
    head = _head(session,decision,rows,decision.actor_id)
    return dto.SubmissionHeadDTO(submission_id=head.submission_id,revision=head.revision,as_of=decision.checked_at)


def list_own_submission_history(session,actor_id,release_id,query:dto.SubmissionHistoryQuery):
    query = _query(query,dto.SubmissionHistoryQuery)
    decision, rows = _own_release(session,actor_id,release_id)
    position = decode_cursor(query.cursor,'own_history',rows.release.id,decision.actor_id,student_id=decision.actor_id)
    head = _head(session,decision,rows,decision.actor_id)
    selection = _submissions_query(session,decision,rows,decision.actor_id).filter(Submission.sequence<=head.revision)
    if position is not None:
        selection = selection.filter(Submission.sequence>position['after_sequence'])
    selected = selection.populate_existing().order_by(Submission.sequence).limit(query.limit+1).with_for_update().all()
    items = [_history(row) for row in selected[:query.limit]]
    cursor = encode_cursor('own_history',rows.release.id,decision.actor_id,student_id=decision.actor_id,
        after_sequence=items[-1].sequence) if len(selected)>query.limit else None
    return dto.SubmissionHistoryDTO(items=items,current_head_id=head.submission_id,next_cursor=cursor,as_of=decision.checked_at)


def list_release_submissions(session,actor_id,release_id,query:dto.TeacherSubmissionQuery):
    query = _query(query,dto.TeacherSubmissionQuery)
    decision, rows = _read(session,actor_id,TeachingAction.SUBMISSION_LIST,'release',release_id)
    if not _teacher(decision):
        _error(403,'permission_denied')
    kind = 'teacher_heads' if query.student_id is None else 'teacher_history'
    position = decode_cursor(query.cursor,kind,rows.release.id,decision.actor_id,student_id=query.student_id)
    if query.student_id is not None:
        # No query of an out-of-ceiling learner; cursor validation is still exact.
        if query.student_id not in decision.learner_ceiling:
            return dto.TeacherSubmissionPageDTO(items=[],current_head_id=None,next_cursor=None,as_of=decision.checked_at)
        head = _head(session,decision,rows,query.student_id,required=False)
        if head is None:
            recipient = session.query(ReleaseRecipient).filter(ReleaseRecipient.institution_id==decision.scope.institution_id,
                ReleaseRecipient.offering_id==decision.scope.id,ReleaseRecipient.release_id==rows.release.id,
                ReleaseRecipient.version_id==rows.version.id,ReleaseRecipient.student_id==query.student_id).populate_existing().with_for_update().first()
            if recipient is not None:
                _error(503,'invalid_assessment_state')
            return dto.TeacherSubmissionPageDTO(items=[],current_head_id=None,next_cursor=None,as_of=decision.checked_at)
        selection = _submissions_query(session,decision,rows,query.student_id).filter(Submission.sequence<=head.revision)
        if position is not None:
            selection = selection.filter(Submission.sequence>position['after_sequence'])
        selected = selection.populate_existing().order_by(Submission.sequence).limit(query.limit+1).with_for_update().all()
        items = [_history(row,teacher=True) for row in selected[:query.limit]]
        cursor = encode_cursor(kind,rows.release.id,decision.actor_id,student_id=query.student_id,
            after_sequence=items[-1].sequence) if len(selected)>query.limit else None
        return dto.TeacherSubmissionPageDTO(items=items,current_head_id=head.submission_id,next_cursor=cursor,as_of=decision.checked_at)
    selection = session.query(SubmissionHead,Submission).join(Submission,
        (Submission.id==SubmissionHead.submission_id)&(Submission.institution_id==SubmissionHead.institution_id)&
        (Submission.offering_id==SubmissionHead.offering_id)&(Submission.release_id==SubmissionHead.release_id)&
        (Submission.version_id==SubmissionHead.version_id)&(Submission.student_id==SubmissionHead.student_id)).filter(
        SubmissionHead.institution_id==decision.scope.institution_id,SubmissionHead.offering_id==decision.scope.id,
        SubmissionHead.release_id==rows.release.id,SubmissionHead.version_id==rows.version.id,
        SubmissionHead.student_id.in_(sorted(decision.learner_ceiling)))
    if position is not None:
        selection = selection.filter(SubmissionHead.student_id>position['after_student_id'])
    selected = selection.populate_existing().order_by(SubmissionHead.student_id).limit(query.limit+1).with_for_update().all()
    items = []
    for head,current in selected[:query.limit]:
        _check_head(head,current)
        items.append(_history(current,teacher=True))
    cursor = encode_cursor(kind,rows.release.id,decision.actor_id,student_id=None,
        after_student_id=items[-1].student_id) if len(selected)>query.limit else None
    return dto.TeacherSubmissionPageDTO(items=items,current_head_id=None,next_cursor=cursor,as_of=decision.checked_at)
