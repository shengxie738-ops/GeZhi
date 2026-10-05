// Test-only environment for the bounded student Work Node regression selection.
// Uses shipped Vue and in-memory Web Storage; no browser or persistent storage.
import { registerHooks } from 'node:module';

const frontendUrl = new URL('../../', import.meta.url).href;
const vueUrl = new URL('libs/vue.esm-browser.js', frontendUrl).href;
registerHooks({
    resolve(specifier, context, nextResolve) {
        if (specifier === 'vue' && context.parentURL?.startsWith(frontendUrl)) {
            return { url: vueUrl, shortCircuit: true };
        }
        return nextResolve(specifier, context);
    }
});

const values = new Map();
globalThis.localStorage = {
    getItem: key => values.has(String(key)) ? values.get(String(key)) : null,
    setItem: (key, value) => values.set(String(key), String(value)),
    removeItem: key => values.delete(String(key)),
    clear: () => values.clear(),
    key: index => [...values.keys()][index] ?? null,
    get length() { return values.size(); }
};
