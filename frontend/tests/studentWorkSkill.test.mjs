import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { registerHooks } from 'node:module';
import test from 'node:test';
import * as Vue from '../libs/vue.esm-browser.js';
import * as pluginsRegistry from '../js/config/academicPlugins.js';
import { buildChatPayload } from '../js/utils/chatModes.js';
import { API_BASE_URL } from '../js/config/env.js';
import { capabilityResponse, isCapabilityRequest } from './support/studentWorkCapabilitiesFixture.mjs';

// Shipped Vue, production hooks and transport, synthetic fetch only. This file
// never starts a server, imports main.js, opens a browser or calls a provider.
const jsRoot = new URL('../js/', import.meta.url).href;
const vueUrl = new URL('../libs/vue.esm-browser.js', import.meta.url).href;
const resolution = registerHooks({
    resolve(specifier, context, nextResolve) {
        if (specifier === 'vue' && context.parentURL?.startsWith(jsRoot)) {
            return { url: vueUrl, shortCircuit: true };
        }
        return nextResolve(specifier, context);
    }
});
const { useChat } = await import('../js/hooks/useChat.js');
const { usePlugins } = await import('../js/hooks/usePlugins.js');
resolution.deregister();

const reviewer = () => pluginsRegistry.getPluginById('plugin_peer_review');
const settle = async () => {
    await Vue.nextTick();
    await new Promise(resolve => setImmediate(resolve));
    await Vue.nextTick();
};
const deferred = () => {
    let resolve, reject;
    const promise = new Promise((done, fail) => { resolve = done; reject = fail; });
    return { promise, resolve, reject };
};
const jsonResponse = value => new Response(JSON.stringify(value), {
    status: 200, headers: { 'Content-Type': 'application/json' }
});
const streamResponse = events => new Response(new ReadableStream({
    start(controller) {
        controller.enqueue(new TextEncoder().encode(events.map(event => `data: ${JSON.stringify(event)}\n\n`).join('')));
        controller.close();
    }
}), { status: 200, headers: { 'Content-Type': 'text/event-stream' } });
const success = () => ({
    reply: 'source-grounded review', content: 'source-grounded review',
    delivery_status: 'complete', history_saved: true,
    history_receipt: { user_message_id: 801, assistant_message_id: 802 }
});

async function setup({ withChat = false } = {}) {
    const saved = Object.fromEntries(['localStorage', 'window', 'document', 'fetch', 'CustomEvent'].map(key => [key, globalThis[key]]));
    const savedWarn = console.warn, savedError = console.error;
    const storage = new Map([['token', 'skill-test-alice']]);
    const calls = [], capabilityCalls = [], toasts = [], storageListeners = new Map(), unexpectedRequests = [];
    let capabilityHandler = () => capabilityResponse();
    let chatHandler = async call => call.path === '/chat/stream'
        ? streamResponse([{ type: 'token', content: 'source-grounded review' }, { type: 'complete', ...success() }])
        : jsonResponse(success());
    globalThis.localStorage = {
        getItem: key => storage.get(key) ?? null,
        setItem: (key, value) => storage.set(key, String(value)),
        removeItem: key => storage.delete(key)
    };
    globalThis.window = {
        localStorage, location: { hostname: 'frontend.invalid' },
        addEventListener: (name, listener) => storageListeners.set(name, listener),
        removeEventListener: name => storageListeners.delete(name), dispatchEvent() {}
    };
    globalThis.document = { querySelector: () => null };
    globalThis.CustomEvent = class { constructor(type, options = {}) { this.type = type; this.detail = options.detail; } };
    console.warn = () => {};
    console.error = () => {};
    globalThis.fetch = async (rawUrl, options = {}) => {
        if (isCapabilityRequest(rawUrl)) { capabilityCalls.push(options); assert.ok(capabilityCalls.length < 10); return capabilityHandler(); }
        const url = new URL(String(rawUrl));
        const base = new URL(API_BASE_URL);
        const path = url.pathname.slice(base.pathname.length);
        try {
            assert.equal(url.origin, base.origin, 'Only the configured synthetic API origin is allowed');
            assert.ok(url.pathname.startsWith(`${base.pathname}/`), 'Only configured API paths are allowed');
            assert.ok(calls.length < 40, 'Finite synthetic transport budget exceeded');
            assert.ok(['/chat/stream', '/chat', '/ai/models', '/user/models', '/user/knowledge', '/knowledge/courses', '/chat/history'].includes(path), `Unexpected synthetic route: ${path}`);
            if (['/chat/stream', '/chat'].includes(path)) assert.equal(options.method, 'POST');
            else assert.ok(!options.method || options.method === 'GET', 'Bootstrap requests must remain read-only');
        } catch (error) { unexpectedRequests.push(error.message); throw error; }
        const call = { path, options, payload: options.body ? JSON.parse(options.body) : null };
        calls.push(call);
        if (['/chat/stream', '/chat'].includes(path)) {
            return chatHandler(call);
        }
        return jsonResponse({ status: 'success', data: [], pagination: { has_more: false, complete: true } });
    };
    const scope = Vue.effectScope(), user = Vue.ref({ username: 'Alice' }), input = Vue.ref('');
    const state = scope.run(() => withChat ? useChat(user, (...args) => toasts.push(args)) : null);
    const plugins = scope.run(() => usePlugins(user, (...args) => toasts.push(args), state?.inputText || input));
    await settle();
    return {
        scope, user, input, state, plugins, storage, calls, capabilityCalls, toasts,
        respondCapabilities(handler) { capabilityHandler = handler; },
        chatCalls: () => calls.filter(call => ['/chat/stream', '/chat'].includes(call.path)),
        respondWith(handler) { chatHandler = handler; },
        connectSelection() {
            assert.equal(typeof state.setChatSkillSelectionResolver, 'function', 'Chat must accept an explicit selection resolver');
            state.setChatSkillSelectionResolver(() => plugins.selectedChatSkillIds.value);
        },
        async close() {
            scope.stop();
            await settle();
            for (const [key, value] of Object.entries(saved)) {
                if (value === undefined) delete globalThis[key]; else globalThis[key] = value;
            }
            console.warn = savedWarn;
            console.error = savedError;
            assert.deepEqual(unexpectedRequests, [], 'Even swallowed bootstrap errors must respect the synthetic route guard');
        }
    };
}

test('student Work skill: only Academic Reviewer declares the executable academic-review capability', () => {
    const executable = pluginsRegistry.ACADEMIC_PLUGINS.filter(plugin => plugin.executionKind === 'chat_skill');
    assert.deepEqual(executable.map(plugin => [plugin.id, plugin.chatSkillId]), [['plugin_peer_review', 'academic-review']]);
    assert.equal(reviewer().canSearchLive, false);
});

test('selected Reviewer discovery failure blocks real send without dropping input or choosing plain chat', async () => {
    const h = await setup({ withChat: true });
    try {
        h.connectSelection();
        h.state.agentMode.value = 'paper';
        h.plugins.insertPluginToInput(reviewer());
        h.state.inputText.value = 'Keep the supplied abstract';
        h.respondCapabilities(() => Promise.reject(new Error('synthetic catalog outage')));
        assert.equal(await h.plugins.refreshCapabilities({ force: true }), false);
        assert.equal(await h.state.sendMessage(), false);
        assert.equal(h.state.inputText.value, 'Keep the supplied abstract');
        assert.deepEqual(h.plugins.activeInputPlugins.value.map(p => p.id), ['plugin_peer_review']);
        assert.equal(h.chatCalls().length, 0);
        assert.ok(h.toasts.some(([message]) => /能力清单.*重试/.test(message)));
        h.plugins.removeActiveInputPlugin(reviewer().id);
        await h.state.sendMessage();
        assert.equal(h.chatCalls().length, 1);
        assert.equal(Object.hasOwn(h.chatCalls()[0].payload, 'skill_ids'), false);
    } finally { await h.close(); }
});

test('student Work skill: installed defaults do not select any chat skill', async () => {
    const h = await setup();
    try {
        assert.ok(h.plugins.installedPluginIds.value.includes(reviewer().id));
        assert.ok(h.plugins.selectedChatSkillIds, 'Plugin state must expose explicit chat-skill selection');
        assert.deepEqual(h.plugins.selectedChatSkillIds.value, []);
        assert.equal(h.calls.length, 0);
    } finally { await h.close(); }
});

test('student Work skill: mounting reviewer selects once; ordinary labels and forged metadata never add skills', async () => {
    const h = await setup();
    try {
        h.plugins.insertPluginToInput(reviewer());
        h.plugins.insertPluginToInput(reviewer());
        h.plugins.insertPluginToInput({ ...pluginsRegistry.getPluginById('plugin_python_sandbox'), executionKind: 'chat_skill', chatSkillId: 'academic-review' });
        assert.ok(h.plugins.selectedChatSkillIds, 'Mounted selection must be resolved by registered capability');
        assert.deepEqual(h.plugins.selectedChatSkillIds.value, ['academic-review']);
        assert.equal(h.plugins.activeInputPlugins.value.filter(plugin => plugin.id === reviewer().id).length, 1);
        assert.ok(h.toasts.some(([message]) => /已选用.*Skill/.test(message)));
        assert.ok(h.toasts.some(([message]) => /未连接执行/.test(message)));
        assert.equal(h.calls.length, 0);
    } finally { await h.close(); }
});

for (const action of ['remove', 'uninstall', 'account', 'unmount']) {
    test(`student Work skill: ${action} clears explicit reviewer selection`, async () => {
        const h = await setup();
        try {
            h.plugins.insertPluginToInput(reviewer());
            if (action === 'remove') h.plugins.removeActiveInputPlugin(reviewer().id);
            if (action === 'uninstall') h.plugins.uninstallPlugin(reviewer().id);
            if (action === 'account') h.user.value = { username: 'Bob' };
            if (action === 'unmount') h.scope.stop();
            assert.ok(h.plugins.selectedChatSkillIds, 'Selection state must exist');
            assert.deepEqual(h.plugins.selectedChatSkillIds.value, []);
            assert.equal(h.plugins.activeInputPlugins.value.some(plugin => plugin.id === reviewer().id), false);
        } finally { await h.close(); }
    });
}

for (const mode of ['chat', 'paper']) {
    test(`student Work skill: ${mode} payload carries only explicit captured IDs and preserves chosen model`, () => {
        const ids = ['academic-review'];
        const payload = buildChatPayload({ message: 'review supplied excerpt', agentMode: mode, model: 'owner-chosen-model', skillIds: ids });
        assert.deepEqual(payload.skill_ids, ['academic-review']);
        ids.length = 0;
        assert.deepEqual(payload.skill_ids, ['academic-review'], 'Payload owns its snapshot');
        assert.equal(payload.agent_model, 'owner-chosen-model');
        assert.equal(payload.force_rag, false);
        assert.equal('skill_ids' in buildChatPayload({ message: 'ordinary', agentMode: mode }), false);
    });
}

for (const skillIds of [['unknown-skill'], ['academic-review', 'academic-review'], 'academic-review']) {
    test(`student Work skill: malformed selection ${JSON.stringify(skillIds)} is rejected by payload construction`, () => {
        assert.throws(() => buildChatPayload({ message: 'review', agentMode: 'chat', skillIds }), /Skill|研读|academic-review/);
    });
}

for (const overrides of [{ agentMode: 'tutor' }, { agentMode: 'rag' }, { forceRAG: true }, { repositoryId: 'repo-1' }, { courseDatasetIds: ['course-1'] }]) {
    test(`student Work skill: incompatible ${JSON.stringify(overrides)} is visibly rejected before chat fetch`, async () => {
        const h = await setup({ withChat: true });
        try {
            await settle();
            h.connectSelection();
            h.plugins.insertPluginToInput(reviewer());
            h.state.agentMode.value = overrides.agentMode || 'chat';
            h.state.forceRAG.value = Boolean(overrides.forceRAG);
            // RAG repository/dataset exclusions are also checked at the payload boundary.
            if (overrides.repositoryId || overrides.courseDatasetIds) {
                assert.throws(() => buildChatPayload({ message: 'review', agentMode: 'chat', skillIds: ['academic-review'], ...overrides }), /Skill|研读|academic-review/);
            } else {
                const result = await h.state.sendMessage('review supplied excerpt');
                assert.equal(result, false);
                assert.equal(h.chatCalls().length, 0, 'Invalid selection must never silently run ordinary chat');
                assert.ok(h.toasts.some(([message, kind]) => kind === 'error' && /Skill|研读/.test(message)));
                assert.deepEqual(h.state.modeMessageBuckets.value[h.state.agentMode.value], []);
            }
        } finally { await h.close(); }
    });
}

test('student Work skill: unselected installed reviewer keeps ordinary chat request free of skill IDs', async () => {
    const h = await setup({ withChat: true });
    try {
        await settle(); h.connectSelection(); h.state.agentMode.value = 'chat';
        await h.state.sendMessage('ordinary request');
        assert.equal(h.chatCalls().length, 1);
        assert.equal('skill_ids' in h.chatCalls()[0].payload, false);
    } finally { await h.close(); }
});

for (const mode of ['chat', 'paper']) {
    test(`student Work skill: ${mode} preserves submitted choice after delayed stream failure`, async () => {
        const h = await setup({ withChat: true }), pending = deferred();
        try {
            await settle(); h.connectSelection(); h.plugins.insertPluginToInput(reviewer());
            h.state.agentMode.value = mode; h.state.paperActiveTab.value = 'dialog';
            h.state.currentModel.value = 'owner-selected-model';
            h.respondWith(call => call.path === '/chat/stream' ? pending.promise : jsonResponse(success()));
            const sending = h.state.sendMessage('review this bounded excerpt');
            await settle();
            assert.deepEqual(h.chatCalls()[0].payload.skill_ids, ['academic-review']);
            h.plugins.removeActiveInputPlugin(reviewer().id);
            h.state.currentModel.value = 'later-selected-model';
            pending.reject(new Error('synthetic stream unavailable'));
            await sending;
            // A stream failure cannot safely repeat the invocation through
            // /chat; preserve the submitted snapshot and expose uncertainty.
            assert.equal(h.chatCalls().length, 1);
            assert.equal(h.chatCalls()[0].payload.agent_model, 'owner-selected-model');
            if (mode === 'chat') {
                assert.deepEqual(h.chatCalls()[0].payload.skill_ids, ['academic-review']);
                assert.equal(h.state.modeMessageBuckets.value.chat.at(-1).deliveryStatus, 'unknown');
                assert.match(h.state.modeMessageBuckets.value.chat.at(-1).deliveryError, /重试可能重复执行/);
            } else {
                assert.equal(h.state.modeMessageBuckets.value.paper.at(-1).syncState, 'failed');
            }
            assert.deepEqual(h.plugins.selectedChatSkillIds.value, []);
        } finally { await h.close(); }
    });
}

// Both authoritative error forms are supported within the original stream.
// The removed nonstream fallback was a new execution without idempotency proof.
for (const transport of ['error-event', 'completion-error']) {
    for (const error of ['model_error', 'model_unavailable', 'empty_response']) {
        test(`student Work skill: ${transport} ${error} preserves terminal status, explicit UI error and no saved assistant`, async () => {
            const h = await setup({ withChat: true });
            try {
                await settle(); h.connectSelection(); h.plugins.insertPluginToInput(reviewer()); h.state.agentMode.value = 'chat';
                const status = error === 'empty_response' ? 'empty' : 'failed';
                const message = `${error}: synthetic provider returned no reply`;
                const completion = { content: '', reply: '', delivery_status: status, error, message, history_saved: false, history_receipt: { user_message_id: 901, assistant_message_id: null } };
                h.respondWith(call => {
                    assert.equal(call.path, '/chat/stream', 'Terminal model failure must never replay through fallback');
                    if (transport === 'completion-error') return streamResponse([{ type: 'complete', ...completion }]);
                    const event = error === 'model_unavailable' ? { type: error, model: 'chosen-model', message } : { type: 'error', code: error, message };
                    return streamResponse([event, { type: 'complete', content: '', delivery_status: status, history_saved: false, history_receipt: completion.history_receipt }]);
                });
                await h.state.sendMessage('review excerpt');
                const assistant = h.state.modeMessageBuckets.value.chat.at(-1);
                assert.equal(assistant.deliveryStatus, status, 'Empty canonical content must not overwrite an explicit failed status');
                assert.equal(assistant.syncState, 'failed');
                assert.ok(!String(assistant.id).startsWith('db-'));
                assert.equal(assistant.deliveryError, message, 'Human-readable provider failure must survive canonical empty content');
                assert.doesNotMatch(assistant.content, /已保存|已同步/);
                assert.equal(h.chatCalls().length, 1);
                assert.equal(h.state.currentModel.value, 'Auto Mode', 'Failure must not switch models');
            } finally { await h.close(); }
        });
    }
}

test('student Work skill: authoritative context invalidation cannot be revived by a local model error', async () => {
    const h = await setup({ withChat: true });
    try {
        await settle(); h.connectSelection(); h.plugins.insertPluginToInput(reviewer()); h.state.agentMode.value = 'chat';
        h.respondWith(() => streamResponse([
            { type: 'error', code: 'model_error', message: 'obsolete provider error' },
            { type: 'complete', content: '', delivery_status: 'failed', history_saved: false, history_invalidated: true, history_receipt: { user_message_id: null, assistant_message_id: null } }
        ]));
        await h.state.sendMessage('obsolete task');
        assert.deepEqual(h.state.modeMessageBuckets.value.chat, []);
    } finally { await h.close(); }
});

for (const eventType of ['model_unavailable', 'error']) {
    test(`student Work skill: unselected ${eventType} followed by authoritative saved reset remains a saved legacy reply`, async () => {
        const h = await setup({ withChat: true });
        try {
            await settle(); h.connectSelection();
            h.state.agentMode.value = eventType === 'error' ? 'rag' : 'chat';
            const mode = h.state.agentMode.value;
            const canonical = 'legacy persisted fallback from the existing backend route';
            h.respondWith(call => {
                assert.equal(call.path, '/chat/stream', 'Legacy recovery is server-owned, not a second frontend request');
                assert.equal('skill_ids' in call.payload, false);
                return streamResponse([
                    { type: eventType, code: 'model_error', model: 'legacy-model', message: 'transient legacy invocation failure' },
                    { type: 'reset', content: canonical },
                    { type: 'complete', ...success(), content: canonical }
                ]);
            });
            await h.state.sendMessage('unselected legacy task');
            const rows = h.state.modeMessageBuckets.value[mode];
            assert.equal(rows.at(-1).content, canonical);
            assert.equal(rows.at(-1).deliveryStatus, 'complete');
            assert.ok(!rows.at(-1).deliveryError, 'An authoritative saved legacy terminal supersedes its transient error');
            assert.deepEqual(rows.map(row => [row.id, row.syncState]), [['db-801', 'saved'], ['db-802', 'saved']]);
            assert.equal(h.chatCalls().length, 1);
            assert.deepEqual(h.plugins.selectedChatSkillIds.value, []);
        } finally { await h.close(); }
    });
}

test('student Work skill: main wires explicit selection and template exposes bounded skill and unavailable labels', async () => {
    const main = readFileSync(new URL('../js/main.js', import.meta.url), 'utf8');
    const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
    assert.match(main, /chat\.setChatSkillSelectionResolver\(\(\) => pluginsState\.selectedChatSkillIds\.value\)/);
    assert.match(html, /getPluginExecutionLabel\(plugin\)/);
    assert.match(html, /msg\.deliveryError/);
    const start = html.indexOf('<button v-else-if="selectedPluginDetail.executionKind');
    const end = html.indexOf('</button>', start);
    assert.ok(start >= 0 && end > start, 'Reviewer detail must expose a real explicit selection action');
    const h = await setup();
    try {
        h.plugins.openPluginDetail(reviewer());
        // Compile the real branch as an isolated conditional; a standalone
        // v-else-if otherwise lacks its adjacent search-source branch.
        const fragment = html.slice(start, end + '</button>'.length).replace('v-else-if=', 'v-if=');
        const render = Vue.compile(fragment, { hoistStatic: false, decodeEntities: raw => raw, onError(error) { throw error; } });
        const node = render(Vue.reactive({ ...h.plugins }), []);
        assert.equal(node.type, 'button');
        node.props.onClick();
        assert.deepEqual(h.plugins.selectedChatSkillIds.value, ['academic-review']);
        assert.equal(h.plugins.selectedPluginDetail.value, null);
        assert.equal(h.calls.length, 0, 'Selection does not submit a request');
    } finally { await h.close(); }
});
