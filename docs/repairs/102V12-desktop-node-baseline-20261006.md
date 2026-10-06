# Desktop Node test baseline repair

Date: 2026-10-06 UTC. Source base: `bd452b16c20e64c6cea5387dd9c9ae5c7aae2fb8`.

## Scope

This change repairs test dependency setup, harness bindings and obsolete assertions. It changes no production frontend source, shipped Vue, backend implementation, Gitea/RAGFlow feature, browser/mobile test, deployment or service configuration. The earlier materials publication remains the base.

The original complete selection reported 943 tests, 924 passes and 19 established failures. Eight failed before their compiler-dependent file bodies ran; they were not declared product-safe from that initial result.

## Reproducible commands and lanes

From `frontend`, install with `npm ci --ignore-scripts`, then run `npm test`. Node 24 or newer is required; verification used Node 24.19.0 and npm 11.9.0. `npm run test:plan` prints the complete file partition without executing tests.

The aggregate discovers every top-level `frontend/tests/*.test.mjs` exactly once. Eight explicitly registered compiler/custom-renderer/SSR files use official Vue, compiler-dom and server-renderer 3.5.39. All remaining files use shipped Vue 3.3.4, including compatibility, materials and foreground tests. The aggregate fixes each child process to `TZ=Asia/Shanghai`, uses concurrency one, verifies disjoint/full file coverage and rejects missing/duplicate files, unreviewed compiler imports, failed child exits, incomplete TAP accounting, assertions, skips, cancellations and todos. AST import detection uses pinned Babel parser 7.29.9.

Both lane preloads reject unregistered fetches; individual tests supply synthetic transports. The shipped lane additionally refuses official compiler/SSR imports. The official lane does not remap Vue to the shipped runtime. Separate child-process regressions verify the exact runtime versions and singleton bindings. No test-name filtering is used by the aggregate.

The npm lock records 23 packages from the official npm registry with integrity hashes. A clean, isolated `npm ci --offline --ignore-scripts` using the retained cache succeeded. Production Vue SHA256 remains `ff0c8fcaa207637d20372a08af75cee5dda3d870168a01fa110f3af7eb4500fd`.

## Harness and assertion repairs

- Auth VM tests now supply real navigation and Vue ref/readonly bindings; token, server identity, expiry, logout and stale-response assertions remain. A negative control detects a writable auth epoch
- Forum tests intercept the exact mockData module before the API import, sharing four writable synthetic arrays. All five failing mutations are awaited and rejected, and every array remains snapshot-checked. Mutation controls detect forbidden fallback writes
- Analytics tests assert null/unknown measurements, absent invented tasks and no local focus increase after a reminder, matching the current representation
- Knowledge transport tests specify a synthetic API origin and retain exact encoded repository/user paths and DELETE semantics
- Diagnosis, Work rail and tutor assertions follow the current guarded navigation, task controls and async tutor-only steps. Existing ownership/session/navigation fences are retained and mutation-tested
- PR presentation assertions preserve the already-reviewed safe native action URL, provenance/permissions, noncopyable templates and explicit unknown states. No remote feature was restored or developed

## Newly generated analytics HTTP capture

The missing older analytics fixture was not recovered. One existing exporter, `backend/tests/test_rebuild_analytics_evidence.py::test_http_contract_fixture_export`, generated a new capture using its unchanged synthetic in-memory SQLite harness and actual analytics router through in-process `httpx.ASGITransport`.

Producer commit is the source base above. Actual capture-write time is `2026-10-06T02:50:22.720968Z`; the historical fixed window clock remains test input. The exporter passed one test, captured eleven HTTP responses and opened one in-memory SQLite connection. Its unchanged production MySQL engine opened zero connections. Network/service/process controls observed no unexpected denials. Synthetic response strings were reviewed; no credentials, bearer tokens, personal production data or production account access were exported.

The fixture is `frontend/tests/fixtures/analytics-http-fixtures.json` (76,269 bytes), SHA256 `ac7ec60287a15241c546bdb987d6c8fe288e57af5e8ee5b3feb4fed081a42ed0`. Adjacent provenance SHA256 is `c754766d7c817f41bce06be7e930bb19f3609d18c7bb4ea6d1ce814413bdbc6b`. Provenance retains the exact producer command, source hashes, generation timestamps, dependency versions and official prerequisite wheel hash. The frontend asserts fixture/hash/provenance consistency and retains both original actual-response assertions; its focused official-lane file passed 22/22.

## Limits

Final deterministic aggregate passed **1,194/1,194** tests across **104/104** files, with zero failures, skips, cancellations or todos and exit code zero. Official 3.5.39: 248/248 cases in eight files. Shipped 3.3.4: 946/946 cases in 96 files. It was launched from a parent `TZ=Asia/Tokyo` environment to verify that both lane commands explicitly set the required Shanghai process timezone. Independent review found no blockers; it separately reran finite selections and did not duplicate the full aggregate.

These are finite offline Node, custom-renderer/SSR and synthetic analytics HTTP checks. They do not prove browser pixels, desktop browser interaction, deployed frontend/backend readiness, live services, teacher Work native MySQL acceptance or missing older-artifact identity. Existing module-type, development-runtime and lifecycle/deprecation warnings, plus deliberately rejected synthetic-request logs, are visible rather than hidden. No commit, merge, publication or deployment is performed by this repair task.
