export const EARLY_CONVERSATION_TITLE = '早期消息';
export const UNTITLED_CONVERSATION_TITLE = '未命名对话';

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
        if (message.senderType === 'user') {
            conversations.push({
                id: `conv-${String(message.id)}`,
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

export function findConversationForMessage(conversations = [], messageId = null) {
    if (!Array.isArray(conversations) || messageId === null || messageId === undefined) return null;
    const target = String(messageId);
    return conversations.find(conversation =>
        conversation.messages.some(message => String(message.id) === target)
    ) || null;
}
