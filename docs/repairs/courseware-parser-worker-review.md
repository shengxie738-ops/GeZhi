# Dormant parser worker: bounded review remediation

Date: 2026-10-07. Scope: the existing detached wire/worker candidate only. The application remains unwired and default extraction remains unavailable. No Docker or deployment qualification is claimed.

## Corrected review findings

1. Source integrity: the bridge hashes its bounded source read and then compiles/executes those same bytes. Module metadata and registration remain available to dataclasses. It no longer calls the source loader's execution method, which could use a timestamp-valid divergent `.pyc` even with `-B`, or reopen changed source. The foundation parser is unchanged, SHA-256 `60d12bdda6eeb0c3fb26a9d83748b358a1b3feff31f63257f63952275225db8f`.
2. Diagnostic isolation: parser imports/execution run with Python stdout/stderr and fd 1/2 directed to `/dev/null`, without an in-memory capture buffer. Setup failure prevents parsing. Existing Python buffers are flushed while still discarded, and descriptors are restored for the framed result. After the result is flushed, the real one-shot entrypoint permanently discards output through interpreter shutdown, including delayed native buffers and exit hooks. If the terminal open or either fd redirect fails, the entrypoint hard-exits with status 1 after the frame flush, bypassing interpreter/stdio teardown so registered hooks or delayed buffers cannot leak diagnostics onto surviving pipes. The future host must still enforce capped output/stderr draining and fail closed.

These are worker-specific process-global operations for a single-threaded one-shot runtime, not utilities for application threads. Real bootstrap observations, limit establishment/readback, parser hash verification, and sanitized error framing remain in place. No request or environment bypass is added.

## Focused verification

Run from `backend`:

    python -B -m unittest tests.test_courseware_docker_protocol.ProtocolTests tests.test_teacher_work_courseware_foundation tests.test_teacher_work_courseware_extract -v
    python -B -m unittest tests.test_courseware_docker_protocol.WorkerReviewRegressionTests -v

The unchanged baseline selection is 56 tests: 15 protocol/bootstrap plus 41 accepted foundation tests. The separate review regression class adds 9 tests: divergent cache, source-path replacement after hashing, changed source hash rejection, real malformed-PDF warning suppression, Python diagnostics on success/failure, native/buffered diagnostics with descriptor restoration, discard setup failure, delayed native/exit-hook diagnostics in a fresh owned interpreter, and hard-exit safety for terminal open/fd-1/fd-2 redirect failures. Every hard-exit case runs only in a bounded test subprocess, never the test runner.

Both original defects were reproduced before edits. Independent rereview then exposed a residual terminal-discard failure path: a nonzero return still ran leaking exit hooks. Its three fault positions were reproduced and a new acceptance test failed before the hard-exit correction. New acceptance tests failed before their corresponding fixes. The original independent defect probes are historical reproductions, not acceptance tests. A separately saved adaptation of those probes asserts corrected behavior and preserves the original boundary checks; its author rerun is not a fresh independent review.

Tests use tiny owned fixtures. Kernel observations/resource calls are mocked where relevant; no test changes real RLIMITs, cgroups, security settings, or Docker state. The fixed subprocess script emits only bounded synthetic test data. Full-suite/native MySQL, Docker/image/dependency installation, browser/mobile, provider/model, service, CI, and deployment checks were not run.

## Remaining gates

Independent review must accept the exact frozen worker/test bytes. Actual image/dependency pins, effective container controls, host supervisor transport, cancellation, kill/reap, target-host qualification and explicit deployment authorization remain separate. This work neither changes nor accepts the lifecycle module. The earlier v2 always-deny interface was amended in the evidence bundle to describe the already-authorized fail-closed observed bootstrap accurately.
