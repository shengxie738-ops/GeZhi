import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createTeacherWorkState } from '../js/controllers/teacherWorkState.js';
import TeacherWork from '../js/components/teacher-work/TeacherWork.js';
import { mount, globals, textOf, button, find } from './fixtures/teacherWorkHarness.mjs';
import { materialLesson, materialSlides } from './fixtures/teacherWorkMaterialsFixtures.mjs';

test('desktop Work composes the isolated manual materials surface and forwards its explicit events', async () => {
    globals(); const state = createTeacherWorkState(); state.task = { task_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', title: '循环教学', target_slide_count: 6 };
    state.materials = { capabilities: { status: 'ready', data: { save: true, read: true, approve: true, source_configured: true, files: false }, reason: null },
        snapshot: null, draft: { lesson: materialLesson(), slides: materialSlides() }, dirty: true, status: 'ready', error: null, conflict: false,
        retryAvailable: false, canSave: true, canApprove: false, validationErrors: [], pendingReplace: false, lastReceipt: null };
    const host = await mount(TeacherWork, { state });
    try { assert.ok(textOf(host.root).includes('手动整理')); assert.ok(button(host.root, '保存为新大纲版本'));
        button(host.root, '保存为新大纲版本').props.onClick(); assert.deepEqual(host.emitted['save-materials'], [[]]);
        assert.ok(Object.hasOwn(button(host.root, '确认已审阅此保存版本').props, 'disabled'));
        assert.ok(find(host.root, node => node.props.id === 'teacher-work-chat-input'));
    } finally { host.close(); }
});

test('main desktop event boundary wires every materials action to the isolated lifecycle', () => {
    const main = readFileSync(new URL('../js/main.js', import.meta.url), 'utf8'), html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
    for (const name of ['UpdateMaterialsDraft', 'SaveMaterials', 'ReloadMaterials', 'ReplaceMaterialsDraft', 'CancelMaterialsReplace', 'ApproveMaterials', 'RetryMaterials', 'RetryMaterialsCapabilities'])
        assert.ok(main.includes(`teacherWork${name}: teacherWork.`), name);
    for (const name of ['update-materials-draft', 'save-materials', 'reload-materials', 'replace-materials-draft', 'cancel-materials-replace', 'approve-materials', 'retry-materials', 'retry-materials-capabilities'])
        assert.ok(html.includes(`@${name}="teacherWork`), name);
});
