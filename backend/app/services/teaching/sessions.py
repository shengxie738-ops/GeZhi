"""Dedicated B1 connection ownership; no global isolation changes or commits."""
from contextlib import contextmanager

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.teaching.policy import capture_deployment_policy


# Stable process initialization only. Every dedicated session reads the same
# complete frozen generation; mutating Settings cannot change an active policy.
# Deployment changes require restart and an operator-owned multi-worker gate.
_DEPLOYMENT_POLICY_INPUTS = capture_deployment_policy(settings)


def _deployment_policy_provider():
    return _DEPLOYMENT_POLICY_INPUTS


@contextmanager
def open_teaching_session(engine):
    """Set isolation before Session/identity SQL; always return a clean connection.

    Engine.connect() gives this request exclusive connection ownership. Closing
    it restores SQLAlchemy's pool isolation state. Real vendor/pool behavior is
    an outstanding integration gate; intercepted tests prove ordering only.
    Existing Sessions/connections are deliberately not adopted or restarted.
    """
    if isinstance(engine, Session) or not callable(getattr(engine, "connect", None)):
        raise TypeError("a dedicated Engine is required, not an existing Session")
    if engine.dialect.name != "mysql":
        raise HTTPException(503, "database_unavailable")
    connection = engine.connect()
    db = None
    try:
        if connection.in_transaction():
            raise HTTPException(503, "lock_orchestration_required")
        connection = connection.execution_options(isolation_level="READ COMMITTED")
        db = Session(bind=connection, autoflush=False, expire_on_commit=False)
        db.begin()
        db.info["teaching_transaction"] = "READ COMMITTED"
        db.info["teaching_policy_provider"] = _deployment_policy_provider
        yield db
    finally:
        try:
            if db is not None:
                try:
                    if db.in_transaction():
                        db.rollback()
                finally:
                    db.close()
        finally:
            connection.close()
