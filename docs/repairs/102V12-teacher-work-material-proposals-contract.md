# Teacher Work lesson_outline@1 proposal contract — frozen v1

Base: `d7f1a293ad5b1a434cf6914a13fedc370bf9bd8a`, branch102V12. This stage adds exactly one server-owned Skill. No frontend changes, app.main startup, browser/mobile tests, live AI, Gitea/RAGFlow, production enablement or deployment. All endpoints below start with `/api/teacher/work` and require current signed teacher identity.

## Source selection and client behavior

Existing chat history wire/fixtures stay unchanged. The UI may offer a persisted `role=assistant` message with nonnull run_id and send its message_id explicitly. This is a selection affordance, not eligibility proof. Admission resolves it server-side and requires exact current owner/task, a completed chat run and its classified unique completion message, and matching current input_revision. No separate eligibility endpoint or client parsing of displayed prose is added. SOURCE_MESSAGE_INELIGIBLE409 means the chosen owned reply fails those checks; a foreign/missing message is NOT_FOUND404.

Generate only admits a run and returns confirmed run facts. The client polls its GET run, then GET proposal; an admission response never contains candidate lesson/slides. Completion changes no local or saved draft. Preview is escaped/read-only. Explicit adoption copies a candidate into the local editable draft and marks it dirty; replacing dirty edits requires a separate visible choice. No automatic save/approval/export or adoption endpoint exists.

## Routes and envelopes

Every success is HTTP200 `{code:200,message:"ok",data:<exact DTO>}` with Cache-Control:no-store. Controlled errors use their HTTP status as code, uppercase message and data=null. Only COMMIT_OUTCOME_UNKNOWN with an actual unconfirmed run locator may use exactly `data:{run_id:<UUID>}`; this is a lookup locator, not admission/completion proof. All generic/unclassified failures are503 MATERIAL_PROPOSAL_STATE_UNAVAILABLE with data=null. Request and full response envelopes are at most262144 UTF-8 bytes. UUIDs are canonical lowercase hyphenated strings. Revision values are strict integers>=1 (outline revisions in existing save may be0). Digests are lowercase64-character SHA256. omitted_context is a nonnull strictboolean. deadline/created_at are nonnull UTC RFC3339 strings emitted with Z, optionally six fractional digits; cancelled_at is nullable. error_code is nullable or a controlled string matching [A-Z][A-Z0-9_]{0,63}. Unknown commit results are503 COMMIT_OUTCOME_UNKNOWN, with no redispatch/recovery on GET or exact replay.

- GET `/material-proposals/capabilities`.
- POST `/tasks/{task_id}/material-proposals`, required Idempotency-Key. Body exactly `{skill_ref:"lesson_outline@1",input_revision:<positive integer>,expected_revision:<positive integer>,source_message_id:<UUID>}`. No other caller authority/model/URL/key/code/plugin fields.
- GET `/tasks/{task_id}/material-proposals/runs`: exactly `{task_id:<UUID>,runs:<ProposalRun array>}`,0..20 owned task runs, no pagination/query parameters. Ordered by persisted input record created_at descending, then run_id descending. Every receipt=null. Corrupt/overflow stored history refuses instead of silently hiding runs. Read-only discovery on fresh reopen; no dispatch/lease settlement.
- GET `/tasks/{task_id}/material-proposals/runs/{run_id}`.
- GET `/tasks/{task_id}/material-proposals/runs/{run_id}/proposal`.
- POST `/tasks/{task_id}/material-proposals/runs/{run_id}/cancel`, body exactly `{}`; no idempotency key required. Repeated cancel returns current terminal facts. COMPLETE/FAILED are preserved.

### Capabilities DTO

Exactly `skill_ref,generate,read,cancel,provider_configured,external_provider_verified,reasons,limits`.
skill_ref is always lesson_outline@1; all operation/configured fields are strict booleans; external_provider_verified is alwaysfalse in this stage. reasons has exactly the false operation fields among generate/read/cancel; values are one of `private_material_proposals_disabled`, `proposal_schema_unavailable`, `materials_unavailable`, `proposal_runtime_unavailable`, `provider_unconfigured`. provider_configured is factual configuration readiness, not an operation gate or external acceptance certificate, and has no reasons entry.

limits has exactly these fixed integer fields: `max_context_characters:24000,max_content_utf8_bytes:131072,max_envelope_utf8_bytes:262144,max_retained_runs_per_task:20,max_provider_calls:1,max_attempts:1,max_timeout_seconds:90,max_output_tokens:8192`. Actual provider timeout/tokens are also capped by the configured positive AI_LESSON_PREP values and remaining absolute deadline. Local instance capacity is shared with chat, capped by min(TEACHER_WORK_MAX_ACTIVE_RUNS,4); saturation returns INSTANCE_BUSY429. No new client-selected provider configuration.

Read/cancel require default-off TEACHER_WORK_PRIVATE_MATERIAL_PROPOSALS_ENABLED, private-task admission, exact core v3 and proposal-extension schema. Generate additionally requires manual materials enabled, configured source fingerprints, fixed configured provider and available runtime. Existing production/offering gates remain unverified/closed.

### Run DTO

Exactly `run_id,task_id,kind,skill_ref,input_revision,source_message_id,input_digest,source_digest,stage,attempt,provider_call_count,deadline,cancelled_at,error_code,omitted_context,proposal_available,receipt`.
kind=outline; skill_ref=lesson_outline@1; attempt=1; provider_call_count is0 or1. stage is PENDING/OUTLINE_RUNNING/COMPLETE/FAILED/CANCELLED. cancelled_at and error_code are nullable. omitted_context is a strict boolean frozen at admission. proposal_available istrue only for confirmed COMPLETE with its exact result record. receipt is `{operation:"generate",replayed:<boolean>}` on POST generate, otherwise null. Exact-key replay observes the current persisted run without allocating a slot or dispatching. Changed body with the same key is IDEMPOTENCY_CONFLICT409, including source_message_id or expected_revision changes.

### Proposal-read DTO

Exactly `task_id,run_id,proposal,freshness`. proposal is null until a confirmed COMPLETE result exists; otherwise it has exactly `skill_ref,input_revision,source_message_id,input_digest,source_digest,omitted_context,lesson,slides,created_at`. lesson/slides use the existing strict LessonSnapshot/SlideSnapshot wire. citations/evidence_refs are empty arrays; every source_note is an empty string. There are no evidence/source snapshots or invented courseware claims. Duration and slide count exactly match the saved task metadata frozen at admission. Full candidate content follows the existing FrozenPackageContent canonical128KiB bound, including empty source_snapshots. Before COMPLETE, the current candidate must additionally pass the actual existing manual-save serialization and65535-byte draft bound, including receipt/origin overhead; oversized output becomes FAILED with error_code=PROPOSAL_DRAFT_TOO_LARGE, without truncation or material writes.

freshness is exactly `{adoptable:<boolean>,reason:<nullable controlled string>}`. reason=null iff adoptable=true; otherwise one of PROPOSAL_NOT_READY/STALE_INPUT_REVISION/SOURCE_CHANGED/SOURCE_UNAVAILABLE/SOURCE_MESSAGE_INELIGIBLE. This is a read-only current observation, not durable adoption authorization. Current unknown/unavailable source observation never yields adoptable=true. Stale completed results remain viewable to their owner. No GET changes state or settles a lease.

## Explicit materials save and immutable lineage

The existing POST materials body gains only optional `origin_proposal_run_id:<UUID|null>`; omission/null retains the old manual request digest and behavior. The materials response wire stays unchanged. A provided origin is resolved under the same durable owner/task locks, must be a confirmed owned COMPLETE proposal and fresh against its frozen original input/source/message, and allows teacher edits to lesson/slides. It atomically appends immutable proposal→new OutlineSnapshot lineage with the existing save. Changed/stale origin refuses before writes; exact save replay checks the existing exact lineage and does not re-adopt or create duplicates. No task revisions change until this explicit existing save; that save keeps its existing revision behavior. Saved manual OutlineSnapshot.skill_versions stays[]; approvals/exporters retain their exact manual semantics.

The original draft remains MySQL TEXT65535 UTF-8 bytes. Completion reuses the actual manual-save preparation/serialization, including a bounded reserved receipt key and origin overhead, to reject any candidate that cannot enter the current intended save workflow. It reports PROPOSAL_DRAFT_TOO_LARGE without truncation. A later source/input/storage change can still make an explicit save fail; adoption revalidates instead of treating past freshness as authority. Existing PRIVATE_DRAFT_TOO_LARGE422 and65535/65536 boundary semantics remain unchanged.

## Limits, records and finite execution

Context is a frozen saved task brief including duration/slide count/requirements, source fingerprints and a chronological transcript ending at the chosen reply. Whole-message truncation removes only older messages and reports omitted_context; selected reply must fit. Canonical context JSON is at most24000 characters; no courseware text is read. The provider receives bounded complete_raw through the fixed LessonPrepWorkAI path, once, no repair/retry. Duplicate JSON keys/nonfinite numbers/extra fields/invented evidence, XML-unsafe or exporter-density-invalid candidate text refuse. Combined content131072 bytes and full envelopes262144 bytes are enforced before persistence/commit.

One explicit fresh proposal extension migration adds `teacher_work_material_proposal_records` with JSON payload, owner/task/run identity, typed deterministic input/result keys, typed outline lineage and physical PK/unique/FK/CHECKs. It writes an independent `teacher_work_material_proposals` component completion receipt only after exact physical verification; core teacher_work v3 ledger/hash/13 tables stay unchanged. Existing/partial/unledgered target structures and unsafe identity/session/temporary resolution refuse. It is not startup migration or DDL rollback/resume. Official record writes are INSERT-only under retained InnoDB account/owner/task locks; reads request exact identity and refuse duplicates. Direct administrative SQL is outside append-only certification.

Per-task retained outline runs cap20 is checked before new admission. Absolute deadline <=90 seconds is saved once. Call count/token is charged and committed before provider await; no SQL Session/checked-out connection crosses await. Cancellation preserves unsettled call/lease until observed transport termination. Timeout/late result cannot publish. Unknown admission/reservation/completion never authorizes another invocation; no generic restart/recovery dispatcher is introduced.

## Controlled errors

The new proposal namespace normalizes internal/unclassified errors to503 MATERIAL_PROPOSAL_STATE_UNAVAILABLE. Its complete public mapping is:

| HTTP | message |
|---|---|
|401|INVALID_CURRENT_IDENTITY|
|403|CURRENT_TEACHER_REQUIRED, CURRENT_AUTHORITY_DENIED|
|404|NOT_FOUND|
|413|REQUEST_BODY_TOO_LARGE|
|422|INVALID_MATERIAL_PROPOSAL_REQUEST, INVALID_MATERIAL_PROPOSAL_CANCEL_REQUEST, PROPOSAL_CONTEXT_TOO_LARGE|
|409|IDEMPOTENCY_CONFLICT, REVISION_CONFLICT, STALE_INPUT_REVISION, SOURCE_MESSAGE_INELIGIBLE, SOURCE_CHANGED, OWNER_RUN_BUSY, PROPOSAL_RUN_LIMIT, PROPOSAL_NOT_READY|
|429|INSTANCE_BUSY|
|503|PRIVATE_MATERIAL_PROPOSALS_DISABLED, TEACHER_WORK_LIVE_GATES_UNVERIFIED, TEACHER_WORK_SCHEMA_UNAVAILABLE, PROPOSAL_SCHEMA_UNAVAILABLE, PRIVATE_MATERIALS_DISABLED, MATERIAL_SOURCES_UNAVAILABLE, WORK_AI_UNAVAILABLE, PROPOSAL_RUNTIME_UNAVAILABLE, MATERIAL_PROPOSAL_STATE_UNAVAILABLE, COMMIT_OUTCOME_UNKNOWN|

All error data=null except only COMMIT_OUTCOME_UNKNOWN may carry an actual `{run_id:<UUID>}` locator. Background run error_code is independent of HTTP status and may be WORK_AI_TIMEOUT/WORK_AI_RATE_LIMITED/WORK_AI_UPSTREAM_FAILED/WORK_AI_INVALID_RESPONSE/WORK_AI_UNAVAILABLE/INVALID_MATERIAL_PROPOSAL_RESPONSE/PROPOSAL_DRAFT_TOO_LARGE/PROPOSAL_DEADLINE_EXPIRED, controlled freshness/authority failures or controlled runtime/state failures. It is never upstream/private exception prose. Existing materials-save endpoints retain their existing error mapping, including PRIVATE_DRAFT_TOO_LARGE422, plus explicit origin NOT_FOUND404/PROPOSAL_NOT_READY409/STALE_INPUT_REVISION409/SOURCE_CHANGED409/SOURCE_MESSAGE_INELIGIBLE409 and proposal gates/storage503.
