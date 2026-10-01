import uuid
from sqlalchemy import Boolean, Column, JSON, String, Text, TIMESTAMP, text
from sqlalchemy.sql import func

from app.core.crypto import decrypt_secret, mask_api_key
from app.core.database import Base


class UserCustomAIModel(Base):
    __tablename__ = "user_custom_ai_models"

    id = Column(String(64), primary_key=True, default=lambda: uuid.uuid4().hex, index=True)
    user_id = Column(String(255), nullable=False, index=True)
    provider = Column(String(64), nullable=False, default="OpenAI Compatible")
    api_type = Column(String(64), nullable=False, default="Chat Completions API")
    base_url = Column(String(512), nullable=False)
    encrypted_api_key = Column(Text, nullable=False)
    model_ids = Column(JSON, nullable=False, default=list)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"), onupdate=func.now())

    def get_decrypted_api_key(self) -> str:
        """解密并返回原始 API Key，用于服务端发起 LLM 请求。"""
        return decrypt_secret(self.encrypted_api_key)

    def to_dict(self, mask_key: bool = True) -> dict:
        """序列化输出字典。默认脱敏 API Key。"""
        raw_key = self.get_decrypted_api_key()
        display_key = mask_api_key(raw_key) if mask_key else raw_key
        return {
            "id": self.id,
            "user_id": self.user_id,
            "provider": self.provider,
            "api_type": self.api_type,
            "base_url": self.base_url,
            "api_key": display_key,
            "model_ids": self.model_ids if isinstance(self.model_ids, list) else [],
            "is_active": bool(self.is_active),
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }
