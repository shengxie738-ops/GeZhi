import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { ref, computed, version } from '../libs/vue.esm-browser.js';

// Isolated shipped-Vue component contracts. Network and chart dependencies are
// deliberately replaced; these assertions do not prove HTTP or DB persistence.
assert.equal(version, '3.3.4');
function loadTeacher(api = {}) {
    const source = fs.readFileSync(new URL('../js/components/TeacherHomework.js', import.meta.url), 'utf8')
        .replace(/^import .*?;\r?$/gm, '')
        .replace('export default', 'globalThis.component =');
    const context = { ref, computed, onMounted() {}, homeworkApi: api, LineChart: {}, console };
    vm.createContext(context);
    vm.runInContext(source, context);
    const notices = [];
    const state = context.component.setup({}, { emit: (...notice) => notices.push(notice) });
    return { state, notices, component: context.component };
}
const attempt = (id = 'hw:student-A', patch = {}) => ({ id, status: 'pending', grade: null, aiScore: null, teacherComment: '', ...patch });
const receipt = { success: true, gradedAt: '2026-10-07T00:00:00Z' };
const diagnosis = { alinaMsg: 'Alina建议：检查边界', codeninjaMsg: 'CodeNinja建议：补充测试', profxMsg: 'Prof. X建议：解释思路' };
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };

test('existing numeric zero grade is retained when selecting a submission', () => {
    const { state: s } = loadTeacher();
    s.selectSubmission(attempt(undefined, { status: 'graded', grade: 0, aiScore: 90, recommendedGrade: 'A' }));
    assert.equal(s.gradeLevel.value, 0);
});

test('ungraded submission uses its actual numeric AI score', () => {
    const { state: s } = loadTeacher();
    s.selectSubmission(attempt(undefined, { aiScore: 82.5, recommendedGrade: 'B' }));
    assert.equal(s.gradeLevel.value, 82.5);
});

test('unmeasured submission does not invent an A or numeric grade', () => {
    const { state: s } = loadTeacher();
    s.selectSubmission(attempt(undefined, { recommendedGrade: 'A' }));
    assert.equal(s.gradeLevel.value, '');
});

test('AI adoption retains measured zero and describes numeric points', () => {
    const { state: s } = loadTeacher();
    s.selectSubmission(attempt(undefined, { aiScore: 0, recommendedGrade: 'E', diagnosis }));
    s.adoptAiFeedback();
    assert.equal(s.gradeLevel.value, 0);
    assert.match(s.teacherComment.value, /0 分/);
});

test('AI adoption without a measured numeric score preserves teacher draft', () => {
    const { state: s, notices } = loadTeacher();
    s.selectSubmission(attempt(undefined, { recommendedGrade: 'A', diagnosis }));
    s.gradeLevel.value = 45;
    s.teacherComment.value = 'Teacher draft';
    s.adoptAiFeedback();
    assert.equal(s.gradeLevel.value, 45);
    assert.equal(s.teacherComment.value, 'Teacher draft');
    assert.ok(notices.some(n => n[2] === 'error'));
});

test('numeric text is sent as a number and zero survives the local receipt', async () => {
    let sent;
    const { state: s } = loadTeacher({ gradeHomework: async (id, payload) => { sent = { id, payload }; return receipt; } });
    const sub = attempt();
    s.submissionList.value = [sub];
    s.selectSubmission(sub);
    s.gradeLevel.value = '0';
    s.teacherComment.value = 'Needs another attempt';
    await s.submitGrading();
    assert.equal(sent.payload.grade, 0);
    assert.equal(sub.grade, 0);
    assert.equal(sub.status, 'graded');
});

test('invalid grades never issue a grade request', async () => {
    let calls = 0;
    const { state: s, notices } = loadTeacher({ gradeHomework: async () => { calls++; return receipt; } });
    s.selectSubmission(attempt());
    for (const value of ['', '  ', 'A', -1, 101, NaN, Infinity, true, null, undefined, [], {}]) {
        s.gradeLevel.value = value;
        await s.submitGrading();
    }
    assert.equal(calls, 0);
    assert.equal(notices.filter(n => n[2] === 'error').length, 12);
});

test('failed or missing grade receipt does not claim publication', async () => {
    for (const result of [undefined, {}, { success: false }, { success: true }]) {
        const { state: s, notices } = loadTeacher({ gradeHomework: async () => result });
        const sub = attempt();
        s.submissionList.value = [sub];
        s.selectSubmission(sub);
        s.gradeLevel.value = 90;
        await s.submitGrading();
        assert.equal(sub.status, 'pending');
        assert.ok(notices.some(n => n[2] === 'error'));
        assert.ok(notices.every(n => n[2] !== 'success'));
    }
});

test('switching students during grading updates only the requested attempt and captured draft', async () => {
    const pending = deferred();
    let sent;
    const { state: s } = loadTeacher({ gradeHomework: (id, payload) => { sent = { id, payload }; return pending.promise; } });
    const a = attempt('hw:student-A'), b = attempt('hw:student-B');
    s.submissionList.value = [a, b];
    s.selectSubmission(a);
    s.gradeLevel.value = 88.5;
    s.teacherComment.value = 'A feedback';
    const save = s.submitGrading();
    s.selectSubmission(b);
    s.gradeLevel.value = 35;
    s.teacherComment.value = 'B draft';
    pending.resolve(receipt);
    await save;
    assert.equal(sent.id, a.id);
    assert.equal(a.grade, 88.5);
    assert.equal(a.teacherComment, 'A feedback');
    assert.equal(b.status, 'pending');
    assert.equal(b.grade, null);
    assert.equal(s.activeSubmission.value.id, b.id);
    assert.equal(s.teacherComment.value, 'B draft');
});

test('duplicate click while saving issues one request', async () => {
    const pending = deferred();
    let calls = 0;
    const { state: s } = loadTeacher({ gradeHomework: () => { calls++; return pending.promise; } });
    s.selectSubmission(attempt());
    s.gradeLevel.value = 60;
    const save = s.submitGrading();
    await s.submitGrading();
    assert.equal(calls, 1);
    pending.resolve(receipt);
    await save;
    assert.equal(s.isSavingGrade.value, false);
});

test('grade API failure preserves draft and pending state', async () => {
    const { state: s, notices } = loadTeacher({ gradeHomework: async () => { throw new Error('offline'); } });
    const sub = attempt();
    s.submissionList.value = [sub];
    s.selectSubmission(sub);
    s.gradeLevel.value = 70;
    s.teacherComment.value = 'Unsaved feedback';
    await s.submitGrading();
    assert.equal(sub.status, 'pending');
    assert.equal(s.gradeLevel.value, 70);
    assert.equal(s.teacherComment.value, 'Unsaved feedback');
    assert.equal(s.isSavingGrade.value, false);
    assert.ok(notices.some(n => n[2] === 'error'));
});

test('desktop grade input is numeric and preserves the existing style', () => {
    const { component } = loadTeacher();
    assert.match(component.template, /<input[^>]+v-model\.number="gradeLevel"[^>]+type="number"[^>]+min="0"[^>]+max="100"/);
    assert.doesNotMatch(component.template, /<option value="[A-E]">/);
});

test('older homework detail response cannot replace the newer homework submissions', async () => {
    const a = deferred(), b = deferred();
    const { state: s } = loadTeacher({
        getHomeworkSubmissions: id => (id === 'A' ? a : b).promise,
        getHomeworkAnalysis: async id => ({ homeworkId: id })
    });
    const openA = s.openHomeworkDetail({ id: 'A', questions: [] });
    const openB = s.openHomeworkDetail({ id: 'B', questions: [] });
    b.resolve([attempt('B:student-B')]);
    await openB;
    a.resolve([attempt('A:student-A')]);
    await openA;
    assert.equal(s.selectedHomework.value.id, 'B');
    assert.equal(s.activeSubmission.value.id, 'B:student-B');
    assert.equal(s.homeworkAnalysis.value.homeworkId, 'B');
});

test('closing detail ignores a pending response and clears the detail state', async () => {
    const pending = deferred();
    const { state: s } = loadTeacher({ getHomeworkSubmissions: () => pending.promise, getHomeworkAnalysis: async () => ({ homeworkId: 'A' }) });
    const open = s.openHomeworkDetail({ id: 'A' });
    s.backToOverview();
    pending.resolve([attempt('A:student-A')]);
    await open;
    assert.equal(s.activeTab.value, 'overview');
    assert.equal(s.activeSubmission.value, null);
    assert.equal(s.submissionList.value.length, 0);
    assert.equal(s.homeworkAnalysis.value, null);
});

test('detail read failure does not retain submissions from a previous homework', async () => {
    const { state: s } = loadTeacher({
        getHomeworkSubmissions: async id => { if (id === 'B') throw new Error('offline'); return [attempt('A:student-A')]; },
        getHomeworkAnalysis: async id => ({ homeworkId: id })
    });
    await s.openHomeworkDetail({ id: 'A' });
    await s.openHomeworkDetail({ id: 'B' });
    assert.equal(s.submissionList.value.length, 0);
    assert.equal(s.homeworkAnalysis.value, null);
    assert.equal(s.activeSubmission.value, null);
});

test('late report for another homework cannot enter the current grading payload', async () => {
    const pending = deferred();
    let sent;
    const { state: s } = loadTeacher({
        getHomeworkSubmissions: async id => [attempt(id + ':student')],
        getHomeworkAnalysis: async id => ({ homeworkId: id }),
        generateHomeworkReport: () => pending.promise,
        gradeHomework: async (_id, payload) => { sent = payload; return receipt; }
    });
    await s.openHomeworkDetail({ id: 'A' });
    const report = s.generateReport();
    await s.openHomeworkDetail({ id: 'B' });
    pending.resolve({ homeworkId: 'A', studentInsight: 'A-only feedback' });
    await report;
    assert.equal(s.homeworkReport.value, null);
    assert.equal(s.detailMode.value, 'student');
    assert.equal(s.reportGenerating.value, false);
    s.gradeLevel.value = 70;
    await s.submitGrading();
    assert.equal(sent.classInsight, '');
});

test('new homework can request its own report while an abandoned report remains pending', async () => {
    const old = deferred(), current = deferred();
    const { state: s } = loadTeacher({
        getHomeworkSubmissions: async () => [], getHomeworkAnalysis: async () => ({}),
        generateHomeworkReport: id => (id === 'A' ? old : current).promise
    });
    await s.openHomeworkDetail({ id: 'A' });
    const reportA = s.generateReport();
    await s.openHomeworkDetail({ id: 'B' });
    const reportB = s.generateReport();
    old.resolve({ homeworkId: 'A', studentInsight: 'A-only feedback' });
    await reportA;
    assert.equal(s.reportGenerating.value, true);
    assert.equal(s.homeworkReport.value, null);
    current.resolve({ homeworkId: 'B', studentInsight: 'B feedback' });
    await reportB;
    assert.equal(s.homeworkReport.value.homeworkId, 'B');
    assert.equal(s.reportGenerating.value, false);
});

test('grade-triggered analysis cannot overwrite a newer same-homework detail after close and reopen', async () => {
    const old = deferred();
    const started = deferred();
    let reads = 0;
    const { state: s } = loadTeacher({
        getHomeworkSubmissions: async () => [attempt('A:student')],
        getHomeworkAnalysis: () => {
            reads++;
            if (reads === 2) { started.resolve(); return old.promise; }
            return Promise.resolve({ homeworkId: 'A', revision: reads });
        },
        gradeHomework: async () => receipt
    });
    await s.openHomeworkDetail({ id: 'A' });
    s.gradeLevel.value = 80;
    const grade = s.submitGrading();
    await started.promise;
    s.backToOverview();
    await s.openHomeworkDetail({ id: 'A' });
    assert.equal(s.homeworkAnalysis.value.revision, 3);
    old.resolve({ homeworkId: 'A', revision: 2 });
    await grade;
    assert.equal(s.homeworkAnalysis.value.revision, 3);
});

test('retained detail can finish while a top tab is selected and return without permanent loading', async () => {
    const pending = deferred();
    const { state: s } = loadTeacher({ getHomeworkSubmissions: () => pending.promise, getHomeworkAnalysis: async () => ({ homeworkId: 'A' }) });
    const open = s.openHomeworkDetail({ id: 'A' });
    s.activeTab.value = 'overview';
    pending.resolve([attempt('A:student')]);
    await open;
    s.activeTab.value = 'detail';
    assert.equal(s.detailLoading.value, false);
    assert.equal(s.activeSubmission.value.id, 'A:student');
});

test('grading refuses to attach a report whose homework ID differs from the selected homework', async () => {
    let sent;
    const { state: s } = loadTeacher({ gradeHomework: async (_id, payload) => { sent = payload; return receipt; }, getHomeworkAnalysis: async () => ({}) });
    s.selectedHomework.value = { id: 'B' };
    s.selectSubmission(attempt('B:student'));
    s.gradeLevel.value = 65;
    s.homeworkReport.value = { homeworkId: 'A', studentInsight: 'A-only feedback' };
    await s.submitGrading();
    assert.equal(sent.classInsight, '');
});
