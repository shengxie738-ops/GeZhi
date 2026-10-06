import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { createTeacherWorkApi } from '../js/api/teacherWork.js';
import { validateMaterialsSaveBody, validateMaterialsApprovalBody } from '../js/api/teacherWorkMaterials.js';

// Captured authenticated ASGI/MySQL exchanges, replayed only at the fetch boundary.
// No HTTP server, native database, browser, or external provider runs in these tests.
const fixtureURL = new URL('../../backend/tests/fixtures/teacher_work_private_materials_http_contract.native.json', import.meta.url);
const rawFixture = readFileSync(fixtureURL), fixtureSha = '97ea4c47943162b99793082f1a013d4b1846ebdc33f4a0b287846759508d8f4a';
const freeze = value => { if (value && typeof value === 'object') { Object.values(value).forEach(freeze); Object.freeze(value); } return value; };
const captured = freeze(JSON.parse(rawFixture)), examples = captured.examples;
const byName = name => { const value = examples.find(item => item.name === name); assert.ok(value, name); return value; };
const sha = value => createHash('sha256').update(value).digest('hex');
const unchanged = () => { assert.equal(sha(readFileSync(fixtureURL)), fixtureSha); assert.deepEqual(JSON.parse(rawFixture), captured); };
const errorReasons = { REVISION_CONFLICT: 'revision_conflict', OUTLINE_REVISION_CONFLICT: 'outline_revision_conflict',
    OUTLINE_APPROVAL_CONFLICT: 'outline_approval_conflict', IDEMPOTENCY_CONFLICT: 'idempotency_conflict', SOURCE_CHANGED: 'source_changed',
    MATERIAL_SOURCES_UNAVAILABLE: 'material_sources_unavailable', COMMIT_OUTCOME_UNKNOWN: 'request_failed', MATERIAL_RECEIPT_LIMIT: 'material_receipt_limit',
    PRIVATE_DRAFT_TOO_LARGE: 'private_draft_too_large', CURRENT_TEACHER_REQUIRED: 'teacher_required', NORMALIZATION_REQUIRED: 'normalization_required' };
function invoke(api, request, signal) {
    const options = { signal, ...(request.idempotency_key === null ? {} : { idempotencyKey: request.idempotency_key }) };
    if (request.path === '/api/teacher/work/materials/capabilities') return api.getMaterialsCapabilities(options);
    const match = /^\/api\/teacher\/work\/tasks\/([^/]+)\/(materials(?:\/approve)?|working)$/.exec(request.path);
    assert.ok(match, request.path); const [, taskId, route] = match;
    if (route === 'working') { assert.equal(request.method, 'PATCH'); return api.updateWorking(taskId, request.body, options); }
    if (request.method === 'GET') return api.getMaterials(taskId, options);
    assert.equal(request.method, 'POST');
    return route.endsWith('/approve') ? api.approveMaterials(taskId, request.body, options) : api.saveMaterials(taskId, request.body, options);
}
function replay(example) {
    let calls = 0; const controller = new AbortController();
    const api = createTeacherWorkApi({ getToken: () => 'synthetic-materials-contract-session', dispatchAuthExpired() { assert.fail('unexpected auth expiry'); },
        fetchImpl: async (url, options) => {
            calls++; assert.equal(new URL(url).pathname, example.request.path); assert.equal(options.method, example.request.method);
            assert.equal(options.cache, 'no-store'); assert.equal(options.credentials, undefined); assert.equal(options.signal, controller.signal);
            assert.equal(options.headers.Authorization, 'Bearer synthetic-materials-contract-session');
            assert.deepEqual(Object.keys(options.headers).sort(), ['Authorization', 'Content-Type', ...(example.request.idempotency_key === null ? [] : ['Idempotency-Key'])].sort());
            if (example.request.idempotency_key === null) assert.equal(options.headers['Idempotency-Key'], undefined);
            else assert.equal(options.headers['Idempotency-Key'], example.request.idempotency_key);
            if (example.request.body === null) assert.equal(options.body, undefined);
            else assert.deepEqual(JSON.parse(options.body), example.request.body, 'the captured request body must be sent unchanged');
            return { status: example.response.status, text: async () => JSON.stringify(example.response.body) };
        } });
    return { pending: invoke(api, example.request, controller.signal), calls: () => calls };
}

test('native material fixture hash provenance and all38 request envelopes remain immutable', () => {
    assert.equal(sha(rawFixture), fixtureSha); assert.equal(captured.format, 'gezhi-private-materials-http-native-v1');
    assert.equal(examples.length, 38); assert.equal(new Set(examples.map(item => item.name)).size, 38);
    assert.equal(captured.provenance.mysql_version, '8.4.10'); assert.equal(captured.provenance.synthetic_only, true);
    assert.equal(captured.provenance.no_app_main, true); assert.equal(captured.provenance.no_external_ai, true);
    assert.equal(captured.provenance.authorization_headers_omitted, true);
    assert.deepEqual(captured.provenance.http_one_byte_boundary, { passed: 1, original_payload_success_bytes: 65535,
        original_payload_refused_bytes: 65536, error: 'PRIVATE_DRAFT_TOO_LARGE' });
    for (const example of examples) {
        const bytes = new TextEncoder().encode(JSON.stringify(example.response.body)).byteLength;
        assert.equal(bytes, example.response_utf8_bytes, example.name); assert.ok(bytes <= 262144, example.name);
        assert.equal(example.response.body.code, example.response.status, example.name);
        if (example.request.method === 'POST') {
            const validate = example.request.path.endsWith('/approve') ? validateMaterialsApprovalBody : validateMaterialsSaveBody;
            assert.deepEqual(validate(example.request.body), example.request.body, example.name);
        }
    }
    unchanged();
});

for (const example of examples) {
    test('native material API replay: ' + example.name, async () => {
        const operation = replay(example);
        if (example.response.status === 200) assert.deepEqual(await operation.pending, example.response.body.data);
        else {
            const reason = errorReasons[example.response.body.message]; assert.ok(reason, example.name);
            await assert.rejects(operation.pending, caught => {
                assert.equal(caught.name, 'TeacherWorkError'); assert.equal(caught.reason, reason); assert.equal(caught.status, example.response.status);
                assert.equal(Object.hasOwn(caught, 'cause'), false);
                assert.doesNotMatch(caught.message, /COMMIT_OUTCOME_UNKNOWN|PRIVATE_DRAFT_TOO_LARGE|CURRENT_TEACHER_REQUIRED|gezhi-tw-native|synthetic-materials-contract-session/);
                assert.doesNotMatch(JSON.stringify(caught), /\/tmp\/|\/var\/|owner_subject|schema_name|synthetic-materials-contract-session/); return true;
            });
        }
        assert.equal(operation.calls(), 1, 'captured operations never repost automatically'); unchanged();
    });
}

test('native physical draft capacity preserves full65535-byte content and classifies one-byte overflow separately', async () => {
    const exact = byName('near_capacity_saved'), reopened = byName('near_capacity_reopened'), above = byName('one_byte_over_capacity_error'), untouched = byName('one_byte_over_task_unchanged');
    assert.equal(above.request.body.lesson.summary, exact.request.body.lesson.summary + 'x');
    assert.deepEqual({ ...above.request.body, lesson: { ...above.request.body.lesson, summary: exact.request.body.lesson.summary } }, exact.request.body);
    const saved = await replay(exact).pending, read = await replay(reopened).pending;
    assert.deepEqual(saved.outline.lesson, exact.request.body.lesson); assert.deepEqual(saved.outline.slides, exact.request.body.slides);
    assert.deepEqual(read, { ...saved, receipt: null });
    await assert.rejects(replay(above).pending, caught => caught.reason === 'private_draft_too_large' && caught.status === 422);
    const unchangedTask = await replay(untouched).pending;
    assert.equal(unchangedTask.input_revision, 1); assert.equal(unchangedTask.working_revision, 1); assert.equal(unchangedTask.outline, null); unchanged();
});

test('native replay keeps original receipts when current outline source or working state has advanced', async () => {
    const historical = await replay(byName('historical_save_replay')).pending;
    assert.equal(historical.receipt.replayed, true); assert.notEqual(historical.receipt.outline_id, historical.current_outline_id);
    assert.ok(historical.receipt.input_revision < historical.input_revision); assert.ok(historical.receipt.working_revision < historical.working_revision);
    const drift = await replay(byName('historical_approval_replay_after_source_change')).pending;
    assert.equal(drift.receipt.replayed, true); assert.equal(drift.source_status, 'changed'); assert.equal(drift.approval_current, false);
    for (const [unknown, reconciled] of [['unknown_save_commit', 'reconciled_save_commit'], ['unknown_approve_commit', 'reconciled_approve_commit']]) {
        assert.deepEqual(byName(unknown).request, byName(reconciled).request);
        await assert.rejects(replay(byName(unknown)).pending, caught => caught.reason === 'request_failed' && caught.status === 503);
        assert.equal((await replay(byName(reconciled)).pending).receipt.replayed, true);
    }
    unchanged();
});
