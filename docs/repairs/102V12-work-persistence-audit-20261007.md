# 102V12 Work persistence audit and bounded paper receipt fix

## Required migration and release boundary

**Fresh pulls require the explicit `chat_batch_receipts` migration before keyed paper history can save.** Missing or incompatible schema returns HTTP503; there is no unsafe legacy-write fallback or startup DDL. The code is an isolated candidate, not a production deployment or completed production migration. The separate frontend paper-sync wording fix must be composed before publication: `CHAT_BATCH_COMMIT_UNKNOWN`/`CHAT_BATCH_OUTCOME_UNKNOWN` mean cloud save is unconfirmed, not definitely local-only.

Source: shengxie738-ops/GeZhi, 102V12, exact commit `05c23b2a20d39ac6521190d021d5988caebff5fb`. A fresh GitHub Connector recursive tree and Git blob hashes verified every one of the 502 copied tracked backend files before editing. A read-only frontend `useChat.js` comparison also matched that tree. Work ran only in an isolated dot cloud filesystem copy. Canonical/previous candidates were not changed.

## Verified flow map

| Flow | Consumed production path | Evidence level |
|---|---|---|
| Student capabilities | `student_work.router`, current-account auth, static capability policy | Actual assembled router, in-process ASGI, real SQL account read and temporary SQLite. Body and static revision remain exact; separate readiness header does not alter plugin facts |
| Selected Skill | ChatRequest, validation/resolution helpers and existing selected dispatch functions | Exact source-extracted `/chat` rejects invalid selections before origin persistence; existing AST/recording-port tests verify fixed server prompt, owner model, truthful unavailable/empty/failed result, no invented tool fallback |
| Paper pair save/read | Exact extracted batch/history/delete/clear handlers, actual chat history services, SQLAlchemy models | Actual HTTP + temporary file SQLite + fresh Sessions; exact frontend two-message wire shape, atomic pair/receipt, stable IDs, owner/scope/digest conflicts, fresh query/results/abstract/completeness read |
| Teacher private task | Actual Work ORM, SQL repository/coordinator and current-account helpers | Real SQL repository slice with explicitly test-owned trusted namespace/transaction adapter: CRU, revision, rollback, ownership; not production MySQL request-owner admission |
| Teacher private chat | Actual repository/decoders/executor with controlled provider double | PENDING accepted receipt; stable replay; owner/task history/run/cancel scope; COMPLETE/FAILED/CANCELLED; rollback/retry and completion receipts; no DB connection held during provider await |
| Teacher assembled production route | Actual router/bootstrap/teaching-session guard | Negative503 on SQLite with synthetic private flags; no production gate bypassed. This does not establish successful full-app/MySQL HTTP acceptance |

Personal student AI/paper history remains self-only. Teachers are not given access to personal transcripts. Academic Reviewer is prompt-only `academic-review`; Python/chart/Zotero/Semantic Scholar cards remain metadata-only, and installed browser preference does not establish executable capability. All external live-verification facts remain false. No searches or live provider calls ran.

## Proven baseline defects and candidate closure

- Two Sessions paused before their first INSERT both append the same stable paper key: baseline returns distinct pairs `[3,4]` and `[1,2]`, leaving four rows
- Saving a pair, clearing both rows through actual `clear_chat_history`, then replaying the same body returns baseline200 success and recreates two rows
- The final candidate passes both unchanged semantic regressions: one unique pair, and409/no resurrection after deletion

The original schema has no unique batch receipt. `DomainRecord` likewise declares only its integer primary key and ordinary indexes, no composite unique key. `JsonStore.create` calls overwriting `upsert`; caller-owned/atomic modes add no unique reservation. Global DomainRecord semantics are preserved.

## Minimal implementation

- New isolated-metadata `ChatBatchReceipt`: exact owner UTF-8 bytes (max1020) and client-key bytes (max512) form the composite primary key. Unicode normalization variants, casing and trailing key spaces are not collapsed. Noncanonical/oversized owners are rejected, not truncated
- Receipt stores only owner/key, SHA256 canonical fingerprint, paper/conversation/project scope, the two message IDs and state. It contains no message/query/request-body plaintext. No message foreign keys: transcript deletion must retain its minimal retry tombstone
- Plain INSERT reserves the key before any append. Pair flush, exact IDs and committed state share one commit. A failed reservation gets a whole-root rollback and one fresh/current locked read; it never performs another INSERT automatically
- The keyed-paper HTTP route uses a separate fresh Engine-bound Session because authentication already owns a read transaction on its dependency Session. The receipt service refuses any active/pending/flushed caller or external-Connection root before SQL/flush/commit/rollback. It begins and finalizes only the fresh supplied root
- Same key/different fingerprint/scope, partial/deleted/missing pair or inconsistent legacy pair gives409. A matching replay validates both exact owned message IDs and persisted body facts, returning a commit-time projection without post-commit refresh. All response-consumed attributes, including lazily loaded server TIMESTAMP defaults on no-RETURNING INSERTs, are materialized before detach
- Commit/cleanup ambiguity gives explicit503 unknown. Deadlock, lock timeout, unrelated SQL error, absent schema or corrupt receipt gives explicit unavailable; no automatic append/retry. Cleanup failure cannot mask a commit-unknown result
- Receipt-first ordered locks precede paper transcript mutation. Owner/pair-ID/scope/key associations are validated before mutation; corrupted digest alone does not block legitimate owned deletion when the related metadata is safely tombstoned. Single deletion or clear marks minimal receipt state deleted in the same transaction. Other chat/tutor/rag deletion behavior is not coupled to receipt readiness
- Missing receipt schema still allows deleting old unreceipted history, but known receipt_version1-backed rows refuse deletion503. Adopted old pairs gain that internal marker without replacing IDs or fingerprint. Present-but-incompatible schema explicitly blocks paper deletion503 and leaves rows unchanged, so the operation is not silently reported successful
- Valid old `_sync` pairs can adopt a receipt under one reservation without append, ID replacement or fingerprint overwrite. Duplicate/partial/mismatched legacy rows409. SQL candidate lookup is followed by exact stored owner/key comparison to avoid MySQL text-padding/case aliases

Exact-owner SQL filtering is shared across personal history/page reads and the touched paper save/adoption/replay/deletion paths. SQLite compares CAST-as-BLOB bytes; MySQL compiles character conversion USING utf8mb4 followed by CAST-as-BINARY, preserving Unicode code points without relying on case/padding text collation. Paper bulk deletion targets only locked, exact-owned verified row IDs. Conditional NOCASE fixtures prove no foreign rows/IDs/snapshot/cursor leak and no foreign paper mutation while own rows remain visible. The schema premise is deliberately synthetic; no deployed incident or native MySQL runtime verification is claimed. No table collation or account identity schema was changed. Other generic-mode mutation semantics remain unchanged and were not given a new collation/lifecycle certification.

**Compatibility limit:** fully deleted pre-migration keys have no surviving source receipt and cannot be reconstructed. Non-resurrection is guaranteed only for receipt-backed/adopted requests. Mixed old/new writers must be quiesced for rollout; old code ignores the new reservation protocol. Username deletion/recreation is an existing account-incarnation limitation, not solved by this patch.

## HTTP contract

-200 success: unchanged success envelope, exactly two positive persisted IDs
-409: fingerprint/scope conflict, deleted/missing pair, inconsistent legacy history
-503 `CHAT_BATCH_SCHEMA_UNAVAILABLE`: schema unavailable; no write is attempted
-503 `CHAT_BATCH_COMMIT_UNKNOWN` or `CHAT_BATCH_OUTCOME_UNKNOWN`: cloud outcome unconfirmed; retain stable body/key for explicit reconciliation
-503 `CHAT_BATCH_UNAVAILABLE`, `CHAT_BATCH_SESSION_NOT_CLEAN` or `CHAT_BATCH_RECEIPT_INVALID`: controlled unavailable outcome, no automatic append

The capabilities JSON shape/revision is unchanged because the production frontend validator rejects extra top-level keys. `X-Gezhi-Paper-Batch-Available: true|false` is additive diagnostic readiness only; no claim is made that the frontend consumes this header or that cross-origin access is exposed. No CORS/security setting was changed. Existing frontend explicit retry retains the serialized body/key; the separate frontend wording patch is required to avoid calling unknown cloud outcomes local-only.

## Explicit installation/preflight

`backend/migrations/v20261007_chat_batch_receipts.py` exposes:

- `observe_database_identity(connection)` (read-only)
- `preflight_chat_batch_receipts(connection, expected_identity=..., contract_hash=...)` (read-only, fresh caller connection)
- `apply_chat_batch_receipts(connection, expected_identity=..., contract_hash=...)` (explicit caller-authorized additive installer)

No function creates an engine, reads settings/secrets or runs at app startup. A fresh absent table is installed; exact schema is a no-op; incompatible/partial schema is refused without ALTER/DROP/automatic repair. Physical checks require exact columns, full-length VARBINARY primary key, enforced checks, actual utf8mb4/utf8mb4_bin table and character-column facts, nullability/default/generated attributes and signed integer types, persistent transactional InnoDB participants, autocommit0 and uniqueness enabled. Padded BINARY and prefix primary indexes are refused.

Operator sequence, from the backend source directory:

1. Stop/quiesce all old and new keyed paper writers; approve the exact database/schema/server UUID and retain a backup. Deployment/migration approval is separate from this code patch
2. Obtain the existing operator-authorized SQLAlchemy engine without putting credentials in command arguments or documents. Do not infer identity from the configured URL
3. On a fresh dedicated connection, call preflight with independently approved identity and the reviewed `CONTRACT_HASH`. Close/rollback its read transaction before calling apply
4. Call apply on a fresh dedicated connection with the same identity/hash. Reinspect complete physical schema and test owner save/replay/delete before releasing writers

Example with an already authorized `approved_engine`:

```python
from migrations.v20261007_chat_batch_receipts import preflight_chat_batch_receipts, apply_chat_batch_receipts
from app.services.chat_batch_schema import CONTRACT_HASH
expected = {'dialect': 'mysql', 'database': '<approved schema>', 'server_uuid': '<approved server UUID>'}
with approved_engine.connect() as connection:
    preflight_chat_batch_receipts(connection, expected_identity=expected, contract_hash=CONTRACT_HASH)
    connection.rollback()
    result = apply_chat_batch_receipts(connection, expected_identity=expected, contract_hash=CONTRACT_HASH)
    assert result['completed']
```

MySQL DDL auto-commit can leave a table after an interrupted apply. Failure is not an atomic rollback promise: re-inspect identity/shape before retry, and separately review incompatible partial state. Rolling app code back reintroduces the old defect; preserve the receipt table/tombstones and keep old keyed writers quiesced. Dropping/purging receipts permits old retries to recreate content and is not a safe application rollback.

Receipt-only metadata must remain while old retries are permitted. A genuine account/data purge requires a separately approved retention/purge decision and cancellation of outstanding retries; deleting/recreating usernames is not an account-incarnation-safe resolver. No indefinite retention policy or account-purge operation is silently introduced or executed here.

## Reproducible tests

Use the existing isolated venv or the pinned direct dependencies already listed in `backend/tests/requirements-interaction-audit.txt`; no new dependencies were installed.

```sh
python backend/tests/run_work_persistence_audit.py --report-json /tmp/work-contracts.json
python backend/tests/run_work_persistence_audit.py --race-probe --report-json /tmp/work-race.json
python backend/tests/run_work_persistence_audit.py --deletion-probe --report-json /tmp/work-deletion.json
```

Final R2 candidate: **80 passed** (17 existing capability/skill cases +63 bounded contracts, including eight supplied-MySQL-observation decoder cases). Previous explicit interaction/private-history regression slice: **52 passed**, including40 personal-history owner/teacher/peer policy cases. The ordinary runner includes both former-red proofs. Independently replaying the final harness against the exact original source with `--source-root ORIGINAL_BACKEND --race-probe` and `--deletion-probe` produces one expected failure each with four appended rows and two resurrected rows respectively. Source namespace resolution is pinned and every imported/extracted application file is hashed; mixed-source runs are rejected.

R1 was independently NO-GO despite its66 authored passes: caller ownership, missing backed schema, physical catalog gaps, no-RETURNING projection and conditional collation cases were added as red regressions before R2 fixes. R1 files/evidence remain unchanged. Coverage includes second-insert rollback/no orphan receipt, commit-ack loss, cleanup failure preserving unknown, explicit retry of committed pair, clean caller refusal, legacy adoption/conflict, metadata-only receipt, exact Unicode/trailing keys, schema absent/incompatible, unrelated deletion compatibility, actual installer identity/hash preflight/apply/no-op on an owned SQLite file, SQL constraint NULL handling, and MySQL DDL compilation. Synthetic SQLite foreign keys are enabled. Earlier Pydantic configuration deprecation warnings were recorded in baseline-stage logs; final focused output reports80 passed.

The subprocess uses a temporary blank cwd and synthetic-only environment, blocks sockets/DNS before imports, and does not import app.main/init_db. Tests are `native_*` opt-in, with no global pytest configuration.

## Remaining qualification gates

No full app, MySQL service/concurrency/isolation, production migration/data, live provider, Docker, native parser, browser/mobile, full suite, training, system settings, .env/secret read, Git commit/push or publication occurred in this executor. SQLite proofs and compiled MySQL DDL do not establish native MySQL commit/lock/isolation behavior. The root coordinates independent code review, native MySQL qualification and the separate frontend unknown-outcome wording fix before any release claim.

R2 supersedes R1 only after independent review. MySQL8.0.39 initialization in a separate root qualification attempt succeeded, but its UNIX socket bind was denied and the server exited; no native acceptance was possible and no TCP fallback was used. This executor did not run that qualification.
