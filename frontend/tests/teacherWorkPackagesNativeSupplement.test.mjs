import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { createTeacherWorkApi } from '../js/api/teacherWork.js';
import { validatePackageArtifact } from '../js/api/teacherWorkPackages.js';

const fixturesRoot = new URL('../../backend/tests/fixtures/', import.meta.url);
const readFixture = name => {
    const raw = readFileSync(new URL(name, fixturesRoot)); return { raw, data: JSON.parse(raw) };
};
const original = readFixture('teacher_work_private_exports_http_contract.native.json');
const retained = readFixture('teacher_work_private_exports_http_original_bytes.native.json');
const metadata = readFixture('teacher_work_private_exports_metadata_read.native.json');
const sha256 = bytes => createHash('sha256').update(bytes).digest('hex');
const pinned = [
    [original, 657815, 'fb9d5699b5795699399719df7a0d1f02959737578be0be9cb735afebebc0b71a'],
    [retained, 136095, '9a8b5e2761b52bccbf085959832267c03f7bee69be34a1852789e951c7faa6e8'],
    [metadata, 249394, '871af724ca31a7facb13c8f26abf558826d7b045eb70122872d7a8bce2b423bd']
];
const originalByName = new Map(original.data.examples.map(entry => [entry.name, entry]));
const readyArtifacts = examples => {
    const result = new Map();
    for (const entry of examples) for (const artifact of entry.response.body?.data?.artifacts || []) {
        if (artifact.version_id && artifact.state === 'READY') result.set(artifact.artifact_id, structuredClone(artifact));
    }
    return result;
};
const originalArtifacts = readyArtifacts(original.data.examples);
const metadataArtifacts = readyArtifacts(metadata.data.examples);
const nativePayloads = new Map(Object.entries(retained.data.payloads).map(([digest, value]) => [digest, Buffer.from(value.base64, 'base64')]));
const safeFailure = (reason, status) => caught => {
    assert.equal(caught.name, 'TeacherWorkError'); assert.equal(caught.reason, reason); assert.equal(caught.status, status);
    assert.doesNotMatch(caught.message + JSON.stringify(caught), /supplement-session|owner_subject|\/var\/|\/tmp\/|traceback/i);
    assert.equal(Object.hasOwn(caught, 'cause'), false); return true;
};
const normalizedPath = value => {
    const url = new URL(value, 'https://native-supplement.invalid');
    // The real API emits documented default limit20 where the original request omitted it.
    if (/\/packages$/.test(url.pathname) && !url.searchParams.has('limit')) url.searchParams.set('limit', '20');
    url.searchParams.sort(); return url.pathname + (url.searchParams.size ? '?' + url.searchParams : '');
};
const verifyRequest = (entry, url, options) => {
    assert.equal(normalizedPath(url), normalizedPath(entry.request.path)); assert.equal(options.method, entry.request.method);
    assert.equal(options.cache, 'no-store'); assert.equal(options.redirect, 'error');
    assert.equal(options.headers.Authorization, 'Bearer synthetic-supplement-session');
    assert.equal(options.headers['Idempotency-Key'] ?? null, entry.request.idempotency_key ?? null);
    assert.deepEqual(options.body === undefined ? null : JSON.parse(options.body), entry.request.body);
    assert.doesNotMatch(url, /supplement-session|token=/);
};
function invoke(api, entry, artifacts) {
    const url = new URL(entry.request.path, 'https://native-supplement.invalid'), parts = url.pathname.split('/').filter(Boolean);
    const taskId = parts[4], type = parts[5], id = parts[6];
    if (type === 'artifacts') {
        const artifact = artifacts.get(id); assert.ok(artifact, 'unchanged full native READY DTO exists for ' + id);
        return api.downloadArtifact(taskId, structuredClone(artifact));
    }
    if (type === 'runs') return api.retryPackage(taskId, id, structuredClone(entry.request.body));
    if (type === 'packages') {
        if (entry.request.method === 'POST') return api.createPackage(taskId, structuredClone(entry.request.body), { idempotencyKey: entry.request.idempotency_key });
        if (id) return api.getPackage(taskId, id);
        return api.listPackages(taskId, { ...(url.searchParams.has('limit') ? { limit: Number(url.searchParams.get('limit')) } : {}),
            ...(url.searchParams.has('before') ? { before: url.searchParams.get('before') } : {}) });
    }
    assert.fail('Unaccounted native supplement route ' + entry.request.path);
}

function verifyBinaryMetadata(entry, capturedBinary, artifacts) {
    const artifactId = entry.request.path.split('/').at(-2), artifact = validatePackageArtifact(artifacts.get(artifactId));
    assert.equal(capturedBinary.byte_size, artifact.byte_size); assert.equal(capturedBinary.sha256, artifact.sha256);
    assert.equal(entry.response.status, 200); assert.equal(entry.response.headers['content-type'], artifact.mime);
    assert.equal(entry.response.headers['content-length'], String(artifact.byte_size));
    assert.equal(entry.response.headers['cache-control'], 'no-store'); assert.equal(entry.response.headers['x-content-type-options'], 'nosniff');
    assert.equal(entry.response.headers['content-disposition'], `attachment; filename="GeZhi-${artifactId}.${artifact.kind}"; filename*=UTF-8''${encodeURIComponent(artifact.download_name)}`);
    return artifact;
}

test('original and supplementary fixture hashes, retained payload identity and omitted thirteenth response stay exact', () => {
    for (const [fixture, bytes, digest] of pinned) { assert.equal(fixture.raw.byteLength, bytes); assert.equal(sha256(fixture.raw), digest); }
    assert.equal(retained.data.format, 'gezhi-private-exports-http-original-bytes-native-v1');
    assert.equal(retained.data.provenance.regenerated, false); assert.equal(retained.data.provenance.new_database_run, false);
    assert.equal(retained.data.provenance.source_fixture_sha256, pinned[0][2]);
    assert.equal(retained.data.examples.length, 12); assert.equal(nativePayloads.size, 2);
    assert.equal(new Set(retained.data.examples.map(entry => entry.case_id)).size, 12);
    for (const [digest, payload] of Object.entries(retained.data.payloads)) {
        const bytes = nativePayloads.get(digest); assert.equal(payload.encoding, 'base64'); assert.equal(payload.sha256, digest);
        assert.equal(bytes.byteLength, payload.byte_size); assert.equal(sha256(bytes), digest);
        assert.equal(bytes.toString('base64'), payload.base64); assert.equal(bytes.subarray(0, 2).toString('hex'), '504b');
    }
    const originalBinary = original.data.examples.filter(entry => entry.binary);
    assert.equal(originalBinary.length, 13); assert.equal(retained.data.omitted_examples.length, 1);
    const omitted = retained.data.omitted_examples[0];
    assert.equal(omitted.case_id, 'access_flags_tampering_and_historical_download-13');
    assert.equal(omitted.reason, 'original_artifact_file_no_longer_matches_captured_response');
    assert.deepEqual(omitted.captured_binary, originalByName.get(omitted.case_id).binary);
    assert.equal(retained.data.examples.some(entry => entry.case_id === omitted.case_id), false);
    assert.deepEqual(new Set([...retained.data.examples.map(entry => entry.case_id), omitted.case_id]), new Set(originalBinary.map(entry => entry.name)));
    assert.equal(metadata.data.format, 'gezhi-private-exports-metadata-read-http-native-v1');
    assert.equal(metadata.data.provenance.new_capture, true); assert.equal(metadata.data.provenance.not_original_137_responses, true);
    assert.equal(metadata.data.provenance.binary_payloads_omitted, true); assert.equal(metadata.data.examples.length, 56);
    assert.equal(new Set(metadata.data.examples.map(entry => entry.name)).size, 56);
    assert.equal(metadata.data.examples.filter(entry => entry.binary).length, 6);
    assert.equal(metadata.data.examples.filter(entry => !entry.binary).length, 50);
});

for (const entry of retained.data.examples) {
    test(`exact retained original Office bytes replay: ${entry.case_id}`, async () => {
        const source = originalByName.get(entry.case_id); assert.ok(source?.binary);
        assert.deepEqual(entry.request, source.request); assert.deepEqual(entry.response, source.response);
        assert.equal(entry.byte_size, source.binary.byte_size); assert.equal(entry.sha256, source.binary.sha256);
        assert.equal(entry.payload_sha256, entry.sha256);
        for (const [name, value] of Object.entries(source.evidence)) assert.deepEqual(entry.original_evidence[name], value);
        const bytes = nativePayloads.get(entry.payload_sha256); assert.ok(bytes);
        assert.equal(bytes.byteLength, source.binary.byte_size); assert.equal(sha256(bytes), source.binary.sha256);
        const artifact = verifyBinaryMetadata(entry, source.binary, originalArtifacts);
        assert.equal(retained.data.payloads[entry.payload_sha256].kind, artifact.kind); let fetches = 0;
        const api = createTeacherWorkApi({ getToken: () => 'synthetic-supplement-session', fetchImpl: async (url, options) => {
            fetches++; verifyRequest(entry, url, options);
            return new Response(bytes, { status: entry.response.status, headers: entry.response.headers });
        } });
        const downloaded = await invoke(api, entry, originalArtifacts); assert.equal(fetches, 1);
        assert.deepEqual(Buffer.from(downloaded.bytes), bytes); assert.equal(sha256(downloaded.bytes), source.binary.sha256);
        assert.equal(downloaded.byte_size, bytes.byteLength); assert.equal(downloaded.download_name, artifact.download_name);
        assert.equal(downloaded.mime, artifact.mime); assert.equal(downloaded.blob.type, artifact.mime); assert.equal(downloaded.blob.size, bytes.byteLength);
        assert.deepEqual(Buffer.from(await downloaded.blob.arrayBuffer()), bytes);
        assert.deepEqual(Object.keys(downloaded).sort(), ['blob', 'byte_size', 'bytes', 'download_name', 'mime']);
    });
}

for (const [index, entry] of metadata.data.examples.entries()) {
    const category = entry.binary ? 'native unchanged header/metadata + synthetic omitted-body refusal' : 'native new JSON replay';
    test(`${index}: ${category}: ${entry.name}`, async () => {
        let fetches = 0, binaryReads = 0;
        const api = createTeacherWorkApi({ getToken: () => 'synthetic-supplement-session', fetchImpl: async (url, options) => {
            fetches++; verifyRequest(entry, url, options);
            if (entry.binary) {
                // New fixture's payloads remain omitted. Never substitute the original batch's bytes for them.
                const body = new ReadableStream({ start(controller) { controller.close(); } });
                const getReader = body.getReader.bind(body);
                body.getReader = () => { const reader = getReader(); return { read: () => { binaryReads++; return reader.read(); },
                    cancel: () => reader.cancel(), releaseLock: () => reader.releaseLock() }; };
                return { status: entry.response.status, headers: new Headers(entry.response.headers), body, redirected: false };
            }
            const headers = Object.fromEntries(Object.entries(entry.response.headers || {}).filter(([, value]) => value !== null));
            return new Response(JSON.stringify(entry.response.body), { status: entry.response.status, headers });
        } });
        if (entry.binary) {
            verifyBinaryMetadata(entry, entry.binary, metadataArtifacts); assert.equal(entry.binary.zip_magic, '504b');
            await assert.rejects(invoke(api, entry, metadataArtifacts), safeFailure('invalid_response', 200));
            assert.equal(binaryReads, 1, 'unchanged native metadata admitted before absent synthetic bytes are refused');
        } else {
            const envelope = entry.response.body;
            assert.deepEqual(Object.keys(envelope).sort(), ['code', 'data', 'message']); assert.equal(envelope.code, entry.response.status);
            if (entry.response_utf8_bytes !== undefined) assert.equal(new TextEncoder().encode(JSON.stringify(envelope)).byteLength, entry.response_utf8_bytes);
            if (entry.response.status === 200) { assert.equal(envelope.message, 'ok'); assert.deepEqual(await invoke(api, entry, metadataArtifacts), envelope.data); }
            else {
                assert.equal(entry.response.status, 503); assert.equal(envelope.message, 'PRIVATE_STORAGE_UNAVAILABLE'); assert.equal(envelope.data, null);
                await assert.rejects(invoke(api, entry, metadataArtifacts), safeFailure('private_storage_unavailable', 503));
            }
        }
        assert.equal(fetches, 1);
    });
}
