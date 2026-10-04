import { API_BASE_URL } from '../config/env.js';
import { createTeachingError, safeTeachingHttpReason } from './teachingStatus.js';
import { isAssessmentCursor, isAssessmentSubject } from './teachingAssessmentDTO.js';

const B1_RECOVERY_SCOPES = Object.freeze({
    course_create: 'institution', course_update: 'course', offering_create: 'course',
    course_manage: 'offering', roster_manage: 'offering', roles_manage: 'offering'
});
const teachingIdentifier = (value, max = 36) => typeof value === 'string'
    && [...value].length >= 1 && [...value].length <= max && value === value.trim()
    && value !== '.' && value !== '..' && !/[\p{C}/\\%?#]/u.test(value);

function registeredTeachingRead(url) {
    if (typeof url !== 'string' || !url.startsWith('/teaching/') || url.includes('#')) return false;
    const parts = url.split('?');
    if (parts.length > 2) return false;
    const path = parts[0], query = new URLSearchParams(parts[1] || '');
    const pairs = [...query.entries()];
    if (new Set(pairs.map(([key]) => key)).size !== pairs.length) return false;
    const keys = pairs.map(([key]) => key);
    const only = allowed => keys.every(key => allowed.includes(key));
    const page = () => (!query.has('cursor') || teachingIdentifier(query.get('cursor')))
        && (!query.has('limit') || /^(?:[1-9]|[1-9][0-9]|100)$/.test(query.get('limit')));
    const membership = () => !query.has('membership') || ['teaching', 'learning', 'all'].includes(query.get('membership'));
    if (parts.length === 2 && (!parts[1] || query.toString() !== parts[1])) return false;
    if (path === '/teaching/capabilities') return keys.length === 0;
    if (path === '/teaching/courses') return only(['membership', 'cursor', 'limit']) && page() && membership();
    if (path === '/teaching/offerings') return only(['membership', 'course_id', 'cursor', 'limit']) && page() && membership()
        && (!query.has('course_id') || teachingIdentifier(query.get('course_id')));
    if (path === '/teaching/receipts') {
        const action = query.get('action'), scope = query.get('scope_type');
        return keys.length === 4 && only(['action', 'scope_type', 'scope_id', 'key'])
            && Object.hasOwn(B1_RECOVERY_SCOPES, action) && B1_RECOVERY_SCOPES[action] === scope
            && teachingIdentifier(query.get('scope_id'), scope === 'institution' ? 64 : 36)
            && /^[A-Za-z0-9._:-]{8,128}$/.test(query.get('key') || '');
    }
    // Exactly the ten public B2 GET templates. B1 keeps its separate cursor
    // grammar, and protected/private/preview/recipient routes remain closed.
    const assessment = /^\/teaching\/(?:offerings\/([^/]+)\/(assignments|releases)|assignments\/([^/]+)\/(draft|versions)(?:\/([^/]+))?|releases\/([^/]+)(?:\/(my-submission-head|my-submissions|submissions))?|submissions\/([^/]+))$/.exec(path);
    if (assessment) {
        const ids = [assessment[1], assessment[3], assessment[5], assessment[6], assessment[8]].filter(value => value !== undefined);
        if (ids.some(segment => {
            try { const id = decodeURIComponent(segment); return !teachingIdentifier(id) || encodeURIComponent(id) !== segment; }
            catch { return true; }
        })) return false;
        if (assessment[5] && assessment[4] !== 'versions') return false;
        const paged = !!assessment[2] || assessment[4] === 'versions' && !assessment[5]
            || ['my-submissions', 'submissions'].includes(assessment[7]);
        if (!paged) return keys.length === 0;
        const teacher = assessment[7] === 'submissions';
        return only(['limit', 'cursor', ...(teacher ? ['student_id'] : [])])
            && (!query.has('limit') || /^(?:[1-9]|[1-9][0-9]|100)$/.test(query.get('limit')))
            && (!query.has('cursor') || isAssessmentCursor(query.get('cursor')))
            && (!query.has('student_id') || isAssessmentSubject(query.get('student_id')));
    }
    const match = /^\/teaching\/(courses|offerings|receipts)\/([^/]+)(?:\/(enrollment|roster|roles))?$/.exec(path);
    if (!match) return false;
    let id;
    try { id = decodeURIComponent(match[2]); } catch { return false; }
    if (!teachingIdentifier(id) || encodeURIComponent(id) !== match[2]) return false;
    if (match[3] && match[1] !== 'offerings') return false;
    return match[3] === 'roster' ? only(['cursor', 'limit']) && page() : keys.length === 0;
}

// This branch is deliberately before all legacy URL/error construction and
// logging. It cannot accept public headers, bodies, foreign routes or writes.
async function teachingGet(url, options) {
    if (!registeredTeachingRead(url) || ![Object.prototype, null].includes(Object.getPrototypeOf(options))
        || Reflect.ownKeys(options).some(key => !['teachingTransport', 'method', 'signal'].includes(key)
            || !Object.hasOwn(Object.getOwnPropertyDescriptor(options, key), 'value'))
        || (options.method !== undefined && options.method !== 'GET')
        || (options.signal !== undefined && !(options.signal instanceof AbortSignal))) {
        throw createTeachingError('validation_error');
    }
    // Caller options are mutable; the validated signal is request-local.
    const signal = options.signal;
    let token, status = 0, phase = 'session';
    const current = () => !signal?.aborted && (localStorage.getItem('token') || '') === (token || '');
    const fence = () => { if (!current()) throw createTeachingError('request_aborted'); };
    try {
        token = localStorage.getItem('token');
        const headers = { 'Content-Type': 'application/json' };
        if (token) headers.Authorization = `Bearer ${token}`;
        fence();
        phase = 'fetch';
        const response = await fetch(`${API_BASE_URL}${url}`, { method: 'GET', headers, ...(signal ? { signal } : {}) });
        fence();
        status = Number.isInteger(response.status) && response.status >= 100 && response.status <= 599 ? response.status : 0;
        phase = 'body';
        const text = await response.text();
        fence();
        let envelope;
        try { envelope = JSON.parse(text); } catch { envelope = null; }
        const object = envelope != null && typeof envelope === 'object' && !Array.isArray(envelope);
        if (status < 200 || status >= 300) {
            if (status === 401) {
                const currentToken = localStorage.getItem('token') || '';
                const currentAuthorization = currentToken ? `Bearer ${currentToken}` : '';
                if (!signal?.aborted && (headers.Authorization || '') === currentAuthorization) {
                    window.dispatchEvent(new CustomEvent('auth-expired'));
                }
            }
            const consistent = object && envelope.code === status;
            const correlation = consistent ? envelope.data?.correlation_id : undefined;
            const queryValues = [...new URLSearchParams(url.split('?')[1] || '').values()];
            const routeValues = url.split('?')[0].split('/').filter(Boolean).map(segment => decodeURIComponent(segment));
            const privateValues = [token, ...queryValues, ...routeValues];
            // Shape validation alone is insufficient when a UUID-shaped
            // locator/key/token is reflected into the correlation field.
            throw createTeachingError(consistent ? safeTeachingHttpReason(envelope.message) : 'request_failed', status,
                privateValues.includes(correlation) ? undefined : correlation);
        }
        if (status !== 200 || !object || envelope.code !== 200 || envelope.message !== 'ok'
            || Object.keys(envelope).length !== 3 || !Object.hasOwn(envelope, 'data')) {
            throw createTeachingError('invalid_response', status);
        }
        return { httpStatus: status, envelope };
    } catch (error) {
        // Never expose a caught exception, body or its cause. Session changes
        // take precedence over any pending reply, including a late 401.
        let sameSession;
        try { sameSession = current(); } catch { throw createTeachingError('request_failed', status); }
        if (!sameSession) throw createTeachingError('request_aborted');
        if (error?.name === 'TeachingError' || error?.name === 'AbortError' && error?.reason === 'request_aborted') {
            throw createTeachingError(error.reason, error.status, error.correlationId);
        }
        throw createTeachingError(phase === 'fetch' ? 'network_error' : 'request_failed', status);
    }
}

/**
 * 统一的 Fetch 网络请求封装
 * @param {string} url - 请求路径（自动拼接 API_BASE_URL）
 * @param {object} options - Fetch 配置项（支持 isStream 标识流式请求）
 * @returns {Promise<any>}
 */
export const request = async (url, options = {}) => {
    if (options.teachingTransport === true) return teachingGet(url, options);
    const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData;
    const defaultHeaders = {};
    
    if (!isFormData) {
        defaultHeaders['Content-Type'] = 'application/json';
    }

    // 自动携带 Token
    const token = localStorage.getItem('token');
    if (token) {
        defaultHeaders['Authorization'] = `Bearer ${token}`;
    }

    const config = {
        ...options,
        headers: {
            ...defaultHeaders,
            ...options.headers
        }
    };

    // 支持全链接覆盖
    const fullUrl = url.startsWith('http') ? url : `${API_BASE_URL}${url}`;

    const requireCurrentSession = () => {
        if (config.signal?.aborted || (localStorage.getItem('token') || '') !== (token || '')) {
            const error = new Error('Session changed while request was pending');
            error.name = 'AbortError';
            throw error;
        }
    };
    try {
        requireCurrentSession();
        const response = await fetch(fullUrl, config);
        requireCurrentSession();
        
        // 1. 如果是流式请求，或者预期返回二进制，直接返回 response
        if (response.ok && (options.isStream || config.headers.Accept === 'application/octet-stream')) {
            return response;
        }

        // 2. 尝试解析 JSON，如果为空可能导致错误
        let data;
        const text = await response.text();
        requireCurrentSession();
        if (text) {
            try {
                data = JSON.parse(text);
            } catch (e) {
                data = text;
            }
        }

        // 3. 处理全局响应状态码（差异化错误信息）
        if (!response.ok) {
            let message;
            if (response.status === 401) {
                const currentToken = localStorage.getItem('token') || '';
                const currentAuthorization = currentToken ? `Bearer ${currentToken}` : '';
                const requestAuthorization = config.headers.Authorization || config.headers.authorization || '';
                if (!config.signal?.aborted && requestAuthorization === currentAuthorization) {
                    window.dispatchEvent(new CustomEvent('auth-expired'));
                }
                message = '登录已过期，请重新登录';
            } else if (response.status === 403) {
                message = data?.detail || data?.message || '没有权限执行此操作';
            } else if (response.status === 404) {
                message = data?.detail || data?.message || '请求的资源不存在';
            } else if (response.status >= 500) {
                message = data?.detail || data?.message || '服务器内部错误，请稍后重试';
            } else {
                message = data?.detail || data?.message || data?.error ||
                    `HTTP error! status: ${response.status}`;
            }
            const error = new Error(message);
            error.status = response.status;
            throw error;
        }
        
        return data;
    } catch (error) {
        if (error instanceof TypeError && /fetch/i.test(error.message || '')) {
            error.message = `无法连接后端服务（${fullUrl}）。请确认服务正在运行，并检查浏览器跨域设置。`;
        }
        console.error(`[API Request Error] ${fullUrl}:`, error);
        throw error;
    }
};

/**
 * 调用后端 API，自动解包 {code, message, data} 标准响应
 * @param {string} url
 * @param {object} options
 * @returns {Promise<any>}
 */
export async function apiRequest(url, options = {}) {
    const json = await request(url, options);
    if (json && json.code === 200) return json.data;
    throw new Error(json?.message || json?.detail || 'API 请求失败');
}

export default request;
