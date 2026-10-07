import { renderMarkdown } from '../utils/safeRendering.js';
import { computed, ref, watch, nextTick, getCurrentScope, onScopeDispose } from 'vue';
import { sendStreamingMessage, parsedHtmlCache } from '../api/streamChat.js';
import { buildVisualGuideSvg, createLocalVisualGuide, getVisualGuideSourceLabel, requestVisualGuideImage, resolveVisualGuideState } from '../api/visualGuide.js';
import { knowledgeApi } from '../api/knowledgeApi.js';
import { userApi } from '../api/userApi.js';
import { getUserCustomModels } from '../api/userModelApi.js';
import request from '../utils/request.js';
import { formatChatTimestamp, getChatStorageKey, mapHistoryRecordToMessage, normalizeAgentMode, sanitizeStoredMessagesForMode, validateChatSkillSelection } from '../utils/chatModes.js';
import { CHAT_TASK_MODES, sortConversationsByRecency, createModeMessageBuckets, createTaskConversationId, findConversationForMessage, flattenModeMessageBuckets, getSystemProjectIdForMode, groupMessagesIntoConversations, groupConversationsByProjects, reconcileModeHistory, resolveConversationIdForSend, DEFAULT_PROJECT_ID, DEFAULT_PROJECT_NAME, PROJECT_DEFAULT_ID, PROJECT_DEFAULT_NAME, PROJECT_TUTOR_ID, PROJECT_RAG_ID, PROJECT_PAPER_ID, PROJECT_PAPER_NAME, INITIAL_SYSTEM_PROJECTS } from '../utils/conversations.js';
import { getKnowledgeFileStatusLabel, isSupportedKnowledgeFile } from '../utils/knowledgeFiles.js';
import { TEXT_MODEL_OPTIONS, mergeModelOptions } from '../config/aiModels.js';

export function useChat(currentUser, showToast, agentResolver = null) {
    const inputText = ref('');
    const chatContainer = ref(null);
    const thinkingAgent = ref(null);
    const forceRAG = ref(false);
    const agentMode = ref('tutor');
    const historyLoading = ref(false);
    const historyError = ref('');
    const historyMutating = ref(false);
    const blockedWriteModes = new Set();
    const mutationEpochs = new Map();
    const advanceMutation = mode => { mutationEpochs.set(mode, (mutationEpochs.get(mode) || 0) + 1); invalidateHistoryLoads(mode); };
    const activeConversationId = ref(null);
    const draftConversationId = ref('');
    let sessionGeneration = 0;
    let navigationGeneration = 0;
    let inputRevision = 0;
    let cancelWorkspaceSearch = () => {};
    let getChatSkillSelection = () => [];
    const setChatSkillSelectionResolver = resolver => { getChatSkillSelection = typeof resolver === 'function' ? resolver : () => []; };
    let chatSendController = null;
    const historyLoads = new Map();
    const paperSyncTasks = new Map();
    const ownerId = () => currentUser.value?.username || 'guest_user';
    const isSessionCurrent = (owner, generation) => owner === ownerId() && generation === sessionGeneration;
    const getWorkspaceGeneration = () => `${sessionGeneration}:${navigationGeneration}`;
    const setWorkspaceCancellationHandler = handler => { cancelWorkspaceSearch = typeof handler === 'function' ? handler : () => {}; };
    const invalidateWorkspaceNavigation = ({ resetSearch = true } = {}) => {
        navigationGeneration += 1;
        cancelWorkspaceSearch({ reset: resetSearch });
        chatSendController?.abort();
        chatSendController = null;
        thinkingAgent.value = null;
    };
    const capturePaperSearchTransaction = () => Object.freeze({
        sessionId: ownerId(), sessionGeneration, navigationGeneration,
        conversationId: draftConversationId.value || createTaskConversationId('paper')
    });
    watch(inputText, () => { inputRevision += 1; }, { flush: 'sync' });
    const getInputRevision = () => inputRevision;
    const invalidateHistoryLoads = (mode = null) => {
        for (const [key, load] of historyLoads) {
            if (!mode || key === mode) { load.controller.abort(); historyLoads.delete(key); }
        }
        historyLoading.value = historyLoads.size > 0;
    };
    let observedToken = localStorage.getItem('token') || '';
    const handleSessionStorage = event => {
        if (event.key !== null && !['token', 'currentUser'].includes(event.key)) return;
        const token = localStorage.getItem('token') || '';
        if (token === observedToken) return;
        observedToken = token;
        sessionGeneration += 1;
        invalidateWorkspaceNavigation();
        invalidateHistoryLoads();
        for (const task of paperSyncTasks.values()) task.controller?.abort();
        paperSyncTasks.clear();
        blockedWriteModes.clear();
        historyMutating.value = false;
    };
    window.addEventListener('storage', handleSessionStorage);
    if (getCurrentScope()) onScopeDispose(() => {
        window.removeEventListener?.('storage', handleSessionStorage);
        invalidateHistoryLoads();
        chatSendController?.abort();
        for (const task of paperSyncTasks.values()) task.controller?.abort();
    });

    const safeSetLocalStorage = (key, value) => {
        try {
            if (typeof window === 'undefined' || !window.localStorage) return false;
            const serialized = typeof value === 'string' ? value : JSON.stringify(value);
            localStorage.setItem(key, serialized);
            return true;
        } catch (e) {
            console.warn(`[useChat] Failed to set localStorage for key "${key}":`, e);
            return false;
        }
    };

    const escapeHtmlAndMarkdown = (str) => {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;')
            .replace(/`/g, '&#96;');
    };

    const sanitizePaperUrl = (url) => {
        if (!url || typeof url !== 'string') return '';
        const trimmed = url.trim();
        return /^https?:\/\//i.test(trimmed) ? trimmed : '';
    };

    // AI 模型热切换状态与选项
    const currentModel = ref(localStorage.getItem('preferred_chat_model') || 'Auto Mode');
    const baseSystemModels = ref([
        { id: 'Auto Mode', label: 'Auto Mode', provider: '系统自适应', hint: '智能推荐' },
        ...TEXT_MODEL_OPTIONS
    ]);
    const userCustomConfigs = ref([]);
    const modelOptions = ref([...baseSystemModels.value]);
    const showModelDropdown = ref(false);

    const rebuildMergedModelOptions = () => {
        const customItems = [];
        (userCustomConfigs.value || []).forEach(cfg => {
            if (Array.isArray(cfg.model_ids)) {
                cfg.model_ids.forEach(mId => {
                    const cleanId = (mId || '').trim();
                    if (cleanId && !customItems.some(item => item.id === cleanId)) {
                        customItems.push({
                            id: cleanId,
                            label: cleanId,
                            provider: cfg.provider || '自定义',
                            hint: `${cfg.provider || '自定义'} · ${cfg.base_url || ''}`,
                            isCustom: true,
                            configId: cfg.id
                        });
                    }
                });
            }
        });

        const sysFiltered = baseSystemModels.value.filter(sm => !customItems.some(ci => ci.id === sm.id));
        modelOptions.value = [
            ...sysFiltered,
            ...customItems
        ];

        // 若当前选中的自定义模型已被删除，则重置回 Auto Mode，避免请求崩溃
        const currentStillExists = modelOptions.value.some(m => m.id === currentModel.value);
        if (!currentStillExists && currentModel.value !== 'Auto Mode') {
            currentModel.value = 'Auto Mode';
            safeSetLocalStorage('preferred_chat_model', 'Auto Mode');
        }
    };

    const loadChatModelOptions = async () => {
        try {
            const payload = await request('/ai/models');
            const data = payload?.data || {};
            if (Array.isArray(data.text) && data.text.length) {
                const backendModels = data.text.map(m => ({
                    id: m.id,
                    label: m.label || m.id,
                    provider: m.provider || '',
                    baseUrl: m.base_url || m.baseUrl || '',
                    apiModel: m.api_model || m.apiModel || '',
                    hint: m.hint || ''
                }));
                const merged = mergeModelOptions(backendModels, TEXT_MODEL_OPTIONS);
                baseSystemModels.value = [
                    { id: 'Auto Mode', label: 'Auto Mode', provider: '系统自适应', hint: '智能推荐' },
                    ...merged
                ];
                rebuildMergedModelOptions();
            }
        } catch (e) {
            console.info('[Chat] Backend model registry unavailable, using fallback list.', e);
        }
    };
    loadChatModelOptions();

    const loadUserCustomModels = async () => {
        const owner = ownerId(), generation = sessionGeneration;
        try {
            const res = await getUserCustomModels();
            if (!isSessionCurrent(owner, generation)) return;
            if (res && res.status === 'success' && Array.isArray(res.data)) {
                userCustomConfigs.value = res.data.filter(c => c.is_active);
                rebuildMergedModelOptions();
            }
        } catch (e) {
            console.debug('[Chat] User custom models load skipped or failed:', e);
        }
    };
    loadUserCustomModels();

    const refreshUserCustomModels = async () => {
        await loadUserCustomModels();
    };

    const switchModel = (modelId) => {
        currentModel.value = modelId;
        safeSetLocalStorage('preferred_chat_model', modelId);
        showModelDropdown.value = false;
        if (typeof showToast === 'function') {
            showToast(`已切换至模型：${modelId}`, 'success');
        }
    };

    const toggleModelDropdown = () => {
        showModelDropdown.value = !showModelDropdown.value;
    };

    const currentModelInfo = computed(() => {
        return modelOptions.value.find(m => m.id === currentModel.value) || {
            id: currentModel.value,
            label: currentModel.value,
            provider: '自定义',
            hint: ''
        };
    });

    // 论文模式下的工作台双态切换视图: 'results' (文献检索卡片列表) | 'dialog' (研读对话流)
    const paperActiveTab = ref('results');

    const switchWorkMode = (mode) => {
        invalidateWorkspaceNavigation();
        activeConversationId.value = null;
        draftConversationId.value = '';
        showModelDropdown.value = false;
        if (showVisualGuideViewer) showVisualGuideViewer.value = false;
        if (mode === 'paper') {
            agentMode.value = 'paper';
            paperActiveTab.value = 'results';
            forceRAG.value = false;
            activeProjectId.value = PROJECT_PAPER_ID;
            loadChatHistory('paper');
            if (typeof showToast === 'function') showToast('已切换至「论文查询」学术文献研读模式', 'info');
        } else if (mode === 'rag') {
            agentMode.value = 'rag';
            forceRAG.value = true;
            activeProjectId.value = PROJECT_RAG_ID;
            loadChatHistory('rag');
            if (typeof showToast === 'function') showToast('已切换至「知识库检索」模式', 'info');
        } else if (mode === 'tutor') {
            agentMode.value = 'tutor';
            forceRAG.value = false;
            activeProjectId.value = PROJECT_TUTOR_ID;
            loadChatHistory('tutor');
            if (typeof showToast === 'function') showToast('已切换至「引导式学习」导师点拨模式', 'info');
        } else {
            agentMode.value = 'chat';
            forceRAG.value = false;
            activeProjectId.value = PROJECT_DEFAULT_ID;
            loadChatHistory('chat');
            if (typeof showToast === 'function') showToast('已切换至「AI 对话」全能问答模式', 'info');
        }
    };


    const recordPaperSearchWork = async (query, meta = {}) => {
        const cleanQuery = String(query || '').trim();
        if (!cleanQuery || blockedWriteModes.has('paper')) return false;
        const transaction = meta.transaction || capturePaperSearchTransaction();
        if (!isSessionCurrent(transaction.sessionId, transaction.sessionGeneration)) return false;
        const mayActivate = () => transaction.navigationGeneration === navigationGeneration && agentMode.value === 'paper';
        // 论文模式下的学术检索代表独立的研究主题。
        // 若处于新建草稿态（draftConversationId 存在），使用该草稿 ID；
        // 否则每次学术检索都必须创建独立的 conversationId，防止历史任务被追加污染，并确保左侧任务树即时呈现新检索任务。
        let conversationId = transaction.conversationId;
        if (!conversationId) {
            conversationId = createTaskConversationId('paper');
        }
        if (mayActivate()) {
            activeConversationId.value = conversationId;
            draftConversationId.value = '';
        }
        const sessionId = transaction.sessionId;
        const results = Array.isArray(meta.results) ? meta.results : [];
        const summary = meta.summary || {};
        const statuses = Array.isArray(meta.statuses) ? meta.statuses : [];
        const searchStatus = String(meta.status || (results.length > 0 ? 'success' : 'empty'));
        const paperSearchSnapshot = {
            query: cleanQuery,
            status: searchStatus,
            results: results.slice(0, 50).map((paper, index) => ({ ...paper, ordinal: paper.ordinal || index + 1, abstract: String(paper.abstract || '').slice(0, 4000) })),
            summary: { ...summary, snapshotCount: Math.min(results.length, 50), snapshotComplete: Math.min(results.length, 50) >= Number(summary.totalAfterMerge ?? results.length) },
            statuses
        };

        const countBefore = summary.totalBeforeMerge ?? results.length;
        const countAfter = summary.totalAfterMerge ?? results.length;
        const countFetched = summary.totalFetched ?? countBefore;
        const countRejected = summary.totalRejected || 0;
        const effectiveQuery = String(summary.effectiveQuery || '').trim();
        const activeSources = statuses
            .filter(s => s.status === 'success')
            .map(s => `${escapeHtmlAndMarkdown(s.label || s.key)} (${Number(s.count) || 0}篇)`)
            .join('、') || '学术数据源';

        const topPapers = results.slice(0, 3).map((p, idx) => {
            const safeTitle = escapeHtmlAndMarkdown(p.title || '无标题文献');
            const safeAuthors = escapeHtmlAndMarkdown(p.authorsText || '未知学者');
            const safeSource = escapeHtmlAndMarkdown(p.sources?.map(s => s.label).join('/') || '学术源');
            const safeUrl = sanitizePaperUrl(p.officialUrl || p.openAccessUrl || '');
            const titleDisplay = safeUrl ? `[《${safeTitle}》](${safeUrl})` : `《${safeTitle}》`;
            const doiDisplay = p.doi ? ` · DOI: ${escapeHtmlAndMarkdown(p.doi)}` : '';
            return `${idx + 1}. **${titleDisplay}** (${escapeHtmlAndMarkdown(p.year || '年份未知')})
   - 👥 作者: ${safeAuthors}
   - 🏛️ 来源: ${safeSource}${doiDisplay}`;
        }).join('\n\n');

        const effectiveQueryLine = summary.queryTranslated && effectiveQuery
            ? `- **实际检索词**：\`${escapeHtmlAndMarkdown(effectiveQuery)}\`（保留未匹配条件的术语规范化）\n`
            : '';
        const filterLine = countRejected > 0
            ? `- **记录有效性检查**：来源返回 ${countFetched} 条，剔除 ${countRejected} 条缺少有效标题的无效记录。\n`
            : '';

        const reportContent = `📚 **学术文献多源检索工作记录**\n\n` +
            `- **检索主题**：\`${escapeHtmlAndMarkdown(cleanQuery)}\`\n` +
            effectiveQueryLine +
            `- **响应数据源**：${activeSources}\n` +
            filterLine +
            `- **文献汇总**：相关候选 ${countBefore} 篇，去重后 **${countAfter} 篇来源可核验文献记录**。\n\n` +
            `**核心检索文献代表**：\n\n${topPapers || '已完成多源去重检索，详情见主视图文献卡片。'}\n\n` +
            `> 阅读范围：本次仅保存来源元数据及摘要，未读取全文。云端同步状态请查看任务提示。`;

        const timestamp = typeof formatChatTimestamp === 'function' ? formatChatTimestamp() : new Date().toLocaleString('zh-CN');
        const userMsgId = `paper-user-${conversationId}`;
        const agentMsgId = `paper-agent-${conversationId}`;
        const clientRequestId = `paper-search:${conversationId}`;

        const userMsg = {
            id: userMsgId,
            syncState: 'pending',
            clientRequestId,
            senderType: 'user',
            content: cleanQuery,
            time: timestamp,
            createdAt: timestamp,
            mode: 'paper',
            conversationId,
            projectId: PROJECT_PAPER_ID
        };

        const agentMsg = {
            id: agentMsgId,
            syncState: 'pending',
            clientRequestId,
            senderType: 'agent',
            senderId: 'agent_paper',
            content: reportContent,
            attachedPapers: paperSearchSnapshot.results,
            paperSearchSnapshot,
            time: timestamp,
            createdAt: timestamp,
            mode: 'paper',
            conversationId,
            projectId: PROJECT_PAPER_ID
        };

        const bucket = modeMessageBuckets.value.paper || [];
        bucket.push(userMsg, agentMsg);
        modeMessageBuckets.value.paper = bucket;
        if (mayActivate()) {
            paperActiveTab.value = 'results';
            activeConversationId.value = conversationId;
            draftConversationId.value = '';
        }
        hydrateParsedMessages();
        safeSetLocalStorage(getChatStorageKey(sessionId, 'paper'), bucket);
        return retryPaperWorkSync(conversationId);
    };

    const buildPaperSyncBody = (owner, userMessage, agentMessage) => JSON.stringify({
        user_id: owner, agent_mode: 'paper', conversation_id: agentMessage.conversationId,
        project_id: PROJECT_PAPER_ID,
        client_request_id: agentMessage.clientRequestId,
        messages: [
            { role: 'user', content: userMessage.content, agent_mode: 'paper', sender_id: null, conversation_id: agentMessage.conversationId, project_id: PROJECT_PAPER_ID },
            { role: 'assistant', content: agentMessage.content, agent_mode: 'paper', sender_id: 'agent_paper', conversation_id: agentMessage.conversationId, project_id: PROJECT_PAPER_ID, payload: { kind: 'paper_search', ...agentMessage.paperSearchSnapshot } }
        ]
    });

    const retryPaperWorkSync = async (conversationId) => {
        if (blockedWriteModes.has('paper')) return false;
        const rows = (modeMessageBuckets.value.paper || []).filter(message => message.conversationId === conversationId);
        const agentMessage = rows.find(message => message.paperSearchSnapshot && message.syncState !== 'saved' && !/^db-/.test(String(message.id)));
        const userMessage = rows.find(message => message.senderType === 'user');
        if (!agentMessage || !userMessage) return false;
        const existingTask = paperSyncTasks.get(conversationId);
        if (existingTask?.promise) return existingTask.promise;
        const owner = getSessionId();
        const generation = sessionGeneration;
        if (owner === 'guest_user') { rows.forEach(row => { row.syncState = 'failed'; }); historyError.value = '请登录后重试云端同步'; return false; }
        const task = existingTask || { owner, generation, body: buildPaperSyncBody(owner, userMessage, agentMessage) };
        task.controller = new AbortController();
        paperSyncTasks.set(conversationId, task);
        rows.forEach(row => { row.syncState = 'pending'; row.syncError = ''; });
        task.promise = (async () => {
            try {
                const res = await request('/chat/history/batch', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: task.body, signal: task.controller.signal });
                if (!isSessionCurrent(owner, generation)) return false;
                if (res?.status !== 'success' || !Array.isArray(res.data) || res.data.length !== 2 || !res.data.every(row => Number.isInteger(Number(row.id)) && Number(row.id) > 0)) throw new Error(res?.message || '云端未返回完整保存回执');
                const currentRows = modeMessageBuckets.value.paper || [];
                [userMessage, agentMessage].forEach((row, index) => {
                    const target = currentRows.find(item => item.id === row.id || (item.clientRequestId === agentMessage.clientRequestId && item.senderType === row.senderType));
                    if (target) { target.id = `db-${res.data[index].id}`; target.syncState = 'saved'; target.syncError = ''; }
                });
                historyError.value = '';
                hydrateParsedMessages();
                paperSyncTasks.delete(conversationId);
                return true;
            } catch (error) {
                if (!isSessionCurrent(owner, generation)) return false;
                rows.forEach(row => { row.syncState = 'failed'; row.syncError = error.message || '云端同步失败'; });
                historyError.value = `当前显示本地副本，云端保存结果尚未确认：${error.message || '请重试'}。可重试同步或刷新历史记录核对`;
                return false;
            } finally {
                task.promise = null;
                if (isSessionCurrent(owner, generation)) safeSetLocalStorage(getChatStorageKey(owner, 'paper'), modeMessageBuckets.value.paper || []);
            }
        })();
        return task.promise;
    };

    const returnToChatDialog = () => {
        invalidateWorkspaceNavigation({ resetSearch: false });
        if (agentMode.value === 'paper') {
            paperActiveTab.value = 'dialog';
            if (typeof window !== 'undefined') {
                setTimeout(() => {
                    const textarea = document.querySelector('main textarea');
                    if (textarea) {
                        textarea.focus();
                        try {
                            const len = textarea.value ? textarea.value.length : 0;
                            textarea.setSelectionRange(len, len);
                        } catch (e) {}
                        textarea.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    }
                }, 60);
            }
            if (typeof showToast === 'function') {
                showToast('已返回论文研读对话框', 'info');
            }
            return;
        }

        switchWorkMode('chat');
        if (typeof window !== 'undefined') {
            setTimeout(() => {
                const textarea = document.querySelector('main textarea');
                if (textarea) {
                    textarea.focus();
                    try {
                        const len = textarea.value ? textarea.value.length : 0;
                        textarea.setSelectionRange(len, len);
                    } catch (e) {}
                    textarea.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
            }, 60);
        }
        if (typeof showToast === 'function') {
            showToast('已返回 AI 对话框', 'info');
        }
    };
    const createEmptyVisualGuide = () => ({
        title: 'AI 引导图生成师',
        caption: '可将问题转为可视化步骤架构图。',
        center: '等待问题',
        nodes: [],
        edges: [],
        type: 'steps',
        source: 'empty',
        generatedAt: ''
    });
    const visualGuidePrompt = ref('');
    const visualGuideType = ref('steps');
    const visualGuideStatus = ref('ready');
    const visualGuideImage = ref(null);
    const showVisualGuideViewer = ref(false);
    const visualGuide = ref(createEmptyVisualGuide());
    const visualGuideCache = ref({});
    const visualGuideHistory = ref([]);
    let visualGuideRequestId = 0;

    const getSessionId = () => currentUser.value?.username || 'guest_user';
    const getAgentById = (id) => (typeof agentResolver === 'function' ? agentResolver(id) : null);
    const getActiveChatAgent = () => {
        const mode = normalizeAgentMode(agentMode.value);
        const agentId = mode === 'paper' ? 'agent_paper' : (mode === 'rag' ? 'agent_researcher' : 'agent_tutor');
        return getAgentById(agentId);
    };
    const getVisualGuideAgent = () => getAgentById('agent_visual_guide');
    const getArchitectureGuideAgent = () => getAgentById('agent_tutor');
    const readStoredMessages = (mode = agentMode.value) => {
        const normalizedMode = normalizeAgentMode(mode);
        const storageKey = getChatStorageKey(getSessionId(), normalizedMode);
        // Unscoped legacy caches have no verifiable owner and must never cross account boundaries.
        const stored = localStorage.getItem(storageKey);
        if (!stored) return [];
        try {
            return sanitizeStoredMessagesForMode(JSON.parse(stored), normalizedMode);
        } catch (error) {
            console.warn('[Chat] Failed to parse stored messages.', error);
            return [];
        }
    };

    const modeMessageBuckets = ref(createModeMessageBuckets(readStoredMessages));
    const messages = computed({
        get: () => modeMessageBuckets.value[normalizeAgentMode(agentMode.value)] || [],
        set: (nextMessages) => {
            const mode = normalizeAgentMode(agentMode.value);
            modeMessageBuckets.value[mode] = Array.isArray(nextMessages) ? nextMessages : [];
        }
    });
    const allTaskMessages = computed(() => flattenModeMessageBuckets(modeMessageBuckets.value));

    // ================== 大项目与子任务树状体系 (OpenAI Codex 风格) ==================
    const getProjectsStorageKey = (sessionId) => `task_projects:${sessionId}`;
    const readStoredProjects = () => {
        try {
            const raw = localStorage.getItem(getProjectsStorageKey(getSessionId()));
            if (raw) {
                const parsed = JSON.parse(raw);
                if (Array.isArray(parsed) && parsed.length > 0) {
                    const hasTutor = parsed.some(p => p.id === PROJECT_TUTOR_ID);
                    const hasRag = parsed.some(p => p.id === PROJECT_RAG_ID);
                    const hasPaper = parsed.some(p => p.id === PROJECT_PAPER_ID);
                    if (!hasTutor || !hasRag || !hasPaper) {
                        return [...INITIAL_SYSTEM_PROJECTS, ...parsed.filter(p => p.id !== 'proj-default' && p.id !== PROJECT_TUTOR_ID && p.id !== PROJECT_RAG_ID && p.id !== PROJECT_PAPER_ID)];
                    }
                    return parsed;
                }
            }
        } catch (e) {
            console.warn('[useChat] Failed to parse stored projects:', e);
        }
        return INITIAL_SYSTEM_PROJECTS.map(project => ({ ...project }));
    };

    const projectList = ref(readStoredProjects());
    const activeProjectId = ref(agentMode.value === 'rag' ? PROJECT_RAG_ID : PROJECT_TUTOR_ID);

    watch(projectList, (newVal) => {
        try {
            localStorage.setItem(getProjectsStorageKey(getSessionId()), JSON.stringify(newVal));
        } catch (e) {
            console.warn('[useChat] Failed to save projects to localStorage:', e);
        }
    }, { deep: true, flush: 'sync' });

    // 大项目与小任务两级聚合树
    const projectTaskTree = computed(() => {
        return groupConversationsByProjects(allTaskMessages.value, projectList.value);
    });

    const createProject = (name) => {
        const cleanName = String(name || '').trim();
        if (!cleanName) {
            showToast('请输入项目名称', 'error');
            return null;
        }
        const newProj = {
            id: `proj-${Date.now()}`,
            name: cleanName,
            icon: 'ph-folder',
            expanded: true,
            isSystem: false,
            createdAt: Date.now()
        };
        projectList.value.push(newProj);
        activeProjectId.value = newProj.id;
        activeConversationId.value = 'new';
        showToast(`已创建项目「${cleanName}」`, 'success');
        return newProj;
    };

    const deleteProject = (projectId) => {
        if (projectId === PROJECT_TUTOR_ID || projectId === PROJECT_RAG_ID || projectId === PROJECT_PAPER_ID || projectId === 'proj-default') {
            showToast('系统任务分组不能删除', 'info');
            return;
        }
        const target = projectList.value.find(p => p.id === projectId);
        const name = target?.name || '该项目';
        const confirmed = window.confirm(`确认删除项目「${name}」？其下的小任务将自动归入对应系统分组。`);
        if (!confirmed) return;

        // 迁移该项目下的消息到对应系统分组
        allTaskMessages.value.forEach(msg => {
            if (msg.projectId === projectId) {
                msg.projectId = getSystemProjectIdForMode(msg.mode);
            }
        });
        projectList.value = projectList.value.filter(p => p.id !== projectId);
        if (activeProjectId.value === projectId) {
            activeProjectId.value = getSystemProjectIdForMode(agentMode.value);
        }
        showToast(`项目「${name}」已删除`, 'success');
    };

    const renameProject = (projectId, newName) => {
        const cleanName = String(newName || '').trim();
        if (!cleanName) return;
        const target = projectList.value.find(p => p.id === projectId);
        if (target) {
            target.name = cleanName;
            showToast('项目已重命名', 'success');
        }
    };

    const toggleProjectExpand = (projectId) => {
        const target = projectList.value.find(p => p.id === projectId);
        if (target) {
            target.expanded = !target.expanded;
        } else {
            // 如果尚未在 projectList 中，添加并设置
            const sys = INITIAL_SYSTEM_PROJECTS.find(p => p.id === projectId);
            if (sys) {
                projectList.value.push({ ...sys, expanded: false });
            }
        }
    };

    const startNewSubTask = (projectId) => {
        activeProjectId.value = projectId || getSystemProjectIdForMode(agentMode.value);
        const targetProj = projectList.value.find(p => p.id === activeProjectId.value);
        if (targetProj) {
            targetProj.expanded = true;
        }
        if (projectId === PROJECT_PAPER_ID && agentMode.value !== 'paper') {
            switchWorkMode('paper');
        } else if (projectId === PROJECT_TUTOR_ID && agentMode.value !== 'tutor') {
            switchWorkMode('tutor');
        } else if (projectId === PROJECT_RAG_ID && agentMode.value !== 'rag') {
            switchWorkMode('rag');
        } else if (projectId === PROJECT_DEFAULT_ID && agentMode.value !== 'chat') {
            switchWorkMode('chat');
        }
        startNewConversation(projectId);
    };

    const setPaperActiveTab = tab => {
        if (!['results', 'dialog'].includes(tab) || tab === paperActiveTab.value) return;
        invalidateWorkspaceNavigation({ resetSearch: false });
        paperActiveTab.value = tab;
    };
    const paperWorkSyncStatus = computed(() => {
        if (activeConversationId.value === 'new') return null;
        const source = activeConversation.value?.messages || modeMessageBuckets.value.paper || [];
        const message = source.slice().reverse().find(message => message.paperSearchSnapshot);
        return message ? { state: message.syncState || (/^db-/.test(String(message.id)) ? 'saved' : 'failed'), error: message.syncError || '', conversationId: message.conversationId } : null;
    });

    const showPaperSearchResults = () => {
        if (agentMode.value !== 'paper') return;
        paperActiveTab.value = 'results';
        draftConversationId.value = '';
        activeProjectId.value = PROJECT_PAPER_ID;
    };

    // ================== 伪会话模型：把线性消息流按用户提问切分为对话 ==================
    // activeConversationId: null = 当前最新对话；'new' = 新增对话的空白态；'conv-xxx' = 查看历史对话
    const conversationList = computed(() => {
        const conversations = groupMessagesIntoConversations(messages.value);
        return sortConversationsByRecency(conversations, messages.value);
    });

    const allConversationList = computed(() => {
        const conversations = groupMessagesIntoConversations(allTaskMessages.value);
        return sortConversationsByRecency(conversations, allTaskMessages.value);
    });

    const activeConversation = computed(() => {
        if (!activeConversationId.value || activeConversationId.value === 'new') return null;
        return conversationList.value.find(conversation => conversation.id === activeConversationId.value) || null;
    });

    const isViewingHistory = computed(() => Boolean(
        activeConversation.value && conversationList.value[0]?.id !== activeConversation.value.id
    ));

    // 侧栏高亮：查看历史时指向该对话，其余情况指向最新对话（新增对话空白态时不高亮）
    const sidebarActiveConversationId = computed(() => {
        if (activeConversationId.value === 'new') return null;
        if (activeConversation.value) return activeConversation.value.id;
        return conversationList.value[0]?.id || null;
    });

    const activeConversationMessages = computed(() => {
        if (activeConversationId.value === 'new') return [];
        if (activeConversation.value) return activeConversation.value.messages;
        if (agentMode.value === 'paper') {
            // 论文模式遵循 Claude 桌面端单任务隔离原则：未明确激活会话时绝不跨会话倾倒历史消息
            return [];
        }
        return conversationList.value[0]?.messages || [];
    });

    const openPaperTaskDialog = async (conversationId) => {
        if (!conversationId) return;
        if (agentMode.value !== 'paper') {
            agentMode.value = 'paper';
            forceRAG.value = false;
        }
        activeProjectId.value = PROJECT_PAPER_ID;
        if (await selectConversation(conversationId) === false) return false;
        paperActiveTab.value = 'dialog';
        if (typeof window !== 'undefined') {
            setTimeout(() => {
                const textarea = document.querySelector('main textarea');
                if (textarea) {
                    textarea.focus();
                    try {
                        const len = textarea.value ? textarea.value.length : 0;
                        textarea.setSelectionRange(len, len);
                    } catch (e) {}
                    textarea.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
            }, 60);
        }
        if (typeof showToast === 'function') {
            showToast('已加载当前任务研读对话', 'info');
        }
    };

    const scrollChatToBottom = async () => {
        await nextTick();
        if (chatContainer.value) chatContainer.value.scrollTop = chatContainer.value.scrollHeight;
    };

    const getConversationIdForSend = ({ mode = agentMode.value, activate = true } = {}) => {
        const normalizedMode = normalizeAgentMode(mode);
        const isCurrentMode = normalizedMode === normalizeAgentMode(agentMode.value);
        const targetConversations = isCurrentMode
            ? conversationList.value
            : sortConversationsByRecency(groupMessagesIntoConversations(modeMessageBuckets.value[normalizedMode] || []));
        let conversationId = resolveConversationIdForSend({
            activeConversationId: isCurrentMode ? activeConversationId.value : null,
            draftConversationId: isCurrentMode ? draftConversationId.value : '',
            latestConversationId: targetConversations[0]?.id || ''
        });
        if (!conversationId) {
            conversationId = createTaskConversationId(normalizedMode);
        }
        if (activate && isCurrentMode) {
            activeConversationId.value = conversationId;
            draftConversationId.value = '';
        }
        return conversationId;
    };

    const selectConversation = async (conversationId) => {
        invalidateWorkspaceNavigation();
        const selectionGeneration = getWorkspaceGeneration();
        const nextId = conversationId || null;

        // 智能联动切换工作模式
        const conv = allConversationList.value.find(c => c.id === conversationId);
        if (conv) {
            if (conv.mode === 'paper' && agentMode.value !== 'paper') {
                agentMode.value = 'paper';
                forceRAG.value = false;
            } else if (conv.mode === 'rag' && agentMode.value !== 'rag') {
                agentMode.value = 'rag';
                forceRAG.value = true;
            } else if (conv.mode === 'tutor' && agentMode.value !== 'tutor') {
                agentMode.value = 'tutor';
                forceRAG.value = false;
            } else if (conv.mode === 'chat' && agentMode.value !== 'chat') {
                agentMode.value = 'chat';
                forceRAG.value = false;
            }
            activeProjectId.value = conv.projectId || getSystemProjectIdForMode(conv.mode);
            const epoch = mutationEpochs.get(conv.mode) || 0;
            await loadChatHistory(conv.mode, { conversationId });
            if (selectionGeneration !== getWorkspaceGeneration() || epoch !== (mutationEpochs.get(conv.mode) || 0)) return false;
        }

        if (selectionGeneration !== getWorkspaceGeneration()) return false;
        if (activeConversationId.value === nextId) return true;
        activeConversationId.value = nextId;
        await nextTick();
        if (chatContainer.value) chatContainer.value.scrollTop = 0;
        return true;
    };

    const backToCurrentConversation = async () => {
        const latestId = conversationList.value[0]?.id;
        invalidateWorkspaceNavigation();
        activeConversationId.value = latestId || null;
        await scrollChatToBottom();
    };

    const resetVisualGuideForNewConversation = () => {
        visualGuidePrompt.value = '';
        visualGuideImage.value = null;
        visualGuideStatus.value = 'ready';
        visualGuide.value = createEmptyVisualGuide();
        showVisualGuideViewer.value = false;
    };

    const startNewConversation = async (projectId = '') => {
        invalidateWorkspaceNavigation();
        const normalizedMode = normalizeAgentMode(agentMode.value);
        const requestedProjectId = typeof projectId === 'string' ? projectId : '';
        draftConversationId.value = createTaskConversationId(normalizedMode);
        activeConversationId.value = 'new';
        activeProjectId.value = requestedProjectId || getSystemProjectIdForMode(normalizedMode);
        const targetProj = projectList.value.find(p => p.id === activeProjectId.value);
        if (targetProj) {
            targetProj.expanded = true;
        }
        if (normalizeAgentMode(agentMode.value) !== 'rag') {
            resetVisualGuideForNewConversation();
        }
        await scrollChatToBottom();
        return draftConversationId.value;
    };

    const hydrateParsedMessages = () => {
        Object.keys(parsedHtmlCache).forEach(key => delete parsedHtmlCache[key]);
        allTaskMessages.value.forEach(msg => {
            if (msg.senderType === 'agent') {
                parsedHtmlCache[msg.id] = renderMarkdown(msg.content);
            }
        });
    };

    const loadChatHistory = async (mode = agentMode.value, { conversationId = '' } = {}) => {
        const normalizedMode = normalizeAgentMode(mode);
        const sessionId = getSessionId();
        const generation = sessionGeneration;
        if (sessionId === 'guest_user') return false;
        historyLoads.get(normalizedMode)?.controller.abort();
        const mutationEpoch = mutationEpochs.get(normalizedMode) || 0;
        const load = { controller: new AbortController(), initialIds: new Set((modeMessageBuckets.value[normalizedMode] || []).map(message => message.id)) };
        historyLoads.set(normalizedMode, load);
        const isCurrent = () => isSessionCurrent(sessionId, generation) && historyLoads.get(normalizedMode) === load && mutationEpoch === (mutationEpochs.get(normalizedMode) || 0) && !load.controller.signal.aborted;
        historyLoading.value = true;
        historyError.value = '';
        try {
            const remoteMessages = [];
            let before = '', complete = false, snapshotMaxId = null;
            const seenCursors = new Set();
            for (let page = 0; page < 50; page += 1) {
                const url = `/chat/history?session_id=${encodeURIComponent(sessionId)}&agent_mode=${encodeURIComponent(normalizedMode)}&limit=200${conversationId ? `&conversation_id=${encodeURIComponent(conversationId)}` : ''}${before ? `&before=${encodeURIComponent(before)}` : ''}`;
                const result = await request(url, { signal: load.controller.signal });
                if (!isCurrent()) return false;
                if (result?.status !== 'success' || !Array.isArray(result.data)) throw new Error(result?.message || '历史记录响应无效');
                remoteMessages.unshift(...result.data.map(mapHistoryRecordToMessage));
                const pagination = result.pagination;
                if (Number.isInteger(pagination?.snapshot_max_id)) snapshotMaxId = pagination.snapshot_max_id;
                if (!pagination?.has_more) { complete = pagination?.complete === true; break; }
                if (!pagination.next_cursor || seenCursors.has(pagination.next_cursor)) throw new Error('历史记录分页游标无效');
                before = pagination.next_cursor;
                seenCursors.add(before);
            }
            if (!isCurrent()) return false;
            const current = modeMessageBuckets.value[normalizedMode] || [];
            const local = conversationId ? current.filter(message => message.conversationId === conversationId) : current;
            const deduped = Array.from(new Map(remoteMessages.map(message => [message.id, message])).values());
            const reconciled = reconcileModeHistory(local, deduped, { complete, preserveIds: local.filter(message => !load.initialIds.has(message.id) || (snapshotMaxId != null && Number(String(message.id).replace(/^db-/, '')) > snapshotMaxId)).map(message => message.id) });
            // Keep the task's original position; inspecting history is not new activity.
            if (conversationId) {
                const pending = new Map(reconciled.map(message => [message.id, message]));
                const merged = [];
                for (const message of current) {
                    if (message.conversationId !== conversationId) merged.push(message);
                    else if (pending.has(message.id)) {
                        merged.push(pending.get(message.id));
                        pending.delete(message.id);
                    }
                }
                modeMessageBuckets.value[normalizedMode] = [...merged, ...pending.values()];
            } else modeMessageBuckets.value[normalizedMode] = reconciled;
            if (before && !complete) historyError.value = '已加载最近的历史窗口；较早任务尚未全部同步。';
            hydrateParsedMessages();
            safeSetLocalStorage(getChatStorageKey(sessionId, normalizedMode), modeMessageBuckets.value[normalizedMode]);
            await nextTick();
            if (isCurrent() && agentMode.value === normalizedMode && chatContainer.value) chatContainer.value.scrollTop = chatContainer.value.scrollHeight;
            return true;
        } catch (error) {
            if (isCurrent() && error?.name !== 'AbortError') historyError.value = '历史记录暂时无法同步，当前显示本地缓存。';
            return false;
        } finally {
            if (historyLoads.get(normalizedMode) === load) historyLoads.delete(normalizedMode);
            if (isSessionCurrent(sessionId, generation)) historyLoading.value = historyLoads.size > 0;
        }
    };

    const loadAllChatHistories = () => Promise.all(
        CHAT_TASK_MODES.map(mode => loadChatHistory(mode))
    );

    const setAgentMode = (mode) => switchWorkMode(mode);

    const resolveHistoryMessageDbId = (messageId) => {
        const raw = String(messageId || '');
        if (raw.startsWith('db-')) {
            const parsed = Number(raw.slice(3));
            return Number.isFinite(parsed) ? parsed : null;
        }
        return null;
    };

    // Remove confirmed server records only after an actual deletion receipt.
    const removeHistoryMessageRecord = async (message) => {
        const mode = normalizeAgentMode(message.mode);
        const owner = getSessionId(), generation = sessionGeneration;
        invalidateHistoryLoads(mode);
        const task = paperSyncTasks.get(message.conversationId);
        if (task?.promise) await task.promise;
        if (!isSessionCurrent(owner, generation)) return false;
        const dbId = resolveHistoryMessageDbId(message.id);
        try {
            if (dbId != null) {
                const result = await request(`/chat/history/${dbId}?session_id=${encodeURIComponent(owner)}`, { method: 'DELETE' });
                if (!isSessionCurrent(owner, generation)) return false;
                if (result?.status !== 'success') throw new Error(result?.message || '删除失败');
            }
            advanceMutation(mode);
            modeMessageBuckets.value[mode] = (modeMessageBuckets.value[mode] || []).filter(item => item.id !== message.id);
            delete parsedHtmlCache[message.id];
            paperSyncTasks.delete(message.conversationId);
            return true;
        } catch (error) {
            if (isSessionCurrent(owner, generation)) historyError.value = `云端删除未完成，记录仍保留：${error.message || '请重试'}`;
            return false;
        }
    };

    const deleteConversation = async (conversation) => {
        if (!conversation?.id || !conversation.messages?.length || blockedWriteModes.has(normalizeAgentMode(conversation.mode || conversation.messages[0]?.mode))) return false;
        if (!window.confirm(`确认删除这段对话？\n「${conversation.title || '未命名对话'}」共 ${conversation.messages.length} 条消息，删除后不可恢复。`)) return false;
        const owner = getSessionId(), generation = sessionGeneration;
        invalidateWorkspaceNavigation();
        const mode = normalizeAgentMode(conversation.mode || conversation.messages[0]?.mode);
        blockedWriteModes.add(mode);
        historyMutating.value = true;
        advanceMutation(mode);
        try {
            const task = paperSyncTasks.get(conversation.id);
            if (task?.promise) await task.promise;
            if (!isSessionCurrent(owner, generation)) return false;
            if (!await loadChatHistory(mode, { conversationId: conversation.id })) {
                if (isSessionCurrent(owner, generation)) historyError.value = '删除未完成：无法确认云端任务记录，请重试';
                return false;
            }
            const currentRows = (modeMessageBuckets.value[mode] || []).filter(message => message.conversationId === conversation.id);
            let completed = true;
            for (const message of currentRows) {
                if (!isSessionCurrent(owner, generation)) return false;
                if (!await removeHistoryMessageRecord(message)) completed = false;
            }
            if (!isSessionCurrent(owner, generation)) return false;
            if (completed && activeConversationId.value === conversation.id) activeConversationId.value = null;
            showToast(completed ? '对话已删除' : '部分记录未能删除，请重试', completed ? 'success' : 'warning');
            return completed;
        } finally {
            if (isSessionCurrent(owner, generation)) {
                advanceMutation(mode);
                blockedWriteModes.delete(mode);
                historyMutating.value = blockedWriteModes.size > 0;
            }
        }
    };

    const clearChatHistory = async (mode = agentMode.value) => {
        const normalizedMode = normalizeAgentMode(mode);
        if (blockedWriteModes.has(normalizedMode) || (modeMessageBuckets.value[normalizedMode] || []).length === 0) return false;
        const label = normalizedMode === 'paper' ? '论文查询' : normalizedMode === 'rag' ? '知识库检索' : normalizedMode === 'chat' ? 'AI 对话' : '引导式学习';
        if (!window.confirm(`确认清空全部「${label}」历史对话？此操作不可恢复。`)) return false;
        const owner = getSessionId(), generation = sessionGeneration;
        invalidateWorkspaceNavigation();
        advanceMutation(normalizedMode);
        const clearNavigationGeneration = navigationGeneration;
        blockedWriteModes.add(normalizedMode);
        historyMutating.value = true;
        // Resolve in-flight saves before clearing so their late receipts cannot resurrect work.
        await Promise.all([...paperSyncTasks.values()].filter(task => task.promise).map(task => task.promise));
        if (!isSessionCurrent(owner, generation)) return false;
        try {
            const result = await request(`/chat/history?session_id=${encodeURIComponent(owner)}&agent_mode=${encodeURIComponent(normalizedMode)}`, { method: 'DELETE' });
            if (!isSessionCurrent(owner, generation)) return false;
            if (result?.status !== 'success') throw new Error(result?.message || '清空失败');
            advanceMutation(normalizedMode);
            modeMessageBuckets.value[normalizedMode] = [];
            if (normalizedMode === 'paper') paperSyncTasks.clear();
            hydrateParsedMessages();
            if (clearNavigationGeneration === navigationGeneration && normalizeAgentMode(agentMode.value) === normalizedMode) {
                activeConversationId.value = null;
                draftConversationId.value = '';
                historyError.value = '';
            }
            showToast('历史记录已清空', 'success');
            return true;
        } catch (error) {
            if (isSessionCurrent(owner, generation)) {
                historyError.value = `云端清空未完成，历史记录仍保留：${error.message || '请重试'}`;
                showToast(historyError.value, 'warning');
            }
            return false;
        } finally {
            if (isSessionCurrent(owner, generation)) {
                blockedWriteModes.delete(normalizedMode);
                historyMutating.value = blockedWriteModes.size > 0;
            }
        }
    };

    hydrateParsedMessages();
    if (getSessionId() !== 'guest_user') {
        loadAllChatHistories();
    }

    const legacyFiles = ref([
        { id: 1, name: '软件杯竞赛指导书.pdf', size: '2.4 MB' },
        { id: 2, name: '大模型原理基础概念(必读).docx', size: '1.1 MB' }
    ]);

    const knowledgeRepositories = ref([]);
    const selectedRepositoryId = ref(localStorage.getItem(`knowledge_repo:${getSessionId()}`) || '');
    const newRepositoryName = ref('');
    const knowledgeLoading = ref(false);
    const knowledgeUploading = ref(false);
    const knowledgeDeletingId = ref('');
    const knowledgeRepositoryDeletingId = ref('');
    const knowledgeDatasetId = ref('');
    const courseKnowledgeBases = ref([]);
    const selectedCourseDatasetIds = ref([]);

    const formatFileSize = (bytes) => {
        const size = Number(bytes || 0);
        if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`;
        if (size >= 1024) return `${(size / 1024).toFixed(1)} KB`;
        return `${size} B`;
    };

    const normalizeDocument = (doc) => ({
        id: doc.id,
        name: doc.filename,
        size: formatFileSize(doc.file_size),
        status: doc.status || 'parsing',
        repository_id: doc.repository_id,
        dataset_id: doc.dataset_id,
        rag_document_id: doc.rag_document_id,
        created_at: doc.created_at
    });

    const normalizeRepository = (repo) => ({
        ...repo,
        documents: Array.isArray(repo.documents) ? repo.documents.map(normalizeDocument) : [],
        document_count: Number(repo.document_count || repo.documents?.length || 0)
    });

    const selectedRepository = computed(() => (
        knowledgeRepositories.value.find(repo => repo.id === selectedRepositoryId.value) || null
    ));
    const files = computed(() => selectedRepository.value?.documents || []);

    const loadCourseKnowledgeBases = async () => {
        const owner = getSessionId(), generation = sessionGeneration;
        try {
            const resJson = await knowledgeApi.getCourseKnowledgeBases();
            if (!isSessionCurrent(owner, generation)) return;
            const list = Array.isArray(resJson?.data) ? resJson.data : [];
            courseKnowledgeBases.value = list;
            if (selectedCourseDatasetIds.value.length === 0 && list.length > 0) {
                selectedCourseDatasetIds.value = list.map(item => item.id);
            }
        } catch (error) {
            console.info('[Knowledge] Course knowledge bases unavailable.', error);
        }
    };

    const toggleCourseDataset = (datasetId) => {
        const idx = selectedCourseDatasetIds.value.indexOf(datasetId);
        if (idx >= 0) {
            selectedCourseDatasetIds.value.splice(idx, 1);
        } else {
            selectedCourseDatasetIds.value.push(datasetId);
        }
    };

    const loadKnowledgeRepositories = async () => {
        const userId = getSessionId();
        const generation = sessionGeneration;
        if (!userId || userId === 'guest_user') return;
        knowledgeLoading.value = true;
        try {
            const resJson = await knowledgeApi.list(userId);
            if (!isSessionCurrent(userId, generation)) return;
            const data = resJson?.data || {};
            knowledgeDatasetId.value = data.dataset_id || '';
            knowledgeRepositories.value = Array.isArray(data.repositories) ? data.repositories.map(normalizeRepository) : [];
            if (!knowledgeRepositories.value.some(repo => repo.id === selectedRepositoryId.value)) {
                selectedRepositoryId.value = knowledgeRepositories.value[0]?.id || '';
            }
            if (selectedRepositoryId.value) {
                localStorage.setItem(`knowledge_repo:${userId}`, selectedRepositoryId.value);
            } else {
                localStorage.removeItem(`knowledge_repo:${userId}`);
            }
        } catch (error) {
            console.info('[Knowledge] Backend unavailable.', error);
            if (isSessionCurrent(userId, generation)) showToast('知识库暂时无法同步', 'error');
        } finally {
            if (isSessionCurrent(userId, generation)) knowledgeLoading.value = false;
        }
    };

    const selectKnowledgeRepository = (repoId) => {
        selectedRepositoryId.value = repoId;
        if (repoId) {
            localStorage.setItem(`knowledge_repo:${getSessionId()}`, repoId);
        }
    };

    const createKnowledgeRepository = async () => {
        const name = newRepositoryName.value.trim();
        if (!name) return showToast('请输入仓库名称', 'error');
        knowledgeLoading.value = true;
        try {
            const resJson = await knowledgeApi.createRepository({ userId: getSessionId(), name });
            const repo = normalizeRepository(resJson.data);
            knowledgeRepositories.value.push(repo);
            selectKnowledgeRepository(repo.id);
            newRepositoryName.value = '';
            showToast('仓库已创建', 'success');
        } catch (error) {
            showToast(error.message || '仓库创建失败', 'error');
        } finally {
            knowledgeLoading.value = false;
        }
    };

    const toggleRAG = () => {
        const nextMode = forceRAG.value ? 'tutor' : 'rag';
        setAgentMode(nextMode);
        showToast(nextMode === 'rag' ? '已开启专属知识库检索模式' : '已切换回多智能体引导式学习模式', 'success');
    };

    const fillInput = (text) => {
        inputText.value = text;
    };

    const shouldTriggerVisualGuideGeneration = (prompt) => {
        const text = String(prompt || '').trim();
        if (!text) return false;
        const compactText = text.replace(/\s+/g, '');
        const questionPattern = /[?？]|(什么|为什么|为何|如何|怎么|怎样|讲解|解释|说明|请问|帮我|学习|制定|生成|画|图解|步骤|流程|原理|概念|架构|区别|对比|实现|分析)/;
        if (questionPattern.test(text)) return true;
        return compactText.length >= 18 && /(结构|算法|模型|系统|机制|场景|应用|关系|过程)/.test(text);
    };

    const visualGuideTypes = [
        { id: 'steps', label: '步骤图', icon: 'ph-list-checks' }
    ];

    const getVisualGuideTypeMeta = (type) => visualGuideTypes.find(item => item.id === type) || visualGuideTypes[0];
    const canOpenVisualGuideViewer = computed(() => (
        visualGuideStatus.value !== 'generating' &&
        Boolean(visualGuidePrompt.value.trim()) &&
        Boolean(
            visualGuideImage.value?.renderedSvg ||
            visualGuideImage.value?.treeText ||
            visualGuideImage.value?.mermaid ||
            visualGuideImage.value?.svg ||
            visualGuideImage.value?.backgroundUrl ||
            visualGuideImage.value?.backgroundBase64 ||
            visualGuideImage.value?.imageUrl ||
            visualGuideImage.value?.imageBase64 ||
            visualGuide.value?.title
        )
    ));

    const generateVisualGuide = async (prompt = visualGuidePrompt.value, options = {}) => {
        const { reason = 'tab-demand', force = false } = options;
        const cleanPrompt = (prompt || visualGuidePrompt.value || '').trim();
        if (!cleanPrompt) return;

        // 1. 判断是否是新问题。如果 prompt 与缓存的当前问题不同，说明是全新查询，清空缓存并更新当前问题
        if (cleanPrompt !== visualGuidePrompt.value || reason === 'student-question') {
            visualGuideCache.value = {};
            visualGuidePrompt.value = cleanPrompt;
        }

        // 2. 检查是否有当前类型的缓存数据
        if (!force && visualGuideCache.value[visualGuideType.value]) {
            const cached = visualGuideCache.value[visualGuideType.value];
            visualGuideImage.value = cached.image;
            visualGuide.value = cached.guide;
            visualGuideStatus.value = cached.status;
            return;
        }

        const requestId = ++visualGuideRequestId;
        const sessionId = getSessionId();
        visualGuideStatus.value = 'generating';
        visualGuideImage.value = null;
        showVisualGuideViewer.value = false;

        let backendGuide = null;
        const architectureAgent = getArchitectureGuideAgent();
        try {
            backendGuide = await requestVisualGuideImage({
                prompt: cleanPrompt,
                guideType: visualGuideType.value,
                sessionId,
                imageModel: getVisualGuideAgent()?.model,
                textModel: architectureAgent?.model,
                architectureAgent
            });
        } catch (error) {
            console.info('[Mira] Visual guide backend unavailable, using local sketch mode.', error);
        }

        if (requestId !== visualGuideRequestId) return;

        const localGuide = createLocalVisualGuide(cleanPrompt, visualGuideType.value);
        const resolvedGuide = resolveVisualGuideState({ localGuide, backendGuide });
        const renderedImage = await renderArchitectureGuide(resolvedGuide.image);
        if (requestId !== visualGuideRequestId) return;

        visualGuideImage.value = renderedImage;
        visualGuide.value = resolvedGuide.guide;
        visualGuideStatus.value = resolvedGuide.status;

        // 3. 将本次成功渲染生成的数据放入缓存中
        visualGuideCache.value[visualGuideType.value] = {
            image: renderedImage,
            guide: resolvedGuide.guide,
            status: resolvedGuide.status
        };

        visualGuideHistory.value.unshift({
            id: Date.now(),
            type: visualGuideType.value,
            prompt: cleanPrompt,
            title: visualGuide.value.title,
            source: resolvedGuide.historySource,
            generatedAt: visualGuide.value.generatedAt
        });
        visualGuideHistory.value = visualGuideHistory.value.slice(0, 3);

        window.dispatchEvent?.(new CustomEvent('agent-log', {
            detail: {
                agent: 'Mira',
                content: resolvedGuide.logMessage,
                time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
            }
        }));
    };

    const switchVisualGuideType = (type) => {
        if (visualGuideType.value === type) return;
        visualGuideType.value = type;
        if (!visualGuidePrompt.value.trim()) return;
        generateVisualGuide(visualGuidePrompt.value, { reason: 'tab-demand' });
    };

    const regenerateVisualGuide = () => {
        if (!visualGuidePrompt.value.trim()) return;
        delete visualGuideCache.value[visualGuideType.value];
        generateVisualGuide(visualGuidePrompt.value, { reason: 'regenerate', force: true });
    };

    const openVisualGuideViewer = () => {
        if (!canOpenVisualGuideViewer.value) return;
        showVisualGuideViewer.value = true;
    };

    const closeVisualGuideViewer = () => {
        showVisualGuideViewer.value = false;
    };

    const selectVisualGuideHistory = (item) => {
        if (!item) return;
        visualGuideType.value = item.type;
        generateVisualGuide(item.prompt, { reason: 'history' });
    };

    const renderArchitectureGuide = async (image) => {
        if (!image?.mermaid) return image;
        // mermaid 库未加载成功（CDN 失败等）时标记渲染失败，让界面展示友好提示而不是源码
        if (!window.mermaid?.render) {
            console.info('[Mira] Mermaid engine unavailable, architecture guide will show failure hint.');
            return { ...image, renderError: '图表引擎未加载成功，请检查网络后重新生成' };
        }

        try {
            // 自动为未包裹双引号的节点文案加上双引号，防止尖括号(<br>)、空格等字符引发 Mermaid 语法解析报错
            const cleanedMermaid = image.mermaid.replace(/([a-zA-Z0-9_-]+)\[([^"\]\n\r]+)\]/g, '$1["$2"]');

            const renderId = `visual-guide-architecture-${Date.now()}-${Math.random().toString(36).slice(2)}`;
            const { svg } = await window.mermaid.render(renderId, cleanedMermaid);
            return { ...image, mermaid: cleanedMermaid, renderedSvg: svg };
        } catch (error) {
            console.info('[Mira] Mermaid architecture render failed.', error);
            return { ...image, renderError: error?.message || String(error) };
        }
    };

    const downloadTextArtifact = (content, filename, type = 'text/plain;charset=utf-8') => {
        const blob = new Blob([content], { type });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = filename;
        link.click();
        URL.revokeObjectURL(url);
    };

    const downloadVisualGuide = () => {
        if (!visualGuidePrompt.value.trim()) return;
        if (visualGuideImage.value?.renderedSvg) {
            downloadTextArtifact(
                visualGuideImage.value.renderedSvg,
                `${visualGuide.value.center || 'prof-x-architecture'}.svg`,
                'image/svg+xml;charset=utf-8'
            );
            return;
        }

        if (visualGuideImage.value?.mermaid) {
            downloadTextArtifact(
                visualGuideImage.value.mermaid,
                `${visualGuide.value.center || 'prof-x-architecture'}.mmd`
            );
            return;
        }

        if (visualGuideImage.value?.treeText) {
            downloadTextArtifact(
                visualGuideImage.value.treeText,
                `${visualGuide.value.center || 'prof-x-architecture'}.txt`
            );
            return;
        }

        if (visualGuideImage.value?.svg) {
            const blob = new Blob([visualGuideImage.value.svg], { type: 'image/svg+xml;charset=utf-8' });
            const link = document.createElement('a');
            link.href = URL.createObjectURL(blob);
            link.download = `${visualGuide.value.center || 'mira-guide'}.svg`;
            link.click();
            URL.revokeObjectURL(link.href);
            return;
        }

        if (visualGuideImage.value?.imageUrl || visualGuideImage.value?.imageBase64) {
            const link = document.createElement('a');
            link.href = visualGuideImage.value.imageUrl || visualGuideImage.value.imageBase64;
            link.download = `${visualGuide.value.center || 'mira-guide'}.png`;
            link.click();
            return;
        }

        const svg = visualGuideImage.value?.svg || buildVisualGuideSvg(visualGuide.value, visualGuideType.value);
        const blob = new Blob([svg], { type: 'image/svg+xml;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `${visualGuide.value.center || 'mira-guide'}.svg`;
        link.click();
        URL.revokeObjectURL(url);
    };

    const legacyTriggerFileInput = (isLoggedIn) => {
        if (!isLoggedIn) return showToast('请先登录后上传个人资料', 'error');
        const fileInput = document.getElementById('realFileInput');
        if (fileInput) fileInput.click();
    };

    const legacyHandleFileUpload = async (event) => {
        const file = event.target.files[0];
        if (!file) return;

        showToast('正在上传并解析文档...', 'success');
        const formData = new FormData();
        formData.append('user_id', getSessionId());
        formData.append('file', file);

        try {
            const resJson = await userApi.uploadFile(formData);

            if (resJson && resJson.status === 'success') {
                files.value.unshift({ id: Date.now(), name: file.name, size: (file.size / 1024 / 1024).toFixed(2) + ' MB' });
                showToast('私有知识库更新成功！', 'success');
            } else {
                showToast('上传失败: ' + (resJson?.message || '未知错误'), 'error');
            }
        } catch (err) {
            showToast('网络错误，上传失败', 'error');
        }
        event.target.value = '';
    };

    const triggerFileInput = (isLoggedIn) => {
        if (!isLoggedIn) return showToast('请先登录后上传个人资料', 'error');
        if (!selectedRepositoryId.value) return showToast('请先创建或选择一个仓库', 'error');
        const fileInput = document.getElementById('realFileInput');
        if (fileInput) fileInput.click();
    };

    const handleFileUpload = async (event) => {
        const file = event.target.files[0];
        if (!file) return;
        if (!isSupportedKnowledgeFile(file)) {
            showToast('当前知识库仅支持上传 PDF 文件', 'error');
            event.target.value = '';
            return;
        }
        if (!selectedRepositoryId.value) {
            showToast('请先选择仓库', 'error');
            event.target.value = '';
            return;
        }

        knowledgeUploading.value = true;
        showToast('正在上传并同步 RAGFlow...', 'success');
        try {
            await knowledgeApi.uploadDocument({
                userId: getSessionId(),
                repositoryId: selectedRepositoryId.value,
                file
            });
            await loadKnowledgeRepositories();
            showToast('文件已进入个人知识库', 'success');
        } catch (error) {
            showToast(error.message || '上传失败', 'error');
        } finally {
            knowledgeUploading.value = false;
            event.target.value = '';
        }
    };

    const deleteKnowledgeDocument = async (file) => {
        if (!file?.id) return;
        const confirmed = window.confirm(`确认从知识库删除「${file.name}」？`);
        if (!confirmed) return;

        knowledgeDeletingId.value = file.id;
        try {
            await knowledgeApi.deleteDocument({ userId: getSessionId(), documentId: file.id });
            await loadKnowledgeRepositories();
            showToast('文件已从 RAGFlow 同步删除', 'success');
        } catch (error) {
            showToast(error.message || '删除失败', 'error');
        } finally {
            knowledgeDeletingId.value = '';
        }
    };

    const deleteKnowledgeRepository = async (repo) => {
        if (!repo?.id) return;
        const confirmed = window.confirm(`确认删除资料仓库「${repo.name}」及其中的 ${repo.document_count || 0} 个文件？`);
        if (!confirmed) return;

        knowledgeRepositoryDeletingId.value = repo.id;
        try {
            await knowledgeApi.deleteRepository({ userId: getSessionId(), repositoryId: repo.id });
            if (selectedRepositoryId.value === repo.id) {
                selectedRepositoryId.value = '';
            }
            await loadKnowledgeRepositories();
            showToast('资料仓库已删除', 'success');
        } catch (error) {
            showToast(error.message || '仓库删除失败', 'error');
        } finally {
            knowledgeRepositoryDeletingId.value = '';
        }
    };

    loadKnowledgeRepositories();
    loadCourseKnowledgeBases();

    const sendMessage = async (overrideText = null) => {
        handleSessionStorage({ key: 'token' });
        const sessionId = getSessionId();
        const prompt = typeof overrideText === 'string' ? overrideText : inputText.value;
        if (!prompt.trim() || thinkingAgent.value || blockedWriteModes.has(normalizeAgentMode(agentMode.value))) return false;
        const repositoryId = agentMode.value === 'rag' ? selectedRepositoryId.value : '';
        const courseDatasetIds = agentMode.value === 'rag' ? [...selectedCourseDatasetIds.value] : null;
        let skillIds;
        try {
            skillIds = Object.freeze(validateChatSkillSelection({ skillIds: getChatSkillSelection(), agentMode: agentMode.value, forceRAG: forceRAG.value, repositoryId, courseDatasetIds }));
        } catch (error) {
            showToast(error.message, 'error');
            return false;
        }
        const conversationId = getConversationIdForSend();
        const projectId = activeProjectId.value || getSystemProjectIdForMode(agentMode.value);
        if (agentMode.value === 'tutor') {
            visualGuideType.value = 'steps';
            generateVisualGuide(prompt, { reason: 'student-question', force: true });
        }
        const mode = normalizeAgentMode(agentMode.value);
        const generation = sessionGeneration;
        const navigation = navigationGeneration;
        const controller = new AbortController();
        chatSendController = controller;
        const detachedMessages = modeMessageBuckets.value[mode];
        // Bind to the captured mode, but follow its live array across history reconciliation.
        const capturedMessages = computed(() => isSessionCurrent(sessionId, generation) ? modeMessageBuckets.value[mode] : detachedMessages);
        const isCurrent = () => isSessionCurrent(sessionId, generation) && navigation === navigationGeneration && chatSendController === controller && !controller.signal.aborted;
        try {
            return await sendStreamingMessage(
            prompt,
            capturedMessages,
            thinkingAgent,
            inputText,
            chatContainer,
            forceRAG.value,
            sessionId,
            agentMode.value,
            repositoryId,
            getActiveChatAgent(),
            courseDatasetIds,
            (modelId) => {
                showToast(`模型 ${modelId} 当前不可用，请更换模型`, 'error');
            },
            currentModel.value,
            conversationId,
            projectId,
            { signal: controller.signal, isCurrent, skillIds, onHistoryInvalidated: () => { if (isCurrent()) historyError.value = '任务上下文已变更，本次未保存模型回复；请刷新历史记录后重试'; } }
            );
        } finally {
            // Only this request may release its busy lease, even when its token changed.
            if (chatSendController === controller) { chatSendController = null; thinkingAgent.value = null; }
        }
    };

    watch(modeMessageBuckets, (newBuckets) => {
        CHAT_TASK_MODES.forEach(mode => {
            safeSetLocalStorage(getChatStorageKey(getSessionId(), mode), newBuckets[mode] || []);
        });
    }, { deep: true, flush: 'sync' });

    watch(() => currentUser.value?.username, () => {
        sessionGeneration += 1;
        invalidateWorkspaceNavigation();
        invalidateHistoryLoads();
        for (const task of paperSyncTasks.values()) task.controller?.abort();
        paperSyncTasks.clear();
        inputText.value = '';
        historyError.value = '';
        blockedWriteModes.clear();
        historyMutating.value = false;
        modeMessageBuckets.value = createModeMessageBuckets(readStoredMessages);
        activeConversationId.value = null;
        draftConversationId.value = '';
        paperActiveTab.value = 'results';
        projectList.value = readStoredProjects();
        activeProjectId.value = getSystemProjectIdForMode(agentMode.value);
        userCustomConfigs.value = [];
        visualGuideRequestId += 1;
        resetVisualGuideForNewConversation();
        visualGuideCache.value = {};
        visualGuideHistory.value = [];
        knowledgeRepositories.value = [];
        knowledgeLoading.value = false;
        knowledgeDatasetId.value = '';
        newRepositoryName.value = '';
        courseKnowledgeBases.value = [];
        selectedCourseDatasetIds.value = [];
        loadAllChatHistories();
        selectedRepositoryId.value = localStorage.getItem(`knowledge_repo:${getSessionId()}`) || '';
        loadKnowledgeRepositories();
        // 用户登入或账号切换时，即刻刷新专属自定义模型列表
        loadUserCustomModels();
    }, { flush: 'sync' });

    return {
        inputText,
        chatContainer,
        thinkingAgent,
        forceRAG,
        agentMode,
        historyLoading,
        historyError,
        historyMutating,
        setPaperActiveTab,
        paperWorkSyncStatus,
        retryPaperWorkSync,
        capturePaperSearchTransaction,
        getWorkspaceGeneration,
        getInputRevision,
        setWorkspaceCancellationHandler,
        setChatSkillSelectionResolver,
        activeConversationId,
        draftConversationId,
        modeMessageBuckets,
        conversationList,
        activeConversation,
        activeConversationMessages,
        isViewingHistory,
        sidebarActiveConversationId,
        projectList,
        activeProjectId,
        projectTaskTree,
        createProject,
        deleteProject,
        renameProject,
        toggleProjectExpand,
        startNewSubTask,
        currentModel,
        modelOptions,
        currentModelInfo,
        showModelDropdown,
        switchModel,
        toggleModelDropdown,
        userCustomConfigs,
        loadUserCustomModels,
        refreshUserCustomModels,
        switchWorkMode,
        showPaperSearchResults,
        paperActiveTab,
        returnToChatDialog,
        openPaperTaskDialog,
        recordPaperSearchWork,
        messages,
        files,
        knowledgeRepositories,
        selectedRepositoryId,
        selectedRepository,
        newRepositoryName,
        knowledgeLoading,
        knowledgeUploading,
        knowledgeDeletingId,
        knowledgeRepositoryDeletingId,
        knowledgeDatasetId,
        courseKnowledgeBases,
        selectedCourseDatasetIds,
        loadCourseKnowledgeBases,
        toggleCourseDataset,
        loadKnowledgeRepositories,
        selectKnowledgeRepository,
        createKnowledgeRepository,
        deleteKnowledgeRepository,
        deleteKnowledgeDocument,
        getKnowledgeFileStatusLabel,
        visualGuidePrompt,
        visualGuideType,
        visualGuideTypes,
        visualGuideStatus,
        visualGuide,
        visualGuideImage,
        visualGuideHistory,
        showVisualGuideViewer,
        canOpenVisualGuideViewer,
        toggleRAG,
        setAgentMode,
        loadChatHistory,
        startNewConversation,
        selectConversation,
        backToCurrentConversation,
        deleteConversation,
        clearChatHistory,
        fillInput,
        getVisualGuideTypeMeta,
        getVisualGuideSourceLabel: () => visualGuidePrompt.value.trim() ? getVisualGuideSourceLabel(visualGuideImage.value) : '等待输入',
        getActiveChatAgent,
        switchVisualGuideType,
        regenerateVisualGuide,
        selectVisualGuideHistory,
        openVisualGuideViewer,
        closeVisualGuideViewer,
        downloadVisualGuide,
        triggerFileInput,
        handleFileUpload,
        sendMessage,
        parsedHtmlCache
    };
}
