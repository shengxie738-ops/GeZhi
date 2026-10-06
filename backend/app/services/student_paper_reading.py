"""Server-owned paper deadline; no client-controlled timeout or I/O here."""
import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import time


PAPER_REQUEST_TIMEOUT_SECONDS = 90.0
_paper_state = ContextVar("student_paper_request", default=None)


@dataclass
class PaperRequestState:
    deadline: float
    origin: object = None
    write_started: bool = False


def paper_deadline():
    # Tests may shorten this internal constant; neither HTTP nor config can
    # extend the fixed production maximum.
    return time.monotonic() + min(90.0, max(0.001, PAPER_REQUEST_TIMEOUT_SECONDS))


@contextmanager
def paper_request_scope(deadline=None):
    state = PaperRequestState(deadline if deadline is not None else paper_deadline())
    token = _paper_state.set(state)
    try:
        yield state
    finally:
        _paper_state.reset(token)


def current_paper_state():
    return _paper_state.get()


def paper_remaining_seconds():
    state = current_paper_state()
    remaining = state.deadline - time.monotonic() if state else min(90.0, PAPER_REQUEST_TIMEOUT_SECONDS)
    if remaining <= 0:
        raise TimeoutError("paper deadline expired")
    return remaining


def remember_paper_origin(origin):
    state = current_paper_state()
    if state:
        state.origin = origin


def mark_paper_write():
    state = current_paper_state()
    if state:
        paper_remaining_seconds()
        state.write_started = True


def paper_timeout_scope():
    state = current_paper_state()
    return asyncio.timeout_at(state.deadline)
