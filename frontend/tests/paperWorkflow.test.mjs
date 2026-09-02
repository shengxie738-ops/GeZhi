import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
    CHAT_AGENT_MODES,
    normalizeAgentMode,
    getChatStorageKey,
    buildChatPayload,
    mapHistoryRecordToMessage,
    sanitizeStoredMessagesForMode
} from '../js/utils/chatModes.js';
import {
    PROJECT_DEFAULT_ID,
    PROJECT_TUTOR_ID,
    PROJECT_RAG_ID,
    PROJECT_PAPER_ID,
    INITIAL_SYSTEM_PROJECTS,
    detectMessageMode,
    groupMessagesIntoConversations,
    groupConversationsByProjects
} from '../js/utils/conversations.js';

test('Paper Mode: CHAT_AGENT_MODES and normalizeAgentMode', () => {
    assert.equal(CHAT_AGENT_MODES.paper.id, 'paper');
    assert.equal(CHAT_AGENT_MODES.paper.defaultAgentId, 'agent_paper');
    assert.equal(normalizeAgentMode('paper'), 'paper');
    assert.equal(normalizeAgentMode('academic'), 'paper');
    assert.equal(normalizeAgentMode('scholar'), 'paper');
    assert.equal(getChatStorageKey('test_user', 'paper'), 'messages:test_user:paper');
});

test('Paper Mode: buildChatPayload should pass paper mode and model properly', () => {
    const payload = buildChatPayload({
        message: '检索强化学习论文',
        agentMode: 'paper',
        model: 'qwen3.7-max'
    });
    assert.equal(payload.agent_mode, 'paper');
    assert.equal(payload.force_rag, false);
    assert.equal(payload.agent_model, 'qwen3.7-max');
});

test('Paper Mode: detectMessageMode should identify paper messages reliably', () => {
    assert.equal(detectMessageMode({ mode: 'paper' }), 'paper');
    assert.equal(detectMessageMode({ agentMode: 'paper' }), 'paper');
    assert.equal(detectMessageMode({ senderId: 'agent_paper' }), 'paper');
    assert.equal(detectMessageMode({ senderName: 'PaperBot' }), 'paper');
    assert.equal(detectMessageMode({ senderName: '论文研读助手' }), 'paper');
});

test('Paper Mode: groupMessagesIntoConversations should keep paper mode and fallback to proj-paper', () => {
    const msgs = [
        { id: 101, senderType: 'user', content: '请查找有关扩散模型的经典文献', mode: 'paper' },
        { id: 102, senderType: 'agent', senderId: 'agent_paper', content: 'DDPM 与 SGM 是经典奠基之作...', mode: 'paper' }
    ];
    const convs = groupMessagesIntoConversations(msgs);
    assert.equal(convs.length, 1);
    assert.equal(convs[0].mode, 'paper');
    assert.equal(convs[0].projectId, PROJECT_PAPER_ID);
    assert.equal(convs[0].messages.length, 2);
});

test('Paper Mode: groupConversationsByProjects should place paper conv under proj-paper', () => {
    const msgs = [
        { id: 201, senderType: 'user', content: 'Attention Is All You Need 深度拆解', mode: 'paper', projectId: PROJECT_PAPER_ID },
        { id: 202, senderType: 'agent', senderId: 'agent_paper', content: '核心机制为 Multi-Head Attention...', mode: 'paper', projectId: PROJECT_PAPER_ID }
    ];
    const tree = groupConversationsByProjects(msgs, INITIAL_SYSTEM_PROJECTS);
    const paperProj = tree.find(p => p.id === PROJECT_PAPER_ID);
    assert.ok(paperProj, 'projectTaskTree 必须包含 proj-paper 分组');
    assert.equal(paperProj.tasks.length, 1);
    assert.equal(paperProj.tasks[0].title.startsWith('Attention Is All You Nee'), true);
});

test('Paper Mode Audit: mapHistoryRecordToMessage should include mode, projectId, and proper senderId', () => {
    const dbRecord = {
        id: 999,
        role: 'assistant',
        content: '这是学术论文综述内容',
        agent_mode: 'paper',
        sender_id: 'agent_paper',
        created_at: '2026-09-02 23:00:00'
    };
    const mapped = mapHistoryRecordToMessage(dbRecord);
    assert.equal(mapped.mode, 'paper', '历史映射必须包含 mode: paper');
    assert.equal(mapped.projectId, PROJECT_PAPER_ID, '历史映射必须包含 projectId: proj-paper');
    assert.equal(mapped.senderId, 'agent_paper', '历史映射发送者必须保留 agent_paper');

    // 针对 sender_id 为空的边界情况
    const fallbackMapped = mapHistoryRecordToMessage({
        id: 1000,
        role: 'assistant',
        content: '测试 fallback',
        agent_mode: 'paper',
        created_at: '2026-09-02 23:01:00'
    });
    assert.equal(fallbackMapped.senderId, 'agent_paper', 'senderId 为空时应回退到 agent_paper 而非 agent_tutor');
});
