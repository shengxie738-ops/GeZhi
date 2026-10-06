import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

let runner;
try { runner = await import('../scripts/desktopTestRunner.mjs'); }
catch (error) { if (error.code !== 'ERR_MODULE_NOT_FOUND') throw error; }
const ready = () => {
    assert.equal(typeof runner?.createDesktopTestPlan, 'function', 'A complete deterministic desktop test plan must exist');
    return runner;
};
const official = [
    'rebuildAnalyticsEvidence.test.mjs', 'rebuildForumInteraction.test.mjs', 'studentDashboard.test.mjs',
    'teamGitComponents.test.mjs', 'teachingAssignmentRead.test.mjs', 'teachingReadDetailFocus.test.mjs',
    'teachingWorkbenchShell.test.mjs', 'teachingWorkspaceTruth.test.mjs'
];
const files = () => [...official, 'teacherWorkMaterialsForms.test.mjs', 'teachingForegroundRevalidation.test.mjs', 'desktopTestRunner.test.mjs'];
const tap = extra => '# tests 2\n# pass 2\n# fail 0\n# cancelled 0\n# skipped 0\n# todo 0\n' + (extra || '');

test('desktop aggregate partitions every discovered file exactly once into coherent official and shipped lanes', () => {
    const r = ready(), input = files(), plan = r.createDesktopTestPlan(input, official);
    assert.deepEqual(plan.map(lane => [lane.id, lane.vueVersion]), [['official', '3.5.39'], ['shipped', '3.3.4']]);
    assert.deepEqual(plan[0].files, [...official].sort());
    const assigned = plan.flatMap(lane => lane.files);
    assert.equal(new Set(assigned).size, input.length);
    assert.deepEqual([...assigned].sort(), [...input].sort());
    assert.deepEqual(input, files(), 'Planning must not mutate discovery');
});

test('desktop aggregate rejects duplicate discovery missing registered files and unreviewed compiler files', () => {
    const r = ready();
    assert.throws(() => r.createDesktopTestPlan([...files(), files()[0]], official), /duplicate/i);
    assert.throws(() => r.createDesktopTestPlan(files().slice(1), official.slice(1)), /missing/i);
    assert.throws(() => r.createDesktopTestPlan([...files(), 'newCompiler.test.mjs'], [...official, 'newCompiler.test.mjs']), /compiler.*lane|lane.*compiler/i);
    assert.throws(() => r.createDesktopTestPlan([...files(), '../outside.test.mjs'], official), /filename/i);
    assert.throws(() => r.createDesktopTestPlan([], []), /missing|empty/i);
});

test('desktop command fixes process timezone and concurrency without weakening test or import failures', () => {
    const r = ready();
    for (const lane of r.createDesktopTestPlan(files(), official)) {
        const command = r.commandForDesktopLane(lane, { TZ: 'Asia/Tokyo', TEST_SENTINEL: 'kept' });
        assert.equal(command.env.TZ, 'Asia/Shanghai');
        assert.equal(command.env.TEST_SENTINEL, 'kept');
        assert.ok(command.args.includes('--test-concurrency=1'));
        assert.ok(command.args.includes('--test-reporter=tap'));
        assert.ok(command.args.includes('./frontend/tests/fixtures/' + lane.preload));
        assert.deepEqual(command.args.filter(value => value.endsWith('.test.mjs')), lane.files.map(name => './frontend/tests/' + name));
        assert.ok(!command.args.some(value => /skip|test-name-pattern/.test(value)));
    }
});

test('desktop lane result requires successful exit full TAP accounting and zero failures skips cancellations or todos', () => {
    const r = ready();
    assert.equal(r.acceptDesktopLaneResult({ status: 0, signal: null, stdout: tap() }).ok, true);
    for (const result of [
        { status: 1, stdout: tap() }, { status: null, signal: 'SIGTERM', stdout: tap() },
        { status: 0, stdout: '' }, { status: 0, stdout: tap().replace('# fail 0', '# fail 1') },
        { status: 0, stdout: tap().replace('# skipped 0', '# skipped 1') },
        { status: 0, stdout: tap().replace('# cancelled 0', '# cancelled 1') },
        { status: 0, stdout: tap().replace('# todo 0', '# todo 1') },
        { status: 0, stdout: tap().replace('# pass 2', '# pass 1') },
        { status: 0, stdout: tap('not ok 1 - assertion failed\n') },
        { status: 0, stdout: tap('ok 1 - omitted # SKIP\n') },
        { status: 0, stdout: tap('ok 1 - unfinished # TODO\n') },
        { status: 0, stdout: tap(), error: new Error('Child failed to start') }
    ]) assert.equal(r.acceptDesktopLaneResult(result).ok, false, JSON.stringify(result));
    assert.equal(r.acceptDesktopLaneResult({ status: 1, stdout: tap('not ok 1 - assertion failed\n') }).summary.tests, 2,
        'Rejected lanes must retain their actual test accounting');
});

test('desktop aggregate propagates either lane failure while still executing both complete file selections', () => {
    const r = ready(), plan = r.createDesktopTestPlan(files(), official);
    assert.equal(typeof r.executeDesktopTestPlan, 'function', 'Aggregate execution must propagate lane outcomes');
    for (const badLane of [null, 'official', 'shipped']) {
        const calls = [], messages = [];
        const result = r.executeDesktopTestPlan(plan, {
            runCommand(command, args, options) {
                calls.push({ command, args, options });
                const lane = args.includes('./frontend/tests/fixtures/desktopOfficialNodePreload.mjs') ? 'official' : 'shipped';
                return { status: lane === badLane ? 1 : 0, stdout: tap(), stderr: '' };
            }, writeOut: text => messages.push(text), writeError: text => messages.push(text)
        });
        assert.equal(result.ok, badLane === null);
        assert.equal(calls.length, 2);
        assert.deepEqual(calls.flatMap(call => call.args.filter(arg => arg.endsWith('.test.mjs'))).sort(), files().map(name => './frontend/tests/' + name).sort());
        assert.ok(calls.every(call => call.options.env.TZ === 'Asia/Shanghai'));
        assert.equal(result.tests, 4);
    }
});

test('desktop preloads bind source and tests to their lane singleton and refuse compiler imports in shipped lane', () => {
    const cwd = fileURLToPath(new URL('../', import.meta.url));
    const source = "import * as Bare from 'vue'; import * as Bundled from './libs/vue.esm-browser.js'; console.log(JSON.stringify({bare:Bare.version,bundled:Bundled.version,same:Bare.ref===Bundled.ref}));";
    for (const [lane, version, same] of [['official', '3.5.39', false], ['shipped', '3.3.4', true]]) {
        const result = spawnSync(process.execPath, ['--import', './tests/fixtures/desktop' + (lane === 'official' ? 'Official' : 'Shipped') + 'NodePreload.mjs', '--input-type=module', '-e', source], { cwd, encoding: 'utf8' });
        assert.equal(result.status, 0, result.stderr);
        assert.deepEqual(JSON.parse(result.stdout.trim().split('\n').at(-1)), { bare: version, bundled: '3.3.4', same });
    }
    for (const dependency of ['@vue/compiler-dom', '@vue/server-renderer']) {
        const result = spawnSync(process.execPath, ['--import', './tests/fixtures/desktopShippedNodePreload.mjs', '--input-type=module', '-e', 'import ' + JSON.stringify(dependency)], { cwd, encoding: 'utf8' });
        assert.notEqual(result.status, 0, 'Shipped lane must reject cross-lane dependency ' + dependency);
        assert.match(result.stderr, /official.*lane/i);
    }
});

test('desktop discovery detects actual compiler imports without misclassifying dependency names in test data', () => {
    const r = ready();
    assert.equal(typeof r.requiresOfficialCompiler, 'function', 'Compiler lane detection must distinguish import syntax from literal test data');
    for (const source of ["import {compile} from '@vue/compiler-dom';", "import '@vue/server-renderer';", "await import('@vue/compiler-dom');"])
        assert.equal(r.requiresOfficialCompiler(source), true, source);
    assert.equal(r.requiresOfficialCompiler("const dependencies = ['@vue/compiler-dom', '@vue/server-renderer'];"), false);
    const plan = r.discoverDesktopTestPlan();
    assert.ok(plan.find(lane => lane.id === 'shipped').files.includes('desktopTestRunner.test.mjs'));
});

test('both desktop lanes deny unregistered fetches until a test supplies its synthetic transport', () => {
    const cwd = fileURLToPath(new URL('../', import.meta.url));
    const source = "import assert from 'node:assert/strict'; assert.equal(globalThis.fetch.name,'denyDesktopNetwork'); assert.throws(()=>fetch('https://never-contact.synthetic.invalid'),/Unregistered network/); globalThis.fetch=async()=>({synthetic:true}); assert.equal((await fetch('synthetic')).synthetic,true);";
    for (const lane of ['Official', 'Shipped']) {
        const result = spawnSync(process.execPath, ['--import', './tests/fixtures/desktop' + lane + 'NodePreload.mjs', '--input-type=module', '-e', source], { cwd, encoding: 'utf8' });
        assert.equal(result.status, 0, result.stderr);
    }
});
