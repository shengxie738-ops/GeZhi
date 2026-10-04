"""B2 signed-token, isolated ASGI source/synthetic evidence only.

The request app overrides only the dedicated DB dependency. Real signatures and
current persisted UserAccount resolution run. b2case retains its exactly five
reviewed fixture-local substitutions; closed boundaries restore real gates.
No aggregate/startup/server/browser import or production-readiness claim.
"""
import ast
import asyncio
import base64
import json
from datetime import timedelta
from functools import wraps
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete, update
from sqlalchemy.exc import OperationalError

from tests.test_teaching_assessment_authorization import b2case, feature, NOW, PUBLIC, PRIVATE, policy
from tests.test_teaching_bounded_write_finalization import accept_pending


def sync_asgi(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))
    return run


def app_for(case):
    adapter = feature('app.api.endpoints.teaching')
    assessment = feature('app.api.endpoints.teaching_assessment')
    db, *_ = case
    app = FastAPI()
    app.include_router(adapter.router, prefix='/api')
    app.include_router(assessment.router, prefix='/api')
    async def fixture_db():
        return db
    app.dependency_overrides[adapter.get_teaching_db] = fixture_db
    assert set(app.dependency_overrides) == {adapter.get_teaching_db}
    assert assessment.get_teaching_request_account is adapter.get_teaching_request_account
    assert assessment.get_teaching_db is adapter.get_teaching_db
    assert assessment.commit_write is adapter.commit_write
    return app, adapter


async def request(app, method, path, *, actor='owner', token_role='teacher',
                  key='b2-signed-http:123', authorization='signed', **kwargs):
    headers = {} if key is None else {'Idempotency-Key': key}
    if authorization == 'signed':
        token = feature('app.core.security').create_access_token(actor, token_role)
        headers['Authorization'] = 'Bearer ' + token
    elif authorization is not None:
        headers['Authorization'] = authorization
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://synthetic-asgi') as client:
        return await client.request(method, path, headers=headers, **kwargs)


def data(response, status=200):
    assert response.status_code == status, response.text
    assert response.json()['code'] == status
    assert response.headers['cache-control'] == 'no-store'
    for private in ('password_hash', 'phone', 'trusted_roster_json', 'trusted_delegations_json', 'source_policy_digest'):
        assert private not in response.text
    return response.json()['data']


def submission(parent=None, text='第一行\r\nprint("🙂")\n'):
    return {'expected_parent_id':parent, 'content':{'kind':'code','language':'python','text':text},
            'ai_usage_declaration':{'used_ai':True,'description':'Self-reported help'}}


def confirmation(preview):
    return {**{field:preview[field] for field in ('version_id','public_spec_hash','recipient_count','recipient_digest','policy_digest')},
            'preview_id':preview['id'],'confirmed':True}


def recovery(receipt, key):
    return {'action':receipt['action'],'scope_type':'offering','scope_id':'o','key':key}


async def accepted(app, method, path, body, key, *, actor='owner', status=201):
    response = await request(app, method, path, actor=actor, key=key, json=body)
    return data(response, status)


@sync_asgi
async def test_signed_teacher_learner_b2_journey(b2case):
    app, _ = app_for(b2case)
    db, _, _, _, _, m, b, *_ = b2case
    accepted_rows = []
    created = await accepted(app,'POST','/api/teaching/offerings/o/assignments',{'public_spec':PUBLIC},'journey-create')
    aid = created['result']['assignment_id']; accepted_rows.append((created,'journey-create','owner'))
    replaced = await accepted(app,'PATCH',f'/api/teaching/assignments/{aid}/draft',
        {'expected_revision':1,'public_spec':{**PUBLIC,'title':'Saved public'}},'journey-public',status=200)
    accepted_rows.append((replaced,'journey-public','owner'))
    private = await accepted(app,'PUT',f'/api/teaching/assignments/{aid}/private-draft',
        {'expected_revision':2,'private_spec':PRIVATE},'journey-private',status=200)
    accepted_rows.append((private,'journey-private','owner'))
    shown_private = data(await request(app,'GET',f'/api/teaching/assignments/{aid}/private-draft'))
    assert shown_private['private_spec'] == PRIVATE
    frozen = await accepted(app,'POST',f'/api/teaching/assignments/{aid}/versions',{'expected_revision':3},'journey-freeze')
    vid = frozen['result']['version_id']; accepted_rows.append((frozen,'journey-freeze','owner'))
    version = data(await request(app,'GET',f'/api/teaching/assignments/{aid}/versions/{vid}',actor='releaser'))
    assert version['public_spec']['title'] == 'Saved public'
    preview_result = await accepted(app,'POST',f'/api/teaching/assignments/{aid}/release-previews',
        {'version_id':vid,'student_ids':['learner','assistant'],'due_at':None,'late_policy':'reject'},'journey-preview',actor='releaser')
    accepted_rows.append((preview_result,'journey-preview','releaser'))
    pid = preview_result['result']['preview_id']
    preview = data(await request(app,'GET',f'/api/teaching/assignments/{aid}/release-previews/{pid}',actor='releaser'))
    first = data(await request(app,'GET',f'/api/teaching/assignments/{aid}/release-previews/{pid}/recipients',actor='releaser',params={'limit':1}))
    second = data(await request(app,'GET',f'/api/teaching/assignments/{aid}/release-previews/{pid}/recipients',actor='releaser',params={'limit':1,'cursor':first['next_cursor']}))
    assert first['items'] + second['items'] == ['assistant','learner'] and second['next_cursor'] is None
    released = await accepted(app,'POST',f'/api/teaching/assignments/{aid}/releases',confirmation(preview),'journey-release',actor='releaser')
    rid = released['result']['release_id']; accepted_rows.append((released,'journey-release','releaser'))
    own_release = data(await request(app,'GET',f'/api/teaching/releases/{rid}',actor='learner',token_role='teacher'))
    assert own_release['version']['id'] == vid and 'recipient_count' not in own_release
    first_body = submission()
    first_submit = await accepted(app,'POST',f'/api/teaching/releases/{rid}/submissions',first_body,'journey-submit',actor='learner')
    sid = first_submit['result']['submission_id']; accepted_rows.append((first_submit,'journey-submit','learner'))
    head = data(await request(app,'GET',f'/api/teaching/releases/{rid}/my-submission-head',actor='learner'))
    assert head['submission_id'] == sid and head['revision'] == 1
    history = data(await request(app,'GET',f'/api/teaching/releases/{rid}/my-submissions',actor='learner'))
    assert history['current_head_id'] == sid and [item['sequence'] for item in history['items']] == [1]
    assert 'content' not in history['items'][0] and 'student_id' not in history['items'][0]
    stale = await request(app,'POST',f'/api/teaching/releases/{rid}/submissions',actor='learner',key='journey-stale',json=submission())
    data(stale,409); assert stale.json()['message'] == 'parent_conflict'
    second_submit = await accepted(app,'POST',f'/api/teaching/releases/{rid}/submissions',submission(sid,'Newer\n'),'journey-submit-2',actor='learner')
    assert second_submit['result']['sequence'] == 2
    replay = data(await request(app,'POST',f'/api/teaching/releases/{rid}/submissions',actor='learner',key='journey-submit',json=first_body))
    assert replay['replayed'] and replay['receipt'] == first_submit['receipt'] and replay['result'] == first_submit['result']
    teacher = data(await request(app,'GET',f'/api/teaching/submissions/{sid}',actor='viewer'))
    assert teacher['student_id'] == 'learner' and teacher['content']['text'] == first_body['content']['text']
    for row,key,actor in accepted_rows:
        by_id = data(await request(app,'GET',f"/api/teaching/receipts/{row['receipt']['id']}",actor=actor))
        by_key = data(await request(app,'GET','/api/teaching/receipts',actor=actor,params=recovery(row['receipt'],key)))
        assert by_id['receipt'] == by_key['receipt'] == row['receipt']
        assert by_id['result'] == by_key['result'] == row['result']
    assert db.query(b.AssessmentEvent).count() == 8 and db.query(m.AccessEvent).count() == 0
    db.execute(update(m.Enrollment).where(m.Enrollment.student_id=='learner').values(status='withdrawn')); db.commit()
    for path in (f'/api/teaching/releases/{rid}',f'/api/teaching/submissions/{sid}',f"/api/teaching/receipts/{first_submit['receipt']['id']}"):
        response = await request(app,'GET',path,actor='learner')
        data(response,404); assert response.json()['message'] == 'not_found'
    assert db.get(b.ReleaseRecipient,(rid,'learner')) is not None
    historical = data(await request(app,'GET',f'/api/teaching/releases/{rid}/recipients',actor='viewer'))
    assert historical['projection'] == 'historical_recipients' and 'learner' in historical['items']


@sync_asgi
async def test_current_account_role_change_rechecked(b2case):
    app, _ = app_for(b2case)
    db, _, _, _, _, _, _, accounts, _ = b2case
    token = feature('app.core.security').create_access_token('releaser','teacher')
    auth = 'Bearer ' + token
    data(await request(app,'GET','/api/teaching/assignments/a/versions/v',authorization=auth))
    db.execute(update(accounts.UserAccount).where(accounts.UserAccount.username=='releaser').values(role='student')); db.commit()
    data(await request(app,'GET','/api/teaching/assignments/a/versions/v',authorization=auth),404)
    db.execute(update(accounts.UserAccount).where(accounts.UserAccount.username=='releaser').values(role='admin')); db.commit()
    response = await request(app,'GET','/api/teaching/assignments/a/versions/v',authorization=auth)
    data(response,401); assert response.json()['message'] == 'unauthenticated'
    for auth in (None,'Bearer invalid','Basic nonsense'):
        response = await request(app,'GET','/api/teaching/releases/r',authorization=auth)
        data(response,401); assert response.json()['message'] == 'unauthenticated'


@sync_asgi
@pytest.mark.parametrize('boundary', ['default_off','assignment_off','b1_vendor','b2_missing','b2_incompatible','transaction','hardgate'])
async def test_default_off_missing_incompatible_schema_are_not_empty_success(b2case,monkeypatch,boundary):
    app, _ = app_for(b2case)
    db, a, aa, w, t, m, b, _, originals = b2case
    if boundary == 'default_off':
        db.info['teaching_policy_provider'] = lambda:policy(t,enabled=False)
    elif boundary == 'assignment_off':
        db.info['teaching_policy_provider'] = lambda:policy(t,assignments=False)
    elif boundary == 'b1_vendor':
        monkeypatch.setattr(a,'require_teaching_schema',originals['b1'])
    elif boundary in {'b2_missing','b2_incompatible'}:
        ledger = feature('app.models.teaching_schema').TeachingSchemaVersion
        if boundary == 'b2_missing':
            db.execute(delete(ledger).where(ledger.component=='b2'))
        else:
            db.execute(update(ledger).where(ledger.component=='b2').values(contract_hash='0'*64))
        db.commit()
        monkeypatch.setattr(aa,'require_assessment_schema',originals['b2'])
    else:
        monkeypatch.setattr(w,'_require_transaction' if boundary=='transaction' else '_require_write_safety',originals[boundary])
    response = await request(app,'POST','/api/teaching/offerings/o/assignments',json={'public_spec':PUBLIC})
    data(response,503)
    reasons = {'default_off':'feature_disabled','assignment_off':'assessment_disabled','b1_vendor':'teaching_schema_incompatible',
               'b2_missing':'assessment_schema_incompatible','b2_incompatible':'assessment_schema_incompatible',
               'transaction':'lock_orchestration_required','hardgate':'write_safety_unproven'}
    assert response.json()['message'] == reasons[boundary]
    assert db.query(m.WriteReceipt).count() == db.query(b.AssessmentEvent).count() == 0
    if boundary not in {'transaction','hardgate'}:
        data(await request(app,'GET','/api/teaching/offerings/o/assignments'),503)


@sync_asgi
@pytest.mark.parametrize('committed',[False,True])
async def test_commit_failure_is_unknown_and_same_key_recovery(b2case,monkeypatch,committed):
    app, _ = app_for(b2case)
    db, _, _, _, _, m, b, *_ = b2case
    original_commit = db.commit
    def fail_commit():
        if committed:
            original_commit()
        raise OperationalError('synthetic commit',{},RuntimeError('PRIVATE COMMIT TEXT'))
    with monkeypatch.context() as patch:
        patch.setattr(db,'commit',fail_commit)
        response = await request(app,'POST','/api/teaching/offerings/o/assignments',key='unknown-original',json={'public_spec':PUBLIC})
    expected = {'action':'assignment_create','scope_type':'offering','scope_id':'o','key':'unknown-original'}
    shown = data(response,201 if committed else 503)
    assert response.json()['message'] == ('ok' if committed else 'write_outcome_unknown')
    if not committed: assert shown == {'recovery':expected}
    assert 'PRIVATE COMMIT TEXT' not in response.text
    recovered = await request(app,'GET','/api/teaching/receipts',params=expected)
    if committed:
        original = data(recovered)
        assert original['receipt'] == shown['receipt'] and original['result'] == shown['result']
        retry = data(await request(app,'POST','/api/teaching/offerings/o/assignments',key='unknown-original',json={'public_spec':PUBLIC}))
        assert retry['replayed'] and retry['receipt'] == original['receipt'] and retry['result'] == original['result']
    else:
        data(recovered,404)
        # Unknown outcome does not authorize a replacement key. Same intent only.
        retry = data(await request(app,'POST','/api/teaching/offerings/o/assignments',key='unknown-original',json={'public_spec':PUBLIC}),201)
        assert not retry['replayed']
    assert db.query(m.WriteReceipt).count() == db.query(b.AssessmentEvent).count() == 1


@sync_asgi
async def test_send_loss_then_newer_get_does_not_rewrite_receipt(b2case,monkeypatch):
    app, _ = app_for(b2case)
    db, _, _, w, _, m, b, *_ = b2case
    # Ordinary successful HTTP business flow. The client sets the first response
    # aside as if delivery was lost; no callback mutates business/replay state.
    first = await request(app,'POST','/api/teaching/releases/r/submissions',actor='assistant',key='lost-original',json=submission())
    original = data(first,201)
    sid = original['result']['submission_id']
    assert db.get(b.Submission,sid) is not None
    await accepted(app,'POST','/api/teaching/releases/r/submissions',submission(sid,'Newer'),'newer-after-loss',actor='assistant')
    db.execute(update(m.Offering).where(m.Offering.id=='o').values(state='archived')); db.commit()
    monkeypatch.setattr(w,'_server_clock',lambda session:NOW+timedelta(days=1))
    newer = data(await request(app,'GET','/api/teaching/releases/r/my-submission-head',actor='assistant'))
    assert newer['revision'] == 2 and newer['submission_id'] != sid
    by_id = data(await request(app,'GET',f"/api/teaching/receipts/{original['receipt']['id']}",actor='assistant'))
    by_key = data(await request(app,'GET','/api/teaching/receipts',actor='assistant',params=recovery(original['receipt'],'lost-original')))
    replay = data(await request(app,'POST','/api/teaching/releases/r/submissions',actor='assistant',key='lost-original',json=submission()))
    assert by_id['receipt'] == by_key['receipt'] == replay['receipt'] == original['receipt']
    assert by_id['result'] == by_key['result'] == replay['result'] == original['result']
    assert replay['replayed'] and replay['receipt']['http_status'] == 201


@sync_asgi
async def test_private_answer_absent_from_every_student_envelope(b2case):
    app, _ = app_for(b2case)
    own = await accepted(app,'POST','/api/teaching/releases/r/submissions',submission(),'privacy-submit',actor='assistant')
    sid = own['result']['submission_id']
    paths = ['/api/teaching/offerings/o/releases','/api/teaching/releases/r',
        '/api/teaching/releases/r/my-submission-head','/api/teaching/releases/r/my-submissions',
        f'/api/teaching/submissions/{sid}',f"/api/teaching/receipts/{own['receipt']['id']}",
        '/api/teaching/assignments/a/private-draft','/api/teaching/assignments/a/versions/v/private-spec',
        '/api/teaching/releases/r/recipients','/api/teaching/releases/r/submissions']
    for path in paths:
        response = await request(app,'GET',path,actor='assistant',token_role='student')
        assert response.status_code in {200,403}, response.text
        assert response.headers['cache-control'] == 'no-store'
        for private in ('private answer','answer_text','private_test_notes','private_spec_hash','recipient_digest'):
            assert private not in response.text
    response = await request(app,'GET','/api/teaching/assignments/a/versions/v/private-spec',actor='learner')
    data(response,403)
    assert 'private answer' not in response.text
    assert own['result'].get('execution_status') is None and own['result'].get('grade') is None
    shown = data(await request(app,'GET',f'/api/teaching/submissions/{sid}',actor='assistant'))
    assert shown['execution_status'] == 'not_available' and shown['assessment_status'] == 'not_implemented'
    assert 'student_id' not in shown


def test_private_exception_text_and_sql_parameters_are_not_logged(caplog):
    adapter = feature('app.api.endpoints.teaching')
    for exc in (RuntimeError('private answer authored text'),OperationalError('SELECT private answer',{'secret':'SQL PARAM PRIVATE'},RuntimeError('raw SQL exception'))):
        try:
            raise exc
        except Exception:
            response = adapter._private_error()
        payload = json.loads(response.body)
        assert payload['code'] == 500 and payload['message'] == 'internal_error'
        assert set(payload['data']) == {'correlation_id'}
        assert payload['data']['correlation_id'] in caplog.text
        record = caplog.records[-1]
        assert type(exc).__name__ in record.getMessage()
        assert record.exc_info is None and record.stack_info is None
    for secret in ('private answer','authored text','SQL PARAM PRIVATE','SELECT','raw SQL exception'):
        assert secret not in caplog.text


@sync_asgi
async def test_strict_paths_queries_and_unknown_fields(b2case):
    app, _ = app_for(b2case)
    lists = ['/api/teaching/offerings/o/assignments','/api/teaching/assignments/a/versions',
        '/api/teaching/assignments/a/release-previews/p/recipients','/api/teaching/offerings/o/releases',
        '/api/teaching/releases/r/recipients','/api/teaching/releases/r/my-submissions','/api/teaching/releases/r/submissions']
    for path in lists:
        actor = 'learner' if path.endswith('/my-submissions') else 'owner'
        for params in ([('limit','1'),('limit','2')],{'limit':'01'},{'limit':'0'},{'limit':'101'},{'limit':'true'},{'limit':'+1'},{'cursor':''},{'owner_id':'owner'}):
            data(await request(app,'GET',path,actor=actor,params=params),422)
    details = ['/api/teaching/assignments/a/draft','/api/teaching/assignments/a/private-draft',
        '/api/teaching/assignments/a/versions/v','/api/teaching/assignments/a/versions/v/private-spec',
        '/api/teaching/assignments/a/release-previews/p','/api/teaching/releases/r','/api/teaching/submissions/s',
        '/api/teaching/releases/r/my-submission-head']
    for path in details:
        actor = 'learner' if path.endswith('/my-submission-head') else 'owner'
        data(await request(app,'GET',path,actor=actor,params={'unexpected':'value'}),422)
    for path in ['/api/teaching/assignments/%20a/draft','/api/teaching/assignments/fa/draft',
                 '/api/teaching/assignments/wrong/versions/v','/api/teaching/releases/missing',
                 '/api/teaching/submissions/missing']:
        response = await request(app,'GET',path)
        data(response,404); assert response.json()['message'] == 'not_found'
    writes = [('POST','/api/teaching/offerings/o/assignments',{'public_spec':PUBLIC}),
        ('PATCH','/api/teaching/assignments/a/draft',{'expected_revision':3,'public_spec':PUBLIC}),
        ('PUT','/api/teaching/assignments/a/private-draft',{'expected_revision':3,'private_spec':PRIVATE}),
        ('POST','/api/teaching/assignments/a/versions',{'expected_revision':3}),
        ('POST','/api/teaching/assignments/a/release-previews',{'version_id':'v2','student_ids':['learner'],'due_at':None,'late_policy':'reject'}),
        ('POST','/api/teaching/assignments/a/releases',{'preview_id':'p2','version_id':'v2','public_spec_hash':'a'*64,'recipient_count':2,'recipient_digest':'a'*64,'policy_digest':'a'*64,'confirmed':True}),
        ('POST','/api/teaching/releases/r/submissions',submission())]
    for method,path,body in writes:
        for bad in ({**body,'actor_id':'owner'},body):
            data(await request(app,method,path,json=bad,key=None if bad is body else 'strict-extra'),422)
        data(await request(app,method,path,json=body,params={'unexpected':'value'}),422)
    for student in ('',' learner','learner\n'):
        data(await request(app,'GET','/api/teaching/releases/r/submissions',params={'student_id':student}),422)
    invalid = {'version_id':'v2','student_ids':['learner'],'due_at':'2026-10-03T15:00:00.1234567Z','late_policy':'reject'}
    data(await request(app,'POST','/api/teaching/assignments/a/release-previews',json=invalid),422)


@sync_asgi
async def test_capabilities_never_advertise_writes_or_assessment(b2case):
    app, _ = app_for(b2case)
    db, _, _, _, t, *_ = b2case
    shown = data(await request(app,'GET','/api/teaching/capabilities'))
    assert shown['assignments']['configured'] and shown['assignments']['installed'] and shown['assignments']['available']
    assert shown['assignments']['reason'] == 'read_ready'
    assert shown['writes_available'] is False and shown['can_create_course'] is False
    for stage in ('assignments','feedback','revisions'):
        assert shown[stage]['writes_available'] is False and shown[stage]['write_reason'] == 'write_safety_unproven'
    assert not shown['feedback']['available'] and not shown['revisions']['available']
    offering = data(await request(app,'GET','/api/teaching/offerings/o'))
    assert offering['access']['available_actions'] == []
    ledger = feature('app.models.teaching_schema').TeachingSchemaVersion
    db.execute(update(ledger).where(ledger.component=='b2').values(contract_hash='0'*64)); db.commit()
    incompatible = data(await request(app,'GET','/api/teaching/capabilities'))['assignments']
    assert incompatible['configured'] and not incompatible['installed'] and not incompatible['available']
    assert incompatible['reason'] == 'assessment_schema_incompatible'
    db.info['teaching_policy_provider'] = lambda:policy(t,enabled=False)
    off = data(await request(app,'GET','/api/teaching/capabilities'))
    assert not off['available'] and not off['assignments']['available']
    assert off['assignments']['reason'] == 'dependency_disabled'


def test_router_mount_is_structural_only():
    tree = ast.parse((Path(__file__).parents[1]/'app/api/api.py').read_text())
    imports = [node for node in ast.walk(tree) if isinstance(node,ast.ImportFrom) and node.module=='app.api.endpoints']
    assert sum(alias.name=='teaching_assessment' for node in imports for alias in node.names) == 1
    includes = [node for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='include_router']
    assert sum(bool(node.args) and ast.unparse(node.args[0])=='teaching_assessment.router' for node in includes) == 1
    source = (Path(__file__).parents[1]/'app/api/endpoints/teaching_assessment.py')
    assert source.is_file(), 'Standalone B2 router missing'
    adapter = ast.parse(source.read_text())
    forbidden = {'app.main','app.api.api','app.core.init_db'}
    assert not any(isinstance(node,ast.ImportFrom) and node.module in forbidden for node in ast.walk(adapter))


@sync_asgi
async def test_catalog_reload_and_release_only_projection(b2case):
    app, _ = app_for(b2case)
    db, _, _, _, _, m, *_ = b2case
    created = await accepted(app,'POST','/api/teaching/offerings/o/assignments',{'public_spec':{**PUBLIC,'title':'Unpublished'}},'catalog-new')
    aid = created['result']['assignment_id']
    db.expire_all()
    author = data(await request(app,'GET','/api/teaching/offerings/o/assignments'))
    assert any(item['id']==aid and item['projection']=='author_draft' and item['title']=='Unpublished' for item in author['items'])
    await accepted(app,'PATCH','/api/teaching/assignments/a/draft',{'expected_revision':3,'public_spec':{**PUBLIC,'title':'Hidden later draft'}},'catalog-edit',status=200)
    release = data(await request(app,'GET','/api/teaching/offerings/o/assignments',actor='releaser'))
    assert [item['id'] for item in release['items']] == ['a']
    assert release['items'][0]['projection'] == 'release_frozen' and release['items'][0]['title'] == PUBLIC['title']
    assert 'draft_revision' not in release['items'][0] and 'updated_at' not in release['items'][0]
    first = data(await request(app,'GET','/api/teaching/assignments/a/versions',actor='releaser',params={'limit':1}))
    assert first['items'][0]['version_number'] == 1 and first['next_cursor']
    second = data(await request(app,'GET','/api/teaching/assignments/a/versions',actor='releaser',params={'limit':1,'cursor':first['next_cursor']}))
    assert [item['version_number'] for item in second['items']] == [2]
    db.execute(update(m.TeachingRole).where(m.TeachingRole.subject_id=='releaser').values(status='revoked',permissions=[])); db.commit()
    data(await request(app,'GET','/api/teaching/assignments/a/versions',actor='releaser',params={'cursor':first['next_cursor']}),404)
    data(await request(app,'GET','/api/teaching/assignments/a/versions/v',actor='releaser'),404)


@sync_asgi
async def test_unicode_maximum_subjects_paginate(b2case):
    app, _ = app_for(b2case)
    db, _, _, _, t, m, _, accounts, _ = b2case
    students = ['\U00020000'*254+char for char in ('甲','乙','丙')]
    for index,student in enumerate(students):
        db.add(accounts.UserAccount(username=student,role='student',password_hash='synthetic-only'))
        db.add(m.Enrollment(id='unicode-'+str(index),institution_id='school',offering_id='o',student_id=student,status='active',
            effective_from=NOW-timedelta(days=1),revision=1,source_kind='deployment_roster',source_teacher_id='owner',source_policy_digest='a'*64,created_at=NOW,updated_at=NOW))
    db.commit(); db.info['teaching_policy_provider'] = lambda:policy(t,roster=students)
    accepted_preview = await accepted(app,'POST','/api/teaching/assignments/a/release-previews',
        {'version_id':'v2','student_ids':students,'due_at':None,'late_policy':'reject'},'unicode-preview',actor='releaser')
    pid = accepted_preview['result']['preview_id']
    found = []; cursor = None
    while True:
        params = {'limit':1,**({'cursor':cursor} if cursor else {})}
        page = data(await request(app,'GET',f'/api/teaching/assignments/a/release-previews/{pid}/recipients',actor='releaser',params=params))
        found.extend(page['items']); cursor = page['next_cursor']
        if cursor is None: break
    assert found == sorted(students) and len(found) == 3
    shown = data(await request(app,'GET',f'/api/teaching/assignments/a/release-previews/{pid}',actor='releaser'))
    release = await accepted(app,'POST','/api/teaching/assignments/a/releases',confirmation(shown),'unicode-confirm',actor='releaser')
    rid = release['result']['release_id']
    first = await accepted(app,'POST',f'/api/teaching/releases/{rid}/submissions',submission(),'unicode-submit',actor=students[0])
    teacher = data(await request(app,'GET',f'/api/teaching/releases/{rid}/submissions',actor='viewer',params={'student_id':students[0]}))
    assert teacher['current_head_id'] == first['result']['submission_id'] and teacher['items'][0]['student_id'] == students[0]


@sync_asgi
async def test_cursor_encoding_json_fields_bindings_and_limits(b2case):
    app, _ = app_for(b2case)
    codec = feature('app.services.teaching.assessment_pagination')
    actor = '\U00020000'*255; identifier = '\U00020000'*36; student = '\U00020000'*255
    encoded = codec.encode_cursor('teacher_heads',identifier,actor,student_id=student,after_student_id=student)
    raw = base64.urlsafe_b64decode(encoded+'='*((-len(encoded))%4))
    assert len(raw) == 3301 and len(encoded) == 4402
    assert len(raw) <= 6144 and len(encoded) <= 8192
    cases = [('/api/teaching/offerings/o/assignments','owner','assignment_catalog_author','o',{'after_id':'a'}),
        ('/api/teaching/offerings/o/assignments','releaser','assignment_catalog_release','o',{'after_id':'a'}),
        ('/api/teaching/assignments/a/versions','owner','assignment_versions','a',{'after_version_number':1}),
        ('/api/teaching/offerings/o/releases','owner','releases','o',{'after_id':'r'}),
        ('/api/teaching/assignments/a/release-previews/p/recipients','owner','preview_recipients','p',{'after_student_id':'assistant'}),
        ('/api/teaching/releases/r/recipients','owner','historical_recipients','r',{'after_student_id':'assistant'}),
        ('/api/teaching/releases/r/my-submissions','learner','own_history','r',{'student_id':'learner','after_sequence':1}),
        ('/api/teaching/releases/r/submissions','viewer','teacher_heads','r',{'student_id':None,'after_student_id':'learner'}),
        ('/api/teaching/releases/r/submissions','viewer','teacher_history','r',{'student_id':'learner','after_sequence':1})]
    def token(raw):
        return base64.urlsafe_b64encode(raw).decode().rstrip('=')
    for path,actor,kind,obj,position in cases:
        valid = codec.encode_cursor(kind,obj,actor,**position)
        query = {'student_id':position['student_id']} if kind=='teacher_history' else {}
        if kind=='own_history':
            # Own history binds the actor inside its cursor, never a caller filter.
            data(await request(app,'GET',path,actor=actor,params={'student_id':actor,'cursor':valid}),422)
        data(await request(app,'GET',path,actor=actor,params={**query,'cursor':valid}))
        payload = json.loads(base64.urlsafe_b64decode(valid+'='*((-len(valid))%4)))
        altered = [{**payload,'actor_id':'outsider'},{**payload,'object_id':'wrong'},
            {**payload,'kind':'unknown'},{**payload,'unused':None},{**payload,'v':True}]
        if kind=='teacher_heads':
            altered.append({key:value for key,value in payload.items() if key!='student_id'})
        invalid = ['***',valid+'=',valid+'\n',token(b'\xff'),token(b'{"v":1,"v":1}'),token(b'NaN'),token(b'[]'),
                   'a'*8193,token(b' '*6145)]
        invalid += [token(json.dumps(item,separators=(',',':')).encode()) for item in altered]
        for cursor in invalid:
            data(await request(app,'GET',path,actor=actor,params={**query,'cursor':cursor}),422)


@sync_asgi
async def test_original_receipt_detail_rejects_queries_and_malformed_ids(b2case):
    adapter = feature('app.api.endpoints.teaching')
    db, _, _, engine, *_ = b2case
    service = feature('app.services.teaching.assignments')
    intent, operation = service.prepare_assignment_write(db,'owner','o',None,'create',{'public_spec':PUBLIC},'strict-receipt-original')
    accepted_result = accept_pending(db,engine.execute_write(db,intent,intent.scope,operation),intent)
    app = FastAPI(); app.include_router(adapter.router,prefix='/api')
    async def fixture_db():
        return db
    app.dependency_overrides[adapter.get_teaching_db] = fixture_db
    assert set(app.dependency_overrides) == {adapter.get_teaching_db}
    path = '/api/teaching/receipts/' + accepted_result.receipt.id
    original = data(await request(app,'GET',path))
    assert original['receipt']['id'] == accepted_result.receipt.id
    for params in ({'unexpected':'value'},[('unexpected','one'),('unexpected','two')]):
        data(await request(app,'GET',path,params=params),422)
    for malformed in ('%20','x'*37,'bad%0Aid'):
        response = await request(app,'GET','/api/teaching/receipts/'+malformed)
        data(response,404); assert response.json()['message'] == 'not_found'
