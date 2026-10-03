"""Task4 ordinary release workflows. Synthetic rows, no production activation."""
import importlib
import json
from datetime import timedelta

import pytest
from sqlalchemy import update

from tests.test_teaching_assessment_authorization import b2case, NOW, policy, denied


def releases():
    try:
        return importlib.import_module('app.services.teaching.releases')
    except ModuleNotFoundError as exc:
        pytest.fail(f'B2 Task4 release service absent: {exc}')


def query(**values):
    return importlib.import_module('app.schemas.teaching_assessment').RecipientPageQuery(**values)


def preview_command(*, students=None, due=None):
    return {'version_id':'v2','student_ids':['learner','assistant'] if students is None else students,
        'due_at':due,'late_policy':'reject'}


def confirm_command(preview):
    return {**{field:getattr(preview,field) for field in
        ('version_id','public_spec_hash','recipient_count','recipient_digest','policy_digest')},
        'preview_id':preview.id,'confirmed':True}


def write(case,purpose,command,*,actor='owner',key=None,commit=True,assignment_id='a'):
    service = releases()
    db, _, _, engine, *_ = case
    intent, operation = service.prepare_release_write(db,actor,assignment_id,purpose,command,key or 'task4-'+purpose)
    result = engine.execute_write(db,intent,intent.scope,operation)
    if commit:
        db.commit()
    return result,intent


def preview(case,*,actor='owner',key='task4-preview',students=None,due=None):
    service = releases()
    accepted,intent = write(case,'preview',preview_command(students=students,due=due),actor=actor,key=key)
    db,*_ = case
    return service.get_release_preview(db,actor,'a',accepted.result['preview_id']),accepted,intent


def expand_audience(case,count=1000):
    db, _, _, _, t, m, _, accounts, _ = case
    students = [f'person-{number:04d}' for number in range(count)]
    for subject in students:
        db.add(accounts.UserAccount(username=subject,role='student',password_hash='synthetic-only'))
        db.add(m.Enrollment(id='e-'+subject,institution_id='school',offering_id='o',student_id=subject,
            status='active',effective_from=NOW-timedelta(days=1),revision=1,source_kind='deployment_roster',
            source_teacher_id='owner',source_policy_digest='a'*64,created_at=NOW,updated_at=NOW))
    db.commit()
    db.info['teaching_policy_provider'] = lambda:policy(t,roster=students)
    return students


def test_preview_canonicalizes_complete_explicit_audience(b2case):
    service = releases()
    db, _, _, _, _, _, b, *_ = b2case
    shown,accepted,intent = preview(b2case)
    saved = db.get(b.ReleasePreview,shown.id)
    assert shown.recipient_count == 2 and shown.first_recipient_page.items == ['assistant','learner']
    assert [member['student_id'] for member in saved.recipient_snapshot] == ['assistant','learner']
    assert shown.expires_at == NOW+timedelta(minutes=15)
    reordered,_ = service.prepare_release_write(db,'owner','a','preview',preview_command(students=['assistant','learner']),intent.idempotency_key)
    assert reordered.request_hash == intent.request_hash
    assert tuple(intent.canonical_payload['student_ids']) == ('assistant','learner')
    assert not {'student_ids','recipients','private_spec','private_spec_hash'} & accepted.result.keys()
    assert saved.created_at.replace(tzinfo=NOW.tzinfo) == NOW


def test_preview_exact_duplicate_and_unknown_are_rejected(b2case):
    releases()
    denied(lambda:write(b2case,'preview',preview_command(students=['learner','learner'])),422,'validation_error')
    denied(lambda:write(b2case,'preview',preview_command(students=['missing'])),422,'unavailable_or_out_of_scope')


def test_preview_paginates_all_1000_without_sample_substitution(b2case):
    service = releases()
    students = expand_audience(b2case)
    db, _, _, _, _, _, b, *_ = b2case
    shown,accepted,_ = preview(b2case,students=list(reversed(students)))
    assert shown.recipient_count == 1000 and len(shown.first_recipient_page.items) == 100
    page = shown.first_recipient_page
    found = list(page.items)
    while page.next_cursor:
        page = service.list_release_preview_recipients(db,'owner','a',shown.id,query(limit=100,cursor=page.next_cursor))
        found.extend(page.items)
    assert found == students and len(db.get(b.ReleasePreview,shown.id).recipient_snapshot) == 1000
    confirmed,_ = write(b2case,'confirm',confirm_command(shown))
    rid = confirmed.result['release_id']
    assert db.query(b.ReleaseRecipient).filter_by(release_id=rid).count() == 1000
    assert db.query(b.SubmissionHead).filter_by(release_id=rid,submission_id=None,revision=0).count() == 1000
    assert len(json.dumps(accepted.receipt.original_result).encode()) < 65536


@pytest.mark.parametrize('field,value,status,detail',[
    ('public_spec_hash','0'*64,409,'preview_stale'),
    ('recipient_count',1,409,'preview_stale'),
    ('recipient_digest','0'*64,409,'preview_stale'),
    ('policy_digest','0'*64,409,'preview_stale'),
    ('version_id','v',404,'not_found'),
    ('preview_id','missing',404,'not_found'),
])
def test_confirm_binds_version_audience_and_deadline_policy(b2case,field,value,status,detail):
    releases()
    shown,_,_ = preview(b2case,due=NOW+timedelta(hours=1))
    denied(lambda:write(b2case,'confirm',{**confirm_command(shown),field:value}),status,detail)


@pytest.mark.parametrize('change',['roster','role','offering','policy','enrollment'])
def test_roster_role_policy_or_offering_revision_change_invalidates_new_confirm(b2case,change):
    releases()
    shown,_,_ = preview(b2case)
    db, _, _, _, t, m, *_ = b2case
    if change == 'role':
        db.execute(update(m.TeachingRole).where(m.TeachingRole.subject_id=='owner').values(revision=2))
    elif change == 'enrollment':
        db.execute(update(m.Enrollment).where(m.Enrollment.student_id=='learner').values(revision=2))
    elif change == 'policy':
        db.info['teaching_policy_provider'] = lambda:policy(t,roster=['learner','assistant','assigned','new-member'])
    else:
        db.execute(update(m.Offering).where(m.Offering.id=='o').values(**{('roster_revision' if change=='roster' else 'revision'):2}))
    db.commit()
    denied(lambda:write(b2case,'confirm',confirm_command(shown)),409,'preview_stale')


@pytest.mark.parametrize('delta',[0,-1])
def test_expiry_and_due_boundary_use_final_clock(b2case,delta):
    service = releases()
    db, _, _, _, _, _, b, *_ = b2case
    # p2 is ordinary preseeded fixture data, not an accepted command result.
    db.execute(update(b.ReleasePreview).where(b.ReleasePreview.id=='p2').values(
        created_at=NOW-timedelta(minutes=15)+timedelta(microseconds=delta),
        expires_at=NOW+timedelta(microseconds=delta)))
    db.commit()
    shown = service.get_release_preview(db,'owner','a','p2')
    denied(lambda:write(b2case,'confirm',confirm_command(shown)),409,'preview_expired')


def test_release_creates_exact_recipients_and_empty_heads_atomically(b2case):
    service = releases()
    shown,_,_ = preview(b2case)
    db, _, _, _, _, m, b, *_ = b2case
    accepted,_ = write(b2case,'confirm',confirm_command(shown))
    rid = accepted.result['release_id']
    recipients = db.query(b.ReleaseRecipient).filter_by(release_id=rid).order_by(b.ReleaseRecipient.student_id).all()
    assert [row.student_id for row in recipients] == ['assistant','learner']
    heads = db.query(b.SubmissionHead).filter_by(release_id=rid).all()
    assert len(heads) == 2 and all(row.revision==0 and row.submission_id is None for row in heads)
    assert db.query(m.WriteReceipt).filter_by(action='release_create').count() == 1
    assert db.query(b.AssessmentEvent).filter_by(action='release_create').count() == 1
    assert db.query(m.AccessEvent).count() == 0
    own = service.get_release(db,'learner',rid).model_dump(mode='json')
    assert not {'recipient_count','recipient_digest','student_ids','private_spec','private_spec_hash'} & own.keys()
    dual = service.get_release(db,'assistant',rid).model_dump(mode='json')
    assert dual.keys() == own.keys()


def test_ordinary_confirmation_rollback_leaves_no_partial_acceptance(b2case):
    releases()
    shown,_,_ = preview(b2case)
    db, _, _, _, _, m, b, *_ = b2case
    accepted,_ = write(b2case,'confirm',confirm_command(shown),commit=False)
    rid = accepted.result['release_id']
    db.rollback()
    assert db.get(b.Release,rid) is None
    assert db.query(b.ReleaseRecipient).filter_by(release_id=rid).count() == 0
    assert db.query(b.SubmissionHead).filter_by(release_id=rid).count() == 0
    assert db.query(m.WriteReceipt).filter_by(action='release_create').count() == 0
    assert db.query(b.AssessmentEvent).filter_by(action='release_create').count() == 0


def test_later_enrollment_is_not_old_audience(b2case):
    service = releases()
    shown,_,_ = preview(b2case,students=['learner'])
    accepted,_ = write(b2case,'confirm',confirm_command(shown))
    db, _, _, _, _, _, b, *_ = b2case
    rid = accepted.result['release_id']
    later_student = expand_audience(b2case,count=1)[0]
    denied(lambda:service.get_release(db,later_student,rid),404)
    assert service.list_releases(db,later_student,'o',query()).items == []
    assert db.get(b.ReleaseRecipient,(rid,later_student)) is None


def test_release_permission_does_not_read_private(b2case):
    service = releases()
    shown,_,_ = preview(b2case,actor='releaser')
    accepted,_ = write(b2case,'confirm',confirm_command(shown),actor='releaser')
    db,*_ = b2case
    result = service.get_release(db,'releaser',accepted.result['release_id']).model_dump(mode='json')
    assert result['recipient_count'] == 2 and 'private' not in json.dumps(result)
    assignments = importlib.import_module('app.services.teaching.assignments')
    denied(lambda:assignments.get_private_spec(db,'releaser','a','v2'),403)


def test_new_key_cannot_release_same_version_twice(b2case):
    releases()
    shown,_,_ = preview(b2case)
    write(b2case,'confirm',confirm_command(shown))
    denied(lambda:write(b2case,'confirm',confirm_command(shown),key='another-release'),409,'version_already_released')


def test_same_release_intent_recovers_after_preview_expiry(b2case,monkeypatch):
    releases()
    shown,preview_accepted,preview_intent = preview(b2case,due=NOW+timedelta(minutes=5))
    assert shown.expires_at == NOW+timedelta(minutes=15)
    command = confirm_command(shown)
    accepted,intent = write(b2case,'confirm',command)
    db, _, _, engine, *_ = b2case
    # Approved refinement of the existing fifth b2case substitution only.
    later = NOW+timedelta(minutes=16)
    monkeypatch.setattr(engine,'_server_clock',lambda session:later)
    replay,_ = write(b2case,'confirm',command,key=intent.idempotency_key)
    assert replay.replayed and replay.result == accepted.result and replay.receipt.id == accepted.receipt.id
    earlier,_ = write(b2case,'preview',preview_command(due=NOW+timedelta(minutes=5)),key=preview_intent.idempotency_key)
    assert earlier.replayed and earlier.result == preview_accepted.result
    assert engine.get_receipt(db,'owner',accepted.receipt.id).result == accepted.result
    denied(lambda:write(b2case,'confirm',command,key='expired-new-intent'),409,'preview_expired')


@pytest.mark.parametrize('purpose',['preview','confirm'])
@pytest.mark.parametrize('change',['withdrawal','missing_account','ceiling'])
def test_accepted_audience_receipt_recovers_after_withdrawal_or_missing_recipient_account(b2case,purpose,change):
    service = releases()
    shown,accepted,intent = preview(b2case)
    command = preview_command()
    if purpose == 'confirm':
        command = confirm_command(shown)
        accepted,intent = write(b2case,'confirm',command)
    db, _, _, engine, t, m, _, accounts, _ = b2case
    if change == 'withdrawal':
        db.execute(update(m.Enrollment).where(m.Enrollment.student_id=='learner').values(status='withdrawn'))
    elif change == 'missing_account':
        db.delete(db.get(accounts.UserAccount,'learner'))
    else:
        db.info['teaching_policy_provider'] = lambda:policy(t,roster=[])
    db.commit()
    again,_ = write(b2case,purpose,command,key=intent.idempotency_key)
    assert again.replayed and again.receipt.id == accepted.receipt.id and again.result == accepted.result
    assert engine.get_receipt(db,'owner',accepted.receipt.id).result == accepted.result
    assert engine.find_receipt(db,'owner',intent.action,intent.scope,intent.idempotency_key).result == accepted.result
    if change == 'ceiling':
        denied(lambda:service.get_release_preview(db,'owner','a',shown.id),403)


@pytest.mark.parametrize('purpose',['preview','confirm'])
def test_actor_revocation_still_denies_audience_receipt(b2case,purpose):
    releases()
    shown,accepted,intent = preview(b2case)
    command = preview_command()
    if purpose == 'confirm':
        command = confirm_command(shown)
        accepted,intent = write(b2case,'confirm',command)
    db, _, _, engine, _, m, *_ = b2case
    db.execute(update(m.TeachingRole).where(m.TeachingRole.subject_id=='owner').values(status='revoked'))
    db.commit()
    denied(lambda:write(b2case,purpose,command,key=intent.idempotency_key),403)
    denied(lambda:engine.get_receipt(db,'owner',accepted.receipt.id),404)


@pytest.mark.parametrize('subject',['missing','outsider',' learner '])
def test_unknown_and_out_of_scope_recipient_are_indistinguishable(b2case,subject):
    releases()
    denied(lambda:write(b2case,'preview',preview_command(students=[subject])),422,
        'validation_error' if subject==' learner ' else 'unavailable_or_out_of_scope')


@pytest.mark.parametrize('bad',['2026-10-04','2026-10-04T00:00:00','2026-10-04T00:00:00-00:00',
    '2026-10-04T00:00:00+01:00','2026-10-04 00:00:00Z','2026-10-04T00:00:00z',
    '2026-10-04T00:00:00.1234567Z','2026-02-30T00:00:00Z','2026-10-04T00:00:60Z',123])
def test_utc_wire_parser_is_strict(b2case,bad):
    service = releases()
    db,*_ = b2case
    denied(lambda:service.prepare_release_write(db,'owner','a','preview',preview_command(due=bad),'invalid-utc-key'),422,'validation_error')


def test_utc_wire_hash_is_normalized_and_deadline_changes_hash(b2case):
    service = releases()
    db,*_ = b2case
    hashes = [service.prepare_release_write(db,'owner','a','preview',preview_command(due=due),'same-instant')[0].request_hash
        for due in ('2026-10-04T00:00:00Z','2026-10-04T00:00:00.000000+00:00')]
    assert hashes[0] == hashes[1]
    changed,_ = service.prepare_release_write(db,'owner','a','preview',preview_command(due='2026-10-04T00:00:00.000001Z'),'same-instant')
    assert changed.request_hash != hashes[0]


@pytest.mark.parametrize('delta',[0,-1])
def test_past_or_equal_deadline_rejected_for_preview_and_confirm(b2case,delta):
    service = releases()
    due = NOW+timedelta(microseconds=delta)
    denied(lambda:write(b2case,'preview',preview_command(due=due)),409,'deadline_closed')
    db, _, _, engine, _, _, b, *_ = b2case
    digest = importlib.import_module('app.services.teaching.assessment_writes')._digest
    db.execute(update(b.ReleasePreview).where(b.ReleasePreview.id=='p2').values(due_at=due,
        policy_digest=digest({'version':1,'due_at':due,'timezone':'UTC','late_policy':'reject'})))
    db.commit()
    shown = service.get_release_preview(db,'owner','a','p2')
    denied(lambda:write(b2case,'confirm',confirm_command(shown)),409,'deadline_closed')


def test_preview_captures_locked_timezone_and_release_keeps_snapshot(b2case):
    service = releases()
    db, _, _, _, _, m, *_ = b2case
    db.execute(update(m.Offering).where(m.Offering.id=='o').values(timezone='Asia/Shanghai')); db.commit()
    shown,_,_ = preview(b2case,due=NOW+timedelta(hours=1))
    assert shown.timezone == 'Asia/Shanghai'
    accepted,_ = write(b2case,'confirm',confirm_command(shown))
    db.execute(update(m.Offering).where(m.Offering.id=='o').values(timezone='UTC',revision=2)); db.commit()
    assert service.get_release(db,'learner',accepted.result['release_id']).timezone == 'Asia/Shanghai'


def test_preview_pages_are_actor_route_and_current_ceiling_bound(b2case):
    service = releases()
    db, _, _, _, t, *_ = b2case
    page = service.list_release_preview_recipients(db,'owner','a','p',query(limit=1))
    assert page.items == ['assistant'] and page.next_cursor
    assert service.list_release_preview_recipients(db,'owner','a','p',query(cursor=page.next_cursor)).items == ['learner']
    denied(lambda:service.get_release_preview(db,'releaser','a','p'),403)
    denied(lambda:service.get_release_preview(db,'owner','wrong','p'),404)
    denied(lambda:service.list_release_preview_recipients(db,'owner','a','p2',query(cursor=page.next_cursor)),422,'invalid_cursor')
    db.info['teaching_policy_provider'] = lambda:policy(t,roster=['learner'])
    denied(lambda:service.list_release_preview_recipients(db,'owner','a','p',query(cursor=page.next_cursor)),403)


def test_historical_pages_show_only_current_authorized_count_and_withdrawn_history(b2case):
    service = releases()
    db, _, _, _, t, m, *_ = b2case
    db.execute(update(m.Enrollment).where(m.Enrollment.student_id=='learner').values(status='withdrawn')); db.commit()
    db.info['teaching_policy_provider'] = lambda:policy(t,roster=['learner'])
    page = service.list_historical_recipients(db,'viewer','r',query())
    assert page.projection == 'historical_recipients' and page.items == ['learner']
    assert page.authorized_recipient_count == 1 and page.next_cursor is None
    assert 'recipient_digest' not in page.model_dump() and 'recipient_count' not in page.model_dump()
    denied(lambda:service.get_release(db,'learner','r'),404)
    denied(lambda:service.list_historical_recipients(db,'assigned','r',query()),404)


def test_release_list_reauthorizes_current_roles_and_cursor(b2case):
    service = releases()
    shown,_,_ = preview(b2case)
    write(b2case,'confirm',confirm_command(shown))
    db, _, _, _, _, m, *_ = b2case
    first = service.list_releases(db,'viewer','o',query(limit=1))
    second = service.list_releases(db,'viewer','o',query(limit=1,cursor=first.next_cursor))
    assert len(first.items) == len(second.items) == 1 and second.next_cursor is None
    assert first.items[0].id < second.items[0].id
    denied(lambda:service.list_releases(db,'owner','o',query(cursor=first.next_cursor)),422,'invalid_cursor')
    own = service.list_releases(db,'learner','o',query())
    assert len(own.items) == 2 and all('recipient_count' not in item.model_dump() for item in own.items)
    db.execute(update(m.TeachingRole).where(m.TeachingRole.subject_id=='viewer').values(status='revoked')); db.commit()
    denied(lambda:service.list_releases(db,'viewer','o',query(cursor=first.next_cursor)),404)


def test_release_routes_and_commands_are_strict(b2case):
    service = releases()
    db,*_ = b2case
    for extra in ({'timezone':'UTC'},{'actor_id':'owner'},{'offering_id':'o'}):
        denied(lambda:service.prepare_release_write(db,'owner','a','preview',{**preview_command(),**extra},'extra-field'),422,'validation_error')
    denied(lambda:service.prepare_release_write(db,'owner','a','confirm',{'confirmed':1},'not-true'),422,'validation_error')
    denied(lambda:service.prepare_release_write(db,'owner','fa','preview',preview_command(),'foreign-route'),404)
    denied(lambda:service.get_release(db,'owner','missing'),404)
    denied(lambda:service.list_releases(db,'owner','fo',query()),404)
    denied(lambda:service.list_releases(db,'owner','o',{'limit':True}),422,'validation_error')
