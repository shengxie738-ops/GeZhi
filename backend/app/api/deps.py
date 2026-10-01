"""统一的 API 鉴权依赖。

用法：
    from app.api.deps import get_auth_payload, ensure_self_or_teacher

    @router.get("/user/knowledge")
    async def get_user_knowledge(user_id: str, payload: dict = Depends(get_auth_payload), db=...):
        ensure_self_or_teacher(user_id, payload)
        ...

get_auth_payload    —— 要求携带有效登录 token（未登录/无效 token 返回 401）
ensure_self_or_teacher —— 校验目标 user_id 归属：仅本人或教师角色可访问（越权返回 403）
"""

from fastapi import Depends, Header, HTTPException

from app.core.security import decode_access_token


def get_auth_payload(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="not authenticated")
    payload = decode_access_token(authorization.split(" ", 1)[1])
    if not payload or not payload.get("sub"):
        raise HTTPException(status_code=401, detail="invalid token")
    return payload


def require_teacher(payload: dict = Depends(get_auth_payload)) -> dict:
    """要求教师角色（学生 token 返回 403）。"""
    if payload.get("role") != "teacher":
        raise HTTPException(status_code=403, detail="teacher role required")
    return payload


def ensure_self_or_teacher(user_id: str | None, payload: dict) -> None:
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    if payload.get("role") == "teacher":
        return
    if payload.get("sub") != user_id:
        raise HTTPException(status_code=403, detail="no permission to access another user's data")
