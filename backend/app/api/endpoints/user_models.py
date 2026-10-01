import logging
from typing import Any, List
import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_auth_payload
from app.core.crypto import encrypt_secret
from app.core.database import get_db
from app.models.user_custom_ai_model import UserCustomAIModel
from app.schemas.user_model import (
    TestConnectionRequest,
    UserCustomModelCreateRequest,
    UserCustomModelUpdateRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/user/models", tags=["UserCustomModels"])


@router.get("", response_model=dict)
async def list_user_custom_models(
    payload: dict = Depends(get_auth_payload),
    db: Session = Depends(get_db),
):
    """获取当前登录用户的自定义模型列表（API Key 严格脱敏返回）。"""
    user_id = payload.get("sub")
    records = (
        db.query(UserCustomAIModel)
        .filter(UserCustomAIModel.user_id == user_id)
        .order_by(UserCustomAIModel.created_at.desc())
        .all()
    )
    return {
        "status": "success",
        "data": [r.to_dict(mask_key=True) for r in records],
    }


@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_user_custom_model(
    req: UserCustomModelCreateRequest,
    payload: dict = Depends(get_auth_payload),
    db: Session = Depends(get_db),
):
    """新增自定义大模型配置，API Key 密文存储，仅当前用户可用。"""
    user_id = payload.get("sub")
    encrypted_key = encrypt_secret(req.api_key)

    record = UserCustomAIModel(
        user_id=user_id,
        provider=req.provider,
        api_type=req.api_type,
        base_url=req.base_url,
        encrypted_api_key=encrypted_key,
        model_ids=req.model_ids,
        is_active=req.is_active,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    logger.info(f"[CustomModel] User {user_id} added custom model config: {record.id}, models={req.model_ids}")
    return {
        "status": "success",
        "message": "自定义大模型配置添加成功",
        "data": record.to_dict(mask_key=True),
    }


@router.put("/{config_id}", response_model=dict)
async def update_user_custom_model(
    config_id: str,
    req: UserCustomModelUpdateRequest,
    payload: dict = Depends(get_auth_payload),
    db: Session = Depends(get_db),
):
    """更新已有自定义大模型配置，严格校验用户归属。"""
    user_id = payload.get("sub")
    record = (
        db.query(UserCustomAIModel)
        .filter(UserCustomAIModel.id == config_id, UserCustomAIModel.user_id == user_id)
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="未找到该模型配置或无权访问")

    if req.provider is not None:
        record.provider = req.provider
    if req.api_type is not None:
        record.api_type = req.api_type
    if req.base_url is not None:
        record.base_url = req.base_url
    if req.model_ids is not None:
        record.model_ids = req.model_ids
    if req.is_active is not None:
        record.is_active = req.is_active

    # 若传入了新的明文 API Key 且非脱敏字符串，则重新加密
    if req.api_key and not req.api_key.strip().startswith("****") and "****" not in req.api_key:
        record.encrypted_api_key = encrypt_secret(req.api_key.strip())

    db.commit()
    db.refresh(record)
    return {
        "status": "success",
        "message": "配置更新成功",
        "data": record.to_dict(mask_key=True),
    }


@router.delete("/{config_id}", response_model=dict)
async def delete_user_custom_model(
    config_id: str,
    payload: dict = Depends(get_auth_payload),
    db: Session = Depends(get_db),
):
    """删除指定的自定义大模型配置，严格隔离。"""
    user_id = payload.get("sub")
    record = (
        db.query(UserCustomAIModel)
        .filter(UserCustomAIModel.id == config_id, UserCustomAIModel.user_id == user_id)
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="未找到该模型配置或无权访问")

    db.delete(record)
    db.commit()
    logger.info(f"[CustomModel] User {user_id} deleted custom model config: {config_id}")
    return {
        "status": "success",
        "message": "自定义模型配置已删除",
    }


@router.post("/test", response_model=dict)
async def test_custom_model_connection(
    req: TestConnectionRequest,
    payload: dict = Depends(get_auth_payload),
    db: Session = Depends(get_db),
):
    """在线测试 Base URL 与 API Key 的连通性。"""
    raw_api_key = req.api_key.strip()
    # 支持传入脱敏 key 时自动在数据库中查原密文解密（当用户编辑已有模型测试时）
    if "****" in raw_api_key:
        user_id = payload.get("sub")
        saved = (
            db.query(UserCustomAIModel)
            .filter(UserCustomAIModel.user_id == user_id, UserCustomAIModel.base_url == req.base_url)
            .first()
        )
        if saved:
            raw_api_key = saved.get_decrypted_api_key()
        else:
            return {"status": "error", "message": "API Key 格式不正确，请重新输入明文 Key 测试"}

    test_model = (req.model_id or "default").strip()
    clean_base = req.base_url.rstrip("/")
    if clean_base.endswith("/chat/completions"):
        clean_base = clean_base[:-len("/chat/completions")].rstrip("/")
    target_endpoint = f"{clean_base}/chat/completions"

    headers = {
        "Authorization": f"Bearer {raw_api_key}",
        "Content-Type": "application/json",
    }
    payload_body = {
        "model": test_model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 5,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(target_endpoint, json=payload_body, headers=headers)

            if res.status_code == 200:
                return {
                    "status": "success",
                    "message": "连通性测试成功！模型接口响应正常",
                    "status_code": 200,
                }
            elif res.status_code == 401:
                return {
                    "status": "error",
                    "message": "认证失败 (401)：API Key 无效或未授权",
                    "status_code": 401,
                }
            elif res.status_code == 404:
                return {
                    "status": "error",
                    "message": f"接口地址未找到 (404)，请检查 Base URL 是否准确 (请求了 {target_endpoint})",
                    "status_code": 404,
                }
            else:
                return {
                    "status": "warning",
                    "message": f"接口返回 HTTP {res.status_code}，请检查服务状态与端点参数",
                    "status_code": res.status_code,
                }
    except httpx.TimeoutException:
        return {
            "status": "error",
            "message": "连接超时（12秒），请检查网络是否通畅或接口地址是否正确",
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"请求发生异常：{str(e)}",
        }
