import { API_BASE_URL } from '../config/env.js';

/**
 * 统一的 Fetch 网络请求封装
 * @param {string} url - 请求路径（自动拼接 API_BASE_URL）
 * @param {object} options - Fetch 配置项（支持 isStream 标识流式请求）
 * @returns {Promise<any>}
 */
export const request = async (url, options = {}) => {
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

    try {
        const response = await fetch(fullUrl, config);
        
        // 1. 如果是流式请求，或者预期返回二进制，直接返回 response
        if (options.isStream || config.headers.Accept === 'application/octet-stream') {
            return response;
        }

        // 2. 尝试解析 JSON，如果为空可能导致错误
        let data;
        const text = await response.text();
        if (text) {
            try {
                data = JSON.parse(text);
            } catch (e) {
                data = text;
            }
        }

        // 3. 处理全局响应状态码（差异化错误信息）
        if (!response.ok) {
            if (response.status === 401) {
                window.dispatchEvent(new CustomEvent('auth-expired'));
                throw new Error('登录已过期，请重新登录');
            }
            if (response.status === 403) {
                throw new Error(data?.detail || data?.message || '没有权限执行此操作');
            }
            if (response.status === 404) {
                throw new Error(data?.detail || data?.message || '请求的资源不存在');
            }
            if (response.status >= 500) {
                throw new Error(data?.detail || data?.message || '服务器内部错误，请稍后重试');
            }
            throw new Error(
                data?.detail || data?.message || data?.error ||
                `HTTP error! status: ${response.status}`
            );
        }
        
        return data;
    } catch (error) {
        console.error(`[API Request Error] ${url}:`, error);
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
