/**
 * workspaceSendRouter.js - 工作台消息/检索发送分流控制器
 * 严格解耦论文检索链路与普通对话/问答链路，不调用 /api/chat/stream
 */

/**
 * 创建工作台发送分流函数
 * @param {object} deps 依赖项
 * @param {() => string} deps.getMode 获取当前 Agent 模式
 * @param {() => string} deps.getInput 获取当前输入框文本
 * @param {() => boolean} deps.isPaperSearching 判断当前是否处于论文检索中
 * @param {(text: string, options?: any) => Promise<any>} deps.sendChat 聊天链路发送方法
 * @param {(query: string, options?: any) => Promise<boolean>} deps.searchPapers 论文检索方法
 * @param {() => void} deps.clearInput 清空输入框回调
 * @param {() => void} deps.showPaperResults 切换至论文结果工作区
 * @returns {(overrideText?: string, options?: any) => Promise<any>}
 */
export function interpretPaperSearchResponse(response = {}) {
    if (response?.status !== 'error') {
        return { completed: true, errorMessage: '' };
    }

    const sourceErrors = (Array.isArray(response?.sourceStatuses) ? response.sourceStatuses : [])
        .filter(item => item?.status === 'error')
        .map(item => `${item.label || item.key || '未知来源'}：${item.error || '请求失败'}`);
    const details = sourceErrors.length ? `（${sourceErrors.join('；')}）` : '';

    return {
        completed: false,
        errorMessage: `全部论文来源检索失败，请稍后重试${details}`
    };
}

export function createWorkspaceMessageSender(deps = {}) {
    const {
        getMode = () => '',
        getInput = () => '',
        getPaperTab = () => 'results',
        isPaperSearching = () => false,
        sendChat = async () => {},
        searchPapers = async () => false,
        clearInput = () => {},
        recordPaperWork = async () => {},
        showPaperResults = () => {}
    } = deps;

    let isRouting = false;

    return async function sendMessage(overrideText = null, options = {}) {
        if (isRouting) {
            return false;
        }

        // Vue 的裸事件处理器会把 PointerEvent/KeyboardEvent 作为第一个参数传入。
        // 仅字符串可作为程序化查询覆盖值，其他类型一律回退到输入框真实内容。
        const text = (typeof overrideText === 'string'
            ? overrideText
            : String(getInput() || '')).trim();

        if (!text) {
            return false;
        }

        const mode = String(getMode ? getMode() : '').toLowerCase();

        if (mode === 'paper') {
            const paperTab = String(getPaperTab ? getPaperTab() : 'results').toLowerCase();
            // 研读对话态：用户与 AI 论文研读助手进行深度对话与追问，进入聊天流
            if (paperTab === 'dialog') {
                try {
                    isRouting = true;
                    return await sendChat(text, options);
                } finally {
                    isRouting = false;
                }
            }

            // 文献结果态：执行多来源学术文献检索
            // 处于检索中时防止重复提交
            if (isPaperSearching && isPaperSearching()) {
                return false;
            }

            try {
                isRouting = true;
                const success = await searchPapers(text, options);
                // 只有成功才沉淀工作记录并清空输入框，失败时保留查询词供用户修正
                if (success) {
                    if (typeof recordPaperWork === 'function') {
                        try {
                            await recordPaperWork(text, options);
                        } catch (e) {
                            console.warn('[Workspace] recordPaperWork failed:', e);
                        }
                    }
                    if (typeof showPaperResults === 'function') {
                        showPaperResults();
                    }
                    if (typeof clearInput === 'function') {
                        clearInput();
                    }
                    return true;
                }
                return false;
            } finally {
                isRouting = false;
            }
        }

        // chat, tutor, rag 模式进入原有聊天流
        try {
            isRouting = true;
            return await sendChat(text, options);
        } finally {
            isRouting = false;
        }
    };
}
