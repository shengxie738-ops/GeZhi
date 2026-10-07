# Work chat: one execution per submission

Baseline: `102V12` commit `05c23b2a20d39ac6521190d021d5988caebff5fb`.

Normal Work chat sends one POST to `/chat/stream`. It no longer automatically
repeats that submission through `/chat` after an HTTP/transport failure or an
empty stream. The current normal-chat request has no server idempotency key:
each endpoint can create a new origin/history row and invoke the model. Lost
confirmation is therefore insufficient evidence to safely invoke it again.

## What the desktop displays

- Lost response headers, HTTP 500, unreadable/non-SSE responses, an interrupted
  reader, or EOF without an authoritative completion are an unknown outcome
  when no explicit model failure is known. The assistant keeps any partial text
  and displays a separate warning. Local rows remain unconfirmed and never gain
  database IDs or a saved state without a positive receipt pair.
- The warning says the server may still be processing, asks the user to refresh
  history before deciding to resend, and warns that resending may execute twice.
  A deliberate user send remains available and is a new execution.
- Auth/router/validation HTTP 401/403/404/405/422 responses retain their known
  rejection reason. They do not trigger another endpoint request. HTTP 401
  continues to use the request wrapper's session-expired wording.
- A server model error remains a failure with its server reason. If the stream
  ends before its storage receipt, cloud saving remains unconfirmed.
- An authoritative completion and positive user/assistant receipt still control
  the saved state, including when a still-current reader subsequently disconnects
  or throws an AbortError. A bare `type: complete` marker carries no outcome or
  persistence authority; it remains unknown and cannot replace an earlier valid
  completion. Every current normal-backend completion carries `history_saved`
  and a receipt pair. Status or content cannot bypass a malformed receipt:
  a claimed positive save needs positive integer user and assistant IDs;
  a negative receipt needs a null assistant ID and a positive-or-null user ID.
  The first accepted normal terminal result is latched. Later contradictory or
  malformed envelopes cannot rewrite it. Existing
  context invalidation and concurrent history-refresh receipt deduplication remain
  in place. History is read separately; it never triggers automatic resubmission.
- Account changes, token changes, navigation and scope disposal keep their
  existing cancellation and late-result fences. Browser-side abort is not a
  guarantee that an accepted server/model operation was cancelled. Genuine
  caller abort or a stale context still prevents applying a receipt there;
  an exception's name alone does not establish that the caller aborted.

## Compatibility and scope

An older deployment without a working SSE route now reports rejection or an
unknown outcome instead of silently executing `/chat`. No pre-execution fallback
contract or idempotency protocol is introduced. Backend code, paper batch
deduplication, paper-reading behavior, capabilities, personal self-only privacy,
cache-owner boundaries, teacher coursework and homework are unchanged.

The bounded Node tests use production hooks/request/SSE code and shipped Vue
with offline fetch doubles. Synthetic acceptance counters demonstrate the
frontend's duplicate request behavior, not actual provider execution or database
duplicates. No live backend, browser, model, Docker, network, mobile or full-suite
verification is claimed.

Run the focused regression from the repository root:

```sh
node --import ./frontend/tests/fixtures/desktopShippedNodePreload.mjs --test --test-concurrency=1 --test-reporter=tap ./frontend/tests/workChatRetryTruth.test.mjs ./frontend/tests/streamChatSafety.test.mjs ./frontend/tests/workSessionLifecycle.test.mjs ./frontend/tests/workMutationRaces.test.mjs ./frontend/tests/workAuthTransition.test.mjs ./frontend/tests/studentPaperReading.test.mjs ./frontend/tests/studentWorkSkill.test.mjs
```

The previous tests that required `/chat` after ambiguous stream failure now test
the one-request boundary. Receipt, context invalidation and known model-error
checks use an authoritative completion from the original stream instead.

This single-terminal rule follows the verified normal-stream implementation in
`backend/app/api/endpoints/chat.py`: `_stream_chat_admitted` emits one invalidation
completion and returns, while `_stream_chat_events_sql` emits one completion on
its terminal branches and returns or ends. Legacy model-error/reset recovery
occurs before that completion. Paper parsing and paper deadline/error completion
semantics are outside this change.
