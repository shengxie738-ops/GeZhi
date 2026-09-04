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
        model: 'deepseek-v4-pro'
    });
    assert.equal(payloadWithModel.agent_model, 'deepseek-v4-pro');

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

    // index.html 必须包含返回对话框按钮与其对应 id
    assert.match(htmlCode, /header-return-to-chat-btn/);
    assert.match(htmlCode, /status-return-to-chat-btn/);
    assert.match(htmlCode, /float-return-to-chat-btn/);
    assert.match(htmlCode, /bottom-return-to-chat-btn/);
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
