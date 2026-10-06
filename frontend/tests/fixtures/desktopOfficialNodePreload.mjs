// Official compiler/custom-renderer/SSR lane only. No shipped-runtime remapping.
import assert from 'node:assert/strict';
import * as Vue from 'vue';
import compiler from '@vue/compiler-dom/package.json' with { type: 'json' };
import serverRenderer from '@vue/server-renderer/package.json' with { type: 'json' };

assert.equal(Vue.version, '3.5.39');
assert.equal(compiler.version, '3.5.39');
assert.equal(serverRenderer.version, '3.5.39');
globalThis.fetch = function denyDesktopNetwork() { throw new Error('Unregistered network work in official desktop Node lane'); };
const values = new Map();
globalThis.localStorage = {
    getItem: key => values.has(String(key)) ? values.get(String(key)) : null,
    setItem: (key, value) => values.set(String(key), String(value)),
    removeItem: key => values.delete(String(key)), clear: () => values.clear(),
    key: index => [...values.keys()][index] ?? null,
    get length() { return values.size; }
};
