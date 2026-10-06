import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import { normalizeAgentMode, validateChatSkillSelection } from '../js/utils/chatModes.js';

const source = readFileSync(new URL('../js/hooks/useChat.js', import.meta.url), 'utf8');

assert.match(source, /const visualGuidePrompt = ref\(''\);/);
assert.match(source, /const visualGuideHistory = ref\(\[\]\);/);
assert.doesNotMatch(source, /const visualGuidePrompt = ref\('.*Transformer.*'\);/);
assert.match(source, /const shouldTriggerVisualGuideGeneration = \(prompt\) => \{/);

const switchMatch = source.match(/const switchVisualGuideType = \(type\) => \{([\s\S]*?)\n    \};/);
assert.ok(switchMatch, 'switchVisualGuideType definition should exist');
assert.match(switchMatch[1], /visualGuideType\.value = type;/);
assert.match(switchMatch[1], /if \(!visualGuidePrompt\.value\.trim\(\)\) return;/);
assert.match(switchMatch[1], /generateVisualGuide\(visualGuidePrompt\.value,\s*\{\s*reason:\s*'tab-demand'\s*\}\);/);

const regenerateMatch = source.match(/const regenerateVisualGuide = \(\) => \{([\s\S]*?)\n    \};/);
assert.ok(regenerateMatch, 'regenerateVisualGuide definition should exist');
assert.match(regenerateMatch[1], /if \(!visualGuidePrompt\.value\.trim\(\)\) return;/);
assert.match(regenerateMatch[1], /generateVisualGuide\(visualGuidePrompt\.value,\s*\{\s*reason:\s*'regenerate',\s*force:\s*true\s*\}\);/);

const sendMatch = source.match(/const sendMessage\s*=\s*async\s*\(overrideText\s*=\s*null\)\s*=>\s*\{([\s\S]*?)\n    \};/);
assert.ok(sendMatch, 'sendMessage definition should exist');

// Run the actual send body with isolated in-memory boundaries. No hook startup,
// network, storage, timers or rendering is needed to test its dispatch contract.
function sendHarness(mode = 'tutor') {
  const guideCalls = [];
  const sessionEvents = [];
  const context = {
    AbortController,
    owner: 'synthetic-student', sessionGeneration: 3, navigationGeneration: 4,
    chatSendController: null,
    inputText: { value: '输入框问题' }, thinkingAgent: { value: null },
    chatContainer: { value: null }, forceRAG: { value: mode === 'rag' },
    agentMode: { value: mode }, blockedWriteModes: new Set(),
    selectedRepositoryId: { value: 'synthetic-repository' },
    selectedCourseDatasetIds: { value: ['synthetic-course-dataset'] },
    activeProjectId: { value: 'synthetic-project' }, currentModel: { value: 'synthetic-model' },
    visualGuideType: { value: 'unchanged' }, historyError: { value: '' },
    modeMessageBuckets: { value: { tutor: [], chat: [], rag: [], paper: [] } },
    computed: getter => ({ get value() { return getter(); } }),
    normalizeAgentMode, validateChatSkillSelection,
    handleSessionStorage: event => sessionEvents.push(event.key),
    getSessionId: () => context.owner,
    isSessionCurrent: (owner, generation) => owner === context.owner && generation === context.sessionGeneration,
    getChatSkillSelection: () => [],
    getConversationIdForSend: () => 'synthetic-conversation',
    getSystemProjectIdForMode: mode => `system:${mode}`,
    getActiveChatAgent: () => ({ id: 'synthetic-agent' }),
    generateVisualGuide: (prompt, options) => guideCalls.push({ prompt, options }),
    showToast: () => { throw new Error('Unexpected send validation failure'); },
    sendStreamingMessage: async (...args) => {
      context.sendArgs = args;
      assert.equal(args[15].isCurrent(), true, 'The dispatched send owns its active request');
      return context.stream ? context.stream(args) : true;
    },
  };
  const sendMessage = runInNewContext(`${sendMatch[0]}\nsendMessage;`, context);
  return { sendMessage, context, guideCalls, sessionEvents };
}

for (const mode of ['tutor', 'chat', 'rag', 'paper']) {
  const { sendMessage, context, guideCalls, sessionEvents } = sendHarness(mode);
  assert.equal(await sendMessage('显式发送问题'), true);
  assert.equal(sessionEvents.join(','), 'token');
  assert.equal(context.sendArgs[0], '显式发送问题');
  assert.equal(context.sendArgs[6], 'synthetic-student');
  assert.equal(context.sendArgs[7], mode);
  assert.equal(context.sendArgs[8], mode === 'rag' ? 'synthetic-repository' : '');
  assert.equal(context.sendArgs[10]?.join(',') ?? null, mode === 'rag' ? 'synthetic-course-dataset' : null);
  if (mode === 'rag') assert.notEqual(context.sendArgs[10], context.selectedCourseDatasetIds.value, 'Dataset selection is captured for this send');
  assert.equal(context.sendArgs[13], 'synthetic-conversation');
  assert.equal(context.sendArgs[14], 'synthetic-project');
  assert.equal(Object.isFrozen(context.sendArgs[15].skillIds), true);
  assert.equal(guideCalls.length, mode === 'tutor' ? 1 : 0, `${mode} guide dispatch`);
  assert.equal(context.visualGuideType.value, mode === 'tutor' ? 'steps' : 'unchanged');
  if (mode === 'tutor') {
    assert.equal(guideCalls[0].prompt, '显式发送问题');
    assert.equal(guideCalls[0].options.reason, 'student-question');
    assert.equal(guideCalls[0].options.force, true);
  }
  assert.equal(context.chatSendController, null);
  assert.equal(context.thinkingAgent.value, null);
}

const inputSend = sendHarness();
assert.equal(await inputSend.sendMessage(), true);
assert.equal(inputSend.context.sendArgs[0], '输入框问题');
for (const blocked of ['blank', 'busy', 'write-blocked']) {
  const { sendMessage, context, guideCalls } = sendHarness();
  if (blocked === 'blank') context.inputText.value = '  ';
  if (blocked === 'busy') context.thinkingAgent.value = 'occupied';
  if (blocked === 'write-blocked') context.blockedWriteModes.add('tutor');
  assert.equal(await sendMessage(), false, blocked);
  assert.equal(context.sendArgs, undefined);
  assert.equal(guideCalls.length, 0);
}

// Preserve live history reconciliation in the captured mode and detach on logout.
const captured = sendHarness();
const originalMessages = captured.context.modeMessageBuckets.value.tutor;
captured.context.stream = async args => {
  const messages = args[1];
  captured.context.agentMode.value = 'rag';
  assert.equal(messages.value, originalMessages);
  const reconciled = ['reconciled-tutor-history'];
  captured.context.modeMessageBuckets.value.tutor = reconciled;
  assert.equal(messages.value, reconciled);
  captured.context.sessionGeneration += 1;
  assert.equal(args[15].isCurrent(), false);
  assert.equal(messages.value, originalMessages);
  return true;
};
assert.equal(await captured.sendMessage(), true);

for (const fence of ['owner', 'navigation', 'abort', 'replacement']) {
  const { sendMessage, context } = sendHarness();
  const replacement = new AbortController();
  context.stream = async args => {
    context.thinkingAgent.value = 'new-owner';
    if (fence === 'owner') context.owner = 'different-student';
    if (fence === 'navigation') context.navigationGeneration += 1;
    if (fence === 'abort') context.chatSendController.abort();
    if (fence === 'replacement') context.chatSendController = replacement;
    assert.equal(args[15].isCurrent(), false, fence);
    return true;
  };
  assert.equal(await sendMessage(), true);
  assert.equal(context.chatSendController, fence === 'replacement' ? replacement : null);
  assert.equal(context.thinkingAgent.value, fence === 'replacement' ? 'new-owner' : null);
}

const failed = sendHarness();
failed.context.stream = async () => { throw new Error('synthetic-stream-failure'); };
await assert.rejects(failed.sendMessage(), /synthetic-stream-failure/);
assert.equal(failed.context.chatSendController, null);
assert.equal(failed.context.thinkingAgent.value, null);

console.log('visualGuideInteraction tests passed');
