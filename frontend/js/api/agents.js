import request from '../utils/request.js';

async function acknowledgedRequest(path, options, agentId) {
    const result = await request(path, options);
    if (result?.status !== 'success' || result.data?.id !== agentId) throw new Error(result?.message || '智能体配置未获服务器确认');
    return result;
}

export const agentApi = {
    getAgents() {
        return request('/agents');
    },

    saveAgentConfig(agentId, payload) {
        return acknowledgedRequest(`/agents/${encodeURIComponent(agentId)}`, {
            method: 'PUT',
            body: JSON.stringify(payload)
        }, agentId);
    },

    deleteAgentConfig(agentId) {
        return acknowledgedRequest(`/agents/${encodeURIComponent(agentId)}`, {
            method: 'DELETE'
        }, agentId);
    }
};
