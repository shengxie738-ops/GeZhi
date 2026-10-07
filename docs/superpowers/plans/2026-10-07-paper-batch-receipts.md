# Paper batch receipts implementation plan

Goal: close the proven concurrent double-append and deleted-pair resurrection bugs for keyed paper pairs, without changing generic DomainRecord semantics or running project database DDL.

Architecture: one additive, explicitly prepared receipt table reserves an exact owner/key. One transaction binds its digest to exactly two message IDs. Replay requires the intact owned pair; deletion retains metadata-only tombstones. Existing valid legacy pairs may be adopted without append; missing legacy receipts cannot recover already-deleted old keys.

Files:
- Create app/models/chat_batch_receipt.py: isolated metadata; byte-exact composite primary key; digest, scope, pair IDs and receipt state; no plaintext message/query
- Create app/services/chat_batch_schema.py: read-only physical schema check and pure expected contract; MySQL InnoDB and exact primary key/column/check requirements, synthetic SQLite support
- Create app/services/chat_batch_receipts.py: keyed paper validation, plain INSERT reservation, transactional append/adoption/replay, duplicate loser rollback + one fresh reconciliation, explicit unavailable outcomes
- Modify app/services/chat_history.py: delegate keyed paper writes; receipt-first deletion/clear locks and tombstones; leave unkeyed generic history semantics unchanged
- Modify app/api/endpoints/chat.py: batch-only explicit503 for unavailable/commit-unknown; existing409 conflicts
- Create migrations/v20261007_chat_batch_receipts.py: identity/hash checked read-only preflight and explicit caller-authorized additive apply; never automatic startup installer; no global unique constraint or startup DDL
- Extend tests/native_work_persistence_contracts.py and explicit subprocess runner: unchanged capability/teacher proofs, synthetic-only receipt tests and hashes

Ordered checks:
1. Record red concurrent two-Session and complete-deletion retry proofs; inspect exact pre-existing schema and generic-store semantics (done: four concurrent rows and deleted history recreated)
2. Add tests for missing/incompatible schema with zero append, exact Unicode/trailing-space keys, receipt metadata without plaintext, transactional pair/receipt rollback and post-commit unknown outcome
3. Add isolated model/schema/preparation artifact, compile MySQL DDL only; ensure no startup creation
4. Implement reserve/append/replay with one commit. A duplicate insert must discard the failed root before one fresh/current lookup. Any unknown or unrelated SQL failure must return unavailable without automatic append
5. Integrate deletion using receipt-first ordered locks. Replay of deleted/missing pair conflicts with zero new rows. Legacy valid pair adoption must preserve IDs/fingerprint; duplicate/partial/inconsistent old history conflicts and never overwrites
6. Run all explicitly selected offline contracts, both previously red proofs, compile/metadata checks and source-byte manifest. No full suite, live DB/provider, new dependency or publication
7. Return exact patch/hashes and request independent review; actual MySQL concurrency/isolation remains an unverified deployment gate

Review focus: MySQL current reads after duplicate rollback; ambiguous commit and refresh/read failure; partial/deleted legacy receipts; exact UTF-8 owner/key without lossy normalization; transaction/table engine and deletion lock ordering. Account purge/recreation and retention of receipt-only metadata remain disclosed boundaries.

Execution result: the final ordinary explicit runner includes both formerly red proofs and passes80 cases; a separate prior privacy/interaction slice passes52. Actual installation was verified only on a task-owned temporary SQLite file; native MySQL qualification and deployment remain separate. Independent review is required before publication.

R2 review corrections: fresh route-owned transaction and non-mutating refusal of caller roots; server-default projection loaded before detach; known receipt-backed schema-loss fence; owner/ID/scope validation with digest-only deletion retained; strict physical charset/default/generated/integer catalog checks; shared exact-owner SQL filtering and verified-ID paper bulk deletion. R1 remains frozen NO-GO; R2 requires independent GO.
