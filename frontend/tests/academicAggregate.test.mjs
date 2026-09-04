import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
    searchAcademicPapers,
    ACADEMIC_PROVIDERS,
    clearAcademicCache
} from '../js/api/academic/aggregate.js';
import { createAcademicPaper } from '../js/api/academic/paperModel.js';

test('academicAggregate: registry exports 4 verified academic providers', () => {
    assert.ok(ACADEMIC_PROVIDERS.openalex, 'OpenAlex provider should be defined');
    assert.ok(ACADEMIC_PROVIDERS.crossref, 'Crossref provider should be defined');
    assert.ok(ACADEMIC_PROVIDERS.arxiv, 'arXiv provider should be defined');
    assert.ok(ACADEMIC_PROVIDERS.europepmc, 'Europe PMC provider should be defined');
    assert.equal(typeof ACADEMIC_PROVIDERS.openalex.search, 'function');
    assert.equal(typeof ACADEMIC_PROVIDERS.crossref.search, 'function');
    assert.equal(typeof ACADEMIC_PROVIDERS.arxiv.search, 'function');
    assert.equal(typeof ACADEMIC_PROVIDERS.europepmc.search, 'function');
    assert.ok(
        ACADEMIC_PROVIDERS.arxiv.timeoutMs >= 20000,
        'arXiv 官方接口存在较高延迟，应使用独立的长超时窗口'
    );
});

test('academicAggregate: initial searching events are emitted before provider resolves', async () => {
    clearAcademicCache();
    const events = [];
    const mockProviders = {
        source_a: {
            label: 'Source A',
            search: async () => {
                // When search starts, searching event should already have been recorded
                assert.equal(events.length, 2);
                assert.equal(events[0].status, 'searching');
                assert.equal(events[1].status, 'searching');
                return [createAcademicPaper({ title: 'Paper 1', year: 2024 }, { key: 'source_a', label: 'Source A' })];
            }
        },
        source_b: {
            label: 'Source B',
            search: async () => []
        }
    };

    const res = await searchAcademicPapers('test', {
        sourceKeys: ['source_a', 'source_b'],
        providers: mockProviders,
        onSourceStatus: (ev) => events.push({ ...ev })
    });

    assert.equal(res.status, 'success');
    assert.equal(events[0].key, 'source_a');
    assert.equal(events[0].status, 'searching');
    assert.equal(events[1].key, 'source_b');
    assert.equal(events[1].status, 'searching');
});

test('academicAggregate: fast source emits success before slow source resolves', async () => {
    clearAcademicCache();
    const events = [];
    let resolveSlow;
    const slowPromise = new Promise(r => { resolveSlow = r; });

    const mockProviders = {
        fast: {
            label: 'Fast Source',
            search: async () => [
                createAcademicPaper({ title: 'Fast Paper', year: 2024 }, { key: 'fast', label: 'Fast Source' })
            ]
        },
        slow: {
            label: 'Slow Source',
            search: async () => {
                await slowPromise;
                return [createAcademicPaper({ title: 'Slow Paper', year: 2023 }, { key: 'slow', label: 'Slow Source' })];
            }
        }
    };

    const searchPromise = searchAcademicPapers('incremental test', {
        sourceKeys: ['fast', 'slow'],
        providers: mockProviders,
        onSourceStatus: (ev) => events.push({ ...ev })
    });

    // Wait a tick for fast source to resolve
    await new Promise(r => setTimeout(r, 50));

    // Fast should have emitted searching and then success
    const fastSuccess = events.find(e => e.key === 'fast' && e.status === 'success');
    assert.ok(fastSuccess, 'Fast source should have emitted success event before slow source');
    const slowSuccess = events.find(e => e.key === 'slow' && e.status === 'success');
    assert.equal(slowSuccess, undefined, 'Slow source should not have resolved yet');

    // Unblock slow source
    resolveSlow();
    const res = await searchPromise;
    assert.equal(res.status, 'success');
    assert.equal(res.items.length, 2);
});

test('academicAggregate: status is partial when one succeeds and one fails', async () => {
    clearAcademicCache();
    const mockProviders = {
        ok_source: {
            label: 'OK Source',
            search: async () => [
                createAcademicPaper({ title: 'Paper OK', year: 2024 }, { key: 'ok_source', label: 'OK Source' })
            ]
        },
        fail_source: {
            label: 'Fail Source',
            search: async () => {
                throw new Error('Network timeout');
            }
        }
    };

    const res = await searchAcademicPapers('partial test', {
        sourceKeys: ['ok_source', 'fail_source'],
        providers: mockProviders
    });

    assert.equal(res.status, 'partial');
    assert.equal(res.items.length, 1);
    assert.equal(res.sourceStatuses.find(s => s.key === 'ok_source').status, 'success');
    assert.equal(res.sourceStatuses.find(s => s.key === 'fail_source').status, 'error');
    assert.equal(res.sourceStatuses.find(s => s.key === 'fail_source').error, 'Network timeout');
});

test('academicAggregate: status is partial with empty items when one succeeds with 0 items and one fails', async () => {
    clearAcademicCache();
    const mockProviders = {
        empty_ok: {
            label: 'Empty OK Source',
            search: async () => []
        },
        fail_source: {
            label: 'Fail Source',
            search: async () => {
                throw new Error('500 Internal Error');
            }
        }
    };

    const res = await searchAcademicPapers('partial empty test', {
        sourceKeys: ['empty_ok', 'fail_source'],
        providers: mockProviders
    });

    assert.equal(res.status, 'partial');
    assert.equal(res.items.length, 0);
    assert.equal(res.totalAfterMerge, 0);
});

test('academicAggregate: status is empty when all sources succeed but return no items', async () => {
    clearAcademicCache();
    const mockProviders = {
        s1: { label: 'S1', search: async () => [] },
        s2: { label: 'S2', search: async () => [] }
    };

    const res = await searchAcademicPapers('empty test', {
        sourceKeys: ['s1', 's2'],
        providers: mockProviders
    });

    assert.equal(res.status, 'empty');
    assert.equal(res.items.length, 0);
    assert.equal(res.totalAfterMerge, 0);
});

test('academicAggregate: status is error when all sources fail', async () => {
    clearAcademicCache();
    const mockProviders = {
        s1: {
            label: 'S1',
            search: async () => {
                throw new Error('S1 down');
            }
        },
        s2: {
            label: 'S2',
            search: async () => {
                throw new Error('S2 down');
            }
        }
    };

    const res = await searchAcademicPapers('all fail test', {
        sourceKeys: ['s1', 's2'],
        providers: mockProviders
    });

    assert.equal(res.status, 'error');
    assert.equal(res.items.length, 0);
    assert.equal(res.sourceStatuses.every(s => s.status === 'error'), true);
});

test('academicAggregate: preserves actionable upstream timeout diagnostics', async () => {
    clearAcademicCache();
    const diagnostic = 'arXiv 上游请求超时（export.arxiv.org）；请检查服务器到该官方接口的网络连通性';
    const res = await searchAcademicPapers('timeout diagnostic', {
        sourceKeys: ['arxiv'],
        providers: {
            arxiv: {
                label: 'arXiv',
                timeoutMs: 25000,
                search: async () => { throw new Error(diagnostic); }
            }
        }
    });

    assert.equal(res.status, 'error');
    assert.equal(res.sourceStatuses[0].error, diagnostic);
});

test('academicAggregate: unknown source keys are recorded as error', async () => {
    clearAcademicCache();
    const mockProviders = {
        known: {
            label: 'Known',
            search: async () => [
                createAcademicPaper({ title: 'Known Paper', year: 2024 }, { key: 'known', label: 'Known' })
            ]
        }
    };

    const res = await searchAcademicPapers('unknown source test', {
        sourceKeys: ['known', 'unknown_key'],
        providers: mockProviders
    });

    assert.equal(res.status, 'partial');
    const unknownStatus = res.sourceStatuses.find(s => s.key === 'unknown_key');
    assert.ok(unknownStatus);
    assert.equal(unknownStatus.status, 'error');
    assert.ok(unknownStatus.error.includes('未知来源') || unknownStatus.error.includes('unknown_key'));
});

test('academicAggregate: abort signal cancels search and re-throws AbortError', async () => {
    clearAcademicCache();
    const controller = new AbortController();

    const mockProviders = {
        hanging: {
            label: 'Hanging',
            search: async (_query, { signal }) => {
                return new Promise((_, reject) => {
                    signal.addEventListener('abort', () => {
                        const err = new Error('The operation was aborted');
                        err.name = 'AbortError';
                        reject(err);
                    });
                });
            }
        }
    };

    setTimeout(() => controller.abort(), 20);

    await assert.rejects(
        async () => {
            await searchAcademicPapers('abort test', {
                sourceKeys: ['hanging'],
                providers: mockProviders,
                signal: controller.signal
            });
        },
        (err) => {
            return err.name === 'AbortError' || err.message.includes('aborted');
        }
    );
});

test('academicAggregate: RRF rank fusion correctly merges and ranks papers independent of provider order', async () => {
    clearAcademicCache();
    // Paper X appears in source A (rank 1) and source B (rank 1) -> RRF score = 1/(60+1) + 1/(60+1) = 2/61 ≈ 0.03278
    // Paper Y appears only in source A (rank 2) -> RRF score = 1/(60+2) = 1/62 ≈ 0.01612
    // Paper Z appears only in source B (rank 2) -> RRF score = 1/(60+2) = 1/62 ≈ 0.01612
    // Even if source B is placed before source A, paper X should definitely be rank 1!

    const paperX_A = createAcademicPaper({
        title: 'Unified Transformer Foundations',
        doi: '10.1000/transformer-foundations',
        year: 2023
    }, { key: 'source_a', label: 'Source A', recordId: 'xa' });

    const paperY_A = createAcademicPaper({
        title: 'Single Source Deep Dive',
        doi: '10.1000/single-deep-dive',
        year: 2024
    }, { key: 'source_a', label: 'Source A', recordId: 'ya' });

    const paperX_B = createAcademicPaper({
        title: 'Unified Transformer Foundations',
        doi: '10.1000/transformer-foundations',
        year: 2023
    }, { key: 'source_b', label: 'Source B', recordId: 'xb' });

    const paperZ_B = createAcademicPaper({
        title: 'Alpha Novel Architecture',
        doi: '10.1000/alpha-arch',
        year: 2022
    }, { key: 'source_b', label: 'Source B', recordId: 'zb' });

    const mockProviders = {
        source_b: {
            label: 'Source B',
            search: async () => [paperX_B, paperZ_B]
        },
        source_a: {
            label: 'Source A',
            search: async () => [paperX_A, paperY_A]
        }
    };

    const res = await searchAcademicPapers('ranking test', {
        sourceKeys: ['source_b', 'source_a'],
        providers: mockProviders
    });

    assert.equal(res.status, 'success');
    assert.equal(res.totalBeforeMerge, 4);
    assert.equal(res.totalAfterMerge, 3);
    assert.equal(res.items[0].title, 'Unified Transformer Foundations');
    // Check sources merged
    assert.equal(res.items[0].sources.length, 2);

    // Ties (paperY_A: score 1/62, year 2024; paperZ_B: score 1/62, year 2022)
    // Same score -> sorted by year desc -> paperY_A (2024) before paperZ_B (2022)
    assert.equal(res.items[1].title, 'Single Source Deep Dive');
    assert.equal(res.items[2].title, 'Alpha Novel Architecture');
});

test('academicAggregate: 5-minute short cache serves successful results and replays source events', async () => {
    clearAcademicCache();
    let callCountA = 0;
    let callCountB = 0;

    const mockProviders = {
        source_a: {
            label: 'Source A',
            search: async () => {
                callCountA++;
                return [createAcademicPaper({ title: 'Cached Paper 1', year: 2024 }, { key: 'source_a', label: 'Source A' })];
            }
        },
        source_b: {
            label: 'Source B',
            search: async () => {
                callCountB++;
                return [createAcademicPaper({ title: 'Cached Paper 2', year: 2023 }, { key: 'source_b', label: 'Source B' })];
            }
        }
    };

    const eventsFirst = [];
    const res1 = await searchAcademicPapers('caching query', {
        sourceKeys: ['source_a', 'source_b'],
        providers: mockProviders,
        onSourceStatus: ev => eventsFirst.push(ev)
    });

    assert.equal(res1.status, 'success');
    assert.equal(callCountA, 1);
    assert.equal(callCountB, 1);

    // Second call with same parameters should hit cache
    const eventsSecond = [];
    const res2 = await searchAcademicPapers('  caching query  ', {
        sourceKeys: ['source_b', 'source_a'], // different order should normalize to same key
        providers: mockProviders,
        onSourceStatus: ev => eventsSecond.push(ev)
    });

    assert.equal(callCountA, 1, 'Provider A should not be called again');
    assert.equal(callCountB, 1, 'Provider B should not be called again');
    assert.equal(res2.status, 'success');
    assert.equal(res2.items.length, res1.items.length);
    // Should replay source status events for cached items
    assert.ok(eventsSecond.some(e => e.key === 'source_a' && e.status === 'success'));
    assert.ok(eventsSecond.some(e => e.key === 'source_b' && e.status === 'success'));
});
