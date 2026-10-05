import { API_BASE_URL } from '../config/env.js';

const fields = Object.freeze(['chat', 'task_write', 'generate', 'storage', 'structural_preview', 'rendered_preview', 'publish']);
const privateFields = Object.freeze(['create', 'read', 'update']);
const reasonCodes = new Set(['enabled', 'current_teacher_allowed', 'schema_ready', 'transaction_ready', 'storage_ready',
    'ai_ready', 'exporters_ready', 'outline_handler_ready', 'package_handler_ready', 'rendered_preview_unsupported', 'private_teacher_work_only']);
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const exact = (value, names) => object(value) && Object.keys(value).length === names.length && names.every(name => Object.hasOwn(value, name));
const text = (value, max, nonempty = false) => typeof value === 'string' && [...value].length <= max && (!nonempty || value.trim().length > 0);
const integer = (value, min, max = Number.MAX_SAFE_INTEGER) => Number.isSafeInteger(value) && value >= min && value <= max;
export const isTeacherWorkTaskId = value => typeof value === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
const resources = value => Array.isArray(value) && value.length >= 1 && value.length <= 10 &&
    value.every(id => text(id, 255, true)) && new Set(value).size === value.length;
const error = (reason, status = 0) => Object.assign(new Error({
    TEACHER_WORK_UNAVAILABLE: '教师 Work 暂不可用', network_error: '无法连接教师 Work，请重试',
    request_aborted: '本次请求已失效', auth_required: '登录身份未通过验证', teacher_required: '此页面仅供教师使用',
    invalid_response: '教师 Work 响应无法验证', request_failed: '教师 Work 请求失败，请重试',
    invalid_input: '请检查任务信息和资料选择', task_not_found: '任务不存在或当前身份无法读取',
    revision_conflict: '任务版本已变化，请重新读取后检查并保存', idempotency_conflict: '创建请求标识与内容不一致，请修改后重试'
}[reason] || '教师 Work 请求失败，请重试'), { name: 'TeacherWorkError', reason, status });

function capabilities(data) {
    const hasPrivate = object(data) && Object.hasOwn(data, 'private_tasks');
    if (!exact(data, [...fields, 'reasons', ...(hasPrivate ? ['private_tasks'] : [])]) ||
        !fields.every(name => typeof data[name] === 'boolean') || data.rendered_preview !== false || data.publish !== false ||
        !object(data.reasons) || Object.keys(data.reasons).length > fields.length ||
        hasPrivate && (!exact(data.private_tasks, privateFields) || !privateFields.every(name => typeof data.private_tasks[name] === 'boolean'))) throw error('invalid_response');
    const reasons = {};
    for (const [name, value] of Object.entries(data.reasons)) {
        if (!fields.includes(name) || !text(value, 200, true) || value.split(',').some(code => !reasonCodes.has(code))) throw error('invalid_response');
        reasons[name] = value;
    }
    return { ...Object.fromEntries(fields.map(name => [name, data[name]])), reasons,
        private_tasks: Object.fromEntries(privateFields.map(name => [name, hasPrivate && data.private_tasks[name] === true])) };
}

export function validatePrivateTaskSnapshot(data) {
    const names = ['task_id', 'scope', 'title', 'topic', 'audience', 'duration_minutes', 'target_slide_count',
        'input_revision', 'working_revision', 'created_at', 'updated_at', 'working'];
    const instant = value => typeof value === 'string' && value.length <= 40 && /(?:Z|\+00:00)$/.test(value) && Number.isFinite(Date.parse(value));
    if (!exact(data, names) || !isTeacherWorkTaskId(data.task_id) || data.scope !== 'private' ||
        !['title', 'topic', 'audience'].every(name => text(data[name], 200, true)) ||
        !integer(data.duration_minutes, 1, 600) || !integer(data.target_slide_count, 6, 12) ||
        !integer(data.input_revision, 1) || !integer(data.working_revision, 1) ||
        !instant(data.created_at) || !instant(data.updated_at) ||
        !exact(data.working, ['requirements', 'resource_ids', 'needs_normalization_fields']) ||
        !text(data.working.requirements, 4000) || !resources(data.working.resource_ids) ||
        !Array.isArray(data.working.needs_normalization_fields) || data.working.needs_normalization_fields.length > 100 ||
        !data.working.needs_normalization_fields.every(name => text(name, 200, true))) throw error('invalid_response');
    return { ...Object.fromEntries(names.filter(name => name !== 'working').map(name => [name, data[name]])), working: {
        requirements: data.working.requirements, resource_ids: [...data.working.resource_ids],
        needs_normalization_fields: [...data.working.needs_normalization_fields] } };
}

export function validatePrivateTaskCreate(body) {
    const required = ['title', 'topic', 'audience', 'resource_ids', 'scope'];
    const optional = ['duration_minutes', 'target_slide_count', 'offering_id'];
    if (!object(body) || required.some(name => !Object.hasOwn(body, name)) ||
        Object.keys(body).some(name => ![...required, ...optional].includes(name)) || body.scope !== 'private' ||
        body.offering_id != null || !['title', 'topic', 'audience'].every(name => text(body[name], 200, true)) ||
        !resources(body.resource_ids) || !integer(body.duration_minutes === undefined ? 45 : body.duration_minutes, 1, 600) || !integer(body.target_slide_count === undefined ? 8 : body.target_slide_count, 6, 12)) throw error('invalid_input');
    return { title: body.title, topic: body.topic, audience: body.audience, duration_minutes: body.duration_minutes === undefined ? 45 : body.duration_minutes,
        target_slide_count: body.target_slide_count === undefined ? 8 : body.target_slide_count, resource_ids: [...body.resource_ids], scope: 'private',
        ...(Object.hasOwn(body, 'offering_id') ? { offering_id: null } : {}) };
}

function validatePatch(body) {
    if (!exact(body, ['expected_revision', 'changes']) || !integer(body.expected_revision, 1) || !object(body.changes) ||
        !Object.keys(body.changes).length || Object.keys(body.changes).some(name => !['requirements', 'resource_ids', 'target_slide_count'].includes(name)) ||
        Object.hasOwn(body.changes, 'requirements') && !text(body.changes.requirements, 4000) ||
        Object.hasOwn(body.changes, 'resource_ids') && !resources(body.changes.resource_ids) ||
        Object.hasOwn(body.changes, 'target_slide_count') && !integer(body.changes.target_slide_count, 6, 12)) throw error('invalid_input');
    return { expected_revision: body.expected_revision, changes: { ...body.changes,
        ...(Object.hasOwn(body.changes, 'resource_ids') ? { resource_ids: [...body.changes.resource_ids] } : {}) } };
}

function catalog(data) {
    if (!object(data) || !Array.isArray(data.resources) || data.resources.length > 5000) throw error('invalid_response');
    const ids = new Set();
    return data.resources.map(item => {
        if (!object(item) || !text(item.id, 255, true) || !text(item.name, 1024, true) || !text(item.course, 255, true) ||
            !['.pdf', '.ppt', '.pptx'].includes(item.extension) || ids.has(item.id)) throw error('invalid_response');
        ids.add(item.id);
        // Resource paths and legacy index metadata never enter Work state.
        return { id: item.id, name: item.name, course: item.course, extension: item.extension };
    });
}

export function createTeacherWorkApi({ fetchImpl = (...args) => globalThis.fetch(...args),
    getToken = () => globalThis.localStorage?.getItem('token') || '',
    dispatchAuthExpired = () => globalThis.window?.dispatchEvent(new CustomEvent('auth-expired')) } = {}) {
    async function send(path, method, body, options, decode, maximum = 65536, create = false) {
        if (!object(options) || Object.keys(options).some(name => !['signal', ...(create ? ['idempotencyKey'] : [])].includes(name)) ||
            options.signal !== undefined && !(options.signal instanceof AbortSignal) ||
            create && (!text(options.idempotencyKey, 128, true) || /[\p{C}]/u.test(options.idempotencyKey))) throw error('invalid_input');
        const signal = options.signal, idempotencyKey = options.idempotencyKey;
        let token = '', status = 0, phase = 'session';
        const current = () => !signal?.aborted && (getToken() || '') === token;
        const fence = () => { if (!current()) throw error('request_aborted', status); };
        try {
            token = getToken() || '';
            if (!token) throw error('auth_required', 401);
            fence(); phase = 'fetch';
            const result = await fetchImpl(`${API_BASE_URL}${path}`, { method,
                headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}`, ...(create ? { 'Idempotency-Key': idempotencyKey } : {}) },
                cache: 'no-store', ...(body !== undefined ? { body: JSON.stringify(body) } : {}), ...(signal ? { signal } : {}) });
            fence(); phase = 'body';
            status = Number.isInteger(result?.status) && result.status >= 100 && result.status <= 599 ? result.status : 0;
            const raw = await result.text(); fence();
            if (status < 200 || status >= 300) {
                if (status === 401) { fence(); dispatchAuthExpired(); throw error('auth_required', status); }
                if (status === 403) throw error('teacher_required', status);
                if (status === 409) throw error(create ? 'idempotency_conflict' : 'revision_conflict', status);
                if (status === 404) throw error(path.endsWith('/capabilities') ? 'TEACHER_WORK_UNAVAILABLE' : 'task_not_found', status);
                if (status === 503) throw error('TEACHER_WORK_UNAVAILABLE', status);
                if (status === 400 || status === 422) throw error('invalid_input', status);
                throw error('request_failed', status);
            }
            if (status !== 200 || typeof raw !== 'string' || raw.length > maximum) throw error('invalid_response', status);
            let envelope;
            try { envelope = JSON.parse(raw); } catch { throw error('invalid_response', status); }
            if (!exact(envelope, ['code', 'message', 'data']) || envelope.code !== 200 || envelope.message !== 'ok') throw error('invalid_response', status);
            const data = decode(envelope.data); fence(); return data;
        } catch (caught) {
            let sameSession;
            try { sameSession = current(); } catch { throw error('request_failed', status); }
            if (!sameSession) throw error('request_aborted', status);
            if (caught?.name === 'TeacherWorkError') throw error(caught.reason, caught.status || status);
            throw error(phase === 'fetch' ? 'network_error' : 'request_failed', status);
        }
    }
    const taskDecoder = taskId => data => { const decoded = validatePrivateTaskSnapshot(data);
        if (decoded.task_id !== taskId) throw error('invalid_response'); return decoded; };
    return Object.freeze({
        getCapabilities: (options = {}) => send('/teacher/work/capabilities', 'GET', undefined, options, capabilities, 16384),
        listResources: (options = {}) => send('/teacher/lesson-prep/resources', 'GET', undefined, options, catalog, 2 * 1024 * 1024),
        async createTask(body, options = {}) { return send('/teacher/work/tasks', 'POST', validatePrivateTaskCreate(body), options, validatePrivateTaskSnapshot, 65536, true); },
        async getTask(taskId, options = {}) {
            if (!isTeacherWorkTaskId(taskId)) throw error('invalid_input');
            return send(`/teacher/work/tasks/${encodeURIComponent(taskId)}`, 'GET', undefined, options, taskDecoder(taskId));
        },
        async updateWorking(taskId, body, options = {}) {
            if (!isTeacherWorkTaskId(taskId)) throw error('invalid_input');
            return send(`/teacher/work/tasks/${encodeURIComponent(taskId)}/working`, 'PATCH', validatePatch(body), options, taskDecoder(taskId));
        }
    });
}

export const teacherWorkApi = createTeacherWorkApi();
export default teacherWorkApi;
