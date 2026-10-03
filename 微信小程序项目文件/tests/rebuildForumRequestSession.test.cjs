// Run only through the reviewed offline launcher; actual config is an inert staged leaf.
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const config = require('../utils/config.js');
const source = path.resolve(__dirname, '../utils/request.js');

function harness(token = 'actor-A') {
  const storage = new Map([[config.TOKEN_KEY, token], [config.USER_KEY, { username: 'A' }]]);
  const calls = [], removed = [], navigation = [];
  global.wx = {
    getStorageSync: key => storage.get(key),
    removeStorageSync: key => { removed.push(key); storage.delete(key); },
    reLaunch: value => navigation.push(value),
    cloud: { callFunction: value => calls.push(value) }
  };
  delete require.cache[source];
  const { request } = require(source);
  const respond = (index, body, statusCode = 200) => calls[index].success({ result: { statusCode, data: body } });
  return { request, storage, calls, removed, navigation, respond };
}

for (const body of [
  { code: 0, data: { id: 'mini-reply', content: 'Synthetic mini reply' } },
  { code: 200, data: { id: 'web-reply', content: 'Synthetic reply' } },
  { success: true, data: { id: 'api-response-reply', content: 'Synthetic reply' } },
  { status: 'success', data: { id: 'status-reply', content: 'Synthetic reply' } }
]) test(`actual request accepts ${body.code === undefined ? (body.success === true ? 'api_response' : body.status) : 'code ' + body.code} reply envelope`, async () => {
  const h = harness(); const result = h.request({ url: '/forum/posts/p/replies', method: 'POST', data: { content: 'Synthetic reply' } });
  h.respond(0, body); assert.deepEqual(await result, body.data);
});

test('proxy method, path, query/data override, action and token semantics remain intact', async () => {
  const h = harness(); const result = h.request({ url: '/forum/posts?q=hello+world&x=old', method: 'put', action: 'synthetic', data: { x: 'new', content: 'body' } });
  assert.equal(h.calls[0].name, config.API_PROXY_FUNCTION);
  assert.deepEqual(h.calls[0].data, { action: 'synthetic', data: { q: 'hello world', x: 'new', content: 'body', _method: 'PUT', _path: '/forum/posts', _token: 'actor-A' } });
  h.respond(0, { code: 200, data: [] }); assert.deepEqual(await result, []);
});

test('anonymous reads send no invented credential', async () => {
  const h = harness(''); const result = h.request({ url: '/forum/posts' });
  assert.equal(h.calls[0].data.data._token, undefined); h.respond(0, { code: 200, data: [] }); await result;
});

test('legacy token fallback is preserved', async () => {
  const h = harness(''); h.storage.set(config.LEGACY_TOKEN_KEY, 'legacy-A'); const result = h.request({ url: '/forum/posts' });
  assert.equal(h.calls[0].data.data._token, 'legacy-A'); h.respond(0, { code: 0, data: [] }); await result;
});

for (const status of ['success', '401', 'network']) test(`late actor A ${status} cannot affect actor B session`, async () => {
  const h = harness(); const result = h.request({ url: '/forum/posts' });
  const rejection = assert.rejects(result, error => error.code === 'STALE_SESSION');
  h.storage.set(config.TOKEN_KEY, 'actor-B'); h.storage.set(config.USER_KEY, { username: 'B' });
  if (status === 'network') h.calls[0].fail({ errMsg: 'old transport error' });
  else h.respond(0, status === '401' ? { detail: 'not authenticated' } : { code: 200, data: ['old'] }, status === '401' ? 401 : 200);
  await rejection; assert.deepEqual(h.removed, []); assert.deepEqual(h.navigation, []);
  assert.equal(h.storage.get(config.TOKEN_KEY), 'actor-B'); assert.deepEqual(h.storage.get(config.USER_KEY), { username: 'B' });
});

test('current-session 401 still expires that session exactly once', async () => {
  const h = harness(); h.storage.set(config.LEGACY_TOKEN_KEY, 'actor-A'); const result = h.request({ url: '/forum/posts' });
  const rejection = assert.rejects(result, /登录已失效/); h.respond(0, { detail: 'not authenticated' }, 401); await rejection;
  assert.deepEqual(h.removed, [config.TOKEN_KEY, config.LEGACY_TOKEN_KEY, config.USER_KEY]);
  assert.deepEqual(h.navigation, [{ url: '/pages/login/index' }]);
});

test('invalid supplied credentials are never retried as anonymous', async () => {
  const h = harness(); const result = h.request({ url: '/forum/posts' }); const rejection = assert.rejects(result, /登录已失效/);
  h.respond(0, { code: 401, message: 'not authenticated' }); await rejection; assert.equal(h.calls.length, 1);
});

for (const body of [{ code: 403, message: 'denied' }, { success: false, message: 'denied' }, { status: 'error', error: 'denied' }]) test(`failed envelope ${JSON.stringify(body)} rejects without clearing session`, async () => {
  const h = harness(); const result = h.request({ url: '/forum/posts' }); const rejection = assert.rejects(result, /denied/);
  h.respond(0, body); await rejection; assert.deepEqual(h.removed, []);
});

for (const [before, after] of [['', 'actor-B'], ['actor-A', '']]) test(`effective token transition ${before ? 'authenticated' : 'anonymous'} rejects older success`, async () => {
  const h = harness(before); const result = h.request({ url: '/forum/posts' }); const rejection = assert.rejects(result, error => error.code === 'STALE_SESSION');
  h.storage.set(config.TOKEN_KEY, after); h.respond(0, { code: 200, data: [] }); await rejection; assert.deepEqual(h.removed, []); assert.deepEqual(h.navigation, []);
});

test('stale code-envelope 401 cannot expire newer legacy session', async () => {
  const h = harness(''); h.storage.set(config.LEGACY_TOKEN_KEY, 'legacy-A'); const result = h.request({ url: '/forum/posts' }); const rejection = assert.rejects(result, error => error.code === 'STALE_SESSION');
  h.storage.set(config.LEGACY_TOKEN_KEY, 'legacy-B'); h.respond(0, { code: 401, message: 'not authenticated' }); await rejection;
  assert.equal(h.storage.get(config.LEGACY_TOKEN_KEY), 'legacy-B'); assert.deepEqual(h.removed, []); assert.deepEqual(h.navigation, []);
});
