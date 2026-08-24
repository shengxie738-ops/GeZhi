import assert from 'node:assert/strict';
import { test } from 'node:test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

test('Plugin Marketplace: index.html should contain all UI elements and modals', () => {
    const htmlPath = path.resolve(__dirname, '../index.html');
    const htmlContent = fs.readFileSync(htmlPath, 'utf8');

    // 侧栏插件市场入口
    assert.ok(htmlContent.includes('openPluginMarket'), '侧栏应绑定 openPluginMarket');
    assert.ok(htmlContent.includes('插件市场'), '侧栏应有插件市场文本');

    // 插件市场大模态面板
    assert.ok(htmlContent.includes('showPluginMarketModal'), '应挂载 showPluginMarketModal');
    assert.ok(htmlContent.includes('filteredPlugins'), '应循环 filteredPlugins 插件网格');
    assert.ok(htmlContent.includes('openPluginDetail'), '应支持 openPluginDetail 打开插件详情');

    // 插件详情面板
    assert.ok(htmlContent.includes('selectedPluginDetail'), '应挂载 selectedPluginDetail 详情面板');
    assert.ok(htmlContent.includes('核心能力特性'), '详情应包含能力特性');

    // 即时论文检索交互抽屉
    assert.ok(htmlContent.includes('activeSearchPlugin'), '应挂载 activeSearchPlugin 在线检索抽屉');
    assert.ok(htmlContent.includes('executePaperSearch'), '应有 executePaperSearch 检索执行方法');
    assert.ok(htmlContent.includes('copyBibtexCitation'), '应有 copyBibtexCitation 复制BibTeX');
    assert.ok(htmlContent.includes('insertPaperToChat'), '应有 insertPaperToChat 引入对话');

    // 输入框左侧 + 号 Codex 扩展菜单与胶囊
    assert.ok(htmlContent.includes('toggleAddMenu'), '输入框 + 号应绑定 toggleAddMenu');
    assert.ok(htmlContent.includes('showAddMenu'), '应有 showAddMenu 悬浮菜单');
    assert.ok(htmlContent.includes('activeInputPlugins'), '应渲染 activeInputPlugins 插件胶囊');
    assert.ok(htmlContent.includes('insertPluginToInput'), '菜单中应能点击 insertPluginToInput 插入插件');
});

test('Plugin Marketplace: main.js should import and export usePlugins states', () => {
    const mainJsPath = path.resolve(__dirname, '../js/main.js');
    const mainContent = fs.readFileSync(mainJsPath, 'utf8');

    assert.ok(mainContent.includes("import { usePlugins } from './hooks/usePlugins.js'"), 'main.js 应导入 usePlugins');
    assert.ok(mainContent.includes('usePlugins(auth.currentUser'), 'main.js 应实例化 usePlugins');
    assert.ok(mainContent.includes('openPluginMarket: pluginsState.openPluginMarket'), 'main.js 应导出 openPluginMarket');
    assert.ok(mainContent.includes('openPluginDetail: pluginsState.openPluginDetail'), 'main.js 应导出 openPluginDetail');
    assert.ok(mainContent.includes('insertPluginToInput: pluginsState.insertPluginToInput'), 'main.js 应导出 insertPluginToInput');
});
