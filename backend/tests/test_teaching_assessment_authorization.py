"""Ordinary B2 current authority tests; synthetic SQLite only."""
import importlib

import pytest


def feature(name):
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        pytest.fail(f'B2 Task2 feature absent: {name}: {exc}')


def test_finite_actions_do_not_alias_reserved_b3_permissions():
    t = feature('app.services.teaching.types')
    expected = {'assignment_create','assignment_update','assignment_private_update','assignment_freeze','release_preview','release_create','submission_create','assignment_read','assignment_list','assignment_versions_list','assignment_version_read','assignment_private_read','release_read','submission_read','submission_list','release_preview_read'}
    assert expected <= {a.value for a in t.TeachingAction}
    assert {t.TeachingAction.AUTHOR,t.TeachingAction.RELEASE,t.TeachingAction.REVIEW,t.TeachingAction.PUBLISH}.isdisjoint(t.ASSESSMENT_ACTIONS)

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256

from fastapi import HTTPException
from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session

NOW = datetime(2026,10,3,12,0,0,123456,tzinfo=timezone.utc)
PUBLIC = {'title':'Frozen public','instructions':'Read\nthen write','rubric':'Explain','ai_policy':'allowed'}
PRIVATE = {'answer_text':'private answer','private_test_notes':''}


def policy(t, *, enabled=True, assignments=True, roster=None, generation='b2-test'):
    members = ['learner','assistant','assigned'] if roster is None else roster
    grants = {
        'releaser': {'account_role':'teacher','permissions':['RELEASE'],'scope':'offering'},
        'viewer': {'account_role':'teacher','permissions':['SUBMISSION_VIEW'],'scope':'offering'},
        'assistant': {'account_role':'teacher','permissions':['AUTHOR','PRIVATE_SPEC_VIEW'],'scope':'offering'},
        'assigned': {'account_role':'student','permissions':['AUTHOR'],'scope':'assigned'},
    }
    return t.TeachingPolicyInputs(institution_id='school',enabled=enabled,assignments_enabled=assignments,
        trusted_roster_json=json.dumps({'owner':members,'releaser':members,'viewer':members,'assistant':members}),
        trusted_delegations_json=json.dumps({'owner':grants}),generation=generation)


def _b2case_data(monkeypatch):
    # Exactly five parent-approved function-scoped synthetic substitutions.
    # Real identity, source policy, object loaders, mutations and events remain.
    a = feature('app.services.teaching.access')
    aa = feature('app.services.teaching.assessment_access')
    w = feature('app.services.teaching.writes')
    t = feature('app.services.teaching.types')
    m = feature('app.models.teaching')
    b = feature('app.models.teaching_assessment')
    accounts = feature('app.models.user_account')
    ledger = feature('app.models.teaching_schema')
    schema = feature('app.services.teaching.schema')
    bs = feature('app.services.teaching.assessment_schema')
    originals = {'b1':a.require_teaching_schema,'b2':aa.require_assessment_schema,
        'transaction':w._require_transaction,'hardgate':w._require_write_safety}
    monkeypatch.setattr(a,'require_teaching_schema',lambda session:None)
    monkeypatch.setattr(aa,'require_assessment_schema',lambda session:None)
    monkeypatch.setattr(w,'_require_transaction',lambda session:None)
    monkeypatch.setattr(w,'_require_write_safety',lambda session:None)
    monkeypatch.setattr(w,'_server_clock',lambda session:NOW)
    engine = create_engine('sqlite:///:memory:')
    db = None
    try:
        tables = [accounts.UserAccount.__table__] + list(schema.b1_tables()) + list(bs.b2_tables())
        accounts.UserAccount.metadata.create_all(engine,tables=tables)
        db = Session(engine,autoflush=False)
        db.add_all([ledger.TeachingSchemaVersion(component='b1',version=1,contract_hash=schema.B1_CONTRACT_HASH,completed_at=NOW),ledger.TeachingSchemaVersion(component='b2',version=1,contract_hash=bs.B2_CONTRACT_HASH,completed_at=NOW)])
        for subject in ['owner','releaser','viewer','assistant','learner','assigned','outsider']:
            db.add(accounts.UserAccount(username=subject,role='student' if subject in {'learner','assigned'} else 'teacher',password_hash='synthetic-only'))
        for inst, cid, oid in [('school','c','o'),('foreign','fc','fo')]:
            db.add(m.Course(id=cid,institution_id=inst,source_teacher_id='owner',title='Course',code='C',description='',timezone='UTC',revision=1,created_at=NOW,updated_at=NOW)); db.flush()
            db.add(m.Offering(id=oid,institution_id=inst,course_id=cid,title='Offering',term='2026',timezone='UTC',state='active',revision=1,roster_revision=1,created_at=NOW,updated_at=NOW)); db.flush()
        for subject, permissions, scope in [('owner',[p.value for p in t.Permission],'offering'),('releaser',['RELEASE'],'offering'),('viewer',['SUBMISSION_VIEW'],'offering'),('assistant',['AUTHOR','PRIVATE_SPEC_VIEW'],'offering'),('assigned',['AUTHOR'],'assigned')]:
            db.add(m.TeachingRole(id='role-'+subject,institution_id='school',offering_id='o',subject_id=subject,granted_account_role='student' if subject=='assigned' else 'teacher',label='assistant' if subject=='assigned' else 'teacher',permissions=sorted(permissions),scope=scope,status='active',effective_from=NOW-timedelta(days=1),revision=1,source_policy_digest='a'*64,created_at=NOW,updated_at=NOW))
        for subject in ['learner','assistant','assigned']:
            db.add(m.Enrollment(id='enroll-'+subject,institution_id='school',offering_id='o',student_id=subject,status='active',effective_from=NOW-timedelta(days=1),revision=1,source_kind='deployment_roster',source_teacher_id='owner',source_policy_digest='a'*64,created_at=NOW,updated_at=NOW))
        db.add(b.Assignment(id='a',institution_id='school',offering_id='o',public_draft=PUBLIC,draft_revision=3,next_version_number=3,created_by='owner',created_at=NOW,updated_at=NOW)); db.flush()
        db.add(b.AssignmentDraftPrivate(assignment_id='a',institution_id='school',offering_id='o',private_draft=PRIVATE,updated_at=NOW))
        db.add(b.Assignment(id='fa',institution_id='foreign',offering_id='fo',public_draft=PUBLIC,draft_revision=1,next_version_number=1,created_by='owner',created_at=NOW,updated_at=NOW))
        public_hash = sha256(w._json(PUBLIC).encode()).hexdigest()
        for vid, num in [('v',1),('v2',2)]:
            db.add(b.AssignmentVersion(id=vid,assignment_id='a',institution_id='school',offering_id='o',version_number=num,source_draft_revision=num,public_spec=PUBLIC,public_spec_hash=public_hash,frozen_by='owner',frozen_at=NOW)); db.flush()
            private = PRIVATE if vid=='v' else {'answer_text':'','private_test_notes':''}
            db.add(b.PrivateSpec(version_id=vid,assignment_id='a',institution_id='school',offering_id='o',private_spec=private,private_spec_hash=sha256(w._json(private).encode()).hexdigest()))
        audience = [{'student_id':subject,'enrollment_id':'enroll-'+subject,'enrollment_revision':1} for subject in ['assistant','learner']]
        recipient_digest = sha256(w._json({'version':1,'recipients':audience}).encode()).hexdigest()
        policy_digest = sha256(w._json({'version':1,'due_at':None,'timezone':'UTC','late_policy':'reject'}).encode()).hexdigest()
        for pid, vid in [('p','v'),('p2','v2')]:
            db.add(b.ReleasePreview(id=pid,assignment_id='a',version_id=vid,institution_id='school',offering_id='o',actor_id='owner',actor_role_id='role-owner',actor_role_revision=1,offering_revision=1,roster_revision=1,source_policy_digest=feature('app.services.teaching.policy').read_teaching_policy(policy(t),'owner',actor_id='owner').digest,recipient_snapshot=audience,recipient_count=2,recipient_digest=recipient_digest,public_spec_hash=public_hash,due_at=None,timezone='UTC',late_policy='reject',policy_digest=policy_digest,created_at=NOW,expires_at=NOW+timedelta(minutes=15)))
        db.flush()
        db.add(b.Release(id='r',assignment_id='a',version_id='v',institution_id='school',offering_id='o',preview_id='p',public_spec_hash=public_hash,recipient_count=2,recipient_digest=recipient_digest,due_at=None,timezone='UTC',late_policy='reject',policy_digest=policy_digest,released_by='owner',released_at=NOW)); db.flush()
        for subject in ['assistant','learner']:
            db.add(b.ReleaseRecipient(release_id='r',institution_id='school',offering_id='o',version_id='v',student_id=subject,enrollment_id='enroll-'+subject,enrollment_revision_at_release=1,accepted_policy_digest='a'*64)); db.flush()
            db.add(b.SubmissionHead(release_id='r',institution_id='school',offering_id='o',version_id='v',student_id=subject,submission_id=None,revision=0))
        db.add(b.Submission(id='s',institution_id='school',offering_id='o',release_id='r',version_id='v',student_id='learner',parent_submission_id=None,sequence=1,content={'kind':'text','language':None,'text':'Original'},content_hash=sha256(b'Original').hexdigest(),ai_usage_declaration={'used_ai':False,'description':''},received_at=NOW)); db.flush()
        head = db.get(b.SubmissionHead,('r','learner')); head.submission_id='s'; head.revision=1
        db.commit()
        db.info['teaching_policy_provider'] = lambda:policy(t)
        yield db,a,aa,w,t,m,b,accounts,originals
    finally:
        if db is not None:
            db.close()
        engine.dispose()


@pytest.fixture
def b2case(monkeypatch):
    # Defer absent-feature assertions into the test body so RED is a failure,
    # never a setup/collection error. The same generator owns scoped teardown.
    builder = _b2case_data(monkeypatch)
    class LazyCase:
        value = None
        def __iter__(self):
            if self.value is None:
                self.value = next(builder)
            return iter(self.value)
    try:
        yield LazyCase()
    finally:
        builder.close()


def denied(call, status=None, detail=None):
    with pytest.raises(HTTPException) as caught:
        call()
    if status is not None: assert caught.value.status_code==status
    if detail is not None: assert caught.value.detail==detail


def read(case, actor, action, kind, identifier):
    db,a,aa,w,t,*_ = case
    scope, ref = aa.resolve_assessment_object(db,actor,kind,identifier)
    assert scope.kind=='offering'
    return aa.authorize_assessment_read(db,actor,t.TeachingAction(action),ref)


def test_b2_disabled_and_uninstalled_are_explicit(b2case):
    db,a,aa,w,t,m,b,accounts,originals = b2case
    db.info['teaching_policy_provider']=lambda:policy(t,assignments=False)
    denied(lambda:read(b2case,'owner','assignment_read','assignment','a'),503,'assessment_disabled')
    db.info['teaching_policy_provider']=lambda:policy(t,enabled=False)
    denied(lambda:read(b2case,'owner','assignment_read','assignment','a'),503,'feature_disabled')
    db.info['teaching_policy_provider']=lambda:policy(t)
    for name in ['b1','b2']:
        with pytest.raises(feature('app.services.teaching.schema').TeachingSchemaError): originals[name](db)
    denied(lambda:originals['transaction'](db),503,'lock_orchestration_required')
    denied(lambda:originals['hardgate'](db),503,'write_safety_unproven')
    report=feature('app.services.teaching.assessment_schema').inspect_assessment_schema(db.connection())
    assert report.shape_valid and not report.mysql_verified and not report.ready


def test_foreign_chain_and_guess_id_are_hidden(b2case):
    for identifier in ['missing','fa','a\n']:
        denied(lambda:read(b2case,'owner','assignment_read','assignment',identifier),404)
    denied(lambda:read(b2case,'outsider','assignment_read','assignment','a'),404)


def test_teacher_role_requires_local_permission_and_ceiling(b2case):
    db,a,aa,w,t,m,*_ = b2case
    decision,rows=read(b2case,'owner','assignment_read','assignment','a')
    assert t.Permission.AUTHOR in decision.permissions and rows.assignment.id=='a'
    db.execute(update(m.TeachingRole).where(m.TeachingRole.subject_id=='owner').values(status='revoked')); db.commit()
    denied(lambda:read(b2case,'owner','assignment_read','assignment','a'),403)
    db.info['teaching_policy_provider']=lambda:replace(policy(t,roster=[]),trusted_delegations_json='{}')
    denied(lambda:read(b2case,'assistant','assignment_read','assignment','a'),404)


def test_assigned_and_b3_actions_remain_denied(b2case):
    db,a,aa,w,t,*_=b2case
    denied(lambda:read(b2case,'assigned','assignment_read','assignment','a'),403)
    for action in [t.TeachingAction.AUTHOR,t.TeachingAction.RELEASE,t.TeachingAction.REVIEW,t.TeachingAction.PUBLISH]:
        denied(lambda:a.authorize_action(db,'owner',action,t.ScopeRef('school','offering','o')),403,'assessment_stage_unavailable')


def test_recipient_membership_does_not_replace_current_access(b2case):
    db,a,aa,w,t,m,b,*_=b2case
    assert read(b2case,'learner','release_read','release','r')[0].learning
    db.execute(update(m.Enrollment).where(m.Enrollment.student_id=='learner').values(status='withdrawn')); db.commit()
    denied(lambda:read(b2case,'learner','release_read','release','r'),404)
    assert db.get(b.ReleaseRecipient,('r','learner')) is not None
    assert read(b2case,'viewer','submission_read','submission','s')[1].target_submission.id=='s'


def test_private_permission_is_independent(b2case):
    assert read(b2case,'releaser','assignment_version_read','version','v')[1].version.id=='v'
    denied(lambda:read(b2case,'releaser','assignment_private_read','version','v'),403)
    assert read(b2case,'owner','assignment_private_read','version','v')[1].private_spec.private_spec==PRIVATE


def test_dual_role_learner_cannot_read_private_answers(b2case):
    denied(lambda:read(b2case,'assistant','assignment_private_read','version','v'),403,'private_conflict')
    denied(lambda:read(b2case,'assistant','assignment_private_read','assignment','a'),403,'private_conflict')


def seed_receipt(case, actor, action, result_type, result_id, original):
    db,a,aa,w,t,m,b,*_=case
    receipt=m.WriteReceipt(id='receipt-'+result_id,institution_id='school',actor_id=actor,action=action,scope_type='offering',scope_id='o',target_type=result_type,target_id=result_id,idempotency_key='accepted-'+result_id,canonicalization_version=1,request_hash='b'*64,result_type=result_type,result_id=result_id,accepted_at=NOW,http_status=201,original_result=original)
    db.add(receipt); db.commit()
    return receipt


def test_submit_receipt_requires_original_actor_and_current_recipient(b2case):
    db,a,aa,w,t,m,b,*_=b2case
    receipt=seed_receipt(b2case,'learner','submission_create','submission','s',{'submission_id':'s','release_id':'r','version_id':'v','parent_submission_id':None,'sequence':1,'content_hash':sha256(b'Original').hexdigest(),'received_at':NOW.isoformat().replace('+00:00','Z')})
    assert w.get_receipt(db,'learner',receipt.id).result['submission_id']=='s'
    denied(lambda:w.get_receipt(db,'owner',receipt.id),404)
    db.execute(update(m.Enrollment).where(m.Enrollment.student_id=='learner').values(status='withdrawn')); db.commit()
    denied(lambda:w.get_receipt(db,'learner',receipt.id),404)
    denied(lambda:w.find_receipt(db,'learner',t.TeachingAction('submission_create'),t.ScopeRef('school','offering','o'),'accepted-s'),404)


def test_release_receipt_is_summary_not_recipient_read_authority(b2case):
    db,a,aa,w,t,m,b,*_=b2case
    row=db.get(b.Release,'r')
    original={key:getattr(row,key) for key in ['assignment_id','version_id','public_spec_hash','recipient_count','recipient_digest','due_at','timezone','late_policy','policy_digest']}
    original.update(release_id='r',released_at=NOW.isoformat().replace('+00:00','Z'))
    receipt=seed_receipt(b2case,'owner','release_create','release','r',original)
    db.info['teaching_policy_provider']=lambda:policy(t,roster=[])
    assert w.get_receipt(db,'owner',receipt.id).result['recipient_count']==2
    denied(lambda:read(b2case,'owner','release_preview_read','release_preview','p'),403)
    assert not {'recipients','student_ids','private_spec_hash'} & set(original)


def test_frozen_private_conflict_survives_current_withdrawal(b2case):
    db,a,aa,w,t,m,b,*_=b2case
    db.execute(update(m.Enrollment).where(m.Enrollment.student_id=='assistant').values(status='withdrawn')); db.commit()
    denied(lambda:read(b2case,'assistant','assignment_private_read','version','v'),403,'private_conflict')


def test_read_action_requires_its_exact_loaded_object_kind(b2case):
    db,a,aa,w,t,*_=b2case
    _,ref=aa.resolve_assessment_object(db,'owner','release','r')
    denied(lambda:aa.authorize_assessment_read(db,'owner',t.TeachingAction('assignment_read'),ref),404)
    wrong=replace(ref,course_id='another-course')
    denied(lambda:aa.authorize_assessment_read(db,'owner',t.TeachingAction('release_read'),wrong),404)
