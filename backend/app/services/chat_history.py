from sqlalchemy.orm import Session

from app.models.chat_message import ChatMessage


VALID_AGENT_MODES = {"tutor", "rag", "chat", "paper"}


def normalize_agent_mode(agent_mode: str | None) -> str:
    cleaned = (agent_mode or "").strip().lower()
    if cleaned in ("chat", "default", "general"):
        return "chat"
    if cleaned in ("paper", "academic", "scholar", "agent_paper"):
        return "paper"
    if cleaned in ("rag", "researcher", "agent_researcher"):
        return "rag"
    if cleaned in ("tutor", "agent_tutor"):
        return "tutor"
    return cleaned if cleaned in VALID_AGENT_MODES else "tutor"


def normalize_user_id(user_id: str | None) -> str:
    cleaned = (user_id or "").strip()
    return cleaned or "guest_user"


def normalize_conversation_id(conversation_id: str | None) -> str | None:
    cleaned = (conversation_id or "").strip()
    return cleaned[:64] or None


def build_agent_thread_id(
    user_id: str | None,
    agent_mode: str | None,
    conversation_id: str | None = None,
) -> str:
    base = f"{normalize_user_id(user_id)}:{normalize_agent_mode(agent_mode)}"
    normalized_conversation_id = normalize_conversation_id(conversation_id)
    return f"{base}:{normalized_conversation_id}" if normalized_conversation_id else base


def save_chat_message(
    db: Session,
    *,
    user_id: str,
    agent_mode: str,
    role: str,
    content: str,
    sender_id: str | None = None,
    conversation_id: str | None = None,
    project_id: str | None = None,
) -> ChatMessage:
    record = ChatMessage(
        user_id=normalize_user_id(user_id),
        agent_mode=normalize_agent_mode(agent_mode),
        role=role,
        content=content or "",
        sender_id=sender_id,
        conversation_id=normalize_conversation_id(conversation_id),
        project_id=(project_id or "").strip()[:64] or None,
    )
    try:
        db.add(record)
        db.commit()
        db.refresh(record)
        return record
    except Exception:
        db.rollback()
        raise


def save_chat_messages_batch(
    db: Session,
    *,
    user_id: str,
    agent_mode: str,
    items: list,
    conversation_id: str | None = None,
    project_id: str | None = None,
) -> list[ChatMessage]:
    norm_user = normalize_user_id(user_id)
    norm_mode = normalize_agent_mode(agent_mode)
    records = []
    for item in items:
        item_mode = normalize_agent_mode(getattr(item, "agent_mode", None) or norm_mode)
        records.append(
            ChatMessage(
                user_id=norm_user,
                agent_mode=item_mode,
                role=getattr(item, "role", "user") or "user",
                content=getattr(item, "content", "") or "",
                sender_id=getattr(item, "sender_id", None),
                conversation_id=normalize_conversation_id(
                    getattr(item, "conversation_id", None) or conversation_id
                ),
                project_id=(
                    getattr(item, "project_id", None) or project_id or ""
                ).strip()[:64] or None,
            )
        )
    if not records:
        return []
    try:
        db.add_all(records)
        db.commit()
        for record in records:
            db.refresh(record)
        return records
    except Exception:
        db.rollback()
        raise


def list_chat_history(db: Session, *, user_id: str, agent_mode: str, limit: int = 200) -> list[dict]:
    records = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.user_id == normalize_user_id(user_id),
            ChatMessage.agent_mode == normalize_agent_mode(agent_mode),
        )
        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
        .limit(max(1, min(limit, 500)))
        .all()
    )
    history = []
    legacy_conversation_id = None
    normalized_mode = normalize_agent_mode(agent_mode)
    for record in records:
        item = serialize_chat_message(record)
        if item["conversation_id"]:
            legacy_conversation_id = item["conversation_id"]
        elif record.role == "user":
            legacy_conversation_id = f"legacy-{normalized_mode}-{record.id}"
        elif not legacy_conversation_id:
            legacy_conversation_id = f"legacy-{normalized_mode}-early-{record.id}"
        item["conversation_id"] = legacy_conversation_id
        if not item["project_id"]:
            item["project_id"] = {
                "chat": "proj-default",
                "tutor": "proj-tutor",
                "rag": "proj-rag",
                "paper": "proj-paper",
            }[normalized_mode]
        history.append(item)
    return history


def serialize_chat_message(record: ChatMessage) -> dict:
    return {
        "id": record.id,
        "user_id": record.user_id,
        "agent_mode": record.agent_mode,
        "role": record.role,
        "content": record.content,
        "sender_id": record.sender_id,
        "conversation_id": record.conversation_id,
        "project_id": record.project_id,
        "created_at": record.created_at.strftime("%Y-%m-%d %H:%M:%S") if record.created_at else None,
    }


def delete_chat_message(db: Session, *, user_id: str, message_id: int) -> bool:
    record = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.id == message_id,
            ChatMessage.user_id == normalize_user_id(user_id),
        )
        .first()
    )
    if not record:
        return False
    try:
        db.delete(record)
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise


def clear_chat_history(db: Session, *, user_id: str, agent_mode: str) -> int:
    try:
        deleted = (
            db.query(ChatMessage)
            .filter(
                ChatMessage.user_id == normalize_user_id(user_id),
                ChatMessage.agent_mode == normalize_agent_mode(agent_mode),
            )
            .delete(synchronize_session=False)
        )
        db.commit()
        return int(deleted or 0)
    except Exception:
        db.rollback()
        raise

