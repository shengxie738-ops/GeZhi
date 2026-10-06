export const CHAT_AGENT_MODES = {
    chat: {
        id: 'chat',
        label: 'AI 对话',
        defaultAgentId: 'agent_tutor'
    },
    tutor: {
        id: 'tutor',
        label: '引导式学习',
        defaultAgentId: 'agent_tutor'
    },
    rag: {
        id: 'rag',
        label: '知识库检索',
        defaultAgentId: 'agent_researcher'
    },
    paper: {
        id: 'paper',
        label: '论文查询',
        defaultAgentId: 'agent_paper'
    }
};

export function normalizeAgentMode(mode) {
    if (mode === 'chat' || mode === 'default' || mode === 'general') return 'chat';
    if (mode === 'paper' || mode === 'academic' || mode === 'scholar') return 'paper';
    if (mode === 'rag') return 'rag';
    return 'tutor';
}

export function getChatStorageKey(sessionId = 'guest_user', agentMode = 'tutor') {
    const userId = sessionId || 'guest_user';
    return `messages:${userId}:${normalizeAgentMode(agentMode)}`;
}

export function shouldShowHistoryButton(agentMode = 'tutor') {
    return ['chat', 'tutor', 'rag', 'paper'].includes(normalizeAgentMode(agentMode));
}

export function getHistoryPanelTitle(agentMode = 'tutor') {
    const normalized = normalizeAgentMode(agentMode);
    if (normalized === 'chat') return 'AI 对话历史记录';
    if (normalized === 'rag') return '知识库检索历史记录';
    if (normalized === 'paper') return '论文查询历史记录';
    return '引导式学习历史记录';
}

export function validateChatSkillSelection({ skillIds = [], forceRAG = false, agentMode = 'tutor', repositoryId = '', courseDatasetIds = null } = {}) {
    if (normalizeAgentMode(agentMode) === 'paper' && (forceRAG || repositoryId?.trim()
        || (courseDatasetIds && (!Array.isArray(courseDatasetIds) || courseDatasetIds.length > 0)))) {
        throw new Error('论文研读仅使用当前论文资料；请关闭强制知识库检索并移除知识库或课程选择后发送');
    }
    if (!Array.isArray(skillIds) || skillIds.length > 1 || skillIds.some(id => id !== 'academic-review')) {
        throw new Error('学术 Skill 选择无效，请重新选用 Academic Reviewer');
    }
    if (skillIds.length && (!['chat', 'paper'].includes(normalizeAgentMode(agentMode)) || forceRAG || repositoryId
        || (courseDatasetIds && (!Array.isArray(courseDatasetIds) || courseDatasetIds.length > 0)))) {
        throw new Error('学术评审 Skill 仅支持 AI 对话或论文研读；请移除此 Skill 或切换到支持的模式后发送');
    }
    return [...skillIds];
}

export function buildChatPayload({ message, forceRAG = false, sessionId = 'guest_user', agentMode = 'tutor', conversationId = '', projectId = '', repositoryId = '', agent = null, courseDatasetIds = null, model = '', skillIds = [] }) {
    const normalizedMode = normalizeAgentMode(agentMode);
    const capturedSkillIds = validateChatSkillSelection({ skillIds, forceRAG, agentMode: normalizedMode, repositoryId, courseDatasetIds });
    const resolvedModel = (model && model !== 'Auto Mode') ? model : agent?.model;
    const payload = {
        message,
        force_rag: forceRAG || normalizedMode === 'rag',
        sessionId,
        agent_mode: normalizedMode,
        conversation_id: conversationId || undefined,
        project_id: projectId || undefined,
        agent_id: agent?.id,
        agent_model: resolvedModel,
        agent_prompt: agent?.prompt
    };
    if (repositoryId) {
        payload.repository_id = repositoryId;
    }
    if (courseDatasetIds && Array.isArray(courseDatasetIds) && courseDatasetIds.length > 0) {
        payload.course_dataset_ids = courseDatasetIds;
    }
    if (capturedSkillIds.length) payload.skill_ids = capturedSkillIds;
    Object.keys(payload).forEach(key => payload[key] === undefined && delete payload[key]);
    return payload;
}

export function formatChatTimestamp(date = new Date()) {
    return new Intl.DateTimeFormat('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false
    }).format(date).replaceAll('/', '-');
}

const REFERENCE_SOURCE_PATTERN = /\n{0,2}【(?:数据结构)?知识库引用来源】[:：][ \t]*(?:\n[ \t]*[-•][ \t]*[^\n]+)*/g;

export function stripReferenceSourceBlock(text = '') {
    return String(text || '').replace(REFERENCE_SOURCE_PATTERN, '').trim();
}

export function sanitizeMessageContentForMode(content = '', agentMode = 'tutor') {
    const rawContent = content || '';
    return normalizeAgentMode(agentMode) === 'rag' ? rawContent : stripReferenceSourceBlock(rawContent);
}

export function sanitizeStoredMessagesForMode(messages = [], agentMode = 'tutor') {
    if (!Array.isArray(messages)) return [];
    return messages.map(message => {
        if (!message || typeof message !== 'object') return message;
        return {
            ...message,
            content: sanitizeMessageContentForMode(message.content, agentMode)
        };
    });
}

export function mapHistoryRecordToMessage(record) {
    const role = record?.role || 'assistant';
    const createdAt = record?.created_at || '';
    const agentMode = normalizeAgentMode(record?.agent_mode);
    const rawContent = record?.content || '';
    const content = sanitizeMessageContentForMode(rawContent, agentMode);
    const defaultAgentId = CHAT_AGENT_MODES[agentMode]?.defaultAgentId || 'agent_tutor';
    const fallbackProjectId = agentMode === 'paper' ? 'proj-paper' : (agentMode === 'rag' ? 'proj-rag' : (agentMode === 'tutor' ? 'proj-tutor' : 'proj-default'));
    const message = {
        id: `db-${record?.id}`,
        senderType: role === 'user' ? 'user' : 'agent',
        senderId: role === 'user' ? undefined : (record?.sender_id || defaultAgentId),
        content,
        time: createdAt,
        createdAt,
        mode: agentMode,
        projectId: record?.project_id || fallbackProjectId
    };
    if (record?.conversation_id) message.conversationId = record.conversation_id;
    const payload = record?.payload;
    if (agentMode === 'paper' && payload?.kind === 'paper_search' && Array.isArray(payload.results)) {
        const snapshot = {
            query: String(payload.query || ''),
            status: String(payload.status || (payload.results.length > 0 ? 'success' : 'empty')),
            results: payload.results,
            summary: payload.summary && typeof payload.summary === 'object' ? payload.summary : {},
            statuses: Array.isArray(payload.statuses) ? payload.statuses : []
        };
        message.attachedPapers = snapshot.results;
        message.paperSearchSnapshot = snapshot;
    }
    return message;
}
