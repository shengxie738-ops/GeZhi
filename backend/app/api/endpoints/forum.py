"""Public forum reads and server-owned identity/authorization for writes."""
import json
import re
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.miniprogram_response import api_response, is_miniprogram_client, page_items
from app.core.responses import ok
from app.models.domain_record import DomainRecord
from app.models.user_account import UserAccount
from app.repositories.json_store import JsonStore, atomic_store, load_payload, make_record_key
from app.services.current_identity import get_current_account, get_optional_current_account, load_current_account
from app.utils.datetime import utc_now_iso

router = APIRouter()
# MySQL TEXT is byte-limited, not character-limited. Match JsonStore serialization.
MAX_RECORD_BYTES = 65535


class ForumInput(BaseModel):
    # Historical web/mini-program clients still send author/avatar/isAi. Ignore
    # those fields; they can never become stored authority or provenance.
    model_config = ConfigDict(extra="ignore")


class PostInput(ForumInput):
    title: str = Field(default="Untitled", max_length=2000)
    content: str = Field(default="", max_length=60000)
    category: str = Field(default="qna", max_length=80)
    tags: list[str] = Field(default_factory=list, max_length=64)


class ReplyInput(ForumInput):
    content: str = Field(default="", max_length=60000)


class AnnouncementInput(ForumInput):
    title: str = Field(default="Announcement", max_length=2000)
    content: str = Field(default="", max_length=60000)


class HotTopicInput(ForumInput):
    tag: str = Field(min_length=1, max_length=255)


class HotTopicWeightInput(HotTopicInput):
    change: int = Field(default=0, ge=-1000000, le=1000000)


class AuditInput(ForumInput):
    content: str | None = Field(default=None, max_length=60000)
    status: Literal["pending_audit", "approved", "rejected"] | None = None


def require_user(current_user: UserAccount = Depends(get_current_account)) -> UserAccount:
    return current_user


def _is_moderator(account: UserAccount | None) -> bool:
    if account is None:
        return False
    try:
        configured = json.loads(settings.FORUM_MODERATOR_IDS)
    except (TypeError, ValueError):
        return False
    return isinstance(configured, list) and account.username in {
        value for value in configured if isinstance(value, str) and value
    }


def require_moderator(current_user: UserAccount = Depends(require_user)) -> UserAccount:
    if not _is_moderator(current_user):
        raise HTTPException(status_code=403, detail="forum moderator permission required")
    return current_user


def _write_actor(db: Session, account: UserAccount, *, moderator: bool = False) -> UserAccount:
    # Freshly load after the write unit starts, before object locks. A dependency
    # or SQLAlchemy identity-map snapshot cannot grant stale authority.
    current = load_current_account(db, account.username, lock=True)
    if moderator and not _is_moderator(current):
        raise HTTPException(status_code=403, detail="forum moderator permission required")
    return current


def _avatar_url(account: UserAccount | None) -> str:
    name = account.avatar_path if account else ""
    if not isinstance(name, str) or not re.fullmatch(r"[\w .-]+\.(?:png|jpe?g|gif|webp)", name, re.IGNORECASE):
        return ""
    if name in {".", ".."} or name.startswith("."):
        return ""
    return f"/static/avatars/{name}"


def _identity(account: UserAccount) -> dict:
    return {
        "authorId": account.username,
        "authorUsername": account.username,
        "authorRole": account.role,
        "author": account.real_name or account.username,
        "avatar": _avatar_url(account),
        "provenance": "verified_account",
        "isAi": False,
    }


def _category_label(category: str) -> str:
    return {"qna": "Course Q&A", "competition": "Competition", "experience": "Experience", "chat": "Chat"}.get(category, category or "Course Q&A")


def _save(store: JsonStore, kind: str, key: str, data: dict, *, owner: str = "", role: str = "", status: str = "") -> dict:
    if len(json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")) > MAX_RECORD_BYTES:
        raise HTTPException(status_code=422, detail="forum record exceeds the 65535-byte UTF-8 storage limit")
    return store.upsert("forum", kind, key, data, owner_id=owner, role=role, status=status)


def _post(store: JsonStore, post_id: str) -> tuple[DomainRecord, dict]:
    record = store.get_record("forum", "post", post_id)
    value = load_payload(record)
    if record is None or value is None:
        raise HTTPException(status_code=404, detail="Post not found")
    return record, value


def _save_existing(store: JsonStore, record: DomainRecord, value: dict) -> dict:
    return _save(store, record.record_type, record.record_key, value, owner=record.owner_id, role=record.role, status=record.status)


def _reply_authorities(db: Session) -> dict[tuple[str, str], tuple[str, str]]:
    # These sidecars have no public/generic write endpoint. A historical JSON
    # authorRole/provenance marker is deliberately insufficient evidence.
    records = db.query(DomainRecord).filter_by(module="forum", record_type="reply_identity").all()
    result = {}
    for record in records:
        data = load_payload(record) or {}
        post_id, reply_id = data.get("postId"), data.get("replyId")
        if (
            isinstance(post_id, str) and isinstance(reply_id, str)
            and record.record_key == reply_id and record.owner_id
            and record.role in {"student", "teacher"}
            and data.get("authorId") == record.owner_id
            and data.get("authorRole") == record.role
        ):
            result[(post_id, reply_id)] = (record.owner_id, record.role)
    return result


def _public_identity(value: dict, authority: tuple[str, str] | None, accounts: dict[str, UserAccount]) -> dict:
    result = dict(value)
    if authority is None:
        result.update(authorId="", authorUsername="", authorRole="", avatar="", provenance="legacy_unknown", isAi=None)
        return result
    username, role = authority
    account = accounts.get(username)
    result.update(
        authorId=username, authorUsername=username, authorRole=role,
        author=(account.real_name or account.username) if account else "Former user",
        avatar=_avatar_url(account), provenance="verified_account", isAi=False,
    )
    return result


def _public_post(record: DomainRecord, value: dict, authorities: dict, accounts: dict, viewer: UserAccount | None) -> dict:
    authority = (record.owner_id, record.role) if record.owner_id and record.role in {"student", "teacher"} else None
    result = _public_identity(value, authority, accounts)
    result["replies"] = [
        _public_identity(reply, authorities.get((record.record_key, str(reply.get("id") or ""))), accounts)
        for reply in value.get("replies") or [] if isinstance(reply, dict)
    ]
    result["permissions"] = {
        "canDelete": bool(viewer and (_is_moderator(viewer) or (record.owner_id and record.owner_id == viewer.username))),
        "canPin": _is_moderator(viewer),
        "canReply": viewer is not None,
    }
    return result


def _accounts(db: Session, records: list[DomainRecord], authorities: dict) -> dict[str, UserAccount]:
    usernames = {record.owner_id for record in records if record.owner_id}
    usernames.update(authority[0] for authority in authorities.values())
    if not usernames:
        return {}
    return {account.username: account for account in db.query(UserAccount).filter(UserAccount.username.in_(usernames)).populate_existing().all()}


def _present_one(db: Session, record: DomainRecord, value: dict, viewer: UserAccount | None = None) -> dict:
    authorities = _reply_authorities(db)
    return _public_post(record, value, authorities, _accounts(db, [record], authorities), viewer)


@router.get("/forum/context")
async def get_forum_context(current_user: UserAccount = Depends(require_user)):
    return ok({"username": current_user.username, "role": current_user.role, "canPost": True, "canModerate": _is_moderator(current_user)})


@router.get("/forum/posts")
async def get_posts(
    db: Session = Depends(get_db),
    x_gezhi_client: str | None = Header(default=None, alias="X-Gezhi-Client"),
    current_user: UserAccount | None = Depends(get_optional_current_account),
):
    records = db.query(DomainRecord).filter_by(module="forum", record_type="post").order_by(DomainRecord.created_at.desc(), DomainRecord.id.desc()).all()
    authorities = _reply_authorities(db)
    accounts = _accounts(db, records, authorities)
    posts = [_public_post(record, value, authorities, accounts, current_user) for record in records if (value := load_payload(record)) is not None]
    if is_miniprogram_client(x_gezhi_client):
        return api_response(page_items(posts, limit=len(posts) or 20))
    return ok(posts)


@router.get("/forum/unanswered-qna")
async def get_unanswered_qna(limit: int = 5, db: Session = Depends(get_db)):
    """Only trusted server sidecars establish a teacher answer at creation."""
    limit = max(1, min(limit, 20))
    records = db.query(DomainRecord).filter_by(module="forum", record_type="post").all()
    authorities = _reply_authorities(db)
    accounts = _accounts(db, records, authorities)
    unanswered = []
    for record in records:
        value = load_payload(record) or {}
        answered = any(
            authorities.get((record.record_key, str(reply.get("id") or "")), ("", ""))[1] == "teacher"
            for reply in value.get("replies") or [] if isinstance(reply, dict)
        )
        if value.get("category") == "qna" and not answered:
            unanswered.append(_public_post(record, value, authorities, accounts, None))
    unanswered.sort(key=lambda post: str(post.get("createdAt") or ""), reverse=True)
    result = []
    for post in unanswered[:limit]:
        result.append({
            **{key: post.get(key, "") for key in ["id", "title", "content", "author", "avatar", "createdAt", "authorId", "authorUsername", "authorRole", "provenance"]},
            "isAi": post.get("isAi"), "tags": post.get("tags", []), "views": post.get("views", 0), "likes": post.get("likes", 0),
            "repliesCount": len(post.get("replies") or []), "permissions": post["permissions"],
        })
    return ok(result)


@router.post("/forum/posts")
async def create_post(payload: PostInput, db: Session = Depends(get_db), current_user=Depends(require_user)):
    store = JsonStore(db)
    with atomic_store(db):
        actor = _write_actor(db, current_user)
        post_id = make_record_key("post")
        data = payload.model_dump()
        category = data["category"] or "qna"
        post = {
            "id": post_id, "title": data["title"] or "Untitled", "content": data["content"],
            **_identity(actor), "category": category, "categoryLabel": _category_label(category), "tags": data["tags"],
            "likes": 0, "isLiked": False, "views": 1, "createdAt": utc_now_iso(), "replies": [],
        }
        value = _save(store, "post", post_id, post, owner=actor.username, role=actor.role)
    record, _ = _post(store, post_id)
    return ok(_present_one(db, record, value, actor))


@router.post("/forum/posts/{post_id}/replies")
async def create_reply(
    post_id: str, payload: ReplyInput, db: Session = Depends(get_db), current_user=Depends(require_user),
    x_gezhi_client: str | None = Header(default=None, alias="X-Gezhi-Client"),
):
    store = JsonStore(db)
    with atomic_store(db):
        actor = _write_actor(db, current_user)
        record, post = _post(store, post_id)
        reply_id = make_record_key("reply")
        reply = {"id": reply_id, **_identity(actor), "content": payload.content, "createdAt": utc_now_iso(), "likes": 0}
        replies = list(post.get("replies") or [])
        replies.append(reply)
        post["replies"] = replies
        _save_existing(store, record, post)
        _save(store, "reply_identity", reply_id, {"id": reply_id, "postId": post_id, "replyId": reply_id, "authorId": actor.username, "authorRole": actor.role}, owner=actor.username, role=actor.role)
    if is_miniprogram_client(x_gezhi_client):
        return api_response(reply)
    return ok(reply)


@router.delete("/forum/posts/{post_id}")
async def delete_post(post_id: str, db: Session = Depends(get_db), current_user=Depends(require_user)):
    store = JsonStore(db)
    with atomic_store(db):
        actor = _write_actor(db, current_user)
        record, _ = _post(store, post_id)
        if not _is_moderator(actor) and (not record.owner_id or record.owner_id != actor.username):
            raise HTTPException(status_code=403, detail="post belongs to another user or ownership is unknown")
        db.delete(record)
        for sidecar in db.query(DomainRecord).filter_by(module="forum", record_type="reply_identity").with_for_update().all():
            if (load_payload(sidecar) or {}).get("postId") == post_id:
                db.delete(sidecar)
        pin = store.get_record("forum", "announcement", f"ann-post-{post_id}")
        if pin:
            db.delete(pin)
        db.flush()
    return ok({"success": True})


@router.put("/forum/posts/{post_id}/pin")
async def set_post_pin(post_id: str, pinned: bool = False, db: Session = Depends(get_db), current_user=Depends(require_moderator)):
    store = JsonStore(db)
    with atomic_store(db):
        actor = _write_actor(db, current_user, moderator=True)
        record, post = _post(store, post_id)
        post["isPinned"] = pinned
        _save_existing(store, record, post)
        ann_id = f"ann-post-{post_id}"
        existing = store.get_record("forum", "announcement", ann_id)
        if pinned:
            _save(store, "announcement", ann_id, {"id": ann_id, "title": f"[Pinned] {post.get('title', '')}", "date": "pinned"}, owner=existing.owner_id if existing else actor.username, role=existing.role if existing else actor.role)
        elif existing:
            db.delete(existing)
            db.flush()
    return ok({"success": True})


@router.put("/forum/posts/{post_id}/like")
async def like_post(post_id: str, db: Session = Depends(get_db), current_user=Depends(require_user)):
    store = JsonStore(db)
    with atomic_store(db):
        actor = _write_actor(db, current_user)
        record, post = _post(store, post_id)
        post["likes"] = int(post.get("likes") or 0) + 1
        value = _save_existing(store, record, post)
    return ok(_present_one(db, record, value, actor))


@router.put("/forum/posts/{post_id}/replies/{reply_id}/like")
async def like_reply(post_id: str, reply_id: str, db: Session = Depends(get_db), current_user=Depends(require_user)):
    store = JsonStore(db)
    with atomic_store(db):
        actor = _write_actor(db, current_user)
        record, post = _post(store, post_id)
        reply = next((value for value in post.get("replies") or [] if value.get("id") == reply_id), None)
        if reply is None:
            raise HTTPException(status_code=404, detail="Reply not found")
        reply["likes"] = int(reply.get("likes") or 0) + 1
        _save_existing(store, record, post)
    authorities = _reply_authorities(db)
    return ok(_public_identity(reply, authorities.get((post_id, reply_id)), _accounts(db, [record], authorities)))


@router.put("/forum/posts/{post_id}/view")
async def view_post(post_id: str, db: Session = Depends(get_db)):
    store = JsonStore(db)
    with atomic_store(db):
        record, post = _post(store, post_id)
        post["views"] = int(post.get("views") or 0) + 1
        value = _save_existing(store, record, post)
    return ok(_present_one(db, record, value))


@router.get("/forum/announcements")
async def get_announcements(db: Session = Depends(get_db)):
    records = db.query(DomainRecord).filter_by(module="forum", record_type="announcement").order_by(DomainRecord.created_at.desc(), DomainRecord.id.desc()).all()
    accounts = _accounts(db, records, {})
    announcements = []
    for record in records:
        value = load_payload(record)
        if value is not None:
            authority = (record.owner_id, record.role) if record.owner_id and record.role in {"student", "teacher"} else None
            announcements.append(_public_identity(value, authority, accounts))
    return ok(announcements)


@router.post("/forum/announcements")
async def publish_announcement(payload: AnnouncementInput, db: Session = Depends(get_db), current_user=Depends(require_moderator)):
    store = JsonStore(db)
    with atomic_store(db):
        actor = _write_actor(db, current_user, moderator=True)
        ann_id = make_record_key("ann")
        announcement = {"id": ann_id, "title": payload.title or "Announcement", "content": payload.content, "date": utc_now_iso(), **_identity(actor)}
        _save(store, "announcement", ann_id, announcement, owner=actor.username, role=actor.role)
        post_id = make_record_key("post-ann")
        _save(store, "post", post_id, {
            "id": post_id, "title": announcement["title"], "content": announcement["content"], **_identity(actor),
            "category": "qna", "categoryLabel": "Course Q&A", "tags": ["announcement"], "likes": 0,
            "isLiked": False, "views": 1, "createdAt": utc_now_iso(), "replies": [],
        }, owner=actor.username, role=actor.role)
    return ok(announcement)


@router.get("/forum/hottopics")
async def get_hot_topics(db: Session = Depends(get_db)):
    return ok(JsonStore(db).list_payloads("forum", "hot_topic"))


@router.post("/forum/hottopics")
async def add_hot_topic(payload: HotTopicInput, db: Session = Depends(get_db), current_user=Depends(require_moderator)):
    store = JsonStore(db)
    tag = payload.tag.strip()
    if not tag:
        raise HTTPException(status_code=422, detail="tag is required")
    with atomic_store(db):
        actor = _write_actor(db, current_user, moderator=True)
        existing = store.get_record("forum", "hot_topic", tag)
        _save(store, "hot_topic", tag, {"id": tag, "tag": tag, "count": 10}, owner=existing.owner_id if existing else actor.username, role=existing.role if existing else actor.role)
    return ok(store.list_payloads("forum", "hot_topic"))


@router.put("/forum/hottopics/weight")
async def update_hot_topic_weight(payload: HotTopicWeightInput, db: Session = Depends(get_db), current_user=Depends(require_moderator)):
    store = JsonStore(db)
    tag = payload.tag.strip()
    with atomic_store(db):
        actor = _write_actor(db, current_user, moderator=True)
        record = store.get_record("forum", "hot_topic", tag)
        if record is None:
            raise HTTPException(status_code=404, detail="Hot topic not found")
        topic = load_payload(record) or {}
        topic["count"] = max(0, int(topic.get("count") or 0) + payload.change)
        _save_existing(store, record, topic)
    return ok(store.list_payloads("forum", "hot_topic"))


@router.delete("/forum/hottopics")
async def delete_hot_topic(tag: str, db: Session = Depends(get_db), current_user=Depends(require_moderator)):
    store = JsonStore(db)
    with atomic_store(db):
        _write_actor(db, current_user, moderator=True)
        record = store.get_record("forum", "hot_topic", tag)
        if record is None:
            raise HTTPException(status_code=404, detail="Hot topic not found")
        db.delete(record)
        db.flush()
    return ok(store.list_payloads("forum", "hot_topic"))


@router.get("/forum/ai-replies/logs")
async def get_ai_reply_logs(db: Session = Depends(get_db), current_user=Depends(require_moderator)):
    return ok(JsonStore(db).list_payloads("forum", "ai_reply_log"))


@router.put("/forum/ai-replies/logs/{log_id}")
async def audit_ai_reply(log_id: str, payload: AuditInput, db: Session = Depends(get_db), current_user=Depends(require_moderator)):
    store = JsonStore(db)
    data = {key: value for key, value in payload.model_dump(exclude_unset=True).items() if value is not None}
    if not data:
        raise HTTPException(status_code=422, detail="content or status is required")
    with atomic_store(db):
        _write_actor(db, current_user, moderator=True)
        record = store.get_record("forum", "ai_reply_log", log_id)
        if record is None:
            raise HTTPException(status_code=404, detail="AI reply log not found")
        log = load_payload(record) or {}
        if "content" in data:
            post_record, post = _post(store, str(log.get("postId") or ""))
            reply = next((value for value in post.get("replies") or [] if value.get("id") == log.get("replyId")), None)
            if reply is None:
                raise HTTPException(status_code=404, detail="Reply not found")
            reply["content"] = data["content"]
            _save_existing(store, post_record, post)
        log.update(data)
        # Only the accepted audit status changes the indexed storage status.
        # Other identity/status-preserving operations retain their old contract.
        _save(store, record.record_type, record.record_key, log, owner=record.owner_id, role=record.role, status=data.get("status") or record.status)
    return ok({"success": True})
