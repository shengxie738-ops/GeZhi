# Teacher Work executor ownership unit regression

Date: 2026-10-05. Stage base: `03f680e68cbd3cde27ddbffe38caf23f1d249959` on `102V12`. Scope: detached first-call executor source candidate only.

## Corrections

- Only the exact scheduled supervisor can enter an admitted local run. A competing task is rejected before preparation, charging or dispatch.
- A supervisor ending before coroutine entry receives explicit terminal cleanup. The callback uses a fresh owner-finalized pending-failure operation, with at most one authorized observation if that operation fails or is uncertain.
- Local capacity is released only for matching terminal, uncharged facts with the old lease detached. Charged, denied and unresolved pending outcomes retain their blockers. A newer run's lease is untouched.

## Reproducible narrow test

Run from the checkout with the project's Python interpreter:

```sh
timeout --signal=KILL 30s python -B -I -S backend/tests/teacher_work_executor_ownership_unit.py
```

This standalone runner executes the actual selected executor/error/slot-check AST without importing application modules. It uses explicit fixed synthetic DTO/transaction facts, standard-library asyncio, four-second case timeouts and one-second task cleanup.

The six cases cover uncharged pre-entry cancellation, competing entry, charged state, denied cleanup/read, replacement lease and commit-unknown pending state. Before correction, the first two and replacement-local-release cases failed; the three blocker-preservation cases passed. The unchanged six cases passed after correction, with no application/SQLAlchemy/Pydantic modules or prompt/provider boundary calls.

The portable invocation reads current checkout nodes. Review-pinned runs can supply `--manifest` and `--manifest-sha256` together; their manifest also binds the runner, source bytes, extracted AST and interpreter.

## Broader recording-port verification

A separate, newly reviewed recording-port scope ran the four original execution selectors and two supervisor regressions unchanged. It used the actual pure repository, request-owner, schema, chat and executor modules over their original recording primitives. The actual SQL UoW/helper and transaction-origin enum AST were projected without importing SQLAlchemy; an explicitly unreachable `IntegrityError` sentinel means real SQL exception mapping remains unproved.

The accepted run passed all six selectors and exactly 18 setup/call/teardown phases, with native exit 0 under the 30-second wrapper; pytest reported 2.52 seconds. Its 24-record phase journal, empty denial/excluded-module lists, six closed stock asyncio loops, 12 local wakeup wrappers, zero pending tasks/timers and no installed profiler were checked. This overlaps the narrow six-case proof; the two sets are not twelve independent end-to-end checks. Historical freeze comments in the original test files do not qualify their old execution profile.

The first recording-port attempt passed its 18 phases but then failed pytest's restoration of an initial cwd outside the exact directory inventory, yielding exit 2. That attempt was not accepted. The new run began in its already-allowed owned work directory before installing the unchanged guard and explicitly required all 18 passing phases. No directory permissions were widened and the blocked attempt was not rerun.

Earlier heavily guarded executor processes terminated by SIGKILL. Their cause remains unexplained; those runs do not establish a product assertion failure, resource-limit enforcement or full-profile acceptance.

## Verification limits

Both accepted scopes are product unit evidence. The broader run exercises actual workflow and request-owner logic against recording ports; it does not prove real account/offering authorization, database lease/CAS constraints, SQL Session/transport behavior or provider execution. The original full-runtime profile, database/provider integration and live readiness remain unverified. The production `TEACHER_WORK_LIVE_GATES_UNVERIFIED` refusal is unchanged. No browser or Office acceptance was performed.
