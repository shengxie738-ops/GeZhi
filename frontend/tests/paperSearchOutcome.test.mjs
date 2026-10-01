import assert from 'node:assert/strict';
import { test } from 'node:test';
import { interpretPaperSearchResponse } from '../js/controllers/workspaceSendRouter.js';

test('paperSearchOutcome: all-source failure is not treated as a completed search', () => {
    const outcome = interpretPaperSearchResponse({
        status: 'error',
        sourceStatuses: [
            { label: 'arXiv', status: 'error', error: '请求超时' },
            { label: 'Crossref', status: 'error', error: '上游不可用' }
        ]
    });

    assert.equal(outcome.completed, false);
    assert.match(outcome.errorMessage, /全部论文来源检索失败/);
    assert.match(outcome.errorMessage, /arXiv：请求超时/);
    assert.match(outcome.errorMessage, /Crossref：上游不可用/);
});

for (const status of ['success', 'partial', 'empty']) {
    test(`paperSearchOutcome: ${status} is a completed search`, () => {
        assert.deepEqual(
            interpretPaperSearchResponse({ status, sourceStatuses: [] }),
            { completed: true, errorMessage: '' }
        );
    });
}
