import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = path.resolve(__dirname, '..');

const read = (relPath) => fs.readFileSync(path.join(projectRoot, relPath), 'utf-8');

test('Audit 1: Vue template bindings in index.html vs main.js setup exports', async () => {
    const html = read('index.html');
    const mainJs = read('js/main.js');

    // 1. 提取 main.js setup() 的 return { ... } 中的全部 key
    const setupIdx = mainJs.indexOf('setup() {');
    assert.ok(setupIdx !== -1, 'main.js 必须包含 setup() 函数');
    const setupBody = mainJs.slice(setupIdx);
    const lastReturnIdx = setupBody.lastIndexOf('return {');
    const returnSlice = setupBody.slice(lastReturnIdx);
    const returnEnd = returnSlice.indexOf('};');
    const returnBody = returnSlice.slice(0, returnEnd);

    const exportedKeys = new Set();
    returnBody.split('\n').forEach(line => {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith('//') || trimmed.startsWith('return {')) return;
        const match = trimmed.match(/^([a-zA-Z0-9_$]+)\s*[:,\n]/);
        if (match) {
            exportedKeys.add(match[1]);
        }
    });

    console.log(`[Audit 1] main.js setup() 共导出 ${exportedKeys.size} 个属性/方法`);

    // 2. 检查自定义模型模态框 (showCustomModelModal 区间)
    const modalStart = html.indexOf('v-if="showCustomModelModal"');
    assert.ok(modalStart !== -1, 'index.html 必须包含自定义模型模态框');
    const modalEnd = html.indexOf('</transition>', modalStart);
    const modalHtml = html.slice(modalStart, modalEnd);

    // 模态框中关键变量与事件
    const expectedModalBindings = [
        'showCustomModelModal',
        'closeCustomModelModal',
        'customModelModalTab',
        'editingConfigId',
        'userCustomConfigs',
        'customModelForm',
        'customModelProviderOptions',
        'customModelApiTypeOptions',
        'showCustomModelApiKey',
        'toggleShowCustomModelApiKey',
        'addCustomModelIdInput',
        'removeCustomModelIdInput',
        'customModelTestResult',
        'handleTestCustomModelConnection',
        'isTestingCustomModel',
        'handleSaveCustomModelConfig',
        'isSavingCustomModel',
        'openCustomModelModal',
        'handleDeleteCustomModelConfig',
        'switchModel',
        'currentModel'
    ];

    const missingInMain = [];
    for (const key of expectedModalBindings) {
        if (!exportedKeys.has(key)) {
            missingInMain.push(key);
        }
    }
    assert.deepEqual(missingInMain, [], `模态框中引用的变量必须在 main.js 中全部导出，缺失: ${missingInMain.join(', ')}`);

    // 3. 检查输入栏模型热切换面板 (首屏 & 底部)
    const expectedDropdownBindings = [
        'toggleModelDropdown',
        'currentModelInfo',
        'currentModel',
        'showModelDropdown',
        'modelOptions',
        'switchModel',
        'openCustomModelModal'
    ];

    const missingDropdownKeys = [];
    for (const key of expectedDropdownBindings) {
        if (!exportedKeys.has(key)) {
            missingDropdownKeys.push(key);
        }
    }
    assert.deepEqual(missingDropdownKeys, [], `模型热切换下拉中引用的变量必须在 main.js 中全部导出，缺失: ${missingDropdownKeys.join(', ')}`);
});

test('Audit 2: useCustomModels concurrency guard inspection', async () => {
    const hookCode = read('js/hooks/useCustomModels.js');

    // 检查 handleTestConnection 是否有内置 isTesting 并发锁
    const hasTestingGuard = /handleTestConnection\s*=\s*async\s*\(\)\s*=>\s*\{\s*if\s*\(\s*isTesting\.value\s*\)\s*return/.test(hookCode);
    console.log(`[Audit 2.1] handleTestConnection 内置并发锁 (if isTesting.value return): ${hasTestingGuard ? '已具备' : '缺少'}`);

    // 检查 handleSaveModelConfig 是否有内置 isSaving 并发锁
    const hasSavingGuard = /handleSaveModelConfig\s*=\s*async\s*\(\)\s*=>\s*\{\s*if\s*\(\s*isSaving\.value\s*\)\s*return/.test(hookCode);
    console.log(`[Audit 2.2] handleSaveModelConfig 内置并发锁 (if isSaving.value return): ${hasSavingGuard ? '已具备' : '缺少'}`);

    // 检查 handleDeleteModelConfig 是否有 loading 状态与并发锁
    const hasDeletingState = hookCode.includes('isDeleting');
    console.log(`[Audit 2.3] handleDeleteModelConfig 是否具备独立 loading 与并发防护: ${hasDeletingState ? '具备' : '未声明任何 isDeleting 状态'}`);
});

test('Audit 3: Base URL slash and protocol handling', async () => {
    const hookCode = read('js/hooks/useCustomModels.js');

    // 检查是否对末尾多余斜杠做了 strip / replace(/\/+$/, '')
    const hasRstripSlash = /baseUrl\.replace\(|\.rstrip\(|\.replace\(\/\\\/\+\$/i.test(hookCode);
    console.log(`[Audit 3.1] useCustomModels 是否在前端保存前标准化去除末尾斜杠: ${hasRstripSlash ? '有处理' : '未去除末尾斜杠，保留原始输入'}`);

    // 检查协议校验
    assert.match(hookCode, /!baseUrl\.startsWith\('http:\/\/'\)\s*&&\s*!baseUrl\.startsWith\('https:\/\/'\)/);
});

test('Audit 4: Model ID array handling and empty checks', async () => {
    const hookCode = read('js/hooks/useCustomModels.js');

    // 检查 removeModelIdInput 在只有1项时的防空处理
    assert.match(hookCode, /if\s*\(form\.model_ids\.length\s*<=\s*1\)\s*\{\s*form\.model_ids\[0\]\s*=\s*''/);

    // 检查 Model ID 保存时是否校验 validModels.length === 0
    assert.match(hookCode, /validModels\.length\s*===\s*0/);

    // 检查 Model ID 是否做了去重处理 Set(validModels)
    const hasDeduplication = /new Set\s*\(\s*validModels\s*\)/.test(hookCode) || /filter\(\(item,\s*index,\s*self\)/.test(hookCode);
    console.log(`[Audit 4.1] useCustomModels 是否对重复的 Model ID 做了去重: ${hasDeduplication ? '已去重' : '未去重，重复 Model ID 将被存入数据库并在 UI 中重复渲染'}`);
});

test('Audit 5: User switch / login dynamic model reload in useChat.js', async () => {
    const chatCode = read('js/hooks/useChat.js');

    // 检查 watch(() => currentUser.value?.username) 里面是否包含 loadUserCustomModels
    const userWatchMatch = chatCode.match(/watch\(\(\)\s*=>\s*currentUser\.value\?\.username[\s\S]*?\}\);/);
    assert.ok(userWatchMatch, 'useChat 必须包含对 currentUser.value.username 的监听');
    
    const watchBlock = userWatchMatch[0];
    const reloadsCustomModels = watchBlock.includes('loadUserCustomModels');
    console.log(`[Audit 5.1] watch currentUser.username 是否重新拉取自定义模型配置: ${reloadsCustomModels ? '已重新拉取' : '未重新拉取 (新登录用户无法即时获取自己已存的模型配置，存在数据残留)'}`);
});

test('Audit 6: Deleted model synchronization with currentModel', async () => {
    const chatCode = read('js/hooks/useChat.js');

    // 检查 rebuildMergedModelOptions 是否在模型被删除后重置 currentModel
    const rebuildMatch = chatCode.match(/const rebuildMergedModelOptions = \(\) => \{([\s\S]*?)\};/);
    assert.ok(rebuildMatch, 'useChat 必须包含 rebuildMergedModelOptions');
    
    const rebuildBody = rebuildMatch[1];
    const resetsStaleModel = rebuildBody.includes('currentModel.value =') || rebuildBody.includes('switchModel(');
    console.log(`[Audit 6.1] rebuildMergedModelOptions 是否在当前模型失效/被删除时自动回退: ${resetsStaleModel ? '有回退' : '无回退 (当前选中模型被删除后，仍显示该无效模型且发送时会产生404/不可用)'}`);
});
