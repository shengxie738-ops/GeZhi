from typing import List, Optional
from urllib.parse import urlparse
from pydantic import BaseModel, Field, field_validator


def clean_and_validate_base_url(url_str: str) -> str:
    trimmed = url_str.strip()
    parsed = urlparse(trimmed)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("接口地址 (Base URL) 必须是包含有效域名的 http:// 或 https:// 完整链接")
    
    # 防范本地/私有内网 SSRF
    hostname = (parsed.hostname or "").lower()
    blocked_hosts = {"localhost", "127.0.0.1", "0.0.0.0", "169.254.169.254", "::1"}
    if hostname in blocked_hosts or hostname.startswith("127."):
        raise ValueError("禁止使用本地或内网回环地址作为大模型端点")

    clean_url = trimmed.rstrip("/")
    # 自动剥离末尾多余的 /chat/completions，防止 SDK 拼接双重路径报 404
    if clean_url.endswith("/chat/completions"):
        clean_url = clean_url[:-len("/chat/completions")].rstrip("/")
    return clean_url


class UserCustomModelCreateRequest(BaseModel):
    provider: str = Field(default="OpenAI Compatible", max_length=64)
    api_type: str = Field(default="Chat Completions API", max_length=64)
    base_url: str = Field(..., max_length=512)
    api_key: str = Field(..., min_length=1, max_length=1024)
    model_ids: List[str] = Field(..., min_length=1)
    is_active: bool = Field(default=True)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: str) -> str:
        return clean_and_validate_base_url(v)

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("API Key 不能为空或纯空白字符")
        return cleaned

    @field_validator("model_ids")
    @classmethod
    def validate_model_ids(cls, v: List[str]) -> List[str]:
        cleaned = [item.strip() for item in v if item and item.strip()]
        if not cleaned:
            raise ValueError("至少需要填写一个有效的 Model ID")
        return list(dict.fromkeys(cleaned))  # 保留顺序去重


class UserCustomModelUpdateRequest(BaseModel):
    provider: Optional[str] = Field(default=None, max_length=64)
    api_type: Optional[str] = Field(default=None, max_length=64)
    base_url: Optional[str] = Field(default=None, max_length=512)
    api_key: Optional[str] = Field(default=None, max_length=1024)
    model_ids: Optional[List[str]] = None
    is_active: Optional[bool] = None

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return clean_and_validate_base_url(v)

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("API Key 不能为空或纯空白字符")
        return cleaned

    @field_validator("model_ids")
    @classmethod
    def validate_model_ids(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return None
        cleaned = [item.strip() for item in v if item and item.strip()]
        if not cleaned:
            raise ValueError("至少需要填写一个有效的 Model ID")
        return list(dict.fromkeys(cleaned))


class TestConnectionRequest(BaseModel):
    base_url: str = Field(..., max_length=512)
    api_key: str = Field(..., max_length=1024)
    model_id: Optional[str] = None
    provider: Optional[str] = "OpenAI Compatible"

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: str) -> str:
        return clean_and_validate_base_url(v)

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("API Key 不能为空或纯空白字符")
        return cleaned
