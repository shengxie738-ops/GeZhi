import os
import unittest
from unittest.mock import patch

os.environ.setdefault("RAGFLOW_API_KEY", "test")
os.environ.setdefault("RAGFLOW_BASE_URL", "http://localhost")
os.environ.setdefault("RAGFLOW_AGENT_ID", "test")
os.environ.setdefault("RAGFLOW_CHAT_ID", "test")
os.environ.setdefault("RAGFLOW_DATASET_ID", "test")
os.environ.setdefault("RAGFLOW_PUBLIC_DATASET_IDS", "")
os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("OPENAI_API_BASE", "http://localhost")

from langchain_core.messages import AIMessage, HumanMessage

from app.services import agent_workflow


class FakeModel:
    def __init__(self, model_id, calls):
        self.model_id = model_id
        self.calls = calls

    def bind_tools(self, tools):
        self.calls.append(("bind_tools", self.model_id, len(tools)))
        return self

    def stream(self, messages):
        self.calls.append(("stream", self.model_id, messages[0].content))
        yield AIMessage(content=f"model={self.model_id}")


class AgentWorkflowRoutingTest(unittest.TestCase):
    def test_request_model_overrides_default_agent_model(self):
        self.assertEqual(
            agent_workflow.resolve_runtime_model_id(
                {"configurable": {"agent_id": "agent_tutor", "agent_model": "qwen3.6-max-preview"}},
                "解释一下栈",
            ),
            "qwen3.6-max-preview",
        )

    def test_zhipu_request_model_hot_switches_agent_model(self):
        self.assertEqual(
            agent_workflow.resolve_runtime_model_id(
                {"configurable": {"agent_id": "agent_tutor", "agent_model": "glm-4.6v"}},
                "解释一下队列",
            ),
            "glm-4.6v",
        )

    def test_invalid_request_model_falls_back_to_agent_default(self):
        self.assertEqual(
            agent_workflow.resolve_runtime_model_id(
                {"configurable": {"agent_id": "agent_coder", "agent_model": "bad-model"}},
                "【用户当前代码】\nconsole.log(1)",
            ),
            "kimi-k2.7-code",
        )

    def test_call_model_invokes_selected_backend_model(self):
        calls = []

        def fake_build_chat_model(model_id, temperature=0.1):
            return FakeModel(model_id, calls)

        with patch.object(agent_workflow, "build_chat_model", side_effect=fake_build_chat_model):
            result = agent_workflow.call_model(
                {"messages": [HumanMessage(content="解释一下队列")]},
                {"configurable": {"agent_id": "agent_tutor", "agent_model": "qwen3.7-plus", "agent_prompt": "你是 Prof.X。"}},
            )

        self.assertEqual(result["messages"][0].content, "model=qwen3.7-plus")
        self.assertIn(("bind_tools", "qwen3.7-plus", len(agent_workflow.tools)), calls)
        self.assertTrue(any(call[0] == "stream" and call[1] == "qwen3.7-plus" and "你是 Prof.X。" in call[2] for call in calls))

    def test_paper_agent_model_and_academic_prompt(self):
        # 1. 默认模型为 qwen3.7-plus
        model_id = agent_workflow.resolve_runtime_model_id(
            {"configurable": {"agent_id": "agent_paper"}},
            "请查询关于 Transformer 的论文",
        )
        self.assertEqual(model_id, "qwen3.7-plus")

        # 2. 学术 Prompt 正确注入（包含文献检索与研读指令，且绝非数据结构私教苏格拉底提问）
        system_msg = agent_workflow.build_system_prompt(agent_id="agent_paper", agent_mode="paper")
        self.assertIn("PaperBot", system_msg.content)
        self.assertIn("BibTeX", system_msg.content)
        self.assertNotIn("苏格拉底启发式教学法", system_msg.content)

        # 3. 验证 call_model 正确读取 paper agent 专属 Prompt
        calls = []

        def fake_build_chat_model(m_id, temperature=0.1):
            return FakeModel(m_id, calls)

        with patch.object(agent_workflow, "build_chat_model", side_effect=fake_build_chat_model):
            result = agent_workflow.call_model(
                {"messages": [HumanMessage(content="查询关于 Diffusion 模型的最新进展")]},
                {"configurable": {"agent_id": "agent_paper", "agent_mode": "paper"}},
            )

        self.assertEqual(result["messages"][0].content, "model=qwen3.7-plus")
        self.assertTrue(any(call[0] == "stream" and "BibTeX" in call[2] for call in calls))


if __name__ == "__main__":
    unittest.main()
