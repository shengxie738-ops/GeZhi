"""Atomic, metadata-only idempotency for keyed two-message paper snapshots.

Every failure discards the caller root. Duplicate reservation gets one fresh
current read, never a second INSERT. No schema installation or external I/O.
"""
import hashlib
import json
import sqlite3

from sqlalchemy import select, or_
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app.models.chat_batch_receipt import ChatBatchReceipt
from app.models.chat_message import ChatMessage
from app.services.chat_identity import exact_owner_predicate
from app.services.chat_batch_schema import inspect_receipt_schema


class ChatBatchUnavailable(RuntimeError):
    def __init__(self,code='CHAT_BATCH_UNAVAILABLE'):
        self.code=code
        super().__init__(code)


def _rollback(db):
    """Never turn cleanup failure into a false known rollback or leaked error."""
    try:
        db.rollback()
        return True
    except Exception:
        try:
            db.close()
        except Exception:
            pass
        return False


def owner_bytes(owner):
    if type(owner) is not str or not owner or owner!=owner.strip() or len(owner)>255:
        raise ValueError('canonical account owner required')
    value=owner.encode('utf-8',errors='strict')
    if len(value)>1020:
        raise ValueError('account owner exceeds exact UTF-8 bound')
    return value


def require_schema(db,*,optional=False):
    try:
        status=inspect_receipt_schema(db.connection())
    except Exception:
        raise ChatBatchUnavailable('CHAT_BATCH_SCHEMA_UNAVAILABLE') from None
    if status=='absent' and optional:
        return False
    if status!='ready':
        raise ChatBatchUnavailable('CHAT_BATCH_SCHEMA_UNAVAILABLE')
    return True


def _scope(value):
    if value is None:
        return None
    if type(value) is not str or len(value.strip())>64:
        raise ValueError('bounded paper scope required')
    return value.strip() or None


def _fields(item,mode,conversation,project):
    return {'agent_mode':getattr(item,'agent_mode',None) or mode,
        'role':getattr(item,'role',None), 'content':getattr(item,'content',None),
        'sender_id':getattr(item,'sender_id',None),
        'conversation_id':_scope(getattr(item,'conversation_id',None) or conversation),
        'project_id':_scope(getattr(item,'project_id',None) or project),
        'payload':getattr(item,'payload',None)}


def _validate(owner,key,mode,items,conversation,project):
    encoded_owner=owner_bytes(owner)
    if type(key) is not str or not 1<=len(key)<=128:
        raise ValueError('bounded exact client request key required')
    encoded_key=key.encode('utf-8',errors='strict')
    if len(encoded_key)>512:
        raise ValueError('request key exceeds exact UTF-8 bound')
    conversation,normalized_project=_scope(conversation),_scope(project)
    if mode!='paper' or len(items)!=2:
        raise ValueError('keyed paper history requires exactly two messages')
    fields=[_fields(item,mode,conversation,normalized_project) for item in items]
    if [v['role'] for v in fields]!=['user','assistant'] or any(
        (v['agent_mode'],v['conversation_id'],v['project_id'])!=('paper',conversation,normalized_project)
        or type(v['content']) is not str or not v['content'].strip()
        or v['payload'] is not None and (type(v['payload']) is not dict or '_sync' in v['payload']) for v in fields):
        raise ValueError('paper pair must have one owned scope and user/assistant roles')
    # Preserve the previously published canonical digest for safe legacy adoption.
    body={'agent_mode':mode,'conversation_id':conversation,'project_id':project,
        'items':[item.model_dump() if hasattr(item,'model_dump') else vars(item) for item in items]}
    digest=hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    return encoded_owner,encoded_key,digest,conversation,normalized_project,fields


def _matching_rows(rows,owner,key,digest,fields):
    if len(rows)!=2:
        raise ValueError('paper receipt conflicts with existing or deleted history')
    for index,(record,expected) in enumerate(zip(rows,fields)):
        payload=record.payload or {}
        sync=payload.get('_sync',{})
        actual_payload={k:v for k,v in payload.items() if k!='_sync'} or None
        if (record.user_id!=owner or sync.get('client_request_id')!=key or sync.get('digest')!=digest
                or sync.get('index')!=index or sync.get('count')!=2
                or actual_payload!=(expected['payload'] or None)
                or any(getattr(record,name)!=expected[name] for name in expected if name!='payload')):
            raise ValueError('paper receipt conflicts with existing history')
    return rows


def _detach_and_commit(db,rows):
    # All attributes were materialized under the receipt/message locks. Keep a
    # commit-time projection, avoiding expired rows/refresh after lock release.
    for row in rows:
        # MySQL/lastrowid INSERTs need not eagerly load server TIMESTAMP defaults.
        # Load the complete response projection while this owned root is active.
        for field in ('id','user_id','agent_mode','role','content','sender_id',
                      'conversation_id','project_id','payload','created_at'):
            getattr(row,field)
        db.expunge(row)
    try:
        db.commit()
    except Exception:
        _rollback(db)
        raise ChatBatchUnavailable('CHAT_BATCH_COMMIT_UNKNOWN') from None
    return rows


def _replay(db,receipt,owner,key,digest,conversation,project,fields):
    if receipt is None:
        raise ChatBatchUnavailable('CHAT_BATCH_OUTCOME_UNKNOWN')
    if (receipt.owner_key,receipt.request_key)!=(owner_bytes(owner),key.encode()):
        raise ChatBatchUnavailable('CHAT_BATCH_RECEIPT_INVALID')
    if (receipt.request_digest,receipt.agent_mode,receipt.conversation_id,receipt.project_id)!=(digest,'paper',conversation,project):
        raise ValueError('client_request_id conflicts with existing paper receipt')
    if receipt.state=='deleted':
        raise ValueError('paper history was deleted; this request cannot recreate it')
    ids=(receipt.user_message_id,receipt.assistant_message_id)
    if receipt.state!='committed' or any(type(i) is not int or i<=0 for i in ids) or ids[0]==ids[1]:
        raise ChatBatchUnavailable('CHAT_BATCH_RECEIPT_INVALID')
    records=db.scalars(select(ChatMessage).where(exact_owner_predicate(ChatMessage.user_id,owner),ChatMessage.id.in_(ids))
        .execution_options(populate_existing=True).with_for_update()).all()
    by_id={row.id:row for row in records}
    rows=[by_id[i] for i in ids if i in by_id]
    _matching_rows(rows,owner,key,digest,fields)
    return _detach_and_commit(db,rows)


def _duplicate_reservation(error,dialect):
    if dialect=='mysql':
        return getattr(error.orig,'args',())[0:1]==(1062,)
    if dialect=='sqlite':
        return (getattr(error.orig,'sqlite_errorcode',None) in
            (sqlite3.SQLITE_CONSTRAINT_PRIMARYKEY,sqlite3.SQLITE_CONSTRAINT_UNIQUE)
            and 'chat_batch_receipts.owner_key, chat_batch_receipts.request_key' in str(error.orig))
    return False


def save_paper_pair(db,*,user_id,items,conversation_id,project_id,client_request_id):
    # A clean identity map does not prove a transaction has no flushed writes.
    # Refuse caller/external roots before any rollback, commit, flush or SQL.
    if (not isinstance(db.get_bind(),Engine) or db.in_transaction() or db.new or db.dirty
            or db.deleted or not db.is_active or db.info.get('atomic_json_store')):
        raise ChatBatchUnavailable('CHAT_BATCH_SESSION_NOT_CLEAN')
    owner_key,key,digest,conversation,project,fields=_validate(user_id,client_request_id,'paper',items,conversation_id,project_id)
    try:
        db.begin()  # This function owns only the fresh supplied Session root.
        require_schema(db)
        receipt=ChatBatchReceipt(owner_key=owner_key,request_key=key,request_digest=digest,agent_mode='paper',
            conversation_id=conversation,project_id=project,state='reserved')
        db.add(receipt)
        try:
            db.flush()  # The database unique reservation precedes any message append.
        except IntegrityError as error:
            duplicate=_duplicate_reservation(error,db.get_bind().dialect.name)
            if not _rollback(db):
                raise ChatBatchUnavailable('CHAT_BATCH_OUTCOME_UNKNOWN') from None
            if not duplicate:
                raise ChatBatchUnavailable() from None
            require_schema(db)
            winner=db.scalars(select(ChatBatchReceipt).where(ChatBatchReceipt.owner_key==owner_key,
                ChatBatchReceipt.request_key==key).execution_options(populate_existing=True).with_for_update()).one_or_none()
            return _replay(db,winner,user_id,client_request_id,digest,conversation,project,fields)
        legacy=db.scalars(select(ChatMessage).where(exact_owner_predicate(ChatMessage.user_id,user_id),
            ChatMessage.payload['_sync']['client_request_id'].as_string()==client_request_id)
            .order_by(ChatMessage.id).execution_options(populate_existing=True).with_for_update()).all()
        # Legacy JSON/text comparisons may use padding/case-insensitive MySQL
        # collations. Only exact stored owner/key values can be adopted.
        legacy=[row for row in legacy if row.user_id == user_id and isinstance(row.payload,dict)
            and isinstance(row.payload.get('_sync'),dict)
            and row.payload['_sync'].get('client_request_id') == client_request_id]
        if legacy:
            rows=_matching_rows(legacy,user_id,client_request_id,digest,fields)
            for row in rows:
                row.payload={**row.payload,'_sync':{**row.payload['_sync'],'receipt_version':1}}
        else:
            rows=[ChatMessage(user_id=user_id,**{**value,'payload':{**(value['payload'] or {}),'_sync':{
                'client_request_id':client_request_id,'digest':digest,'index':index,'count':2,'receipt_version':1}}})
                for index,value in enumerate(fields)]
            db.add_all(rows)
            db.flush()
        receipt.user_message_id,receipt.assistant_message_id=rows[0].id,rows[1].id
        receipt.state='committed'
        db.flush()
        return _detach_and_commit(db,rows)
    except ChatBatchUnavailable:
        _rollback(db)
        raise
    except ValueError:
        if not _rollback(db):
            raise ChatBatchUnavailable('CHAT_BATCH_OUTCOME_UNKNOWN') from None
        raise
    except Exception:
        rolled_back = _rollback(db)
        raise ChatBatchUnavailable('CHAT_BATCH_UNAVAILABLE' if rolled_back else 'CHAT_BATCH_OUTCOME_UNKNOWN') from None


def lock_receipts_for_deletion(db,*,user_id,agent_mode=None,message_id=None):
    """Old unkeyed history may be deleted without schema; known receipts may not."""
    if agent_mode is not None and agent_mode != 'paper':
        return []
    target=select(ChatMessage).where(exact_owner_predicate(ChatMessage.user_id,user_id),ChatMessage.agent_mode=='paper')
    if message_id is not None:
        target=target.where(ChatMessage.id==message_id)
    observed=db.scalars(target).all()  # Identification read precedes receipt locks.
    backed=[row for row in observed if isinstance(row.payload,dict)
        and isinstance(row.payload.get('_sync'),dict) and row.payload['_sync'].get('receipt_version')==1]
    if not require_schema(db,optional=True):
        if backed:
            raise ChatBatchUnavailable('CHAT_BATCH_SCHEMA_UNAVAILABLE')
        return []
    statement=select(ChatBatchReceipt).where(ChatBatchReceipt.owner_key==owner_bytes(user_id))
    if message_id is not None:
        statement=statement.where(or_(ChatBatchReceipt.user_message_id==message_id,ChatBatchReceipt.assistant_message_id==message_id))
    receipts=db.scalars(statement.order_by(ChatBatchReceipt.request_key)
        .execution_options(populate_existing=True).with_for_update()).all()
    covered=set()
    for receipt in receipts:
        ids=(receipt.user_message_id,receipt.assistant_message_id)
        if (receipt.owner_key!=owner_bytes(user_id) or receipt.agent_mode!='paper'
                or receipt.state not in ('committed','deleted') or any(type(i) is not int or i<=0 for i in ids) or ids[0]==ids[1]):
            raise ChatBatchUnavailable('CHAT_BATCH_RECEIPT_INVALID')
        pair=db.scalars(select(ChatMessage).where(ChatMessage.id.in_(ids))
            .execution_options(populate_existing=True).with_for_update()).all()
        if receipt.state=='committed' and len(pair)!=2:
            raise ChatBatchUnavailable('CHAT_BATCH_RECEIPT_INVALID')
        for row in pair:
            index=0 if row.id==ids[0] else 1
            sync=row.payload.get('_sync',{}) if isinstance(row.payload,dict) else {}
            key=sync.get('client_request_id')
            if (row.user_id!=user_id or row.agent_mode!='paper' or row.role!=('user','assistant')[index]
                    or row.conversation_id!=receipt.conversation_id or row.project_id!=receipt.project_id
                    or type(key) is not str or key.encode('utf-8')!=receipt.request_key
                    or sync.get('index')!=index or sync.get('count')!=2):
                raise ChatBatchUnavailable('CHAT_BATCH_RECEIPT_INVALID')
            # Digest/content attestation is a save/replay obligation. It does not
            # prevent legitimate owned deletion when bindings safely tombstone.
            covered.add(row.id)
    if any(row.id not in covered for row in backed):
        raise ChatBatchUnavailable('CHAT_BATCH_RECEIPT_INVALID')
    return receipts


def mark_deleted(receipts):
    for receipt in receipts:
        if receipt.state not in ('committed','deleted'):
            raise ChatBatchUnavailable('CHAT_BATCH_RECEIPT_INVALID')
        receipt.state='deleted'
