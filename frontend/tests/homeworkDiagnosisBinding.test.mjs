import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { ref, computed, watch } from '../libs/vue.esm-browser.js';

// Isolated shipped-Vue/API doubles only; no HTTP, DB, browser or provider call.
function setup(api) {
    const source = fs.readFileSync(new URL('../js/components/StudentHomework.js', import.meta.url), 'utf8')
        .replace(/^import .*?;\r?$/gm, '').replace('export default', 'globalThis.component =');
    const notices = [];
    const context = { ref, computed, watch, onMounted() {}, homeworkApi: api, mockSubjects: [], RadarChart: {}, console };
    vm.createContext(context);
    vm.runInContext(source, context);
    const state = context.component.setup({ currentUser: { username: 'student-A' } }, { emit: (...n) => notices.push(n) });
    return { state, notices };
}
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const homework = id => ({ id, subjectId: 'DS-201', questions: [], status: 'unsubmitted' });
const diagnosis = label => ({ scores: { alina: 70, codeninja: 80, profx: 90 }, alinaMsg: label, codeninjaMsg: label, profxMsg: label, source: 'ai' });

test('diagnosis for A cannot be written to B after switching homework', async () => {
    const pending = deferred();
    const { state: s, notices } = setup({ requestAgentDiagnosis: () => pending.promise });
    const a = homework('A'), b = homework('B');
    s.homeworkList.value = [a, b];
    s.selectHomework(a);
    const request = s.handleDiagnose();
    s.selectHomework(b);
    pending.resolve(diagnosis('A feedback'));
    await request;
    assert.equal(b.diagnosis, undefined);
    assert.equal(s.currentDiagnosis.value, null);
    assert.equal(s.selectedHomework.value.id, 'B');
    assert.ok(notices.every(n => n[2] !== 'success'));
});

test('abandoned diagnosis cannot prevent or finish a newer homework diagnosis', async () => {
    const a = deferred(), b = deferred();
    const calls = [];
    const { state: s } = setup({ requestAgentDiagnosis: id => { calls.push(id); return (id === 'A' ? a : b).promise; } });
    s.homeworkList.value = [homework('A'), homework('B')];
    s.selectHomework(s.homeworkList.value[0]);
    const first = s.handleDiagnose();
    s.selectHomework(s.homeworkList.value[1]);
    const second = s.handleDiagnose();
    assert.deepEqual(calls, ['A', 'B']);
    a.resolve(diagnosis('A feedback'));
    await first;
    assert.equal(s.diagnosing.value, true);
    assert.equal(s.currentDiagnosis.value, null);
    b.resolve(diagnosis('B feedback'));
    await second;
    assert.equal(s.currentDiagnosis.value.alinaMsg, 'B feedback');
    assert.equal(s.homeworkList.value[1].diagnosis.alinaMsg, 'B feedback');
    assert.equal(s.diagnosing.value, false);
});

test('closing diagnosis while a replacement is pending prevents late modal reopening', async () => {
    const pending = deferred();
    const { state: s } = setup({ requestAgentDiagnosis: () => pending.promise });
    const a = { ...homework('A'), diagnosis: diagnosis('old feedback') };
    s.homeworkList.value = [a];
    s.selectHomework(a);
    const request = s.handleDiagnose();
    s.closeDiagnosis();
    pending.resolve(diagnosis('late replacement'));
    await request;
    assert.equal(s.currentDiagnosis.value, null);
    assert.equal(s.diagnosing.value, false);
    assert.equal(a.diagnosis.alinaMsg, 'old feedback');
});

test('exiting the subject drops a late diagnosis without reopening its modal', async () => {
    const pending = deferred();
    const { state: s, notices } = setup({ requestAgentDiagnosis: () => pending.promise });
    s.selectHomework(homework('A'));
    const request = s.handleDiagnose();
    s.exitSubject();
    pending.resolve(diagnosis('A feedback'));
    await request;
    assert.equal(s.selectedHomework.value, null);
    assert.equal(s.currentDiagnosis.value, null);
    assert.equal(s.diagnosing.value, false);
    assert.ok(notices.every(n => n[2] !== 'success'));
});

test('same-homework exit and reopen starts a new diagnosis lifetime', async () => {
    const pending = deferred();
    const { state: s } = setup({ requestAgentDiagnosis: () => pending.promise });
    const a = homework('A');
    s.homeworkList.value = [a];
    s.selectHomework(a);
    const request = s.handleDiagnose();
    s.exitSubject();
    s.selectHomework(a);
    pending.resolve(diagnosis('stale A feedback'));
    await request;
    assert.equal(s.currentDiagnosis.value, null);
    assert.equal(a.diagnosis, undefined);
});

test('diagnosis receives a snapshot of answers, not a mutable later edit', async () => {
    const pending = deferred();
    let sent;
    const { state: s } = setup({ requestAgentDiagnosis: (_id, answers) => { sent = answers; return pending.promise; } });
    s.selectHomework(homework('A'));
    s.submittedAnswers.value = { q1: 'original answer' };
    const request = s.handleDiagnose();
    s.selectChoice('q1', 'later edit');
    assert.equal(sent.q1, 'original answer');
    pending.resolve(diagnosis('snapshot feedback'));
    await request;
    assert.equal(s.submittedAnswers.value.q1, 'later edit');
});

test('stale diagnosis failure does not show an error for the newer homework', async () => {
    const pending = deferred();
    const { state: s, notices } = setup({ requestAgentDiagnosis: () => pending.promise });
    s.selectHomework(homework('A'));
    const request = s.handleDiagnose();
    s.selectHomework(homework('B'));
    pending.reject(new Error('A unavailable'));
    await request;
    assert.equal(s.currentDiagnosis.value, null);
    assert.equal(notices.length, 0);
});

test('current diagnosis is single-flight and API failure preserves its homework state', async () => {
    const pending = deferred();
    let calls = 0;
    const { state: s, notices } = setup({ requestAgentDiagnosis: () => { calls++; return pending.promise; } });
    const a = { ...homework('A'), diagnosis: diagnosis('existing feedback') };
    s.homeworkList.value = [a];
    s.selectHomework(a);
    const request = s.handleDiagnose();
    await s.handleDiagnose();
    assert.equal(calls, 1);
    pending.reject(new Error('unavailable'));
    await request;
    assert.equal(a.diagnosis.alinaMsg, 'existing feedback');
    assert.equal(s.currentDiagnosis.value.alinaMsg, 'existing feedback');
    assert.equal(s.diagnosing.value, false);
    assert.ok(notices.some(n => n[2] === 'error'));
});

test('reselecting the same current homework does not unlock a duplicate diagnosis', async () => {
    const pending = deferred();
    let calls = 0;
    const { state: s } = setup({ requestAgentDiagnosis: () => { calls++; return pending.promise; } });
    const a = homework('A');
    s.homeworkList.value = [a];
    s.selectHomework(a);
    const request = s.handleDiagnose();
    s.selectHomework(a);
    await s.handleDiagnose();
    assert.equal(calls, 1);
    pending.resolve(diagnosis('A feedback'));
    await request;
    assert.equal(a.diagnosis.alinaMsg, 'A feedback');
});
