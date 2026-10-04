"""B2 source/synthetic contract tests; no production activation evidence."""
import importlib
import inspect
from datetime import datetime, timezone
from hashlib import sha256

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

NOW = datetime(2026, 10, 3, 12, 0, 0, 123456, tzinfo=timezone.utc)
ACTIONS = ('assignment_create', 'assignment_update', 'assignment_private_update', 'assignment_freeze', 'release_preview', 'release_create', 'submission_create')


def feature(name):
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        pytest.fail(f'B2 Task2 feature absent: {name}: {exc}')


def test_b2_actions_map_to_exact_event_kinds():
    t = feature('app.services.teaching.types')
    w = feature('app.services.teaching.writes')
    b = feature('app.services.teaching.assessment_writes')
    expected = dict(zip(ACTIONS, ('assignment_draft', 'assignment_draft', 'assignment_draft', 'assignment_version', 'release_preview', 'release', 'submission_head')))
    assert {a.value: value.revision_kind for a, value in b.ASSESSMENT_RESULTS.items()} == expected
    assert all(t.TeachingAction(value) in w.WRITE_ACTIONS for value in ACTIONS)
    s = feature('app.schemas.teaching')
    assert set(s.WriteActionName.__args__) == {a.value for a in w.WRITE_ACTIONS}


def test_raw_duplicate_subjects_rejected_before_canonical_hash():
    s = feature('app.schemas.teaching_assessment')
    with pytest.raises(ValidationError):
        s.ReleasePreviewCommand(version_id='v', student_ids=['学生', '学生'], due_at=None, late_policy='reject')
    w = feature('app.services.teaching.writes')
    t = feature('app.services.teaching.types')
    with pytest.raises(HTTPException) as caught:
        w.make_write_intent('owner', t.TeachingAction('release_preview'), t.ScopeRef('school', 'offering', 'o'), 'v', 'preview-1', dict(version_id='v', student_ids=['学生','学生'], due_at=None, late_policy='reject'))
    assert caught.value.status_code == 422


def test_permuted_submitted_subjects_hash_equally_without_alias_substitution():
    s = feature('app.schemas.teaching_assessment')
    w = feature('app.services.teaching.writes')
    t = feature('app.services.teaching.types')
    def digest(ids, due):
        command = s.ReleasePreviewCommand(version_id='v', student_ids=ids, due_at=due, late_policy='reject').model_dump()
        return w.canonical_request_hash(t.TeachingAction('release_preview'), t.ScopeRef('school','offering','o'), 'v', command)
    assert digest(['学生','A'], '2026-10-04T12:00:00Z') == digest(['A','学生'], '2026-10-04T12:00:00.000000+00:00')
    assert digest(['学生','a'], None) != digest(['学生','A'], None)


def test_b2_text_preserves_lines_without_relaxing_identifiers():
    s = feature('app.schemas.teaching_assessment')
    b1 = feature('app.schemas.teaching')
    text = '第一行\r\n\tprint("hello")\n'
    assert s.SubmissionContent(kind='code', language='python', text=text).text.encode() == text.encode()
    assert s.PublicSpec(title='Title', instructions=text, rubric=text, ai_policy='allowed').instructions == text
    for bad in [' x', 'x ', 'x\n', 'x\x00']:
        with pytest.raises(ValidationError):
            s.ReleasePreviewCommand(version_id='v', student_ids=[bad], due_at=None, late_policy='reject')
    with pytest.raises(ValidationError):
        b1.PageQuery(cursor='x\n')
    with pytest.raises(ValidationError):
        s.SubmissionContent(kind='text', language='python', text='x')
    with pytest.raises(ValidationError):
        s.SubmissionContent(kind='code', language='', text='x')
    with pytest.raises(ValidationError):
        s.SubmissionContent(kind='text', language=None, text='😀' * 65537)
    with pytest.raises(ValidationError):
        s.CreateSubmissionCommand(expected_parent_id=None, content={'kind':'text','language':None,'text':'x'}, ai_usage_declaration={'used_ai':False,'description':''}, student_id='victim')


@pytest.mark.parametrize('value', ['2026-10-04', '2026-10-04T12:00:00', '2026-10-04 12:00:00Z', '2026-10-04T12:00:00z', '2026-10-04T12:00:00-00:00', '2026-10-04T12:00:00+01:00', '2026-10-04T12:00:00.1234567Z', '2026-10-04T12:00:60Z', 123])
def test_strict_utc_rejects_ambiguous_wire(value):
    s = feature('app.schemas.teaching_assessment')
    with pytest.raises(ValidationError):
        s.ReleasePreviewCommand(version_id='v', student_ids=['learner'], due_at=value, late_policy='reject')


def test_acceptance_rejects_wrong_action_extra_content_and_effects():
    b = feature('app.services.teaching.assessment_writes')
    w = feature('app.services.teaching.writes')
    t = feature('app.services.teaching.types')
    result = t.MutationResult('assignment','a', {'assignment_id':'a','draft_revision':1,'accepted_at':NOW}, 'assignment_draft',0,1, {'assignment_id':'a','draft_revision':1}, 201)
    assert w._validate_mutation(result, action=t.TeachingAction('assignment_create'))[0]['assignment_id'] == 'a'
    from dataclasses import replace
    for invalid in [replace(result, original_result={**result.original_result,'private_spec_hash':'a'*64}), replace(result, effect_metadata={**result.effect_metadata,'content':'secret'}), replace(result, revision_kind='course')]:
        with pytest.raises(HTTPException) as caught:
            w._validate_mutation(invalid, action=t.TeachingAction('assignment_create'))
        assert caught.value.detail == 'invalid_mutation_result'
    with pytest.raises(HTTPException):
        w._validate_mutation(result, action=t.TeachingAction('submission_create'))


def test_b1_hashes_and_event_shape_are_unchanged():
    w = feature('app.services.teaching.writes')
    t = feature('app.services.teaching.types')
    import json
    command = {'student_ids':['b','a','a'], 'reason':'ordinary'}
    expected = {'version':1,'action':'roster_manage','scope_type':'offering','scope_id':'o','target_id':'o','command':{'student_ids':['a','b'],'reason':'ordinary'}}
    assert w.canonical_request_hash(t.TeachingAction.ROSTER_MANAGE, t.ScopeRef('school','offering','o'), 'o', command) == sha256(json.dumps(expected,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    result = t.MutationResult('roster','o',{'id':'o'},'roster',0,1,{'count':1},200)
    assert w._validate_mutation(result, action=t.TeachingAction.ROSTER_MANAGE) == ({'id':'o'},{'count':1})
    with pytest.raises(HTTPException):
        w._validate_mutation(t.MutationResult('submission','s',{},'submission_head',0,1,{},201), action=t.TeachingAction.ROSTER_MANAGE)


def test_real_production_write_gate_still_refuses():
    w = feature('app.services.teaching.writes')
    with pytest.raises(HTTPException) as caught:
        w._require_write_safety(None)
    assert (caught.value.status_code, caught.value.detail) == (503, 'write_safety_unproven')


def test_closed_shapes_have_no_generic_append_authority():
    import dataclasses
    b = feature('app.services.teaching.assessment_types')
    names = ('AssignmentCreateShape','AssignmentUpdateShape','PrivateDraftUpdateShape','VersionCreateShape','ReleasePreviewCreateShape','ReleaseCreateShape','SubmissionCreateShape','RecoveryOnlyShape')
    assert {item.__name__ for item in b.AssessmentMutationShape.__args__} == set(names)
    for name in names:
        cls = getattr(b, name)
        assert cls.__dataclass_params__.frozen
        assert not {'models','allow_append','callback','loader'} & {f.name for f in dataclasses.fields(cls)}

from tests.test_teaching_assessment_authorization import b2case, PUBLIC, PRIVATE, policy, denied, read


class OrdinaryOperation:
    """Valid finite business writes for engine integration, not B2 services."""
    def collect_locks(self, session, intent, roots, preview_footprint=None):
        b=feature('app.services.teaching.assessment_writes')
        assert preview_footprint is None
        return b.assessment_lock_plan(roots,intent,b.collect_assessment_spec(session,intent,roots))

    def validate_new(self, context, command, at):
        assert context.preview is None and context.preview_footprint is None

    def apply_new(self, context, command, at):
        from datetime import timedelta
        w=feature('app.services.teaching.writes'); b=feature('app.models.teaching_assessment'); t=feature('app.services.teaching.types')
        q=context.assessment_shape; rows=context.assessment; actor=context.authorization.actor_id
        action=context.lock_plan.assessment.purpose
        scope={'institution_id':context.scope.institution_id,'offering_id':context.scope.id}
        plain=lambda value:__import__('json').loads(w._json(value))
        digest=lambda value:sha256(w._json(value).encode()).hexdigest()
        if action=='assignment_create':
            context.session.add(b.Assignment(id=q.assignment_id,**scope,public_draft=plain(command['public_spec']),draft_revision=1,next_version_number=1,created_by=actor,created_at=at,updated_at=at))
            context.session.add(b.AssignmentDraftPrivate(assignment_id=q.assignment_id,**scope,private_draft={'answer_text':'','private_test_notes':''},updated_at=at))
            original={'assignment_id':q.assignment_id,'draft_revision':1,'accepted_at':at}; before=0; kind='assignment_draft'; result_type='assignment'; identifier=q.assignment_id
        elif action in {'assignment_update','assignment_private_update'}:
            before=q.before_revision
            rows.assignment.draft_revision=before+1; rows.assignment.updated_at=at
            if action=='assignment_update': rows.assignment.public_draft=plain(command['public_spec'])
            else: rows.draft_private.private_draft=plain(command['private_spec']); rows.draft_private.updated_at=at
            original={'assignment_id':q.assignment_id,'draft_revision':before+1,'accepted_at':at}; kind='assignment_draft'; result_type='assignment' if action=='assignment_update' else 'assignment_private'; identifier=q.assignment_id
        elif action=='assignment_freeze':
            context.session.add(b.AssignmentVersion(id=q.version_id,assignment_id=q.assignment_id,**scope,version_number=q.version_number,source_draft_revision=q.source_draft_revision,public_spec=plain(rows.assignment.public_draft),public_spec_hash=digest(rows.assignment.public_draft),frozen_by=actor,frozen_at=at))
            context.session.add(b.PrivateSpec(version_id=q.version_id,assignment_id=q.assignment_id,**scope,private_spec=plain(rows.draft_private.private_draft),private_spec_hash=digest(rows.draft_private.private_draft)))
            rows.assignment.next_version_number=q.version_number+1
            original={'assignment_id':q.assignment_id,'version_id':q.version_id,'version_number':q.version_number,'source_draft_revision':q.source_draft_revision,'public_spec_hash':digest(rows.assignment.public_draft),'frozen_at':at}; before=q.version_number-1; kind='assignment_version'; result_type='assignment_version'; identifier=q.version_id
        elif action=='release_preview':
            audience=[{'student_id':r.student_id,'enrollment_id':r.enrollment_id,'enrollment_revision':r.enrollment_revision} for r in q.audience]
            due=feature('app.schemas.teaching_assessment').parse_assessment_utc(command['due_at'])
            fields={'assignment_id':q.assignment_id,'version_id':q.version_id,'public_spec_hash':rows.version.public_spec_hash,'recipient_count':len(audience),'recipient_digest':digest({'version':1,'recipients':audience}),'due_at':due,'timezone':context.offering.timezone,'late_policy':'reject','policy_digest':digest({'version':1,'due_at':due,'timezone':context.offering.timezone,'late_policy':'reject'})}
            context.session.add(b.ReleasePreview(id=q.preview_id,**scope,**fields,actor_id=actor,actor_role_id=context.authorization.role_id,actor_role_revision=context.authorization.role_revision,offering_revision=context.offering.revision,roster_revision=context.offering.roster_revision,source_policy_digest=context.policy.digest,recipient_snapshot=audience,created_at=at,expires_at=at+timedelta(minutes=15)))
            original={**fields,'preview_id':q.preview_id,'expires_at':at+timedelta(minutes=15),'accepted_at':at}; before=0; kind='release_preview'; result_type='release_preview'; identifier=q.preview_id
        elif action=='release_create':
            p=rows.release_preview
            fields={name:getattr(p,name) for name in ['assignment_id','version_id','public_spec_hash','recipient_count','recipient_digest','due_at','timezone','late_policy','policy_digest']}
            context.session.add(b.Release(id=q.release_id,**scope,**fields,preview_id=p.id,released_by=actor,released_at=at))
            for r in q.audience:
                context.session.add(b.ReleaseRecipient(release_id=q.release_id,**scope,version_id=q.version_id,student_id=r.student_id,enrollment_id=r.enrollment_id,enrollment_revision_at_release=r.enrollment_revision,accepted_policy_digest=context.policy.digest))
                context.session.add(b.SubmissionHead(release_id=q.release_id,**scope,version_id=q.version_id,student_id=r.student_id,submission_id=None,revision=0))
            original={**fields,'release_id':q.release_id,'released_at':at}; before=0; kind='release'; result_type='release'; identifier=q.release_id
        else:
            content=plain(command['content']); content_hash=sha256(content['text'].encode()).hexdigest()
            context.session.add(b.Submission(id=q.submission_id,**scope,release_id=q.release_id,version_id=q.version_id,student_id=q.student_id,parent_submission_id=q.parent_submission_id,sequence=q.sequence,content=content,content_hash=content_hash,ai_usage_declaration=plain(command['ai_usage_declaration']),received_at=at))
            rows.head.submission_id=q.submission_id; rows.head.revision=q.sequence
            original={'submission_id':q.submission_id,'release_id':q.release_id,'version_id':q.version_id,'parent_submission_id':q.parent_submission_id,'sequence':q.sequence,'content_hash':content_hash,'received_at':at}; before=q.sequence-1; kind='submission_head'; result_type='submission'; identifier=q.submission_id
        descriptor=feature('app.services.teaching.assessment_writes').ASSESSMENT_RESULTS[t.TeachingAction(action)]
        effects={name:original[name] for name in descriptor.effect_fields}
        return t.MutationResult(result_type,identifier,original,kind,before,before+1,effects,201)


def command_for(case,action):
    db,a,aa,w,t,m,b,*_=case
    if action=='assignment_create': return 'owner',None,{'public_spec':PUBLIC}
    if action=='assignment_update': return 'owner','a',{'expected_revision':3,'public_spec':{**PUBLIC,'title':'New'}}
    if action=='assignment_private_update': return 'owner','a',{'expected_revision':3,'private_spec':{'answer_text':'new answer','private_test_notes':''}}
    if action=='assignment_freeze': return 'owner','a',{'expected_revision':3}
    if action=='release_preview': return 'owner','a',{'version_id':'v2','student_ids':['learner','assistant'],'due_at':None,'late_policy':'reject'}
    if action=='release_create':
        p=db.get(b.ReleasePreview,'p2')
        return 'owner','a',{'preview_id':'p2','version_id':'v2','public_spec_hash':p.public_spec_hash,'recipient_count':p.recipient_count,'recipient_digest':p.recipient_digest,'policy_digest':p.policy_digest,'confirmed':True}
    return 'learner','r',{'expected_parent_id':'s','content':{'kind':'code','language':'python','text':'print("hi")\r\n'},'ai_usage_declaration':{'used_ai':False,'description':''}}


def run_ordinary(case, action, *, key='ordinary-key', command=None):
    db,a,aa,w,t,*_=case
    actor,target,payload=command or command_for(case,action)
    intent=w.make_write_intent(actor,t.TeachingAction(action),t.ScopeRef('school','offering','o'),target,key,payload)
    from tests.test_teaching_bounded_write_finalization import accept_pending
    return accept_pending(db,w.execute_write(db,intent,intent.scope,OrdinaryOperation()),intent),intent


@pytest.mark.parametrize('action',ACTIONS)
def test_ordinary_acceptance_uses_exact_b2_event_and_original_receipt(b2case,action):
    from tests.test_teaching_bounded_write_finalization import accept_pending
    db,a,aa,w,t,m,b,*_=b2case
    first,intent=run_ordinary(b2case,action)
    assert not first.replayed
    event=db.query(b.AssessmentEvent).filter_by(receipt_id=first.receipt.id).one()
    assert event.action==action and event.target_id==first.receipt.result_id
    assert event.actor_id==first.receipt.original_result.get('actor_id',intent.actor_id)
    assert event.institution_id==intent.scope.institution_id and event.offering_id==intent.scope.id
    assert db.query(m.AccessEvent).count()==0
    replay=accept_pending(db,w.execute_write(db,intent,intent.scope,OrdinaryOperation()),intent)
    assert replay.replayed and replay.receipt.id==first.receipt.id and replay.result==first.result
    assert db.query(b.AssessmentEvent).count()==1


def test_b2_preview_uses_only_assessment_loader(b2case):
    result,_=run_ordinary(b2case,'release_create')
    assert result.result['version_id']=='v2'


def test_b1_preview_cannot_substitute_for_release_preview(b2case):
    from datetime import timedelta
    db,a,aa,w,t,m,*_=b2case
    actor,target,command=command_for(b2case,'release_create')
    db.add(m.RosterPreview(id='b1-only',institution_id='school',offering_id='o',actor_id='owner',actor_role_id='role-owner',actor_role_revision=1,expected_roster_revision=1,offering_revision=1,mode='merge',canonical_command={},command_hash='a'*64,source_policy_digest='b'*64,target_ids=['learner'],add_ids=[],keep_ids=['learner'],update_ids=[],withdraw_ids=[],validation_issues=[],target_digest='c'*64,withdrawals_digest='d'*64,withdrawals_count=0,can_apply=True,created_at=NOW,expires_at=NOW+timedelta(minutes=15)))
    db.commit()
    denied(lambda:run_ordinary(b2case,'release_create',command=(actor,target,{**command,'preview_id':'b1-only'})),404)


def test_all_business_append_identities_precede_clock():
    w=feature('app.services.teaching.writes')
    source=inspect.getsource(w._collect_locked_context)
    assert source.index('allocate_assessment_shape(')<source.index('_server_clock(')
    b=feature('app.services.teaching.assessment_writes')
    assert 'uuid4' in inspect.getsource(b.allocate_assessment_shape)


def test_accepted_receipt_has_empty_business_shape(b2case):
    from dataclasses import replace
    db,a,aa,w,t,*_=b2case
    first,intent=run_ordinary(b2case,'assignment_create')
    context=w._lock_context(db,intent.actor_id,intent.action,intent.scope,intent=intent,mutation=OrdinaryOperation(),write=True)
    shapes=feature('app.services.teaching.assessment_types')
    assert isinstance(context.assessment_shape,shapes.RecoveryOnlyShape)
    assert context.assessment_receipt.mode=='existing'


def test_declared_b2_scope_is_complete_before_clock(b2case):
    db,a,aa,w,t,*_=b2case
    actor,target,command=command_for(b2case,'submission_create')
    intent=w.make_write_intent(actor,t.TeachingAction('submission_create'),t.ScopeRef('school','offering','o'),target,'footprint-key',command)
    context=w._lock_context(db,actor,intent.action,intent.scope,intent=intent,mutation=OrdinaryOperation(),write=True)
    assert context.assessment.assignment.id=='a' and context.assessment.version.id=='v'
    assert context.assessment.release.id=='r' and context.assessment.head.student_id=='learner'
    assert context.assessment.parent_submission.id=='s'
    assert context.preview is None and context.lock_plan.preview_id is None
    assert context.assessment_shape.parent_submission_id=='s' and context.assessment_shape.sequence==2


def test_cross_route_assignment_is_part_of_request_hash(b2case):
    db,a,aa,w,t,*_=b2case
    actor,target,command=command_for(b2case,'release_preview')
    first=w.make_write_intent(actor,t.TeachingAction('release_preview'),t.ScopeRef('school','offering','o'),target,'route-key',command)
    second=w.make_write_intent(actor,first.action,first.scope,'another-assignment','route-key',command)
    assert first.request_hash!=second.request_hash
    denied(lambda:w.execute_write(db,second,second.scope,OrdinaryOperation()),404)


def test_release_recovery_ignores_later_deadline_archive_and_old_recipient_validity(b2case):
    from sqlalchemy import update
    from tests.test_teaching_bounded_write_finalization import accept_pending
    db,a,aa,w,t,m,b,accounts,*_=b2case
    result,intent=run_ordinary(b2case,'release_preview')
    db.execute(update(m.Offering).where(m.Offering.id=='o').values(state='archived')); db.commit()
    db.info['teaching_policy_provider']=lambda:policy(t,roster=[])
    replay=accept_pending(db,w.execute_write(db,intent,intent.scope,OrdinaryOperation()),intent)
    assert replay.receipt.id==result.receipt.id and replay.result==result.result
    assert w.get_receipt(db,'owner',result.receipt.id).result==result.result


def test_new_invalid_audience_fails_after_current_authority(b2case):
    actor,target,command=command_for(b2case,'release_preview')
    denied(lambda:run_ordinary(b2case,'release_preview',command=(actor,target,{**command,'student_ids':['outsider']})),422,'unavailable_or_out_of_scope')
    denied(lambda:run_ordinary(b2case,'release_preview',command=('releaser',target,{**command,'student_ids':['outsider']})),422,'unavailable_or_out_of_scope')


def test_changed_valid_retry_resolves_original_summary_before_audience_or_hash(b2case):
    db,a,aa,w,t,m,b,*_=b2case
    first,intent=run_ordinary(b2case,'release_preview')
    db.info['teaching_policy_provider']=lambda:policy(t,roster=[])
    actor,target,command=command_for(b2case,'release_preview')
    changed={**command,'student_ids':['no-current-account'],'due_at':'2020-01-01T00:00:00Z'}
    denied(lambda:run_ordinary(b2case,'release_preview',command=(actor,target,changed)),409,'idempotency_conflict')
    assert w.get_receipt(db,actor,first.receipt.id).result==first.result


def test_submission_recovery_returns_older_acceptance_after_new_head_and_archive(b2case):
    from sqlalchemy import update
    from tests.test_teaching_bounded_write_finalization import accept_pending
    db,a,aa,w,t,m,b,*_=b2case
    first,intent=run_ordinary(b2case,'submission_create')
    actor,target,command=command_for(b2case,'submission_create')
    later,_=run_ordinary(b2case,'submission_create',key='later-key',command=(actor,target,{**command,'expected_parent_id':first.result['submission_id']}))
    assert later.result['sequence']==3
    db.execute(update(m.Offering).where(m.Offering.id=='o').values(state='archived')); db.commit()
    assert w.get_receipt(db,actor,first.receipt.id).result==first.result
    assert accept_pending(db,w.execute_write(db,intent,intent.scope,OrdinaryOperation()),intent).result==first.result


def test_frozen_receipt_uses_original_private_status_not_mutable_draft(b2case):
    from sqlalchemy import update
    from tests.test_teaching_assessment_authorization import seed_receipt
    db,a,aa,w,t,m,b,*_=b2case
    row=db.get(b.AssignmentVersion,'v2')
    receipt=seed_receipt(b2case,'owner','assignment_freeze','assignment_version','v2',{'assignment_id':'a','version_id':'v2','version_number':2,'source_draft_revision':2,'public_spec_hash':row.public_spec_hash,'frozen_at':NOW.isoformat().replace('+00:00','Z')})
    db.execute(update(m.TeachingRole).where(m.TeachingRole.subject_id=='owner').values(permissions=['AUTHOR'])); db.commit()
    assert w.get_receipt(db,'owner',receipt.id).result['version_id']=='v2'
    denied(lambda:run_ordinary(b2case,'assignment_freeze'),403)


def test_receipt_projection_matches_immutable_target_chain(b2case):
    from tests.test_teaching_assessment_authorization import seed_receipt
    db,a,aa,w,t,m,b,*_=b2case
    receipt=seed_receipt(b2case,'learner','submission_create','submission','s',{'submission_id':'s','release_id':'another-release','version_id':'v','parent_submission_id':None,'sequence':1,'content_hash':sha256(b'Original').hexdigest(),'received_at':NOW.isoformat().replace('+00:00','Z')})
    denied(lambda:w.get_receipt(db,'learner',receipt.id),503,'invalid_assessment_state')


def test_confirmation_expiry_precedes_deadline_and_new_preview_deadline_is_strict(b2case):
    from sqlalchemy import update
    from datetime import timedelta
    db,a,aa,w,t,m,b,*_=b2case
    actor,target,command=command_for(b2case,'release_preview')
    denied(lambda:run_ordinary(b2case,'release_preview',command=(actor,target,{**command,'due_at':NOW})),409,'deadline_closed')
    # Ordinary fixture setup represents an already expired immutable preview;
    # this is not a production update operation or a callback probe.
    db.execute(update(b.ReleasePreview).where(b.ReleasePreview.id=='p2').values(created_at=NOW-timedelta(minutes=30),expires_at=NOW-timedelta(minutes=15),due_at=NOW-timedelta(minutes=20))); db.commit()
    denied(lambda:run_ordinary(b2case,'release_create'),409,'preview_expired')


@pytest.mark.parametrize('entrypoint',['loader','allocation'])
def test_missing_loaded_actor_is_typed_denial(b2case,entrypoint):
    """Direct missing-context handling; no deletion, race or callback variant."""
    from dataclasses import replace
    db,a,aa,w,t,*_=b2case
    boundary=feature('app.services.teaching.assessment_writes')
    if entrypoint=='loader':
        scope,ref=aa.resolve_assessment_object(db,'owner','release','r')
        context=w._lock_context(db,'owner',t.TeachingAction('release_read'),scope,object_ref=ref)
        missing=replace(context,actor_account=None)
        denied(lambda:boundary.lock_assessment_rows(db,missing,context.lock_plan.assessment,None),401,'invalid_current_account')
    else:
        actor,target,command=command_for(b2case,'submission_create')
        intent=w.make_write_intent(actor,t.TeachingAction('submission_create'),t.ScopeRef('school','offering','o'),target,'missing-actor-key',command)
        context=w._lock_context(db,actor,intent.action,intent.scope,intent=intent,mutation=OrdinaryOperation(),write=True)
        missing=replace(context,actor_account=None)
        denied(lambda:boundary.allocate_assessment_shape(missing,intent.action,intent.canonical_payload),401,'invalid_current_account')
