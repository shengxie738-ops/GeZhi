# Student paper reading implementation plan

> **For agentic workers:** Use superpowers:executing-plans for this authorized inline implementation.

**Goal:** Make the existing paper dialog a truthful, tool-free asynchronous request with real identity, task context and SQL receipts.

**Architecture:** Reuse Academic Reviewer instructions/completion classification and the existing admission/context/save fences. A server-owned 90-second deadline starts before task admission, including queue/model/terminal preparation; the provider receives no tools and has zero retries. Paper requests with a selected Academic Reviewer retain its fixed review prompt; other modes retain their existing execution semantics.

**Tech Stack:** Existing locked Python/FastAPI/SQLAlchemy/LangChain/httpx and shipped desktop Vue/Node tests; owned official MySQL 8.4.10 controller.

**Spec:** Parent thread confirmed engineering contract on 2026-10-06: paper consumes only authenticated task context, no graph/tools/RAG fallback/profile task; reject nonempty retrieval/diagnosis selectors before writes; 90-second total deadline, at most one provider attempt; nonempty explicit stop alone permits one saved assistant; errors/incomplete/unknown/empty/timeout never claim success; preserve cancellation/deletion/revision fences.

## Global constraints

- Work only on 102V12 based on cb2bfbc9623f692d47dd8b73c87e7882ceb57c14; no main/force/deploy/CI endpoint.
- No browser/mobile/Gitea/RAGFlow/live provider/credential or .env reads.
- Provider/source responses synthetic only at HTTP transport; actual auth and transactions in acceptance.
- New private MySQL schemas/container/volumes only; record verified cleanup and existing-service preservation.
- Push only explicit files after parent CAS confirmation.

## Review focus

- Contentless terminal chunks and absent/unknown completion metadata cannot become saved success.
- Queue/header/context delays consume the same deadline; synchronous SQL cannot be interrupted and must be documented.
- Stream-to-nonstream/empty-stream fallback must not issue a second paper provider request.
- Clear/delete/account/transport cancellation cannot resurrect an assistant or mutate another frontend session.
- Broken custom credentials and uncertain DB commit acknowledgements produce truthful failures without registry/RAG fallback.

## Task 1: backend paper request and desktop presentation

Files: modify `backend/app/api/endpoints/chat.py` and the optional save-budget callback in `backend/app/services/chat_history.py`, create focused `backend/app/services/student_paper_reading.py`; modify `frontend/js/utils/chatModes.js` and `frontend/js/api/streamChat.js` plus its existing error label in `frontend/index.html` only as demonstrated by tests. Add `backend/tests/test_student_paper_reading.py` and transport support; add `frontend/tests/studentPaperReading.test.mjs`. Update existing paper-specific harness expectations where the confirmed contract supersedes shared-graph behavior.

- [x] Add actual route/auth/SQLite plus synthetic HTTP transport tests for stop/length/content_filter/tool_calls/unknown/empty/error, no tools/extra calls, conflicts-before-write, deadlines/queue/context/cancellation and durable receipts.
- [x] Run RED against cb2bfbc: expect policy failures, not setup/import failures; retain logs/selectors/hash.
- [x] Implement fixed paper policy/deadline scope, one async invocation/stream, fail-closed completion and no profile/graph fallback. Use existing task receipt fences.
- [x] Add/run frontend RED for conflict hints, no automatic paper resubmission, failed EOF/partial status and valid receipt reconciliation; implement minimally.
- [x] Run related existing backend and desktop Node regression selections without skip/empty discovery.

## Task 2: complete application/native MySQL evidence

Files: add `backend/tests/native_student_paper_work.py`, `backend/tests/support/student_paper_full_app_scenario.py`, `backend/tests/run_student_paper_acceptance.py`; reuse frozen owned MySQL controller/real startup/auth/fixture patterns. Add result/evidence documentation under `docs/repairs/102V12-student-paper-reading*`.

- [x] Exercise real login, academic proxy, snapshot save/replay, supplied metadata dialog, history read/delete/clear, forbidden identity and stale/expired/deleted accounts.
- [x] Exercise stream/nonstream failures, timeout/queued invalidation/disconnect and commit-ack uncertainty with real SQL; isolate provider/source at transport only.
- [x] Assert no graph/RAG/code/profile request, at most one model request, no DB checkout across model awaits, no dependency overrides.
- [x] Verify exact schema drops, stopped/removed owned container and volumes, baseline services preserved; reject skip/zero tests.
- [x] Freeze sources, run necessary regression suites, obtain independent review, address material findings with RED/GREEN, record limits.
- [ ] Commit explicit files, send candidate HEAD/files/test/pins to parent, wait for current-head CAS confirmation, ordinary push and verify saved remote bytes.

## Decisions and limits

- Accept false/None/empty defaults. Reject nonempty `force_rag`, `repository_id`, `course_dataset_ids`, `is_diagnosis`, `problem_id`, `problem_title`, `user_code` in paper mode. Normal frontend payload does not send diagnosis fields.
- Model/HTTP async waits and task-lock wait are cancellable. SQLAlchemy/PyMySQL synchronous reads/commit/refresh cannot be forcibly stopped by an asyncio deadline; check the budget around them and record any committed acknowledgement truthfully. No claim of interruptible synchronous transactions.
- Do not repair unrelated visual-guide authentication, generic stream sandbox labels, diagram localhost links or unavailable plugins in this stage.
- Academic Reviewer implementation and DOI parser are reused; paper-mode stricter terminal policy does not change chat-mode Reviewer behavior.
