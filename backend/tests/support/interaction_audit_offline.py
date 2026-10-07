"""Offline actual-router harness. Synthetic SQLite only; no app startup or AI."""
import socket
import sys
from types import ModuleType


def _blocked(*args, **kwargs):
    raise AssertionError("External network calls are forbidden in this audit")


# Install the guard before importing application modules. ASGITransport is in-process.
socket.socket.connect = _blocked
socket.socket.connect_ex = _blocked
socket.create_connection = _blocked
socket.getaddrinfo = _blocked

# This unavailable external adapter is the only module substitution. The actual
# routers, auth, current DB identity, JsonStore and SQLAlchemy models are exercised.
adapter = ModuleType("app.services.model_registry")
adapter.build_chat_model = _blocked
sys.modules[adapter.__name__] = adapter
