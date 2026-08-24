export const EARLY_CONVERSATION_TITLE = '早期消息';
export const UNTITLED_CONVERSATION_TITLE = '未命名对话';
export const DEFAULT_PROJECT_ID = 'proj-default';
export const DEFAULT_PROJECT_NAME = '默认项目';

const TITLE_MAX_LENGTH = 24;

export function truncateConversationTitle(content, maxLength = TITLE_MAX_LENGTH) {
    const text = String(content || '').replace(/\s+/g, ' ').trim();
    if (!text) return '';
    return text.length > maxLength ? `${text.slice(0, maxLength)}…` : text;
}

export function groupMessagesIntoConversations(messages = []) {
    if (!Array.isArray(messages)) return [];
    const conversations = [];
    let earlyGroup = null;

    messages.forEach(message => {
        if (!message || typeof message !== 'object') return;
        const msgProjectId = message.projectId || DEFAULT_PROJECT_ID;
        if (message.senderType === 'user') {
            conversations.push({
                id: `conv-${String(message.id)}`,
                projectId: msgProjectId,
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
        } else {
            if (!earlyGroup) {
                earlyGroup = {
                    id: 'conv-early',
                    projectId: msgProjectId,
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
    const projectList = Array.isArray(projects) && projects.length > 0 ? [...projects] : [
        { id: DEFAULT_PROJECT_ID, name: DEFAULT_PROJECT_NAME, expanded: true }
    ];

    const projectMap = new Map();
    projectList.forEach(p => {
        projectMap.set(p.id, {
            id: p.id,
            name: p.name || DEFAULT_PROJECT_NAME,
            expanded: p.expanded !== false,
            createdAt: p.createdAt || 0,
            tasks: []
        });
    });

    if (!projectMap.has(DEFAULT_PROJECT_ID)) {
        projectMap.set(DEFAULT_PROJECT_ID, {
            id: DEFAULT_PROJECT_ID,
            name: DEFAULT_PROJECT_NAME,
            expanded: true,
            createdAt: 0,
            tasks: []
        });
    }

    allConversations.forEach(conv => {
        const targetProjectId = conv.projectId || DEFAULT_PROJECT_ID;
        let proj = projectMap.get(targetProjectId);
        if (!proj) {
            proj = projectMap.get(DEFAULT_PROJECT_ID);
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
