// Actual production Vue lane; initialize before any synthetic document fixture.
import assert from 'node:assert/strict';
import { registerHooks } from 'node:module';
import * as Vue from '../../libs/vue.esm-browser.js';
import './studentWorkNodePreload.mjs';

assert.equal(Vue.version, '3.3.4');
globalThis.fetch = function denyDesktopNetwork() { throw new Error('Unregistered network work in shipped desktop Node lane'); };
registerHooks({
    resolve(specifier, context, nextResolve) {
        if (/^@vue\/(?:compiler-dom|server-renderer)(?:\/|$)/.test(specifier)) {
            throw new Error('Compiler and SSR dependencies require the official Vue test lane');
        }
        return nextResolve(specifier, context);
    }
});
