export const TEXT_MODEL_OPTIONS = [
    // ---- 讯飞星火 Spark 系列 ----
    {
        id: 'spark Ultra-32K',
        label: 'spark Ultra-32K',
        provider: '讯飞星火',
        baseUrl: 'https://spark-api-open.xf-yun.com/v1',
        hint: '顶级认知大模型'
    },
    {
        id: 'spark Lite',
        label: 'spark Lite',
        provider: '讯飞星火',
        baseUrl: 'https://spark-api-open.xf-yun.com/v1',
        hint: '轻量极速'
    },
    {
        id: 'spark-x',
        label: 'spark-x',
        provider: '讯飞星火',
        baseUrl: 'https://spark-api-open.xf-yun.com/v1',
        hint: '主流推理'
    },

    // ---- 阿里云百炼系列（仅保留未欠费的原生可用模型） ----
    {
        id: 'qwen3.8-max',
        label: 'qwen3.8-max',
        provider: '阿里云百炼',
        baseUrl: 'https://ws-ormgvfkztc6f2p76.cn-beijing.maas.aliyuncs.com/compatible-mode/v1',
        hint: '旗舰推理',
        enableThinking: true
    },
    {
        id: 'qwen3.8-max-0902',
        label: 'qwen3.8-max-0902',
        provider: '阿里云百炼',
        baseUrl: 'https://ws-ormgvfkztc6f2p76.cn-beijing.maas.aliyuncs.com/compatible-mode/v1',
        hint: '长效推理',
        enableThinking: true
    },
    {
        id: 'qwen3.7-flash',
        label: 'qwen3.7-flash',
        provider: '阿里云百炼',
        baseUrl: 'https://ws-ormgvfkztc6f2p76.cn-beijing.maas.aliyuncs.com/compatible-mode/v1',
        hint: '极速轻量',
        enableThinking: true
    },
    {
        id: 'qwen3.8-flash',
        label: 'qwen3.8-flash',
        provider: '阿里云百炼',
        baseUrl: 'https://ws-ormgvfkztc6f2p76.cn-beijing.maas.aliyuncs.com/compatible-mode/v1',
        hint: '极速响应',
        enableThinking: true
    },
    {
        id: 'deepseek-v4-pro-0813',
        label: 'deepseek-v4-pro-0813',
        provider: '阿里云百炼',
        baseUrl: 'https://ws-ormgvfkztc6f2p76.cn-beijing.maas.aliyuncs.com/compatible-mode/v1',
        hint: '深度分析'
    },
    {
        id: 'deepseek-v4-flash-0731',
        label: 'deepseek-v4-flash-0731',
        provider: '阿里云百炼',
        baseUrl: 'https://ws-ormgvfkztc6f2p76.cn-beijing.maas.aliyuncs.com/compatible-mode/v1',
        hint: '极速推理',
        enableThinking: true
    },
    {
        id: 'kimi-k2.7-code',
        label: 'kimi-k2.7-code',
        provider: '阿里云百炼',
        baseUrl: 'https://ws-ormgvfkztc6f2p76.cn-beijing.maas.aliyuncs.com/compatible-mode/v1',
        hint: '代码生成'
    },
    {
        id: 'kimi-k3',
        label: 'kimi-k3',
        provider: '阿里云百炼',
        baseUrl: 'https://ws-ormgvfkztc6f2p76.cn-beijing.maas.aliyuncs.com/compatible-mode/v1',
        hint: '长文本理解'
    },
    {
        id: 'glm-5.2',
        label: 'glm-5.2',
        provider: '阿里云百炼',
        baseUrl: 'https://ws-ormgvfkztc6f2p76.cn-beijing.maas.aliyuncs.com/compatible-mode/v1',
        hint: '通用协作'
    },

    // ---- 智谱 AI 原生系列 ----
    {
        id: 'glm-5.1',
        label: 'glm-5.1',
        provider: '智谱 AI',
        baseUrl: 'https://open.bigmodel.cn/api/paas/v4',
        hint: '逻辑推理',
        enableThinking: true
    },
    {
        id: 'glm-4-flash',
        label: 'glm-4-flash',
        provider: '智谱 AI',
        baseUrl: 'https://open.bigmodel.cn/api/paas/v4',
        hint: '极速轻量'
    },
    {
        id: 'glm-4-plus',
        label: 'glm-4-plus',
        provider: '智谱 AI',
        baseUrl: 'https://open.bigmodel.cn/api/paas/v4',
        hint: '高阶推理'
    },
    {
        id: 'glm-4.5-air',
        label: 'glm-4.5-air',
        provider: '智谱 AI',
        baseUrl: 'https://open.bigmodel.cn/api/paas/v4',
        hint: '轻量响应'
    },
    {
        id: 'glm-4.6v',
        label: 'glm-4.6v',
        provider: '智谱 AI',
        baseUrl: 'https://open.bigmodel.cn/api/paas/v4',
        hint: '视觉理解'
    }
];

// 欠费生图模型全部删除，不再提供不可用模型选项
export const IMAGE_MODEL_OPTIONS = [];

// 全模态语音与高精口语评测模型（Qwen-Audio & Paraformer 系列）：口语训练专属
export const OMNI_MODEL_OPTIONS = [
    {
        id: 'qwen-audio-3.0-asr-flash',
        label: 'qwen-audio-3.0-asr-flash',
        provider: '阿里云百炼',
        baseUrl: 'https://ws-ormgvfkztc6f2p76.cn-beijing.maas.aliyuncs.com/api/v1',
        hint: '极速多模态语音'
    },
    {
        id: 'paraformer-v2',
        label: 'paraformer-v2',
        provider: '阿里达摩院',
        baseUrl: 'https://dashscope.aliyuncs.com/api/v1',
        hint: '高精通用语音'
    },
    {
        id: 'paraformer-v1',
        label: 'paraformer-v1',
        provider: '阿里达摩院',
        baseUrl: 'https://dashscope.aliyuncs.com/api/v1',
        hint: '标准通用语音'
    },
    {
        id: 'paraformer-mtl-v1',
        label: 'paraformer-mtl-v1',
        provider: '阿里达摩院',
        baseUrl: 'https://dashscope.aliyuncs.com/api/v1',
        hint: '多语种语音'
    },
    {
        id: 'paraformer-8k-v2',
        label: 'paraformer-8k-v2',
        provider: '阿里达摩院',
        baseUrl: 'https://dashscope.aliyuncs.com/api/v1',
        hint: '8K电话音质'
    }
];

export const DEFAULT_AGENT_MODEL = 'qwen3.8-max';
export const DEFAULT_IMAGE_MODEL = '';
export const DEFAULT_OMNI_MODEL = 'qwen-audio-3.0-asr-flash';

export const DISABLED_MODEL_IDS = new Set([
    'deepseek-v4-pro',
    'deepseek-v4-flash',
    'qwen3.7-plus',
    'qwen3.7-max',
    'qwen3.6-plus',
    'qwen3.6-max-preview',
    'qwen3.5-plus',
    'mimo-v2.5',
    'qwen-image-2.0',
    'qwen-image-2.0-pro',
    'qwen-image-max',
    'z-image-turbo',
    'qwen3.5-omni-flash',
    'qwen3.5-omni-plus',
    'qwen-omni-turbo',
    'qwen3-omni-flash-2025-12-01'
]);

export function mergeModelOptions(primaryOptions = [], fallbackOptions = []) {
    const merged = new Map();
    for (const model of fallbackOptions) {
        if (model?.id && !DISABLED_MODEL_IDS.has(model.id)) {
            merged.set(model.id, model);
        }
    }
    for (const model of primaryOptions) {
        if (model?.id && !DISABLED_MODEL_IDS.has(model.id)) {
            merged.set(model.id, model);
        }
    }
    return Array.from(merged.values());
}

export function getTextModelLabel(modelId) {
    if (!modelId || DISABLED_MODEL_IDS.has(modelId)) {
        return DEFAULT_AGENT_MODEL;
    }
    return TEXT_MODEL_OPTIONS.find((model) => model.id === modelId)?.label || modelId || DEFAULT_AGENT_MODEL;
}

export function getImageModelLabel(modelId) {
    if (!modelId || DISABLED_MODEL_IDS.has(modelId)) {
        return DEFAULT_IMAGE_MODEL;
    }
    return IMAGE_MODEL_OPTIONS.find((model) => model.id === modelId)?.label || modelId || DEFAULT_IMAGE_MODEL;
}

export function getOmniModelLabel(modelId) {
    if (!modelId || DISABLED_MODEL_IDS.has(modelId)) {
        return DEFAULT_OMNI_MODEL;
    }
    return OMNI_MODEL_OPTIONS.find((model) => model.id === modelId)?.label || modelId || DEFAULT_OMNI_MODEL;
}
