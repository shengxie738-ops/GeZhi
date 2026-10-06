import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { Vue, mount, find, walk, textOf, settle } from './fixtures/teacherWorkHarness.mjs';
import { createTeacherWorkState } from '../js/controllers/teacherWorkState.js';
import TeacherWork from '../js/components/teacher-work/TeacherWork.js';

const sourceId = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
const message = (changes = {}) => ({ message_id: sourceId, role: 'assistant', run_id: 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',
    result_type: 'answer', plain_text: '已保存的真实回复', created_at: '2026-10-06T00:00:00Z', omitted_context: false, ...changes });
const currentState = () => Vue.reactive({ ...createTeacherWorkState(), task: { task_id: 'task-a', title: '合成任务' }, taskReadStatus: 'ready',
    materialProposals: { capabilities: { status: 'ready', data: { skill_ref: 'lesson_outline@1', generate: true, read: true,
        cancel: true, provider_configured: true, external_provider_verified: false, reasons: {} }, reason: null },
        sourceMessageId: null, selectedMessage: null, status: 'idle', run: null, proposal: null, freshness: null,
        error: null, retryAvailable: false, pendingReplace: false, canSelect: true, canGenerate: false, canRetry: false,
        canCancel: false, canRefresh: false, canAdopt: false } });
const sourceButtons = root => walk(root).filter(node => node.tag === 'button' && Object.hasOwn(node.props, 'data-material-proposal-source'));
const click = node => { assert.ok(node, 'control exists'); node.props.onClick(); };
const bindings = [
    ['select-material-proposal-source', 'SelectMaterialProposalSource', 'selectMaterialProposalSource'],
    ['generate-material-proposal', 'GenerateMaterialProposal', 'generateMaterialProposal'],
    ['retry-material-proposal', 'RetryMaterialProposal', 'retryMaterialProposal'],
    ['refresh-material-proposal', 'RefreshMaterialProposal', 'refreshMaterialProposal'],
    ['cancel-material-proposal', 'CancelMaterialProposal', 'cancelMaterialProposal'],
    ['adopt-material-proposal', 'AdoptMaterialProposal', 'adoptMaterialProposal'],
    ['confirm-material-proposal-replace', 'ConfirmMaterialProposalReplace', 'confirmMaterialProposalReplace'],
    ['cancel-material-proposal-replace', 'CancelMaterialProposalReplace', 'cancelMaterialProposalReplace'],
    ['retry-material-proposals-capabilities', 'RetryMaterialProposalsCapabilities', 'retryMaterialProposalsCapabilities'],
    ['open-material-proposal-run', 'OpenMaterialProposalRun', 'openMaterialProposalRun'],
    ['reload-material-proposal-history', 'ReloadMaterialProposalHistory', 'reloadMaterialProposalHistory']
];

// Production parent + child templates on shipped Vue; finite local host without browser, app entrypoint, or network.
test('persisted assistant replies with run IDs offer explicit source selection without selecting the latest automatically', async () => {
    const state = currentState(); state.messages = [message({ message_id: 'user', role: 'user' }), message({ message_id: 'tool', role: 'tool' }),
        message({ message_id: 'no-run', run_id: null }), message(), message({ message_id: 'older' })];
    const host = await mount(TeacherWork, { state });
    try {
        const controls = sourceButtons(host.root); assert.equal(controls.length, 2, 'only persisted assistant replies with run IDs offer source controls');
        assert.equal(state.materialProposals.sourceMessageId, null); assert.deepEqual(host.emitted, {});
        assert.ok(controls.every(control => control.props['aria-pressed'] === false));
        click(controls[0]); assert.deepEqual(host.emitted['select-material-proposal-source'], [[sourceId]]);
        assert.match(textOf(controls[0]), /选为建议来源/);
        assert.doesNotMatch(textOf(controls[0].parent), /已完成回复|来源已验证/);
        state.materialProposals.sourceMessageId = sourceId; state.materialProposals.selectedMessage = message(); await settle();
        assert.equal(sourceButtons(host.root)[0].props['aria-pressed'], true);
    } finally { host.close(); }
});

test('source selection rechecks the explicit local canSelect gate on click', async () => {
    const state = currentState(); state.messages = [message()]; const host = await mount(TeacherWork, { state });
    try {
        state.materialProposals.canSelect = false; await settle();
        assert.equal(sourceButtons(host.root)[0].props.disabled, true); click(sourceButtons(host.root)[0]);
        assert.equal(host.emitted['select-material-proposal-source'], undefined);
        state.materialProposals.canSelect = true; await settle(); click(sourceButtons(host.root)[0]);
        assert.deepEqual(host.emitted['select-material-proposal-source'], [[sourceId]]);
        delete state.materialProposals; await settle(); assert.equal(sourceButtons(host.root)[0].props.disabled, true);
    } finally { host.close(); }
});

test('proposal child actions are emitted through TeacherWork without save approve or export side effects', async () => {
    const state = currentState(); state.messages = [message()]; state.materialProposals.sourceMessageId = sourceId;
    state.materialProposals.selectedMessage = message(); state.materialProposals.canGenerate = true;
    const host = await mount(TeacherWork, { state });
    try {
        const proposalSection = find(host.root, node => Object.hasOwn(node.props, 'data-teacher-work-material-proposals')); assert.ok(proposalSection);
        click(find(proposalSection, node => node.tag === 'button' && textOf(node) === '使用 lesson_outline@1 生成建议'));
        assert.deepEqual(host.emitted['generate-material-proposal'], [[]]);
        assert.equal(host.emitted['save-materials'], undefined); assert.equal(host.emitted['approve-materials'], undefined);
        assert.equal(host.emitted['create-package'], undefined);
        state.createOpen = true; await settle();
        assert.equal(find(host.root, node => Object.hasOwn(node.props, 'data-teacher-work-material-proposals')), undefined);
    } finally { host.close(); }
});

test('main and HTML bind all explicit proposal events to their hook methods without adding a provider call', () => {
    const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8'), main = readFileSync(new URL('../js/main.js', import.meta.url), 'utf8');
    for (const [event, binding, method] of bindings) {
        assert.ok(TeacherWork.emits.includes(event), event + ' declared');
        assert.ok(html.includes('@' + event + '="teacherWork' + binding + '"'), event + ' bound');
        assert.ok(main.includes('teacherWork' + binding + ': teacherWork.' + method), method + ' exposed');
    }
});

test('Skills catalog shows only lesson_outline@1 and leaves other skills and plugins as disabled placeholders', async () => {
    const state = currentState(); state.presentation.catalogOpen = 'skills'; const host = await mount(TeacherWork, { state });
    try {
        const dialog = find(host.root, node => node.props.role === 'dialog');
        assert.match(textOf(dialog), /lesson_outline@1/); assert.match(textOf(dialog), /其他 Skills 暂未开放/);
        assert.equal(find(dialog, node => node.tag === 'button' && textOf(node) === '其他 Skills').props.disabled, true);
        assert.equal(walk(dialog).filter(node => ['input', 'select', 'a'].includes(node.tag)).length, 0);
        state.presentation.catalogOpen = 'store'; await settle(); const store = find(host.root, node => node.props.role === 'dialog');
        assert.match(textOf(store), /插件.*暂不可用|尚未接通教师插件目录/);
        assert.equal(walk(store).filter(node => node.tag === 'button' && /添加|连接|执行/.test(textOf(node))).length, 0);
    } finally { host.close(); }
});


test('proposal history open and reload route through the Work parent without changing the selected reply', async () => {
    const state = currentState(); state.materialProposals.historyStatus = 'ready';
    state.materialProposals.history = [{ run_id: 'historical-run', stage: 'COMPLETE', input_revision: 1, source_message_id: sourceId }];
    const host = await mount(TeacherWork, { state });
    try {
        const record = find(host.root, node => node.props['data-open-material-proposal-run'] === 'historical-run'); assert.ok(record);
        click(record); assert.deepEqual(host.emitted['open-material-proposal-run'], [['historical-run']]);
        click(find(host.root, node => node.tag === 'button' && textOf(node) === '重新读取建议记录'));
        assert.deepEqual(host.emitted['reload-material-proposal-history'], [[]]);
        assert.equal(state.materialProposals.sourceMessageId, null); assert.equal(host.emitted['adopt-material-proposal'], undefined);
    } finally { host.close(); }
});
