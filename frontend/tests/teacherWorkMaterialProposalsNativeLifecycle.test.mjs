import test from 'node:test';
import assert from 'node:assert/strict';
import { createTeacherWorkApi } from '../js/api/teacherWork.js';
import { useTeacherWork } from '../js/hooks/useTeacherWork.js';
import TeacherWork from '../js/components/teacher-work/TeacherWork.js';
import { Vue, globals, authRefs, settle, capabilityFacts, mount, find, walk, textOf, button } from './fixtures/teacherWorkHarness.mjs';
import { bySelector, nativeResponseReplay, verifyNativeRequest, assertNativeFixtureUnchanged } from './fixtures/teacherWorkMaterialProposalsNative.mjs';

const clone = value => structuredClone(value);
const vertical = bySelector('test_edited_origin_save_new_manual_save_historical_replay_approve_export');
const selectorName = group => group.provenance.selector.split('::').at(-1);
const taskOf = group => group.exchanges.find(x => x.request.path === '/api/teacher/work/tasks').response.body.data;
const historyOf = group => group.exchanges.find(x => x.request.method === 'GET' && x.request.path.endsWith('/messages'));
const validGenerations = group => {
    const selected = historyOf(group).response.body.data.messages.find(message => message.role === 'assistant');
    return group.exchanges.filter(x => x.request.method === 'POST' && x.request.path.endsWith('/material-proposals') &&
        x.request.body?.skill_ref === 'lesson_outline@1' && x.request.body.source_message_id === selected.message_id);
};
const materialsOf = group => group.exchanges.filter(x => x.request.method === 'POST' && x.request.path.endsWith('/materials'));
const proposalReadOf = group => group.exchanges.filter(x => x.request.path.endsWith('/proposal') && x.response.status === 200);
const emptyMaterials = (task, digest) => ({ task_id: task.task_id, input_revision: task.input_revision, working_revision: task.working_revision,
    last_outline_revision: 0, current_outline_id: null, outline: null, approval: null, source_status: 'unprepared', current_source_digest: digest,
    needs_normalization_fields: clone(task.working.needs_normalization_fields), approval_eligible: false, approval_current: false, approval_blocker: 'NO_OUTLINE', receipt: null });

// Bootstrap task GET, source/material capability reads and the initial material read are not
// captured in these selectors. They are explicitly local test setup, not native HTTP evidence.
// Every proposal/chat/material mutation and displayed candidate below uses immutable captured DTOs;
// retained response.body_utf8 is replayed exactly, normalized DTO encoding is labeled separately.
async function harness(group, { loseFirstOriginResponse = false } = {}) {
    const env = globals(), refs = authRefs(), scope = Vue.effectScope(), task = clone(taskOf(group)), actualCalls = [], localSetupReads = [];
    const generations = validGenerations(group), materialPosts = materialsOf(group), capturedReads = proposalReadOf(group);
    const history = historyOf(group), cap = group.exchanges.find(x => x.request.path.endsWith('/material-proposals/capabilities')) || vertical.exchanges[6];
    const proposalDigest = capturedReads[0]?.response.body.data.proposal?.source_digest || generations[0]?.response.body.data?.source_digest || '0'.repeat(64);
    let serverTask = task, materialSnapshot = emptyMaterials(task, proposalDigest), materialRead = null, proposalRead = capturedReads[0] || group.exchanges.filter(x => x.request.path.endsWith('/proposal')).at(-1) || null;
    let historyEnabled = false, lookup = null, firstOriginLost = false;
    const scheduled = new Map(); let timerId = 0;
    const scheduler = { setTimeout(fn) { const id = ++timerId; scheduled.set(id, fn); return id; }, clearTimeout(id) { scheduled.delete(id); } };
    const runId = generations.find(x => x.response.status === 200)?.response.body.data.run_id || generations[0]?.response.body.data?.run_id;
    const polls = group.exchanges.filter(x => x.request.method === 'GET' && x.request.path.endsWith('/material-proposals/runs/' + runId) && x.response.status === 200);
    let pollIndex = 0; const mutationUses = new Map();
    const keys = [...new Set([...generations, ...materialPosts.filter(x => [200, 503].includes(x.response.status)), ...group.exchanges.filter(x => x.request.path.endsWith('/materials/approve'))].map(x => x.request.idempotency_key))];
    let keyIndex = 0;
    function responseFrom(exchange, url, options) {
        assert.ok(exchange, 'No unregistered native exchange'); verifyNativeRequest(exchange, url, options);
        const replay = nativeResponseReplay(exchange);
        actualCalls.push({ exchange, body: options.body, key: options.headers['Idempotency-Key'] ?? null, replayMode: replay.replayMode,
            actualCapturedByteLength: replay.actualCapturedByteLength, testTransportByteLength: replay.testTransportByteLength });
        if (options.method === 'POST' && exchange.request.path.endsWith('/materials') && exchange.response.status === 200) {
            materialSnapshot = { ...clone(exchange.response.body.data), receipt: null };
            serverTask = { ...serverTask, input_revision: materialSnapshot.input_revision, working_revision: materialSnapshot.working_revision,
                working: { ...serverTask.working, needs_normalization_fields: clone(materialSnapshot.needs_normalization_fields) } };
            if (loseFirstOriginResponse && !firstOriginLost && exchange.request.body.origin_proposal_run_id) {
                firstOriginLost = true;
                // Test-owned network fault after a captured confirmed response, not an extra native503 capture.
                throw new Error('test-owned lost origin confirmation');
            }
        }
        return replay.response;
    }
    const transport = createTeacherWorkApi({ getToken: () => 'synthetic-native-proposal-session', dispatchAuthExpired() {},
        fetchImpl: async (url, options) => {
            const path = new URL(url).pathname;
            if (path.endsWith('/messages')) return responseFrom(history, url, options);
            if (path.endsWith('/material-proposals/capabilities')) return responseFrom(cap, url, options);
            if (path.endsWith('/proposal')) return responseFrom(proposalRead, url, options);
            if (path.endsWith('/material-proposals/runs')) return responseFrom(lookup, url, options);
            if (path.endsWith('/material-proposals/runs/' + runId)) {
                const exchange = polls[Math.min(pollIndex++, polls.length - 1)] || group.exchanges.find(x => x.request.path === path);
                return responseFrom(exchange, url, options);
            }
            if (path.endsWith('/materials') && options.method === 'GET') return responseFrom(materialRead, url, options);
            if (options.method === 'POST') {
                const candidates = group.exchanges.filter(x => x.request.path === path && (x.request.idempotency_key ?? null) === (options.headers['Idempotency-Key'] ?? null));
                const use = mutationUses.get(options.headers['Idempotency-Key']) || 0; mutationUses.set(options.headers['Idempotency-Key'], use + 1);
                return responseFrom(candidates[use], url, options);
            }
            return responseFrom(group.exchanges.find(x => x.request.path === path && x.request.method === options.method), url, options);
        } });
    const api = { ...transport,
        getCapabilities: async () => { localSetupReads.push('uncaptured bootstrap capabilities'); return { ...capabilityFacts(), chat: false, private_tasks: { create: true, read: true, update: true } }; },
        getTask: async () => { localSetupReads.push('uncaptured task GET projection'); return clone(serverTask); },
        listResources: async () => { localSetupReads.push('uncaptured resource catalog'); return []; },
        getMaterialsCapabilities: async () => { localSetupReads.push('uncaptured manual capability setup'); return { save: true, read: true, approve: true, source_configured: true, files: false, reasons: { files: 'files_not_enabled' } }; },
        getMaterials: async (taskId, options) => { if (materialRead) return transport.getMaterials(taskId, options); localSetupReads.push('uncaptured initial/current local material projection'); return clone(materialSnapshot); },
        listMaterialProposalRuns: async (taskId, options) => { if (historyEnabled) return transport.listMaterialProposalRuns(taskId, options);
            localSetupReads.push('uncaptured bootstrap empty proposal history'); return { task_id: taskId, runs: [] }; },
        getPackagesCapabilities: undefined
    };
    const hook = scope.run(() => useTeacherWork(refs, { api, storage: env.storage, documentTarget: document, eventTarget: env.eventTarget,
        viewportTarget: { innerWidth: 1440 }, location: new URL('https://finite.invalid/?teacher_work_task=' + task.task_id), history: { replaceState() {} },
        chatScheduler: scheduler, packageScheduler: scheduler, newIdempotencyKey: () => keys[keyIndex++] }));
    await settle();
    const persistedHistory = await transport.listMessages(task.task_id);
    hook.state.messages = persistedHistory.messages; hook.state.chatHistoryStatus = 'ready'; await settle();
    return { hook, transport, scope, refs, actualCalls, localSetupReads, scheduled, taskId: task.task_id, runId, group,
        enableHistory(exchange) { historyEnabled = true; lookup = exchange || group.exchanges.find(x => x.request.path.endsWith('/material-proposals/runs') && x.response.status === 200); },
        setProposalRead(exchange) { proposalRead = exchange; },
        setMaterialRead(exchange) { materialRead = exchange; if (exchange.response.status === 200) {
            materialSnapshot = clone(exchange.response.body.data); serverTask = { ...serverTask, input_revision: materialSnapshot.input_revision,
                working_revision: materialSnapshot.working_revision, working: { ...serverTask.working, needs_normalization_fields: clone(materialSnapshot.needs_normalization_fields) } };
        } },
        async finishPolling() { for (let count = 0; count < polls.length; count++) { const entry = scheduled.entries().next().value; assert.ok(entry, 'bounded poll exists');
            scheduled.delete(entry[0]); await entry[1](); await settle(); } },
        async generate() { assert.equal(hook.selectMaterialProposalSource(generations[0].request.body.source_message_id), true); return hook.generateMaterialProposal(); },
        close() { scope.stop(); assertNativeFixtureUnchanged(); }
    };
}
const draftFrom = exchange => ({ lesson: clone(exchange.request.body.lesson), slides: clone(exchange.request.body.slides) });
const mutatingCalls = h => h.actualCalls.filter(call => call.exchange.request.method !== 'GET');

test('actual Task4 proposal reply generation preview and explicit edited A/manual B saves retain historical replay identity', async () => {
    const h = await harness(vertical);
    try {
        assert.equal(h.hook.state.materialProposals.sourceMessageId, null); assert.equal(mutatingCalls(h).length, 0);
        assert.equal(await h.generate(), true); await h.finishPolling(); h.enableHistory(); assert.equal(await h.hook.reloadMaterialProposalHistory(), true);
        assert.deepEqual(h.hook.state.materialProposals.history, vertical.exchanges[15].response.body.data.runs);
        assert.equal(h.hook.state.materials.dirty, false); assert.equal(h.hook.state.materials.draft.lesson.summary, '');
        const host = await mount(TeacherWork, { state: h.hook.state });
        try { assert.match(textOf(host.root), /<b>Synthetic plain JSON candidate<\/b>/); assert.equal(walk(host.root).filter(node => node.tag === 'b').length, 0);
            button(host.root, '填入手动草稿').props.onClick(); assert.deepEqual(host.emitted['adopt-material-proposal'], [[]]);
            assert.equal(host.emitted['save-materials'], undefined); assert.equal(host.emitted['approve-materials'], undefined); assert.equal(host.emitted['create-package'], undefined);
        } finally { host.close(); }
        assert.equal(await h.hook.adoptMaterialProposal(), true); assert.equal(h.hook.state.materials.dirty, true); assert.equal(mutatingCalls(h).length, 1);
        h.hook.updateMaterialsDraft(draftFrom(vertical.exchanges[16])); assert.equal(await h.hook.saveMaterials(), true);
        assert.equal(h.hook.state.materials.proposalOrigin, null); assert.deepEqual(h.hook.state.materials.snapshot, vertical.exchanges[16].response.body.data);
        h.hook.updateMaterialsDraft(draftFrom(vertical.exchanges[17])); assert.equal(await h.hook.saveMaterials(), true);
        assert.equal(Object.hasOwn(mutatingCalls(h).at(-1).exchange.request.body, 'origin_proposal_run_id'), false);
        const replay = await h.transport.saveMaterials(h.taskId, clone(vertical.exchanges[18].request.body), { idempotencyKey: vertical.exchanges[18].request.idempotency_key });
        assert.equal(replay.receipt.outline_id, vertical.exchanges[16].response.body.data.current_outline_id);
        assert.equal(replay.current_outline_id, vertical.exchanges[17].response.body.data.current_outline_id); assert.equal(replay.receipt.replayed, true);
        assert.equal(h.hook.state.materials.draft.lesson.summary, vertical.exchanges[17].request.body.lesson.summary);
        assert.equal(await h.hook.approveMaterials(), true); assert.deepEqual(h.hook.state.materials.snapshot, vertical.exchanges[21].response.body.data);
        const created = await h.transport.createPackage(h.taskId, clone(vertical.exchanges[22].request.body), { idempotencyKey: vertical.exchanges[22].request.idempotency_key });
        assert.equal(created.provenance, 'manual'); assert.deepEqual(created.version.skill_versions, []); assert.deepEqual(created.version.source_snapshots, []);
        const read = await h.transport.getPackage(h.taskId, created.version.version_id); assert.deepEqual(read, vertical.exchanges[29].response.body.data);
        assert.ok(created.artifacts.every(artifact => artifact.state === 'READY' && artifact.byte_size > 0 && /^[a-f0-9]{64}$/.test(artifact.sha256)));
        assert.equal(h.actualCalls.filter(call => call.exchange.binary).length, 0, 'omitted new binary bodies are never invented or downloaded');
        assert.ok(h.localSetupReads.length > 0, 'uncaptured bootstrap prerequisites are explicitly separate local setup');
    } finally { h.close(); }
});

test('actual old A replay through uncertain lifecycle clears consumed origin and preserves concurrent edits over current B', async () => {
    const h = await harness(vertical, { loseFirstOriginResponse: true });
    try {
        assert.equal(await h.generate(), true); await h.finishPolling(); assert.equal(await h.hook.adoptMaterialProposal(), true);
        h.hook.updateMaterialsDraft(draftFrom(vertical.exchanges[16])); assert.equal(await h.hook.saveMaterials(), false);
        assert.equal(h.hook.state.materials.status, 'uncertain'); assert.equal(h.hook.state.materials.retryAvailable, true);
        h.hook.updateMaterialsDraft({ ...draftFrom(vertical.exchanges[16]), lesson: { ...draftFrom(vertical.exchanges[16]).lesson, summary: 'Concurrent local edit stays copyable' } });
        await h.transport.saveMaterials(h.taskId, clone(vertical.exchanges[17].request.body), { idempotencyKey: vertical.exchanges[17].request.idempotency_key });
        assert.equal(await h.hook.retryMaterials(), true); await settle();
        const originCalls = mutatingCalls(h).filter(call => call.key === 'contract-origin-save-A'); assert.equal(originCalls.length, 2);
        assert.equal(originCalls[0].body, originCalls[1].body); assert.equal(originCalls[0].key, originCalls[1].key);
        assert.equal(h.hook.state.materials.proposalOrigin, null); assert.equal(h.hook.state.materials.draft.lesson.summary, 'Concurrent local edit stays copyable');
        assert.equal(h.hook.state.materials.dirty, true); assert.equal(h.hook.state.materials.lastReceipt.outline_id, vertical.exchanges[16].response.body.data.current_outline_id);
        assert.equal(h.hook.state.materials.snapshot.current_outline_id, vertical.exchanges[17].response.body.data.current_outline_id);
        assert.equal(h.hook.state.materials.canApprove, false); assert.equal(h.hook.state.materials.canSave, true);
    } finally { h.close(); }
});

for (const phase of ['before', 'after']) test('actual origin ' + phase + '-commit503 never invents receipt and freezes original body/key', async () => {
    const group = bySelector('test_actual_http_origin_save_unknown_dbapi_ack_no_fabricated_receipt[' + phase + ']'), h = await harness(group);
    try {
        assert.equal(await h.generate(), true); await h.finishPolling(); assert.equal(await h.hook.adoptMaterialProposal(), true);
        const original = materialsOf(group)[0]; h.hook.updateMaterialsDraft(draftFrom(original)); assert.equal(await h.hook.saveMaterials(), false);
        assert.equal(h.hook.state.materials.status, 'uncertain'); assert.equal(h.hook.state.materials.lastReceipt, null);
        const edited = draftFrom(original); edited.lesson.summary += ' Concurrent edit'; h.hook.updateMaterialsDraft(edited);
        const observed = group.exchanges.find(x => x.request.method === 'GET' && x.request.path.endsWith('/materials'));
        h.setMaterialRead(observed); assert.equal(await h.hook.reloadMaterials(), true); await settle();
        assert.equal(h.hook.state.materials.retryAvailable, true); assert.equal(h.hook.state.materials.draft.lesson.summary, edited.lesson.summary);
        assert.equal(h.hook.state.materials.canApprove, false);
        if (phase === 'before') { assert.equal(h.hook.state.materials.snapshot.outline, null); assert.equal(h.hook.state.materials.lastReceipt, null);
            assert.equal(h.hook.state.materials.canSave, false); assert.equal(mutatingCalls(h).filter(call => call.exchange.request.path.endsWith('/materials')).length, 1);
        } else { assert.equal(h.hook.state.materials.snapshot.outline.outline_id, observed.response.body.data.current_outline_id);
            assert.equal(await h.hook.retryMaterials(), true); const calls = mutatingCalls(h).filter(call => call.exchange.request.path.endsWith('/materials'));
            assert.equal(calls.length, 2); assert.equal(calls[0].body, calls[1].body); assert.equal(calls[0].key, calls[1].key);
            assert.equal(h.hook.state.materials.proposalOrigin, null); assert.equal(h.hook.state.materials.draft.lesson.summary, edited.lesson.summary);
        }
        const fact = group.selected_actual_row_facts.at(-1); assert.equal(fact.real_commit_called, phase === 'after');
        assert.deepEqual(fact.unknown_envelope, original.response.body);
    } finally { h.close(); }
});

for (const phase of ['before', 'after']) test('actual proposal ' + phase + '-admission503 keeps query locator separate from admitted run', async () => {
    const group = bySelector('test_actual_dbapi_unknown_ack_no_redispatch_or_write_retry[' + phase + '-admission]'), h = await harness(group);
    try {
        assert.equal(await h.generate(), false); assert.equal(h.hook.state.materialProposals.status, 'uncertain'); assert.equal(h.hook.state.materialProposals.run, null);
        assert.equal(h.hook.state.materialProposals.retryAvailable, true); assert.equal(h.hook.selectMaterialProposalSource(validGenerations(group)[0].request.body.source_message_id), false);
        assert.equal(mutatingCalls(h).length, 1); await h.hook.refreshMaterialProposal();
        if (phase === 'before') { assert.equal(h.hook.state.materialProposals.run, null); assert.equal(h.hook.state.materialProposals.error.reason, 'task_not_found'); }
        else { assert.equal(h.hook.state.materialProposals.run.stage, 'PENDING'); assert.equal(await h.hook.retryMaterialProposal(), true);
            const calls = mutatingCalls(h); assert.equal(calls.length, 2); assert.equal(calls[0].body, calls[1].body); assert.equal(calls[0].key, calls[1].key);
            assert.equal(h.hook.state.materialProposals.run.receipt.replayed, true);
        }
        assert.equal(h.hook.state.materials.dirty, false); assert.equal(h.hook.state.materialProposals.proposal, null);
    } finally { h.close(); }
});
test('actual stale-source and foreign404 observations retain readonly preview without adopting or writing', async () => {
    const group = bySelector('test_current_freshness_authority_and_foreign_ownership[source]'), h = await harness(group);
    try {
        assert.equal(await h.generate(), true); await h.finishPolling();
        assert.equal(h.hook.state.materialProposals.freshness.reason, 'SOURCE_CHANGED'); assert.ok(h.hook.state.materialProposals.proposal);
        assert.equal(h.hook.state.materialProposals.canAdopt, false); assert.equal(await h.hook.adoptMaterialProposal(), false);
        const host = await mount(TeacherWork, { state: h.hook.state });
        try { assert.equal(button(host.root, '填入手动草稿').props.disabled, true); button(host.root, '填入手动草稿').props.onClick();
            assert.equal(host.emitted['adopt-material-proposal'], undefined);
        } finally { host.close(); }
        h.setProposalRead(group.exchanges.find(x => x.request.path.endsWith('/proposal') && x.response.status === 404));
        assert.equal(await h.hook.refreshMaterialProposal(), false); assert.equal(h.hook.state.materialProposals.error.reason, 'task_not_found');
        assert.equal(h.hook.state.materialProposals.canAdopt, false); assert.equal(await h.hook.adoptMaterialProposal(), false);
        assert.equal(mutatingCalls(h).length, 1); assert.equal(h.hook.state.materials.dirty, false);
    } finally { h.close(); }
});

test('actual role403 clears selected candidate and closes generation read adoption and cancel gates', async () => {
    const group = bySelector('test_current_freshness_authority_and_foreign_ownership[role]'), h = await harness(group);
    try {
        assert.equal(await h.generate(), true); await h.finishPolling();
        assert.equal(h.hook.state.materialProposals.error.reason, 'teacher_required');
        assert.equal(h.hook.state.materialProposals.proposal, null); assert.equal(h.hook.state.materialProposals.sourceMessageId, null);
        for (const name of ['canGenerate', 'canRefresh', 'canAdopt', 'canCancel']) assert.equal(h.hook.state.materialProposals[name], false, name);
        assert.equal(await h.hook.adoptMaterialProposal(), false); assert.equal(mutatingCalls(h).length, 1); assert.equal(h.hook.state.materials.dirty, false);
    } finally { h.close(); }
});

test('actual cancelled and late-provider run facts never publish a candidate or mutate drafts', async () => {
    const group = bySelector('test_actual_bridge_cancel_timeout_stubborn_late_result[True-cancel]'), h = await harness(group);
    try {
        assert.equal(await h.generate(), true); assert.equal(await h.hook.cancelMaterialProposal(), true);
        assert.equal(h.hook.state.materialProposals.status, 'cancelled'); assert.equal(h.scheduled.size, 0);
        assert.equal(await h.hook.refreshMaterialProposal(), true); assert.equal(h.hook.state.materialProposals.run.stage, 'CANCELLED');
        const repeated = await h.transport.cancelMaterialProposal(h.taskId, h.runId); assert.equal(repeated.stage, 'CANCELLED');
        assert.equal(h.hook.state.materialProposals.proposal, null); assert.equal(h.hook.state.materials.dirty, false);
        assert.equal(h.hook.state.materialProposals.canAdopt, false); assert.ok(mutatingCalls(h).every(call => !call.exchange.request.path.endsWith('/materials')));
    } finally { h.close(); }
});

test('actual timeout run failure remains terminal without repair generation save or export', async () => {
    const group = bySelector('test_actual_bridge_cancel_timeout_stubborn_late_result[True-timeout]'), h = await harness(group);
    try {
        assert.equal(await h.generate(), true); await h.finishPolling(); assert.equal(h.hook.state.materialProposals.status, 'failed');
        assert.equal(h.hook.state.materialProposals.run.error_code, group.exchanges.at(-1).response.body.data.error_code);
        assert.equal(h.hook.state.materialProposals.proposal, null); assert.equal(h.hook.state.materialProposals.canAdopt, false);
        assert.equal(h.scheduled.size, 0); assert.equal(mutatingCalls(h).length, 1); assert.equal(h.hook.state.materials.dirty, false);
    } finally { h.close(); }
});
