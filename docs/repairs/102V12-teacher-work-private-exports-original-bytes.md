# Original download bytes and package metadata-read supplement

Base backend: `f5ddac341f18f3d50b913373d29e760e4111c3f7`, branch `102V12`.
The original 137-exchange [HTTP fixture](../../backend/tests/fixtures/teacher_work_private_exports_http_contract.native.json) is unchanged: SHA256 `fb9d5699b5795699399719df7a0d1f02959737578be0be9cb735afebebc0b71a`.

## Retained original Office bytes

The separate UTF-8 [original-bytes companion](../../backend/tests/fixtures/teacher_work_private_exports_http_original_bytes.native.json) is 136095 bytes, SHA256 `9a8b5e2761b52bccbf085959832267c03f7bee69be34a1852789e951c7faa6e8`. It contains 12 of the 13 successful original download examples, with original case IDs, exact recorded five response headers, lengths, hashes and retained evidence paths. Two distinct payloads are stored once as canonical base64. These are original files left by the published native run, verified at their own task/artifact paths against the captured response hash; no Office generation or new database run was used to produce this companion.

| Original happy-path case | Format | Bytes | SHA256 |
| --- | --- | ---: | --- |
| `real_private_package_create_and_download-3` | PPTX | 49387 | `e64917953724cb5afa9cda8f3a96d5564f2ce4ff9602ba5c3f86bceba46c3daf` |
| `real_private_package_create_and_download-4` | DOCX | 34865 | `94fb8bdeb52d642eb28fa2273539a7383e12f4fa10597326a370df2b3a7bff1f` |

`access_flags_tampering_and_historical_download-13` is explicitly omitted: its own artifact path was subsequently overwritten by that test with eight-byte `tampered` content, SHA256 `d121be3103007b41edf96f8262925f8c7d61894afe9a041843b631f69445bc57`. The companion does not replace this missing original body with another example's equal-hash file.

Frontend replay can select the original case and decode its referenced payload:

```js
const example = companion.examples.find(e => e.case_id === originalCase.name);
if (!example) throw new Error('No retained original response body for this case');
const payload = companion.payloads[example.payload_sha256];
const bytes = Uint8Array.from(atob(payload.base64), char => char.charCodeAt(0));
const response = new Response(bytes, {
  status: example.response.status,
  headers: example.response.headers,
});
```

Both payloads pass base64 canonicality, exact length/SHA256, ZIP CRC/all-member reads and the actual published Office structural/content validator against the originally captured PackageVersionDTO. This is backend byte/structure evidence; no browser or rendered Office verification was performed.

## Authenticated GET repair

The frontend reproduced list200 with one unavailable READY sibling, then package GET503 even though direct healthy download worked. GET shared mutation finalization's full-package byte certification. Only authenticated package GET now selects explicit `metadata_read=True`, retaining persisted owner/task/version/approval/run/artifact coherence and final authority checks. The same mode is rechecked during final held admission, requires a read root, and rejects mutation operations, current/fenced publication, changed lease/completion or a targeted download. Create/retry/file paths retain their existing default byte verification. Targeted download still verifies the selected actual length/SHA256 at finalization.

GET returns the same eight-field package and eleven-field artifact wire, including trusted committed name/size/SHA256. State and validation_summary record generation's committed result. List's download_available reports current availability. The explicit read-only storage path check opens no payload content and checks every artifact state. A nonREADY generation may have no owner directory yet; its safe absence is rechecked against the named root. READY still requires a safely resolved owner. Safely missing, empty or stable corrupt READY leaves no longer block metadata GET; unsafe root/public aliases/owner or artifact symlinks still return503, including FAILED/FAILED packages. GET performs no SQL writes or state repair.

## Verification and evidence

Original archive checks read every tar member and verify 79 source/log/utility hashes in each archive. Their hashes remain `42dd1cbeb77bbb5d1519bc1235579b3f9163c3020de4417cec6b074c696b82e2` (original evidence) and `b187c9f44977ab802dbffe228661cc67d6d2c703e374edffe1123873da753fb3` (published evidence). The supplement keeps its new native GET regression provenance separate from those immutable captures.

Offline companion verification:

```bash
PYTHONPATH=backend:backend/tests /tmp/gezhi-mysql-venv/bin/python -m pytest -q backend/tests/test_teacher_work_private_export_bytes.py
```

Result: **3 passed**. The relevant ordinary suite command is:

```bash
PYTHONPATH=backend:backend/tests /tmp/gezhi-mysql-venv/bin/python -m pytest -q backend/tests/test_teacher_work*.py
```

Final result: **195 passed**, one existing serializer warning, 19.22 seconds. This includes eight direct safe/unsafe path-boundary tests and the three offline byte checks. Broad application tests that import app.main or unrelated Gitea/RAG services were excluded under the task boundary.

The RED native case reproduced `503 PRIVATE_STORAGE_UNAVAILABLE` at the GET200 assertion (1 failed, 34.78 seconds). Its official network-disabled MySQL8.4.10 container stopped with exit0 and was removed with volumes. After the fix, all four missing/corrupt/empty/symlink scenarios passed (69.33 seconds): list→metadata GET→healthy download, bad download refusal, unchanged rows, SELECT/SHOW-only GET and refusal of exact-create replay with bad bytes.

Independent test review identified a noREADY owner/leaf-symlink gap in the first metadata implementation. Two real native cases reproduced the incorrect200 after FAILED/FAILED (38.50 seconds). The final path-only method fixed it: all six READY/nonREADY path cases passed (72.33 seconds), with normal never-created owner directories still readable and unsafe existing links refused. Intermediate53-pass results precede this final change and are preserved as intermediate evidence, not final acceptance.

Final native command:

```bash
PYTHONPATH=backend:backend/tests /tmp/gezhi-mysql-venv/bin/python -m pytest -q -s backend/tests/native_teacher_work_private_exports.py
```

Result: **55 passed**, one existing Config deprecation warning, **247.75 seconds**. This reruns all 48 original export regressions and seven added operation/storage cases, including the unchanged same-v3 private CRU/material/chat checks with synthetic MockTransport. The final actual MySQL root is `/tmp/gezhi-tw-native-5gjt1gdy`. Its first SELECT1/version/connection/settings and owned teardown are retained. All six supplemental instances, including RED/intermediate runs, stopped with exit0 and were removed with volumes; every pre-existing container baseline was preserved, and final running-container inventory was empty.

The separate [metadata-read native fixture](../../backend/tests/fixtures/teacher_work_private_exports_metadata_read.native.json) contains **56 actual new exchanges** from ten selected READY/nonREADY/unsafe/retry scenarios, 249394 UTF-8 bytes, SHA256 `871af724ca31a7facb13c8f26abf558826d7b045eb70122872d7a8bce2b423bd`. It explicitly identifies new capture provenance, exact final verified source hashes, actual MySQL identity, source exchange file hashes and teardown. It contains binary response metadata; the original Office bytes remain in the original-bytes companion above. The original137 responses are not rewritten or relabeled as responses of the new implementation.

Independent code and evidence/test reviews found no remaining blocker; all56 new exchanges match their source capture literals and hashes. [The supplement manifest](102V12-teacher-work-private-exports-original-bytes-evidence.json) records precise commands, original archive verification and source/log hashes. The separate new archive is `/workspace/gezhi-private-exports-metadata-bytes-supplement-evidence.tar.gz`. No production flag changes or production migrations, external AI, real student data or application startup are involved; actual migrations run only on this task's isolated synthetic schemas. The previously denied CI proxy query is not retried or routed through another path; local test success is not a CI-success claim.
