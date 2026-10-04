"""Finite Tranche 2 tests: synthetic selections and NOT-RUN native acceptance.

The guarded selection names only the unit/synthetic nodes below. Native tests
need an explicitly reviewed, test-owned run supplied by a separate native
launcher; this module never starts a server, creates a schema, or reads secrets.
"""
import asyncio
import importlib
import json
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import event

from tests.test_teaching_assessment_authorization import b2case, PUBLIC


def _support():
    try:
        return importlib.import_module('tests.support.native_assessment_validation')
    except ModuleNotFoundError:
        pytest.fail('the reviewed native validation support is not implemented')


def _owner(case):
    db, *_ = case
    sessions = importlib.import_module('app.services.teaching.sessions')
    owner_type = getattr(sessions, 'B2RequestOwner', None)
    assert owner_type is not None, 'B2 needs a dedicated outcome/session owner'
    return owner_type(db, db.connection())


def _manifest():
    support = _support()
    schema = importlib.import_module('app.services.teaching.schema')
    types = importlib.import_module('app.services.teaching.types')
    run_id = '00000000-0000-4000-8000-000000000001'
    institution = 'nv-0000000000004000'
    actor, learner = 'nv_000000000000_owner', 'nv_000000000000_learner'
    inputs = types.TeachingPolicyInputs(institution_id=institution, enabled=True,
        assignments_enabled=True, trusted_roster_json=json.dumps({actor:[learner]}),
        trusted_delegations_json='{}', generation='native-'+run_id)
    return support.NativeValidationManifest(run_id=run_id,
        identity=schema.DatabaseIdentity('nv_0000000000004000', run_id, '/native/run/', '/native/run/mysql.sock'),
        expires_at=datetime.now(timezone.utc)+timedelta(minutes=30), policy=inputs,
        scopes=(types.ScopeRef(institution, 'offering', '00000000-0000-4000-8000-000000000002'),),
        actor_id=actor, learner_ids=(learner,), code_contract=support.current_code_contract(),
        seed_inventory=tuple(support.SeedInventory(name, (), '0'*64) for name in support.SEED_TABLE_NAMES))


def _app(owner):
    adapter = importlib.import_module('app.api.endpoints.teaching')
    assessment = importlib.import_module('app.api.endpoints.teaching_assessment')
    dependency = getattr(assessment, 'get_b2_write_owner', None)
    assert dependency is not None, 'finite B2 mutations need the owner dependency'
    app = FastAPI()
    app.include_router(assessment.router, prefix='/api')
    async def fixture_owner():
        # This is the same request-lifetime context used by the production
        # owner dependency. Its cleanup runs when FastAPI unwinds the generator.
        with owner:
            yield owner
    app.dependency_overrides[dependency] = fixture_owner
    assert set(app.dependency_overrides) == {dependency}
    return app, adapter, assessment


async def _request(app, method, path, *, actor='owner', key='native-unit-original', **kwargs):
    security = importlib.import_module('app.core.security')
    # The signed claim deliberately disagrees with the actual teacher account.
    headers = {'Authorization':'Bearer '+security.create_access_token(actor, 'student'),
               'Idempotency-Key':key}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://synthetic-asgi') as client:
        return await client.request(method, path, headers=headers, **kwargs)


def _replace(app):
    return asyncio.run(_request(app, 'PATCH', '/api/teaching/assignments/a/draft',
        json={'expected_revision':3, 'public_spec':{**PUBLIC, 'title':'Owned synthetic candidate'}}))


def test_native_manifest_is_immutable_and_exact():
    manifest = _manifest()
    _support()._unsubstituted_contract()  # Code-only check; no native owner/admission.
    with pytest.raises(FrozenInstanceError):
        manifest.run_id = str(UUID(int=3))
    with pytest.raises(ValueError):
        replace(manifest, scopes=())
    with pytest.raises(ValueError):
        replace(manifest, learner_ids=('ordinary-account',))
    with pytest.raises(ValueError):
        replace(manifest, code_contract=manifest.code_contract[:-1])
    with pytest.raises(ValueError):
        replace(manifest, seed_inventory=manifest.seed_inventory[:-1])


def test_native_run_rejects_sqlite_before_schema_or_admission(b2case):
    db, *_ = b2case
    manifest = _manifest()
    attempts = []
    def observed(connection, cursor, statement, parameters, context, executemany):
        attempts.append(statement)
    engine = db.get_bind()
    event.listen(engine, 'before_cursor_execute', observed)
    try:
        with pytest.raises(HTTPException) as denied:
            _support().NativeValidationRun.open(engine, manifest)
        assert denied.value.status_code == 503
        assert denied.value.detail == 'native_validation_unavailable'
        assert attempts == [], 'SQLite must be rejected before identity/schema SQL'
    finally:
        event.remove(engine, 'before_cursor_execute', observed)


def test_production_b2_owner_stays_hard_closed(b2case, monkeypatch):
    db, _, _, writes, _, _, _, _, originals = b2case
    owner = _owner(b2case)
    service = importlib.import_module('app.services.teaching.assignments')
    intent, operation = service.prepare_assignment_write(db, 'owner', None, 'a', 'replace_public',
        {'expected_revision':3, 'public_spec':PUBLIC}, 'production-owner-closed')
    monkeypatch.setattr(writes, '_require_write_safety', originals['hardgate'])
    with pytest.raises(HTTPException) as denied:
        owner.execute(intent, intent.scope, operation)
    assert denied.value.status_code == 503 and denied.value.detail == 'write_safety_unproven'
    assert owner.pending is None
    owner.close()


def test_signed_b2_mutation_uses_exact_owner_session(b2case):
    db, *_ = b2case
    owner = _owner(b2case)
    app, _, _ = _app(owner)
    response = _replace(app)
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'no-store'
    assert owner.pending._controller.context.authorization.actor_id == 'owner'
    assert owner.pending._controller.session is db
    assert owner.pending._controller.connection is owner.connection
    assert owner.pending._controller.context.authorization.account_role == 'teacher'
    assert owner.outcome == 'confirmed' and owner.closed
    assert owner.response.body == response.content


@pytest.mark.parametrize('outcome', ['confirmed', 'ambiguous'])
@pytest.mark.parametrize('fault', ['rollback', 'session_close', 'connection_close'])
def test_dependency_teardown_preserves_prepared_outcome(b2case, monkeypatch, outcome, fault):
    db, *_ = b2case
    owner = _owner(b2case)
    connection = owner.connection
    app, _, _ = _app(owner)
    reached = {'commit':0, 'cleanup':0}
    def commit_fault(*args):
        reached['commit'] += 1
        raise RuntimeError('simulated completion fault')
    target, name = (db, 'after_commit') if outcome == 'confirmed' else (connection, 'commit')
    event.listen(target, name, commit_fault)
    cleanup_target, cleanup_name = {
        'rollback':(db, 'rollback'), 'session_close':(db, 'close'),
        'connection_close':(connection, 'close'),
    }[fault]
    original_cleanup = getattr(cleanup_target, cleanup_name)
    def cleanup_fault(*args, **kwargs):
        reached['cleanup'] += 1
        raise RuntimeError('simulated dependency cleanup fault')
    try:
        with monkeypatch.context() as bounded:
            bounded.setattr(cleanup_target, cleanup_name, cleanup_fault)
            response = _replace(app)
            assert reached['commit'] == 1 and reached['cleanup'] >= 1
            assert owner.closed
            assert connection.closed or connection.invalidated
            assert owner.response.body == response.content
            assert response.headers['cache-control'] == 'no-store'
            if outcome == 'confirmed':
                assert owner.pending._controller.commit_confirmed
                assert owner.outcome == 'confirmed'
                assert response.status_code == 200 and response.json()['message'] == 'ok'
                assert response.json()['data']['result']['draft_revision'] == 4
            else:
                assert not owner.pending._controller.commit_confirmed
                assert owner.outcome == 'possible'
                assert response.status_code == 503
                assert response.json()['message'] == 'write_outcome_unknown'
                assert response.json()['data']['recovery'] == {
                    'action':'assignment_update', 'scope_type':'offering',
                    'scope_id':'o', 'key':'native-unit-original'}
            # Simulated dispatch confidence is explicit: the ambiguous fault
            # interrupts a pre-driver commit event, not a native transport.
            assert owner.pending._controller.commit_dispatched == (outcome == 'confirmed')
        assert getattr(cleanup_target, cleanup_name) == original_cleanup
    finally:
        event.remove(target, name, commit_fault)
        # No observer/query follows invalidation. Original cleanup is restored.
        owner.close()


def test_closed_b2_owner_refuses_reuse_before_sql(b2case):
    db, *_ = b2case
    owner = _owner(b2case)
    app, _, _ = _app(owner)
    assert _replace(app).status_code == 200
    attempts = []
    engine = db.get_bind()
    def observed(connection, cursor, statement, parameters, context, executemany):
        attempts.append(statement)
    event.listen(engine, 'before_cursor_execute', observed)
    try:
        intent = owner.pending._controller.intent
        operation = importlib.import_module('app.services.teaching.assignments')._AssignmentOperation('replace_public')
        with pytest.raises(HTTPException) as denied:
            owner.execute(intent, intent.scope, operation)
        assert denied.value.detail == 'b2_owner_closed' and attempts == []
    finally:
        event.remove(engine, 'before_cursor_execute', observed)


def test_b2_owner_factory_receives_session_owned_physical_root(b2case):
    db, *_ = b2case
    sessions = importlib.import_module('app.services.teaching.sessions')
    from sqlalchemy import text
    from sqlalchemy.orm import Session
    construct = getattr(sessions, '_construct_b2_request_owner', None)
    assert construct is not None, 'B2 owner construction must establish Session root ownership first'
    engine = db.get_bind()
    connection = engine.connect()
    dedicated = Session(bind=connection, autoflush=False, expire_on_commit=False)
    dedicated.begin()
    observed = []
    def verification_factory(session, physical):
        # No NativeRun/NativeOwner, dialect spoof or admission. This ordinary
        # in-memory factory observes the exact binding before verification SQL.
        bindings = session.get_transaction()._connections
        observed.append(physical in bindings and bindings[physical][1] is physical.get_transaction()
                        and bindings[physical][2] is True)
        assert physical.execute(text('SELECT 1')).scalar_one() == 1
        return sessions.B2RequestOwner(session, physical)
    owner = None
    try:
        owner = construct(dedicated, connection, verification_factory)
        assert observed == [True], 'Session must own the physical root before factory verification SQL'
        root = connection.get_transaction()
        dedicated.commit()
        assert not root.is_active and connection.get_transaction() is None
    finally:
        if owner is not None:
            owner.close(preserve_exception=True)
        else:
            dedicated.close(); connection.close()


@pytest.fixture
def native_validation_run(request):
    # Only a separately authorized native launcher may supply this trusted
    # object. Environment, request fields and client headers cannot select it.
    run = getattr(request.config, '_reviewed_native_validation_run', None)
    if run is None:
        pytest.skip('NOT RUN: separate exact native environment/schema/seed/selection approval required')
    assert type(run) is _support().NativeValidationRun
    from sqlalchemy.pool import NullPool
    assert type(run.engine.pool) is NullPool, 'native observers require a non-reusing physical connection pool'
    run.require_open()
    return run


# Native seven-action and critical-negative matrix follows below. These nodes
# are deliberately absent from every source/synthetic registration.


def _native_data(response, status):
    assert response.status_code == status, response.text
    assert response.headers['cache-control'] == 'no-store'
    assert response.json()['code'] == status
    return response.json()['data']


def _native_observe(run, accepted, action):
    """A new native connection under the factory-required non-reusing NullPool.

    Driver-ID inequality is asserted against the pre-kernel writer diagnostic.
    A different SQLAlchemy wrapper is never itself physical evidence.
    """
    from sqlalchemy import select, text
    from app.models.teaching import WriteReceipt
    from app.models.teaching_assessment import AssessmentEvent
    owner = run.owners[-1]
    guard = owner.pending._controller
    assert owner.outcome == 'confirmed' and owner.closed and guard.commit_confirmed
    assert guard.context.authorization.checked_at <= guard.finalized.authorization.checked_at
    assert owner.connection.closed and owner.session.get_transaction() is None
    run.require_open()
    with run.engine.connect().execution_options(isolation_level='READ COMMITTED') as observer:
        observer_id = observer.execute(text('SELECT CONNECTION_ID()')).scalar_one()
        assert type(observer_id) is int and observer_id > 0
        assert observer_id != owner.native_connection_id
        assert observer.get_isolation_level().replace('-', ' ').upper() == 'READ COMMITTED'
        receipt = observer.execute(select(WriteReceipt.__table__).where(
            WriteReceipt.id == accepted['receipt']['id'])).mappings().one()
        events = observer.execute(select(AssessmentEvent.__table__).where(
            AssessmentEvent.receipt_id == receipt['id'])).mappings().all()
        assert receipt['action'] == action and receipt['original_result'] == accepted['result']
        assert len(events) == 1 and events[0]['action'] == action
        assert receipt['actor_id'] == guard.context.authorization.actor_id
        assert accepted['receipt']['id'] == guard.pending.receipt.id
        run.observations.append({'action':action,'receipt_id':receipt['id'],
            'writer_connection_id':owner.native_connection_id,'observer_connection_id':observer_id,
            't0':guard.context.authorization.checked_at.isoformat(),
            't1':guard.finalized.authorization.checked_at.isoformat()})
        return receipt


def test_native_seven_action_signed_acceptance(native_validation_run):
    """NOT RUN here: same actual services, schemas, locks, clocks and owner."""
    run = native_validation_run
    support = _support()
    app = support.native_asgi_app(run)
    manifest = run.manifest
    actor, learner = manifest.actor_id, manifest.learner_ids[0]
    offering = manifest.scopes[0].id
    from app.models.teaching_assessment import (
        Assignment, AssignmentDraftPrivate, AssignmentVersion, PrivateSpec,
        ReleasePreview, Release, ReleaseRecipient, SubmissionHead, Submission,
    )
    from sqlalchemy import select
    private = {'answer_text':'Native synthetic private answer', 'private_test_notes':''}
    def request(method, path, body=None, key='native-original', subject=actor, status=201):
        response = asyncio.run(_request(app, method, '/api/teaching'+path,
            actor=subject, key=key, **({} if body is None else {'json':body})))
        return _native_data(response, status)
    accepted = []
    created = request('POST', f'/offerings/{offering}/assignments', {'public_spec':PUBLIC}, 'native-create')
    accepted.append((created,'assignment_create','native-create',actor))
    _native_observe(run,created,'assignment_create')
    aid = created['result']['assignment_id']
    public = {**PUBLIC,'title':'Native saved public'}
    replaced = request('PATCH',f'/assignments/{aid}/draft',
        {'expected_revision':1,'public_spec':public},'native-public',status=200)
    accepted.append((replaced,'assignment_update','native-public',actor))
    _native_observe(run,replaced,'assignment_update')
    saved = request('PUT',f'/assignments/{aid}/private-draft',
        {'expected_revision':2,'private_spec':private},'native-private',status=200)
    accepted.append((saved,'assignment_private_update','native-private',actor))
    _native_observe(run,saved,'assignment_private_update')
    frozen = request('POST',f'/assignments/{aid}/versions',{'expected_revision':3},'native-freeze')
    accepted.append((frozen,'assignment_freeze','native-freeze',actor))
    _native_observe(run,frozen,'assignment_freeze')
    vid = frozen['result']['version_id']
    preview = request('POST',f'/assignments/{aid}/release-previews',
        {'version_id':vid,'student_ids':list(manifest.learner_ids),'due_at':None,'late_policy':'reject'},'native-preview')
    accepted.append((preview,'release_preview','native-preview',actor))
    _native_observe(run,preview,'release_preview')
    fields = preview['result']
    confirm = {name:fields[name] for name in ('version_id','public_spec_hash','recipient_count','recipient_digest','policy_digest')}
    confirm.update(preview_id=fields['preview_id'],confirmed=True)
    released = request('POST',f'/assignments/{aid}/releases',confirm,'native-release')
    accepted.append((released,'release_create','native-release',actor))
    _native_observe(run,released,'release_create')
    rid = released['result']['release_id']
    body = {'expected_parent_id':None,'content':{'kind':'text','language':None,'text':'Native synthetic answer'},
            'ai_usage_declaration':{'used_ai':False,'description':''}}
    submitted = request('POST',f'/releases/{rid}/submissions',body,'native-submit',learner)
    accepted.append((submitted,'submission_create','native-submit',learner))
    _native_observe(run,submitted,'submission_create')
    sid = submitted['result']['submission_id']
    # Independent physical visibility and all seven action bindings. These are
    # native assertions only, never a replay of the denied SQLite observation.
    with run.engine.connect() as observer:
        def one(model, *criteria):
            return observer.execute(select(model.__table__).where(*criteria)).mappings().one()
        assignment = one(Assignment,Assignment.id==aid)
        assert assignment['public_draft'] == public and assignment['draft_revision'] == 3
        assert assignment['next_version_number'] == 2
        assert one(AssignmentDraftPrivate,AssignmentDraftPrivate.assignment_id==aid)['private_draft'] == private
        assert one(AssignmentVersion,AssignmentVersion.id==vid)['public_spec'] == public
        assert one(PrivateSpec,PrivateSpec.version_id==vid)['private_spec'] == private
        audience = one(ReleasePreview,ReleasePreview.id==fields['preview_id'])
        assert audience['recipient_count'] == len(manifest.learner_ids)
        assert [row['student_id'] for row in audience['recipient_snapshot']] == list(manifest.learner_ids)
        assert one(Release,Release.id==rid)['version_id'] == vid
        recipients = observer.execute(select(ReleaseRecipient.student_id).where(ReleaseRecipient.release_id==rid)).scalars().all()
        assert sorted(recipients) == list(manifest.learner_ids)
        heads = observer.execute(select(SubmissionHead.__table__).where(SubmissionHead.release_id==rid)).mappings().all()
        assert len(heads) == len(manifest.learner_ids)
        assert all((head['submission_id'],head['revision']) == ((sid,1) if head['student_id']==learner else (None,0)) for head in heads)
        assert one(Submission,Submission.id==sid)['content'] == body['content']
    # Exact-key replay and conflict use the same actual route/operation, never
    # side-effecting operation callbacks. No second receipt/event is created.
    replay = request('POST',f'/releases/{rid}/submissions',body,'native-submit',learner,status=200)
    assert replay['replayed'] and replay['receipt'] == submitted['receipt'] and replay['result'] == submitted['result']
    conflict = asyncio.run(_request(app,'POST',f'/api/teaching/releases/{rid}/submissions',
        actor=learner,key='native-submit',json={**body,'content':{**body['content'],'text':'Different'}}))
    assert conflict.status_code == 409 and conflict.json()['message'] == 'idempotency_conflict'
    stale = asyncio.run(_request(app,'POST',f'/api/teaching/releases/{rid}/submissions',
        actor=learner,key='native-stale-parent',json=body))
    assert stale.status_code == 409 and stale.json()['message'] == 'parent_conflict'
    for row,action,key,subject in accepted:
        by_id = request('GET',f"/receipts/{row['receipt']['id']}",subject=subject,status=200)
        by_key_response = asyncio.run(_request(app,'GET','/api/teaching/receipts',actor=subject,
            params={'action':action,'scope_type':'offering','scope_id':offering,'key':key}))
        by_key = _native_data(by_key_response,200)
        assert by_id['receipt'] == by_key['receipt'] == row['receipt']
        assert by_id['result'] == by_key['result'] == row['result']
    capabilities = request('GET','/capabilities',status=200)
    assert not capabilities['writes_available']
    assert not capabilities['can_create_course']
    assert capabilities['write_reason'] == 'write_safety_unproven'
    with run.engine.connect() as observer:
        from app.models.teaching import WriteReceipt, AccessEvent
        from app.models.teaching_assessment import AssessmentEvent
        assert len(observer.execute(select(WriteReceipt.id)).all()) == 7
        assert len(observer.execute(select(AssessmentEvent.id)).all()) == 7
        assert observer.execute(select(AccessEvent.id)).all() == []


@pytest.mark.parametrize('action', ['course_create','course_update','offering_create','course_manage','roster_manage','roles_manage','unknown_action'])
def test_native_owner_rejects_b1_and_unknown_actions(native_validation_run, action):
    run = native_validation_run
    from app.services.teaching import assignments, writes
    from app.services.teaching.types import TeachingAction
    with run.request_owner() as owner:
        scope = run.manifest.scopes[0]
        intent = writes.make_write_intent(run.manifest.actor_id, TeachingAction.ASSIGNMENT_CREATE,
            scope,None,'native-reject-action',{'public_spec':PUBLIC})
        changed = replace(intent,action=TeachingAction(action) if action!='unknown_action' else action)
        with pytest.raises(HTTPException) as denied:
            owner.execute(changed,scope,assignments._AssignmentOperation('create'))
        assert denied.value.status_code == 503 and owner.pending is None


def test_native_owner_rejects_wrong_session_and_changed_transaction(native_validation_run):
    run = native_validation_run
    from app.services.teaching import assignments, writes
    from app.services.teaching.types import TeachingAction
    with run.request_owner() as owner, run.read_session() as other:
        scope = run.manifest.scopes[0]
        intent = writes.make_write_intent(run.manifest.actor_id,TeachingAction.ASSIGNMENT_CREATE,
            scope,None,'native-reject-binding',{'public_spec':PUBLIC})
        operation = assignments._AssignmentOperation('create')
        with pytest.raises(HTTPException) as denied:
            owner.require_admission(other,intent,scope,operation)
        assert denied.value.detail == 'transaction_changed'
        owner.session.rollback()
        with pytest.raises(HTTPException) as denied:
            owner.require_admission(owner.session,intent,scope,operation)
        assert denied.value.detail == 'transaction_changed' and owner.pending is None


def test_native_ordinary_kernel_remains_hard_closed(native_validation_run):
    run = native_validation_run
    from app.services.teaching import assignments, writes
    from app.services.teaching.types import TeachingAction
    with run.request_owner() as owner:
        scope = run.manifest.scopes[0]
        intent = writes.make_write_intent(run.manifest.actor_id,TeachingAction.ASSIGNMENT_CREATE,
            scope,None,'native-ordinary-closed',{'public_spec':PUBLIC})
        with pytest.raises(HTTPException) as denied:
            writes.execute_write(owner.session,intent,scope,assignments._AssignmentOperation('create'))
        assert denied.value.status_code == 503 and denied.value.detail == 'write_safety_unproven'
        assert owner.pending is None


def test_native_owner_rejects_unapproved_scope(native_validation_run):
    run = native_validation_run
    from app.services.teaching import assignments, writes
    from app.services.teaching.types import TeachingAction, ScopeRef
    with run.request_owner() as owner:
        scope = ScopeRef(run.manifest.policy.institution_id,'offering','unapproved-offering')
        intent = writes.make_write_intent(run.manifest.actor_id,TeachingAction.ASSIGNMENT_CREATE,
            scope,None,'native-scope-refused',{'public_spec':PUBLIC})
        with pytest.raises(HTTPException) as denied:
            owner.execute(intent,scope,assignments._AssignmentOperation('create'))
        assert denied.value.detail == 'invalid_native_owner' and owner.pending is None


def test_native_owner_rejects_expired_or_closed_run(native_validation_run):
    run = native_validation_run
    expired = replace(run.manifest,expires_at=datetime.now(timezone.utc)-timedelta(seconds=1))
    with pytest.raises(HTTPException) as denied:
        _support().NativeValidationRun.open(run.engine,expired)
    assert denied.value.detail == 'native_run_closed'
    from app.services.teaching import assignments, writes
    from app.services.teaching.types import TeachingAction
    with run.request_owner() as owner:
        scope = run.manifest.scopes[0]
        intent = writes.make_write_intent(run.manifest.actor_id,TeachingAction.ASSIGNMENT_CREATE,
            scope,None,'native-revoked-run',{'public_spec':PUBLIC})
        run.close()
        with pytest.raises(HTTPException) as denied:
            owner.execute(intent,scope,assignments._AssignmentOperation('create'))
        assert denied.value.detail in {'native_run_closed','b2_owner_closed'} and owner.pending is None
