"""Task3 ordinary assignment business cases; isolated synthetic B2 only."""
import importlib
import json
from dataclasses import replace

import pytest
from sqlalchemy import update

from tests.test_teaching_assessment_authorization import b2case, PUBLIC, PRIVATE, NOW, policy, denied


def assignments():
    try:
        return importlib.import_module('app.services.teaching.assignments')
    except ModuleNotFoundError as exc:
        pytest.fail(f'B2 Task3 assignment service absent: {exc}')


def page_query(**values):
    return importlib.import_module('app.schemas.teaching_assessment').AssessmentPageQuery(**values)


def write(case, purpose, command, *, actor='owner', assignment_id='a', key=None):
    service = assignments()
    db, _, _, engine, *_ = case
    intent, operation = service.prepare_assignment_write(db, actor,
        'o' if purpose == 'create' else None, None if purpose == 'create' else assignment_id,
        purpose, command, key or f'task3-{purpose}')
    result = engine.execute_write(db, intent, intent.scope, operation)
    db.commit()
    return result, intent


def create(case, *, title='New draft', key='task3-create'):
    return write(case, 'create', {'public_spec': {**PUBLIC, 'title': title}}, key=key)


def test_create_and_public_replace_require_expected_revision(b2case):
    service = assignments()
    db, _, _, _, _, _, b, *_ = b2case
    first, _ = create(b2case)
    identifier = first.result['assignment_id']
    assert first.result['draft_revision'] == 1
    assert db.get(b.Assignment, identifier).next_version_number == 1
    assert db.get(b.AssignmentDraftPrivate, identifier).private_draft == {'answer_text':'','private_test_notes':''}
    second, _ = write(b2case, 'replace_public', {'expected_revision':1,'public_spec':PUBLIC}, assignment_id=identifier)
    assert second.result['draft_revision'] == 2
    denied(lambda:write(b2case,'replace_public',{'expected_revision':1,'public_spec':PUBLIC},assignment_id=identifier,key='stale-revision'),409,'revision_conflict')
    assert service.get_assignment_draft(db,'owner',identifier).draft_revision == 2


def test_edit_after_freeze_leaves_old_version_unchanged(b2case):
    service = assignments()
    db, *_ = b2case
    frozen, _ = write(b2case,'freeze',{'expected_revision':3})
    before = service.get_assignment_version(db,'owner','a',frozen.result['version_id']).model_dump(mode='json')
    write(b2case,'replace_public',{'expected_revision':3,'public_spec':{**PUBLIC,'title':'Edited later'}})
    assert service.get_assignment_version(db,'owner','a',frozen.result['version_id']).model_dump(mode='json') == before
    assert service.get_assignment_draft(db,'owner','a').public_spec.title == 'Edited later'


def test_second_freeze_of_same_revision_conflicts(b2case):
    assignments()
    db, _, _, _, _, _, b, *_ = b2case
    first, _ = write(b2case,'freeze',{'expected_revision':3})
    denied(lambda:write(b2case,'freeze',{'expected_revision':3},key='new-freeze-intent'),409,'version_already_frozen')
    assert db.get(b.Assignment,'a').draft_revision == 3
    assert db.get(b.Assignment,'a').next_version_number == 4
    assert db.query(b.AssignmentVersion).filter_by(assignment_id='a',source_draft_revision=3).count() == 1
    assert first.result['version_number'] == 3


def test_new_write_archive_refused_but_authorized_original_receipt_recovers(b2case):
    assignments()
    db, _, _, engine, t, m, b, *_ = b2case
    first, intent = write(b2case,'replace_public',{'expected_revision':3,'public_spec':{**PUBLIC,'title':'Accepted'}})
    db.execute(update(m.Offering).where(m.Offering.id=='o').values(state='archived')); db.commit()
    denied(lambda:write(b2case,'replace_public',{'expected_revision':4,'public_spec':PUBLIC},key='archived-new'),409,'lifecycle_conflict')
    replay = engine.execute_write(db,intent,intent.scope,assignments().prepare_assignment_write(db,'owner',None,'a','replace_public',{'expected_revision':3,'public_spec':{**PUBLIC,'title':'Accepted'}},intent.idempotency_key)[1])
    assert replay.replayed and replay.receipt.id == first.receipt.id and replay.result == first.result
    assert db.query(b.AssessmentEvent).count() == 1
    db.execute(update(m.TeachingRole).where(m.TeachingRole.subject_id=='owner').values(permissions=['RELEASE'])); db.commit()
    denied(lambda:engine.find_receipt(db,'owner',t.TeachingAction.ASSIGNMENT_UPDATE,intent.scope,intent.idempotency_key),404)


def test_author_rediscovers_unpublished_draft_after_reload(b2case):
    service = assignments()
    db, *_ = b2case
    created, _ = create(b2case,title='Unpublished recovery')
    db.expire_all()
    page = service.list_assignments(db,'owner','o',page_query())
    item = next(item for item in page.items if item.id == created.result['assignment_id'])
    assert item.projection == 'author_draft' and item.title == 'Unpublished recovery' and item.draft_revision == 1
    assert service.get_assignment_draft(db,'owner',item.id).public_spec.title == item.title
    assert page.as_of == NOW


def test_release_only_catalog_has_frozen_public_summaries_only(b2case):
    service = assignments()
    db, *_ = b2case
    unpublished, _ = create(b2case,title='Never published')
    write(b2case,'replace_public',{'expected_revision':3,'public_spec':{**PUBLIC,'title':'Hidden mutable title'}})
    page = service.list_assignments(db,'releaser','o',page_query())
    assert [item.id for item in page.items] == ['a']
    item = page.items[0].model_dump(mode='json')
    assert item == {'projection':'release_frozen','id':'a','offering_id':'o','title':PUBLIC['title'],'latest_version_id':'v2','latest_version_number':2,'frozen_at':NOW.isoformat(timespec='microseconds').replace('+00:00','Z')}
    assert unpublished.result['assignment_id'] not in json.dumps(item)
    denied(lambda:service.get_assignment_draft(db,'releaser','a'),403)


def test_versions_list_is_ordered_public_and_role_rechecked(b2case):
    service = assignments()
    db, _, _, _, _, m, *_ = b2case
    first = service.list_assignment_versions(db,'releaser','a',page_query(limit=1))
    assert [item.version_number for item in first.items] == [1] and first.next_cursor
    second = service.list_assignment_versions(db,'releaser','a',page_query(limit=1,cursor=first.next_cursor))
    assert [item.version_number for item in second.items] == [2] and second.next_cursor is None
    assert 'private' not in json.dumps(first.model_dump(mode='json'))
    db.execute(update(m.TeachingRole).where(m.TeachingRole.subject_id=='releaser').values(status='revoked',permissions=[])); db.commit()
    denied(lambda:service.list_assignment_versions(db,'releaser','a',page_query(cursor=first.next_cursor)),404)
    denied(lambda:service.get_assignment_version(db,'releaser','a','v'),404)


def test_intentional_identical_public_replace_enables_new_version(b2case):
    assignments()
    db, _, _, _, _, _, b, *_ = b2case
    first, _ = write(b2case,'freeze',{'expected_revision':3})
    replacement, _ = write(b2case,'replace_public',{'expected_revision':3,'public_spec':PUBLIC})
    second, _ = write(b2case,'freeze',{'expected_revision':4},key='freeze-after-explicit-save')
    assert replacement.result['draft_revision'] == 4
    assert (first.result['version_number'],second.result['version_number']) == (3,4)
    assert first.result['public_spec_hash'] == second.result['public_spec_hash']
    assert db.get(b.Assignment,'a').draft_revision == 4


def test_original_receipt_survives_later_revision_and_body_conflict(b2case):
    service = assignments()
    db, _, _, engine, *_ = b2case
    payload = {'expected_revision':3,'public_spec':{**PUBLIC,'title':'First save'}}
    first, intent = write(b2case,'replace_public',payload,key='stable-original')
    write(b2case,'replace_public',{'expected_revision':4,'public_spec':{**PUBLIC,'title':'Second save'}},key='later-save')
    again, _ = write(b2case,'replace_public',payload,key='stable-original')
    assert again.replayed and again.receipt.id == first.receipt.id and again.result == first.result
    assert again.result['draft_revision'] == 4 and service.get_assignment_draft(db,'owner','a').draft_revision == 5
    denied(lambda:write(b2case,'replace_public',{**payload,'public_spec':PUBLIC},key='stable-original'),409,'idempotency_conflict')
    assert first.receipt.original_result == again.receipt.original_result


def test_catalog_cursor_binds_current_projection_actor_and_route(b2case):
    service = assignments()
    db, _, _, _, t, m, *_ = b2case
    create(b2case)
    first = service.list_assignments(db,'owner','o',page_query(limit=1))
    assert first.next_cursor
    denied(lambda:service.list_assignments(db,'releaser','o',page_query(cursor=first.next_cursor)),422,'invalid_cursor')
    db.execute(update(m.TeachingRole).where(m.TeachingRole.subject_id=='owner').values(permissions=['RELEASE'])); db.commit()
    denied(lambda:service.list_assignments(db,'owner','o',page_query(cursor=first.next_cursor)),422,'invalid_cursor')
    db.info['teaching_policy_provider'] = lambda:replace(policy(t),trusted_delegations_json='{}',generation='task3-revoked')
    denied(lambda:service.list_assignments(db,'assistant','o',page_query()),403)


def test_assignment_read_routes_and_commands_are_exact(b2case):
    service = assignments()
    db, *_ = b2case
    denied(lambda:service.get_assignment_version(db,'owner','wrong-assignment','v'),404)
    denied(lambda:service.get_assignment_version(db,'owner','a','missing'),404)
    denied(lambda:service.get_assignment_draft(db,'owner','fa'),404)
    denied(lambda:service.prepare_assignment_write(db,'owner','o',None,'create',{'public_spec':PUBLIC,'owner_id':'owner'},'extra-field-key'),422,'validation_error')
    denied(lambda:service.prepare_assignment_write(db,'owner','o','a','replace_public',{'expected_revision':3,'public_spec':PUBLIC},'ambiguous-route'),422,'validation_error')
    denied(lambda:service.prepare_assignment_write(db,'owner',None,'a','freeze',{'expected_revision':3,'public_spec':PUBLIC},'body-freeze'),422,'validation_error')


def test_source_owner_without_effective_local_role_cannot_discover(b2case):
    service = assignments()
    db, _, _, _, _, m, *_ = b2case
    db.execute(update(m.TeachingRole).where(m.TeachingRole.subject_id=='owner').values(status='revoked',permissions=[])); db.commit()
    denied(lambda:service.list_assignments(db,'owner','o',page_query()),403)
    denied(lambda:service.get_assignment_draft(db,'owner','a'),403)
    denied(lambda:service.list_assignment_versions(db,'owner','a',page_query()),403)
