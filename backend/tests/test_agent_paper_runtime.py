import os
import unittest
from unittest.mock import patch, MagicMock

os.environ.setdefault("RAGFLOW_API_KEY", "test")
os.environ.setdefault("RAGFLOW_BASE_URL", "http://localhost")
os.environ.setdefault("RAGFLOW_AGENT_ID", "test")
os.environ.setdefault("RAGFLOW_CHAT_ID", "test")
os.environ.setdefault("RAGFLOW_DATASET_ID", "test")
os.environ.setdefault("RAGFLOW_PUBLIC_DATASET_IDS", "")
os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("OPENAI_API_BASE", "http://localhost")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from langchain_core.messages import AIMessage, HumanMessage

from app.core.database import Base
from app.models.chat_message import ChatMessage
from app.schemas.chat import ChatRequest
from app.services import agent_workflow
from app.services.default_agents import (
    get_default_agents,
    get_default_agent,
    get_default_agent_prompt,
)
from app.services.chat_history import (
    build_agent_thread_id,
    clear_chat_history,
    delete_chat_message,
    list_chat_history,
    normalize_agent_mode,
    save_chat_message,
)
from app.api.endpoints.chat import (
    build_agent_runtime_config,
    resolve_agent_mode,
    resolve_request_agent_id,
    resolve_thread_id,
    get_runtime_agent_id,
)
from app.services.model_registry import has_model


class FakeModel:
    def __init__(self, model_id, calls):
        self.model_id = model_id
        self.calls = calls

    def bind_tools(self, tools):
        self.calls.append(("bind_tools", self.model_id, len(tools)))
        return self

    def stream(self, messages):
        self.calls.append(("stream", self.model_id, messages[0].content))
        yield AIMessage(content=f"PaperBot Review response for {self.model_id}")


class AgentPaperRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)

    def test_01_agent_paper_definition_and_registration(self):
        """验证 agent_paper 的元数据字段完整性与模型映射"""
        defaults = get_default_agents()
        paper_agent = next((a for a in defaults if a["id"] == "agent_paper"), None)
        self.assertIsNotNone(paper_agent, "DEFAULT_AGENTS 必须包含 agent_paper")
        self.assertEqual(paper_agent["name"], "PaperBot")
        self.assertEqual(paper_agent["role"], "学术论文与文献研读专家")
        self.assertEqual(paper_agent["modelCategory"], "text")
        self.assertEqual(paper_agent["model"], "qwen3.7-plus")
        self.assertTrue(paper_agent["isActive"])
        self.assertIn("学术论文检索与文献研读专家", paper_agent["prompt"])
        self.assertIn("BibTeX", paper_agent["prompt"])

        # 验证默认模型注册
        self.assertIn("agent_paper", agent_workflow.DEFAULT_AGENT_MODELS)
        self.assertEqual(agent_workflow.DEFAULT_AGENT_MODELS["agent_paper"], "qwen3.7-plus")
        self.assertTrue(has_model("qwen3.7-plus", category="text"))

        # 验证辅助读取方法
        agent = get_default_agent("agent_paper")
        self.assertIsNotNone(agent)
        prompt = get_default_agent_prompt("agent_paper")
        self.assertTrue(len(prompt) > 50)
        self.assertIn("PaperBot", prompt)

    def test_02_agent_mode_normalization_and_resolution(self):
        """验证 agent_mode 归一化与路由分发的双向推断逻辑"""
        # normalize_agent_mode 针对多种论文模式变体的归一化
        self.assertEqual(normalize_agent_mode("paper"), "paper")
        self.assertEqual(normalize_agent_mode("academic"), "paper")
        self.assertEqual(normalize_agent_mode("scholar"), "paper")
        self.assertEqual(normalize_agent_mode("agent_paper"), "paper")
        self.assertEqual(normalize_agent_mode(" PAPER "), "paper")

        # resolve_agent_mode 从 ChatRequest 属性解析
        req_mode = ChatRequest(message="transformer", agent_mode="paper")
        self.assertEqual(resolve_agent_mode(req_mode), "paper")

        req_mode_alias = ChatRequest(message="transformer", agent_mode="agent_paper")
        self.assertEqual(resolve_agent_mode(req_mode_alias), "paper")

        # 当未传 agent_mode 但传了 agent_id 时，能正确推导为 paper
        req_id_only = ChatRequest(message="transformer", agent_id="agent_paper")
        self.assertEqual(resolve_agent_mode(req_id_only), "paper")

        # resolve_request_agent_id 解析
        self.assertEqual(resolve_request_agent_id(req_mode, "paper"), "agent_paper")
        self.assertEqual(resolve_thread_id(req_mode, "user123", "paper"), "user123:paper")
        req_task = ChatRequest(message="transformer", agent_mode="paper", conversation_id="task-paper-1")
        self.assertEqual(resolve_thread_id(req_task, "user123", "paper"), "user123:paper:task-paper-1")

    def test_03_runtime_config_and_prompt_injection(self):
        """验证 build_agent_runtime_config 能正确为 agent_paper 注入专属模型与学术提示词"""
        req = ChatRequest(message="查询 Attention is all you need 论文", agent_mode="paper")
        config = build_agent_runtime_config(
            req,
            thread_id="user123:paper",
            agent_mode="paper",
            message=req.message,
        )

        configurable = config["configurable"]
        self.assertEqual(configurable["agent_id"], "agent_paper")
        self.assertEqual(configurable["agent_mode"], "paper")
        self.assertEqual(configurable["agent_model"], "qwen3.7-plus")
        self.assertIn("学术论文检索与文献研读专家", configurable["agent_prompt"])
        self.assertIn("BibTeX", configurable["agent_prompt"])

    def test_04_system_prompt_decoupling(self):
        """验证 agent_paper 不会被 200 字苏格拉底私教铁律污染"""
        # 默认模式下的学术提示词
        sys_msg = agent_workflow.build_system_prompt(agent_id="agent_paper", agent_mode="paper")
        self.assertIn("学术论文检索与文献研读专家", sys_msg.content)
        self.assertIn("BibTeX", sys_msg.content)
        # 严苛教学铁律不得出现在论文专家的提示词中
        self.assertNotIn("控制在 200 字以内", sys_msg.content)
        self.assertNotIn("苏格拉底提问律", sys_msg.content)

        # 自定义 prompt 优先
        custom = "你是一个计算机视觉顶级审稿专家。"
        custom_sys_msg = agent_workflow.build_system_prompt(custom, agent_id="agent_paper", agent_mode="paper")
        self.assertEqual(custom_sys_msg.content, custom)

    def test_05_database_persistence_and_isolation(self):
        """验证 paper 模式的消息持久化、mode 隔离与事务回滚机制"""
        db = self.SessionLocal()
        try:
            # 保存学术研读记录
            msg_user = save_chat_message(
                db,
                user_id="researcher_1",
                agent_mode="paper",
                role="user",
                content="查询 ResNet-50 核心创新与实验表现",
            )
            msg_assistant = save_chat_message(
                db,
                user_id="researcher_1",
                agent_mode="paper",
                role="assistant",
                content="ResNet-50 提出了残差学习框架...",
                sender_id="agent_paper",
            )

            # 同时存一条私教和 RAG 记录
            save_chat_message(db, user_id="researcher_1", agent_mode="tutor", role="user", content="讲解二叉树")
            save_chat_message(db, user_id="researcher_1", agent_mode="rag", role="user", content="检索课件第3章")

            # 验证 paper 模式隔离性
            paper_history = list_chat_history(db, user_id="researcher_1", agent_mode="paper")
            self.assertEqual(len(paper_history), 2)
            self.assertEqual(paper_history[0]["content"], "查询 ResNet-50 核心创新与实验表现")
            self.assertEqual(paper_history[1]["sender_id"], "agent_paper")
            self.assertTrue(all(item["agent_mode"] == "paper" for item in paper_history))

            # 验证删除和清空
            deleted = delete_chat_message(db, user_id="researcher_1", message_id=msg_user.id)
            self.assertTrue(deleted)
            paper_history_after_delete = list_chat_history(db, user_id="researcher_1", agent_mode="paper")
            self.assertEqual(len(paper_history_after_delete), 1)

            cleared_count = clear_chat_history(db, user_id="researcher_1", agent_mode="paper")
            self.assertEqual(cleared_count, 1)
            self.assertEqual(len(list_chat_history(db, user_id="researcher_1", agent_mode="paper")), 0)

            # tutor 模式的历史不受影响
            self.assertEqual(len(list_chat_history(db, user_id="researcher_1", agent_mode="tutor")), 1)
        finally:
            db.close()

    def test_06_database_transaction_rollback(self):
        """验证数据库操作异常时触发事务回滚"""
        db = self.SessionLocal()
        try:
            with patch.object(db, "commit", side_effect=Exception("Database lock failure")):
                with self.assertRaises(Exception):
                    save_chat_message(
                        db,
                        user_id="user_err",
                        agent_mode="paper",
                        role="user",
                        content="test failure",
                    )
            # 回滚后 session 仍健康，可继续执行正常查询
            count = db.query(ChatMessage).filter(ChatMessage.user_id == "user_err").count()
            self.assertEqual(count, 0)
        finally:
            db.close()

    def test_07_agent_workflow_call_model_execution(self):
        """验证 agent_workflow.call_model 在 agent_paper 配置下的真实运行流"""
        calls = []

        def fake_build_chat_model(model_id, temperature=0.1):
            return FakeModel(model_id, calls)

        with patch.object(agent_workflow, "build_chat_model", side_effect=fake_build_chat_model):
            config = {
                "configurable": {
                    "agent_id": "agent_paper",
                    "agent_mode": "paper",
                    "agent_model": "qwen3.7-plus",
                    "agent_prompt": get_default_agent_prompt("agent_paper"),
                }
            }
            state = {"messages": [HumanMessage(content="查询 LoRA 微调论文")]}
            result = agent_workflow.call_model(state, config)

        self.assertIn("PaperBot Review response for qwen3.7-plus", result["messages"][0].content)
        self.assertTrue(any(c[0] == "bind_tools" and c[1] == "qwen3.7-plus" for c in calls))
        # 验证提示词确实为 PaperBot 专属提示词
        self.assertTrue(any(c[0] == "stream" and "学术论文检索与文献研读专家" in c[2] for c in calls))


if __name__ == "__main__":
    unittest.main()
