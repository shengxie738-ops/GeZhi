"""Tranche 1 source/synthetic protocol evidence, never native wait proof.

Only the five historical fixture targets are substituted. Clock sequences use
that same test-only clock target; transaction/SQL/encoding/commit guards run.
"""
import importlib
import json
from dataclasses import replace
from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text, update
from sqlalchemy.orm import Session

from tests.test_teaching_assessment_authorization import b2case, NOW, PUBLIC, policy


def modules():
    return (importlib.import_module('app.services.teaching.writes'),
            importlib.import_module('app.api.endpoints.teaching'))



def intent_for(case, kind='update', key='finalization-original'):
    db, _, _, w, *_ = case
    if kind == 'submission':
        service = importlib.import_module('app.services.teaching.submissions')
        body = {'expected_parent_id':None,'content':{'kind':'text','language':None,'text':'Synthetic answer'},
                'ai_usage_declaration':{'used_ai':False,'description':''}}
        return service.prepare_submission_write(db,'assistant','r',body,key)
    if kind in {'preview','release'}:
        service = importlib.import_module('app.services.teaching.releases')
        body = {'version_id':'v2','student_ids':['assistant','learner'],'due_at':None,'late_policy':'reject'}
        if kind == 'release':
            # Saved fixture values, before execution's t0. No extra read-clock
            # admission consumes the controlled candidate/final clock sequence.
            b = importlib.import_module('app.models.teaching_assessment')
            preview = db.get(b.ReleasePreview,'p2')
            body = {**{name:getattr(preview,name) for name in ('version_id','public_spec_hash','recipient_count','recipient_digest','policy_digest')},'preview_id':'p2','confirmed':True}
        return service.prepare_release_write(db,'owner','a','preview' if kind=='preview' else 'confirm',body,key)
    service = importlib.import_module('app.services.teaching.assignments')
    return service.prepare_assignment_write(db,'owner',None,'a','replace_public',
        {'expected_revision':3,'public_spec':{**PUBLIC,'title':'Candidate'}},key)


def stage(case, kind='update', key='finalization-original'):
    db, _, _, w, *_ = case
    intent, operation = intent_for(case,kind,key)
    pending = w.execute_write(db,intent,intent.scope,operation)
    pending_type = getattr(w,'B2PendingWrite',None)
    assert pending_type is not None and isinstance(pending,pending_type), 'B2 must return a guarded pending write'
    return pending, intent


def complete(case, pending, intent):
    db, *_ = case
    _, adapter = modules()
    owner = getattr(adapter,'commit_pending_write',None)
    assert owner is not None, 'B2 requires the byte-encoding final owner'
    return owner(db,pending,intent)


def accept_pending(db, pending, intent):
    """Historical synthetic helpers now use the real byte-encoding owner."""
    _, adapter = modules()
    response = adapter.commit_pending_write(db,pending,intent)
    if response.status_code >= 400:
        raise HTTPException(response.status_code,json.loads(response.body)['message'])
    return pending.projection


def abandon(case, pending):
    db, _, _, w, *_ = case
    w.rollback_pending_write(db,pending)


def count_effects(case):
    db, _, _, _, _, m, b, *_ = case
    return db.query(m.WriteReceipt).count(), db.query(b.AssessmentEvent).count()


def set_clocks(monkeypatch, case, *times):
    _, _, _, w, *_ = case
    values = iter(times)
    monkeypatch.setattr(w,'_server_clock',lambda session:next(values))


@pytest.mark.parametrize('kind',['update','submission','preview','release'])
def test_pending_owner_preserves_baseline_and_candidate_time(b2case,monkeypatch,kind):
    set_clocks(monkeypatch,b2case,NOW,NOW+timedelta(seconds=2))
    pending,intent = stage(b2case,kind)
    candidate = pending.receipt.model_dump(mode='json')
    response = complete(b2case,pending,intent)
    assert response.status_code in {200,201}
    body = json.loads(response.body)
    assert body['data']['receipt'] == candidate
    assert pending.receipt.accepted_at == NOW
    assert count_effects(b2case) == (1,1)


@pytest.mark.parametrize('kind',['submission','preview','release'])
def test_final_deadline_refusal_rolls_back_every_staged_effect(b2case,monkeypatch,kind):
    db, _, _, _, _, _, b, *_ = b2case
    due = NOW+timedelta(seconds=1)
    w,_ = modules(); digest = __import__('hashlib').sha256(w._json({'version':1,'due_at':due,'timezone':'UTC','late_policy':'reject'}).encode()).hexdigest()
    if kind == 'submission':
        db.execute(update(b.Release).where(b.Release.id=='r').values(due_at=due,policy_digest=digest)); db.commit()
    elif kind == 'release':
        # The ordinary confirm DTO binds this saved deadline policy.
        db.execute(update(b.ReleasePreview).where(b.ReleasePreview.id=='p2').values(due_at=due,policy_digest=digest)); db.commit()
    set_clocks(monkeypatch,b2case,NOW,NOW+(timedelta(minutes=15) if kind=='preview' else timedelta(seconds=1)))
    pending,intent = stage(b2case,kind)
    with pytest.raises(HTTPException) as denied:
        complete(b2case,pending,intent)
    assert denied.value.detail == ('preview_expired' if kind=='preview' else 'deadline_closed')
    assert count_effects(b2case) == (0,0)
    if kind == 'submission': assert db.get(b.SubmissionHead,('r','assistant')).revision == 0
    if kind == 'release': assert db.query(b.Release).filter_by(version_id='v2').count() == 0


@pytest.mark.parametrize('relationship',['actor','recipient'])
def test_final_authority_and_all_recipient_periods_are_current(b2case,monkeypatch,relationship):
    db, _, _, _, _, m, *_ = b2case
    model = m.TeachingRole if relationship=='actor' else m.Enrollment
    condition = model.subject_id=='owner' if relationship=='actor' else model.student_id=='learner'
    db.execute(update(model).where(condition).values(effective_until=NOW+timedelta(seconds=1))); db.commit()
    set_clocks(monkeypatch,b2case,NOW,NOW+timedelta(seconds=1))
    pending,intent = stage(b2case,'release' if relationship=='recipient' else 'update')
    with pytest.raises(HTTPException) as denied: complete(b2case,pending,intent)
    assert denied.value.status_code in {403,404,422}
    assert count_effects(b2case) == (0,0)


def test_final_policy_change_rejects_without_expanding_held_footprint(b2case,monkeypatch):
    db, _, _, _, t, *_ = b2case
    pending,intent = stage(b2case)
    db.info['teaching_policy_provider'] = lambda:policy(t,generation='changed-after-stage')
    with pytest.raises(HTTPException) as denied: complete(b2case,pending,intent)
    assert denied.value.detail == 'lock_footprint_changed'
    assert count_effects(b2case) == (0,0)


@pytest.mark.parametrize('delta',[timedelta(microseconds=-1),None])
def test_final_clock_rejects_backward_or_invalid_time(b2case,monkeypatch,delta):
    set_clocks(monkeypatch,b2case,NOW,None if delta is None else NOW+delta)
    pending,intent = stage(b2case)
    with pytest.raises(HTTPException) as denied: complete(b2case,pending,intent)
    assert denied.value.detail == 'invalid_authorization_clock'
    assert count_effects(b2case) == (0,0)


@pytest.mark.parametrize('sql_route',['orm','connection','commit'])
def test_handoff_keeps_continuous_sql_and_owner_guards(b2case,sql_route):
    db, *_ = b2case
    pending,intent = stage(b2case)
    with pytest.raises(HTTPException) as denied:
        if sql_route=='orm': db.execute(text('SELECT 1'))
        elif sql_route=='connection': db.connection().execute(text('SELECT 1'))
        else: db.commit()
    assert denied.value.detail in {'post_clock_query_forbidden','service_commit_forbidden'}
    abandon(b2case,pending)
    assert count_effects(b2case) == (0,0)


def test_pending_mutation_cannot_be_flushed_or_finalized(b2case):
    db, _, _, _, _, _, b, *_ = b2case
    pending,intent = stage(b2case)
    with pytest.raises(HTTPException):
        # Held draft is already loaded; no new query/discovery happens here.
        next(row for row in db.identity_map.values() if isinstance(row,b.Assignment) and row.id=='a').draft_revision = 99
        db.flush()
    abandon(b2case,pending)
    assert count_effects(b2case) == (0,0)


def test_full_json_byte_encoding_failure_is_precommit_and_rolls_back(b2case):
    pending,intent = stage(b2case)
    pending.result['invalid_json_text'] = '\ud800'
    with pytest.raises(ValueError): complete(b2case,pending,intent)
    assert count_effects(b2case) == (0,0)


@pytest.mark.parametrize('cleanup_failure',[False,True])
def test_commit_dispatch_exception_keeps_original_unknown_envelope(b2case,monkeypatch,cleanup_failure):
    db, *_ = b2case
    pending,intent = stage(b2case)
    connection = db.connection()
    reached = []
    def unavailable(connection):
        reached.append('commit')
        raise RuntimeError('synthetic commit transport loss')
    def failed_cleanup():
        reached.append('rollback')
        raise RuntimeError('synthetic rollback transport loss')
    event.listen(connection,'commit',unavailable)
    try:
        with monkeypatch.context() as fault:
            if cleanup_failure: fault.setattr(db,'rollback',failed_cleanup)
            response = complete(b2case,pending,intent)
        body = json.loads(response.body)
        assert response.status_code == 503 and body['message'] == 'write_outcome_unknown'
        assert body['data']['recovery'] == {'action':intent.action.value,'scope_type':'offering','scope_id':'o','key':intent.idempotency_key}
        assert reached == (['commit','rollback'] if cleanup_failure else ['commit'])
    finally:
        event.remove(connection,'commit',unavailable)


def test_sealed_commit_rejects_sql_after_final_admission(b2case):
    db, *_ = b2case
    pending,intent = stage(b2case)
    connection = db.connection()
    def late_sql(connection): connection.execute(text('SELECT 1'))
    event.listen(connection,'commit',late_sql)
    try:
        response = complete(b2case,pending,intent)
        assert json.loads(response.body)['message'] == 'write_outcome_unknown'
    finally: event.remove(connection,'commit',late_sql)
    assert count_effects(b2case) == (0,0)


def test_original_preview_replay_ignores_expiry_but_rechecks_final_authority(b2case,monkeypatch):
    db, _, _, w, _, m, *_ = b2case
    pending,intent = stage(b2case,'preview')
    first = json.loads(complete(b2case,pending,intent).body)['data']
    set_clocks(monkeypatch,b2case,NOW+timedelta(hours=1),NOW+timedelta(hours=2))
    service = importlib.import_module('app.services.teaching.releases')
    _,operation = service.prepare_release_write(db,'owner','a','preview',dict(intent.canonical_payload),intent.idempotency_key)
    pending = w.execute_write(db,intent,intent.scope,operation)
    replay = json.loads(complete(b2case,pending,intent).body)['data']
    assert replay['receipt'] == first['receipt'] and replay['result'] == first['result'] and replay['replayed']
    assert count_effects(b2case) == (1,1)
    db.execute(update(m.TeachingRole).where(m.TeachingRole.subject_id=='owner').values(effective_until=NOW+timedelta(hours=3))); db.commit()
    set_clocks(monkeypatch,b2case,NOW+timedelta(hours=2),NOW+timedelta(hours=3))
    pending = w.execute_write(db,intent,intent.scope,operation)
    with pytest.raises(HTTPException): complete(b2case,pending,intent)
    assert count_effects(b2case) == (1,1)


def test_genuine_production_gate_stays_unconditionally_closed(b2case,monkeypatch):
    db, _, _, w, _, _, _, _, originals = b2case
    monkeypatch.setattr(w,'_require_write_safety',originals['hardgate'])
    intent,operation = intent_for(b2case)
    with pytest.raises(HTTPException) as denied: w.execute_write(db,intent,intent.scope,operation)
    assert (denied.value.status_code,denied.value.detail) == (503,'write_safety_unproven')
    assert count_effects(b2case) == (0,0)


@pytest.mark.parametrize('sql',['SELECT 1','SELECT UTC_TIMESTAMP(6); SELECT 1'])
def test_final_clock_permission_rejects_every_other_statement(b2case,monkeypatch,sql):
    db, _, _, w, *_ = b2case
    pending,intent = stage(b2case)
    def inadmissible_clock(session):
        session.execute(text(sql))
        return NOW
    monkeypatch.setattr(w,'_server_clock',inadmissible_clock)
    with pytest.raises(HTTPException) as denied: complete(b2case,pending,intent)
    assert denied.value.detail == 'post_clock_query_forbidden'
    assert count_effects(b2case) == (0,0)


def test_exact_final_clock_sql_is_one_shot_and_snapshots_stay_distinct(b2case,monkeypatch):
    db, _, _, w, *_ = b2case
    pending,intent = stage(b2case)
    candidate = pending._controller.context.authorization
    db.connection().connection.driver_connection.create_function('UTC_TIMESTAMP',1,lambda precision:'synthetic clock')
    def actual_clock_sql(session):
        assert session.execute(text('SELECT UTC_TIMESTAMP(6)')).scalar_one() == 'synthetic clock'
        with pytest.raises(HTTPException): session.execute(text('SELECT UTC_TIMESTAMP(6)'))
        return NOW+timedelta(seconds=1)
    monkeypatch.setattr(w,'_server_clock',actual_clock_sql)
    response = complete(b2case,pending,intent)
    final = pending._controller.finalized.authorization
    assert response.status_code == 200 and candidate.checked_at == NOW
    assert final.checked_at == NOW+timedelta(seconds=1) and final is not candidate
    assert pending._controller.context.authorization is candidate


@pytest.mark.parametrize('flush_number',[1,2,3])
def test_staging_flush_failures_roll_back_business_receipt_and_event(b2case,flush_number):
    db, _, _, w, _, _, b, *_ = b2case
    calls = []
    def failed_flush(session,context):
        calls.append(None)
        if len(calls)==flush_number: raise RuntimeError('synthetic stage flush failure')
    event.listen(db,'after_flush_postexec',failed_flush)
    try:
        intent,operation = intent_for(b2case)
        with pytest.raises(RuntimeError): w.execute_write(db,intent,intent.scope,operation)
    finally: event.remove(db,'after_flush_postexec',failed_flush)
    assert count_effects(b2case) == (0,0)
    assert len(calls) == flush_number
    assert db.get(b.Assignment,'a').draft_revision == 3


@pytest.mark.parametrize('boundary',['existing_session','new_session','new_connection'])
def test_b2_owner_refuses_nested_transaction_boundaries(b2case,boundary):
    db, _, _, w, *_ = b2case
    if boundary=='existing_session':
        db.begin_nested()
        intent,operation = intent_for(b2case)
        with pytest.raises(HTTPException): w.execute_write(db,intent,intent.scope,operation)
        db.rollback()
    else:
        pending,intent = stage(b2case)
        with pytest.raises(HTTPException):
            if boundary=='new_session': db.begin_nested()
            else: db.connection().begin_nested()
        abandon(b2case,pending)
    assert count_effects(b2case) == (0,0)


def test_finalizer_is_one_shot_and_bound_to_issued_transaction(b2case):
    from sqlalchemy.orm import Session
    db, _, _, w, *_ = b2case
    pending,intent = stage(b2case)
    other = Session(db.get_bind(),autoflush=False)
    try:
        with pytest.raises(HTTPException): w.finalize_pending_write(other,pending)
    finally: other.close()
    _,adapter = modules()
    prepared = adapter._response(200,'ok',adapter._write_data(pending))
    finalized = w.finalize_pending_write(db,pending)
    with pytest.raises(HTTPException): w.finalize_pending_write(db,pending)
    w.commit_finalized_write(db,finalized)
    assert prepared.status_code == 200 and count_effects(b2case) == (1,1)
    with pytest.raises(HTTPException): w.finalize_pending_write(db,pending)
    assert not event.contains(db,'before_flush',pending._controller._before_flush)


def test_cleanup_failure_retains_guards_and_original_unknown_outcome(b2case,monkeypatch):
    db, _, _, w, *_ = b2case
    pending,intent = stage(b2case)
    connection = db.connection()
    reached = []
    def failed_commit(connection):
        reached.append('commit')
        raise RuntimeError('synthetic uncertain COMMIT')
    def failed_rollback():
        reached.append('rollback')
        raise RuntimeError('synthetic failed rollback')
    def failed_invalidation():
        reached.append('invalidation')
        raise RuntimeError('synthetic failed invalidation')
    event.listen(connection,'commit',failed_commit)
    try:
        with monkeypatch.context() as fault:
            # Explicit parent-approved ORM-method cleanup fault simulation;
            # no additional application function or operation callback target.
            fault.setattr(db,'rollback',failed_rollback)
            fault.setattr(db,'invalidate',failed_invalidation)
            response = complete(b2case,pending,intent)
            body = json.loads(response.body)
            assert body['message'] == 'write_outcome_unknown'
            assert body['data']['recovery']['key'] == intent.idempotency_key
            assert reached == ['commit','rollback','invalidation']
            assert event.contains(db,'before_flush',pending._controller._before_flush)
            with pytest.raises(HTTPException) as refused: db.execute(text('SELECT 1'))
            assert refused.value.detail == 'post_clock_query_forbidden'
    finally:
        event.remove(connection,'commit',failed_commit)
        w.rollback_pending_write(db,pending)
    assert not event.contains(db,'before_flush',pending._controller._before_flush)
    assert count_effects(b2case) == (0,0)


def test_completed_handoff_seals_before_snapshot_serialization():
    import inspect
    w,_ = modules()
    source = inspect.getsource(w._B2WriteGuard.handoff)
    assert source.index("self.phase = 'pending'") < source.index('self.row_snapshots =')
    assert source.index("self.phase = 'pending'") < source.index('self.projection_snapshot =')


@pytest.mark.parametrize('fault_kind',['after_commit','guard_cleanup'])
def test_known_commit_owner_response_preserves_prepared_success(b2case,monkeypatch,fault_kind):
    """Owner-response proof only; no post-invalidation durability observation."""
    db, _, _, w, *_ = b2case
    pending,intent = stage(b2case)
    _,adapter = modules()
    expected = adapter._response(200,'ok',adapter._write_data(pending))
    reached = []
    def failed_after_commit(session):
        reached.append('after_commit')
        raise RuntimeError('synthetic post-confirmed-COMMIT listener failure')
    def failed_guard_cleanup():
        reached.append('guard_cleanup')
        raise RuntimeError('synthetic listener cleanup failure')
    if fault_kind=='after_commit': event.listen(db,'after_commit',failed_after_commit)
    try:
        with monkeypatch.context() as fault:
            if fault_kind=='guard_cleanup': fault.setattr(pending._controller,'close',failed_guard_cleanup)
            response = complete(b2case,pending,intent)
            assert response.status_code == expected.status_code and response.body == expected.body
            assert response.headers['cache-control'] == expected.headers['cache-control']
            assert pending._controller.commit_confirmed is True
            assert reached == (['after_commit'] if fault_kind=='after_commit' else ['guard_cleanup','guard_cleanup'])
            if fault_kind=='guard_cleanup':
                assert event.contains(db,'before_flush',pending._controller._before_flush)
                with pytest.raises(HTTPException) as refused: db.execute(text('SELECT 1'))
                assert refused.value.detail == 'post_clock_query_forbidden'
    finally:
        if fault_kind=='after_commit': event.remove(db,'after_commit',failed_after_commit)
        w.rollback_pending_write(db,pending)
    assert not event.contains(db,'before_flush',pending._controller._before_flush)
