import { API_BASE_URL } from '../config/env.js';

const fields = Object.freeze(['chat', 'task_write', 'generate', 'storage', 'structural_preview', 'rendered_preview', 'publish']);
const privateFields = Object.freeze(['create', 'read', 'update']);
const privateChatHistoryMaximumBytes = 262144;
const privateChatFields = Object.freeze(['send', 'history', 'read_run', 'cancel', 'provider_configured', 'external_provider_verified']);
const reasonCodes = new Set(['enabled', 'current_teacher_allowed', 'schema_ready', 'transaction_ready', 'storage_ready',
    'ai_ready', 'exporters_ready', 'outline_handler_ready', 'package_handler_ready', 'rendered_preview_unsupported', 'private_teacher_work_only',
    'private_chat_disabled', 'chat_runtime_unavailable']);
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const exact = (value, names) => object(value) && Object.keys(value).length === names.length && names.every(name => Object.hasOwn(value, name));
const text = (value, max, nonempty = false) => typeof value === 'string' && [...value].length <= max && (!nonempty || value.trim().length > 0);
const integer = (value, min, max = Number.MAX_SAFE_INTEGER) => Number.isSafeInteger(value) && value >= min && value <= max;
const chatKey = value => text(value, 128, true) && !/[\p{C}]/u.test(value);
const utcOrder = value => {
    if (typeof value !== 'string' || value.length > 40) return null;
    const match = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,6}))?(?:Z|\+00:00)$/.exec(value);
    const milliseconds = match ? Date.parse(value) : NaN;
    if (!Number.isFinite(milliseconds) || new Date(milliseconds).toISOString().slice(0, 19) !== match[1]) return null;
    // Compare all database microseconds, rather than Date's millisecond truncation.
    return `${match[1]}.${(match[2] || '').padEnd(6, '0')}`;
};
const utcInstant = value => utcOrder(value) !== null;
export const isTeacherWorkTaskId = value => typeof value === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
const resources = value => Array.isArray(value) && value.length >= 1 && value.length <= 10 &&
    value.every(id => text(id, 255, true)) && new Set(value).size === value.length;
const error = (reason, status = 0) => Object.assign(new Error({
    TEACHER_WORK_UNAVAILABLE: '教师 Work 暂不可用', network_error: '无法连接教师 Work，请重试',
    request_aborted: '本次请求已失效', auth_required: '登录身份未通过验证', teacher_required: '此页面仅供教师使用',
    invalid_response: '教师 Work 响应无法验证', request_failed: '教师 Work 请求失败，请重试',
    invalid_input: '请检查任务信息和资料选择', task_not_found: '任务不存在或当前身份无法读取',
    revision_conflict: '任务版本已变化，请重新读取后检查并保存', idempotency_conflict: '创建请求标识与内容不一致，请修改后重试',
    request_too_large: '消息内容过长，请缩短后重试', capacity_unavailable: '教师 Work 当前繁忙，请稍后重试',
    owner_busy: '当前身份已有运行中的任务，请等待完成或明确取消后重试'
}[reason] || '教师 Work 请求失败，请重试'), { name: 'TeacherWorkError', reason, status });

function capabilities(data) {
    const hasPrivate = object(data) && Object.hasOwn(data, 'private_tasks');
    const hasPrivateChat = object(data) && Object.hasOwn(data, 'private_chat');
    if (!exact(data, [...fields, 'reasons', ...(hasPrivate ? ['private_tasks'] : []), ...(hasPrivateChat ? ['private_chat'] : [])]) ||
        !fields.every(name => typeof data[name] === 'boolean') || data.rendered_preview !== false || data.publish !== false ||
        !object(data.reasons) || Object.keys(data.reasons).length > fields.length ||
        hasPrivate && (!exact(data.private_tasks, privateFields) || !privateFields.every(name => typeof data.private_tasks[name] === 'boolean')) ||
        hasPrivateChat && (!exact(data.private_chat, privateChatFields) ||
            !privateChatFields.every(name => typeof data.private_chat[name] === 'boolean') || data.private_chat.external_provider_verified !== false ||
            data.private_chat.send !== data.chat || data.private_chat.send && !data.private_chat.provider_configured)) throw error('invalid_response');
    const reasons = {};
    for (const [name, value] of Object.entries(data.reasons)) {
        if (!fields.includes(name) || !text(value, 200, true) || value.split(',').some(code => !reasonCodes.has(code))) throw error('invalid_response');
        reasons[name] = value;
    }
    return { ...Object.fromEntries(fields.map(name => [name, data[name]])), reasons,
        private_tasks: Object.fromEntries(privateFields.map(name => [name, hasPrivate && data.private_tasks[name] === true])),
        private_chat: Object.fromEntries(privateChatFields.map(name => [name, hasPrivateChat && data.private_chat[name] === true])) };
}

export function validatePrivateChatBody(body) {
    if (!exact(body, ['kind', 'input_revision', 'skill_ref', 'payload']) || body.kind !== 'chat' || !integer(body.input_revision, 1) ||
        body.skill_ref !== null || !exact(body.payload, ['text', 'client_message_key']) ||
        !text(body.payload.text, 4000, true) || !chatKey(body.payload.client_message_key)) throw error('invalid_input');
    return { kind: 'chat', input_revision: body.input_revision, skill_ref: null,
        payload: { text: body.payload.text, client_message_key: body.payload.client_message_key } };
}

export function validatePrivateChatRun(data) {
    const names = ['run_id', 'task_id', 'kind', 'input_revision', 'stage', 'attempt', 'provider_call_count', 'deadline', 'cancelled_at', 'error_code'];
    if (!exact(data, names) || !isTeacherWorkTaskId(data.run_id) || !isTeacherWorkTaskId(data.task_id) || data.kind !== 'chat' ||
        !integer(data.input_revision, 1) || !['PENDING', 'CHAT_RUNNING', 'COMPLETE', 'FAILED', 'CANCELLED', 'INTERRUPTED'].includes(data.stage) ||
        !integer(data.attempt, 1, 2) || !integer(data.provider_call_count, 0, 3) || !utcInstant(data.deadline) ||
        data.cancelled_at !== null && !utcInstant(data.cancelled_at) ||
        data.error_code !== null && (typeof data.error_code !== 'string' || !/^[A-Z][A-Z0-9_]{0,63}$/.test(data.error_code))) throw error('invalid_response');
    return Object.fromEntries(names.map(name => [name, data[name]]));
}

export function comparePrivateChatMessages(left, right) {
    const first = utcOrder(left?.created_at), second = utcOrder(right?.created_at);
    if (first === null || second === null || !isTeacherWorkTaskId(left?.message_id) || !isTeacherWorkTaskId(right?.message_id)) throw error('invalid_response');
    if (first !== second) return first < second ? -1 : 1;
    return left.message_id === right.message_id ? 0 : left.message_id < right.message_id ? -1 : 1;
}

export function validatePrivateChatHistory(data) {
    const messageFields = ['message_id', 'task_id', 'role', 'plain_text', 'run_id', 'client_message_key', 'result_type', 'result_refs', 'omitted_context', 'created_at'];
    if (!exact(data, ['task_id', 'messages', 'has_more', 'next_before']) || !isTeacherWorkTaskId(data.task_id) ||
        !Array.isArray(data.messages) || data.messages.length > 50 || typeof data.has_more !== 'boolean' ||
        data.next_before !== null && !isTeacherWorkTaskId(data.next_before) ||
        !data.has_more && data.next_before !== null || data.has_more && (!data.messages.length || data.next_before !== data.messages[0]?.message_id)) throw error('invalid_response');
    const ids = new Set(); let previous = null;
    const messages = data.messages.map(item => {
        if (!exact(item, messageFields) || !isTeacherWorkTaskId(item.message_id) || item.task_id !== data.task_id ||
            !['user', 'assistant', 'tool'].includes(item.role) || !text(item.plain_text, 32768) ||
            item.run_id !== null && !isTeacherWorkTaskId(item.run_id) || item.client_message_key !== null && !chatKey(item.client_message_key) ||
            item.result_type !== null && !['answer', 'outline_proposal', 'revision_proposal', 'skill_suggestion'].includes(item.result_type) ||
            !Array.isArray(item.result_refs) || item.result_refs.length > 10 || !item.result_refs.every(isTeacherWorkTaskId) ||
            item.omitted_context !== null && typeof item.omitted_context !== 'boolean' || !utcInstant(item.created_at) || ids.has(item.message_id)) throw error('invalid_response');
        if ((item.result_type !== null || item.omitted_context !== null) && (item.role !== 'assistant' || item.run_id === null ||
            item.result_type === null || item.omitted_context === null || !text(item.plain_text, 32768, true))) throw error('invalid_response');
        if (previous && comparePrivateChatMessages(previous, item) >= 0) throw error('invalid_response');
        ids.add(item.message_id); previous = item;
        return { ...Object.fromEntries(messageFields.filter(name => name !== 'result_refs').map(name => [name, item[name]])), result_refs: [...item.result_refs] };
    });
    return { task_id: data.task_id, messages, has_more: data.has_more, next_before: data.next_before };
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
    async function send(path, method, body, options, decode, maximum = 65536, create = false, chat = false, maximumBytes = null) {
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
                if (status === 409) {
                    if (!chat) throw error(create ? 'idempotency_conflict' : 'revision_conflict', status);
                    let conflict;
                    try { if (typeof raw === 'string' && raw.length <= maximum) conflict = JSON.parse(raw); } catch { /* Unknown errors stay generic. */ }
                    const conflicts = { REVISION_CONFLICT: 'revision_conflict', STALE_INPUT_REVISION: 'revision_conflict',
                        IDEMPOTENCY_CONFLICT: 'idempotency_conflict', MESSAGE_KEY_CONFLICT: 'idempotency_conflict',
                        OWNER_BUSY: 'owner_busy', OWNER_RUN_BUSY: 'owner_busy' };
                    const known = exact(conflict, ['code', 'message', 'data']) && conflict.code === 409 && conflict.data === null &&
                        typeof conflict.message === 'string' && Object.hasOwn(conflicts, conflict.message) ? conflicts[conflict.message] : null;
                    throw error(known || 'request_failed', status);
                }
                if (status === 404) throw error(path.endsWith('/capabilities') ? 'TEACHER_WORK_UNAVAILABLE' : 'task_not_found', status);
                if (status === 503) throw error('TEACHER_WORK_UNAVAILABLE', status);
                if (chat && status === 413) throw error('request_too_large', status);
                if (chat && status === 429) throw error('capacity_unavailable', status);
                if (status === 400 || status === 422) throw error('invalid_input', status);
                throw error('request_failed', status);
            }
            if (status !== 200 || typeof raw !== 'string' || raw.length > maximum ||
                maximumBytes !== null && new TextEncoder().encode(raw).byteLength > maximumBytes) throw error('invalid_response', status);
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
    const runDecoder = (taskId, runId, revision) => data => { const decoded = validatePrivateChatRun(data);
        if (decoded.task_id !== taskId || runId !== undefined && decoded.run_id !== runId ||
            revision !== undefined && decoded.input_revision !== revision) throw error('invalid_response'); return decoded; };
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
        },
        async sendMessage(taskId, body, options = {}) {
            if (!isTeacherWorkTaskId(taskId)) throw error('invalid_input');
            const validated = validatePrivateChatBody(body);
            return send(`/teacher/work/tasks/${encodeURIComponent(taskId)}/messages`, 'POST', validated, options,
                runDecoder(taskId, undefined, validated.input_revision), 16384, true, true);
        },
        async listMessages(taskId, options = {}) {
            if (!isTeacherWorkTaskId(taskId) || !object(options) || Object.keys(options).some(name => !['limit', 'before', 'signal'].includes(name)) ||
                !integer(options.limit === undefined ? 20 : options.limit, 1, 50) ||
                Object.hasOwn(options, 'before') && !isTeacherWorkTaskId(options.before)) throw error('invalid_input');
            const limit = options.limit === undefined ? 20 : options.limit;
            const query = new URLSearchParams({ limit: String(limit), ...(Object.hasOwn(options, 'before') ? { before: options.before } : {}) });
            return send(`/teacher/work/tasks/${encodeURIComponent(taskId)}/messages?${query}`, 'GET', undefined,
                options.signal === undefined ? {} : { signal: options.signal }, data => {
                    const decoded = validatePrivateChatHistory(data);
                    if (decoded.task_id !== taskId || decoded.messages.length > limit) throw error('invalid_response'); return decoded;
                }, privateChatHistoryMaximumBytes, false, true, privateChatHistoryMaximumBytes);
        },
        async getRun(taskId, runId, options = {}) {
            if (!isTeacherWorkTaskId(taskId) || !isTeacherWorkTaskId(runId)) throw error('invalid_input');
            return send(`/teacher/work/tasks/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(runId)}`, 'GET', undefined,
                options, runDecoder(taskId, runId), 16384, false, true);
        },
        async cancelRun(taskId, runId, options = {}) {
            if (!isTeacherWorkTaskId(taskId) || !isTeacherWorkTaskId(runId)) throw error('invalid_input');
            return send(`/teacher/work/tasks/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(runId)}/cancel`, 'POST', {},
                options, runDecoder(taskId, runId), 16384, false, true);
        }
    });
}

export const teacherWorkApi = createTeacherWorkApi();
export default teacherWorkApi;
