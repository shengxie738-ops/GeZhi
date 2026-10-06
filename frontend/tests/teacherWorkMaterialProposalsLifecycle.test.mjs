// Reconstructed from retained lifecycle test-writing context; fresh verification is required.
import test from 'node:test';
import assert from 'node:assert/strict';
import { useTeacherWork } from '../js/hooks/useTeacherWork.js';
import { Vue, globals, authRefs, settle, capabilityFacts, deferred } from './fixtures/teacherWorkHarness.mjs';
import { proposalTaskId, proposalCapabilities, sourceMessage, proposalMessageId, proposalRunId, proposalRun, proposalRead, proposalCommand } from './fixtures/teacherWorkMaterialProposalsFixtures.mjs';
import { materialsCapabilities, materialsSnapshot } from './fixtures/teacherWorkMaterialsFixtures.mjs';
const instant = '2026-10-06T00:00:00+00:00';
const task = () => ({ task_id: proposalTaskId, scope: 'private', title: '循环教学', topic: '循环', audience: '一年级', duration_minutes: 45,
    target_slide_count: 6, input_revision: 1, working_revision: 1, created_at: instant, updated_at: instant,
    working: { requirements: '', resource_ids: ['resource-one'], needs_normalization_fields: [] } });
const materialRead = () => ({ ...materialsSnapshot(), input_revision: 1, working_revision: 1, last_outline_revision: 0,
    current_outline_id: null, outline: null, source_status: 'unprepared', approval_eligible: false, approval_blocker: 'NO_OUTLINE' });
async function harness(overrides = {}) {
    const env = globals(), refs = authRefs(), scope = Vue.effectScope(), calls = { generate: [], reads: [], lists: [] }, scheduled = new Map(); let timerId = 0;
    const scheduler = { setTimeout(fn) { const id = ++timerId; scheduled.set(id, fn); return id; }, clearTimeout(id) { scheduled.delete(id); } };
    const api = { getCapabilities: async () => ({ ...capabilityFacts(), private_tasks: { create: true, read: true, update: true } }),
        listResources: async () => [], getTask: async () => task(), getMaterialsCapabilities: async () => materialsCapabilities(), getMaterials: async () => materialRead(),
        getMaterialProposalsCapabilities: async () => proposalCapabilities(), listMaterialProposalRuns: async (...args) => { calls.lists.push(args); return { task_id: proposalTaskId, runs: [] }; },
        getMaterialProposalRun: async (...args) => { calls.reads.push(args); return proposalRun('COMPLETE'); }, getMaterialProposal: async () => proposalRead(),
        cancelMaterialProposal: async () => proposalRun('CANCELLED'), generateMaterialProposal: async (...args) => { calls.generate.push(args); throw { reason: 'network_error' }; }, ...overrides };
    const hook = scope.run(() => useTeacherWork(refs, { api, storage: env.storage, documentTarget: document, eventTarget: env.eventTarget,
        viewportTarget: { innerWidth: 1440 }, location: new URL('https://example.invalid/?teacher_work_task=' + proposalTaskId),
        history: { replaceState() {} }, chatScheduler: scheduler, newIdempotencyKey: () => 'proposal-key' }));
    await settle(); hook.state.messages = [sourceMessage()]; await settle(); return { hook, scope, refs, calls, scheduled, ...env };
}
test('proposal lifecycle starts with no selected reply and never generates or changes materials on arrival', async () => {
    const h = await harness(); try {
        assert.ok(h.hook.state.materialProposals); assert.equal(h.hook.state.materialProposals.capabilities.status, 'ready');
        assert.equal(h.hook.state.materialProposals.sourceMessageId, null); assert.equal(h.hook.state.materialProposals.canGenerate, false);
        assert.equal(h.calls.generate.length, 0); assert.equal(h.hook.state.materials.draft.lesson.title, '');
    } finally { h.scope.stop(); }
});
test('only explicit persisted assistant source selection opens generation without claiming eligibility', async () => {
    const h = await harness(); try {
        const state = h.hook.state; assert.equal(h.hook.selectMaterialProposalSource('11111111-1111-4111-8111-111111111111'), false);
        state.messages = [{ ...sourceMessage(), role: 'user', result_type: null, omitted_context: null }]; assert.equal(h.hook.selectMaterialProposalSource(proposalMessageId), false);
        state.messages = [{ ...sourceMessage(), run_id: null, result_type: null, omitted_context: null }]; assert.equal(h.hook.selectMaterialProposalSource(proposalMessageId), false);
        state.messages = [sourceMessage()]; assert.equal(h.hook.selectMaterialProposalSource(proposalMessageId), true);
        assert.equal(state.materialProposals.sourceMessageId, proposalMessageId); assert.equal(state.materialProposals.canGenerate, true);
        assert.equal(Object.hasOwn(state.materialProposals, 'sourceEligible'), false); assert.equal(h.calls.generate.length, 0);
        h.hook.updateInput('尚未保存'); await settle(); assert.equal(state.materialProposals.canGenerate, false);
    } finally { h.scope.stop(); }
});
test('generation admits one frozen command and polling only reads before explicit adoption', async () => {
    const h = await harness({ generateMaterialProposal: async (...args) => { h.calls.generate.push(args); return proposalRun('PENDING', { operation: 'generate', replayed: false }); } });
    try {
        h.hook.selectMaterialProposalSource(proposalMessageId); assert.equal(await h.hook.generateMaterialProposal(), true); assert.deepEqual(h.calls.generate[0][1], proposalCommand());
        assert.equal(h.hook.state.materialProposals.status, 'queued'); assert.equal(h.hook.state.materials.dirty, false);
        const timer = h.scheduled.values().next().value; assert.equal(typeof timer, 'function'); await timer(); await settle();
        assert.equal(h.hook.state.materialProposals.proposal.lesson.title, '循环教学'); assert.equal(h.hook.state.materialProposals.canAdopt, true);
        assert.equal(h.hook.state.materials.draft.lesson.title, ''); assert.equal(await h.hook.adoptMaterialProposal(), true);
        assert.equal(h.hook.state.materials.dirty, true); assert.equal(h.hook.state.materials.proposalOrigin.run_id, proposalRunId); assert.equal(h.calls.generate.length, 1);
    } finally { h.scope.stop(); }
});
test('uncertain submission retries only exact command and key even after task revisions change', async () => {
    let attempts = 0; const h = await harness({ generateMaterialProposal: async (...args) => { h.calls.generate.push(args);
        if (++attempts === 1) throw { reason: 'commit_outcome_unknown', queryRunId: proposalRunId, status: 503 };
        return proposalRun('COMPLETE', { operation: 'generate', replayed: true }); } });
    try {
        h.hook.selectMaterialProposalSource(proposalMessageId); assert.equal(await h.hook.generateMaterialProposal(), false);
        assert.equal(h.hook.state.materialProposals.status, 'uncertain'); assert.equal(h.hook.state.materialProposals.run, null);
        assert.equal(h.hook.selectMaterialProposalSource(proposalMessageId), false); assert.equal(h.calls.generate.length, 1);
        h.hook.state.input_revision = 2; h.hook.state.working_revision = 2; await settle(); assert.equal(await h.hook.retryMaterialProposal(), true);
        assert.deepEqual(h.calls.generate[1][1], h.calls.generate[0][1]); assert.equal(h.calls.generate[1][2].idempotencyKey, h.calls.generate[0][2].idempotencyKey);
        assert.equal(h.hook.state.materialProposals.canAdopt, false); assert.equal(h.hook.state.materials.draft.lesson.title, '');
    } finally { h.scope.stop(); }
});
const readOnlyProposals = (reason = 'proposal_runtime_unavailable') => ({ ...proposalCapabilities(), generate: false,
    provider_configured: reason !== 'provider_unconfigured', reasons: { generate: reason } });
for (const reason of ['proposal_runtime_unavailable', 'provider_unconfigured']) test('uncertain COMPLETE query recovers original replay with new generation unavailable: ' + reason, async () => {
    let attempts = 0, capabilities = proposalCapabilities();
    const h = await harness({ getMaterialProposalsCapabilities: async () => capabilities,
        generateMaterialProposal: async (...args) => { h.calls.generate.push(args);
            if (++attempts === 1) throw { reason: 'commit_outcome_unknown', queryRunId: proposalRunId, status: 503 };
            return proposalRun('COMPLETE', { operation: 'generate', replayed: true }); } });
    try {
        h.hook.selectMaterialProposalSource(proposalMessageId); assert.equal(await h.hook.generateMaterialProposal(), false);
        capabilities = readOnlyProposals(reason); assert.equal(await h.hook.retryMaterialProposalsCapabilities(), true);
        assert.equal(await h.hook.refreshMaterialProposal(), true);
        const current = h.hook.state.materialProposals;
        assert.equal(current.run.stage, 'COMPLETE'); assert.equal(current.freshness.adoptable, true);
        assert.equal(current.canGenerate, false); assert.equal(current.canAdopt, false, 'query cannot manufacture a command receipt');
        assert.equal(current.canRetry, true, 'read authorization permits only the retained original request');
        assert.equal(await h.hook.generateMaterialProposal(), false); assert.equal(h.calls.generate.length, 1);
        assert.equal(await h.hook.retryMaterialProposal(), true);
        assert.deepEqual(h.calls.generate[1][1], h.calls.generate[0][1]);
        assert.equal(h.calls.generate[1][2].idempotencyKey, h.calls.generate[0][2].idempotencyKey);
        assert.equal(current.retryAvailable, false); assert.equal(current.canRetry, false); assert.equal(current.canGenerate, false);
        assert.equal(current.canAdopt, true); assert.equal(h.hook.state.materials.dirty, false);
        assert.equal(await h.hook.adoptMaterialProposal(), true); assert.equal(h.hook.state.materials.dirty, true);
        assert.equal(h.hook.state.materials.proposalOrigin.run_id, proposalRunId); assert.equal(h.calls.generate.length, 2);
    } finally { h.scope.stop(); }
});
test('original replay survives a new-generation gate tightening during its response', async () => {
    let attempts = 0; const pending = deferred(), h = await harness({ generateMaterialProposal: (...args) => {
        h.calls.generate.push(args); return ++attempts === 1 ? Promise.reject({ reason: 'commit_outcome_unknown', queryRunId: proposalRunId, status: 503 }) : pending.promise;
    } });
    try {
        h.hook.selectMaterialProposalSource(proposalMessageId); await h.hook.generateMaterialProposal();
        const retrying = h.hook.retryMaterialProposal(); assert.equal(h.calls.generate.length, 2);
        h.hook.state.materialProposals.capabilities.data = readOnlyProposals();
        assert.equal(h.calls.generate[1][2].signal.aborted, false, 'the old replay still has read authorization');
        pending.resolve(proposalRun('COMPLETE', { operation: 'generate', replayed: true }));
        assert.equal(await retrying, true); assert.equal(h.hook.state.materialProposals.canAdopt, true);
        assert.equal(h.hook.state.materialProposals.canGenerate, false); assert.equal(h.hook.state.materials.dirty, false);
    } finally { pending.resolve(proposalRun('COMPLETE', { operation: 'generate', replayed: true })); h.scope.stop(); }
});
test('read-only recovery rejects a new-admission receipt and retains original uncertain command', async () => {
    let attempts = 0; const h = await harness({ generateMaterialProposal: async (...args) => { h.calls.generate.push(args);
        if (++attempts === 1) throw { reason: 'commit_outcome_unknown', queryRunId: proposalRunId, status: 503 };
        return proposalRun('COMPLETE', { operation: 'generate', replayed: false }); } });
    try {
        h.hook.selectMaterialProposalSource(proposalMessageId); await h.hook.generateMaterialProposal();
        h.hook.state.materialProposals.capabilities.data = readOnlyProposals();
        assert.equal(h.hook.state.materialProposals.canRetry, true); assert.equal(await h.hook.retryMaterialProposal(), false);
        assert.equal(h.hook.state.materialProposals.retryAvailable, true); assert.equal(h.hook.state.materialProposals.canAdopt, false);
        assert.equal(h.hook.state.materialProposals.run, null); assert.equal(h.hook.state.materials.dirty, false);
    } finally { h.scope.stop(); }
});
test('read-only original replay retains identity revision disposal and read-gate fences', async () => {
    for (const change of ['actor', 'role', 'epoch', 'auth', 'task', 'view', 'revision', 'working', 'dispose', 'read', 'capability', 'create']) {
        let attempts = 0; const pending = deferred(), h = await harness({ generateMaterialProposal: (...args) => {
            h.calls.generate.push(args); return ++attempts === 1 ? Promise.reject({ reason: 'commit_outcome_unknown', queryRunId: proposalRunId, status: 503 }) : pending.promise;
        } });
        try {
            h.hook.selectMaterialProposalSource(proposalMessageId); await h.hook.generateMaterialProposal();
            h.hook.state.materialProposals.capabilities.data = readOnlyProposals();
            assert.equal(h.hook.state.materialProposals.canRetry, true, change); const retrying = h.hook.retryMaterialProposal();
            if (change === 'actor') h.refs.actor.value = 'teacher-b'; if (change === 'role') h.refs.role.value = 'student';
            if (change === 'epoch') h.refs.authEpoch.value++; if (change === 'auth') h.refs.authVerified.value = false;
            if (change === 'task') h.hook.state.task_id = '11111111-1111-4111-8111-111111111111';
            if (change === 'view') h.refs.currentView.value = 't_lesson_prep'; if (change === 'revision') h.hook.state.input_revision++;
            if (change === 'working') h.hook.state.working_revision++; if (change === 'dispose') h.scope.stop();
            if (change === 'read') h.hook.state.materialProposals.capabilities.data.read = false;
            if (change === 'capability') h.hook.state.materialProposals.capabilities.status = 'loading';
            if (change === 'create') h.hook.state.createOpen = true;
            assert.equal(h.calls.generate[1][2].signal.aborted, true, change);
            pending.resolve(proposalRun('COMPLETE', { operation: 'generate', replayed: true }));
            assert.equal(await retrying, false, change); assert.equal(h.hook.state.materialProposals.canAdopt, false, change);
            assert.equal(h.hook.state.materials.dirty, false, change);
        } finally { pending.resolve(proposalRun('COMPLETE', { operation: 'generate', replayed: true })); h.scope.stop(); }
    }
});
test('dirty draft replacement requires visible choice and fresh server observation at adoption', async () => {
    let read = proposalRead(); const h = await harness({ getMaterialProposal: async () => read,
        listMaterialProposalRuns: async () => ({ task_id: proposalTaskId, runs: [proposalRun('COMPLETE')] }) });
    try {
        assert.equal(await h.hook.openMaterialProposalRun(proposalRunId), true);
        h.hook.updateMaterialsDraft({ lesson: { ...proposalRead().proposal.lesson, title: '手动编辑' }, slides: proposalRead().proposal.slides });
        assert.equal(await h.hook.adoptMaterialProposal(), false); assert.equal(h.hook.state.materialProposals.pendingReplace, true);
        assert.equal(h.hook.state.materials.draft.lesson.title, '手动编辑'); h.hook.cancelMaterialProposalReplace();
        assert.equal(h.hook.state.materialProposals.pendingReplace, false); await h.hook.adoptMaterialProposal();
        read = proposalRead(false, 'SOURCE_CHANGED'); assert.equal(await h.hook.confirmMaterialProposalReplace(), false);
        assert.equal(h.hook.state.materials.draft.lesson.title, '手动编辑'); assert.equal(h.hook.state.materialProposals.canAdopt, false);
        read = proposalRead(); await h.hook.refreshMaterialProposal(); await h.hook.adoptMaterialProposal();
        assert.equal(await h.hook.confirmMaterialProposalReplace(), true); assert.equal(h.hook.state.materials.draft.lesson.title, '循环教学');
    } finally { h.scope.stop(); }
});
test('edits made during freshness read cannot be overwritten by a late adoption result', async () => {
    let block = false; const pending = deferred(), h = await harness({ getMaterialProposal: async () => block ? pending.promise : proposalRead(),
        listMaterialProposalRuns: async () => ({ task_id: proposalTaskId, runs: [proposalRun('COMPLETE')] }) });
    try {
        await h.hook.openMaterialProposalRun(proposalRunId); block = true; const adopting = h.hook.adoptMaterialProposal();
        h.hook.updateMaterialsDraft({ lesson: { ...proposalRead().proposal.lesson, title: '检查时新增编辑' }, slides: proposalRead().proposal.slides });
        pending.resolve(proposalRead()); assert.equal(await adopting, false); assert.equal(h.hook.state.materials.draft.lesson.title, '检查时新增编辑');
        assert.equal(h.hook.state.materialProposals.pendingReplace, true);
    } finally { h.scope.stop(); }
});
test('fresh page lists persisted runs and opens only explicitly chosen old preview', async () => {
    const h = await harness({ listMaterialProposalRuns: async () => ({ task_id: proposalTaskId, runs: [proposalRun('COMPLETE')] }), getMaterialProposal: async () => proposalRead(false, 'STALE_INPUT_REVISION') });
    try {
        assert.equal(h.hook.state.materialProposals.history.length, 1); assert.equal(h.hook.state.materialProposals.proposal, null); assert.equal(h.hook.state.materialProposals.sourceMessageId, null);
        assert.equal(await h.hook.openMaterialProposalRun(proposalRunId), true); assert.equal(h.hook.state.materialProposals.proposal.lesson.title, '循环教学');
        assert.equal(h.hook.state.materialProposals.canAdopt, false); assert.equal(h.calls.generate.length, 0);
        assert.ok(h.operations.every(([kind, key]) => kind !== 'set' || key.includes(':ui:')));
    } finally { h.scope.stop(); }
});
test('account task view revision disposal fences reject generation replies and double submission', async () => {
    for (const change of ['actor', 'epoch', 'task', 'view', 'revision', 'dispose']) {
        const pending = deferred(), h = await harness({ generateMaterialProposal: (...args) => { h.calls.generate.push(args); return pending.promise; } });
        try {
            h.hook.selectMaterialProposalSource(proposalMessageId); const sending = h.hook.generateMaterialProposal();
            assert.equal(await h.hook.generateMaterialProposal(), false); assert.equal(h.calls.generate.length, 1);
            if (change === 'actor') h.refs.actor.value = 'teacher-b'; if (change === 'epoch') h.refs.authEpoch.value++;
            if (change === 'task') h.hook.state.task_id = '11111111-1111-4111-8111-111111111111'; if (change === 'view') h.refs.currentView.value = 't_lesson_prep';
            if (change === 'revision') h.hook.state.input_revision++; if (change === 'dispose') h.scope.stop();
            assert.equal(h.calls.generate[0][2].signal.aborted, true, change); pending.resolve(proposalRun('COMPLETE', { operation: 'generate', replayed: false }));
            assert.equal(await sending, false); assert.equal(h.hook.state.materialProposals.proposal, null); assert.notEqual(h.hook.state.materials.draft?.lesson.title, '循环教学');
        } finally { h.scope.stop(); }
    }
});
test('cancel and late complete preserve server facts without adopting or redispatching', async () => {
    const h = await harness({ generateMaterialProposal: async () => proposalRun('PENDING', { operation: 'generate', replayed: false }), cancelMaterialProposal: async () => proposalRun('COMPLETE') });
    try {
        h.hook.selectMaterialProposalSource(proposalMessageId); await h.hook.generateMaterialProposal(); assert.equal(await h.hook.cancelMaterialProposal(), true); await settle();
        assert.equal(h.hook.state.materialProposals.status, 'complete'); assert.equal(h.hook.state.materialProposals.proposal.lesson.title, '循环教学');
        assert.equal(h.hook.state.materials.draft.lesson.title, ''); assert.equal(h.scheduled.size, 0);
    } finally { h.scope.stop(); }
});
test('active proposal blocks competing chat and material writes while preserving editable draft', async () => {
    let chatSends = 0; const h = await harness({ generateMaterialProposal: async () => proposalRun('PENDING', { operation: 'generate', replayed: false }),
        sendMessage: async () => { chatSends++; return { run_id: proposalRunId, task_id: proposalTaskId, kind: 'chat', input_revision: 1, stage: 'PENDING',
            attempt: 1, provider_call_count: 0, deadline: instant, cancelled_at: null, error_code: null }; } });
    try {
        h.hook.updateMaterialsDraft({ lesson: proposalRead().proposal.lesson, slides: proposalRead().proposal.slides }); assert.equal(h.hook.state.materials.canSave, true);
        h.hook.selectMaterialProposalSource(proposalMessageId); assert.equal(await h.hook.generateMaterialProposal(), true); assert.equal(h.hook.state.materialProposalBusy, true);
        assert.equal(h.hook.state.materials.canSave, false); h.hook.state.privateChatAvailability = { send: true, history: false, read_run: true, cancel: true, provider_configured: true, external_provider_verified: false };
        h.hook.updateChatText('另一个问题'); assert.equal(await h.hook.sendChat(), false); assert.equal(chatSends, 0);
        h.hook.updateMaterialsDraft({ lesson: { ...proposalRead().proposal.lesson, title: '生成过程中仍可编辑' }, slides: proposalRead().proposal.slides });
        assert.equal(h.hook.state.materials.draft.lesson.title, '生成过程中仍可编辑');
    } finally { h.scope.stop(); }
});
test('keep-current aborts pending replace freshness read and rejects late candidate', async () => {
    let block = false, adoptionSignal = null; const pending = deferred(), h = await harness({ listMaterialProposalRuns: async () => ({ task_id: proposalTaskId, runs: [proposalRun('COMPLETE')] }),
        getMaterialProposal: async (_task, _run, options) => { if (block) { adoptionSignal = options.signal; return pending.promise; } return proposalRead(); } });
    try {
        await h.hook.openMaterialProposalRun(proposalRunId); h.hook.updateMaterialsDraft({ lesson: { ...proposalRead().proposal.lesson, title: '保留教师编辑' }, slides: proposalRead().proposal.slides });
        await h.hook.adoptMaterialProposal(); block = true; const adopting = h.hook.confirmMaterialProposalReplace(); assert.equal(h.hook.cancelMaterialProposalReplace(), true);
        assert.equal(adoptionSignal.aborted, true); pending.resolve(proposalRead()); assert.equal(await adopting, false);
        assert.equal(h.hook.state.materials.draft.lesson.title, '保留教师编辑'); assert.equal(h.hook.state.materialProposals.pendingReplace, false);
    } finally { h.scope.stop(); }
});
test('proposal busy transition refreshes approved-package creation affordance', async () => {
    const approved = materialsSnapshot('approve'); approved.input_revision = 1; approved.working_revision = 1; approved.outline.input_revision = 1; approved.approval.input_revision = 1; approved.receipt = null;
    const h = await harness({ getMaterials: async () => approved, getPackagesCapabilities: async () => ({ create: true, read: true, retry: true, download: true, storage_configured: true, reasons: {} }),
        listPackages: async () => ({ task_id: proposalTaskId, items: [], next_before: null, truncated: false }), generateMaterialProposal: async () => proposalRun('PENDING', { operation: 'generate', replayed: false }) });
    try { assert.equal(h.hook.state.packages.canCreate, true); h.hook.selectMaterialProposalSource(proposalMessageId); await h.hook.generateMaterialProposal();
        assert.equal(h.hook.state.materialProposalBusy, true); assert.equal(h.hook.state.packages.canCreate, false);
    } finally { h.scope.stop(); }
});
