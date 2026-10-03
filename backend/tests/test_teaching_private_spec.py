"""Task3 private text, immutable snapshots and current conflict boundaries."""
import json
from hashlib import sha256

from sqlalchemy import update

from tests.test_teaching_assessment_authorization import b2case, PUBLIC, PRIVATE, policy, denied
from tests.test_teaching_assignments import assignments, write, page_query


def test_private_replace_increments_same_draft_revision(b2case):
    service = assignments()
    db, _, _, _, _, _, b, *_ = b2case
    replacement = {'answer_text':'新答案\r\n第二行\t✓','private_test_notes':'Inert only'}
    first, _ = write(b2case,'replace_private',{'expected_revision':3,'private_spec':replacement})
    assert first.result['draft_revision'] == 4
    assert service.get_assignment_draft(db,'owner','a').public_spec.model_dump() == PUBLIC
    assert service.get_private_spec(db,'owner','a',None).private_spec.model_dump() == replacement
    assert db.get(b.Assignment,'a').draft_revision == 4
    denied(lambda:write(b2case,'replace_public',{'expected_revision':3,'public_spec':PUBLIC},key='stale-after-private'),409,'revision_conflict')


def test_freeze_copies_exact_public_and_private_snapshots(b2case):
    service = assignments()
    db, _, _, engine, _, _, b, *_ = b2case
    private = {'answer_text':'准确\r\n\t答案\n','private_test_notes':'不执行\n'}
    write(b2case,'replace_private',{'expected_revision':3,'private_spec':private})
    frozen, _ = write(b2case,'freeze',{'expected_revision':4})
    identifier = frozen.result['version_id']
    version = service.get_assignment_version(db,'owner','a',identifier)
    assert version.public_spec.model_dump() == PUBLIC and version.source_draft_revision == 4
    assert version.public_spec_hash == sha256(engine._json(PUBLIC).encode('utf-8')).hexdigest()
    saved = db.get(b.PrivateSpec,identifier)
    assert saved.private_spec == private
    assert saved.private_spec_hash == sha256(engine._json(private).encode('utf-8')).hexdigest()
    write(b2case,'replace_private',{'expected_revision':4,'private_spec':{'answer_text':'Later','private_test_notes':''}},key='later-private')
    assert service.get_private_spec(db,'owner','a',identifier).private_spec.model_dump() == private


def test_freeze_without_private_permission_rejects_nonempty_private(b2case):
    assignments()
    db, _, _, _, _, m, b, *_ = b2case
    db.execute(update(m.TeachingRole).where(m.TeachingRole.subject_id=='owner').values(permissions=['AUTHOR'])); db.commit()
    denied(lambda:write(b2case,'freeze',{'expected_revision':3}),403,'permission_denied')
    assert db.query(b.AssessmentEvent).count() == 0
    assert db.query(b.AssignmentVersion).filter_by(source_draft_revision=3).count() == 0
    db.execute(update(b.AssignmentDraftPrivate).where(b.AssignmentDraftPrivate.assignment_id=='a').values(private_draft={'answer_text':'','private_test_notes':''})); db.commit()
    accepted, _ = write(b2case,'freeze',{'expected_revision':3},key='empty-private-freeze')
    assert accepted.result['version_number'] == 3


def test_private_text_never_enters_public_projection_receipt_or_event(b2case):
    service = assignments()
    db, _, _, engine, _, _, b, *_ = b2case
    secret = {'answer_text':'TASK3_PRIVATE_CANARY_答案','private_test_notes':'TASK3_NOTES_CANARY'}
    private, _ = write(b2case,'replace_private',{'expected_revision':3,'private_spec':secret})
    frozen, _ = write(b2case,'freeze',{'expected_revision':4})
    public = [service.get_assignment_draft(db,'owner','a').model_dump(mode='json'),
              service.get_assignment_version(db,'releaser','a',frozen.result['version_id']).model_dump(mode='json'),
              service.list_assignments(db,'owner','o',page_query()).model_dump(mode='json'),
              private.result,frozen.result,private.receipt.model_dump(mode='json'),frozen.receipt.model_dump(mode='json')]
    public.extend(row.effect_metadata for row in db.query(b.AssessmentEvent).all())
    encoded = json.dumps(public,ensure_ascii=False)
    for forbidden in ('TASK3_PRIVATE_CANARY','TASK3_NOTES_CANARY',sha256(engine._json(secret).encode('utf-8')).hexdigest(),'private_spec_hash'):
        assert forbidden not in encoded
    assert db.query(b.AssessmentEvent).count() == 2
    denied(lambda:service.get_private_spec(db,'releaser','a',None),403)
    denied(lambda:service.get_private_spec(db,'releaser','a',frozen.result['version_id']),403)


def test_multiline_unicode_and_byte_limits(b2case):
    service = assignments()
    db, *_ = b2case
    public = {**PUBLIC,'instructions':'中文\r\n\t🙂\n','rubric':'第一条\n第二条'}
    accepted, _ = write(b2case,'replace_public',{'expected_revision':3,'public_spec':public})
    assert service.get_assignment_draft(db,'owner','a').public_spec.model_dump() == public
    denied(lambda:write(b2case,'replace_public',{'expected_revision':4,'public_spec':{**PUBLIC,'instructions':'界'*10923}},key='over-public-bytes'),422,'validation_error')
    denied(lambda:write(b2case,'replace_private',{'expected_revision':4,'private_spec':{'answer_text':'界'*10923,'private_test_notes':''}},key='over-private-bytes'),422,'validation_error')
    denied(lambda:write(b2case,'replace_public',{'expected_revision':4,'public_spec':{**PUBLIC,'instructions':'bad\x00'}},key='forbidden-control'),422,'validation_error')
    assert accepted.result['draft_revision'] == 4


def test_dual_role_private_conflicts_recheck_current_and_frozen_recipient(b2case):
    service = assignments()
    db, _, _, _, _, m, *_ = b2case
    denied(lambda:service.get_private_spec(db,'assistant','a',None),403,'private_conflict')
    denied(lambda:write(b2case,'replace_private',{'expected_revision':3,'private_spec':PRIVATE},actor='assistant'),403,'private_conflict')
    denied(lambda:service.get_private_spec(db,'assistant','a','v'),403,'private_conflict')
    db.execute(update(m.Enrollment).where(m.Enrollment.student_id=='assistant').values(status='withdrawn')); db.commit()
    assert service.get_private_spec(db,'assistant','a',None).private_spec.model_dump() == PRIVATE
    denied(lambda:service.get_private_spec(db,'assistant','a','v'),403,'private_conflict')


def test_freeze_receipt_recovery_uses_original_private_status(b2case):
    service = assignments()
    db, _, _, _, _, m, *_ = b2case
    write(b2case,'replace_private',{'expected_revision':3,'private_spec':{'answer_text':'','private_test_notes':''}})
    first, _ = write(b2case,'freeze',{'expected_revision':4},key='original-empty-freeze')
    write(b2case,'replace_private',{'expected_revision':4,'private_spec':PRIVATE},key='later-nonempty-private')
    db.execute(update(m.TeachingRole).where(m.TeachingRole.subject_id=='owner').values(permissions=['AUTHOR'])); db.commit()
    replay, _ = write(b2case,'freeze',{'expected_revision':4},key='original-empty-freeze')
    assert replay.replayed and replay.result == first.result
    denied(lambda:write(b2case,'freeze',{'expected_revision':5},key='new-private-freeze'),403)
    assert service.get_assignment_version(db,'owner','a',first.result['version_id']).source_draft_revision == 4
