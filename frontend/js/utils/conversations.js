export const EARLY_CONVERSATION_TITLE = '早期消息';
export const UNTITLED_CONVERSATION_TITLE = '未命名对话';

export const PROJECT_DEFAULT_ID = 'proj-default';
export const PROJECT_DEFAULT_NAME = '默认任务';
export const PROJECT_TUTOR_ID = 'proj-tutor';
export const PROJECT_TUTOR_NAME = '引导式学习';
export const PROJECT_RAG_ID = 'proj-rag';
export const PROJECT_RAG_NAME = '知识库检索';
export const PROJECT_PAPER_ID = 'proj-paper';
export const PROJECT_PAPER_NAME = '论文查询';

export const DEFAULT_PROJECT_ID = PROJECT_DEFAULT_ID;
export const DEFAULT_PROJECT_NAME = PROJECT_DEFAULT_NAME;

export const INITIAL_SYSTEM_PROJECTS = [
    { id: PROJECT_DEFAULT_ID, name: PROJECT_DEFAULT_NAME, mode: 'chat', icon: 'ph-chats-circle', expanded: true, isSystem: true },
    { id: PROJECT_TUTOR_ID, name: PROJECT_TUTOR_NAME, mode: 'tutor', icon: 'ph-graduation-cap', expanded: true, isSystem: true },
    { id: PROJECT_RAG_ID, name: PROJECT_RAG_NAME, mode: 'rag', icon: 'ph-database', expanded: true, isSystem: true },
    { id: PROJECT_PAPER_ID, name: PROJECT_PAPER_NAME, mode: 'paper', icon: 'ph-article', expanded: true, isSystem: true }
];

const TITLE_MAX_LENGTH = 24;

export function truncateConversationTitle(content, maxLength = TITLE_MAX_LENGTH) {
    const text = String(content || '').replace(/\s+/g, ' ').trim();
    if (!text) return '';
    return text.length > maxLength ? `${text.slice(0, maxLength)}…` : text;
}

export function detectMessageMode(message) {
    if (!message || typeof message !== 'object') return 'chat';
    if (message.mode === 'paper' || message.agentMode === 'paper') return 'paper';
    if (message.mode === 'rag' || message.agentMode === 'rag') return 'rag';
    if (message.mode === 'tutor' || message.agentMode === 'tutor') return 'tutor';
    if (message.mode === 'chat' || message.agentMode === 'chat') return 'chat';
    if (message.senderName?.includes('论文') || message.senderName?.includes('PaperBot') || message.senderId === 'agent_paper') return 'paper';
    if (message.senderName?.includes('知识库') || message.senderName?.includes('Researcher')) return 'rag';
    if (message.senderName?.includes('导师') || message.senderName?.includes('Prof')) return 'tutor';
    return 'chat';
}

export function groupMessagesIntoConversations(messages = []) {
    if (!Array.isArray(messages)) return [];
    const conversations = [];
    let earlyGroup = null;

    messages.forEach(message => {
        if (!message || typeof message !== 'object') return;
        const mode = detectMessageMode(message);
        const fallbackProjectId = mode === 'paper' ? PROJECT_PAPER_ID : (mode === 'rag' ? PROJECT_RAG_ID : (mode === 'tutor' ? PROJECT_TUTOR_ID : PROJECT_DEFAULT_ID));
        const msgProjectId = message.projectId ? message.projectId : fallbackProjectId;

        if (message.senderType === 'user') {
            conversations.push({
                id: `conv-${String(message.id)}`,
                projectId: msgProjectId,
                mode,
                title: truncateConversationTitle(message.content) || UNTITLED_CONVERSATION_TITLE,
                startedTime: message.time || message.createdAt || '',
                lastTime: message.time || message.createdAt || '',
                isEarly: false,
                messages: [message]
            });
            return;
        }

        const latest = conversations[conversations.length - 1];
        if (latest) {
            latest.messages.push(message);
            latest.lastTime = message.time || message.createdAt || latest.lastTime;
            if (!latest.mode && mode) {
                latest.mode = mode;
            }
        } else {
            if (!earlyGroup) {
                earlyGroup = {
                    id: 'conv-early',
                    projectId: fallbackProjectId,
                    mode,
                    title: EARLY_CONVERSATION_TITLE,
                    startedTime: '',
                    lastTime: '',
                    isEarly: true,
                    messages: []
                };
                conversations.push(earlyGroup);
            }
            earlyGroup.messages.push(message);
            const time = message.time || message.createdAt || '';
            if (time) {
                if (!earlyGroup.startedTime) earlyGroup.startedTime = time;
                earlyGroup.lastTime = time;
            }
        }
    });

    conversations.forEach(conversation => {
        conversation.messageCount = conversation.messages.length;
    });
    return conversations;
}

export function groupConversationsByProjects(messages = [], projects = []) {
    const allConversations = groupMessagesIntoConversations(messages);
    
    // 初始化系统项目列表，确保 默认任务、引导式学习、知识库检索、论文查询 核心分组始终排在最前
    const systemMap = new Map();
    INITIAL_SYSTEM_PROJECTS.forEach(sysProj => {
        systemMap.set(sysProj.id, {
            ...sysProj,
            tasks: []
        });
    });

    const customProjects = [];
    if (Array.isArray(projects)) {
        projects.forEach(p => {
            if (systemMap.has(p.id)) {
                const sys = systemMap.get(p.id);
                sys.expanded = p.expanded !== false;
                if (p.name) sys.name = p.name;
            } else {
                customProjects.push({
                    id: p.id,
                    name: p.name || '未命名项目',
                    icon: p.icon || 'ph-folder',
                    expanded: p.expanded !== false,
                    isSystem: false,
                    createdAt: p.createdAt || 0,
                    tasks: []
                });
            }
        });
    }

    const projectMap = new Map();
    systemMap.forEach((val, key) => projectMap.set(key, val));
    customProjects.forEach(cp => projectMap.set(cp.id, cp));

    allConversations.forEach(conv => {
        let targetProjectId = conv.projectId;
        if (!targetProjectId) {
            targetProjectId = conv.mode === 'paper' ? PROJECT_PAPER_ID : (conv.mode === 'rag' ? PROJECT_RAG_ID : (conv.mode === 'tutor' ? PROJECT_TUTOR_ID : PROJECT_DEFAULT_ID));
        }

        let proj = projectMap.get(targetProjectId);
        if (!proj) {
            // 自动归类到对应系统分组
            const fallbackId = conv.mode === 'paper' ? PROJECT_PAPER_ID : (conv.mode === 'rag' ? PROJECT_RAG_ID : (conv.mode === 'tutor' ? PROJECT_TUTOR_ID : PROJECT_DEFAULT_ID));
            proj = projectMap.get(fallbackId) || systemMap.get(PROJECT_DEFAULT_ID);
        }
        proj.tasks.push(conv);
    });

    return Array.from(projectMap.values());
}

export function findConversationForMessage(conversations = [], messageId = null) {
    if (!Array.isArray(conversations) || messageId === null || messageId === undefined) return null;
    const target = String(messageId);
    return conversations.find(conversation =>
        conversation.messages.some(message => String(message.id) === target)
    ) || null;
}
