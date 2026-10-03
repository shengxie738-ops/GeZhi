# Frontend integrity repair specification

Scope: existing homework/exam delivery, session teardown, teacher queue/dashboard/course honesty, agent persistence and chat sanitizer integration. Preserve API contracts; no Gitea/RAGFlow or new course subsystem.

Acceptance: failed writes remain failures; production cannot opt into mock receipts through browser storage; per-exam attempts restore server answers and autosave with visible acknowledgement/errors; unsupported code/attendance/course writes are visibly unavailable; empty review queues stay empty; logout/401 removes token and user state; agent mutations apply only after acknowledged persistence; every untrusted chat sink uses central fail-closed sanitizer.

Test plan: Node behavior tests with controlled fetch responses (401/403/404/409/500/network), actual Vue setup where feasible, serialized/debounced save and exam-switch tests, queue race tests, session teardown tests, agent rollback tests; offline full suite with excluded known integration failures recorded separately. No production credentials, external services or restored database writes. Parent performs independent final review.
