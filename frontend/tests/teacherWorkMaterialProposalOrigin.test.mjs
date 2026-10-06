// Reconstructed origin tests; prior runs are historical only.
import test from 'node:test';
import assert from 'node:assert/strict';
import { validateMaterialsSaveBody } from '../js/api/teacherWorkMaterials.js';
import { createTeacherWorkApi } from '../js/api/teacherWork.js';
import { useTeacherWorkMaterials } from '../js/hooks/useTeacherWorkMaterials.js';
import { Vue, context, globals, settle, deferred } from './fixtures/teacherWorkHarness.mjs';
import { createTeacherWorkState, synchronizeTeacherWork } from '../js/controllers/teacherWorkState.js';
import { materialLesson, materialSlides, materialsSaveBody, materialsSnapshot, materialsCapabilities, materialsTaskId, materialsDigest } from './fixtures/teacherWorkMaterialsFixtures.mjs';
const runId = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
async function harness(overrides = {}) {
    globals(); const state = Vue.reactive(createTeacherWorkState()), scope = Vue.effectScope(), calls = [];
    const hook = scope.run(() => useTeacherWorkMaterials(state, { newIdempotencyKey: () => 'origin-save', api: {
        getMaterialsCapabilities: async () => materialsCapabilities(), getMaterials: async () => ({ ...materialsSnapshot(),
            input_revision: 1, working_revision: 1, last_outline_revision: 0, current_outline_id: null, outline: null,
            source_status: 'unprepared', approval_eligible: false, approval_blocker: 'NO_OUTLINE' }),
        saveMaterials: async (...args) => { calls.push(args); throw { reason: 'network_error' }; }, ...overrides
    }}));
    synchronizeTeacherWork(state, context()); state.task_id = materialsTaskId; state.input_revision = 1; state.working_revision = 1;
    state.task = { task_id: materialsTaskId, duration_minutes: 45, target_slide_count: 6, working: { requirements: '', resource_ids: [] } };
    state.taskReadStatus = 'ready'; state.composerStatus = 'saved'; state.draftTargetSlideCount = 6;
    await settle(); return { state, hook, scope, calls };
}
const proposal = () => ({ input_revision: 1, source_digest: materialsDigest, lesson: materialLesson(), slides: materialSlides() });
test('materials save adds only optional nullable proposal origin and preserves manual commands', () => {
    for (const origin of [null, runId]) { const command = { ...materialsSaveBody(), origin_proposal_run_id: origin }; assert.deepEqual(validateMaterialsSaveBody(command), command); }
    assert.deepEqual(validateMaterialsSaveBody(materialsSaveBody()), materialsSaveBody());
    for (const origin of ['', 'arbitrary', 1, false, undefined, runId.toUpperCase()]) assert.throws(() => validateMaterialsSaveBody({ ...materialsSaveBody(), origin_proposal_run_id: origin }));
});
test('explicit local fill is dirty retains origin through edits and sends it only at manual save', async () => {
    const h = await harness(); try {
        assert.equal(h.hook.adoptMaterialsProposal(proposal(), runId), true); assert.equal(h.state.materials.dirty, true); assert.equal(h.calls.length, 0);
        h.hook.updateMaterialsDraft({ lesson: { ...materialLesson(), title: '教师修改' }, slides: materialSlides() }); assert.equal(await h.hook.saveMaterials(), false);
        assert.equal(h.calls[0][1].origin_proposal_run_id, runId); assert.equal(h.calls[0][1].lesson.title, '教师修改');
        await h.hook.retryMaterials(); assert.deepEqual(h.calls[1][1], h.calls[0][1]); assert.equal(h.calls[1][2].idempotencyKey, h.calls[0][2].idempotencyKey);
    } finally { h.scope.stop(); }
});
test('stale input or source prevents adopting and saving proposal-origin drafts', async () => {
    const h = await harness(); try {
        assert.equal(h.hook.adoptMaterialsProposal({ ...proposal(), input_revision: 2 }, runId), false);
        assert.equal(h.hook.adoptMaterialsProposal({ ...proposal(), source_digest: 'b'.repeat(64) }, runId), false);
        assert.equal(h.hook.adoptMaterialsProposal(proposal(), runId), true); h.state.materials.snapshot.current_source_digest = 'b'.repeat(64); await settle();
        assert.equal(h.state.materials.canSave, false); assert.equal(await h.hook.saveMaterials(), false); assert.equal(h.calls.length, 0);
    } finally { h.scope.stop(); }
});
test('confirmed origin save consumes origin while preserving edits made during save', async () => {
    const pending = deferred(), h = await harness({ saveMaterials: () => pending.promise }); try {
        assert.equal(h.hook.adoptMaterialsProposal(proposal(), runId), true); const saving = h.hook.saveMaterials();
        h.hook.updateMaterialsDraft({ lesson: { ...materialLesson(), title: '保存途中编辑' }, slides: materialSlides() });
        pending.resolve(materialsSnapshot('save')); assert.equal(await saving, true); assert.equal(h.state.materials.draft.lesson.title, '保存途中编辑');
        assert.equal(h.state.materials.dirty, true); assert.equal(h.state.materials.proposalOrigin, null); assert.equal(h.state.materials.canSave, true);
    } finally { h.scope.stop(); }
});
test('definite origin freshness409 keeps edits and releases uncertain retry operation', async () => {
    for (const [code, reason] of [['STALE_INPUT_REVISION', 'revision_conflict'], ['SOURCE_MESSAGE_INELIGIBLE', 'source_message_ineligible'], ['PROPOSAL_NOT_READY', 'proposal_not_ready']]) {
        const api = createTeacherWorkApi({ getToken: () => 'synthetic-origin-session', fetchImpl: async () => new Response(JSON.stringify({ code: 409, message: code, data: null }), { status: 409 }), dispatchAuthExpired() {} });
        await assert.rejects(api.saveMaterials(materialsTaskId, { ...materialsSaveBody(), origin_proposal_run_id: runId }, { idempotencyKey: 'exact-origin' }), caught => {
            assert.equal(caught.reason, reason); assert.equal(caught.status, 409); return true;
        });
        const h = await harness({ saveMaterials: api.saveMaterials }); try {
            h.hook.adoptMaterialsProposal(proposal(), runId); assert.equal(await h.hook.saveMaterials(), false);
            assert.equal(h.state.materials.dirty, true); assert.equal(h.state.materials.status, 'error'); assert.equal(h.state.materials.retryAvailable, false);
        } finally { h.scope.stop(); }
    }
});
test('confirmed replay consumes matching origin even when another outline is now current', async () => {
    const replay = materialsSnapshot('save'); replay.input_revision = 3; replay.working_revision = 3; replay.last_outline_revision = 2;
    replay.current_outline_id = '11111111-1111-4111-8111-111111111111'; replay.outline.outline_id = replay.current_outline_id;
    replay.outline.input_revision = 3; replay.outline.outline_revision = 2; replay.receipt.replayed = true;
    const h = await harness({ saveMaterials: async () => replay });
    try {
        assert.equal(h.hook.adoptMaterialsProposal(proposal(), runId), true); assert.equal(await h.hook.saveMaterials(), true);
        assert.equal(h.state.materials.proposalOrigin, null, 'confirmed receipt consumes original adoption even if newer outline is current');
        h.state.input_revision = 3; h.state.working_revision = 3; h.state.taskConflict = false; await settle();
        assert.equal(h.state.materials.dirty, true); assert.equal(h.state.materials.canSave, true);
    } finally { h.scope.stop(); }
});
