import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { Vue, globals, authRefs, deferred, settle, capabilityFacts, response, mount, button, textOf, find } from './fixtures/teacherWorkHarness.mjs';

const A = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', B = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const instant = '2026-10-06T12:00:00.123456Z';
const item = id => ({ task_id: id, title: id === A ? '历史任务 A' : '历史任务 B', created_at: instant, updated_at: instant });
const page = (ids = [B, A], more = false) => ({ items: ids.map(item), has_more: more, next_before: more ? ids.at(-1) : null });
const snapshot = id => ({ ...item(id), scope: 'private', topic: '主题', audience: '对象', duration_minutes: 45, target_slide_count: 8,
    input_revision: 1, working_revision: 1, working: { requirements: '', resource_ids: ['source'], needs_normalization_fields: [] } });
const facts = () => ({ ...capabilityFacts(), chat: false, private_tasks: { create: true, read: true, update: true } });
async function harness(overrides = {}) {
    const env = globals(), refs = authRefs(), location = new URL('https://synthetic.invalid/index.html?keep=yes'), reads = [], lists = [];
    const history = { replaceState(_a, _b, value) { location.href = new URL(value, location.href).href; } };
    const api = { getCapabilities: async () => facts(), getTask: async id => { reads.push(id); return snapshot(id); },
        listTasks: async options => { lists.push(options); return page(); }, ...overrides };
    const { useTeacherWork } = await import('../js/hooks/useTeacherWork.js');
    const scope = Vue.effectScope(), hook = scope.run(() => useTeacherWork(refs, { api, storage: env.storage,
        eventTarget: env.eventTarget, documentTarget: document, location, history, newIdempotencyKey: () => 'synthetic-key' }));
    await settle(); return { ...env, refs, location, reads, lists, hook, scope };
}

test('history API strictly decodes a bounded descending metadata-only page and canonical cursor', async () => {
    globals(); const { createTeacherWorkApi } = await import('../js/api/teacherWork.js'); const calls = [];
    const api = createTeacherWorkApi({ getToken: () => 'synthetic-token', fetchImpl: async (url, options) => {
        calls.push({ url, options }); return response(200, { code: 200, message: 'ok', data: page([A]) }); } });
    assert.deepEqual(await api.listTasks({ limit: 1, before: B }), page([A]));
    assert.ok(calls[0].url.endsWith(`/teacher/work/tasks?limit=1&before=${B}`));
    assert.equal(calls[0].options.method, 'GET'); assert.equal(calls[0].options.cache, 'no-store');
    for (const invalid of [{ limit: 0 }, { limit: 51 }, { limit: true }, { before: B.toUpperCase() }, { owner: 'other' }])
        await assert.rejects(api.listTasks(invalid), e => e.reason === 'invalid_input');
    assert.equal(calls.length, 1);
    for (const bad of [{ ...page(), items: [item(A), item(B)] }, { ...page(), items: [item(B), item(B)] },
        { ...page(), items: [{ ...item(B), owner_subject: 'other' }] }, { ...page(), next_before: A },
        { ...page(), has_more: true, next_before: B }, { ...page(), items: [{ ...item(B), created_at: '2026-02-30T12:00:00Z' }] }]) {
        const invalidApi = createTeacherWorkApi({ getToken: () => 'synthetic-token', fetchImpl: async () => response(200, { code: 200, message: 'ok', data: bad }) });
        await assert.rejects(invalidApi.listTasks(), e => e.reason === 'invalid_response');
    }
});

test('history loads for current verified teacher without selecting a task or calling a provider', async () => {
    const h = await harness(); try {
        assert.equal(h.lists.length, 1); assert.deepEqual(h.hook.state.taskHistory.items, page().items);
        assert.equal(h.hook.state.task_id, null); assert.deepEqual(h.reads, []);
        assert.ok(h.operations.filter(([action]) => action === 'set').every(([, key]) => key.endsWith(':ui:v1')));
        await h.hook.readTask(A); assert.deepEqual(h.hook.state.taskHistory.items, page().items);
    } finally { h.scope.stop(); }
});

test('load older uses only last server cursor, suppresses duplicates and preserves first page on error', async () => {
    const calls = [], h = await harness({ listTasks: async options => { calls.push(options); return calls.length === 1 ? page([B], true) : page([A]); } });
    try {
        assert.equal(await h.hook.loadOlderTasks(), true); assert.equal(calls[1].before, B);
        assert.deepEqual(h.hook.state.taskHistory.items.map(x => x.task_id), [B, A]);
        assert.equal(await h.hook.loadOlderTasks(), false); assert.equal(calls.length, 2);
    } finally { h.scope.stop(); }
});

test('an older-page failure preserves the existing items/cursor and explicit retry uses that same cursor', async () => {
    const calls = [], h = await harness({ listTasks: async options => { calls.push(options);
        if (calls.length === 1) return page([B], true);
        if (calls.length === 2) throw { reason: 'network_error' };
        return page([A]); } });
    try {
        assert.equal(await h.hook.loadOlderTasks(), false); assert.deepEqual(h.hook.state.taskHistory.items, page([B]).items);
        assert.equal(h.hook.state.taskHistory.next_before, B); assert.equal(h.hook.state.taskHistory.status, 'error');
        assert.equal(await h.hook.loadOlderTasks(), true); assert.equal(calls[1].before, calls[2].before);
    } finally { h.scope.stop(); }
});

test('closing read admission during a list flight closes its loading state and discards its late result', async () => {
    const pending = deferred(), h = await harness({ listTasks: () => pending.promise });
    try {
        h.hook.state.privateTaskAvailability.read = false;
        assert.equal(h.hook.state.taskHistory.status, 'idle');
        pending.resolve(page()); await settle(); assert.deepEqual(h.hook.state.taskHistory.items, []);
    } finally { h.scope.stop(); }
});

test('clicking the selected history item does not reload or abort an active save', async () => {
    const h = await harness(); try {
        await h.hook.readTask(A); h.hook.state.taskWriteBusy = true;
        assert.equal(await h.hook.requestTaskSwitch(A), true); assert.deepEqual(h.reads, [A]);
        assert.equal(h.hook.state.taskWriteBusy, true);
    } finally { h.scope.stop(); }
});

for (const outcome of ['success', 'error']) test(`late list ${outcome} cannot cross identity/view or clear a newer flight`, async () => {
    const pending = deferred(), newest = deferred(); let calls = 0;
    const h = await harness({ listTasks: () => ++calls === 1 ? pending.promise : newest.promise });
    try {
        h.refs.authEpoch.value++; await settle();
        assert.equal(h.hook.state.taskHistory.status, 'loading');
        if (outcome === 'success') pending.resolve(page([B])); else pending.reject({ reason: 'network_error' });
        await settle(); assert.equal(h.hook.state.taskHistory.status, 'loading'); assert.deepEqual(h.hook.state.taskHistory.items, []);
        newest.resolve(page([A])); await settle(); assert.deepEqual(h.hook.state.taskHistory.items, page([A]).items);
        h.refs.currentView.value = 't_lesson_prep'; await settle(); assert.deepEqual(h.hook.state.taskHistory.items, []);
    } finally { h.scope.stop(); }
});

test('dirty requirements, resources, slides and unsent chat require explicit switch confirmation', async () => {
    const h = await harness(); try {
        await h.hook.readTask(A); h.hook.updateInput('未保存需求'); h.hook.state.chatText = '未发送问题';
        h.hook.state.draftResourceIds = ['different']; h.hook.updateTargetSlides(9);
        assert.equal(await h.hook.requestTaskSwitch(B), false); assert.equal(h.hook.state.task_id, A);
        assert.equal(h.hook.state.taskSwitch.reason, 'dirty'); assert.deepEqual(h.reads, [A]);
        h.hook.cancelTaskSwitch(); assert.equal(h.hook.state.composerText, '未保存需求');
        await h.hook.requestTaskSwitch(B); assert.equal(await h.hook.confirmTaskSwitch(), true);
        assert.equal(h.hook.state.task_id, B); assert.equal(h.hook.state.composerText, ''); assert.deepEqual(h.reads, [A, B]);
    } finally { h.scope.stop(); }
});

for (const change of ['edit', 'material', 'revision', 'gate', 'auth']) test(`switch confirmation rechecks ${change} before discarding`, async () => {
    const h = await harness(); try {
        await h.hook.readTask(A); h.hook.updateInput('original'); await h.hook.requestTaskSwitch(B);
        if (change === 'edit') h.hook.updateInput('newer');
        if (change === 'material') h.hook.state.materials.draftEpoch++;
        if (change === 'revision') h.hook.state.working_revision++;
        if (change === 'gate') h.hook.state.privateTaskAvailability.read = false;
        if (change === 'auth') h.refs.authEpoch.value++;
        assert.equal(await h.hook.confirmTaskSwitch(), false); assert.ok(!h.reads.includes(B));
        if (change !== 'auth') assert.equal(h.hook.state.task_id, A);
        if (change === 'edit') assert.equal(h.hook.state.composerText, 'newer');
    } finally { h.scope.stop(); }
});

const blockers = [
    s => { s.chatStatus = 'sending'; }, s => { s.chatRun = { stage: 'PENDING' }; },
    s => { s.chatRetryAvailable = true; s.chatStatus = 'uncertain'; }, s => { s.taskWriteBusy = true; },
    s => { s.materials.status = 'saving'; }, s => { s.materials.retryAvailable = true; },
    s => { s.materialProposals.run = { stage: 'OUTLINE_RUNNING' }; }, s => { s.materialProposals.retryAvailable = true; },
    s => { s.packageWriteBusy = true; }, s => { s.packages.downloadBusy = A; },
    s => { s.packages.detail = { run: { stage: 'FILES_RUNNING' } }; }, s => { s.packages.status = 'uncertain'; },
    s => { s.createStatus = 'loading'; }, s => { s.operationError = { operation: 'save', reason: 'network_error' }; }
];
test('active and unknown operations block switching without aborting or discarding original request state', async () => {
    for (const block of blockers) {
        const h = await harness(); try {
            await h.hook.readTask(A); block(h.hook.state); const before = JSON.stringify(h.hook.state.chatRun);
            assert.equal(await h.hook.readTask(B), false); assert.equal(h.hook.state.task_id, A);
            assert.equal(h.hook.state.taskSwitch.reason, 'operation'); assert.equal(await h.hook.confirmTaskSwitch(), false);
            assert.equal(JSON.stringify(h.hook.state.chatRun), before); assert.deepEqual(h.reads, [A]);
        } finally { h.scope.stop(); }
    }
});

test('popstate selection and URL removal use the same guard and retain current locator on cancellation', async () => {
    const h = await harness(); try {
        await h.hook.readTask(A); h.hook.updateInput('保留');
        h.location.searchParams.set('teacher_work_task', B); h.eventTarget.dispatchEvent({ type: 'popstate' }); await settle();
        assert.equal(h.hook.state.task_id, A); assert.equal(h.location.searchParams.get('teacher_work_task'), A);
        h.hook.cancelTaskSwitch();
        h.location.searchParams.delete('teacher_work_task'); h.eventTarget.dispatchEvent({ type: 'popstate' }); await settle();
        assert.equal(h.hook.state.taskSwitch.reason, 'dirty'); assert.equal(h.hook.state.task_id, A);
        assert.equal(await h.hook.confirmTaskSwitch(), true); assert.equal(h.hook.state.task_id, null);
        assert.equal(h.location.searchParams.get('keep'), 'yes');
    } finally { h.scope.stop(); }
});

test('edited create form is protected, while failed task opens never fabricate a snapshot', async () => {
    const h = await harness({ getTask: async () => { throw { reason: 'task_not_found', status: 404 }; } }); try {
        h.hook.openCreateTask(); h.hook.updateCreateForm({ title: '未提交新任务' });
        assert.equal(await h.hook.requestTaskSwitch(B), false); assert.equal(h.hook.state.createForm.title, '未提交新任务');
        assert.equal(h.hook.state.taskSwitch.reason, 'dirty');
        assert.equal(await h.hook.confirmTaskSwitch(), false); assert.equal(h.hook.state.task, null);
        assert.equal(h.hook.state.operationError.reason, 'task_not_found');
    } finally { h.scope.stop(); }
});

test('explicit material abandonment clears only the current cache, never another task draft or uncertain operation', async () => {
    globals();
    const { createTeacherWorkState, synchronizeTeacherWork, clearTeacherTaskSelection, captureRequest, applyTeacherTaskSnapshot } = await import('../js/controllers/teacherWorkState.js');
    const { useTeacherWorkMaterials } = await import('../js/hooks/useTeacherWorkMaterials.js');
    const state = Vue.reactive(createTeacherWorkState()), scope = Vue.effectScope();
    const hook = scope.run(() => useTeacherWorkMaterials(state, { api: {
        getMaterialsCapabilities: async () => ({ save: true, read: true, approve: true, source_configured: true, files: false, reasons: { files: 'files_not_enabled' } }),
        getMaterials: async id => ({ task_id: id, input_revision: 1, working_revision: 1, last_outline_revision: 0,
            current_outline_id: null, outline: null, approval: null, source_status: 'unprepared', current_source_digest: 'a'.repeat(64),
            needs_normalization_fields: [], approval_eligible: false, approval_current: false, approval_blocker: 'NO_OUTLINE', receipt: null })
    } }));
    const select = async id => {
        clearTeacherTaskSelection(state); state.task_id = id; applyTeacherTaskSnapshot(state, captureRequest(state), snapshot(id)); await settle();
    };
    const edit = title => hook.updateMaterialsDraft({ ...JSON.parse(JSON.stringify(state.materials.draft)),
        lesson: { ...state.materials.draft.lesson, title } });
    try {
        synchronizeTeacherWork(state, { actor: 'teacher-a', role: 'teacher', authEpoch: 4, authVerified: true, active: true });
        await select(B); edit('保留 B 草稿'); await select(A); edit('放弃 A 草稿');
        const expected = { task_id: A, draftEpoch: state.materials.draftEpoch };
        assert.equal(hook.discardCurrentMaterialsDraft({ ...expected, draftEpoch: expected.draftEpoch - 1 }), false);
        state.materials.retryAvailable = true; assert.equal(hook.discardCurrentMaterialsDraft(expected), false);
        assert.equal(state.materials.draft.lesson.title, '放弃 A 草稿'); state.materials.retryAvailable = false;
        assert.equal(hook.discardCurrentMaterialsDraft(expected), true);
        await select(B); assert.equal(state.materials.draft.lesson.title, '保留 B 草稿'); assert.equal(state.materials.dirty, true);
        await select(A); assert.equal(state.materials.draft.lesson.title, ''); assert.equal(state.materials.dirty, false);
    } finally { scope.stop(); }
});

test('guard preserves the real chat hook original uncertain body and key for explicit replay', async () => {
    const calls = [], run = { run_id: B, task_id: A, kind: 'chat', input_revision: 1, stage: 'COMPLETE',
        attempt: 1, provider_call_count: 1, deadline: instant, cancelled_at: null, error_code: null };
    const h = await harness({ getCapabilities: async () => ({ ...facts(), chat: true,
        private_chat: { send: true, history: false, read_run: true, cancel: true, provider_configured: true, external_provider_verified: false } }),
        sendMessage: async (id, body, options) => { calls.push({ id, body: JSON.parse(JSON.stringify(body)), options });
            if (calls.length === 1) throw { reason: 'network_error' }; return run; } });
    try {
        await h.hook.readTask(A); h.hook.updateChatText('合成未知结果请求'); assert.equal(await h.hook.sendChat(), false);
        assert.equal(h.hook.state.chatRetryAvailable, true); assert.equal(await h.hook.requestTaskSwitch(B), false);
        assert.equal(calls[0].options.signal.aborted, false); assert.equal(h.hook.state.chatRetryAvailable, true);
        h.hook.cancelTaskSwitch(); assert.equal(await h.hook.retryChat(), true);
        assert.deepEqual(calls[1].body, calls[0].body); assert.equal(calls[1].options.idempotencyKey, calls[0].options.idempotencyKey);
        assert.deepEqual(h.reads, [A]);
    } finally { h.scope.stop(); }
});

test('new-task open and direct create cannot bypass an uncertain chat request or drop its frozen replay', async () => {
    const calls = [], created = [], h = await harness({ getCapabilities: async () => ({ ...facts(), chat: true,
        private_chat: { send: true, history: false, read_run: true, cancel: true, provider_configured: true, external_provider_verified: false } }),
        sendMessage: async (id, body, options) => { calls.push({ id, body: JSON.parse(JSON.stringify(body)), options }); throw { reason: 'network_error' }; },
        createTask: async body => { created.push(body); return snapshot(B); } });
    try {
        await h.hook.readTask(A); h.hook.updateChatText('未知聊天'); await h.hook.sendChat();
        assert.equal(h.hook.openCreateTask(), false); assert.equal(h.hook.state.taskSwitch.reason, 'operation'); h.hook.cancelTaskSwitch();
        h.hook.updateCreateForm({ title: '新任务', topic: '主题', audience: '对象', resource_ids: ['source'] });
        assert.equal(await h.hook.createTask(), false); assert.deepEqual(created, []); assert.equal(h.hook.state.task_id, A);
        h.hook.cancelTaskSwitch(); await h.hook.retryChat();
        assert.deepEqual(calls[1].body, calls[0].body); assert.equal(calls[1].options.idempotencyKey, calls[0].options.idempotencyKey);
    } finally { h.scope.stop(); }
});

test('new-task entry shares dirty confirmation and rechecks edits before opening its form', async () => {
    const h = await harness(); try {
        await h.hook.readTask(A); h.hook.updateInput('未保存旧任务');
        assert.equal(h.hook.openCreateTask(), false); assert.equal(h.hook.state.createOpen, false);
        h.hook.updateInput('弹窗之后编辑'); assert.equal(await h.hook.confirmTaskSwitch(), false);
        assert.equal(h.hook.state.composerText, '弹窗之后编辑');
        assert.equal(await h.hook.confirmTaskSwitch(), true); assert.equal(h.hook.state.createOpen, true);
        assert.equal(h.hook.state.task_id, A); assert.equal(h.hook.state.composerText, '');
    } finally { h.scope.stop(); }
});

test('a confirmed create does not replace the current task when another operation became uncertain during its wait', async () => {
    const pending = deferred(), h = await harness({ getCapabilities: async () => ({ ...facts(), chat: true,
        private_chat: { send: true, history: false, read_run: true, cancel: true, provider_configured: true, external_provider_verified: false } }),
        createTask: () => pending.promise, sendMessage: async () => { throw { reason: 'network_error' }; } });
    try {
        await h.hook.readTask(A); h.hook.updateCreateForm({ title: '新任务', topic: '主题', audience: '对象', resource_ids: ['source'] });
        const creating = h.hook.createTask(); h.hook.updateChatText('创建等待期间的未知请求'); await h.hook.sendChat();
        assert.equal(h.hook.state.chatRetryAvailable, true); pending.resolve(snapshot(B));
        assert.equal(await creating, true); assert.equal(h.hook.state.task_id, A); assert.equal(h.hook.state.chatRetryAvailable, true);
        assert.equal(h.hook.state.taskSwitch.target, B); assert.equal(h.hook.state.taskSwitch.reason, 'operation');
    } finally { h.scope.stop(); }
});

test('unknown working save survives normal edits and failed reads until authoritative same-task reconciliation', async () => {
    let readError = false, writes = 0;
    const h = await harness({ updateWorking: async () => { writes++; throw { reason: 'network_error' }; },
        getTask: async id => { if (readError) throw { reason: 'network_error' }; return snapshot(id); } });
    try {
        await h.hook.readTask(A); h.hook.updateInput('原保存内容'); assert.equal(await h.hook.saveWorking(), false);
        await h.hook.requestTaskSwitch(B); assert.equal(h.hook.state.taskSwitch.reason, 'operation'); h.hook.cancelTaskSwitch();
        h.hook.updateInput('继续编辑后仍未确认'); assert.equal(h.hook.state.operationError, null);
        const { default: TeacherWork } = await import('../js/components/teacher-work/TeacherWork.js');
        const view = await mount(TeacherWork, { state: h.hook.state });
        try { assert.equal(button(view.root, '保存需求').props.disabled, true);
            assert.ok(textOf(view.root).includes('保存结果尚未确认')); } finally { view.close(); }
        assert.equal(await h.hook.requestTaskSwitch(B), false); assert.equal(h.hook.state.taskSwitch.reason, 'operation');
        assert.equal(await h.hook.confirmTaskSwitch(), false); assert.equal(await h.hook.saveWorking(), false); assert.equal(writes, 1);
        readError = true; assert.equal(await h.hook.reloadTask(), false); assert.equal(h.hook.state.workingOutcomeUnknown, true);
        readError = false; assert.equal(await h.hook.reloadTask(), true); assert.equal(h.hook.state.workingOutcomeUnknown, false);
        assert.equal(h.hook.state.composerText, '继续编辑后仍未确认');
        await h.hook.requestTaskSwitch(B); assert.equal(h.hook.state.taskSwitch.reason, 'dirty');
        assert.equal(await h.hook.confirmTaskSwitch(), true); assert.equal(h.hook.state.task_id, B);
    } finally { h.scope.stop(); }
});

test('desktop rail exposes loading, empty, retry, current selection, older pages and guarded dialog events', async () => {
    const h = await harness(); const { default: TeacherWork } = await import('../js/components/teacher-work/TeacherWork.js');
    const view = await mount(TeacherWork, { state: h.hook.state });
    try {
        await h.hook.readTask(A); await settle();
        const current = button(view.root, '历史任务 A'); assert.equal(current.props['aria-current'], 'true');
        button(view.root, '历史任务 B').props.onClick(); assert.equal(view.emitted['request-task-switch'][0][0], B);
        h.hook.updateInput('dirty'); await h.hook.requestTaskSwitch(B); await settle();
        assert.ok(find(view.root, n => n.props.role === 'dialog' && n.props['aria-modal'] === true));
        const artifacts = find(view.root, n => n.props.id === 'teacher-work-artifacts');
        assert.equal(artifacts.props.inert, '');
        button(view.root, '继续编辑').props.onClick(); button(view.root, '放弃未保存编辑并打开').props.onClick();
        assert.equal(view.emitted['cancel-task-switch'].length, 1); assert.equal(view.emitted['confirm-task-switch'].length, 1);
        assert.ok(!textOf(view.root).includes('owner_storage_id'));
        const main = readFileSync(new URL('../js/main.js', import.meta.url), 'utf8'), index = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
        for (const event of ['request-task-switch', 'confirm-task-switch', 'cancel-task-switch', 'reload-task-history', 'load-older-tasks'])
            assert.ok(index.includes('@' + event + '='), event);
        assert.ok(main.includes('teacherWorkRequestTaskSwitch: teacherWork.requestTaskSwitch'));
    } finally { view.close(); h.scope.stop(); }
});
