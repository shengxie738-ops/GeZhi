# Durable Git coach jobs implementation plan

Goal: acknowledge only durably recorded events and recoverable jobs; keep feedback outside project JSON.
Architecture: additive SQLAlchemy event, commit-ledger, job, feedback and worker-heartbeat tables; transaction-scoped enqueue, optimistic conditional claims with lease fencing, lifecycle-supervised database polling. Existing database infrastructure only.
Scope: approved audit repair; no real Gitea/provider calls, existing/restored database migrations, commits or pushes.

1. Write isolated SQLite regressions for idempotent enqueue, SHA replay beyond UI cache, competing claims, lease recovery, fenced persistence, bounded retries and failed-save atomicity; observe failures before implementation.
2. Add `app/models/git_coach.py` and `app/services/git_coach_jobs.py`. `enqueue_coach_event(db, project_id, payload, repository_key=..., delivery_id=None, commit=True)` returns eventId/jobId/duplicate/status. `register_commit(db, repository_key, sha)` participates in caller transaction. Worker consumes `compute_git_coach_feedback(db, project_id, payload=...) -> list[dict]`, without project writes or open write transactions across provider I/O.
3. Add independent authenticated read/retry router, reusing project authorization. Responses include jobs, feedback, cursor and worker availability. Retry requires project management permission and bounded total attempts.
4. Register models and lifecycle worker; disabled worker is explicit. No claim of hard cancellation of synchronous Python/provider code. SDK timeouts and job lease heartbeat bound ordinary operation; hung worker shutdown remains daemonized and expired leases recover after process exit.
5. Versioned additive migration script, explicit operator execution, preservation of legacy feedback and deterministic idempotent import guidance. Do not mutate existing database during development.
6. Run synthetic/offline tests and provide integration contracts, operational limits and outstanding MySQL verification.

Review focus: concurrent unique conflicts must not rollback ingestion; stale leases cannot publish; storage failures cannot mark ready; replay must survive latest-20 eviction; absent worker/provider must remain visible.

## Implemented contract and operator procedure

- Models: `git_coach_events` (unique SHA256 semantic event key); `git_coach_deliveries` (unique repository/project/delivery key); `git_coach_commits` (persistent repository/SHA ledger); `git_coach_jobs` (one job/event); `git_coach_feedback` (unique job/context); `git_coach_workers` heartbeat; `team_git_project_identities` permanent project ID reservations
- Repository identity includes canonical owner/name and accepted numeric ID. Worker preflight and stateless computation validate binding. Publication locks the raw project row briefly, compares accepted identity again, then fences the job completion in the same transaction. Rebinding cannot attach old feedback to a new repository
- Enqueue and ingestion must share caller transaction (`commit=False`). Savepoint uniqueness conflicts do not rollback the caller's accepted event. Reused delivery with conflicting semantic identity rejects and rolls back. SQLite legacy mode explicitly begins a write transaction before savepoints, so outer rollback is real; MySQL uses its native transaction
- Event history is independent of the latest-20 UI cache. Stored SHA ledger survives cache eviction. Replayed delivery IDs and semantically identical events reuse the durable job without repeat inference
- Claim uses conditional UPDATE with attempt counter and random lease token; worker recovery reclaims expired leases. Stale tokens cannot save feedback. Feedback and terminal status commit atomically; serialization/database errors propagate and are retried, never reported ready
- Three total attempts per job (manual retry cannot reset the limit). Automatic error retry backoff is 10/20 seconds, capped at 300; failed last attempts are terminal. Manual retry is only failed/incomplete/fallback, with project management authorization. Concurrent retries have one winner
- FastAPI lifespan supervises one serial worker plus heartbeat thread per application process. Poll interval two seconds; heartbeat fifteen seconds; lease ninety seconds. `GIT_COACH_WORKER_ENABLED=false` disables worker explicitly. Independent workers use database claims safely; no Redis/new infrastructure
- Nine-hundred-second soft job budget: after budget, heartbeat stops extending the job lease and removes worker availability; a late result cannot publish. SDK calls have bounded network timeouts owned by the computation/adapter modules. Python synchronous provider threads cannot be forcibly cancelled. A hung daemon computation may remain until process exit; a healthy separate worker can recover the lease. Process supervision and alerts remain necessary. Crash after paid inference before durable publication may repeat inference; this is at-least-once execution, not exactly-once external billing
- Feedback states: queued/running live in jobs; ready/rules_only/fallback/incomplete/failed explicit. Empty computation is incomplete, never ready. Worker absence is exposed independently of job state
- GET `/api/team-git/projects/{project_id}/coach?limit=20&before=123`: authenticated visible project members/scoped teacher only; raw persisted authorization read, no Gitea, normalization or provider call. Returns `{projectId,feedback,jobs,nextCursor,worker:{enabled,available}}`; jobs expose attempts/maxAttempts/errorCode/timestamps. Feedback id is decimal string, pagination cursor integer
- POST `/api/team-git/projects/{project_id}/coach/jobs/{job_id}/retry`: leader/scoped teacher only, checks both project and job; 404 unknown scoped job, 409 busy/exhausted; receipt `{projectId,jobId,status,attempts}`
- GET `/api/team-git/coach-health`: authenticated actor; `{schemaReady,workerEnabled}`. Missing schema yields coach read/retry HTTP503 `coach_schema_unavailable`; lifespan does not start a worker, and the rest of the app stays available

### Additive migration and preservation

Do not use application `init_db` as this feature's schema migration. It deliberately excludes all new coach/identity tables. No migration was run against a restored or business database during development.

Before deploying: back up the intended database; stop application writers; explicitly verify the database target and credentials using the deployment's existing secure process; run from `backend`:

```
python -m migrations.v20261002_git_coach --apply --backfill
```

The script creates only the seven new tables plus `gezhi_schema_versions`, stamps revision `20261002_git_coach`, and never drops/changes existing tables. It always reserves existing project IDs from `domain_records`; `--backfill` additionally copies legacy feedback into new feedback rows without changing the original project JSON. Legacy provenance is unknown, so imported rows retain `legacyStatus` but expose `status=incomplete` and `source=legacy_import`. No fake AI-ready inference is manufactured. The deterministic import key makes a repeated import of unchanged legacy content idempotent. MySQL DDL may autocommit: after a partial DDL failure rerun the migration, which uses `checkfirst`. Run a single migration process with writers stopped. Table existence is not a general schema drift repair system; verify schema/unique constraints before rollout. Rollback means disable the feature/worker and retain these additive tables/data, not destructive automatic downgrades.

Legacy feedback imports are not retryable jobs because no trustworthy original event exists. New event feedback retains history across events; a retry updates that job's current feedback, not a permanent history of every failed attempt. No automatic event/ledger pruning is enabled; operators must size/monitor storage and define an explicit retention policy without destroying replay protection.

### Verification status

Seventeen isolated SQLite tests cover concurrency, rollback (without a test-only explicit BEGIN), lease reclaim/fencing, serialized worker lifecycle, terminal atomicity, attempts, delivery conflict, repository rebinding including same path/new numeric ID, pagination API permissions/missing schema/local-only read and migration preservation/idempotence. No real Gitea or model calls. MySQL validation is assigned separately to the isolated runtime QA harness; full deployment/process-supervisor recovery and live external integrations remain acceptance work.

### MySQL concurrency follow-up (09:04 UTC)

Actual isolated MySQL QA reproduced InnoDB deadlocks that SQLite did not expose. Claims now use `SELECT ... FOR UPDATE SKIP LOCKED` on MySQL 8+/PostgreSQL, rather than broad expired-row UPDATE followed by a read-to-write upgrade. CAS/lease fencing remain. Only MySQL deadlock (1213) and lock-wait timeout (1205) are retried, at most three fresh transactions with bounded short backoff; unrelated SQL errors propagate. SQLite retains its CAS path.

Duplicate INSERT in InnoDB retains shared locks. Duplicate-event/delivery/job lookup therefore uses a current shared locking read (`LOCK IN SHARE MODE`), not an exclusive-lock upgrade that can deadlock multiple redeliveries. Enqueue does not restart the caller's transaction internally; `commit=False` cannot silently discard project ingestion. Independent-session MySQL recheck is owned by the runtime QA worker.

MySQL recheck: runtime QA reported 45/45 probes passing, including ten rounds of four independent enqueue/claim sessions, killed-process/fresh-process lease recovery, rollback and failed-save atomicity. Local coach jobs/migration/API tests now total twenty passing. This establishes the isolated database/runtime contract, not live Gitea/provider/deployment acceptance.
