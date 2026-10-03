# 102V12 chat, agent configuration, evaluator permissions

## Authorization contract

- `/chat`, `/chat/stream`, both OpenAI-compatible completions aliases, private history/diagnosis reads and writes, uploads, agent configuration and evaluator attempts now require the shared signed bearer-token dependency. Public model and quiz-summary catalogs remain public.
- Chat replaces supplied session/thread identity with the verified token subject before persistence, graph-thread construction or custom-model credential lookup. A teacher cannot select a student's custom-model account. OpenAI-compatible requests namespace their graph threads and use the verified identity for personal retrieval/profile updates; their existing model selection behavior is unchanged.
- History/diagnosis and evaluator attempt/result reads allow the owner or an explicitly assigned teacher via `TEACHER_STUDENT_ASSIGNMENTS`. This deployment-managed roster is authoritative; profile `class_name` is not an authorization source. Missing assignment denies access.
- History creation, batch creation, deletion, clearing and personal document upload are owner-only, including for teachers. Guards execute before the existing broad error wrappers so denial remains HTTP 403 rather than a misleading 200.
- Evaluator attempt creation derives its owner from the token and rejects a conflicting supplied user ID. Submission is owner-only. Submitted answers are immutable; an identical retry returns the original summary, and changed answers return 409. This is sequential request idempotency, not a claim of database-level concurrency serialization.
- Global agent configuration writes require **both** the existing teacher role and an operator-approved username in `AGENT_CONFIG_WRITERS`, a JSON array defaulting to `[]`. Malformed/non-array values fail closed. No new admin role or self-service privilege escalation was introduced. Authenticated students can read configuration; ordinary teachers keep their own teaching features but cannot mutate global prompts/models unless explicitly approved.

## Deployment/migration

Populate the trusted roster and global writer allowlist through deployment configuration after reviewing existing accounts. For example, `AGENT_CONFIG_WRITERS='["approved_teacher_username"]'` uses an existing approved teacher account. Do not trust historical self-registered teacher accounts automatically. Existing signed tokens retain their claims until expiration; the shared authentication layer does not perform DB role/account revalidation or token revocation in this patch. Review historical teacher accounts/tokens before exposure and plan revocation separately.

Clients must send bearer authorization for formerly anonymous chat/history/agent/evaluator routes. Missing/invalid token returns 401; cross-owner or unassigned-teacher access returns 403. Evaluator clients may omit `userId`; if sent, it must match the token subject.

## Verification and boundaries

`backend/tests/test_chat_permissions_repair.py` exercises actual FastAPI routers and actual in-memory SQLite persistence, synthetic signed identities and fake AI/profile/retrieval adapters. It does not import application startup, read restored databases or contact real AI providers. Existing chat-history direct-call tests now pass explicit synthetic authorization, preserving their persistence assertions. Existing model-unavailability tests exposed a missing `httpx` import, repaired without changing fallback policy.

No Gitea/RAGFlow implementation or live integration operation was performed. The existing upload route received only an owner authorization boundary; retrieval call-site identity was corrected without modifying the retrieval services. No external credentials, real account login, production database, commit/push, OS setting or Codex Cloud was used.
