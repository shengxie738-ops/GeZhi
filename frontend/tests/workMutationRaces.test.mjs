import test from 'node:test';
import assert from 'node:assert/strict';
import { effectScope, ref, nextTick } from 'vue';
import { useChat } from '../js/hooks/useChat.js';
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
  const events = new Map();
  const storage = new Map([['token', 'alice-token']]);
  globalThis.localStorage = {
    getItem: k => storage.get(k) ?? null,
    setItem: (k, v) => storage.set(k, String(v)),
    removeItem: k => storage.delete(k)
  };
  globalThis.window = {
    localStorage,
    location: {
      hostname: 'localhost'
    },
    dispatchEvent() {},
    addEventListener: (name, cb) => events.set(name, cb),
    removeEventListener: name => events.delete(name),
    confirm: () => true
  };
  globalThis.document = {
    querySelector: () => null
  };
  globalThis.fetch = async () => response({
    status: 'success',
    data: [],
    pagination: {
      complete: true,
      has_more: false
    }
  });
  const scope = effectScope();
  const user = ref({
    username: 'Alice'
  });
  const state = scope.run(() => useChat(user, () => {}));
  return {
    state,
    scope,
    storage,
    user,
    events
  };
}
const saved = (id, conversationId) => ({
  id: `db-${id}`,
  content: `question ${id}`,
  senderType: 'user',
  mode: 'paper',
  conversationId,
  syncState: 'saved'
});
test('read started during clear cannot resurrect successfully deleted history', async () => {
  const {
    state,
    scope
  } = setup();
  await settle();
  state.agentMode.value = 'paper';
  state.modeMessageBuckets.value.paper = [saved(9, 'task9')];
  const deletion = deferred(),
    reading = deferred();
  globalThis.fetch = async (url, o) => o?.method === 'DELETE' ? deletion.promise : reading.promise;
  const clearing = state.clearChatHistory('paper');
  await settle();
  const loading = state.loadChatHistory('paper');
  await settle();
  deletion.resolve(response({
    status: 'success'
  }));
  assert.equal(await clearing, true);
  assert.equal(state.modeMessageBuckets.value.paper.length, 0);
  reading.resolve(response({
    status: 'success',
    data: [{
      id: 9,
      content: 'question 9',
      role: 'user',
      agent_mode: 'paper',
      conversation_id: 'task9'
    }],
    pagination: {
      complete: true,
      has_more: false,
      snapshot_max_id: 9
    }
  }));
  await loading;
  assert.equal(state.modeMessageBuckets.value.paper.length, 0);
  scope.stop();
});
test('retry cannot issue a save after clear dispatches DELETE', async () => {
  const {
    state,
    scope
  } = setup();
  await settle();
  state.agentMode.value = 'paper';
  globalThis.fetch = async () => response({
    status: 'error',
    message: 'offline'
  });
  await state.recordPaperSearchWork('old topic', {
    results: [],
    status: 'empty'
  });
  const id = state.modeMessageBuckets.value.paper[0].conversationId;
  assert.equal(state.paperWorkSyncStatus.value.state, 'failed');
  const deletion = deferred(),
    batch = deferred(),
    calls = [];
  globalThis.fetch = async (url, o) => {
    calls.push({
      url: String(url),
      method: o?.method
    });
    return o?.method === 'DELETE' ? deletion.promise : batch.promise;
  };
  const clearing = state.clearChatHistory('paper');
  await settle();
  assert.equal(state.historyMutating.value, true);
  const retry = state.retryPaperWorkSync(id);
  await settle();
  assert.ok(!calls.some(x => x.url.endsWith('/chat/history/batch')));
  deletion.resolve(response({
    status: 'success'
  }));
  await clearing;
  batch.resolve(response({
    status: 'success',
    data: [{
      id: 101
    }, {
      id: 102
    }]
  }));
  assert.equal(await retry, false);
  scope.stop();
});
test('return to latest paper task selects its transcript', async () => {
  const {
    state,
    scope
  } = setup();
  await settle();
  state.agentMode.value = 'paper';
  state.paperActiveTab.value = 'dialog';
  state.modeMessageBuckets.value.paper = [saved(1, 'older'), saved(2, 'latest')];
  state.activeConversationId.value = 'older';
  assert.equal(state.isViewingHistory.value, true);
  await state.backToCurrentConversation();
  assert.equal(state.sidebarActiveConversationId.value, 'latest');
  assert.equal(state.activeConversationMessages.value.length, 1);
  assert.equal(state.activeConversation.value.id, 'latest');
  scope.stop();
});
test('token rotation releases completed stream thinking state', async () => {
  const {
    state,
    scope,
    storage
  } = setup();
  await settle();
  state.agentMode.value = 'paper';
  const stream = deferred();
  globalThis.fetch = async () => stream.promise;
  const sending = state.sendMessage('question');
  assert.ok(state.thinkingAgent.value);
  storage.set('token', 'renewed-alice-token');
  stream.resolve({
    ok: true,
    body: new ReadableStream({
      start(c) {
        c.close();
      }
    })
  });
  assert.equal(await sending, false);
  assert.equal(state.thinkingAgent.value, null);
  scope.stop();
});
test('selecting older history preserves latest task ordering', async () => {
  const {
    state,
    scope
  } = setup();
  await settle();
  state.agentMode.value = 'paper';
  state.modeMessageBuckets.value.paper = [saved(1, 'older'), saved(2, 'latest')];
  globalThis.fetch = async () => response({
    status: 'success',
    data: [{
      id: 1,
      content: 'question 1',
      role: 'user',
      agent_mode: 'paper',
      conversation_id: 'older'
    }],
    pagination: {
      complete: true,
      has_more: false,
      snapshot_max_id: 2
    }
  });
  await state.selectConversation('older');
  assert.deepEqual(state.conversationList.value.map(x => x.id), ['latest', 'older']);
  assert.equal(state.isViewingHistory.value, true);
  scope.stop();
});
test('history selection during task deletion cannot resurrect deleted rows', async () => {
  const {
    state,
    scope
  } = setup();
  await settle();
  state.agentMode.value = 'paper';
  state.modeMessageBuckets.value.paper = [saved(9, 'task9')];
  const record = {
    id: 9,
    content: 'question 9',
    role: 'user',
    agent_mode: 'paper',
    conversation_id: 'task9'
  };
  const inventory = () => response({
    status: 'success',
    data: [record],
    pagination: {
      complete: true,
      has_more: false,
      snapshot_max_id: 9
    }
  });
  const deletion = deferred(),
    reading = deferred();
  let reads = 0;
  globalThis.fetch = async (url, o) => o?.method === 'DELETE' ? deletion.promise : ++reads === 1 ? inventory() : reading.promise;
  const removing = state.deleteConversation(state.conversationList.value[0]);
  await settle();
  const selecting = state.selectConversation('task9');
  await settle();
  deletion.resolve(response({
    status: 'success'
  }));
  assert.equal(await removing, true);
  assert.equal(state.modeMessageBuckets.value.paper.length, 0);
  reading.resolve(inventory());
  await selecting;
  assert.equal(state.modeMessageBuckets.value.paper.length, 0);
  scope.stop();
});
test('stream reset replaces partial output with saved fallback body', async () => {
  const {
    state,
    scope
  } = setup();
  await settle();
  state.agentMode.value = 'paper';
  const frames = [{
    type: 'token',
    content: 'MODEL_PARTIAL_ANSWER'
  }, {
    type: 'progress',
    content: 'fallback'
  }, {
    type: 'reset',
    content: 'FALLBACK_ONLY'
  }, {
    type: 'complete',
    history_saved: true,
    history_receipt: {
      user_message_id: 1,
      assistant_message_id: 2
    }
  }];
  globalThis.fetch = async () => ({
    ok: true,
    body: new ReadableStream({
      start(c) {
        c.enqueue(new TextEncoder().encode(frames.map(x => 'data: ' + JSON.stringify(x) + '\n\n').join('')));
        c.close();
      }
    })
  });
  await state.sendMessage('question');
  const assistant = state.modeMessageBuckets.value.paper[1];
  assert.equal(assistant.content, 'FALLBACK_ONLY');
  assert.equal(assistant.syncState, 'saved');
  scope.stop();
});
test('empty terminal saved completion renders empty assistant and suppresses fallback', async () => {
  const {
    state,
    scope
  } = setup();
  await settle();
  state.agentMode.value = 'paper';
  let calls = 0;
  globalThis.fetch = async () => {
    calls++;
    return {
      ok: true,
      body: new ReadableStream({
        start(c) {
          c.enqueue(new TextEncoder().encode('data: ' + JSON.stringify({
            type: 'complete',
            history_saved: true,
            history_receipt: {
              user_message_id: 1,
              assistant_message_id: 2
            }
          }) + '\n\n'));
          c.close();
        }
      })
    };
  };
  await state.sendMessage('question');
  const assistant = state.modeMessageBuckets.value.paper[1];
  assert.equal(assistant.content, '');
  assert.equal(assistant.syncState, 'failed');
  assert.equal(assistant.deliveryStatus, 'empty');
  assert.equal(calls, 1);
  scope.stop();
});
test('canonical terminal replaces prior tokens and failed terminal never claims saved or replays', async () => {
  for (const delivery of ['complete', 'failed', 'empty']) {
    const {
      state,
      scope
    } = setup();
    await settle();
    state.agentMode.value = 'paper';
    let calls = 0;
    const canonical = delivery === 'empty' ? '' : 'canonical body';
    globalThis.fetch = async () => {
      calls++;
      return {
        ok: true,
        body: new ReadableStream({
          start(c) {
            c.enqueue(new TextEncoder().encode([{
              type: 'token',
              content: 'partial'
            }, {
              type: 'complete',
              content: canonical,
              delivery_status: delivery,
              history_saved: true,
              history_receipt: {
                user_message_id: 1,
                assistant_message_id: 2
              }
            }].map(x => `data: ${JSON.stringify(x)}\n\n`).join('')));
            c.close();
          }
        })
      };
    };
    await state.sendMessage('question');
    const assistant = state.modeMessageBuckets.value.paper[1];
    assert.equal(assistant.content, canonical);
    assert.equal(assistant.syncState, delivery === 'complete' ? 'saved' : 'failed');
    assert.equal(calls, 1);
    scope.stop();
  }
});
test('token storage event immediately releases pending send without letting its completion clear a newer send', async () => {
  const {
    state,
    scope,
    storage,
    events
  } = setup();
  await settle();
  state.agentMode.value = 'paper';
  const old = deferred(),
    fresh = deferred();
  let calls = 0;
  globalThis.fetch = async () => ++calls === 1 ? old.promise : fresh.promise;
  const first = state.sendMessage('first');
  storage.set('token', 'new-token');
  events.get('storage')?.({
    key: 'token'
  });
  assert.equal(state.thinkingAgent.value, null);
  const second = state.sendMessage('second');
  assert.ok(state.thinkingAgent.value);
  old.resolve({
    ok: true,
    body: new ReadableStream({
      start(c) {
        c.close();
      }
    })
  });
  await first;
  assert.ok(state.thinkingAgent.value);
  fresh.resolve({
    ok: true,
    body: new ReadableStream({
      start(c) {
        c.enqueue(new TextEncoder().encode('data: {"type":"complete","content":"new answer","history_saved":false}\n\n'));
        c.close();
      }
    })
  });
  await second;
  assert.equal(state.thinkingAgent.value, null);
  scope.stop();
});
test('task recency follows latest dated activity rather than bucket first occurrence', async () => {
  const {
    state,
    scope
  } = setup();
  await settle();
  state.agentMode.value = 'paper';
  state.modeMessageBuckets.value.paper = [{
    ...saved(1, 'older'),
    createdAt: '2026-01-01T10:00:00Z'
  }, {
    ...saved(2, 'latest'),
    createdAt: '2026-01-02T10:00:00Z'
  }, {
    ...saved(3, 'older'),
    createdAt: '2026-01-03T10:00:00Z'
  }];
  assert.deepEqual(state.conversationList.value.map(c => c.id), ['older', 'latest']);
  scope.stop();
});
test('failed delete retains records and releases write blocking', async () => {
  const {
    state,
    scope
  } = setup();
  await settle();
  state.agentMode.value = 'paper';
  state.modeMessageBuckets.value.paper = [saved(9, 'task9')];
  globalThis.fetch = async (url, o) => o?.method === 'DELETE' ? response({
    status: 'error',
    message: 'offline'
  }) : response({
    status: 'success',
    data: [{
      id: 9,
      content: 'question 9',
      role: 'user',
      agent_mode: 'paper',
      conversation_id: 'task9'
    }],
    pagination: {
      complete: true
    }
  });
  assert.equal(await state.deleteConversation(state.conversationList.value[0]), false);
  assert.equal(state.modeMessageBuckets.value.paper.length, 1);
  assert.equal(state.historyMutating.value, false);
  scope.stop();
});
test('actual main latest-navigation wrapper restores latest paper snapshot', async () => {
  const {
    readFile
  } = await import('node:fs/promises');
  const {
    usePlugins
  } = await import('../js/hooks/usePlugins.js');
  const {
    resolvePaperHistoryState
  } = await import('../js/utils/conversations.js');
  const {
    state,
    scope,
    user
  } = setup();
  await settle();
  state.agentMode.value = 'paper';
  state.modeMessageBuckets.value.paper = [saved(1, 'older'), {
    ...saved(2, 'latest'),
    paperSearchSnapshot: {
      query: 'latest query',
      results: [{
        id: 'latest-paper',
        title: 'Latest paper'
      }],
      summary: {
        totalAfterMerge: 1
      }
    }
  }];
  state.activeConversationId.value = 'older';
  const plugins = scope.run(() => usePlugins(user, () => {}, state.inputText));
  const main = await readFile(new URL('../js/main.js', import.meta.url), 'utf8');
  const restore = main.match(/const restoreActivePaperTask = \(\) => \{[\s\S]*?\n        \};/)[0];
  const back = main.match(/const handleBackToCurrentConversation = async \(\) => \{[\s\S]*?\n        \};/)[0];
  assert.match(main, /backToCurrentConversation: handleBackToCurrentConversation/);
  await new Function('chat', 'pluginsState', 'resolvePaperHistoryState', `${restore}\n${back}\nreturn handleBackToCurrentConversation();`)(state, plugins, resolvePaperHistoryState);
  assert.equal(state.activeConversation.value.id, 'latest');
  assert.equal(plugins.paperSearchResults.value[0].id, 'latest-paper');
  scope.stop();
});
test('adding an older server timestamp on scoped refresh cannot promote it above newer undated database rows', async () => {
  const {
    state,
    scope
  } = setup();
  await settle();
  state.agentMode.value = 'paper';
  state.modeMessageBuckets.value.paper = [saved(1, 'older'), saved(2, 'latest')];
  globalThis.fetch = async () => response({
    status: 'success',
    data: [{
      id: 1,
      content: 'question 1',
      role: 'user',
      agent_mode: 'paper',
      conversation_id: 'older',
      created_at: '2026-01-01 10:00:00'
    }],
    pagination: {
      complete: true
    }
  });
  await state.selectConversation('older');
  assert.deepEqual(state.conversationList.value.map(c => c.id), ['latest', 'older']);
  assert.equal(state.isViewingHistory.value, true);
  scope.stop();
});
