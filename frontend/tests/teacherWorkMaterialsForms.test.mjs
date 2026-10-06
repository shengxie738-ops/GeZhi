import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { Vue, mount, find, walk, textOf, button, settle } from './fixtures/teacherWorkHarness.mjs';

const componentURL = new URL('../js/components/teacher-work/TeacherWorkMaterials.js', import.meta.url);
const clone = value => JSON.parse(JSON.stringify(value));
const lesson = () => ({ title: '手动课程', topic: '主题', course_name: '课程', audience: '对象', duration_minutes: 45,
    objectives: ['目标'], key_points: ['重点'], difficulties: ['难点'], questions: ['问题'], exercises: ['练习'], homework: ['作业'],
    summary: '总结', teaching_flow: [{ stage: '导入', minutes: 45, content: '手动内容' }], citations: [{ name: '真实名称', page: 0, excerpt: '引用文本' }] });
const slide = (index = 1) => ({ layout: 'bullets', title: '第' + index + '页', body: ['内容'], columns: [], notes: '讲稿', source_note: '手动填写', evidence_refs: [] });
const state = (changes = {}) => Vue.reactive({ task: { task_id: 'task-a', title: '任务', target_slide_count: 6 }, materials: {
    capabilities: { status: 'ready', data: { read: true, save: true, approve: true, files: false }, reason: null },
    snapshot: null, draft: { lesson: lesson(), slides: Array.from({ length: 6 }, (_, index) => slide(index + 1)) },
    dirty: false, status: 'ready', error: null, conflict: false, retryAvailable: false, canSave: true, canApprove: false,
    validationErrors: [], pendingReplace: false, lastReceipt: null, ...changes } });
async function component() { assert.ok(existsSync(componentURL), 'manual materials component is missing'); return (await import(componentURL)).default; }
const field = (root, name) => find(root, node => node.props['data-materials-field'] === name);
const click = node => { assert.ok(node, 'control exists'); node.props.onClick(); };
const input = (root, name, value) => { const node = field(root, name); assert.ok(node, name + ' is editable'); node.props.onInput({ target: { value } }); };
const latest = host => host.emitted['update-materials-draft'].at(-1)[0];
async function mountExpanded(current) { const host = await mount(await component(), { state: current }); click(button(host.root, '编辑教案与幻灯片')); await settle(); return host; }
const visibleTextOf = node => {
    if (node.props.hidden !== undefined && node.props.hidden !== false) return '';
    if (node.tag === 'details' && !node.props.open) return node.children.filter(child => child.tag === 'summary').map(visibleTextOf).join('');
    return node.tag === '#comment' ? '' : node.text + node.children.map(visibleTextOf).join('');
};

// These cases execute the compiled, shipped-Vue component in the finite synthetic host.
// No browser, network, app entrypoint, installs, timers, AI calls, or mobile QA.
test('manual materials form renders every lesson schema field with bounded native controls', async () => {
    const current = state(), host = await mountExpanded(current);
    try {
        assert.match(textOf(host.root), /手动整理/);
        const expected = ['title', 'topic', 'course_name', 'audience', 'duration_minutes', 'summary',
            'objectives.0', 'key_points.0', 'difficulties.0', 'questions.0', 'exercises.0', 'homework.0',
            'teaching_flow.0.stage', 'teaching_flow.0.minutes', 'teaching_flow.0.content', 'citations.0.name', 'citations.0.page', 'citations.0.excerpt'];
        for (const name of expected) assert.ok(field(host.root, 'lesson.' + name), name);
        assert.equal(Number(field(host.root, 'lesson.title').props.maxlength), 200);
        assert.equal(Number(field(host.root, 'lesson.summary').props.maxlength), 8000);
        assert.equal(Number(field(host.root, 'lesson.citations.0.excerpt').props.maxlength), 4000);
        assert.equal(Number(field(host.root, 'lesson.duration_minutes').props.min), 1);
        assert.equal(Number(field(host.root, 'lesson.duration_minutes').props.max), 600);
        assert.equal(Number(field(host.root, 'lesson.citations.0.page').props.min), 0);
    } finally { host.close(); }
});

test('lesson edits emit the whole detached draft without mutating props or discarding invalid empty items', async () => {
    const current = state(), original = clone(current.materials.draft), host = await mountExpanded(current);
    try {
        input(host.root, 'lesson.title', '<script>plain text</script>');
        let value = latest(host); assert.equal(value.lesson.title, '<script>plain text</script>'); assert.deepEqual(current.materials.draft, original);
        value.slides[0].body[0] = 'only clone changed'; assert.equal(current.materials.draft.slides[0].body[0], '内容');
        input(host.root, 'lesson.objectives.0', ''); assert.deepEqual(latest(host).lesson.objectives, ['']);
        input(host.root, 'lesson.duration_minutes', ''); assert.equal(latest(host).lesson.duration_minutes, '');
        input(host.root, 'lesson.teaching_flow.0.minutes', '15'); assert.equal(latest(host).lesson.teaching_flow[0].minutes, 15);
        input(host.root, 'lesson.citations.0.page', '2'); assert.equal(latest(host).lesson.citations[0].page, 2);
        input(host.root, 'lesson.citations.0.excerpt', '改过的原文'); assert.equal(latest(host).lesson.citations[0].excerpt, '改过的原文');
    } finally { host.close(); }
});

test('lesson arrays add and remove explicit items and respect 20-item and one-stage boundaries', async () => {
    const current = state(), host = await mountExpanded(current);
    try {
        click(button(host.root, '添加教学目标')); assert.deepEqual(latest(host).lesson.objectives, ['目标', '']);
        click(button(host.root, '删除教学目标第1项')); assert.deepEqual(latest(host).lesson.objectives, []);
        assert.equal(button(host.root, '删除教学流程第1阶段').props.disabled, true);
        click(button(host.root, '添加教学阶段')); assert.equal(latest(host).lesson.teaching_flow.length, 2);
        click(button(host.root, '添加引用')); assert.equal(latest(host).lesson.citations.length, 2);
        for (const name of ['objectives', 'key_points', 'difficulties', 'questions', 'exercises', 'homework']) current.materials.draft.lesson[name] = Array(20).fill('保留');
        current.materials.draft.lesson.teaching_flow = Array.from({ length: 20 }, () => ({ stage: '阶段', minutes: 1, content: '内容' }));
        current.materials.draft.lesson.citations = Array.from({ length: 20 }, () => ({ name: '', page: 0, excerpt: '' })); await settle();
        for (const label of ['教学目标', '教学重点', '教学难点', '课堂问题', '课堂练习', '课后作业']) assert.equal(button(host.root, '添加' + label).props.disabled, true);
        assert.equal(button(host.root, '添加教学阶段').props.disabled, true); assert.equal(button(host.root, '添加引用').props.disabled, true);
    } finally { host.close(); }
});

test('all slide layouts and plain text fields are editable and layout conversion never drops overflow', async () => {
    const current = state(), host = await mountExpanded(current);
    try {
        const selector = field(host.root, 'slides.0.layout'); assert.equal(selector.tag, 'select');
        assert.deepEqual(selector.children.filter(node => node.tag === 'option').map(node => node.props.value), ['title', 'section', 'bullets', 'two_column', 'question', 'summary']);
        assert.equal(Number(field(host.root, 'slides.0.title').props.maxlength), 60);
        assert.equal(Number(field(host.root, 'slides.0.body.0').props.maxlength), 90);
        assert.equal(Number(field(host.root, 'slides.0.notes').props.maxlength), 1200);
        assert.equal(Number(field(host.root, 'slides.0.source_note').props.maxlength), 120);
        current.materials.draft.slides[0].body = ['1', '2', '3', '4', '5', 'overflow']; await settle();
        field(host.root, 'slides.0.layout').props.onChange({ target: { value: 'two_column' } });
        let value = latest(host); assert.deepEqual(value.slides[0].body, []); assert.deepEqual(value.slides[0].columns, [['1', '2', '3', '4', '5', 'overflow'], []]);
        current.materials.draft = value; await settle();
        assert.ok(field(host.root, 'slides.0.columns.0.0')); assert.equal(button(host.root, '第1页左栏添加要点').props.disabled, true);
        current.materials.draft.slides[0].columns = [['left'], ['right1', 'right2', 'right3', 'right4', 'right5']]; await settle();
        field(host.root, 'slides.0.layout').props.onChange({ target: { value: 'summary' } });
        value = latest(host); assert.deepEqual(value.slides[0].body, ['left', 'right1', 'right2', 'right3', 'right4', 'right5']); assert.deepEqual(value.slides[0].columns, []);
        for (const entry of value.slides) assert.deepEqual(entry.evidence_refs, []);
        input(host.root, 'slides.0.title', '<b>纯文本</b>'); assert.equal(latest(host).slides[0].title, '<b>纯文本</b>');
    } finally { host.close(); }
});

test('slide list allows explicit bounded addition removal and reordering while exposing exact target', async () => {
    const current = state(), host = await mountExpanded(current);
    try {
        assert.match(textOf(host.root), /目标.*6.*当前.*6/);
        assert.equal(button(host.root, '删除第1页').props.disabled, true);
        assert.equal(button(host.root, '上移第1页').props.disabled, true); assert.equal(button(host.root, '下移第6页').props.disabled, true);
        click(button(host.root, '下移第1页')); assert.equal(latest(host).slides[0].title, '第2页'); assert.equal(latest(host).slides[1].title, '第1页');
        click(button(host.root, '添加幻灯片')); assert.equal(latest(host).slides.length, 7); assert.deepEqual(latest(host).slides.at(-1).evidence_refs, []);
        current.materials.draft.slides.push(slide(7)); await settle(); click(button(host.root, '删除第1页')); assert.equal(latest(host).slides.length, 6);
        current.materials.draft.slides = Array.from({ length: 12 }, (_, index) => slide(index + 1)); await settle(); assert.equal(button(host.root, '添加幻灯片').props.disabled, true);
    } finally { host.close(); }
});

test('saved immutable outline identifies exact revision digest and source with approval independent of dirty edits', async () => {
    const current = state({ snapshot: { last_outline_revision: 4, current_outline_id: 'outline-new', current_source_digest: 'source-new', outline: { outline_revision: 4, outline_id: 'outline-new', outline_digest: 'new-digest', source_digest: 'source-new', input_revision: 3, lesson: lesson(), slides: Array.from({ length: 6 }, () => slide()) },
        source_status: 'current', approval_current: true }, dirty: true, canApprove: false,
        lastReceipt: { outline_id: 'outline-old', content_digest: 'old-digest', reviewed_at: 'old-date' } });
    const host = await mountExpanded(current);
    try {
        const allText = textOf(host.root); assert.match(allText, /保存版本.*4/); assert.match(allText, /来源.*3/);
        const technical = find(host.root, node => node.props['data-materials-technical'] !== undefined); assert.ok(technical);
        assert.match(textOf(technical), /outline-new/); assert.match(textOf(technical), /new-digest/);
        assert.match(allText, /已确认审阅/); assert.match(allText, /未保存/);
        const saved = find(host.root, node => node.props['data-materials-saved'] !== undefined); assert.doesNotMatch(textOf(saved), /outline-old|old-digest|old-date/);
        assert.match(allText, /此前操作回执/); assert.match(allText, /outline-old/);
        assert.equal(button(host.root, '确认已审阅此保存版本').props.disabled, true);
        current.materials.canApprove = true; await settle(); click(button(host.root, '确认已审阅此保存版本')); assert.deepEqual(host.emitted['approve-materials'], [[]]);
        for (const [status, label] of [['unprepared', '尚未准备'], ['changed', '已变更'], ['unavailable', '不可用']]) {
            current.materials.snapshot.source_status = status; await settle(); assert.match(textOf(host.root), new RegExp(label));
        }
        assert.match(textOf(host.root), /不可修改|不可变/); assert.match(textOf(host.root), /PPTX.*DOCX.*尚未/);
        assert.equal(walk(host.root).filter(node => node.tag === 'a' && node.props.download !== undefined).length, 0);
    } finally { host.close(); }
});

test('save reload replace and exact retry are explicit events and errors preserve all editable content', async () => {
    const current = state({ dirty: true, status: 'error', error: { reason: 'revision_conflict' }, conflict: true, validationErrors: ['必须填写标题'] }), original = clone(current.materials.draft);
    const host = await mountExpanded(current);
    try {
        assert.match(textOf(host.root), /revision_conflict/); assert.match(textOf(host.root), /必须填写标题/);
        assert.ok(field(host.root, 'lesson.title')); click(button(host.root, '保存为新大纲版本')); assert.deepEqual(host.emitted['save-materials'], [[]]);
        click(button(host.root, '重新读取服务端最新版本')); assert.deepEqual(host.emitted['reload-materials'], [[]]); assert.deepEqual(current.materials.draft, original);
        current.materials.pendingReplace = true; await settle(); assert.match(textOf(host.root), /替换.*未保存/);
        click(button(host.root, '替换当前编辑')); click(button(host.root, '保留当前编辑')); assert.deepEqual(host.emitted['replace-materials-draft'], [[]]); assert.deepEqual(host.emitted['cancel-materials-replace'], [[]]);
        current.materials.status = 'uncertain'; current.materials.retryAvailable = true; current.materials.canSave = false; await settle();
        assert.match(textOf(host.root), /结果未确认/); click(button(host.root, '用同一请求重试保存或审阅')); assert.deepEqual(host.emitted['retry-materials'], [[]]);
        assert.equal(button(host.root, '保存为新大纲版本').props.disabled, true); assert.deepEqual(current.materials.draft, original);
    } finally { host.close(); }
});

test('blank manual draft stays editable without fabricating saved outline sources or file success', async () => {
    const current = state({ draft: null, snapshot: null, canSave: false }), host = await mountExpanded(current);
    try {
        assert.equal(field(host.root, 'lesson.title').props.value, ''); assert.match(textOf(host.root), /尚无保存版本/);
        input(host.root, 'lesson.title', '手动开始'); assert.equal(latest(host).lesson.title, '手动开始');
        assert.equal(latest(host).slides.length, 6); assert.ok(latest(host).slides.every(entry => entry.title === '' && entry.evidence_refs.length === 0));
        assert.doesNotMatch(textOf(host.root), /已生成|资料包完成|下载 PPTX|下载 DOCX/);
        current.materials.capabilities = { status: 'error', data: null, reason: 'materials_unavailable' }; await settle();
        click(button(host.root, '重新检查手动整理能力')); assert.deepEqual(host.emitted['retry-materials-capabilities'], [[]]);
    } finally { host.close(); }
});

test('manual materials stylesheet is confined to the existing light desktop shell', async () => {
    await component(); const css = readFileSync(new URL('../styles/teacher-work.css', import.meta.url), 'utf8');
    assert.match(css, /\.teacher-work-materials/); assert.doesNotMatch(css, /v-html|@media[^\n]*(?:767|768|640)px/);
});

test('approval blockers explain the exact source and task conditions in Chinese', async () => {
    const current = state({ snapshot: { current_outline_id: 'outline-a', outline: { outline_id: 'outline-a', outline_revision: 2,
        input_revision: 1, outline_digest: 'digest-a', source_digest: 'source-a', lesson: lesson(), slides: Array.from({ length: 6 }, () => slide()) },
        source_status: 'current', approval_current: false, approval_blocker: null } }), host = await mountExpanded(current);
    try {
        const cases = [['NO_OUTLINE', '尚无保存大纲'], ['MATERIAL_SOURCES_UNAVAILABLE', '资料来源不可用'],
            ['STALE_INPUT_REVISION', '任务版本已变更'], ['SOURCE_CHANGED', '引用资料已变更'],
            ['OWNER_RUN_BUSY', '仍在处理中'], ['NORMALIZATION_REQUIRED', '需要先手动整理'],
            ['MATERIAL_TEXT_UNREPRESENTABLE', '无法保存为当前结构']];
        for (const [code, label] of cases) { current.materials.snapshot.approval_blocker = code; await settle(); assert.match(textOf(host.root), new RegExp(label)); }
        current.materials.error = { reason: 'MATERIAL_RECEIPT_LIMIT' }; await settle(); assert.match(textOf(host.root), /回执数量已达上限/);
    } finally { host.close(); }
});

test('body and column edits add explicit empty points and remove only the requested point', async () => {
    const current = state(), host = await mountExpanded(current);
    try {
        click(button(host.root, '第1页添加要点')); assert.deepEqual(latest(host).slides[0].body, ['内容', '']);
        click(button(host.root, '删除第1页第1条要点')); assert.deepEqual(latest(host).slides[0].body, []);
        input(host.root, 'slides.0.body.0', '改过的要点'); assert.deepEqual(latest(host).slides[0].body, ['改过的要点']);
        input(host.root, 'slides.0.notes', '新讲稿'); assert.equal(latest(host).slides[0].notes, '新讲稿');
        input(host.root, 'slides.0.source_note', '教师核对'); assert.equal(latest(host).slides[0].source_note, '教师核对');
        current.materials.draft.slides[0] = { ...slide(), layout: 'two_column', body: [], columns: [['左'], ['右']] }; await settle();
        click(button(host.root, '第1页右栏添加要点')); assert.deepEqual(latest(host).slides[0].columns, [['左'], ['右', '']]);
        input(host.root, 'slides.0.columns.1.0', '修改右栏'); assert.deepEqual(latest(host).slides[0].columns, [['左'], ['修改右栏']]);
        click(button(host.root, '删除第1页第1栏第1条要点')); assert.deepEqual(latest(host).slides[0].columns, [[], ['右']]);
        current.materials.draft.slides[0].columns = [['1', '2', '3'], ['4', '5']]; await settle();
        assert.equal(button(host.root, '第1页左栏添加要点').props.disabled, true); assert.equal(button(host.root, '第1页右栏添加要点').props.disabled, true);
        const before = host.emitted['update-materials-draft'].length; click(button(host.root, '第1页左栏添加要点')); assert.equal(host.emitted['update-materials-draft'].length, before);
    } finally { host.close(); }
});

test('stage and citation deletions preserve remaining content and edits stop during submissions', async () => {
    const current = state(), host = await mountExpanded(current);
    try {
        current.materials.draft.lesson.teaching_flow.push({ stage: '结尾', minutes: 5, content: '保留结尾' }); await settle();
        click(button(host.root, '删除教学流程第1阶段')); assert.deepEqual(latest(host).lesson.teaching_flow, [{ stage: '结尾', minutes: 5, content: '保留结尾' }]);
        click(button(host.root, '删除引用第1项')); assert.deepEqual(latest(host).lesson.citations, []);
        input(host.root, 'lesson.teaching_flow.0.stage', '开始'); assert.equal(latest(host).lesson.teaching_flow[0].stage, '开始');
        input(host.root, 'lesson.teaching_flow.0.content', '新内容'); assert.equal(latest(host).lesson.teaching_flow[0].content, '新内容');
        input(host.root, 'lesson.citations.0.name', '真实书名'); assert.equal(latest(host).lesson.citations[0].name, '真实书名');
        for (const status of ['saving', 'approving']) {
            current.materials.status = status; await settle(); const before = host.emitted['update-materials-draft'].length;
            input(host.root, 'lesson.title', '不要接受'); click(button(host.root, '添加幻灯片')); assert.equal(host.emitted['update-materials-draft'].length, before);
            assert.equal(find(host.root, node => node.tag === 'fieldset').props.disabled, true);
        }
    } finally { host.close(); }
});

test('blank form uses saved task duration and preserves unsafe numeric text for validation', async () => {
    const current = state({ draft: null }); current.task.duration_minutes = 60;
    const host = await mountExpanded(current);
    try {
        assert.equal(field(host.root, 'lesson.duration_minutes').props.value, 60);
        assert.equal(field(host.root, 'lesson.teaching_flow.0.minutes').props.value, 60);
        current.materials.draft = { lesson: lesson(), slides: Array.from({ length: 6 }, () => slide()) }; await settle();
        input(host.root, 'lesson.citations.0.page', '9007199254740993'); assert.equal(latest(host).lesson.citations[0].page, '9007199254740993');
    } finally { host.close(); }
});

test('manual materials is compact by default and hides raw identifiers inside closed technical details', async () => {
    const current = state({ snapshot: { current_outline_id: 'raw-outline-uuid', outline: { outline_id: 'raw-outline-uuid', outline_revision: 3,
        input_revision: 2, outline_digest: 'raw-outline-digest', source_digest: 'raw-source-digest', lesson: lesson(), slides: Array.from({ length: 6 }, () => slide()) },
        source_status: 'current', approval_current: false, approval_blocker: 'OWNER_RUN_BUSY' }, error: { reason: 'outline_revision_conflict' },
        lastReceipt: { outline_id: 'raw-old-uuid', replayed: true } });
    const host = await mount(await component(), { state: current });
    try {
        const edit = button(host.root, '编辑教案与幻灯片'); assert.ok(edit); assert.equal(edit.props['aria-expanded'], false); assert.ok(edit.props['aria-controls']);
        assert.equal(field(host.root, 'lesson.title'), undefined); assert.equal(walk(host.root).filter(node => node.tag === 'fieldset').length, 0);
        const technical = find(host.root, node => node.props['data-materials-technical'] !== undefined); assert.equal(technical.tag, 'details'); assert.equal(Boolean(technical.props.open), false);
        const visible = visibleTextOf(host.root); assert.match(visible, /保存版本 3/); assert.match(visible, /来源与保存版本一致/); assert.match(visible, /尚未有效确认审阅/);
        assert.doesNotMatch(visible, /raw-outline-uuid|raw-outline-digest|raw-source-digest|raw-old-uuid|OWNER_RUN_BUSY|outline_revision_conflict/);
        for (const item of ['raw-outline-uuid', 'raw-outline-digest', 'raw-source-digest', 'raw-old-uuid', 'OWNER_RUN_BUSY', 'outline_revision_conflict']) assert.ok(textOf(technical).includes(item));
        click(edit); await settle(); assert.equal(button(host.root, '收起教案与幻灯片编辑').props['aria-expanded'], true); assert.ok(field(host.root, 'lesson.title'));
    } finally { host.close(); }
});

test('expanding and collapsing preserves the full dirty draft and in-flight operation without emitting lifecycle actions', async () => {
    const current = state({ dirty: true }), original = clone(current.materials.draft), host = await mount(await component(), { state: current });
    try {
        click(button(host.root, '编辑教案与幻灯片')); await settle(); input(host.root, 'lesson.title', '继续保留的编辑');
        current.materials.draft = latest(host); current.materials.status = 'saving'; current.materials.canSave = false; await settle();
        const retained = clone(current.materials.draft), emissions = clone(host.emitted);
        click(button(host.root, '收起教案与幻灯片编辑')); await settle(); assert.equal(field(host.root, 'lesson.title'), undefined);
        assert.deepEqual(current.materials.draft, retained); assert.equal(current.materials.status, 'saving'); assert.equal(current.materials.dirty, true); assert.deepEqual(host.emitted, emissions);
        click(button(host.root, '编辑教案与幻灯片')); await settle(); assert.equal(field(host.root, 'lesson.title').props.value, '继续保留的编辑');
        assert.equal(find(host.root, node => node.tag === 'fieldset').props.disabled, true); assert.deepEqual(current.materials.draft.slides, original.slides);
        current.materials.status = 'uncertain'; current.materials.retryAvailable = true; await settle();
        click(button(host.root, '收起教案与幻灯片编辑')); await settle(); click(button(host.root, '用同一请求重试保存或审阅'));
        assert.deepEqual(host.emitted['retry-materials'], [[]]); assert.equal(current.materials.status, 'uncertain'); assert.deepEqual(current.materials.draft, retained);
    } finally { host.close(); }
});

test('read capability gates editing and unavailable sources clearly keep drafts unsaved in the current session', async () => {
    const current = state({ capabilities: { status: 'ready', data: { read: false, save: false, approve: false, source_configured: false, files: false }, reason: null }, canSave: false }),
        host = await mount(await component(), { state: current });
    try {
        assert.match(visibleTextOf(host.root), /编辑暂不可用/); assert.equal(button(host.root, '编辑教案与幻灯片').props.disabled, true);
        click(button(host.root, '编辑教案与幻灯片')); await settle(); assert.equal(field(host.root, 'lesson.title'), undefined); assert.equal(host.emitted['update-materials-draft'], undefined);
        current.materials.capabilities.data.read = true; current.materials.dirty = true; await settle();
        assert.match(visibleTextOf(host.root), /保存当前不可用/); assert.match(visibleTextOf(host.root), /本次会话.*未持久保存/);
        click(button(host.root, '编辑教案与幻灯片')); await settle(); assert.ok(field(host.root, 'lesson.title')); assert.equal(find(host.root, node => node.tag === 'fieldset').props.disabled, false);
        input(host.root, 'lesson.title', '来源不可用时仍可编辑'); assert.equal(latest(host).lesson.title, '来源不可用时仍可编辑'); assert.equal(button(host.root, '保存为新大纲版本').props.disabled, true);
        current.materials.capabilities = { status: 'loading', data: null, reason: null }; await settle();
        assert.ok(field(host.root, 'lesson.title')); assert.equal(find(host.root, node => node.tag === 'fieldset').props.disabled, true);
        const edits = host.emitted['update-materials-draft'].length; input(host.root, 'lesson.title', '不要更新'); assert.equal(host.emitted['update-materials-draft'].length, edits);
        current.materials.capabilities = { status: 'ready', data: { read: false, save: false, approve: false, source_configured: false, files: false }, reason: null }; await settle();
        assert.equal(field(host.root, 'lesson.title'), undefined); assert.equal(button(host.root, '编辑教案与幻灯片').props.disabled, true);
    } finally { host.close(); }
});

test('local editor expansion resets on task account and auth identity changes without rewriting root drafts', async () => {
    const current = state(); current.actor = 'teacher-a'; current.role = 'teacher'; current.authEpoch = 1;
    const host = await mount(await component(), { state: current });
    try {
        for (const update of [() => { current.task.task_id = 'task-b'; }, () => { current.actor = 'teacher-b'; }, () => { current.authEpoch++; }]) {
            click(button(host.root, '编辑教案与幻灯片')); await settle(); assert.ok(field(host.root, 'lesson.title'));
            const draftBefore = clone(current.materials.draft); update(); await settle(); assert.equal(field(host.root, 'lesson.title'), undefined);
            assert.equal(button(host.root, '编辑教案与幻灯片').props['aria-expanded'], false); assert.deepEqual(current.materials.draft, draftBefore); assert.equal(host.emitted['update-materials-draft'], undefined);
        }
    } finally { host.close(); }
});

test('blank untouched compact drafts defer validation guidance until the editor is opened or edited', async () => {
    const current = state({ validationErrors: ['请填写教案必填项', '请核对各教学阶段时长'], dirty: false, canSave: false }),
        host = await mount(await component(), { state: current });
    try {
        assert.doesNotMatch(visibleTextOf(host.root), /请填写教案必填项|请核对各教学阶段时长/);
        assert.equal(find(host.root, node => node.props.role === 'alert'), undefined);
        click(button(host.root, '编辑教案与幻灯片')); await settle(); assert.match(visibleTextOf(host.root), /请填写教案必填项/);
        click(button(host.root, '收起教案与幻灯片编辑')); await settle(); assert.doesNotMatch(visibleTextOf(host.root), /请填写教案必填项/);
        current.materials.dirty = true; await settle(); assert.match(visibleTextOf(host.root), /请填写教案必填项/);
    } finally { host.close(); }
});

test('source-unavailable saved versions remain persisted while new edits are explicitly session-only', async () => {
    const current = state({ capabilities: { status: 'ready', data: { read: true, save: false, approve: false, source_configured: false, files: false }, reason: null },
        snapshot: { current_outline_id: 'outline-a', outline: { outline_id: 'outline-a', outline_revision: 2, input_revision: 1, outline_digest: 'digest-a', source_digest: 'source-a', lesson: lesson(), slides: Array.from({ length: 6 }, () => slide()) },
            source_status: 'unavailable', approval_current: false, approval_blocker: 'MATERIAL_SOURCES_UNAVAILABLE' }, dirty: false, canSave: false }),
        host = await mount(await component(), { state: current });
    try {
        assert.match(visibleTextOf(host.root), /保存当前不可用/); assert.match(visibleTextOf(host.root), /已有保存版本仍保留/);
        assert.doesNotMatch(visibleTextOf(host.root), /当前编辑.*尚未持久保存/);
        current.materials.dirty = true; await settle(); assert.match(visibleTextOf(host.root), /当前编辑.*尚未持久保存/);
        assert.match(visibleTextOf(host.root), /保存版本 2/);
    } finally { host.close(); }
});

test('save warning keeps both the button and emitted action closed despite stale affirmative save flags', async () => {
    for (const unavailable of ['snapshot', 'root']) {
        const current = state({ capabilities: { status: 'ready', data: { read: true, save: true, approve: true, source_configured: unavailable !== 'root', files: false }, reason: null },
            ...(unavailable === 'snapshot' ? { snapshot: { source_status: 'unavailable', outline: null, approval_current: false } } : {}), canSave: true });
        const host = await mount(await component(), { state: current });
        try { assert.match(visibleTextOf(host.root), /保存当前不可用/);
            const save = button(host.root, '保存为新大纲版本'); assert.equal(save.props.disabled, true);
            click(save); assert.equal(host.emitted['save-materials'], undefined);
        } finally { host.close(); }
    }
});

test('terminal capability closure collapses the disclosure truthfully while preserving every draft field', async () => {
    for (const status of ['error', 'unavailable', 'idle']) {
        const current = state(), host = await mountExpanded(current), before = clone(current.materials.draft);
        try { current.materials.capabilities = { status, data: null, reason: status === 'error' ? 'auth_required' : 'TEACHER_WORK_UNAVAILABLE' }; await settle();
            assert.equal(field(host.root, 'lesson.title'), undefined); const edit = button(host.root, '编辑教案与幻灯片'); assert.ok(edit);
            assert.equal(edit.props['aria-expanded'], false); assert.equal(edit.props.disabled, true); assert.deepEqual(current.materials.draft, before);
            assert.equal(host.emitted['update-materials-draft'], undefined);
        } finally { host.close(); }
    }
});

test('whole-draft capacity guidance names the refused save and keeps teacher input reviewable', async () => {
    const current = state({ error: { reason: 'private_draft_too_large' }, status: 'error', dirty: true, retryAvailable: false }), before = clone(current.materials.draft);
    const host = await mount(await component(), { state: current });
    try { assert.match(visibleTextOf(host.root), /整个任务草稿/); assert.match(visibleTextOf(host.root), /缩短/);
        assert.match(visibleTextOf(host.root), /编辑.*保留/); assert.deepEqual(current.materials.draft, before);
        click(button(host.root, '编辑教案与幻灯片')); await settle(); assert.equal(field(host.root, 'lesson.title').props.value, before.lesson.title);
        assert.equal(button(host.root, '用同一请求重试保存或审阅'), undefined);
    } finally { host.close(); }
});
