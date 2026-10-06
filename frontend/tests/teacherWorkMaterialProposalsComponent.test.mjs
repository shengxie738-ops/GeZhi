import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { Vue, mount, find, walk, textOf, button, settle } from './fixtures/teacherWorkHarness.mjs';
import { materialLesson, materialSlides } from './fixtures/teacherWorkMaterialsFixtures.mjs';

const componentURL = new URL('../js/components/teacher-work/TeacherWorkMaterialProposals.js', import.meta.url);
const sourceId = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
const source = () => ({ message_id: sourceId, role: 'assistant', run_id: 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',
    plain_text: '已保存的教学回复', created_at: '2026-10-06T00:00:00Z', omitted_context: false });
const capability = () => ({ status: 'ready', data: { skill_ref: 'lesson_outline@1', generate: true, read: true,
    cancel: true, provider_configured: true, external_provider_verified: false, reasons: {} }, reason: null });
const proposal = () => ({ lesson: { ...materialLesson(), title: '<img src=x onerror=alert(1)>', objectives: ['目标全文'],
    key_points: ['重点全文'], difficulties: ['难点全文'], questions: ['问题全文'], exercises: ['练习全文'], homework: ['作业全文'],
    summary: '总结全文', citations: [{ name: '引用全文', page: 3, excerpt: '<script>引用摘录</script>' }] },
    slides: materialSlides().map((slide, index) => ({ ...slide, title: '幻灯片标题' + index, body: ['要点全文' + index],
        notes: '讲稿全文' + index, source_note: '来源全文' + index })), skill_ref: 'lesson_outline@1', input_revision: 2,
    source_message_id: sourceId, input_digest: 'a'.repeat(64), source_digest: 'b'.repeat(64),
    omitted_context: true, created_at: '2026-10-06T00:00:00Z' });
const state = (changes = {}) => Vue.reactive({ task: { task_id: 'task-a' }, createOpen: false, messages: [source()],
    materials: { dirty: false }, materialProposals: { capabilities: capability(), sourceMessageId: sourceId,
        selectedMessage: source(), status: 'idle', run: null, proposal: null, freshness: null, error: null,
        retryAvailable: false, pendingReplace: false, canSelect: true, canGenerate: true, canRetry: false,
        canCancel: false, canRefresh: false, canAdopt: false, ...changes } });
async function component() { assert.ok(existsSync(componentURL), 'material proposal preview component is missing'); return (await import(componentURL)).default; }
const click = node => { assert.ok(node, 'control exists'); node.props.onClick(); };
const generateLabel = '使用 lesson_outline@1 生成建议';
const adoptLabel = '填入手动草稿';

// Real compiled shipped Vue in a finite synthetic desktop host; no browser, provider, entrypoint, or timers.
test('proposal section fails closed before capability and source confirmation without automatic actions', async () => {
    const current = state(); delete current.materialProposals;
    const host = await mount(await component(), { state: current });
    try {
        assert.ok(find(host.root, node => Object.hasOwn(node.props, 'data-teacher-work-material-proposals')));
        assert.match(textOf(host.root), /大纲建议/); assert.match(textOf(host.root), /能力尚未确认/);
        assert.match(textOf(host.root), /选为建议来源/); assert.match(textOf(host.root), /服务端.*已完成/);
        assert.equal(button(host.root, generateLabel).props.disabled, true); click(button(host.root, generateLabel));
        assert.deepEqual(host.emitted, {}); assert.equal(walk(host.root).filter(node => ['input', 'textarea', 'select', 'a'].includes(node.tag)).length, 0);
    } finally { host.close(); }
});

test('explicit generate uses the one curated skill and fails closed for each capability source and lifecycle gate', async () => {
    const current = state(), host = await mount(await component(), { state: current });
    try {
        assert.equal(button(host.root, generateLabel).props.disabled, false); click(button(host.root, generateLabel));
        assert.deepEqual(host.emitted['generate-material-proposal'], [[]]);
        const changes = [
            () => { current.materialProposals.canGenerate = false; },
            () => { current.materialProposals.sourceMessageId = null; },
            () => { current.materialProposals.selectedMessage = { ...source(), role: 'user' }; },
            () => { current.materialProposals.selectedMessage = { ...source(), run_id: null }; },
            () => { current.materialProposals.capabilities.status = 'error'; },
            () => { current.materialProposals.capabilities.data.generate = false; },
            () => { current.materialProposals.capabilities.data.provider_configured = false; },
            () => { current.materialProposals.capabilities.data.external_provider_verified = true; },
            () => { current.materialProposals.capabilities.data.skill_ref = 'other@1'; },
            () => { current.materialProposals.retryAvailable = true; },
            () => { current.materialProposals.status = 'generating'; },
            () => { current.packageWriteBusy = true; },
            () => { current.createOpen = true; }
        ];
        for (const change of changes) {
            current.materialProposals = state().materialProposals; current.createOpen = false; current.packageWriteBusy = false;
            change(); await settle(); assert.equal(button(host.root, generateLabel)?.props.disabled ?? true, true);
            const control = button(host.root, generateLabel); if (control) click(control);
            assert.equal(host.emitted['generate-material-proposal'].length, 1);
        }
    } finally { host.close(); }
});

test('provider configuration never implies an externally verified model', async () => {
    const current = state(), host = await mount(await component(), { state: current });
    try {
        assert.match(textOf(host.root), /AI 已配置.*外部模型尚未验证/);
        current.materialProposals.capabilities.data.provider_configured = false; await settle();
        assert.match(textOf(host.root), /AI 尚未配置/); assert.equal(button(host.root, generateLabel).props.disabled, true);
        assert.equal(walk(host.root).filter(node => node.tag === 'select').length, 0);
        assert.doesNotMatch(textOf(host.root), /外部模型已验证|已连通.*模型|已调用.*模型/);
    } finally { host.close(); }
});

test('generation statuses are truthful about queue completion uncertainty and cancellation', async () => {
    const current = state(), host = await mount(await component(), { state: current });
    try {
        for (const [status, expected] of Object.entries({ generating: /正在提交.*尚未确认/, uncertain: /提交结果未确认/,
            queued: /已入队.*等待/, running: /正在生成.*尚未完成/, checking: /正在查询/,
            complete: /生成已完成.*只读建议/, failed: /生成失败/, cancelled: /已取消/,
            paused: /状态未确认.*手动查询/, cancelling: /正在请求取消.*服务端/, error: /操作未完成/ })) {
            current.materialProposals.status = status; await settle(); assert.match(textOf(host.root), expected, status);
        }
    } finally { host.close(); }
});

test('uncertain generation exposes only an explicit original-request retry with its own gate', async () => {
    const current = state({ status: 'uncertain', retryAvailable: true, canRetry: true }), host = await mount(await component(), { state: current });
    try {
        assert.equal(button(host.root, generateLabel).props.disabled, true);
        click(button(host.root, '用同一请求重试建议')); assert.deepEqual(host.emitted['retry-material-proposal'], [[]]);
        current.materialProposals.canRetry = false; await settle();
        assert.equal(button(host.root, '用同一请求重试建议').props.disabled, true); click(button(host.root, '用同一请求重试建议'));
        assert.equal(host.emitted['retry-material-proposal'].length, 1); assert.equal(host.emitted['generate-material-proposal'], undefined);
    } finally { host.close(); }
});
test('COMPLETE preview with an unconfirmed command exposes read-authorized original retry while generation stays disabled', async () => {
    const current = state({ status: 'complete', run: { run_id: 'run-a', stage: 'COMPLETE' }, proposal: proposal(),
        freshness: { adoptable: true, reason: null }, retryAvailable: true, canRetry: true, canGenerate: false, canAdopt: false });
    current.materialProposals.capabilities.data.generate = false;
    current.materialProposals.capabilities.data.provider_configured = false;
    const host = await mount(await component(), { state: current });
    try {
        assert.equal(button(host.root, generateLabel).props.disabled, true);
        assert.equal(button(host.root, adoptLabel).props.disabled, true);
        assert.equal(button(host.root, '用同一请求重试建议').props.disabled, false);
        click(button(host.root, '用同一请求重试建议')); assert.deepEqual(host.emitted['retry-material-proposal'], [[]]);
        const gates = [
            () => { current.materialProposals.canRetry = false; },
            () => { current.materialProposals.capabilities.data.read = false; },
            () => { current.materialProposals.capabilities.status = 'loading'; },
            () => { current.materialProposals.capabilities.data.external_provider_verified = true; },
            () => { current.materialProposals.capabilities.data.skill_ref = 'other@1'; },
            () => { current.materialProposals.status = 'generating'; },
            () => { current.packageWriteBusy = true; },
            () => { current.createOpen = true; },
            () => { current.task = null; }
        ];
        for (const change of gates) {
            current.materialProposals.canRetry = true; current.materialProposals.capabilities = capability();
            current.materialProposals.capabilities.data.generate = false; current.materialProposals.status = 'complete';
            current.packageWriteBusy = false; current.createOpen = false; current.task = { task_id: 'task-a' };
            change(); await settle();
            const control = button(host.root, '用同一请求重试建议');
            assert.equal(control?.props.disabled ?? true, true);
            if (control) click(control); assert.equal(host.emitted['retry-material-proposal'].length, 1);
        }
        assert.equal(host.emitted['generate-material-proposal'], undefined); assert.equal(host.emitted['adopt-material-proposal'], undefined);
    } finally { host.close(); }
});

test('manual refresh and cancel are explicit and independently capability gated', async () => {
    const current = state({ status: 'running', run: { run_id: 'run-a', stage: 'OUTLINE_RUNNING' }, canCancel: true, canRefresh: true }),
        host = await mount(await component(), { state: current });
    try {
        click(button(host.root, '查询建议状态')); click(button(host.root, '取消建议生成'));
        assert.deepEqual(host.emitted['refresh-material-proposal'], [[]]); assert.deepEqual(host.emitted['cancel-material-proposal'], [[]]);
        current.materialProposals.capabilities.data.read = false; current.materialProposals.capabilities.data.cancel = false; await settle();
        assert.equal(button(host.root, '查询建议状态').props.disabled, true); assert.equal(button(host.root, '取消建议生成').props.disabled, true);
        click(button(host.root, '查询建议状态')); click(button(host.root, '取消建议生成'));
        assert.equal(host.emitted['refresh-material-proposal'].length, 1); assert.equal(host.emitted['cancel-material-proposal'].length, 1);
        current.materialProposals.status = 'cancelling'; await settle(); assert.match(textOf(host.root), /以服务端确认结果为准/);
    } finally { host.close(); }
});

test('full proposal is escaped and read only including empty fields teaching stages citations and both slide columns', async () => {
    const value = proposal(); value.slides[1] = { ...value.slides[1], layout: 'two_column', body: [], columns: [['左栏全文'], ['右栏全文']] };
    const current = state({ status: 'complete', proposal: value, freshness: { adoptable: true, reason: null }, canAdopt: true }),
        before = JSON.stringify(current), host = await mount(await component(), { state: current });
    try {
        const preview = find(host.root, node => Object.hasOwn(node.props, 'data-material-proposal-preview')); assert.ok(preview);
        for (const content of ['<img src=x onerror=alert(1)>', '循环', '程序设计', '一年级', '45', '目标全文', '重点全文', '难点全文',
            '问题全文', '练习全文', '作业全文', '总结全文', '讲解', '讲解循环条件', '引用全文', '3', '<script>引用摘录</script>', '左栏全文', '右栏全文',
            ...value.slides.flatMap(slide => [slide.title, slide.notes, slide.source_note])]) assert.ok(textOf(preview).includes(content), content);
        assert.equal(walk(preview).filter(node => ['input', 'textarea', 'select', 'img', 'script', 'a'].includes(node.tag)).length, 0);
        assert.ok(walk(preview).every(node => node.props.innerHTML === undefined));
        assert.match(textOf(preview), /证据引用.*无/); assert.match(textOf(host.root), /部分历史上下文已省略/);
        assert.equal(JSON.stringify(current), before); assert.deepEqual(host.emitted, {});
        const sourceText = readFileSync(componentURL, 'utf8'); assert.doesNotMatch(sourceText, /v-html|innerHTML|fetch\(|localStorage|setInterval|setTimeout/);
    } finally { host.close(); }
});

test('adoption emits only the local draft action and retains stale preview while blocking adoption', async () => {
    const current = state({ status: 'complete', proposal: proposal(), freshness: { adoptable: true, reason: null }, canAdopt: true }),
        host = await mount(await component(), { state: current });
    try {
        assert.match(textOf(host.root), /手动保存.*审阅/); click(button(host.root, adoptLabel));
        assert.deepEqual(host.emitted['adopt-material-proposal'], [[]]);
        assert.equal(host.emitted['save-materials'], undefined); assert.equal(host.emitted['approve-materials'], undefined); assert.equal(host.emitted['create-package'], undefined);
        current.materialProposals.freshness = { adoptable: false, reason: 'stale_input_revision' }; await settle();
        assert.equal(button(host.root, adoptLabel).props.disabled, true); click(button(host.root, adoptLabel));
        assert.match(textOf(host.root), /任务版本已变更/); assert.ok(find(host.root, node => Object.hasOwn(node.props, 'data-material-proposal-preview')));
        assert.equal(host.emitted['adopt-material-proposal'].length, 1);
        current.materialProposals.freshness = null; await settle(); assert.equal(button(host.root, adoptLabel).props.disabled, true);
    } finally { host.close(); }
});

test('dirty draft requires a separate visible replace choice with a reversible keep choice', async () => {
    const current = state({ status: 'complete', proposal: proposal(), freshness: { adoptable: true, reason: null }, canAdopt: true, pendingReplace: true });
    current.materials.dirty = true;
    const host = await mount(await component(), { state: current });
    try {
        assert.match(textOf(host.root), /当前手动草稿有未保存编辑/); assert.equal(button(host.root, adoptLabel), undefined);
        click(button(host.root, '替换当前未保存草稿')); assert.deepEqual(host.emitted['confirm-material-proposal-replace'], [[]]);
        click(button(host.root, '保留当前草稿')); assert.deepEqual(host.emitted['cancel-material-proposal-replace'], [[]]);
        assert.equal(host.emitted['adopt-material-proposal'], undefined); assert.equal(host.emitted['update-materials-draft'], undefined);
        current.materialProposals.canAdopt = false; await settle();
        assert.equal(button(host.root, '替换当前未保存草稿').props.disabled, true); click(button(host.root, '替换当前未保存草稿'));
        assert.equal(host.emitted['confirm-material-proposal-replace'].length, 1);
    } finally { host.close(); }
});

test('controlled errors explain unavailable or stale operations without exposing raw provider payloads', async () => {
    const current = state({ capabilities: { status: 'unavailable', data: null, reason: 'private_material_proposals_disabled' },
        error: { reason: 'provider_timeout', detail: 'secret-provider-trace' } }), host = await mount(await component(), { state: current });
    try {
        assert.match(textOf(host.root), /建议生成暂未开放/); assert.match(textOf(host.root), /生成超时/); assert.doesNotMatch(textOf(host.root), /secret-provider-trace/);
        click(button(host.root, '重新检查建议能力')); assert.deepEqual(host.emitted['retry-material-proposals-capabilities'], [[]]);
        current.materialProposals.capabilities.status = 'loading'; await settle();
        assert.match(textOf(host.root), /正在检查建议能力/); click(button(host.root, '重新检查建议能力'));
        assert.equal(host.emitted['retry-material-proposals-capabilities'].length, 1);
    } finally { host.close(); }
});

const historyRun = (id, stage = 'COMPLETE') => ({ run_id: id, stage, input_revision: 2, source_message_id: sourceId });
const historySection = host => find(host.root, node => Object.hasOwn(node.props, 'data-material-proposal-history'));
const historyButtons = host => { const section = historySection(host); assert.ok(section, 'authoritative history section exists');
    return walk(section).filter(node => node.tag === 'button' && Object.hasOwn(node.props, 'data-open-material-proposal-run')); };

test('authoritative history shows unqueried loading empty and failed states truthfully without inventing saved proposals', async () => {
    const current = state({ history: [], historyStatus: 'idle' }), host = await mount(await component(), { state: current });
    try {
        assert.ok(historySection(host), 'authoritative history section exists');
        assert.match(textOf(historySection(host)), /尚未读取建议记录/); assert.deepEqual(host.emitted, {});
        click(button(host.root, '重新读取建议记录')); assert.deepEqual(host.emitted['reload-material-proposal-history'], [[]]);
        current.materialProposals.historyStatus = 'loading'; await settle();
        assert.match(textOf(historySection(host)), /正在读取建议记录/); assert.equal(button(host.root, '重新读取建议记录').props.disabled, true);
        click(button(host.root, '重新读取建议记录')); assert.equal(host.emitted['reload-material-proposal-history'].length, 1);
        current.materialProposals.historyStatus = 'ready'; await settle(); assert.match(textOf(historySection(host)), /暂无已保存的建议记录/);
        current.materialProposals.historyStatus = 'error'; await settle(); assert.match(textOf(historySection(host)), /建议记录读取失败/);
        assert.equal(historyButtons(host).length, 0); assert.equal(host.emitted['open-material-proposal-run'], undefined);
    } finally { host.close(); }
});

test('history preserves server order and reopens an explicitly chosen run without selecting a reply or adopting content', async () => {
    const second = '22222222-2222-4222-8222-222222222222', first = '11111111-1111-4111-8111-111111111111';
    const current = state({ history: [historyRun(second, 'FAILED'), historyRun(first)], historyStatus: 'ready', sourceMessageId: null, selectedMessage: null }),
        host = await mount(await component(), { state: current });
    try {
        const controls = historyButtons(host); assert.equal(controls.length, 2);
        assert.deepEqual(controls.map(control => control.props['data-open-material-proposal-run']), [second, first]);
        assert.match(textOf(historySection(host)), /生成失败/); assert.match(textOf(historySection(host)), /生成完成/);
        assert.ok(textOf(historySection(host)).includes(sourceId)); assert.match(textOf(historySection(host)), /输入版本 2/);
        click(controls[1]); assert.deepEqual(host.emitted['open-material-proposal-run'], [[first]]);
        assert.equal(host.emitted['adopt-material-proposal'], undefined); assert.equal(host.emitted['generate-material-proposal'], undefined);
        assert.equal(current.materialProposals.sourceMessageId, null); assert.equal(current.materialProposals.selectedMessage, null);
        current.materialProposals.run = historyRun(first); await settle(); assert.equal(historyButtons(host)[1].props['aria-pressed'], true);
        current.materialProposals.history = [historyRun(second, 'FAILED')]; await settle();
        click(controls[1]); assert.equal(host.emitted['open-material-proposal-run'].length, 1, 'detached control cannot reopen a removed record');
    } finally { host.close(); }
});

test('history reads require confirmed read capability and remain independent of provider configuration', async () => {
    const current = state({ history: [historyRun('run-a')], historyStatus: 'ready' });
    current.materialProposals.capabilities.data.generate = false; current.materialProposals.capabilities.data.provider_configured = false;
    const host = await mount(await component(), { state: current });
    try {
        assert.equal(historyButtons(host)[0].props.disabled, false); click(historyButtons(host)[0]);
        assert.deepEqual(host.emitted['open-material-proposal-run'], [['run-a']]);
        for (const change of [() => { current.materialProposals.capabilities.data.read = false; },
            () => { current.materialProposals.capabilities.status = 'error'; }, () => { current.materialProposals.historyStatus = 'loading'; },
            () => { current.packageWriteBusy = true; }]) {
            current.materialProposals.capabilities = capability(); current.materialProposals.historyStatus = 'ready'; current.packageWriteBusy = false;
            change(); await settle(); assert.equal(historyButtons(host)[0].props.disabled, true); click(historyButtons(host)[0]);
            click(button(host.root, '重新读取建议记录')); assert.equal(host.emitted['open-material-proposal-run'].length, 1);
            assert.equal(host.emitted['reload-material-proposal-history'], undefined);
        }
    } finally { host.close(); }
});

test('all authoritative freshness blockers remain readable while preventing draft adoption', async () => {
    const current = state({ status: 'complete', proposal: proposal(), canAdopt: true }), host = await mount(await component(), { state: current });
    try {
        for (const [reason, expected] of Object.entries({ PROPOSAL_NOT_READY: /建议尚未确认可用/, STALE_INPUT_REVISION: /任务版本已变更/,
            SOURCE_CHANGED: /引用来源已变更/, SOURCE_UNAVAILABLE: /引用来源暂不可用/, SOURCE_MESSAGE_INELIGIBLE: /来源回复未通过.*资格检查/ })) {
            current.materialProposals.freshness = { adoptable: false, reason }; await settle();
            assert.match(textOf(host.root), expected); assert.equal(button(host.root, adoptLabel).props.disabled, true);
        }
    } finally { host.close(); }
});

test('proposal-specific controlled failures have actionable labels and failure codes never render provider details', async () => {
    const current = state({ run: { run_id: 'run-a', stage: 'FAILED', error_code: 'PROVIDER_TIMEOUT', detail: 'secret-provider-body' } }),
        host = await mount(await component(), { state: current });
    try {
        for (const [reason, expected] of Object.entries({ proposal_run_limit: /建议记录已达保留上限/, proposal_context_too_large: /建议上下文过长/,
            live_gates_unverified: /执行条件尚未确认/, private_materials_disabled: /私人手动整理暂未开放/, work_ai_unavailable: /AI 服务暂不可用/,
            material_proposal_state_unavailable: /建议状态暂不可用/, commit_outcome_unknown: /提交结果尚未确认/ })) {
            current.materialProposals.error = { reason, detail: 'secret-provider-body' }; await settle(); assert.match(textOf(host.root), expected, reason);
            assert.doesNotMatch(textOf(host.root), /secret-provider-body/);
        }
        assert.match(textOf(host.root), /建议生成超时/);
    } finally { host.close(); }
});

test('unconfirmed commit query locator allows only explicit lookup without claiming admission or enabling cancellation adoption', async () => {
    const locator = '99999999-9999-4999-8999-999999999999';
    const current = state({ status: 'uncertain', run: null, queryRunId: locator, canRefresh: true, canCancel: true,
        canAdopt: true, proposal: null, freshness: null, retryAvailable: false });
    const host = await mount(await component(), { state: current });
    try {
        assert.deepEqual(host.emitted, {}, 'render does not redispatch an unknown commit');
        const refresh = button(host.root, '查询建议状态'); assert.ok(refresh, 'query locator exposes a lookup action');
        assert.equal(refresh.props.disabled, false); assert.match(textOf(host.root), /查询标识.*尚未确认执行记录/);
        assert.match(textOf(host.root), /提交结果未确认/); assert.doesNotMatch(textOf(host.root), /建议已入队|生成已完成/);
        assert.equal(button(host.root, '取消建议生成'), undefined); assert.equal(button(host.root, adoptLabel), undefined);
        click(refresh); assert.deepEqual(host.emitted['refresh-material-proposal'], [[]]);
        assert.equal(host.emitted['generate-material-proposal'], undefined); assert.equal(host.emitted['cancel-material-proposal'], undefined);
        assert.equal(host.emitted['adopt-material-proposal'], undefined); assert.equal(current.materialProposals.run, null);
        current.materialProposals.capabilities.data.read = false; await settle();
        assert.equal(button(host.root, '查询建议状态').props.disabled, true); click(button(host.root, '查询建议状态'));
        assert.equal(host.emitted['refresh-material-proposal'].length, 1);
        current.materialProposals.capabilities.data.read = true; current.materialProposals.canRefresh = false; await settle();
        assert.equal(button(host.root, '查询建议状态').props.disabled, true);
    } finally { host.close(); }
});
