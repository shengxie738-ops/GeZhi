# Teacher Work T2b SQL adapter source slice

Date: 2026-10-04 UTC
Stage: adapter-only source verification; feature and real-transaction gates remain closed

## Included

- A separate explicit-Session SQL factory and task/draft/UoW primitives that reuse the T2a production coordinator
- Exact owner/object selectors, fresh ordered row locks, strict detached task decoding and owner/task/revision CAS statements
- Exact UTF-8 binary receipt keys, including Unicode and trailing spaces
- A durable, non-null unique owner namespace declaration on OwnerRunLease; first-write initialization requires the trusted locked authorizer, while reads never initialize or renew a run
- Create-only original draft reservation, ambiguity refusal and preservation of original content/ID/timestamps
- Explicit JsonStore caller_owned participation with active-caller checks and flush/refresh only; default legacy behavior remains unchanged

The Work raw-draft decoder rejects duplicate object names at every nesting level. Caller-owned storage rejects non-string keys, tuples and other Python-only payload shapes before querying or changing a row. Unknown reservation errors propagate; only an exact expected named Task unique conflict requests caller rollback and fresh authorized reconciliation. The adapter never performs replay inside a failed Session.

## Verification

53 unique finite source/contract cases passed, including nine SQL-adapter/strict-payload cases and the retained 44-case coordinator/contract selection. Both strict-JSON regressions were observed failing before their fixes, then passed with the previous checks retained.

The tests call production methods using actual declared SQLAlchemy metadata/compiled MySQL statement objects and supplied recording transport results. They check predicates, parameter binding, rowcount decisions, mutation/flush ordering and controlled errors. The injected DomainRecord fixture is isolated metadata, not the actual application ORM binding.

No engine, real Session, connection, DBAPI, live SQL, DDL or database was used. These results do not establish physical schema preparation, durable namespace/uniqueness, real locking, atomic rollback, concurrency or commit success.

## Still pending and closed

T3 must provide the actual current identity/offering authority footprint, durable namespace resolver, explicit request transaction owner, final admission after waits/flush and commit-before-response. Account-incarnation/username-reuse safety and supported MySQL acceptance remain release blockers.

The legacy endpoint/service is deliberately not wired to the new guarded caller-owned flow yet. Existing legacy consumers keep their prior behavior. Real schema/identity/transaction/storage gates, legacy wiring, providers, HTTP/browser/Office integration and activation remain unexecuted. This is not Task2 completion or an enabled Teacher Work feature; course-write and classroom-publishing gates remain closed.
