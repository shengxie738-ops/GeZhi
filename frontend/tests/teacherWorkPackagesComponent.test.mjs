import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { Vue, mount, find, walk, textOf, button, settle, globals } from './fixtures/teacherWorkHarness.mjs';
import { createTeacherWorkState } from '../js/controllers/teacherWorkState.js';

const componentURL = new URL('../js/components/teacher-work/TeacherWorkPackages.js', import.meta.url);
const capabilities = () => ({ status: 'ready', data: { create: true, read: true, retry: true, download: true,
    storage_configured: true, reasons: {} }, reason: null });
const historyItem = (changes = {}) => ({ version_id: 'version-a', version_no: 3, run_id: 'run-a', approval_id: 'approval-a',
    created_at: '2026-10-06T03:00:00Z', stage: 'FAILED', attempt: 1,
    artifacts: [{ artifact_id: 'pptx-a', kind: 'pptx', state: 'READY', download_available: true },
        { artifact_id: 'docx-a', kind: 'docx', state: 'FAILED', download_available: false }], ...changes });
const readyArtifact = (changes = {}) => { const kind = changes.kind || 'pptx'; return { artifact_id: kind + '-a', version_id: 'version-a', kind, state: 'READY',
    download_name: '循环课.' + kind, mime: kind === 'pptx' ? 'application/vnd.openxmlformats-officedocument.presentationml.presentation' :
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document', byte_size: 4096,
    sha256: 'a'.repeat(64), exporter_version: 'gezhi-' + kind + '@1', validation_summary: { valid: true, checks: ['package_valid'], warnings: [] },
    error_code: null, ...changes }; };
const detail = (changes = {}) => ({ task_id: 'task-a', run: { run_id: 'run-a', stage: 'FAILED', attempt: 1, error_code: 'EXPORT_FAILED' },
    version: { version_id: 'version-a', version_no: 3, run_id: 'run-a', created_at: '2026-10-06T03:00:00Z', content_digest: 'b'.repeat(64),
        template_version: 'gezhi@1' }, approval: { approval_id: 'approval-a', outline_id: 'outline-a', outline_revision: 4 },
    provenance: 'manual', artifacts: [readyArtifact(), readyArtifact({ artifact_id: 'docx-a', kind: 'docx', state: 'FAILED',
        download_name: '循环课.docx', byte_size: 0, sha256: null, validation_summary: null, error_code: 'EXPORT_FAILED' })],
    retry_available: true, receipt: null, ...changes });
const state = (changes = {}) => Vue.reactive({ task: { task_id: 'task-a' }, createOpen: false,
    materials: { dirty: false, snapshot: { approval_current: true } }, packages: { capabilities: capabilities(), history: [], nextBefore: null,
        truncated: false, historyStatus: 'ready', detail: null, status: 'idle', error: null, canCreate: false,
        canRetry: false, canReplay: false, downloadBusy: null, pollPaused: false, lastReceipt: null, ...changes } });
async function component() { assert.ok(existsSync(componentURL), 'compact packages component is missing'); return (await import(componentURL)).default; }
const click = node => { assert.ok(node, 'control exists'); node.props.onClick(); };
const section = host => find(host.root, node => node.props['data-teacher-work-packages'] !== undefined);

// Finite shipped-Vue desktop host only: no browser, network, entrypoint, install, AI call, or mobile QA.
test('file section fails closed before package capability confirmation', async () => {
    const current = state(); delete current.packages;
    const host = await mount(await component(), { state: current });
    try {
        assert.ok(section(host)); assert.match(textOf(host.root), /文件与版本/); assert.match(textOf(host.root), /能力尚未确认/);
        assert.equal(button(host.root, '导出已审阅的保存版本').props.disabled, true);
        click(button(host.root, '导出已审阅的保存版本')); assert.equal(host.emitted['create-package'], undefined);
        assert.equal(walk(host.root).filter(node => node.tag === 'a').length, 0);
        assert.doesNotMatch(textOf(host.root), /已生成文件|保证.*Office|AI 已生成/);
    } finally { host.close(); }
});

test('create exports only through the explicit capability-gated saved-version action', async () => {
    const current = state({ canCreate: true }), host = await mount(await component(), { state: current });
    try {
        assert.match(textOf(host.root), /已审阅.*保存.*手动内容|手动.*已审阅.*保存/);
        assert.match(textOf(host.root), /未保存.*不会.*导出/);
        assert.equal(button(host.root, '导出已审阅的保存版本').props.disabled, false);
        click(button(host.root, '导出已审阅的保存版本')); assert.deepEqual(host.emitted['create-package'], [[]]);
        for (const [key, value] of [['create', false], ['storage_configured', false]]) {
            current.packages.capabilities.data[key] = value; await settle();
            assert.equal(button(host.root, '导出已审阅的保存版本').props.disabled, true);
            click(button(host.root, '导出已审阅的保存版本')); assert.equal(host.emitted['create-package'].length, 1);
            current.packages.capabilities.data[key] = true;
        }
        current.packages.canCreate = false; await settle(); assert.equal(button(host.root, '导出已审阅的保存版本').props.disabled, true);
        current.packages.canCreate = true; current.packages.status = 'creating'; await settle();
        assert.match(textOf(host.root), /正在提交.*尚未确认/); assert.equal(button(host.root, '导出已审阅的保存版本').props.disabled, true);
    } finally { host.close(); }
});

test('unavailable capability has a bounded explanation and explicit recheck event', async () => {
    const current = state({ capabilities: { status: 'unavailable', data: null, reason: 'private_exports_disabled' } });
    const host = await mount(await component(), { state: current });
    try {
        assert.match(textOf(host.root), /文件导出暂未开放/);
        click(button(host.root, '重新检查文件能力')); assert.deepEqual(host.emitted['retry-packages-capabilities'], [[]]);
        current.packages.capabilities.status = 'loading'; await settle();
        assert.equal(button(host.root, '重新检查文件能力').props.disabled, true);
        click(button(host.root, '重新检查文件能力')); assert.equal(host.emitted['retry-packages-capabilities'].length, 1);
        assert.match(textOf(host.root), /正在检查文件导出能力/);
    } finally { host.close(); }
});

test('history can reopen an owned saved version independently of current draft and source', async () => {
    const current = state({ history: [historyItem()], canCreate: false });
    current.materials = { dirty: true, snapshot: { source_status: 'unavailable', approval_current: false } };
    current.packages.capabilities.data.create = false; current.packages.capabilities.data.storage_configured = false;
    const host = await mount(await component(), { state: current, view: 'versions', idPrefix: 'history-test' });
    try {
        assert.match(textOf(host.root), /导出版本 3/); assert.match(textOf(host.root), /第 1 次/);
        assert.match(textOf(host.root), /PPTX.*文件已就绪/); assert.match(textOf(host.root), /DOCX.*失败/);
        click(button(host.root, '打开导出版本 3')); assert.deepEqual(host.emitted['open-package'], [['version-a']]);
        assert.equal(host.emitted['create-package'], undefined);
        assert.equal(find(host.root, node => node.tag === 'h2').props.id, 'history-test-heading');
    } finally { host.close(); }
});

test('history pagination is explicit and gated without manufacturing more versions', async () => {
    const current = state({ history: [historyItem()], nextBefore: 'older-version', truncated: true });
    const host = await mount(await component(), { state: current });
    try {
        click(button(host.root, '重新读取导出版本')); assert.deepEqual(host.emitted['reload-packages'], [[]]);
        click(button(host.root, '读取更早导出版本')); assert.deepEqual(host.emitted['load-older-packages'], [[]]);
        assert.match(textOf(host.root), /部分历史.*未显示/);
        current.packages.historyStatus = 'loading'; await settle();
        assert.equal(button(host.root, '重新读取导出版本').props.disabled, true);
        assert.equal(button(host.root, '读取更早导出版本').props.disabled, true);
        click(button(host.root, '读取更早导出版本')); assert.equal(host.emitted['load-older-packages'].length, 1);
        current.packages.historyStatus = 'ready'; current.packages.capabilities.data.read = false; await settle();
        assert.equal(button(host.root, '打开导出版本 3').props.disabled, true);
    } finally { host.close(); }
});

test('failed run keeps the ready format downloadable and retries only through the explicit retry action', async () => {
    const current = state({ detail: detail(), canRetry: true }), host = await mount(await component(), { state: current });
    try {
        assert.match(textOf(host.root), /导出版本 3/); assert.match(textOf(host.root), /第 1 次/);
        assert.match(textOf(host.root), /手动内容.*已审阅/); assert.match(textOf(host.root), /未调用 AI/);
        assert.equal(button(host.root, '下载 PPTX').props.disabled, false);
        assert.equal(button(host.root, '下载 DOCX').props.disabled, true);
        click(button(host.root, '下载 PPTX')); assert.deepEqual(host.emitted['download-package-artifact'], [['pptx-a']]);
        click(button(host.root, '下载 DOCX')); assert.equal(host.emitted['download-package-artifact'].length, 1);
        click(button(host.root, '重试失败格式')); assert.deepEqual(host.emitted['retry-package'], [[]]);
        current.packages.canRetry = false; await settle(); assert.equal(button(host.root, '重试失败格式').props.disabled, true);
        current.packages.canRetry = true; current.packages.capabilities.data.retry = false; await settle();
        assert.equal(button(host.root, '重试失败格式').props.disabled, true);
        assert.doesNotMatch(textOf(host.root), /文件全部生成成功|Office.*视觉.*一致/);
    } finally { host.close(); }
});

test('downloads fail closed for unvalidated artifacts and while any download is busy', async () => {
    const current = state({ detail: detail() }), host = await mount(await component(), { state: current, view: 'files' });
    try {
        for (const value of [readyArtifact({ state: 'BUILDING' }), readyArtifact({ validation_summary: { valid: false } }),
            readyArtifact({ byte_size: 0 }), readyArtifact({ sha256: null })]) {
            current.packages.detail.artifacts[0] = value; await settle();
            assert.equal(button(host.root, '下载 PPTX').props.disabled, true);
            click(button(host.root, '下载 PPTX')); assert.equal(host.emitted['download-package-artifact'], undefined);
        }
        current.packages.detail.artifacts[0] = readyArtifact(); current.packages.downloadBusy = 'pptx-a'; await settle();
        assert.equal(button(host.root, '下载 PPTX').props.disabled, true); assert.match(textOf(host.root), /正在下载/);
        current.packages.downloadBusy = null; current.packages.capabilities.data.download = false; await settle();
        assert.equal(button(host.root, '下载 PPTX').props.disabled, true);
        assert.equal(walk(host.root).filter(node => node.tag === 'a' || Object.hasOwn(node.props, 'href')).length, 0);
    } finally { host.close(); }
});

test('an uncertain creation offers only explicit replay of the original request', async () => {
    const current = state({ status: 'uncertain', canReplay: true, canCreate: true, error: { reason: 'network_error' } });
    const host = await mount(await component(), { state: current });
    try {
        assert.match(textOf(host.root), /结果未确认/); assert.equal(button(host.root, '导出已审阅的保存版本').props.disabled, true);
        click(button(host.root, '用原请求重新确认导出')); assert.deepEqual(host.emitted['replay-package'], [[]]);
        assert.equal(host.emitted['retry-package'], undefined); assert.equal(host.emitted['create-package'], undefined);
        current.packages.canReplay = false; await settle(); assert.equal(button(host.root, '用原请求重新确认导出'), undefined);
    } finally { host.close(); }
});

test('paused polling keeps selected package visible and exposes manual refresh', async () => {
    const current = state({ detail: detail({ run: { run_id: 'run-a', stage: 'FILES_RUNNING', attempt: 2 }, retry_available: false }), pollPaused: true });
    const host = await mount(await component(), { state: current });
    try {
        assert.match(textOf(host.root), /自动查询已暂停/); assert.match(textOf(host.root), /第 2 次/);
        assert.equal(button(host.root, '查询导出状态').props.disabled, false);
        click(button(host.root, '查询导出状态')); assert.deepEqual(host.emitted['refresh-package'], [[]]);
        current.packages.capabilities.data.read = false; await settle(); assert.equal(button(host.root, '查询导出状态').props.disabled, true);
    } finally { host.close(); }
});

test('file detail presents bounded server diagnostics as escaped text without raw storage paths', async () => {
    const current = state({ detail: detail() });
    current.packages.detail.artifacts[0].download_name = '<b>课件</b>.pptx';
    const host = await mount(await component(), { state: current });
    try {
        const technical = find(host.root, node => node.props['data-packages-technical'] !== undefined); assert.ok(technical);
        assert.match(textOf(technical), /version-a/); assert.match(textOf(technical), /approval-a/); assert.match(textOf(technical), /run-a/);
        assert.match(textOf(host.root), /<b>课件<\/b>\.pptx/);
        assert.equal(walk(host.root).filter(node => node.tag === 'b' || node.props.innerHTML !== undefined).length, 0);
        assert.match(textOf(technical), /gezhi-pptx@1/); assert.match(textOf(technical), /4096/); assert.match(textOf(technical), /a{64}/);
        assert.match(textOf(host.root), /结构校验/); assert.match(textOf(host.root), /核对.*版式/);
    } finally { host.close(); }
});

test('known package errors explain a next action without implying success', async () => {
    const current = state(), host = await mount(await component(), { state: current });
    try {
        for (const [reason, wording] of [['outline_approval_conflict', /审阅/], ['source_changed', /来源.*变更|引用资料.*变更/],
            ['revision_conflict', /任务版本.*变更/], ['owner_busy', /处理中/], ['private_storage_unavailable', /文件存储.*不可用/],
            ['artifact_unavailable', /文件.*尚未.*可下载/], ['invalid_response', /响应.*校验|响应.*验证/], ['idempotency_conflict', /原请求|请求标识/]]) {
            current.packages.error = { reason }; await settle();
            const alert = find(host.root, node => node.props.role === 'alert'); assert.ok(alert); assert.match(textOf(alert), wording, reason);
        }
        current.packages.error = { reason: 'https://unsafe.example/internal/path' }; await settle();
        assert.doesNotMatch(textOf(find(host.root, node => node.props.role === 'alert')), /unsafe\.example/);
        assert.match(textOf(host.root), /操作未完成/);
    } finally { host.close(); }
});

test('capability actions remain independent from the legacy manual-materials files flag', async () => {
    const current = state({ detail: detail(), canCreate: true }); current.materials.capabilities = { status: 'ready', data: { files: false } };
    const host = await mount(await component(), { state: current });
    try {
        assert.equal(button(host.root, '下载 PPTX').props.disabled, false);
        assert.equal(button(host.root, '导出已审阅的保存版本').props.disabled, false);
        current.packages.capabilities.data.create = false; await settle();
        assert.equal(button(host.root, '下载 PPTX').props.disabled, false);
        assert.match(textOf(host.root), /创建导出.*不可用/);
    } finally { host.close(); }
});

test('Work integrates packages and forwards every explicit action while retaining collapsible desktop navigation', async () => {
    globals(); const current = Vue.reactive(createTeacherWorkState()); current.task = { task_id: 'task-a', title: '循环教学', target_slide_count: 6 };
    current.packages = state({ canCreate: true, canRetry: true, detail: detail(), history: [historyItem()], nextBefore: 'older' }).packages;
    const work = (await import('../js/components/teacher-work/TeacherWork.js')).default;
    const host = await mount(work, { state: current, menus: [], currentUser: {} });
    try {
        const flow = find(host.root, node => node.props['data-teacher-work-packages'] === 'flow'); assert.ok(flow);
        for (const [label, event, args] of [['导出已审阅的保存版本', 'create-package', []], ['重试失败格式', 'retry-package', []],
            ['查询导出状态', 'refresh-package', []], ['下载 PPTX', 'download-package-artifact', ['pptx-a']],
            ['重新读取导出版本', 'reload-packages', []], ['读取更早导出版本', 'load-older-packages', []],
            ['打开导出版本 3', 'open-package', ['version-a']]]) {
            click(button(flow, label)); assert.deepEqual(host.emitted[event], [args], event);
        }
        current.packages.status = 'uncertain'; current.packages.canReplay = true; await settle();
        click(button(flow, '用原请求重新确认导出')); assert.deepEqual(host.emitted['replay-package'], [[]]);
        current.packages.capabilities = { status: 'error', data: null, reason: 'network_error' }; await settle();
        click(button(flow, '重新检查文件能力')); assert.deepEqual(host.emitted['retry-packages-capabilities'], [[]]);
        assert.ok(button(host.root, '收起主导航')); assert.ok(find(host.root, node => node.props['data-teacher-work-zone'] === 'navigation'));
        const ids = walk(host.root).filter(node => node.props.id).map(node => node.props.id); assert.equal(new Set(ids).size, ids.length);
        assert.doesNotMatch(textOf(host.root), /文件与版本产物读取尚未接通|AI 生成与文件产物尚未接通|PPTX 与 DOCX 文件导出尚未开放/);
    } finally { host.close(); }
});

test('packages styles are compact and remain confined to the light desktop Work shell', () => {
    const css = readFileSync(new URL('../styles/teacher-work.css', import.meta.url), 'utf8');
    assert.match(css, /\.teacher-work-packages/); assert.match(css, /\.teacher-work-package-artifact/);
    assert.match(css, /\.teacher-work-packages[^}]+background: #fff/s);
    assert.doesNotMatch(css, /@media[^\n]*(?:767|768|640)px/);
});

test('empty unconfirmed history never implies a successful saved export', async () => {
    const current = state({ capabilities: { status: 'idle', data: null, reason: null } });
    const host = await mount(await component(), { state: current });
    try {
        assert.doesNotMatch(textOf(host.root), /已保存/);
        assert.match(textOf(host.root), /尚无已读取的导出版本/);
        assert.equal(host.emitted['create-package'], undefined);
    } finally { host.close(); }
});

test('confirmed disabled capabilities expose a recovery check without enabling unsupported actions', async () => {
    const current = state(); current.packages.capabilities.data.create = false;
    current.packages.capabilities.data.reasons = { create: 'private_exports_disabled' };
    const host = await mount(await component(), { state: current });
    try {
        assert.equal(button(host.root, '导出已审阅的保存版本').props.disabled, true);
        click(button(host.root, '重新检查文件能力')); assert.deepEqual(host.emitted['retry-packages-capabilities'], [[]]);
        current.packages.status = 'creating'; await settle();
        assert.equal(button(host.root, '重新检查文件能力').props.disabled, true);
        click(button(host.root, '重新检查文件能力')); assert.equal(host.emitted['retry-packages-capabilities'].length, 1);
    } finally { host.close(); }
});

test('export receipt is labeled current only for the exact selected version and run', async () => {
    const current = state({ detail: detail(), lastReceipt: { version_id: 'prior-version', run_id: 'prior-run', attempt: 1, replayed: true } });
    const host = await mount(await component(), { state: current });
    try {
        assert.match(textOf(host.root), /此前导出操作回执（不代表当前版本）/);
        assert.doesNotMatch(textOf(host.root), /此导出版本操作已确认/);
        current.packages.lastReceipt = { version_id: 'version-a', run_id: 'prior-run', attempt: 1, replayed: true }; await settle();
        assert.doesNotMatch(textOf(host.root), /此导出版本操作已确认/);
        current.packages.lastReceipt.run_id = 'run-a'; await settle(); assert.match(textOf(host.root), /此导出版本操作已确认/);
    } finally { host.close(); }
});

test('storage capability closes byte download and retry while leaving history read available', async () => {
    const current = state({ detail: detail(), canRetry: true, history: [historyItem()] });
    current.packages.capabilities.data.storage_configured = false;
    const host = await mount(await component(), { state: current });
    try {
        assert.equal(button(host.root, '重新读取导出版本').props.disabled, false);
        assert.equal(button(host.root, '下载 PPTX').props.disabled, true);
        assert.equal(button(host.root, '重试失败格式').props.disabled, true);
        click(button(host.root, '下载 PPTX')); click(button(host.root, '重试失败格式'));
        assert.equal(host.emitted['download-package-artifact'], undefined); assert.equal(host.emitted['retry-package'], undefined);
        click(button(host.root, '打开导出版本 3')); assert.deepEqual(host.emitted['open-package'], [['version-a']]);
    } finally { host.close(); }
});

test('capacity and service availability errors give actionable Chinese recovery guidance', async () => {
    const current = state(), host = await mount(await component(), { state: current });
    try {
        current.packages.error = { reason: 'capacity_unavailable' }; await settle();
        assert.match(textOf(find(host.root, node => node.props.role === 'alert')), /处理容量.*稍后/);
        current.packages.error = { reason: 'TEACHER_WORK_UNAVAILABLE' }; await settle();
        assert.match(textOf(find(host.root, node => node.props.role === 'alert')), /服务.*暂不可用.*重新检查/);
    } finally { host.close(); }
});

test('selected-package refresh locks history and byte controls until the detail read settles', async () => {
    const current = state({ detail: detail(), history: [historyItem()], nextBefore: 'older-version', status: 'loading' });
    const host = await mount(await component(), { state: current });
    try {
        for (const label of ['重新读取导出版本', '读取更早导出版本', '打开导出版本 3', '下载 PPTX', '查询导出状态']) {
            assert.equal(button(host.root, label).props.disabled, true, label);
            click(button(host.root, label));
        }
        for (const event of ['reload-packages', 'load-older-packages', 'open-package', 'download-package-artifact', 'refresh-package'])
            assert.equal(host.emitted[event], undefined, event);
        current.packages.status = 'failed'; await settle();
        assert.equal(button(host.root, '重新读取导出版本').props.disabled, false);
        assert.equal(button(host.root, '下载 PPTX').props.disabled, false);
        click(button(host.root, '下载 PPTX')); assert.deepEqual(host.emitted['download-package-artifact'], [['pptx-a']]);
    } finally { host.close(); }
});

test('accepted package response retains every action lock until context reconciliation finishes', async () => {
    const current = state({ detail: detail(), history: [historyItem()], nextBefore: 'older-version', status: 'complete', canCreate: true, canRetry: true });
    current.packageWriteBusy = true;
    const host = await mount(await component(), { state: current });
    try {
        for (const label of ['导出已审阅的保存版本', '重新读取导出版本', '读取更早导出版本', '打开导出版本 3', '下载 PPTX', '查询导出状态', '重试失败格式']) {
            assert.equal(button(host.root, label).props.disabled, true, label); click(button(host.root, label));
        }
        current.packages.canReplay = true; await settle();
        assert.equal(button(host.root, '用原请求重新确认导出').props.disabled, true);
        click(button(host.root, '用原请求重新确认导出'));
        for (const event of ['create-package', 'reload-packages', 'load-older-packages', 'open-package', 'download-package-artifact', 'refresh-package', 'retry-package', 'replay-package'])
            assert.equal(host.emitted[event], undefined, event);
        assert.equal(section(host).props['aria-busy'], true);
        current.packageWriteBusy = false; current.packages.canReplay = false; current.packages.status = 'running'; await settle();
        assert.equal(button(host.root, '下载 PPTX').props.disabled, false, 'ready partial-success format remains usable without a lock');
        click(button(host.root, '下载 PPTX')); assert.deepEqual(host.emitted['download-package-artifact'], [['pptx-a']]);
    } finally { host.close(); }
});

test('Work package lock disables requirement save chat send cancel and task create while editors remain editable', async () => {
    globals(); const current = Vue.reactive(createTeacherWorkState());
    Object.assign(current, { task: { task_id: 'task-a', title: '循环教学', target_slide_count: 6 }, taskReadStatus: 'ready',
        privateTaskAvailability: { create: true, read: true, update: true }, composerStatus: 'unsaved', composerText: '保留需求',
        privateChatAvailability: { send: true, history: true, read_run: true, cancel: true }, chatText: '教学问题', packageWriteBusy: true });
    current.packages = state({ detail: detail(), status: 'complete' }).packages;
    const work = (await import('../js/components/teacher-work/TeacherWork.js')).default;
    const host = await mount(work, { state: current, menus: [], currentUser: {} });
    try {
        for (const [label, event] of [['保存需求', 'save-working'], ['发送教学问题', 'send-chat']]) {
            assert.equal(button(host.root, label).props.disabled, true, label); click(button(host.root, label));
            assert.equal(host.emitted[event], undefined, event);
        }
        const requirement = find(host.root, node => node.props.id === 'teacher-work-input');
        const question = find(host.root, node => node.props.id === 'teacher-work-chat-input');
        const slides = find(host.root, node => node.props.id === 'teacher-work-target-slides');
        assert.notEqual(requirement.props.disabled, true); assert.notEqual(question.props.disabled, true); assert.equal(slides.props.disabled, false);
        requirement.props.onInput({ target: { value: '继续编辑需求' } }); question.props.onInput({ target: { value: '继续编辑问题' } });
        assert.deepEqual(host.emitted['update-input'], [['继续编辑需求']]); assert.deepEqual(host.emitted['update-chat-text'], [['继续编辑问题']]);
        current.chatRun = { run_id: 'chat-a', stage: 'PENDING' }; current.chatStatus = 'running'; await settle();
        assert.equal(button(host.root, '取消当前问题').props.disabled, true); click(button(host.root, '取消当前问题'));
        assert.equal(host.emitted['cancel-chat'], undefined);
        current.packageWriteBusy = false; await settle();
        assert.equal(button(host.root, '取消当前问题').props.disabled, false);
        current.packageWriteBusy = true; current.createOpen = true; await settle();
        assert.equal(button(host.root, '创建私人任务').props.disabled, true); click(button(host.root, '创建私人任务'));
        assert.equal(host.emitted['create-task'], undefined);
        assert.notEqual(find(host.root, node => node.props.id === 'teacher-work-create-title').props.disabled, true);
        current.packageWriteBusy = false; await settle(); assert.equal(button(host.root, '创建私人任务').props.disabled, false);
    } finally { host.close(); }
});

test('expired package error directs an explicit new export from the current saved reviewed version', async () => {
    const current = state({ detail: detail({ retry_available: false }), canRetry: false, canCreate: true,
        error: { reason: 'package_deadline_expired' } });
    const host = await mount(await component(), { state: current });
    try {
        const alert = find(host.root, node => node.props.role === 'alert'); assert.ok(alert);
        assert.match(textOf(alert), /已过期|已超时/);
        assert.match(textOf(alert), /不能重试/);
        assert.match(textOf(alert), /已有文件/);
        assert.match(textOf(alert), /当前.*已保存.*审阅.*创建新导出/);
        assert.doesNotMatch(textOf(alert), /重试入口|重新保存|重新审阅/);
        assert.equal(button(host.root, '重试失败格式'), undefined);
        assert.equal(button(host.root, '导出已审阅的保存版本').props.disabled, false);
        assert.equal(host.emitted['create-package'], undefined);
        click(button(host.root, '导出已审阅的保存版本')); assert.deepEqual(host.emitted['create-package'], [[]]);
    } finally { host.close(); }
});
test('verified shared material errors give actionable bounded text while oversized package response keeps result uncertainty explicit',async()=>{
    const cases=[['normalization_required',/整理|规范/],['material_text_unrepresentable',/字符|格式/],['material_sources_unavailable',/资料|来源/],
        ['private_materials_disabled',/手动材料.*暂不可用/],['package_response_too_large',/未确认.*原请求|原请求.*未确认/]];
    for(const [reason,expected] of cases){const current=state({error:{reason}}),host=await mount(await component(),{state:current});
        try{const alert=find(host.root,node=>node.props.role==='alert');assert.match(textOf(alert),expected,reason);assert.doesNotMatch(textOf(alert),/\/var\/|owner_subject|<img/);}
        finally{host.close();}}
    const current=state({capabilities:{status:'ready',data:{...capabilities().data,create:false,retry:false,reasons:{create:'materials_unavailable',retry:'materials_unavailable'}},reason:null}}),host=await mount(await component(),{state:current});
    try{assert.match(textOf(host.root),/手动材料或引用来源暂不可用/);}finally{host.close();}
});
test('persisted READY metadata honors current unavailable history and keeps a healthy sibling downloadable',async()=>{
    const version=detail({run:{run_id:'run-a',stage:'COMPLETE',attempt:1,error_code:null},retry_available:false,
        artifacts:[readyArtifact(),readyArtifact({kind:'docx'})]});
    const item=historyItem({stage:'COMPLETE',artifacts:[{artifact_id:'pptx-a',kind:'pptx',state:'READY',download_available:false},
        {artifact_id:'docx-a',kind:'docx',state:'READY',download_available:true}]});
    const current=state({detail:version,history:[item]}),host=await mount(await component(),{state:current});
    try{assert.equal(button(host.root,'下载 PPTX').props.disabled,true);assert.equal(button(host.root,'下载 DOCX').props.disabled,false);
        assert.match(textOf(host.root),/当前文件暂不可下载/);click(button(host.root,'下载 PPTX'));assert.equal(host.emitted['download-package-artifact'],undefined);
        click(button(host.root,'下载 DOCX'));assert.deepEqual(host.emitted['download-package-artifact'],[['docx-a']]);
    }finally{host.close();}
});
test('known unavailable artifact survives displayed-page reset until explicit positive server observation',async()=>{
    const current=state({detail:detail({artifacts:[readyArtifact(),readyArtifact({kind:'docx'})]}),history:[],
        unavailableArtifacts:{'pptx-a':'version-a'}}),host=await mount(await component(),{state:current});
    try{assert.equal(button(host.root,'下载 PPTX').props.disabled,true);assert.match(textOf(host.root),/当前文件暂不可下载/);
        delete current.packages.unavailableArtifacts['pptx-a'];current.packages.history=[historyItem()];await settle();
        assert.equal(button(host.root,'下载 PPTX').props.disabled,false);
    }finally{host.close();}
});
