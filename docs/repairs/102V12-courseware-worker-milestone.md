# Courseware worker milestone

2026-10-07 UTC. This delivery adds a dormant binary protocol and one-shot parser worker, not an enabled teacher Work endpoint. The accepted courseware snapshot/extraction foundation is unchanged.

## Verified scope

- The fixed header and bounded response protocol reject malformed or oversized messages
- The worker compiles the exact bounded source bytes whose accepted hash was verified, rather than executing a cached bytecode file or reopening source
- Python and native diagnostics are discarded during parsing and process shutdown; terminal discard failures hard-exit after the protocol frame flush attempt
- Independent review closed the divergent-cache, diagnostic-leak, and terminal-discard failure counterexamples
- The 65-test explicit selection passed without skips. Seven earlier acceptance probes and six independent acceptance probes also passed in separate runs; these are overlapping scopes, not a combined full-suite count

Run the repository selection from `backend`:

    python -B -m unittest tests.test_courseware_docker_protocol tests.test_teacher_work_courseware_foundation tests.test_teacher_work_courseware_extract -v

Accepted implementation SHA-256 values:

- `backend/parser_worker/courseware_wire.py`: `b3559ebaeaa5c0575b03090e6fdb8d56c8dcea0e66e04ff9363551d1fe75f255`
- `backend/parser_worker/courseware_worker.py`: `b0120e9d4e998e13d48b10b2c221bf90843cf8c67a604da7772b497ab48314a6`
- `backend/tests/test_courseware_docker_protocol.py`: `e84ac8df28169b56ddd0d52ad5e84dc85a4607ceaa8566f3936dd4f9e317e43c`

## Remaining integration

The ordinary host entry refuses with `ISOLATION_UNAVAILABLE`. Tests mock kernel observations and resource calls where applicable; they do not qualify a container or prove real resource enforcement. No document endpoint, provider, courseware directory grant, configuration, database schema, frontend capability, or deployment is enabled by this milestone.

Actual image/dependency pins, container controls, host transport, bounded draining, durable lifecycle ownership, cancellation, kill/reap, and target-environment tests remain separate gates. The lifecycle candidate is not part of this delivery. Existing application extraction therefore remains unavailable until that integration is implemented and verified.
