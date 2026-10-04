# Teacher Work T2a command coordinator

Date: 2026-10-04 UTC
Stage: bounded source foundation; Teacher Work remains disabled and unintegrated

## Included

- A production pure coordinator implementing create_task, from_legacy, get_task and patch_working
- Required caller-owned active transaction participation and trusted current teacher/scope authorization seams
- Original lesson-preparation draft remains the only current lesson/resource store
- Exact Unicode task-create receipts, paired nullable server-only key/digest declarations and owner/key uniqueness contract
- CAS saves always advance working_revision; content, selection or base-lineage changes advance input_revision and clear current-outline eligibility without deleting prior approvals/history
- Requirements, base lineage and normalization markers stay in server-owned metadata beside the original draft content
- Pure legacy normalization and guarded save-decision helpers

Legacy import preserves the original ID, content and timestamps. Missing required task metadata, especially a blank audience, requires explicit normalization before linking. Unknown paragraphs are retained and marked, without manufacturing a validated lesson, outline or version.

Known-field lesson edits retain opaque legacy root fields and uniquely matched stage/citation provenance. If safe matching is unavailable, the save refuses atomically with a normalization-required outcome. An inner lesson duration that disagrees with the Task duration remains marked on import and later metadata-only saves; original minutes are preserved.

## Verification

44 unique finite source/contract cases passed: 23 coordinator/helper/static checks, including two product-review regressions, plus the existing 21-case T1 contract regression selection. The new cases call the production coordinator/helpers with synthetic recording row, draft and caller-UoW adapters. Both product-review regressions were observed failing before their fixes, then passing with the previous checks retained.

These checks establish pure command orchestration and source declarations only. Recording rollback, ordering and receipt observations do not establish actual SQL transactions, locking, durability, uniqueness or concurrency. No real ORM/database, DDL, identity producer, provider, browser, HTTP or Office-file integration was exercised.

## Still pending and closed

T2b must implement and verify the SQL/row/draft adapters, caller-owned JsonStore participation and actual legacy save guard wiring. The pure guard is deliberately not wired into the existing legacy service yet. T3 must supply current identity/offering authorization, a durable owner namespace, HTTP/current-draft projections and the legacy normalization bridge.

The existing AI lesson-preparation service and JsonStore are unchanged. Teacher Work task writes and generation remain closed until their real schema, identity, transaction and storage gates pass. This is not Task2 completion or an enabled teacher feature. Classroom publishing and existing course-write capability remain closed.
