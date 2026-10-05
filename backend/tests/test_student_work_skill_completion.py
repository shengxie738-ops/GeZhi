"""Selected-skill completion and credential-failure regressions, synthetic only.

Actual route and credential-helper functions execute from source AST. Recording
query/decrypt failures demonstrate routing behavior, not a real account failure.
No application startup, SQL, credentials, provider, server, or browser runs.
"""
from __future__ import annotations

import ast
import asyncio
from types import SimpleNamespace
import unittest

from test_student_work_skills import ENDPOINT, RecordingPorts, SKILL_ID, load_endpoints, load_helper, parse_events


def load_routes(ports):
    routes = load_endpoints(ports)
    helper = load_helper()
    classifier = getattr(helper, "classify_student_skill_completion", None)
    if callable(classifier):
        routes.chat.__globals__["classify_student_skill_completion"] = classifier
    return routes


def execute(routes, ports, *, stream, skill_ids=None, model="glm-5.1"):
    request = routes.ChatRequest(message="Review supplied abstract", agent_mode="chat", sessionId="alice",
                                 agent_model=model, conversation_id="task-a", skill_ids=skill_ids)
    async def run():
        if stream:
            return parse_events([value async for value in routes.stream_chat_events(request, ports.db)])
        return await routes.chat(request, auth={"sub": "alice"}, db=ports.db)
    result = asyncio.run(run())
    return result[-1] if stream else result


def completion_model(ports, reason):
    class SyntheticModel:
        async def ainvoke(self, messages):
            ports.model_inputs.append(messages)
            return SimpleNamespace(content=ports.answer, response_metadata={"finish_reason": reason})

        async def astream(self, messages):
            ports.model_inputs.append(messages)
            yield SimpleNamespace(content=ports.answer, response_metadata={})
            # A contentless terminal chunk is still relevant to honest completion.
            yield SimpleNamespace(content="", response_metadata={"finish_reason": reason})

    return lambda *_args, **_kwargs: SyntheticModel()


def use_actual_credential_helper(routes, ports, failure):
    namespace = routes.chat.__globals__
    tree = ast.parse(ENDPOINT.read_text(encoding="utf-8"))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name in {"find_user_custom_model_credentials", "get_request_chat_model",
                                   "is_configured_model_unavailable"}]
    assert len(functions) == 3, "actual credential/configured-model/model-constructor boundaries are required"
    selected = ast.Module(body=functions, type_ignores=[])
    ast.fix_missing_locations(selected)
    namespace["UserCustomAIModel"] = SimpleNamespace(user_id="synthetic_user_id_column", is_active=True)
    exec(compile(selected, str(ENDPOINT), "exec"), namespace)
    ports.constructed_models = []

    def registry_model(model_id, **options):
        ports.constructed_models.append(("registry", model_id))
        return ports.model({"configurable": {"agent_model": model_id}}, **options)

    def custom_model(**options):
        ports.constructed_models.append(("custom", options["model"]))
        return ports.model({"configurable": {"agent_model": options["model"]}})

    # glm-5.1 is a registry ID and also permitted by custom registration.
    namespace.update({"has_model": lambda model_id, **_kwargs: model_id == "glm-5.1",
                      "build_chat_model": registry_model, "ChatOpenAI": custom_model})

    class CredentialDb:
        def query(self, _model):
            if failure == "lookup":
                raise RuntimeError("synthetic lookup failure")
            return self

        def filter(self, *_criteria):
            return self

        def all(self):
            def decrypt():
                if failure == "decrypt":
                    raise RuntimeError("synthetic decryption failure")
                return "" if failure == "empty_key" else " \t" if failure == "whitespace_key" else "synthetic-owner-key"
            base_url = "" if failure == "empty_url" else " \t" if failure == "whitespace_url" else "https://synthetic.invalid/v1"
            return [SimpleNamespace(model_ids=["glm-5.1"], base_url=base_url,
                                    get_decrypted_api_key=decrypt)]

        def rollback(self):
            ports.events.append("rollback")

    ports.db = CredentialDb()


class StudentWorkSkillCompletionTests(unittest.TestCase):
    def test_pure_classifier_distinguishes_known_incomplete_stop_and_unknown(self):
        helper = load_helper()
        classifier = getattr(helper, "classify_student_skill_completion", None)
        self.assertTrue(callable(classifier), "selected-skill completion classifier is missing")
        for reason in ("length", "content_filter", "tool_calls"):
            self.assertEqual(classifier({"finish_reason": reason}), "incomplete")
        self.assertEqual(classifier({"finish_reason": "stop"}), "complete")
        for metadata in ({}, None, {"finish_reason": None}, {"finish_reason": "unknown-provider-marker"}):
            self.assertEqual(classifier(metadata), "unknown")

    def test_known_incomplete_nonempty_response_never_saves_or_reports_success(self):
        for stream in (False, True):
            for reason in ("length", "content_filter", "tool_calls"):
                with self.subTest(stream=stream, reason=reason):
                    ports = RecordingPorts()
                    routes = load_routes(ports)
                    routes.chat.__globals__["get_request_chat_model"] = completion_model(ports, reason)
                    response = execute(routes, ports, stream=stream, skill_ids=[SKILL_ID])
                    self.assertEqual(response.get("delivery_status"), "failed")
                    self.assertFalse(response["history_saved"])
                    self.assertEqual(response.get("final_content", response.get("reply")), "")
                    self.assertEqual(ports.reply_rows, [])
                    self.assertEqual(ports.graph_calls, [])

    def test_missing_or_unknown_metadata_preserves_answer_with_explicit_unknown_status(self):
        for stream in (False, True):
            for reason in (None, "unknown-provider-marker"):
                with self.subTest(stream=stream, reason=reason):
                    ports = RecordingPorts()
                    routes = load_routes(ports)
                    routes.chat.__globals__["get_request_chat_model"] = completion_model(ports, reason)
                    response = execute(routes, ports, stream=stream, skill_ids=[SKILL_ID])
                    self.assertTrue(response["history_saved"])
                    self.assertEqual(response.get("final_content", response.get("reply")), ports.answer)
                    self.assertEqual(response.get("model_completion_status"), "unknown")

    def test_explicit_stop_has_complete_model_status(self):
        for stream in (False, True):
            with self.subTest(stream=stream):
                ports = RecordingPorts()
                routes = load_routes(ports)
                routes.chat.__globals__["get_request_chat_model"] = completion_model(ports, "stop")
                response = execute(routes, ports, stream=stream, skill_ids=[SKILL_ID])
                self.assertTrue(response["history_saved"])
                self.assertEqual(response.get("model_completion_status"), "complete")

    def test_selected_credential_lookup_or_decrypt_failure_does_not_fall_back(self):
        for stream in (False, True):
            for failure in ("lookup", "decrypt", "empty_key", "empty_url", "whitespace_key", "whitespace_url"):
                with self.subTest(stream=stream, failure=failure):
                    ports = RecordingPorts()
                    routes = load_routes(ports)
                    use_actual_credential_helper(routes, ports, failure)
                    response = execute(routes, ports, stream=stream, skill_ids=[SKILL_ID])
                    self.assertFalse(response["history_saved"])
                    self.assertEqual(response["delivery_status"], "failed")
                    self.assertEqual(ports.model_inputs, [])
                    self.assertEqual(ports.constructed_models, [])
                    self.assertEqual(ports.reply_rows, [])
                    self.assertEqual(ports.graph_calls, [])

    def test_unselected_credential_failure_keeps_legacy_graph_behavior(self):
        for stream in (False, True):
            for failure in ("lookup", "decrypt", "empty_key", "empty_url", "whitespace_key", "whitespace_url"):
                with self.subTest(stream=stream, failure=failure):
                    ports = RecordingPorts()
                    routes = load_routes(ports)
                    use_actual_credential_helper(routes, ports, failure)
                    response = execute(routes, ports, stream=stream, skill_ids=[])
                    self.assertTrue(response["history_saved"])
                    self.assertEqual(len(ports.graph_calls), 1)
                    self.assertEqual(ports.model_inputs, [])
                    self.assertNotIn("model_completion_status", response)


if __name__ == "__main__":
    unittest.main()
