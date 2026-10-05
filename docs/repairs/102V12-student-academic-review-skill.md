# Student Work: explicit Academic Reviewer execution

## Implemented capability

Academic Reviewer is now an explicitly selected, server-defined text-review skill,
not merely a catalog label. Installation alone never activates it. The student
selects the skill and sends a message in AI chat or the paper-reading dialog.
The frontend captures the skill and chosen model once for that submission,
including any streaming-to-nonstream transport fallback.

The backend accepts at most one `academic-review` ID. Unsupported IDs and modes
are rejected before persistence or model invocation. Selected execution uses the
authenticated owner's model settings, fixed review instructions and the existing
task-scoped context/receipt path. It bypasses the graph, tools and RAG fallback.

The review covers supplied text, metadata and available abstracts. It does not
download links or claim to have read unseen full text, experiments or references.
Other unavailable catalog entries remain clearly labeled; this is not a general
third-party plugin execution engine.

## Failure and lifecycle behavior

- Removing/uninstalling a skill, account changes and unmounting clear selection
- Incompatible frontend mode/knowledge selections are rejected visibly
- Failed/empty model output has a separate local error, not a saved-answer claim
- Selected custom-credential lookup/decryption failures cannot silently switch
  to registry credentials, including IDs that shadow registry models
- Known incomplete finish reasons, including contentless terminal stream chunks,
  prevent successful save; absent/unrecognized metadata is labeled `unknown`
- Clear/delete/disconnect/cancellation paths retain existing receipt fences
- Unselected legacy successful recovery remains authoritative: transient warnings
  do not invalidate a later nonempty successful completion with valid saved IDs

The strict credential behavior in this stage is selected-skill-only. Existing
unselected credential-helper behavior was preserved rather than silently changed.

## Verification (2026-10-05 UTC)

- Frontend: 209 related Node tests passed, zero failed/skipped/cancelled
- Backend: 25 unittest functions passed, including focused dispatch, real helper
  credential regressions and in-process FastAPI/Pydantic request/response tests
- Independent frontend/backend review findings were reproduced and repaired
- These totals overlap earlier 23/117/127 frontend results; do not add them

The backend tests execute actual schema/helpers and extracted route/streaming
response source with synthetic authentication, storage and model ports. In-process
ASGI tests verify parsing and response wiring, not the production application's
startup, real authentication verifier, SQL transactions or provider availability.

Frontend tests use shipped Vue, a synthetic renderer/transport and in-memory Web
Storage. Initial aggregate attempts exposed missing bare-Vue and Web Storage test
setup; the repository preload below supplies those fixtures without installing
packages or changing application behavior.

```sh
node --import ./frontend/tests/fixtures/studentWorkNodePreload.mjs --test --test-concurrency=1 frontend/tests/{academicAggregate,academicBoundary,academicPlugins,academicProviders,academicRepair,paperSearchFlow,paperSearchOutcome,paperWorkflow,pluginMarket,paperDrawerSelection,studentWorkSkill,workSessionLifecycle,workMutationRaces,streamChatSafety,chatModes,agentModelRouting,customModelHotSwitch,workPaperDetailPresentation}.test.mjs
python -B -m unittest discover -s backend/tests -p 'test_student_work_skill*.py' -v
```

Node 24 was used for `registerHooks`; backend checks require the project's
FastAPI/Pydantic/httpx dependencies. Existing Vue development/module-format
warnings and intentionally injected failure logs are not browser verification.

No browser, live provider, real database or production application server was
started. Teacher Work, production deployment and full-system readiness are not
part of this stage's verification claim.
