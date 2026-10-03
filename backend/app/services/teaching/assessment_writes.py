"""Closed B2 lock, shape, receipt and event extension. No business services.

Only finite action branches select rows and append identities. The unchanged
production write gate remains authoritative; synthetic evidence is not rollout.
"""
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from hashlib import sha256
from types import MappingProxyType
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import inspect

from app.models.teaching import WriteReceipt
from app.models.teaching_assessment import (
    Assignment, AssignmentDraftPrivate, AssignmentVersion, PrivateSpec,
    ReleasePreview, Release, ReleaseRecipient, SubmissionHead, Submission, AssessmentEvent,
)
from app.models.user_account import UserAccount
from app.schemas import teaching_assessment as dto
from app.services.teaching import access
from app.services.teaching.types import (
    ASSESSMENT_WRITE_ACTIONS, TeachingAction, LockPlan, ReceiptLookup, ScopeRef, MutationResult, exact_identifier,
)
from app.services.teaching.assessment_types import (
    AssessmentLockSpec, AssessmentReceiptDiscovery, AssessmentLockedRows, RecipientIdentity,
    AssignmentCreateShape, AssignmentUpdateShape, PrivateDraftUpdateShape, VersionCreateShape,
    ReleasePreviewCreateShape, ReleaseCreateShape, SubmissionCreateShape, RecoveryOnlyShape,
)


def _error(code, reason):
    raise HTTPException(code,reason)


def _w():
    from app.services.teaching import writes
    return writes


def _plain(value):
    if isinstance(value,Mapping): return {key:_plain(item) for key,item in value.items()}
    if isinstance(value,(tuple,list)): return [_plain(item) for item in value]
    return value


def _digest(value):
    return sha256(_w()._json(value).encode('utf-8')).hexdigest()


_COMMANDS = MappingProxyType({
    TeachingAction.ASSIGNMENT_CREATE:dto.CreateAssignmentCommand,
    TeachingAction.ASSIGNMENT_UPDATE:dto.ReplaceAssignmentDraftCommand,
    TeachingAction.ASSIGNMENT_PRIVATE_UPDATE:dto.ReplacePrivateDraftCommand,
    TeachingAction.ASSIGNMENT_FREEZE:dto.FreezeAssignmentCommand,
    TeachingAction.RELEASE_PREVIEW:dto.ReleasePreviewCommand,
    TeachingAction.RELEASE_CREATE:dto.ConfirmReleaseCommand,
    TeachingAction.SUBMISSION_CREATE:dto.CreateSubmissionCommand,
})


def normalize_assessment_command(action, scope, target_id, command):
    if action not in ASSESSMENT_WRITE_ACTIONS or scope.kind!='offering':
        _error(422,'validation_error')
    if action==TeachingAction.ASSIGNMENT_CREATE:
        if target_id is not None: _error(422,'validation_error')
    elif not exact_identifier(target_id,36):
        _error(422,'validation_error')
    try:
        result=_COMMANDS[action].model_validate(_plain(command)).model_dump()
    except (ValidationError,ValueError,TypeError,RecursionError):
        _error(422,'validation_error')
    if len(_w()._json(result).encode('utf-8'))>524288:
        _error(422,'validation_error')
    return result


@dataclass(frozen=True)
class _ResultContract:
    dto_type: type
    result_type: str
    revision_kind: str
    effect_fields: tuple[str,...]
    id_field: str
    revision_field: str | None
    time_field: str


ASSESSMENT_RESULTS = MappingProxyType({
    TeachingAction.ASSIGNMENT_CREATE:_ResultContract(dto.AssignmentAcceptanceDTO,'assignment','assignment_draft',('assignment_id','draft_revision'),'assignment_id','draft_revision','accepted_at'),
    TeachingAction.ASSIGNMENT_UPDATE:_ResultContract(dto.AssignmentAcceptanceDTO,'assignment','assignment_draft',('assignment_id','draft_revision'),'assignment_id','draft_revision','accepted_at'),
    TeachingAction.ASSIGNMENT_PRIVATE_UPDATE:_ResultContract(dto.PrivateDraftAcceptanceDTO,'assignment_private','assignment_draft',('assignment_id','draft_revision'),'assignment_id','draft_revision','accepted_at'),
    TeachingAction.ASSIGNMENT_FREEZE:_ResultContract(dto.VersionAcceptanceDTO,'assignment_version','assignment_version',('assignment_id','version_id','source_draft_revision'),'version_id','version_number','frozen_at'),
    TeachingAction.RELEASE_PREVIEW:_ResultContract(dto.ReleasePreviewAcceptanceDTO,'release_preview','release_preview',('preview_id','assignment_id','version_id','recipient_count','recipient_digest'),'preview_id',None,'accepted_at'),
    TeachingAction.RELEASE_CREATE:_ResultContract(dto.ReleaseAcceptanceDTO,'release','release',('release_id','assignment_id','version_id','recipient_count','recipient_digest'),'release_id',None,'released_at'),
    TeachingAction.SUBMISSION_CREATE:_ResultContract(dto.SubmissionAcceptanceDTO,'submission','submission_head',('submission_id','release_id','version_id','parent_submission_id','sequence'),'submission_id','sequence','received_at'),
})


def validate_assessment_mutation(result, action):
    contract=ASSESSMENT_RESULTS[action]
    try:
        original=contract.dto_type.model_validate(_plain(result.original_result)).model_dump(mode='json')
    except (ValidationError,ValueError,TypeError):
        _error(503,'invalid_mutation_result')
    after=original[contract.revision_field] if contract.revision_field else 1
    if (result.result_type!=contract.result_type or result.result_id!=original[contract.id_field]
            or result.revision_kind!=contract.revision_kind or type(result.before_revision) is not int
            or type(result.after_revision) is not int or result.before_revision!=after-1 or result.after_revision!=after
            or action==TeachingAction.ASSIGNMENT_CREATE and after!=1):
        _error(503,'invalid_mutation_result')
    effects={field:original[field] for field in contract.effect_fields}
    if _w()._canonical(result.effect_metadata)!=effects:
        _error(503,'invalid_mutation_result')
    return original,effects


def _fingerprint(row):
    return _digest({column.name:access._utc(getattr(row,column.name)) if isinstance(getattr(row,column.name),datetime) else getattr(row,column.name) for column in row.__table__.columns})


def discover_assessment_receipt(session, actor_id, action, scope, key):
    if action not in ASSESSMENT_WRITE_ACTIONS or scope.kind!='offering': _error(503,'invalid_lock_footprint')
    row=session.query(WriteReceipt).filter(WriteReceipt.institution_id==scope.institution_id,
        WriteReceipt.actor_id==actor_id,WriteReceipt.action==action.value,WriteReceipt.scope_type=='offering',
        WriteReceipt.scope_id==scope.id,WriteReceipt.idempotency_key==key).populate_existing().first()
    if row is None: return AssessmentReceiptDiscovery('absent')
    if (row.actor_id,row.action,row.institution_id,row.scope_type,row.scope_id,row.idempotency_key)!=(actor_id,action.value,scope.institution_id,'offering',scope.id,key):
        _error(503,'lock_footprint_changed')
    contract=ASSESSMENT_RESULTS[action]
    if row.result_type!=contract.result_type or row.target_type!=row.result_type or row.target_id!=row.result_id:
        _error(503,'invalid_assessment_state')
    try:
        original=contract.dto_type.model_validate(row.original_result)
    except ValidationError:
        _error(503,'invalid_assessment_state')
    if getattr(original,contract.id_field)!=row.result_id:
        _error(503,'invalid_assessment_state')
    return AssessmentReceiptDiscovery('existing',row.id,row.result_type,row.result_id,_fingerprint(row))


def verify_assessment_receipt(discovery, receipt):
    if discovery is None or (discovery.mode=='existing')!=(receipt is not None):
        _error(503,'lock_footprint_changed')
    if receipt is not None and (receipt.id!=discovery.receipt_id or _fingerprint(receipt)!=discovery.fingerprint):
        _error(503,'lock_footprint_changed')


def _one(session,model,scope,*predicates,lock=False,required=True):
    row=_w()._fresh(session,model,model.institution_id==scope.institution_id,model.offering_id==scope.id,*predicates,lock=lock)
    if row is None:
        if required: _error(404,'not_found')
        return None
    if (row.institution_id,row.offering_id)!=(scope.institution_id,scope.id): _error(404,'not_found')
    return row


def _target_spec(session, roots, purpose, kind, identifier):
    """Read ancestry under held roots; later exact row locks must revalidate it."""
    scope=roots.scope
    aid=vid=pid=rid=student=None
    if kind in {'assignment','assignment_private'}:
        row=_one(session,Assignment,scope,Assignment.id==identifier); aid=row.id
        if aid!=identifier: _error(404,'not_found')
    elif kind in {'version','assignment_version'}:
        row=_one(session,AssignmentVersion,scope,AssignmentVersion.id==identifier); aid,vid=row.assignment_id,row.id
        if vid!=identifier: _error(404,'not_found')
    elif kind=='release_preview':
        row=_one(session,ReleasePreview,scope,ReleasePreview.id==identifier); aid,vid,pid=row.assignment_id,row.version_id,row.id
        if pid!=identifier: _error(404,'not_found')
    elif kind=='release':
        row=_one(session,Release,scope,Release.id==identifier); aid,vid,pid,rid=row.assignment_id,row.version_id,row.preview_id,row.id
        if rid!=identifier: _error(404,'not_found')
    elif kind=='submission':
        row=_one(session,Submission,scope,Submission.id==identifier)
        if row.id!=identifier: _error(404,'not_found')
        release=_one(session,Release,scope,Release.id==row.release_id)
        if row.version_id!=release.version_id: _error(404,'not_found')
        aid,vid,pid,rid,student=release.assignment_id,release.version_id,release.preview_id,release.id,row.student_id
    elif kind=='offering' and identifier==scope.id:
        pass
    else: _error(404,'not_found')
    return AssessmentLockSpec(purpose,aid,vid,pid,rid,student)


def _saved_audience(preview):
    try:
        if not isinstance(preview.recipient_snapshot,list): raise ValueError('list required')
        values=tuple(dto.RecipientSnapshotDTO.model_validate(value) for value in preview.recipient_snapshot)
        ids=tuple(value.student_id for value in values)
        if ids!=tuple(sorted(set(ids))) or len(ids)!=preview.recipient_count or not 1<=len(ids)<=1000:
            raise ValueError('invalid saved audience')
        if _digest({'version':1,'recipients':[value.model_dump() for value in values]})!=preview.recipient_digest:
            raise ValueError('invalid audience digest')
    except (ValidationError,ValueError,TypeError):
        _error(503,'invalid_assessment_state')
    return values


def _resolve_audience(session, requested, ceiling):
    # The database predicate bounds every candidate before alias resolution.
    # No arbitrary out-of-ceiling account lookup or account-dependent error.
    query=session.query(UserAccount.username).filter(UserAccount.username.in_(sorted(ceiling)))
    resolved=[]; issues=[]
    for subject in sorted(requested):
        values=query.filter(UserAccount.username==subject).limit(2).all() if ceiling else []
        if len(values)!=1 or values[0][0] not in ceiling:
            issues.append(dto.RecipientIssueDTO(code='unavailable_or_out_of_scope',subject_id=subject))
        else:
            canonical=values[0][0]
            if canonical in resolved: issues.append(dto.RecipientIssueDTO(code='duplicate_recipient',subject_id=subject))
            resolved.append(canonical)
    return tuple(sorted(set(resolved))),tuple(issues)


def collect_assessment_spec(session, intent, roots):
    """Finite intent discovery; an accepted receipt never resolves old learners."""
    if roots.lock_plan is not None and roots.lock_plan.assessment is not None:
        return roots.lock_plan.assessment
    action=intent.action; command=intent.canonical_payload; discovery=roots.assessment_receipt
    if discovery is None: _error(503,'invalid_lock_footprint')
    if discovery.mode=='existing':
        return _target_spec(session,roots,action.value,discovery.result_type,discovery.result_id)
    if action==TeachingAction.ASSIGNMENT_CREATE:
        return AssessmentLockSpec(action.value)
    if action in {TeachingAction.ASSIGNMENT_UPDATE,TeachingAction.ASSIGNMENT_PRIVATE_UPDATE,TeachingAction.ASSIGNMENT_FREEZE}:
        return _target_spec(session,roots,action.value,'assignment',intent.target_id)
    if action==TeachingAction.RELEASE_PREVIEW:
        spec=_target_spec(session,roots,action.value,'version',command['version_id'])
        if spec.assignment_id!=intent.target_id: _error(404,'not_found')
        recipients,issues=_resolve_audience(session,command['student_ids'],roots.policy.learner_ceiling)
        return replace(spec,recipient_ids=recipients,audience_issues=issues)
    if action==TeachingAction.RELEASE_CREATE:
        spec=_target_spec(session,roots,action.value,'release_preview',command['preview_id'])
        if spec.assignment_id!=intent.target_id or spec.version_id!=command['version_id']: _error(404,'not_found')
        preview=_one(session,ReleasePreview,roots.scope,ReleasePreview.id==spec.release_preview_id)
        return replace(spec,recipient_ids=tuple(value.student_id for value in _saved_audience(preview)))
    if action==TeachingAction.SUBMISSION_CREATE:
        spec=_target_spec(session,roots,action.value,'release',intent.target_id)
        return replace(spec,student_id=roots.actor_account.username)
    _error(503,'invalid_lock_footprint')


def assessment_lock_plan(roots, intent, spec):
    subjects=tuple(sorted(set(spec.recipient_ids)|({spec.student_id} if spec.student_id else set())))
    return LockPlan(root_course_id=roots.course.id,root_offering_id=roots.offering.id,
        account_ids=subjects,enrollment_subject_ids=subjects,receipt_lookup=ReceiptLookup.from_intent(intent),assessment=spec)


def assessment_read_spec(session, roots, action):
    ref=roots.object_ref
    if ref is None: _error(404,'not_found')
    return _target_spec(session,roots,action.value,ref.kind,ref.id)


def assessment_recovery_spec(session, roots, action):
    discovery=roots.assessment_receipt
    if discovery.mode=='absent': return AssessmentLockSpec(action.value)
    return _target_spec(session,roots,action.value,discovery.result_type,discovery.result_id)


def lock_assessment_rows(session, roots, spec, receipt):
    """Assignment → Version → Preview → Release → Recipient/Head/Submission."""
    if roots.actor_account is None:
        _error(401,'invalid_current_account')
    scope=roots.scope
    assignment=private=version=private_spec=preview=release=head=parent=target=None
    if spec.assignment_id:
        assignment=_one(session,Assignment,scope,Assignment.id==spec.assignment_id,lock=True)
        private=_one(session,AssignmentDraftPrivate,scope,AssignmentDraftPrivate.assignment_id==assignment.id,lock=True)
    if spec.version_id:
        version=_one(session,AssignmentVersion,scope,AssignmentVersion.id==spec.version_id,AssignmentVersion.assignment_id==spec.assignment_id,lock=True)
        private_spec=_one(session,PrivateSpec,scope,PrivateSpec.version_id==version.id,PrivateSpec.assignment_id==assignment.id,lock=True)
    elif assignment is not None and spec.purpose==TeachingAction.ASSIGNMENT_FREEZE.value:
        version=_one(session,AssignmentVersion,scope,AssignmentVersion.assignment_id==assignment.id,AssignmentVersion.source_draft_revision==assignment.draft_revision,lock=True,required=False)
        if version:
            private_spec=_one(session,PrivateSpec,scope,PrivateSpec.version_id==version.id,PrivateSpec.assignment_id==assignment.id,lock=True)
    if spec.release_preview_id:
        preview=_one(session,ReleasePreview,scope,ReleasePreview.id==spec.release_preview_id,ReleasePreview.assignment_id==spec.assignment_id,ReleasePreview.version_id==spec.version_id,lock=True)
        _saved_audience(preview)
    if spec.release_id:
        release=_one(session,Release,scope,Release.id==spec.release_id,Release.assignment_id==spec.assignment_id,Release.version_id==spec.version_id,lock=True)
        if preview is None or release.preview_id!=preview.id: _error(404,'not_found')
    elif version is not None:
        release=_one(session,Release,scope,Release.version_id==version.id,Release.assignment_id==assignment.id,lock=True,required=False)
    recipients=()
    if release is not None:
        # Only the current actor/original submission learner is needed for
        # conflict/own-access checks; summary recovery never reloads old users.
        student=spec.student_id or roots.actor_account.username
        query=session.query(ReleaseRecipient).filter(ReleaseRecipient.institution_id==scope.institution_id,
            ReleaseRecipient.offering_id==scope.id,ReleaseRecipient.release_id==release.id,
            ReleaseRecipient.version_id==release.version_id,ReleaseRecipient.student_id==student)
        recipients=tuple(query.populate_existing().order_by(ReleaseRecipient.student_id).with_for_update().all())
        if spec.student_id is not None:
            head=_one(session,SubmissionHead,scope,SubmissionHead.release_id==release.id,SubmissionHead.version_id==release.version_id,SubmissionHead.student_id==student,lock=True,required=receipt is None)
            target_id=(roots.object_ref.id if roots.object_ref and roots.object_ref.kind=='submission' else
                       receipt.result_id if receipt is not None and receipt.result_type=='submission' else None)
            identifiers=sorted({item for item in (head.submission_id if head else None,target_id) if item})
            submissions={identifier:_one(session,Submission,scope,Submission.id==identifier,Submission.release_id==release.id,
                Submission.version_id==release.version_id,Submission.student_id==student,lock=True) for identifier in identifiers}
            parent=submissions.get(head.submission_id) if head else None
            target=submissions.get(target_id)
    return AssessmentLockedRows(assignment,private,version,private_spec,preview,release,recipients,head,parent,target)



def validate_assessment_receipt_target(context):
    """Verify original projection against locked immutable rows, without SQL.

    Mutable draft revision/update time are historical receipt values. Immutable
    version, preview, release and submission fields must describe their exact
    loaded target; newer draft/head state never substitutes for that target.
    """
    receipt=context.receipt
    if receipt is None: return
    action=TeachingAction(context.lock_plan.assessment.purpose)
    contract=ASSESSMENT_RESULTS[action]
    rows=context.assessment
    try:
        original=contract.dto_type.model_validate(receipt.original_result).model_dump(mode='json')
    except (ValidationError,ValueError,TypeError):
        _error(503,'invalid_assessment_state')
    if (receipt.actor_id!=context.policy.actor_id or receipt.action!=action.value
            or receipt.institution_id!=context.scope.institution_id or receipt.scope_type!='offering'
            or receipt.scope_id!=context.scope.id or receipt.result_type!=contract.result_type
            or receipt.result_id!=original[contract.id_field] or receipt.target_type!=receipt.result_type
            or receipt.target_id!=receipt.result_id or receipt.canonicalization_version!=1
            or receipt.http_status not in {200,201}):
        _error(503,'invalid_assessment_state')
    expected={contract.time_field:access._utc(receipt.accepted_at)}
    if action in {TeachingAction.ASSIGNMENT_CREATE,TeachingAction.ASSIGNMENT_UPDATE,TeachingAction.ASSIGNMENT_PRIVATE_UPDATE}:
        if rows.assignment is None: _error(503,'invalid_assessment_state')
        expected['assignment_id']=rows.assignment.id
        if action==TeachingAction.ASSIGNMENT_CREATE:
            expected['draft_revision']=1
            if rows.assignment.created_by!=receipt.actor_id: _error(503,'invalid_assessment_state')
    elif action==TeachingAction.ASSIGNMENT_FREEZE:
        if rows.version is None: _error(503,'invalid_assessment_state')
        version=row_values(rows.version)
        expected.update({key:version[key] for key in ('assignment_id','version_number','source_draft_revision','public_spec_hash')})
        expected['version_id']=version['id']
        if version['frozen_at']!=_w()._canonical(access._utc(receipt.accepted_at)) or rows.version.frozen_by!=receipt.actor_id:
            _error(503,'invalid_assessment_state')
    elif action in {TeachingAction.RELEASE_PREVIEW,TeachingAction.RELEASE_CREATE}:
        row=rows.release_preview if action==TeachingAction.RELEASE_PREVIEW else rows.release
        if row is None: _error(503,'invalid_assessment_state')
        target=row_values(row)
        expected.update({key:target[key] for key in ('assignment_id','version_id','public_spec_hash','recipient_count','recipient_digest','due_at','timezone','late_policy','policy_digest')})
        expected[contract.id_field]=target['id']
        if action==TeachingAction.RELEASE_PREVIEW:
            expected['expires_at']=target['expires_at']; accepted=target['created_at']; actor=row.actor_id
        else:
            accepted=target['released_at']; actor=row.released_by
        if accepted!=_w()._canonical(access._utc(receipt.accepted_at)) or actor!=receipt.actor_id: _error(503,'invalid_assessment_state')
        if rows.version is None or target['public_spec_hash']!=rows.version.public_spec_hash: _error(503,'invalid_assessment_state')
    elif action==TeachingAction.SUBMISSION_CREATE:
        if rows.target_submission is None: _error(503,'invalid_assessment_state')
        target=row_values(rows.target_submission)
        expected.update({key:target[key] for key in ('release_id','version_id','parent_submission_id','sequence','content_hash')})
        expected['submission_id']=target['id']
        if target['received_at']!=_w()._canonical(access._utc(receipt.accepted_at)) or target['student_id']!=receipt.actor_id:
            _error(503,'invalid_assessment_state')
    if any(original[key]!=value for key,value in _w()._canonical(expected).items()):
        _error(503,'invalid_assessment_state')


def allocate_assessment_shape(context, action, command):
    """Engine-only allocation after locks/policy, strictly before final clock."""
    if context.actor_account is None:
        _error(401,'invalid_current_account')
    if context.assessment_receipt is not None and context.assessment_receipt.mode=='existing':
        return RecoveryOnlyShape()
    rows=context.assessment; scope=(context.scope.institution_id,context.scope.id)
    if action==TeachingAction.ASSIGNMENT_CREATE: return AssignmentCreateShape(*scope,str(uuid4()))
    if rows.assignment is None: _error(404,'not_found')
    if action==TeachingAction.ASSIGNMENT_UPDATE: return AssignmentUpdateShape(*scope,rows.assignment.id,rows.assignment.draft_revision)
    if action==TeachingAction.ASSIGNMENT_PRIVATE_UPDATE: return PrivateDraftUpdateShape(*scope,rows.assignment.id,rows.assignment.draft_revision)
    if action==TeachingAction.ASSIGNMENT_FREEZE:
        return VersionCreateShape(*scope,rows.assignment.id,str(uuid4()),rows.assignment.next_version_number,rows.assignment.draft_revision)
    if action in {TeachingAction.RELEASE_PREVIEW,TeachingAction.RELEASE_CREATE}:
        audience=tuple(RecipientIdentity(subject,row.id,row.revision) for subject in context.lock_plan.assessment.recipient_ids
                       if (row:=context.enrollments.get(subject)) is not None)
        if action==TeachingAction.RELEASE_PREVIEW:
            return ReleasePreviewCreateShape(*scope,rows.assignment.id,rows.version.id,str(uuid4()),audience)
        return ReleaseCreateShape(*scope,rows.assignment.id,rows.version.id,rows.release_preview.id,str(uuid4()),audience)
    if action==TeachingAction.SUBMISSION_CREATE:
        if rows.release is None or rows.head is None: _error(404,'not_found')
        return SubmissionCreateShape(*scope,rows.release.id,rows.version.id,context.actor_account.username,str(uuid4()),rows.head.submission_id,rows.head.revision+1)
    _error(503,'invalid_lock_footprint')


def validate_assessment_new(context, action, command, at):
    """Non-bypassable finite invariants. Later services may add stricter checks."""
    rows=context.assessment; spec=context.lock_plan.assessment
    allowed={'draft','active'} if action in {TeachingAction.ASSIGNMENT_CREATE,TeachingAction.ASSIGNMENT_UPDATE,TeachingAction.ASSIGNMENT_PRIVATE_UPDATE} else {'active'}
    if context.offering.state not in allowed: _error(409,'lifecycle_conflict')
    if 'expected_revision' in command and command['expected_revision']!=rows.assignment.draft_revision:
        _error(409,'revision_conflict')
    if action==TeachingAction.ASSIGNMENT_FREEZE and rows.version is not None:
        _error(409,'version_already_frozen')
    if action in {TeachingAction.RELEASE_PREVIEW,TeachingAction.RELEASE_CREATE}:
        if spec.audience_issues:
            _error(422,'duplicate_recipient' if any(issue.code=='duplicate_recipient' for issue in spec.audience_issues) else 'unavailable_or_out_of_scope')
        for subject in spec.recipient_ids:
            account=context.accounts.get(subject); enrollment=context.enrollments.get(subject)
            if (subject not in context.authorization.learner_ceiling or account is None or account.username!=subject
                    or account.role not in {'student','teacher'} or not access._active(enrollment,at)
                    or enrollment.source_kind!='deployment_roster' or enrollment.source_teacher_id!=context.policy.source_teacher_id
                    or subject not in context.policy.source_roster.members):
                _error(422,'unavailable_or_out_of_scope')
        if not spec.recipient_ids or len(context.assessment_shape.audience)!=len(spec.recipient_ids): _error(422,'unavailable_or_out_of_scope')
        if action==TeachingAction.RELEASE_CREATE:
            p=rows.release_preview
            if at>=access._utc(p.expires_at): _error(409,'preview_expired')
            expected={field:getattr(p,field) for field in ('version_id','public_spec_hash','recipient_count','recipient_digest','policy_digest')}
            if any(command[field]!=value for field,value in expected.items()) or command['preview_id']!=p.id:
                _error(409,'preview_stale')
            if (p.actor_id!=context.authorization.actor_id or p.actor_role_id!=context.authorization.role_id
                    or p.actor_role_revision!=context.authorization.role_revision or p.offering_revision!=context.offering.revision
                    or p.roster_revision!=context.offering.roster_revision or p.timezone!=context.offering.timezone
                    or p.source_policy_digest!=context.policy.digest): _error(409,'preview_stale')
            current=tuple(RecipientIdentity(value.student_id,value.enrollment_id,value.enrollment_revision) for value in _saved_audience(p))
            if current!=context.assessment_shape.audience: _error(409,'preview_stale')
            if rows.release is not None: _error(409,'version_already_released')
            due=access._utc(p.due_at)
        else:
            due=dto.parse_assessment_utc(command['due_at'])
        if due is not None and due<=at: _error(409,'deadline_closed')
        try: dto.AssessmentDTO.known_timezone(context.offering.timezone)
        except ValueError: _error(503,'invalid_assessment_state')
    if action==TeachingAction.SUBMISSION_CREATE:
        if rows.release.due_at is not None and access._utc(rows.release.due_at)<=at: _error(409,'deadline_closed')
        if command['expected_parent_id']!=rows.head.submission_id: _error(409,'parent_conflict')
        if (rows.head.submission_id is None and rows.head.revision!=0 or rows.head.submission_id is not None
                and (rows.parent_submission is None or rows.parent_submission.sequence!=rows.head.revision)):
            _error(503,'invalid_assessment_state')


def row_values(row):
    if row is None: return None
    return {column.name:_w()._canonical(access._utc(value) if isinstance(value:=getattr(row,column.name),datetime) else value)
            for column in row.__table__.columns}


def assessment_baseline(rows):
    return {field:row_values(getattr(rows,field)) for field in ('assignment','draft_private','version','private_spec','release_preview','release','head','parent_submission','target_submission')}


def protected_assessment_rows(context):
    rows=context.assessment
    return tuple(row for row in (rows.assignment,rows.draft_private,rows.version,rows.private_spec,
        rows.release_preview,rows.release,*rows.recipients,rows.head,rows.parent_submission,rows.target_submission) if row is not None)


def _identity(row):
    return type(row),tuple(getattr(row,column.name) for column in row.__table__.primary_key.columns)


def _expected_identity(model,values):
    return model,tuple(values[column.name] for column in model.__table__.primary_key.columns)


def _expected_business(context):
    """Closed concrete append/update values fixed by engine data, never a callback."""
    shape=context.assessment_shape
    if isinstance(shape,RecoveryOnlyShape): return (),{}
    base=context.pre_mutation['assessment_baseline']; command=context.pre_mutation['assessment_command']
    rows=context.assessment; at=context.authorization.checked_at; actor=context.authorization.actor_id
    scope={'institution_id':shape.institution_id,'offering_id':shape.offering_id}
    appends=[]; updates={}
    if type(shape) is AssignmentCreateShape:
        appends=[(Assignment,dict(id=shape.assignment_id,**scope,public_draft=_plain(command['public_spec']),draft_revision=1,next_version_number=1,created_by=actor,created_at=at,updated_at=at)),
                 (AssignmentDraftPrivate,dict(assignment_id=shape.assignment_id,**scope,private_draft={'answer_text':'','private_test_notes':''},updated_at=at))]
    elif type(shape) is AssignmentUpdateShape:
        updates[id(rows.assignment)]={'public_draft':_plain(command['public_spec']),'draft_revision':shape.before_revision+1,'updated_at':at}
    elif type(shape) is PrivateDraftUpdateShape:
        updates[id(rows.assignment)]={'draft_revision':shape.before_revision+1,'updated_at':at}
        updates[id(rows.draft_private)]={'private_draft':_plain(command['private_spec']),'updated_at':at}
    elif type(shape) is VersionCreateShape:
        public=_plain(base['assignment']['public_draft']); private=_plain(base['draft_private']['private_draft'])
        appends=[(AssignmentVersion,dict(id=shape.version_id,assignment_id=shape.assignment_id,**scope,version_number=shape.version_number,source_draft_revision=shape.source_draft_revision,public_spec=public,public_spec_hash=_digest(public),frozen_by=actor,frozen_at=at)),
                 (PrivateSpec,dict(version_id=shape.version_id,assignment_id=shape.assignment_id,**scope,private_spec=private,private_spec_hash=_digest(private)))]
        updates[id(rows.assignment)]={'next_version_number':shape.version_number+1}
    elif type(shape) is ReleasePreviewCreateShape:
        audience=[{'student_id':r.student_id,'enrollment_id':r.enrollment_id,'enrollment_revision':r.enrollment_revision} for r in shape.audience]
        due=dto.parse_assessment_utc(command['due_at']); timezone=context.offering.timezone
        appends=[(ReleasePreview,dict(id=shape.preview_id,assignment_id=shape.assignment_id,version_id=shape.version_id,**scope,
            actor_id=actor,actor_role_id=context.authorization.role_id,actor_role_revision=context.authorization.role_revision,
            offering_revision=context.offering.revision,roster_revision=context.offering.roster_revision,source_policy_digest=context.policy.digest,
            recipient_snapshot=audience,recipient_count=len(audience),recipient_digest=_digest({'version':1,'recipients':audience}),
            public_spec_hash=base['version']['public_spec_hash'],due_at=due,timezone=timezone,late_policy='reject',
            policy_digest=_digest({'version':1,'due_at':due,'timezone':timezone,'late_policy':'reject'}),created_at=at,expires_at=at+timedelta(minutes=15)))]
    elif type(shape) is ReleaseCreateShape:
        preview=base['release_preview']
        fields={field:preview[field] for field in ('assignment_id','version_id','public_spec_hash','recipient_count','recipient_digest','due_at','timezone','late_policy','policy_digest')}
        appends=[(Release,dict(id=shape.release_id,**scope,**fields,preview_id=shape.preview_id,released_by=actor,released_at=at))]
        for member in shape.audience:
            appends.append((ReleaseRecipient,dict(release_id=shape.release_id,**scope,version_id=shape.version_id,student_id=member.student_id,
                enrollment_id=member.enrollment_id,enrollment_revision_at_release=member.enrollment_revision,accepted_policy_digest=context.policy.digest)))
            appends.append((SubmissionHead,dict(release_id=shape.release_id,**scope,version_id=shape.version_id,student_id=member.student_id,submission_id=None,revision=0)))
    elif type(shape) is SubmissionCreateShape:
        content=_plain(command['content'])
        appends=[(Submission,dict(id=shape.submission_id,**scope,release_id=shape.release_id,version_id=shape.version_id,student_id=shape.student_id,
            parent_submission_id=shape.parent_submission_id,sequence=shape.sequence,content=content,content_hash=sha256(content['text'].encode('utf-8')).hexdigest(),
            ai_usage_declaration=_plain(command['ai_usage_declaration']),received_at=at))]
        updates[id(rows.head)]={'submission_id':shape.submission_id,'revision':shape.sequence}
    else: _error(503,'invalid_lock_footprint')
    return tuple((model,_w()._canonical(values)) for model,values in appends),{key:_w()._canonical(values) for key,values in updates.items()}


def assessment_mutation_boundary(context):
    """Internal flush checker. Only the engine can consume its own allowance."""
    appends,updates=_expected_business(context)
    expected={_expected_identity(model,values):values for model,values in appends}
    protected=(context.course,context.offering,*context.accounts.values(),*context.roles.values(),*context.enrollments.values(),*protected_assessment_rows(context))
    originals={id(row):row_values(row) for row in protected if row is not None}
    expected_existing={key:{**values,**updates.get(key,{})} for key,values in originals.items()}
    seen={}

    def check(session, own_appends):
        if session.deleted: _error(503,'undeclared_mutation')
        for row in protected:
            if row is None: continue
            values=row_values(row); before=originals[id(row)]; after=expected_existing[id(row)]
            allowed=updates.get(id(row),{})
            dirty={attribute.key for attribute in inspect(row).attrs if attribute.history.has_changes()}
            if not dirty<=set(allowed) or any(values[key]!=before[key] for key in before if key not in allowed):
                _error(503,'undeclared_mutation')
            if any(values[key] not in (before[key],after[key]) for key in allowed): _error(503,'undeclared_mutation')
        for row in session.dirty:
            if id(row) not in originals and id(row) not in own_appends and _identity(row) not in seen:
                _error(503,'undeclared_mutation')
        for row in session.new:
            if id(row) in own_appends: continue
            key=_identity(row)
            if key not in expected or row_values(row)!=expected[key] or key in seen and seen[key] is not row:
                _error(503,'undeclared_mutation')
            seen[key]=row
        for key,row in seen.items():
            if row_values(row)!=expected[key]: _error(503,'undeclared_mutation')

    def complete():
        if set(seen)!=set(expected): _error(503,'undeclared_mutation')
        for row in protected:
            if row is not None and row_values(row)!=expected_existing[id(row)]: _error(503,'undeclared_mutation')
    return check,complete


def validate_assessment_binding(context, mutation):
    action=TeachingAction(context.lock_plan.assessment.purpose)
    original,effects=validate_assessment_mutation(mutation,action)
    shape=context.assessment_shape; base=context.pre_mutation['assessment_baseline']; at=context.authorization.checked_at
    if isinstance(shape,RecoveryOnlyShape): _error(503,'invalid_mutation_result')
    appends,updates=_expected_business(context)
    if type(shape) in {AssignmentCreateShape,AssignmentUpdateShape,PrivateDraftUpdateShape}:
        expected={'assignment_id':shape.assignment_id,'draft_revision':1 if type(shape) is AssignmentCreateShape else shape.before_revision+1,'accepted_at':at}
    elif type(shape) is VersionCreateShape:
        expected={'assignment_id':shape.assignment_id,'version_id':shape.version_id,'version_number':shape.version_number,
            'source_draft_revision':shape.source_draft_revision,'public_spec_hash':_digest(base['assignment']['public_draft']),'frozen_at':at}
    elif type(shape) in {ReleasePreviewCreateShape,ReleaseCreateShape}:
        fields=appends[0][1]
        expected={key:fields[key] for key in ('assignment_id','version_id','public_spec_hash','recipient_count','recipient_digest','due_at','timezone','late_policy','policy_digest')}
        if type(shape) is ReleasePreviewCreateShape: expected.update(preview_id=shape.preview_id,expires_at=at+timedelta(minutes=15),accepted_at=at)
        else: expected.update(release_id=shape.release_id,released_at=at)
    elif type(shape) is SubmissionCreateShape:
        fields=appends[0][1]
        expected={key:fields[key] for key in ('release_id','version_id','parent_submission_id','sequence','content_hash','received_at')}
        expected['submission_id']=shape.submission_id
    else: _error(503,'invalid_mutation_result')
    if original!=_w()._canonical(expected): _error(503,'invalid_mutation_result')
    return original,effects


def build_assessment_event(receipt, context, mutation):
    original,effects=validate_assessment_binding(context,mutation)
    action=TeachingAction(context.lock_plan.assessment.purpose)
    if (receipt.actor_id!=context.authorization.actor_id or receipt.action!=action.value or receipt.scope_type!='offering'
            or receipt.institution_id!=context.scope.institution_id or receipt.scope_id!=context.scope.id
            or receipt.result_type!=mutation.result_type or receipt.result_id!=mutation.result_id
            or receipt.target_type!=mutation.result_type or receipt.target_id!=mutation.result_id
            or access._utc(receipt.accepted_at)!=context.authorization.checked_at or receipt.original_result!=original):
        _error(503,'invalid_mutation_result')
    return AssessmentEvent(id=str(uuid4()),receipt_id=receipt.id,institution_id=context.scope.institution_id,
        offering_id=context.scope.id,actor_id=context.authorization.actor_id,actor_role=context.authorization.account_role,
        action=action.value,target_type=mutation.result_type,target_id=mutation.result_id,revision_kind=mutation.revision_kind,
        before_revision=mutation.before_revision,after_revision=mutation.after_revision,
        occurred_at=context.authorization.checked_at,effect_metadata=effects)
