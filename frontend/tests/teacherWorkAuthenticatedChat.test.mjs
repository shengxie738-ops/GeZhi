import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { Vue, globals, authRefs, deferred, settle, capabilityFacts, mount, find, button, textOf } from './fixtures/teacherWorkHarness.mjs';

const taskA = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', taskB = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const runA = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc', runB = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
const id = n => `${String(n).padStart(8, '0')}-0000-4000-8000-000000000000`;
const facts = changes => ({ ...capabilityFacts(), chat: true, generate: false, storage: false, structural_preview: false,
    private_tasks: { create: true, read: true, update: true }, private_chat: { send: true, history: true, read_run: true,
        cancel: true, provider_configured: true, external_provider_verified: false, ...changes } });
const snapshot = (task_id = taskA, revision = 1) => ({ task_id, scope: 'private', title: '循环教学', topic: '循环', audience: '一年级',
    duration_minutes: 45, target_slide_count: 8, input_revision: revision, working_revision: revision,
    created_at: '2026-10-05T20:00:00Z', updated_at: '2026-10-05T20:00:00Z',
    working: { requirements: '已保存需求', resource_ids: ['courseware-one'], needs_normalization_fields: [] } });
const run = (stage = 'PENDING', changes = {}) => ({ run_id: runA, task_id: taskA, kind: 'chat', input_revision: 1, stage,
    attempt: 1, provider_call_count: stage === 'PENDING' ? 0 : 1, deadline: '2026-10-06T01:00:00Z', cancelled_at: null, error_code: null, ...changes });
const message = (n, role = 'user', changes = {}) => ({ message_id: id(n), task_id: taskA, role, plain_text: role === 'user' ? '教学问题' : '已持久回复',
    run_id: runA, client_message_key: role === 'user' ? 'message-one' : null, result_type: role === 'user' ? null : 'answer',
    result_refs: [], omitted_context: role === 'user' ? null : false, created_at: '2026-10-05T20:00:00Z', ...changes });
const page = (messages = [], changes = {}) => ({ task_id: taskA, messages, has_more: false, next_before: null, ...changes });
function scheduler() { let serial = 0; const jobs = new Map(); return { jobs,
    setTimeout(fn) { const key = ++serial; jobs.set(key, fn); return key; }, clearTimeout(key) { jobs.delete(key); },
    async tick() { const next = jobs.entries().next().value; assert.ok(next, 'expected scheduled read'); jobs.delete(next[0]); await next[1](); await settle(); } }; }
async function harness(overrides = {}, config = {}) {
    const env = globals(), refs = authRefs(), timer = scheduler(), calls = { send: [], history: [], read: [], cancel: [] }; let keys = 0;
    const api = { getCapabilities: async () => facts(), listResources: async () => [], getTask: async value => snapshot(value),
        updateWorking: async (value, body) => ({ ...snapshot(value, body.expected_revision + 1), working: { ...snapshot().working, ...body.changes } }),
        sendMessage: async (...args) => { calls.send.push(args); return run(); },
        listMessages: async (...args) => { calls.history.push(args); return page(); },
        getRun: async (...args) => { calls.read.push(args); return run('CHAT_RUNNING'); },
        cancelRun: async (...args) => { calls.cancel.push(args); return run('CANCELLED', { cancelled_at: '2026-10-06T00:00:00Z' }); }, ...overrides };
    const { useTeacherWork } = await import('../js/hooks/useTeacherWork.js');
    const scope = Vue.effectScope(), hook = scope.run(() => useTeacherWork(refs, { api, storage: env.storage, eventTarget: env.eventTarget,
        documentTarget: document, viewportTarget: { innerWidth: 1440 }, newIdempotencyKey: () => `chat-key-${++keys}`,
        chatScheduler: timer, chatPollLimit: 3, ...config }));
    await settle(); await hook.readTask(taskA); await settle(); return { ...env, refs, timer, calls, api, scope, hook };
}

test('private chat uses independent input, one queued send, and only persisted messages as transcript', async () => {
    const pending = deferred(); let history = 0; const h = await harness({ sendMessage: (...args) => { h.calls.send.push(args); return pending.promise; },
        listMessages: async () => ++history === 1 ? page() : page([message(1)]) });
    try { h.hook.updateInput('未保存教学需求'); assert.equal(h.hook.updateChatText('教学问题'), true);
        const sending = h.hook.sendChat(); assert.equal(await h.hook.sendChat(), false); assert.equal(h.calls.send.length, 1);
        assert.deepEqual(h.calls.send[0][1], { kind: 'chat', input_revision: 1, skill_ref: null, payload: { text: '教学问题', client_message_key: 'chat-key-2' } });
        assert.deepEqual(h.hook.state.messages, []); assert.equal(h.hook.state.chatStatus, 'sending');
        pending.resolve(run()); assert.equal(await sending, true); await settle();
        assert.equal(h.hook.state.chatText, ''); assert.equal(h.hook.state.chatStatus, 'queued');
        assert.deepEqual(h.hook.state.messages, [message(1)]); assert.equal(h.hook.state.composerText, '未保存教学需求');
        assert.equal(h.hook.state.composerStatus, 'unsaved'); assert.equal(h.timer.jobs.size, 1);
        assert.ok(h.operations.filter(([op]) => op === 'set').every(([, key]) => key.endsWith(':ui:v1')));
    } finally { h.scope.stop(); assert.equal(h.timer.jobs.size, 0); }
});

test('uncertain send retains exact keys and input for explicit retry, with no automatic repost', async () => {
    const calls = []; const h = await harness({ sendMessage: async (...args) => { calls.push(args); if (calls.length === 1) throw { reason: 'network_error' }; return run(); } });
    try { h.hook.updateChatText('重试问题'); assert.equal(await h.hook.sendChat(), false); assert.equal(h.hook.state.chatStatus, 'uncertain');
        assert.equal(h.hook.state.chatText, '重试问题'); assert.equal(h.timer.jobs.size, 0); assert.deepEqual(h.hook.state.messages, []);
        await settle(); assert.equal(calls.length, 1); assert.equal(await h.hook.retryChat(), true);
        assert.deepEqual(calls[1][1], calls[0][1]); assert.equal(calls[1][2].idempotencyKey, calls[0][2].idempotencyKey);
    } finally { h.scope.stop(); }
});

test('changed chat body or saved revision discards uncertain retry keys and starts a new operation', async () => {
    for (const change of ['text', 'revision']) { const calls = []; const h = await harness({ sendMessage: async (...args) => { calls.push(args); throw { reason: 'network_error' }; } });
        try { h.hook.updateChatText('原问题'); await h.hook.sendChat();
            if (change === 'text') h.hook.updateChatText('新问题'); else { h.hook.updateInput('新需求'); await h.hook.saveWorking(); }
            assert.equal(await h.hook.retryChat(), false); await h.hook.sendChat(); assert.equal(calls.length, 2);
            assert.notEqual(calls[1][2].idempotencyKey, calls[0][2].idempotencyKey);
            assert.notEqual(calls[1][1].payload.client_message_key, calls[0][1].payload.client_message_key);
            assert.equal(calls[1][1].input_revision, change === 'revision' ? 2 : 1);
        } finally { h.scope.stop(); }
    }
});

test('revision conflict and provider failure remain explicit without changing requirements or fabricating answers', async () => {
    const h = await harness({ sendMessage: async () => { throw { reason: 'revision_conflict', status: 409 }; } });
    try { h.hook.updateChatText('问题'); h.hook.updateInput('未保存需求'); await h.hook.sendChat();
        assert.equal(h.hook.state.chatError.reason, 'revision_conflict'); assert.equal(h.hook.state.chatStatus, 'error');
        assert.equal(h.hook.state.chatText, '问题'); assert.deepEqual(h.hook.state.messages, []); assert.equal(h.hook.state.composerText, '未保存需求');
    } finally { h.scope.stop(); }
    const failed = await harness({ getRun: async () => run('FAILED', { error_code: 'PROVIDER_ERROR' }) });
    try { failed.hook.updateChatText('问题'); await failed.hook.sendChat(); await failed.timer.tick();
        assert.equal(failed.hook.state.chatStatus, 'failed'); assert.equal(failed.hook.state.chatRun.error_code, 'PROVIDER_ERROR');
        assert.equal(failed.timer.jobs.size, 0); assert.deepEqual(failed.hook.state.messages, []);
    } finally { failed.scope.stop(); }
});

test('history pages deduplicate and order persisted messages; reopening recovers run without repost', async () => {
    let histories = 0; const h = await harness({ listMessages: async (_task, options) => { histories++; return options.before ?
        page([message(1), message(2)], { has_more: false }) : page([message(2), message(3, 'assistant')], { has_more: true, next_before: id(2) }); },
        getRun: async () => run('COMPLETE') });
    try { assert.equal(histories, 2, 'terminal run recovery refreshes the persisted transcript'); assert.equal(h.hook.state.chatHistoryHasMore, true);
        assert.equal(await h.hook.loadOlderChat(), true); assert.deepEqual(h.hook.state.messages.map(value => value.message_id), [id(1), id(2), id(3)]);
        assert.equal(h.calls.send.length, 0); assert.equal(h.hook.state.chatStatus, 'complete'); assert.equal(h.timer.jobs.size, 0);
    } finally { h.scope.stop(); }
});

test('bounded polling can resume explicitly and cancel aborts the old poll without stale completion', async () => {
    const pending = deferred(), cancel = deferred(); let count = 0; const h = await harness({ getRun: (...args) => { h.calls.read.push(args); return ++count === 1 ? pending.promise : Promise.resolve(run('CHAT_RUNNING')); },
        cancelRun: (...args) => { h.calls.cancel.push(args); return cancel.promise; } });
    try { h.hook.updateChatText('问题'); await h.hook.sendChat(); const reading = h.timer.tick(); await settle();
        const cancelling = h.hook.cancelChat(); assert.equal(await h.hook.cancelChat(), false); assert.equal(h.calls.cancel.length, 1);
        assert.equal(h.calls.read[0][2].signal.aborted, true); pending.resolve(run('COMPLETE')); await reading;
        assert.equal(h.hook.state.chatStatus, 'cancelling'); cancel.resolve(run('CANCELLED', { cancelled_at: '2026-10-06T00:00:00Z' })); await cancelling;
        assert.equal(h.hook.state.chatStatus, 'cancelled'); assert.equal(h.timer.jobs.size, 0);
    } finally { h.scope.stop(); }
    const bounded = await harness();
    try { bounded.hook.updateChatText('问题'); await bounded.hook.sendChat(); for (let n = 0; n < 3; n++) await bounded.timer.tick();
        assert.equal(bounded.hook.state.chatStatus, 'paused'); assert.equal(bounded.timer.jobs.size, 0);
        assert.equal(await bounded.hook.refreshChatRun(), true); assert.equal(bounded.hook.state.chatStatus, 'running');
    } finally { bounded.scope.stop(); }
});

test('stale send history run and cancel responses cannot cross task actor auth view or disposal', async () => {
    for (const operation of ['sendMessage', 'listMessages', 'getRun', 'cancelRun']) for (const change of ['task', 'actor', 'epoch', 'view', 'dispose']) {
        const pending = deferred(), calls = []; let armed = false; const h = await harness({ [operation]: (...args) => { calls.push(args);
            if (armed) return pending.promise; return Promise.resolve(operation === 'listMessages' ? page() : run()); } });
        try { h.hook.updateChatText('旧问题'); let result;
            if (operation === 'sendMessage') { armed = true; result = h.hook.sendChat(); }
            else if (operation === 'listMessages') { armed = true; result = h.hook.reloadChatHistory(); }
            else { await h.hook.sendChat(); armed = true; result = operation === 'getRun' ? h.hook.refreshChatRun() : h.hook.cancelChat(); }
            await settle(); const last = calls.at(-1);
            if (change === 'task') await h.hook.readTask(taskB);
            if (change === 'actor') h.refs.actor.value = 'teacher-b';
            if (change === 'epoch') h.refs.authEpoch.value++;
            if (change === 'view') h.refs.currentView.value = 't_lesson_prep';
            if (change === 'dispose') h.scope.stop();
            assert.equal(last.at(-1).signal.aborted, true, `${operation}/${change}`);
            pending.resolve(operation === 'listMessages' ? page([message(8, 'assistant', { plain_text: '过期回复' })]) : run('COMPLETE'));
            await result; await settle(); assert.ok(!h.hook.state.messages.some(value => value.plain_text === '过期回复'));
            assert.notEqual(h.hook.state.chatStatus, 'sending'); assert.notEqual(h.hook.state.chatStatus, 'cancelling');
            assert.equal(h.timer.jobs.size, 0);
        } finally { h.scope.stop(); }
    }
});

test('unconfigured provider closes only send, leaving authorized history run and cancel usable', async () => {
    const h = await harness({ getCapabilities: async () => ({ ...facts({ send: false, provider_configured: false }), chat: false }),
        listMessages: async () => page([message(1)]), getRun: async () => run('CHAT_RUNNING') });
    try { assert.equal(h.hook.state.privateChatAvailability.send, false); h.hook.updateChatText('问题'); assert.equal(await h.hook.sendChat(), false);
        assert.equal(h.hook.state.messages.length, 1); assert.equal(await h.hook.cancelChat(), true);
        assert.equal(h.hook.state.chatStatus, 'cancelled');
    } finally { h.scope.stop(); }
});

test('current 401 and 403 close chat actions while late auth errors are discarded', async () => {
    for (const reason of ['auth_required', 'teacher_required']) { const h = await harness({ sendMessage: async () => { throw { reason, status: reason === 'auth_required' ? 401 : 403 }; } });
        try { h.hook.updateChatText('问题'); await h.hook.sendChat(); assert.equal(h.hook.state.chatError.reason, reason);
            assert.deepEqual(h.hook.state.privateChatAvailability, { send: false, history: false, read_run: false, cancel: false,
                provider_configured: false, external_provider_verified: false });
        } finally { h.scope.stop(); }
    }
});

test('desktop UI renders escaped persisted text and independent composers with truthful queued and provider states', async () => {
    const h = await harness({ listMessages: async () => page([message(1, 'assistant', { plain_text: '<img src=x onerror=alert(1)>' })]), getRun: async () => run('COMPLETE') });
    const component = (await import('../js/components/teacher-work/TeacherWork.js')).default;
    try { h.hook.updateChatText('问题'); const host = await mount(component, { state: h.hook.state });
        try { const chat = find(host.root, node => node.props.id === 'teacher-work-chat-input'); assert.ok(chat);
            assert.equal(chat.props.value, '问题'); chat.props.onInput({ target: { value: '新问题' } }); assert.deepEqual(host.emitted['update-chat-text'], [['新问题']]);
            button(host.root, '发送教学问题').props.onClick(); assert.deepEqual(host.emitted['send-chat'], [[]]);
            assert.ok(find(host.root, node => node.props.id === 'teacher-work-input')); assert.ok(textOf(host.root).includes('<img src=x onerror=alert(1)>'));
            assert.equal(find(host.root, node => node.tag === 'img'), undefined); assert.ok(textOf(host.root).includes('外部模型尚未验证'));
            assert.ok(button(host.root, '保存需求')); assert.equal(find(host.root, node => node.props['data-teacher-work-zone'] === 'conversation') !== undefined, true);
            h.hook.state.chatStatus = 'queued'; await settle(); assert.ok(textOf(host.root).includes('已入队'));
        } finally { host.close(); }
    } finally { h.scope.stop(); }
    const main = readFileSync(new URL('../js/main.js', import.meta.url), 'utf8'), html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
    for (const name of ['UpdateChatText', 'SendChat', 'RetryChat', 'ReloadChatHistory', 'LoadOlderChat', 'RefreshChatRun', 'CancelChat'])
        assert.ok(main.includes(`teacherWork${name}: teacherWork.`), name);
    for (const name of ['update-chat-text', 'send-chat', 'retry-chat', 'reload-chat-history', 'load-older-chat', 'refresh-chat-run', 'cancel-chat'])
        assert.ok(html.includes(`@${name}="teacherWork`), name);
});


test('uncertain operation cannot silently become a fresh send, and edited text during send remains copyable', async () => {
    const calls = [], h = await harness({ sendMessage: async (...args) => { calls.push(args); throw { reason: 'network_error' }; } });
    try { h.hook.updateChatText('原问题'); await h.hook.sendChat(); assert.equal(await h.hook.sendChat(), false);
        assert.equal(calls.length, 1); assert.equal(h.hook.state.chatRetryAvailable, true);
    } finally { h.scope.stop(); }
    const pending = deferred(), edited = await harness({ sendMessage: () => pending.promise });
    try { edited.hook.updateChatText('已提交问题'); const sending = edited.hook.sendChat(); edited.hook.updateChatText('提交后新编辑');
        pending.resolve(run()); assert.equal(await sending, true); assert.equal(edited.hook.state.chatText, '提交后新编辑');
    } finally { edited.scope.stop(); }
});

test('newer history and run requests fence older out-of-order results within the same task', async () => {
    const pending = deferred(), newest = deferred(); let reads = 0; const h = await harness({ listMessages: () => {
        reads++; return reads === 1 ? Promise.resolve(page()) : reads === 2 ? pending.promise : newest.promise; } });
    try { const old = h.hook.reloadChatHistory(), fresh = h.hook.reloadChatHistory();
        newest.resolve(page([message(2, 'assistant', { plain_text: '较新回复' })])); await fresh; await settle();
        pending.resolve(page([message(1, 'assistant', { plain_text: '过期回复' })])); assert.equal(await old, false);
        assert.deepEqual(h.hook.state.messages.map(value => value.plain_text), ['较新回复']);
    } finally { h.scope.stop(); }
    const oldRun = deferred(), newRun = deferred(); let count = 0; const r = await harness({ getRun: () => ++count === 1 ? oldRun.promise : newRun.promise });
    try { r.hook.updateChatText('问题'); await r.hook.sendChat(); const first = r.hook.refreshChatRun(), second = r.hook.refreshChatRun();
        newRun.resolve(run('FAILED', { error_code: 'PROVIDER_ERROR' })); await second;
        oldRun.resolve(run('COMPLETE')); assert.equal(await first, false); assert.equal(r.hook.state.chatStatus, 'failed');
    } finally { r.scope.stop(); }
});

test('opening and closing create task clears chat waits without dropping unsaved requirements or cancelling upstream', async () => {
    const pending = deferred(), calls = []; const h = await harness({ sendMessage: (...args) => { calls.push(args); return pending.promise; } });
    try { h.hook.updateInput('保留需求草稿'); h.hook.updateChatText('待发送问题'); const sending = h.hook.sendChat();
        h.hook.openCreateTask(); assert.equal(calls[0][2].signal.aborted, true); assert.equal(h.hook.state.chatStatus, 'uncertain');
        assert.equal(h.hook.state.chatRetryAvailable, true); h.hook.closeCreateTask(); pending.resolve(run()); assert.equal(await sending, false); await settle();
        assert.equal(h.hook.state.chatText, '待发送问题'); assert.equal(h.hook.state.composerText, '保留需求草稿');
        assert.equal(h.hook.state.composerStatus, 'unsaved'); assert.equal(h.calls.cancel.length, 0);
        assert.equal(h.hook.state.chatHistoryStatus, 'ready'); assert.equal(h.timer.jobs.size, 0);
    } finally { h.scope.stop(); }
});


test('persisted history resolves an uncertain send by its client key without posting again', async () => {
    const calls = []; let saved = false; const h = await harness({ sendMessage: async (...args) => { calls.push(args); throw { reason: 'network_error' }; },
        listMessages: async () => saved ? page([message(1, 'user', { client_message_key: calls[0][1].payload.client_message_key })]) : page(),
        getRun: async () => run('COMPLETE') });
    try { h.hook.updateChatText('原问题'); await h.hook.sendChat(); saved = true; await h.hook.reloadChatHistory(); await settle();
        assert.equal(calls.length, 1); assert.equal(h.hook.state.chatRetryAvailable, false); assert.equal(h.hook.state.chatText, '');
        assert.equal(h.hook.state.chatStatus, 'complete'); assert.equal(await h.hook.retryChat(), false);
    } finally { h.scope.stop(); }
});

test('microsecond ordering is retained when older and latest persisted pages are merged', async () => {
    const h = await harness({ listMessages: async (_task, options) => options.before ?
        page([message(2, 'assistant', { created_at: '2026-10-05T20:00:00.000001Z' })]) :
        page([message(1, 'assistant', { created_at: '2026-10-05T20:00:00.000999Z' })], { has_more: true, next_before: id(1) }),
        getRun: async () => run('COMPLETE') });
    try { await h.hook.loadOlderChat(); assert.deepEqual(h.hook.state.messages.map(value => value.message_id), [id(2), id(1)]);
    } finally { h.scope.stop(); }
});

test('normalized older capability response keeps private CRUD readable and chat backward-closed', async () => {
    globals(); const { createTeacherWorkApi } = await import('../js/api/teacherWork.js');
    const api = createTeacherWorkApi({ getToken: () => 'session', fetchImpl: async () => ({ status: 200,
        text: async () => JSON.stringify({ code: 200, message: 'ok', data: { ...capabilityFacts(), private_tasks: { create: true, read: true, update: true } } }) }) });
    const decoded = await api.getCapabilities(), h = await harness({ getCapabilities: async () => decoded });
    try { assert.equal(h.hook.state.capabilities.status, 'ready'); assert.equal(h.hook.state.privateTaskAvailability.read, true);
        assert.equal(h.hook.state.task_id, taskA); assert.equal(h.hook.state.privateChatAvailability.send, false);
        assert.equal(h.hook.state.operationAvailability.chat, false); assert.equal(h.calls.history.length, 0);
    } finally { h.scope.stop(); }
});

test('new uncertain turn recovers its persisted run after a previous turn finished', async () => {
    let sends = 0, saved = false, secondKey; const readIds = []; const h = await harness({ sendMessage: async (_id, body) => {
        if (++sends === 1) return run('COMPLETE'); secondKey = body.payload.client_message_key; throw { reason: 'network_error' }; },
        listMessages: async () => saved ? page([message(1, 'assistant'), message(2, 'user', { run_id: runB, client_message_key: secondKey })]) : page(),
        getRun: async (_task, value) => { readIds.push(value); return run('PENDING', { run_id: value }); } });
    try { h.hook.updateChatText('首轮问题'); await h.hook.sendChat(); h.hook.updateChatText('第二轮问题'); await h.hook.sendChat();
        saved = true; await h.hook.reloadChatHistory(); await settle(); assert.equal(h.hook.state.chatRun.run_id, runB);
        assert.equal(h.hook.state.chatStatus, 'queued'); assert.equal(h.hook.state.chatRetryAvailable, false);
        assert.ok(readIds.includes(runB)); assert.equal(h.timer.jobs.size, 1); assert.equal(sends, 2);
    } finally { h.scope.stop(); }
});

test('capability recheck interrupts a send as uncertain and preserves explicit retry identity', async () => {
    const pending = deferred(), calls = []; const h = await harness({ sendMessage: (...args) => { calls.push(args);
        return calls.length === 1 ? pending.promise : Promise.resolve(run()); } });
    try { h.hook.updateChatText('待确认问题'); const sending = h.hook.sendChat(); await h.hook.retryCapabilities(); await settle();
        assert.equal(calls[0][2].signal.aborted, true); assert.equal(h.hook.state.chatStatus, 'uncertain');
        assert.equal(h.hook.state.chatRetryAvailable, true); pending.resolve(run()); assert.equal(await sending, false);
        assert.equal(await h.hook.sendChat(), false); assert.equal(await h.hook.retryChat(), true);
        assert.deepEqual(calls[1][1], calls[0][1]); assert.equal(calls[1][2].idempotencyKey, calls[0][2].idempotencyKey);
    } finally { h.scope.stop(); }
});

test('capability restoration resumes authorized pending run reads and aborts history when access closes', async () => {
    const h = await harness();
    try { h.hook.updateChatText('问题'); await h.hook.sendChat(); assert.equal(h.timer.jobs.size, 1);
        await h.hook.retryCapabilities(); await settle(); assert.equal(h.hook.state.chatStatus, 'running');
        assert.equal(h.timer.jobs.size, 1); assert.equal(h.calls.read.length, 1);
    } finally { h.scope.stop(); }
    const pending = deferred(), calls = []; let armed = false; const closed = await harness({ listMessages: (...args) => { calls.push(args); return armed ? pending.promise : Promise.resolve(page()); } });
    try { armed = true; const reading = closed.hook.reloadChatHistory(); closed.hook.state.privateChatAvailability.history = false;
        assert.equal(calls.at(-1)[1].signal.aborted, true); pending.resolve(page([message(1)])); assert.equal(await reading, false);
        assert.deepEqual(closed.hook.state.messages, []); assert.equal(closed.hook.state.chatHistoryStatus, 'idle');
    } finally { closed.scope.stop(); }
});

test('old persisted turn cannot label a newer unconfirmed question complete', async () => {
    let sends = 0; const readIds = []; const h = await harness({ sendMessage: async () => {
        if (++sends === 1) return run('COMPLETE'); throw { reason: 'network_error' }; },
        listMessages: async () => page([message(1, 'assistant')]), getRun: async (_task, value) => { readIds.push(value); return run('COMPLETE'); } });
    try { h.hook.updateChatText('首轮问题'); await h.hook.sendChat(); h.hook.updateChatText('第二轮未确认'); await h.hook.sendChat();
        readIds.length = 0; await h.hook.reloadChatHistory(); await settle(); assert.equal(h.hook.state.chatStatus, 'uncertain');
        assert.equal(h.hook.state.chatText, '第二轮未确认'); assert.equal(h.hook.state.chatRetryAvailable, true);
        assert.equal(h.hook.state.chatError.reason, 'network_error'); assert.deepEqual(readIds, []);
    } finally { h.scope.stop(); }
});

test('loading older history does not replace latest terminal execution with an old run', async () => {
    const reads = []; const h = await harness({ listMessages: async (_task, options) => options.before ?
        page([message(1, 'assistant', { run_id: runA })]) : page([message(2, 'assistant', { run_id: runB })], { has_more: true, next_before: id(2) }),
        getRun: async (_task, value) => { reads.push(value); return run(value === runB ? 'COMPLETE' : 'FAILED', { run_id: value, error_code: value === runB ? null : 'PROVIDER_ERROR' }); } });
    try { assert.equal(h.hook.state.chatRun.run_id, runB); reads.length = 0; await h.hook.loadOlderChat(); await settle();
        assert.equal(h.hook.state.chatRun.run_id, runB); assert.equal(h.hook.state.chatStatus, 'complete'); assert.deepEqual(reads, []);
        assert.equal(h.hook.state.messages.length, 2);
    } finally { h.scope.stop(); }
});

test('history confirmation keeps a known run even when run reads are unavailable, with authorized cancel still usable', async () => {
    let saved = false, key; const h = await harness({ getCapabilities: async () => facts({ read_run: false }),
        sendMessage: async (_task, body) => { key = body.payload.client_message_key; throw { reason: 'network_error' }; },
        listMessages: async () => saved ? page([message(1, 'user', { client_message_key: key })]) : page() });
    try { h.hook.updateChatText('待确认问题'); await h.hook.sendChat(); saved = true; await h.hook.reloadChatHistory(); await settle();
        assert.equal(h.hook.state.chatRun.run_id, runA); assert.equal(h.hook.state.chatStatus, 'paused');
        assert.equal(h.hook.state.chatRetryAvailable, false); assert.equal(h.hook.state.chatText, ''); assert.equal(h.calls.read.length, 0);
        h.hook.updateChatText('新问题'); assert.equal(await h.hook.sendChat(), false);
        assert.equal(await h.hook.cancelChat(), true); assert.equal(h.hook.state.chatStatus, 'cancelled');
    } finally { h.scope.stop(); }
});
