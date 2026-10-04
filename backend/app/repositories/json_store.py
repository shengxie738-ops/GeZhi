from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import time
import uuid
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from app.models.domain_record import DomainRecord


def make_record_key(prefix: str) -> str:
    return f"{prefix}-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"


def load_payload(record: DomainRecord | None) -> dict[str, Any] | None:
    if not record:
        return None
    try:
        data = json.loads(record.payload)
    except Exception:
        data = {}
    if isinstance(data, dict):
        data.setdefault("id", record.record_key)
        return data
    return {"id": record.record_key, "value": data}


def _require_json_value(value: object) -> None:
    """Caller-owned mode must not normalize Python-only values into JSON."""
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError("JSON object keys must be strings")
            _require_json_value(item)
    elif type(value) is list:
        for item in value:
            _require_json_value(item)
    elif value is not None and type(value) not in (str, int, float, bool):
        raise ValueError("exact JSON-compatible values required")


class JsonStore:
    def __init__(self, db: Session, *, commit_policy: str = "legacy", record_model=None):
        if commit_policy not in ("legacy", "caller_owned"):
            raise ValueError("unknown JsonStore commit policy")
        if record_model is None:
            from app.models.domain_record import DomainRecord
            record_model = DomainRecord
        self.db = db
        self.commit_policy = commit_policy
        self.record_model = record_model

    def _require_mutation(self) -> None:
        if self.commit_policy == "caller_owned" and self.db.in_transaction() is not True:
            raise ValueError("active caller transaction required")

    def list_payloads(
        self,
        module: str,
        record_type: str | None = None,
        owner_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        model = self.record_model
        query = self.db.query(model).filter(model.module == module)
        if record_type is not None:
            query = query.filter(model.record_type == record_type)
        if owner_id is not None:
            query = query.filter(model.owner_id == owner_id)
        if status is not None:
            query = query.filter(model.status == status)
        records = query.order_by(model.created_at.desc(), model.id.desc()).all()
        return [payload for payload in (load_payload(record) for record in records) if payload is not None]

    def get_record(
        self,
        module: str,
        record_type: str,
        record_key: str,
        owner_id: str | None = None,
    ) -> DomainRecord | None:
        model = self.record_model
        query = self.db.query(model).filter(
            model.module == module,
            model.record_type == record_type,
            model.record_key == record_key,
        )
        if owner_id is not None:
            query = query.filter(model.owner_id == owner_id)
        if self.commit_policy == "caller_owned" or self.db.info.get("atomic_json_store"):
            query = query.with_for_update()
        return query.order_by(model.id.desc()).first()

    def get_payload(
        self,
        module: str,
        record_type: str,
        record_key: str,
        owner_id: str | None = None,
    ) -> dict[str, Any] | None:
        return load_payload(self.get_record(module, record_type, record_key, owner_id))

    def upsert(
        self,
        module: str,
        record_type: str,
        record_key: str,
        payload: dict[str, Any],
        owner_id: str = "",
        role: str = "",
        status: str = "",
    ) -> dict[str, Any]:
        self._require_mutation()
        if self.commit_policy == "caller_owned":
            if type(payload) is not dict:
                raise ValueError("caller-owned payload must be a JSON object")
            _require_json_value(payload)
        payload = dict(payload or {})
        payload.setdefault("id", record_key)
        encoded = (json.dumps(payload, ensure_ascii=False, allow_nan=False)
                   if self.commit_policy == "caller_owned" else json.dumps(payload, ensure_ascii=False, default=str))
        record = self.get_record(module, record_type, record_key, owner_id=owner_id)
        if not record:
            record = self.record_model(
                module=module,
                record_type=record_type,
                record_key=record_key,
                owner_id=owner_id or "",
                role=role or "",
            )
            self.db.add(record)
        record.status = status or payload.get("status") or record.status or ""
        record.payload = encoded
        record.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        if self.commit_policy == "caller_owned" or self.db.info.get("atomic_json_store"):
            self.db.flush()
        else:
            self.db.commit()
        self.db.refresh(record)
        return load_payload(record) or payload

    def create(
        self,
        module: str,
        record_type: str,
        payload: dict[str, Any],
        prefix: str,
        owner_id: str = "",
        role: str = "",
        status: str = "",
    ) -> dict[str, Any]:
        record_key = str((payload or {}).get("id") or make_record_key(prefix))
        return self.upsert(module, record_type, record_key, payload, owner_id=owner_id, role=role, status=status)

    def patch(
        self,
        module: str,
        record_type: str,
        record_key: str,
        patch: dict[str, Any],
        owner_id: str | None = None,
    ) -> dict[str, Any] | None:
        self._require_mutation()
        record = self.get_record(module, record_type, record_key, owner_id=owner_id)
        payload = load_payload(record)
        if not record or payload is None:
            return None
        payload.update(patch or {})
        return self.upsert(
            module,
            record_type,
            record.record_key,
            payload,
            owner_id=record.owner_id,
            role=record.role,
            status=payload.get("status") or record.status,
        )

    def delete(self, module: str, record_type: str, record_key: str) -> bool:
        if self.commit_policy == "caller_owned":
            raise ValueError("caller-owned delete is outside this participation contract")
        record = self.get_record(module, record_type, record_key)
        if not record:
            return False
        self.db.delete(record)
        self.db.commit()
        return True


@contextmanager
def atomic_store(db: Session):
    """Opt-in unit of work. Existing callers retain immediate-commit semantics."""
    if db.info.get("atomic_json_store"):
        yield
        return
    db.info["atomic_json_store"] = True
    try:
        yield
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.info.pop("atomic_json_store", None)
