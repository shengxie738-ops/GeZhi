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
 * @returns {(overrideText?: string, options?: any) => Promise<any>}
 */
export function createWorkspaceMessageSender(deps = {}) {
    const {
        getMode = () => '',
        getInput = () => '',
        isPaperSearching = () => false,
        sendChat = async () => {},
        searchPapers = async () => false,
        clearInput = () => {}
    } = deps;

    return async function sendMessage(overrideText = null, options = {}) {
        const text = (overrideText !== null && overrideText !== undefined
            ? String(overrideText)
            : String(getInput() || '')).trim();

        if (!text) {
            return false;
        }

        const mode = String(getMode ? getMode() : '').toLowerCase();

        if (mode === 'paper') {
            // 处于检索中时防止重复提交
            if (isPaperSearching && isPaperSearching()) {
                return false;
            }

            const success = await searchPapers(text, options);
            // 只有成功才清空输入框，失败时保留查询词供用户修正
            if (success) {
                if (typeof clearInput === 'function') {
                    clearInput();
                }
                return true;
            }
            return false;
        }

        // chat, tutor, rag 模式进入原有聊天流
        return await sendChat(text, options);
    };
}
