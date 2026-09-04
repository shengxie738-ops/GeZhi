import assert from 'node:assert/strict';

import {
    EARLY_CONVERSATION_TITLE,
    UNTITLED_CONVERSATION_TITLE,
    createModeMessageBuckets,
    createTaskConversationId,
    findConversationForMessage,
    flattenModeMessageBuckets,
    groupMessagesIntoConversations,
    reconcileModeHistory,
    resolveConversationIdForSend,
    truncateConversationTitle
} from '../js/utils/conversations.js';

assert.deepEqual(groupMessagesIntoConversations([]), []);
assert.deepEqual(groupMessagesIntoConversations(null), []);
assert.deepEqual(groupMessagesIntoConversations('not-array'), []);

const userMsg = (id, content, time = '2026/08/22 10:00:00') => ({
    id,
    senderType: 'user',
    content,
    time,
    createdAt: time
});
const agentMsg = (id, senderId, content, time = '2026/08/22 10:00:01') => ({
    id,
    senderType: 'agent',
    senderId,
    content,
    time,
    createdAt: time
});

// 用户提问开启一组对话，随后的智能体回复归入该组
const basic = groupMessagesIntoConversations([
    userMsg('u1', '什么是队列？', '2026/08/22 10:00:00'),
    agentMsg('a1', 'agent_tutor', '队列是先进先出…', '2026/08/22 10:00:05'),
    agentMsg('a2', 'agent_visual_guide', '[QUIZ]…', '2026/08/22 10:00:09')
]);
assert.equal(basic.length, 1);
assert.equal(basic[0].id, 'conv-u1');
assert.equal(basic[0].title, '什么是队列？');
assert.equal(basic[0].messageCount, 3);
assert.equal(basic[0].startedTime, '2026/08/22 10:00:00');
assert.equal(basic[0].lastTime, '2026/08/22 10:00:09');
assert.equal(basic[0].isEarly, false);
assert.deepEqual(basic[0].messages.map(m => m.id), ['u1', 'a1', 'a2']);

// 每条新的用户消息开启新对话，顺序保持旧→新
const multi = groupMessagesIntoConversations([
    userMsg('u1', '第一个问题', '2026/08/22 10:00:00'),
    agentMsg('a1', 'agent_tutor', '回答一', '2026/08/22 10:00:05'),
    userMsg('u2', '第二个问题', '2026/08/22 11:00:00'),
    agentMsg('a2', 'agent_tutor', '回答二', '2026/08/22 11:00:05')
]);
assert.equal(multi.length, 2);
assert.equal(multi[0].id, 'conv-u1');
assert.equal(multi[1].id, 'conv-u2');
assert.equal(multi[1].title, '第二个问题');
assert.deepEqual(multi[1].messages.map(m => m.id), ['u2', 'a2']);

// 开头孤立的智能体消息归入单组「早期消息」
const early = groupMessagesIntoConversations([
    agentMsg('a0', 'agent_tutor', '旧版欢迎语', '2026/08/21 09:00:00'),
    agentMsg('a0b', 'agent_visual_guide', '旧版引导图', '2026/08/21 09:00:02'),
    userMsg('u1', '新问题', '2026/08/22 10:00:00'),
    agentMsg('a1', 'agent_tutor', '新回答', '2026/08/22 10:00:05')
]);
assert.equal(early.length, 2);
assert.equal(early[0].id, 'conv-early');
assert.equal(early[0].title, EARLY_CONVERSATION_TITLE);
assert.equal(early[0].isEarly, true);
assert.equal(early[0].messageCount, 2);
assert.equal(early[1].id, 'conv-u1');

// 标题：折叠空白并截断
const longTitle = groupMessagesIntoConversations([
    userMsg('u1', '  帮我制定一份   大语言模型的\n学习计划，越详细越好，谢谢  ')
]);
assert.equal(longTitle[0].title, `${'帮我制定一份 大语言模型的 学习计划，越详细越好，谢谢'.slice(0, 24)}…`);

// 空内容的用户消息得到兜底标题
const blank = groupMessagesIntoConversations([userMsg('u1', '   ')]);
assert.equal(blank[0].title, UNTITLED_CONVERSATION_TITLE);

// 独立截断工具
assert.equal(truncateConversationTitle('短标题', 24), '短标题');
assert.equal(truncateConversationTitle('a'.repeat(30), 24), `${'a'.repeat(24)}…`);
assert.equal(truncateConversationTitle(null, 24), '');

// 按消息 id 定位对话
assert.equal(findConversationForMessage(multi, 'a2').id, 'conv-u2');
assert.equal(findConversationForMessage(multi, 'u1').id, 'conv-u1');
assert.equal(findConversationForMessage(multi, 'missing'), null);

// 显式任务 ID 是任务边界：同一任务中的多轮问答不能被拆成多个侧栏任务
const multiTurnTask = groupMessagesIntoConversations([
    { ...userMsg('u10', '查找 RAG 论文'), mode: 'paper', conversationId: 'task-paper-1' },
    { ...agentMsg('a10', 'agent_paper', '找到 8 篇论文'), mode: 'paper', conversationId: 'task-paper-1' },
    { ...userMsg('u11', '继续比较实验数据'), mode: 'paper', conversationId: 'task-paper-1' },
    { ...agentMsg('a11', 'agent_paper', '对比如下'), mode: 'paper', conversationId: 'task-paper-1' },
    { ...userMsg('u12', '新主题'), mode: 'paper', conversationId: 'task-paper-2' }
]);
assert.equal(multiTurnTask.length, 2);
assert.equal(multiTurnTask[0].id, 'task-paper-1');
assert.equal(multiTurnTask[0].title, '查找 RAG 论文');
assert.deepEqual(multiTurnTask[0].messages.map(message => message.id), ['u10', 'a10', 'u11', 'a11']);

// 任务树必须聚合四种功能的独立消息桶，切换当前功能不能让其他任务消失
const buckets = createModeMessageBuckets(mode => mode === 'chat'
    ? [{ ...userMsg('chat-u1', 'AI 对话历史'), mode: 'chat', conversationId: 'task-chat-1' }]
    : mode === 'paper'
        ? [{ ...userMsg('paper-u1', '论文查询历史'), mode: 'paper', conversationId: 'task-paper-3' }]
        : []);
const flattened = flattenModeMessageBuckets(buckets);
assert.equal(flattened.length, 2);
assert.deepEqual(flattened.map(message => message.conversationId), ['task-chat-1', 'task-paper-3']);

// 云端暂时返回空数组时保留本地未同步任务，防止刷新导致历史记录消失
const localOnly = [{ ...userMsg('local-u1', '离线任务'), mode: 'chat', conversationId: 'task-chat-local' }];
assert.equal(reconcileModeHistory(localOnly, []), localOnly);
const remote = [{ ...userMsg('db-u1', '云端任务'), mode: 'chat', conversationId: 'task-chat-db' }];
assert.deepEqual(
    reconcileModeHistory(localOnly, remote).map(message => message.conversationId),
    ['task-chat-db', 'task-chat-local']
);
const mirroredRemote = [{ ...localOnly[0], id: 'db-100' }];
assert.equal(reconcileModeHistory(localOnly, mirroredRemote).length, 1);

// 新建任务在当前功能内获得独立 ID；后续发送继续使用同一个任务，而不是退回默认 AI 对话
assert.equal(createTaskConversationId('paper', 123456, 'abc123'), 'task-paper-123456-abc123');
assert.equal(resolveConversationIdForSend({
    activeConversationId: 'new',
    draftConversationId: 'task-paper-new',
    latestConversationId: 'task-paper-old'
}), 'task-paper-new');
assert.equal(resolveConversationIdForSend({
    activeConversationId: 'task-paper-selected',
    draftConversationId: '',
    latestConversationId: 'task-paper-old'
}), 'task-paper-selected');
assert.equal(resolveConversationIdForSend({
    activeConversationId: null,
    draftConversationId: '',
    latestConversationId: 'task-paper-old'
}), 'task-paper-old');

// 本地旧记录继续提问时，显式沿用旧任务 ID，不能生成一个同名的重复任务
const continuedLegacyTask = groupMessagesIntoConversations([
    userMsg('legacy-u1', '旧任务第一轮'),
    agentMsg('legacy-a1', 'agent_tutor', '旧回答'),
    { ...userMsg('new-u1', '继续追问'), conversationId: 'conv-legacy-u1' },
    { ...agentMsg('new-a1', 'agent_tutor', '继续回答'), conversationId: 'conv-legacy-u1' }
]);
assert.equal(continuedLegacyTask.length, 1);
assert.deepEqual(continuedLegacyTask[0].messages.map(message => message.id), [
    'legacy-u1', 'legacy-a1', 'new-u1', 'new-a1'
]);

console.log('conversations.test.mjs: all assertions passed');
