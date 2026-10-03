import test from 'node:test';
import assert from 'node:assert/strict';
import { effectScope, nextTick } from 'vue';
import { useAuth } from '../js/hooks/useAuth.js';
import request from '../js/utils/request.js';
const deferred = () => {
  let resolve;
  const promise = new Promise(r => resolve = r);
  return {
    promise,
    resolve
  };
};
const response = data => ({
  ok: true,
  text: async () => JSON.stringify(data)
});
const settle = async () => {
  await nextTick();
  await new Promise(r => setImmediate(r));
  await nextTick();
};
function setup() {
  const events = new Map(),
    storage = new Map([['token', 'A'], ['currentUser', JSON.stringify({
      username: 'Alice'
    })], ['isLoggedIn', 'true']]);
  globalThis.localStorage = {
    getItem: k => storage.get(k) ?? null,
    setItem: (k, v) => storage.set(k, String(v)),
    removeItem: k => storage.delete(k)
  };
  globalThis.window = {
    localStorage,
    location: {
      hostname: 'localhost',
      href: ''
    },
    addEventListener: (k, v) => events.set(k, v),
    removeEventListener: k => events.delete(k),
    dispatchEvent() {}
  };
  return {
    events,
    storage
  };
}
test('request rejects old successful response when shared token changes', async () => {
  const {
    storage
  } = setup();
  const waiting = deferred();
  globalThis.fetch = async () => waiting.promise;
  const reading = request('/chat/history');
  storage.set('token', 'B');
  waiting.resolve(response({
    data: ['old']
  }));
  await assert.rejects(reading, {
    name: 'AbortError'
  });
});
test('storage token transition revalidates identity and fences prior auth reply', async () => {
  const {
    storage,
    events
  } = setup();
  const a = deferred(),
    b = deferred();
  let calls = 0;
  globalThis.fetch = async () => ++calls === 1 ? a.promise : b.promise;
  const scope = effectScope();
  const auth = scope.run(() => useAuth(() => {}, () => {}));
  const old = auth.verifySession();
  storage.set('token', 'B');
  events.get('storage')?.({
    key: 'token'
  });
  assert.equal(auth.authVerified.value, false);
  b.resolve(response({
    success: true,
    data: {
      username: 'Bob',
      role: 'teacher'
    }
  }));
  await settle();
  assert.equal(auth.currentUser.value?.username, 'Bob');
  assert.equal(auth.authVerified.value, true);
  a.resolve(response({
    success: true,
    data: {
      username: 'Alice'
    }
  }));
  await old;
  assert.equal(auth.currentUser.value.username, 'Bob');
  scope.stop();
});
test('same-user token transition revalidates and cross-tab logout releases identity', async () => {
  const {
    storage,
    events
  } = setup();
  let calls = 0;
  globalThis.fetch = async () => {
    calls++;
    return response({
      success: true,
      data: {
        username: 'Alice'
      }
    });
  };
  const scope = effectScope();
  const auth = scope.run(() => useAuth(() => {}, () => {}));
  await auth.verifySession();
  storage.set('token', 'B');
  events.get('storage')?.({
    key: 'token'
  });
  await settle();
  assert.equal(calls, 2);
  assert.equal(auth.authVerified.value, true);
  storage.delete('token');
  events.get('storage')?.({
    key: 'token'
  });
  await settle();
  assert.equal(auth.currentUser.value, null);
  assert.equal(auth.isLoggedIn.value, false);
  scope.stop();
});
