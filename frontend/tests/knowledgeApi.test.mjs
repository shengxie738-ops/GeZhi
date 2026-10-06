import assert from 'node:assert/strict';

const storage = new Map();
globalThis.window = {
  // Keep this transport fixture independent of the host's production default.
  __API_ORIGIN__: 'https://knowledge-api.example.test/api/',
  location: { hostname: 'localhost' },
  localStorage: {
    getItem(key) {
      return storage.get(key) || null;
    },
    setItem(key, value) {
      storage.set(key, value);
    },
    removeItem(key) {
      storage.delete(key);
    },
  },
};
globalThis.localStorage = globalThis.window.localStorage;

const calls = [];
globalThis.fetch = async (url, config = {}) => {
  calls.push({ url, config });
  return {
    ok: true,
    status: 200,
    text: async () => JSON.stringify({ status: 'success', data: { id: 'repo_a' } }),
  };
};

const { knowledgeApi } = await import('../js/api/knowledgeApi.js');

await knowledgeApi.deleteRepository({ userId: 'student 01', repositoryId: 'repo/a' });

assert.equal(
  calls[0].url,
  'https://knowledge-api.example.test/api/user/knowledge/repositories/repo%2Fa?user_id=student%2001',
);
assert.equal(calls[0].config.method, 'DELETE');

// env.js resolves once per import, so each isolated case gets a fresh module.
const runtimeWindow = globalThis.window;
let originCase = 0;
async function resolveOrigin(runtime) {
  globalThis.window = runtime;
  try {
    return await import(`../js/config/env.js?knowledge-origin-case=${++originCase}`);
  } finally {
    globalThis.window = runtimeWindow;
  }
}
for (const hostname of ['localhost', '127.0.0.1', '::1']) {
  const env = await resolveOrigin({ location: { hostname } });
  assert.equal(env.API_ORIGIN, 'http://127.0.0.1:8516');
  assert.equal(env.API_BASE_URL, 'http://127.0.0.1:8516/api');
}
assert.equal((await resolveOrigin({ location: { hostname: 'app.example.test' } })).API_ORIGIN, 'https://gezhisystem.com');
assert.equal((await resolveOrigin({
  location: { hostname: 'localhost' },
  __API_ORIGIN__: 'https://override.example.test/api///',
  __API_BASE_URL__: 'https://ignored.example.test',
})).API_ORIGIN, 'https://override.example.test');
assert.equal((await resolveOrigin({
  location: { hostname: 'localhost' },
  __API_BASE_URL__: 'https://base-override.example.test/api/',
})).API_BASE_URL, 'https://base-override.example.test/api');
storage.set('apiOrigin', 'https://saved-api.example.test/api/');
assert.equal((await resolveOrigin({ location: { hostname: 'localhost' }, localStorage: runtimeWindow.localStorage })).API_ORIGIN, 'https://saved-api.example.test');
storage.delete('apiOrigin');
assert.equal(calls.length, 1, 'Origin resolution must not perform additional requests');

console.log('knowledgeApi tests passed');
