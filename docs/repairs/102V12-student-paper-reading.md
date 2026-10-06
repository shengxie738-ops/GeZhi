# Student paper reading: bounded requests and truthful persistence

Base: `cb2bfbc9623f692d47dd8b73c87e7882ceb57c14`, branch `102V12`. This stage implements the parent-approved student paper contract following the teacher full-app and portable lesson-prep stages. It does not extend the plugin market or change the other chat modes' execution contract.

Ordinary paper previously used the shared agent graph, could save a truncated reply, and could trigger an automatic second desktop request after a stream failed. Paper now rebuilds only the verified owner's current SQL task context and calls one asynchronous model without tools, graph/RAG fallback or profile extraction. The selected Academic Reviewer retains its fixed server instructions. Nonempty retrieval/diagnosis options fail with 422 before a write or provider request; empty defaults remain accepted.

The server owns a 90-second deadline covering admission/queue, context preparation, inference and stream transmission. Neither HTTP timeout fields nor private-looking client fields extend it. The SDK has zero retries. The paper desktop never automatically resubmits a failed/empty/unterminated stream to `/chat`; a failed operation remains visibly unsaved or unconfirmed. Only nonempty explicit `stop`, without parsed, malformed or legacy tool/function calls, permits one assistant write. Other finish states remain incomplete or unknown failures.

Before inference and while queued, the real SQL read transaction is released. After inference, the existing origin/context locking reads still protect clear/delete/revision fences. A paper-only callback rechecks the budget after those reads and before starting the assistant write. Synchronous PyMySQL reads/commit/refresh cannot be forcibly interrupted. An already-started commit can finish after the budget expires: the response reports timeout with `history_confirmation_status: unknown`; the desktop asks the user to refresh history instead of asserting that nothing was saved. A blocked socket may prevent delivery of a terminal receipt altogether. Missing completion never triggers an automatic paper retry.

Paper generator cleanup runs in the Starlette streaming task where its deadline/ContextVar scopes began. Explicit nested `aclosing` releases the model stream, SQL generator and task lock after token-send timeout or disconnect. The nonstream operation consumes completed child exceptions even when its parent deadline cancels concurrently.

## Acceptance assembly

`backend/tests/run_student_paper_acceptance.py` accepts no service/credential arguments. It creates a blank working directory and fixed environment, disables plugin autoload and private `.env` loading, denies DNS/TCP access, records exact selectors/JUnit/commands/source/dependency hashes, and rejects errors, skipped or zero tests. Ordinary selectors explicitly cover student paper, source/context/history/auth/model behavior and existing teacher Work regressions. An old `test_user_models_api.py` imports `app.main` at collection against the default DB; its attempted DNS was blocked before socket access and it is not part of this ordinary selection. The native scenario instead exercises actual owner model configuration and authentication.

Native acceptance reuses the existing official, network-disabled MySQL controller and cleanup fixtures. Each scenario imports actual `app.main`, executes its startup and lifespan on a fresh owned schema, then logs in two students and a teacher using real password verification, JWT validation and canonical account lookup. No FastAPI dependency override, model object, permission guard or transaction/save replacement is used. Model and Crossref responses are synthetic only at the actual HTTP transports (including the SDK's supported `httpx`/`httpx2` boundary). Synthetic custom keys are inserted and encrypted in the owned fixture; inherited credentials and business databases are never selected. Startup keeps teacher production gates, Gitea and background workers closed.

Four scenarios cover:

- Authenticated source proxy → exact paper snapshot batch save/replay/conflict → stream/nonstream reading → fixed Reviewer prompt → real history read/delete; student/unassigned teacher cross-owner refusal and invalid/expired/nonexistent-account identities.
- Length/filter/tool-call/absent/unknown terminal states, empty output, provider 500, malformed and legacy unsolicited tool calls, contradictory retrieval/diagnosis options and broken encrypted model configuration. At most one provider attempt per request; no fallback/profile HTTP call.
- Actual clear/delete/revision invalidation during inference, queue budget and checkout observation, server timeout despite client timeout hints, actual ASGI disconnect, blocked headers and blocked token sends, expired context/save-fence reads, and an already-started slow commit with unknown confirmation. Immediate task lock release is observed.
- SQLAlchemy before/after-commit acknowledgement faults for user and assistant writes on both paths. These callbacks surround actual SQL commits; they are not a physical database wire cut. After a real assistant commit followed by an acknowledgement exception, SQL contains the full assistant but the API never claims confirmed saved success.

Final gate commands, exact counts, source pins, dependency observations, HTTP evidence and cleanup receipts are in `102V12-student-paper-reading-evidence.json` and `backend/tests/fixtures/student_paper_full_app_acceptance.synthetic.json`. The latter is parsed/reserialized evidence: `response_utf8` retains response text; login JSON omits token/password; raw ASGI observations normalize bytes and are explicitly separate from HTTP UTF-8 evidence. Tests/runs overlap: do not sum them or fold subtests into primary counts.

The final source canonical SHA-256 is `ee601b4ab568830c73f5a1e40fdf2d970035a958d8172381f6f81c3460c77102`. Backend: **608 primary + 201 subtests**, no failure/error/skip, exit 0. Native: **4 scenarios, 92 recorded HTTP exchanges, 44 synthetic SDK attempts, 5 separately recorded raw ASGI requests**, exit 0, all owned schema/container/volume cleanup confirmed and baseline services preserved. Related desktop: **252 tests in 24 files**, no failure/cancel/skip/todo, exit 0. Final provider waits and queued requests observed zero SQL checkouts. The native JSON archive SHA-256 is `c284190141ddeb4c144133ca0fb4f2a45bd1dc07414072a8f3c03f8592b9cff0`.

Reproduce the backend gate from the repository with the environment installed from its unchanged requirements files:

```sh
python -B backend/tests/run_student_paper_acceptance.py
```

Desktop verification uses the shipped Vue/Node synthetic-fetch suite. The exact 24-file command is archived in the evidence. The normal full desktop aggregate remains:

```sh
node frontend/scripts/desktopTestRunner.mjs
```

That aggregate was attempted here but could not start without locked `@babel/parser`. Official `npm ci --ignore-scripts --registry=https://registry.npmjs.org` installs failed with DNS `EAI_AGAIN`, including a bounded attempt with normal additional network permission. No alternative registry, lock change or approval bypass was used. The related desktop suite passes; the complete aggregate is **not** claimed green. No browser or mobile tests were run.

## RED/GREEN and review

The original HTTP-policy RED was 26 failures/2 passes (exit 1) and desktop RED was 4 failures (exit 1). A genuine queued-auth checkout RED and genuine post-commit acknowledgement RED led to the connection-release and safe session-discard fixes. Setup errors in the early HTTP transport fixture, obsolete graph-event test ports, a native test missing `session_id`, and an unsafe ordinary test import are recorded separately; they are not evidence of product-policy RED.

Independent review reproduced three material defects: malformed tool calls accepted under `stop`, cross-context cleanup after token backpressure, and a new assistant write begun after a locked read consumed the budget. The added regressions failed before their fixes (5 failures/57 passes, then 2 read-budget failures; exit 1) and passed afterwards. It also verified the unknown-confirmation UI correction and consumption of completed child exceptions. Legacy paper fallback tests were updated to the new contract while preserving chat fallback coverage; paper receipt/invalidation/deduplication tests now consume actual SSE terminal envelopes.

Review and final verification are source-pinned. No deployment, production-gate opening, main mutation, forced push or CI check endpoint was used. Live AI quality/provider behavior, real external academic services, full app/system-wide acceptance, and the blocked complete desktop aggregate remain unverified. The previous teacher proposal native JSON retains SHA-256 `4f70b0e0fc4e5294e935346c2f1738a03031cbc2e474f1ea5be8e440e70efb7b`.
