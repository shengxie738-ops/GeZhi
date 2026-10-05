import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { Vue, globals, authRefs, deferred, settle, capabilityFacts, response, mount, find, button, textOf } from './fixtures/teacherWorkHarness.mjs';

const taskA = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', taskB = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const facts = (private_tasks = { create: true, read: true, update: true }) => ({ ...capabilityFacts(),
    chat: false, generate: false, storage: false, structural_preview: false, private_tasks });
const snapshot = (task_id = taskA, revision = 1, requirements = '') => ({ task_id, scope: 'private', title: '循环教学', topic: '循环',
    audience: '一年级', duration_minutes: 45, target_slide_count: 8, input_revision: revision, working_revision: revision,
    created_at: '2026-10-05T20:00:00+00:00', updated_at: '2026-10-05T20:00:00+00:00',
    working: { requirements, resource_ids: ['courseware-one'], needs_normalization_fields: [] } });
const form = () => ({ title: '循环教学', topic: '循环', audience: '一年级', duration_minutes: 45, target_slide_count: 8,
    resource_ids: ['courseware-one'], scope: 'private' });
const envelope = data => ({ code: 200, message: 'ok', data });
const catalog = () => ({ resources: [{ id: 'courseware-one', name: '循环课件.pdf', course: '程序设计', extension: '.pdf',
    frontend_url: '/private/path', filename: '循环课件.pdf', searchable: true, size_bytes: 1, index_status: 'NOT_INDEXED' }],
    summary: { total: 1 }, filtered_total: 1 });
async function harness(overrides = {}, url = 'https://example.invalid/index.html?keep=yes') {
    const env = globals(), refs = authRefs(), location = new URL(url), writes = [];
    const history = { replaceState(_state, _title, value) { writes.push(value); const next = new URL(value, location.href);
        location.href = next.href; } };
    const api = { getCapabilities: async () => facts(), listResources: async () => catalog().resources.map(({ id, name, course, extension }) => ({ id, name, course, extension })),
        createTask: async () => snapshot(), getTask: async id => snapshot(id), updateWorking: async (id, body) => ({ ...snapshot(id, body.expected_revision + 1, body.changes.requirements ?? ''),
            target_slide_count: body.changes.target_slide_count ?? 8, working: { requirements: body.changes.requirements ?? '',
                resource_ids: body.changes.resource_ids ?? ['courseware-one'], needs_normalization_fields: [] } }), ...overrides };
    const { useTeacherWork } = await import('../js/hooks/useTeacherWork.js');
    const scope = Vue.effectScope(), hook = scope.run(() => useTeacherWork(refs, { api, storage: env.storage, eventTarget: env.eventTarget,
        viewportTarget: { innerWidth: 1440 }, documentTarget: document, location, history, newIdempotencyKey: () => 'key-' + ++keyIndex }));
    await settle();
    return { ...env, refs, scope, hook, location, writes };
}
let keyIndex = 0;
const fill = hook => hook.updateCreateForm(form());

test('private capabilities are explicit, optional for old servers, and cannot open unrelated adapters', async () => {
    globals(); const { createTeacherWorkApi } = await import('../js/api/teacherWork.js');
    for (const [data, enabled] of [[capabilityFacts(), false], [facts(), true]]) {
        const api = createTeacherWorkApi({ getToken: () => 'session', fetchImpl: async () => response(200, envelope(data)) });
        const result = await api.getCapabilities();
        assert.deepEqual(result.private_tasks, { create: enabled, read: enabled, update: enabled });
    }
    const { hook, scope } = await harness({ getCapabilities: async () => capabilityFacts() });
    try { assert.deepEqual(hook.state.privateTaskAvailability, { create: false, read: false, update: false });
        assert.equal(await hook.createTask(), false); assert.equal(hook.state.operationAvailability.chat, false);
    } finally { scope.stop(); }
});

test('private transport uses only approved methods and validates DTO/body without owner/path leakage', async () => {
    globals(); const { createTeacherWorkApi } = await import('../js/api/teacherWork.js'), calls = [];
    const api = createTeacherWorkApi({ getToken: () => 'session', fetchImpl: async (url, options) => {
        calls.push({ url, options }); return response(200, envelope(url.endsWith('/resources') ? catalog() : snapshot())); } });
    const controller = new AbortController();
    assert.deepEqual(await api.listResources({ signal: controller.signal }), [{ id: 'courseware-one', name: '循环课件.pdf', course: '程序设计', extension: '.pdf' }]);
    assert.deepEqual(await api.createTask(form(), { idempotencyKey: 'key-retry', signal: controller.signal }), snapshot());
    await api.getTask(taskA, { signal: controller.signal });
    await api.updateWorking(taskA, { expected_revision: 1, changes: { requirements: '' } }, { signal: controller.signal });
    assert.deepEqual(calls.map(call => call.options.method), ['GET', 'POST', 'GET', 'PATCH']);
    assert.ok(calls[0].url.endsWith('/api/teacher/lesson-prep/resources'));
    assert.equal(calls[1].options.headers['Idempotency-Key'], 'key-retry');
    assert.deepEqual(JSON.parse(calls[1].options.body), form());
    assert.deepEqual(JSON.parse(calls[3].options.body), { expected_revision: 1, changes: { requirements: '' } });
    for (const invalid of [{ ...form(), scope: 'offering', offering_id: taskA }, { ...form(), resource_ids: [] },
        { ...form(), title: ' ' }, { ...form(), target_slide_count: 13 }, { ...form(), owner_subject: 'bad' }])
        await assert.rejects(api.createTask(invalid, { idempotencyKey: 'key-retry' }), error => error.reason === 'invalid_input');
    await assert.rejects(api.updateWorking(taskA, { expected_revision: 1, changes: {} }), error => error.reason === 'invalid_input');
    assert.equal(calls.length, 4);
    for (const invalid of [{ ...snapshot(), owner_subject: 'secret' }, { ...snapshot(), scope: 'offering' },
        { ...snapshot(), working_revision: 0 }, { ...snapshot(), working: { ...snapshot().working, requirements: 'x'.repeat(4001) } }]) {
        const bad = createTeacherWorkApi({ getToken: () => 'session', fetchImpl: async () => response(200, envelope(invalid)) });
        await assert.rejects(bad.getTask(taskA), error => error.reason === 'invalid_response');
    }
});

test('private transport fences token replacement during body and suppresses stale 401 expiry', async () => {
    globals(); const { createTeacherWorkApi } = await import('../js/api/teacherWork.js');
    for (const status of [200, 401]) {
        let token = 'old', expired = 0; const body = deferred();
        const api = createTeacherWorkApi({ getToken: () => token, dispatchAuthExpired: () => expired++,
            fetchImpl: async () => ({ status, text: () => body.promise }) });
        const pending = api.getTask(taskA); await settle(); token = 'new'; body.resolve(JSON.stringify(envelope(snapshot())));
        await assert.rejects(pending, error => error.reason === 'request_aborted'); assert.equal(expired, 0);
    }
    const api = createTeacherWorkApi({ getToken: () => 'session', fetchImpl: async () => response(409, { code: 409, message: 'REVISION_CONFLICT', data: null }) });
    await assert.rejects(api.updateWorking(taskA, { expected_revision: 1, changes: { requirements: 'copyable' } }),
        error => error.reason === 'revision_conflict' && error.status === 409);
});

test('creation submits once, retains retry key on failure, replaces key after form edits, and selects real snapshot', async () => {
    const first = deferred(), calls = [], second = deferred();
    const h = await harness({ createTask(body, options) { calls.push({ body, options }); return calls.length === 1 ? first.promise : second.promise; } });
    try {
        fill(h.hook); const creating = h.hook.createTask(); assert.equal(await h.hook.createTask(), false); assert.equal(calls.length, 1);
        first.reject(Object.assign(new Error('private error'), { reason: 'network_error' })); assert.equal(await creating, false);
        assert.equal(h.hook.state.createForm.title, '循环教学'); assert.equal(h.hook.state.task_id, null);
        const retry = h.hook.createTask(); assert.equal(calls.length, 2); assert.equal(calls[1].options.idempotencyKey, calls[0].options.idempotencyKey);
        second.resolve(snapshot()); assert.equal(await retry, true); assert.equal(h.hook.state.task_id, taskA);
        assert.equal(h.hook.state.working_revision, 1); assert.equal(h.hook.state.composerStatus, 'saved');
        assert.equal(h.location.searchParams.get('teacher_work_task'), taskA); assert.equal(h.location.searchParams.get('keep'), 'yes');
        assert.ok(h.operations.filter(([action]) => action === 'set').every(([, key]) => key.endsWith(':ui:v1')));
        h.hook.openCreateTask(); fill(h.hook); h.hook.updateCreateForm({ topic: '新的主题' });
        const failed = h.hook.createTask(); await failed;
        assert.notEqual(calls.at(-1).options.idempotencyKey, calls[0].options.idempotencyKey);
    } finally { h.scope.stop(); }
});

test('URL refresh reads only explicit read capability and error never fabricates current task', async () => {
    let reads = 0;
    const closed = await harness({ getCapabilities: async () => capabilityFacts(), getTask: async () => { reads++; return snapshot(); } },
        `https://example.invalid/index.html?teacher_work_task=${taskA}&keep=yes`);
    try { assert.equal(reads, 0); assert.equal(closed.hook.state.task_id, null); } finally { closed.scope.stop(); }
    const open = await harness({ getTask: async id => { reads++; return snapshot(id, 3, '服务器需求'); } },
        `https://example.invalid/index.html?teacher_work_task=${taskA}&keep=yes`);
    try { assert.equal(reads, 1); assert.equal(open.hook.state.task_id, taskA); assert.equal(open.hook.state.composerText, '服务器需求');
        assert.equal(open.hook.state.working_revision, 3);
    } finally { open.scope.stop(); }
});

test('save is explicit, successful server snapshot alone marks saved, and editing during save keeps newer draft', async () => {
    const pending = deferred(), calls = [], h = await harness({ updateWorking(id, body, options) { calls.push({ id, body, options }); return pending.promise; } });
    try {
        await h.hook.readTask(taskA); h.hook.updateInput('准备保存'); assert.equal(calls.length, 0); assert.equal(h.hook.state.composerStatus, 'unsaved');
        const save = h.hook.saveWorking(); assert.equal(await h.hook.saveWorking(), false); assert.equal(calls.length, 1);
        assert.deepEqual(calls[0].body, { expected_revision: 1, changes: { requirements: '准备保存' } });
        h.hook.updateInput('发送后继续编辑'); pending.resolve(snapshot(taskA, 2, '准备保存')); assert.equal(await save, true);
        assert.equal(h.hook.state.composerText, '发送后继续编辑'); assert.equal(h.hook.state.working_revision, 2);
        assert.equal(h.hook.state.composerStatus, 'unsaved'); assert.deepEqual(h.hook.state.messages, []); assert.deepEqual(h.hook.state.artifacts, []);
    } finally { h.scope.stop(); }
});

test('409 preserves draft and reload rebases without overwriting edits or replaying PATCH', async () => {
    let writes = 0, reads = 0; const h = await harness({ getTask: async id => snapshot(id, ++reads, reads === 1 ? '' : '其他页面需求'),
        updateWorking: async () => { writes++; throw Object.assign(new Error('conflict'), { reason: 'revision_conflict', status: 409 }); } });
    try {
        await h.hook.readTask(taskA); h.hook.updateInput('当前编辑'); assert.equal(await h.hook.saveWorking(), false);
        assert.equal(h.hook.state.composerText, '当前编辑'); assert.equal(h.hook.state.composerStatus, 'unsaved'); assert.equal(h.hook.state.taskConflict, true);
        await h.hook.reloadTask(); assert.equal(h.hook.state.composerText, '当前编辑'); assert.equal(h.hook.state.working_revision, 2);
        assert.equal(h.hook.state.composerStatus, 'unsaved'); assert.equal(writes, 1); assert.equal(h.hook.state.taskConflict, false);
    } finally { h.scope.stop(); }
});

test('late read cannot overwrite newer editing, task selection, account, departed view, or unmount', async () => {
    for (const action of ['edit', 'task', 'account', 'view', 'unmount']) {
        const pending = deferred(), calls = [], h = await harness({ getTask(id, options) { calls.push({ id, options }); return calls.length === 1 ? Promise.resolve(snapshot(id)) : pending.promise; } });
        try {
            await h.hook.readTask(taskA); const reading = h.hook.reloadTask();
            if (action === 'edit') h.hook.updateInput('保留晚于读取的编辑');
            if (action === 'task') { const other = h.hook.readTask(taskB); pending.resolve(snapshot(taskA, 2, 'old')); await other; }
            if (action === 'account') h.refs.actor.value = 'teacher-b';
            if (action === 'view') h.refs.currentView.value = 't_lesson_prep';
            if (action === 'unmount') h.scope.stop();
            pending.resolve(snapshot(taskA, 2, '过期内容')); await reading; await settle();
            if (action === 'edit') assert.equal(h.hook.state.composerText, '保留晚于读取的编辑');
            else assert.notEqual(h.hook.state.composerText, '过期内容');
            if (['account', 'view', 'unmount'].includes(action)) assert.equal(calls[1].options.signal.aborted, true);
        } finally { h.scope.stop(); }
    }
});

test('late create and save success are discarded after account or task switch', async () => {
    for (const operation of ['create', 'save']) {
        const pending = deferred(), calls = [], h = await harness({ [operation === 'create' ? 'createTask' : 'updateWorking'](...args) { calls.push(args); return pending.promise; } });
        try {
            let result;
            if (operation === 'create') { fill(h.hook); result = h.hook.createTask(); h.refs.actor.value = 'teacher-b'; }
            else { await h.hook.readTask(taskA); h.hook.updateInput('old'); result = h.hook.saveWorking(); await h.hook.readTask(taskB); }
            pending.resolve(snapshot(taskA, 2, 'stale')); assert.equal(await result, false);
            assert.notEqual(h.hook.state.composerText, 'stale'); assert.equal(calls[0].at(-1).signal.aborted, true);
        } finally { h.scope.stop(); }
    }
});

test('four-zone UI exposes only real private create/read/edit-save, keeps conflict copyable, and bridges events', async () => {
    const h = await harness(), component = (await import('../js/components/teacher-work/TeacherWork.js')).default;
    try {
        h.hook.openCreateTask(); const host = await mount(component, { state: h.hook.state });
        try { assert.equal(button(host.root, '新建任务').props.disabled, false);
            const createTrigger = button(host.root, '新建任务'), triggerEvent = { currentTarget: createTrigger };
            assert.ok(Object.hasOwn(createTrigger.props, 'data-teacher-work-create-trigger'));
            createTrigger.props.onClick(triggerEvent); assert.deepEqual(host.emitted['open-create-task'], [[triggerEvent]]);
            assert.ok(find(host.root, node => node.props.id === 'teacher-work-create-title'));
            const input = find(host.root, node => node.props.id === 'teacher-work-create-title'); input.props.onInput({ target: { value: '新标题' } });
            assert.deepEqual(host.emitted['update-create-form'].at(-1), [{ title: '新标题' }]);
            button(host.root, '创建私人任务').props.onClick(); assert.deepEqual(host.emitted['create-task'], [[]]);
            assert.ok(button(host.root, '发送').props.disabled); assert.doesNotMatch(textOf(host.root), /已保存/);
        } finally { host.close(); }
        await h.hook.readTask(taskA); h.hook.updateInput('可复制');
        const savedHost = await mount(component, { state: h.hook.state });
        try { assert.equal(button(savedHost.root, '保存需求').props.disabled, false);
            button(savedHost.root, '保存需求').props.onClick(); assert.deepEqual(savedHost.emitted['save-working'], [[]]);
            h.hook.state.taskConflict = true; await settle();
            assert.equal(button(savedHost.root, '保存需求').props.disabled, true);
            button(savedHost.root, '重新读取版本并保留编辑').props.onClick();
            assert.deepEqual(savedHost.emitted['reload-task'], [[]]); assert.match(textOf(savedHost.root), /未保存/);
            const input = find(savedHost.root, node => node.props.id === 'teacher-work-input');
            assert.equal(input.props.value, '可复制'); assert.ok(!input.props.disabled);
            h.hook.state.taskConflict = false; h.hook.state.composerStatus = 'saved'; await settle();
            assert.equal(button(savedHost.root, '保存需求').props.disabled, true);
            h.hook.state.createOpen = true; await settle(); assert.doesNotMatch(textOf(savedHost.root), /已保存/);
            h.hook.state.createOpen = false; h.hook.state.taskReadStatus = 'loading'; await settle();
            assert.equal(button(savedHost.root, '保存需求').props.disabled, true); assert.doesNotMatch(textOf(savedHost.root), /已保存/);
            h.hook.state.taskReadStatus = 'ready'; h.hook.state.composerStatus = 'saving'; await settle();
            assert.equal(button(savedHost.root, '保存需求').props.disabled, true);
            h.hook.state.composerStatus = 'unsaved'; await settle();
            assert.equal(button(savedHost.root, '保存需求').props.disabled, false);
            h.hook.state.createOpen = true; await settle();
            assert.equal(button(savedHost.root, '保存需求').props.disabled, true);
        } finally { savedHost.close(); }
        const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8'), main = readFileSync(new URL('../js/main.js', import.meta.url), 'utf8');
        for (const name of ['open-create-task', 'close-create-task', 'update-create-form', 'create-task', 'save-working',
            'reload-task', 'toggle-resource', 'update-target-slides', 'reload-resources'])
            assert.ok(html.includes('@' + name + '='), name);
        assert.match(main, /teacherWorkCreateTask:\s*teacherWork\.createTask/);
    } finally { h.scope.stop(); }
});

test('save failure retains all changed fields and retry posts latest explicit draft', async () => {
    const calls = [], h = await harness({ listResources: async () => [
        { id: 'courseware-one', name: 'one', course: 'course', extension: '.pdf' },
        { id: 'courseware-two', name: 'two', course: 'course', extension: '.pptx' }],
        updateWorking: async (id, body) => { calls.push({ id, body }); if (calls.length === 1) throw { reason: 'network_error' };
            return { ...snapshot(id, 2, body.changes.requirements), target_slide_count: body.changes.target_slide_count,
                working: { requirements: body.changes.requirements, resource_ids: body.changes.resource_ids, needs_normalization_fields: [] } }; } });
    try {
        await h.hook.readTask(taskA); await settle(); h.hook.updateInput('edited'); h.hook.toggleResource('courseware-two'); h.hook.updateTargetSlides(10);
        assert.equal(await h.hook.saveWorking(), false); assert.equal(h.hook.state.composerText, 'edited');
        assert.deepEqual(h.hook.state.draftResourceIds, ['courseware-one', 'courseware-two']); assert.equal(h.hook.state.draftTargetSlideCount, 10);
        assert.equal(h.hook.state.composerStatus, 'unsaved');
        assert.equal(await h.hook.saveWorking(), true);
        assert.deepEqual(calls[1].body, { expected_revision: 1, changes: { requirements: 'edited', resource_ids: ['courseware-one', 'courseware-two'], target_slide_count: 10 } });
        assert.equal(h.hook.state.composerStatus, 'saved');
    } finally { h.scope.stop(); }
});

test('reloaded identical draft still allows an explicit save confirmation without an empty PATCH', async () => {
    let reads = 0, writes = 0, sent; const h = await harness({ getTask: async id => snapshot(id, ++reads, reads === 1 ? '' : 'same'),
        updateWorking: async (id, body) => { writes++; sent = body; return snapshot(id, 3, 'same'); } });
    try {
        await h.hook.readTask(taskA); h.hook.updateInput('same'); h.hook.state.taskConflict = true;
        await h.hook.reloadTask(); assert.equal(h.hook.state.composerStatus, 'unsaved');
        assert.equal(await h.hook.saveWorking(), true); assert.equal(writes, 1);
        assert.deepEqual(sent, { expected_revision: 2, changes: { requirements: 'same' } });
        assert.equal(h.hook.state.composerStatus, 'saved');
    } finally { h.scope.stop(); }
});

test('modifying an in-flight creation aborts old result and uses a new key for new payload', async () => {
    const old = deferred(), calls = [], h = await harness({ createTask(body, options) { calls.push({ body, options }); return calls.length === 1 ? old.promise : Promise.resolve(snapshot(taskB)); } });
    try {
        h.hook.openCreateTask(); fill(h.hook); const before = h.hook.createTask(); h.hook.updateCreateForm({ topic: 'new topic' });
        assert.equal(calls[0].options.signal.aborted, true); const next = await h.hook.createTask(); assert.equal(next, true);
        assert.notEqual(calls[0].options.idempotencyKey, calls[1].options.idempotencyKey); assert.equal(calls[1].body.topic, 'new topic');
        old.resolve(snapshot(taskA)); assert.equal(await before, false); assert.equal(h.hook.state.task_id, taskB);
    } finally { h.scope.stop(); }
});

test('pending resource read never leaves permanent loading after successful save and stale catalog is discarded', async () => {
    const pending = deferred(), h = await harness({ listResources: () => pending.promise });
    try {
        await h.hook.readTask(taskA); h.hook.updateInput('save now'); assert.equal(await h.hook.saveWorking(), true);
        assert.notEqual(h.hook.state.resourcesStatus, 'loading');
        pending.resolve([{ id: 'courseware-stale', name: 'stale', course: 'old', extension: '.pdf' }]); await settle();
        assert.deepEqual(h.hook.state.resourceCatalog, []);
    } finally { h.scope.stop(); }
});

test('resource read is aborted on account change and cannot restore prior catalog or draft selections', async () => {
    const pending = deferred(), options = [], h = await harness({ listResources: opts => { options.push(opts); return options.length === 1 ? pending.promise : Promise.resolve([]); } });
    try {
        h.refs.actor.value = 'teacher-b'; assert.equal(options[0].signal.aborted, true);
        pending.resolve([{ id: 'courseware-old', name: 'old', course: 'old', extension: '.pdf' }]); await settle();
        assert.deepEqual(h.hook.state.resourceCatalog, []); assert.deepEqual(h.hook.state.draftResourceIds, []);
    } finally { h.scope.stop(); }
});

test('opening and cancelling a create form preserves the current task draft, locator, and pending-save copy', async () => {
    const h = await harness();
    try {
        await h.hook.readTask(taskA); h.hook.updateInput('保留当前草稿'); const url = h.location.href;
        assert.equal(h.hook.openCreateTask(), true); assert.equal(h.hook.state.task_id, taskA); assert.equal(h.hook.state.composerText, '保留当前草稿');
        h.hook.updateCreateForm({ title: '填写到一半' }); h.hook.openCreateTask(); assert.equal(h.hook.state.createForm.title, '填写到一半');
        h.hook.closeCreateTask(); assert.equal(h.hook.state.composerText, '保留当前草稿'); assert.equal(h.hook.state.composerStatus, 'unsaved');
        assert.equal(h.hook.state.taskReadStatus, 'ready'); assert.equal(h.location.href, url);
    } finally { h.scope.stop(); }
});

test('same-task reload aborts the resource flight tied to the old revision without permanent loading', async () => {
    const pending = deferred(), calls = []; let reads = 0;
    const h = await harness({ getTask: async id => snapshot(id, ++reads), listResources: options => {
        calls.push(options); return calls.length <= 2 ? pending.promise : Promise.resolve([]); } });
    try {
        await h.hook.readTask(taskA); await h.hook.reloadTask();
        assert.equal(calls[1].signal.aborted, true);
        pending.resolve([{ id: 'courseware-old', name: 'old', course: 'old', extension: '.pdf' }]); await settle();
        assert.notEqual(h.hook.state.resourcesStatus, 'loading'); assert.deepEqual(h.hook.state.resourceCatalog, []);
    } finally { h.scope.stop(); }
});

test('create form focus enters the title, returns to its live trigger, and rejects departed-view focus', async () => {
    const h = await harness(), focuses = [];
    const trigger = { isConnected: true, getClientRects: () => [{}], focus: () => focuses.push('trigger') };
    const title = { isConnected: true, getClientRects: () => [{}], focus: () => focuses.push('title') };
    const composer = { isConnected: true, getClientRects: () => [{}], focus: () => focuses.push('composer') };
    document.querySelector = selector => selector === '#teacher-work-create-title' ? title : selector === '[data-teacher-work-create-trigger]' ? trigger : composer;
    try {
        h.hook.openCreateTask({ currentTarget: trigger }); await settle(); assert.equal(focuses.at(-1), 'title');
        h.hook.closeCreateTask(); await settle(); assert.equal(focuses.at(-1), 'trigger');
        h.hook.openCreateTask({ currentTarget: trigger }); h.refs.currentView.value = 't_lesson_prep'; await settle();
        assert.deepEqual(focuses, ['title', 'trigger']);
    } finally { h.scope.stop(); }
});

test('creation cannot claim unsent requirements saved or overwrite editing during its request', async () => {
    for (const during of [false, true]) {
        const pending = deferred(), h = await harness({ createTask: () => pending.promise });
        try {
            h.hook.openCreateTask(); fill(h.hook); h.hook.updateInput('创建前需求'); const creating = h.hook.createTask();
            if (during) h.hook.updateInput('创建期间继续编辑');
            pending.resolve(snapshot()); assert.equal(await creating, true);
            assert.equal(h.hook.state.composerText, during ? '创建期间继续编辑' : '创建前需求');
            assert.equal(h.hook.state.composerStatus, 'unsaved'); assert.equal(h.hook.state.task.working.requirements, '');
            assert.deepEqual(h.hook.state.draftResourceIds, ['courseware-one']);
        } finally { h.scope.stop(); }
    }
});

test('global capability recheck remains usable when a pending save commits a newer task revision', async () => {
    const capability = deferred(), saving = deferred(); let checks = 0;
    const h = await harness({ getCapabilities: () => ++checks === 1 ? Promise.resolve(facts()) : capability.promise,
        updateWorking: () => saving.promise });
    try {
        await h.hook.readTask(taskA); h.hook.updateInput('new revision'); const save = h.hook.saveWorking();
        const recheck = h.hook.retryCapabilities(); saving.resolve(snapshot(taskA, 2, 'new revision')); assert.equal(await save, true);
        capability.resolve(facts()); assert.equal(await recheck, true);
        assert.equal(h.hook.state.capabilities.status, 'ready'); assert.deepEqual(h.hook.state.privateTaskAvailability, { create: true, read: true, update: true });
        assert.equal(h.hook.state.working_revision, 2);
    } finally { h.scope.stop(); }
});

test('Back navigation cancels a pending create and keeps its form retryable without late selection', async () => {
    const pending = deferred(), calls = [], h = await harness({ createTask(body, options) { calls.push({ body, options }); return calls.length === 1 ? pending.promise : Promise.resolve(snapshot(taskB)); } });
    try {
        await h.hook.readTask(taskA); h.hook.openCreateTask(); fill(h.hook); const creating = h.hook.createTask();
        h.location.searchParams.delete('teacher_work_task'); h.eventTarget.dispatchEvent({ type: 'popstate' });
        assert.equal(calls[0].options.signal.aborted, true); assert.notEqual(h.hook.state.createStatus, 'loading');
        pending.resolve(snapshot(taskA)); assert.equal(await creating, false); assert.equal(h.hook.state.task_id, null);
        assert.equal(await h.hook.createTask(), true); assert.equal(h.hook.state.task_id, taskB);
        assert.equal(calls[1].options.idempotencyKey, calls[0].options.idempotencyKey);
    } finally { h.scope.stop(); }
});

test('private create defaults do not coerce explicitly null numeric fields into valid values', async () => {
    globals(); const { createTeacherWorkApi } = await import('../js/api/teacherWork.js'); let requests = 0;
    const api = createTeacherWorkApi({ getToken: () => 'session', fetchImpl: async () => { requests++; return response(200, envelope(snapshot())); } });
    for (const name of ['duration_minutes', 'target_slide_count'])
        await assert.rejects(api.createTask({ ...form(), [name]: null }, { idempotencyKey: 'key' }), error => error.reason === 'invalid_input');
    assert.equal(requests, 0);
});

test('first read initializes resources and slides while preserving only genuinely typed requirements', async () => {
    for (const flow of ['failed-first', 'typed-pending']) {
        const pending = deferred(); let reads = 0;
        const data = { ...snapshot(taskA, 1, '服务器需求'), target_slide_count: 10 };
        const h = await harness({ getTask: () => ++reads === 1 ? pending.promise : Promise.resolve(data) });
        try {
            const first = h.hook.readTask(taskA);
            if (flow === 'failed-first') { pending.reject({ reason: 'network_error' }); await first; await h.hook.reloadTask(); }
            else { h.hook.updateInput('读取期间输入'); pending.resolve(data); await first; }
            assert.deepEqual(h.hook.state.draftResourceIds, ['courseware-one']); assert.equal(h.hook.state.draftTargetSlideCount, 10);
            assert.equal(h.hook.state.composerText, flow === 'failed-first' ? '服务器需求' : '读取期间输入');
            assert.equal(h.hook.state.composerStatus, flow === 'failed-first' ? 'saved' : 'unsaved');
        } finally { h.scope.stop(); }
    }
});

test('a malformed successful save never overwrites the draft or claims it was committed', async () => {
    const h = await harness({ updateWorking: async () => snapshot(taskA, 2, 'different server text') });
    try {
        await h.hook.readTask(taskA); h.hook.updateInput('requested text');
        assert.equal(await h.hook.saveWorking(), false); assert.equal(h.hook.state.composerText, 'requested text');
        assert.equal(h.hook.state.composerStatus, 'unsaved'); assert.equal(h.hook.state.working_revision, 1);
        assert.equal(h.hook.state.operationError.reason, 'invalid_response');
    } finally { h.scope.stop(); }
});

test('correcting target slide input clears its obsolete validation error', async () => {
    const h = await harness();
    try {
        await h.hook.readTask(taskA); assert.equal(h.hook.updateTargetSlides(5), false); assert.equal(h.hook.state.operationError.reason, 'invalid_input');
        assert.equal(h.hook.updateTargetSlides(10), true); assert.equal(h.hook.state.operationError, null);
    } finally { h.scope.stop(); }
});

test('a create form cannot save or change the previous task resources behind the new task form', async () => {
    const h = await harness();
    try {
        await h.hook.readTask(taskA); h.hook.updateInput('older draft'); await settle(); h.hook.openCreateTask();
        assert.equal(await h.hook.saveWorking(), false); assert.equal(h.hook.updateTargetSlides(10), false);
        assert.equal(h.hook.toggleResource('courseware-one'), false); assert.deepEqual(h.hook.state.draftResourceIds, ['courseware-one']);
        h.hook.closeCreateTask(); assert.equal(h.hook.state.composerText, 'older draft');
    } finally { h.scope.stop(); }
});

// These four envelopes were captured by the backend's actual native ASGI/MySQL run.
// The public responses below are loaded unchanged; only the existing resource-catalog
// dependency is a separate synthetic read stub. No server or network is started here.
const nativeContractURL = new URL('../../backend/tests/fixtures/teacher_work_private_http_contract.native.json', import.meta.url);
const nativeCreateRequest = () => ({ title: '合成标题', topic: '合成主题', audience: '合成对象',
    resource_ids: ['synthetic-resource'], scope: 'private' });
const nativePatchRequest = () => ({ expected_revision: 1,
    changes: { requirements: '合成编辑', resource_ids: ['synthetic-next'], target_slide_count: 9 } });
function capturedNativeContract() {
    const raw = readFileSync(nativeContractURL), captured = JSON.parse(raw);
    assert.equal(captured.provenance.origin, 'captured_native_asgi_mysql_responses');
    assert.equal(captured.provenance.responses_handwritten, false);
    assert.equal(captured.provenance.synthetic_data_only, true);
    assert.equal(captured.provenance.mysql_version, '8.4.10');
    assert.deepEqual(captured.provenance.native_test_selectors, [
        'test_private_capabilities_and_get_are_read_only_and_default_closed',
        'test_private_http_create_read_patch_persists_on_new_connection'
    ]);
    assert.ok(Object.values(captured.provenance.source_records_sha256).every(value => /^[0-9a-f]{64}$/.test(value)));
    assert.deepEqual(captured.create, captured.get);
    return { raw, captured };
}
async function nativeReplayApi(captured) {
    const { createTeacherWorkApi } = await import('../js/api/teacherWork.js'), calls = [];
    const id = captured.create.data.task_id;
    const api = createTeacherWorkApi({ getToken: () => 'synthetic-contract-session',
        dispatchAuthExpired() { assert.fail('captured success must not expire authentication'); },
        fetchImpl: async (url, options) => {
            const path = new URL(url).pathname; calls.push({ path, options });
            if (path === '/api/teacher/work/capabilities' && options.method === 'GET') return response(200, captured.capabilities);
            if (path === '/api/teacher/work/tasks' && options.method === 'POST') return response(200, captured.create);
            if (path === '/api/teacher/work/tasks/' + id && options.method === 'GET') return response(200, captured.get);
            if (path === '/api/teacher/work/tasks/' + id + '/working' && options.method === 'PATCH') return response(200, captured.patch);
            if (path === '/api/teacher/lesson-prep/resources' && options.method === 'GET') return response(200, envelope({ resources: [
                { id: 'synthetic-resource', name: '合成原资料.pdf', course: '合成课程', extension: '.pdf' },
                { id: 'synthetic-next', name: '合成新资料.pptx', course: '合成课程', extension: '.pptx' }
            ] }));
            assert.fail('unexpected replay route or method: ' + options.method + ' ' + path);
        } });
    return { api, calls };
}

test('captured native public envelopes match the actual API decoder, reasons, UTC, normalization, and request DTOs exactly', async () => {
    globals(); const { raw, captured } = capturedNativeContract(), { api, calls } = await nativeReplayApi(captured);
    assert.deepEqual(await api.getCapabilities(), captured.capabilities.data);
    assert.deepEqual(await api.createTask(nativeCreateRequest(), { idempotencyKey: 'synthetic-create' }), captured.create.data);
    assert.deepEqual(await api.getTask(captured.create.data.task_id), captured.get.data);
    assert.deepEqual(await api.updateWorking(captured.create.data.task_id, nativePatchRequest()), captured.patch.data);
    assert.deepEqual(captured.capabilities.data.private_tasks, { create: true, read: true, update: true });
    assert.equal(captured.capabilities.data.task_write, true);
    for (const name of ['chat', 'generate', 'storage', 'structural_preview', 'rendered_preview', 'publish'])
        assert.equal(captured.capabilities.data[name], false);
    assert.deepEqual(captured.capabilities.data.reasons, { chat: 'private_teacher_work_only', generate: 'private_teacher_work_only',
        storage: 'private_teacher_work_only', structural_preview: 'private_teacher_work_only',
        rendered_preview: 'rendered_preview_unsupported', publish: 'private_teacher_work_only' });
    for (const name of ['create', 'get', 'patch']) {
        assert.match(captured[name].data.created_at, /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z$/);
        assert.match(captured[name].data.updated_at, /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z$/);
        assert.deepEqual(captured[name].data.working.needs_normalization_fields, ['teaching_flow']);
        assert.deepEqual(Object.keys(captured[name].data.working).sort(), ['needs_normalization_fields', 'requirements', 'resource_ids']);
        for (const field of ['owner', 'owner_subject', 'owner_storage_id', 'institution_id', 'lesson_draft_id', 'payload', 'path'])
            assert.equal(Object.hasOwn(captured[name].data, field), false);
    }
    assert.deepEqual(calls.map(({ options }) => options.method), ['GET', 'POST', 'GET', 'PATCH']);
    assert.deepEqual(JSON.parse(calls[1].options.body), { ...nativeCreateRequest(), duration_minutes: 45, target_slide_count: 8 });
    assert.equal(calls[1].options.headers['Idempotency-Key'], 'synthetic-create');
    assert.deepEqual(JSON.parse(calls[3].options.body), nativePatchRequest());
    assert.deepEqual(readFileSync(nativeContractURL), raw, 'captured fixture remains byte-for-byte unchanged');
});

test('captured native envelopes drive the real API plus hook create-read-edit-save lifecycle without claiming generated content', async () => {
    const { raw, captured } = capturedNativeContract(), { api, calls } = await nativeReplayApi(captured);
    const { storage, eventTarget, operations } = globals(), refs = authRefs();
    const location = new URL('https://example.invalid/index.html?keep=yes');
    const history = { replaceState(_state, _title, value) { location.href = new URL(value, location.href).href; } };
    const { useTeacherWork } = await import('../js/hooks/useTeacherWork.js'), scope = Vue.effectScope();
    const hook = scope.run(() => useTeacherWork(refs, { api, storage, eventTarget, documentTarget: document,
        viewportTarget: { innerWidth: 1440 }, location, history, newIdempotencyKey: () => 'synthetic-create' }));
    try {
        await settle(); assert.equal(hook.state.capabilities.status, 'ready');
        assert.deepEqual(hook.state.capabilities.data, captured.capabilities.data);
        hook.openCreateTask(); hook.updateCreateForm(nativeCreateRequest());
        assert.equal(await hook.createTask(), true); assert.deepEqual(hook.state.task, captured.create.data);
        assert.equal(location.searchParams.get('teacher_work_task'), captured.create.data.task_id);
        assert.equal(location.searchParams.get('keep'), 'yes');
        assert.equal(await hook.reloadTask(), true); await settle(); assert.deepEqual(hook.state.task, captured.get.data);
        assert.deepEqual(hook.state.draftResourceIds, ['synthetic-resource']); assert.equal(hook.state.draftTargetSlideCount, 8);
        hook.updateInput('合成编辑'); hook.toggleResource('synthetic-resource'); hook.toggleResource('synthetic-next'); hook.updateTargetSlides(9);
        assert.equal(hook.state.composerStatus, 'unsaved');
        assert.equal(calls.filter(({ options }) => options.method === 'PATCH').length, 0, 'editing alone never sends PATCH');
        assert.equal(await hook.saveWorking(), true); assert.deepEqual(hook.state.task, captured.patch.data);
        assert.equal(hook.state.composerText, '合成编辑'); assert.equal(hook.state.composerStatus, 'saved');
        assert.equal(hook.state.input_revision, 2); assert.equal(hook.state.working_revision, 2);
        assert.deepEqual(hook.state.task.working.needs_normalization_fields, ['teaching_flow']);
        assert.deepEqual(hook.state.messages, []); assert.deepEqual(hook.state.artifacts, []);
        assert.deepEqual(hook.state.versions, []); assert.equal(hook.state.operationAvailability.chat, false);
        assert.equal(hook.state.operationAvailability.generate, false);
        const post = calls.find(({ options }) => options.method === 'POST'), patch = calls.find(({ options }) => options.method === 'PATCH');
        assert.deepEqual(JSON.parse(post.options.body), { ...nativeCreateRequest(), duration_minutes: 45, target_slide_count: 8 });
        assert.deepEqual(JSON.parse(patch.options.body), nativePatchRequest());
        assert.ok(operations.filter(([action]) => action === 'set').every(([, key]) => key.endsWith(':ui:v1')));
        assert.deepEqual(readFileSync(nativeContractURL), raw, 'native fixture remains byte-for-byte unchanged');
    } finally { scope.stop(); }
});
