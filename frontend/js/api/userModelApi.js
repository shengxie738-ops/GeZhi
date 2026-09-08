import request from '../utils/request.js';

/**
 * 获取当前登录用户的自定义模型配置列表
 */
export async function getUserCustomModels() {
    return request('/user/models', { method: 'GET' });
}

/**
 * 新增自定义大模型配置
 * @param {Object} data - { provider, api_type, base_url, api_key, model_ids, is_active }
 */
export async function createUserCustomModel(data) {
    return request('/user/models', {
        method: 'POST',
        body: JSON.stringify(data)
    });
}

/**
 * 更新已有自定义大模型配置
 * @param {string} id - 配置记录 ID
 * @param {Object} data - 需要更新的字段
 */
export async function updateUserCustomModel(id, data) {
    return request(`/user/models/${encodeURIComponent(id)}`, {
        method: 'PUT',
        body: JSON.stringify(data)
    });
}

/**
 * 删除自定义大模型配置
 * @param {string} id - 配置记录 ID
 */
export async function deleteUserCustomModel(id) {
    return request(`/user/models/${encodeURIComponent(id)}`, {
        method: 'DELETE'
    });
}

/**
 * 测试自定义大模型 Base URL 与 API Key 连通性
 * @param {Object} data - { base_url, api_key, model_id, provider }
 */
export async function testCustomModelConnection(data) {
    return request('/user/models/test', {
        method: 'POST',
        body: JSON.stringify(data)
    });
}
