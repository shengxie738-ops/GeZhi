import assert from 'node:assert/strict';

import {
    EARLY_CONVERSATION_TITLE,
    UNTITLED_CONVERSATION_TITLE,
    findConversationForMessage,
    groupMessagesIntoConversations,
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

console.log('conversations.test.mjs: all assertions passed');
