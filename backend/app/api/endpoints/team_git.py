import hashlib
import hmac
import json
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.responses import ok
from app.repositories.json_store import atomic_store
from app.core.security import decode_access_token
from app.api.deps import get_auth_payload
from fastapi.routing import APIRoute
from app.models.user_account import UserAccount
from requests.exceptions import RequestException

from app.services.gitea_service import is_gitea_webhook_secret_configured

from app.services.team_git_service import (
    apply_gitea_webhook,
    assign_member_task,
    bind_project_repository,
    check_gitea_health,
    confirm_clone,
    create_collaboration_project,
    create_project_repository,
    delete_collaboration_project,
    evaluate_team_contribution,
    get_collaboration_project,
    get_repository_home,
    get_team_repository_blob,
    get_team_repository_languages,
    get_team_repository_tree,
    list_team_branches,
    list_collaboration_projects,
    remind_unsubmitted_members,
    review_pull_request,
    search_team_members,
    update_collaboration_project,
    refresh_project_status,
    enqueue_git_coach_feedback,
    update_repository_feedback,
    resolve_team_project_id,
)

class TeamGitRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()
        async def handler(request):
            try:
                return await original(request)
            except FileExistsError as exc:
                raise HTTPException(409, str(exc)) from exc
            except PermissionError as exc:
                raise HTTPException(403, str(exc)) from exc
            except FileNotFoundError as exc:
                raise HTTPException(404, str(exc)) from exc
            except (ValueError, TypeError) as exc:
                raise HTTPException(422, str(exc)) from exc
            except (RuntimeError, RequestException) as exc:
                raise HTTPException(503 if str(exc) == "coach_schema_unavailable" else 502, str(exc)) from exc
        return handler

router = APIRouter(route_class=TeamGitRoute)


class FreePayload(BaseModel):
    class Config:
        extra = "allow"


def _payload(payload: FreePayload | None) -> dict[str, Any]:
    return payload.model_dump() if payload else {}


def _decoded_token(authorization: str | None) -> dict[str, Any] | None:
    if authorization and authorization.lower().startswith("bearer "):
        return decode_access_token(authorization.split(" ", 1)[1])
    return None


def resolve_team_git_actor(
    authorization: str | None,
    db: Session,
    *,
    fallback_username: str = "anonymous",
    fallback_role: str = "student",
) -> dict[str, Any]:
    decoded = get_auth_payload(authorization)
    username = str(decoded["sub"])
    account = db.query(UserAccount).filter(UserAccount.username == username).first()
    if not account:
        raise HTTPException(401, "account not found")
    return {
        "username": account.username, "role": account.role,
        "name": account.real_name or account.username,
        "realName": account.real_name or account.username,
        "studentId": account.student_id or "", "teacherId": account.teacher_id or "",
        "className": account.class_name or "",
    }


def _actor_name(actor: dict[str, Any]) -> str:
    return str(actor.get("username") or actor.get("name") or "anonymous")


def verify_gitea_signature(payload_body: bytes, secret: str, signature: str | None) -> bool:
    if not payload_body or not is_gitea_webhook_secret_configured(secret) or not signature:
        return False
    expected = hmac.new(secret.encode("utf-8"), payload_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, str(signature).strip())


def _ensure_project_access(db: Session, project_id: str, actor: dict[str, Any], *, sync: bool = False) -> dict[str, Any]:
    try:
        return get_collaboration_project(db, project_id, actor=actor, sync=sync)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/team-git/gitea-health")
async def team_git_gitea_health(auth: dict = Depends(get_auth_payload)):
    result = check_gitea_health()
    if not result.get("ok"):
        return ok(result)
    return ok(result)


@router.get("/team-git/projects")
async def list_team_git_projects(
    viewer: str = "",
    scope: str = Query(default="all"),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    actor = resolve_team_git_actor(authorization, db, fallback_username=viewer or "anonymous")
    return ok(list_collaboration_projects(db, viewer=viewer, actor=actor, scope=scope))


@router.post("/team-git/projects")
async def create_team_git_project(
    payload: FreePayload,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    data = _payload(payload)
    actor = resolve_team_git_actor(
        authorization,
        db,
        fallback_username=data.get("actor") or data.get("leaderId") or "captain",
    )
    return ok(create_collaboration_project(db, data, actor=actor))


@router.delete("/team-git/projects/{project_id}")
async def delete_team_git_project(
    project_id: str,
    payload: FreePayload | None = None,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    data = _payload(payload)
    actor = resolve_team_git_actor(
        authorization,
        db,
        fallback_username=data.get("actor") or "student",
    )
    try:
        return ok(delete_collaboration_project(db, project_id, actor=actor), message="project deleted")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/team-git/members/search")
async def search_team_git_members(
    keyword: str = Query(default=""),
    course: str = Query(default=""),
    class_name: str = Query(default="", alias="className"),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    actor = resolve_team_git_actor(authorization, db, fallback_username="teacher", fallback_role="teacher")
    return ok(search_team_members(db, keyword, actor=actor, course=course, class_name=class_name))


@router.get("/team-git/projects/{project_id}")
async def get_team_git_project(
    project_id: str,
    viewer: str = "",
    sync: int = Query(default=0),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    actor = resolve_team_git_actor(authorization, db, fallback_username=viewer or "student")
    return ok(_ensure_project_access(db, project_id, actor, sync=bool(sync)))


@router.patch("/team-git/projects/{project_id}")
async def update_team_git_project(
    project_id: str,
    payload: FreePayload,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    data = _payload(payload)
    actor = resolve_team_git_actor(authorization, db, fallback_username=data.get("actor") or "captain")
    _ensure_project_access(db, project_id, actor)
    return ok(update_collaboration_project(db, project_id, data, actor=actor))


@router.get("/team-git/projects/{project_id}/repository-home")
async def get_team_git_repository_home(
    project_id: str,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    actor = resolve_team_git_actor(authorization, db, fallback_username="student")
    try:
        return ok(get_repository_home(db, project_id, actor=actor))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/team-git/projects/{project_id}/tree")
async def get_team_git_repository_tree(
    project_id: str,
    path: str = "",
    ref: str = "",
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    actor = resolve_team_git_actor(authorization, db, fallback_username="student")
    try:
        return ok(get_team_repository_tree(db, project_id, path=path, ref=ref or None, actor=actor))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Gitea 文件目录读取失败：{exc}") from exc


@router.get("/team-git/projects/{project_id}/branches")
async def get_team_git_branches(
    project_id: str,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    actor = resolve_team_git_actor(authorization, db, fallback_username="student")
    try:
        return ok(list_team_branches(db, project_id, actor=actor))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Gitea 分支列表读取失败：{exc}") from exc


@router.get("/team-git/projects/{project_id}/blob")
async def get_team_git_repository_blob(
    project_id: str,
    path: str,
    ref: str = "",
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    if not path.strip():
        raise HTTPException(status_code=400, detail="path is required")
    actor = resolve_team_git_actor(authorization, db, fallback_username="student")
    try:
        return ok(get_team_repository_blob(db, project_id, path=path, ref=ref or None, actor=actor))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Gitea 文件预览失败：{exc}") from exc


@router.get("/team-git/projects/{project_id}/languages")
async def get_team_git_repository_languages(
    project_id: str,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    actor = resolve_team_git_actor(authorization, db, fallback_username="student")
    try:
        return ok(get_team_repository_languages(db, project_id, actor=actor))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Gitea 语言统计读取失败：{exc}") from exc


@router.put("/team-git/projects/{project_id}/repository-feedback")
async def update_team_git_repository_feedback(
    project_id: str,
    payload: FreePayload,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    actor = resolve_team_git_actor(authorization, db, fallback_username="teacher", fallback_role="teacher")
    try:
        return ok(update_repository_feedback(db, project_id, _payload(payload), actor=actor))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/team-git/projects/{project_id}/repository")
async def create_team_git_repository(
    project_id: str,
    payload: FreePayload | None = None,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    data = _payload(payload)
    actor = resolve_team_git_actor(authorization, db, fallback_username=data.get("actor") or "teacher")
    _ensure_project_access(db, project_id, actor)
    try:
        return ok(create_project_repository(db, project_id, actor=actor))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/team-git/projects/{project_id}/repository/bind")
async def bind_team_git_repository(
    project_id: str,
    payload: FreePayload,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    data = _payload(payload)
    actor = resolve_team_git_actor(authorization, db, fallback_username=data.get("actor") or "teacher")
    _ensure_project_access(db, project_id, actor)
    return ok(bind_project_repository(db, project_id, data, actor=actor))


@router.post("/team-git/projects/{project_id}/tasks")
async def assign_team_git_task(
    project_id: str,
    payload: FreePayload,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    data = _payload(payload)
    actor = resolve_team_git_actor(authorization, db, fallback_username=data.get("actor") or "captain")
    _ensure_project_access(db, project_id, actor)
    member_id = data.get("memberId") or data.get("member") or data.get("assignee")
    if not member_id:
        raise HTTPException(status_code=400, detail="memberId is required")
    try:
        return ok(assign_member_task(db, project_id, str(member_id), data, actor=actor))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/team-git/projects/{project_id}/reminders")
async def remind_team_git_members(
    project_id: str,
    payload: FreePayload,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    data = _payload(payload)
    actor = resolve_team_git_actor(authorization, db, fallback_username=data.get("actor") or "captain")
    _ensure_project_access(db, project_id, actor)
    return ok(remind_unsubmitted_members(db, project_id, data, actor=actor))


@router.post("/team-git/projects/{project_id}/clone-confirmation")
async def confirm_team_git_clone(
    project_id: str,
    payload: FreePayload | None = None,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    data = _payload(payload)
    actor = resolve_team_git_actor(authorization, db, fallback_username=data.get("userId") or "student")
    _ensure_project_access(db, project_id, actor)
    return ok(confirm_clone(db, project_id, user_id=_actor_name(actor)))


@router.post("/team-git/projects/{project_id}/refresh")
async def refresh_team_git_project(
    project_id: str,
    payload: FreePayload | None = None,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    data = _payload(payload)
    actor = resolve_team_git_actor(authorization, db, fallback_username=data.get("actor") or "system")
    _ensure_project_access(db, project_id, actor)
    try:
        return ok(
            refresh_project_status(
                db,
                project_id,
                stage=data.get("stage") or "detected",
                actor=actor,
                actor_info=actor,
                allow_demo_stage=False,
            )
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/team-git/projects/{project_id}/pull-requests/{pr_number}/review")
async def review_team_git_pull_request(
    project_id: str,
    pr_number: int,
    payload: FreePayload,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    data = _payload(payload)
    actor = resolve_team_git_actor(authorization, db, fallback_username=data.get("actor") or "reviewer")
    _ensure_project_access(db, project_id, actor)
    try:
        return ok(review_pull_request(db, project_id, pr_number, data, actor=actor))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/team-git/projects/{project_id}/contribution-evaluation")
async def evaluate_team_git_contribution(
    project_id: str,
    payload: FreePayload,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    data = _payload(payload)
    actor = resolve_team_git_actor(
        authorization,
        db,
        fallback_username=data.get("actor") or data.get("teacherId") or "teacher",
        fallback_role="teacher",
    )
    _ensure_project_access(db, project_id, actor)
    return ok(evaluate_team_contribution(db, project_id, data, actor=actor))


@router.post("/team-git/projects/{project_id}/webhooks/gitea")
async def receive_team_git_webhook(
    project_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    x_gitea_signature: str | None = Header(default=None, alias="X-Gitea-Signature"),
    x_gitea_event: str | None = Header(default=None, alias="X-Gitea-Event"),
    x_gitea_delivery: str | None = Header(default=None, alias="X-Gitea-Delivery"),
    db: Session = Depends(get_db),
):
    # Bound unsigned input before JSON decoding or HMAC computation.
    chunks = bytearray()
    async for chunk in request.stream():
        if len(chunks) + len(chunk) > 1024 * 1024:
            raise HTTPException(413, "webhook body exceeds 1 MiB")
        chunks.extend(chunk)
    body = bytes(chunks)
    if not verify_gitea_signature(body, settings.GITEA_WEBHOOK_SECRET, x_gitea_signature):
        raise HTTPException(status_code=403, detail="invalid gitea webhook signature")
    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid gitea webhook payload") from exc
    if not isinstance(payload, dict):
        raise ValueError("webhook payload must be an object")
    if x_gitea_event not in {"push", "pull_request"}:
        raise ValueError("unsupported webhook event")
    if payload.get("hook_name") and payload["hook_name"] != x_gitea_event:
        raise ValueError("webhook event header/body mismatch")
    payload["hook_name"] = x_gitea_event
    if x_gitea_event == "push":
        commits = payload.get("commits")
        if not isinstance(commits, list) or not isinstance(payload.get("ref"), str) or not payload["ref"].startswith("refs/heads/"):
            raise ValueError("push requires branch ref and commits array")
        import re
        if any(not isinstance(c, dict) or not re.fullmatch(r"[0-9a-fA-F]{40,64}", str(c.get("id") or c.get("sha") or "")) for c in commits):
            raise ValueError("push commits require full SHA identities")
    else:
        pr = payload.get("pull_request")
        if not isinstance(pr, dict) or type(pr.get("number")) is not int or pr["number"] <= 0:
            raise ValueError("pull request object and positive number required")
        if payload.get("action") not in {"opened", "closed", "reopened", "synchronized", "synchronize", "edited", "assigned", "unassigned", "label_updated", "label_cleared", "milestoned", "demilestoned", "merged"}:
            raise ValueError("unsupported pull request action")
        if not all(isinstance(pr.get(k), dict) and pr[k].get("ref") for k in ("head", "base")):
            raise ValueError("pull request head and base refs required")
    resolved_id = resolve_team_project_id(db, project_id, payload)
    from app.services.git_coach_jobs import enqueue_coach_event, schema_ready
    if not schema_ready(db.get_bind()):
        raise HTTPException(503, "coach_schema_unavailable")
    repo = payload["repository"]
    owner = repo["owner"].get("login") or repo["owner"].get("username")
    with atomic_store(db):
        receipt = enqueue_coach_event(db, resolved_id, payload, repository_key=f"{owner}/{repo['name']}".lower(), delivery_id=x_gitea_delivery, commit=False)
        if receipt["duplicate"]:
            result = {"id": resolved_id}
        else:
            result = apply_gitea_webhook(db, resolved_id, payload, durable=True)
    return ok({**result, "coachJob": receipt})
