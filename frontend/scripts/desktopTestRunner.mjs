import { readdirSync, readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import { parse } from '@babel/parser';

const repoRoot = fileURLToPath(new URL('../../', import.meta.url));
const testsRoot = new URL('../tests/', import.meta.url);
const officialFiles = Object.freeze([
    'rebuildAnalyticsEvidence.test.mjs', 'rebuildForumInteraction.test.mjs', 'studentDashboard.test.mjs',
    'teamGitComponents.test.mjs', 'teachingAssignmentRead.test.mjs', 'teachingReadDetailFocus.test.mjs',
    'teachingWorkbenchShell.test.mjs', 'teachingWorkspaceTruth.test.mjs'
]);

export function createDesktopTestPlan(files, compilerFiles = []) {
    if (!Array.isArray(files) || !files.length) throw new Error('Empty desktop test discovery');
    if (files.some(name => typeof name !== 'string' || !/^[A-Za-z0-9_-]+\.test\.mjs$/.test(name))) throw new Error('Invalid test filename');
    if (new Set(files).size !== files.length) throw new Error('Duplicate desktop test file');
    for (const name of officialFiles) if (!files.includes(name)) throw new Error('Missing registered official test: ' + name);
    for (const name of compilerFiles) if (!files.includes(name) || !officialFiles.includes(name)) throw new Error('Unreviewed compiler test lane: ' + name);
    const plan = [
        { id: 'official', vueVersion: '3.5.39', preload: 'desktopOfficialNodePreload.mjs', files: files.filter(name => officialFiles.includes(name)).sort() },
        { id: 'shipped', vueVersion: '3.3.4', preload: 'desktopShippedNodePreload.mjs', files: files.filter(name => !officialFiles.includes(name)).sort() }
    ];
    const assigned = plan.flatMap(lane => lane.files);
    if (assigned.length !== files.length || new Set(assigned).size !== files.length) throw new Error('Incomplete or overlapping desktop coverage');
    return plan;
}

export function commandForDesktopLane(lane, environment = process.env) {
    return {
        command: process.execPath,
        args: ['--import', './frontend/tests/fixtures/' + lane.preload, '--test', '--test-concurrency=1', '--test-reporter=tap',
            ...lane.files.map(name => './frontend/tests/' + name)],
        cwd: repoRoot,
        env: { ...environment, TZ: 'Asia/Shanghai' }
    };
}

export function acceptDesktopLaneResult(result) {
    const summary = {};
    for (const key of ['tests', 'pass', 'fail', 'cancelled', 'skipped', 'todo']) {
        const matches = [...String(result.stdout || '').matchAll(new RegExp('^# ' + key + ' (\\d+)\\r?$', 'gm'))];
        if (matches.length !== 1) return { ok: false, reason: 'Missing or ambiguous TAP accounting: ' + key, summary };
        summary[key] = Number(matches[0][1]);
    }
    if (/^\s*not ok \d+\b/m.test(String(result.stdout || ''))
        || /^\s*(?:not )?ok \d+[^\r\n]*#\s*(?:SKIP|TODO)\b/im.test(String(result.stdout || ''))) {
        return { ok: false, reason: 'TAP contains a failed skipped or unfinished test', summary };
    }
    const ok = result.status === 0 && !result.signal && !result.error && summary.tests > 0 && summary.pass === summary.tests
        && ['fail', 'cancelled', 'skipped', 'todo'].every(key => summary[key] === 0);
    return { ok, reason: ok ? null : 'Desktop lane failed or incomplete', summary };
}

export function discoverDesktopTestPlan() {
    const entries = readdirSync(testsRoot, { withFileTypes: true }).filter(entry => entry.name.endsWith('.test.mjs'));
    if (entries.some(entry => !entry.isFile())) throw new Error('Desktop test discovery requires regular test files');
    const files = entries.map(entry => entry.name);
    const compilerFiles = files.filter(name => requiresOfficialCompiler(readFileSync(new URL(name, testsRoot), 'utf8')));
    return createDesktopTestPlan(files, compilerFiles);
}

export function requiresOfficialCompiler(source) {
    const ast = parse(source, { sourceType: 'module', createImportExpressions: true });
    const official = value => typeof value === 'string' && /^@vue\/(?:compiler-dom|server-renderer)(?:\/|$)/.test(value);
    function visit(node) {
        if (!node || typeof node !== 'object') return false;
        if (['ImportDeclaration', 'ExportNamedDeclaration', 'ExportAllDeclaration', 'ImportExpression'].includes(node.type)
            && official(node.source?.value)) return true;
        if (node.type === 'CallExpression' && node.callee?.type === 'Identifier' && node.callee.name === 'require'
            && official(node.arguments?.[0]?.value)) return true;
        return Object.values(node).some(value => Array.isArray(value) ? value.some(visit) : visit(value));
    }
    return visit(ast);
}

export function executeDesktopTestPlan(plan, {
    runCommand = spawnSync, writeOut = text => process.stdout.write(text), writeError = text => process.stderr.write(text)
} = {}) {
    const totals = { tests: 0, pass: 0, fail: 0, cancelled: 0, skipped: 0, todo: 0 };
    let failed = false;
    for (const lane of plan) {
        writeOut('Starting ' + lane.id + ' Vue ' + lane.vueVersion + ': ' + lane.files.length + ' files\n');
        const command = commandForDesktopLane(lane);
        const result = runCommand(command.command, command.args, { cwd: command.cwd, env: command.env, encoding: 'utf8', maxBuffer: 128 * 1024 * 1024 });
        writeOut(result.stdout || '');
        writeError(result.stderr || '');
        const accepted = acceptDesktopLaneResult(result);
        for (const key of Object.keys(totals)) totals[key] += accepted.summary[key] || 0;
        if (!accepted.ok) {
            failed = true;
            writeError('Rejected ' + lane.id + ' lane: ' + accepted.reason + '; exit=' + result.status + '; signal=' + result.signal + '\n');
            if (result.error) writeError(result.error.message + '\n');
        }
    }
    return { ...totals, ok: !failed, totalFiles: plan.reduce((sum, lane) => sum + lane.files.length, 0), lanes: plan.map(lane => lane.id) };
}

function main() {
    if (process.argv.slice(2).some(arg => arg !== '--list') || process.argv.slice(2).length > 1) throw new Error('Only --list is supported; the aggregate always includes every desktop Node test file');
    const plan = discoverDesktopTestPlan();
    const coverage = { timezone: 'Asia/Shanghai', totalFiles: plan.reduce((sum, lane) => sum + lane.files.length, 0), disjoint: true, fullCoverage: true, lanes: plan };
    if (process.argv.includes('--list')) { console.log(JSON.stringify(coverage, null, 2)); return; }
    console.log('Desktop Node coverage: ' + JSON.stringify(coverage));
    const summary = executeDesktopTestPlan(plan);
    console.log('Desktop aggregate summary: ' + JSON.stringify(summary));
    if (!summary.ok) process.exitCode = 1;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
    try { main(); }
    catch (error) { console.error('Desktop aggregate setup failed: ' + error.message); process.exitCode = 1; }
}
