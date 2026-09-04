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

export const CHAT_TASK_MODES = ['chat', 'tutor', 'rag', 'paper'];

export function getSystemProjectIdForMode(mode) {
    if (mode === 'paper') return PROJECT_PAPER_ID;
    if (mode === 'rag') return PROJECT_RAG_ID;
    if (mode === 'tutor') return PROJECT_TUTOR_ID;
    return PROJECT_DEFAULT_ID;
}

export function createModeMessageBuckets(readMessages = () => []) {
    return Object.fromEntries(CHAT_TASK_MODES.map(mode => {
        const storedMessages = readMessages(mode);
        return [mode, Array.isArray(storedMessages) ? storedMessages : []];
    }));
}

export function flattenModeMessageBuckets(buckets = {}) {
    return CHAT_TASK_MODES.flatMap(mode => Array.isArray(buckets?.[mode]) ? buckets[mode] : []);
}

export function reconcileModeHistory(localMessages = [], remoteMessages = []) {
    const local = Array.isArray(localMessages) ? localMessages : [];
    const remote = Array.isArray(remoteMessages) ? remoteMessages : [];
    if (remote.length === 0) return local.length > 0 ? local : [];
    if (local.length === 0) return remote;

    const signatureFor = message => {
        const conversationId = String(message?.conversationId || message?.conversation_id || '').trim();
        const role = message?.senderType || message?.role || '';
        const senderId = message?.senderId || message?.sender_id || '';
        return `${conversationId}\u0000${role}\u0000${senderId}\u0000${String(message?.content || '')}`;
    };
    const remoteIds = new Set(remote.map(message => String(message?.id || '')).filter(Boolean));
    const remainingRemoteSignatures = new Map();
    remote.forEach(message => {
        const signature = signatureFor(message);
        remainingRemoteSignatures.set(signature, (remainingRemoteSignatures.get(signature) || 0) + 1);
    });

    const merged = [...remote];
    local.forEach(message => {
        const signature = signatureFor(message);
        const matchingRemoteCount = remainingRemoteSignatures.get(signature) || 0;
        const hasMatchingRemoteId = remoteIds.has(String(message?.id || ''));
        if (hasMatchingRemoteId || matchingRemoteCount > 0) {
            if (matchingRemoteCount > 0) {
                remainingRemoteSignatures.set(signature, matchingRemoteCount - 1);
            }
            return;
        }
        merged.push(message);
    });
    return merged;
}

export function createTaskConversationId(mode = 'chat', timestamp = Date.now(), entropy = '') {
    const normalizedMode = CHAT_TASK_MODES.includes(mode) ? mode : 'chat';
    const randomPart = String(entropy || globalThis.crypto?.randomUUID?.().slice(0, 8) || Math.random().toString(36).slice(2, 10));
    return `task-${normalizedMode}-${timestamp}-${randomPart}`;
}

export function resolveConversationIdForSend({
    activeConversationId = null,
    draftConversationId = '',
    latestConversationId = ''
} = {}) {
    if (activeConversationId === 'new') return draftConversationId || '';
    return activeConversationId || latestConversationId || draftConversationId || '';
}

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
    const explicitConversations = new Map();
    const latestLegacyByMode = new Map();
    const earlyLegacyByMode = new Map();

    messages.forEach(message => {
        if (!message || typeof message !== 'object') return;
        const mode = detectMessageMode(message);
        const fallbackProjectId = getSystemProjectIdForMode(mode);
        const msgProjectId = message.projectId ? message.projectId : fallbackProjectId;
        const explicitConversationId = String(message.conversationId || message.conversation_id || '').trim();

        if (explicitConversationId) {
            let conversation = explicitConversations.get(explicitConversationId);
            if (!conversation) {
                conversation = {
                    id: explicitConversationId,
                    projectId: msgProjectId,
                    mode,
                    title: message.senderType === 'user'
                        ? (truncateConversationTitle(message.content) || UNTITLED_CONVERSATION_TITLE)
                        : EARLY_CONVERSATION_TITLE,
                    startedTime: message.time || message.createdAt || '',
                    lastTime: message.time || message.createdAt || '',
                    isEarly: message.senderType !== 'user',
                    messages: []
                };
                explicitConversations.set(explicitConversationId, conversation);
                conversations.push(conversation);
            }
            conversation.messages.push(message);
            conversation.lastTime = message.time || message.createdAt || conversation.lastTime;
            if (message.senderType === 'user' && conversation.isEarly) {
                conversation.title = truncateConversationTitle(message.content) || UNTITLED_CONVERSATION_TITLE;
                conversation.isEarly = false;
            }
            return;
        }

        if (message.senderType === 'user') {
            const conversation = {
                id: `conv-${String(message.id)}`,
                projectId: msgProjectId,
                mode,
                title: truncateConversationTitle(message.content) || UNTITLED_CONVERSATION_TITLE,
                startedTime: message.time || message.createdAt || '',
                lastTime: message.time || message.createdAt || '',
                isEarly: false,
                messages: [message]
            };
            conversations.push(conversation);
            explicitConversations.set(conversation.id, conversation);
            latestLegacyByMode.set(mode, conversation);
            return;
        }

        const latest = latestLegacyByMode.get(mode);
        if (latest) {
            latest.messages.push(message);
            latest.lastTime = message.time || message.createdAt || latest.lastTime;
            if (!latest.mode && mode) {
                latest.mode = mode;
            }
        } else {
            let earlyGroup = earlyLegacyByMode.get(mode);
            if (!earlyGroup) {
                earlyGroup = {
                    id: mode === 'chat' ? 'conv-early' : `conv-early-${mode}`,
                    projectId: fallbackProjectId,
                    mode,
                    title: EARLY_CONVERSATION_TITLE,
                    startedTime: '',
                    lastTime: '',
                    isEarly: true,
                    messages: []
                };
                earlyLegacyByMode.set(mode, earlyGroup);
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
            targetProjectId = getSystemProjectIdForMode(conv.mode);
        }

        let proj = projectMap.get(targetProjectId);
        if (!proj) {
            // 自动归类到对应系统分组
            const fallbackId = getSystemProjectIdForMode(conv.mode);
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
