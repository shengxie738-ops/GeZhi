import { API_BASE_URL } from '../../config/env.js';

/** Academic-only gateway preserving structured provider diagnostics. */
export async function requestAcademicGateway(source, query, options = {}) {
    const headers = { 'Content-Type': 'application/json' };
    const token = typeof localStorage !== 'undefined' ? localStorage.getItem('token') : '';
    const checkActive=()=> {
        const current=typeof localStorage !== 'undefined' ? localStorage.getItem('token') : '';
        if(options.signal?.aborted || current!==token)throw Object.assign(new Error('The operation was aborted'),{name:'AbortError'});
    };
    checkActive();
    if (token) headers.Authorization = `Bearer ${token}`;
    const url = `${API_BASE_URL}/academic/${source}/search?query=${encodeURIComponent(query)}&limit=${options.limit}`;
    const response = await fetch(url, { method: 'GET', headers, signal: options.signal });
    checkActive();
    let data;
    const body = await response.text();
    checkActive();
    try { data = body ? JSON.parse(body) : null; } catch { data = null; }
    if (!response.ok) {
        const detail = data?.detail;
        const message = typeof detail === 'string' ? detail : detail?.message || data?.message || `${source} HTTP ${response.status}`;
        const error = new Error(message);
        error.status = response.status;
        error.source = detail?.source || source;
        error.code = detail?.code || `http_${response.status}`;
        if (detail?.retryAfter !== undefined) error.retryAfter = detail.retryAfter;
        if (response.status === 401 && typeof window !== 'undefined' && typeof CustomEvent !== 'undefined') window.dispatchEvent(new CustomEvent('auth-expired'));
        throw error;
    }
    if (!data || !Array.isArray(data.items)) {
        const error = new Error(`${options.label || source} 返回了无效的文献响应`);
        error.source = source; error.code = 'invalid_response';
        throw error;
    }
    return data;
}
