import test from 'node:test';
import assert from 'node:assert/strict';
import { Vue, source, mount, textOf, button, settle } from './fixtures/workPresentationRenderer.mjs';

const origin = 'https://paper-sync-uncertainty.test.invalid';
globalThis.window = { __API_ORIGIN__: origin, location: { hostname: 'paper-sync-uncertainty.test.invalid' } };
const { useChat } = await import('../js/hooks/useChat.js');
const { API_BASE_URL } = await import('../js/config/env.js');
const response = (data, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const snapshot = { status: 'success', results: [{ id: 'synthetic-paper', title: 'Synthetic metadata record' }], summary: { totalAfterMerge: 1 } };
const success = () => response({ status: 'success', data: [{ id: 703 }, { id: 704 }] });

// Real shipped Vue, request, hook, cache parser, and installed status markup.
// Only fetch/Web Storage and the renderer host are synthetic; no network.
function fixture(t, code = 'CHAT_BATCH_COMMIT_UNKNOWN', status = 503) {
    const values = new Map([['token', 'synthetic-paper-sync-token']]);
    const writes = [], unexpectedIO = [], scopes = [], requestErrors = [];
    globalThis.localStorage = { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, String(value)), removeItem: key => values.delete(key) };
    globalThis.window = { __API_ORIGIN__: origin, location: { hostname: 'paper-sync-uncertainty.test.invalid' }, localStorage, addEventListener() {}, removeEventListener() {}, dispatchEvent() {} };
    globalThis.document = { querySelector: () => null };
    const oldConsoleError = console.error;
    console.error = (...args) => {
        assert.equal(args[0], `[API Request Error] ${origin}/api/chat/history/batch:`);
        requestErrors.push(args[1]);
    };
    const f = { values, writes, requestErrors, historyRows: [], batch: async () => response({ detail: code }, status) };
    globalThis.fetch = async (rawUrl, options = {}) => {
        const url = new URL(String(rawUrl)), method = options.method || 'GET';
        if (url.origin === origin && url.pathname.startsWith('/api/')) {
            const path = url.pathname.slice(4);
            if (method === 'POST' && path === '/chat/history/batch' && !url.search) {
                const body = JSON.parse(options.body);
                assert.equal(body.user_id, 'Alice'); assert.equal(body.agent_mode, 'paper');
                assert.equal(body.messages.length, 2); assert.match(body.client_request_id, /^paper-search:/);
                writes.push({ body: options.body, key: body.client_request_id, authorization: options.headers.Authorization, signal: options.signal });
                return f.batch(body);
            }
            if (method === 'GET' && ['/ai/models', '/user/models', '/knowledge/courses'].includes(path) && !url.search) return response({ status: 'success', data: [] });
            if (method === 'GET' && path === '/user/knowledge' && ['Alice', 'Bob'].includes(url.searchParams.get('user_id')) && [...url.searchParams.keys()].every(key => key === 'user_id')) return response({ status: 'success', data: { repositories: [] } });
            if (method === 'GET' && path === '/chat/history' && ['Alice', 'Bob'].includes(url.searchParams.get('session_id')) && ['chat', 'tutor', 'rag', 'paper'].includes(url.searchParams.get('agent_mode')) && [...url.searchParams.keys()].every(key => ['session_id', 'agent_mode', 'limit', 'conversation_id'].includes(key))) {
                return response({ status: 'success', data: url.searchParams.get('agent_mode') === 'paper' && url.searchParams.get('session_id') === 'Alice' ? f.historyRows : [], pagination: { complete: true, has_more: false } });
            }
        }
        unexpectedIO.push(`${method} ${rawUrl}`);
        throw new Error(`Unregistered offline I/O: ${method} ${rawUrl}`);
    };
    assert.equal(API_BASE_URL, `${origin}/api`);
    f.open = (username = 'Alice') => {
        const scope = Vue.effectScope(), user = Vue.ref({ username });
        const state = scope.run(() => useChat(user, () => {}));
        scopes.push(scope); state.agentMode.value = 'paper';
        return { scope, user, state };
    };
    t.after(async () => {
        scopes.forEach(scope => scope.stop()); await settle(); console.error = oldConsoleError;
        assert.deepEqual(unexpectedIO, [], 'unregistered I/O must fail closed');
    });
    return f;
}

async function statusView(t, state) {
    const html = source('index.html'), start = html.indexOf('<div v-if="paperWorkSyncStatus" role="status"');
    assert.ok(start >= 0, 'installed paper sync status exists');
    const end = html.indexOf('</div>', start) + '</div>'.length;
    const view = await mount({ template: html.slice(start, end), setup: () => ({ paperWorkSyncStatus: state.paperWorkSyncStatus, retryPaperWorkSync: state.retryPaperWorkSync }) });
    t.after(() => view.close());
    return view;
}

function assertUnconfirmed(copy) {
    assert.match(copy, /保存结果尚未确认|云端保存待确认/);
    assert.doesNotMatch(copy, /仅.*本地|只.*本地/, 'no failed response proves absence of a cloud commit');
}

for (const code of ['CHAT_BATCH_SCHEMA_UNAVAILABLE', 'CHAT_BATCH_UNAVAILABLE', 'CHAT_BATCH_SESSION_NOT_CLEAN', 'CHAT_BATCH_RECEIPT_INVALID', 'CHAT_BATCH_COMMIT_UNKNOWN', 'CHAT_BATCH_OUTCOME_UNKNOWN']) {
    test(`production paper503 ${code} keeps truthful live status and stable deliberate retry`, async t => {
        const f = fixture(t, code), { state } = f.open(); await settle();
        assert.equal(await state.recordPaperSearchWork('synthetic paper query', snapshot), false); await settle();
        assert.equal(f.writes.length, 1, 'failed save does not automatically POST again');
        assertUnconfirmed(state.historyError.value); assert.match(state.historyError.value, new RegExp(code));
        const rows = state.modeMessageBuckets.value.paper, beforeIds = rows.map(row => row.id);
        assert.equal(rows.length, 2); assert.ok(rows.every(row => row.syncState === 'failed' && row.syncError === code));
        assert.ok(beforeIds.every(id => !String(id).startsWith('db-')));
        assert.equal(rows[1].paperSearchSnapshot.results.length, 1);
        const view = await statusView(t, state);
        assertUnconfirmed(textOf(view.root)); assert.match(textOf(view.root), new RegExp(code));
        assert.match(textOf(view.root), /重试同步/); assert.match(textOf(view.root), /刷新历史记录/);
        f.batch = success;
        assert.equal(await button(view.root, '重试同步').props.onClick(), true); await settle();
        assert.equal(f.writes.length, 2); assert.equal(f.writes[0].body, f.writes[1].body);
        assert.equal(f.writes[0].authorization, f.writes[1].authorization);
        assert.deepEqual(rows.map(row => row.id), ['db-703', 'db-704']);
        assert.ok(rows.every(row => row.syncState === 'saved' && row.syncError === ''));
        assert.equal(state.historyError.value, ''); assert.match(textOf(view.root), /已收到云端保存回执/);
    });
}

for (const detail of [
    'client_request_id conflicts with existing paper receipt',
    'paper history was deleted; this request cannot recreate it',
    'paper receipt conflicts with existing or deleted history',
    'paper receipt conflicts with existing history'
]) {
    test(`paper409 retains actual cause without asserting cloud absence: ${detail}`, async t => {
        const f = fixture(t, detail, 409), { state } = f.open(); await settle();
        assert.equal(await state.recordPaperSearchWork('synthetic paper query', snapshot), false); await settle();
        assert.equal(f.writes.length, 1); assertUnconfirmed(state.historyError.value); assert.ok(state.historyError.value.includes(detail));
        const view = await statusView(t, state); assertUnconfirmed(textOf(view.root)); assert.ok(textOf(view.root).includes(detail));
        assert.ok(state.modeMessageBuckets.value.paper.every(row => row.syncState === 'failed' && !String(row.id).startsWith('db-')));
    });
}

test('generic server500 retains neutral failed copy without assuming a prewrite failure', async t => {
    const f = fixture(t, 'synthetic server failure', 500), { state } = f.open(); await settle();
    assert.equal(await state.recordPaperSearchWork('synthetic paper query', snapshot), false); await settle();
    assert.equal(f.writes.length, 1); assertUnconfirmed(state.historyError.value);
    const view = await statusView(t, state); assertUnconfirmed(textOf(view.root));
});

for (const receipt of [[], [{ id: 703 }], [{ id: 0 }, { id: 704 }]]) {
    test(`incomplete or nonpositive paper receipt cannot mark rows saved: ${JSON.stringify(receipt)}`, async t => {
        const f = fixture(t), { state } = f.open(); await settle();
        f.batch = async () => response({ status: 'success', data: receipt });
        assert.equal(await state.recordPaperSearchWork('synthetic paper query', snapshot), false); await settle();
        assert.equal(f.writes.length, 1); assertUnconfirmed(state.historyError.value);
        const view = await statusView(t, state); assertUnconfirmed(textOf(view.root));
        assert.ok(state.modeMessageBuckets.value.paper.every(row => row.syncState === 'failed' && !String(row.id).startsWith('db-')));
    });
}

test('lost response retains neutral copy and does not fabricate saving or automatically retry', async t => {
    const f = fixture(t); f.batch = async () => { throw new Error('synthetic lost response'); };
    const { state } = f.open(); await settle();
    assert.equal(await state.recordPaperSearchWork('synthetic paper query', snapshot), false); await settle();
    assert.equal(f.writes.length, 1); assertUnconfirmed(state.historyError.value);
    const view = await statusView(t, state); assertUnconfirmed(textOf(view.root));
    assert.ok(state.modeMessageBuckets.value.paper.every(row => row.syncState === 'failed' && !String(row.id).startsWith('db-')));
});

for (const code of ['CHAT_BATCH_SCHEMA_UNAVAILABLE', 'CHAT_BATCH_COMMIT_UNKNOWN', 'CHAT_BATCH_OUTCOME_UNKNOWN']) {
    test(`cached ${code} reload preserves cause rows snapshot and exact explicit-retry body`, async t => {
        const f = fixture(t, code), first = f.open(); await settle();
        assert.equal(await first.state.recordPaperSearchWork('synthetic paper query', snapshot), false); await settle();
        const before = JSON.parse(f.values.get('messages:Alice:paper')), conversationId = before[1].conversationId;
        first.scope.stop();
        const { state } = f.open(); await settle();
        assert.equal(f.writes.length, 1, 'mount and history GET never automatically retry cached work');
        assert.deepEqual(state.modeMessageBuckets.value.paper.map(row => row.id), before.map(row => row.id));
        assert.equal(state.paperWorkSyncStatus.value.state, 'failed'); assert.equal(state.paperWorkSyncStatus.value.error, code);
        assert.deepEqual(state.modeMessageBuckets.value.paper[1].paperSearchSnapshot, before[1].paperSearchSnapshot);
        const view = await statusView(t, state); assertUnconfirmed(textOf(view.root)); assert.match(textOf(view.root), new RegExp(code));
        f.batch = success;
        assert.equal(await state.retryPaperWorkSync(conversationId), true); await settle();
        assert.equal(f.writes.length, 2); assert.equal(f.writes[0].body, f.writes[1].body);
        assert.equal(f.writes[0].key, f.writes[1].key);
        assert.deepEqual(state.modeMessageBuckets.value.paper.map(row => row.id), ['db-703', 'db-704']);
        assert.ok(JSON.parse(f.values.get('messages:Alice:paper')).every(row => row.syncState === 'saved'));
        assert.match(textOf(view.root), /已收到云端保存回执/);
    });
}

test('unknown followed by schema failure still avoids claiming the original write exists only locally', async t => {
    const f = fixture(t), { state } = f.open(); await settle();
    assert.equal(await state.recordPaperSearchWork('synthetic paper query', snapshot), false);
    const conversationId = state.modeMessageBuckets.value.paper[1].conversationId;
    f.batch = async () => response({ detail: 'CHAT_BATCH_SCHEMA_UNAVAILABLE' }, 503);
    assert.equal(await state.retryPaperWorkSync(conversationId), false); await settle();
    assert.equal(f.writes.length, 2); assert.equal(f.writes[0].body, f.writes[1].body);
    assertUnconfirmed(state.historyError.value); const view = await statusView(t, state); assertUnconfirmed(textOf(view.root));
    assert.match(textOf(view.root), /CHAT_BATCH_SCHEMA_UNAVAILABLE/);
});

test('explicit history refresh can confirm an unknown commit without issuing another POST', async t => {
    const f = fixture(t), { state } = f.open(); await settle();
    assert.equal(await state.recordPaperSearchWork('synthetic paper query', snapshot), false);
    const body = JSON.parse(f.writes[0].body);
    f.historyRows = body.messages.map((row, index) => ({ ...row, id: 703 + index, created_at: '2026-10-07 05:00:00' }));
    assert.equal(await state.loadChatHistory('paper'), true); await settle();
    assert.equal(f.writes.length, 1); assert.deepEqual(state.modeMessageBuckets.value.paper.map(row => row.id), ['db-703', 'db-704']);
    assert.equal(state.paperWorkSyncStatus.value.state, 'saved'); assert.equal(state.historyError.value, '');
    const view = await statusView(t, state); assert.match(textOf(view.root), /已收到云端保存回执/);
    assert.equal(await state.retryPaperWorkSync(body.conversation_id), false); assert.equal(f.writes.length, 1);
});

test('account switch fences a delayed unknown retry and never exposes Alice cache to Bob', async t => {
    const f = fixture(t), { state, user } = f.open(); await settle();
    assert.equal(await state.recordPaperSearchWork('Alice synthetic query', snapshot), false);
    const conversationId = state.modeMessageBuckets.value.paper[1].conversationId, waiting = deferred();
    f.batch = () => waiting.promise; const retry = state.retryPaperWorkSync(conversationId);
    f.values.set('token', 'synthetic-bob-token'); user.value = { username: 'Bob' }; await settle();
    waiting.resolve(response({ detail: 'CHAT_BATCH_OUTCOME_UNKNOWN' }, 503));
    assert.equal(await retry, false); await settle();
    assert.equal(f.writes.length, 2); assert.equal(f.writes[0].body, f.writes[1].body); assert.equal(f.writes[1].signal.aborted, true);
    assert.deepEqual(state.modeMessageBuckets.value.paper, []); assert.equal(state.paperWorkSyncStatus.value, null); assert.equal(state.historyError.value, '');
    assert.doesNotMatch(f.values.get('messages:Bob:paper') || '', /Alice synthetic query|CHAT_BATCH_/);
    assert.equal(await state.retryPaperWorkSync(conversationId), false); assert.equal(f.writes.length, 2);
});

test('repeated deliberate retry coalesces and a late receipt does not hijack newer navigation', async t => {
    const f = fixture(t), { state } = f.open(); await settle();
    assert.equal(await state.recordPaperSearchWork('synthetic paper query', snapshot), false);
    const conversationId = state.modeMessageBuckets.value.paper[1].conversationId, waiting = deferred();
    f.batch = () => waiting.promise;
    const retry = state.retryPaperWorkSync(conversationId), again = state.retryPaperWorkSync(conversationId);
    assert.equal(f.writes.length, 2, 'repeated clicks share the one in-flight batch request');
    const draftId = await state.startNewConversation();
    waiting.resolve(success()); assert.equal(await retry, true); assert.equal(await again, true); await settle();
    assert.equal(f.writes.length, 2); assert.equal(f.writes[0].body, f.writes[1].body);
    assert.equal(state.activeConversationId.value, 'new'); assert.equal(state.draftConversationId.value, draftId);
    assert.deepEqual(state.modeMessageBuckets.value.paper.map(row => row.id), ['db-703', 'db-704']);
    assert.equal(state.paperWorkSyncStatus.value, null);
});
