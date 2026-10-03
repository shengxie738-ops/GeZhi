import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source = fs.readFileSync(new URL('../js/components/CodingSandbox.js', import.meta.url), 'utf8');
assert.ok(!source.includes('new Function'), 'No submitted code may run in the application origin');
assert.ok(!source.includes('new Worker('), 'Same-origin workers are not an isolated runner');
assert.ok(!source.includes('window.marked.parse'));
assert.ok(source.includes('v-html="renderMarkdown(msg.content)"'));
function extract(name, next) { return source.slice(source.indexOf(`        const ${name} =`), source.indexOf(next, source.indexOf(`        const ${name} =`))); }
const ranked = extract('submitRankedMatch', '        const resolveRankedMatch');
assert.ok(!ranked.includes('resolveRankedMatch('), 'Unavailable execution must not settle a ranked win or loss');
assert.ok(!source.includes('profileApi.recordTest('), 'Unavailable local execution must not write assessment evidence');
const teacher = fs.readFileSync(new URL('../js/components/TeacherForumManager.js', import.meta.url), 'utf8');
assert.ok(teacher.includes('safeRendering.js') && !teacher.includes('window.marked.parse'));
const main = fs.readFileSync(new URL('../js/main.js', import.meta.url), 'utf8');
assert.ok(!main.includes('svgContainer.innerHTML = svg'), 'Mermaid SVG output is untrusted');
console.log('coding execution and HTML boundary checks passed');

// Execute real UI handlers in a minimal state; no submitted code is evaluated.
const notices = [];
const context = {
 emit: (...args) => notices.push(args), isRunning: {value:false},
 activeTab: {value:'console'}, consoleLogs: {value:[]},
 testCaseResults: {value:[{status:'passed', actual:'old'}]},
 isRankedRunning: {value:false}, rankedActiveTab:{value:'console'},
 rankedConsoleLogs:{value:[]}, rankedTestCaseResults:{value:[{status:'passed'}]},
 runHomeworkTesting:{value:false}, activeHomeworkConsoleLogs:{value:[]},
 runCollabTesting:{value:false}
};
vm.createContext(context);
for (const [name, next] of [
 ['runTests', '        // 获取 AI 智能代码Review诊断'],
 ['runRankedCode','        const formatDuration'],
 ['runHomeworkTest','        const handleHomeworkDiagnose'],
 ['runCollabTest','        const sendCollabMessage'],
 ['submitRankedMatch','        const resolveRankedMatch']
]) {
 vm.runInContext(extract(name, next) + `\n globalThis.${name} = ${name};`, context);
}
context.runTests();
assert.equal(context.testCaseResults.value[0].status, 'unavailable');
assert.equal(context.testCaseResults.value[0].actual, null);
assert.equal(context.isRunning.value, false);
await context.runRankedCode();
assert.equal(context.rankedTestCaseResults.value[0].status, 'unavailable');
await context.submitRankedMatch();
context.runHomeworkTest();
context.runCollabTest();
assert.equal(notices.length, 5);
assert.ok(notices.every(args => args[1].includes('代码执行不可用') && args[2] !== 'success'));
console.log('practice, ranked, homework and collaboration run handlers report unavailable');
