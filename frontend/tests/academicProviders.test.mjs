import assert from 'node:assert/strict';
import { test, beforeEach } from 'node:test';

// 准备 Node.js 运行时的全局环境（mock localStorage 与 window）
globalThis.localStorage = {
    getItem: (key) => (key === 'token' ? 'test-token' : null),
    setItem: () => {},
    removeItem: () => {}
};

globalThis.window = {
    dispatchEvent: () => {},
    localStorage: globalThis.localStorage,
    location: { hostname: 'localhost' }
};

import { searchOpenAlex } from '../js/api/academic/providers/openalex.js';
import { searchCrossref } from '../js/api/academic/providers/crossref.js';
import { searchEuropePmc } from '../js/api/academic/providers/europePmc.js';
import { searchArxiv } from '../js/api/academic/providers/arxiv.js';

let capturedFetchCalls = [];
let mockFetchHandler = null;

globalThis.fetch = async (url, options) => {
    capturedFetchCalls.push({ url: String(url), options });
    if (mockFetchHandler) {
        return mockFetchHandler(url, options);
    }
    return {
        ok: true,
        status: 200,
        text: async () => JSON.stringify({ items: [] }),
        json: async () => ({ items: [] })
    };
};

beforeEach(() => {
    capturedFetchCalls = [];
    mockFetchHandler = null;
});

test('searchOpenAlex: queries backend gateway and maps verified metadata correctly', async () => {
    mockFetchHandler = async (url) => {
        assert.ok(url.includes('/academic/openalex/search?query=Attention%20%26%20Transformers&limit=5'));
        return {
            ok: true,
            status: 200,
            text: async () => JSON.stringify({
                source: 'openalex',
                items: [
                    {
                        id: 'https://openalex.org/W2741809807',
                        title: 'Attention Is All You Need',
                        display_name: 'Attention Is All You Need',
                        publication_year: 2017,
                        authorships: [
                            { author: { display_name: 'Ashish Vaswani' } },
                            { author: { display_name: 'Noam Shazeer' } }
                        ],
                        primary_location: {
                            source: { display_name: 'NeurIPS 2017' },
                            landing_page_url: 'https://openalex.org/W2741809807'
                        },
                        type_crossref: 'proceedings-article',
                        doi: 'https://doi.org/10.48550/arxiv.1706.03762',
                        ids: {
                            arxiv: 'https://arxiv.org/abs/1706.03762',
                            openalex: 'https://openalex.org/W2741809807'
                        },
                        open_access: {
                            is_oa: true,
                            oa_url: 'https://arxiv.org/pdf/1706.03762'
                        },
                        best_oa_location: {
                            pdf_url: 'https://arxiv.org/pdf/1706.03762.pdf'
                        },
                        cited_by_count: 98000,
                        abstract_inverted_index: {
                            The: [0],
                            dominant: [1],
                            sequence: [2],
                            transduction: [3],
                            models: [4]
                        }
                    }
                ]
            })
        };
    };

    const papers = await searchOpenAlex('Attention & Transformers', { limit: 5 });
    assert.equal(papers.length, 1);
    const p = papers[0];
    assert.equal(p.title, 'Attention Is All You Need');
    assert.deepEqual(p.authors, ['Ashish Vaswani', 'Noam Shazeer']);
    assert.equal(p.year, 2017);
    assert.equal(p.venue, 'NeurIPS 2017');
    assert.equal(p.workType, 'conference-paper');
    assert.equal(p.doi, '10.48550/arxiv.1706.03762');
    assert.equal(p.arxivId, '1706.03762');
    assert.equal(p.abstract, 'The dominant sequence transduction models');
    assert.equal(p.abstractSource, 'openalex');
    assert.equal(p.officialUrl, 'https://doi.org/10.48550/arxiv.1706.03762');
    assert.equal(p.openAccessUrl, 'https://arxiv.org/pdf/1706.03762.pdf');
    assert.equal(p.isOpenAccess, true);
    assert.equal(p.citationCount, 98000);
    assert.equal(p.sources[0].key, 'openalex');
});

test('searchOpenAlex: rejects on HTTP 429 rate limit', async () => {
    mockFetchHandler = async () => ({
        ok: false,
        status: 429,
        text: async () => JSON.stringify({ detail: 'OpenAlex Rate Limit Exceeded' })
    });

    await assert.rejects(
        () => searchOpenAlex('rate limit test'),
        (err) => {
            assert.equal(err.status, 429);
            return true;
        }
    );
});

test('searchCrossref: queries backend gateway and maps metadata', async () => {
    mockFetchHandler = async (url) => {
        assert.ok(url.includes('/academic/crossref/search?query=Deep%20Learning&limit=10'));
        return {
            ok: true,
            status: 200,
            text: async () => JSON.stringify({
                source: 'crossref',
                items: [
                    {
                        title: ['Deep Learning in Medicine'],
                        author: [
                            { given: 'Yann', family: 'LeCun' },
                            { given: 'Geoffrey', family: 'Hinton' }
                        ],
                        'container-title': ['Nature Medicine'],
                        issued: { 'date-parts': [[2019, 5, 10]] },
                        type: 'journal-article',
                        DOI: '10.1038/s41591-018-0316-z',
                        URL: 'http://dx.doi.org/10.1038/s41591-018-0316-z',
                        abstract: '<jats:p>Deep learning enables computational models...</jats:p>',
                        'is-referenced-by-count': 1250
                    }
                ]
            })
        };
    };

    const papers = await searchCrossref('Deep Learning', { limit: 10 });
    assert.equal(papers.length, 1);
    const p = papers[0];
    assert.equal(p.title, 'Deep Learning in Medicine');
    assert.deepEqual(p.authors, ['Yann LeCun', 'Geoffrey Hinton']);
    assert.equal(p.year, 2019);
    assert.equal(p.venue, 'Nature Medicine');
    assert.equal(p.workType, 'journal-article');
    assert.equal(p.doi, '10.1038/s41591-018-0316-z');
    assert.equal(p.abstract, 'Deep learning enables computational models...');
    assert.equal(p.openAccessUrl, ''); // Crossref 本期不猜测 OA
    assert.equal(p.isOpenAccess, false);
    assert.equal(p.citationCount, 1250);
});

test('searchCrossref: rejects on HTTP 429 rate limit', async () => {
    mockFetchHandler = async () => ({
        ok: false,
        status: 429,
        text: async () => JSON.stringify({ detail: 'Crossref Rate Limit' })
    });

    await assert.rejects(
        () => searchCrossref('stress test'),
        (err) => err.status === 429
    );
});

test('searchEuropePmc: directly calls Europe PMC REST API with proper parameters and mapping', async () => {
    mockFetchHandler = async (url) => {
        assert.ok(url.startsWith('https://www.ebi.ac.uk/europepmc/webservices/rest/search?'));
        const parsed = new URL(url);
        assert.equal(parsed.searchParams.get('query'), 'p53 crispr');
        assert.equal(parsed.searchParams.get('format'), 'json');
        assert.equal(parsed.searchParams.get('pageSize'), '8');
        assert.equal(parsed.searchParams.get('resultType'), 'core');

        const payload = {
            resultList: {
                result: [
                    {
                        id: '31234567',
                        source: 'MED',
                        pmid: '31234567',
                        doi: '10.1016/j.cell.2019.05.001',
                        title: 'Genome-wide CRISPR screen identifies p53 regulators',
                        authorList: {
                            author: [
                                { fullName: 'Alice Wong' },
                                { fullName: 'Bob Smith' }
                            ]
                        },
                        journalTitle: 'Cell',
                        pubYear: '2019',
                        pubTypeList: { pubType: ['Journal Article'] },
                        abstractText: 'Here we perform a pooled CRISPR knockout screen...',
                        isOpenAccess: 'Y',
                        fullTextUrlList: {
                            fullTextUrl: [
                                { availabilityCode: 'OA', documentStyle: 'pdf', url: 'https://europepmc.org/backend/ptpmcrender.fcgi?accid=PMC67890&blobtype=pdf' },
                                { availabilityCode: 'OA', documentStyle: 'html', url: 'https://europepmc.org/articles/PMC67890' }
                            ]
                        },
                        citedByCount: 88
                    }
                ]
            }
        };

        return {
            ok: true,
            status: 200,
            text: async () => JSON.stringify(payload),
            json: async () => payload
        };
    };

    const papers = await searchEuropePmc('p53 crispr', { limit: 8 });
    assert.equal(papers.length, 1);
    const p = papers[0];
    assert.equal(p.title, 'Genome-wide CRISPR screen identifies p53 regulators');
    assert.deepEqual(p.authors, ['Alice Wong', 'Bob Smith']);
    assert.equal(p.year, 2019);
    assert.equal(p.pmid, '31234567');
    assert.equal(p.doi, '10.1016/j.cell.2019.05.001');
    assert.equal(p.venue, 'Cell');
    assert.equal(p.workType, 'journal-article');
    assert.equal(p.abstract, 'Here we perform a pooled CRISPR knockout screen...');
    assert.equal(p.isOpenAccess, true);
    // 优先选择 HTML 全文
    assert.equal(p.openAccessUrl, 'https://europepmc.org/articles/PMC67890');
    assert.equal(p.citationCount, 88);
    assert.equal(p.sources[0].key, 'europepmc');
});

test('searchEuropePmc: rejects on HTTP error', async () => {
    mockFetchHandler = async () => ({
        ok: false,
        status: 503,
        text: async () => 'Service Unavailable'
    });

    await assert.rejects(
        () => searchEuropePmc('cancer research'),
        /Europe PMC HTTP 503/
    );
});

test('searchArxiv: queries backend gateway and maps preprint metadata', async () => {
    mockFetchHandler = async (url) => {
        assert.ok(url.includes('/academic/arxiv/search?query=transformer&limit=6'));
        return {
            ok: true,
            status: 200,
            text: async () => JSON.stringify({
                source: 'arxiv',
                items: [
                    {
                        sourceId: '1706.03762',
                        arxivId: '1706.03762',
                        title: 'Attention Is All You Need',
                        authors: ['Ashish Vaswani', 'Noam Shazeer'],
                        year: 2017,
                        venue: 'arXiv',
                        abstract: 'The dominant sequence transduction models...',
                        doi: '10.48550/arXiv.1706.03762',
                        officialUrl: 'https://arxiv.org/abs/1706.03762',
                        openAccessUrl: 'https://arxiv.org/pdf/1706.03762.pdf',
                        isOpenAccess: true
                    }
                ]
            })
        };
    };

    const papers = await searchArxiv('transformer', { limit: 6 });
    assert.equal(papers.length, 1);
    const p = papers[0];
    assert.equal(p.title, 'Attention Is All You Need');
    assert.equal(p.arxivId, '1706.03762');
    assert.equal(p.doi, '10.48550/arxiv.1706.03762');
    assert.equal(p.workType, 'preprint');
    assert.equal(p.officialUrl, 'https://arxiv.org/abs/1706.03762');
    assert.equal(p.openAccessUrl, 'https://arxiv.org/pdf/1706.03762.pdf');
    assert.equal(p.isOpenAccess, true);
    assert.equal(p.sources[0].key, 'arxiv');
    assert.equal(p.sources[0].recordId, '1706.03762');
});

test('searchArxiv: rejects on HTTP 429 rate limit', async () => {
    mockFetchHandler = async () => ({
        ok: false,
        status: 429,
        text: async () => JSON.stringify({ detail: 'arXiv Rate Limit Exceeded' })
    });

    await assert.rejects(
        () => searchArxiv('neural network'),
        (err) => err.status === 429
    );
});
