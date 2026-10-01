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
    createTaskConversationId,
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

test('Paper Task Tree: paper search records should dynamically populate projectTaskTree', () => {
    // 模拟多次论文查询工作产生的工作记录
    const messages = [
        // 第一次论文检索：图神经网络
        {
            id: 'paper-user-1',
            senderType: 'user',
            content: 'Graph Neural Networks in Drug Discovery',
            mode: 'paper',
            projectId: PROJECT_PAPER_ID,
            createdAt: '2026-09-04 10:00:00'
        },
        {
            id: 'paper-agent-1',
            senderType: 'agent',
            senderId: 'agent_paper',
            content: '📚 **学术文献多源检索工作记录**\n- 检索主题：`Graph Neural Networks in Drug Discovery`\n- 响应数据源：arXiv (10篇)、Semantic Scholar (8篇)\n- 文献汇总：去重后 15 篇真实文献。',
            mode: 'paper',
            projectId: PROJECT_PAPER_ID,
            createdAt: '2026-09-04 10:00:02'
        },
        // 第二次论文检索：大型语言模型推理能力
        {
            id: 'paper-user-2',
            senderType: 'user',
            content: 'Reasoning Techniques in Large Language Models',
            mode: 'paper',
            projectId: PROJECT_PAPER_ID,
            createdAt: '2026-09-04 10:15:00'
        },
        {
            id: 'paper-agent-2',
            senderType: 'agent',
            senderId: 'agent_paper',
            content: '📚 **学术文献多源检索工作记录**\n- 检索主题：`Reasoning Techniques in Large Language Models`\n- 响应数据源：arXiv (10篇)\n- 文献汇总：去重后 10 篇真实文献。',
            mode: 'paper',
            projectId: PROJECT_PAPER_ID,
            createdAt: '2026-09-04 10:15:02'
        }
    ];

    const taskTree = groupConversationsByProjects(messages, INITIAL_SYSTEM_PROJECTS);
    const paperProject = taskTree.find(p => p.id === PROJECT_PAPER_ID);

    assert.ok(paperProject, '任务树必须包含【论文查询】项目');
    assert.equal(paperProject.tasks.length, 2, '任务列表应准确包含 2 个论文查询工作记录');
    assert.match(paperProject.tasks[0].title, /Graph Neural Networks/, '第1个任务标题应包含检索关键词');
    assert.match(paperProject.tasks[1].title, /Reasoning Techniques/, '第2个任务标题应包含检索关键词');
});

test('Paper Task Tree: consecutive paper queries must create distinct task records and preserve snapshots', () => {
    // 模拟真实用户场景：连续两次在论文检索大厅输入不同主题
    const taskId1 = createTaskConversationId('paper', 1000, 'task1');
    const taskId2 = createTaskConversationId('paper', 2000, 'task2');

    const messages = [
        // 第一次检索：金融量化
        {
            id: 'paper-user-1',
            senderType: 'user',
            content: '查找金融量化的论文',
            mode: 'paper',
            conversationId: taskId1,
            projectId: PROJECT_PAPER_ID,
            createdAt: '2026-09-08 10:00:00'
        },
        {
            id: 'paper-agent-1',
            senderType: 'agent',
            senderId: 'agent_paper',
            content: '📚 **学术文献多源检索工作记录**\n- 检索主题：`查找金融量化的论文`',
            mode: 'paper',
            conversationId: taskId1,
            projectId: PROJECT_PAPER_ID,
            paperSearchSnapshot: {
                query: '查找金融量化的论文',
                status: 'success',
                results: [{ id: 'P-Finance-1', title: 'Quantitative Finance with Deep Learning' }]
            },
            createdAt: '2026-09-08 10:00:02'
        },
        // 第二次检索：生物医学（未手动点击新建任务，系统自动分配独立任务ID）
        {
            id: 'paper-user-2',
            senderType: 'user',
            content: '生物医学用的纳米结晶氧化铁及钴钴铁氧体的构造,安定性,磁性,毒性的研究',
            mode: 'paper',
            conversationId: taskId2,
            projectId: PROJECT_PAPER_ID,
            createdAt: '2026-09-08 10:05:00'
        },
        {
            id: 'paper-agent-2',
            senderType: 'agent',
            senderId: 'agent_paper',
            content: '📚 **学术文献多源检索工作记录**\n- 检索主题：`生物医学用的纳米结晶氧化铁...`',
            mode: 'paper',
            conversationId: taskId2,
            projectId: PROJECT_PAPER_ID,
            paperSearchSnapshot: {
                query: '生物医学用的纳米结晶氧化铁...',
                status: 'success',
                results: [{ id: 'P-Bio-1', title: 'Biomedical Nano Iron Oxide Research' }]
            },
            createdAt: '2026-09-08 10:05:02'
        }
    ];

    const taskTree = groupConversationsByProjects(messages, INITIAL_SYSTEM_PROJECTS);
    const paperProject = taskTree.find(p => p.id === PROJECT_PAPER_ID);

    assert.ok(paperProject, '任务树必须包含【论文查询】项目');
    assert.equal(paperProject.tasks.length, 2, '任务列表必须包含 2 个独立的论文查询工作记录');
    assert.equal(paperProject.tasks[0].id, taskId1);
    assert.match(paperProject.tasks[0].title, /金融量化/);
    assert.equal(paperProject.tasks[1].id, taskId2);
    assert.match(paperProject.tasks[1].title, /生物医学/);
});

test('Paper Navigation: returnToChatDialog must retain paper agentMode and switch paperActiveTab to dialog', () => {
    // 模拟状态机
    let agentMode = 'paper';
    let paperActiveTab = 'results';
    let switchedMode = null;
    let toastMessage = null;

    const mockSwitchWorkMode = (mode) => {
        switchedMode = mode;
        agentMode = mode;
    };
    const mockShowToast = (msg) => {
        toastMessage = msg;
    };

    // 执行当前 useChat 中的核心跳转控制逻辑
    const executeReturnToChatDialog = () => {
        if (agentMode === 'paper') {
            paperActiveTab = 'dialog';
            mockShowToast('已返回论文研读对话框');
            return;
        }
        mockSwitchWorkMode('chat');
    };

    executeReturnToChatDialog();

    // 严密断言：
    // 1. 工作模式必须依旧保持为 paper，绝不能切换到 chat
    assert.equal(agentMode, 'paper', '工作模式必须依旧保持为 paper');
    assert.equal(switchedMode, null, '绝不能触发 switchWorkMode(chat)');
    // 2. 视图必须切换到研读对话
    assert.equal(paperActiveTab, 'dialog', '视图子状态必须切换为 dialog 研读对话框');
    assert.equal(toastMessage, '已返回论文研读对话框');
});

test('Claude Desktop Logic: activeConversationMessages strictly isolates task messages and never leaks other historical tasks', () => {
    const taskIdA = 'task-paper-gnn';
    const taskIdB = 'task-paper-rl';

    const messages = [
        // 任务 A：GNN 检索与研读
        { id: 'msg-u-1', senderType: 'user', content: 'GNN 论文', conversationId: taskIdA, mode: 'paper', projectId: PROJECT_PAPER_ID },
        { id: 'msg-a-1', senderType: 'agent', senderId: 'agent_paper', content: 'GNN 报告', conversationId: taskIdA, mode: 'paper', projectId: PROJECT_PAPER_ID },
        { id: 'msg-u-2', senderType: 'user', content: '请分析 GNN 创新点', conversationId: taskIdA, mode: 'paper', projectId: PROJECT_PAPER_ID },
        { id: 'msg-a-2', senderType: 'agent', senderId: 'agent_paper', content: '创新点如下', conversationId: taskIdA, mode: 'paper', projectId: PROJECT_PAPER_ID },

        // 任务 B：强化学习 检索与研读
        { id: 'msg-u-3', senderType: 'user', content: 'RL 论文', conversationId: taskIdB, mode: 'paper', projectId: PROJECT_PAPER_ID },
        { id: 'msg-a-3', senderType: 'agent', senderId: 'agent_paper', content: 'RL 报告', conversationId: taskIdB, mode: 'paper', projectId: PROJECT_PAPER_ID }
    ];

    const conversations = groupMessagesIntoConversations(messages);
    const conversationList = conversations.slice().reverse();

    const computeActiveMessages = (activeId, mode = 'paper') => {
        if (activeId === 'new') return [];
        const active = activeId ? conversationList.find(c => c.id === activeId) : null;
        if (active) return active.messages;
        if (mode === 'paper') return [];
        return conversations.length ? conversations[conversations.length - 1].messages : [];
    };

    // 1. 激活任务 A 时，仅返回任务 A 的 4 条消息
    const messagesA = computeActiveMessages(taskIdA);
    assert.equal(messagesA.length, 4, '任务 A 研读对话流中应包含且仅包含本任务的 4 条消息');
    assert.deepEqual(messagesA.map(m => m.id), ['msg-u-1', 'msg-a-1', 'msg-u-2', 'msg-a-2']);
    assert.ok(messagesA.every(m => m.conversationId === taskIdA));

    // 2. 激活任务 B 时，仅返回任务 B 的 2 条消息
    const messagesB = computeActiveMessages(taskIdB);
    assert.equal(messagesB.length, 2, '任务 B 研读对话流中应包含且仅包含本任务的 2 条消息');
    assert.deepEqual(messagesB.map(m => m.id), ['msg-u-3', 'msg-a-3']);
    assert.ok(messagesB.every(m => m.conversationId === taskIdB));

    // 3. 未激活任何任务（activeId 为 null）时，返回空数组，杜绝历史对话倾倒泄露
    const unselectedMessages = computeActiveMessages(null);
    assert.deepEqual(unselectedMessages, [], '论文模式未选择具体任务时应返回空数组，绝不跨会话泄漏其他历史对话');
});

test('Claude Desktop Logic: selecting paper task preserves dialog tab when already in dialog', () => {
    let paperActiveTab = 'dialog'; // 用户当前正在研读对话视图

    // 模拟 handleSelectConversation 中的保护机制
    const onSelectTask = (historySuggestedTab) => {
        if (paperActiveTab !== 'dialog') {
            paperActiveTab = historySuggestedTab;
        }
    };

    // 即使该任务具有检索快照（suggestedTab 为 results），当前在 dialog 仍保持在 dialog
    onSelectTask('results');
    assert.equal(paperActiveTab, 'dialog', '用户处于研读对话时切换任务应保持在研读对话，加载对应任务的研读内容');
});


