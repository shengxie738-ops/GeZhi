import { ref, reactive, computed } from 'vue';
import { DEFAULT_AGENT_MODEL, DEFAULT_IMAGE_MODEL, DEFAULT_OMNI_MODEL, DISABLED_MODEL_IDS, IMAGE_MODEL_OPTIONS, OMNI_MODEL_OPTIONS, TEXT_MODEL_OPTIONS, mergeModelOptions } from '../config/aiModels.js';
import { agentApi } from '../api/agents.js';
import request from '../utils/request.js';

export function useAgents(showToast) {
    const agents = ref([]);
    const textModelOptions = ref([...TEXT_MODEL_OPTIONS]);
    const imageModelOptions = ref([...IMAGE_MODEL_OPTIONS]);
    const omniModelOptions = ref([...OMNI_MODEL_OPTIONS]);
    const showAgentModal = ref(false);
    const isEditingAgent = ref(false);

    const agentForm = reactive({
        id: '',
        name: '',
        role: '',
        prompt: '',
        model: DEFAULT_AGENT_MODEL,
        modelCategory: 'text',
        colorClass: 'bg-blue-500',
        icon: 'ph-robot',
        isActive: true,
        isThinking: false
    });

    const getAgentModelOptions = (agent) => {
        if (agent?.modelCategory === 'image') return imageModelOptions.value;
        if (agent?.modelCategory === 'omni') return omniModelOptions.value;
        return textModelOptions.value;
    };

    const getDefaultModelForCategory = (modelCategory) => {
        if (modelCategory === 'image') return DEFAULT_IMAGE_MODEL;
        if (modelCategory === 'omni') return DEFAULT_OMNI_MODEL;
        return DEFAULT_AGENT_MODEL;
    };

    const activeAgentModelOptions = computed(() => getAgentModelOptions(agentForm));

    const normalizeBackendModel = (model) => ({
        id: model.id,
        label: model.label || model.id,
        provider: model.provider || '',
        baseUrl: model.base_url || model.baseUrl || '',
        apiModel: model.api_model || model.apiModel || '',
        hint: model.hint || ''
    });

    const loadBackendModelOptions = async () => {
        try {
            const payload = await request('/ai/models');
            const data = payload?.data || {};
            if (Array.isArray(data.text)) {
                textModelOptions.value = mergeModelOptions(
                    data.text.map(normalizeBackendModel),
                    TEXT_MODEL_OPTIONS
                );
            }
            if (Array.isArray(data.image)) {
                imageModelOptions.value = mergeModelOptions(
                    data.image.map(normalizeBackendModel),
                    IMAGE_MODEL_OPTIONS
                );
            }
            if (Array.isArray(data.omni)) {
                omniModelOptions.value = mergeModelOptions(
                    data.omni.map(normalizeBackendModel),
                    OMNI_MODEL_OPTIONS
                );
            }
        } catch (error) {
            console.info('[Agents] Backend model registry unavailable, using local model options.', error);
        }
    };

    const loadBackendAgents = async () => {
        try {
            const payload = await agentApi.getAgents();
            if (Array.isArray(payload?.data)) {
                agents.value = payload.data.map(agent => {
                    if (!agent.model || DISABLED_MODEL_IDS.has(agent.model)) {
                        return {
                            ...agent,
                            model: getDefaultModelForCategory(agent.modelCategory)
                        };
                    }
                    return agent;
                });
            }
        } catch (error) {
            showToast?.('智能体配置加载失败，请重试', 'error');
        }
    };

    loadBackendAgents();
    loadBackendModelOptions();

    const openAgentModal = (agent = null) => {
        if (agent) {
            isEditingAgent.value = true;
            Object.assign(agentForm, {
                modelCategory: 'text',
                ...JSON.parse(JSON.stringify(agent))
            });
        } else {
            isEditingAgent.value = false;
            Object.assign(agentForm, {
                id: `agent_custom_${Date.now()}`,
                name: '',
                role: '',
                prompt: '',
                model: DEFAULT_AGENT_MODEL,
                modelCategory: 'text',
                colorClass: 'bg-blue-500',
                icon: 'ph-robot',
                isActive: true,
                isThinking: false
            });
        }
        showAgentModal.value = true;
    };

    const closeAgentModal = () => {
        showAgentModal.value = false;
    };

    const updateAgentModel = async (agent, modelId) => {
        const options = getAgentModelOptions(agent);
        if (!agent || !options.some((model) => model.id === modelId)) {
            return;
        }
        try {
            await agentApi.saveAgentConfig(agent.id, { ...agent, model: modelId });
            agent.model = modelId;
            showToast?.(`Agent [${agent.name}] 已保存为 ${modelId}`, 'success');
        } catch (error) {
            showToast?.('模型切换未保存，请重试', 'error');
        }
    };

    const saveAgent = async () => {
        if (!agentForm.name || !agentForm.prompt) {
            return showToast('Agent名称和核心指令不能为空', 'error');
        }
        const nextAgent = { ...agentForm };
        try {
            await agentApi.saveAgentConfig(nextAgent.id, nextAgent);
        } catch (error) {
            showToast('配置未保存，请检查连接后重试', 'error');
            return;
        }
        const index = agents.value.findIndex(a => a.id === nextAgent.id);
        if (index >= 0) agents.value[index] = nextAgent;
        else agents.value.push(nextAgent);
        showToast(`Agent [${agentForm.name}] 配置已保存`, 'success');
        closeAgentModal();
    };

    const deleteAgent = async () => {
        if (confirm(`确定要移除节点 [${agentForm.name}] 吗？`)) {
            try {
                await agentApi.deleteAgentConfig(agentForm.id);
            } catch (error) {
                showToast('删除失败，配置已保留', 'error');
                return;
            }
            agents.value = agents.value.filter(a => a.id !== agentForm.id);
            showToast('Agent 节点已成功下线');
            closeAgentModal();
        }
    };

    const unavailableAgent = Object.freeze({ name: '智能体配置不可用', role: '未加载', icon: 'ph-warning', colorClass: 'bg-slate-400', isActive: false, model: '', prompt: '' });
    const getAgentInfo = (id) => {
        return agents.value.find(a => a.id === id) || unavailableAgent;
    };

    const getAgentInfoBySource = (source) => {
        return agents.value.find(a => (a.name || '').toLowerCase() === (source || '').toLowerCase()) || unavailableAgent;
    };

    return {
        agents,
        textModelOptions,
        imageModelOptions,
        omniModelOptions,
        activeAgentModelOptions,
        showAgentModal,
        isEditingAgent,
        agentForm,
        getAgentModelOptions,
        getDefaultModelForCategory,
        loadBackendAgents,
        loadBackendModelOptions,
        openAgentModal,
        closeAgentModal,
        updateAgentModel,
        saveAgent,
        deleteAgent,
        getAgentInfo,
        getAgentInfoBySource
    };
}
