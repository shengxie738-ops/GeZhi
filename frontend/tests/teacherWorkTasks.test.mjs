import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { Vue, mount, find, walk, textOf, button, settle, documentFor, globals, context, authRefs,
    unavailableApi } from './fixtures/teacherWorkHarness.mjs';

const stateURL = new URL('../js/controllers/teacherWorkState.js', import.meta.url);
const hookURL = new URL('../js/hooks/useTeacherWork.js', import.meta.url);
const componentURL = new URL('../js/components/teacher-work/TeacherWork.js', import.meta.url);
const source = path => readFileSync(new URL('../' + path, import.meta.url), 'utf8');
const imports = new Map([
    [stateURL.href, () => import('../js/controllers/teacherWorkState.js')],
    [hookURL.href, () => import('../js/hooks/useTeacherWork.js')],
    [componentURL.href, () => import('../js/components/teacher-work/TeacherWork.js')]
]);
async function required(url) { assert.ok(existsSync(url), 'Task5a feature missing: ' + url.pathname.split('/').at(-1)); return imports.get(url.href)(); }
async function fresh() { const module = await required(stateURL), state = module.createTeacherWorkState(); module.synchronizeTeacherWork(state, context()); return { module, state }; }

test('T5a01 empty state has no fabricated records and keeps all unsupplied operations closed', async () => {
    const module = await required(stateURL), state = module.createTeacherWorkState();
    for (const key of ['tasks', 'messages', 'artifacts', 'versions', 'sources']) assert.deepEqual(state[key], []);
    assert.equal(state.composerText, ''); assert.equal(state.authVerified, false);
    assert.equal(module.captureRequest(state), null);
    assert.deepEqual(state.operationAvailability, { task_write: false, chat: false, generate: false, storage: false });
    assert.equal(state.task_id, null); assert.equal(state.run_id, null);
});

test('T5a02 teacher navigation preserves legacy prep and student workspace fallback', async () => {
    await required(stateURL);
    // Existing auth/router files are data-only in this finite Task5a scope.
    const auth = source('js/hooks/useAuth.js');
    const studentMenus = auth.slice(auth.indexOf('const studentMenus'), auth.indexOf('const teacherMenus'));
    const teacherMenus = auth.slice(auth.indexOf('const teacherMenus'), auth.indexOf('export function useAuth'));
    assert.match(teacherMenus, /id:\s*['"]t_work['"]/); assert.match(teacherMenus, /id:\s*['"]t_lesson_prep['"]/);
    assert.doesNotMatch(studentMenus, /id:\s*['"]t_work['"]/); assert.match(studentMenus, /id:\s*['"]workspace['"]/);
    assert.match(auth, /const legacyMenus\s*=\s*role === ['"]student['"]\s*\?\s*studentMenus\s*:\s*teacherMenus/);
    assert.match(auth, /legacyMenus\.some\(menu => menu\.id === view\)/);
    assert.match(auth, /return role === ['"]student['"]\s*\?\s*['"]teaching-home['"]\s*:\s*['"]t_teaching-home['"]/);
    assert.match(auth, /const authVerified\s*=\s*ref\(false\)/, 'stored role remains non-authorizing');
});

test('T5a03 UI preferences use verified actor namespace and explicit allowlist only', async () => {
    globals(); const { module, state } = await fresh();
    const storage = new Map(), calls = [], store = {
        getItem(key) { calls.push(['get', key]); return storage.get(key) ?? null; },
        setItem(key, value) { calls.push(['set', key]); storage.set(key, value); }
    };
    assert.equal(module.teacherWorkPreferenceKey(state), 'teacher_work:teacher-a:teacher:ui:v1');
    module.patchTeacherWorkPreferences(state, { navCollapsed: true, taskRailCollapsed: true, drawerOpen: true,
        artifactTab: 'sources', actor: 'other', messages: [{ text: 'never persist' }], token: 'not a real token' });
    state.ui.untrusted = 'do not persist'; state.composerText = 'private unsaved input';
    module.writeTeacherWorkPreferences(state, store);
    const saved = JSON.parse(storage.get('teacher_work:teacher-a:teacher:ui:v1'));
    assert.deepEqual(Object.keys(saved).sort(), ['artifactCollapsed', 'artifactTab', 'drawerOpen', 'navCollapsed', 'taskRailCollapsed'].sort());
    assert.equal(saved.navCollapsed, true); assert.equal(saved.artifactTab, 'sources');
    assert.doesNotMatch(JSON.stringify(saved), /private|never persist|token|other|untrusted/);
    module.synchronizeTeacherWork(state, { ...context(), actor: 'teacher-b' });
    module.readTeacherWorkPreferences(state, store);
    assert.equal(state.ui.navCollapsed, false);
    assert.deepEqual(calls, [['set', 'teacher_work:teacher-a:teacher:ui:v1'], ['get', 'teacher_work:teacher-b:teacher:ui:v1']]);
    module.synchronizeTeacherWork(state, { ...context(), role: 'student' });
    assert.equal(module.teacherWorkPreferenceKey(state), null);
    module.writeTeacherWorkPreferences(state, store); module.readTeacherWorkPreferences(state, store);
    assert.equal(calls.length, 2);
});

test('T5a04 independent folds and tabs never change request task revision or run identity', async () => {
    globals(); const { module, state } = await fresh();
    module.selectTeacherTask(state, { task_id: 'synthetic-task', input_revision: 3 }); state.run_id = 'synthetic-run';
    state.messages.push({ id: 'synthetic-message', plain_text: 'test only' }); module.updateTeacherInput(state, 'retained input');
    const token = module.captureRequest(state);
    for (const changes of [{ navCollapsed: true }, { taskRailCollapsed: true }, { artifactCollapsed: true },
        { drawerOpen: true }, { artifactTab: 'versions' }, { navCollapsed: false }]) {
        module.patchTeacherWorkPreferences(state, changes);
        assert.deepEqual(module.captureRequest(state), token); assert.equal(module.acceptResponse(state, token), true);
        assert.equal(state.messages.length, 1); assert.equal(state.composerText, 'retained input');
    }
    assert.equal(state.ui.navCollapsed, false); assert.equal(state.ui.taskRailCollapsed, true);
    assert.equal(state.ui.artifactCollapsed, true); assert.equal(state.ui.artifactTab, 'versions');
});

test('T5a05 four-zone unavailable shell has real legacy fallback and no seeded success', async () => {
    globals(); const { module, state } = await fresh();
    module.applyCapabilityResult(state, module.captureRequest(state), { status: 'unavailable', data: null, reason: 'TEACHER_WORK_UNAVAILABLE' });
    const component = (await required(componentURL)).default;
    const host = await mount(component, { state, menus: [], currentUser: { username: 'verified-teacher' } });
    try {
        for (const zone of ['navigation', 'tasks', 'conversation', 'artifacts'])
            assert.ok(find(host.root, node => node.props['data-teacher-work-zone'] === zone), zone);
        assert.match(textOf(host.root), /教师 Work 暂不可用/); assert.match(textOf(host.root), /TEACHER_WORK_UNAVAILABLE/);
        assert.match(textOf(host.root), /尚未接通|尚未开放/);
        assert.match(textOf(host.root), /没有.*任务|暂无.*任务/); assert.match(textOf(host.root), /没有.*文件|暂无.*文件/);
        assert.ok(button(host.root, '新建任务').props.disabled); assert.ok(button(host.root, '发送教学问题').props.disabled);
        assert.equal(walk(host.root).filter(node => node.props['data-teacher-work-message'] !== undefined).length, 0);
        assert.equal(walk(host.root).filter(node => node.props['data-teacher-work-artifact'] !== undefined).length, 0);
        assert.doesNotMatch(textOf(host.root), /进程同步|王老师|10:14|已按确认|v1.*待审阅|资料包完成|已审阅/);
        button(host.root, '打开原 AI 备课').props.onClick();
        assert.deepEqual(host.emitted.navigate, [['t_lesson_prep']]);
        button(host.root, 'Skills').props.onClick(); assert.deepEqual(host.emitted['open-catalog'].at(-1).slice(0, 1), ['skills']);
        button(host.root, '插件商店').props.onClick(); assert.deepEqual(host.emitted['open-catalog'].at(-1).slice(0, 1), ['store']);
        const input = find(host.root, node => node.tag === 'textarea'); input.props.onInput({ target: { value: 'unsent private input' } });
        assert.deepEqual(host.emitted['update-input'], [['unsent private input']]);
    } finally { host.close(); }
});

test('T5a06 artifact drawer and catalog expose Escape close and native Tab trap', async () => {
    globals(); const { state } = await fresh(), component = (await required(componentURL)).default;
    for (const kind of ['artifacts', 'skills', 'store']) {
        state.presentation.drawerMode = true; state.ui.drawerOpen = kind === 'artifacts';
        state.presentation.catalogOpen = kind === 'artifacts' ? null : kind;
        const host = await mount(component, { state, menus: [], currentUser: {} }); documentFor(host.root);
        try {
            const dialog = find(host.root, node => node.props.role === 'dialog');
            assert.ok(dialog); assert.equal(dialog.props['aria-modal'], true); assert.ok(dialog.props['aria-labelledby']);
            const controls = dialog.querySelectorAll(); assert.ok(controls.length >= 1);
            let prevented = 0; document.activeElement = controls.at(-1);
            dialog.props.onKeydown({ key: 'Tab', currentTarget: dialog, shiftKey: false, preventDefault() { prevented++; } });
            assert.equal(document.activeElement, controls[0]); assert.equal(prevented, 1);
            document.activeElement = controls[0];
            dialog.props.onKeydown({ key: 'Tab', currentTarget: dialog, shiftKey: true, preventDefault() { prevented++; } });
            assert.equal(document.activeElement, controls.at(-1)); assert.equal(prevented, 2);
            dialog.props.onKeydown({ key: 'Escape', currentTarget: dialog, preventDefault() {}, stopPropagation() {} });
            assert.deepEqual(host.emitted[kind === 'artifacts' ? 'close-artifacts' : 'close-catalog'], [[]]);
        } finally { host.close(); }
    }
});

test('T5a07 presentation focus returns exact surviving trigger and rejects stale detached focus', async () => {
    const { storage, eventTarget } = globals(), { useTeacherWork } = await required(hookURL), refs = authRefs();
    const focuses = [], trigger = { isConnected: true, getClientRects: () => [{}], focus: () => focuses.push('trigger') };
    const heading = { isConnected: true, getClientRects: () => [{}], focus: () => focuses.push('heading') };
    const documentTarget = { activeElement: trigger, querySelector: () => heading };
    const scope = Vue.effectScope();
    const hook = scope.run(() => useTeacherWork(refs, { api: unavailableApi(), storage, eventTarget,
        viewportTarget: { innerWidth: 1024 }, documentTarget }));
    try {
        await hook.openArtifacts({ currentTarget: trigger }); assert.equal(focuses.at(-1), 'heading');
        await hook.closeArtifacts(); assert.equal(focuses.at(-1), 'trigger');
        const opening = hook.openArtifacts({ currentTarget: trigger }); refs.currentView.value = 't_lesson_prep';
        await opening; assert.equal(focuses.length, 2, 'departed view cannot focus stale drawer');
        refs.currentView.value = 't_work'; await settle();
        await hook.openArtifacts({ currentTarget: trigger }); trigger.isConnected = false;
        await hook.closeArtifacts(); assert.equal(focuses.at(-1), 'heading', 'detached trigger must not receive focus');
    } finally { scope.stop(); }
});

test('T5a08 dedicated teacher branch uses isolated template AST bindings and scoped desktop CSS', async () => {
    await required(stateURL); await required(componentURL);
    const html = source('index.html'), start = html.indexOf('<teacher-work '), end = html.indexOf('</teacher-work>', start) + 15;
    assert.ok(start >= 0 && end > start, 'dedicated TeacherWork branch');
    const tag = html.slice(start, end), nodes = [];
    Vue.compile(tag.replace('v-else-if=', 'v-if='), { nodeTransforms: [node => { nodes.push(node); }],
        onError(error) { throw error; }, decodeEntities: raw => raw });
    const branch = nodes.find(node => node.type === 9), condition = branch?.branches[0]?.condition?.content || '';
    for (const term of ['isLoggedIn', 'authVerified', 'currentRole', 'teacher', 'currentView', 't_work', 'teachingLegacyRenderAllowed']) assert.ok(condition.includes(term), term);
    const element = nodes.find(node => node.type === 1 && node.tag === 'teacher-work'); assert.ok(element);
    const directives = element.props.filter(prop => prop.type === 7);
    assert.ok(directives.some(prop => prop.name === 'bind' && prop.arg?.content === 'state' && prop.exp?.content === 'teacherWorkState'));
    assert.ok(directives.some(prop => prop.name === 'on' && prop.arg?.content === 'navigate' && prop.exp?.content === 'teachingOpenTool'));
    assert.ok(start < html.indexOf('class="h-full w-full flex relative home-bg-container"'), 'Work bypasses glass legacy frame');
    const main = source('js/main.js'); assert.match(main, /import TeacherWork from ['"]\.\/components\/teacher-work\/TeacherWork\.js['"]/);
    assert.match(main, /useTeacherWork\s*\(/); assert.match(main, /authEpoch:\s*auth\.authEpoch/); assert.match(main, /authVerified:\s*auth\.authVerified/);
    assert.match(main, /currentView:\s*guardedView/); assert.match(main, /teacherWorkState:\s*teacherWork\.state/);
    assert.match(html, /href="\.\/styles\/teacher-work\.css"/);
    const cssURL = new URL('../styles/teacher-work.css', import.meta.url); assert.ok(existsSync(cssURL), 'scoped desktop stylesheet missing');
    const css = readFileSync(cssURL, 'utf8'); assert.match(css, /\.teacher-work\b/); assert.match(css, /min-width:\s*480px/);
    assert.match(css, /@media\s*\([^)]*1359px/); assert.match(css, /@media\s*\([^)]*1179px/);
    assert.doesNotMatch(css, /@media[^\n]*(?:767|768|640)px|backdrop-filter|linear-gradient/);
});
