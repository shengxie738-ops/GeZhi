import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { createTeacherWorkApi, validatePrivateTaskCreate } from '../js/api/teacherWork.js';
import { validatePackageArtifact } from '../js/api/teacherWorkPackages.js';

const fixtureURL = new URL('../../backend/tests/fixtures/teacher_work_private_exports_http_contract.native.json', import.meta.url);
const original = readFileSync(fixtureURL);
const expectedHash = 'fb9d5699b5795699399719df7a0d1f02959737578be0be9cb735afebebc0b71a';
const fixture = JSON.parse(original);
const examples = fixture.examples;
const localGuards = new Set([17, 26, 46, 47, 48]);
const nativeArtifacts = new Map();
for (const entry of examples) {
    for (const artifact of entry.response.body?.data?.artifacts || []) {
        if (artifact.version_id && artifact.state === 'READY') nativeArtifacts.set(artifact.artifact_id, structuredClone(artifact));
    }
}
const errorReasons = Object.freeze({ REVISION_CONFLICT: 'revision_conflict', IDEMPOTENCY_CONFLICT: 'idempotency_conflict',
    PRIVATE_STORAGE_UNAVAILABLE: 'private_storage_unavailable', PRIVATE_EXPORTS_DISABLED: 'private_exports_disabled',
    COMMIT_OUTCOME_UNKNOWN: 'commit_outcome_unknown', PACKAGE_STATE_UNAVAILABLE: 'package_state_unavailable',
    PACKAGE_RETRY_UNAVAILABLE: 'package_retry_unavailable', CURRENT_TEACHER_REQUIRED: 'teacher_required',
    STALE_INPUT_REVISION: 'revision_conflict' });
const safeFailure = (reason, status) => caught => {
    assert.equal(caught.name, 'TeacherWorkError'); assert.equal(caught.reason, reason); assert.equal(caught.status, status);
    assert.doesNotMatch(caught.message + JSON.stringify(caught), /synthetic-native-replay-session|owner_subject|\/var\/|\/tmp\/|traceback/i);
    assert.equal(Object.hasOwn(caught, 'cause'), false); return true;
};
const normalizedPath = value => {
    const url = new URL(value, 'https://native-replay.invalid');
    if (/\/(packages|messages)$/.test(url.pathname) && !url.searchParams.has('limit')) url.searchParams.set('limit', '20');
    url.searchParams.sort();
    return url.pathname + (url.searchParams.size ? '?' + url.searchParams : '');
};
function invoke(api, entry) {
    const { method, path, body, idempotency_key } = entry.request;
    const url = new URL(path, 'https://native-replay.invalid'), parts = url.pathname.split('/').filter(Boolean);
    const taskId = parts[4], target = parts[5], identity = parts[6];
    const options = idempotency_key == null ? {} : { idempotencyKey: idempotency_key };
    if (url.pathname === '/api/teacher/work/capabilities') return api.getCapabilities();
    if (url.pathname === '/api/teacher/work/materials/capabilities') return api.getMaterialsCapabilities();
    if (url.pathname === '/api/teacher/work/packages/capabilities') return api.getPackagesCapabilities();
    if (url.pathname === '/api/teacher/work/tasks' && method === 'POST') return api.createTask(structuredClone(body), options);
    if (!target) return api.getTask(taskId);
    if (target === 'working') return api.updateWorking(taskId, structuredClone(body));
    if (target === 'materials') return identity === 'approve' ? api.approveMaterials(taskId, structuredClone(body), options) :
        method === 'POST' ? api.saveMaterials(taskId, structuredClone(body), options) : api.getMaterials(taskId);
    if (target === 'packages') {
        if (method === 'POST') return api.createPackage(taskId, structuredClone(body), options);
        if (identity) return api.getPackage(taskId, identity);
        return api.listPackages(taskId, { ...(url.searchParams.has('limit') ? { limit: Number(url.searchParams.get('limit')) } : {}),
            ...(url.searchParams.has('before') ? { before: url.searchParams.get('before') } : {}) });
    }
    if (target === 'runs') return api.retryPackage(taskId, identity, structuredClone(body));
    if (target === 'artifacts') {
        const artifact = nativeArtifacts.get(identity); assert.ok(artifact, 'native READY DTO for captured artifact ' + identity);
        return api.downloadArtifact(taskId, structuredClone(artifact));
    }
    if (target === 'messages') return method === 'POST' ? api.sendMessage(taskId, structuredClone(body), options) : api.listMessages(taskId);
    assert.fail('Unaccounted native route: ' + method + ' ' + path);
}
function verifyRequest(entry, url, options) {
    assert.equal(normalizedPath(url), normalizedPath(entry.request.path));
    assert.equal(options.method, entry.request.method);
    assert.equal(options.cache, 'no-store');
    assert.equal(options.headers.Authorization, 'Bearer synthetic-native-replay-session');
    assert.equal(options.headers['Idempotency-Key'] ?? null, entry.request.idempotency_key ?? null);
    assert.doesNotMatch(url, /synthetic-native-replay-session|token=/);
    let expectedBody = entry.request.body;
    if (entry.request.path === '/api/teacher/work/tasks') expectedBody = validatePrivateTaskCreate(expectedBody);
    assert.deepEqual(options.body === undefined ? null : JSON.parse(options.body), expectedBody);
}

test('native fixture is unchanged, all 137 captures are accounted for and binary omission remains explicit', () => {
    assert.equal(original.byteLength, 657815);
    assert.equal(createHash('sha256').update(original).digest('hex'), expectedHash);
    assert.equal(fixture.format, 'gezhi-private-exports-http-native-v1');
    assert.equal(examples.length, 137);
    assert.equal(new Set(examples.map(entry => entry.name)).size, 137);
    assert.equal(fixture.provenance.binary_payloads_omitted, true);
    assert.equal(fixture.provenance.authorization_headers_omitted, true);
    assert.equal(fixture.provenance.synthetic_only, true);
    assert.equal(examples.filter(entry => entry.binary).length, 13);
    assert.equal(localGuards.size, 5);
    assert.equal(examples.filter(entry => entry.response_utf8_bytes !== undefined).length, 117);
    assert.equal(examples.filter((entry, index) => !entry.binary && !localGuards.has(index)).length, 119);
});

for (const [index, entry] of examples.entries()) {
    const category = localGuards.has(index) ? 'client preflight guard' : entry.binary ? 'native header/metadata + synthetic empty-body refusal' : 'native JSON replay';
    test(`${index}: ${category}: ${entry.name}`, async () => {
        let fetched = 0, binaryReads = 0;
        const api = createTeacherWorkApi({ getToken: () => 'synthetic-native-replay-session', dispatchAuthExpired: () => assert.fail('Unexpected auth expiry'),
            fetchImpl: async (url, options) => {
                fetched++; verifyRequest(entry, url, options);
                if (entry.binary) {
                    // The capture omitted the native Office bytes. This empty stream is deliberately synthetic and must fail.
                    const body = new ReadableStream({ start(controller) { controller.close(); } });
                    const getReader = body.getReader.bind(body);
                    body.getReader = () => {
                        const reader = getReader(); return { read: () => { binaryReads++; return reader.read(); },
                            cancel: () => reader.cancel(), releaseLock: () => reader.releaseLock() };
                    };
                    return { status: entry.response.status, headers: new Headers(entry.response.headers), body, redirected: false };
                }
                const headers = Object.fromEntries(Object.entries(entry.response.headers || {}).filter(([, value]) => value !== null));
                return new Response(JSON.stringify(entry.response.body), { status: entry.response.status, headers });
            } });
        if (localGuards.has(index)) {
            assert.equal(entry.response.status, 422);
            assert.deepEqual(Object.keys(entry.response.body).sort(), ['code', 'data', 'message']);
            assert.equal(entry.response.body.code, 422); assert.equal(entry.response.body.data, null);
            await assert.rejects(invoke(api, entry), safeFailure('invalid_input', 0)); assert.equal(fetched, 0); return;
        }
        if (entry.binary) {
            const artifactId = entry.request.path.split('/').at(-2), artifact = validatePackageArtifact(nativeArtifacts.get(artifactId));
            assert.equal(entry.binary.byte_size, artifact.byte_size); assert.equal(entry.binary.sha256, artifact.sha256);
            assert.equal(entry.binary.zip_magic, '504b'); assert.equal(entry.response.headers['content-type'], artifact.mime);
            assert.equal(entry.response.headers['content-length'], String(artifact.byte_size));
            assert.equal(entry.response.headers['cache-control'], 'no-store'); assert.equal(entry.response.headers['x-content-type-options'], 'nosniff');
            assert.equal(entry.response.headers['content-disposition'], `attachment; filename="GeZhi-${artifactId}.${artifact.kind}"; filename*=UTF-8''${encodeURIComponent(artifact.download_name)}`);
            await assert.rejects(invoke(api, entry), safeFailure('invalid_response', 200));
            assert.equal(fetched, 1); assert.equal(binaryReads, 1, 'native headers admitted; absent synthetic body rejected'); return;
        }
        const captured = entry.response.body;
        if (entry.response_utf8_bytes !== undefined) assert.equal(new TextEncoder().encode(JSON.stringify(captured)).byteLength, entry.response_utf8_bytes);
        assert.deepEqual(Object.keys(captured).sort(), ['code', 'data', 'message']); assert.equal(captured.code, entry.response.status);
        if (entry.response.status === 200) {
            assert.equal(captured.message, 'ok'); const decoded = await invoke(api, entry); assert.deepEqual(decoded, captured.data);
        } else {
            assert.equal(captured.data, null); assert.match(captured.message, /^[A-Z][A-Z0-9_]{0,63}$/);
            const legacyMessages = /\/messages(?:\?|$)/.test(entry.request.path);
            const reason = captured.message === 'NOT_FOUND' ? legacyMessages ? 'task_not_found' : 'request_failed' : errorReasons[captured.message];
            assert.ok(reason, 'Explicit expected safe native error mapping');
            await assert.rejects(invoke(api, entry), safeFailure(reason, entry.response.status));
        }
        assert.equal(fetched, 1);
    });
}

// Controlled errors below are synthetic source-contract tests, not additional native captures.
const sourceErrorCases = [[409, 'STALE_INPUT_REVISION', 'revision_conflict'], [409, 'NORMALIZATION_REQUIRED', 'normalization_required'],
    [409, 'MATERIAL_TEXT_UNREPRESENTABLE', 'material_text_unrepresentable'], [409, 'MATERIAL_SOURCES_UNAVAILABLE', 'material_sources_unavailable'],
    [409, 'PACKAGE_FENCE_CHANGED', 'package_state_unavailable'], [409, 'ARTIFACT_NOT_READY', 'artifact_unavailable'],
    [422, 'NORMALIZATION_REQUIRED', 'normalization_required'], [503, 'PRIVATE_MATERIALS_DISABLED', 'private_materials_disabled'],
    [503, 'PACKAGE_RESPONSE_TOO_LARGE', 'package_response_too_large'], [503, 'MATERIAL_SOURCES_UNAVAILABLE', 'material_sources_unavailable'],
    [413, 'REQUEST_BODY_TOO_LARGE', 'request_too_large']];
for (const [status, code, reason] of sourceErrorCases) {
    test(`synthetic source-contract error: ${status} ${code} preserves ${reason}`, async () => {
        const api = createTeacherWorkApi({ getToken: () => 'synthetic-native-replay-session', fetchImpl: async () =>
            new Response(JSON.stringify({ code: status, message: code, data: null }), { status }) });
        await assert.rejects(invoke(api, examples[2]), safeFailure(reason, status));
    });
}
