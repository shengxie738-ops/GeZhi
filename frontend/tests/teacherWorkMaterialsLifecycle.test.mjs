import test from 'node:test';
import assert from 'node:assert/strict';
import { Vue, globals, authRefs, deferred, settle, capabilityFacts } from './fixtures/teacherWorkHarness.mjs';

const taskA = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', taskB = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const outlineA = '11111111-1111-4111-8111-111111111111', outlineB = '22222222-2222-4222-8222-222222222222';
const approvalA = '33333333-3333-4333-8333-333333333333';
const digest = 'a'.repeat(64), source = 'b'.repeat(64);
const instant = '2026-10-06T00:00:00+00:00';
const facts = () => ({ ...capabilityFacts(), chat: false, generate: false, storage: false,
    private_tasks: { create: true, read: true, update: true } });
const task = (id = taskA, revision = 1) => ({ task_id: id, scope: 'private', title: '循环教学', topic: '循环', audience: '一年级',
    duration_minutes: 45, target_slide_count: 6, input_revision: revision, working_revision: revision, created_at: instant, updated_at: instant,
    working: { requirements: '已保存需求', resource_ids: ['courseware-one'], needs_normalization_fields: [] } });
export const lesson = (title = '手动课时') => ({ title, topic: '', course_name: '', audience: '', duration_minutes: 45,
    objectives: [], key_points: [], difficulties: [], questions: [], exercises: [], homework: [], summary: '',
    teaching_flow: [{ stage: '讲授', minutes: 45, content: '教师录入内容' }], citations: [] });
export const slides = () => Array.from({ length: 6 }, (_, i) => ({ layout: 'bullets', title: `第${i + 1}页`, body: ['教师录入'],
    columns: [], notes: '', source_note: '', evidence_refs: [] }));
const outline = (id = outlineA, revision = 1, input = 2) => ({ outline_id: id, task_id: taskA, input_revision: input, outline_revision: revision,
    lesson: lesson(), slides: slides(), source_digest: source, outline_digest: digest, skill_versions: [], created_at: instant });
const materials = (overrides = {}) => ({ task_id: taskA, input_revision: 1, working_revision: 1, last_outline_revision: 0,
    current_outline_id: null, outline: null, approval: null, source_status: 'unprepared', current_source_digest: source,
    needs_normalization_fields: [], approval_eligible: false, approval_current: false, approval_blocker: 'NO_OUTLINE', receipt: null, ...overrides });
const saved = (overrides = {}) => materials({ input_revision: 2, working_revision: 2, last_outline_revision: 1, current_outline_id: outlineA,
    outline: outline(), source_status: 'current', current_source_digest: source, approval_eligible: true, approval_blocker: null,
    receipt: { operation: 'save', outline_id: outlineA, approval_id: null, input_revision: 2, working_revision: 2, replayed: false }, ...overrides });
const caps = () => ({ save: true, read: true, approve: true, source_configured: true, files: false, reasons: { files: 'files_not_enabled' } });
async function harness(overrides = {}) {
    const env = globals(), refs = authRefs(), calls = { read: [], save: [], approve: [] }, location = new URL('https://example.invalid/?teacher_work_task=' + taskA);
    const api = { getCapabilities: async () => facts(), listResources: async () => [], getTask: async id => task(id),
        getMaterialsCapabilities: async () => caps(), getMaterials: async (...args) => { calls.read.push(args); return materials({ task_id: args[0] }); },
        saveMaterials: async (...args) => { calls.save.push(args); return saved(); },
        approveMaterials: async (...args) => { calls.approve.push(args); return saved({ working_revision: 3, receipt: { operation: 'approve', outline_id: outlineA,
            approval_id: approvalA, input_revision: 2, working_revision: 3, replayed: false }, approval_current: true,
            approval: { approval_id: approvalA, task_id: taskA, outline_id: outlineA, input_revision: 2, outline_revision: 1,
                outline_digest: digest, source_digest: source, confirmed_at: instant } }); }, ...overrides };
    const { useTeacherWork } = await import('../js/hooks/useTeacherWork.js');
    const scope = Vue.effectScope(); let keys = 0;
    const hook = scope.run(() => useTeacherWork(refs, { api, storage: env.storage, documentTarget: document, eventTarget: env.eventTarget,
        viewportTarget: { innerWidth: 1440 }, location, history: { replaceState() {} }, newIdempotencyKey: () => `materials-${++keys}` }));
    await settle(); return { hook, scope, refs, calls, ...env };
}
const fill = hook => hook.updateMaterialsDraft({ lesson: lesson(), slides: slides() });

test('manual materials initializes a blank task-aligned draft and opens only its separate capability', async () => {
    const h = await harness();
    try { assert.ok(h.hook.state.materials, 'materials lifecycle state exists');
        assert.equal(h.hook.state.materials.capabilities.status, 'ready'); assert.equal(h.hook.state.materials.draft.lesson.title, '');
        assert.equal(h.hook.state.materials.draft.lesson.duration_minutes, 45); assert.equal(h.hook.state.materials.draft.slides.length, 6);
        assert.equal(h.hook.state.materials.canSave, false); assert.equal(h.hook.state.materials.canApprove, false);
        assert.equal(h.hook.state.materials.capabilities.data.files, false);
    } finally { h.scope.stop(); }
});

test('manual save and exact approval advance shared revisions while requirements and chat drafts remain untouched', async () => {
    const h = await harness();
    try { h.hook.updateInput('尚未保存需求'); h.hook.updateChatText('尚未发送问题'); fill(h.hook);
        assert.equal(h.hook.state.materials.canSave, false, 'save requirements first before freezing content');
        h.hook.state.composerText = '已保存需求'; h.hook.state.composerStatus = 'saved'; await settle();
        assert.equal(h.hook.state.materials.canSave, true); assert.equal(await h.hook.saveMaterials(), true);
        assert.deepEqual(h.calls.save[0][1], { expected_revision: 1, input_revision: 1, expected_outline_revision: 0, lesson: lesson(), slides: slides() });
        assert.equal(h.hook.state.input_revision, 2); assert.equal(h.hook.state.task.input_revision, 2);
        assert.equal(h.hook.state.working_revision, 2); assert.equal(h.hook.state.chatText, '尚未发送问题');
        assert.equal(h.hook.state.materials.dirty, false); assert.equal(h.hook.state.materials.canApprove, true);
        assert.equal(await h.hook.approveMaterials(), true); assert.equal(h.hook.state.working_revision, 3);
        assert.equal(h.hook.state.input_revision, 2); assert.equal(h.hook.state.materials.snapshot.approval_current, true);
        assert.deepEqual(h.calls.approve[0][1], { input_revision: 2, outline_revision: 1, outline_digest: digest, source_digest: source });
        fill(h.hook); h.hook.updateMaterialsDraft({ lesson: lesson('新编辑'), slides: slides() });
        assert.equal(h.hook.state.materials.canApprove, false); assert.equal(await h.hook.approveMaterials(), false);
        assert.equal(h.calls.approve.length, 1);
    } finally { h.scope.stop(); }
});

test('409 retains all manual content and explicit reload keeps it until replace choice', async () => {
    let current = materials(); const h = await harness({ getMaterials: async () => current, getTask: async () => task(taskA, current.input_revision),
        saveMaterials: async () => { throw { reason: 'revision_conflict', status: 409 }; } });
    try { fill(h.hook); h.hook.updateMaterialsDraft({ lesson: lesson('保留的手动输入'), slides: slides() });
        assert.equal(await h.hook.saveMaterials(), false); assert.equal(h.hook.state.materials.conflict, true);
        current = saved({ receipt: null }); assert.equal(await h.hook.reloadMaterials(), true); await settle();
        assert.equal(h.hook.state.materials.draft.lesson.title, '保留的手动输入'); assert.equal(h.hook.state.materials.dirty, true);
        assert.equal(h.hook.state.materials.pendingReplace, true); assert.equal(h.hook.state.input_revision, 2);
        h.hook.cancelMaterialsReplace(); assert.equal(h.hook.state.materials.draft.lesson.title, '保留的手动输入');
        await h.hook.reloadMaterials(); assert.equal(h.hook.replaceMaterialsDraft(), true);
        assert.equal(h.hook.state.materials.draft.lesson.title, '手动课时'); assert.equal(h.hook.state.materials.dirty, false);
        assert.equal(h.hook.state.materials.canApprove, true);
    } finally { h.scope.stop(); }
});

test('unknown save result only retries the frozen original operation even after draft editing', async () => {
    const calls = []; const h = await harness({ saveMaterials: async (...args) => { calls.push(args); if (calls.length === 1) throw { reason: 'network_error' }; return saved(); } });
    try { fill(h.hook); assert.equal(await h.hook.saveMaterials(), false); assert.equal(h.hook.state.materials.status, 'uncertain');
        assert.equal(h.hook.state.materials.retryAvailable, true); assert.equal(await h.hook.saveMaterials(), false);
        h.hook.updateMaterialsDraft({ lesson: lesson('后续编辑'), slides: slides() });
        assert.equal(await h.hook.retryMaterials(), true); assert.deepEqual(calls[1][1], calls[0][1]);
        assert.equal(calls[1][2].idempotencyKey, calls[0][2].idempotencyKey); assert.equal(h.hook.state.materials.draft.lesson.title, '后续编辑');
        assert.equal(h.hook.state.materials.dirty, true); assert.equal(h.hook.state.materials.canApprove, false);
        assert.equal(h.hook.state.materials.retryAvailable, false);
    } finally { h.scope.stop(); }
});

test('replayed old operation receipt cannot be mistaken for the latest current outline', async () => {
    const h = await harness({ saveMaterials: async () => saved({ input_revision: 3, working_revision: 4, last_outline_revision: 2,
        current_outline_id: outlineB, outline: outline(outlineB, 2, 3), receipt: { operation: 'save', outline_id: outlineA,
            approval_id: null, input_revision: 2, working_revision: 2, replayed: true } }) });
    try { fill(h.hook); assert.equal(await h.hook.saveMaterials(), true); assert.equal(h.hook.state.materials.snapshot.current_outline_id, outlineB);
        assert.equal(h.hook.state.materials.lastReceipt.outline_id, outlineA); assert.equal(h.hook.state.materials.dirty, true);
        assert.equal(h.hook.state.materials.canApprove, false); assert.equal(h.hook.state.materials.pendingReplace, true);
    } finally { h.scope.stop(); }
});

test('task duration/count mismatch and invalid schema block save without dropping editable values', async () => {
    const h = await harness();
    try { fill(h.hook); const invalid = { lesson: { ...lesson(), duration_minutes: 44, teaching_flow: [{ stage: '讲授', minutes: 44, content: '内容' }] }, slides: slides() };
        h.hook.updateMaterialsDraft(invalid); assert.equal(h.hook.state.materials.draft.lesson.duration_minutes, 44);
        assert.equal(h.hook.state.materials.canSave, false); assert.equal(await h.hook.saveMaterials(), false);
        h.hook.updateMaterialsDraft({ lesson: lesson(), slides: [...slides(), slides()[0]] }); assert.equal(h.hook.state.materials.canSave, false);
        h.hook.updateMaterialsDraft({ lesson: lesson(), slides: [{ ...slides()[0], title: '<img src=x>' }, ...slides().slice(1)] });
        assert.equal(h.hook.state.materials.canSave, false); assert.equal(h.calls.save.length, 0);
    } finally { h.scope.stop(); }
});

test('source drift normalization and unavailable legacy materials never falsely approve or disable private tasks', async () => {
    for (const changes of [{ source_status: 'changed', current_source_digest: 'c'.repeat(64), approval_blocker: 'SOURCE_CHANGED' },
        { source_status: 'unavailable', current_source_digest: null, approval_blocker: 'MATERIAL_SOURCES_UNAVAILABLE' },
        { needs_normalization_fields: ['unknown.field'], approval_blocker: 'NORMALIZATION_REQUIRED' }]) {
        const h = await harness({ getTask: async () => task(taskA, 2), getMaterials: async () => saved({ receipt: null, approval_eligible: false, ...changes }) });
        try { assert.equal(h.hook.state.materials.canApprove, false); assert.equal(await h.hook.approveMaterials(), false);
            assert.equal(h.hook.state.privateTaskAvailability.update, true); } finally { h.scope.stop(); }
    }
    const legacy = await harness({ getMaterialsCapabilities: async () => { throw { status: 404, reason: 'TEACHER_WORK_UNAVAILABLE' }; } });
    try { assert.equal(legacy.hook.state.materials.capabilities.status, 'unavailable'); assert.equal(legacy.hook.state.privateTaskAvailability.read, true);
        assert.equal(legacy.hook.state.task_id, taskA); } finally { legacy.scope.stop(); }
});

test('materials double-click and auth task view races reject stale results and retain same-session task draft', async () => {
    const { clearTeacherTaskSelection } = await import('../js/controllers/teacherWorkState.js');
    for (const change of ['task', 'actor', 'epoch', 'view', 'dispose']) {
        const pending = deferred(), calls = []; const h = await harness({ saveMaterials: (...args) => { calls.push(args); return pending.promise; } });
        try { fill(h.hook); const sending = h.hook.saveMaterials(); assert.equal(await h.hook.saveMaterials(), false); assert.equal(calls.length, 1);
            if (change === 'task') {
                assert.equal(await h.hook.readTask(taskB), false); assert.equal(calls[0][2].signal.aborted, false);
                clearTeacherTaskSelection(h.hook.state); await h.hook.readTask(taskB);
            }
            if (change === 'actor') h.refs.actor.value = 'teacher-b';
            if (change === 'epoch') h.refs.authEpoch.value++;
            if (change === 'view') h.refs.currentView.value = 't_lesson_prep';
            if (change === 'dispose') h.scope.stop();
            assert.equal(calls[0][2].signal.aborted, true, change); pending.resolve(saved()); assert.equal(await sending, false);
            assert.notEqual(h.hook.state.materials.snapshot?.current_outline_id, outlineA);
            if (change === 'task') { await h.hook.readTask(taskA); await settle(); assert.equal(h.hook.state.materials.draft.lesson.title, '手动课时');
                assert.equal(h.hook.state.materials.retryAvailable, true); }
            if (change === 'view') { h.refs.currentView.value = 't_work'; await settle(); assert.equal(h.hook.state.materials.draft.lesson.title, '手动课时'); }
        } finally { h.scope.stop(); }
    }
});

test('edits made during save remain dirty and a parent task revision change aborts stale completion', async () => {
    const pending = deferred(), h = await harness({ saveMaterials: () => pending.promise });
    try { fill(h.hook); const saving = h.hook.saveMaterials(); h.hook.updateMaterialsDraft({ lesson: lesson('保存途中编辑'), slides: slides() });
        h.hook.updateInput('保存途中需求'); h.hook.updateChatText('保存途中问题'); pending.resolve(saved()); assert.equal(await saving, true);
        assert.equal(h.hook.state.materials.draft.lesson.title, '保存途中编辑'); assert.equal(h.hook.state.materials.canApprove, false);
        assert.equal(h.hook.state.composerText, '保存途中需求'); assert.equal(h.hook.state.chatText, '保存途中问题');
    } finally { h.scope.stop(); }
    const old = deferred(), calls = [], changed = await harness({ saveMaterials: (...args) => { calls.push(args); return old.promise; } });
    try { fill(changed.hook); const saving = changed.hook.saveMaterials(); changed.hook.state.input_revision = 3; changed.hook.state.working_revision = 3;
        assert.equal(calls[0][2].signal.aborted, true); old.resolve(saved()); assert.equal(await saving, false);
        assert.equal(changed.hook.state.input_revision, 3); assert.equal(changed.hook.state.materials.draft.lesson.title, '手动课时');
    } finally { changed.scope.stop(); }
});

test('current save response must match the exact submitted frozen content before marking a draft saved', async () => {
    const h = await harness({ saveMaterials: async () => saved({ outline: { ...outline(), lesson: lesson('服务器替换的错误内容') } }) });
    try { fill(h.hook); assert.equal(await h.hook.saveMaterials(), false); assert.equal(h.hook.state.materials.dirty, true);
        assert.equal(h.hook.state.materials.draft.lesson.title, '手动课时'); assert.equal(h.hook.state.materials.status, 'uncertain');
        assert.equal(h.hook.state.input_revision, 1); assert.equal(h.hook.state.materials.canApprove, false);
    } finally { h.scope.stop(); }
});

test('unknown approval retries its original exact version when newer current outline exists', async () => {
    let reads = saved({ receipt: null }), attempts = 0; const calls = [];
    const h = await harness({ getTask: async () => task(taskA, 2), getMaterials: async () => reads,
        approveMaterials: async (...args) => { calls.push(args); if (++attempts === 1) throw { reason: 'network_error' };
            return saved({ input_revision: 3, working_revision: 5, last_outline_revision: 2, current_outline_id: outlineB,
                outline: outline(outlineB, 2, 3), receipt: { operation: 'approve', outline_id: outlineA, approval_id: approvalA,
                    input_revision: 2, working_revision: 3, replayed: true } }); } });
    try { assert.equal(await h.hook.approveMaterials(), false);
        reads = saved({ input_revision: 3, working_revision: 4, last_outline_revision: 2, current_outline_id: outlineB, outline: outline(outlineB, 2, 3), receipt: null });
        await h.hook.reloadMaterials(); assert.equal(await h.hook.retryMaterials(), true); assert.deepEqual(calls[1][1], calls[0][1]);
        assert.equal(calls[1][2].idempotencyKey, calls[0][2].idempotencyKey); assert.equal(h.hook.state.materials.lastReceipt.outline_id, outlineA);
        assert.equal(h.hook.state.materials.canApprove, false); assert.equal(h.hook.state.materials.dirty, true);
        assert.equal(h.hook.state.materials.pendingReplace, true);
    } finally { h.scope.stop(); }
});

test('closed capabilities abort pending reads and writes, preserve input, and disable visible approval immediately', async () => {
    const pending = deferred(), calls = [], h = await harness({ getTask: async () => task(taskA, 2), getMaterials: async (...args) => {
        calls.push(args); return calls.length === 1 ? saved({ receipt: null }) : pending.promise; } });
    try { assert.equal(h.hook.state.materials.canApprove, true); const reading = h.hook.reloadMaterials();
        h.hook.state.materials.capabilities.data.read = false; h.hook.state.materials.capabilities.data.approve = false;
        assert.equal(calls.at(-1)[1].signal.aborted, true); assert.equal(h.hook.state.materials.canApprove, false);
        pending.resolve(saved({ receipt: null })); assert.equal(await reading, false);
    } finally { h.scope.stop(); }
});

test('materials revision adoption coordinates pending parent task and resource reads instead of leaving spinners stuck', async () => {
    const materialPost = deferred(), taskRead = deferred(); let taskReads = 0;
    const h = await harness({ saveMaterials: () => materialPost.promise, getTask: async id => ++taskReads === 1 ? task(id) : taskRead.promise });
    try { fill(h.hook); const saving = h.hook.saveMaterials(), reading = h.hook.reloadTask();
        assert.equal(h.hook.state.taskReadStatus, 'loading'); materialPost.resolve(saved()); assert.equal(await saving, true);
        assert.equal(h.hook.state.taskReadStatus, 'ready'); assert.equal(h.hook.state.materials.canApprove, true);
        taskRead.resolve(task()); assert.equal(await reading, false); assert.equal(h.hook.state.input_revision, 2);
    } finally { h.scope.stop(); }
    const posted = deferred(), catalog = deferred(); let armed = false;
    const r = await harness({ saveMaterials: () => posted.promise, listResources: async () => armed ? catalog.promise : [] });
    try { fill(r.hook); const saving = r.hook.saveMaterials(); armed = true; const reading = r.hook.loadResources();
        assert.equal(r.hook.state.resourcesStatus, 'loading'); posted.resolve(saved()); assert.equal(await saving, true);
        assert.notEqual(r.hook.state.resourcesStatus, 'loading'); catalog.resolve([]); assert.equal(await reading, false);
        assert.equal(r.hook.state.materials.canApprove, true);
    } finally { r.scope.stop(); }
});

test('stale immutable outline can reopen after parent target count changes so manual revision can be saved', async () => {
    let latest = saved({ receipt: null }); const h = await harness({ getTask: async () => task(taskA, 2), getMaterials: async () => latest,
        updateWorking: async () => ({ ...task(taskA, 3), target_slide_count: 8 }) });
    try { h.hook.updateTargetSlides(8); assert.equal(await h.hook.saveWorking(), true);
        latest = saved({ input_revision: 3, working_revision: 3, approval_eligible: false, approval_blocker: 'STALE_INPUT_REVISION', receipt: null });
        assert.equal(await h.hook.reloadMaterials(), true); assert.equal(h.hook.state.materials.snapshot.outline.slides.length, 6);
        assert.equal(h.hook.state.materials.canApprove, false);
        h.hook.updateMaterialsDraft({ lesson: lesson(), slides: [...slides(), slides()[0], slides()[1]] });
        assert.equal(h.hook.state.materials.canSave, true); assert.equal(h.hook.state.materials.conflict, false);
    } finally { h.scope.stop(); }
});

test('external materials revisions reconcile real parent task fields before any further mutation while retaining local drafts', async () => {
    const realTask = deferred(); let reads = 0, materialsNow = saved({ receipt: null });
    const h = await harness({ getTask: async () => ++reads === 1 ? task(taskA, 2) : realTask.promise,
        getMaterials: async () => materialsNow, updateWorking: async () => { throw new Error('must stay blocked during reconciliation'); } });
    try { h.hook.updateInput('尚未保存的A编辑'); h.hook.updateChatText('保留问题');
        materialsNow = saved({ input_revision: 3, working_revision: 3, approval_eligible: false, approval_blocker: 'STALE_INPUT_REVISION', receipt: null });
        assert.equal(await h.hook.reloadMaterials(), true); assert.equal(h.hook.state.taskConflict, true);
        assert.equal(h.hook.state.materials.canSave, false); assert.equal(await h.hook.saveWorking(), false);
        realTask.resolve({ ...task(taskA, 3), working: { ...task().working, requirements: '另一标签页已保存B' } }); await settle();
        assert.equal(h.hook.state.task.working.requirements, '另一标签页已保存B'); assert.equal(h.hook.state.composerText, '尚未保存的A编辑');
        assert.equal(h.hook.state.chatText, '保留问题'); assert.equal(h.hook.state.taskConflict, false);
        assert.equal(h.hook.state.materials.canSave, false, 'requirements are still unsaved against authoritative B');
    } finally { h.scope.stop(); }
});

test('unknown approval receipt settles even when the same current outline approval is now stale after source drift', async () => {
    let attempts = 0; const h = await harness({ getTask: async () => ({ ...task(taskA, 2), working_revision: attempts ? 3 : 2 }),
        getMaterials: async () => saved({ receipt: null }), approveMaterials: async () => {
            if (++attempts === 1) throw { reason: 'network_error' };
            return saved({ working_revision: 3, source_status: 'changed', current_source_digest: 'c'.repeat(64), approval_eligible: false,
                approval_current: false, approval_blocker: 'SOURCE_CHANGED', approval: { approval_id: approvalA, task_id: taskA, outline_id: outlineA,
                    input_revision: 2, outline_revision: 1, outline_digest: digest, source_digest: source, confirmed_at: instant },
                receipt: { operation: 'approve', outline_id: outlineA, approval_id: approvalA, input_revision: 2, working_revision: 3, replayed: true } }); } });
    try { assert.equal(await h.hook.approveMaterials(), false); assert.equal(await h.hook.retryMaterials(), true);
        assert.equal(h.hook.state.materials.retryAvailable, false); assert.equal(h.hook.state.materials.status, 'ready');
        assert.equal(h.hook.state.materials.snapshot.approval_current, false); assert.equal(h.hook.state.materials.canApprove, false);
        assert.equal(h.hook.state.materials.lastReceipt.approval_id, approvalA);
    } finally { h.scope.stop(); }
});

test('parent revision change aborts a materials read and immediately leaves explicit reload usable', async () => {
    const pending = deferred(); let reads = 0;
    const h = await harness({ getTask: async () => task(taskA, 2), getMaterials: async () => ++reads === 1 ? saved({ receipt: null }) : pending.promise,
        updateWorking: async () => ({ ...task(taskA, 3), working: { ...task().working, requirements: '新保存需求' } }) });
    try { const reading = h.hook.reloadMaterials(); assert.equal(h.hook.state.materials.status, 'loading');
        h.hook.updateInput('新保存需求'); assert.equal(await h.hook.saveWorking(), true);
        assert.notEqual(h.hook.state.materials.status, 'loading'); assert.equal(h.hook.state.materials.conflict, true);
        pending.resolve(saved({ receipt: null })); assert.equal(await reading, false);
        assert.notEqual(h.hook.state.materials.status, 'loading'); assert.equal(h.hook.state.materials.draft.lesson.title, '手动课时');
    } finally { h.scope.stop(); }
});

test('read and approval completions are fenced across actor role auth task view and disposal boundaries', async () => {
    const { clearTeacherTaskSelection } = await import('../js/controllers/teacherWorkState.js');
    for (const operation of ['read', 'approve']) for (const change of ['actor', 'role', 'epoch', 'task', 'view', 'dispose']) {
        const pending = deferred(), calls = []; let armed = false;
        const h = await harness({ getTask: async id => task(id, 2), getMaterials: async (...args) => {
            if (operation === 'read' && armed) { calls.push(args); return pending.promise; }
            return saved({ task_id: args[0], receipt: null, ...(args[0] !== taskA ? { outline: { ...outline(), task_id: args[0] } } : {}) }); },
            approveMaterials: (...args) => { calls.push(args); return pending.promise; } });
        try { armed = true; const request = operation === 'read' ? h.hook.reloadMaterials() : h.hook.approveMaterials();
            assert.equal(calls.length, 1);
            if (change === 'actor') h.refs.actor.value = 'teacher-b';
            if (change === 'role') h.refs.role.value = 'student';
            if (change === 'epoch') h.refs.authEpoch.value++;
            if (change === 'task') {
                if (operation === 'approve') {
                    assert.equal(await h.hook.readTask(taskB), false); assert.equal(calls[0].at(-1).signal.aborted, false);
                }
                clearTeacherTaskSelection(h.hook.state); await h.hook.readTask(taskB);
            }
            if (change === 'view') h.refs.currentView.value = 't_lesson_prep';
            if (change === 'dispose') h.scope.stop();
            assert.equal(calls[0].at(-1).signal.aborted, true, operation + '/' + change);
            pending.resolve(operation === 'read' ? saved({ receipt: null }) : saved({ working_revision: 3,
                approval_current: true, approval: { approval_id: approvalA, task_id: taskA, outline_id: outlineA, input_revision: 2,
                    outline_revision: 1, outline_digest: digest, source_digest: source, confirmed_at: instant },
                receipt: { operation: 'approve', outline_id: outlineA, approval_id: approvalA, input_revision: 2, working_revision: 3, replayed: false } }));
            assert.equal(await request, false); await settle();
            assert.notEqual(h.hook.state.materials.snapshot?.approval_current, true, operation + '/' + change);
        } finally { h.scope.stop(); }
    }
});

test('externally saved current outline with changed count reconciles authoritative task metadata before alignment checks', async () => {
    let taskReads = 0, now = saved({ receipt: null });
    const h = await harness({ getTask: async () => ++taskReads === 1 ? task(taskA, 2) : ({ ...task(taskA, 4), target_slide_count: 8 }),
        getMaterials: async () => now });
    try { now = saved({ input_revision: 4, working_revision: 4, last_outline_revision: 2, current_outline_id: outlineB,
            outline: { ...outline(outlineB, 2, 4), slides: [...slides(), slides()[0], slides()[1]] }, receipt: null });
        assert.equal(await h.hook.reloadMaterials(), true); await settle(); assert.equal(taskReads, 2);
        assert.equal(h.hook.state.task.target_slide_count, 8); assert.equal(h.hook.state.materials.draft.slides.length, 8);
        assert.equal(h.hook.state.materials.snapshot.current_outline_id, outlineB); assert.equal(h.hook.state.materials.canApprove, true);
    } finally { h.scope.stop(); }
});

test('unavailable selected sources close save even when global resource-root capabilities remain open', async () => {
    const h = await harness({ getTask: async () => task(taskA, 2), getMaterials: async () => saved({ receipt: null,
        source_status: 'unavailable', current_source_digest: null, approval_eligible: false, approval_blocker: 'MATERIAL_SOURCES_UNAVAILABLE' }) });
    try { assert.equal(h.hook.state.materials.capabilities.data.save, true); fill(h.hook);
        assert.equal(h.hook.state.materials.canSave, false); assert.equal(await h.hook.saveMaterials(), false);
        assert.equal(h.hook.state.materials.canApprove, false); assert.equal(h.calls.save.length, 0);
        assert.equal(h.hook.state.materials.draft.lesson.title, '手动课时');
    } finally { h.scope.stop(); }
});

test('an unconfigured source root cannot open write actions through contradictory save and approve flags', async () => {
    const h = await harness({ getTask: async () => task(taskA, 2), getMaterials: async () => saved({ receipt: null }),
        getMaterialsCapabilities: async () => ({ save: true, read: true, approve: true, source_configured: false, files: false,
            reasons: { source_configured: 'sources_unavailable', files: 'files_not_enabled' } }) });
    try { assert.equal(h.hook.state.materials.capabilities.data.read, true);
        assert.equal(h.hook.state.materials.canSave, false); assert.equal(h.hook.state.materials.canApprove, false);
        assert.equal(await h.hook.approveMaterials(), false); fill(h.hook); assert.equal(await h.hook.saveMaterials(), false);
    } finally { h.scope.stop(); }
});

test('source-root capability closure aborts an in-flight mutation and preserves its exact uncertain operation', async () => {
    const pending = deferred(), calls = [], h = await harness({ saveMaterials: (...args) => { calls.push(args); return pending.promise; } });
    try { fill(h.hook); const saving = h.hook.saveMaterials(); h.hook.state.materials.capabilities.data.source_configured = false;
        assert.equal(calls[0][2].signal.aborted, true); assert.equal(h.hook.state.materials.retryAvailable, true);
        assert.equal(h.hook.state.materials.canSave, false); pending.resolve(saved()); assert.equal(await saving, false);
        assert.equal(h.hook.state.materials.draft.lesson.title, '手动课时'); assert.equal(await h.hook.retryMaterials(), false);
    } finally { h.scope.stop(); }
});

test('physical whole-draft capacity refusal preserves all edits and a shorter new operation receives a fresh key', async () => {
    const calls = [], h = await harness({ saveMaterials: async (...args) => { calls.push(args); if (calls.length === 1) throw { reason: 'private_draft_too_large', status: 422 };
        return saved({ outline: { ...outline(), lesson: args[1].lesson } }); } });
    try { fill(h.hook); h.hook.updateChatText('未发送问题'); assert.equal(await h.hook.saveMaterials(), false);
        assert.equal(h.hook.state.materials.error.reason, 'private_draft_too_large'); assert.equal(h.hook.state.materials.dirty, true);
        assert.equal(h.hook.state.materials.retryAvailable, false); assert.equal(h.hook.state.materials.status, 'error');
        assert.equal(h.hook.state.materials.draft.lesson.title, '手动课时'); assert.equal(h.hook.state.chatText, '未发送问题');
        h.hook.updateMaterialsDraft({ lesson: lesson('短稿'), slides: slides() }); assert.equal(await h.hook.saveMaterials(), true);
        assert.notEqual(calls[1][2].idempotencyKey, calls[0][2].idempotencyKey); assert.equal(h.hook.state.materials.dirty, false);
    } finally { h.scope.stop(); }
});

test('opaque normalization fields can survive a manual save while exact approval stays closed', async () => {
    const fields = ['opaque_paragraph', 'teaching_flow[0].opaque_stage'];
    const h = await harness({ getMaterials: async () => materials({ needs_normalization_fields: fields }),
        saveMaterials: async () => saved({ needs_normalization_fields: fields, approval_eligible: false, approval_blocker: 'NORMALIZATION_REQUIRED' }) });
    try { fill(h.hook); assert.equal(h.hook.state.materials.canSave, true); assert.equal(await h.hook.saveMaterials(), true);
        assert.deepEqual(h.hook.state.materials.snapshot.needs_normalization_fields, fields);
        assert.equal(h.hook.state.materials.canApprove, false); assert.equal(await h.hook.approveMaterials(), false);
    } finally { h.scope.stop(); }
});
