"""Durable queue tests: isolated synthetic SQLite only; no provider/network."""
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import pytest


def setup_queue(tmp_path):
    from app.models.git_coach import CoachJob
    from app.models.domain_record import DomainRecord
    import json
    engine = create_engine('sqlite:///' + str(tmp_path / 'coach.sqlite'))
    CoachJob.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        db.add(DomainRecord(module='team_collaboration_git',record_type='project',record_key='p',payload=json.dumps({'repository':{'giteaOwner':'o','repoName':'r'}})))
        db.commit()
    return factory


def test_enqueue_is_durable_and_replay_idempotent(tmp_path):
    from app.services.git_coach_jobs import enqueue_coach_event, claim_job, register_commit
    factory = setup_queue(tmp_path)
    with factory() as db:
        first = enqueue_coach_event(db, 'p', {'ref':'refs/heads/main','commits':[{'id':'a'}]}, repository_key='campus/r', delivery_id='d1')
        second = enqueue_coach_event(db, 'p', {'ref':'refs/heads/main','commits':[{'id':'a'}]}, repository_key='campus/r', delivery_id='d2')
        assert second['duplicate'] and first['jobId'] == second['jobId']
        assert register_commit(db, 'campus/r', 'a')
        for i in range(30): assert register_commit(db, 'campus/r', str(i))
        assert not register_commit(db, 'campus/r', 'a')
        db.commit()
    claim = claim_job(factory)
    assert claim and claim['attempts'] == 1
    assert claim_job(factory) is None


def test_expired_lease_is_fenced_and_retry_is_bounded(tmp_path):
    from app.services.git_coach_jobs import enqueue_coach_event, claim_job, finish_job, fail_job
    from app.models.git_coach import CoachJob
    factory = setup_queue(tmp_path)
    with factory() as db:
        enqueue_coach_event(db,'p',{'commits':[{'id':'a'}]},repository_key='o/r')
    old = claim_job(factory)
    with factory() as db:
        db.query(CoachJob).update({'lease_until':datetime.utcnow()-timedelta(seconds=1)})
        db.commit()
    current = claim_job(factory)
    assert current['attempts'] == 2
    assert not finish_job(factory, old, [{'contextKey':'a','status':'ready'}])
    assert finish_job(factory, current, [{'contextKey':'a','status':'rules_only'}])
    with factory() as db:
        assert db.get(CoachJob,current['id']).status == 'rules_only'


def test_empty_computation_is_incomplete_not_ready(tmp_path):
    from app.services.git_coach_jobs import enqueue_coach_event, claim_job, finish_job
    from app.models.git_coach import CoachJob
    factory = setup_queue(tmp_path)
    with factory() as db: enqueue_coach_event(db,'p',{},repository_key='o/r')
    job=claim_job(factory)
    assert finish_job(factory,job,[])
    with factory() as db: assert db.get(CoachJob,job['id']).status == 'incomplete'


def test_enqueue_rollback_does_not_leave_acknowledged_job(tmp_path):
    from app.services.git_coach_jobs import enqueue_coach_event
    from app.models.git_coach import CoachJob
    factory = setup_queue(tmp_path)
    with factory() as db:
        enqueue_coach_event(db,'p',{'after':'x'},repository_key='o/r',commit=False)
        db.rollback()
    with factory() as db: assert db.query(CoachJob).count() == 0


def test_failed_feedback_save_never_reports_ready(tmp_path):
    from app.services.git_coach_jobs import enqueue_coach_event, claim_job, finish_job
    from app.models.git_coach import CoachJob, CoachFeedback
    factory = setup_queue(tmp_path)
    with factory() as db: enqueue_coach_event(db,'p',{},repository_key='o/r')
    job=claim_job(factory)
    with pytest.raises(TypeError):
        finish_job(factory,job,[{'contextKey':'a','status':'ready','invalid':object()}])
    with factory() as db:
        assert db.get(CoachJob,job['id']).status == 'running'
        assert db.query(CoachFeedback).count() == 0


def test_worker_runs_and_retries_without_provider_network(tmp_path):
    from app.services.git_coach_jobs import enqueue_coach_event, CoachWorkerLoop, retry_job
    from app.models.git_coach import CoachJob
    factory = setup_queue(tmp_path)
    with factory() as db: receipt=enqueue_coach_event(db,'p',{},repository_key='o/r')
    worker=CoachWorkerLoop(factory,compute=lambda *a,**k:[{'contextKey':'a','status':'fallback'}])
    assert worker.run_once()
    with factory() as db: retry_job(db,'p',receipt['jobId'])
    assert worker.run_once()
    with factory() as db: retry_job(db,'p',receipt['jobId'])
    assert worker.run_once()
    with factory() as db:
        assert db.get(CoachJob,receipt['jobId']).attempts == 3
        with pytest.raises(ValueError): retry_job(db,'p',receipt['jobId'])


def test_concurrent_enqueue_and_claim_one_logical_job(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from app.services.git_coach_jobs import enqueue_coach_event, claim_job
    from app.models.git_coach import CoachJob
    factory = setup_queue(tmp_path)
    def enqueue(_):
        with factory() as db: return enqueue_coach_event(db,'p',{'after':'a'},repository_key='o/r')
    with ThreadPoolExecutor(max_workers=4) as pool: receipts=list(pool.map(enqueue,range(4)))
    assert len({r['jobId'] for r in receipts}) == 1
    with ThreadPoolExecutor(max_workers=4) as pool: claims=list(pool.map(lambda _:claim_job(factory),range(4)))
    assert len([j for j in claims if j]) == 1


def test_concurrent_retry_has_one_winner(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from app.services.git_coach_jobs import enqueue_coach_event, claim_job, finish_job, retry_job
    factory = setup_queue(tmp_path)
    with factory() as db: receipt=enqueue_coach_event(db,'p',{},repository_key='o/r')
    job=claim_job(factory); finish_job(factory,job,[{'status':'fallback'}])
    def retry(_):
        with factory() as db:
            try: return retry_job(db,'p',receipt['jobId'])
            except ValueError: return None
    with ThreadPoolExecutor(max_workers=3) as pool: results=list(pool.map(retry,range(3)))
    assert len([r for r in results if r]) == 1


def test_delivery_reuse_with_different_payload_rejected(tmp_path):
    from app.services.git_coach_jobs import enqueue_coach_event
    factory=setup_queue(tmp_path)
    with factory() as db:
        enqueue_coach_event(db,'p',{'after':'a'},repository_key='o/r',delivery_id='delivery')
        with pytest.raises(ValueError,match='delivery_payload_conflict'):
            enqueue_coach_event(db,'p',{'after':'b'},repository_key='o/r',delivery_id='delivery')


def test_repository_rebind_prevents_inference_and_publication(tmp_path):
    from app.services.git_coach_jobs import enqueue_coach_event, claim_job, finish_job, CoachWorkerLoop
    from app.models.domain_record import DomainRecord
    from app.models.git_coach import CoachJob, CoachFeedback
    import json
    factory=setup_queue(tmp_path)
    with factory() as db:
        receipt=enqueue_coach_event(db,'p',{'after':'a'},repository_key='o/r')
    job=claim_job(factory)
    with factory() as db:
        row=db.query(DomainRecord).first();row.payload=json.dumps({'repository':{'giteaOwner':'o','repoName':'other'}});db.commit()
    assert not finish_job(factory,job,[{'status':'ready'}])
    with factory() as db:
        assert db.get(CoachJob,receipt['jobId']).error_code=='repository_binding_changed'
        assert db.query(CoachFeedback).count()==0
        receipt2=enqueue_coach_event(db,'p',{'after':'b'},repository_key='o/r')
    def forbidden(*args,**kwargs):
        pytest.fail('Inference must not run on rebound repository')
    CoachWorkerLoop(factory,compute=forbidden).run_once()
    with factory() as db: assert db.get(CoachJob,receipt2['jobId']).error_code=='repository_binding_changed'


def test_same_repository_path_new_id_rejects_old_feedback(tmp_path):
    import json
    from app.models.domain_record import DomainRecord
    from app.models.git_coach import CoachJob
    from app.services.git_coach_jobs import enqueue_coach_event, claim_job, finish_job
    factory=setup_queue(tmp_path)
    with factory() as db:
        row=db.query(DomainRecord).first();row.payload=json.dumps({'repository':{'giteaOwner':'o','repoName':'r','giteaRepositoryId':1}});db.commit()
        enqueue_coach_event(db,'p',{'repository':{'id':1}},repository_key='o/r')
    job=claim_job(factory)
    with factory() as db:
        row=db.query(DomainRecord).first();row.payload=json.dumps({'repository':{'giteaOwner':'o','repoName':'r','giteaRepositoryId':2}});db.commit()
    assert not finish_job(factory,job,[{'status':'ready'}])
    with factory() as db: assert db.get(CoachJob,job['id']).error_code=='repository_binding_changed'


def test_supervised_worker_start_stop_consumes_durable_job(tmp_path):
    import threading
    from app.services.git_coach_jobs import enqueue_coach_event, CoachWorkerLoop
    from app.models.git_coach import CoachJob, CoachWorker
    factory=setup_queue(tmp_path)
    with factory() as db: receipt=enqueue_coach_event(db,'p',{},repository_key='o/r')
    entered=threading.Event()
    def compute(*args,**kwargs):
        entered.set()
        return [{'status':'rules_only','contextKey':'a'}]
    worker=CoachWorkerLoop(factory,compute=compute)
    worker.start()
    assert entered.wait(5)
    worker.stop()
    assert not worker.thread.is_alive()
    with factory() as db:
        assert db.get(CoachJob,receipt['jobId']).status=='rules_only'
        assert db.query(CoachWorker).count()==0


def test_mysql_deadlock_claim_retry_rolls_back_and_returns_real_claim(tmp_path,monkeypatch):
    from sqlalchemy.exc import OperationalError
    from app.services import git_coach_jobs as jobs
    factory=setup_queue(tmp_path)
    with factory() as db: jobs.enqueue_coach_event(db,'p',{},repository_key='o/r')
    real=jobs._claim_job_once
    calls=[]
    def once(*args,**kwargs):
        calls.append(1)
        if len(calls)==1:
            raise OperationalError('UPDATE',{},Exception(1213,'Deadlock found'))
        return real(*args,**kwargs)
    monkeypatch.setattr(jobs,'_claim_job_once',once)
    result=jobs.claim_job(factory)
    assert result and result['attempts']==1
    assert jobs.claim_job(factory) is None


def test_claim_does_not_hide_unrelated_database_error(tmp_path,monkeypatch):
    from sqlalchemy.exc import OperationalError
    from app.services import git_coach_jobs as jobs
    factory=setup_queue(tmp_path)
    def forbidden(*args,**kwargs):
        raise OperationalError('SELECT',{},Exception(1146,'Table does not exist'))
    monkeypatch.setattr(jobs,'_claim_job_once',forbidden)
    with pytest.raises(OperationalError): jobs.claim_job(factory)


def test_mysql_claim_lock_retries_are_bounded(tmp_path,monkeypatch):
    from sqlalchemy.exc import OperationalError
    from app.services import git_coach_jobs as jobs
    factory=setup_queue(tmp_path)
    attempts=[]
    def locked(*args,**kwargs):
        attempts.append(1)
        raise OperationalError('SELECT',{},Exception(1213,'Deadlock found'))
    monkeypatch.setattr(jobs,'_claim_job_once',locked)
    with pytest.raises(OperationalError): jobs.claim_job(factory)
    assert len(attempts)==3
