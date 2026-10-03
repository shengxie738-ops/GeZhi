# 102V12 backend repair spec and implementation plan

## Goal and constraints
Repair the user-approved authentication, assessment-integrity and activity-ingestion defects without replacing the existing education product. Work on 102V12 only; do not touch Gitea/RAGFlow, restored databases, execution-isolation files, or frontend. Parent coordinates isolated execution, chat, and broader class analytics work. No real provider calls or credentials in tests.

## Architecture and policies
- Keep existing FastAPI paths and response wrappers. Derive identity from authenticated tokens, reject cross-user access, require teachers for teaching writes.
- Teacher signup is closed by default. An operator must provision approved teacher accounts; freeform teacher/class IDs grant no privilege.
- Trusted `TEACHER_STUDENT_ASSIGNMENTS` JSON maps teacher usernames to explicit student usernames. No assignment means no student access. This is a fail-closed deployment roster until a dedicated enrollment UI exists; self-editable class_name is not an authorization source.
- Teachers own newly created homework/exams. Legacy unowned content requires explicit operator assignment; never silently claim another teacher's content.
- Students see published assessments only and never standard answers, explanations or private test cases. Explicit sample fields remain visible.
- Exam start is an idempotent resume keyed by exam and authenticated student; client attempt IDs cannot redirect writes. Deadline is earliest exam end or personal duration limit. Saved answers freeze at deadline; late finalization grades saved work only. Submission retry returns the stored outcome without duplicating mistakes/events. Finalized attempts reject answer writes; judges check ownership and submission state.
- Internal activity ingestion requires a configured matching shared token and constructs occurred_at once. Empty token configuration disables this HTTP route; in-process events continue separately.

## Tasks and test plan
1. Write failing actual-router HTTP regression tests with an isolated SQLite database and patched side-effect publishers. Prove missing authentication and private read/write denial; no external provider calls.
2. Implement shared roster helper, teacher signup gate, agent write guard, homework teacher/content ownership and student self identity. Test anonymous, invalid token, student-other, teacher-other-class, teacher-other-content, and legitimate own-class access.
3. Test then repair evaluator ownership and immutable final submission.
4. Test then repair exam answer redaction on list/detail, missing/draft/future/closed exam rejection, resume preservation, immutable finalization and score/mistake idempotency, late saved-answer finalization, judge owner/state checks. Use synthetic data only.
5. Test then repair activity token validation and duplicate timestamp argument. Verify authorized dispatch and default-off behavior.
6. Run focused integration suite and existing offline subset; compile touched modules; report compatibility changes and limitations. No commits or staging.

## Review focus
- Empty, malformed, or self-asserted teacher rosters must never broaden access
- Teacher content IDs and client supplied student/attempt IDs must not replace another owner's records
- All student-facing exam list/detail paths must redact nested standard answers and private test values
- Repeated final submit and reconnect start must preserve authoritative results, timestamps and mistakes
- Invalid timestamps and offline/late requests must not silently extend examination windows

## Implementation outcome
Backend-owned focused regression suite: 34 passed; existing safe offline subset: 31 passed. Tests use actual routers with synthetic SQLite records. MySQL multi-session concurrency and full-stack/browser checks are coordinated by the runtime QA worker. Sibling workers own chat/agents/evaluator, wider teacher analytics/review scope, and code execution. Additional bounded integrity repairs: targeted resource/dashboard visibility, immutable mistake identity and self-reported mastery evidence, honest AI unavailability, actual roster-size aggregates. Deployment requires reviewed teacher accounts, explicit trusted roster/agent-writer configuration and verified ownership assignment for legacy records; no production backfill is automatic.
