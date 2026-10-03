import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

// Exercise the real Vue component setup/lifecycle. Resolve Vue from either the
// project install or the supplied offline runtime; API calls stay in memory.
const require = createRequire(import.meta.url);
let vuePath;
try { vuePath = require.resolve('vue'); }
catch { vuePath = require.resolve('../../../.gezhi-runtime/frontend/app-root/node_modules/vue'); }
const vueUrl = pathToFileURL(vuePath).href;
const { createRenderer, reactive, nextTick } = await import(vueUrl);
globalThis.window = Object.assign(new EventTarget(), { location: { hostname: 'localhost' }, setTimeout, clearTimeout });
globalThis.document = Object.assign(new EventTarget(), { fullscreenElement: {}, visibilityState: 'visible', documentElement: {} });
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: { onLine: true } });
const { examCenterApi } = await import('../js/api/examCenter.js');
const source = (await readFile(new URL('../js/components/StudentExamCenter.js', import.meta.url), 'utf8'))
    .replace("from 'vue'", `from '${vueUrl}'`)
    .replace("from '../api/examCenter.js'", `from '${new URL('../js/api/examCenter.js', import.meta.url).href}'`);
const { default: Component } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const renderer = createRenderer({
    createElement: type => ({ type, children: [] }), createText: text => ({ text }), createComment: text => ({ text }),
    insert(child, parent) { parent.children.push(child); }, remove() {}, setText() {}, setElementText() {}, patchProp() {},
    parentNode: () => null, nextSibling: () => null
});
const exam = id => ({ id, title: id, durationMinutes: 30, programming: true });
const detail = id => ({ ...exam(id), remainingSeconds: 600, programmingProblems: [
    { id: 'q1', starterCode: 'starter', publicCases: [{ input: [1], expected: 1, label: 'sample' }] },
    { id: 'q2', starterCode: 'second', publicCases: [] }
] });
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
const settle = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); await nextTick(); };
function mount(t, overrides = {}) {
    const calls = [], toasts = [];
    Object.assign(examCenterApi, {
        getStudentOverview: async () => ({ summary: {}, exams: [], waitingSubjects: [] }),
        getExamDetail: async id => detail(id),
        startExamAttempt: async (id, body) => ({ attemptId: `${id}:${body.userId}`, status: 'started', answers: {}, remainingSeconds: 600 }),
        saveAnswer: async (id, body) => { calls.push(['save', id, JSON.parse(JSON.stringify(body))]); return { attemptId: id, status: 'saved', savedAt: new Date().toISOString() }; },
        submitAttempt: async (id, body) => { calls.push(['submit', id, JSON.parse(JSON.stringify(body))]); return { attemptId: id, status: 'submitted', submittedAt: new Date().toISOString() }; },
        judgeProgramming: async () => { calls.push(['judge']); },
        ...overrides
    });
    const props = reactive({ currentUser: { username: 'alice' } });
    let state;
    const app = renderer.createApp({ setup() { state = Component.setup(props, { emit: (...args) => toasts.push(args) }); return () => null; } });
    app.mount({ children: [] });
    t.after(() => { app.unmount(); navigator.onLine = true; });
    return { state, props, calls, toasts, app };
}
const enter = (state, id = 'A') => state.enterProgrammingRoom(exam(id), { confirmed: true });

test('start/resume restores server answers including empty strings and every answer type', async t => {
    const { state } = mount(t, { startExamAttempt: async () => ({ attemptId: 'server-A', status: 'started', remainingSeconds: 600, answers: { q1: '', choice: ['B', 'C'], essay: 'saved text' } }) });
    await enter(state);
    assert.deepEqual(state.answers.value, { q1: '', choice: ['B', 'C'], essay: 'saved text' });
    assert.equal(state.getEditorCode(), '');
});

test('exam A saves before navigation and exam B uses its own server attempt', async t => {
    const { state, calls } = mount(t);
    await enter(state, 'A'); state.setEditorCode('answer A');
    await state.backToOverview();
    assert.equal(state.attemptId.value, null);
    assert.deepEqual(state.answers.value, {});
    await enter(state, 'B'); state.setEditorCode('answer B');
    await state.flushAnswers();
    assert.deepEqual(calls.filter(c => c[0] === 'save').map(c => [c[1], c[2].answer]), [['A:alice', 'answer A'], ['B:alice', 'answer B']]);
});

test('failed start never enters or announces a successful exam room', async t => {
    const { state, toasts } = mount(t, { startExamAttempt: async () => { throw new Error('Denied'); } });
    await enter(state);
    assert.equal(state.roomMode.value, 'overview');
    assert.equal(state.attemptId.value, null);
    assert.equal(toasts.some(c => c[2] === 'success'), false);
});

test('authoritative zero remaining seconds is preserved rather than a fresh duration', async t => {
    const { state } = mount(t, { getExamDetail: async id => ({ ...detail(id), remainingSeconds: 0 }) });
    await state.openExamDetail(exam('A'));
    assert.equal(state.remainingSeconds.value, 0);
});

test('autosave debounces edits and only reports saved after server acknowledgement', async t => {
    const ack = deferred(), writes = [];
    const { state } = mount(t, { saveAnswer: async (id, body) => { writes.push(body.answer); return ack.promise; } });
    await enter(state); state.setEditorCode('old'); state.setEditorCode('latest');
    assert.equal(state.saveState.value, 'pending');
    await new Promise(resolve => setTimeout(resolve, 700));
    assert.deepEqual(writes, ['latest']);
    assert.equal(state.saveState.value, 'saving');
    ack.resolve({ attemptId: 'A:alice', status: 'saved', savedAt: new Date().toISOString() });
    await settle();
    assert.equal(state.saveState.value, 'saved');
});

test('slow saves serialize newer edits and submit only after latest save acknowledgement', async t => {
    const first = deferred(), writes = [];
    const { state, calls } = mount(t, { saveAnswer: async (id, body) => { writes.push(body.answer); if (writes.length === 1) return first.promise; return { attemptId: id, status: 'saved', savedAt: new Date().toISOString() }; } });
    await enter(state); state.setEditorCode('v1'); const saving = state.flushAnswers();
    await settle(); state.setEditorCode('v2'); const submitting = state.submitAttempt();
    await settle(); assert.equal(calls.length, 0); assert.deepEqual(writes, ['v1']);
    first.resolve({ attemptId: 'A:alice', status: 'saved', savedAt: new Date().toISOString() });
    await saving; await submitting;
    assert.deepEqual(writes, ['v1', 'v2']);
    assert.equal(calls[0][0], 'submit'); assert.equal(calls[0][2].answers.q1, 'v2');
});

test('failed/offline autosave preserves answer and prevents navigation or submission', async t => {
    const { state, calls } = mount(t, { saveAnswer: async () => { throw new Error('network down'); } });
    await enter(state); state.setEditorCode('unsaved');
    await state.backToOverview();
    assert.equal(state.roomMode.value, 'programming'); assert.equal(state.answers.value.q1, 'unsaved');
    assert.equal(state.saveState.value, 'error');
    await state.submitAttempt(); assert.equal(calls.some(c => c[0] === 'submit'), false);
    navigator.onLine = false; await state.flushAnswers(); assert.equal(state.saveState.value, 'offline');
});

test('submission without matching authoritative receipt keeps attempt open and never judges', async t => {
    const { state, calls, toasts } = mount(t, { submitAttempt: async () => ({ status: 'submitted', programmingStatus: 'pending_judge' }) });
    await enter(state); await state.submitAttempt();
    assert.equal(state.roomMode.value, 'programming'); assert.equal(state.attemptId.value, 'A:alice');
    assert.equal(toasts.some(c => c[2] === 'success'), false);
    assert.equal(calls.some(c => c[0] === 'judge'), false);
});

test('slow earlier entry cannot overwrite newer exam context', async t => {
    const slow = deferred();
    const { state } = mount(t, { getExamDetail: async id => id === 'A' ? slow.promise : detail(id) });
    const earlier = enter(state, 'A'); await enter(state, 'B'); slow.resolve(detail('A')); await earlier;
    assert.equal(state.selectedExam.value.id, 'B'); assert.equal(state.examDetail.value.id, 'B'); assert.equal(state.attemptId.value, 'B:alice');
});

test('identity change clears prior attempt and prevents stale saves contaminating a new user', async t => {
    const { state, props } = mount(t);
    await enter(state); props.currentUser = { username: 'bob' }; await nextTick();
    assert.equal(state.attemptId.value, null); assert.deepEqual(state.answers.value, {});
    await enter(state); assert.equal(state.attemptId.value, 'A:bob');
});

test('run code does not execute student code or claim public-case success', async t => {
    const { state, toasts } = mount(t);
    await enter(state); state.setEditorCode('globalThis.__examCodeExecuted = true; function answer() { return 1; }');
    await state.runCode();
    assert.equal(globalThis.__examCodeExecuted, undefined);
    assert.equal(state.caseResults.value.some(c => c.status === 'passed'), false);
    assert.equal(toasts.some(c => c[2] === 'success'), false);
});

test('attempt identity key updates when navigating across user and server attempt', async t => {
    const { state } = mount(t);
    assert.equal(state.attemptKey.value, null);
    await enter(state, 'A'); assert.equal(state.attemptKey.value, JSON.stringify(['alice', 'A', 'A:alice']));
    await state.backToOverview(); await enter(state, 'B');
    assert.equal(state.attemptKey.value, JSON.stringify(['alice', 'B', 'B:alice']));
});

test('edits made while the next exam loads are saved to the original attempt before switching', async t => {
    const nextExam = deferred();
    const { state, calls } = mount(t, { getExamDetail: async id => id === 'B' ? nextExam.promise : detail(id) });
    await enter(state, 'A');
    const navigating = enter(state, 'B'); await settle();
    state.setEditorCode('edited during load'); nextExam.resolve(detail('B')); await navigating;
    assert.equal(calls.some(c => c[0] === 'save' && c[1] === 'A:alice' && c[2].answer === 'edited during load'), true);
    assert.equal(state.attemptId.value, 'B:alice');
});

test('failed pending save while loading next exam keeps original attempt and edits', async t => {
    const nextExam = deferred();
    const { state } = mount(t, { getExamDetail: async id => id === 'B' ? nextExam.promise : detail(id), saveAnswer: async () => { throw new Error('Offline'); } });
    await enter(state, 'A'); const navigating = enter(state, 'B'); await settle();
    state.setEditorCode('keep this answer'); nextExam.resolve(detail('B')); await navigating;
    assert.equal(state.attemptId.value, 'A:alice'); assert.equal(state.answers.value.q1, 'keep this answer');
});

test('finalized resume does not reopen editing or submit again', async t => {
    const { state, calls } = mount(t, { startExamAttempt: async () => ({ attemptId: 'A:alice', status: 'submitted', answers: { q1: 'final' }, remainingSeconds: 0, submittedAt: '2026-10-02T01:00:00Z' }) });
    await enter(state); state.setEditorCode('overwrite'); await state.submitAttempt();
    assert.equal(state.roomMode.value, 'detail'); assert.equal(state.answers.value.q1, 'final');
    assert.equal(state.securityActive.value, false); assert.equal(calls.length, 0);
});

test('zero-second resumed attempt immediately requests finalization without granting edit time', async t => {
    const submit = deferred();
    const { state } = mount(t, { startExamAttempt: async () => ({ attemptId: 'A:alice', status: 'started', answers: { q1: 'saved' }, remainingSeconds: 0 }), submitAttempt: async () => submit.promise });
    await enter(state); await settle();
    assert.equal(state.remainingSeconds.value, 0); assert.equal(state.submitting.value, true);
    state.setEditorCode('late overwrite'); assert.equal(state.answers.value.q1, 'saved');
    submit.resolve({ attemptId: 'A:alice', status: 'submitted', submittedAt: new Date().toISOString(), late: true }); await settle();
});

test('stale save acknowledgement after identity change cannot mark new user answers as saved', async t => {
    const oldSave = deferred();
    const { state, props } = mount(t, { saveAnswer: async () => oldSave.promise });
    await enter(state); state.setEditorCode('alice private'); const saving = state.flushAnswers(); await settle();
    props.currentUser = { username: 'bob' }; await nextTick(); await enter(state);
    state.setEditorCode('bob work');
    oldSave.resolve({ attemptId: 'A:alice', status: 'saved', savedAt: new Date().toISOString() }); await saving;
    assert.equal(state.saveState.value, 'pending'); assert.equal(state.answers.value.q1, 'bob work');
});

test('a synchronous save transport failure can be retried and acknowledged', async t => {
    let attempts = 0;
    const { state } = mount(t, { saveAnswer: id => { if (++attempts === 1) throw new Error('Cannot prepare request'); return Promise.resolve({ attemptId: id, status: 'saved', savedAt: new Date().toISOString() }); } });
    await enter(state); state.setEditorCode('retry me');
    assert.equal(await state.flushAnswers(), false); assert.equal(state.saveState.value, 'error');
    assert.equal(await state.flushAnswers(), true); assert.equal(state.saveState.value, 'saved');
});

test('a save response for the wrong attempt is rejected and pending answer retained', async t => {
    const { state } = mount(t, { saveAnswer: async () => ({ attemptId: 'other:alice', status: 'saved', savedAt: new Date().toISOString() }) });
    await enter(state); state.setEditorCode('not confirmed');
    assert.equal(await state.flushAnswers(), false); assert.equal(state.saveState.value, 'error');
    assert.equal(state.answers.value.q1, 'not confirmed'); assert.equal(await state.backToOverview(), false);
});
