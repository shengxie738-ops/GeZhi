# Task-history foreground gate test repair

Date: 2026-10-06 UTC. Published source base: `8ec87be3bb599138cfd7d6829419ec6dfefca792`, tree `69fadae320af2e7b6fbdaf13c0aa73fb480a3f2a`, branch `102V12`.

## Scope and cause

This candidate changes only `frontend/tests/teachingForegroundRevalidation.test.mjs` and this additive runbook. Production frontend/backend source, auth and foreground behavior, test discovery, shipped Vue, dependencies and existing evidence stay unchanged.

The original complete desktop invocation failed: 2,114 tests, 2,113 passes and one failure across 122 files, exit 1. Its module-level `priorGateRegion.length < 4500` assertion failed before the foreground file registered its 25 internal tests. Zero TAP skips did not establish that those tests ran. Preserve that original failure as historical evidence; this later successful candidate does not rewrite it.

The task-history stage added five event bindings within the existing authenticated `teacher-work` owner. The raw bounded root-gate region is 5,845 UTF-16 characters. Existing exact package/proposal exclusions leave 4,653. Removing only the five additional exact reviewed binding strings leaves 4,406, beneath the unchanged strict 4,500 bound. Whitespace, other bindings, and every gate predicate remain counted.

## Reviewed bindings and guards

- `reload-task-history` → `teacherWorkReloadTaskHistory`
- `load-older-tasks` → `teacherWorkLoadOlderTasks`
- `request-task-switch` → `teacherWorkRequestTaskSwitch`
- `confirm-task-switch` → `teacherWorkConfirmTaskSwitch`
- `cancel-task-switch` → `teacherWorkCancelTaskSwitch`

Each reviewed binding must occur exactly once in the root-gate region and exactly once on the `teacher-work` opening tag. The complete task-history/switch event family must equal those five names in source order; unknown family members fail. The owner predicate is checked exactly: `isLoggedIn && authVerified && currentRole === 'teacher' && currentView === 't_work' && teachingLegacyRenderAllowed`. Existing package/proposal completeness checks, the 4,500 bound, and all 25 auth/foreground lifecycle cases remain intact. No broad regular-expression removal is used for exclusions.

## Fresh verification and reproduction

Use the existing locked dependencies and Node 24.19.0. No install, npm command, notification check, registry request or network operation was performed for this repair. From repository root:

```sh
TZ=Asia/Shanghai node --import ./frontend/tests/fixtures/desktopShippedNodePreload.mjs --test --test-concurrency=1 --test-reporter=tap ./frontend/tests/teachingForegroundRevalidation.test.mjs
TZ=Asia/Shanghai node --import ./frontend/tests/fixtures/desktopShippedNodePreload.mjs --test --test-concurrency=1 --test-reporter=tap ./frontend/tests/teachingForegroundRevalidation.test.mjs ./frontend/tests/teacherWorkTaskHistory.test.mjs ./frontend/tests/teacherWorkPrivateTasks.test.mjs ./frontend/tests/teacherWorkAuthenticatedChat.test.mjs ./frontend/tests/teacherWorkMaterialsLifecycle.test.mjs ./frontend/tests/desktopTestRunner.test.mjs
TZ=Asia/Tokyo node frontend/scripts/desktopTestRunner.mjs --list
TZ=Asia/Tokyo node frontend/scripts/desktopTestRunner.mjs
```

The preserved original test first reproduced RED: exit 1 at the original line-53 size assertion; no internal lifecycle tests registered. The repaired single file then passed 25/25. The focused six-file selection passed 139/139, with zero failures, skips, cancellations or todos. Seven in-memory mutation controls separately rejected a missing binding, wrong handler, duplicate binding, unexpected history event, binding moved outside its authenticated owner, removed auth predicate and unreviewed size growth; production files were never mutated for these controls.

Fresh full aggregate ran `2026-10-06T15:53:18Z`–`2026-10-06T15:53:49Z`, exit 0: **2,138/2,138 tests across all 122 files**, with zero failures, skips, cancellations or todos. Official Vue 3.5.39 lane: 248/248 tests in eight files. Shipped Vue 3.3.4 lane: 1,890/1,890 tests in 114 files. Both child lane processes are explicitly fixed to `Asia/Shanghai`, despite outer `Asia/Tokyo`. Discovery is full and disjoint. The count rises by 24 because the old failed-file placeholder is replaced by its 25 successfully registered internal cases; no lifecycle test declarations were added or removed.

## Evidence and freeze

- Original full failure log SHA256: `df274ab37709bbacabe0849e0af00c48b6231d2a64d623ddc560a43330f3da7a` (760870 bytes)
- Original checkpoint receipt SHA256: `46f7adcced0acbd436bda452568ae4a6363f781bb0346c58289294c9a3e909b0` (13070 bytes)
- Fresh single-file RED SHA256: `c744319292f5bb38b55e1f920289df487216738a8874032a5e5a8238285e27cf` (1803 bytes)
- Fresh full aggregate TAP SHA256: `550fa93a8755ad9206429615e739a68c7afe4a88e3408b9330ab1eca45253cb2` (770530 bytes)

Original files and byte-for-byte preserved copies are unchanged. Before/after verification pinned all 1,154 readable baseline source blobs with the one explicitly changed test, all 441 frontend files, all 157 test/fixture files and the entire non-environment source inventory. The existing 23 installed packages match lock versions, integrity/resolved metadata and package dependency metadata. All 601 physical dependency files/symlinks retained the same inventory SHA256 `acf7deddf517cca7bd50a8af9dce50f2dbc71f95dec928f7a343d049d628a99c`. Package SHA256 remains `4a1662bb56bec1654cfa36840178c451ebd81eb4451b5480c2dcb868ab1cf9dd`; lock SHA256 remains `970037fc141010c84a78066f894f1589de7883794401328462db975fafe5c0ac`.

The full run tested the repaired test and unchanged production bytes. This documentation was added after that run and records its result; it is not represented as a tested production change. Candidate manifest, exact two-file diff/payload, source/dependency freeze receipts, negative controls and fresh TAP evidence accompany the repair for independent review before any compare-and-swap publication.

## Limits

These are finite offline desktop Node, synthetic transport and custom-renderer checks. Existing development-runtime/module-type/lifecycle warnings and deliberately rejected synthetic logs remain visible. Seven original PNG assets remain missing, and two environment-example byte pins are inherited without rereading their contents. Registry tarballs were not downloaded or independently rehashed. No browser/mobile testing, native database/backend rerun, real provider, service, deployment, CI, Git command, commit or push was performed. This passing aggregate does not establish live or browser readiness.
