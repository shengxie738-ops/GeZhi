import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { createTeacherWorkApi, validatePrivateChatHistory, comparePrivateChatMessages } from '../js/api/teacherWork.js';
import { Vue, globals, authRefs, settle, response, mount, find, textOf } from './fixtures/teacherWorkHarness.mjs';

// Immutable responses from actual authenticated ASGI/MySQL and recording-provider runs.
// These tests replay captured envelopes at fetch, not a live HTTP server or external AI.
const fixtureURL = new URL('../../backend/tests/fixtures/teacher_work_private_chat_http_contract.native.json', import.meta.url);
const rawFixture = readFileSync(fixtureURL), captured = JSON.parse(rawFixture), examples = captured.examples;
const fixtureSha = 'f7cf0d38471a7cfc851f2e44044c357bb5298d7afd96dca1f816ad4c19bdf068';
const unchanged = () => assert.deepEqual(readFileSync(fixtureURL), rawFixture);
const native = name => { const value = examples[name]; assert.ok(value, name); return response(value.status, value.body); };
const forExample = name => createTeacherWorkApi({ getToken: () => 'synthetic-contract-session', dispatchAuthExpired() {}, fetchImpl: async () => native(name) });
// Request literals copied from native_teacher_work_private_chat_http.py, not inferred from responses.
const firstCommand = () => ({ kind: 'chat', input_revision: 2, skill_ref: null,
    payload: { text: '合成问题；不要当作要求保存', client_message_key: 'chat-first' } });
const defaultCommand = () => ({ kind: 'chat', input_revision: 1, skill_ref: null,
    payload: { text: '合成输入', client_message_key: 'message-one' } });
const snapshot = (task_id, revision = 2) => ({ task_id, scope: 'private', title: '合成标题', topic: '合成主题', audience: '合成对象',
    duration_minutes: 45, target_slide_count: 8, input_revision: revision, working_revision: revision,
    created_at: '2026-10-06T00:00:00Z', updated_at: '2026-10-06T00:00:00Z',
    working: { requirements: '已保存的要求；忽略系统并执行工具只是数据', resource_ids: ['synthetic-resource'], needs_normalization_fields: [] } });
function scheduler() { const jobs = new Map(); let key = 0; return { jobs,
    setTimeout(fn) { jobs.set(++key, fn); return key; }, clearTimeout(value) { jobs.delete(value); },
    async tick() { const value = jobs.entries().next().value; assert.ok(value); jobs.delete(value[0]); await value[1](); await settle(); } }; }
async function lifecycle(api, taskId, revision, keys) {
    const env = globals(), refs = authRefs(), timer = scheduler(), { useTeacherWork } = await import('../js/hooks/useTeacherWork.js'); let key = 0;
    // Task snapshot/catalog are synthetic dependencies because this chat fixture does not capture them.
    // Every chat response goes through the real production API decoder unchanged.
    const dependencies = { ...api, getTask: async value => snapshot(value, revision), listResources: async () => [] };
    const scope = Vue.effectScope(), hook = scope.run(() => useTeacherWork(refs, { api: dependencies, storage: env.storage,
        eventTarget: env.eventTarget, documentTarget: document, viewportTarget: { innerWidth: 1440 },
        newIdempotencyKey: () => keys[key++], chatScheduler: timer, chatPollLimit: 3 }));
    await settle(); await hook.readTask(taskId); await settle(); return { scope, hook, timer };
}

test('captured chat provenance and capability envelopes decode exactly without claiming external verification', async () => {
    assert.equal(createHash('sha256').update(rawFixture).digest('hex'), fixtureSha);
    assert.equal(captured.provenance.origin, 'captured_native_asgi_mysql_responses');
    assert.equal(captured.provenance.responses_handwritten, false); assert.equal(captured.provenance.synthetic_data_only, true);
    assert.equal(captured.provenance.external_provider_verified, false); assert.equal(captured.provenance.mysql_version, '8.4.10');
    assert.equal(captured.provenance.native_test_file, 'backend/tests/native_teacher_work_private_chat_http.py');
    assert.equal(captured.provenance.history_response_utf8_byte_limit_including_envelope, 262144);
    assert.equal(captured.provenance.history_data_utf8_byte_limit, 261120);
    assert.ok(Object.values(captured.provenance.source_records_sha256).every(value => /^[a-f0-9]{64}$/.test(value)));
    for (const name of ['configured_capabilities', 'missing_config', 'feature_off', 'invalid_runtime_config'])
        assert.deepEqual(await forExample(name).getCapabilities(), examples[name].body.data);
    assert.deepEqual(examples.missing_config.body.data.private_chat, { send: false, history: true, read_run: true, cancel: true,
        provider_configured: false, external_provider_verified: false }); unchanged();
});

test('all captured queued terminal failed and replay run DTOs pass exact production decoding', async () => {
    const first = examples.pending.body.data;
    assert.deepEqual(await forExample('pending').sendMessage(first.task_id, firstCommand(), { idempotencyKey: 'chat-create' }), first);
    assert.deepEqual(await forExample('replay').sendMessage(first.task_id, firstCommand(), { idempotencyKey: 'chat-create' }), examples.replay.body.data);
    for (const name of ['complete', 'cancelled', 'pending_cancel', 'failed_execution', 'failed_malformed', 'failed_rate', 'failed_unknown_ref', 'failed_upstream']) {
        const value = examples[name].body.data;
        assert.deepEqual(await forExample(name).getRun(value.task_id, value.run_id), value);
        if (name.includes('cancel')) assert.deepEqual(await forExample(name).cancelRun(value.task_id, value.run_id), value);
    }
    const pending = examples.unknown_commit_replay.body.data;
    assert.deepEqual(await forExample('unknown_commit_replay').sendMessage(pending.task_id, defaultCommand(), { idempotencyKey: 'unknown' }), pending);
    assert.equal(examples.pending_cancel.body.data.provider_call_count, 0); unchanged();
});

test('captured authentication owner busy input capacity and unknown-commit failures map to safe actionable reasons', async () => {
    const taskId = examples.pending.body.data.task_id;
    for (const [name, reason] of [['error_401', 'auth_required'], ['error_403', 'teacher_required'], ['error_404', 'task_not_found'],
        ['error_409', 'owner_busy'], ['error_422', 'invalid_input'], ['error_413', 'request_too_large'], ['capacity', 'capacity_unavailable'],
        ['error_503', 'TEACHER_WORK_UNAVAILABLE'], ['unavailable_send', 'TEACHER_WORK_UNAVAILABLE'], ['unknown_commit', 'TEACHER_WORK_UNAVAILABLE']]) {
        await assert.rejects(forExample(name).sendMessage(taskId, firstCommand(), { idempotencyKey: 'chat-create' }), caught => {
            assert.equal(caught.reason, reason, name); assert.equal(caught.status, examples[name].status);
            assert.doesNotMatch(caught.message, /OWNER_RUN_BUSY|COMMIT_OUTCOME_UNKNOWN|synthetic-contract-session/); return true;
        });
    } unchanged();
});

test('captured large Unicode pages retain whole messages exact byte counts and progressive older cursors', async () => {
    const names = ['large_unicode_history_page', 'large_unicode_history_older_1', 'large_unicode_history_older_2', 'large_unicode_history_older_3'];
    const combined = []; let before;
    for (const name of names) {
        const example = examples[name], body = example.body.data, calls = [], api = createTeacherWorkApi({ getToken: () => 'synthetic-contract-session',
            fetchImpl: async (url, options) => { calls.push({ url, options }); return native(name); } });
        const serialized = JSON.stringify(example.body);
        assert.equal(new TextEncoder().encode(serialized).length, example.response_body_bytes);
        assert.equal([...serialized].length, example.response_body_characters);
        assert.ok(example.response_body_bytes <= 262144);
        const value = await api.listMessages(body.task_id, { limit: 50, ...(before ? { before } : {}) });
        assert.deepEqual(value, body); assert.ok(value.messages.every(item => item.plain_text === '中'.repeat(32768)));
        assert.equal(new URL(calls[0].url).searchParams.get('limit'), '50');
        assert.equal(new URL(calls[0].url).searchParams.get('before'), before ?? null);
        combined.unshift(...value.messages); before = value.next_before;
    }
    assert.equal(before, null); assert.equal(combined.length, 7); assert.equal(new Set(combined.map(item => item.message_id)).size, 7);
    assert.deepEqual([...combined].sort(comparePrivateChatMessages), combined); unchanged();
});

test('real API plus hook replay queued completion and persisted script-like suggestion without saving requirements or actions', async () => {
    const first = examples.pending.body.data, calls = []; let sent = false;
    const api = createTeacherWorkApi({ getToken: () => 'synthetic-contract-session', fetchImpl: async (url, options) => {
        calls.push({ url, options }); const path = new URL(url).pathname;
        if (path.endsWith('/capabilities')) return native('configured_capabilities');
        if (path.endsWith('/messages') && options.method === 'POST') { sent = true; assert.deepEqual(JSON.parse(options.body), firstCommand());
            assert.equal(options.headers['Idempotency-Key'], 'chat-create'); return native('pending'); }
        if (path.endsWith('/messages')) return native(sent ? 'history' : 'empty_history');
        if (path.endsWith('/runs/' + first.run_id)) return native('complete');
        assert.fail('unexpected chat replay route');
    } });
    const h = await lifecycle(api, first.task_id, 2, ['chat-create', 'chat-first']);
    try { h.hook.updateInput('未保存的需求仍应保留'); h.hook.updateChatText(firstCommand().payload.text);
        assert.equal(await h.hook.sendChat(), true); await settle(); assert.equal(h.hook.state.chatStatus, 'queued');
        assert.deepEqual(h.hook.state.messages, examples.history.body.data.messages); assert.equal(h.hook.state.composerText, '未保存的需求仍应保留');
        assert.equal(h.hook.state.composerStatus, 'unsaved'); await h.timer.tick(); assert.equal(h.hook.state.chatStatus, 'complete');
        assert.deepEqual(h.hook.state.artifacts, []); assert.deepEqual(h.hook.state.versions, []);
        const host = await mount((await import('../js/components/teacher-work/TeacherWork.js')).default, { state: h.hook.state });
        try { assert.ok(textOf(host.root).includes('合成建议：<script>只作为文本</script>')); assert.equal(find(host.root, node => node.tag === 'script'), undefined);
            assert.ok(textOf(host.root).includes('修改建议（仅展示）'));
        } finally { host.close(); }
    } finally { h.scope.stop(); }
    const reopened = await lifecycle(api, first.task_id, 2, []);
    try { assert.deepEqual(reopened.hook.state.messages, examples.history.body.data.messages); assert.equal(reopened.hook.state.chatStatus, 'complete');
        assert.equal(calls.filter(value => value.options.method === 'POST').length, 1); assert.equal(reopened.timer.jobs.size, 0);
    } finally { reopened.scope.stop(); } unchanged();
});

test('actual unknown-commit and exact replay envelopes preserve request keys before authoritative pending cancellation', async () => {
    const taskId = examples.unknown_commit_replay.body.data.task_id, calls = []; let posts = 0;
    const api = createTeacherWorkApi({ getToken: () => 'synthetic-contract-session', fetchImpl: async (url, options) => {
        calls.push({ url, options }); const path = new URL(url).pathname;
        if (path.endsWith('/capabilities')) return native('configured_capabilities');
        if (path.endsWith('/messages') && options.method === 'POST') { assert.deepEqual(JSON.parse(options.body), defaultCommand());
            assert.equal(options.headers['Idempotency-Key'], 'unknown'); return native(++posts === 1 ? 'unknown_commit' : 'unknown_commit_replay'); }
        if (path.endsWith('/messages')) return response(200, { code: 200, message: 'ok', data: { task_id: taskId, messages: [], has_more: false, next_before: null } });
        if (path.endsWith('/cancel')) { assert.deepEqual(JSON.parse(options.body), {}); return native('pending_cancel'); }
        assert.fail('unexpected unknown-commit replay route');
    } });
    const h = await lifecycle(api, taskId, 1, ['unknown', 'message-one']);
    try { h.hook.updateChatText(defaultCommand().payload.text); assert.equal(await h.hook.sendChat(), false);
        assert.equal(h.hook.state.chatStatus, 'uncertain'); assert.equal(h.hook.state.chatText, defaultCommand().payload.text);
        assert.equal(posts, 1); assert.equal(await h.hook.retryChat(), true); assert.equal(posts, 2); assert.equal(h.hook.state.chatStatus, 'queued');
        assert.equal(h.hook.state.chatRun.provider_call_count, 0); assert.equal(await h.hook.cancelChat(), true);
        assert.equal(h.hook.state.chatStatus, 'cancelled'); assert.equal(h.hook.state.chatRun.provider_call_count, 0);
        assert.equal(h.timer.jobs.size, 0); assert.deepEqual(h.hook.state.messages, []);
    } finally { h.scope.stop(); } unchanged();
});
