import { renderMarkdown } from '../utils/safeRendering.js';
import { reactive, nextTick } from 'vue';
import { throttle } from '../utils/helpers.js';
import request from '../utils/request.js';
import { buildChatPayload, formatChatTimestamp, normalizeAgentMode } from '../utils/chatModes.js';

export const parsedHtmlCache = reactive({});

// Keep the local name for cache callers, with a single safe rendering boundary.
const safeParse = renderMarkdown;

export const throttledParse = throttle((id, text, isCurrent = () => true) => {
    if (!isCurrent()) return;
    parsedHtmlCache[id] = safeParse(text);
}, 200);

export const throttledScroll = throttle(async (chatContainer, isCurrent = () => true) => {
    await nextTick();
    if (!isCurrent()) return;
    if (chatContainer && chatContainer.value) {
        chatContainer.value.scrollTop = chatContainer.value.scrollHeight;
    }
}, 120);

export async function sendStreamingMessage(msg, messages, thinkingAgent, inputText, chatContainer, forceRAG = false, sessionId = 'guest_user', agentMode = 'tutor', repositoryId = '', agent = null, courseDatasetIds = null, onModelUnavailable = null, model = '', conversationId = '', projectId = '', lifecycle = {}) {
    const capturedToken = globalThis.localStorage?.getItem('token') || '';
    const isCurrent = () => !lifecycle.signal?.aborted && (typeof lifecycle.isCurrent !== 'function' || lifecycle.isCurrent()) && capturedToken === (globalThis.localStorage?.getItem('token') || '');
    const requireCurrent = () => { if (!isCurrent()) { const error = new Error('Conversation request cancelled'); error.name = 'AbortError'; throw error; } };
    const requestOptions = { signal: lifecycle.signal, headers: { Authorization: capturedToken ? `Bearer ${capturedToken}` : '' } };
    if (!msg.trim() || thinkingAgent.value || !isCurrent()) return;
    const normalizedMode = normalizeAgentMode(agentMode);
    // A retry is the same submission. Never reread mounted Skills, mutable
    // agent settings or the model choice after transport has started.
    const requestBody = JSON.stringify(buildChatPayload({ message: msg, forceRAG, sessionId, agentMode: normalizedMode, conversationId, projectId, repositoryId, agent, courseDatasetIds, model, skillIds: lifecycle.skillIds || [] }));
    const usesChatSkill = Boolean(lifecycle.skillIds?.length);
    const currentTime = formatChatTimestamp();

    const requestId = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    const userMsgId = `local-user-${requestId}`;
    const userMessage = reactive({ id: userMsgId, senderType: 'user', content: msg, time: currentTime, createdAt: currentTime, mode: normalizedMode, conversationId, projectId, syncState: 'pending' });
    messages.value.push(userMessage);
    parsedHtmlCache[userMsgId] = safeParse(msg);

    inputText.value = '';
    throttledScroll(chatContainer, isCurrent);

    const resolvedAgentId = normalizedMode === 'paper' ? 'agent_paper' : (normalizedMode === 'rag' ? 'agent_researcher' : 'agent_tutor');
    thinkingAgent.value = resolvedAgentId;
    const streamMessageId = `local-agent-${requestId}`;
    const agentTime = formatChatTimestamp();
    const newAgentMsg = reactive({
        id: streamMessageId,
        senderType: 'agent',
        senderId: resolvedAgentId,
        time: agentTime,
        createdAt: agentTime,
        mode: normalizedMode,
        conversationId,
        projectId,
        syncState: 'pending',
        content: ''
    });
    messages.value.push(newAgentMsg);
    parsedHtmlCache[streamMessageId] = '';
    const applyHistoryReceipt = completion => {
        if (!isCurrent()) return;
        const receipt = completion?.history_receipt;
        // A complete receipt with null assistant ID is an authoritative invalidation,
        // rather than an unconfirmed transport failure. Never revive deleted context.
        const invalidated = completion?.history_invalidated === true && completion?.history_saved === false && receipt && Object.hasOwn(receipt, 'user_message_id') && receipt.assistant_message_id === null && (receipt.user_message_id === null || (Number.isInteger(receipt.user_message_id) && receipt.user_message_id > 0));
        if (invalidated) {
            for (let index = messages.value.length - 1; index >= 0; index -= 1) {
                const row = messages.value[index];
                if (row.id === newAgentMsg.id || (receipt.user_message_id === null && row.id === userMessage.id)) {
                    delete parsedHtmlCache[row.id];
                    messages.value.splice(index, 1);
                }
            }
            if (receipt.user_message_id !== null) {
                const previousId = userMessage.id;
                userMessage.id = `db-${receipt.user_message_id}`;
                userMessage.syncState = 'saved';
                userMessage.syncError = '';
                parsedHtmlCache[userMessage.id] = safeParse(userMessage.content);
                delete parsedHtmlCache[previousId];
            }
            if (typeof lifecycle.onHistoryInvalidated === 'function') lifecycle.onHistoryInvalidated();
            return;
        }
        const saved = Boolean(newAgentMsg.content.trim()) && !newAgentMsg.deliveryError && !['empty', 'failed'].includes(newAgentMsg.deliveryStatus) && completion?.history_saved === true && Number.isInteger(receipt?.user_message_id) && receipt.user_message_id > 0 && Number.isInteger(receipt?.assistant_message_id) && receipt.assistant_message_id > 0;
        [userMessage, newAgentMsg].forEach((message, index) => {
            const previousId = message.id;
            message.syncState = saved ? 'saved' : 'failed';
            message.syncError = saved ? '' : newAgentMsg.deliveryError ? '本次模型回复未保存，请处理错误后重试' : '云端保存未确认，请刷新历史记录核对';
            if (saved) {
                const databaseId = `db-${index === 0 ? receipt.user_message_id : receipt.assistant_message_id}`;
                const canonical = messages.value.find(row => row.id === databaseId && row !== message);
                if (canonical) {
                    // A concurrent refresh may have already loaded this receipt row.
                    canonical.syncState = 'saved';
                    canonical.syncError = '';
                    for (let position = messages.value.length - 1; position >= 0; position -= 1) {
                        if (messages.value[position].id === previousId) messages.value.splice(position, 1);
                    }
                    parsedHtmlCache[databaseId] = safeParse(canonical.content);
                } else {
                    message.id = databaseId;
                    parsedHtmlCache[message.id] = safeParse(message.content);
                }
                delete parsedHtmlCache[previousId];
            }
        });
    };
    let streamCompletion = null;
    let streamDeliveryError = null;
    const applyCompletion = completion => {
        if (typeof completion?.content === 'string') newAgentMsg.content = completion.content;
        else if (typeof completion?.reply === 'string') newAgentMsg.content = completion.reply;
        if (completion?.delivery_status) newAgentMsg.deliveryStatus = completion.delivery_status;
        const receipt = completion?.history_receipt;
        // Legacy routes can recover on the server after a transient model
        // error. Only their authoritative successful saved pair clears it.
        // Selected chat Skills retain terminal errors and never opt into RAG.
        if (!usesChatSkill && completion?.delivery_status === 'complete' && completion?.history_saved === true
            && newAgentMsg.content.trim() && Number.isInteger(receipt?.user_message_id) && receipt.user_message_id > 0
            && Number.isInteger(receipt?.assistant_message_id) && receipt.assistant_message_id > 0) {
            streamDeliveryError = null;
            newAgentMsg.deliveryError = '';
            newAgentMsg.deliveryErrorCode = '';
        }
        // Canonical content may intentionally be empty after a provider error.
        // Keep its explicit terminal status and display the error separately.
        if (!newAgentMsg.content.trim() && !newAgentMsg.deliveryStatus) newAgentMsg.deliveryStatus = 'empty';
        const errorCode = completion?.error || streamDeliveryError?.code;
        if (errorCode || ['failed', 'empty'].includes(newAgentMsg.deliveryStatus)) {
            if (!newAgentMsg.deliveryStatus) newAgentMsg.deliveryStatus = errorCode === 'empty_response' ? 'empty' : 'failed';
            newAgentMsg.deliveryError = completion?.message || streamDeliveryError?.message
                || (newAgentMsg.deliveryStatus === 'empty' ? '模型未返回可显示的文本，请调整输入后重试' : '模型请求失败，请检查所选模型后重试');
            newAgentMsg.deliveryErrorCode = errorCode || (newAgentMsg.deliveryStatus === 'empty' ? 'empty_response' : 'model_error');
        }
        parsedHtmlCache[streamMessageId] = safeParse(newAgentMsg.content);
        applyHistoryReceipt(completion);
    };

    try {
        // Try streaming first, fall back to non-streaming if it fails
        let response;
        let useStreaming = true;
        
        try {
            requireCurrent();
            response = await request('/chat/stream', {
                ...requestOptions,
                method: 'POST',
                body: requestBody,
                isStream: true
            });
            requireCurrent();
            if (!response.ok) throw new Error('Stream API failed');
        } catch (streamError) {
            requireCurrent();
            if (streamError?.name === 'AbortError') throw streamError;
            console.warn('[Chat] Streaming failed, falling back to non-streaming:', streamError);
            useStreaming = false;
            // Use non-streaming endpoint as fallback
            requireCurrent();
            const chatResponse = await request('/chat', {
                ...requestOptions,
                method: 'POST',
                body: requestBody
            });
            requireCurrent();
            // Simulate streaming response
            if (chatResponse && typeof chatResponse.reply === 'string') {
                applyCompletion(chatResponse);
                if (chatResponse.error === 'model_unavailable' && typeof onModelUnavailable === 'function') onModelUnavailable(chatResponse.model || model);
                thinkingAgent.value = null;
                throttledScroll(chatContainer, isCurrent);
                return;
            }
            throw new Error('Both streaming and non-streaming failed');
        }

        if (!response.ok) throw new Error('API failed');

        requireCurrent();
        const reader = response.body.getReader();
        const cancelReader = () => { Promise.resolve(reader.cancel()).catch(() => {}); };
        lifecycle.signal?.addEventListener('abort', cancelReader, { once: true });
        const decoder = new TextDecoder('utf-8');
        let buffer = '';

        try {
        while (true) {
            requireCurrent();
            const { value, done } = await reader.read();
            requireCurrent();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop(); // 保留不完整的一行

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const dataStr = line.slice(6).trim();
                    if (!dataStr) continue;
                    try {
                        const data = JSON.parse(dataStr);
                        if (data.type === 'complete') {
                            streamCompletion = data;
                        } else if (data.type === 'reset') {
                            newAgentMsg.content = typeof data.content === 'string' ? data.content : '';
                            parsedHtmlCache[streamMessageId] = safeParse(newAgentMsg.content);
                        } else if (data.type === 'token') {
                            newAgentMsg.content += data.content;
                            throttledParse(streamMessageId, newAgentMsg.content, isCurrent);
                            throttledScroll(chatContainer, isCurrent);
                            const agentMap = {
                                'Alina': 'agent_planner',
                                '首席规划师': 'agent_planner',
                                'Prof. X': 'agent_tutor',
                                'Prof.X': 'agent_tutor',
                                '知识讲授导师': 'agent_tutor',
                                '导师': 'agent_tutor',
                                'DataBot': 'agent_researcher',
                                '数据检索助手': 'agent_researcher',
                                'CodeNinja': 'agent_coder',
                                '代码演示助手': 'agent_coder',
                                'PaperBot': 'agent_paper',
                                '论文研读助手': 'agent_paper',
                                '学术文献与前沿论文研读专家': 'agent_paper',
                                'agent_paper': 'agent_paper'
                            };
                            const agentId = agentMap[data.agent] || newAgentMsg.senderId || resolvedAgentId;
                            thinkingAgent.value = agentId;
                            newAgentMsg.senderId = agentId; // 动态变更消息发送者头像

                            // 派发全局日志事件，同步到教师监控大屏
                            if (window.dispatchEvent) {
                                window.dispatchEvent(new CustomEvent('agent-log', {
                                    detail: {
                                        agent: data.agent,
                                        content: data.status,
                                        time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
                                    }
                                }));
                            }
                        } else if (data.type === 'error') {
                            streamDeliveryError = { code: data.code || 'model_error', message: data.message || '模型请求失败，请重试' };
                            newAgentMsg.deliveryStatus = streamDeliveryError.code === 'empty_response' ? 'empty' : 'failed';
                            newAgentMsg.deliveryError = streamDeliveryError.message;
                        } else if (data.type === 'model_unavailable') {
                            streamDeliveryError = { code: 'model_unavailable', message: data.message || '所选模型当前不可用，请更换模型后重试' };
                            newAgentMsg.deliveryStatus = 'failed';
                            newAgentMsg.deliveryError = streamDeliveryError.message;
                            throttledScroll(chatContainer, isCurrent);
                            if (typeof onModelUnavailable === 'function') {
                                onModelUnavailable(data.model);
                            }
                        }
                    } catch (e) {
                        console.error('SSE JSON解析失败:', e);
                    }
                }
            }
        }

        } finally {
            lifecycle.signal?.removeEventListener('abort', cancelReader);
            reader.releaseLock?.();
        }
        requireCurrent();
        thinkingAgent.value = null;
        
        // If no content was received from streaming, fall back to non-streaming
        if (!newAgentMsg.content && useStreaming && !streamCompletion && !streamDeliveryError) {
            console.warn('[Chat] No token events received, falling back to non-streaming');
            try {
                requireCurrent();
                const chatResponse = await request('/chat', {
                    ...requestOptions,
                    method: 'POST',
                    body: requestBody
                });
                requireCurrent();
                if (chatResponse && typeof chatResponse.reply === 'string') {
                    newAgentMsg.content = chatResponse.reply;
                    streamCompletion = chatResponse;
                }
            } catch (fallbackError) {
                requireCurrent();
                console.error('[Chat] Fallback also failed:', fallbackError);
            }
        }
        
        applyCompletion(streamCompletion);
        throttledScroll(chatContainer, isCurrent);

    } catch (error) {
        if (!isCurrent() || error?.name === 'AbortError') return false;
        thinkingAgent.value = null;
        userMessage.syncState = 'failed';
        newAgentMsg.syncState = 'failed';
        newAgentMsg.deliveryStatus = 'failed';
        newAgentMsg.deliveryError = '请求失败，未获得模型回复。请检查连接后重试。';
        newAgentMsg.deliveryErrorCode = 'transport_error';
        newAgentMsg.content = '请求失败，未获得模型回复。请检查连接后重试。';
        parsedHtmlCache[streamMessageId] = safeParse(newAgentMsg.content);
        throttledScroll(chatContainer, isCurrent);
    }
}
