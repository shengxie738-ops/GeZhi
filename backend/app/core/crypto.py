import base64
import hashlib
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def _get_fernet_instance() -> Fernet:
    """根据应用 SECRET_KEY 派生确定性的 32 字节 URL-safe base64 密钥并构建 Fernet 实例。"""
    raw_key = getattr(settings, "SECRET_KEY", "gezhi-system-secret-key-salt-2026")
    derived_32bytes = hashlib.sha256(raw_key.encode("utf-8")).digest()
    urlsafe_b64 = base64.urlsafe_b64encode(derived_32bytes)
    return Fernet(urlsafe_b64)


def encrypt_secret(plaintext: str | None) -> str:
    """加密敏感字符串（如 API Key），返回 Fernet 密文字符串。若输入为空则返回空字符串。"""
    if not plaintext:
        return ""
    fernet = _get_fernet_instance()
    encrypted_bytes = fernet.encrypt(plaintext.strip().encode("utf-8"))
    return encrypted_bytes.decode("utf-8")


def decrypt_secret(ciphertext: str | None) -> str:
    """解密敏感密文字符串，返回明文。若密文损坏或解密失败返回空字符串。"""
    if not ciphertext:
        return ""
    try:
        fernet = _get_fernet_instance()
        decrypted_bytes = fernet.decrypt(ciphertext.strip().encode("utf-8"))
        return decrypted_bytes.decode("utf-8")
    except (InvalidToken, Exception):
        return ""


def mask_api_key(api_key: str | None) -> str:
    """对 API Key 进行脱敏处理，保护私密信息。
    例如: sk-1234567890abcdef -> sk-****cdef
    若字符串过短（<=6）则统一显示为 ****。
    """
    if not api_key:
        return ""
    key = api_key.strip()
    if len(key) <= 6:
        return "****"
    if len(key) <= 10:
        return key[:2] + "****" + key[-2:]
    prefix = key[:3]
    suffix = key[-4:]
    return f"{prefix}****{suffix}"
