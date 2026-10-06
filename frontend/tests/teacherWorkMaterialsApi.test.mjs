import test from 'node:test';
import assert from 'node:assert/strict';
import * as materials from '../js/api/teacherWorkMaterials.js';
import { createTeacherWorkApi } from '../js/api/teacherWork.js';
import { materialLesson, materialSlide, materialsSaveBody, materialsApprovalBody, materialsCapabilities, materialsSnapshot,
    materialsOutlineId, materialsApprovalId, materialsTaskId, materialsDigest, materialsApproval } from './fixtures/teacherWorkMaterialsFixtures.mjs';

const failure = (reason, status) => caught => {
    assert.equal(caught.name, 'TeacherWorkError'); assert.equal(caught.reason, reason);
    if (status !== undefined) assert.equal(caught.status, status);
    assert.doesNotMatch(caught.message, /secret|owner_subject|\/var\/|synthetic-session/);
    assert.doesNotMatch(JSON.stringify(caught), /secret|owner_subject|\/var\/|synthetic-session/);
    assert.equal(Object.hasOwn(caught, 'cause'), false); return true;
};
const check = name => { assert.equal(typeof materials[name], 'function', name); return materials[name]; };

test('materials save validator clones the exact approved command and nested plain text', () => {
    const validate = check('validateMaterialsSaveBody'), input = materialsSaveBody();
    input.lesson.title = '  保留课题格式  '; input.slides[0].body = ['  保留幻灯片格式  '];
    const decoded = validate(input); assert.deepEqual(decoded, input);
    for (const [before, after] of [[input, decoded], [input.lesson, decoded.lesson], [input.lesson.teaching_flow, decoded.lesson.teaching_flow],
        [input.lesson.teaching_flow[0], decoded.lesson.teaching_flow[0]], [input.slides, decoded.slides], [input.slides[0], decoded.slides[0]],
        [input.slides[0].body, decoded.slides[0].body], [input.slides[0].evidence_refs, decoded.slides[0].evidence_refs]]) assert.notEqual(before, after);
    input.lesson.teaching_flow[0].content = 'changed'; input.slides[0].body[0] = 'changed';
    assert.equal(decoded.lesson.teaching_flow[0].content, '讲解循环条件'); assert.equal(decoded.slides[0].body[0], '  保留幻灯片格式  ');
});

test('materials content validators match schema defaults without admitting unknown nested fields', () => {
    const lesson = check('validateLessonSnapshot')({ title: 'Lesson', teaching_flow: [{ stage: 'Stage', minutes: 45, content: 'Content' }] });
    assert.deepEqual(lesson, { ...materialLesson(), title: 'Lesson', topic: '', course_name: '', audience: '', objectives: [], key_points: [],
        teaching_flow: [{ stage: 'Stage', minutes: 45, content: 'Content' }] });
    assert.deepEqual(check('validateSlideSnapshot')({ layout: 'title', title: 'Slide' }), { ...materialSlide(), layout: 'title', title: 'Slide', body: [] });
    for (const mutate of [value => { value.owner_subject = 'secret'; }, value => { value.citations = [{ name: '', page: 0, excerpt: '', resource_path: '/var/secret' }]; },
        value => { value.teaching_flow[0].handler = 'secret'; }]) {
        const value = materialLesson(); mutate(value); assert.throws(() => check('validateLessonSnapshot')(value), failure('invalid_input'));
    }
});

test('materials save rejects extra command fields and invalid strict revisions before transport', () => {
    for (const mutate of [value => { value.reviewed = true; }, value => { value.owner_subject = 'secret'; }, value => { delete value.expected_outline_revision; },
        value => { value.expected_revision = 0; }, value => { value.input_revision = '1'; }, value => { value.input_revision = true; },
        value => { value.expected_outline_revision = -1; }, value => { value.expected_outline_revision = 0.5; },
        value => { value.expected_revision = Number.MAX_SAFE_INTEGER + 1; }, value => { value.lesson = null; }, value => { value.slides = {}; }]) {
        const value = materialsSaveBody(); mutate(value); assert.throws(() => check('validateMaterialsSaveBody')(value), failure('invalid_input'));
    }
});

test('manual request arrays must contain actual items rather than holes or hidden extra metadata', () => {
    for (const mutate of [value => { value.slides = Array(6); }, value => { value.lesson.objectives = Array(1); },
        value => { value.lesson.citations = Array(1); }, value => { delete value.lesson.teaching_flow[0]; },
        value => { value.slides[0].body = Array(1); }, value => { value.slides[0].columns = Array(1); },
        value => { value.slides[0].body.owner_subject = 'secret'; }]) {
        const value = materialsSaveBody(); mutate(value); assert.throws(() => check('validateMaterialsSaveBody')(value), failure('invalid_input'));
    }
});

test('lesson validator enforces scalar counts lists citations and exact teaching-flow duration', () => {
    for (const mutate of [value => { value.title = ''; }, value => { value.title = '字'.repeat(201); }, value => { value.duration_minutes = 601; },
        value => { value.duration_minutes = 44; }, value => { value.teaching_flow = []; }, value => { value.teaching_flow[0].minutes = true; },
        value => { value.teaching_flow[0].content = ''; }, value => { value.teaching_flow = Array(21).fill(value.teaching_flow[0]); },
        value => { value.objectives = Array(21).fill('a'); }, value => { value.objectives = ['']; }, value => { value.questions = ['字'.repeat(2001)]; },
        value => { value.summary = '字'.repeat(8001); }, value => { value.citations = Array(21).fill({ name: '', page: 0, excerpt: '' }); },
        value => { value.citations = [{ name: '', page: -1, excerpt: '' }]; }, value => { value.citations = [{ name: '', page: 0, excerpt: '字'.repeat(4001) }]; }]) {
        const value = materialLesson(); mutate(value); assert.throws(() => check('validateLessonSnapshot')(value), failure('invalid_input'));
    }
    assert.equal(check('validateLessonSnapshot')({ ...materialLesson(), title: '🧑'.repeat(200) }).title.length, 400);
    assert.deepEqual(check('validateLessonSnapshot')({ ...materialLesson(), citations: [{}] }).citations, [{ name: '', page: 0, excerpt: '' }]);
});

test('slide validator enforces manual layout density plain text and zero evidence refs', () => {
    for (const mutate of [value => { value.layout = 'html'; }, value => { value.title = ''; }, value => { value.title = '字'.repeat(61); },
        value => { value.body = Array(6).fill('a'); }, value => { value.body = ['字'.repeat(91)]; }, value => { value.body = Array(5).fill('字'.repeat(73)); },
        value => { value.columns = [['a'], ['b']]; }, value => { value.layout = 'two_column'; },
        value => { value.notes = '字'.repeat(1201); }, value => { value.source_note = '字'.repeat(121); },
        value => { value.title = '<h1>secret</h1>'; }, value => { value.notes = 'JavaScript :secret'; },
        value => { value.body = ['<img src="secret">']; }, value => { value.source_note = 'data:secret'; },
        value => { value.evidence_refs = ['aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa']; }, value => { value.evidence_refs = null; },
        value => { value.file_path = '/var/secret'; }]) {
        const value = materialSlide(); mutate(value); assert.throws(() => check('validateSlideSnapshot')(value), failure('invalid_input'));
    }
    const two = { ...materialSlide(), layout: 'two_column', body: [], columns: [['left'], ['right']] };
    assert.deepEqual(check('validateSlideSnapshot')(two), two);
    assert.equal(check('validateSlideSnapshot')({ ...materialSlide(), title: '🧑'.repeat(60) }).title.length, 120);
});

test('save enforces six to twelve slides and canonical frozen UTF-8 byte budget', () => {
    for (const count of [0, 5, 13]) assert.throws(() => check('validateMaterialsSaveBody')({ ...materialsSaveBody(), slides: Array.from({ length: count }, materialSlide) }), failure('invalid_input'));
    const input = materialsSaveBody(); input.lesson.summary = '字'.repeat(8000);
    input.lesson.objectives = Array(20).fill('字'.repeat(2000));
    assert.throws(() => check('validateMaterialsSaveBody')(input), failure('request_too_large'));
    const valid = materialsSaveBody(); valid.lesson.summary = '字'.repeat(8000);
    assert.deepEqual(check('validateMaterialsSaveBody')(valid), valid);
});

test('canonical frozen materials budget accepts its inclusive boundary and rejects one more byte', () => {
    const input = materialsSaveBody();
    for (const name of ['objectives', 'key_points', 'difficulties']) input.lesson[name] = Array(20).fill('x'.repeat(2000));
    input.lesson.summary = 'x'.repeat(8000); input.lesson.questions = ['x'];
    const size = () => new TextEncoder().encode(JSON.stringify({ lesson: input.lesson, slides: input.slides })).byteLength;
    input.lesson.questions[0] += 'x'.repeat(131072 - size());
    assert.equal(size(), 131072); assert.deepEqual(check('validateMaterialsSaveBody')(input), input);
    input.lesson.questions[0] += 'x'; assert.throws(() => check('validateMaterialsSaveBody')(input), failure('request_too_large'));
});

test('approval command requires exact positive revisions and lowercase SHA-256 digests', () => {
    const validate = check('validateMaterialsApprovalBody'), input = materialsApprovalBody(), decoded = validate(input);
    assert.deepEqual(decoded, input); assert.notEqual(decoded, input);
    for (const mutate of [value => { value.reviewed = true; }, value => { value.approval_id = 'secret'; }, value => { value.input_revision = 0; },
        value => { value.outline_revision = 0; }, value => { value.input_revision = '1'; }, value => { value.outline_digest = 'A'.repeat(64); },
        value => { value.source_digest = 'a'.repeat(63); }, value => { value.source_digest = null; }, value => { delete value.outline_digest; }]) {
        const value = materialsApprovalBody(); mutate(value); assert.throws(() => validate(value), failure('invalid_input'));
    }
});

test('materials capability facts validate a separate closed private manual service', () => {
    const validate = check('validateMaterialsCapabilities'), input = materialsCapabilities(), decoded = validate(input);
    assert.deepEqual(decoded, input); assert.notEqual(decoded, input); assert.notEqual(decoded.reasons, input.reasons);
    const disabled = { save: false, read: false, approve: false, source_configured: false, files: false,
        reasons: { save: 'private_materials_disabled', read: 'private_materials_disabled', approve: 'sources_unavailable',
            source_configured: 'sources_unavailable', files: 'files_not_enabled' } };
    assert.deepEqual(validate(disabled), disabled);
    for (const mutate of [value => { value.files = true; }, value => { value.save = 'true'; }, value => { value.owner_subject = 'secret'; },
        value => { delete value.read; }, value => { value.reasons.files = 'sources_unavailable'; }, value => { value.reasons.files = 'unknown'; },
        value => { value.reasons.storage = 'private_materials_disabled'; }, value => { value.reasons.save = 'private_materials_disabled'; },
        value => { value.reasons = null; }]) {
        const value = materialsCapabilities(); mutate(value); assert.throws(() => validate(value), failure('invalid_response'));
    }
});

test('each false manual capability has an exact reason and true capabilities omit their reason', () => {
    for (const name of ['save', 'read', 'approve', 'source_configured']) {
        const disabled = materialsCapabilities(); disabled[name] = false;
        assert.throws(() => check('validateMaterialsCapabilities')(disabled), failure('invalid_response'));
        disabled.reasons[name] = 'private_materials_disabled'; assert.deepEqual(check('validateMaterialsCapabilities')(disabled), disabled);
        disabled[name] = true; assert.throws(() => check('validateMaterialsCapabilities')(disabled), failure('invalid_response'));
    }
});

test('materials snapshot returns detached current state and only public outline approval receipt fields', () => {
    const validate = check('validateMaterialsSnapshot');
    for (const operation of [null, 'save', 'approve']) {
        const input = materialsSnapshot(operation), decoded = validate(input); assert.deepEqual(decoded, input);
        assert.notEqual(decoded, input); assert.notEqual(decoded.outline, input.outline); assert.notEqual(decoded.outline.lesson, input.outline.lesson);
        assert.notEqual(decoded.outline.slides[0].columns, input.outline.slides[0].columns);
        assert.notEqual(decoded.needs_normalization_fields, input.needs_normalization_fields);
        if (operation === 'approve') assert.notEqual(decoded.approval, input.approval);
        if (operation !== null) assert.notEqual(decoded.receipt, input.receipt);
    }
    const empty = { ...materialsSnapshot(), input_revision: 1, working_revision: 1, last_outline_revision: 0,
        current_outline_id: null, outline: null, approval: null, source_status: 'unprepared', current_source_digest: materialsDigest,
        approval_eligible: false, approval_current: false, approval_blocker: 'NO_OUTLINE' };
    assert.deepEqual(validate(empty), empty);
});

test('materials snapshot validates every bounded scalar nested DTO and disallows private metadata', () => {
    for (const mutate of [value => { value.owner_subject = 'secret'; }, value => { delete value.receipt; },
        value => { value.task_id = '/var/secret'; }, value => { value.input_revision = 0; }, value => { value.working_revision = '2'; },
        value => { value.last_outline_revision = -1; }, value => { value.current_outline_id = 'bad'; }, value => { value.source_status = 'prepared'; },
        value => { value.current_source_digest = 'A'.repeat(64); }, value => { value.needs_normalization_fields = ['']; },
        value => { value.needs_normalization_fields = ['x'.repeat(256)]; },
        value => { value.needs_normalization_fields = Array(1001).fill('lesson.title'); }, value => { value.approval_eligible = 1; },
        value => { value.approval_current = 'false'; }, value => { value.approval_blocker = 'unknown'; },
        value => { value.outline.source_path = '/var/secret'; }, value => { value.outline.skill_versions = ['lesson_outline@1']; },
        value => { value.outline.outline_digest = null; }, value => { value.outline.created_at = '2026-10-06T08:00:00+08:00'; },
        value => { value.outline.created_at = '2026-02-30T00:00:00Z'; }, value => { value.outline.lesson.objectives = ['']; },
        value => { delete value.outline.lesson.summary; }, value => { delete value.outline.slides[0].evidence_refs; },
        value => { value.outline.slides[0].evidence_refs = [materialsApprovalId]; }, value => { value.outline.task_id = materialsApprovalId; },
        value => { value.approval = { ...materialsApproval(), owner: 'secret' }; },
        value => { value.approval = { ...materialsApproval(), task_id: materialsApprovalId }; },
        value => { value.approval = { ...materialsApproval(), confirmed_at: null }; },
        value => { value.receipt = { operation: 'save', outline_id: materialsOutlineId, approval_id: materialsApprovalId, input_revision: 2, working_revision: 2, replayed: false }; },
        value => { value.receipt = { operation: 'approve', outline_id: materialsOutlineId, approval_id: null, input_revision: 2, working_revision: 2, replayed: false }; },
        value => { value.receipt = { operation: 'save', outline_id: materialsOutlineId, approval_id: null, input_revision: 2, working_revision: 2, replayed: 'true' }; }]) {
        const value = materialsSnapshot(); mutate(value); assert.throws(() => check('validateMaterialsSnapshot')(value), failure('invalid_response'));
    }
});

test('materials response accepts all exact blockers source statuses and original replay receipt', () => {
    const validate = check('validateMaterialsSnapshot');
    for (const approval_blocker of ['NO_OUTLINE', 'MATERIAL_SOURCES_UNAVAILABLE', 'STALE_INPUT_REVISION', 'SOURCE_CHANGED', 'OWNER_RUN_BUSY',
        'NORMALIZATION_REQUIRED', 'MATERIAL_TEXT_UNREPRESENTABLE']) {
        const input = { ...materialsSnapshot(), approval_eligible: false, approval_current: false, approval_blocker };
        assert.deepEqual(validate(input), input);
    }
    const unprepared = { ...materialsSnapshot(), input_revision: 1, working_revision: 1, last_outline_revision: 0, current_outline_id: null,
        outline: null, source_status: 'unprepared', approval_eligible: false, approval_blocker: 'NO_OUTLINE' };
    const changed = { ...materialsSnapshot(), source_status: 'changed', current_source_digest: 'b'.repeat(64), approval_eligible: false, approval_blocker: 'SOURCE_CHANGED' };
    const unavailable = { ...materialsSnapshot(), source_status: 'unavailable', current_source_digest: null, approval_eligible: false, approval_blocker: 'MATERIAL_SOURCES_UNAVAILABLE' };
    for (const input of [unprepared, materialsSnapshot(), changed, unavailable, { ...unavailable, last_outline_revision: 0, current_outline_id: null, outline: null }]) assert.deepEqual(validate(input), input);
    const replay = { ...materialsSnapshot('approve'), input_revision: 8, working_revision: 12, approval_eligible: false, approval_current: false, approval_blocker: 'STALE_INPUT_REVISION',
        receipt: { operation: 'save', outline_id: materialsApprovalId, approval_id: null, input_revision: 3, working_revision: 4, replayed: true } };
    assert.deepEqual(validate(replay), replay);
});

test('source status strictly binds nullable outline and current digest while allowing independently stale input', () => {
    const noOutline = { ...materialsSnapshot(), last_outline_revision: 0, current_outline_id: null, outline: null, approval_eligible: false, approval_blocker: 'NO_OUTLINE' };
    for (const input of [{ ...noOutline, source_status: 'current' },
        { ...materialsSnapshot(), source_status: 'changed' }, { ...materialsSnapshot(), source_status: 'changed', current_source_digest: null },
        { ...noOutline, source_status: 'changed', current_source_digest: 'b'.repeat(64) },
        { ...materialsSnapshot(), source_status: 'unavailable' },
        { ...materialsSnapshot(), source_status: 'unprepared', approval_eligible: false, approval_blocker: 'NO_OUTLINE' },
        { ...noOutline, source_status: 'unprepared', current_source_digest: null }]) {
        assert.throws(() => check('validateMaterialsSnapshot')(input), failure('invalid_response'));
    }
    const stale = { ...materialsSnapshot(), input_revision: 3, working_revision: 4, approval_eligible: false, approval_blocker: 'STALE_INPUT_REVISION' };
    assert.deepEqual(check('validateMaterialsSnapshot')(stale), stale);
});

test('latest historical outline remains readable after the current pointer clears without claiming current approval', () => {
    const historical = { ...materialsSnapshot(), input_revision: 3, working_revision: 4, current_outline_id: null,
        approval_eligible: false, approval_blocker: 'STALE_INPUT_REVISION' };
    assert.deepEqual(check('validateMaterialsSnapshot')(historical), historical);
    assert.throws(() => check('validateMaterialsSnapshot')({ ...materialsSnapshot('approve'), current_outline_id: null }), failure('invalid_response'));
});

test('native DTO approval eligibility tuple sequence and receipt bounds are enforced for tampered states', () => {
    for (const mutate of [value => { value.approval_current = false; value.approval.outline_id = materialsApprovalId; },
        value => { value.approval_current = false; value.approval.input_revision = 1; },
        value => { value.approval_eligible = false; value.approval_blocker = 'OWNER_RUN_BUSY'; },
        value => { value.approval_eligible = false; value.approval_current = false; },
        value => { value.needs_normalization_fields = ['legacy-field']; },
        value => { value.approval_current = false; value.input_revision = 3; },
        value => { value.approval_current = false; value.current_outline_id = null; },
        value => { value.approval_current = false; value.source_status = 'changed'; value.current_source_digest = 'b'.repeat(64); },
        value => { value.receipt.input_revision = value.input_revision + 1; },
        value => { value.receipt.working_revision = value.working_revision + 1; },
        value => { value.current_outline_id = null; value.outline = null; value.approval = null; value.approval_eligible = false; value.approval_current = false;
            value.approval_blocker = 'NO_OUTLINE'; value.source_status = 'unprepared'; },
        value => { value.current_outline_id = null; value.outline = null; value.last_outline_revision = 0; value.approval_eligible = false; value.approval_current = false;
            value.approval_blocker = 'NO_OUTLINE'; value.source_status = 'unprepared'; value.receipt = null; }]) {
        const value = materialsSnapshot('approve'); mutate(value); assert.throws(() => check('validateMaterialsSnapshot')(value), failure('invalid_response'));
    }
});

test('ineligible historical reads accept bounded normalization IDs without imposing current approval identity', () => {
    const historical = { ...materialsSnapshot(), input_revision: 3, working_revision: 4, current_outline_id: materialsApprovalId,
        needs_normalization_fields: ['legacy field?!', '历史 旧字段？！', '🧑'.repeat(255)], approval_eligible: false, approval_blocker: 'STALE_INPUT_REVISION' };
    assert.deepEqual(check('validateMaterialsSnapshot')(historical), historical);
});

test('materials response applies canonical frozen content budget without forwarding invalid details', () => {
    const input = materialsSnapshot(); input.outline.lesson.objectives = Array(20).fill('字'.repeat(2000)); input.outline.lesson.summary = '字'.repeat(8000);
    assert.throws(() => check('validateMaterialsSnapshot')(input), failure('invalid_response'));
});

test('materials state cannot claim current outline source or approval with inconsistent public identities', () => {
    for (const mutate of [value => { value.current_outline_id = materialsApprovalId; }, value => { value.last_outline_revision = 2; },
        value => { value.outline.input_revision = 0; }, value => { value.current_source_digest = null; },
        value => { value.current_source_digest = 'b'.repeat(64); }, value => { value.approval_blocker = 'SOURCE_CHANGED'; },
        value => { value.approval = null; }, value => { value.approval.outline_id = materialsApprovalId; },
        value => { value.approval.input_revision = 1; }, value => { value.approval.outline_digest = 'b'.repeat(64); },
        value => { value.approval.source_digest = 'b'.repeat(64); }, value => { value.outline = null; }]) {
        const value = materialsSnapshot('approve'); mutate(value); assert.throws(() => check('validateMaterialsSnapshot')(value), failure('invalid_response'));
    }
});

const envelope = data => ({ code: 200, message: 'ok', data });
const response = (status, body) => ({ status, text: async () => typeof body === 'string' ? body : JSON.stringify(body) });
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const tick = async () => { for (let index = 0; index < 5; index++) await Promise.resolve(); };
const apiFor = (status = 200, body = envelope(materialsSnapshot()), overrides = {}) => createTeacherWorkApi({
    getToken: () => 'synthetic-session', fetchImpl: async () => response(status, body), ...overrides });
const requiredApi = (...args) => {
    const api = apiFor(...args);
    for (const name of ['getMaterialsCapabilities', 'getMaterials', 'saveMaterials', 'approveMaterials']) assert.equal(typeof api[name], 'function', name);
    return api;
};

test('materials transport uses only explicit private routes bearer no-store and mutation idempotency', async () => {
    const calls = [], controller = new AbortController(), api = requiredApi(200, undefined, {
        fetchImpl: async (url, options) => { calls.push({ url, options }); return response(200, envelope(url.endsWith('/capabilities') ? materialsCapabilities() :
            materialsSnapshot(options.method === 'GET' ? null : url.endsWith('/approve') ? 'approve' : 'save'))); }
    });
    assert.deepEqual(await api.getMaterialsCapabilities({ signal: controller.signal }), materialsCapabilities());
    assert.deepEqual(await api.getMaterials(materialsTaskId, { signal: controller.signal }), materialsSnapshot());
    assert.deepEqual(await api.saveMaterials(materialsTaskId, materialsSaveBody(), { idempotencyKey: 'save-key', signal: controller.signal }), materialsSnapshot('save'));
    const approvalBody = { ...materialsApprovalBody(), input_revision: 2 };
    assert.deepEqual(await api.approveMaterials(materialsTaskId, approvalBody, { idempotencyKey: 'approve-key', signal: controller.signal }), materialsSnapshot('approve'));
    assert.deepEqual(calls.map(({ options }) => options.method), ['GET', 'GET', 'POST', 'POST']);
    assert.ok(calls[0].url.endsWith('/api/teacher/work/materials/capabilities'));
    assert.ok(calls[1].url.endsWith(`/api/teacher/work/tasks/${materialsTaskId}/materials`));
    assert.ok(calls[2].url.endsWith(`/api/teacher/work/tasks/${materialsTaskId}/materials`));
    assert.ok(calls[3].url.endsWith(`/api/teacher/work/tasks/${materialsTaskId}/materials/approve`));
    assert.deepEqual(JSON.parse(calls[2].options.body), materialsSaveBody()); assert.deepEqual(JSON.parse(calls[3].options.body), approvalBody);
    for (const { options } of calls) {
        assert.equal(options.headers.Authorization, 'Bearer synthetic-session'); assert.equal(options.cache, 'no-store');
        assert.equal(options.signal, controller.signal); assert.equal(options.credentials, undefined);
        assert.deepEqual(Object.keys(options.headers).sort(), ['Authorization', 'Content-Type', ...(options.method === 'POST' ? ['Idempotency-Key'] : [])].sort());
        if (options.method === 'GET') assert.equal(options.body, undefined);
    }
    assert.equal(calls[2].options.headers['Idempotency-Key'], 'save-key'); assert.equal(calls[3].options.headers['Idempotency-Key'], 'approve-key');
});

test('materials API rejects invalid commands task identifiers keys and options before HTTP', async () => {
    let calls = 0; const api = requiredApi(200, undefined, { fetchImpl: async () => { calls++; return response(200, envelope(materialsSnapshot())); } });
    for (const invoke of [() => api.getMaterials('../secret'), () => api.saveMaterials('../secret', materialsSaveBody(), { idempotencyKey: 'key' }),
        () => api.approveMaterials('../secret', materialsApprovalBody(), { idempotencyKey: 'key' }), () => api.saveMaterials(materialsTaskId, materialsSaveBody()),
        () => api.approveMaterials(materialsTaskId, materialsApprovalBody()), () => api.getMaterialsCapabilities({ idempotencyKey: 'secret' }),
        () => api.getMaterials(materialsTaskId, { owner_subject: 'secret' }), () => api.getMaterials(materialsTaskId, { signal: {} }),
        () => api.saveMaterials(materialsTaskId, { ...materialsSaveBody(), reviewed: true }, { idempotencyKey: 'key' }),
        () => api.saveMaterials(materialsTaskId, materialsSaveBody(), { idempotencyKey: 'bad\nkey' }),
        () => api.approveMaterials(materialsTaskId, { ...materialsApprovalBody(), source_digest: null }, { idempotencyKey: 'key' })]) {
        await assert.rejects(invoke(), failure('invalid_input'));
    }
    assert.equal(calls, 0);
});

test('materials transport binds task and response operation while preserving older replay receipts', async () => {
    for (const [data, invoke] of [[{ ...materialsSnapshot(), task_id: materialsApprovalId }, api => api.getMaterials(materialsTaskId)],
        [materialsSnapshot('save'), api => api.getMaterials(materialsTaskId)],
        [materialsSnapshot(), api => api.saveMaterials(materialsTaskId, materialsSaveBody(), { idempotencyKey: 'key' })],
        [materialsSnapshot('approve'), api => api.saveMaterials(materialsTaskId, materialsSaveBody(), { idempotencyKey: 'key' })],
        [materialsSnapshot('save'), api => api.approveMaterials(materialsTaskId, materialsApprovalBody(), { idempotencyKey: 'key' })]])
        await assert.rejects(invoke(requiredApi(200, envelope(data))), failure('invalid_response', 200));
    const replay = { ...materialsSnapshot('approve'), input_revision: 8, working_revision: 12, approval_eligible: false, approval_current: false, approval_blocker: 'STALE_INPUT_REVISION',
        receipt: { operation: 'save', outline_id: materialsApprovalId, approval_id: null, input_revision: 2, working_revision: 2, replayed: true } };
    assert.deepEqual(await requiredApi(200, envelope(replay)).saveMaterials(materialsTaskId, materialsSaveBody(), { idempotencyKey: 'key' }), replay);
});

test('mutation receipts bind original command revisions even when current state advanced before replay', async () => {
    for (const [operation, mutate] of [['save', value => { value.receipt.input_revision = 3; }], ['save', value => { value.receipt.working_revision = 3; }],
        ['approve', value => { value.receipt.input_revision = 3; }]]) {
        for (const replayed of [false, true]) {
            const value = materialsSnapshot(operation); value.receipt.replayed = replayed; mutate(value);
            const api = requiredApi(200, envelope(value));
            await assert.rejects(operation === 'save' ? api.saveMaterials(materialsTaskId, materialsSaveBody(), { idempotencyKey: 'key' }) :
                api.approveMaterials(materialsTaskId, { ...materialsApprovalBody(), input_revision: 2 }, { idempotencyKey: 'key' }), failure('invalid_response', 200));
        }
    }
});

test('materials successes require HTTP200 exact ok envelope and bounded UTF-8 body', async () => {
    const tooLarge = materialsSnapshot(); tooLarge.outline.lesson.objectives = Array(20).fill('字'.repeat(2000));
    tooLarge.needs_normalization_fields = Array(1000).fill('x'.repeat(200));
    const raw = JSON.stringify(envelope(tooLarge));
    assert.ok(raw.length < 262144); assert.ok(new TextEncoder().encode(raw).byteLength > 262144);
    for (const [status, body] of [[201, envelope(materialsSnapshot())], [200, { ...envelope(materialsSnapshot()), extra: 'secret' }],
        [200, { code: 200, message: 'success', data: materialsSnapshot() }], [200, { code: 201, message: 'ok', data: materialsSnapshot() }],
        [200, { code: 200, message: 'ok', data: null }], [200, '{secret'], [200, raw]])
        await assert.rejects(requiredApi(status, body).getMaterials(materialsTaskId), failure('invalid_response', status));
});

test('materials UTF-8 response budget includes whitespace and accepts exactly262144 bytes', async () => {
    const data = materialsSnapshot(), raw = JSON.stringify(envelope(data)), byteLength = new TextEncoder().encode(raw).byteLength;
    const boundary = raw + ' '.repeat(262144 - byteLength);
    assert.equal(new TextEncoder().encode(boundary).byteLength, 262144);
    assert.deepEqual(await requiredApi(200, boundary).getMaterials(materialsTaskId), data);
    await assert.rejects(requiredApi(200, boundary + ' ').getMaterials(materialsTaskId), failure('invalid_response', 200));
});

test('materials errors map only exact bounded HTTP envelopes and allowlisted error codes', async () => {
    const mappings = { REVISION_CONFLICT: 'revision_conflict', OUTLINE_REVISION_CONFLICT: 'outline_revision_conflict',
        OUTLINE_APPROVAL_CONFLICT: 'outline_approval_conflict', IDEMPOTENCY_CONFLICT: 'idempotency_conflict', SOURCE_CHANGED: 'source_changed',
        OWNER_RUN_BUSY: 'owner_busy', NORMALIZATION_REQUIRED: 'normalization_required', MATERIAL_TEXT_UNREPRESENTABLE: 'material_text_unrepresentable',
        MATERIAL_RECEIPT_LIMIT: 'material_receipt_limit' };
    for (const [message, reason] of Object.entries(mappings))
        await assert.rejects(requiredApi(409, { code: 409, message, data: null }).getMaterials(materialsTaskId), failure(reason, 409));
    await assert.rejects(requiredApi(503, { code: 503, message: 'MATERIAL_SOURCES_UNAVAILABLE', data: null }).getMaterials(materialsTaskId), failure('material_sources_unavailable', 503));
    for (const body of [{ code: 409, message: 'OWNER_BUSY', data: null }, { code: 409, message: 'STALE_INPUT_REVISION', data: null },
        { code: 409, message: 'SOURCE_CHANGED', data: { secret: '/var/secret' } }, { code: 400, message: 'SOURCE_CHANGED', data: null },
        { code: 409, message: 'SOURCE_CHANGED', data: null, owner_subject: 'secret' }, 'secret'])
        await assert.rejects(requiredApi(409, body).getMaterials(materialsTaskId), failure('request_failed', 409));
    for (const [status, reason, message] of [[403, 'teacher_required', 'TEACHER_REQUIRED'], [404, 'task_not_found', 'NOT_FOUND'],
        [400, 'invalid_input', 'INVALID_INPUT'], [422, 'invalid_input', 'INVALID_INPUT'], [413, 'request_too_large', 'BODY_TOO_LARGE']])
        await assert.rejects(requiredApi(status, { code: status, message, data: null }).getMaterials(materialsTaskId), failure(reason, status));
    await assert.rejects(requiredApi(404, { code: 404, message: 'NOT_FOUND', data: null }).getMaterialsCapabilities(), failure('TEACHER_WORK_UNAVAILABLE', 404));
});

test('only exact422 PRIVATE_DRAFT_TOO_LARGE identifies the physical private draft capacity', async () => {
    await assert.rejects(requiredApi(422, { code: 422, message: 'PRIVATE_DRAFT_TOO_LARGE', data: null }).saveMaterials(materialsTaskId,
        materialsSaveBody(), { idempotencyKey: 'capacity-key' }), failure('private_draft_too_large', 422));
    for (const message of ['INVALID_INPUT', 'PRIVATE_DRAFT_TOO_LARGE_UNKNOWN', 'BODY_TOO_LARGE'])
        await assert.rejects(requiredApi(422, { code: 422, message, data: null }).getMaterials(materialsTaskId), failure('invalid_input', 422));
    await assert.rejects(requiredApi(400, { code: 400, message: 'PRIVATE_DRAFT_TOO_LARGE', data: null }).getMaterials(materialsTaskId), failure('invalid_input', 400));
    await assert.rejects(requiredApi(409, { code: 409, message: 'PRIVATE_DRAFT_TOO_LARGE', data: null }).getMaterials(materialsTaskId), failure('request_failed', 409));
});

test('materials requests fence replacement abort and late401 before auth expiry or DTO acceptance', async () => {
    for (const status of [200, 401]) {
        let token = 'old', expired = 0; const body = deferred();
        const api = requiredApi(status, undefined, { getToken: () => token, dispatchAuthExpired: () => expired++,
            fetchImpl: async () => ({ status, text: () => body.promise }) });
        const pending = api.getMaterials(materialsTaskId); await tick(); token = 'new'; body.resolve(JSON.stringify(envelope(materialsSnapshot())));
        await assert.rejects(pending, failure('request_aborted', status)); assert.equal(expired, 0);
    }
    const controller = new AbortController(), pendingBody = deferred(), api = requiredApi(200, undefined, {
        fetchImpl: async () => ({ status: 200, text: () => pendingBody.promise }) });
    const pending = api.saveMaterials(materialsTaskId, materialsSaveBody(), { idempotencyKey: 'key', signal: controller.signal });
    await tick(); controller.abort(); pendingBody.resolve(JSON.stringify(envelope(materialsSnapshot('save'))));
    await assert.rejects(pending, failure('request_aborted', 200));
    let expired = 0;
    await assert.rejects(requiredApi(401, { code: 401, message: 'AUTH_REQUIRED', data: null }, { dispatchAuthExpired: () => expired++ }).getMaterials(materialsTaskId), failure('auth_required', 401));
    assert.equal(expired, 1);
    await assert.rejects(requiredApi(200, undefined, { getToken: () => '' }).getMaterials(materialsTaskId), failure('auth_required', 401));
    await assert.rejects(requiredApi(200, undefined, { fetchImpl: async () => { throw new Error('/var/secret'); } }).getMaterials(materialsTaskId), failure('network_error', 0));
});
