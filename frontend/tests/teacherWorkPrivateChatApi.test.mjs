import test from 'node:test';
import assert from 'node:assert/strict';
import * as transport from '../js/api/teacherWork.js';

// Finite, offline transport fixtures. fetch is replaced only at the HTTP boundary.
const taskId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const otherTask = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const runId = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const otherRun = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
const messageId = 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee';
const laterMessage = 'ffffffff-ffff-4fff-8fff-ffffffffffff';
const instant = '2026-10-06T00:00:00+00:00';
const envelope = data => ({ code: 200, message: 'ok', data });
const response = (status, body) => ({ status, text: async () => typeof body === 'string' ? body : JSON.stringify(body) });
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const tick = async () => { for (let index = 0; index < 5; index++) await Promise.resolve(); };
const body = () => ({ kind: 'chat', input_revision: 1, skill_ref: null,
    payload: { text: '  请解释循环\n保留输入格式  ', client_message_key: 'chat-key-one' } });
const run = () => ({ run_id: runId, task_id: taskId, kind: 'chat', input_revision: 1, stage: 'PENDING',
    attempt: 1, provider_call_count: 0, deadline: instant, cancelled_at: null, error_code: null });
const message = () => ({ message_id: messageId, task_id: taskId, role: 'user', plain_text: '请解释循环', run_id: runId,
    client_message_key: 'chat-key-one', result_type: null, result_refs: [], omitted_context: null, created_at: instant });
const history = () => ({ task_id: taskId, messages: [message()], has_more: false, next_before: null });
const chatFacts = () => ({ send: true, history: true, read_run: true, cancel: true,
    provider_configured: true, external_provider_verified: false });
const facts = () => ({ chat: true, task_write: true, generate: false, storage: false, structural_preview: false,
    rendered_preview: false, publish: false,
    reasons: { chat: 'enabled,ai_ready', rendered_preview: 'rendered_preview_unsupported', publish: 'private_teacher_work_only' },
    private_tasks: { create: true, read: true, update: true }, private_chat: chatFacts() });
const validate = name => { assert.equal(typeof transport[name], 'function', name + ' must validate actual private-chat DTOs'); return transport[name]; };
const apiFor = (status = 200, value = envelope(run()), overrides = {}) => transport.createTeacherWorkApi({
    getToken: () => 'synthetic-session', fetchImpl: async () => response(status, value), ...overrides });
const requiredApi = (...args) => { const api = apiFor(...args); for (const name of ['sendMessage', 'listMessages', 'getRun', 'cancelRun'])
    assert.equal(typeof api[name], 'function', name + ' transport is required'); return api; };
const failure = (reason, status) => caught => {
    assert.equal(caught.name, 'TeacherWorkError'); assert.equal(caught.reason, reason);
    if (status !== undefined) assert.equal(caught.status, status);
    assert.doesNotMatch(caught.message, /secret|OWNER_BUSY|\/var\/|owner_subject|prompt|synthetic-session/);
    assert.doesNotMatch(JSON.stringify(caught), /secret|OWNER_BUSY|\/var\/|owner_subject|prompt|synthetic-session/);
    assert.equal(Object.hasOwn(caught, 'cause'), false); return true;
};

test('private-chat capabilities retain private CRUD and decode older servers closed', async () => {
    assert.deepEqual((await apiFor(200, envelope(facts())).getCapabilities()).private_chat, chatFacts());
    for (const omitPrivateTasks of [false, true]) {
        const old = facts(); delete old.private_chat; if (omitPrivateTasks) delete old.private_tasks;
        const decoded = await apiFor(200, envelope(old)).getCapabilities();
        assert.deepEqual(decoded.private_chat, { send: false, history: false, read_run: false, cancel: false,
            provider_configured: false, external_provider_verified: false });
        assert.deepEqual(decoded.private_tasks, { create: !omitPrivateTasks, read: !omitPrivateTasks, update: !omitPrivateTasks });
    }
});

test('private-chat capability reason codes support enabled and explicitly unavailable states', async () => {
    for (const reason of ['private_chat_disabled', 'chat_runtime_unavailable', 'enabled,ai_ready']) {
        const data = facts(); data.reasons.chat = reason;
        assert.equal((await apiFor(200, envelope(data)).getCapabilities()).reasons.chat, reason);
    }
});

test('private-chat capability shape and external-provider verification are closed-world facts', async () => {
    for (const mutation of [data => { data.private_chat.owner_subject = 'secret'; },
        data => { delete data.private_chat.cancel; }, data => { data.private_chat.send = 'true'; },
        data => { data.private_chat.external_provider_verified = true; }, data => { data.private_chat = null; },
        data => { data.private_chat.send = false; }, data => { data.chat = false; },
        data => { data.private_chat.provider_configured = false; },
        data => { data.reasons.chat = 'unrecognized'; }, data => { data.private_tasks.update = 'true'; }]) {
        const data = facts(); mutation(data);
        await assert.rejects(apiFor(200, envelope(data)).getCapabilities(), failure('invalid_response'));
    }
});

test('send body validator preserves exact teacher text and clones allowed payload only', () => {
    const check = validate('validatePrivateChatBody'), input = body(), decoded = check(input);
    assert.deepEqual(decoded, input); assert.notEqual(decoded, input); assert.notEqual(decoded.payload, input.payload);
    input.payload.text = 'changed'; assert.equal(decoded.payload.text, body().payload.text);
    assert.equal(check({ ...body(), payload: { text: '🧑'.repeat(4000), client_message_key: 'k'.repeat(128) } }).payload.text.length, 8000);
});

test('send body rejects unsupported kind skill invalid revision controls and owner/provider metadata', () => {
    const check = validate('validatePrivateChatBody');
    for (const mutation of [value => { value.kind = 'outline'; }, value => { value.input_revision = 0; },
        value => { value.input_revision = 1.5; }, value => { value.input_revision = Number.MAX_SAFE_INTEGER + 1; },
        value => { value.skill_ref = taskId; }, value => { delete value.skill_ref; },
        value => { value.payload.text = ' \n\t'; }, value => { value.payload.text = 'x'.repeat(4001); },
        value => { value.payload.client_message_key = ''; }, value => { value.payload.client_message_key = 'k'.repeat(129); },
        value => { value.payload.client_message_key = 'key\nsecret'; }, value => { value.payload.client_message_key = 'key\u200b'; },
        value => { value.payload.owner_subject = 'secret'; }, value => { value.owner_subject = 'secret'; },
        value => { value.model = 'external-provider'; }, value => { value.payload = []; }]) {
        const input = body(); mutation(input); assert.throws(() => check(input), failure('invalid_input'));
    }
});

test('run validator accepts only chat lifecycle states and returns an isolated DTO', () => {
    const check = validate('validatePrivateChatRun');
    for (const stage of ['PENDING', 'CHAT_RUNNING', 'COMPLETE', 'FAILED', 'CANCELLED', 'INTERRUPTED']) {
        const input = { ...run(), stage, attempt: 2, provider_call_count: 3,
            cancelled_at: stage === 'CANCELLED' ? instant : null, error_code: stage === 'FAILED' ? 'PROVIDER_UNAVAILABLE' : null };
        const decoded = check(input); assert.deepEqual(decoded, input); assert.notEqual(decoded, input);
    }
});

test('run validator rejects extra owner paths and malformed bounded lifecycle fields', () => {
    const check = validate('validatePrivateChatRun');
    for (const mutation of [value => { value.owner_subject = 'secret'; }, value => { value.run_id = '../secret'; },
        value => { value.task_id = null; }, value => { value.kind = 'generate'; }, value => { value.stage = 'RUNNING'; },
        value => { value.input_revision = 0; }, value => { value.attempt = 0; }, value => { value.attempt = 3; },
        value => { value.provider_call_count = -1; }, value => { value.provider_call_count = 4; },
        value => { value.deadline = null; }, value => { value.deadline = '2026-10-06T00:00:00+08:00'; },
        value => { value.cancelled_at = 'not-a-date'; }, value => { value.error_code = 'secret raw error'; },
        value => { value.error_code = 'A'.repeat(65); }, value => { delete value.error_code; }]) {
        const input = run(); mutation(input); assert.throws(() => check(input), failure('invalid_response'));
    }
});

test('history validator accepts nullable metadata and clones ascending plain-text message DTOs', () => {
    const check = validate('validatePrivateChatHistory');
    for (const [role, resultType] of [['user', null], ['assistant', null], ['tool', null],
        ...['answer', 'outline_proposal', 'revision_proposal', 'skill_suggestion'].map(type => ['assistant', type])]) {
        const input = { ...history(), messages: [{ ...message(), role, plain_text: '<script>plain text only</script>', run_id: null,
            client_message_key: null, result_type: resultType, result_refs: [otherRun], omitted_context: null }],
            has_more: true, next_before: messageId };
        if (resultType !== null) Object.assign(input.messages[0], { run_id: runId, omitted_context: true });
        const decoded = check(input); assert.deepEqual(decoded, input); assert.notEqual(decoded.messages, input.messages);
        assert.notEqual(decoded.messages[0], input.messages[0]); assert.notEqual(decoded.messages[0].result_refs, input.messages[0].result_refs);
    }
    assert.deepEqual(check({ task_id: taskId, messages: [], has_more: false, next_before: null }).messages, []);
    assert.deepEqual(check({ ...history(), messages: [message(), { ...message(), message_id: laterMessage }] }).messages.map(item => item.message_id), [messageId, laterMessage]);
});

test('history validator rejects out-of-order duplicates task leakage and malformed message metadata', () => {
    const check = validate('validatePrivateChatHistory');
    for (const mutation of [value => { value.owner_subject = 'secret'; }, value => { value.has_more = 'false'; },
        value => { value.next_before = '../secret'; }, value => { value.messages[0].owner_subject = 'secret'; },
        value => { value.messages[0].task_id = otherTask; }, value => { value.messages[0].message_id = 'not-an-id'; },
        value => { value.messages[0].role = 'system'; }, value => { value.messages[0].plain_text = null; },
        value => { value.messages[0].plain_text = 'x'.repeat(32769); }, value => { value.messages[0].run_id = 'bad'; },
        value => { value.messages[0].client_message_key = 'bad\nkey'; }, value => { value.messages[0].result_type = 'pptx'; },
        value => { value.messages[0].result_refs = ['private/path']; }, value => { value.messages[0].result_refs = Array(11).fill(runId); },
        value => { value.messages[0].omitted_context = 'false'; }, value => { value.messages[0].created_at = null; },
        value => { delete value.messages[0].result_type; }, value => { value.messages.push(message()); },
        value => { value.messages = [{ ...message(), message_id: laterMessage }, message()]; },
        value => { value.messages = [{ ...message(), created_at: '2026-10-07T00:00:00Z' }, { ...message(), message_id: laterMessage }]; }]) {
        const input = history(); mutation(input); assert.throws(() => check(input), failure('invalid_response'));
    }
});

test('private chat routes send history read and cancel using only bearer token and explicit idempotency', async () => {
    const calls = [], controller = new AbortController(), api = requiredApi(200, undefined, {
        fetchImpl: async (url, options) => { calls.push({ url, options }); return response(200, envelope(options.method === 'GET' && url.includes('/messages?') ? history() : run())); }
    });
    assert.deepEqual(await api.sendMessage(taskId, body(), { idempotencyKey: 'request-key', signal: controller.signal }), run());
    assert.deepEqual(await api.listMessages(taskId, { signal: controller.signal }), history());
    assert.deepEqual(await api.getRun(taskId, runId, { signal: controller.signal }), run());
    assert.deepEqual(await api.cancelRun(taskId, runId, { signal: controller.signal }), run());
    assert.deepEqual(calls.map(({ options }) => options.method), ['POST', 'GET', 'GET', 'POST']);
    assert.ok(calls[0].url.endsWith(`/api/teacher/work/tasks/${taskId}/messages`));
    assert.ok(calls[1].url.endsWith(`/api/teacher/work/tasks/${taskId}/messages?limit=20`));
    assert.ok(calls[2].url.endsWith(`/api/teacher/work/tasks/${taskId}/runs/${runId}`));
    assert.ok(calls[3].url.endsWith(`/api/teacher/work/tasks/${taskId}/runs/${runId}/cancel`));
    assert.deepEqual(JSON.parse(calls[0].options.body), body()); assert.deepEqual(JSON.parse(calls[3].options.body), {});
    assert.equal(calls[1].options.body, undefined); assert.equal(calls[2].options.body, undefined);
    for (const { options } of calls) {
        assert.equal(options.headers.Authorization, 'Bearer synthetic-session'); assert.equal(options.cache, 'no-store');
        assert.equal(options.signal, controller.signal); assert.equal(options.credentials, undefined);
        assert.deepEqual(Object.keys(options.headers).sort(), ['Authorization', 'Content-Type', ...(options.method === 'POST' && options.body !== '{}' ? ['Idempotency-Key'] : [])].sort());
    }
    assert.equal(calls[0].options.headers['Idempotency-Key'], 'request-key');
});

test('history pagination defaults to20 and encodes only bounded explicit limit and UUID cursor', async () => {
    const calls = [], api = requiredApi(200, undefined, { fetchImpl: async (url, options) => { calls.push({ url, options }); return response(200, envelope(history())); } });
    await api.listMessages(taskId, { limit: 1, before: messageId });
    const request = new URL(calls[0].url); assert.equal(request.searchParams.get('limit'), '1');
    assert.equal(request.searchParams.get('before'), messageId); assert.equal(request.searchParams.size, 2);
    for (const options of [{ limit: 0 }, { limit: 51 }, { limit: 1.5 }, { before: 'private/path' }, { before: null },
        { owner_subject: 'secret' }, { idempotencyKey: 'not-for-read' }, { signal: {} }])
        await assert.rejects(api.listMessages(taskId, options), failure('invalid_input'));
    assert.equal(calls.length, 1);
});

test('chat validates task run send options and body before fetching', async () => {
    let calls = 0; const api = requiredApi(200, envelope(run()), { fetchImpl: async () => { calls++; return response(200, envelope(run())); } });
    for (const invoke of [() => api.sendMessage('../secret', body(), { idempotencyKey: 'key' }),
        () => api.sendMessage(taskId, { ...body(), owner_subject: 'secret' }, { idempotencyKey: 'key' }),
        () => api.sendMessage(taskId, body()), () => api.sendMessage(taskId, body(), { idempotencyKey: 'key\nsecret' }),
        () => api.sendMessage(taskId, body(), { idempotencyKey: 'key', owner_subject: 'secret' }),
        () => api.getRun(taskId, 'secret'), () => api.getRun('secret', runId), () => api.getRun(taskId, runId, { before: messageId }),
        () => api.cancelRun(taskId, 'secret'), () => api.cancelRun(taskId, runId, { idempotencyKey: 'key' })])
        await assert.rejects(invoke(), failure('invalid_input'));
    assert.equal(calls, 0);
});

test('chat responses bind to the requested task run and send revision', async () => {
    for (const [method, dto, invoke] of [
        ['sendMessage', { ...run(), task_id: otherTask }, api => api.sendMessage(taskId, body(), { idempotencyKey: 'key' })],
        ['sendMessage', { ...run(), input_revision: 2 }, api => api.sendMessage(taskId, body(), { idempotencyKey: 'key' })],
        ['listMessages', { ...history(), task_id: otherTask, messages: [] }, api => api.listMessages(taskId)],
        ['getRun', { ...run(), task_id: otherTask }, api => api.getRun(taskId, runId)],
        ['getRun', { ...run(), run_id: otherRun }, api => api.getRun(taskId, runId)],
        ['cancelRun', { ...run(), run_id: otherRun }, api => api.cancelRun(taskId, runId)]]) {
        const api = requiredApi(200, envelope(dto)); await assert.rejects(invoke(api), failure('invalid_response'), method);
    }
});

test('history cannot return more messages than requested', async () => {
    const dto = { ...history(), messages: [message(), { ...message(), message_id: laterMessage }] };
    await assert.rejects(requiredApi(200, envelope(dto)).listMessages(taskId, { limit: 1 }), failure('invalid_response'));
});

test('chat success requires HTTP200 and exact ok success envelope without raw diagnostics', async () => {
    for (const [status, value] of [[201, envelope(run())], [202, envelope(run())], [204, ''], [200, 'secret /var/private prompt'],
        [200, { ...envelope(run()), owner_subject: 'secret' }], [200, { ...envelope(run()), code: '200' }],
        [200, { ...envelope(run()), message: 'accepted' }], [200, { ...envelope(run()), data: { ...run(), raw_response: 'secret' } }]]) {
        await assert.rejects(requiredApi(status, value).sendMessage(taskId, body(), { idempotencyKey: 'key' }), failure('invalid_response', status));
    }
});

test('chat409 distinguishes revision idempotency and owner capacity conflicts without retrying', async () => {
    for (const [code, reason] of [['REVISION_CONFLICT', 'revision_conflict'], ['IDEMPOTENCY_CONFLICT', 'idempotency_conflict'], ['OWNER_BUSY', 'owner_busy']]) {
        let calls = 0; const api = requiredApi(409, undefined, { fetchImpl: async () => { calls++;
            return response(409, { code: 409, message: code, data: null }); } });
        await assert.rejects(api.sendMessage(taskId, body(), { idempotencyKey: 'key' }), failure(reason, 409)); assert.equal(calls, 1);
    }
});

test('unknown or malformed chat409 never implies a revision or idempotency conflict', async () => {
    for (const value of [{ code: 409, message: 'unknown secret /var/private', data: null }, 'REVISION_CONFLICT',
        { code: 200, message: 'REVISION_CONFLICT', data: null }, { code: 409, message: 'REVISION_CONFLICT', data: null, owner_subject: 'secret' }])
        await assert.rejects(requiredApi(409, value).sendMessage(taskId, body(), { idempotencyKey: 'key' }), failure('request_failed', 409));
});

test('chat409 inherited object property names cannot bypass the known-code allowlist', async () => {
    for (const value of ['__proto__', 'constructor', 'toString'])
        await assert.rejects(requiredApi(409, { code: 409, message: value, data: null }).sendMessage(taskId, body(), { idempotencyKey: 'key' }), failure('request_failed', 409));
});

test('history ordering respects sub-millisecond UTC instants before the UUID tiebreak', () => {
    const check = validate('validatePrivateChatHistory');
    const early = { ...message(), message_id: laterMessage, created_at: '2026-10-06T00:00:00.000001Z' };
    const late = { ...message(), created_at: '2026-10-06T00:00:00.000002+00:00' };
    assert.deepEqual(check({ ...history(), messages: [early, late] }).messages.map(item => item.message_id), [laterMessage, messageId]);
    assert.throws(() => check({ ...history(), messages: [late, early] }), failure('invalid_response'));
});

test('exported message comparator merges pages using full UTC precision and UUID tiebreak', () => {
    const compare = validate('comparePrivateChatMessages');
    const early = { ...message(), message_id: laterMessage, created_at: '2026-10-06T00:00:00.000001Z' };
    const late = { ...message(), created_at: '2026-10-06T00:00:00.000002+00:00' };
    const sameTime = { ...late, message_id: laterMessage };
    assert.deepEqual([sameTime, late, early].sort(compare), [early, late, sameTime]);
    assert.equal(compare(early, { ...early }), 0); assert.equal(compare(late, early), 1);
    assert.throws(() => compare({ ...early, created_at: 'secret' }, late), failure('invalid_response'));
});

test('classified result metadata belongs only to a linked nonblank assistant answer', () => {
    const check = validate('validatePrivateChatHistory');
    for (const changes of [{ role: 'user', result_type: 'answer', omitted_context: true },
        { role: 'tool', result_type: 'answer', omitted_context: false },
        { role: 'assistant', result_type: 'answer', omitted_context: null },
        { role: 'assistant', result_type: null, omitted_context: true },
        { role: 'assistant', result_type: 'answer', omitted_context: true, run_id: null },
        { role: 'assistant', result_type: 'answer', omitted_context: false, plain_text: ' \n ' }])
        assert.throws(() => check({ ...history(), messages: [{ ...message(), ...changes }] }), failure('invalid_response'));
});

test('history cursor agrees with has_more and the oldest ascending message', () => {
    const check = validate('validatePrivateChatHistory');
    for (const input of [{ ...history(), has_more: true }, { ...history(), has_more: true, next_before: laterMessage },
        { ...history(), next_before: messageId }, { task_id: taskId, messages: [], has_more: true, next_before: messageId }])
        assert.throws(() => check(input), failure('invalid_response'));
});

test('run and history UTC instants cannot normalize impossible calendar dates', () => {
    const runCheck = validate('validatePrivateChatRun'), historyCheck = validate('validatePrivateChatHistory');
    for (const invalid of ['2026-02-31T00:00:00Z', '2026-10-06T24:00:00Z']) {
        assert.throws(() => runCheck({ ...run(), deadline: invalid }), failure('invalid_response'));
        assert.throws(() => historyCheck({ ...history(), messages: [{ ...message(), created_at: invalid }] }), failure('invalid_response'));
    }
});

test('chat maps body input capacity unavailable errors without retrying or exposing backend content', async () => {
    for (const [status, reason] of [[400, 'invalid_input'], [401, 'auth_required'], [403, 'teacher_required'], [404, 'task_not_found'],
        [413, 'request_too_large'], [422, 'invalid_input'], [429, 'capacity_unavailable'], [503, 'TEACHER_WORK_UNAVAILABLE'], [500, 'request_failed']]) {
        let calls = 0, expired = 0; const api = requiredApi(status, undefined, { dispatchAuthExpired: () => expired++,
            fetchImpl: async () => { calls++; return response(status, { code: status, message: 'secret /var/path prompt', data: { owner_subject: 'secret' } }); } });
        await assert.rejects(api.sendMessage(taskId, body(), { idempotencyKey: 'key' }), failure(reason, status));
        assert.equal(calls, 1); assert.equal(expired, status === 401 ? 1 : 0);
    }
});

test('chat rejects missing credentials before sending and sanitizes network failures', async () => {
    let calls = 0; const api = requiredApi(200, undefined, { getToken: () => '', fetchImpl: async () => { calls++; return response(200, envelope(run())); } });
    await assert.rejects(api.sendMessage(taskId, body(), { idempotencyKey: 'key' }), failure('auth_required', 401)); assert.equal(calls, 0);
    const failed = requiredApi(200, undefined, { fetchImpl: async () => { throw new Error('secret /var/path prompt'); } });
    await assert.rejects(failed.sendMessage(taskId, body(), { idempotencyKey: 'key' }), failure('network_error'));
});

test('private-chat transport fences token replacement and abort during fetch and async response body', async () => {
    for (const method of ['sendMessage', 'listMessages', 'getRun', 'cancelRun'])
        for (const phase of ['fetch', 'body']) for (const changed of ['token', 'abort']) for (const status of [200, 401]) {
            let token = 'old', expired = 0; const pending = deferred(), controller = new AbortController();
            const success = method === 'listMessages' ? history() : run();
            const api = requiredApi(200, undefined, { getToken: () => token, dispatchAuthExpired: () => expired++,
                fetchImpl: phase === 'fetch' ? () => pending.promise : async () => ({ status, text: () => pending.promise }) });
            const options = { signal: controller.signal };
            const result = method === 'sendMessage' ? api.sendMessage(taskId, body(), { ...options, idempotencyKey: 'key' }) :
                method === 'listMessages' ? api.listMessages(taskId, options) : api[method](taskId, runId, options);
            await tick(); if (changed === 'token') token = 'new'; else controller.abort();
            pending.resolve(phase === 'fetch' ? response(status, envelope(success)) : JSON.stringify(envelope(success)));
            await assert.rejects(result, failure('request_aborted')); assert.equal(expired, 0);
        }
});

test('already-aborted private chat request cannot reach fetch', async () => {
    let calls = 0; const controller = new AbortController(); controller.abort();
    const api = requiredApi(200, undefined, { fetchImpl: async () => { calls++; return response(200, envelope(run())); } });
    await assert.rejects(api.sendMessage(taskId, body(), { idempotencyKey: 'key', signal: controller.signal }), failure('request_aborted'));
    assert.equal(calls, 0);
});

test('private CRUD revision and creation idempotency409 behavior is preserved', async () => {
    const api = requiredApi(409, { code: 409, message: 'secret', data: null });
    const creation = { title: '循环', topic: '循环', audience: '一年级', resource_ids: ['resource'], scope: 'private' };
    await assert.rejects(api.createTask(creation, { idempotencyKey: 'key' }), failure('idempotency_conflict', 409));
    await assert.rejects(api.updateWorking(taskId, { expected_revision: 1, changes: { requirements: 'new' } }), failure('revision_conflict', 409));
});

test('history DTO supports maximum message bounds while transport accepts short whole byte-budgeted pages', async () => {
    const long = '🧑'.repeat(32768), messages = Array.from({ length: 50 }, (_value, index) => ({ ...message(),
        message_id: `${String(index + 1).padStart(8, '0')}-0000-4000-8000-000000000000`, plain_text: long,
        run_id: null, client_message_key: null }));
    const full = { task_id: taskId, messages, has_more: false, next_before: null };
    const decoded = validate('validatePrivateChatHistory')(full);
    assert.equal(decoded.messages.length, 50); assert.ok(decoded.messages.every(value => value.plain_text === long));
    const small = { task_id: taskId, messages: messages.slice(49), has_more: true, next_before: messages[49].message_id };
    const page = await requiredApi(200, envelope(small)).listMessages(taskId, { limit: 50 });
    assert.equal(page.messages.length, 1); assert.equal(page.messages[0].plain_text, long); assert.equal(page.has_more, true);
    assert.equal(page.next_before, messages[49].message_id);
});

test('history response aggregate stays bounded even for valid JSON with oversized whitespace padding', async () => {
    const raw = JSON.stringify(envelope(history())) + ' '.repeat(4 * 1024 * 1024);
    await assert.rejects(requiredApi(200, raw).listMessages(taskId), failure('invalid_response'));
});


test('history transport enforces the262144-byte UTF8 envelope budget rather than UTF16 units', async () => {
    const messageA = { ...message(), plain_text: '🧑'.repeat(32768) }, messageB = { ...messageA, message_id: laterMessage };
    const above = envelope({ task_id: taskId, messages: [messageA, messageB], has_more: false, next_before: null });
    const raw = JSON.stringify(above); assert.ok(raw.length < 262144); assert.ok(new TextEncoder().encode(raw).length > 262144);
    await assert.rejects(requiredApi(200, raw).listMessages(taskId), failure('invalid_response'));
    const below = envelope({ task_id: taskId, messages: [messageB], has_more: true, next_before: laterMessage });
    assert.ok(new TextEncoder().encode(JSON.stringify(below)).length < 262144);
    const whole = await requiredApi(200, below).listMessages(taskId); assert.equal(whole.messages[0].plain_text, messageB.plain_text);
    assert.equal(whole.has_more, true); assert.equal(whole.next_before, laterMessage);
});

test('history UTF8 aggregate budget accepts its inclusive boundary and rejects the next byte', async () => {
    const compact = JSON.stringify(envelope(history())), length = new TextEncoder().encode(compact).length;
    const exact = compact + ' '.repeat(262144 - length);
    assert.equal(new TextEncoder().encode(exact).length, 262144);
    assert.deepEqual(await requiredApi(200, exact).listMessages(taskId), history());
    await assert.rejects(requiredApi(200, exact + ' ').listMessages(taskId), failure('invalid_response'));
});

test('frozen backend admission conflict codes map revision message-key and owner lease conflicts precisely', async () => {
    // Exact WorkRunError literals from private_chat.py/runs.py/repositories/teacher_work.py.
    for (const [message, reason] of [['STALE_INPUT_REVISION', 'revision_conflict'], ['MESSAGE_KEY_CONFLICT', 'idempotency_conflict'], ['OWNER_RUN_BUSY', 'owner_busy']])
        await assert.rejects(requiredApi(409, { code: 409, message, data: null }).sendMessage(taskId, body(), { idempotencyKey: 'send' }), failure(reason, 409));
});
