import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import { Vue, settle, globals, context, authRefs, deferred, capabilityFacts, response } from './fixtures/teacherWorkHarness.mjs';

const stateURL = new URL('../js/controllers/teacherWorkState.js', import.meta.url);
const apiURL = new URL('../js/api/teacherWork.js', import.meta.url);
const hookURL = new URL('../js/hooks/useTeacherWork.js', import.meta.url);
const imports = new Map([
    [stateURL.href, () => import('../js/controllers/teacherWorkState.js')],
    [apiURL.href, () => import('../js/api/teacherWork.js')],
    [hookURL.href, () => import('../js/hooks/useTeacherWork.js')]
]);
async function required(url) { assert.ok(existsSync(url), 'Task5a feature missing: ' + url.pathname.split('/').at(-1)); return imports.get(url.href)(); }
async function fresh() { const module = await required(stateURL), state = module.createTeacherWorkState(); module.synchronizeTeacherWork(state, context()); return { module, state }; }
function restricted(state) {
    state.tasks.push({ id: 'synthetic-task' }); state.messages.push({ id: 'synthetic-message' });
    state.artifacts.push({ id: 'synthetic-artifact' }); state.versions.push({ id: 'synthetic-version' }); state.sources.push({ id: 'synthetic-source' });
    state.composerText = 'private test-only input'; state.run_id = 'synthetic-run';
}
function assertCleared(state) {
    for (const key of ['tasks', 'messages', 'artifacts', 'versions', 'sources']) assert.deepEqual(state[key], []);
    assert.equal(state.composerText, ''); assert.equal(state.task_id, null); assert.equal(state.run_id, null);
}

test('T5a09 request token matches all seven fields and requires active verified teacher', async () => {
    globals(); const { module, state } = await fresh();
    module.selectTeacherTask(state, { task_id: 'synthetic-task', input_revision: 7 }); state.run_id = 'synthetic-run';
    const token = module.captureRequest(state);
    assert.deepEqual(Object.keys(token).sort(), ['actor', 'role', 'authEpoch', 'task_id', 'input_revision', 'view_epoch', 'run_id'].sort());
    assert.equal(Object.isFrozen(token), true); assert.equal(module.acceptResponse(state, token), true);
    for (const field of Object.keys(token)) {
        const original = state[field]; state[field] = typeof original === 'number' ? original + 1 : 'changed';
        assert.equal(module.acceptResponse(state, token), false, field); state[field] = original;
    }
    for (const changes of [{ authVerified: false }, { active: false }, { role: 'student' }]) {
        const altered = { ...state, ...changes }; assert.equal(module.acceptResponse(altered, token), false);
        assert.equal(module.captureRequest(altered), null);
    }
});

test('T5a10 account role auth epoch and verification changes discard replies and clear restricted memory', async () => {
    globals();
    for (const changes of [{ actor: 'teacher-b' }, { role: 'student' }, { authEpoch: 5 }, { authVerified: false }]) {
        const { module, state } = await fresh(); module.selectTeacherTask(state, { task_id: 'synthetic-task', input_revision: 2 });
        restricted(state); const token = module.captureRequest(state);
        module.synchronizeTeacherWork(state, { ...context(), ...changes }); assertCleared(state);
        assert.equal(module.acceptResponse(state, token), false);
        assert.equal(module.applyCapabilityResult(state, token, { status: 'ready', data: capabilityFacts(), reason: null }), false);
    }
});

test('T5a11 task input view run and local cancellation changes reject old replies', async () => {
    globals();
    for (const change of ['task', 'input', 'view', 'run', 'cancel']) {
        const { module, state } = await fresh(); module.selectTeacherTask(state, { task_id: 'synthetic-task', input_revision: 2 });
        restricted(state); const token = module.captureRequest(state);
        if (change === 'task') module.selectTeacherTask(state, { task_id: 'different-task', input_revision: 2 });
        if (change === 'input') state.input_revision++;
        if (change === 'view') module.synchronizeTeacherWork(state, { ...context(), active: false });
        if (change === 'run') state.run_id = 'different-run';
        if (change === 'cancel') module.invalidateTeacherWork(state, 'local-cancel');
        assert.equal(module.acceptResponse(state, token), false, change);
        assert.equal(module.recordTeacherOperationFailure(state, token, 'chat', 'network_error'), false);
        if (change === 'view' || change === 'cancel') assertCleared(state);
    }
});

test('T5a12 chat and save failures preserve input without appending successful history', async () => {
    globals(); const { module, state } = await fresh();
    module.selectTeacherTask(state, { task_id: 'synthetic-task', input_revision: 2 });
    module.updateTeacherInput(state, 'copyable unsent teacher text'); const token = module.captureRequest(state);
    for (const operation of ['chat', 'save']) {
        assert.equal(module.recordTeacherOperationFailure(state, token, operation, 'network_error'), true);
        assert.equal(state.composerText, 'copyable unsent teacher text'); assert.equal(state.composerStatus, 'unsaved');
        assert.deepEqual(state.messages, []); assert.deepEqual(state.artifacts, []); assert.equal(state.input_revision, 2);
        assert.equal(state.operationError.operation, operation);
    }
});

test('T5a13 capability transport keeps its fixed GET and rejects unavailable 503 honestly', async () => {
    globals(); const { createTeacherWorkApi } = await required(apiURL), calls = [];
    const api = createTeacherWorkApi({ getToken: () => 'synthetic-session', dispatchAuthExpired() { assert.fail('unexpected expiry'); },
        fetchImpl: async (url, options) => { calls.push({ url, options }); return response(503, { code: 503, message: 'TEACHER_WORK_UNAVAILABLE', data: null }); } });
    assert.deepEqual(Object.keys(api), ['getCapabilities', 'getMaterialsCapabilities', 'getMaterials', 'saveMaterials', 'approveMaterials',
        'listResources', 'createTask', 'getTask', 'updateWorking', 'sendMessage', 'listMessages', 'getRun', 'cancelRun']);
    for (const name of ['chat', 'generate', 'saveDraft', 'publish', 'deleteTask', 'listTasks']) assert.equal(api[name], undefined);
    await assert.rejects(api.getCapabilities(), error => error.name === 'TeacherWorkError' && error.status === 503 && error.reason === 'TEACHER_WORK_UNAVAILABLE');
    assert.equal(calls.length, 1); assert.ok(calls[0].url.endsWith('/api/teacher/work/capabilities'));
    assert.equal(calls[0].options.method, 'GET'); assert.equal(calls[0].options.body, undefined);
    assert.equal(calls[0].options.headers.Authorization, 'Bearer synthetic-session');
});

test('T5a14 malformed network and server failures never expose raw backend content', async () => {
    globals(); const { createTeacherWorkApi } = await required(apiURL);
    const privatePayload = 'private backend path /var/secret, stack and prompt';
    for (const transport of [
        async () => { throw new Error(privatePayload); }, async () => response(500, { code: 500, message: privatePayload, data: { secret: privatePayload } }),
        async () => response(200, privatePayload), async () => response(200, { code: 200, message: 'ok', data: { ...capabilityFacts(), publish: true } }),
        async () => response(200, { code: 200, message: 'ok', data: { ...capabilityFacts(), unexpected: privatePayload } })
    ]) {
        const api = createTeacherWorkApi({ fetchImpl: transport, getToken: () => 'synthetic-session', dispatchAuthExpired() {} });
        await assert.rejects(api.getCapabilities(), error => {
            assert.equal(error.name, 'TeacherWorkError'); assert.doesNotMatch(error.message, /private backend|var\/secret|stack|prompt/);
            assert.doesNotMatch(JSON.stringify(error), /private backend|var\/secret/); return true;
        });
    }
});

test('T5a15 replaced token or aborted transport discards late success and late auth expiry', async () => {
    globals(); const { createTeacherWorkApi } = await required(apiURL);
    for (const status of [200, 401]) {
        let token = 'synthetic-old-session', expired = 0; const pending = deferred();
        const api = createTeacherWorkApi({ fetchImpl: () => pending.promise, getToken: () => token, dispatchAuthExpired: () => expired++ });
        const result = api.getCapabilities(); token = 'synthetic-new-session';
        pending.resolve(response(status, status === 200 ? { code: 200, message: 'ok', data: capabilityFacts() } : { code: 401, message: 'auth_required', data: null }));
        await assert.rejects(result, error => error.reason === 'request_aborted'); assert.equal(expired, 0);
    }
    const pending = deferred(), controller = new AbortController();
    const api = createTeacherWorkApi({ fetchImpl: () => pending.promise, getToken: () => 'synthetic-session', dispatchAuthExpired() {} });
    const result = api.getCapabilities({ signal: controller.signal }); controller.abort();
    pending.resolve(response(200, { code: 200, message: 'ok', data: capabilityFacts() }));
    await assert.rejects(result, error => error.reason === 'request_aborted');
});

test('T5a16 even ready capability JSON cannot activate unsupplied staged operations', async () => {
    globals(); const { module, state } = await fresh();
    assert.equal(module.applyCapabilityResult(state, module.captureRequest(state), { status: 'ready', data: capabilityFacts(), reason: null }), true);
    assert.equal(state.capabilities.status, 'ready'); assert.equal(state.capabilities.data.chat, true);
    assert.deepEqual(state.operationAvailability, { task_write: false, chat: false, generate: false, storage: false });
    assert.equal(state.operationUnavailableReason, 'TEACHER_WORK_OPERATIONS_UNWIRED');
    assert.deepEqual(state.tasks, []); assert.deepEqual(state.messages, []);
});

test('T5a17 mounted lifecycle aborts capability read and rejects old account reply synchronously', async () => {
    const { storage, eventTarget } = globals(), { useTeacherWork } = await required(hookURL), refs = authRefs(), calls = [];
    const api = { getCapabilities(options) { const pending = deferred(); calls.push({ ...pending, options }); return pending.promise; } };
    const scope = Vue.effectScope(), hook = scope.run(() => useTeacherWork(refs, { api, storage, eventTarget,
        viewportTarget: { innerWidth: 1440 }, documentTarget: document }));
    try {
        assert.equal(calls.length, 1); restricted(hook.state);
        refs.actor.value = 'teacher-b'; assertCleared(hook.state); assert.equal(calls[0].options.signal.aborted, true);
        assert.equal(calls.length, 2); assert.equal(hook.state.actor, 'teacher-b');
        calls[1].reject(Object.assign(new Error('synthetic current closure'), { reason: 'TEACHER_WORK_UNAVAILABLE', status: 503 })); await settle();
        calls[0].resolve(capabilityFacts()); await settle();
        assert.equal(hook.state.capabilities.status, 'unavailable'); assert.equal(hook.state.capabilities.reason, 'TEACHER_WORK_UNAVAILABLE');
        assert.deepEqual(hook.state.messages, []);
    } finally { scope.stop(); }
});

test('T5a18 active view departure clears restricted memory and does not poll or cancel upstream', async () => {
    const { storage, eventTarget } = globals(), { useTeacherWork } = await required(hookURL), refs = authRefs(), pending = deferred();
    let reads = 0, signal;
    const api = { getCapabilities(options) { reads++; signal = options.signal; return pending.promise; } };
    const scope = Vue.effectScope(), hook = scope.run(() => useTeacherWork(refs, { api, storage, eventTarget,
        viewportTarget: { innerWidth: 1024 }, documentTarget: document }));
    try {
        restricted(hook.state); refs.currentView.value = 't_lesson_prep'; assertCleared(hook.state);
        assert.equal(signal.aborted, true); assert.equal(hook.state.active, false);
        pending.resolve(capabilityFacts()); await settle(); assert.equal(reads, 1);
        assert.equal(hook.state.capabilities.status, 'idle');
        assert.deepEqual(Object.keys(api), ['getCapabilities'], 'no fake run/cancel/poll transport');
    } finally { scope.stop(); }
});

test('T5a19 foreign future and malformed preferences cannot restore authorization or student state', async () => {
    globals(); const { module, state } = await fresh(); const reads = [];
    for (const raw of ['{invalid', '[]', '{"version":99,"actor":"teacher-b","authVerified":true,"messages":[1]}',
        '{"navCollapsed":"true","artifactTab":"admin","token":"not a real token","task_id":"foreign"}']) {
        const store = { getItem(key) { reads.push(key); return raw; }, setItem() { assert.fail('read must not write'); } };
        module.readTeacherWorkPreferences(state, store);
        assert.equal(state.ui.navCollapsed, false); assert.equal(state.ui.artifactTab, 'files');
        assert.equal(state.actor, 'teacher-a'); assert.equal(state.task_id, null); assert.deepEqual(state.messages, []);
    }
    assert.deepEqual([...new Set(reads)], ['teacher_work:teacher-a:teacher:ui:v1']);
    module.synchronizeTeacherWork(state, { ...context(), authVerified: false });
    module.readTeacherWorkPreferences(state, { getItem() { assert.fail('unverified identity cannot hydrate preferences'); } });
    assert.equal(module.teacherWorkPreferenceKey(state), null);
});
