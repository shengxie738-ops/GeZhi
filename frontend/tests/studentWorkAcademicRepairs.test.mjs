// Production providers/model/detail, finite synthetic transport only. No browser/server.
import test from 'node:test';
import assert from 'node:assert/strict';
import { Vue, compiled, mount, settle, textOf } from './fixtures/workPresentationRenderer.mjs';
import Detail from '../js/components/WorkPaperDetail.js';
import { searchAcademicPapers, clearAcademicCache } from '../js/api/academic/aggregate.js';
import { searchCrossref } from '../js/api/academic/providers/crossref.js';
import { searchOpenAlex } from '../js/api/academic/providers/openalex.js';
import { searchArxiv } from '../js/api/academic/providers/arxiv.js';
import { searchEuropePmc } from '../js/api/academic/providers/europePmc.js';
import { createAcademicPaper, mergeAcademicPapers } from '../js/api/academic/paperModel.js';
import { formatBibtex, formatRis } from '../js/api/academic/citations.js';

globalThis.localStorage = { getItem: key => key === 'token' ? 'offline-academic-owner' : null };
const doi = '10.1234/source(abc)';
const rawOpenalex = { id: 'https://openalex.org/W123456789', display_name: 'An exact DOI record', doi, publication_year: 2024 };
const json = (items, status = 200) => new Response(JSON.stringify(status === 200 ? { items } : { detail: { source: 'crossref', code: 'not_found', message: 'Synthetic missing DOI' } }), { status });
function transport(handler) {
    clearAcademicCache();
    const calls = [];
    globalThis.fetch = async (raw, options = {}) => {
        const url = new URL(raw);
        assert.match(url.pathname, /^\/api\/academic\/(crossref|openalex)\/search$/);
        assert.equal(options.method, 'GET');
        assert.ok(calls.length < 8, 'Finite synthetic request budget');
        calls.push(url);
        return handler(url);
    };
    return calls;
}

test('student academic repair: OpenAlex-only DOI uses exact gateway lookup', async () => {
    const calls = transport(() => json([rawOpenalex]));
    const result = await searchAcademicPapers(doi, { sourceKeys: ['openalex'] });
    assert.equal(result.status, 'success');
    assert.equal(result.items[0].doi, doi);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].searchParams.get('query'), doi);
});

test('student academic repair: Crossref failure retains selected OpenAlex DOI results', async () => {
    const calls = transport(url => url.pathname.includes('crossref') ? json([], 404) : json([rawOpenalex]));
    const result = await searchAcademicPapers(doi, { sourceKeys: ['crossref', 'openalex', 'arxiv'] });
    assert.equal(result.status, 'partial');
    assert.equal(result.items.length, 1);
    assert.equal(result.sourceStatuses.find(row => row.key === 'crossref').errorCode, 'not_found');
    assert.equal(result.sourceStatuses.find(row => row.key === 'arxiv').status, 'skipped');
    assert.equal(calls.length, 2);
});

test('student academic repair: DOI with no capable selected source does not fetch', async () => {
    const calls = transport(() => assert.fail('Unsupported DOI source must not fetch'));
    const result = await searchAcademicPapers(doi, { sourceKeys: ['arxiv'] });
    assert.equal(result.status, 'error');
    assert.match(result.sourceStatuses[0].error, /Crossref.*OpenAlex/);
    assert.equal(calls.length, 0);
});

test('student academic repair: Crossref chapter preserves publisher and exports chapter semantics', async () => {
    transport(() => json([{ title: ['Chapter One'], type: 'book-chapter', DOI: doi, 'container-title': ['Collected Chapters'], publisher: 'Actual Publisher' }]));
    const [chapter] = await searchCrossref('chapter');
    assert.equal(chapter.workType, 'book-chapter');
    assert.equal(chapter.publisher, 'Actual Publisher');
    assert.equal(chapter.venue, 'Collected Chapters');
    const bib = formatBibtex(chapter), ris = formatRis(chapter);
    assert.match(bib, /^@incollection\{/);
    assert.match(bib, /booktitle = \{Collected Chapters\}/);
    assert.match(bib, /publisher = \{Actual Publisher\}/);
    assert.match(ris, /^TY  - CHAP/m);
    assert.match(ris, /^T2  - Collected Chapters$/m);
    assert.match(ris, /^PB  - Actual Publisher$/m);
});

test('student academic repair: absent book publisher is never inferred from container title', () => {
    const book = createAcademicPaper({ title: 'Book', workType: 'book', venue: 'A Container Title' });
    assert.doesNotMatch(formatBibtex(book), /publisher =/);
    assert.doesNotMatch(formatRis(book), /^PB  -/m);
});

test('student academic repair: publisher and chapter type survive merging and snapshot JSON', () => {
    const chapter = createAcademicPaper({ title: 'Chapter', workType: 'book-chapter', doi, publisher: 'Actual Publisher', venue: 'Collected Chapters' }, { key: 'crossref', recordId: doi });
    const other = createAcademicPaper({ title: 'Chapter', workType: 'book', doi }, { key: 'openalex', recordId: 'W1' });
    for (const records of [[chapter, other], [other, chapter]]) {
        const restored = JSON.parse(JSON.stringify(mergeAcademicPapers(records)[0]));
        assert.equal(restored.workType, 'book-chapter');
        assert.equal(restored.publisher, 'Actual Publisher');
        assert.equal(restored.fieldProvenance.publisher.sourceKey, 'crossref');
    }
});

test('student academic repair: a published chapter outranks its matching preprint', () => {
    const chapter = createAcademicPaper({ title: 'Published Chapter', workType: 'book-chapter', doi, arxivId: '1706.03762', publisher: 'Actual Publisher', venue: 'Collected Chapters' }, { key: 'crossref', recordId: doi });
    const preprint = createAcademicPaper({ title: 'Earlier Preprint', workType: 'preprint', doi, arxivId: '1706.03762' }, { key: 'arxiv', recordId: '1706.03762' });
    for (const records of [[chapter, preprint], [preprint, chapter]]) {
        const merged = mergeAcademicPapers(records)[0];
        assert.equal(merged.workType, 'book-chapter');
        assert.match(formatBibtex(merged), /^@incollection\{/);
        assert.match(formatBibtex(merged), /publisher = \{Actual Publisher\}/);
        assert.match(formatRis(merged), /^TY  - CHAP/m);
    }
});

test('student academic repair: whole books export only their explicit publisher', async () => {
    transport(() => json([{ title: ['A Whole Book'], type: 'book', DOI: doi, 'container-title': ['Series Title'], publisher: 'Actual Publisher' }]));
    const [book] = await searchCrossref('book');
    assert.match(formatBibtex(book), /^@book\{/);
    assert.match(formatBibtex(book), /publisher = \{Actual Publisher\}/);
    assert.match(formatRis(book), /^PB  - Actual Publisher$/m);
    assert.doesNotMatch(formatBibtex(book), /publisher = \{Series Title\}/);
});

test('student academic repair: Europe PMC preserves the shared book-chapter type', async () => {
    globalThis.fetch = async raw => {
        assert.ok(String(raw).startsWith('https://www.ebi.ac.uk/europepmc/webservices/rest/search?'));
        return new Response(JSON.stringify({ resultList: { result: [{ title: 'Source chapter', source: 'MED', id: '123', pubTypeList: { pubType: ['Book Chapter'] } }] } }));
    };
    const [chapter] = await searchEuropePmc('chapter');
    assert.equal(chapter.workType, 'book-chapter');
    assert.match(formatBibtex(chapter), /^@incollection\{/);
});

test('student academic repair: name-only corporate authors remain literal in BibTeX', async () => {
    transport(() => json([{ title: ['Consortium study'], DOI: doi, author: [{ name: 'Example Research Consortium' }, { given: 'Jane', family: 'Smith', name: 'Unused fallback' }] }]));
    const [paper] = await searchCrossref('consortium');
    assert.deepEqual(paper.authors, ['Example Research Consortium', 'Jane Smith']);
    assert.deepEqual(paper.literalAuthors, ['Example Research Consortium']);
    assert.match(formatBibtex(paper), /author = \{\{Example Research Consortium\} and Jane Smith\}/);
    assert.match(formatRis(paper), /^AU  - Example Research Consortium$/m);
    const h = await mount(Detail, { paper });
    try { assert.match(textOf(h.root), /Example Research Consortium, Jane Smith/); }
    finally { h.close(); }
});

test('student academic repair: literal-author metadata follows the chosen merged authors', () => {
    const corporate = createAcademicPaper({ title: 'Study', doi, authors: ['Consortium'], literalAuthors: ['Consortium'] }, { key: 'crossref', recordId: doi });
    const longer = createAcademicPaper({ title: 'Study', doi, authors: ['Jane Smith', 'John Doe'] }, { key: 'openalex', recordId: 'W1' });
    const merged = mergeAcademicPapers([corporate, longer])[0];
    assert.deepEqual(merged.authors, ['Jane Smith', 'John Doe']);
    assert.deepEqual(merged.literalAuthors, []);
    assert.doesNotMatch(formatBibtex(merged), /Consortium/);
    const retained = JSON.parse(JSON.stringify(mergeAcademicPapers([corporate, createAcademicPaper({ title: 'Study', doi }, { key: 'arxiv', recordId: '1706.03762' })])[0]));
    assert.deepEqual(retained.literalAuthors, ['Consortium']);
    assert.match(formatBibtex(retained), /author = \{\{Consortium\}\}/);
});

test('student academic repair: all real providers expose record IDs in detail panes', async () => {
    const cases = [
        [searchCrossref, { title: ['Crossref record'], DOI: doi }, doi],
        [searchOpenAlex, rawOpenalex, 'https://openalex.org/W123456789'],
        [searchArxiv, { title: 'arXiv record', sourceId: '1706.03762', arxivId: '1706.03762', officialUrl: 'https://arxiv.org/abs/1706.03762' }, '1706.03762'],
        [searchEuropePmc, { title: 'PMC record', source: 'MED', id: '123' }, 'MED:123']
    ];
    for (const [search, record, expected] of cases) {
        globalThis.fetch = async raw => {
            const url = new URL(raw);
            assert.ok(/^\/api\/academic\/(crossref|openalex|arxiv)\/search$/.test(url.pathname) || url.origin === 'https://www.ebi.ac.uk' && url.pathname === '/europepmc/webservices/rest/search');
            return new Response(JSON.stringify(search === searchEuropePmc ? { resultList: { result: [record] } } : { items: [record] }));
        };
        const [paper] = await search('record');
        const h = await mount(Detail, { paper });
        try { assert.ok(textOf(h.root).includes(expected), expected); }
        finally { h.close(); }
    }
});

test('student academic repair: repeated-source badge updates keep distinct native keys', async () => {
    const selected = Vue.ref({ title: 'First', sources: [
        { key: 'arxiv', label: 'arXiv One', recordId: '1706.03762' },
        { key: 'arxiv', label: 'arXiv Two', recordId: '2401.00001' }
    ] });
    const h = await mount({ components: { WorkPaperDetail: compiled(Detail) },
        template: '<WorkPaperDetail :paper="paper" />', setup: () => ({ paper: selected }) });
    try {
        selected.value = { title: 'Second', sources: [
            { key: 'crossref', label: 'Crossref One', recordId: '10.1234/one' },
            { key: 'crossref', label: 'Crossref Two', recordId: '10.1234/two' }
        ] };
        await settle();
        assert.match(textOf(h.root), /Crossref One/);
        assert.match(textOf(h.root), /Crossref Two/);
        assert.doesNotMatch(textOf(h.root), /arXiv One/);
    } finally { h.close(); } // The real renderer also asserts there were no duplicate-key warnings.
});

test('student academic repair: detail shows normalized recordId and legacy rawId', async () => {
    transport(() => json([rawOpenalex]));
    const [paper] = await searchOpenAlex('record');
    paper.sources.push({ key: 'openalex', label: 'OpenAlex', recordId: 'https://openalex.org/W987654321' });
    for (const presentation of ['pane', 'modal']) {
        const h = await mount(Detail, { paper: JSON.parse(JSON.stringify(paper)), presentation });
        try {
            assert.match(textOf(h.root), /W123456789/);
            assert.match(textOf(h.root), /W987654321/);
        } finally { h.close(); }
    }
    const h = await mount(Detail, { paper: { title: 'Legacy', sources: [{ key: 'legacy', rawId: 'legacy-id' }] } });
    try { assert.match(textOf(h.root), /legacy-id/); }
    finally { h.close(); }
});
