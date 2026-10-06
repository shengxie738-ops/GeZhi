# 102V12 — private approved Office exports, native backend acceptance

## Outcome and scope

This explicitly authorized backend stage adds authenticated manual-approved PPTX/DOCX creation, historical status/list/download and one bounded retry. It builds and structurally validates real Office bytes, persists state through actual SQLAlchemy/PyMySQL/MySQL, and preserves the existing private task/chat/material contracts. Integration base is `c2161427ce0a5f898c089daa802d3a2cc753ca74` on `102V12`. The default `TEACHER_WORK_PRIVATE_EXPORTS_ENABLED=False` and production `TEACHER_WORK_LIVE_GATES_UNVERIFIED` gate remain in place. No frontend, browser/mobile, external AI, app.main, deployment, main merge, Gitea or RAGFlow work is included.

The exact endpoint/DTO/reason/error contract is in [the frozen wire](102V12-teacher-work-private-exports-plan.md#frozen-wire-v1). Captured JSON responses and actual binary attachment metadata are in [the native HTTP fixture](../../backend/tests/fixtures/teacher_work_private_exports_http_contract.native.json). The fixture contains synthetic data and omits authorization headers and binary payloads; every example identifies its original evidence file and SHA256. `working_revision` increments only on confirmed COMPLETE; clients must re-read the existing task/material responses after mutations or unknown outcomes.

## Migration and defects found by actual execution

The original v2 contract/hash/DDL remain unchanged (`6f2548a7f09b44d182a0d73aa408486634f55de4bdaaac512ed166eedd0822f5`). The separate explicit v2→v3 migration adds four bounded ALTER steps, no tables: approval/task referenced uniqueness, nullable immutable package approval binding and composite FK, manual run CHECK and READY artifact CHECK. v3 hash is `7b3c31472a928e37bb31bb4ae96c75d6aa7674beeecfdc39ccc08e5ae943f65c`. It accepts exact completed v2 or exact completed v3 replay only, verifies database/server UUID/datadir/socket and session/table resolution, preflights existing data, and writes the conditional completion receipt after physical verification. Partial DDL or a missing receipt never resumes automatically. DDL is not transactionally reversible; unknown UPDATE/COMMIT acknowledgment remains unknown.

Native execution exposed MySQL CHECK serialization around JSON predicates and string literals containing `@`, `.` and `-`; the v3 expressions now match the actual server representation and the bounded literal parser recognizes those characters. Comparisons stay exact. MySQL SQL NULL/JSON NULL CHECK semantics required an explicit COALESCE false verdict: an unknown JSON validation result cannot certify a READY file. Independent connections verify the ledger, composite FK, unique key and CHECK rejection. Existing v2 observer tests remain intact; private legacy features explicitly accept either exact reviewed schema.

Storage regressions caught a blocking FIFO read and unsafe partial cleanup of mismatched staging/final inodes. File opens now include NONBLOCK/NOFOLLOW and cleanup validates the entire owned set before unlinking. READY bytes are immutable; full nonREADY claims remain reserved after failure or uncertain commits. A known spawn failure is controlled, and unconfirmed child termination cannot create a stopped-execution proof. Native fault tests also found the need to revalidate source/deadline/released-lease after the final owner flush, including stopped-run recovery. Quota admission reserves directory entries as well as byte claims.

Final independent review found public-directory symlink aliases could bypass lexical private/public root separation. Both lexical and actual public targets are now checked, preserving filesystem symlink/`..` resolution order and refusing dangling/looped or unknown targets. Private root components remain NOFOLLOW and inode-bound. Synthetic filesystem RED tests reproduce both alias forms.

The explicitly requested history correction distinguishes safe leaf absence/stable byte mismatch from unsafe roots/paths. List summaries retain persisted READY and set only the affected format's download_available=false; healthy versions, formats and pagination stay usable. A typed missing-leaf result requires fresh root and namespace/owner-FD inode checks; directory replacement races remain503. Healthy per-format download finalization checks its requested bytes while preserving package SQL/approval/owner binding. A bad target download still returns503. Native missing/corrupt/empty/symlink cases prove the differentiation, healthy actual downloads and unchanged database state with recorded SELECT/SHOW/DO0-only GETs.

## Reproduction and results

Use an isolated disposable execution environment with Docker, an available official pinned image and a Python virtualenv. Never point these fixtures at an existing database or supply a production database URL. Native filenames deliberately start with `native_`, so ordinary pytest discovery does not connect to a database. Each native fixture creates its own network-disabled container and synthetic schemas, accepts no credentials or external database, and stops/removes its exact owned container and anonymous volumes in teardown.

Verified versions: MySQL 8.4.10, SQLAlchemy 2.1.3, PyMySQL 1.2.3, pytest 9.1.1, Pydantic 2.13.5, FastAPI 0.142.2, httpx 0.28.1, python-pptx 1.0.2, python-docx 1.2.0, Pillow 11.3.0 and lxml 6.1.3. Office dependencies were installed from official PyPI. Actual package versions and pinned image digest are recorded in the evidence manifest.

Rebuild the optional native environment using the repository's pinned dependency file and official sources:

```bash
python3.12 -m venv /tmp/gezhi-mysql-venv
/tmp/gezhi-mysql-venv/bin/python -m pip install --index-url https://pypi.org/simple -r backend/tests/requirements-native-teacher-work.txt
docker pull mysql:8.4.10@sha256:8dbcf531a03aade657e181b9cf2f1d1803ce621a1d55610cb44cb531ab7d7db6
```

From the repository root, with the verified virtualenv:

```bash
PYTHONPATH=backend:backend/tests /tmp/gezhi-mysql-venv/bin/python -m pytest -q backend/tests/test_teacher_work*.py
```

Result: **184 passed**, one existing synthetic oversize serializer warning, 18.25 seconds. No native database is started by this command. All12 pinned optional native dependency versions match the installed environment; `pip check` reports no broken requirements.

The original four chat execution behavioral fixtures remain byte/AST pinned: runtime AST hash `3d345760c79c1ae7b35f68b8742c5d6208ada68b7ecdb903e2578c5975530209`. Only their exact named-operation source guard was expanded for the four explicitly gated package operations. An additional independent byte hash pins everything outside that guard; no frozen behavioral expectation was relaxed.

```bash
PYTHONPATH=backend:backend/tests /tmp/gezhi-mysql-venv/bin/python -m pytest -q -s backend/tests/native_teacher_work_mysql.py backend/tests/native_teacher_work_repository.py backend/tests/native_teacher_work_private_http.py backend/tests/native_teacher_work_private_chat_http.py backend/tests/native_teacher_work_private_materials.py backend/tests/native_teacher_work_private_exports.py
```

Final result: **144 passed**, one existing Pydantic Config deprecation warning, **491.20 seconds**. Breakdown: schema/cleanup22, repository7, private CRU15, chat20, materials32, exports48. It used six isolated real MySQL servers with independent physical connections and owned teardown. Exports cover genuine PPTX/DOCX construction/validation/download, partial format failure and READY-preserving retry/replay, concurrency, authorization, quota, source/normalization drift, historical reopen/pagination and isolated bad files, default-off/unsafe-storage capabilities, deadline and late publisher fencing, actual bounded child timeout, unconfirmed stop proof, filesystem fsync fault, and injected before/after SQL commit/DDL acknowledgment faults.

An earlier completed batch passed138 in462.84 seconds before the last additions. Same-v3 supplement passed1 in30.72 seconds, strengthened6unknown+3recovery cases passed9 in76.04 seconds, and the new history4 cases went from3 failed/1 passed to4 passed in62.00 seconds. Two intermediate final batches were deliberately interrupted when a new configuration corner and then the explicitly requested history correction required implementation changes; their interrupted logs and cleanup records are retained and are not acceptance passes. The current final batch includes all of these cases and final source changes.

```bash
PYTHONPATH=backend:backend/tests /tmp/gezhi-mysql-venv/bin/python -m pytest -q -s backend/tests/native_teacher_work_private_exports.py::test_migrated_v3_preserves_authenticated_cru_materials_and_chat
```

This case, also included in the final144 batch, verifies CRU create/read/update, material save/approval/read and authenticated chat completion/history/exact replay on the **same migrated v3 database**. Capability payloads are compared exactly before and after migration, export gate stays off, cross-owner/student reads remain refused, and an independent connection verifies the v3 physical receipt and persisted chat rows. The provider adapter is real but its transport is synthetic `httpx.MockTransport`; no external supplier is called.

## Evidence and remaining limits

[Evidence manifest](102V12-teacher-work-private-exports-evidence.json) records exact commands, results, source hashes, logs, first successful `SELECT 1`, MySQL settings and teardown. The retained archive is `/workspace/gezhi-native-private-exports-evidence.tar.gz`; it includes sanitized JSON/logs, not sockets/datadirs or secrets. Each started server's teardown is checked for stopped/exit0/removal with volumes and preserved baseline. An interrupted creation with no observed container is recorded separately with null ID/stopped/exit values; it is never described as a running server that exited0.

The final HTTP fixture contains137 original exchanges, including READY/download_available=false with retained healthy history/pagination and actual successful healthy per-format downloads. Its original final evidence root is `/tmp/gezhi-tw-native-jtbbpxu2`; fixture SHA256 is `fb9d5699b5795699399719df7a0d1f02959737578be0be9cb735afebebc0b71a`. Every selected source exchange, selector, identity and source-file hash is independently checked. This stage retained37 root evidence records:36 observed started databases all stopped with exit0 and removed with volumes, and one creation-not-observed record. Docker's final running inventory is empty; existing service baselines were preserved.

Response-cap testing uses a reduced512-byte cap to exercise the actual precommit refusal path; it is not a262144-byte one-byte boundary proof. Commit/DDL uncertainty tests inject controlled faults around actual native operations. Structural Office acceptance does not establish visual rendering or browser/mobile behavior. The filesystem verification and SQL commit have a finite crash/TOCTOU interval; retained claims and explicit reconciliation fail closed rather than claiming cross-resource atomicity. Expiry CAS proves publication fencing, not termination of a child in another process. No real provider, complete production authentication/chat acceptance, full teacher Work acceptance or production gate release is claimed. CI must be checked for the published commit; absence of runs is not a pass.
