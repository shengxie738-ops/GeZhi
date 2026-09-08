import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { buildChatPayload } from '../js/utils/chatModes.js';

const resolveFile = (relPath) => {
    if (existsSync(relPath)) return relPath;
    const fallback = relPath.replace(/^frontend\//, './');
    if (existsSync(fallback)) return fallback;
    const fallback2 = './frontend/' + relPath.replace(/^\.\//, '');
    if (existsSync(fallback2)) return fallback2;
    return relPath;
};

test('Task 1: useAuth should have 一站式 Work menu configuration', () => {
    const authCode = readFileSync(resolveFile('frontend/js/hooks/useAuth.js'), 'utf-8');
    assert.match(authCode, /name:\s*['"]一站式 Work['"]/);
});

test('Task 2: buildChatPayload should support custom model selection for hot switching', () => {
    const payloadWithModel = buildChatPayload({
        message: 'Hello',
        model: 'deepseek-v4-pro-0813'
    });
    assert.equal(payloadWithModel.agent_model, 'deepseek-v4-pro-0813');

    const payloadWithAuto = buildChatPayload({
        message: 'Hello',
        model: 'Auto Mode'
    });
    assert.equal(payloadWithAuto.agent_model, undefined);
});

test('Task 2: useChat.js should export model switcher and work mode switcher', () => {
    const chatCode = readFileSync(resolveFile('frontend/js/hooks/useChat.js'), 'utf-8');
    assert.match(chatCode, /currentModel/);
    assert.match(chatCode, /modelOptions/);
    assert.match(chatCode, /switchModel/);
    assert.match(chatCode, /switchWorkMode/);
});

test('Task 3: index.html should contain Codex/TRAE style 一站式 Work workspace structure', () => {
    const htmlCode = readFileSync(resolveFile('frontend/index.html'), 'utf-8');

    // 不再有老旧分流提示
    assert.doesNotMatch(htmlCode, /选择您的工作台模式/);
    // 包含 AI 对话 侧栏按钮
    assert.match(htmlCode, /AI 对话/);
    // 包含 论文查询 侧栏按钮
    assert.match(htmlCode, /论文查询/);
    // 包含 新建任务 按钮
    assert.match(htmlCode, /新建任务/);
    // 包含 模型切换选择器与下拉面板
    assert.match(htmlCode, /toggleModelDropdown/);
    assert.match(htmlCode, /switchModel/);
    // 包含 projectTaskTree 折叠任务列表
    assert.match(htmlCode, /projectTaskTree/);
});

test('Task 4: Return to chat dialog functionality when paper search completed', () => {
    const chatCode = readFileSync(resolveFile('frontend/js/hooks/useChat.js'), 'utf-8');
    const mainCode = readFileSync(resolveFile('frontend/js/main.js'), 'utf-8');
    const htmlCode = readFileSync(resolveFile('frontend/index.html'), 'utf-8');

    // useChat.js 必须导出 returnToChatDialog 方法
    assert.match(chatCode, /returnToChatDialog/);
    assert.match(chatCode, /switchWorkMode\(['"]chat['"]\)/);

    // main.js 必须导出 returnToChatDialog 并联动 insertPaperToChat
    assert.match(mainCode, /returnToChatDialog:\s*chat\.returnToChatDialog/);
    assert.match(mainCode, /insertPaperToChat:\s*\(paper\)\s*=>/);

    // index.html 必须包含返回对话框按钮与其对应 id（已按需移除右下角悬浮按钮）
    assert.match(htmlCode, /header-return-to-chat-btn/);
    assert.match(htmlCode, /status-return-to-chat-btn/);
    assert.match(htmlCode, /bottom-return-to-chat-btn/);
    assert.doesNotMatch(htmlCode, /float-return-to-chat-btn/);
    assert.match(htmlCode, /@click="returnToChatDialog"/);
    assert.match(htmlCode, /返回对话框/);
    // 检索结果较长时从顶部排版，避免统计栏和首条论文被垂直居中裁掉
    assert.match(htmlCode, /paperSearchResults\.length > 0 \|\| paperSearchStatus !== ['"]idle['"]/);
    assert.match(htmlCode, /justify-start/);
});

test('Task 5: Anti-concurrency lock in workspaceSendRouter.js', () => {
    const routerCode = readFileSync(resolveFile('frontend/js/controllers/workspaceSendRouter.js'), 'utf-8');
    assert.match(routerCode, /let isRouting = false;/);
    assert.match(routerCode, /if \(isRouting\) \{/);
    assert.match(routerCode, /isRouting = true;/);
    assert.match(routerCode, /isRouting = false;/);
});

test('Task 6: Robust storage, XSS sanitization and persistent task state in useChat.js', () => {
    const chatCode = readFileSync(resolveFile('frontend/js/hooks/useChat.js'), 'utf-8');
    const htmlCode = readFileSync(resolveFile('frontend/index.html'), 'utf-8');

    // 验证安全存储防崩溃
    assert.match(chatCode, /const safeSetLocalStorage =/);
    // 验证XSS防范
    assert.match(chatCode, /const escapeHtmlAndMarkdown =/);
    assert.match(chatCode, /const sanitizePaperUrl =/);
    // 验证任务草稿 ID 与跨功能消息桶存在，任务不再依赖数据库消息 ID 重命名
    assert.match(chatCode, /draftConversationId/);
    // 验证场景A优化（由单一状态源 paperActiveTab 决定文献列表还是研读对话）
    assert.match(htmlCode, /\(agentMode === 'paper' && paperActiveTab === 'results'\)/);
});

test('Task 7: top-level new task must not pass the click event as a project id', () => {
    const chatCode = readFileSync(resolveFile('frontend/js/hooks/useChat.js'), 'utf-8');
    const htmlCode = readFileSync(resolveFile('frontend/index.html'), 'utf-8');

    assert.match(htmlCode, /@click="startNewConversation\(\)"/);
    assert.match(chatCode, /typeof projectId === ['"]string['"]/);
});

test('Task 8: recordPaperSearchWork must assign fresh task id to avoid hijacking older task', () => {
    const chatCode = readFileSync(resolveFile('frontend/js/hooks/useChat.js'), 'utf-8');

    // 验证新论文检索具有独立的 conversationId，杜绝复用已有历史任务导致任务列表不更新
    assert.match(chatCode, /createTaskConversationId\(['"]paper['"]\)/);
    assert.match(chatCode, /activeConversationId\.value = conversationId;/);
});

test('Task 9: returnToChatDialog in paper mode must switch paperActiveTab to dialog and never jump to chat mode', () => {
    const chatCode = readFileSync(resolveFile('frontend/js/hooks/useChat.js'), 'utf-8');

    // 验证 returnToChatDialog 严格保护论文模式：只切换 paperActiveTab 为 dialog，提前 return，避免破坏性跳回 AI 对话
    assert.match(chatCode, /if\s*\(\s*agentMode\.value\s*===\s*['"]paper['"]\s*\)\s*\{[\s\S]*?paperActiveTab\.value\s*=\s*['"]dialog['"]/);
    assert.match(chatCode, /paperActiveTab\.value\s*=\s*['"]dialog['"][\s\S]*?return;/);
});

test('Task 10: Claude Desktop single-task workflow exports openPaperTaskDialog and provides shortcut button in template', () => {
    const chatCode = readFileSync(resolveFile('frontend/js/hooks/useChat.js'), 'utf-8');
    const mainCode = readFileSync(resolveFile('frontend/js/main.js'), 'utf-8');
    const htmlCode = readFileSync(resolveFile('frontend/index.html'), 'utf-8');

    // 1. useChat.js 必须实现并导出 openPaperTaskDialog
    assert.match(chatCode, /const openPaperTaskDialog = async/);
    assert.match(chatCode, /openPaperTaskDialog,/);
    // 2. main.js 必须将 openPaperTaskDialog 导出至模板
    assert.match(mainCode, /openPaperTaskDialog:\s*handleOpenPaperTaskDialog/);
    // 3. index.html 必须在论文任务项中挂载研读快捷入口
    assert.match(htmlCode, /@click\.stop="openPaperTaskDialog\(task\.id\)"/);
    // 4. index.html 必须包含论文专属研读工作区空状态卡片
    assert.match(htmlCode, /论文专属研读工作区/);
});

test('Task 11: Workspace left sidebar must contain bottom settings button for custom AI model configuration', () => {
    const htmlCode = readFileSync(resolveFile('frontend/index.html'), 'utf-8');
    // 侧栏最底部包含设置按钮
    assert.match(htmlCode, /id="btn-workspace-model-settings"/);
    assert.match(htmlCode, /openCustomModelModal\(['"]create['"]\)/);
    assert.match(htmlCode, /模型设置/);
});

test('Task 12: Custom AI model modal must faithfully implement reference design with all fields and actions', () => {
    const htmlCode = readFileSync(resolveFile('frontend/index.html'), 'utf-8');
    const mainCode = readFileSync(resolveFile('frontend/js/main.js'), 'utf-8');

    // 模态框及响应式显隐
    assert.match(htmlCode, /v-if="showCustomModelModal"/);
    // 供应商与 API 类型选择
    assert.match(htmlCode, /v-model="customModelForm\.provider"/);
    assert.match(htmlCode, /v-model="customModelForm\.api_type"/);
    // 接口地址 Base URL 与 API Key
    assert.match(htmlCode, /id="input-custom-model-base-url"/);
    assert.match(htmlCode, /id="input-custom-model-api-key"/);
    assert.match(htmlCode, /id="btn-toggle-show-api-key"/);
    // Model ID 动态增删
    assert.match(htmlCode, /id="btn-add-model-id"/);
    assert.match(htmlCode, /removeCustomModelIdInput/);
    // 测试连通性与保存按钮
    assert.match(htmlCode, /id="btn-test-model-connection"/);
    assert.match(htmlCode, /id="btn-save-custom-model"/);
    // 管理已有模型 Tab
    assert.match(htmlCode, /customModelModalTab === ['"]manage['"]/);

    // main.js 中正确导出对应方法
    assert.match(mainCode, /showCustomModelModal/);
    assert.match(mainCode, /handleTestCustomModelConnection/);
    assert.match(mainCode, /handleSaveCustomModelConfig/);
});

test('Task 13: Model switcher in chat input bars must display custom model badges and hot-switch seamlessly', () => {
    const htmlCode = readFileSync(resolveFile('frontend/index.html'), 'utf-8');

    // 下拉面板中包含自定义模型高亮与配置快捷入口
    assert.match(htmlCode, /m\.isCustom/);
    assert.match(htmlCode, /配置自定义大模型\.\.\./);
});

