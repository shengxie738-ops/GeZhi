from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func, String, cast
import base64
import json
import hashlib
import re
from datetime import datetime
from dataclasses import dataclass, replace
from contextlib import contextmanager
from contextvars import ContextVar
from weakref import WeakSet
from threading import RLock

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


@dataclass(eq=False)
class RequestAdmission:
    user_id: str
    agent_mode: str
    conversation_id: str | None
    reason: str | None = None
    connection: object | None = None


_admissions = WeakSet()
_admissions_lock = RLock()
_current_admission = ContextVar('chat_request_admission', default=None)


@contextmanager
def admit_chat_request(user_id, agent_mode, conversation_id):
    """Worker-local fence registered before any serialization or database wait.

    Tickets only live for active requests; no persistent tombstone or transcript.
    Cross-worker pre-origin admission requires shared durable coordination.
    """
    admission = RequestAdmission(normalize_user_id(user_id), normalize_agent_mode(agent_mode),
                                 normalize_conversation_id(conversation_id))
    with _admissions_lock:
        _admissions.add(admission)
    token = _current_admission.set(admission)
    try:
        yield admission
    finally:
        _current_admission.reset(token)
        with _admissions_lock:
            _admissions.discard(admission)


def invalidate_admissions(user_id, agent_mode, *, conversation_id=None, all_tasks=False):
    with _admissions_lock:
        for admission in _admissions:
            if (admission.user_id == normalize_user_id(user_id)
                    and admission.agent_mode == normalize_agent_mode(agent_mode)
                    and (all_tasks or admission.conversation_id == normalize_conversation_id(conversation_id))):
                admission.reason = 'history_cleared' if all_tasks else 'context_deleted'


async def chat_client_disconnected():
    admission = _current_admission.get()
    if admission and admission.connection and await admission.connection.is_disconnected():
        admission.reason = 'client_disconnected'
        return True
    return False


def admission_invalidated():
    admission = _current_admission.get()
    return admission.reason if admission else None


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
    payload: dict | None = None,
) -> ChatMessage:
    record = ChatMessage(
        user_id=normalize_user_id(user_id),
        agent_mode=normalize_agent_mode(agent_mode),
        role=role,
        content=content or "",
        sender_id=sender_id,
        conversation_id=normalize_conversation_id(conversation_id),
        project_id=(project_id or "").strip()[:64] or None,
        payload=payload,
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
    client_request_id: str | None = None,
) -> list[ChatMessage]:
    norm_user = normalize_user_id(user_id)
    norm_mode = normalize_agent_mode(agent_mode)
    records = []
    request_digest = None
    if client_request_id:
        body = {'agent_mode':norm_mode, 'conversation_id':normalize_conversation_id(conversation_id),
                'project_id':project_id, 'items':[item.model_dump() if hasattr(item, 'model_dump') else vars(item) for item in items]}
        request_digest = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        existing = db.query(ChatMessage).filter(ChatMessage.user_id == norm_user,
            ChatMessage.payload['_sync']['client_request_id'].as_string() == client_request_id).order_by(ChatMessage.id.asc()).all()
        if existing:
            if len(existing) != len(items) or any(record.payload.get('_sync', {}).get('digest') != request_digest for record in existing):
                raise ValueError('client_request_id conflicts with existing or deleted batch')
            return existing
    for index, item in enumerate(items):
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
                payload=({**(getattr(item, 'payload', None) or {}), '_sync':{
                    'client_request_id':client_request_id, 'digest':request_digest, 'index':index, 'count':len(items)}}
                    if client_request_id else getattr(item, 'payload', None)),
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


def _comparable_timestamp(timestamp):
    # SQLite CURRENT_TIMESTAMP has no fractional suffix, unlike DateTime binds.
    # Normalize both forms without dropping microseconds or changing keyset ties.
    column = func.substr(cast(ChatMessage.created_at, String) + '.000000', 1, 26)
    return column, timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')


def _before_record(timestamp, message_id):
    column, value = _comparable_timestamp(timestamp)
    return or_(column < value, and_(column == value, ChatMessage.id < message_id))


def _after_or_at_record(timestamp, message_id):
    column, value = _comparable_timestamp(timestamp)
    return or_(column > value, and_(column == value, ChatMessage.id >= message_id))


def scoped_chat_query(db: Session, *, user_id: str, agent_mode: str,
                      conversation_id: str | None = None, exact_conversation: bool = False):
    mode = normalize_agent_mode(agent_mode)
    query = db.query(ChatMessage).filter(ChatMessage.user_id == normalize_user_id(user_id),
                                        ChatMessage.agent_mode == mode)
    if exact_conversation or conversation_id is not None:
        normalized = normalize_conversation_id(conversation_id)
        early = re.fullmatch(r'legacy-' + re.escape(mode) + r'-early-(\d+)', normalized or '')
        if early:
            return query.filter(or_(ChatMessage.conversation_id == normalized,
                                    and_(ChatMessage.conversation_id.is_(None), ChatMessage.id == int(early[1]))))
        match = re.fullmatch(r'legacy-' + re.escape(mode) + r'-(\d+)', normalized or '')
        if match:
            anchor = query.filter(ChatMessage.id == int(match[1]), ChatMessage.conversation_id.is_(None),
                                  ChatMessage.role == 'user').first()
            if anchor:
                next_user = query.filter(ChatMessage.conversation_id.is_(None), ChatMessage.role == 'user',
                                         _after_or_at_record(anchor.created_at, anchor.id),
                                         ChatMessage.id != anchor.id).order_by(
                                             ChatMessage.created_at.asc(), ChatMessage.id.asc()).first()
                legacy_range = and_(ChatMessage.conversation_id.is_(None),
                                    _after_or_at_record(anchor.created_at, anchor.id))
                if next_user:
                    legacy_range = and_(legacy_range, _before_record(next_user.created_at, next_user.id))
                return query.filter(or_(ChatMessage.conversation_id == normalized, legacy_range))
        query = query.filter(ChatMessage.conversation_id == normalized)
    return query


def list_chat_history_page(db: Session, *, user_id: str, agent_mode: str, limit: int = 200,
                           before: str | None = None, conversation_id: str | None = None) -> dict:
    """Latest-first keyset pages, each returned in chronological display order.

    Cursor pins an initial max ID. `complete` means all rows in that scoped
    snapshot have been exhausted, not that a partial first page is authoritative.
    """
    scope = {'user_id': normalize_user_id(user_id), 'agent_mode': normalize_agent_mode(agent_mode),
             'conversation_id': normalize_conversation_id(conversation_id)}
    query = scoped_chat_query(db, user_id=user_id, agent_mode=agent_mode, conversation_id=conversation_id)
    if before:
        try:
            if len(before) > 2048:
                raise ValueError('cursor too long')
            cursor = json.loads(base64.urlsafe_b64decode(before + '=' * (-len(before) % 4)))
            if cursor['scope'] != scope or not isinstance(cursor['max_id'], int) or cursor['max_id'] < 0:
                raise ValueError('cursor scope mismatch')
            max_id = cursor['max_id']
            query = query.filter(_before_record(datetime.fromisoformat(cursor['at']), int(cursor['id'])))
        except (ValueError, TypeError, KeyError, UnicodeError) as exc:
            raise ValueError('invalid history cursor') from exc
    else:
        max_id = query.with_entities(func.max(ChatMessage.id)).scalar() or 0
    page_limit = max(1, min(limit, 500))
    records = query.filter(ChatMessage.id <= max_id).order_by(
        ChatMessage.created_at.desc(), ChatMessage.id.desc()).limit(page_limit + 1).all()
    has_more = len(records) > page_limit
    records = records[:page_limit]
    next_cursor = None
    if has_more and records:
        oldest = records[-1]
        cursor = {'scope':scope, 'at':oldest.created_at.isoformat(), 'id':oldest.id, 'max_id':max_id}
        next_cursor = base64.urlsafe_b64encode(json.dumps(cursor, separators=(',', ':')).encode()).decode().rstrip('=')
    return {'data': _serialize_history(db, list(reversed(records)), user_id=user_id, agent_mode=agent_mode),
            'pagination': {'has_more':has_more, 'next_cursor':next_cursor, 'complete':not has_more,
                           'snapshot_max_id':max_id, 'order':'asc',
                           'scope': {'agent_mode':scope['agent_mode'], 'conversation_id':scope['conversation_id']}}}


def list_chat_history(db: Session, *, user_id: str, agent_mode: str, limit: int = 200) -> list[dict]:
    records = scoped_chat_query(db, user_id=user_id, agent_mode=agent_mode).order_by(
        ChatMessage.created_at.desc(), ChatMessage.id.desc()).limit(max(1, min(limit, 500))).all()
    return _serialize_history(db, list(reversed(records)), user_id=user_id, agent_mode=agent_mode)


def _serialize_history(db, records, *, user_id, agent_mode):
    history = []
    normalized_mode = normalize_agent_mode(agent_mode)
    for record in records:
        item = serialize_chat_message(record)
        if not item['conversation_id']:
            # Stable even when a page starts in the middle of a legacy task.
            anchor = scoped_chat_query(db, user_id=user_id, agent_mode=normalized_mode,
                                       exact_conversation=True).filter(
                ChatMessage.role == 'user',
                _before_record(record.created_at, record.id + 1),
            ).order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc()).first()
            item['conversation_id'] = f'legacy-{normalized_mode}-{anchor.id}' if anchor else f'legacy-{normalized_mode}-early-{record.id}'
        if not item['project_id']:
            item['project_id'] = {'chat':'proj-default','tutor':'proj-tutor','rag':'proj-rag','paper':'proj-paper'}[normalized_mode]
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
        "payload": record.payload,
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
        legacy_scope = (_serialize_history(db, [record], user_id=record.user_id, agent_mode=record.agent_mode)[0]['conversation_id']
                        if record.conversation_id is None else None)
        if record.conversation_id is None and record.role == 'user':
            # Synthetic legacy task IDs must survive deletion of their anchor.
            # Stamp only this owner's/mode's original segment atomically with deletion.
            legacy_id = f'legacy-{record.agent_mode}-{record.id}'
            scoped_chat_query(db, user_id=record.user_id, agent_mode=record.agent_mode,
                              conversation_id=legacy_id).update(
                                  {ChatMessage.conversation_id:legacy_id}, synchronize_session=False)
        scope = (record.user_id, record.agent_mode, record.conversation_id)
        db.delete(record)
        db.commit()
        invalidate_admissions(scope[0], scope[1], conversation_id=scope[2])
        if legacy_scope:
            invalidate_admissions(scope[0], scope[1], conversation_id=legacy_scope)
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
        invalidate_admissions(user_id, agent_mode, all_tasks=True)
        return int(deleted or 0)
    except Exception:
        db.rollback()
        raise



@dataclass(frozen=True)
class ChatRequestReceipt:
    id: int
    user_id: str
    agent_mode: str
    token: str
    context_ids: tuple[int, ...] = ()


def chat_request_receipt(record: ChatMessage) -> ChatRequestReceipt:
    # SQLAlchemy expires ORM rows at commit; capture before inference awaits.
    return ChatRequestReceipt(record.id, record.user_id, record.agent_mode,
                              (record.payload or {}).get('_request_token', ''))


def with_context_receipt(receipt: ChatRequestReceipt, messages) -> ChatRequestReceipt:
    return replace(receipt, context_ids=tuple(sorted(getattr(messages, 'source_ids', ()))))


def discard_invalidated_origin(db, receipt):
    """Remove only this request's late insert, never another reused numeric ID."""
    db.query(ChatMessage).filter(ChatMessage.id == receipt.id,
        ChatMessage.user_id == receipt.user_id, ChatMessage.agent_mode == receipt.agent_mode,
        ChatMessage.payload['_request_token'].as_string() == receipt.token).delete(synchronize_session=False)
    db.commit()


def save_chat_reply_if_current(db: Session, *, current_record: ChatRequestReceipt, content: str,
                               sender_id: str | None = None, before_write=None) -> ChatMessage | None:
    """A clear/delete during inference must not resurrect a removed request.

    MySQL FOR UPDATE is a current read and holds the origin row until the reply
    commit. This also prevents the clear-check/insert race across workers.
    The paper caller rechecks its deadline after these synchronous locking
    reads, before starting a new write. Other callers retain existing behavior.
    """
    if admission_invalidated() or not content or not content.strip():
        return None
    token = current_record.token
    try:
        origin = db.query(ChatMessage).filter(ChatMessage.id == current_record.id,
            ChatMessage.user_id == current_record.user_id, ChatMessage.agent_mode == current_record.agent_mode,
            ChatMessage.role == 'user', ChatMessage.payload['_request_token'].as_string() == token).with_for_update().first()
        if not origin or admission_invalidated():
            db.rollback()
            return None
        if current_record.context_ids:
            surviving = db.query(ChatMessage.id).filter(ChatMessage.user_id == current_record.user_id,
                ChatMessage.agent_mode == current_record.agent_mode,
                ChatMessage.id.in_(current_record.context_ids)).with_for_update().all()
            if len(surviving) != len(current_record.context_ids):
                db.rollback()
                return None
        if before_write is not None:
            before_write()
        return save_chat_message(db, user_id=origin.user_id, agent_mode=origin.agent_mode,
                                 role='assistant', content=content, sender_id=sender_id,
                                 conversation_id=origin.conversation_id, project_id=origin.project_id)
    except Exception:
        db.rollback()
        raise


def chat_history_receipt(db: Session, *, current_record: ChatRequestReceipt,
                         saved_reply: ChatMessage | None) -> dict:
    if saved_reply is not None:
        user_id, assistant_id = current_record.id, saved_reply.id
    else:
        user_id = db.query(ChatMessage.id).filter(ChatMessage.id == current_record.id,
            ChatMessage.user_id == current_record.user_id, ChatMessage.agent_mode == current_record.agent_mode,
            ChatMessage.payload['_request_token'].as_string() == current_record.token).scalar()
        assistant_id = None
    reason = admission_invalidated() if saved_reply is None else None
    if saved_reply is None:
        if user_id is None:
            reason = 'request_deleted'
        elif current_record.context_ids:
            surviving = db.query(ChatMessage.id).filter(ChatMessage.user_id == current_record.user_id,
                ChatMessage.agent_mode == current_record.agent_mode,
                ChatMessage.id.in_(current_record.context_ids)).count()
            if surviving != len(current_record.context_ids):
                reason = 'context_deleted'
    return {'history_saved':saved_reply is not None,
            'history_receipt':{'user_message_id':user_id, 'assistant_message_id':assistant_id},
            'history_invalidated':reason is not None, 'history_invalidation_reason':reason}
