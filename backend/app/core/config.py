import json
from typing import Any

from pydantic_settings import BaseSettings


DEFAULT_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://gezhisystem.com",
    "https://www.gezhisystem.com",
]


def parse_cors_origins(value: Any) -> list[str]:
    raw = value if value not in (None, "") else DEFAULT_CORS_ORIGINS
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            raw = DEFAULT_CORS_ORIGINS
        elif text.startswith("["):
            try:
                raw = json.loads(text)
            except json.JSONDecodeError:
                raw = text.split(",")
        else:
            raw = text.split(",")
    if not isinstance(raw, (list, tuple, set)):
        raw = [raw]

    origins: list[str] = []
    seen: set[str] = set()
    for item in raw:
        origin = str(item or "").strip().rstrip("/")
        if not origin or origin in seen:
            continue
        seen.add(origin)
        origins.append(origin)
    return origins

class Settings(BaseSettings):
    APP_SECRET_KEY: str = "change-me-before-production"
    ENVIRONMENT: str = "development"
    BACKEND_PORT: int = 8516
    BACKEND_CORS_ORIGINS: str = ""

    # Operator-managed enrollment. Never infer permissions from editable profiles.
    AGENT_CONFIG_WRITERS: str = "[]"
    FORUM_MODERATOR_IDS: str = "[]"
    TEACHER_STUDENT_ASSIGNMENTS: str = "{}"
    ANALYTICS_RECORDED_TIMEZONE: str = ""

    # B1 structure is prepared explicitly; every teaching stage defaults off.
    TEACHING_ENABLED: bool = False
    TEACHING_ASSIGNMENTS_ENABLED: bool = False
    TEACHING_FEEDBACK_ENABLED: bool = False
    TEACHING_REVISIONS_ENABLED: bool = False
    TEACHING_INSTITUTION_ID: str = ""
    TEACHING_TRUSTED_DELEGATIONS: str = "{}"
    LEARNING_DIAGNOSIS_INTERNAL_TOKEN: str = ""

    # Academic search
    OPENALEX_API_KEY: str = ""
    CROSSREF_MAILTO: str = ""
    ACADEMIC_CACHE_TTL_SECONDS: int = 600
    ACADEMIC_HTTP_TIMEOUT_SECONDS: float = 12.0
    ARXIV_CACHE_TTL_SECONDS: int = 86400
    ARXIV_MIN_INTERVAL_SECONDS: float = 3.0
    ARXIV_HTTP_TIMEOUT_SECONDS: float = 20.0

    # RAGFlow
    RAGFLOW_API_KEY: str
    RAGFLOW_BASE_URL: str
    RAGFLOW_AGENT_ID: str
    RAGFLOW_CHAT_ID: str
    RAGFLOW_DATASET_ID: str
    RAGFLOW_PUBLIC_DATASET_IDS: str
    RAGFLOW_COURSE_DATASETS: str = ""
    
    # LLM
    OPENAI_API_KEY: str
    OPENAI_API_BASE: str
    # 全模态（omni）语音模型 Key；为空时回落到 OPENAI_API_KEY（同一 MaaS 实例）
    QWEN_OMNI_API_KEY: str = ""
    LLM_MODEL: str = "qwen3.8-max"
    LLM_MODEL_MAX: str = "qwen3.8-max"
    LLM_MODEL_FLASH: str = "qwen3.7-flash"

    # Alibaba DashScope（语音识别 paraformer / Qwen-Audio）；Key 仅从 .env 注入
    DASHSCOPE_API_KEY: str = ""

    # Teacher Work defaults: explicit schema, real transactions and private storage required.
    # These declarations do not activate deployment or certify readiness.
    TEACHER_WORK_ENABLED: bool = False
    TEACHER_WORK_PRIVATE_TASKS_ENABLED: bool = False
    TEACHER_WORK_PRIVATE_CHAT_ENABLED: bool = False
    TEACHER_WORK_PRIVATE_MATERIALS_ENABLED: bool = False
    TEACHER_WORK_STORAGE_ROOT: str = ""
    TEACHER_WORK_MAX_ACTIVE_RUNS: int = 4
    TEACHER_WORK_PACKAGE_TIMEOUT_SECONDS: int = 300
    TEACHER_WORK_REFERENCE_TIMEOUT_SECONDS: int = 45
    TEACHER_WORK_FILE_TIMEOUT_SECONDS: int = 30
    TEACHER_WORK_MAX_FILE_BYTES: int = 10485760
    TEACHER_WORK_OWNER_QUOTA_BYTES: int = 209715200

    # Teacher AI lesson preparation
    AI_LESSON_PREP_API_KEY: str = ""
    # 模型广场（model_registry）使用的智谱 Key；为空时回落到 AI_LESSON_PREP_API_KEY
    ZHIPU_MODEL_API_KEY: str = ""
    AI_LESSON_PREP_BASE_URL: str = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    AI_LESSON_PREP_MODEL: str = "glm-4.5-air"
    AI_LESSON_PREP_MAX_INPUT_TOKENS: int = 81920
    AI_LESSON_PREP_MAX_OUTPUT_TOKENS: int = 49152
    AI_LESSON_PREP_TIMEOUT_SECONDS: int = 90
    COURSEWARE_FRONTEND_ROOT: str = ""
    LLM_MODEL_DEFAULT: str = "qwen3.7-flash"  # 作业/考试/学情分析默认使用的模型

    # iFlytek Spark (科大讯飞星火)；Key 仅从 .env 注入，禁止硬编码
    SPARK_API_KEY_ULTRA: str = ""
    SPARK_API_KEY_LITE: str = ""
    SPARK_API_KEY_X: str = ""
    SPARK_BASE_URL: str = "https://spark-api-open.xf-yun.com/v1"

    # Xiaomi Mimo (小米大模型)；Key 仅从 .env 注入，禁止硬编码
    MIMO_API_KEY: str = ""
    MIMO_BASE_URL: str = "https://token-plan-cn.xiaomimimo.com/v1"

    # Qwen image generation
    QWEN_IMAGE_ENABLED: bool = False
    QWEN_IMAGE_API_KEY: str = ""
    QWEN_IMAGE_BASE_URL: str = "https://dashscope.aliyuncs.com"
    QWEN_IMAGE_ENDPOINT: str = "/api/v1/services/aigc/multimodal-generation/generation"
    QWEN_IMAGE_MODEL: str = "qwen-image-2.0-pro"
    QWEN_IMAGE_SIZE: str = "1472*1104"
    QWEN_IMAGE_TIMEOUT_SECONDS: int = 30
    QWEN_IMAGE_PROMPT_EXTEND: bool = False
    QWEN_IMAGE_WATERMARK: bool = False

    # SMS verification
    SMS_MOCK_ENABLED: bool = True
    SMS_CODE_EXPIRE_MINUTES: int = 5
    SMS_SEND_COOLDOWN_SECONDS: int = 60
    SMS_MAX_VERIFY_ATTEMPTS: int = 5
    ALIYUN_SMS_REGION_ID: str = "cn-hangzhou"
    ALIYUN_SMS_ENDPOINT: str = "dypnsapi.aliyuncs.com"
    ALIYUN_SMS_ACCESS_KEY_ID: str = ""
    ALIYUN_SMS_ACCESS_KEY_SECRET: str = ""
    ALIYUN_SMS_SIGN_NAME: str = ""
    ALIYUN_SMS_TEMPLATE_CODE: str = ""
    
    # DB
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASS: str = "root"
    DB_NAME: str = "Software_Cup"

    # Gitea code repository integration
    GITEA_ENABLED: bool = False
    GITEA_BASE_URL: str = "http://127.0.0.1:3000"
    GITEA_PUBLIC_BASE_URL: str = "https://gezhisystem.com/gitea"
    GITEA_SSH_DOMAIN: str = "gezhisystem.com"
    GITEA_SSH_PORT: int = 2222
    GITEA_SSH_USER: str = "git"
    GITEA_API_TOKEN: str = ""
    GITEA_ORG: str = "campus"
    GITEA_DEFAULT_PRIVATE: bool = False
    GITEA_WEBHOOK_SECRET: str = "gezhi_webhook_secret_default"
    GITEA_PUBLIC_BACKEND_URL: str = "https://gezhisystem.com"
    GITEA_SYNC_MAX_BRANCHES: int = 20
    
    @property
    def DATABASE_URL(self):
        return f"mysql+pymysql://{self.DB_USER}:{self.DB_PASS}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

settings = Settings()
