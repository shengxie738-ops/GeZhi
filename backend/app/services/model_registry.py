from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, Literal

from langchain_openai import ChatOpenAI

from app.core.config import settings


ModelCategory = Literal["text", "image", "omni"]


@dataclass(frozen=True)
class AIModelConfig:
    model_id: str
    label: str
    provider: str
    category: ModelCategory
    base_url: str
    api_key: str
    api_model: str = ""
    hint: str = ""
    endpoint: str = ""
    enable_thinking: bool = False

    def to_public_dict(self) -> dict:
        data = {
            "id": self.model_id,
            "label": self.label,
            "provider": self.provider,
            "category": self.category,
            "base_url": self.base_url,
        }
        if self.api_model:
            data["api_model"] = self.api_model
        if self.hint:
            data["hint"] = self.hint
        if self.endpoint:
            data["endpoint"] = self.endpoint
        if self.enable_thinking:
            data["enable_thinking"] = True
        return data


# 密钥经 backend/.env 注入（模板见 .env.example），切勿硬编码进仓库
QWEN_API_KEY = settings.OPENAI_API_KEY
QWEN_TEXT_BASE_URL = "https://ws-ormgvfkztc6f2p76.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
# 全模态 omni 模型与文本模型同属一个 MaaS 实例，Key 可独立配置也可复用
QWEN_OMNI_API_KEY = settings.QWEN_OMNI_API_KEY or settings.OPENAI_API_KEY
QWEN_IMAGE_BASE_URL = "https://ws-ormgvfkztc6f2p76.cn-beijing.maas.aliyuncs.com/api/v1"
ZHIPU_API_KEY = settings.ZHIPU_MODEL_API_KEY or settings.AI_LESSON_PREP_API_KEY
ZHIPU_TEXT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
IMAGE_GENERATION_ENDPOINT = "/services/aigc/multimodal-generation/generation"

# 阿里 DashScope / 达摩院语音识别及 Qwen-Audio 端点
DASHSCOPE_API_KEY = settings.DASHSCOPE_API_KEY
DASHSCOPE_ASR_BASE_URL = "https://dashscope.aliyuncs.com/api/v1"
DASHSCOPE_ASR_ENDPOINT = "https://dashscope.aliyuncs.com/api/v1/services/audio/asr/transcription"
QWEN_AUDIO_BASE_URL = "https://ws-ormgvfkztc6f2p76.cn-beijing.maas.aliyuncs.com/api/v1"
QWEN_AUDIO_ENDPOINT = "https://ws-ormgvfkztc6f2p76.cn-beijing.maas.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"

# 讯飞星火 Spark（Key 仅从 .env 注入）
SPARK_API_KEY_ULTRA = settings.SPARK_API_KEY_ULTRA
SPARK_API_KEY_LITE = settings.SPARK_API_KEY_LITE
SPARK_API_KEY_X = settings.SPARK_API_KEY_X
SPARK_BASE_URL = settings.SPARK_BASE_URL

# 小米 Mimo（Key 仅从 .env 注入）
MIMO_API_KEY = settings.MIMO_API_KEY
MIMO_BASE_URL = settings.MIMO_BASE_URL
DASHSCOPE_IMAGE_BASE_URL = "https://dashscope.aliyuncs.com"


_MODEL_CONFIGS: dict[str, AIModelConfig] = {
    # ---- 讯飞星火 Spark 系列 ----
    "spark Ultra-32K": AIModelConfig(
        model_id="spark Ultra-32K",
        label="spark Ultra-32K",
        provider="讯飞星火",
        category="text",
        base_url=SPARK_BASE_URL,
        api_key=SPARK_API_KEY_ULTRA,
        api_model="4.0Ultra",
        hint="顶级认知大模型",
    ),
    "spark Lite": AIModelConfig(
        model_id="spark Lite",
        label="spark Lite",
        provider="讯飞星火",
        category="text",
        base_url=SPARK_BASE_URL,
        api_key=SPARK_API_KEY_LITE,
        api_model="lite",
        hint="轻量极速",
    ),
    "spark-x": AIModelConfig(
        model_id="spark-x",
        label="spark-x",
        provider="讯飞星火",
        category="text",
        base_url=SPARK_BASE_URL,
        api_key=SPARK_API_KEY_X,
        api_model="generalv3.5",
        hint="主流推理",
    ),

    # ---- 阿里云百炼系列（仅保留真实可用、未欠费的原生模型，无任何替代） ----
    "qwen3.8-max": AIModelConfig(
        model_id="qwen3.8-max",
        label="qwen3.8-max",
        provider="阿里云百炼",
        category="text",
        base_url=QWEN_TEXT_BASE_URL,
        api_key=QWEN_API_KEY,
        hint="旗舰推理",
        enable_thinking=True,
    ),
    "qwen3.8-max-0902": AIModelConfig(
        model_id="qwen3.8-max-0902",
        label="qwen3.8-max-0902",
        provider="阿里云百炼",
        category="text",
        base_url=QWEN_TEXT_BASE_URL,
        api_key=QWEN_API_KEY,
        hint="长效推理",
        enable_thinking=True,
    ),
    "qwen3.7-flash": AIModelConfig(
        model_id="qwen3.7-flash",
        label="qwen3.7-flash",
        provider="阿里云百炼",
        category="text",
        base_url=QWEN_TEXT_BASE_URL,
        api_key=QWEN_API_KEY,
        hint="极速轻量",
        enable_thinking=True,
    ),
    "qwen3.8-flash": AIModelConfig(
        model_id="qwen3.8-flash",
        label="qwen3.8-flash",
        provider="阿里云百炼",
        category="text",
        base_url=QWEN_TEXT_BASE_URL,
        api_key=QWEN_API_KEY,
        hint="极速响应",
        enable_thinking=True,
    ),
    "deepseek-v4-pro-0813": AIModelConfig(
        model_id="deepseek-v4-pro-0813",
        label="deepseek-v4-pro-0813",
        provider="阿里云百炼",
        category="text",
        base_url=QWEN_TEXT_BASE_URL,
        api_key=QWEN_API_KEY,
        hint="深度分析",
    ),
    "deepseek-v4-flash-0731": AIModelConfig(
        model_id="deepseek-v4-flash-0731",
        label="deepseek-v4-flash-0731",
        provider="阿里云百炼",
        category="text",
        base_url=QWEN_TEXT_BASE_URL,
        api_key=QWEN_API_KEY,
        hint="极速推理",
        enable_thinking=True,
    ),
    "kimi-k2.7-code": AIModelConfig(
        model_id="kimi-k2.7-code",
        label="kimi-k2.7-code",
        provider="阿里云百炼",
        category="text",
        base_url=QWEN_TEXT_BASE_URL,
        api_key=QWEN_API_KEY,
        hint="代码生成",
    ),
    "kimi-k3": AIModelConfig(
        model_id="kimi-k3",
        label="kimi-k3",
        provider="阿里云百炼",
        category="text",
        base_url=QWEN_TEXT_BASE_URL,
        api_key=QWEN_API_KEY,
        hint="长文本理解",
    ),
    "glm-5.2": AIModelConfig(
        model_id="glm-5.2",
        label="glm-5.2",
        provider="阿里云百炼",
        category="text",
        base_url=QWEN_TEXT_BASE_URL,
        api_key=QWEN_API_KEY,
        hint="通用协作",
    ),

    # ---- 智谱 AI 原生系列 ----
    "glm-5.1": AIModelConfig(
        model_id="glm-5.1",
        label="glm-5.1",
        provider="智谱 AI",
        category="text",
        base_url=ZHIPU_TEXT_BASE_URL,
        api_key=ZHIPU_API_KEY,
        hint="逻辑推理",
        enable_thinking=True,
    ),
    "glm-4-flash": AIModelConfig(
        model_id="glm-4-flash",
        label="glm-4-flash",
        provider="智谱 AI",
        category="text",
        base_url=ZHIPU_TEXT_BASE_URL,
        api_key=ZHIPU_API_KEY,
        hint="极速轻量",
    ),
    "glm-4-plus": AIModelConfig(
        model_id="glm-4-plus",
        label="glm-4-plus",
        provider="智谱 AI",
        category="text",
        base_url=ZHIPU_TEXT_BASE_URL,
        api_key=ZHIPU_API_KEY,
        hint="高阶推理",
    ),
    "glm-4.5-air": AIModelConfig(
        model_id="glm-4.5-air",
        label="glm-4.5-air",
        provider="智谱 AI",
        category="text",
        base_url=ZHIPU_TEXT_BASE_URL,
        api_key=ZHIPU_API_KEY,
        hint="轻量响应",
    ),
    "glm-4.6v": AIModelConfig(
        model_id="glm-4.6v",
        label="glm-4.6v",
        provider="智谱 AI",
        category="text",
        base_url=ZHIPU_TEXT_BASE_URL,
        api_key=ZHIPU_API_KEY,
        hint="视觉理解",
    ),

    # ---- 阿里云百炼与阿里达摩院语音/全模态 omni 系列（口语评测场景） ----
    "qwen-audio-3.0-asr-flash": AIModelConfig(
        model_id="qwen-audio-3.0-asr-flash",
        label="qwen-audio-3.0-asr-flash",
        provider="阿里云百炼",
        category="omni",
        base_url=QWEN_AUDIO_BASE_URL,
        endpoint=QWEN_AUDIO_ENDPOINT,
        api_key=DASHSCOPE_API_KEY,
        hint="极速多模态语音",
    ),
    "paraformer-v2": AIModelConfig(
        model_id="paraformer-v2",
        label="paraformer-v2",
        provider="阿里达摩院",
        category="omni",
        base_url=DASHSCOPE_ASR_BASE_URL,
        endpoint=DASHSCOPE_ASR_ENDPOINT,
        api_key=DASHSCOPE_API_KEY,
        hint="高精通用语音",
    ),
    "paraformer-v1": AIModelConfig(
        model_id="paraformer-v1",
        label="paraformer-v1",
        provider="阿里达摩院",
        category="omni",
        base_url=DASHSCOPE_ASR_BASE_URL,
        endpoint=DASHSCOPE_ASR_ENDPOINT,
        api_key=DASHSCOPE_API_KEY,
        hint="标准通用语音",
    ),
    "paraformer-mtl-v1": AIModelConfig(
        model_id="paraformer-mtl-v1",
        label="paraformer-mtl-v1",
        provider="阿里达摩院",
        category="omni",
        base_url=DASHSCOPE_ASR_BASE_URL,
        endpoint=DASHSCOPE_ASR_ENDPOINT,
        api_key=DASHSCOPE_API_KEY,
        hint="多语种语音",
    ),
    "paraformer-8k-v2": AIModelConfig(
        model_id="paraformer-8k-v2",
        label="paraformer-8k-v2",
        provider="阿里达摩院",
        category="omni",
        base_url=DASHSCOPE_ASR_BASE_URL,
        endpoint=DASHSCOPE_ASR_ENDPOINT,
        api_key=DASHSCOPE_API_KEY,
        hint="8K电话音质",
    ),
}

# 兼容模型 ID 映射（例如 paraformer-v 规范映射到官方全称 paraformer-v1）
LEGACY_MODEL_COMPAT_MAP: dict[str, str] = {
    "paraformer-v": "paraformer-v1",
}


def _resolve_registry_key(model_id: str | None) -> str:
    requested = (model_id or "").strip()
    if requested in _MODEL_CONFIGS:
        return requested

    if requested in LEGACY_MODEL_COMPAT_MAP:
        return LEGACY_MODEL_COMPAT_MAP[requested]

    for registry_key, config in _MODEL_CONFIGS.items():
        if config.api_model and config.api_model == requested:
            return registry_key
    return requested


def get_model_config(model_id: str | None, *, category: ModelCategory = "text") -> AIModelConfig:
    config = _MODEL_CONFIGS.get(_resolve_registry_key(model_id))
    if not config or config.category != category:
        raise ValueError(f"Unsupported {category} model: {model_id}")
    return config


def has_model(model_id: str | None, *, category: ModelCategory = "text") -> bool:
    try:
        get_model_config(model_id, category=category)
        return True
    except ValueError:
        return False


def list_public_models() -> dict[str, list[dict]]:
    return {
        "text": [config.to_public_dict() for config in _MODEL_CONFIGS.values() if config.category == "text"],
        "image": [config.to_public_dict() for config in _MODEL_CONFIGS.values() if config.category == "image"],
        "omni": [config.to_public_dict() for config in _MODEL_CONFIGS.values() if config.category == "omni"],
    }


@lru_cache(maxsize=64)
def _build_cached_chat_model(model_id: str, temperature: float) -> ChatOpenAI:
    return build_chat_model(model_id, temperature=temperature)


def get_cached_chat_model(model_id: str, *, temperature: float = 0.1) -> ChatOpenAI:
    return _build_cached_chat_model(model_id, float(temperature))


def build_chat_model(
    model_id: str,
    *,
    temperature: float = 0.1,
    client_factory: Callable[..., object] = ChatOpenAI,
):
    config = get_model_config(model_id, category="text")
    provider_model = config.api_model or config.model_id
    thinking_kwargs = {"extra_body": {"enable_thinking": True}} if config.enable_thinking else {}
    model_kwargs = {
        "model": provider_model,
        "openai_api_key": config.api_key,
        "openai_api_base": config.base_url,
        "base_url": config.base_url,
    }
    if provider_model != "kimi-k3":
        model_kwargs["temperature"] = temperature
    return client_factory(
        **model_kwargs,
        **thinking_kwargs,
    )


def build_omni_client(model_id: str, *, timeout: float = 180.0, client_factory: Callable[..., object] | None = None):
    """构建全模态 omni 客户端（仅口语场景使用，音频输入走 input_audio data URI）。"""
    from openai import AsyncOpenAI

    factory = client_factory or AsyncOpenAI
    config = get_model_config(model_id, category="omni")
    client = factory(api_key=config.api_key, base_url=config.base_url, timeout=timeout)
    return client, config.api_model or config.model_id


def get_platform_model_metadata_exact(model_id):
    """Non-secret Work port; no trim, legacy aliases, api_model or fallback.

    Deployment credential sources and existing platform construction remain
    unchanged. The caller separately owns the current platform readiness gates.
    """
    from app.services.byok.errors import ByokError
    config = _MODEL_CONFIGS.get(model_id) if type(model_id) is str else None
    if config is None or config.category != 'text' or config.model_id != model_id:
        raise ByokError('MODEL_SELECTION_REQUIRED')
    return {'model_id': config.model_id, 'capabilities': ('text', 'stream', 'tools', 'json')}
