# B1 Task6A HTTP contract and outstanding runtime validation

## Release boundary

Task6A adds own-scope GET adapters, the structural teaching-router include,
strict public readiness projections and one immutable deployment-policy capture.
It is an offline source/synthetic HTTP candidate. B1 is **not production ready**.
The unchanged write engine unconditionally returns `503 write_safety_unproven`;
there is no deployment setting, session marker or client flag that enables it.

Tests mount only the teaching router under `/api` in a tiny ASGI application.
They use actual signed bearer tokens and the current canonical-account resolver
against synthetic persisted accounts, overriding only the dedicated DB dependency.
Hypothetical write journeys additionally use the previously reviewed fixture-local
schema, transaction, safety and clock substitutions. Those substitutions are test
evidence boundaries, never production activation. Separate tests retain genuine
default-off, SQLite vendor/schema, dedicated-transaction and hard-write refusals.

No aggregate application, `main`, startup or `init_db` is imported/executed for
these tests. The aggregate include is verified by exact-file structural AST only.
No server, socket, actual MySQL connection, browser or external provider is used.

## Deployment policy and identity

The dedicated-session module captures the seven existing deployment values once
at process initialization: institution identity; teaching, assignments, feedback
and revisions flags; trusted teacher/student roster JSON; trusted delegation JSON.
Missing values produce disabled/empty defaults. Every dedicated session receives
a provider returning the same frozen `TeachingPolicyInputs` object. Later Settings
mutation does not change it. Changing deployed policy requires a process restart;
no HTTP/client policy-replacement mechanism exists.

Its private content-derived generation records provenance. Authorization still
hashes relevant source/actor/target policy values, not unrelated configuration or
the generation alone. No raw policy or full-roster hash is a public identity.
Settings are process-local: this does not prove synchronized cross-worker
revocation. Operator-controlled multi-worker policy rollout remains a gate.

Tokens identify a subject; their role claim is not current authority. The actual
resolver re-reads canonical `UserAccount`. Valid teacher-to-student demotion stays
authenticated, while current teaching rights are evaluated independently. Deleted
or invalid accounts are refused. Stable account incarnation/username-reuse safety
is unresolved and must be designed before real rollout.

The exported synchronous account helper retains direct-call compatibility. Actual
teaching routes use an async request dependency calling the same helper with the
same explicit Session. SQL remains synchronous; event-loop responsiveness,
threading/pool behavior and production latency have not been established here.

## Protected read API

All protected responses use `{code, message, data}` and `Cache-Control: no-store`.
Successful reads return 200 and `message: "ok"`. Reader DTOs are strict and frozen;
they never serialize ORM accounts, credentials, editable profiles or raw policy.

- `GET /api/teaching/capabilities`: current account role, B1 read readiness,
  separately configured/uninstalled stage state, and explicit closed-write state
- `GET /api/teaching/courses?membership=all&cursor=...&limit=50`: real own visible
  course definitions, membership modes and permitted visible offering counts
- `GET /api/teaching/offerings?membership=learning&course_id=...&limit=50`: own
  current scoped offerings; a course filter narrows access
- `GET /api/teaching/courses/{course_id}` and
  `GET /api/teaching/offerings/{offering_id}`: scoped details
- `GET /api/teaching/offerings/{offering_id}/enrollment`: current actor's own
  effective enrollment only; no arbitrary student selector
- `GET /api/teaching/offerings/{offering_id}/roster`: independently requires
  current offering-wide `ROSTER_MANAGE`; exposes scoped membership metadata
- `GET /api/teaching/offerings/{offering_id}/roles`: independently requires
  `ROLES_MANAGE`; exposes local configured/effective grants and account-role binding
- Existing preview detail/change pages and receipt recovery remain actor/scope
  filtered and require current authority

List limits default to 50, range 1–100. Limits are canonical ASCII decimal strings,
not booleans, signs, leading-zero forms or repeated parameters. Queries forbid
unknown keys, duplicated keys and control-bearing/overlong cursors. Detail,
enrollment, roles and capabilities routes accept no query parameters. Membership
is `teaching`, `learning` or `all`. Client actor/institution/scope/permission claims
cannot broaden authority. General query-cost/keyset optimization remains deferred;
current reader work may precede final in-memory paging. No performance claim is made.

### Sanitized capability example

This is an illustrative schema-ready synthetic read projection, not live readiness:

```json
{
  "code": 200,
  "message": "ok",
  "data": {
    "account_role": "teacher",
    "configured": true,
    "available": true,
    "can_create_course": false,
    "reason": "available",
    "assignments": {"configured": false, "installed": false, "available": false, "reason": "feature_disabled"},
    "feedback": {"configured": false, "installed": false, "available": false, "reason": "feature_disabled"},
    "revisions": {"configured": false, "installed": false, "available": false, "reason": "feature_disabled"},
    "writes_available": false,
    "write_reason": "write_safety_unproven"
  }
}
```

`available` means B1 **read** readiness only. Feature-off capability introspection
returns 200 with `available: false`, `reason: "feature_disabled"`, and no teaching
table query; an ordinary course GET is 503, never an invented empty success.
Configured later stages report `stage_unavailable`; bad dependency chains retain
stage-specific `dependency_disabled` while B1 read semantics are unchanged.

Offering access retains `configured_permissions` and `role_scope` for honest
authority inspection, but public `available_actions` is always empty while the
hard write gate is closed. It also returns `writes_available: false` and
`write_reason: "write_safety_unproven"`. Reserved assessment permissions do not
represent installed assessment endpoints.

## Roster counts and original receipts

Preview counts describe complete saved canonical sets, separately from bounded
display samples. `keep_count` includes the `update_count` subset:

```text
preview: target_count = add_count + keep_count
example: target=5, add=1, keep=4, update=4
```

Application counts describe actual disjoint persisted effects. `kept_count`
excludes changed retained rows:

```text
application: target_count = added_count + kept_count + updated_count
same example: target=5, added=1, kept=0, updated=4
```

An explicit period applies to supplied desired IDs; retained unrequested merge
members preserve their existing periods. The example explicitly supplies all four
retained IDs plus the new learner. Count fields and saved records are not renamed
or retrospectively mutated. Whole proposed status-active membership remains capped
at 10,000, including future/expired intervals; complete existing sets are not sliced.

Application confirmation sends the server-returned `preview_id`, expected roster
revision, complete `confirmed_withdrawals_digest` and complete
`confirmed_withdrawals_count`. Samples or a capped client withdrawal array cannot
replace full-set confirmation. `can_apply` describes hypothetical domain validity;
it does not override write safety or mean production mutation is available.

All accepted hypothetical writes commit before constructing their success response.
A delayed response retains its original receipt/result after a second authorized
update. `GET /api/teaching/receipts/{receipt_id}` or the original action/scope/key
lookup recovers that immutable acceptance under **current** authorization. A later
offering GET independently reports newer state. Receipt recovery is not a fresh
current-state projection. A lost/ambiguous response must retain the original key;
`write_outcome_unknown` never promises that nothing committed. Frontend stale-
response fencing is a separate unverified task.

## Error distinctions

- 401 `unauthenticated`: missing/invalid/expired signature or missing/invalid
  current account; account/profile details are not returned
- 404 `not_found`: missing, hidden, foreign institution, cross-offering or
  wrong-actor object IDs have the same envelope
- 403 `permission_denied` and bounded domain reasons: visible scope lacks the
  separate requested authority
- 422 `validation_error`: strict malformed DTO/query, with no mutation
- 409: accepted bounded revision/lifecycle/preview/confirmation conflicts
- 503: feature-off, typed missing/incompatible teaching schema, unavailable DB,
  dedicated transaction refusal, hard write safety refusal or outcome ambiguity
- 500 `internal_error`: unexpected programming error, only a correlation ID;
  private SQL/config/stack traces remain server-side

Typed missing-schema dispatch uses a synthetic typed failure and is not missing
MySQL proof. The genuine unpatched SQLite readiness refusal reports
`teaching_schema_incompatible`, because actual MySQL verification is absent.

## Actual MySQL validation: all 14 runtime gates NOT RUN

The current platform could not create the authorized database Unix socket. No
server identity or actual database execution was established. This runbook records
required observations only; it does not launch a server/migration or prescribe an
alternate transport, environment or security workaround. Runtime implementation
and execution require a separately supported, explicitly authorized runtime owner,
frozen sources, exact named selections and a new guarded synthetic schema.

1. **NOT RUN — canonical collation aliases.** Record actual account collation;
   equivalent signed subjects share one canonical relationship/receipt namespace,
   while distinct accounts never gain alias access
2. **NOT RUN — account deletion/demotion during root wait.** Independent committed
   account changes are re-read after lock release; new writes/recovery are refused,
   with an unchanged-account positive control
3. **NOT RUN — role revocation/update during root wait.** Real serialized role
   revision changes deny stale grants/replay with no extra business/event/receipt rows
4. **NOT RUN — trusted-source revocation during wait.** A coherent test-policy
   generation is captured after actual waits; changed sources fail closed. This
   proves only a single-process policy reader, never multi-worker propagation
5. **NOT RUN — authority expiry at final receipt lock.** Real receipt contention
   crosses the boundary; final post-wait clock denies expired role/enrollment.
   Independently establish the production DB clock source
6. **NOT RUN — preview expiry while waiting.** New intent fails atomically;
   accepted old intent with current rights recovers before new preview checks
7. **NOT RUN — competing roster applications.** Same-key duplicates yield one
   original result; competing old revisions yield one acceptance/one conflict;
   verify full withdrawals and stable enrollment IDs
8. **NOT RUN — concurrent role writes.** Missing-row same-key grants do not
   duplicate; competing revision writes serialize and conflict correctly
9. **NOT RUN — import versus role revoke.** Establish both actual root-lock
   orderings and their resulting current-authority/immutable-receipt behavior
10. **NOT RUN — import versus archive.** Both orderings distinguish new lifecycle
    rejection from original-receipt recovery under current rights
11. **NOT RUN — archive versus receipt wait/time.** Historical acceptance does
    not bypass expired current authority after an actual receipt wait
12. **NOT RUN — failures and rollback.** Independent observer sees no partial
    business/event/receipt state; separately classify real timeout/deadlock and
    simulated transport/commit ambiguity
13. **NOT RUN — independent-root missing receipt interval.** Separate canonical
    actors/roots and actual READ COMMITTED connections need server lock/transaction
    evidence and valid final timestamps. Unexpected genuine contention must not
    permit successful stale-clock acceptance
14. **NOT RUN — preview footprint/final-lock order.** Trace actual scoped
    original-actor preview discovery after roots, then account/relationship and
    final preview/receipt locks before clock. Hidden previews never touch target
    accounts; accepted replay and new application retain distinct validity checks

For every future runtime case, record server identity, isolation established before
identity SQL, separate sessions/connections, bounded deterministic barriers,
blocking from server transaction/lock evidence, exact source/test hashes and final
database observations. Sleeps alone and SQLite cannot establish these guarantees.

**Separate migration gate — NOT RUN.** Identity must match authorized socket,
datadir, schema and server UUID before DDL. Verify additive compatible partial
schema/reentry, refusal of incompatible shape, unchanged data on rerun and ordinary
startup exclusion of all teaching/assessment tables. This is plan-only: business
migration, backup and rollback require their own authorization. No ordinary
startup or aggregate import is an approved migration path.

## Remaining rollout gates

Actual MySQL runtime/locking/clock/DDL evidence; resolution of unconditional
write-safety refusal; account incarnation/username reuse; synchronized multi-worker
policy changes; real institution/source roster/delegation ownership; manager
recovery/retention/archive policy; browser permission and user journey acceptance;
query cost and production latency; authorized migration/backup/rollback and release.
No B2/B3 feature, real course, real learner grant or feature activation is delivered.

## B2 Task6 bounded signed HTTP source integration

This later checkpoint mounts a separate finite B2 router structurally under the
same `/api/teaching` prefix. Isolated tests mount B1 and B2 routers directly; they
never execute the aggregate router, main application or startup. The exact B1
async current-account dependency, dedicated DB dependency, error envelope and
commit-before-success helper are reused. No bearer role, body owner/student ID,
module import or fixture substitution grants production authority.

The source workflow is public draft create/replace, separately authorized private
save, immutable freeze, public-only release preview and complete recipient pages,
bound confirmation, learner release read, inert text/code submissions, immutable
own history and scoped teacher views. The original B1 receipt endpoints recover
all seven finite B2 write actions under current object-specific rights; there is
no second recovery token or current-state replacement of an original acceptance.
Unknown or lost responses retain the original action/scope/key. A 404 recovery
means outcome remains unknown, not permission to generate a replacement key.

All B2 detail and mutation routes reject query parameters; lists reject unknown,
duplicate and invalid fields, use limits 1–100/default 50, and retain the existing
nine-kind bounded cursor codec and actor/object/query/projection bindings.
The shared original receipt-detail route now rejects queries and malformed IDs.
Private answers, private hashes and recipient snapshots do not appear in learner
DTOs or acceptance receipts. Shared private-error logging records only a
correlation ID and exception class; no exception text, traceback, authored text,
SQL statement or parameters are logged by that handler.

B2 `configured`, `installed` and `available` describe read readiness only.
Installation requires the actual matching B2 physical shape and component ledger;
production availability additionally requires B1 readiness and the assignment
flag plus the unchanged vendor/schema gate. SQLite remains synthetic and vendor
unverified. Every stage and the overall capability explicitly report
`writes_available=false`, `write_reason=write_safety_unproven`; public write
actions stay empty. B3 feedback and B4 revisions stay unavailable. Accepted
submission DTOs say execution `not_available` and assessment `not_implemented`;
there is no grading, evaluation, mastery or code-execution claim.

The positive signed ASGI journey uses the existing five function-scoped b2case
readiness/transaction/hard-gate/fixed-UTC substitutions, with only the existing
fixed-UTC target advanced for historical replay. Only the DB request dependency
is overridden; signatures and current persisted accounts are real in this
synthetic process. Genuine feature-off, schema/vendor, dedicated-transaction and
hard-gate refusals are separate. Commit tests inject a scoped synthetic exception
before or after the actual Session commit; these are simulated outcomes, not
actual network transport or MySQL commit-ambiguity evidence. The ordinary loss
case sets aside a completed HTTP response before a later business write/GET and
recovers the original receipt. It does not establish frontend stale-response
fencing or an actual socket-delivery failure.

### Additional B2 actual-runtime requirements: all NOT RUN

The preceding fourteen B1 actual-MySQL gates and separate B1 migration gate remain
NOT RUN. None is satisfied by B2 source, isolated ASGI or SQLite results.

1. **NOT RUN — separate additive B2 migration.** Verify authorized DB identity,
   actual composite FKs, unique indexes, checks, byte/collation behavior, partial
   compatible reentry and the unchanged B1 physical contract/data
2. **NOT RUN — two release confirmations.** Same intent yields one release and
   receipt; different intents for one version yield one release and conflict,
   including atomic complete recipient and empty-head rows
3. **NOT RUN — simultaneous submissions.** Two initial null parents or identical
   later parents yield exactly one head advancement, with no root duplicate,
   fork or partial submission/event/receipt state
4. **NOT RUN — authority/lifecycle/deadline races.** Establish both actual lock
   orderings for release versus roster/role/source revocation and submission
   versus withdrawal/archive/deadline, final DB time and independent observers.
   Relevant lock traces, not sleeps alone, are required
5. **NOT RUN — post-clock waits and commit recovery.** Prove actual B2 FK/unique
   waits, real commit ambiguity and recovery rights after authority change.
   Keep the hard gate closed until a separately reviewed solution and vendor
   evidence establish safety; SQLite success does not establish it
6. **NOT RUN — rollout integrity and cost.** Account incarnation/username reuse,
   coherent multi-worker policy generations, real institution/source-roster/
   delegation ownership, retention/archive/recovery policy, query bounds,
   cross-worker visibility, acceptable production latency and performance remain
   prerequisites
7. **NOT RUN — teacher/learner browser and operational release.** Actual browser
   journey, durable data persistence, frontend context/recovery/stale-response
   wiring, approved business migration/backup/rollback and release authorization
   are missing. Flags-off does not imply a historical read-only fallback

No native MySQL, migration execution, server/socket, browser, provider, external
secret, package installation, paused Git semantics, commit, push, deployment,
activation, B3/B4 feature or production acceptance is part of this checkpoint.

## B2 staged/finalized protocol, Tranche 1 source checkpoint

Only the seven finite B2 write actions use the new pending/finalized owner path.
B1 execution, original-receipt recovery, self-revocation and HTTP commit semantics
retain their existing path. The unconditional production `_require_write_safety`
refusal and every public `writes_available=false` projection remain unchanged.
No native validation owner, request/header/query switch or Session admission
boolean is introduced by this tranche.

The B2 candidate is established at database clock **t0**, after the held root,
canonical account, relationship, assessment ancestry and original-receipt locks.
The engine captures the pre-write draft/head/parent and release-existence baseline.
For a new acceptance, it stages and separately flushes business changes, original
receipt and AssessmentEvent. These DML stages may encounter database-internal
constraint/index waits; they all finish before final admission.

Continuously installed engine guards cover staging, pending handoff, detached
response construction and actual JSONResponse byte encoding. Handoff permits no
application SQL or mutation. The owner prebuilds both the fixed success response
and the bounded original-tuple unknown-outcome response before the final clock.
An encoding failure abandons the candidate before COMMIT.

The same-transaction finalizer samples the complete current policy, permits only
one exact owner-issued `SELECT UTC_TIMESTAMP(6)`, and obtains **t1**. Invalid or
backward clocks fail closed. Pure current-authority checks use held accounts,
roots and relationships and a distinct immutable t1 authorization snapshot.
New-intent structural checks use the pre-write baseline, never the already
advanced draft revision or submission head. Temporal checks cover actor periods,
every release recipient's eligibility, confirmation-preview expiry, deadline and
a newly created preview's own fixed `t0 + 15 minutes` expiry. Accepted same-key
replay retains the original historical result and skips new-intent head/revision,
audience and preview/deadline predicates, while rechecking current authority at t1.

Successful admission atomically seals the transaction. No later SQL, DML,
autoflush, allocation or second execution is allowed. Nested transactions and
cross-session/repeated finalization are refused. Only the bounded owner's sole
COMMIT or failure cleanup remains. No receipt, event, version, preview, release or
submission timestamp is rewritten: existing immutable timestamps stay at t0 and
become accepted historical values only after final admission and successful COMMIT.
The deadline contract is validity at t1, **not physical durability before a
specified deadline**. COMMIT can finish later.

An exception from a possibly dispatched COMMIT remains `write_outcome_unknown`
with the original action/scope/key. The connection's pre-COMMIT event is not proof
of success. A first-installed Session after_commit marker additionally requires
that the bound physical root's COMMIT returned and the root was removed; only
then is acceptance confirmed. A later owner cleanup/listener failure preserves
the already encoded accepted response rather than manufacturing ambiguity.
Rollback/invalidation failures retain fail-closed guards until successful cleanup
or disposal proves terminal completion. Private diagnostics contain only bounded
phase/state and exception-class information, never authored content, credentials,
SQL text/parameters or raw exception text.

### Evidence boundary and deferred integration

The bounded protocol and narrow existing direct-owner helper adaptations use only
registered, immutable SQLite/synthetic selections. They retain the five historical
fixture-local application targets; deliberate stage/commit/cleanup faults are
separately labeled simulated. A genuine unpatched production hard-gate negative
control is included. Synthetic success is not native FK/unique/index-wait,
isolation, timeout/deadlock, physical durability or production acceptance proof.
The excluded replay/lock-collection side-effect probe is not exercised.

Owner-helper cleanup containment is the entire Tranche 1 claim. Real request
and dependency teardown through rollback, `db.close()` and `connection.close()`
remains a separately reviewed Tranche 2 integration requirement. Native validation
owner construction, exact native environment/schema/seed/DDL approval, seven-action
acceptance and wait evidence are also deferred. Account incarnation/username reuse,
coherent multi-worker policy rollout and deployment activation remain unresolved
production prerequisites. This checkpoint does not close all fourteen business
validation categories or activate any teaching writes.

**Explicit blocked observation.** The unchanged guarded runner permits only the
original in-memory SQLite fixture. It refused the proposed file-backed synthetic
fixture with `GuardDenied: Only original in-memory SQLite fixtures are allowed`.
Both `test_confirmed_commit_survives_later_owner_cleanup_failure[after_commit]`
and `[guard_cleanup]` therefore produced setup errors, not passes. Their frozen
source/logs retain that history; no guard change, URI/DBAPI workaround or other
executor was used. The unsupported fixture is absent from the final selected
source. The separate `test_known_commit_owner_response_preserves_prepared_success`
uses the historical memory fixture and proves only the prepared owner response,
post-COMMIT marker, reached faults and guard retention/restored cleanup. It makes
no observer or post-invalidation persistence assertion. Durable post-invalidation
visibility remains **BLOCKED/UNPROVED**, to be addressed only in a separately
reviewed supported acceptance environment; this narrower result does not close
that gap or the real dependency-teardown requirement.
