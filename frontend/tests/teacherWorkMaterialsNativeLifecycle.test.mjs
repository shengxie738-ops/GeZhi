import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { createTeacherWorkApi } from '../js/api/teacherWork.js';
import TeacherWork from '../js/components/teacher-work/TeacherWork.js';
import { Vue, globals, authRefs, settle, response, capabilityFacts, mount, button, textOf } from './fixtures/teacherWorkHarness.mjs';

// Native captured material replies are replayed unchanged at the real fetch boundary.
// Supporting core task/catalog facts and uncaptured initial reads are explicitly synthetic.
// This does not run a server, database, application main, browser or external provider.
const fixtureURL = new URL('../../backend/tests/fixtures/teacher_work_private_materials_http_contract.native.json', import.meta.url);
const raw = readFileSync(fixtureURL), pin = '97ea4c47943162b99793082f1a013d4b1846ebdc33f4a0b287846759508d8f4a';
const captured = JSON.parse(raw), get = name => { const item = captured.examples.find(value => value.name === name); assert.ok(item, name); return item; };
const clone = value => JSON.parse(JSON.stringify(value));
const unchanged = () => { assert.deepEqual(readFileSync(fixtureURL), raw); assert.equal(createHash('sha256').update(raw).digest('hex'), pin); };
const instant = '2026-10-06T00:00:00+00:00';
const taskFor = (id, input, working, count, requirements = '') => ({ task_id: id, scope: 'private', title: '合成标题', topic: '合成主题', audience: '合成对象',
    duration_minutes: 45, target_slide_count: count, input_revision: input, working_revision: working, created_at: instant, updated_at: instant,
    working: { requirements, resource_ids: ['uncaptured-synthetic-resource'], needs_normalization_fields: [] } });
const initialFor = id => ({ task_id: id, input_revision: 1, working_revision: 1, last_outline_revision: 0, current_outline_id: null, outline: null,
    approval: null, source_status: 'unprepared', current_source_digest: 'f'.repeat(64), needs_normalization_fields: [], approval_eligible: false,
    approval_current: false, approval_blocker: 'NO_OUTLINE', receipt: null });
async function harness({ readName, postNames = [], initial = null, source = 'saved', serverTask = null }) {
    const first = get(source), taskId = first.request.path.split('/')[5], body = first.request.body;
    const seed = initial || get(readName).response.body.data;
    const count = body?.slides?.length || seed.outline?.slides.length || 8;
    let task = serverTask || taskFor(taskId, seed.input_revision, seed.working_revision, count), read = readName, index = 0;
    const env = globals(), refs = authRefs(), calls = [], keys = postNames.map(name => get(name).request.idempotency_key);
    const api = createTeacherWorkApi({ getToken: () => 'synthetic-native-materials-replay-session', dispatchAuthExpired() {},
        fetchImpl: async (url, options) => {
            const path = new URL(url).pathname;
            if (path === '/api/teacher/work/capabilities') return response(200, { code: 200, message: 'ok', data: { ...capabilityFacts(), chat: false,
                generate: false, storage: false, structural_preview: false, private_tasks: { create: true, read: true, update: true } } });
            if (path === '/api/teacher/lesson-prep/resources') return response(200, { code: 200, message: 'ok', data: { resources: [] } });
            if (path === '/api/teacher/work/tasks/' + taskId) return response(200, { code: 200, message: 'ok', data: clone(task) });
            if (path === '/api/teacher/work/materials/capabilities') return response(get('capabilities_enabled').response.status, get('capabilities_enabled').response.body);
            if (options.method === 'GET') {
                if (!read) return response(200, { code: 200, message: 'ok', data: clone(initial) });
                const sample = get(read); assert.equal(path, sample.request.path); assert.equal(options.method, sample.request.method);
                return response(sample.response.status, sample.response.body);
            }
            const name = postNames[index++], sample = get(name); assert.ok(sample, 'no unexpected material mutation');
            assert.equal(path, sample.request.path); assert.equal(options.method, sample.request.method);
            assert.equal(options.headers['Idempotency-Key'], sample.request.idempotency_key); assert.deepEqual(JSON.parse(options.body), sample.request.body);
            calls.push({ name, body: options.body, key: options.headers['Idempotency-Key'] });
            if (sample.response.status === 200) task = { ...task, input_revision: sample.response.body.data.input_revision, working_revision: sample.response.body.data.working_revision };
            return response(sample.response.status, sample.response.body);
        } });
    const { useTeacherWork } = await import('../js/hooks/useTeacherWork.js');
    const scope = Vue.effectScope(), location = new URL('https://synthetic.invalid/?teacher_work_task=' + taskId); let key = 0;
    const hook = scope.run(() => useTeacherWork(refs, { api, storage: env.storage, eventTarget: env.eventTarget, documentTarget: document,
        viewportTarget: { innerWidth: 1440 }, location, history: { replaceState() {} }, newIdempotencyKey: () => keys[key++] }));
    await settle(); await hook.retryCapabilities(); await hook.readTask(taskId); await hook.retryMaterialsCapabilities();
    assert.equal(await hook.reloadMaterials(), true, 'captured or synthetic initial material read is ready'); await settle();
    return { hook, scope, calls, setRead(name) { read = name; }, taskId };
}
const edit = (hook, name) => { const body = get(name).request.body; hook.updateMaterialsDraft({ lesson: clone(body.lesson), slides: clone(body.slides) }); };

test('native saved-reopened-approved envelopes drive the actual Work lifecycle and compact review component', async () => {
    const h = await harness({ readName: 'empty', postNames: ['saved', 'approved'] });
    try { assert.equal(h.hook.state.materials.snapshot.outline, null); assert.equal(h.hook.state.materials.draft.lesson.title, '');
        h.hook.updateChatText('未发送问题'); edit(h.hook, 'saved'); assert.equal(await h.hook.saveMaterials(), true);
        assert.deepEqual(h.hook.state.materials.snapshot, get('saved').response.body.data); assert.equal(h.hook.state.working_revision, 2);
        h.setRead('reopened_saved'); assert.equal(await h.hook.reloadMaterials(), true); assert.equal(h.hook.state.materials.canApprove, true);
        const host = await mount(TeacherWork, { state: h.hook.state });
        try { assert.ok(textOf(host.root).includes('手动整理')); assert.equal(button(host.root, '编辑教案与幻灯片').props['aria-expanded'], false);
            assert.equal(button(host.root, '确认已审阅此保存版本').props.disabled, false);
        } finally { host.close(); }
        assert.equal(await h.hook.approveMaterials(), true); assert.deepEqual(h.hook.state.materials.snapshot, get('approved').response.body.data);
        assert.equal(h.hook.state.input_revision, 2); assert.equal(h.hook.state.working_revision, 3); assert.equal(h.hook.state.chatText, '未发送问题');
        h.setRead('reopened_approved'); assert.equal(await h.hook.reloadMaterials(), true); assert.equal(h.hook.state.materials.snapshot.approval_current, true);
        assert.equal(h.hook.state.materials.canApprove, false); assert.deepEqual(h.calls.map(value => value.name), ['saved', 'approved']); unchanged();
    } finally { h.scope.stop(); }
});

test('native lost save commit settles only with the original request and retains edits made before exact replay', async () => {
    const sample = get('unknown_save_commit'), id = sample.request.path.split('/')[5];
    const h = await harness({ source: 'unknown_save_commit', initial: initialFor(id), postNames: ['unknown_save_commit', 'reconciled_save_commit'] });
    try { edit(h.hook, 'unknown_save_commit'); assert.equal(await h.hook.saveMaterials(), false);
        assert.equal(h.hook.state.materials.status, 'uncertain'); assert.equal(h.hook.state.materials.retryAvailable, true);
        const revised = clone(h.hook.state.materials.draft); revised.lesson.summary += ' 后续未保存编辑'; h.hook.updateMaterialsDraft(revised);
        assert.equal(await h.hook.saveMaterials(), false); assert.equal(await h.hook.retryMaterials(), true);
        assert.equal(h.calls[0].body, h.calls[1].body); assert.equal(h.calls[0].key, h.calls[1].key);
        assert.deepEqual(h.hook.state.materials.snapshot, get('reconciled_save_commit').response.body.data);
        assert.equal(h.hook.state.materials.draft.lesson.summary, revised.lesson.summary); assert.equal(h.hook.state.materials.dirty, true);
        assert.equal(h.hook.state.materials.canApprove, false); unchanged();
    } finally { h.scope.stop(); }
});

test('native changed source and pointer-cleared historical reads remain readable without false approval', async () => {
    for (const name of ['source_changed', 'stale_input']) {
        const sample = get(name), data = sample.response.body.data, id = data.task_id;
        const h = await harness({ source: name, readName: name, serverTask: taskFor(id, data.input_revision, data.working_revision, data.outline.slides.length) });
        try { assert.deepEqual(h.hook.state.materials.snapshot, data); assert.equal(h.hook.state.materials.canApprove, false);
            assert.equal(await h.hook.approveMaterials(), false); assert.equal(h.calls.length, 0);
            assert.equal(h.hook.state.materials.draft.lesson.title, data.outline.lesson.title); unchanged();
        } finally { h.scope.stop(); }
    }
});

test('native opaque legacy preservation and text precheck keep manual save separate from approval', async () => {
    for (const name of ['preserved_opaque_legacy', 'large_unicode_saved']) {
        const sample = get(name), id = sample.response.body.data.task_id, initial = initialFor(id);
        initial.needs_normalization_fields = clone(sample.response.body.data.needs_normalization_fields);
        const h = await harness({ source: name, initial, postNames: [name] });
        try { edit(h.hook, name); assert.equal(await h.hook.saveMaterials(), true);
            assert.deepEqual(h.hook.state.materials.snapshot, sample.response.body.data); assert.equal(h.hook.state.materials.canApprove, false);
            assert.equal(await h.hook.approveMaterials(), false); assert.equal(h.calls.length, 1);
            assert.deepEqual(h.hook.state.materials.draft.lesson, sample.request.body.lesson); unchanged();
        } finally { h.scope.stop(); }
    }
});

test('native exact whole-draft capacity saves all content while one-byte overflow preserves the unsaved draft', async () => {
    const exact = get('near_capacity_saved'), id = exact.response.body.data.task_id;
    const h = await harness({ source: 'near_capacity_saved', initial: initialFor(id), postNames: ['near_capacity_saved'] });
    try { edit(h.hook, 'near_capacity_saved'); assert.equal(await h.hook.saveMaterials(), true);
        h.setRead('near_capacity_reopened'); assert.equal(await h.hook.reloadMaterials(), true);
        assert.deepEqual(h.hook.state.materials.draft.lesson, exact.request.body.lesson); assert.equal(h.hook.state.materials.dirty, false); unchanged();
    } finally { h.scope.stop(); }
    const above = await harness({ source: 'one_byte_over_capacity_error', readName: 'one_byte_over_task_unchanged', postNames: ['one_byte_over_capacity_error'] });
    try { edit(above.hook, 'one_byte_over_capacity_error'); assert.equal(await above.hook.saveMaterials(), false);
        assert.equal(above.hook.state.materials.error.reason, 'private_draft_too_large'); assert.equal(above.hook.state.materials.retryAvailable, false);
        assert.equal(above.hook.state.input_revision, 1); assert.equal(above.hook.state.working_revision, 1); assert.equal(above.hook.state.materials.snapshot.outline, null);
        assert.deepEqual(above.hook.state.materials.draft.lesson, get('one_byte_over_capacity_error').request.body.lesson); assert.equal(above.hook.state.materials.dirty, true);
        const host = await mount(TeacherWork, { state: above.hook.state });
        try { assert.match(textOf(host.root), /整个任务草稿.*超过保存容量/); assert.match(textOf(host.root), /缩短/); }
        finally { host.close(); } unchanged();
    } finally { above.scope.stop(); }
});

test('native lost approval commit retries the exact saved tuple and leaves newer local content unapproved', async () => {
    const sample = get('reconciled_approve_commit'), data = sample.response.body.data;
    // The fixture does not capture this scenario's pre-approval GET. Use a clearly
    // synthetic initial projection carrying the unchanged captured immutable outline.
    const initial = { task_id: data.task_id, input_revision: data.input_revision, working_revision: data.working_revision - 1,
        last_outline_revision: data.last_outline_revision, current_outline_id: data.current_outline_id, outline: clone(data.outline),
        approval: null, source_status: 'current', current_source_digest: data.current_source_digest, needs_normalization_fields: [],
        approval_eligible: true, approval_current: false, approval_blocker: null, receipt: null };
    const h = await harness({ source: 'unknown_approve_commit', initial, postNames: ['unknown_approve_commit', 'reconciled_approve_commit'] });
    try { assert.equal(h.hook.state.materials.canApprove, true); assert.equal(await h.hook.approveMaterials(), false);
        assert.equal(h.hook.state.materials.status, 'uncertain'); assert.equal(h.hook.state.materials.retryAvailable, true);
        const edited = clone(h.hook.state.materials.draft); edited.lesson.summary += ' 尚未保存'; h.hook.updateMaterialsDraft(edited);
        assert.equal(await h.hook.retryMaterials(), true); assert.equal(h.calls[0].body, h.calls[1].body); assert.equal(h.calls[0].key, h.calls[1].key);
        assert.deepEqual(h.hook.state.materials.snapshot, data); assert.equal(h.hook.state.materials.snapshot.approval_current, true);
        assert.equal(h.hook.state.materials.dirty, true); assert.equal(h.hook.state.materials.canApprove, false);
        assert.equal(h.hook.state.materials.draft.lesson.summary, edited.lesson.summary); unchanged();
    } finally { h.scope.stop(); }
});
