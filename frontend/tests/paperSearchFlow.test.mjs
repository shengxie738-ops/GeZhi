import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import { createWorkspaceMessageSender } from '../js/controllers/workspaceSendRouter.js';

function createSpy(implementation = () => {}) {
    const fn = async (...args) => {
        fn.calls.push(args);
        return await implementation(...args);
    };
    fn.calls = [];
    return fn;
}

test('paperSearchFlow: paper mode invokes searchPapers once and never invokes sendChat', async () => {
    const sendChatSpy = createSpy();
    const searchPapersSpy = createSpy(async () => true);
    let inputValue = 'Attention Is All You Need';
    const clearInputSpy = createSpy(() => { inputValue = ''; });

    const sendMessage = createWorkspaceMessageSender({
        getMode: () => 'paper',
        getInput: () => inputValue,
        isPaperSearching: () => false,
        sendChat: sendChatSpy,
        searchPapers: searchPapersSpy,
        clearInput: clearInputSpy
    });

    const result = await sendMessage();

    assert.equal(result, true);
    assert.equal(searchPapersSpy.calls.length, 1, 'searchPapers 应恰好调用 1 次');
    assert.equal(searchPapersSpy.calls[0][0], 'Attention Is All You Need');
    assert.equal(sendChatSpy.calls.length, 0, 'sendChat 绝不得被调用');
    assert.equal(clearInputSpy.calls.length, 1, '成功检索后应清空输入');
    assert.equal(inputValue, '');
});

for (const eventType of ['click', 'keydown']) {
    test(`paperSearchFlow: ${eventType} event is never stringified as the paper query`, async () => {
        const searchPapersSpy = createSpy(async () => true);
        const sendMessage = createWorkspaceMessageSender({
            getMode: () => 'paper',
            getInput: () => 'Attention Is All You Need',
            isPaperSearching: () => false,
            sendChat: createSpy(),
            searchPapers: searchPapersSpy,
            clearInput: createSpy()
        });

        await sendMessage({ type: eventType, preventDefault() {} });

        assert.equal(searchPapersSpy.calls.length, 1);
        assert.equal(
            searchPapersSpy.calls[0][0],
            'Attention Is All You Need',
            'Vue 事件对象必须被忽略，并从输入框读取真实查询词'
        );
    });
}

test('paperSearchFlow: workspace template invokes sendMessage explicitly for click and Enter', () => {
    const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');

    assert.doesNotMatch(html, /@click="sendMessage"/);
    assert.doesNotMatch(html, /@keydown\.enter\.exact\.prevent="sendMessage"/);
    assert.match(html, /@click="sendMessage\(\)"/);
    assert.match(html, /@keydown\.enter\.exact\.prevent="sendMessage\(\)"/);
});

test('paperSearchFlow: chat, tutor, and rag modes invoke sendChat once and never invoke searchPapers', async () => {
    const modes = ['chat', 'tutor', 'rag'];

    for (const mode of modes) {
        const sendChatSpy = createSpy();
        const searchPapersSpy = createSpy();
        const clearInputSpy = createSpy();

        const sendMessage = createWorkspaceMessageSender({
            getMode: () => mode,
            getInput: () => `Query for ${mode}`,
            isPaperSearching: () => false,
            sendChat: sendChatSpy,
            searchPapers: searchPapersSpy,
            clearInput: clearInputSpy
        });

        await sendMessage();

        assert.equal(sendChatSpy.calls.length, 1, `${mode} 模式下 sendChat 应恰好调用 1 次`);
        assert.equal(sendChatSpy.calls[0][0], `Query for ${mode}`);
        assert.equal(searchPapersSpy.calls.length, 0, `${mode} 模式下 searchPapers 绝不得被调用`);
    }
});

test('paperSearchFlow: empty query does not trigger any search or chat and does not clear input', async () => {
    const sendChatSpy = createSpy();
    const searchPapersSpy = createSpy();
    const clearInputSpy = createSpy();

    const sendMessage = createWorkspaceMessageSender({
        getMode: () => 'paper',
        getInput: () => '   \n  ',
        isPaperSearching: () => false,
        sendChat: sendChatSpy,
        searchPapers: searchPapersSpy,
        clearInput: clearInputSpy
    });

    const result = await sendMessage();

    assert.equal(result, false);
    assert.equal(searchPapersSpy.calls.length, 0, '空查询不触发 searchPapers');
    assert.equal(sendChatSpy.calls.length, 0, '空查询不触发 sendChat');
    assert.equal(clearInputSpy.calls.length, 0, '空查询不应清空输入');
});

test('paperSearchFlow: does not resubmit when paper search is already in progress', async () => {
    const sendChatSpy = createSpy();
    const searchPapersSpy = createSpy();
    const clearInputSpy = createSpy();

    const sendMessage = createWorkspaceMessageSender({
        getMode: () => 'paper',
        getInput: () => 'transformer model',
        isPaperSearching: () => true, // 正在搜索中
        sendChat: sendChatSpy,
        searchPapers: searchPapersSpy,
        clearInput: clearInputSpy
    });

    const result = await sendMessage();

    assert.equal(result, false);
    assert.equal(searchPapersSpy.calls.length, 0, '进行中的检索不应重复提交');
    assert.equal(sendChatSpy.calls.length, 0);
    assert.equal(clearInputSpy.calls.length, 0);
});

test('paperSearchFlow: only clears input when searchPapers returns true', async () => {
    const sendChatSpy = createSpy();
    const searchPapersFailSpy = createSpy(async () => false); // 失败或由于无插件被拦截
    let inputValue = 'failed query';
    const clearInputSpy = createSpy(() => { inputValue = ''; });

    const sendMessage = createWorkspaceMessageSender({
        getMode: () => 'paper',
        getInput: () => inputValue,
        isPaperSearching: () => false,
        sendChat: sendChatSpy,
        searchPapers: searchPapersFailSpy,
        clearInput: clearInputSpy
    });

    const result = await sendMessage();

    assert.equal(result, false);
    assert.equal(searchPapersFailSpy.calls.length, 1);
    assert.equal(clearInputSpy.calls.length, 0, '检索未成功时不应清空输入');
    assert.equal(inputValue, 'failed query', '输入内容必须保留方便用户修改或重试');
});

test('paperSearchFlow: send button disabled condition correctly includes paper searching state', () => {
    // 模拟前端 index.html 中的禁用逻辑:
    // :disabled="!inputText.trim() || thinkingAgent !== null || (agentMode === 'paper' && isSearchingPapers)"
    const isSendDisabled = ({ inputText, thinkingAgent, agentMode, isSearchingPapers }) => {
        return !inputText.trim() || thinkingAgent !== null || (agentMode === 'paper' && isSearchingPapers);
    };

    // 普通模式下不受 isSearchingPapers 影响
    assert.equal(isSendDisabled({ inputText: 'hi', thinkingAgent: null, agentMode: 'chat', isSearchingPapers: true }), false);
    assert.equal(isSendDisabled({ inputText: 'hi', thinkingAgent: null, agentMode: 'tutor', isSearchingPapers: true }), false);
    assert.equal(isSendDisabled({ inputText: 'hi', thinkingAgent: null, agentMode: 'rag', isSearchingPapers: true }), false);

    // 论文模式下，如果正在检索中，发送按钮必须被禁用 (防抖防重复点击)
    assert.equal(isSendDisabled({ inputText: 'Transformer', thinkingAgent: null, agentMode: 'paper', isSearchingPapers: true }), true);
    // 论文模式下，非检索中且输入非空，可发送
    assert.equal(isSendDisabled({ inputText: 'Transformer', thinkingAgent: null, agentMode: 'paper', isSearchingPapers: false }), false);
});

test('paperSearchFlow: invokes recordPaperWork after successful paper search', async () => {
    const searchPapersSpy = createSpy(async () => true);
    const recordPaperWorkSpy = createSpy(async () => {});
    let inputValue = 'Graph Neural Networks';

    const sendMessage = createWorkspaceMessageSender({
        getMode: () => 'paper',
        getInput: () => inputValue,
        isPaperSearching: () => false,
        sendChat: createSpy(),
        searchPapers: searchPapersSpy,
        clearInput: () => { inputValue = ''; },
        recordPaperWork: recordPaperWorkSpy
    });

    const result = await sendMessage();

    assert.equal(result, true);
    assert.equal(searchPapersSpy.calls.length, 1);
    assert.equal(recordPaperWorkSpy.calls.length, 1, '检索成功后应记录论文工作记录');
    assert.equal(recordPaperWorkSpy.calls[0][0], 'Graph Neural Networks');
});

test('paperSearchFlow: successful search leaves task history and exposes the paper result workspace', async () => {
    let visibleSurface = 'history';
    const completionOrder = [];
    const sendMessage = createWorkspaceMessageSender({
        getMode: () => 'paper',
        getInput: () => '查找金融量化的论文',
        isPaperSearching: () => false,
        searchPapers: async () => true,
        recordPaperWork: async () => { completionOrder.push('record'); },
        clearInput: () => {},
        showPaperResults: () => {
            completionOrder.push('show');
            visibleSurface = 'results';
        }
    });

    const result = await sendMessage();

    assert.equal(result, true);
    assert.equal(visibleSurface, 'results');
    assert.deepEqual(
        completionOrder,
        ['record', 'show'],
        '必须先用当前任务 ID 持久化，再切换结果页并清理草稿状态'
    );
});

test('paperSearchFlow: in paper study dialog tab, sendMessage routes to sendChat and strictly avoids searchPapers', async () => {
    const sendChatSpy = createSpy(async () => true);
    const searchPapersSpy = createSpy(async () => true);
    let inputValue = '请详细总结该论文的核心创新点与公式3的推导逻辑';

    const sendMessage = createWorkspaceMessageSender({
        getMode: () => 'paper',
        getPaperTab: () => 'dialog', // 处于研读对话页
        getInput: () => inputValue,
        isPaperSearching: () => false,
        sendChat: sendChatSpy,
        searchPapers: searchPapersSpy,
        clearInput: () => { inputValue = ''; }
    });

    const result = await sendMessage();

    assert.equal(result, true);
    assert.equal(sendChatSpy.calls.length, 1, '在研读对话页提问必须调用 sendChat 进行流式对话');
    assert.equal(sendChatSpy.calls[0][0], '请详细总结该论文的核心创新点与公式3的推导逻辑');
    assert.equal(searchPapersSpy.calls.length, 0, '在研读对话页提问绝不能触发 searchPapers 重新搜索文献');
});

