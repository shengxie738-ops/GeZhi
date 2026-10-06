// Reconstructed from retained test-writing context; previous results are historical only.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createTeacherWorkApi } from '../js/api/teacherWork.js';
import * as validators from '../js/api/teacherWorkMaterialProposals.js';
import { proposalCapabilities, proposalLimits, proposalCommand, proposalRun, proposalRead, proposalTaskId, proposalRunId, proposalMessageId } from './fixtures/teacherWorkMaterialProposalsFixtures.mjs';
const response = data => new Response(JSON.stringify({ code: 200, message: 'ok', data }), { status: 200 });
const apiFor = (fetchImpl, getToken = () => 'synthetic-proposal-session') => createTeacherWorkApi({ fetchImpl, getToken, dispatchAuthExpired() {} });
const method = api => { assert.equal(typeof api.getMaterialProposalsCapabilities, 'function'); return api.getMaterialProposalsCapabilities; };
const check = name => { assert.equal(typeof validators[name], 'function', name); return validators[name]; };
test('curated proposal capability uses authenticated no-store transport and exact configured facts', async () => {
    let calls = 0; const controller = new AbortController(), data = proposalCapabilities();
    const api = apiFor(async (url, options) => { calls++; assert.equal(new URL(url).pathname, '/api/teacher/work/material-proposals/capabilities');
        assert.equal(options.method, 'GET'); assert.equal(options.body, undefined); assert.equal(options.cache, 'no-store'); assert.equal(options.redirect, 'error');
        assert.equal(options.signal, controller.signal); assert.deepEqual(options.headers, { 'Content-Type': 'application/json', Authorization: 'Bearer synthetic-proposal-session' }); return response(data); });
    assert.deepEqual(await method(api)({ signal: controller.signal }), data); assert.equal(calls, 1);
});
test('proposal capability rejects unsupported skill, live verification claims and altered limits', async () => {
    for (const change of [data => { data.skill_ref = 'arbitrary@1'; }, data => { data.external_provider_verified = true; },
        data => { data.limits.max_provider_calls = 2; }, data => { data.limits.owner_subject = 'secret'; }, data => { data.reasons.generate = 'provider_unconfigured'; },
        data => { data.generate = false; }, data => { data.generate = true; data.provider_configured = false; }, data => { data.plugin = {}; }]) {
        const data = proposalCapabilities(); change(data); await assert.rejects(method(apiFor(async () => response(data)))(), caught => caught.reason === 'invalid_response');
    }
    const data = proposalCapabilities(); data.generate = false; data.provider_configured = false; data.reasons = { generate: 'provider_unconfigured' };
    assert.deepEqual(await method(apiFor(async () => response(data)))(), data); assert.deepEqual(data.limits, proposalLimits());
});
test('proposal capability abort and account-token fences discard body without exposing diagnostics', async () => {
    let token = 'one', calls = 0; const controller = new AbortController();
    const api = apiFor(async () => { calls++; token = 'two'; return response(proposalCapabilities()); }, () => token);
    await assert.rejects(method(api)({ signal: controller.signal }), caught => caught.reason === 'request_aborted'); assert.equal(calls, 1);
    await assert.rejects(method(apiFor(async () => new Response('private path /var/secret', { status: 503 })))(), caught => {
        assert.equal(caught.reason, 'request_failed'); assert.doesNotMatch(caught.message, /private|secret/); return true;
    });
});
test('proposal command is exact bounded and canonical before generation transport', async () => {
    const validate = check('validateMaterialProposalBody'); assert.deepEqual(validate(proposalCommand()), proposalCommand());
    for (const change of [value => { value.input_revision = true; }, value => { value.expected_revision = 0; }, value => { value.source_message_id = proposalMessageId.toUpperCase(); },
        value => { value.skill_ref = 'other@1'; }, value => { value.lesson = {}; }, value => { delete value.source_message_id; }]) {
        const value = proposalCommand(); change(value); assert.throws(() => validate(value), caught => caught.reason === 'invalid_input');
    }
    await assert.rejects(apiFor(async () => assert.fail('invalid command must not fetch')).generateMaterialProposal(proposalTaskId, { ...proposalCommand(), model: 'arbitrary' }, { idempotencyKey: 'one' }));
});
test('strict proposal runs detach 17 fields and reject malformed scalars and unsupported stages', () => {
    const validate = check('validateMaterialProposalRun'), original = proposalRun('COMPLETE'), decoded = validate(original);
    assert.deepEqual(decoded, original); assert.notEqual(decoded, original);
    for (const change of [value => { value.run_id = value.run_id.toUpperCase(); }, value => { value.input_digest = 'A'.repeat(64); },
        value => { value.omitted_context = null; }, value => { value.omitted_context = 1; }, value => { value.attempt = 2; }, value => { value.provider_call_count = 2; },
        value => { value.stage = 'INTERRUPTED'; }, value => { value.deadline = null; }, value => { value.created_at = '2026-10-06T00:00:00Z'; },
        value => { value.error_code = 'secret/path'; }, value => { value.receipt = { operation: 'generate', replayed: 1 }; }]) {
        const value = proposalRun(); change(value); assert.throws(() => validate(value), caught => caught.reason === 'invalid_response');
    }
});
test('generation read cancel routes bind exact task run command and receipt without reposting', async () => {
    const calls = [], api = apiFor(async (url, options) => { calls.push({ path: new URL(url).pathname, options });
        return response(proposalRun('PENDING', options.headers['Idempotency-Key'] ? { operation: 'generate', replayed: false } : null)); });
    await api.generateMaterialProposal(proposalTaskId, proposalCommand(), { idempotencyKey: 'original-command' });
    await api.getMaterialProposalRun(proposalTaskId, proposalRunId); await api.cancelMaterialProposal(proposalTaskId, proposalRunId);
    assert.deepEqual(calls.map(call => call.path), [`/api/teacher/work/tasks/${proposalTaskId}/material-proposals`,
        `/api/teacher/work/tasks/${proposalTaskId}/material-proposals/runs/${proposalRunId}`, `/api/teacher/work/tasks/${proposalTaskId}/material-proposals/runs/${proposalRunId}/cancel`]);
    assert.equal(calls[0].options.headers['Idempotency-Key'], 'original-command'); assert.deepEqual(JSON.parse(calls[0].options.body), proposalCommand());
    assert.equal(calls[1].options.body, undefined); assert.deepEqual(JSON.parse(calls[2].options.body), {}); assert.equal(calls[2].options.headers['Idempotency-Key'], undefined);
    await assert.rejects(apiFor(async () => response({ ...proposalRun('PENDING', { operation: 'generate', replayed: false }), source_message_id: proposalTaskId }))
        .generateMaterialProposal(proposalTaskId, proposalCommand(), { idempotencyKey: 'one' }), caught => caught.reason === 'invalid_response');
    await assert.rejects(apiFor(async () => response(proposalRun('COMPLETE', { operation: 'generate', replayed: true }))).getMaterialProposalRun(proposalTaskId, proposalRunId));
});
test('read-only proposal preserves valid old preview with explicit freshness and exact fields', async () => {
    const validate = check('validateMaterialProposalRead'); assert.deepEqual(validate(proposalRead()), proposalRead());
    for (const reason of ['PROPOSAL_NOT_READY', 'STALE_INPUT_REVISION', 'SOURCE_CHANGED', 'SOURCE_UNAVAILABLE', 'SOURCE_MESSAGE_INELIGIBLE']) {
        const value = reason === 'PROPOSAL_NOT_READY' ? { ...proposalRead(false, reason), proposal: null } : proposalRead(false, reason); assert.deepEqual(validate(value), value);
    }
    for (const change of [value => { value.proposal.skill_ref = 'other@1'; }, value => { value.proposal.omitted_context = null; }, value => { value.proposal.lesson.extra = 'untrusted'; },
        value => { value.proposal.slides[0].title = '<img src=x>'; }, value => { value.proposal.created_at = '2026-02-30T00:00:00Z'; },
        value => { value.freshness.adoptable = true; value.freshness.reason = 'SOURCE_CHANGED'; }, value => { value.freshness.reason = 'ARBITRARY'; }, value => { value.proposal = null; }]) {
        const value = proposalRead(); change(value); assert.throws(() => validate(value), caught => caught.reason === 'invalid_response');
    }
    let path = ''; const result = await apiFor(async url => { path = new URL(url).pathname; return response(proposalRead(false, 'SOURCE_CHANGED')); }).getMaterialProposal(proposalTaskId, proposalRunId);
    assert.deepEqual(result, proposalRead(false, 'SOURCE_CHANGED')); assert.equal(path, `/api/teacher/work/tasks/${proposalTaskId}/material-proposals/runs/${proposalRunId}/proposal`);
});
test('authoritative history is bounded unique task-scoped and preserves admission order', async () => {
    const validate = check('validateMaterialProposalHistory'), newer = { ...proposalRun('COMPLETE'), run_id: '11111111-1111-4111-8111-111111111111' };
    const data = { task_id: proposalTaskId, runs: [newer, proposalRun()] }; assert.deepEqual(validate(data), data);
    for (const value of [{ ...data, runs: Array(21).fill(proposalRun()) }, { ...data, runs: [proposalRun(), proposalRun()] }, { ...data, runs: [{ ...proposalRun(), task_id: proposalRunId }] },
        { ...data, runs: [proposalRun('PENDING', { operation: 'generate', replayed: true })] }, { ...data, next_before: null }]) assert.throws(() => validate(value));
    let path = ''; assert.deepEqual(await apiFor(async url => { path = new URL(url).pathname; return response(data); }).listMaterialProposalRuns(proposalTaskId), data);
    assert.equal(path, `/api/teacher/work/tasks/${proposalTaskId}/material-proposals/runs`); await assert.rejects(apiFor(async () => response(data)).listMaterialProposalRuns(proposalTaskId, { limit: 20 }));
});
test('HTTP failures stay sanitized and uncertain commit ID is only a query locator', async () => {
    const api = apiFor(async () => new Response(JSON.stringify({ code: 503, message: 'COMMIT_OUTCOME_UNKNOWN', data: { run_id: proposalRunId } }), { status: 503 }));
    await assert.rejects(api.generateMaterialProposal(proposalTaskId, proposalCommand(), { idempotencyKey: 'one' }), caught => {
        assert.equal(caught.reason, 'commit_outcome_unknown'); assert.equal(caught.queryRunId, proposalRunId); assert.equal(caught.receipt, undefined); return true;
    });
    for (const [status, code, reason] of [[409, 'SOURCE_CHANGED', 'source_changed'], [409, 'OWNER_RUN_BUSY', 'owner_busy'], [409, 'PROPOSAL_RUN_LIMIT', 'proposal_run_limit'],
        [409, 'PROPOSAL_NOT_READY', 'proposal_not_ready'], [422, 'PROPOSAL_CONTEXT_TOO_LARGE', 'proposal_context_too_large'], [429, 'INSTANCE_BUSY', 'instance_busy'],
        [503, 'MATERIAL_PROPOSAL_STATE_UNAVAILABLE', 'material_proposal_state_unavailable'], [503, 'PROPOSAL_SCHEMA_UNAVAILABLE', 'proposal_schema_unavailable']]) {
        await assert.rejects(apiFor(async () => new Response(JSON.stringify({ code: status, message: code, data: null }), { status }))
            .generateMaterialProposal(proposalTaskId, proposalCommand(), { idempotencyKey: 'one' }), caught => {
                assert.equal(caught.reason, reason); assert.equal(caught.status, status); assert.equal(caught.queryRunId, undefined); assert.doesNotMatch(caught.message, /secret|\/var\//); return true;
            });
    }
});
test('stream byte cap and malformed UTF-8 reject before accepting content', async () => {
    await assert.rejects(method(apiFor(async () => new Response(new Uint8Array(262145), { status: 200 })))(), caught => caught.reason === 'invalid_response');
    await assert.rejects(method(apiFor(async () => new Response(new Uint8Array([0xc3, 0x28]), { status: 200 })))(), caught => caught.reason === 'invalid_response');
});
test('hydrated schema forbids invented evidence XML-invalid text and absent-ready mismatch', () => {
    for (const change of [value => { value.proposal.lesson.citations = [{ name: '资料', page: 1, excerpt: '未经读取' }]; }, value => { value.proposal.slides[0].source_note = '来自资料'; },
        value => { value.proposal.lesson.summary = '\u0000'; }, value => { value.proposal = null; value.freshness = { adoptable: false, reason: 'SOURCE_CHANGED' }; }]) {
        const value = proposalRead(); change(value); assert.throws(() => check('validateMaterialProposalRead')(value), caught => caught.reason === 'invalid_response');
    }
    assert.deepEqual(check('validateMaterialProposalRun')({ ...proposalRun('COMPLETE'), proposal_available: false }), { ...proposalRun('COMPLETE'), proposal_available: false });
});
test('proposal arrays refuse sparse or decorated values instead of dropping unknown contents', () => {
    for (const runs of [new Array(1), Object.assign([], { plugin: 'extra' })]) assert.throws(() => check('validateMaterialProposalHistory')({ task_id: proposalTaskId, runs }));
    for (const slides of [new Array(6), Object.assign(proposalRead().proposal.slides, { plugin: 'extra' })]) {
        const value = proposalRead(); value.proposal.slides = slides; assert.throws(() => check('validateMaterialProposalRead')(value));
    }
});
