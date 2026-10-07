import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { ref, computed, watch } from '../libs/vue.esm-browser.js';

// Component/API doubles only, with real shipped Vue refs. No HTTP, providers,
// browser, DB, or persistent storage is invoked by this test file.
function loadStudent(api = {}, currentUser = { username: 'student-A' }) {
    const source = fs.readFileSync(new URL('../js/components/StudentHomework.js', import.meta.url), 'utf8')
        .replace(/^import .*?;\r?$/gm, '')
        .replace('export default', 'globalThis.component =');
    let mounted;
    const notices = [], events = [];
    const context = {
        ref, computed, watch, onMounted: callback => { mounted = callback; },
        homeworkApi: api, mockSubjects: [{ id: 'DS-201' }], RadarChart: {}, console,
        window: { dispatchEvent: event => events.push(event) },
        CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail; } }
    };
    vm.createContext(context);
    vm.runInContext(source, context);
    const state = context.component.setup({ currentUser }, { emit: (...notice) => notices.push(notice) });
    return { state, notices, events, mount: () => mounted() };
}
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
const homework = (id, patch = {}) => ({ id, subjectId: 'DS-201', status: 'unsubmitted', questions: [], ...patch });

test('server pending submission is presented as submitted after reloading', async () => {
    const { state: s, mount } = loadStudent({ getStudentHomeworkList: async () => [homework('H', { status: 'pending', submittedAnswers: { q1: 'B' } })] });
    await mount();
    assert.equal(s.homeworkList.value[0].status, 'submitted');
    assert.equal(s.summary.value.pending, 1);
    assert.equal(s.summary.value.unsubmitted, 0);
});

test('persisted graded zero and teacher feedback are used on a fresh student read', async () => {
    const { state: s, mount } = loadStudent({ getStudentHomeworkList: async () => [homework('H', { status: 'graded', grade: 0, teacherComment: 'Please revise' })] });
    await mount();
    s.enterSubject({ id: 'DS-201' });
    assert.equal(s.selectedHomework.value.grade, 0);
    assert.equal(s.selectedHomework.value.teacherComment, 'Please revise');
    assert.equal(s.summary.value.graded, 1);
});

test('switching homework during submission updates only captured homework and answers', async () => {
    const pending = deferred();
    let sent;
    const { state: s, events } = loadStudent({ submitHomework: (id, payload) => { sent = { id, payload }; return pending.promise; } });
    const a = homework('A'), b = homework('B');
    s.homeworkList.value = [a, b];
    s.selectHomework(a);
    s.submittedAnswers.value = { q1: 'A answer' };
    const submit = s.handleSubmit();
    s.selectHomework(b);
    s.submittedAnswers.value = { q1: 'B draft' };
    pending.resolve({ success: true, attemptId: 'A:student-A', submittedAt: '2026-10-07T00:00:00Z' });
    await submit;
    assert.equal(sent.id, 'A');
    assert.equal(a.status, 'submitted');
    assert.equal(a.submittedAnswers.q1, 'A answer');
    assert.equal(b.status, 'unsubmitted');
    assert.equal(s.selectedHomework.value.id, 'B');
    assert.equal(s.submittedAnswers.value.q1, 'B draft');
    assert.equal(events[0].detail.homeworkId, 'A');
});

test('editing answers during submission does not rewrite the captured server submission', async () => {
    const pending = deferred();
    const { state: s } = loadStudent({ submitHomework: () => pending.promise });
    const a = homework('A');
    s.homeworkList.value = [a];
    s.selectHomework(a);
    s.submittedAnswers.value = { q1: 'sent answer' };
    const submit = s.handleSubmit();
    s.selectChoice('q1', 'new unsaved edit');
    pending.resolve({ success: true, attemptId: 'A:student-A' });
    await submit;
    assert.equal(a.submittedAnswers.q1, 'sent answer');
    assert.equal(s.submittedAnswers.value.q1, 'new unsaved edit');
});

test('exiting subject during submission still records the captured successful homework', async () => {
    const pending = deferred();
    const { state: s, notices, events } = loadStudent({ submitHomework: () => pending.promise });
    const a = homework('A');
    s.homeworkList.value = [a];
    s.selectHomework(a);
    const submit = s.handleSubmit();
    s.exitSubject();
    pending.resolve({ success: true, attemptId: 'A:student-A' });
    await submit;
    assert.equal(a.status, 'submitted');
    assert.equal(s.selectedHomework.value, null);
    assert.equal(events[0].detail.homeworkId, 'A');
    assert.ok(notices.some(n => n[2] === 'success'));
});

test('duplicate submit click produces one API call and failure preserves answers', async () => {
    const pending = deferred();
    let calls = 0;
    const { state: s, notices } = loadStudent({ submitHomework: () => { calls++; return pending.promise; } });
    const a = homework('A');
    s.homeworkList.value = [a];
    s.selectHomework(a);
    s.submittedAnswers.value = { q1: 'draft' };
    const submit = s.handleSubmit();
    await s.handleSubmit();
    assert.equal(calls, 1);
    pending.resolve({ success: false });
    await submit;
    assert.equal(a.status, 'unsubmitted');
    assert.equal(s.submittedAnswers.value.q1, 'draft');
    assert.equal(s.submitting.value, false);
    assert.ok(notices.every(n => n[2] !== 'success'));
});
