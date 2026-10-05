import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { registerHooks } from 'node:module';
import test from 'node:test';
import * as Vue from '../libs/vue.esm-browser.js';
import { getPluginById } from '../js/config/academicPlugins.js';
import { API_BASE_URL } from '../js/config/env.js';
import { clearAcademicCache } from '../js/api/academic/aggregate.js';

// Use the frontend's shipped Vue runtime, without installing packages or
// importing main.js, a browser host, an application server or the backend.
const hookUrl = new URL('../js/hooks/usePlugins.js', import.meta.url).href;
const vueUrl = new URL('../libs/vue.esm-browser.js', import.meta.url).href;
const resolution = registerHooks({
    resolve(specifier, context, nextResolve) {
        if (specifier === 'vue' && context.parentURL === hookUrl) {
            return { url: vueUrl, shortCircuit: true };
        }
        return nextResolve(specifier, context);
    }
});
const { usePlugins } = await import(hookUrl);
resolution.deregister();

const SOURCES = ['arxiv', 'openalex', 'crossref', 'europepmc'];
const QUERY = 'drawer boundary fixture';
const TITLE = 'drawer boundary fixture paper';
const settle = async () => {
    await Vue.nextTick();
    await new Promise(resolve => setImmediate(resolve));
    await Vue.nextTick();
};

function sourceRequest(rawUrl) {
    const url = new URL(String(rawUrl));
    const gateway = /^\/api\/academic\/(arxiv|openalex|crossref)\/search$/.exec(url.pathname);
    const direct = url.origin === 'https://www.ebi.ac.uk'
        && url.pathname === '/europepmc/webservices/rest/search';
    assert.ok(gateway || direct, `Unexpected synthetic request: ${url}`);
    if (gateway) {
        const expected = new URL(`${API_BASE_URL}/academic/${gateway[1]}/search`);
        assert.equal(url.origin, expected.origin, 'The real adapter must use the configured API origin');
        assert.equal(url.pathname, expected.pathname);
        assert.equal(url.searchParams.get('limit'), '10');
    } else {
        assert.equal(url.searchParams.get('format'), 'json');
        assert.equal(url.searchParams.get('pageSize'), '10');
        assert.equal(url.searchParams.get('resultType'), 'core');
    }
    return { source: gateway ? gateway[1] : 'europepmc', query: url.searchParams.get('query') };
}

function paperResponse(source, title = TITLE) {
    const items = {
        arxiv: [{ title, arxivId: '1706.03762', sourceId: '1706.03762', year: 2017 }],
        openalex: [{ title, id: 'https://openalex.org/W12345', publication_year: 2024 }],
        crossref: [{ title: [title], DOI: '10.1234/drawer.fixture', type: 'journal-article' }],
        europepmc: [{ title, source: 'MED', id: '12345678', pubYear: '2024' }]
    };
    const body = source === 'europepmc'
        ? { resultList: { result: items[source] } }
        : { items: items[source] };
    return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } });
}

function deferred() {
    let resolve;
    return { promise: new Promise(done => { resolve = done; }), resolve: value => resolve(value) };
}

function setup() {
    const saved = {
        localStorage: globalThis.localStorage,
        window: globalThis.window,
        fetch: globalThis.fetch
    };
    const storage = new Map([['token', 'drawer-test-alice']]);
    const calls = [];
    let responseFor = request => paperResponse(request.source);
    globalThis.localStorage = {
        getItem: key => storage.get(key) ?? null,
        setItem: (key, value) => storage.set(key, String(value)),
        removeItem: key => storage.delete(key)
    };
    globalThis.window = { location: { hostname: 'frontend.invalid' }, localStorage };
    // This transport never falls through to native fetch. Abort is intentionally
    // ignored by delayed responses to exercise the production stale-result fence.
    globalThis.fetch = async (url, options = {}) => {
        const request = { ...sourceRequest(url), signal: options.signal };
        calls.push(request);
        assert.ok(calls.length <= 12, 'Synthetic transport request budget exceeded');
        return responseFor(request);
    };
    clearAcademicCache();
    const scope = Vue.effectScope();
    const user = Vue.ref({ username: 'Alice' });
    const state = scope.run(() => usePlugins(user, () => {}, Vue.ref('')));
    return {
        state, user, storage, calls,
        respondWith(fn) { responseFor = fn; },
        async close() {
            scope.stop();
            await settle();
            clearAcademicCache();
            globalThis.localStorage = saved.localStorage;
            globalThis.window = saved.window;
            globalThis.fetch = saved.fetch;
        }
    };
}

function installedDetailTrialButton(state) {
    const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
    const start = html.indexOf('<button v-if="selectedPluginDetail.canSearchLive"');
    const end = html.indexOf('</button>', start);
    assert.ok(start >= 0 && end > start, 'Installed plugin-detail trial button must exist');
    const render = Vue.compile(html.slice(start, end + '</button>'.length), {
        hoistStatic: false,
        decodeEntities: raw => raw,
        onError(error) { throw error; }
    });
    const node = render(Vue.reactive({ ...state }), []);
    assert.equal(node.type, 'button');
    assert.equal(typeof node.props.onClick, 'function');
    return node.props.onClick;
}

for (const source of SOURCES) {
    test(`paper drawer: installed detail action preserves ${source} and closes detail before explicit search`, async () => {
        const h = setup();
        try {
            const plugin = getPluginById(`plugin_${source}`);
            h.state.openPluginDetail(plugin);
            installedDetailTrialButton(h.state)();
            assert.equal(h.state.activeSearchPlugin.value?.id, plugin.id,
                'Closing detail must not erase the provider passed to the drawer');
            assert.equal(h.state.selectedPluginDetail.value, null);
            assert.deepEqual(h.state.selectedPaperSourceKeys.value, [source]);
            await settle();
            assert.equal(h.calls.length, 0, 'Opening detail trial must not submit an invented query');
        } finally {
            await h.close();
        }
    });

    test(`paper drawer: opening ${source} starts idle and clears the previous result surface without transport`, async () => {
        const h = setup();
        try {
            const plugin = getPluginById(`plugin_${source}`);
            h.state.restorePaperSearch({
                query: 'older query', status: 'error',
                results: [{ id: 'older', title: 'older paper' }],
                statuses: [{ key: 'crossref', status: 'error', error: 'older failure' }],
                summary: { totalFetched: 7, totalAfterMerge: 6, effectiveQuery: 'older query' }
            });
            h.state.paperSearchError.value = 'older failure';
            h.state.openPaperDetail({ id: 'older', title: 'older paper' });
            h.state.openPaperSearchDrawer(plugin);
            await settle();
            assert.equal(h.calls.length, 0, 'Drawer opening must be read-only');
            assert.equal(h.state.activeSearchPlugin.value?.id, plugin.id);
            assert.equal(h.state.paperSearchQuery.value, '');
            assert.equal(h.state.paperSearchStatus.value, 'idle');
            assert.equal(h.state.isSearchingPapers.value, false);
            assert.deepEqual(h.state.paperSearchResults.value, []);
            assert.deepEqual(h.state.paperSourceStatuses.value, []);
            assert.equal(h.state.paperSearchSummary.value.totalFetched, 0);
            assert.equal(h.state.paperSearchSummary.value.totalAfterMerge, 0);
            assert.equal(h.state.paperSearchError.value, '');
            assert.equal(h.state.selectedPaper.value, null);
        } finally {
            await h.close();
        }
    });

    test(`paper drawer: explicit ${source} submit executes the retained real adapter and displays its paper`, async () => {
        const h = setup();
        try {
            h.state.openPaperSearchDrawer(getPluginById(`plugin_${source}`));
            await settle();
            // Idle-open behavior has dedicated regression coverage above. This
            // case independently pins the real explicit-search adapter path.
            h.calls.length = 0;
            clearAcademicCache();
            h.state.paperSearchQuery.value = QUERY;
            assert.equal(await h.state.executePaperSearch(), true);
            assert.deepEqual(h.calls.map(({ source, query }) => ({ source, query })), [{ source, query: QUERY }]);
            assert.equal(h.state.paperSearchStatus.value, 'success');
            assert.equal(h.state.paperSearchResults.value.length, 1);
            assert.equal(h.state.paperSearchResults.value[0].title, TITLE);
            assert.deepEqual(h.state.paperSearchResults.value[0].sources.map(item => item.key), [source]);
            assert.equal(h.state.isSearchingPapers.value, false);
        } finally {
            await h.close();
        }
    });

    test(`paper drawer: empty ${source} submit stays idle without any provider request`, async () => {
        const h = setup();
        try {
            h.state.openPaperSearchDrawer(getPluginById(`plugin_${source}`));
            await settle();
            h.calls.length = 0;
            h.state.paperSearchQuery.value = ' \n ';
            assert.equal(await h.state.executePaperSearch(), false);
            await settle();
            assert.equal(h.calls.length, 0);
            assert.equal(h.state.paperSearchStatus.value, 'idle');
            assert.equal(h.state.isSearchingPapers.value, false);
            assert.deepEqual(h.state.paperSearchResults.value, []);
            assert.deepEqual(h.state.selectedPaperSourceKeys.value, [source]);
        } finally {
            await h.close();
        }
    });
}

for (const source of ['crossref', 'europepmc']) {
    test(`paper drawer: reopening during delayed ${source} search aborts it and fences its late results`, async () => {
        const h = setup();
        const waiting = deferred();
        let search;
        try {
            h.state.openPaperSearchDrawer(getPluginById(`plugin_${source}`));
            await settle();
            h.calls.length = 0;
            clearAcademicCache();
            h.respondWith(() => waiting.promise);
            search = h.state.executePaperSearch(QUERY);
            assert.equal(h.calls.length, 1);
            const oldSignal = h.calls[0].signal;
            h.state.openPaperSearchDrawer(getPluginById('plugin_arxiv'));
            assert.equal(oldSignal.aborted, true, 'A new drawer must cancel superseded transport');
            assert.equal(h.state.activeSearchPlugin.value?.id, 'plugin_arxiv');
            assert.equal(h.state.paperSearchStatus.value, 'idle');
            assert.equal(h.state.isSearchingPapers.value, false);
            assert.equal(h.state.paperSearchQuery.value, '');
            assert.equal(h.calls.length, 1, 'Reopening must not launch a replacement query');
            waiting.resolve(paperResponse(source, 'drawer boundary fixture obsolete result'));
            assert.equal(await search, false);
            await settle();
            assert.deepEqual(h.state.paperSearchResults.value, []);
            assert.deepEqual(h.state.paperSourceStatuses.value, []);
            assert.equal(h.state.paperSearchStatus.value, 'idle');
        } finally {
            waiting.resolve(paperResponse(source));
            h.state.cancelPaperSearch();
            if (search) await search;
            await h.close();
        }
    });

    test(`paper drawer: account switch during delayed ${source} search clears selection and rejects the old response`, async () => {
        const h = setup();
        const waiting = deferred();
        let search;
        try {
            h.state.openPaperSearchDrawer(getPluginById(`plugin_${source}`));
            await settle();
            h.calls.length = 0;
            clearAcademicCache();
            h.respondWith(() => waiting.promise);
            search = h.state.executePaperSearch(QUERY);
            assert.equal(h.calls.length, 1);
            const oldSignal = h.calls[0].signal;
            h.storage.set('token', 'drawer-test-bob');
            h.user.value = { username: 'Bob' };
            assert.equal(oldSignal.aborted, true);
            assert.equal(h.state.activeSearchPlugin.value, null);
            assert.equal(h.state.paperSearchStatus.value, 'idle');
            waiting.resolve(paperResponse(source, 'drawer boundary fixture previous account'));
            assert.equal(await search, false);
            await settle();
            assert.deepEqual(h.state.paperSearchResults.value, []);
            assert.deepEqual(h.state.paperSourceStatuses.value, []);
            assert.equal(h.state.paperSearchQuery.value, '');
            assert.equal(h.state.paperSearchStatus.value, 'idle');
            assert.equal(h.state.isSearchingPapers.value, false);
        } finally {
            waiting.resolve(paperResponse(source));
            h.state.cancelPaperSearch();
            if (search) await search;
            await h.close();
        }
    });
}

for (const [label, selection] of [
    ['missing', null],
    ['non-search', getPluginById('plugin_peer_review')],
    ['unregistered', { id: 'plugin_unknown', canSearchLive: true, searchSourceKey: 'crossref' }]
]) {
    test(`paper drawer: rejects unavailable ${label} selection without substituting installed sources`, async () => {
        const h = setup();
        try {
            h.state.openPaperSearchDrawer(getPluginById('plugin_crossref'));
            await settle();
            h.calls.length = 0;
            assert.equal(h.state.openPaperSearchDrawer(selection), false);
            await settle();
            assert.equal(h.calls.length, 0);
            assert.equal(h.state.activeSearchPlugin.value?.id, 'plugin_crossref');
            assert.deepEqual(h.state.selectedPaperSourceKeys.value, ['crossref']);
        } finally {
            await h.close();
        }
    });
}
