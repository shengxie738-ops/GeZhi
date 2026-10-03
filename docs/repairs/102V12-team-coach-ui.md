# Team repository / coach UI repair plan

Scope: production API adapter, student collaboration UI, teacher training UI, shared coach feedback component and focused offline behavioral tests. Existing execution/rendering/authentication fixes remain unchanged. No remote credentials, live Gitea, paid AI, restored database, commit or push.

1. Replace implicit mock-first/fallback paths with authenticated receipt-validated requests. Preserve HTTP failures, stable account IDs and display names; never append viewers or manufacture repository evidence.
2. Separate saved project and coach reads from explicit external sync. Shared coach view supports independent pagination, retry, honest status/provenance, bounded backoff and cancellation on navigation.
3. Guard stale requests and duplicate writes; use stable selected member IDs/branches, server capabilities, truthful local deletion/reminder/bind semantics. Remove teacher hardcoded students.
4. Run test-first adapter/component/controller behavioral regressions, refresh isolated runtime staging from actual sources, run focused and aggregate tests, record all limitations.

Coach contract coordinated with durable-job worker: GET projects/:id/coach {projectId, feedback, jobs, nextCursor, worker}; POST projects/:id/coach/jobs/:jobId/retry {projectId,jobId,status,attempts}. No live Gitea operation is required to read persisted feedback.

## Implemented and verified

- Removed the entire production mock-project store and every mock-first/fallback callback from `teamGit.js`. Receipt validators reject missing/mismatched project DTOs and false local-deletion receipts. 401/403/500 remain errors even with the obsolete localStorage mock flag set.
- Stable member usernames/IDs are write targets; readable names are presentation-only. Read enrichment does not append viewers. Workflow commands use the current member's assigned branch. Management controls consume backend `permissions`.
- Saved project reads no longer request live synchronization. A dedicated student/teacher coach component calls persisted coach endpoints independently, paginates, displays all job states including rules-only, evidence provenance and fallback reasons, and supports authorized bounded retries. It keeps prior feedback visible during retry while exposing queued/running jobs and withholding busy/exhausted retry controls.
- Automatic pending polling uses exponential backoff (2s to 30s), at most eight automatic rechecks, and stops on terminal state, error, unavailable worker, navigation or unmount. The UI then offers manual refresh. Request-generation guards prevent cross-project late reads/writes and stale loading unlocks; request signals abort coach reads.
- Teacher writes are single-flight. Teacher creation selects a real roster search result for the leader instead of inserting fictional students. Repository binding prompts for actual owner/name and relies on the backend verification receipt. Delete explicitly means local project only; reminders explicitly mean persisted in-app records; clone confirmation is self-report.

## Verification and limits

Focused offline suite: 26 passed. Tests execute real API functions with mocked HTTP receipts, real Vue component setup/lifecycle/actions through a custom renderer, actual templates through the Vue compiler, and the production polling/request-scope controller with controlled asynchronous responses/timers. This is behavioral coverage, not browser visual acceptance. The compiler only tolerates the pre-existing embedded `<style>` side-effect warning; new syntax errors still fail.

Full frontend suite is also run, with unrelated failures recorded in 102V12-AI-Git-教练交付说明.txt. Runtime staging is refreshed from the actual edited source and byte-compared. No browser retries around the known local-access restriction, no live Gitea, no real credentials, no paid model call, no restored database, no commit or push.

## Legacy evidence gate (review follow-up)

`teamProvenance.js` consumes actual backend provenance. Historical PRs without `verified: true`, or with `provenance: legacy_unverified`, get an explicit unverified label and neutral warning styling rather than saved approved/merged labels. Review controls are hidden and both student/teacher action handlers reject them before any request. Verified real open PRs remain actionable. Home-level and per-field warnings identify historical content; a live `readmeSource` / `classDiagramSource: gitea` exempts only that fetched field. The actual compiled teacher template is rendered through a custom host to assert visible warning and absent historical approval/merge controls, alongside positive action tests.
