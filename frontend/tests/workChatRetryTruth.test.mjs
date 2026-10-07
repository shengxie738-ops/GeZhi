import test, { afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { effectScope, ref, nextTick } from 'vue';

// Production hook, SSE transport, request wrapper and shipped Vue. Every fetch
// is a registered offline double; an accidental URL/write fails the test closed.
const origin = 'https://work-chat.test.invalid';
globalThis.window = { __API_ORIGIN__: origin, location: { hostname: 'work-chat.test.invalid' } };
const { useChat } = await import('../js/hooks/useChat.js');
const { sendStreamingMessage } = await import('../js/api/streamChat.js');
const { API_BASE_URL } = await import('../js/config/env.js');
const encoder = new TextEncoder();
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
const json = (data, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });
const events = rows => new Response(rows.map(row => `data: ${JSON.stringify(row)}\n\n`).join(''), { headers: { 'Content-Type': 'text/event-stream' } });
const savedReply = (reply = 'confirmed answer') => ({ reply, delivery_status: 'complete', history_saved: true, history_receipt: { user_message_id: 101, assistant_message_id: 102 } });
const settle = async () => { await nextTick(); await new Promise(resolve => setImmediate(resolve)); await nextTick(); };
const scopes = [];
let unexpectedIO = [];
afterEach(async () => {
    for (const scope of scopes.splice(0)) scope.stop();
    await settle();
    assert.deepEqual(unexpectedIO, [], 'unregistered I/O must fail even if production catches it');
});

function setup(post, history = () => ({ status: 'success', data: [], pagination: { complete: true, has_more: false } })) {
    unexpectedIO = [];
    const values = new Map([['token', 'synthetic-alice-token']]), listeners = new Map(), calls = [];
    globalThis.localStorage = {
        getItem: key => values.get(key) ?? null,
        setItem: (key, value) => values.set(key, String(value)),
        removeItem: key => values.delete(key)
    };
    globalThis.CustomEvent = class { constructor(type, options) { this.type = type; this.detail = options?.detail; } };
    Object.assign(window, {
        localStorage, dispatchEvent() {}, confirm: () => true,
        addEventListener: (name, callback) => listeners.set(name, callback),
        removeEventListener: name => listeners.delete(name)
    });
    globalThis.document = { querySelector: () => null };
    globalThis.fetch = async (url, options = {}) => {
        const target = new URL(String(url)), method = options.method || 'GET';
        const call = { url: target, method, options }; calls.push(call);
        if (target.origin === origin && target.pathname.startsWith('/api/')) {
            const path = target.pathname.slice(4);
            if (method === 'POST' && ['/chat/stream', '/chat'].includes(path)) return post(path, options, call);
            if (method === 'GET' && ['/ai/models', '/user/models', '/knowledge/courses'].includes(path) && !target.search) return json({ status: 'success', data: [] });
            if (method === 'GET' && path === '/user/knowledge' && ['Alice', 'Bob'].includes(target.searchParams.get('user_id')) && [...target.searchParams.keys()].length === 1) return json({ status: 'success', data: { repositories: [] } });
            if (method === 'GET' && path === '/chat/history' && ['Alice', 'Bob'].includes(target.searchParams.get('session_id')) && ['chat', 'rag', 'tutor', 'paper'].includes(target.searchParams.get('agent_mode')) && [...target.searchParams.keys()].every(key => ['session_id', 'agent_mode', 'limit', 'conversation_id', 'before'].includes(key))) return json(history(target, options));
        }
        unexpectedIO.push(`${method} ${url}`);
        throw new Error(`Unregistered offline I/O: ${method} ${url}`);
    };
    assert.equal(API_BASE_URL, `${origin}/api`);
    const scope = effectScope(), user = ref({ username: 'Alice' }); scopes.push(scope);
    const state = scope.run(() => useChat(user, () => {}));
    state.agentMode.value = 'chat';
    return { state, user, values, calls, listeners, scope };
}
const chatWrites = fixture => fixture.calls.filter(call => call.method === 'POST');
const assertUnknown = rows => {
    assert.equal(rows.length, 2);
    assert.equal(rows[1].deliveryStatus, 'unknown');
    assert.equal(rows[1].historyConfirmationStatus, 'unknown');
    assert.equal(rows[1].deliveryErrorCode, 'unknown_outcome');
    assert.match(rows[1].deliveryError, /可能.*(?:执行|处理)|无法确认/);
    assert.match(rows[1].deliveryError, /刷新历史/);
    assert.match(rows[1].deliveryError, /重试.*(?:重复|再次)/);
    for (const row of rows) {
        assert.equal(row.syncState, 'failed');
        assert.ok(!row.id.startsWith('db-'));
        assert.match(row.syncError, /未确认|核对/);
    }
};

test('accepted stream with lost response headers never automatically executes /chat again', async () => {
    let accepted = 0;
    const fixture = setup(async path => {
        accepted += 1;
        if (path === '/chat/stream') throw new TypeError('fetch failed after synthetic acceptance');
        return json(savedReply());
    });
    await settle();
    await fixture.state.sendMessage('one synthetic command');
    assert.equal(accepted, 1, 'lost confirmation must not issue a second execution');
    assert.deepEqual(chatWrites(fixture).map(call => call.url.pathname), ['/api/chat/stream']);
    assertUnknown(fixture.state.modeMessageBuckets.value.chat);
});

test('accepted stream followed by HTTP 500 has unknown outcome and no second execution', async () => {
    let accepted = 0;
    const fixture = setup(async path => {
        accepted += 1;
        return path === '/chat/stream' ? json({ message: 'synthetic upstream failed after acceptance' }, 500) : json(savedReply());
    });
    await settle(); await fixture.state.sendMessage('ambiguous error response');
    assert.equal(accepted, 1);
    assertUnknown(fixture.state.modeMessageBuckets.value.chat);
});

test('accepted 200 stream ending without events never automatically executes /chat', async () => {
    let accepted = 0;
    const fixture = setup(async path => { accepted += 1; return path === '/chat/stream' ? events([]) : json(savedReply()); });
    await settle(); await fixture.state.sendMessage('empty interrupted stream');
    assert.equal(accepted, 1);
    assertUnknown(fixture.state.modeMessageBuckets.value.chat);
    assert.equal(fixture.state.modeMessageBuckets.value.chat[1].content, '');
});

test('interrupted reader retains partial model text and describes unknown execution/save', async () => {
    const fixture = setup(async () => {
        let read = 0;
        return { ok: true, body: { getReader: () => ({
            async read() { if (read++) throw new Error('synthetic reader disconnected'); return { done: false, value: encoder.encode('data: {"type":"token","content":"partial answer"}\n\n') }; },
            releaseLock() {}, cancel() {}
        }) } };
    });
    await settle(); await fixture.state.sendMessage('partial stream');
    assert.equal(chatWrites(fixture).length, 1);
    assert.equal(fixture.state.modeMessageBuckets.value.chat[1].content, 'partial answer');
    assertUnknown(fixture.state.modeMessageBuckets.value.chat);
});

test('clean EOF with partial tokens and no complete receipt is also unknown', async () => {
    const fixture = setup(async () => events([{ type: 'token', content: 'partial before clean EOF' }]));
    await settle(); await fixture.state.sendMessage('clean EOF');
    assertUnknown(fixture.state.modeMessageBuckets.value.chat);
    assert.equal(fixture.state.modeMessageBuckets.value.chat[1].content, 'partial before clean EOF');
});

test('explicit retry is a new user send after the unknown warning and can confirm a receipt', async () => {
    let accepted = 0;
    const fixture = setup(async () => { accepted += 1; if (accepted === 1) throw new Error('accepted but lost'); return events([{ type: 'complete', ...savedReply() }]); });
    await settle(); await fixture.state.sendMessage('retry deliberately');
    assert.equal(accepted, 1);
    assertUnknown(fixture.state.modeMessageBuckets.value.chat);
    await fixture.state.sendMessage('retry deliberately');
    assert.equal(accepted, 2);
    assert.deepEqual(fixture.state.modeMessageBuckets.value.chat.slice(-2).map(row => row.id), ['db-101', 'db-102']);
    assert.equal(fixture.state.thinkingAgent.value, null);
});

test('an authoritative stream completion still saves only its positive receipt pair', async () => {
    const fixture = setup(async () => events([{ type: 'token', content: 'provisional' }, { type: 'complete', ...savedReply() }]));
    await settle(); await fixture.state.sendMessage('confirmed normal response');
    const rows = fixture.state.modeMessageBuckets.value.chat;
    assert.equal(chatWrites(fixture).length, 1);
    assert.deepEqual(rows.map(row => row.id), ['db-101', 'db-102']);
    assert.equal(rows[1].content, 'confirmed answer');
    assert.ok(rows.every(row => row.syncState === 'saved'));
    await fixture.state.loadChatHistory('chat');
    assert.equal(fixture.state.modeMessageBuckets.value.chat.length, 0, 'complete-empty inventory still reconciles saved rows away');
});

for (const status of [401, 403, 404, 405, 422]) test(`known HTTP ${status} rejection retains the server reason without a fallback`, async () => {
    const reason = `synthetic rejection ${status}`;
    const fixture = setup(async () => json({ detail: reason }, status));
    await settle(); await fixture.state.sendMessage('rejected request');
    const row = fixture.state.modeMessageBuckets.value.chat[1];
    assert.equal(chatWrites(fixture).length, 1);
    assert.equal(row.deliveryStatus, 'failed');
    assert.equal(row.deliveryErrorCode, 'request_rejected');
    assert.match(row.deliveryError, status === 401 ? /登录已过期/ : new RegExp(reason));
    assert.notEqual(row.historyConfirmationStatus, 'unknown');
    assert.equal(row.content, '', 'HTTP error copy is not a model reply');
});

test('authoritative model failure keeps the server reason when EOF loses the save receipt', async () => {
    const fixture = setup(async () => events([{ type: 'error', code: 'model_error', message: 'synthetic provider declined' }]));
    await settle(); await fixture.state.sendMessage('known model error');
    const row = fixture.state.modeMessageBuckets.value.chat[1];
    assert.equal(chatWrites(fixture).length, 1);
    assert.equal(row.deliveryStatus, 'failed');
    assert.equal(row.deliveryErrorCode, 'model_error');
    assert.equal(row.deliveryError, 'synthetic provider declined');
    assert.equal(row.historyConfirmationStatus, 'unknown', 'model rejection does not confirm storage');
    assert.equal(row.content, '');
});

test('valid completion receipt remains authoritative if transport fails after its event', async () => {
    const fixture = setup(async () => {
        let read = 0;
        return { ok: true, body: { getReader: () => ({
            async read() { if (read++) throw new Error('synthetic close after receipt'); return { done: false, value: encoder.encode(`data: ${JSON.stringify({ type: 'complete', ...savedReply() })}\n\n`) }; },
            releaseLock() {}, cancel() {}
        }) } };
    });
    await settle(); await fixture.state.sendMessage('received completion');
    assert.equal(chatWrites(fixture).length, 1);
    assert.deepEqual(fixture.state.modeMessageBuckets.value.chat.map(row => row.id), ['db-101', 'db-102']);
    assert.ok(fixture.state.modeMessageBuckets.value.chat.every(row => row.syncState === 'saved'));
});

for (const fence of ['account', 'token', 'navigation', 'dispose']) test(`late stream loss is fenced after ${fence}`, async () => {
    const pending = deferred();
    const fixture = setup(async () => pending.promise);
    await settle(); const sending = fixture.state.sendMessage('old private request');
    if (fence === 'account') fixture.user.value = { username: 'Bob' };
    if (fence === 'token') { fixture.values.set('token', 'synthetic-renewed-token'); fixture.listeners.get('storage')({ key: 'token' }); }
    if (fence === 'navigation') await fixture.state.startNewConversation();
    if (fence === 'dispose') fixture.scope.stop();
    const draft = fixture.state.draftConversationId.value;
    const before = JSON.stringify(fixture.state.modeMessageBuckets.value);
    pending.reject(new Error('late accepted outcome lost'));
    assert.equal(await sending, false); await settle();
    assert.equal(chatWrites(fixture).length, 1);
    assert.equal(JSON.stringify(fixture.state.modeMessageBuckets.value), before, 'obsolete operation cannot mutate the active buckets');
    assert.equal(fixture.state.draftConversationId.value, draft);
    assert.equal(fixture.state.thinkingAgent.value, null);
    assert.doesNotMatch(fixture.values.get('messages:Bob:chat') || '', /old private request/);
});

test('explicit history checks keep unknown local rows when inventory is empty or forbidden', async () => {
    const fixture = setup(async () => { throw new Error('synthetic accepted confirmation lost'); });
    await settle(); await fixture.state.sendMessage('retain unknown local question');
    const before = JSON.stringify(fixture.state.modeMessageBuckets.value.chat);
    assert.equal(await fixture.state.loadChatHistory('chat'), true);
    assert.equal(JSON.stringify(fixture.state.modeMessageBuckets.value.chat), before);
    const handler = globalThis.fetch;
    globalThis.fetch = (url, options) => new URL(String(url)).pathname === '/api/chat/history'
        ? json({ detail: 'owner history temporarily forbidden' }, 403) : handler(url, options);
    assert.equal(await fixture.state.loadChatHistory('chat'), false);
    assert.equal(JSON.stringify(fixture.state.modeMessageBuckets.value.chat), before);
    assert.equal(chatWrites(fixture).length, 1, 'history reconciliation must not resend the command');
    assert.match(fixture.state.historyError.value, /本地缓存/);
    assertUnknown(fixture.state.modeMessageBuckets.value.chat);
});

test('normal RAG hook also keeps an ambiguous request to one execution', async () => {
    const fixture = setup(async () => { throw new Error('synthetic RAG outcome lost'); });
    await settle(); fixture.state.agentMode.value = 'rag';
    await fixture.state.sendMessage('RAG question');
    assert.equal(chatWrites(fixture).length, 1);
    assert.equal(JSON.parse(chatWrites(fixture)[0].options.body).agent_mode, 'rag');
    assertUnknown(fixture.state.modeMessageBuckets.value.rag);
});

test('normal tutor transport and a non-SSE legacy 200 never replay through /chat', async () => {
    const fixture = setup(async () => json(savedReply()));
    await settle();
    const messages = ref([]), thinking = ref(null);
    await sendStreamingMessage('tutor question', messages, thinking, ref('tutor question'), ref(null),
        false, 'Alice', 'tutor', '', null, null, null, '', 'tutor-task');
    assert.equal(chatWrites(fixture).length, 1);
    assertUnknown(messages.value);
    assert.equal(thinking.value, null);
});

test('navigation abort cancels a live reader and fences its later completion receipt', async () => {
    const pending = deferred(); let reads = 0, cancels = 0, releases = 0;
    const fixture = setup(async () => ({ ok: true, body: { getReader: () => ({
        async read() { if (!reads++) return { done: false, value: encoder.encode('data: {"type":"token","content":"old partial"}\n\n') }; return pending.promise; },
        async cancel() { cancels += 1; }, releaseLock() { releases += 1; }
    }) } }));
    await settle(); const sending = fixture.state.sendMessage('old live stream'); await settle();
    await fixture.state.startNewConversation();
    const before = JSON.stringify(fixture.state.modeMessageBuckets.value);
    pending.resolve({ done: false, value: encoder.encode(`data: ${JSON.stringify({ type: 'complete', ...savedReply() })}\n\n`) });
    assert.equal(await sending, false); await settle();
    assert.equal(chatWrites(fixture).length, 1);
    assert.equal(cancels, 1); assert.equal(releases, 1);
    assert.equal(JSON.stringify(fixture.state.modeMessageBuckets.value), before);
    assert.equal(fixture.state.thinkingAgent.value, null);
});

for (const partial of ['', 'partial model text']) test(`malformed complete marker preserves uncertainty with ${partial ? 'partial' : 'no'} text`, async () => {
    const fixture = setup(async () => events([
        ...(partial ? [{ type: 'token', content: partial }] : []), { type: 'complete' }
    ]));
    await settle(); await fixture.state.sendMessage('malformed terminal');
    assert.equal(chatWrites(fixture).length, 1);
    assertUnknown(fixture.state.modeMessageBuckets.value.chat);
    assert.equal(fixture.state.modeMessageBuckets.value.chat[1].content, partial);
});

test('malformed later complete cannot overwrite a previously authoritative receipt', async () => {
    const fixture = setup(async () => events([{ type: 'complete', ...savedReply() }, { type: 'complete' }]));
    await settle(); await fixture.state.sendMessage('preserve earlier receipt');
    assert.deepEqual(fixture.state.modeMessageBuckets.value.chat.map(row => row.id), ['db-101', 'db-102']);
    assert.ok(fixture.state.modeMessageBuckets.value.chat.every(row => row.syncState === 'saved'));
    assert.equal(fixture.state.modeMessageBuckets.value.chat[1].content, 'confirmed answer');
    assert.equal(chatWrites(fixture).length, 1);
});

test('still-current reader AbortError preserves an authoritative completion receipt', async () => {
    const fixture = setup(async () => {
        let read = 0;
        return { ok: true, body: { getReader: () => ({
            async read() { if (read++) throw new DOMException('synthetic reader cleanup', 'AbortError'); return { done: false, value: encoder.encode(`data: ${JSON.stringify({ type: 'complete', ...savedReply() })}\n\n`) }; },
            releaseLock() {}, cancel() {}
        }) } };
    });
    await settle(); await fixture.state.sendMessage('completion before reader cleanup');
    assert.deepEqual(fixture.state.modeMessageBuckets.value.chat.map(row => row.id), ['db-101', 'db-102']);
    assert.ok(fixture.state.modeMessageBuckets.value.chat.every(row => row.syncState === 'saved'));
    assert.equal(fixture.state.thinkingAgent.value, null);
    assert.equal(chatWrites(fixture).length, 1);
});

for (const fence of ['navigation', 'token']) test(`genuine ${fence} change after receipt still prevents an obsolete operation commit`, async () => {
    let fixture;
    fixture = setup(async () => {
        let read = 0;
        return { ok: true, body: { getReader: () => ({
            async read() {
                if (!read++) return { done: false, value: encoder.encode(`data: ${JSON.stringify({ type: 'complete', ...savedReply() })}\n\n`) };
                if (fence === 'navigation') await fixture.state.startNewConversation();
                else { fixture.values.set('token', 'synthetic-replaced-token'); fixture.listeners.get('storage')({ key: 'token' }); }
                throw new DOMException('genuine obsolete operation', 'AbortError');
            }, releaseLock() {}, cancel() {}
        }) } };
    });
    await settle(); assert.equal(await fixture.state.sendMessage('receipt before context change'), false);
    const rows = fixture.state.modeMessageBuckets.value.chat;
    assert.ok(rows.every(row => row.syncState === 'pending'));
    assert.ok(rows.every(row => !row.id.startsWith('db-')));
    assert.equal(fixture.state.thinkingAgent.value, null);
    assert.equal(chatWrites(fixture).length, 1);
});

test('malformed claimed-positive completion receipt cannot replace an earlier valid receipt', async () => {
    const fixture = setup(async () => events([
        { type: 'complete', ...savedReply() },
        { type: 'complete', delivery_status: 'complete', content: 'late unconfirmed text', history_saved: true,
            history_receipt: { user_message_id: 'bad', assistant_message_id: 'bad' } }
    ]));
    await settle(); await fixture.state.sendMessage('keep first positive receipt');
    assert.deepEqual(fixture.state.modeMessageBuckets.value.chat.map(row => row.id), ['db-101', 'db-102']);
    assert.ok(fixture.state.modeMessageBuckets.value.chat.every(row => row.syncState === 'saved'));
    assert.equal(fixture.state.modeMessageBuckets.value.chat[1].content, 'confirmed answer');
    assert.equal(chatWrites(fixture).length, 1);
});

test('claimed-positive receipt with malformed IDs is unknown even with complete status and content', async () => {
    const fixture = setup(async () => events([
        { type: 'token', content: 'partial real text' },
        { type: 'complete', delivery_status: 'complete', content: 'unconfirmed terminal text', history_saved: true,
            history_receipt: { user_message_id: '101', assistant_message_id: null } }
    ]));
    await settle(); await fixture.state.sendMessage('reject contradictory save claim');
    assertUnknown(fixture.state.modeMessageBuckets.value.chat);
    assert.equal(fixture.state.modeMessageBuckets.value.chat[1].content, 'partial real text');
    assert.equal(chatWrites(fixture).length, 1);
});

test('single-terminal normal protocol latches the first valid completion before a contradictory later one', async () => {
    const fixture = setup(async () => events([
        { type: 'complete', ...savedReply() },
        { type: 'complete', content: '', delivery_status: 'failed', error: 'model_error', message: 'late contradictory error',
            history_saved: false, history_receipt: { user_message_id: 101, assistant_message_id: null } }
    ]));
    await settle(); await fixture.state.sendMessage('one normal terminal result');
    assert.deepEqual(fixture.state.modeMessageBuckets.value.chat.map(row => row.id), ['db-101', 'db-102']);
    assert.ok(fixture.state.modeMessageBuckets.value.chat.every(row => row.syncState === 'saved'));
    assert.equal(fixture.state.modeMessageBuckets.value.chat[1].content, 'confirmed answer');
    assert.equal(chatWrites(fixture).length, 1);
});
