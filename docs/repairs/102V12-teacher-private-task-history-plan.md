# Teacher private task history implementation

Base: `3bc5f0bf768bffe8e1df0628cb9992cf83215748`.
Execution: this Cloud worktree only; local commit and parent CAS handoff, no push.

## Approved boundary

GET `/api/teacher/work/tasks?limit=20&before=<canonical UUID>` returns only
`task_id`, `title`, `created_at`, `updated_at`, plus `has_more` and `next_before`.
Limit is 1–50; keyset order is immutable `(created_at DESC, task_id DESC)`.
The real current teacher, private gate, canonical owner namespace and physical
MySQL read transaction are required. Foreign and missing cursor anchors both
return 404. No owner lease creation, business DML, provider call or migration.
Summaries grant no material/chat/export authority.

The desktop rail loads bounded actor-scoped history. Task clicks and URL changes
share one switch guard: active or uncertain operations retain their original
body/key; dirty edits require explicit abandonment. Confirmation rechecks
identity, view, current task, revisions and draft/edit versions. Abandonment
removes only the current task's local material draft; other cached drafts stay.
Published proposal recovery hook/component semantics remain unchanged.

## Tasks

- [x] Pin old workspace and create a clean isolated worktree at the exact remote base.
- [x] RED→GREEN: strict summary DTO, bounded namespace/keyset SQL, route and real
  application/auth/MySQL list scenario (no dependency overrides or permission mocks).
- [x] RED→GREEN: strict frontend API, actor-scoped list lifecycle, shared switch
  guard, narrow material discard, desktop rail/dialog and main/index wiring.
- [x] Freeze explicit files; independent branch review; repair material findings
  with RED→GREEN; run relevant backend/frontend and owned MySQL acceptance.
- [x] Attempt the complete desktop runner without changing locked dependencies
  or network sources. Preserve any dependency failure for dot.
- [x] Verify protected proposal blobs and original workspace pins; document
  source hashes, commands/counts/exit codes/cleanup; commit explicit files locally.

## Interfaces and review focus

Backend summary DTO is consumed by the frontend strict decoder. List state is
actor/view-scoped, separately from task selection reset. Switch confirmation
consumes task/edit/material epochs and existing busy/unknown run facts. The
material discard API must reject frozen writes and clear only its current cache.
Review late success/catch/finally, popstate removal, dialog-time edits/identity
changes, equal timestamp paging, absent/inconsistent owner leases, foreign
anchors and list SQL with no DML. Provider fixtures remain explicitly synthetic;
live AI, browser/mobile, CI, real credentials and deployment are outside scope.

## Execution ledger

Original workspace and protected proposal blobs: pins are in
`/tmp/gezhi-task-history-ttfgzlas/worktree-baseline.json`; original files untouched.
Backend DTO RED: missing new summary DTO; GREEN: 7 passed. Full-app list RED:
unregistered collection GET; GREEN: 1 scenario / 36 HTTP exchanges, no list DML,
commit or provider calls, owned database/container/volume cleanup confirmed.
Frontend history/guard RED: 15 failed missing API/state/actions; GREEN: 15 passed.
Additional cache preservation and original uncertain chat replay checks: 17 passed.

Ruling: old task-race tests treated navigation as an automatic write abort.
Approved guard now blocks those navigation attempts. Their late-response fencing
cases explicitly simulate an external scope invalidation, while also asserting
that normal navigation does not abort the original operation. This preserves
the lower hook boundary checks and adds the required user-facing protection.

Complete desktop runner currently fails before collection because locked
`@babel/parser` is absent. Keep that failure and hand it to dot; no dependency,
lockfile, registry or DNS changes. CI was not queried.

Final: 24 new history/guard tests; 1130 related frontend tests; 326 ordinary
backend tests (30 subtests separately); 1 history full-app scenario/39 exchanges;
10 original full-app scenarios/385 exchanges. Zero failures/skips in those
selected scopes. Both native source manifests match, cleanup confirmed.
Independent review findings fixed in one RED→GREEN pass, followed by related
regression. New-create entry and confirmed-result navigation share the guard;
unknown working-save facts survive edits until authoritative reconciliation.
Artifact inert omission regraded Important because modal background controls
remained keyboard-interactive; fixed with a rendered assertion. No deferred
findings. Publication remains root's CAS handoff after this local commit.
