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
