# Teacher Work full application ASGI acceptance plan

> Execution: delegated native implementation in this session; independent review after source freeze. User authorization covers implementation and ordinary commits. Push requires parent confirmation of current 102V12 head.

Goal: verify private teacher chat → lesson_outline@1 candidate → teacher edited save → approval → actual Office export/download through app.main and canonical authentication on disposable MySQL.

Base: 562049d5370d4784ccccb3095f015c79d6479cbf. AGENTS.md desktop scope applies. No browser, live AI, existing databases, real .env, Gitea/RAGFlow calls, deployment, production gates, CI endpoints, main edits or force pushes.

## Audit and assembly boundary

- app.main imports the complete api_router, executes init_db immediately, mounts static/CORS and owns the app lifespan. init_db performs startup core DDL, account/chat column maintenance and domain backfill. Explicit Teacher Work tables use a separate registry and formal migrations.
- Settings reads cwd/.env and requires OpenAI/RAGFlow fields. Default DB points at Software_Cup; default Git Coach worker is enabled. A fresh process with a blank cwd and an explicit synthetic environment is mandatory before any application import.
- Auth login uses real password hashing and get_db; current_identity resolves signed subjects against the present canonical account. Work also locks the current account in the dedicated READ COMMITTED root. Existing native tests mount selected routers and replace core database bindings, so they do not certify app.main/login/lifespan.
- Reuse native_teacher_work_mysql's exact pinned official image, network=none, skip-networking and disposable database identity checks. Use the existing DATABASE_URL query suffix for PyMySQL unix_socket and bounded driver timeouts, keeping production engine, SessionLocal and get_db unchanged.
- Child imports app.main and runs its real merged lifespan. No dependency overrides, account/authorization/repository/transaction replacement, startup DDL substitution, or exporter replacement. Only actual LessonPrepAIClient HTTP client transport returns explicitly synthetic responses. ACK-loss cases inject a fault at the actual PyMySQL commit boundary before/after real commit.
- Deny all TCP connections and .env opens with process audit guards; preserve guards for the application lifetime. Disable unrelated worker through configuration. Sources are synthetic fingerprint bytes, never claimed document text/evidence.

## Implementation

- [x] Add an explicit-only native controller that owns server/database lifetimes, launches a fresh isolated application process per scenario and checks nonempty scenario evidence.
- [x] Add a child scenario helper that imports the complete application, seeds minimum canonical accounts, applies formal migrations, uses actual login tokens, records HTTP/DB/Office evidence, and asserts lifecycle, duplicate/conflict, denied/invalid/current identities, disabled gates and unknown ACK behavior.
- [x] Add a credential-free safe runner that supplies a white-listed environment, runs the explicit controller, rejects skips/zero tests/count mismatch, and records source hashes, dependency versions, commands, exit codes and DB/container/volume cleanup receipts.
- [x] If production behavior fails, preserve RED evidence, diagnose the actual defect and implement only the minimum fix; verify GREEN and affected ordinary suites. Otherwise change tests/scripts/docs only.
- [x] Freeze source, obtain independent review, run native full-app acceptance and necessary ordinary backend suite, verify legacy fixture SHA256 unchanged and clean resource inventory.
- [ ] Record exact results and limits, commit only explicit files, report candidate commit/files/results to parent and await confirmed remote head before ordinary push.

Outcome: no production defect found; application/core auth/transaction/export code unchanged. Frozen full-app native 10 passed/exit0; required ordinary 319 passed/exit0 (30 subtests separately). Independent review final findings: no remaining Critical/Important/Minor; actual child timeout cleanup tested independently 2 passed. Expanded old lesson-prep run retains 9 named baseline/environment failures in the report. Evidence and cleanup are complete; local commit and parent CAS coordination are the remaining publication step.
