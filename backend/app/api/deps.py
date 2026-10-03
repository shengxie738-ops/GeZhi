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

import json

from app.core.config import settings

from fastapi import Depends, Header, HTTPException
from fastapi.params import Depends as DependencyParameter
from sqlalchemy.orm import Session
from app.core.database import get_db, SessionLocal
from app.services.current_identity import resolve_current_account


def get_auth_payload(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> dict:
    # Preserve the established direct-call interface as well as dependency
    # injection. Only an omitted Depends sentinel owns a short-lived session;
    # explicit caller/injected sessions are never substituted or closed here.
    if isinstance(db, DependencyParameter):
        with SessionLocal() as owned_db:
            return get_auth_payload(authorization, owned_db)
    account = resolve_current_account(authorization, db)
    return {"sub": account.username, "role": account.role}


def require_teacher(payload: dict = Depends(get_auth_payload)) -> dict:
    """要求教师角色（学生 token 返回 403）。"""
    if payload.get("role") != "teacher":
        raise HTTPException(status_code=403, detail="teacher role required")
    return payload


def ensure_self_or_teacher(user_id: str | None, payload: dict) -> None:
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    if payload.get("sub") == user_id:
        return
    if payload.get("role") == "teacher" and user_id in teacher_student_ids(str(payload.get("sub") or "")):
        return
    if payload.get("sub") != user_id:
        raise HTTPException(status_code=403, detail="no permission to access another user's data")


def teacher_student_ids(teacher_id: str) -> set[str]:
    """Trusted deployment roster; malformed/missing mappings are deliberately empty."""
    try:
        assignments = json.loads(settings.TEACHER_STUDENT_ASSIGNMENTS)
    except (ValueError, TypeError):
        return set()
    students = assignments.get(teacher_id, []) if isinstance(assignments, dict) else []
    return {value for value in students if isinstance(value, str) and value} if isinstance(students, list) else set()


def ensure_content_teacher(content: dict | None, payload: dict) -> dict:
    if content is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    if payload.get("role") != "teacher" or content.get("teacherId") != payload.get("sub"):
        raise HTTPException(status_code=403, detail="This teaching resource belongs to another teacher or needs operator assignment")
    return content


def student_can_access_content(content: dict, student_id: str) -> bool:
    teacher_id = str(content.get("teacherId") or "")
    if not teacher_id or student_id not in teacher_student_ids(teacher_id):
        return False
    targets = content.get("studentIds")
    if targets is not None and (not isinstance(targets, list) or student_id not in targets):
        return False
    target = content.get("targetStudentId")
    return not target or target == student_id


def ensure_content_student(content: dict | None, student_id: str) -> dict:
    if content is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    if not student_can_access_content(content, student_id):
        raise HTTPException(status_code=403, detail="Student is not assigned to this teaching resource")
    return content


def scoped_student_targets(data: dict, teacher_id: str) -> list[str]:
    allowed = teacher_student_ids(teacher_id)
    requested = data.get("studentIds")
    if data.get("targetStudentId"):
        requested = [data["targetStudentId"]]
    if requested is None:
        requested = sorted(allowed)
    if not isinstance(requested, list) or not requested or any(not isinstance(value, str) or value not in allowed for value in requested):
        raise HTTPException(status_code=403, detail="Choose students in your assigned roster")
    return list(dict.fromkeys(requested))
