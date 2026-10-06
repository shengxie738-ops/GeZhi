import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createNavigationGuard } from '../js/utils/navigationGuard.js';
import { createTeachingNavigation } from '../js/controllers/teachingNavigation.js';

const index = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const auth = readFileSync(new URL('../js/hooks/useAuth.js', import.meta.url), 'utf8');
const main = readFileSync(new URL('../js/main.js', import.meta.url), 'utf8');
const dashboard = readFileSync(new URL('../js/components/StudentDashboard.js', import.meta.url), 'utf8');
const workbench = readFileSync(new URL('../js/hooks/useTeachingWorkbench.js', import.meta.url), 'utf8');

// Diagnosis lives in the authenticated global menu, beside the separate overview.
assert.match(auth, /\{ id: 'learning-diagnosis', name: '学习诊断'/);
assert.match(index, /<button\b[^>]*v-for="menu in activeMenus"[^>]*@click="currentView = menu\.id"/);
assert.match(main, /const guardedView = computed\(\{ get: \(\) => auth\.currentView\.value, set: teachingWorkbench\.navigateToView \}\)/);
assert.match(main, /currentView: guardedView/);
assert.match(workbench, /const accepted=await navigation\.openLegacy\(view\)/);
assert.match(index, /<student-dashboard\b[^>]*v-if="currentView === 'dashboard'"[^>]*@navigate="teachingOpenTool"/);
assert.match(dashboard, /<h1 id="student-dashboard-title">学习总览<\/h1>/);
assert.doesNotMatch(dashboard, /continueLearning|继续学习/);
assert.match(index, /<student-learning-diagnosis\b[^>]*v-if="currentView === 'learning-diagnosis'"[^>]*:current-user="currentUser"/);
assert.match(main, /import StudentLearningDiagnosis from '\.\/components\/StudentLearningDiagnosis\.js'/);

// Exercise the same verified-identity and exam-save boundaries used by the menu.
let currentView = 'dashboard';
let verified = false;
let answersSaved = false;
let flushCount = 0;
const notifications = [];
const navigation = createTeachingNavigation({
  initialLegacyView: currentView,
  getContext: () => ({ authVerified: verified, actorId: 'synthetic-student', currentRole: 'student', authEpoch: 1, contextEpoch: 1 }),
  navigateView: createNavigationGuard({
    getCurrentView: () => currentView,
    setView: view => { currentView = view; },
    getExam: () => ({ flushAnswers: async () => { flushCount += 1; return answersSaved; } }),
    notify: (...args) => notifications.push(args),
  }),
});
assert.equal(await navigation.openLegacy('learning-diagnosis'), false);
assert.equal(currentView, 'dashboard');
verified = true;
assert.equal(await navigation.openLegacy('learning-diagnosis'), true);
assert.equal(currentView, 'learning-diagnosis');
assert.equal(flushCount, 0);
currentView = 'exam';
assert.equal(await navigation.openLegacy('learning-diagnosis'), false);
assert.equal(currentView, 'exam');
assert.equal(flushCount, 1);
assert.match(notifications.at(-1)[0], /答案尚未保存/);
answersSaved = true;
assert.equal(await navigation.openLegacy('learning-diagnosis'), true);
assert.equal(currentView, 'learning-diagnosis');
assert.equal(flushCount, 2);
navigation.dispose();

console.log('learningDiagnosisDashboardEntry tests passed');
