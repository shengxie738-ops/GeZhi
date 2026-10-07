# Paper save uncertainty: truthful local-copy status

Baseline: `c91c17584de840a774ffed0bb305cd1dcc219e17` on `102V12`.

## Repair

A failed batch request does not establish that nothing reached the database. In particular, `CHAT_BATCH_COMMIT_UNKNOWN` and `CHAT_BATCH_OUTCOME_UNKNOWN`, a lost response, or an unsuccessful reconciliation can leave the save outcome uncertain.

The paper-save error banner and installed failed-status label now say “当前显示本地副本，云端保存结果尚未确认” and offer deliberate sync retry or history refresh. The actual error remains visible. Neutral wording is used for every failed save, including known prewrite errors: a later prewrite failure cannot disprove an earlier unknown commit.

This is a two-line production-copy change. The `pending` / `saved` / `failed` states, cached message fields, stable `client_request_id`, exact retained serialized retry body, owner/navigation fences, in-flight retry coalescing, and positive two-row receipt requirement are unchanged. Legacy cached failures use the same neutral installed status label without a cache migration or a new state value. Explicit history reads can confirm existing saved rows without another POST.

## Offline verification

The new `frontend/tests/paperSyncUncertainty.test.mjs` runs the production request wrapper, `useChat`, cache parsing, and installed status markup under shipped Vue 3.3.4. Only fetch, Web Storage, and the renderer host are synthetic; unregistered I/O fails closed.

- Test-first run: 22 tests, 3 existing behavioral controls passed, 19 wording assertions failed
- Final focused run: 22/22 passed
- Existing guards plus new tests: 101/101 passed across nine selected files
- Preserved original paper503 probe replay: 1/2 before the repair, 2/2 after it

Coverage includes six503 detail codes (`CHAT_BATCH_SCHEMA_UNAVAILABLE`, `CHAT_BATCH_UNAVAILABLE`, `CHAT_BATCH_SESSION_NOT_CLEAN`, `CHAT_BATCH_RECEIPT_INVALID`, `CHAT_BATCH_COMMIT_UNKNOWN`, `CHAT_BATCH_OUTCOME_UNKNOWN`), four409 conflict/deletion/missing-pair details, generic500 and lost responses, incomplete/nonpositive receipts, cached reload and byte-identical explicit retry, unknown followed by a schema failure, explicit history confirmation without a POST, account switch, repeated retry clicks, and newer navigation while a receipt is pending.

From repository root, run the focused tests without installing dependencies:

```sh
node --import ./frontend/tests/fixtures/desktopShippedNodePreload.mjs --test --test-concurrency=1 --test-reporter=tap ./frontend/tests/paperSyncUncertainty.test.mjs
```

The selected regression files are `paperSyncUncertainty`, `workSessionLifecycle`, `workMutationRaces`, `workAuthTransition`, `workRefreshLayout`, `chatModes`, `conversations`, `paperSearchOutcome`, and `paperWorkflow` (`frontend/tests/*.test.mjs`).

## Limits

This evidence does not establish a real database commit outcome. No actual HTTP service, MySQL/DB, migration, provider, browser, dependency install, or full test suite was run. Existing Vue development-build/module-type diagnostics and expected negative-path request logs are recorded in the regression output; compiled status mounts report no warnings or errors. Backend receipt/schema changes require separate verification. This document does not claim deployment or remote publication.
