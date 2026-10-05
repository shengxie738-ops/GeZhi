import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { Vue, mount, find, walk, settle, globals, context, authRefs, unavailableApi } from './fixtures/teacherWorkHarness.mjs';

// Separate P2 supplement. This file does not modify the original 19 cases or their fixture.
// These finite DOM facts model selector results separately from native Tab order;
// no browser, CSS engine, product entrypoint, real event source or timer is used.
const hasAttribute = (node, name) => node.props[name] !== undefined && node.props[name] !== null && node.props[name] !== false;
function matches(node, selector) {
    const absent = [...selector.matchAll(/:not\(\[([\w-]+)(?:="([^"]*)")?\]\)/g)];
    const base = selector.replace(/:not\(\[[^\]]+\]\)/g, '');
    if (absent.some(([, name, value]) => hasAttribute(node, name) && (value === undefined || String(node.props[name]) === value))) return false;
    const tag = /^[a-z]+/i.exec(base)?.[0];
    if (tag && node.tag !== tag) return false;
    if (base.startsWith('#')) return node.props.id === base.slice(1);
    const attributes = [...base.matchAll(/\[([\w-]+)(?:="([^"]*)")?\]/g)];
    assert.ok(tag || attributes.length || base.startsWith('#'), 'unreviewed synthetic selector: ' + selector);
    return attributes.every(([, name, value]) => hasAttribute(node, name) && (value === undefined || String(node.props[name]) === value));
}
const queryAll = (root, selector) => walk(root).slice(1).filter(node => selector.split(',').some(part => matches(node, part.trim())));
const lineage = node => { const result = []; for (let current = node; current; current = current.parent) result.push(current); return result; };
const connected = (node, root) => lineage(node).includes(root);
const hidden = node => lineage(node).some(current => hasAttribute(current, 'hidden') ||
    current.style.display === 'none' || current.style.visibility === 'hidden');
const inert = node => lineage(node).some(current => hasAttribute(current, 'inert'));
const tabIndex = node => hasAttribute(node, 'tabindex') ? Number(node.props.tabindex) :
    ['button', 'input', 'select', 'textarea'].includes(node.tag) || hasAttribute(node, 'href') ? 0 : -1;
const tabbable = (node, root) => connected(node, root) && !hidden(node) && !inert(node) &&
    !hasAttribute(node, 'disabled') && tabIndex(node) >= 0;

function installNativeFacts(host) {
    const documentTarget = { activeElement: null,
        querySelector: selector => queryAll(host.root, selector)[0] || null };
    globalThis.document = documentTarget;
    for (const node of walk(host.root)) {
        Object.defineProperty(node, 'isConnected', { configurable: true, get: () => connected(node, host.root) });
        Object.defineProperty(node, 'tabIndex', { configurable: true, get: () => tabIndex(node) });
        Object.defineProperty(node, 'parentElement', { configurable: true, get: () => node.parent });
        node.getClientRects = () => connected(node, host.root) && !hidden(node) ? [{}] : [];
        node.getAttribute = name => hasAttribute(node, name) ? String(node.props[name]) : null;
        node.hasAttribute = name => hasAttribute(node, name);
        node.matches = selector => matches(node, selector);
        node.closest = selector => lineage(node).find(current => matches(current, selector)) || null;
        node.querySelectorAll = selector => queryAll(node, selector);
        node.querySelector = selector => queryAll(node, selector)[0] || null;
        node.focus = () => { if (connected(node, host.root) && !hidden(node) && !inert(node) && !hasAttribute(node, 'disabled')) documentTarget.activeElement = node; };
    }
    return documentTarget;
}

function tabEvent(dialog, shiftKey = false) {
    let prevented = 0;
    dialog.props.onKeydown({ key: 'Tab', currentTarget: dialog, shiftKey,
        preventDefault() { prevented++; }, stopPropagation() {} });
    return prevented;
}

for (const selected of ['sources', 'files', 'versions']) {
    test(`T5aP201-${selected} artifact drawer native Tab order wraps selected tab and close only`, async () => {
        globals();
        const { createTeacherWorkState, synchronizeTeacherWork } = await import('../js/controllers/teacherWorkState.js');
        const component = (await import('../js/components/teacher-work/TeacherWork.js')).default;
        const state = Vue.reactive(createTeacherWorkState()); synchronizeTeacherWork(state, context());
        state.presentation.drawerMode = true; state.ui.drawerOpen = true; state.ui.artifactTab = selected;
        const host = await mount(component, { state, menus: [], currentUser: {} });
        try {
            const documentTarget = installNativeFacts(host), dialog = find(host.root, node => node.props.role === 'dialog');
            const close = find(dialog, node => node.props['aria-label'] === '关闭产物抽屉');
            const activeTab = find(dialog, node => node.props.id === 'teacher-work-tab-' + selected);
            const tabs = dialog.querySelectorAll('[role="tab"]');
            assert.equal(tabs.length, 3, 'querySelectorAll includes inactive tabs; it is not Tab order');
            assert.deepEqual(walk(dialog).filter(node => tabbable(node, host.root)), [close, activeTab]);
            activeTab.focus();
            assert.equal(tabEvent(dialog), 1, 'Tab at the last native tabbable must be prevented');
            assert.equal(documentTarget.activeElement, close, 'Tab wraps to the close control');
            assert.equal(tabEvent(dialog, true), 1, 'Shift-Tab at close must be prevented');
            assert.equal(documentTarget.activeElement, activeTab, 'Shift-Tab returns to the selected tab, never tabindex=-1');
        } finally { host.close(); }
    });
}

test('T5aP202 artifact trap excludes hidden and inert controls from focus endpoints', async () => {
    globals();
    const { createTeacherWorkState, synchronizeTeacherWork } = await import('../js/controllers/teacherWorkState.js');
    const component = (await import('../js/components/teacher-work/TeacherWork.js')).default;
    const state = Vue.reactive(createTeacherWorkState()); synchronizeTeacherWork(state, context());
    state.presentation.drawerMode = true; state.ui.drawerOpen = true; state.ui.artifactTab = 'versions';
    const host = await mount(component, { state, menus: [], currentUser: {} });
    try {
        installNativeFacts(host);
        const dialog = find(host.root, node => node.props.role === 'dialog');
        const close = find(dialog, node => node.props['aria-label'] === '关闭产物抽屉');
        const activeTab = find(dialog, node => node.props.id === 'teacher-work-tab-versions');
        // Native querySelectorAll still returns these real descendants. They are
        // deliberately hidden/inert so they must not become focus endpoints.
        const hiddenControl = { tag: 'button', text: '', props: { hidden: true }, children: [], parent: dialog, style: {} };
        const inertControl = { tag: 'button', text: '', props: { inert: '' }, children: [], parent: dialog, style: {} };
        dialog.children.push(hiddenControl, inertControl); installNativeFacts(host);
        const candidateSelector = 'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
        assert.ok(dialog.querySelectorAll(candidateSelector).includes(hiddenControl));
        assert.ok(dialog.querySelectorAll(candidateSelector).includes(inertControl));
        assert.deepEqual(walk(dialog).filter(node => tabbable(node, host.root)), [close, activeTab]);
        // installNativeFacts refreshes the document after the extra descendants.
        activeTab.focus();
        assert.equal(tabEvent(dialog), 1, 'hidden/inert descendants cannot move the last native Tab endpoint');
        assert.equal(globalThis.document.activeElement, close);
        assert.equal(tabEvent(dialog, true), 1);
        assert.equal(globalThis.document.activeElement, activeTab);
    } finally { host.close(); }
});

test('T5aP203 wide to narrow desktop resize rescues focus before removing the artifact region', async () => {
    const { storage, eventTarget } = globals(), refs = authRefs();
    const { useTeacherWork } = await import('../js/hooks/useTeacherWork.js');
    const component = (await import('../js/components/teacher-work/TeacherWork.js')).default;
    const viewportTarget = { innerWidth: 1440 }, scope = Vue.effectScope();
    let nativeDocument = null;
    const documentTarget = { get activeElement() { return nativeDocument?.activeElement || null; },
        querySelector: selector => nativeDocument?.querySelector(selector) || null };
    const hook = scope.run(() => useTeacherWork(refs, { api: unavailableApi(), storage, eventTarget, viewportTarget, documentTarget }));
    const host = await mount(component, { state: hook.state, menus: [], currentUser: {} });
    try {
        nativeDocument = installNativeFacts(host);
        const wideArtifact = find(host.root, node => node.props['data-teacher-work-zone'] === 'artifacts');
        const selectedTab = find(wideArtifact, node => node.props.id === 'teacher-work-tab-files');
        selectedTab.focus(); assert.equal(nativeDocument.activeElement, selectedTab);
        assert.equal(hook.state.presentation.drawerMode, false); assert.equal(hook.state.ui.drawerOpen, false);
        viewportTarget.innerWidth = 1280; eventTarget.dispatchEvent({ type: 'resize' }); await settle();
        // Install facts on any newly created trigger without replacing focus.
        const previousFocus = nativeDocument.activeElement;
        nativeDocument = installNativeFacts(host); nativeDocument.activeElement = previousFocus;
        const currentArtifact = find(host.root, node => node.props['data-teacher-work-zone'] === 'artifacts');
        const trigger = find(host.root, node => hasAttribute(node, 'data-teacher-work-artifact-trigger'));
        assert.equal(hook.state.presentation.drawerMode, true);
        assert.ok(nativeDocument.activeElement?.isConnected, 'focus cannot remain in a detached artifact subtree');
        assert.ok(nativeDocument.activeElement === trigger || currentArtifact?.contains(nativeDocument.activeElement),
            'focus must remain in the visible drawer or move to its surviving trigger');
    } finally { host.close(); scope.stop(); }
});

test('T5aP204 essential normal-size Work status text has AA contrast from exact CSS declarations', () => {
    const css = readFileSync(new URL('../styles/teacher-work.css', import.meta.url), 'utf8');
    const rule = selector => {
        const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        const body = new RegExp(escaped + '\\s*\\{([^}]*)\\}').exec(css)?.[1];
        assert.ok(body, 'missing exact bounded CSS rule: ' + selector); return body;
    };
    const color = (selector, property) => {
        const value = new RegExp('(?:^|;)\\s*' + property + ':\\s*(#[\\da-f]{3,6}|var\\(--[\\w-]+\\))', 'i').exec(rule(selector))?.[1];
        assert.ok(value, 'missing bounded ' + property + ' in ' + selector);
        if (!value.startsWith('var')) return value;
        const name = value.slice(4, -1), resolved = new RegExp(name + ':\\s*(#[\\da-f]{3,6})', 'i').exec(rule('.teacher-work'))?.[1];
        assert.ok(resolved, 'missing explicit status color variable ' + name); return resolved;
    };
    const luminance = hex => {
        const digits = hex.slice(1), normalized = digits.length === 3 ? [...digits].map(digit => digit + digit).join('') : digits;
        assert.equal(normalized.length, 6);
        const channels = [0, 2, 4].map(index => parseInt(normalized.slice(index, index + 2), 16) / 255)
            .map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4);
        return channels[0] * .2126 + channels[1] * .7152 + channels[2] * .0722;
    };
    for (const [foreground, background] of [
        ['.teacher-work-composer-note', '.teacher-work-composer'],
        ['.teacher-work-reason-code', '.teacher-work-stage'],
        ['.teacher-work-artifact-private', '.teacher-work-artifacts'],
        ['.teacher-work-muted', '.teacher-work-stage']
    ]) {
        const first = luminance(color(foreground, 'color')), second = luminance(color(background, 'background'));
        const ratio = (Math.max(first, second) + .05) / (Math.min(first, second) + .05);
        assert.ok(ratio >= 4.5, foreground + ' requires at least 4.5:1, observed ' + ratio.toFixed(2) + ':1');
    }
});
