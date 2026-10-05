// Task5a finite synthetic host. Shipped Vue only; no browser, entrypoint or timers.
import assert from 'node:assert/strict';
import * as Vue from '../../libs/vue.esm-browser.js';

assert.equal(Vue.version, '3.3.4');
export { Vue };
export const walk = node => [node, ...node.children.flatMap(walk)];
export const textOf = node => node.tag === '#comment' ? '' : node.text + node.children.map(textOf).join('');
export const find = (root, predicate) => walk(root).find(predicate);
export const button = (root, label) => find(root, node => node.tag === 'button' &&
    (textOf(node).trim() === label || node.props['aria-label'] === label));
export const settle = async () => { for (let index = 0; index < 8; index++) await Vue.nextTick(); };

function matches(node, selector) {
    if (selector.startsWith('#')) return node.props.id === selector.slice(1);
    const attribute = /^\[([\w-]+)\]$/.exec(selector);
    if (attribute) return Object.hasOwn(node.props, attribute[1]);
    return node.tag === selector;
}
function element(tag = '', text = '') {
    return {
        tag, text, props: {}, children: [], parent: null, style: {},
        get tagName() { return this.tag.toUpperCase(); },
        get isConnected() { return Boolean(this.parent); },
        getClientRects() { return this.isConnected ? [{}] : []; },
        focus() { globalThis.document.activeElement = this; },
        contains(other) { return walk(this).includes(other); },
        querySelector(selector) { return walk(this).find(node => matches(node, selector)); },
        querySelectorAll() { return walk(this).filter(node =>
            !node.props.disabled && (['button', 'input', 'select', 'textarea', 'a'].includes(node.tag) ||
            node.props.tabindex !== undefined && String(node.props.tabindex) !== '-1')); }
    };
}
export const renderer = Vue.createRenderer({
    createElement: tag => element(tag), createText: text => element('#text', text),
    createComment: text => element('#comment', text), setText: (node, text) => node.text = text,
    setElementText: (node, text) => { node.text = text; node.children = []; },
    parentNode: node => node.parent,
    nextSibling: node => node.parent?.children[node.parent.children.indexOf(node) + 1] || null,
    insert(node, parent, anchor) {
        if (node.parent) node.parent.children.splice(node.parent.children.indexOf(node), 1);
        node.parent = parent;
        const index = anchor ? parent.children.indexOf(anchor) : -1;
        if (index < 0) parent.children.push(node); else parent.children.splice(index, 0, node);
    },
    remove(node) {
        if (node.parent) node.parent.children.splice(node.parent.children.indexOf(node), 1);
        node.parent = null;
    },
    patchProp(node, key, _previous, value) { node.props[key] = value; }
});
export const compiled = component => ({ ...component, render: Vue.compile(component.template, {
    hoistStatic: false, onError(error) { throw error; },
    decodeEntities(raw) { assert.doesNotMatch(raw, /&(?:#\d+|#x[\da-f]+|[a-z]+);/iu); return raw; }
}) });
export async function mount(component, props = {}) {
    const root = element('root'), errors = [], warnings = [], emitted = {};
    const installed = compiled(component);
    const handlers = Object.fromEntries((installed.emits || []).map(name =>
        ['on' + name[0].toUpperCase() + name.slice(1), (...args) => (emitted[name] ??= []).push(args)]));
    const app = renderer.createApp({ render: () => Vue.h(installed, { ...props, ...handlers }) });
    app.config.errorHandler = error => errors.push(error);
    app.config.warnHandler = warning => warnings.push(warning);
    app.mount(root);
    await settle();
    return { root, emitted, close() { app.unmount(); assert.deepEqual(errors, []); assert.deepEqual(warnings, []); } };
}
export function documentFor(root) {
    globalThis.document = { activeElement: null, querySelector: selector =>
        walk(root).find(node => matches(node, selector)) || null };
    return globalThis.document;
}
export function globals(seed = {}) {
    const values = new Map(Object.entries(seed)), operations = [], listeners = new Map();
    const storage = {
        getItem(key) { operations.push(['get', key]); return values.get(key) ?? null; },
        setItem(key, value) { operations.push(['set', key, String(value)]); values.set(key, String(value)); },
        removeItem(key) { operations.push(['remove', key]); values.delete(key); }
    };
    const eventTarget = {
        addEventListener(name, listener) { if (!listeners.has(name)) listeners.set(name, new Set()); listeners.get(name).add(listener); },
        removeEventListener(name, listener) { listeners.get(name)?.delete(listener); },
        dispatchEvent(event) { for (const listener of listeners.get(event.type) || []) listener(event); }
    };
    globalThis.localStorage = storage;
    globalThis.window = { ...eventTarget, location: { hostname: 'synthetic.invalid', href: '' }, innerWidth: 1440 };
    globalThis.document = { activeElement: null, querySelector: () => null };
    return { storage, operations, values, eventTarget, listeners };
}
export const context = () => ({ actor: 'teacher-a', role: 'teacher', authEpoch: 4, authVerified: true, active: true });
export const authRefs = () => ({ actor: Vue.ref('teacher-a'), role: Vue.ref('teacher'), authEpoch: Vue.ref(4),
    authVerified: Vue.ref(true), currentView: Vue.ref('t_work') });
export const unavailableApi = () => ({ getCapabilities: async () => {
    throw Object.assign(new Error('synthetic unavailable'), { name: 'TeacherWorkError', status: 503, reason: 'TEACHER_WORK_UNAVAILABLE' });
} });
export const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
export const capabilityFacts = () => ({ chat: true, task_write: true, generate: true, storage: true,
    structural_preview: true, rendered_preview: false, publish: false,
    reasons: { rendered_preview: 'rendered_preview_unsupported', publish: 'private_teacher_work_only' } });
export const response = (status, payload) => ({ status, ok: status >= 200 && status < 300,
    text: async () => typeof payload === 'string' ? payload : JSON.stringify(payload) });
