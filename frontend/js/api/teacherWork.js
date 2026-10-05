import { API_BASE_URL } from '../config/env.js';

const fields = Object.freeze(['chat', 'task_write', 'generate', 'storage', 'structural_preview', 'rendered_preview', 'publish']);
const reasonCodes = new Set(['enabled', 'current_teacher_allowed', 'schema_ready', 'transaction_ready', 'storage_ready',
    'ai_ready', 'exporters_ready', 'outline_handler_ready', 'package_handler_ready', 'rendered_preview_unsupported', 'private_teacher_work_only']);
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const error = (reason, status = 0) => Object.assign(new Error({
    TEACHER_WORK_UNAVAILABLE: '教师 Work 暂不可用', network_error: '无法读取教师 Work 能力',
    request_aborted: '本次请求已失效', auth_required: '登录身份未通过验证', teacher_required: '此页面仅供教师使用',
    invalid_response: '教师 Work 能力响应无法验证', request_failed: '读取教师 Work 能力失败'
}[reason] || '读取教师 Work 能力失败'), { name: 'TeacherWorkError', reason, status });

function capabilities(data) {
    if (!object(data) || Object.keys(data).length !== fields.length + 1 ||
        !fields.every(name => typeof data[name] === 'boolean') || data.rendered_preview !== false || data.publish !== false ||
        !object(data.reasons) || Object.keys(data.reasons).length > fields.length) throw error('invalid_response');
    const reasons = {};
    for (const [name, value] of Object.entries(data.reasons)) {
        if (!fields.includes(name) || typeof value !== 'string' || !value || value.length > 200 ||
            value.split(',').some(code => !reasonCodes.has(code))) throw error('invalid_response');
        reasons[name] = value;
    }
    return { ...Object.fromEntries(fields.map(name => [name, data[name]])), reasons };
}

// Fixed read only. This slice deliberately exports no task/chat/save/run/catalog/download methods.
export function createTeacherWorkApi({ fetchImpl = (...args) => globalThis.fetch(...args),
    getToken = () => globalThis.localStorage?.getItem('token') || '',
    dispatchAuthExpired = () => globalThis.window?.dispatchEvent(new CustomEvent('auth-expired')) } = {}) {
    return Object.freeze({
        async getCapabilities(options = {}) {
            if (!object(options) || Object.keys(options).some(name => name !== 'signal') ||
                options.signal !== undefined && !(options.signal instanceof AbortSignal)) throw error('invalid_response');
            const signal = options.signal;
            let token = '', status = 0, phase = 'session';
            const current = () => !signal?.aborted && (getToken() || '') === token;
            const fence = () => { if (!current()) throw error('request_aborted', status); };
            try {
                token = getToken() || '';
                if (!token) throw error('auth_required', 401);
                fence(); phase = 'fetch';
                const result = await fetchImpl(`${API_BASE_URL}/teacher/work/capabilities`, {
                    method: 'GET', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
                    cache: 'no-store', ...(signal ? { signal } : {})
                });
                fence(); phase = 'body';
                status = Number.isInteger(result?.status) && result.status >= 100 && result.status <= 599 ? result.status : 0;
                const text = await result.text(); fence();
                if (status < 200 || status >= 300) {
                    if (status === 401) { fence(); dispatchAuthExpired(); throw error('auth_required', status); }
                    if (status === 403) throw error('teacher_required', status);
                    if (status === 404 || status === 503) throw error('TEACHER_WORK_UNAVAILABLE', status);
                    throw error('request_failed', status);
                }
                if (status !== 200 || typeof text !== 'string' || text.length > 16384) throw error('invalid_response', status);
                let envelope;
                try { envelope = JSON.parse(text); } catch { throw error('invalid_response', status); }
                if (!object(envelope) || Object.keys(envelope).length !== 3 || envelope.code !== 200 || envelope.message !== 'ok' ||
                    !Object.hasOwn(envelope, 'data')) throw error('invalid_response', status);
                const data = capabilities(envelope.data); fence(); return data;
            } catch (caught) {
                let sameSession;
                try { sameSession = current(); } catch { throw error('request_failed', status); }
                if (!sameSession) throw error('request_aborted', status);
                if (caught?.name === 'TeacherWorkError') throw error(caught.reason, caught.status || status);
                throw error(phase === 'fetch' ? 'network_error' : 'request_failed', status);
            }
        }
    });
}

export const teacherWorkApi = createTeacherWorkApi();
export default teacherWorkApi;
