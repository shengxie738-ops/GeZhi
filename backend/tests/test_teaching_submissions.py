"""Task5 ordinary sequential workflows; synthetic evidence, never MySQL proof."""
import importlib
from datetime import timedelta
from hashlib import sha256
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, update

from tests.test_teaching_assessment_authorization import b2case, NOW, policy, denied
from tests.test_teaching_bounded_write_finalization import accept_pending


def submissions():
    try:
        return importlib.import_module('app.services.teaching.submissions')
    except ModuleNotFoundError as exc:
        pytest.fail(f'B2 Task5 submission service absent: {exc}')


def command(parent=None, text='Answer\r\n最后一行\n', *, kind='text', language=None):
    return {'expected_parent_id':parent,'content':{'kind':kind,'language':language,'text':text},
        'ai_usage_declaration':{'used_ai':False,'description':''}}


def query(*, teacher=False, **values):
    schema = importlib.import_module('app.schemas.teaching_assessment')
    return (schema.TeacherSubmissionQuery if teacher else schema.SubmissionHistoryQuery)(**values)


def write(case, body=None, *, actor='assistant', release='r', key='task5-first', commit=True):
    service = submissions()
    db, _, _, engine, *_ = case
    intent, operation = service.prepare_submission_write(db,actor,release,command() if body is None else body,key)
    result = engine.execute_write(db,intent,intent.scope,operation)
    if commit:
        result = accept_pending(db,result,intent)
    return result,intent


def test_first_submission_advances_precreated_empty_head(b2case):
    service = submissions()
    db, _, _, _, _, m, b, *_ = b2case
    before = service.get_submission_head(db,'assistant','r')
    assert before.submission_id is None and before.revision == 0 and before.as_of == NOW
    accepted,intent = write(b2case)
    row = db.get(b.Submission,accepted.result['submission_id'])
    head = db.get(b.SubmissionHead,('r','assistant'))
    assert (row.student_id,row.release_id,row.version_id,row.parent_submission_id,row.sequence) == ('assistant','r','v',None,1)
    assert (head.submission_id,head.revision) == (row.id,1)
    assert intent.actor_id == 'assistant' and intent.target_id == 'r'
    assert row.received_at.replace(tzinfo=NOW.tzinfo) == NOW
    assert db.query(m.WriteReceipt).filter_by(action='submission_create').count() == 1
    assert db.query(b.AssessmentEvent).filter_by(action='submission_create').count() == 1
    assert db.query(m.AccessEvent).count() == 0


def test_next_submission_links_exact_parent(b2case):
    service = submissions()
    db, _, _, _, _, _, b, *_ = b2case
    accepted,_ = write(b2case,command('s','Second'),actor='learner')
    row = db.get(b.Submission,accepted.result['submission_id'])
    assert row.parent_submission_id == 's' and row.sequence == 2
    assert db.get(b.Submission,'s').content['text'] == 'Original'
    assert db.get(b.SubmissionHead,('r','learner')).submission_id == row.id
    assert service.get_submission_head(db,'learner','r').revision == 2


def test_same_parent_different_intent_conflicts(b2case):
    submissions()
    first,_ = write(b2case,command('s'),actor='learner',key='task5-parent-one')
    denied(lambda:write(b2case,command('s','Competing'),actor='learner',key='task5-parent-two'),409,'parent_conflict')
    db, _, _, _, _, m, b, *_ = b2case
    assert db.get(b.SubmissionHead,('r','learner')).submission_id == first.result['submission_id']
    assert db.query(b.Submission).filter_by(student_id='learner').count() == 2
    assert db.query(m.WriteReceipt).filter_by(action='submission_create').count() == 1


def test_same_intent_returns_original_after_newer_head(b2case,monkeypatch):
    submissions()
    body = command()
    first,intent = write(b2case,body)
    second,_ = write(b2case,command(first.result['submission_id'],'Newer'),key='task5-newer')
    db, _, _, engine, _, m, b, *_ = b2case
    db.execute(update(m.Offering).where(m.Offering.id=='o').values(state='archived')); db.commit()
    # Refinement of the existing fifth substitution: later fixed UTC only.
    monkeypatch.setattr(engine,'_server_clock',lambda session:NOW+timedelta(days=1))
    replay,_ = write(b2case,body,key=intent.idempotency_key)
    assert replay.replayed and replay.result == first.result and replay.receipt.id == first.receipt.id
    assert db.get(b.SubmissionHead,('r','assistant')).submission_id == second.result['submission_id']
    assert db.query(b.Submission).filter_by(student_id='assistant').count() == 2
    assert engine.get_receipt(db,'assistant',first.receipt.id).result == first.result
    assert engine.find_receipt(db,'assistant',intent.action,intent.scope,intent.idempotency_key).result == first.result


def test_missing_head_is_incompatible_not_repaired(b2case):
    service = submissions()
    db, _, _, _, _, m, b, *_ = b2case
    db.execute(delete(b.SubmissionHead).where(b.SubmissionHead.release_id=='r',b.SubmissionHead.student_id=='assistant')); db.commit()
    denied(lambda:service.get_submission_head(db,'assistant','r'),503,'invalid_assessment_state')
    denied(lambda:write(b2case),503,'invalid_assessment_state')
    assert db.get(b.SubmissionHead,('r','assistant')) is None
    assert db.query(b.Submission).filter_by(student_id='assistant').count() == 0
    assert db.query(m.WriteReceipt).filter_by(action='submission_create').count() == 0
    assert db.query(b.AssessmentEvent).filter_by(action='submission_create').count() == 0


def test_missing_head_refusal_follows_current_authority(b2case):
    submissions()
    db, _, _, _, _, m, b, *_ = b2case
    db.execute(delete(b.SubmissionHead).where(b.SubmissionHead.release_id=='r',b.SubmissionHead.student_id=='assistant'))
    db.execute(update(m.Enrollment).where(m.Enrollment.student_id=='assistant').values(status='withdrawn')); db.commit()
    denied(lambda:write(b2case),404,'permission_denied')
    assert db.query(b.Submission).filter_by(student_id='assistant').count() == 0
    assert db.query(m.WriteReceipt).filter_by(action='submission_create').count() == 0


def test_absent_new_head_has_no_allocated_shape(b2case):
    db, _, _, _, t, _, b, accounts, _ = b2case
    allocator = importlib.import_module('app.services.teaching.assessment_writes').allocate_assessment_shape
    context = SimpleNamespace(actor_account=db.get(accounts.UserAccount,'assistant'),assessment_receipt=None,
        assessment=SimpleNamespace(assignment=db.get(b.Assignment,'a'),release=db.get(b.Release,'r'),head=None),
        scope=t.ScopeRef('school','offering','o'))
    assert allocator(context,t.TeachingAction.SUBMISSION_CREATE,command()) is None


def test_accepted_receipt_recovers_without_present_head(b2case):
    submissions()
    accepted,intent = write(b2case)
    db, _, _, engine, _, _, b, *_ = b2case
    db.execute(delete(b.SubmissionHead).where(b.SubmissionHead.release_id=='r',b.SubmissionHead.student_id=='assistant')); db.commit()
    replay,_ = write(b2case,key=intent.idempotency_key)
    assert replay.replayed and replay.result == accepted.result and replay.receipt.id == accepted.receipt.id
    assert engine.get_receipt(db,'assistant',accepted.receipt.id).result == accepted.result
    assert db.get(b.SubmissionHead,('r','assistant')) is None


@pytest.mark.parametrize('field,value',[('student_id','learner'),('actor_id','learner'),('version_id','v2'),
    ('content_hash','0'*64),('received_at','2026-10-03T12:00:00Z'),('grade',100),('status','assessed'),('receipt',{})])
def test_body_cannot_forge_actor_version_hash_time_or_grade(b2case,field,value):
    service = submissions()
    db,*_ = b2case
    denied(lambda:service.prepare_submission_write(db,'assistant','r',{**command(),field:value},'task5-forgery'),422,'validation_error')


def test_exact_utf8_content_hash_preserves_newlines(b2case):
    service = submissions()
    text = 'print("学生🙂")\r\n\t# final\n'
    body = command(text=text,kind='code',language='python')
    body['ai_usage_declaration'] = {'used_ai':True,'description':'Self-reported help\nwith structure'}
    accepted,_ = write(b2case,body)
    db, _, _, _, _, _, b, *_ = b2case
    row = db.get(b.Submission,accepted.result['submission_id'])
    shown = service.get_submission(db,'assistant',row.id)
    assert row.content == body['content'] and shown.content.text == text
    assert row.content_hash == sha256(text.encode('utf-8')).hexdigest() == accepted.result['content_hash']
    assert shown.ai_usage_declaration.used_ai and shown.content.language == 'python'
    assert not {'student_id','private_spec','recipient_count','recipient_digest'} & shown.model_dump().keys()


@pytest.mark.parametrize('bad',[
    {'expected_parent_id':None,'content':{'kind':'text','language':None,'text':''},'ai_usage_declaration':{'used_ai':False,'description':''}},
    command(text='🙂'*65537), command(kind='text',language='python'),command(kind='code',language=None),
    command(kind='code',language=' python '),command(text='bad\x00text'),
    {**command(),'ai_usage_declaration':{'used_ai':True,'description':' '}},
])
def test_submission_command_validation_keeps_exact_limits(b2case,bad):
    service = submissions()
    db,*_ = b2case
    denied(lambda:service.prepare_submission_write(db,'assistant','r',bad,'task5-invalid'),422,'validation_error')


def test_exact_content_byte_limit_is_accepted(b2case):
    service = submissions()
    text = '🙂'*65536
    accepted,_ = write(b2case,command(text=text))
    db,*_ = b2case
    assert service.get_submission(db,'assistant',accepted.result['submission_id']).content.text == text


@pytest.mark.parametrize('change',['deadline_equal','deadline_past','archive','withdrawal','source'])
def test_deadline_archive_and_current_withdrawal_refuse_new_submit(b2case,change):
    submissions()
    db, _, _, _, t, m, b, *_ = b2case
    if change.startswith('deadline'):
        due = NOW if change == 'deadline_equal' else NOW-timedelta(microseconds=1)
        digest = importlib.import_module('app.services.teaching.assessment_writes')._digest
        # Ordinary fixture state, not mutation of an accepted submission/receipt.
        db.execute(update(b.Release).where(b.Release.id=='r').values(due_at=due,
            policy_digest=digest({'version':1,'due_at':due,'timezone':'UTC','late_policy':'reject'})))
    elif change == 'archive':
        db.execute(update(m.Offering).where(m.Offering.id=='o').values(state='archived'))
    elif change == 'withdrawal':
        db.execute(update(m.Enrollment).where(m.Enrollment.student_id=='assistant').values(status='withdrawn'))
    else:
        db.info['teaching_policy_provider'] = lambda:policy(t,roster=['learner'])
    db.commit()
    denied(lambda:write(b2case),409 if change.startswith('deadline') or change=='archive' else 404,
        'deadline_closed' if change.startswith('deadline') else 'lifecycle_conflict' if change=='archive' else 'permission_denied')
    assert db.query(b.Submission).filter_by(student_id='assistant').count() == 0


def test_deadline_replay_returns_original_at_later_fixed_clock(b2case,monkeypatch):
    submissions()
    db, _, _, engine, _, _, b, *_ = b2case
    digest = importlib.import_module('app.services.teaching.assessment_writes')._digest
    due = NOW+timedelta(seconds=1)
    db.execute(update(b.Release).where(b.Release.id=='r').values(due_at=due,
        policy_digest=digest({'version':1,'due_at':due,'timezone':'UTC','late_policy':'reject'}))); db.commit()
    accepted,intent = write(b2case)
    monkeypatch.setattr(engine,'_server_clock',lambda session:NOW+timedelta(seconds=2))
    replay,_ = write(b2case,key=intent.idempotency_key)
    assert replay.replayed and replay.result == accepted.result
    denied(lambda:write(b2case,command(accepted.result['submission_id']),key='task5-after-deadline'),409,'deadline_closed')


def test_history_is_own_and_teacher_reads_are_ceiling_scoped(b2case):
    service = submissions()
    first,_ = write(b2case,command('s','Learner two'),actor='learner')
    second,_ = write(b2case,command(first.result['submission_id'],'Learner three'),actor='learner',key='task5-third')
    own,_ = write(b2case,key='task5-assistant')
    db, _, _, _, t, *_ = b2case
    page = service.list_own_submission_history(db,'learner','r',query(limit=1))
    assert [item.sequence for item in page.items] == [1] and page.current_head_id == second.result['submission_id']
    next_page = service.list_own_submission_history(db,'learner','r',query(limit=1,cursor=page.next_cursor))
    assert [item.sequence for item in next_page.items] == [2]
    assert not {'content','student_id','ai_usage_declaration'} & page.items[0].model_dump().keys()
    assert service.get_submission(db,'viewer','s').student_id == 'learner'
    denied(lambda:service.get_submission(db,'assistant','s'),403)
    db.info['teaching_policy_provider'] = lambda:policy(t,roster=['learner'])
    heads = service.list_release_submissions(db,'viewer','r',query(teacher=True))
    assert [(item.student_id,item.id) for item in heads.items] == [('learner',second.result['submission_id'])]
    assert heads.current_head_id is None and heads.next_cursor is None
    history = service.list_release_submissions(db,'viewer','r',query(teacher=True,student_id='learner',limit=1))
    assert history.items[0].sequence == 1 and history.current_head_id == second.result['submission_id']
    denied(lambda:service.get_submission(db,'viewer',own.result['submission_id']),403)


@pytest.mark.parametrize('subject',['assistant','outsider','missing'])
def test_teacher_student_filter_never_expands_ceiling_or_discloses_existence(b2case,subject):
    service = submissions()
    db, _, _, _, t, *_ = b2case
    db.info['teaching_policy_provider'] = lambda:policy(t,roster=['learner'])
    page = service.list_release_submissions(db,'viewer','r',query(teacher=True,student_id=subject))
    assert page.items == [] and page.current_head_id is None and page.next_cursor is None


@pytest.mark.parametrize('change',['withdrawal','source','missing_account'])
def test_old_recipient_never_grants_current_access(b2case,change):
    service = submissions()
    accepted,intent = write(b2case,command('s'),actor='learner')
    db, _, _, engine, t, m, b, accounts, _ = b2case
    if change == 'withdrawal':
        db.execute(update(m.Enrollment).where(m.Enrollment.student_id=='learner').values(status='withdrawn'))
    elif change == 'missing_account':
        db.delete(db.get(accounts.UserAccount,'learner'))
    else:
        db.info['teaching_policy_provider'] = lambda:policy(t,roster=['assistant'])
    db.commit()
    denied(lambda:service.get_submission(db,'learner','s'))
    denied(lambda:service.get_submission_head(db,'learner','r'))
    denied(lambda:service.list_own_submission_history(db,'learner','r',query()))
    denied(lambda:write(b2case,command('s'),actor='learner',key=intent.idempotency_key))
    denied(lambda:engine.get_receipt(db,'learner',accepted.receipt.id))
    denied(lambda:engine.find_receipt(db,'learner',intent.action,intent.scope,intent.idempotency_key))
    assert db.get(b.ReleaseRecipient,('r','learner')) is not None
    if change == 'withdrawal':
        assert service.get_submission(db,'viewer','s').student_id == 'learner'
        assert len(service.list_release_submissions(db,'viewer','r',query(teacher=True,student_id='learner')).items) == 2


def test_submission_pages_bind_current_actor_release_and_filter(b2case):
    service = submissions()
    first,_ = write(b2case,command('s'),actor='learner')
    write(b2case,command(first.result['submission_id']),actor='learner',key='task5-third')
    write(b2case,key='task5-assistant')
    db, _, _, _, _, m, *_ = b2case
    own = service.list_own_submission_history(db,'learner','r',query(limit=1))
    denied(lambda:service.list_own_submission_history(db,'assistant','r',query(cursor=own.next_cursor)),422,'invalid_cursor')
    teacher = service.list_release_submissions(db,'viewer','r',query(teacher=True,student_id='learner',limit=1))
    denied(lambda:service.list_release_submissions(db,'viewer','r',query(teacher=True,student_id='assistant',cursor=teacher.next_cursor)),422,'invalid_cursor')
    denied(lambda:service.list_release_submissions(db,'viewer','r',query(teacher=True,cursor=teacher.next_cursor)),422,'invalid_cursor')
    heads = service.list_release_submissions(db,'viewer','r',query(teacher=True,limit=1))
    assert heads.next_cursor and heads.items[0].student_id == 'assistant'
    assert service.list_release_submissions(db,'viewer','r',query(teacher=True,cursor=heads.next_cursor)).items[0].student_id == 'learner'
    denied(lambda:service.list_release_submissions(db,'owner','r',query(teacher=True,cursor=heads.next_cursor)),422,'invalid_cursor')
    db.execute(update(m.TeachingRole).where(m.TeachingRole.subject_id=='viewer').values(status='revoked')); db.commit()
    denied(lambda:service.list_release_submissions(db,'viewer','r',query(teacher=True,cursor=heads.next_cursor)),404)


def test_own_editor_and_history_remain_own_for_dual_role_or_teacher(b2case):
    service = submissions()
    db,*_ = b2case
    denied(lambda:service.get_submission_head(db,'viewer','r'),403)
    denied(lambda:service.list_own_submission_history(db,'viewer','r',query()),403)
    denied(lambda:service.list_release_submissions(db,'assistant','r',query(teacher=True)),403)
    assert service.get_submission_head(db,'assistant','r').submission_id is None


def test_ordinary_submission_rollback_leaves_no_partial_acceptance(b2case):
    submissions()
    db, _, _, engine, _, m, b, *_ = b2case
    accepted,_ = write(b2case,commit=False)
    engine.rollback_pending_write(db,accepted)
    assert db.get(b.Submission,accepted.result['submission_id']) is None
    head = db.get(b.SubmissionHead,('r','assistant'))
    assert head.submission_id is None and head.revision == 0
    assert db.query(m.WriteReceipt).filter_by(action='submission_create').count() == 0
    assert db.query(b.AssessmentEvent).filter_by(action='submission_create').count() == 0


def test_all_results_say_unavailable_execution_and_no_assessment(b2case):
    service = submissions()
    accepted,_ = write(b2case)
    db,*_ = b2case
    own = service.get_submission(db,'assistant',accepted.result['submission_id'])
    teacher = service.get_submission(db,'viewer',accepted.result['submission_id'])
    history = service.list_own_submission_history(db,'assistant','r',query()).items[0]
    heads = service.list_release_submissions(db,'viewer','r',query(teacher=True)).items
    for shown in [own,teacher,history,*heads]:
        assert shown.execution_status == 'not_available' and shown.assessment_status == 'not_implemented'
        assert not {'grade','score','feedback','assessment','execution_result'} & shown.model_dump().keys()
    assert not {'content','ai_usage_declaration','student_id','grade','status'} & accepted.result.keys()


def test_submission_routes_and_queries_remain_strict(b2case):
    service = submissions()
    db,*_ = b2case
    denied(lambda:service.prepare_submission_write(db,'assistant','missing',command(),'task5-missing'),404)
    denied(lambda:service.prepare_submission_write(db,'assistant','r\n',command(),'task5-invalid'),422)
    denied(lambda:service.get_submission(db,'viewer','missing'),404)
    denied(lambda:service.get_submission(db,'outsider','s'),404)
    denied(lambda:service.list_release_submissions(db,'releaser','r',query(teacher=True)),403)
    denied(lambda:service.list_release_submissions(db,'viewer','r',{'limit':True}),422,'validation_error')
    denied(lambda:service.list_own_submission_history(db,'learner','r',{'student_id':'assistant'}),422,'validation_error')
