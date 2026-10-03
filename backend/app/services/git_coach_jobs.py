"""Database-backed coach queue; write transactions never contain provider I/O.

Claims and completion are fenced by a random lease token. Delivery is at least
once across process death: an inference can be repeated after a crash, but stale
workers cannot publish, and a durable event has only one logical job.
"""
from __future__ import annotations
import hashlib
import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy import and_, or_, inspect
from sqlalchemy.exc import IntegrityError, OperationalError
from app.models.git_coach import CoachDelivery, CoachCommit, CoachEvent, CoachFeedback, CoachJob, CoachWorker

log = logging.getLogger(__name__)
LEASE_SECONDS = 90
JOB_BUDGET_SECONDS = 900

def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)

TERMINAL = {'ready', 'rules_only', 'fallback', 'failed', 'incomplete'}


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def event_identity(project_id, repository_key, payload):
    """Semantic identity survives new delivery IDs and irrelevant sender metadata."""
    event = str(payload.get('hook_name') or payload.get('type') or ('pull_request' if 'pull_request' in payload else 'push'))
    if event.startswith('pull_request'):
        pr = payload.get('pull_request') or {}
        context = [event, payload.get('action'), pr.get('number') or payload.get('number'),
                   pr.get('head'), pr.get('base'), pr.get('updated_at'), pr.get('state'), pr.get('merged')]
    else:
        context = [event, payload.get('ref'), payload.get('before'), payload.get('after'),
                   sorted(str(c.get('id') or c.get('sha') or '') for c in payload.get('commits', []) if isinstance(c, dict)),
                   payload.get('deleted'), payload.get('created')]
    return _hash([project_id, repository_key.lower(), (payload.get("repository") or {}).get("id"), context])


def ensure_write_transaction(db):
    # sqlite3 legacy transaction mode otherwise RELEASE of a first SAVEPOINT
    # commits it outside Session.rollback(). IMMEDIATE also serializes writers.
    connection = db.connection()
    if connection.dialect.name == 'sqlite' and not connection.connection.driver_connection.in_transaction:
        connection.exec_driver_sql('BEGIN IMMEDIATE')


def enqueue_coach_event(db, project_id, payload, *, repository_key, delivery_id=None, commit=True):
    ensure_write_transaction(db)
    key = event_identity(project_id, repository_key, payload)
    existing = db.query(CoachEvent).filter_by(event_key=key).first()
    duplicate = existing is not None
    if existing is None:
        try:
            with db.begin_nested():
                existing = CoachEvent(id=uuid.uuid4().hex, event_key=key, project_id=project_id,
                                      repository_key=repository_key, delivery_id=str(delivery_id or '')[:255],
                                      payload=json.dumps(payload, ensure_ascii=False))
                db.add(existing)
                db.flush()
                db.add(CoachJob(id=uuid.uuid4().hex, event_id=existing.id, project_id=project_id))
                db.flush()
        except IntegrityError:
            duplicate = True
            existing = db.query(CoachEvent).filter_by(event_key=key).with_for_update(read=True).one()
    if delivery_id:
        delivery_key = _hash([project_id, repository_key.lower(), str(delivery_id)])
        try:
            with db.begin_nested():
                db.add(CoachDelivery(key=delivery_key, event_id=existing.id, event_key=key))
                db.flush()
        except IntegrityError:
            delivery = db.query(CoachDelivery).filter_by(key=delivery_key).with_for_update(read=True).one()
            if delivery.event_key != key:
                db.rollback()
                raise ValueError('delivery_payload_conflict')
    job = db.query(CoachJob).filter_by(event_id=existing.id).with_for_update(read=True).one()
    receipt = {'eventId': existing.id, 'jobId': job.id, 'duplicate': duplicate, 'status': job.status}
    if commit:
        db.commit()
    return receipt


def register_commit(db, repository_key, sha):
    ensure_write_transaction(db)
    if not sha:
        return False
    try:
        with db.begin_nested():
            db.add(CoachCommit(key=_hash([repository_key.lower(), sha]), repository_key=repository_key, sha=sha))
            db.flush()
        return True
    except IntegrityError:
        return False


def claim_job(factory, *, now=None):
    # InnoDB can abort a transaction despite correct locking (e.g. other writers).
    # Retry only its documented deadlock/lock-wait codes with fresh sessions.
    for attempt in range(3):
        try:
            return _claim_job_once(factory, now=now)
        except OperationalError as exc:
            code = exc.orig.args[0] if getattr(exc.orig, 'args', ()) else None
            if code not in (1205, 1213) or attempt == 2:
                raise
            time.sleep(0.01 * (2 ** attempt))


def _claim_job_once(factory, *, now=None):
    now = now or utcnow()
    with factory() as db:
        eligible = or_(and_(CoachJob.status == 'queued', CoachJob.next_attempt_at <= now),
                       and_(CoachJob.status == 'running', CoachJob.lease_until < now))
        query = db.query(CoachJob).filter(eligible).order_by(CoachJob.created_at, CoachJob.id)
        if db.get_bind().dialect.name in ('mysql', 'postgresql'):
            # Claim a row with a current locking read. Never bulk-update expired
            # rows before selection: competing RR transactions can gap-deadlock.
            query = query.with_for_update(skip_locked=True)
        candidate = query.first()
        if candidate is None:
            db.commit()
            return None
        if candidate.attempts >= candidate.max_attempts:
            db.query(CoachJob).filter(CoachJob.id == candidate.id, eligible,
                CoachJob.attempts == candidate.attempts).update(
                {'status': 'failed', 'error_code': 'lease_exhausted', 'lease_token': None,
                 'lease_until': None, 'updated_at': now}, synchronize_session=False)
            db.commit()
            return None
        token = uuid.uuid4().hex
        changed = db.query(CoachJob).filter(CoachJob.id == candidate.id, eligible,
                    CoachJob.attempts == candidate.attempts).update(
            {'status': 'running', 'attempts': CoachJob.attempts + 1, 'lease_token': token,
             'lease_until': now + timedelta(seconds=LEASE_SECONDS), 'updated_at': now}, synchronize_session=False)
        job_id = candidate.id
        db.commit()
        if not changed:
            return None
        db.expire_all()
        row = db.get(CoachJob, job_id)
        event = db.get(CoachEvent, row.event_id)
        return {'id': row.id, 'projectId': row.project_id, 'token': token, 'attempts': row.attempts,
                'maxAttempts': row.max_attempts, 'repositoryKey': event.repository_key, 'payload': json.loads(event.payload)}


def _owned(db, job):
    return db.query(CoachJob).filter_by(id=job['id'], status='running', lease_token=job['token'])


def repository_matches(db, job, *, lock=False):
    from app.models.domain_record import DomainRecord
    query = db.query(DomainRecord).filter_by(module='team_collaboration_git', record_type='project', record_key=job['projectId'])
    row = (query.with_for_update() if lock else query).first()
    if row is None:
        return False
    repo = (json.loads(row.payload).get('repository') or {})
    owner = str(repo.get('giteaOwner') or '').strip()
    name = str(repo.get('repoName') or repo.get('giteaRepo') or '').strip()
    key = name if '/' in name else owner + '/' + name
    event_repo_id = (job['payload'].get('repository') or {}).get('id')
    bound_repo_id = repo.get('giteaRepositoryId', repo.get('giteaRepoId'))
    if event_repo_id is not None and str(event_repo_id) != str(bound_repo_id):
        return False
    return key.lower() == job['repositoryKey'].lower()


def finish_job(factory, job, feedback):
    statuses = [f.get('status', 'incomplete') for f in feedback]
    status = next((s for s in ('failed', 'incomplete', 'fallback', 'rules_only') if s in statuses), 'ready') if statuses else 'incomplete'
    if any(s not in TERMINAL for s in statuses):
        status = 'incomplete'
    with factory() as db:
        if not repository_matches(db, job, lock=True):
            _owned(db, job).update({'status': 'failed', 'error_code': 'repository_binding_changed',
                                  'lease_token': None, 'lease_until': None, 'updated_at': utcnow()}, synchronize_session=False)
            db.commit()
            return False
        changed = _owned(db, job).update({'status': status, 'lease_token': None, 'lease_until': None,
                         'error_code': '', 'updated_at': utcnow()}, synchronize_session=False)
        if not changed:
            db.rollback()
            return False
        db.query(CoachFeedback).filter_by(job_id=job['id']).delete()
        for index, item in enumerate(feedback):
            payload = dict(item)
            if payload.get('status') not in TERMINAL:
                payload['status'] = 'incomplete'
            db.add(CoachFeedback(project_id=job['projectId'], job_id=job['id'],
                context_key=_hash(item.get('contextKey') or [item.get('sha'), item.get('branch'), item.get('id'), index]),
                payload=json.dumps(payload, ensure_ascii=False)))
        db.commit()  # Exceptions propagate. Atomic rollback prevents apparent ready.
        return True


def fail_job(factory, job, code='computation_failed'):
    now = utcnow()
    with factory() as db:
        changed = _owned(db, job).update({'status': 'failed' if job['attempts'] >= job['maxAttempts'] else 'queued',
            'next_attempt_at': now + timedelta(seconds=min(300, 5 * 2 ** job['attempts'])),
            'error_code': code, 'lease_token': None, 'lease_until': None, 'updated_at': now}, synchronize_session=False)
        db.commit()
        return bool(changed)


def retry_job(db, project_id, job_id):
    row = db.query(CoachJob).filter_by(id=job_id, project_id=project_id).first()
    if row is None:
        raise LookupError('job_not_found')
    changed = db.query(CoachJob).filter(CoachJob.id == job_id, CoachJob.project_id == project_id,
        CoachJob.status.in_(['failed', 'incomplete', 'fallback']), CoachJob.attempts < CoachJob.max_attempts).update(
        {'status': 'queued', 'next_attempt_at': utcnow(), 'error_code': '', 'updated_at': utcnow()}, synchronize_session=False)
    if not changed:
        db.rollback()
        raise ValueError('job_busy_or_retry_exhausted')
    receipt = {'projectId': project_id, 'jobId': job_id, 'status': 'queued', 'attempts': row.attempts}
    db.commit()
    return receipt


def schema_ready(bind):
    try:
        tables = set(inspect(bind).get_table_names())
        return all(name in tables for name in ('git_coach_events', 'git_coach_deliveries', 'git_coach_jobs',
                   'git_coach_commits', 'git_coach_feedback', 'git_coach_workers', 'team_git_project_identities'))
    except Exception:
        return False


def worker_enabled():
    return os.getenv('GIT_COACH_WORKER_ENABLED', 'true').lower() in {'1', 'true', 'yes'}


def list_coach(db, project_id, *, limit=20, before=None):
    query = db.query(CoachFeedback).filter_by(project_id=project_id)
    if before is not None:
        query = query.filter(CoachFeedback.id < before)
    rows = query.order_by(CoachFeedback.id.desc()).limit(limit + 1).all()
    feedback = [{**json.loads(row.payload), 'id': str(row.id), 'jobId': row.job_id} for row in rows[:limit]]
    jobs = db.query(CoachJob).filter_by(project_id=project_id).order_by(CoachJob.created_at.desc()).limit(50).all()
    active = db.query(CoachWorker).filter(CoachWorker.heartbeat_at > utcnow() - timedelta(seconds=45)).first()
    return {'projectId': project_id, 'feedback': feedback,
            'jobs': [{'id': j.id, 'status': j.status, 'attempts': j.attempts, 'maxAttempts': j.max_attempts,
                      'errorCode': j.error_code, 'createdAt': j.created_at.isoformat()+'Z', 'updatedAt': j.updated_at.isoformat()+'Z'} for j in jobs],
            'nextCursor': rows[limit-1].id if len(rows) > limit else None,
            'worker': {'enabled': worker_enabled(), 'available': bool(active)}}


class CoachWorkerLoop:
    """Single serial computation thread plus independent lease-heartbeat thread.

    SDK timeout is the cancellation boundary; Python threads cannot be forcibly
    stopped. Stop removes heartbeat and releases no live lease early. A stuck
    daemon computation cannot prevent process exit; recovery waits lease expiry.
    """
    def __init__(self, factory, compute=None):
        self.factory, self.compute = factory, compute
        self.stop_event = threading.Event()
        self.worker_id = uuid.uuid4().hex
        self.current = None
        self.started_at = None
        self.thread = None
        self.heartbeat_thread = None

    def _heartbeat(self):
        while not self.stop_event.is_set():
            try:
                with self.factory() as db:
                    now = utcnow()
                    current = self.current
                    if current and self.started_at and time.monotonic() - self.started_at > JOB_BUDGET_SECONDS:
                        db.query(CoachWorker).filter_by(id=self.worker_id).delete()
                        db.commit()
                        self.stop_event.wait(15)
                        continue
                    db.merge(CoachWorker(id=self.worker_id, heartbeat_at=now))
                    if current:
                        _owned(db, current).update({'lease_until': now + timedelta(seconds=LEASE_SECONDS)}, synchronize_session=False)
                    db.commit()
            except Exception:
                log.exception('Coach worker heartbeat failed')
            self.stop_event.wait(15)

    def run_once(self):
        job = claim_job(self.factory)
        if not job:
            return False
        self.current = job
        self.started_at = time.monotonic()
        try:
            if self.compute is None:
                from app.services.git_coach_service import compute_git_coach_feedback
                compute = compute_git_coach_feedback
            else:
                compute = self.compute
            with self.factory() as db:
                if not repository_matches(db, job):
                    db.rollback()
                    with self.factory() as write_db:
                        _owned(write_db, job).update({'status': 'failed', 'error_code': 'repository_binding_changed',
                            'lease_token': None, 'lease_until': None, 'updated_at': utcnow()}, synchronize_session=False)
                        write_db.commit()
                    return True
                feedback = compute(db, job['projectId'], payload=job['payload'], expected_repository_key=job['repositoryKey'])
                db.rollback()  # computation session is read-only by contract
            if time.monotonic() - self.started_at > JOB_BUDGET_SECONDS:
                fail_job(self.factory, job, 'job_budget_exceeded')
            else:
                finish_job(self.factory, job, feedback)
        except Exception:
            log.exception('Coach job failed id=%s', job['id'])
            fail_job(self.factory, job)
        finally:
            self.current = None
            self.started_at = None
        return True

    def _run(self):
        while not self.stop_event.is_set():
            try:
                worked = self.run_once()
            except Exception:
                log.exception('Coach queue unavailable')
                worked = False
            if not worked:
                self.stop_event.wait(2)

    def start(self):
        self.thread = threading.Thread(target=self._run, name='git-coach-worker', daemon=True)
        self.heartbeat_thread = threading.Thread(target=self._heartbeat, name='git-coach-heartbeat', daemon=True)
        self.heartbeat_thread.start()
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        for thread in (self.thread, self.heartbeat_thread):
            if thread:
                thread.join(timeout=3)
        try:
            with self.factory() as db:
                db.query(CoachWorker).filter_by(id=self.worker_id).delete()
                db.commit()
        except Exception:
            log.exception('Coach worker shutdown heartbeat removal failed')
