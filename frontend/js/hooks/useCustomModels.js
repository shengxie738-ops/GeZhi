import { reactive, ref } from 'vue';
import {
    createUserCustomModel,
    deleteUserCustomModel,
    testCustomModelConnection,
    updateUserCustomModel,
} from '../api/userModelApi.js';

export function useCustomModels(showToast, onConfigUpdated) {
    const showCustomModelModal = ref(false);
    const customModelModalTab = ref('create'); // 'create' | 'manage'
    const editingConfigId = ref(null);
    const isSaving = ref(false);
    const isTesting = ref(false);
    const isDeleting = ref(false);
    const testResult = ref(null);
    const showApiKey = ref(false);

    const providerOptions = [
        'OpenAI Compatible',
        'DeepSeek',
        'Qwen (通义千问)',
        'Ollama (本地)',
        'SiliconFlow (硅基流动)',
        'Moonshot (Kimi)',
        'Zhipu AI (智谱清言)',
        'Custom (自定义)'
    ];

    const apiTypeOptions = [
        'Chat Completions API',
        'Responses API (Beta)'
    ];

    const form = reactive({
        provider: 'OpenAI Compatible',
        api_type: 'Chat Completions API',
        base_url: '',
        api_key: '',
        model_ids: ['gpt-4o', 'gpt-4o-mini']
    });

    const resetForm = () => {
        form.provider = 'OpenAI Compatible';
        form.api_type = 'Chat Completions API';
        form.base_url = '';
        form.api_key = '';
        form.model_ids = ['gpt-4o', 'gpt-4o-mini'];
        editingConfigId.value = null;
        testResult.value = null;
        showApiKey.value = false;
    };

    const addModelIdInput = () => {
        form.model_ids.push('');
    };

    const removeModelIdInput = (index) => {
        if (form.model_ids.length <= 1) {
            form.model_ids[0] = '';
            return;
        }
        form.model_ids.splice(index, 1);
    };

    const openCustomModelModal = (tab = 'create', configToEdit = null) => {
        customModelModalTab.value = tab;
        testResult.value = null;
        showApiKey.value = false;

        if (configToEdit) {
            editingConfigId.value = configToEdit.id;
            form.provider = configToEdit.provider || 'OpenAI Compatible';
            form.api_type = configToEdit.api_type || 'Chat Completions API';
            form.base_url = configToEdit.base_url || '';
            form.api_key = configToEdit.api_key || '';
            form.model_ids = Array.isArray(configToEdit.model_ids) && configToEdit.model_ids.length > 0
                ? [...configToEdit.model_ids]
                : [''];
        } else {
            resetForm();
        }

        showCustomModelModal.value = true;
    };

    const closeCustomModelModal = () => {
        showCustomModelModal.value = false;
        resetForm();
    };

    const toggleShowApiKey = () => {
        showApiKey.value = !showApiKey.value;
    };

    const handleTestConnection = async () => {
        if (isTesting.value) return;
        const baseUrl = (form.base_url || '').trim().replace(/\/+$/, '');
        const apiKey = (form.api_key || '').trim();
        if (!baseUrl) {
            showToast?.('请先填写接口地址 (Base URL)', 'warning');
            return;
        }
        if (!baseUrl.startsWith('http://') && !baseUrl.startsWith('https://')) {
            showToast?.('接口地址必须以 http:// 或 https:// 开头', 'warning');
            return;
        }
        if (!apiKey) {
            showToast?.('请先填写 API Key', 'warning');
            return;
        }

        let validModels = form.model_ids.map(m => (m || '').trim()).filter(Boolean);
        validModels = [...new Set(validModels)];
        const testModel = validModels[0] || 'default';

        isTesting.value = true;
        testResult.value = null;
        try {
            const res = await testCustomModelConnection({
                base_url: baseUrl,
                api_key: apiKey,
                model_id: testModel,
                provider: form.provider
            });
            testResult.value = res;
            if (res && res.status === 'success') {
                showToast?.(res.message || '连通性测试通过！', 'success');
            } else {
                showToast?.(res?.message || '测试未通过，请检查网络或密钥', 'warning');
            }
        } catch (err) {
            testResult.value = { status: 'error', message: err.message || '网络连接异常' };
            showToast?.(err.message || '测试发生异常', 'error');
        } finally {
            isTesting.value = false;
        }
    };

    const handleSaveModelConfig = async () => {
        if (isSaving.value) return;
        const baseUrl = (form.base_url || '').trim().replace(/\/+$/, '');
        const apiKey = (form.api_key || '').trim();
        let validModels = form.model_ids.map(m => (m || '').trim()).filter(Boolean);
        validModels = [...new Set(validModels)];

        if (!baseUrl) {
            showToast?.('接口地址 (Base URL) 不能为空', 'warning');
            return;
        }
        if (!baseUrl.startsWith('http://') && !baseUrl.startsWith('https://')) {
            showToast?.('接口地址必须以 http:// 或 https:// 开头', 'warning');
            return;
        }
        if (!apiKey) {
            showToast?.('API Key 不能为空', 'warning');
            return;
        }
        if (validModels.length === 0) {
            showToast?.('至少需要填写一个 Model ID', 'warning');
            return;
        }

        isSaving.value = true;
        try {
            const payload = {
                provider: form.provider,
                api_type: form.api_type,
                base_url: baseUrl,
                api_key: apiKey,
                model_ids: validModels,
                is_active: true
            };

            let res;
            if (editingConfigId.value) {
                res = await updateUserCustomModel(editingConfigId.value, payload);
            } else {
                res = await createUserCustomModel(payload);
            }

            if (res && res.status === 'success') {
                showToast?.(editingConfigId.value ? '模型配置更新成功' : '模型配置添加成功', 'success');
                if (typeof onConfigUpdated === 'function') {
                    await onConfigUpdated();
                }
                closeCustomModelModal();
            } else {
                showToast?.(res?.message || '保存失败', 'error');
            }
        } catch (err) {
            showToast?.(err.message || '保存发生异常', 'error');
        } finally {
            isSaving.value = false;
        }
    };

    const handleDeleteModelConfig = async (configId) => {
        if (isDeleting.value) return;
        if (!confirm('确定要删除该自定义大模型配置吗？')) {
            return;
        }
        isDeleting.value = true;
        try {
            const res = await deleteUserCustomModel(configId);
            if (res && res.status === 'success') {
                showToast?.('配置已成功删除', 'success');
                if (typeof onConfigUpdated === 'function') {
                    await onConfigUpdated();
                }
            } else {
                showToast?.(res?.message || '删除失败', 'error');
            }
        } catch (err) {
            showToast?.(err.message || '删除发生异常', 'error');
        } finally {
            isDeleting.value = false;
        }
    };

    return {
        showCustomModelModal,
        customModelModalTab,
        editingConfigId,
        isSaving,
        isTesting,
        testResult,
        showApiKey,
        providerOptions,
        apiTypeOptions,
        customModelForm: form,
        addModelIdInput,
        removeModelIdInput,
        openCustomModelModal,
        closeCustomModelModal,
        toggleShowApiKey,
        handleTestConnection,
        handleSaveModelConfig,
        handleDeleteModelConfig,
    };
}
