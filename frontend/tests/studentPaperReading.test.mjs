import assert from 'node:assert/strict';
import test from 'node:test';
import { ref } from '../libs/vue.esm-browser.js';
import { buildChatPayload, validateChatSkillSelection } from '../js/utils/chatModes.js';
import { sendStreamingMessage } from '../js/api/streamChat.js';

globalThis.window = { dispatchEvent() {} };

const state = () => ({ messages: ref([]), thinking: ref(null), input: ref('Explain abstract'), container: ref(null) });
const stream = text => new Response(text, { headers: { 'Content-Type': 'text/event-stream' } });
const call = s => sendStreamingMessage('Explain abstract', s.messages, s.thinking, s.input, s.container,
    false, 'alice', 'paper', '', null, null, null, '', 'paper-task', '', { skillIds: [] });

test('paper forbids retrieval options even without a selected Skill', () => {
    for (const changes of [{ forceRAG: true }, { repositoryId: 'repo' }, { courseDatasetIds: ['course'] }]) {
        assert.throws(() => buildChatPayload({ message: 'question', agentMode: 'paper', ...changes }), /论文研读/);
        assert.throws(() => validateChatSkillSelection({ agentMode: 'paper', ...changes }), /论文研读/);
    }
    assert.doesNotThrow(() => buildChatPayload({ message: 'question', agentMode: 'paper', forceRAG: false,
        repositoryId: '', courseDatasetIds: [] }));
});

test('paper initial streaming transport failure never resubmits to nonstream', async () => {
    let requests = 0;
    globalThis.fetch = async () => { requests += 1; throw new Error('synthetic transport failure'); };
    const s = state();
    await call(s);
    assert.equal(requests, 1);
    assert.equal(s.messages.value.at(-1).deliveryStatus, 'failed');
    assert.equal(s.messages.value.at(-1).syncState, 'failed');
});

test('paper empty EOF never resubmits and lacks successful save receipt', async () => {
    let requests = 0;
    globalThis.fetch = async () => { requests += 1; return stream(''); };
    const s = state();
    await call(s);
    assert.equal(requests, 1);
    assert.equal(s.messages.value.at(-1).deliveryStatus, 'failed');
    assert.equal(s.messages.value.at(-1).syncState, 'failed');
});

test('paper partial EOF remains visibly failed without automatic retry', async () => {
    let requests = 0;
    globalThis.fetch = async () => { requests += 1; return stream('data: {"type":"token","content":"partial"}\n\n'); };
    const s = state();
    await call(s);
    assert.equal(requests, 1);
    assert.equal(s.messages.value.at(-1).deliveryStatus, 'failed');
    assert.equal(s.messages.value.at(-1).syncState, 'failed');
    assert.equal(s.messages.value.at(-1).content, 'partial');
});

for (const code of ['incomplete_response', 'content_filter', 'timeout', 'model_error', 'storage_error']) {
    test('paper terminal ' + code + ' issues one endpoint request and never marks temporary text saved', async () => {
        const endpoints = [];
        globalThis.fetch = async url => {
            endpoints.push(String(url));
            return stream('data: {"type":"token","content":"temporary"}\n\n' + 'data: ' + JSON.stringify({
                type: 'complete', error: code, content: '', delivery_status: 'failed', history_saved: false,
                retry_allowed: false, history_receipt: { user_message_id: 1, assistant_message_id: null }
            }) + '\n\n');
        };
        const s = state();
        await call(s);
        assert.equal(endpoints.length, 1);
        assert.ok(endpoints[0].endsWith('/chat/stream'));
        assert.equal(s.messages.value.at(-1).syncState, 'failed');
        assert.equal(s.messages.value.at(-1).deliveryStatus, 'failed');
        assert.equal(s.messages.value.at(-1).content, '');
    });
}

test('paper uncertain commit receipt asks to verify history and does not deny possible persistence', async () => {
    let requests = 0;
    globalThis.fetch = async () => { requests += 1; return stream('data: ' + JSON.stringify({
        type: 'complete', error: 'storage_error', content: '', message: '保存未确认，请刷新历史核对',
        delivery_status: 'failed', history_saved: false, history_confirmation_status: 'unknown', retry_allowed: false,
        history_receipt: { user_message_id: 1, assistant_message_id: null }
    }) + '\n\n'); };
    const s = state();
    await call(s);
    const message = s.messages.value.at(-1);
    assert.equal(requests, 1);
    assert.equal(message.syncState, 'failed');
    assert.match(message.syncError, /保存未确认.*核对/);
    assert.doesNotMatch(message.syncError, /未保存/);
    assert.equal(message.historyConfirmationStatus, 'unknown');
});
