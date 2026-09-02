import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { buildChatPayload } from '../js/utils/chatModes.js';

test('Task 1: useAuth should have 一站式 Work menu configuration', () => {
    const authCode = readFileSync('./frontend/js/hooks/useAuth.js', 'utf-8');
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
    const chatCode = readFileSync('./frontend/js/hooks/useChat.js', 'utf-8');
    assert.match(chatCode, /currentModel/);
    assert.match(chatCode, /modelOptions/);
    assert.match(chatCode, /switchModel/);
    assert.match(chatCode, /switchWorkMode/);
});

test('Task 3: index.html should contain Codex/TRAE style 一站式 Work workspace structure', () => {
    const htmlCode = readFileSync('./frontend/index.html', 'utf-8');
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
