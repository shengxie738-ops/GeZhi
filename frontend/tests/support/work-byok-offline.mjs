// Explicit synthetic handlers only; no fallback to the host fetch implementation.
export function createOfflineFetch(handlers = []) {
  const calls = [];
  let unexpectedIO = 0;
  return {
    calls,
    get unexpectedIO() { return unexpectedIO; },
    async fetch(url, init = {}) {
      const request = { url: String(url), method: String(init.method || 'GET').toUpperCase(), ...init };
      const handler = handlers.find(h => h.url === request.url && h.method === request.method);
      if (!handler) {
        unexpectedIO += 1;
        throw new Error('OFFLINE_UNREGISTERED_FETCH');
      }
      calls.push(request);
      const result = await handler.respond(request);
      return new Response(JSON.stringify(result.body), { status: result.status || 200,
        headers: { 'Content-Type': 'application/json' } });
    },
    assertClean() { if (unexpectedIO) throw new Error('OFFLINE_UNREGISTERED_FETCH'); },
  };
}

// Import this helper before application modules (or use node --import ...).
// A swallowed unknown global fetch is still a failing offline test process.
let unregisteredGlobalIO = 0;
let activeGlobal = null;
const denyGlobalFetch = async () => {
  unregisteredGlobalIO += 1;
  throw new Error('OFFLINE_UNREGISTERED_FETCH');
};
globalThis.fetch = denyGlobalFetch;
process.on('beforeExit', () => {
  if (unregisteredGlobalIO || (activeGlobal && activeGlobal.unexpectedIO)) {
    process.stderr.write('OFFLINE_UNREGISTERED_FETCH\n');
    process.exitCode = 1;
  }
});
export function installOfflineFetch(handlers = []) {
  if (activeGlobal) throw new Error('OFFLINE_FETCH_SCENARIO_ALREADY_ACTIVE');
  const offline = createOfflineFetch(handlers);
  activeGlobal = offline;
  globalThis.fetch = offline.fetch;
  return Object.assign(offline, {
    restore() {
      offline.assertClean();
      globalThis.fetch = denyGlobalFetch;
      activeGlobal = null;
    },
  });
}
