"""Resolve a signed subject to its current canonical account.

Tokens identify an account; their role claim is not permission authority.
This module deliberately does not serialize accounts or contact other services.
"""
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.user_account import UserAccount


def load_current_account(db: Session, subject: str, *, lock: bool = False) -> UserAccount:
    if not isinstance(subject, str) or not subject:
        raise HTTPException(status_code=401, detail="invalid token")
    query = db.query(UserAccount).filter(UserAccount.username == subject).populate_existing()
    if lock:
        query = query.with_for_update()
    account = query.first()
    if not account or account.role not in {"student", "teacher"}:
        raise HTTPException(status_code=401, detail="user not found or invalid account")
    return account


def resolve_current_account(authorization: str | None, db: Session) -> UserAccount:
    if not isinstance(authorization, str) or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="not authenticated")
    claims = decode_access_token(authorization.split(" ", 1)[1])
    if not isinstance(claims, dict):
        raise HTTPException(status_code=401, detail="invalid token")
    return load_current_account(db, claims.get("sub"))


def get_current_account(
    authorization: str | None = Header(default=None), db: Session = Depends(get_db)
) -> UserAccount:
    return resolve_current_account(authorization, db)


def get_optional_current_account(
    authorization: str | None = Header(default=None), db: Session = Depends(get_db)
) -> UserAccount | None:
    # A supplied invalid credential must not silently become anonymous.
    return None if authorization is None else resolve_current_account(authorization, db)
