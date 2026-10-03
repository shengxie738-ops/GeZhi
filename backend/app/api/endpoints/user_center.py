from pathlib import Path
from uuid import uuid4
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import ensure_self_or_teacher, get_auth_payload
from app.core.database import get_db
from app.core.security import get_password_hash, verify_password
from app.core.username_policy import NUMERIC_ID_RE, has_chinese
from app.models.user_account import UserAccount

router = APIRouter()
AVATAR_DIRECTORY = Path(__file__).resolve().parents[2] / "static" / "avatars"


class UserInfoUpdate(BaseModel):
    username: str
    real_name: Optional[str] = None
    student_id: Optional[str] = None
    teacher_id: Optional[str] = None
    class_name: Optional[str] = None
    phone: Optional[str] = None


class PasswordChange(BaseModel):
    username: str
    old_password: str
    new_password: str


def get_account_or_404(db: Session, username: str) -> UserAccount:
    """用户中心只操作已存在的账号；账号创建必须走注册接口。

    历史上这里会按任意用户名静默建号（教师 token 即可触发），
    是学情画像中 codex_*、BrowserDeepCheck 等幽灵账号的来源。
    """
    account = db.query(UserAccount).filter(UserAccount.username == username).first()
    if not account:
        raise HTTPException(status_code=404, detail="user not found")
    return account


def serialize_gitea_summary(db: Session, account: UserAccount) -> dict:
    try:
        from app.services.gitea_account_service import get_gitea_binding_summary

        return get_gitea_binding_summary(db, account)
    except Exception as exc:
        return {
            "username": "",
            "email": "",
            "syncStatus": "mock",
            "tokenLastFour": "",
            "syncError": str(exc),
        }


def serialize_account(db: Session, account: UserAccount) -> dict:
    return {
        "username": account.username,
        "role": account.role or "student",
        "real_name": account.real_name or "",
        "phone": account.phone or "",
        "student_id": account.student_id or "",
        "teacher_id": account.teacher_id or "",
        "class_name": account.class_name or "",
        "avatar_url": f"/static/avatars/{account.avatar_path}" if account.avatar_path else "",
        "gitea": serialize_gitea_summary(db, account),
    }


@router.get("/user/info/{username}")
async def get_user_info(username: str, payload: dict = Depends(get_auth_payload), db: Session = Depends(get_db)):
    ensure_self_or_teacher(username, payload)
    account = get_account_or_404(db, username)
    return serialize_account(db, account)


@router.post("/user/update_info")
async def update_user_info(data: UserInfoUpdate, payload: dict = Depends(get_auth_payload), db: Session = Depends(get_db)):
    ensure_self_or_teacher(data.username, payload)
    account = get_account_or_404(db, data.username)

    # 与注册接口同一约束：画像展示 real_name，放任任意格式会再现"Codex????"类垃圾展示名
    real_name = (data.real_name or "").strip()
    student_id = (data.student_id or "").strip()
    if real_name and not has_chinese(real_name):
        raise HTTPException(status_code=400, detail="姓名必须为中文")
    if student_id and not NUMERIC_ID_RE.match(student_id):
        raise HTTPException(status_code=400, detail="学号必须为 4-20 位数字")

    for field in ("real_name", "student_id", "teacher_id", "class_name", "phone"):
        value = getattr(data, field)
        if value is not None:
            setattr(account, field, value.strip())

    db.commit()
    db.refresh(account)
    return {
        "status": "success",
        "message": "profile updated",
        "user": serialize_account(db, account),
    }


@router.post("/user/change_password")
async def change_password(data: PasswordChange, payload: dict = Depends(get_auth_payload), db: Session = Depends(get_db)):
    ensure_self_or_teacher(data.username, payload)
    account = get_account_or_404(db, data.username)

    if account.password_hash and not verify_password(data.old_password, account.password_hash):
        raise HTTPException(status_code=400, detail="old password is incorrect")

    if len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="new password must be at least 6 characters")

    account.password_hash = get_password_hash(data.new_password)
    db.commit()
    return {"status": "success", "message": "password updated"}


@router.post("/user/upload_avatar")
async def upload_avatar(
    username: str = Form(...),
    file: UploadFile = File(...),
    payload: dict = Depends(get_auth_payload),
    db: Session = Depends(get_db),
):
    ensure_self_or_teacher(username, payload)
    # Resolve the target before even reading or writing an uploaded file.
    account = get_account_or_404(db, username)
    allowed_types = {"image/jpeg", "image/png", "image/gif", "image/webp"}
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="only JPG / PNG / GIF / WebP images are supported")

    content = await file.read()
    if len(content) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="image size must not exceed 2MB")

    AVATAR_DIRECTORY.mkdir(parents=True, exist_ok=True)

    ext_map = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
    }
    ext = ext_map.get(file.content_type, ".jpg")
    filename = f"avatar-{uuid4().hex}{ext}"
    filepath = AVATAR_DIRECTORY / filename
    created = False
    try:
        with filepath.open("xb") as handle:
            created = True
            handle.write(content)
        account.avatar_path = filename
        db.commit()
    except BaseException:
        try:
            db.rollback()
        finally:
            if created:
                filepath.unlink(missing_ok=True)
        raise
    db.refresh(account)

    return {
        "status": "success",
        "message": "avatar uploaded",
        "avatar_url": f"/static/avatars/{filename}",
        "user": serialize_account(db, account),
    }
