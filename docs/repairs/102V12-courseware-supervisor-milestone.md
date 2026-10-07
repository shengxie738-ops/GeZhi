# Dormant supervisor / transport candidate

Base: `d36630a6d53f61a695e5f921e240244dd137e1d0`. Uncommitted candidate;
no application wiring, image build, Docker execution or deployment authorization.

## Interface and operation plan (written before implementation)

`CoursewareSupervisor(owner, transport, *, qualifier=None, enabled=False)` is
a single-use `TrustedProcessRunner` and explicit context manager. Construction
does not probe or launch. `verify_support(limits)` synchronously reserves before
calling the trusted native qualifier or transport. A successful verification
retains the reservation until `run`, `cancel` / `close`, or context exit. Failed
verification releases only unused reservations. Repeated calls cannot reuse it.

`NativeQualifier.qualify(transport, limits, deadline, cancellation)` must return
current, exact `QualificationEvidence` for the fixed daemon, reviewed image,
accepted source hashes, locked wheels and these limits. This is a trusted native
integration interface, not a request DTO, flag, or certificate supplied by users.
There is no native qualifier in this delivery. A missing qualifier is unavailable.

`DockerTransport` owns bounded fixed-local Unix-socket Engine control requests,
the fixed Docker CLI attach process, host identity observations, and exact cleanup.
Control body, HTTP headers, stdout, and discarded stderr have separate caps.
Document bytes travel only through the attached CLI's stdin. No shell, environment
inheritance, paths from request data, bind mounts, prefix deletion or global prune.

Order: reserve -> qualify / reobserve daemon -> mint and persist intent -> durable
create authorization -> create -> record full ID -> exact ownership inspection ->
durable start authorization -> attach/start with stdin withheld -> capture actual
PID/start ticks and cgroup identity -> durable input authorization -> bounded
exchange -> exit/stop/wait, cgroup/process observations, exact removal and 404 ->
complete durable cleanup receipt -> result. Deadline starts before create. Cleanup
has a separate bounded budget and ignores job cancellation so cancellation cannot
disable cleanup. Unknown create remains quarantined; NOT_FOUND never releases it.

## TDD slices

- [x] Transport: fragmented control HTTP, bounded pipe I/O, fixed creation recipe,
  independent caps, short writes, cancellation, timeout, process reaping.
- [x] Supervisor: real temporary lifecycle owner, admission order, single use,
  unused close, races, delayed create, ownership mismatch, output errors, ledger
  faults, incomplete cleanup and restart quarantine.
- [x] Exact limited verification; unchanged accepted source hashes; complete diff
  and reconstructable file bundle. No commit or push.

## Native qualification actions still required

Reviewed image and official wheel digest validation; actual image bootstrap,
environment, namespace and seccomp checks; enforcement/negative resource probes;
killability independent of a stalled daemon; cgroup observation through runtime
teardown; native ledger locks and crash durability; fenced late-create recovery.
Offline doubles establish none of these. No production ready claim is permitted.

## Delivered behavior and verification

Five new files only: the two service modules, their two selected test modules,
and this document. Accepted wire, worker, lifecycle and pure parser are unchanged.
Original `/workspace/GeZhi` remains on `work` at
`1718a66b5495ff75e0959b051552bfb7a2e997ae`. Normal authenticated Git fetch and
`git worktree add --detach` created
`/workspace/GeZhi-courseware-supervisor-d36630a` at the exact base above.

The initial 25-test red run failed because the implementations were absent.
Subsequent regressions were reproduced before fixes: invalid limits leaking an
unused reservation; shutdown cancellation missed after receipt commit; missing
retry of same-owner durable acknowledgment; CLI reap error preventing worker
cleanup; invalid exchange arguments leaving the CLI unreaped; deletion without
fresh ownership/host exit evidence; and cancellation of a verified unused job.
The initial multi-line `with` syntax mistake was corrected before evaluating
those regressions. A red pipe fixture initially left its producer waiting; that
test process was interrupted and test-only unconditional disposal was added.
No real Docker process or container was involved in these runs.

Run from the isolated worktree's `backend` with an existing Python:

```sh
TMPDIR=/workspace/gezhi-supervisor-offline-tmp python3 -B -W error -m unittest \
  tests.test_courseware_docker_transport tests.test_courseware_supervisor -v
```

The limited selection contains 52 tests. The final result and exact hashes of all
five files are supplied with the delivery bundle's verification log and manifest.
This count does not include or repeat the earlier 120-test milestone selection.
No packages were installed, no real signals were sent, and no socket/Engine/CLI
operation, parser execution, application, provider or other service was exercised.

Control response bodies are capped at 64 KiB; HTTP headers and discarded stderr
are independently capped at 8 KiB. Framing has its own finite overhead budget.
Stdout uses `max(43, 11 + 6 * max_pages + max_output_bytes)`; input uses the
existing bounded wire codec and is never a command argument or mount. The fixed
CLI process is spawned with `shell=False`, `close_fds=True`, a literal local
socket and a clean environment with no credential/config inheritance. Its pipes
are multiplexed with finite reads/writes and a monotonic deadline, and its owned
process is killed/reaped on all exchange exits, including argument rejection.

The create recipe fixes network none, read-only root, UID/GID 65532, capability
drop ALL, no-new-privileges, pids=1, CPU quota/period and memory=memory-swap. It
uses `/usr/bin/env -i ... python -I -B` so the worker is PID 1 with its exact
environment. Inspect readback, actual host capabilities/seccomp/namespaces,
cgroup limits, process start ticks and a second start-tick observation precede
input. A pinned pidfd with a signal-0 permission check, cgroup directory and
events handles stay associated with the exact identity. All such observations
and signals are doubles in this delivery, not qualified native observations.

Cleanup has a three-second separate budget, including one second reserved for
the pinned signal path; owned CLI wait is separately capped at one second.
Daemon failure triggers an exact pidfd SIGKILL attempt and fresh process/cgroup
observations. This attempt is not a cleanup certificate. CLI, wait, exit, stopped,
deletion, exact 404, original process disappearance and pinned cgroup emptiness
are independent facts. Missing facts reject success and keep admission closed.
Handles remain owned while cleanup is incomplete. Uncertain close consumes each
descriptor slot once and still attempts the other owned slots.

## Deliberate remaining boundaries

- No `NativeQualifier` implementation, approved image, Dockerfile or official
  wheel lock is supplied. A returned boolean is rejected; a dataclass's shape or
  matching hashes are also not proof of qualification. Only separately reviewed
  trusted native code may issue evidence after actual current-host checks.
- No application factory/caller or configuration flag is wired. Existing default
  extraction still refuses. Explicit `with` / `close` owns successful unused
  verification; cancel releases only an unused job. Active work first cleans up.
- Unknown/partial/late create is not looked up by prefix, reset, retried or cleared
  by absence. Fenced late-create recovery remains unimplemented. Ownership
  mismatch prevents automatic mutation and keeps the reservation quarantined.
- A job failing before host identity capture cannot produce complete cgroup
  evidence here. Exact-owned stop/wait/removal is still attempted, but no complete
  receipt is invented. The reservation remains quarantined.
- A removed/unreadable `cgroup.events` handle is not treated as empty. Hosts where
  this observation cannot survive teardown are unsupported until a separately
  reviewed native evidence mechanism exists. Process/cgroup observation rights,
  pidfd signal rights, namespace mapping, resource enforcement, hard syscall
  behavior and actual kill/reap must all be qualified in the target runtime.
- Incomplete cleanup raises sanitized unavailability while retaining ownership;
  it does not assert that a worker died. The candidate is therefore not accepted
  as satisfying the complete native `TrustedProcessRunner` contract. Same-owner
  retry may acknowledge an already complete receipt after a ledger failure;
  sticky faults still prohibit new work. Restart requires fresh native evidence.
- No real-document, native filesystem durability, image/host isolation, service,
  full suite, browser/mobile, provider, deployment, commit or push validation was
  performed. Independent review of these exact uncommitted bytes is still due.

## Rebuildable delivery

The external delivery directory contains `changes.patch` (all five full additions),
`new-files.zip` (original repository-relative paths), `manifest.json` (full base,
SHA-256 and byte length for each file), and `verification.txt`. Apply the patch in
a clean checkout of the exact base, or extract the five ZIP entries there. The
patch was reverse-checkable against this candidate without staging or committing.

## Offline review revision 1 (2026-10-07)

The preceding sections record the original delivery. Independent offline review
reproduced four P2 availability/retry defects in those original bytes. This
revision changes only the same five product files, preserving the original
candidate and review evidence. It remains dormant and unqualified. There is no
application wiring, runtime activation, commit, push, Library upload or external
publication in this revision.

Repairs:

1. Intent minting no longer sets a speculative supervisor acceptance flag. Before
   any dispatched create or returned ID, cleanup calls the public exact-owner
   `release_unused` transition. Only its explicit
   `INTENT_REQUIRES_RECONCILIATION` rejection selects `record_create_rejected`.
   This distinguishes an unused cancellation from an accepted in-memory/durable
   obligation without reading or changing private owner state. Persistence
   faults and ambiguous dispatched creates cannot become unused releases.
2. Native `start` retains the exact ownership and fixed CLI process for readiness
   observation. `capture_identity` waits for an actual matching running PID on
   the original absolute job deadline, checking cancellation and ownership on
   every readback. Terminal/error/paused/restarting facts or a CLI exit refuse
   readiness. No request bytes are sent before the actual kernel identity is
   captured and durably authorized. Native capture itself is unchanged after
   this readiness barrier.
3. Worker kill/wait/exit observations still run when CLI reaping fails, but DELETE
   waits for successful reaping. A same-owner retry reobserves the still-existing
   exact container and its pinned exit proof rather than inferring old facts
   from an initial 404. The original test permitting removal on reap failure was
   corrected; a two-stage regression verifies deferred removal and retry.
4. Pinned exit/cgroup proof that arrives during emergency termination now returns
   to removal within the same absolute cleanup deadline. The emergency wait
   leaves a 0.2-second final control window; cleanup freshly checks the daemon,
   exact ownership and stopped state before DELETE and exact 404. Missing proof,
   changed ownership, exhausted budget or failed confirmation keeps a partial
   receipt and quarantine.

The exact original 52 tests and five fault-characterization probes were rerun
unchanged with fail-closed socket, Popen, pidfd signal and host-kernel fences.
They passed as historical reproduction evidence, not as repaired acceptance.
The revised selection contains those 52 test cases (one corrected expectation)
plus 13 new regressions. Its red run against original product bytes had eight
failures and two errors, then the repaired 65-test selection passed. Independent
acceptance is recorded separately in the revision delivery evidence; it does
not overwrite or reinterpret the original characterizations.

Accepted extractor, lifecycle and wire dependency bytes are rehashed unchanged.
The accepted worker was not materialized, modified or executed in this offline
review tree. No accepted interface was changed. All IO and process behavior
outside temporary ledgers/local finite pipes/devnull descriptors is synthetic.
No real socket, Engine, CLI, signal, Docker, native resource-limit execution,
parser/document, service/provider, configuration, `.env`, or full-suite access was
used. No new native qualification is claimed.

The remaining NativeQualifier, image/wheel lock, native enforcement/durability,
observation survival and fenced late-create gates remain exactly open. A failure
before host identity capture still cannot produce a complete cgroup receipt.
An initial 404 still cannot invent wait/exit/removal evidence. If DELETE succeeds
but its subsequent exact 404 observation cannot be established, this transport
still returns a partial receipt rather than manufacturing same-owner completion.
Independent rereview of the five frozen revised files is required before calling
this dormant supervisor milestone accepted; production extraction remains
unavailable/default-off regardless of that offline rereview.

Final independent acceptance contains 22 selected cases. The unchanged harness
against the preserved original backend gives seven failures and one error; the
revised backend passes all 22. The final combined revised focused and independent
selection passes 87 selected cases. Counts are test methods; subtests and
historical repetitions are not presented as additional unique coverage. The
independent supervisor two-stage case verifies first-stage admission retention,
worker termination without DELETE, and second-stage same-owner durable release
only after successful CLI reap, fresh exact ownership/exit proof, DELETE and exact 404.
