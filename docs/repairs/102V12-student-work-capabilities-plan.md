# Student Work capabilities implementation plan

Parent approved the bounded design on 2026-10-06 at baseline b7fe5f80fb6376c09f0106e7210f76b15ffcc72a. Implement inline, then independent review. One first closure: AcademicReviewer. No generic execution, installation database, teacher Work changes, live calls, browser/mobile tests, deployment or CI queries.

- [x] RED: pure registry/fixture contract; forged and unknown client fields; TTL, account/token ABA, logout, failure recovery and revision cancellation. Existing selected Reviewer must never silently become plain chat.
- [x] GREEN: GET /api/student/work/capabilities with actual current-account dependency; canonical static schema-1 hash. Skill ID/policy version/modes share the existing server policy. Client fixed adapters intersect validated facts; preferences grant no execution.
- [x] Verify: shipped Vue/Node controller tests; existing isolated ordinary Python runner; owned MySQL full-app scenario with no permission/transaction overrides and synthetic provider transport. Count nonzero tests and zero skips; preserve prior evidence.
- [x] Freeze source, independent review and necessary RED/GREEN fixes. Record commands, counts, hashes, cleanup and limitations in repair evidence.
- [ ] Explicit-file commit; report candidate/head/results to parent and await CAS confirmation before ordinary push to 102V12.

Files: backend services/student_work_capabilities.py, services/student_work_skills.py, api/endpoints/student_work.py and api/api.py; frontend api/studentWorkCapabilities.js, utils/studentWorkCapabilities.js, config/academicPlugins.js, hooks/usePlugins.js and index.html. Tests/fixtures and the existing owned acceptance controller may be extended; expand only for a demonstrated integration requirement.

Contract: implementation, implemented, configuration_status and live_verified are independent. All live_verified are false; that does not disable implemented paths. Metadata-only entries have no skill/source/modes. Fixed source keys are identifiers, never URLs. Catalog lookup never reads model credentials or probes providers. Existing skill_ids payload is unchanged.

Session cache: memory only, TTL 60 seconds. Sequence/account/token fences apply to success, catch and finally. Account/token/revision changes cancel old discovery/source requests and invalidate academic cache. A selected unavailable Reviewer retains input/selection and requires retry or explicit removal. Ordinary chat after removal remains available.

Review focus: stale A→B→A replies; TTL expiry without a reactive tick; unknown fields/prototype accessors; unavailable Reviewer silently dropped; server/source version drift; revision withdrawal during a search. Each is a required test, not a deferred risk.

Review resolutions: R1 and R2 Important fixed; R3 regraded Important and fixed. Five covering regressions RED→GREEN; capability tests19/19; final necessary suite rerun. No deferred findings. Full Cloud desktop aggregate remains blocked by the existing missing locked dependency, and parent same-source dot aggregate is pending. Publication awaits parent CAS acknowledgment.
