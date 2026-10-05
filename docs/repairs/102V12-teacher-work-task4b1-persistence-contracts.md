# Teacher Work Task4b1 persistence contracts

Date: 2026-10-05 UTC
Stage: source declarations and pure supplied-fact contracts; live gates remain closed

## Included

- Exact UTF-8 run and user-message keys represented as VARBINARY(512), preserving case, spaces and Unicode normalization form
- Durable repair-count and cumulative call-budget declarations, with a four-component nullable active-call record linked to its run; cancelled runs may retain unsettled calls
- A separate nullable unique assistant-completion receipt and optional actual result classification/omission, with no invented historical defaults or assistant user-message keys
- Backward-compatible output metadata and strict pure key, token, stored-state and actual-result receipt/projection helpers
- A chat absolute deadline of three times the configured per-call timeout capped at 90 seconds, never more than 270 seconds; retries and repair must retain the original deadline
- Byte-frozen published v1 contract and pinned original preparer, coordinated active v2 shape/hash and nonexecuting preparation descriptions
- Explicit normalized server-default facts in the v2 hash/readiness comparison: repair-count zero and no fabricated completion/result metadata defaults

Preparation supports fresh v2, exact v2, or exact v1 with explicitly supplied zero run rows, message rows and active leases. Partial/mixed schemas, unknown ledgers, nonempty history and live leases are refused. Supplied facts do not prove a real database is empty or prepared.

## Verification status

All 48 finite checks passed: 11 persistence pure/source cases, 21 retained contract cases, five chat cases, seven run-decision cases and four isolated metadata/MySQL-compilation cases. All selected setup/call/teardown phases passed without denied operations.

The tests-first missing-feature baseline was observed before implementation. An added default-facts regression then exposed the absent v2 default map; the minimal correction passed the same supplied-observation checks. A statement-example assertion was corrected to expect MySQL’s required quoting of the reserved ROLE identifier, preserving all qualified equality and named-binding assertions; no product mapping was changed to accommodate an invalid test expectation.

The four MySQL statement cases compile examples over isolated metadata. They do not exercise a production CAS writer, execute statements or establish physical uniqueness/transaction behavior.

## Still pending and closed

Atomic run/message/lease admission, durable pre-dispatch budget/token charging, real assistant finalization, cancellation settlement/release, retry/recovery and fresh current authority after provider waits remain Task4b2 responsibilities.

Physical schema/data inspection and MySQL DDL, historical migrations, account-incarnation/namespace/teaching acceptance, real providers, storage, HTTP/UI acceptance and feature activation remain closed. Public request fields, RunDTO, existing provider model/settings, identity/account schema, bootstrap/router and unrelated Student Git source remain unchanged.
