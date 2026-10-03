"""Intercepted lifecycle evidence only; no real MySQL connections."""
import importlib
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def feature(name):
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        pytest.fail(f"Task3 feature absent: {name}: {exc}")


class Connection:
    def __init__(self, trace):
        self.trace = trace
        self.dialect = SimpleNamespace(name="mysql")
        self.started = False
    def in_transaction(self):
        return self.started
    def execution_options(self, **values):
        assert not self.started
        self.trace.append(("isolation", values)); return self
    def close(self):
        self.trace.append("connection_close_pool_restore")


class FakeSession:
    def __init__(self, bind, **kw):
        self.bind, self.trace, self.info = bind, bind.trace, {}
        self.active = False
        self.trace.append("session")
    def begin(self):
        assert not self.active
        self.active = True; self.bind.started = True
        self.trace.append("begin")
    def in_transaction(self):
        return self.active
    def rollback(self):
        self.active = False; self.trace.append("rollback")
    def close(self):
        self.trace.append("session_close")
    def commit(self):
        pytest.fail("opener must never commit")


def test_teaching_isolation_is_set_before_identity_and_cleanup(monkeypatch):
    module = feature("app.services.teaching.sessions")
    trace = []
    connection = Connection(trace)
    engine = SimpleNamespace(connect=lambda: trace.append("connect") or connection,
                             dialect=SimpleNamespace(name="mysql"))
    monkeypatch.setattr(module, "Session", FakeSession)
    with module.open_teaching_session(engine) as db:
        trace.append("identity_select")
        assert db.info["teaching_transaction"] == "READ COMMITTED"
    assert trace == ["connect", ("isolation", {"isolation_level": "READ COMMITTED"}), "session", "begin", "identity_select", "rollback", "session_close", "connection_close_pool_restore"]


def test_opener_refuses_begun_session_and_preserves_legacy_sqlite():
    module = feature("app.services.teaching.sessions")
    engine = create_engine("sqlite:///:memory:")
    with Session(engine) as legacy:
        legacy.begin()
        with pytest.raises((HTTPException, TypeError)):
            with module.open_teaching_session(legacy):
                pytest.fail("accepted legacy session")
        assert legacy.in_transaction()
    with engine.connect() as connection:
        assert connection.get_isolation_level() == "SERIALIZABLE"
    with pytest.raises(HTTPException):
        with module.open_teaching_session(engine):
            pytest.fail("SQLite is not a production teaching opener")
    engine.dispose()


def test_opener_cleanup_when_body_raises(monkeypatch):
    module = feature("app.services.teaching.sessions")
    trace = []
    connection = Connection(trace)
    engine = SimpleNamespace(connect=lambda: connection, dialect=SimpleNamespace(name="mysql"))
    monkeypatch.setattr(module, "Session", FakeSession)
    with pytest.raises(ValueError):
        with module.open_teaching_session(engine):
            raise ValueError("synthetic body failure")
    assert trace[-3:] == ["rollback", "session_close", "connection_close_pool_restore"]
