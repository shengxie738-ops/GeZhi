# Teacher courseware context foundation (offline, not enabled)

This candidate adds detached building blocks only. It does **not** connect selected courseware to private chat, enable a shared library, change deployment configuration, add a database schema, advertise a capability, or call an external model. Existing `PrivateChatTransactions.load` still supplies empty evidence. `MaterialSources.observe` remains fingerprint-only and unchanged.

## Files and trusted boundaries

- `backend/app/services/teacher_work/courseware_snapshot.py` captures selected immutable bytes and SHA-256 hashes. A trusted server authorization callback must freshly establish the current teacher, private task owner/namespace, run, revision, ordered selected IDs, configured source root and explicitly enabled shared-library policy. It runs before file access and after capture. A constructed dataclass or a callback that simply echoes its input is **not** a real authorization implementation; that echo exists only in synthetic tests. Default policy is deny. The source root is internal and must never be exposed in a public DTO.
- Source lookup uses the existing five-directory allowlist and casefold ID derivation, rejects symlink ancestors/files, hardlinks, ambiguous IDs, nonregular files and changing bytes, and avoids reading unselected file contents. Limits are 10 resources, 10 MiB/file, 25 MiB total, 4,096 directory entries and depth 16. The 15-second deadline is checked between filesystem calls and after reauthorization. It is **cooperative**, not a hard timeout on a blocking filesystem syscall; call only in a separately bounded executor, not on an async event loop or inside a DB transaction.
- `backend/app/services/teacher_work/courseware_extract.py` accepts exact bytes, binds the result to their SHA-256 hash and returns immutable original page/slide positions. The application entry point `extract_pages` returns `unavailable / ISOLATION_UNAVAILABLE` by default. It never falls back to parsing in-process.
- `TrustedProcessRunner` is an injection contract, **not an implemented sandbox**. A future independently reviewed implementation must prove a killable supervised worker, deny network/arbitrary file access, sanitize environment and inherited handles, prevent child-process escape, enforce wall/CPU/memory and bounded IPC limits, and terminate/reap workers before returning from cancellation/failure. A request flag, thread timeout or synthetic runner double cannot establish those properties.
- `extract_pages_untrusted` is internal worker-only. Unit tests use it with owned tiny fixtures to validate logical parser behavior. It must never be connected directly to request handling. PDF decompression or parser calls can consume resources before logical checks, so logical limits alone do not make untrusted production parsing safe.

## Supported logical parsing and limits

PDF text and PPTX text, including PPTX group shapes/table cells, are parsed from bytes without paths or URLs. Physical blank pages/slides retain their positions. Legacy `.ppt`, encryption, empty/image-only documents, corrupt documents and over-budget inputs fail without partial success; no OCR, source decryption or external link retrieval is added. Tables/group text support is not a promise to understand charts, images, speaker notes or semantic reading order.

Parser hard ceilings (callers can tighten only): 10 MiB source, 200 pages/slides, 20,000 characters/page, 200,000 total characters and 1 MiB UTF-8 result text; PPTX 2,048 ZIP entries, 16 MiB/member, 48 MiB total expanded content, 100:1 ratio, XML depth 64 and 100,000 XML elements. ZIP declarations/observed sizes, duplicate/unsafe members, entities/DTDs, UTF-16 XML and XML disguised through package content types are checked. Requested worker budgets are five seconds wall time, three seconds CPU and 256 MiB memory; **this candidate does not implement or prove their enforcement**. Aggregate multi-document text/prompt limits belong to the still-unimplemented context assembler.

All parser errors use bounded allowlisted codes, revalidated at the application return boundary even if a defective trusted runner mutates or removes an exception code. Exact-class page objects missing fields are rejected as INVALID_OUTPUT. Source snapshot errors do not echo paths or file data. Manifest repr omits captured bytes and configured root. Returned snapshots remain historical observations and confer no future dispatch authority.

## Verification

From `backend/`, using an existing Python with pypdf and python-pptx:

    python -m unittest tests.test_teacher_work_courseware_foundation tests.test_teacher_work_courseware_extract -v

The candidate's focused offline run passed **41 tests** (17 snapshot, 24 parser/boundary). It also passed `py_compile` for all four new Python files. Tests cover default denial, authorization/root substitution, revocation, symlinks/hardlinks/collisions/FIFOs, mutation during read, same-size/same-mtime hash changes, byte/scan/deadline budgets, genuine PDF/PPTX page numbering, Unicode/output limits, hostile ZIP/XML, dependency failures and fail-closed runner behavior.

The available default Python has parser dependencies but no pytest; `/usr/bin/python3` lacks pytest and parser dependencies. No packages were installed. The full existing backend suite, actual process sandbox enforcement, deployment database integration, real courseware mount, browser/mobile QA and provider connectivity were **not verified**. Synthetic runner tests do not prove isolation, hard resource limits, a worker being killed, or an actual AI call.

The inspected byte export has none of the five default courseware directories. A deployed configured mount may differ and was not inspected. A root directory existing is not evidence that selected courseware exists, is authorized or is extractable.

## Required next stages before rollout

1. Supply a real explicit deployment shared-library policy and current-account/task authorization adapter. Do not infer grants from the public catalog or filesystem presence.
2. Implement and independently verify the bounded source executor and process sandbox. Keep extraction unavailable on unsupported hosts.
3. Assemble all selected resources atomically under aggregate time/text/prompt budgets. No silent metadata-only fallback or fabricated full-document coverage; bounded excerpts need honest omission metadata.
4. Persist the exact run-bound evidence manifest and excerpts with call reservation, verify authorized selection/revision/source hashes at dispatch and completion, and ensure historical citation resolution without implicit redispatch. Schema changes require their own reviewed stage.
5. Integrate private chat execution with cancellation/deadline/lease semantics, safe error mapping and no unauthorized external calls. Continue treating all names/text as quoted untrusted prompt data.
6. Update strict frontend/backend contracts together. The current UI statement that resource bodies are not read must remain until genuine context integration exists. Preserve history/read/cancel independently of send capability and continue to show the external model as unverified.

Publication and subsequent implementation remain separate approvals owned by the coordinating task. This foundation is not acceptance of the full selected-courseware-to-chat feature.
