import assert from 'node:assert/strict';
import { test } from 'node:test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
    ACADEMIC_PLUGINS,
    PLUGIN_CATEGORIES,
    getPluginById,
    getDefaultInstalledPluginIds,
    resolvePaperSourceKeys,
    readInstalledPluginIdsSafe
} from '../js/config/academicPlugins.js';
import { formatBibtex, normalizePaperItem } from '../js/api/academicSearch.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

test('academicPlugins: metadata registry should have required academic plugins', () => {
    assert.ok(Array.isArray(ACADEMIC_PLUGINS), 'ACADEMIC_PLUGINS 应为数组');
    assert.ok(ACADEMIC_PLUGINS.length >= 7, '应注册至少 7 款插件');

    const arxivPlugin = getPluginById('plugin_arxiv');
    assert.ok(arxivPlugin, '应包含 arXiv 插件');
    assert.equal(arxivPlugin.name, 'arXiv Paper Hunter');
    assert.equal(arxivPlugin.category, 'paper_search');
    assert.ok(arxivPlugin.features.length > 0, '应包含功能特性列表');
    assert.ok(arxivPlugin.detailDescription, '应包含详细描述');

    const openalexPlugin = getPluginById('plugin_openalex');
    assert.ok(openalexPlugin, '应包含 OpenAlex 插件');
    assert.equal(openalexPlugin.category, 'paper_search');

    const crossrefPlugin = getPluginById('plugin_crossref');
    assert.ok(crossrefPlugin, '应包含 Crossref 插件');

    const defaults = getDefaultInstalledPluginIds();
    assert.ok(defaults.includes('plugin_arxiv'), 'arXiv 默认应在已安装列表中');
});

test('academicPlugins: every marketplace plugin should provide an existing generated image icon', () => {
    for (const plugin of ACADEMIC_PLUGINS) {
        assert.match(
            plugin.iconImage,
            /^\.\/assets\/plugin-icons\/[a-z0-9-]+\.png$/,
            `${plugin.id} 应声明插件市场位图图标`
        );

        const iconPath = path.resolve(__dirname, '..', plugin.iconImage.slice(2));
        assert.ok(fs.existsSync(iconPath), `${plugin.id} 的图标文件应存在: ${iconPath}`);
    }
});

test('academicSearch: normalizePaperItem and formatBibtex should work correctly', () => {
    const raw = {
        title: 'Attention Is All You Need',
        authors: ['Ashish Vaswani', 'Noam Shazeer'],
        year: 2017,
        venue: 'NeurIPS',
        pdfUrl: 'https://arxiv.org/pdf/1706.03762.pdf',
        doi: '10.48550/arXiv.1706.03762',
        abstract: 'The dominant sequence transduction models are based on complex recurrent or convolutional neural networks...'
    };

    const normalized = normalizePaperItem(raw, 'arXiv');
    assert.equal(normalized.title, 'Attention Is All You Need');
    assert.equal(normalized.source, 'arXiv');
    assert.equal(normalized.authorsText, 'Ashish Vaswani, Noam Shazeer');

    const bibtex = formatBibtex(normalized);
    assert.match(bibtex, /@article\{/);
    assert.match(bibtex, /title\s*=\s*\{Attention Is All You Need\}/);
    assert.match(bibtex, /year\s*=\s*\{2017\}/);
});

test('academicPlugins: 4 real academic sources have unique searchSourceKey and canSearchLive', () => {
    const livePlugins = ACADEMIC_PLUGINS.filter(p => p.canSearchLive);
    assert.equal(livePlugins.length, 4, '应正好有 4 个可实时检索的学术插件');

    const keys = livePlugins.map(p => p.searchSourceKey);
    const uniqueKeys = new Set(keys);
    assert.equal(uniqueKeys.size, 4, '4 个真实来源的 searchSourceKey 必须互不相同');
    assert.ok(uniqueKeys.has('arxiv'), '应包含 arxiv');
    assert.ok(uniqueKeys.has('openalex'), '应包含 openalex');
    assert.ok(uniqueKeys.has('crossref'), '应包含 crossref');
    assert.ok(uniqueKeys.has('europepmc'), '应包含 europepmc');

    // Non-live plugins must not have canSearchLive=true
    const nonLivePlugins = ACADEMIC_PLUGINS.filter(p => !p.canSearchLive);
    for (const plugin of nonLivePlugins) {
        assert.equal(plugin.canSearchLive, false, `${plugin.id} 不可实时搜索`);
    }
});

test('academicPlugins: promotional copy calibrated without exaggerated unverified claims', () => {
    const forbiddenPhrases = ['毫秒级', '全文挖掘', '智能提取', '2.5 亿+'];
    const paperPlugins = ACADEMIC_PLUGINS.filter(p => p.category === 'paper_search');

    for (const plugin of paperPlugins) {
        const textToScan = [
            plugin.tagline,
            plugin.detailDescription,
            ...(plugin.features || [])
        ].join(' ');

        for (const phrase of forbiddenPhrases) {
            assert.ok(
                !textToScan.includes(phrase),
                `插件 ${plugin.id} 的文案不应包含未经核实的夸大宣传词汇「${phrase}」`
            );
        }
    }
});

test('academicPlugins: resolvePaperSourceKeys strictly avoids implicit fallback to defaults', () => {
    const arxiv = getPluginById('plugin_arxiv');
    const openalex = getPluginById('plugin_openalex');
    const crossref = getPluginById('plugin_crossref');
    const zotero = getPluginById('plugin_zotero'); // canSearchLive: false

    // 1. Explicit live plugin passed
    assert.deepEqual(
        resolvePaperSourceKeys(arxiv, [], []),
        ['arxiv']
    );

    // 2. Explicit non-live plugin passed -> fall through to mounted/installed
    assert.deepEqual(
        resolvePaperSourceKeys(zotero, [arxiv, openalex], [crossref]),
        ['arxiv', 'openalex']
    );

    // 3. No plugin passed, mounted live plugins exist -> return mounted sources
    assert.deepEqual(
        resolvePaperSourceKeys(null, [openalex, crossref, zotero], [arxiv]),
        ['openalex', 'crossref']
    );

    // 4. No mounted live plugins, installed plugins exist -> return installed sources
    assert.deepEqual(
        resolvePaperSourceKeys(null, [], [arxiv, crossref]),
        ['arxiv', 'crossref']
    );

    // 5. Neither mounted nor installed has live sources -> returns empty array [], NEVER fallback to default
    assert.deepEqual(
        resolvePaperSourceKeys(null, [], []),
        [],
        '全部来源清空时必须返回空数组，绝不能隐式回退到默认插件'
    );
    assert.deepEqual(
        resolvePaperSourceKeys(null, [zotero], [zotero]),
        [],
        '仅有非检索类插件时也必须返回空数组'
    );
});

test('academicPlugins: user saved empty array in storage is preserved and does not revert to defaults', () => {
    // When storage key does not exist (null), fallback to default
    const mockStorageMissing = { getItem: () => null };
    assert.deepEqual(
        readInstalledPluginIdsSafe(mockStorageMissing, 'test_key'),
        getDefaultInstalledPluginIds()
    );

    // When storage explicitly stores empty array '[]', it must stay []
    const mockStorageEmpty = { getItem: () => '[]' };
    assert.deepEqual(
        readInstalledPluginIdsSafe(mockStorageEmpty, 'test_key'),
        [],
        '用户清空后保存的空数组必须被原样保留，不得重置为默认'
    );

    // When storage stores user customized list, it is parsed
    const mockStorageCustom = { getItem: () => '["plugin_crossref"]' };
    assert.deepEqual(
        readInstalledPluginIdsSafe(mockStorageCustom, 'test_key'),
        ['plugin_crossref']
    );
});
