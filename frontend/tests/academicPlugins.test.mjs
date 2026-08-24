import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
    ACADEMIC_PLUGINS,
    PLUGIN_CATEGORIES,
    getPluginById,
    getDefaultInstalledPluginIds
} from '../js/config/academicPlugins.js';
import { formatBibtex, normalizePaperItem } from '../js/api/academicSearch.js';

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
