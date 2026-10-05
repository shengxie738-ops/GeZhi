"""Real FastAPI/Pydantic parsing of extracted student chat route functions.

The actual route functions and streaming response class execute from source,
with synthetic authentication/storage/model dependencies from the focused
contract harness. HTTP uses in-process ASGITransport, not a listening server.
No production app startup, auth verifier, database, provider, or browser runs.
This is request/response integration, not live deployment or SQL verification.
"""
from __future__ import annotations

import ast
import asyncio
import json
import unittest

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
import httpx

from test_student_work_skills import ENDPOINT, RecordingPorts, SKILL_ID, load_endpoints


def make_app(ports):
    routes = load_endpoints(ports)
    namespace = routes.chat.__globals__
    namespace.update({"asyncio": asyncio, "HTTPException": HTTPException,
                      "Session": object, "Request": Request, "StreamingResponse": StreamingResponse})
    tree = ast.parse(ENDPOINT.read_text(encoding="utf-8"))
    response = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                    and node.name == "AdmittedChatStreamingResponse")
    selected = ast.Module(body=[response], type_ignores=[])
    ast.fix_missing_locations(selected)
    exec(compile(selected, str(ENDPOINT), "exec"), namespace)

    async def synthetic_auth(authorization: str | None = Header(default=None)):
        if authorization != "Bearer synthetic-alice-token":
            raise HTTPException(status_code=401, detail="synthetic authentication required")
        return {"sub": "alice", "role": "student"}

    def synthetic_db():
        return ports.db

    routes.chat.__defaults__ = (Depends(synthetic_auth), Depends(synthetic_db), None)
    routes.chat_stream.__defaults__ = (Depends(synthetic_auth), Depends(synthetic_db))
    app = FastAPI()
    app.add_api_route("/chat", routes.chat, methods=["POST"])
    app.add_api_route("/chat/stream", routes.chat_stream, methods=["POST"])
    return app


def post(app, path, body, *, authenticated=True):
    async def request():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://synthetic-asgi.invalid") as client:
            headers = {"Authorization": "Bearer synthetic-alice-token"} if authenticated else {}
            return await client.post(path, json=body, headers=headers)
    return asyncio.run(request())


def body_for(**changes):
    body = {"message": "Review this supplied abstract", "agent_mode": "paper", "conversation_id": "task-a",
            "agent_model": "synthetic-private-model", "skill_ids": [SKILL_ID],
            "sessionId": "bob", "thread_id": "bob", "agent_prompt": "CLIENT OVERRIDE"}
    body.update(changes)
    return body


def completion(response, path):
    if path == "/chat":
        return response.json()
    events = [json.loads(line.removeprefix("data: ").strip()) for line in response.text.splitlines()
              if line.startswith("data: ")]
    return events[-1]


class StudentWorkSkillAsgiTests(unittest.TestCase):
    def test_real_request_schema_rejects_unknown_duplicate_and_malformed_skills(self):
        for path in ("/chat", "/chat/stream"):
            for value in (["unknown"], [SKILL_ID, SKILL_ID], SKILL_ID, {}, [1], [None]):
                with self.subTest(path=path, value=value):
                    ports = RecordingPorts()
                    response = post(make_app(ports), path, body_for(skill_ids=value))
                    self.assertEqual(response.status_code, 422)
                    self.assertEqual(ports.user_rows, [])
                    self.assertEqual(ports.model_inputs, [])

    def test_route_rejects_unsupported_skill_modes_before_storage_and_model(self):
        invalid = [{"agent_mode": "rag"}, {"agent_mode": "tutor"}, {"agent_mode": "coding"},
                   {"force_rag": True}, {"repository_id": "repo"}, {"is_diagnosis": True}]
        for path in ("/chat", "/chat/stream"):
            for changes in invalid:
                with self.subTest(path=path, changes=changes):
                    ports = RecordingPorts()
                    response = post(make_app(ports), path, body_for(**changes))
                    self.assertEqual(response.status_code, 422)
                    self.assertEqual(ports.user_rows, [])
                    self.assertEqual(ports.model_inputs, [])

    def test_selected_route_binds_verified_synthetic_owner_and_saves_actual_output(self):
        for path in ("/chat", "/chat/stream"):
            for mode in ("chat", "paper"):
                with self.subTest(path=path, mode=mode):
                    ports = RecordingPorts()
                    response = post(make_app(ports), path, body_for(agent_mode=mode))
                    self.assertEqual(response.status_code, 200)
                    if path == "/chat/stream":
                        self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
                    result = completion(response, path)
                    self.assertTrue(result["history_saved"])
                    self.assertEqual(result["history_receipt"], {"user_message_id": 1, "assistant_message_id": 2})
                    self.assertEqual(result.get("final_content", result.get("reply")), ports.answer)
                    self.assertEqual(ports.user_rows[0].user_id, "alice")
                    self.assertEqual(ports.credentials_owners, [("alice", "synthetic-private-model")])
                    self.assertNotIn("CLIENT OVERRIDE", ports.model_inputs[0][0].content)
                    self.assertEqual(ports.graph_calls, [])

    def test_missing_synthetic_authentication_never_persists_or_calls_model(self):
        for path in ("/chat", "/chat/stream"):
            with self.subTest(path=path):
                ports = RecordingPorts()
                response = post(make_app(ports), path, body_for(), authenticated=False)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(ports.user_rows, [])
                self.assertEqual(ports.model_inputs, [])

    def test_selected_provider_failure_reports_unsaved_completion_without_fallback(self):
        for path in ("/chat", "/chat/stream"):
            with self.subTest(path=path):
                ports = RecordingPorts()
                ports.failure = RuntimeError("UPSTREAM PRIVATE BODY")
                response = post(make_app(ports), path, body_for())
                self.assertEqual(response.status_code, 200)
                result = completion(response, path)
                self.assertFalse(result["history_saved"])
                self.assertEqual(result["delivery_status"], "failed")
                self.assertEqual(result.get("final_content", result.get("reply")), "")
                self.assertNotIn("UPSTREAM PRIVATE BODY", response.text)
                self.assertEqual(ports.reply_rows, [])
                self.assertEqual(ports.graph_calls, [])


if __name__ == "__main__":
    unittest.main()
