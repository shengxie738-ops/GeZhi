import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';

const helper = new URL('./work-byok-offline.mjs', import.meta.url);
test('offline-unregistered-fetch-rejected', async () => {
  assert.ok(existsSync(helper), 'offline frontend helper is not implemented');
  const { createOfflineFetch } = await import(helper.href);
  const offline = createOfflineFetch();
  await assert.rejects(() => offline.fetch('https://unregistered.example'), /OFFLINE_UNREGISTERED_FETCH/);
  assert.equal(offline.unexpectedIO, 1);
  assert.throws(() => offline.assertClean(), /OFFLINE_UNREGISTERED_FETCH/);
});
test('registered synthetic fetch records exact request and never falls through', async () => {
  assert.ok(existsSync(helper), 'offline frontend helper is not implemented');
  const { createOfflineFetch } = await import(helper.href);
  const offline = createOfflineFetch([{ method: 'POST', url: '/user/models/check-selection',
    respond: request => ({ status: 200, body: { method: request.method, ok: true } }) }]);
  const response = await offline.fetch('/user/models/check-selection', { method: 'POST', body: '{}' });
  assert.deepEqual(await response.json(), { method: 'POST', ok: true });
  assert.equal(offline.calls.length, 1);
  offline.assertClean();
});
test('Vue loader maps only shipped pinned runtime', async () => {
  const loader = new URL('./vue-loader.mjs', import.meta.url);
  assert.ok(existsSync(loader), 'offline Vue loader is not implemented');
  const { resolve, load, vueSource } = await import(loader.href);
  assert.ok(vueSource.endsWith('/frontend/libs/vue.esm-browser.js'));
  const result = await resolve('vue', {}, () => { throw new Error('fallback should not run'); });
  assert.equal(result.url, new URL('../../libs/vue.esm-browser.js', import.meta.url).href);
  assert.equal((await load(result.url, {}, () => {})).format, 'module');
  let forwarded = false;
  await resolve('node:fs', {}, () => { forwarded = true; return {}; });
  assert.equal(forwarded, true);
});

test('caught unregistered global fetch still fails an isolated offline test process', async () => {
  const { spawnSync } = await import('node:child_process');
  const child = spawnSync(process.execPath, ['--input-type=module', '--eval',
    `import ${JSON.stringify(helper.href)}; try { await fetch('/unregistered'); } catch {}`],
    { env: { PATH: '/usr/bin:/bin' }, encoding: 'utf8' });
  assert.equal(child.status, 1);
  assert.match(child.stderr, /OFFLINE_UNREGISTERED_FETCH/);
});

test('installed synthetic global fetch never reaches ambient fetch', async () => {
  const { installOfflineFetch } = await import(helper.href);
  assert.equal(typeof installOfflineFetch, 'function');
  const offline = installOfflineFetch([{ method: 'GET', url: '/synthetic',
    respond: () => ({ body: { synthetic: true } }) }]);
  try { assert.deepEqual(await (await fetch('/synthetic')).json(), { synthetic: true }); }
  finally { offline.restore(); }
  offline.assertClean();
});
