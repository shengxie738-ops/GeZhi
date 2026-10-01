import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
    normalizeDoi,
    normalizeArxivId,
    normalizeHttpUrl,
    normalizeWorkType,
    createAcademicPaper,
    getPaperIdentityKeys,
    getCanonicalPaperKey,
    mergeAcademicPapers
} from '../js/api/academic/paperModel.js';

test('normalizeDoi: standardizes DOI string, removes prefixes and trailing punctuation', () => {
    assert.equal(normalizeDoi('10.1000/182'), '10.1000/182');
    assert.equal(normalizeDoi('https://doi.org/10.1000/182.'), '10.1000/182');
    assert.equal(normalizeDoi('http://dx.doi.org/10.48550/arXiv.1706.03762/'), '10.48550/arxiv.1706.03762');
    assert.equal(normalizeDoi('doi:10.1000/182,'), '10.1000/182');
    assert.equal(normalizeDoi('  10.1145/3377325.3377498;  '), '10.1145/3377325.3377498');
    assert.equal(normalizeDoi('invalid-doi'), '');
    assert.equal(normalizeDoi(''), '');
    assert.equal(normalizeDoi(null), '');
});

test('normalizeArxivId: supports old and new arXiv formats and strips versions', () => {
    assert.equal(normalizeArxivId('1706.03762v7'), '1706.03762');
    assert.equal(normalizeArxivId('arxiv:1706.03762'), '1706.03762');
    assert.equal(normalizeArxivId('https://arxiv.org/abs/1706.03762v2'), '1706.03762');
    assert.equal(normalizeArxivId('https://arxiv.org/pdf/1706.03762.pdf'), '1706.03762');
    assert.equal(normalizeArxivId('solv-int/9901001v1'), 'solv-int/9901001');
    assert.equal(normalizeArxivId('math.GT/0309136'), 'math/0309136');
    assert.equal(normalizeArxivId('arXiv:math/0001001v3'), 'math/0001001');
    assert.equal(normalizeArxivId('not-arxiv'), '');
    assert.equal(normalizeArxivId(null), '');
});

test('normalizeHttpUrl: unsafe or non-http URLs are discarded', () => {
    assert.equal(normalizeHttpUrl('javascript:alert(1)'), '');
    assert.equal(normalizeHttpUrl('data:text/html,hello'), '');
    assert.equal(normalizeHttpUrl('https://user:pass@example.com/paper'), '');
    assert.equal(normalizeHttpUrl('ftp://ftp.example.com/file.pdf'), '');
    assert.equal(normalizeHttpUrl('/local/path/to/paper'), '');
    assert.equal(normalizeHttpUrl('https://arxiv.org/pdf/1706.03762'), 'https://arxiv.org/pdf/1706.03762');
    assert.equal(normalizeHttpUrl('http://dx.doi.org/10.1000/182'), 'http://dx.doi.org/10.1000/182');
});

test('normalizeWorkType: maps various publisher types to canonical types', () => {
    assert.equal(normalizeWorkType('journal-article'), 'journal-article');
    assert.equal(normalizeWorkType('proceedings-article'), 'conference-paper');
    assert.equal(normalizeWorkType('conference-paper'), 'conference-paper');
    assert.equal(normalizeWorkType('preprint'), 'preprint');
    assert.equal(normalizeWorkType('book'), 'book');
    assert.equal(normalizeWorkType('dissertation'), 'thesis');
    assert.equal(normalizeWorkType('thesis'), 'thesis');
    assert.equal(normalizeWorkType('unknown-type'), 'other');
    assert.equal(normalizeWorkType(''), 'other');
});

test('createAcademicPaper: does not invent fake values for missing fields', () => {
    const paper = createAcademicPaper({
        title: 'Sparse Mixture of Experts'
    }, { key: 'arxiv', label: 'arXiv', recordId: '2101.00001' });

    assert.equal(paper.title, 'Sparse Mixture of Experts');
    assert.deepEqual(paper.authors, []);
    assert.equal(paper.authorsText, '');
    assert.equal(paper.year, null);
    assert.equal(paper.abstract, '');
    assert.equal(paper.abstractSource, '');
    assert.equal(paper.venue, '');
    assert.equal(paper.workType, 'preprint'); // arXiv default workType is preprint
    assert.equal(paper.doi, '');
    assert.equal(paper.arxivId, '');
    assert.equal(paper.pmid, '');
    assert.equal(paper.officialUrl, '');
    assert.equal(paper.openAccessUrl, '');
    assert.equal(paper.isOpenAccess, false);
    assert.equal(paper.citationCount, null);
    assert.equal(paper.citationCountSource, '');
    assert.ok(Array.isArray(paper.identityKeys));
    assert.ok(paper.canonicalKey);
    assert.equal(paper.sources.length, 1);
    assert.equal(paper.sources[0].key, 'arxiv');
});

test('getPaperIdentityKeys: generates identity aliases correctly', () => {
    const paper = {
        title: 'Attention Is All You Need',
        year: 2017,
        doi: '10.48550/arxiv.1706.03762',
        arxivId: '1706.03762',
        pmid: '12345678',
        sources: [{ key: 'openalex', recordId: 'W1' }]
    };
    const keys = getPaperIdentityKeys(paper);
    assert.ok(keys.includes('doi:10.48550/arxiv.1706.03762'));
    assert.ok(keys.includes('arxiv:1706.03762'));
    assert.ok(keys.includes('pmid:12345678'));
    assert.ok(keys.includes('title:attention is all you need|year:2017'));

    const canonical = getCanonicalPaperKey(paper);
    assert.equal(canonical, 'doi:10.48550/arxiv.1706.03762');
});

test('mergeAcademicPapers: records merge when any identity alias overlaps', () => {
    const openalex = createAcademicPaper({
        title: 'Attention Is All You Need',
        year: 2017,
        doi: '10.48550/arXiv.1706.03762',
        arxivId: '1706.03762',
        abstract: 'Short summary'
    }, { key: 'openalex', label: 'OpenAlex', recordId: 'W1' });

    const arxiv = createAcademicPaper({
        title: 'Attention Is All You Need',
        year: 2017,
        arxivId: '1706.03762',
        abstract: 'Verified source abstract from arxiv that is longer than openalex'
    }, { key: 'arxiv', label: 'arXiv', recordId: '1706.03762' });

    const merged = mergeAcademicPapers([openalex, arxiv]);
    assert.equal(merged.length, 1);
    assert.equal(merged[0].doi, '10.48550/arxiv.1706.03762');
    assert.equal(merged[0].arxivId, '1706.03762');
    assert.deepEqual(merged[0].sources.map(item => item.key).sort(), ['arxiv', 'openalex']);
    assert.equal(merged[0].abstract, 'Verified source abstract from arxiv that is longer than openalex');
    assert.equal(merged[0].abstractSource, 'arxiv');
});

test('mergeAcademicPapers: multi-group transitive union merge', () => {
    // Record A links to Record B via DOI, Record B links to Record C via arXiv ID
    const recordA = createAcademicPaper({
        title: 'A Study on AI',
        year: 2023,
        doi: '10.1000/182'
    }, { key: 'crossref', label: 'Crossref', recordId: 'cr-1' });

    const recordB = createAcademicPaper({
        title: 'A Study on AI',
        year: 2023,
        doi: '10.1000/182',
        arxivId: '2301.00001'
    }, { key: 'openalex', label: 'OpenAlex', recordId: 'oa-1' });

    const recordC = createAcademicPaper({
        title: 'A Study on AI - Preprint',
        arxivId: '2301.00001'
    }, { key: 'arxiv', label: 'arXiv', recordId: '2301.00001' });

    const merged = mergeAcademicPapers([recordA, recordB, recordC]);
    assert.equal(merged.length, 1);
    assert.equal(merged[0].doi, '10.1000/182');
    assert.equal(merged[0].arxivId, '2301.00001');
    assert.equal(merged[0].sources.length, 3);
});

test('mergeAcademicPapers: citation count priority OpenAlex -> Europe PMC -> Crossref -> arXiv', () => {
    const openalex = createAcademicPaper({
        title: 'Deep Residual Learning',
        doi: '10.1109/cvpr.2016.90',
        citationCount: 150000
    }, { key: 'openalex', label: 'OpenAlex', recordId: 'W1' });

    const crossref = createAcademicPaper({
        title: 'Deep Residual Learning',
        doi: '10.1109/cvpr.2016.90',
        citationCount: 120000
    }, { key: 'crossref', label: 'Crossref', recordId: 'cr-1' });

    const merged = mergeAcademicPapers([crossref, openalex]);
    assert.equal(merged[0].citationCount, 150000);
    assert.equal(merged[0].citationCountSource, 'openalex');

    // If OpenAlex citation is null, fallback to next priority
    const openalexNull = createAcademicPaper({
        title: 'Another Paper',
        doi: '10.1000/another',
        citationCount: null
    }, { key: 'openalex', label: 'OpenAlex', recordId: 'W2' });

    const europepmc = createAcademicPaper({
        title: 'Another Paper',
        doi: '10.1000/another',
        citationCount: 42
    }, { key: 'europepmc', label: 'Europe PMC', recordId: 'epmc-1' });

    const merged2 = mergeAcademicPapers([openalexNull, europepmc]);
    assert.equal(merged2[0].citationCount, 42);
    assert.equal(merged2[0].citationCountSource, 'europepmc');
});
