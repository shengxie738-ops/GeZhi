import test from 'node:test';
import assert from 'node:assert/strict';
import { createTeacherWorkApi } from '../js/api/teacherWork.js';
import * as packageValidators from '../js/api/teacherWorkPackages.js';
import { materialsApproval, materialsApprovalId, materialsDigest, materialsTaskId, materialsInstant,
    materialLesson, materialSlides } from './fixtures/teacherWorkMaterialsFixtures.mjs';

// Synthetic finite contract fixtures. These are never represented as native route captures.
const runId = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
const versionId = 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee';
const artifactIds = ['11111111-1111-4111-8111-111111111111', '22222222-2222-4222-8222-222222222222'];
const mimeTypes = {
    pptx: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
};
const caps = () => ({ create: true, read: true, retry: true, download: true, storage_configured: true, reasons: {} });
const createBody = () => ({ approval_id: materialsApprovalId, input_revision: 2, outline_revision: 1,
    outline_digest: materialsDigest, source_digest: materialsDigest, expected_revision: 3 });
const artifact = (kind = 'pptx', state = 'PENDING') => ({ artifact_id: artifactIds[kind === 'pptx' ? 0 : 1], version_id: versionId,
    kind, state, download_name: `合成教学包.${kind}`, mime: mimeTypes[kind], byte_size: 0, sha256: null,
    exporter_version: `gezhi-${kind}@1`, validation_summary: null, error_code: null });
const snapshot = (operation = null) => ({ task_id: materialsTaskId,
    run: { run_id: runId, kind: 'package', input_revision: 2, outline_revision: 1, stage: 'PENDING', attempt: 1,
        provider_call_count: 0, deadline: '2026-10-06T00:08:00+00:00', error_code: null, result_version_id: versionId },
    version: { version_id: versionId, task_id: materialsTaskId, version_no: 1, base_version_id: null, run_id: runId,
        lesson: materialLesson(), slides: materialSlides(), source_snapshots: [], content_digest: materialsDigest,
        model_id: 'manual-approved@1', skill_versions: [], exporter_versions: ['gezhi-pptx@1', 'gezhi-docx@1'],
        template_version: 'gezhi-office-theme@1', created_at: materialsInstant }, approval: materialsApproval(), provenance: 'manual',
    artifacts: [artifact(), artifact('docx')], retry_available: false,
    receipt: operation === null ? null : { operation, run_id: runId, version_id: versionId, attempt: operation === 'retry' ? 2 : 1, replayed: false } });
const history = () => ({ task_id: materialsTaskId, items: [{ version_id: versionId, version_no: 1, run_id: runId,
    approval_id: materialsApprovalId, created_at: materialsInstant, stage: 'PENDING', attempt: 1,
    artifacts: ['pptx', 'docx'].map((kind, index) => ({ artifact_id: artifactIds[index], kind, state: 'PENDING', download_available: false })) }],
    next_before: null, truncated: false });
const validator = name => { assert.equal(typeof packageValidators[name], 'function', name); return packageValidators[name]; };
const failure = (reason, status) => caught => {
    assert.equal(caught.name, 'TeacherWorkError'); assert.equal(caught.reason, reason);
    if (status !== undefined) assert.equal(caught.status, status);
    assert.doesNotMatch(caught.message + JSON.stringify(caught), /secret|owner_subject|\/var\/|synthetic-session/);
    assert.equal(Object.hasOwn(caught, 'cause'), false); return true;
};
const response = (data, status = 200, message = 'ok') => new Response(JSON.stringify({ code: status, message, data }), {
    status, headers: { 'Content-Type': 'application/json' }
});
const apiFor = (fetchImpl, overrides = {}) => createTeacherWorkApi({ fetchImpl, getToken: () => 'synthetic-session', ...overrides });

test('package create command is exact, detached and revision bounded', () => {
    const input = createBody(), decoded = validator('validatePackageCreateBody')(input);
    assert.deepEqual(decoded, input); assert.notEqual(decoded, input);
    for (const mutate of [value => { value.owner_subject = 'secret'; }, value => { value.input_revision = 0; },
        value => { value.expected_revision = true; }, value => { value.approval_id = '/var/secret'; },
        value => { value.outline_digest = 'A'.repeat(64); }, value => { delete value.source_digest; },
        value => { value.outline_revision = Number.MAX_SAFE_INTEGER + 1; }]) {
        const value = createBody(); mutate(value); assert.throws(() => validator('validatePackageCreateBody')(value), failure('invalid_input'));
    }
});

test('package retry command permits the explicit attempt-one precondition only', () => {
    assert.deepEqual(validator('validatePackageRetryBody')({ expected_attempt: 1 }), { expected_attempt: 1 });
    for (const value of [{ expected_attempt: 2 }, { expected_attempt: true }, { expected_attempt: '1' }, {},
        { expected_attempt: 1, idempotency_key: 'secret' }]) assert.throws(() => validator('validatePackageRetryBody')(value), failure('invalid_input'));
});

test('all enabled package capabilities expose no disabled reasons', () => {
    const value = caps(), decoded = validator('validatePackageCapabilities')(value); assert.deepEqual(decoded, value);
    assert.notEqual(decoded, value); assert.notEqual(decoded.reasons, value.reasons);
    for (const mutate of [value => { value.download = 1; }, value => { value.publish = true; },
        value => { value.reasons.download = 'secret'; }, value => { value.create = false; }]) {
        const value = caps(); mutate(value); assert.throws(() => validator('validatePackageCapabilities')(value), failure('invalid_response'));
    }
});

test('strict package create uses the authenticated package route and explicit idempotency key', async () => {
    let sent; const api = apiFor(async (url, options) => { sent = { url, options }; return response(snapshot('create')); });
    assert.equal(typeof api.getPackagesCapabilities, 'function');
    assert.equal(typeof api.createPackage, 'function');
    const result = await api.createPackage(materialsTaskId, createBody(), { idempotencyKey: 'synthetic-create' });
    assert.deepEqual(result, snapshot('create'));
    assert.match(sent.url, new RegExp(`/api/teacher/work/tasks/${materialsTaskId}/packages$`));
    assert.equal(sent.options.method, 'POST'); assert.equal(sent.options.cache, 'no-store');
    assert.equal(sent.options.headers.Authorization, 'Bearer synthetic-session');
    assert.equal(sent.options.headers['Idempotency-Key'], 'synthetic-create'); assert.deepEqual(JSON.parse(sent.options.body), createBody());
    assert.doesNotMatch(sent.url, /synthetic-session/);
});

test('manual package snapshot is a detached exact cross-linked DTO', () => {
    const value = snapshot(), decoded = validator('validatePackageSnapshot')(value); assert.deepEqual(decoded, value);
    for (const [original, clone] of [[value, decoded], [value.run, decoded.run], [value.version, decoded.version],
        [value.approval, decoded.approval], [value.artifacts, decoded.artifacts], [value.artifacts[0], decoded.artifacts[0]],
        [value.version.lesson, decoded.version.lesson], [value.version.slides[0], decoded.version.slides[0]]]) assert.notEqual(original, clone);
    for (const mutate of [value => { value.owner_subject = 'secret'; }, value => { value.provenance = 'ai'; },
        value => { value.run.provider_call_count = 1; }, value => { value.run.kind = 'chat'; }, value => { value.run.attempt = 3; },
        value => { value.run.deadline = '2026-02-30T00:00:00Z'; }, value => { value.run.task_id = materialsTaskId; },
        value => { value.version.source_snapshots = [{ owner_subject: 'secret' }]; }, value => { value.version.skill_versions = ['lesson_package@1']; },
        value => { value.version.model_id = 'provider@1'; }, value => { value.version.template_version = 'secret'; },
        value => { value.version.exporter_versions.reverse(); }, value => { value.version.run_id = versionId; },
        value => { value.version.lesson.owner_subject = 'secret'; }, value => { delete value.version.lesson.summary; },
        value => { value.version.slides[0].file_path = '/var/secret'; }, value => { value.approval.task_id = versionId; },
        value => { value.approval.owner = 'secret'; }, value => { value.approval.input_revision = 3; },
        value => { value.artifacts.reverse(); }, value => { value.artifacts[1].artifact_id = artifactIds[0]; },
        value => { value.artifacts[0].version_id = runId; }, value => { value.retry_available = 1; },
        value => { value.receipt = { operation: 'create', run_id: versionId, version_id: versionId, attempt: 1, replayed: false }; }]) {
        const value = snapshot(); mutate(value); assert.throws(() => validator('validatePackageSnapshot')(value), failure('invalid_response'));
    }
});

test('artifact validator rejects unsafe filenames unknown nested fields and unvalidated READY bytes', () => {
    const validate = validator('validatePackageArtifact'); assert.deepEqual(validate(artifact()), artifact());
    const ready = { ...artifact(), state: 'READY', byte_size: 1, sha256: materialsDigest,
        validation_summary: { valid: true, checks: ['SYNTHETIC_VALIDATION'], warnings: ['Synthetic offline test'] } };
    const decoded = validate(ready); assert.deepEqual(decoded, ready); assert.notEqual(decoded.validation_summary, ready.validation_summary);
    for (const mutate of [value => { value.storage_key = '/var/secret'; }, value => { value.download_url = 'https://secret'; },
        value => { value.download_name = '../secret.pptx'; }, value => { value.download_name = '\u0000secret.pptx'; },
        value => { value.download_name = 'secret.docx'; }, value => { value.mime = mimeTypes.docx; },
        value => { value.byte_size = 10485761; }, value => { value.byte_size = 0; }, value => { value.sha256 = null; },
        value => { value.validation_summary.valid = false; }, value => { value.validation_summary.owner_subject = 'secret'; },
        value => { value.validation_summary.checks = ['']; }, value => { value.validation_summary.checks = Array(21).fill('check'); },
        value => { value.validation_summary.warnings = ['x'.repeat(201)]; }, value => { value.error_code = 'SECRET'; },
        value => { value.exporter_version = 'secret@1'; }]) {
        const value = structuredClone(ready); mutate(value); assert.throws(() => validate(value), failure('invalid_response'));
    }
});

test('package version history requires bounded exact unique descending versions and ordered artifact summaries', () => {
    const value = history(), decoded = validator('validatePackageHistory')(value); assert.deepEqual(decoded, value);
    assert.notEqual(decoded.items, value.items); assert.notEqual(decoded.items[0].artifacts, value.items[0].artifacts);
    for (const mutate of [value => { value.owner_subject = 'secret'; }, value => { value.items[0].lesson = {}; },
        value => { value.items[0].artifacts.reverse(); }, value => { value.items[0].artifacts[0].download_available = true; },
        value => { value.items[0].artifacts[0].storage_key = '/var/secret'; }, value => { value.items.push(structuredClone(value.items[0])); },
        value => { value.items = Array(21).fill(value.items[0]); }, value => { value.truncated = true; },
        value => { value.next_before = versionId; }, value => { value.items[0].created_at = 'yesterday'; }]) {
        const value = history(); mutate(value); assert.throws(() => validator('validatePackageHistory')(value), failure('invalid_response'));
    }
});

test('package routes bind returned task version receipt run and revision identities', async () => {
    const api = apiFor(async () => response(snapshot()));
    assert.deepEqual(await api.getPackage(materialsTaskId, versionId), snapshot());
    for (const mutate of [value => { value.task_id = runId; }, value => { value.version.version_id = runId; },
        value => { value.receipt = { operation: 'create', run_id: runId, version_id: versionId, attempt: 1, replayed: false }; }]) {
        const value = snapshot(); mutate(value); const wrong = apiFor(async () => response(value));
        await assert.rejects(wrong.getPackage(materialsTaskId, versionId), failure('invalid_response', 200));
    }
    const create = snapshot('create'); create.approval.approval_id = versionId;
    await assert.rejects(apiFor(async () => response(create)).createPackage(materialsTaskId, createBody(), { idempotencyKey: 'key' }), failure('invalid_response', 200));
});

test('package retry submits only expected_attempt with no new idempotency key', async () => {
    const value = snapshot('retry'); value.run.attempt = 2;
    let sent; const api = apiFor(async (url, options) => { sent = { url, options }; return response(value); });
    assert.deepEqual(await api.retryPackage(materialsTaskId, runId, { expected_attempt: 1 }), value);
    assert.match(sent.url, new RegExp(`/tasks/${materialsTaskId}/runs/${runId}/retry$`));
    assert.equal(sent.options.method, 'POST'); assert.deepEqual(JSON.parse(sent.options.body), { expected_attempt: 1 });
    assert.equal(Object.hasOwn(sent.options.headers, 'Idempotency-Key'), false);
    await assert.rejects(api.retryPackage(materialsTaskId, runId, { expected_attempt: 1 }, { idempotencyKey: 'key' }), failure('invalid_input'));
});

test('package history encodes a version cursor and rejects oversized pages before use', async () => {
    let sent; const api = apiFor(async (url, options) => { sent = { url, options }; return response(history()); });
    assert.deepEqual(await api.listPackages(materialsTaskId, { limit: 20, before: runId }), history());
    assert.match(sent.url, new RegExp(`/tasks/${materialsTaskId}/packages\\?limit=20&before=${runId}$`));
    assert.equal(sent.options.cache, 'no-store'); assert.equal(sent.options.method, 'GET');
    for (const options of [{ limit: 21 }, { before: 'secret' }, { before: null }, { limit: true }, { owner_subject: 'secret' }]) {
        await assert.rejects(api.listPackages(materialsTaskId, options), failure('invalid_input'));
    }
});

test('package transport accepts only the exact 200 ok envelope and bounded full UTF-8 responses', async () => {
    for (const value of [{ code: 200, message: 'ok', data: caps(), owner_subject: 'secret' }, { code: 201, message: 'ok', data: caps() },
        { code: 200, message: 'secret', data: caps() }, { code: 200, message: 'ok', data: { ...caps(), storage_key: '/var/secret' } }]) {
        await assert.rejects(apiFor(async () => new Response(JSON.stringify(value))).getPackagesCapabilities(), failure('invalid_response', 200));
    }
    await assert.rejects(apiFor(async () => response(caps(), 201)).getPackagesCapabilities(), failure('invalid_response', 201));
    const raw = JSON.stringify({ code: 200, message: 'ok', data: caps() }) + ' '.repeat(262145);
    await assert.rejects(apiFor(async () => new Response(raw)).getPackagesCapabilities(), failure('invalid_response', 200));
    const utf8 = JSON.stringify({ code: 200, message: 'ok', data: caps() }) + '字'.repeat(90000);
    await assert.rejects(apiFor(async () => new Response(utf8)).getPackagesCapabilities(), failure('invalid_response', 200));
});

test('package controlled failures preserve actionable reasons without leaking remote text', async () => {
    const cases = [
        [409, 'REVISION_CONFLICT', 'revision_conflict'], [409, 'OUTLINE_APPROVAL_CONFLICT', 'outline_approval_conflict'],
        [409, 'IDEMPOTENCY_CONFLICT', 'idempotency_conflict'], [409, 'SOURCE_CHANGED', 'source_changed'], [409, 'OWNER_RUN_BUSY', 'owner_busy'],
        [409, 'PACKAGE_RETRY_UNAVAILABLE', 'package_retry_unavailable'], [409, 'PACKAGE_DEADLINE_EXPIRED', 'package_deadline_expired'],
        [429, 'OWNER_STORAGE_QUOTA_EXCEEDED', 'owner_storage_quota_exceeded'], [422, 'INVALID_PRIVATE_PACKAGE_REQUEST', 'invalid_input'],
        [503, 'PRIVATE_EXPORTS_DISABLED', 'private_exports_disabled'], [503, 'PACKAGE_SCHEMA_UNAVAILABLE', 'package_schema_unavailable'],
        [503, 'PRIVATE_STORAGE_UNAVAILABLE', 'private_storage_unavailable'], [503, 'PACKAGE_STATE_UNAVAILABLE', 'package_state_unavailable'],
        [503, 'COMMIT_OUTCOME_UNKNOWN', 'commit_outcome_unknown']
    ];
    for (const [status, code, reason] of cases) {
        await assert.rejects(apiFor(async () => response(null, status, code)).getPackagesCapabilities(), failure(reason, status));
    }
    for (const raw of ['secret', JSON.stringify({ code: 409, message: 'REVISION_CONFLICT', data: { owner_subject: 'secret' } }),
        JSON.stringify({ code: 409, message: 'secret' + '/var/secret', data: null })]) {
        await assert.rejects(apiFor(async () => new Response(raw, { status: 409 })).getPackagesCapabilities(), failure('request_failed', 409));
    }
});

test('package transport rejects invalid options and commands before token access or fetch', async () => {
    let reads = 0, fetches = 0;
    const api = apiFor(async () => { fetches++; return response(caps()); }, { getToken: () => { reads++; return 'synthetic-session'; } });
    for (const run of [() => api.createPackage(materialsTaskId, createBody()), () => api.createPackage('secret', createBody(), { idempotencyKey: 'key' }),
        () => api.getPackagesCapabilities({ signal: {} }), () => api.createPackage(materialsTaskId, createBody(), { idempotencyKey: '\nsecret' }),
        () => api.getPackage(materialsTaskId, 'secret'), () => api.retryPackage(materialsTaskId, runId, { expected_attempt: 2 })]) {
        await assert.rejects(run(), failure('invalid_input'));
    }
    assert.equal(reads, 0); assert.equal(fetches, 0);
});

test('package responses and auth-expiry events are fenced to the initiating session', async () => {
    let token = 'synthetic-session', expired = 0;
    const api = apiFor(async () => { token = 'replacement'; return response(caps()); }, { getToken: () => token,
        dispatchAuthExpired: () => { expired++; } });
    await assert.rejects(api.getPackagesCapabilities(), failure('request_aborted')); assert.equal(expired, 0);
    await assert.rejects(apiFor(async () => response(null, 401, 'AUTH_REQUIRED'), { dispatchAuthExpired: () => { expired++; } })
        .getPackagesCapabilities(), failure('auth_required', 401)); assert.equal(expired, 1);
    const abort = new AbortController(); abort.abort(); let fetched = false;
    await assert.rejects(apiFor(async () => { fetched = true; return response(caps()); }).getPackagesCapabilities({ signal: abort.signal }), failure('request_aborted'));
    assert.equal(fetched, false);
});

const binaryBytes = Uint8Array.of(0x50, 0x4b, 3, 4, 10, 20);
const readyArtifact = async (kind = 'pptx') => ({ ...artifact(kind), state: 'READY', byte_size: binaryBytes.byteLength,
    sha256: Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', binaryBytes)), byte => byte.toString(16).padStart(2, '0')).join(''),
    validation_summary: { valid: true, checks: ['SYNTHETIC_VALIDATION'], warnings: [] } });
const binaryResponse = (value, overrides = {}, body = binaryBytes) => new Response(body, { status: 200,
    headers: { 'Content-Type': value.mime, 'Content-Length': String(value.byte_size),
        'Content-Disposition': `attachment; filename="lesson.${value.kind}"; filename*=UTF-8''${encodeURIComponent(value.download_name)}`, ...overrides } });

test('Office bytes use an authenticated no-store download and return no automatic object URL', async () => {
    for (const kind of ['pptx', 'docx']) {
        const value = await readyArtifact(kind); let sent;
        const api = apiFor(async (url, options) => { sent = { url, options }; return binaryResponse(value); });
        const result = await api.downloadArtifact(materialsTaskId, value);
        assert.match(sent.url, new RegExp(`/tasks/${materialsTaskId}/artifacts/${value.artifact_id}/download$`));
        assert.doesNotMatch(sent.url, /synthetic-session|token|sha256/);
        assert.equal(sent.options.method, 'GET'); assert.equal(sent.options.cache, 'no-store'); assert.equal(sent.options.redirect, 'error');
        assert.equal(sent.options.headers.Authorization, 'Bearer synthetic-session');
        assert.deepEqual(result.bytes, binaryBytes); assert.equal(result.blob.type, value.mime);
        assert.equal(result.blob.size, value.byte_size); assert.equal(result.download_name, value.download_name);
        assert.equal(result.mime, value.mime); assert.equal(result.byte_size, value.byte_size);
        assert.deepEqual(Object.keys(result).sort(), ['blob', 'byte_size', 'bytes', 'download_name', 'mime']);
    }
});

test('Office response metadata must agree with the validated READY artifact', async () => {
    const value = await readyArtifact();
    for (const headers of [{ 'Content-Type': mimeTypes.docx }, { 'Content-Type': value.mime + '; charset=utf-8' },
        { 'Content-Length': '0' }, { 'Content-Length': '10485761' }, { 'Content-Length': '6, 6' },
        { 'Content-Length': '7' }, { 'Content-Disposition': 'inline; filename="secret.pptx"' },
        { 'Content-Disposition': "attachment; filename*=UTF-8''..%2Fsecret.pptx" },
        { 'Content-Disposition': "attachment; filename*=UTF-8''%00secret.pptx" },
        { 'Content-Disposition': "attachment; filename*=UTF-8''other.pptx" },
        { 'Content-Disposition': "attachment; filename*=UTF-8''%FF.pptx" },
        { 'Content-Disposition': "attachment; filename*=ISO-8859-1''lesson.pptx" },
        { 'Content-Disposition': `attachment; filename*=UTF-8''${encodeURIComponent(value.download_name)}; filename*=UTF-8''other.pptx` }]) {
        await assert.rejects(apiFor(async () => binaryResponse(value, headers)).downloadArtifact(materialsTaskId, value), failure('invalid_response', 200));
    }
    for (const name of ['Content-Type', 'Content-Length', 'Content-Disposition']) {
        const result = binaryResponse(value); result.headers.delete(name);
        await assert.rejects(apiFor(async () => result).downloadArtifact(materialsTaskId, value), failure('invalid_response', 200));
    }
});

test('Office payload rejects byte length and SHA256 mismatches', async () => {
    const value = await readyArtifact();
    for (const bytes of [binaryBytes.slice(1), new Uint8Array([...binaryBytes, 100]), Uint8Array.from(binaryBytes, item => item ^ 1)]) {
        await assert.rejects(apiFor(async () => binaryResponse(value, {}, bytes)).downloadArtifact(materialsTaskId, value), failure('invalid_response', 200));
    }
});

test('bounded readers cancel JSON and Office streams at the first oversized chunk', async () => {
    for (const binary of [false, true]) {
        let cancelled = false, reads = 0;
        const stream = new ReadableStream({ pull(controller) { reads++; controller.enqueue(new Uint8Array(binary ? 7 : 262145)); },
            cancel() { cancelled = true; } });
        const value = await readyArtifact();
        const res = binary ? binaryResponse(value, {}, stream) : new Response(stream);
        const api = apiFor(async () => res);
        await assert.rejects(binary ? api.downloadArtifact(materialsTaskId, value) : api.getPackagesCapabilities(), failure('invalid_response', 200));
        assert.equal(cancelled, true); assert.ok(reads <= 2);
    }
});

test('Office streams cancel and return no bytes after session replacement or explicit abort', async () => {
    for (const replaceSession of [true, false]) {
        let token = 'synthetic-session', cancelled = false; const abort = new AbortController();
        const value = await readyArtifact();
        const stream = new ReadableStream({ pull(controller) {
            if (replaceSession) token = 'replacement'; else abort.abort();
            controller.enqueue(binaryBytes);
        }, cancel() { cancelled = true; } });
        const api = apiFor(async () => binaryResponse(value, {}, stream), { getToken: () => token });
        await assert.rejects(api.downloadArtifact(materialsTaskId, value, { signal: abort.signal }), failure('request_aborted'));
        assert.equal(cancelled, true);
    }
});

test('download preflight rejects non-READY artifacts and redirects without exposing credentials', async () => {
    let reads = 0, fetches = 0;
    const api = apiFor(async () => { fetches++; return new Response(); }, { getToken: () => { reads++; return 'synthetic-session'; } });
    await assert.rejects(api.downloadArtifact(materialsTaskId, artifact()), failure('invalid_input'));
    await assert.rejects(api.downloadArtifact('secret', await readyArtifact()), failure('invalid_input'));
    assert.equal(reads, 0); assert.equal(fetches, 0);
    const value = await readyArtifact(), redirected = binaryResponse(value); Object.defineProperty(redirected, 'redirected', { value: true });
    await assert.rejects(apiFor(async () => redirected).downloadArtifact(materialsTaskId, value), failure('invalid_response', 200));
});

test('package JSON full-response budget accepts its inclusive byte boundary and rejects malformed UTF-8', async () => {
    const raw = JSON.stringify({ code: 200, message: 'ok', data: caps() });
    const padded = raw + ' '.repeat(262144 - new TextEncoder().encode(raw).byteLength);
    assert.deepEqual(await apiFor(async () => new Response(padded)).getPackagesCapabilities(), caps());
    await assert.rejects(apiFor(async () => new Response(padded + ' ')).getPackagesCapabilities(), failure('invalid_response', 200));
    await assert.rejects(apiFor(async () => new Response(Uint8Array.of(0xff, 0xfe))).getPackagesCapabilities(), failure('invalid_response', 200));
});

test('Office maximum byte bound is inclusive and every downloaded byte is integrity checked', async () => {
    const bytes = new Uint8Array(10485760); bytes.set(binaryBytes);
    const value = await readyArtifact(); value.byte_size = bytes.byteLength;
    value.sha256 = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), byte => byte.toString(16).padStart(2, '0')).join('');
    const result = await apiFor(async () => binaryResponse(value, {}, bytes)).downloadArtifact(materialsTaskId, value);
    assert.equal(result.bytes.byteLength, 10485760); assert.equal(result.blob.size, 10485760);
    assert.deepEqual(result.bytes.slice(0, binaryBytes.byteLength), binaryBytes);
});

test('package receipt cannot assert a later attempt than its current run', () => {
    const value = snapshot('retry');
    assert.throws(() => validator('validatePackageSnapshot')(value), failure('invalid_response'));
    value.run.attempt = 2; assert.deepEqual(validator('validatePackageSnapshot')(value), value);
    value.receipt.operation = 'create'; value.receipt.attempt = 1; value.receipt.replayed = true;
    assert.deepEqual(validator('validatePackageSnapshot')(value), value);
});

test('download cancellation releases unread response bodies when metadata is rejected', async () => {
    let cancelled = false;
    const value = await readyArtifact();
    const stream = new ReadableStream({ pull(controller) { controller.enqueue(binaryBytes); }, cancel() { cancelled = true; } });
    await assert.rejects(apiFor(async () => binaryResponse(value, { 'Content-Type': 'text/html' }, stream))
        .downloadArtifact(materialsTaskId, value), failure('invalid_response', 200));
    assert.equal(cancelled, true);
});

test('READY history artifacts may remain unavailable when the server cannot verify stored bytes', () => {
    const value = history(); value.items[0].stage = 'COMPLETE';
    for (const artifact of value.items[0].artifacts) { artifact.state = 'READY'; artifact.download_available = false; }
    assert.deepEqual(validator('validatePackageHistory')(value), value);
    value.items[0].artifacts[0].download_available = true;
    assert.deepEqual(validator('validatePackageHistory')(value), value);
});

test('paged history never returns its exclusive before cursor as a page item', async () => {
    await assert.rejects(apiFor(async () => response(history())).listPackages(materialsTaskId, { before: versionId }), failure('invalid_response', 200));
});

test('JSON errors over the response byte budget are cancelled without retaining remote content', async () => {
    let cancelled = false;
    const stream = new ReadableStream({ pull(controller) { controller.enqueue(new Uint8Array(262145)); }, cancel() { cancelled = true; } });
    await assert.rejects(apiFor(async () => new Response(stream, { status: 503 })).getPackagesCapabilities(), failure('invalid_response', 503));
    assert.equal(cancelled, true);
});

test('package validators reject sparse arrays and hidden nested array metadata', () => {
    for (const mutate of [value => { value.artifacts = Array(2); }, value => { delete value.artifacts[0]; },
        value => { value.artifacts.owner_subject = 'secret'; }, value => { value.version.slides = Array(6); },
        value => { value.version.slides[0].body = Array(1); }, value => { value.version.lesson.citations = Array(1); },
        value => { value.version.lesson.objectives.owner_subject = 'secret'; }, value => { value.version.source_snapshots.owner_subject = 'secret'; }]) {
        const value = snapshot(); mutate(value); assert.throws(() => validator('validatePackageSnapshot')(value), failure('invalid_response'));
    }
});

test('UTF-8 download basenames support bounded non-BMP characters at the DTO name limit', async () => {
    const value = await readyArtifact(); value.download_name = '🧑'.repeat(195) + '.pptx';
    assert.equal([...value.download_name].length, 200);
    const decoded = await apiFor(async () => binaryResponse(value)).downloadArtifact(materialsTaskId, value);
    assert.equal(decoded.download_name, value.download_name);
});

test('native disabled package capabilities accept only confirmed reason literals on exactly false fields', async () => {
    for (const reason of ['private_exports_disabled', 'package_schema_unavailable', 'private_storage_unavailable', 'materials_unavailable']) {
        const value = Object.fromEntries(['create', 'read', 'retry', 'download', 'storage_configured'].map(name => [name, false]));
        value.reasons = Object.fromEntries(Object.keys(value).map(name => [name, reason]));
        const decoded = validator('validatePackageCapabilities')(value); assert.deepEqual(decoded, value); assert.notEqual(decoded.reasons, value.reasons);
        assert.deepEqual(await apiFor(async () => response(value)).getPackagesCapabilities(), value);
    }
    const storageOnly = { ...caps(), create: false, retry: false, download: false, storage_configured: false,
        reasons: { create: 'private_storage_unavailable', retry: 'private_storage_unavailable', download: 'private_storage_unavailable', storage_configured: 'private_storage_unavailable' } };
    assert.deepEqual(validator('validatePackageCapabilities')(storageOnly), storageOnly);
    for (const mutate of [value => { value.reasons.read = 'materials_unavailable'; }, value => { delete value.reasons.download; },
        value => { value.reasons.download = 'unknown_private_package_reason'; }, value => { value.reasons.download = null; },
        value => { value.reasons.owner_subject = 'secret'; }]) {
        const value = structuredClone(storageOnly); mutate(value); assert.throws(() => validator('validatePackageCapabilities')(value), failure('invalid_response'));
    }
});

test('native package 422 request codes are exact rather than accepting guessed command suffixes', async () => {
    for (const code of ['INVALID_PRIVATE_PACKAGE_REQUEST', 'INVALID_PRIVATE_PACKAGE_RETRY_REQUEST', 'INVALID_PRIVATE_PACKAGE_LIST_REQUEST']) {
        await assert.rejects(apiFor(async () => response(null, 422, code)).getPackagesCapabilities(), failure('invalid_input', 422));
    }
    for (const code of ['INVALID_PRIVATE_PACKAGE_CREATE_REQUEST', 'INVALID_PRIVATE_PACKAGE_DOWNLOAD_REQUEST', 'INVALID_PRIVATE_PACKAGE_SECRET_REQUEST']) {
        await assert.rejects(apiFor(async () => response(null, 422, code)).getPackagesCapabilities(), failure('request_failed', 422));
    }
});

test('unconfirmed package download 404 codes stay generic rather than incorrectly declaring the task missing', async () => {
    const value = await readyArtifact();
    await assert.rejects(apiFor(async () => response(null, 404, 'ARTIFACT_NOT_FOUND')).downloadArtifact(materialsTaskId, value), failure('request_failed', 404));
    await assert.rejects(apiFor(async () => response(null, 404, 'PRIVATE_PACKAGE_NOT_FOUND')).getPackage(materialsTaskId, versionId), failure('request_failed', 404));
});
