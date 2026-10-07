"""Self-only privacy policy; extracted route + real auth/service + SQLite.

This deliberately does not import the full chat/agent/provider stack. It runs
the unchanged get_chat_history body and existing _ensure_self helper from source,
with production current-account auth and SQL history storage.
"""
import ast
from pathlib import Path

import pytest
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import ensure_self_or_teacher, get_auth_payload
from app.api.endpoints import homework
from app.core.database import get_db
from app.core.miniprogram_response import api_response, is_miniprogram_client, page_items
from app.models.chat_message import ChatMessage
from app.services.chat_history import list_chat_history_page, normalize_agent_mode, save_chat_message
from tests.native_interaction_audit_teacher_student import request, world

MODES_AND_ALIASES = ["chat", "paper", "tutor", "rag", "default", "general", "academic", "scholar",
                     "agent_paper", "researcher", "agent_researcher", "agent_tutor"]


@pytest.fixture
def history_world(world):
    app, sessions = world
    source = Path(homework.__file__).with_name("chat.py")
    parsed = ast.parse(source.read_text())
    nodes = [node for node in parsed.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
             and node.name in ("get_chat_history", "_ensure_self")]
    assert len(nodes) == 2
    for node in nodes:
        node.decorator_list = []
    namespace = {"Session": Session, "Depends": Depends, "Header": Header,
                 "HTTPException": HTTPException, "get_db": get_db, "get_auth_payload": get_auth_payload,
                 "ensure_self_or_teacher": ensure_self_or_teacher,
                 "list_chat_history_page": list_chat_history_page,
                 "api_response": api_response, "is_miniprogram_client": is_miniprogram_client,
                 "page_items": page_items}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), namespace)
    app.add_api_route("/chat/history", namespace["get_chat_history"], methods=["GET"])
    with sessions() as db:
        ChatMessage.__table__.create(db.get_bind())
        for owner in ("20260001", "teacher"):
            for mode in ("chat", "paper", "tutor", "rag"):
                save_chat_message(db, user_id=owner, agent_mode=mode, role="user",
                                  content=f"private-synthetic-{owner}-{mode}", conversation_id="private-task")
    yield app, sessions


@pytest.mark.parametrize("mode", MODES_AND_ALIASES)
def test_assigned_teacher_cannot_read_personal_student_history(history_world, mode):
    app, _ = history_world
    response = request(app, "GET", f"/chat/history?session_id=20260001&agent_mode={mode}&conversation_id=private-task")
    assert response.status_code == 403 and "private-synthetic" not in response.text


@pytest.mark.parametrize("mode", MODES_AND_ALIASES)
def test_peer_and_unassigned_teacher_cannot_read_student_history(history_world, mode):
    app, _ = history_world
    path = f"/chat/history?session_id=20260001&agent_mode={mode}&conversation_id=private-task"
    for actor, claim in (("20260002", "student"), ("other-teacher", "teacher"), ("20260002", "teacher")):
        response = request(app, "GET", path, user=actor, role=claim)
        assert response.status_code == 403 and "private-synthetic" not in response.text


@pytest.mark.parametrize("mode", MODES_AND_ALIASES)
def test_each_current_account_reads_only_its_requested_owned_history(history_world, mode):
    app, _ = history_world
    for actor, role in (("20260001", "student"), ("teacher", "teacher")):
        response = request(app, "GET", f"/chat/history?session_id={actor}&agent_mode={mode}&conversation_id=private-task",
                           user=actor, role=role)
        assert response.status_code == 200
        assert len(response.json()["data"]) == 1
        assert response.json()["data"][0]["content"] == f"private-synthetic-{actor}-{normalize_agent_mode(mode)}"


@pytest.mark.parametrize("selector", ["sessionId", "thread_id", "user_id"])
def test_unsupported_identity_selector_aliases_do_not_grant_history_access(history_world, selector):
    app, _ = history_world
    response = request(app, "GET", f"/chat/history?{selector}=20260001&agent_mode=paper")
    assert response.status_code == 422 and "private-synthetic" not in response.text


def test_owner_cannot_select_peer_via_extra_identity_alias(history_world):
    app, _ = history_world
    response = request(app, "GET", "/chat/history?session_id=20260001&sessionId=20260002&agent_mode=paper",
                       user="20260001", role="student")
    assert response.status_code == 200
    assert response.json()["data"][0]["user_id"] == "20260001"
