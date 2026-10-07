# Dormant courseware parser lifecycle

2026-10-07 UTC. This adds the standalone POSIX lifecycle owner and offline tests. It does not enable document extraction or add Docker transport/application wiring.

## Ownership and recovery

The owner holds an exclusive local lock and persists bounded create/start/input intentions before allowing the corresponding operation. A reservation must use its own exact generated intent; altered, unissued, stale or cross-reservation intents are rejected. Repeated intent minting retains only the latest bounded issuance.

Container, daemon, process-start and cgroup evidence must match the recorded identity. Ambiguous creation and incomplete cleanup remain quarantined. Ledger failure prevents new work while preserving exact-owned cleanup. Restart recovery, including terminal records, requires fresh trusted acknowledgement; NOT_FOUND alone cannot release it. Sticky storage faults do not auto-reset.

Fork children close inherited descriptors without unlocking the parent's active lock. Successful parent close explicitly unlocks only after unresolved work is acknowledged. Cached and local descriptor slots are consumed before uncertain close attempts, so cleanup cannot retry recycled descriptor numbers. Retired owners cannot reconcile without their ownership lock.

## Verification

Independent review covered intent forgery/replay, inherited locks, uncertain close errors, descriptor reuse, retired-owner writes, and temporary-file/ancestor-handle cleanup. The exact final source is:

- `backend/app/services/teacher_work/courseware_parser_lifecycle.py`: SHA-256 `57b814081f37f3457c7b10dab1609820def300fd6491d7ce1845a34d5ac7bb8e`
- `backend/tests/test_courseware_parser_lifecycle.py`: SHA-256 `e69d42d0394c8aba9c58d36484cde662fcdb64251646b4f60bbbeed158d618e1`

The lifecycle selection passed 55 tests. A fresh combined run of the protocol, accepted foundation and lifecycle selections passed 120 tests in 0.736 seconds; this is not the full backend suite:

    cd backend
    python -B -m unittest tests.test_courseware_docker_protocol tests.test_teacher_work_courseware_foundation tests.test_teacher_work_courseware_extract tests.test_courseware_parser_lifecycle -q

The intentional multithreaded-fork fixture emits Python's DeprecationWarning. These tests do not establish general multithreaded-fork safety. After abnormal owner death, recovery can still wait for a child hook to run; native forks bypassing Python hooks are outside this contract.

## Still required

The supervisor must actually observe and validate the daemon/process/cgroup facts supplied as evidence, bound I/O and time, and complete kill/reap/removal. This module cannot establish those facts by itself. Real filesystem durability, target-host locks, container controls, image/dependency pins, transport cancellation and end-to-end application behaviour remain unqualified. Existing default extraction remains unavailable; no real courseware, provider, browser, database or deployment was exercised by this milestone.
