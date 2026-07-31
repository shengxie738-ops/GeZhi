from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, Literal

from langchain_openai import ChatOpenAI


ModelCategory = Literal["text", "image"]


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
        return data


QWEN_API_KEY = "***REMOVED***"
SPARK_TEXT_BASE_URL = "https://spark-api-open.xf-yun.com/v1"
QWEN_TEXT_BASE_URL = "https://ws-ormgvfkztc6f2p76.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
QWEN_IMAGE_BASE_URL = "https://ws-ormgvfkztc6f2p76.cn-beijing.maas.aliyuncs.com/api/v1"
ZHIPU_API_KEY = "d7fd9d0ad4fe49268afbfb8fc7a817b3.EgjG4hmHkeMFcrnN"
ZHIPU_TEXT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
IMAGE_GENERATION_ENDPOINT = "/services/aigc/multimodal-generation/generation"


_MODEL_CONFIGS: dict[str, AIModelConfig] = {
    "spark Ultra-32K": AIModelConfig(
        model_id="spark Ultra-32K",
        label="Spark 4.0Ultra",
        provider="讯飞星火",
        category="text",
        base_url=SPARK_TEXT_BASE_URL,
        api_key="***REMOVED***",
        api_model="4.0Ultra",
        hint="长上下文",
    ),
    "spark Lite": AIModelConfig(
        model_id="spark Lite",
        label="Spark Lite",
        provider="讯飞星火",
        category="text",
        base_url=SPARK_TEXT_BASE_URL,
        api_key="***REMOVED***",
        api_model="lite",
        hint="轻量响应",
    ),
    "spark-x": AIModelConfig(
        model_id="spark-x",
        label="Spark Max (generalv3.5)",
        provider="讯飞星火",
        category="text",
        base_url=SPARK_TEXT_BASE_URL,
        api_key="***REMOVED***",
        api_model="generalv3.5",
        hint="通用对话",
    ),
    "mimo-v2.5": AIModelConfig(
        model_id="mimo-v2.5",
        label="mimo-v2.5",
        provider="小米 MiMo",
        category="text",
        base_url="https://token-plan-cn.xiaomimimo.com/v1",
        api_key="***REMOVED***",
        hint="中文推理",
    ),
    "qwen3.7-plus": AIModelConfig(
        model_id="qwen3.7-plus",
        label="qwen3.7-plus",
        provider="阿里云百炼",
        category="text",
        base_url=QWEN_TEXT_BASE_URL,
        api_key=QWEN_API_KEY,
        hint="综合讲解",
    ),
    "qwen3.7-max": AIModelConfig(
        model_id="qwen3.7-max",
        label="qwen3.7-max",
        provider="阿里云百炼",
        category="text",
        base_url=QWEN_TEXT_BASE_URL,
        api_key=QWEN_API_KEY,
        hint="复杂规划",
    ),
    "qwen3.6-plus": AIModelConfig(
        model_id="qwen3.6-plus",
        label="qwen3.6-plus",
        provider="阿里云百炼",
        category="text",
        base_url=QWEN_TEXT_BASE_URL,
        api_key=QWEN_API_KEY,
        hint="稳定检索",
    ),
    "qwen3.6-max-preview": AIModelConfig(
        model_id="qwen3.6-max-preview",
        label="qwen3.6-max-preview",
        provider="阿里云百炼",
        category="text",
        base_url=QWEN_TEXT_BASE_URL,
        api_key=QWEN_API_KEY,
        hint="高阶推理",
    ),
    "qwen3.5-plus": AIModelConfig(
        model_id="qwen3.5-plus",
        label="qwen3.5-plus",
        provider="阿里云百炼",
        category="text",
        base_url=QWEN_TEXT_BASE_URL,
        api_key=QWEN_API_KEY,
        hint="日常问答",
    ),
    "deepseek-v4-pro": AIModelConfig(
        model_id="deepseek-v4-pro",
        label="deepseek-v4-pro",
        provider="阿里云百炼",
        category="text",
        base_url=QWEN_TEXT_BASE_URL,
        api_key=QWEN_API_KEY,
        hint="深度分析",
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
    "glm-4.5-air": AIModelConfig(
        model_id="glm-4.5-air",
        label="glm-4.5-air",
        provider="智谱 AI",
        category="text",
        base_url=ZHIPU_TEXT_BASE_URL,
        api_key=ZHIPU_API_KEY,
        hint="轻量响应",
    ),
    "glm-4.7": AIModelConfig(
        model_id="glm-4.7",
        label="glm-4.7",
        provider="智谱 AI",
        category="text",
        base_url=ZHIPU_TEXT_BASE_URL,
        api_key=ZHIPU_API_KEY,
        hint="通用对话",
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
    "kimi-k2.7-code": AIModelConfig(
        model_id="kimi-k2.7-code",
        label="kimi-k2.7-code",
        provider="阿里云百炼",
        category="text",
        base_url=QWEN_TEXT_BASE_URL,
        api_key=QWEN_API_KEY,
        hint="代码生成",
    ),
    "qwen-image-2.0": AIModelConfig(
        model_id="qwen-image-2.0",
        label="qwen-image-2.0",
        provider="阿里云百炼",
        category="image",
        base_url=QWEN_IMAGE_BASE_URL,
        endpoint=IMAGE_GENERATION_ENDPOINT,
        api_key=QWEN_API_KEY,
    ),
    "qwen-image-2.0-pro": AIModelConfig(
        model_id="qwen-image-2.0-pro",
        label="qwen-image-2.0-pro",
        provider="阿里云百炼",
        category="image",
        base_url=QWEN_IMAGE_BASE_URL,
        endpoint=IMAGE_GENERATION_ENDPOINT,
        api_key=QWEN_API_KEY,
    ),
    "qwen-image-max": AIModelConfig(
        model_id="qwen-image-max",
        label="qwen-image-max",
        provider="阿里云百炼",
        category="image",
        base_url=QWEN_IMAGE_BASE_URL,
        endpoint=IMAGE_GENERATION_ENDPOINT,
        api_key=QWEN_API_KEY,
    ),
    "z-image-turbo": AIModelConfig(
        model_id="z-image-turbo",
        label="z-image-turbo",
        provider="阿里云 DashScope",
        category="image",
        base_url="https://dashscope.aliyuncs.com/api/v1",
        endpoint=IMAGE_GENERATION_ENDPOINT,
        api_key=QWEN_API_KEY,
    ),
}


def _resolve_registry_key(model_id: str | None) -> str:
    requested = (model_id or "").strip()
    if requested in _MODEL_CONFIGS:
        return requested

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
    return client_factory(
        model=provider_model,
        openai_api_key=config.api_key,
        openai_api_base=config.base_url,
        base_url=config.base_url,
        temperature=temperature,
    )
