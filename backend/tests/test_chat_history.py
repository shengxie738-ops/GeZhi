import unittest
import os

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

from app.core.database import Base
from app.models.chat_message import ChatMessage
from app.services.chat_history import (
    build_agent_thread_id,
    list_chat_history,
    normalize_agent_mode,
    save_chat_message,
)


class ChatHistoryTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)

    def test_history_is_isolated_by_agent_mode(self):
        db = self.SessionLocal()
        try:
            save_chat_message(db, user_id="alice", agent_mode="tutor", role="user", content="learn dfs")
            save_chat_message(db, user_id="alice", agent_mode="tutor", role="assistant", content="start with nodes")
            save_chat_message(db, user_id="alice", agent_mode="rag", role="user", content="search bfs")
            save_chat_message(db, user_id="alice", agent_mode="chat", role="user", content="hello ai chat")
            save_chat_message(db, user_id="alice", agent_mode="chat", role="assistant", content="hi there!")
            save_chat_message(db, user_id="alice", agent_mode="paper", role="user", content="query attention is all you need")
            save_chat_message(db, user_id="alice", agent_mode="paper", role="assistant", content="Transformer architecture review...")
            save_chat_message(db, user_id="bob", agent_mode="tutor", role="user", content="other user")

            tutor_history = list_chat_history(db, user_id="alice", agent_mode="tutor")
            rag_history = list_chat_history(db, user_id="alice", agent_mode="rag")
            chat_history = list_chat_history(db, user_id="alice", agent_mode="chat")
            paper_history = list_chat_history(db, user_id="alice", agent_mode="paper")

            self.assertEqual([item["content"] for item in tutor_history], ["learn dfs", "start with nodes"])
            self.assertEqual([item["content"] for item in rag_history], ["search bfs"])
            self.assertEqual([item["content"] for item in chat_history], ["hello ai chat", "hi there!"])
            self.assertEqual([item["content"] for item in paper_history], ["query attention is all you need", "Transformer architecture review..."])
            self.assertTrue(all(item["agent_mode"] == "paper" for item in paper_history))
            self.assertTrue(all(item["created_at"] for item in paper_history))
        finally:
            db.close()

    def test_agent_mode_normalization_and_thread_ids_are_stable(self):
        self.assertEqual(normalize_agent_mode("rag"), "rag")
        self.assertEqual(normalize_agent_mode("chat"), "chat")
        self.assertEqual(normalize_agent_mode("default"), "chat")
        self.assertEqual(normalize_agent_mode("general"), "chat")
        self.assertEqual(normalize_agent_mode("paper"), "paper")
        self.assertEqual(normalize_agent_mode("academic"), "paper")
        self.assertEqual(normalize_agent_mode("anything-else"), "tutor")
        self.assertEqual(build_agent_thread_id("alice", "chat"), "alice:chat")
        self.assertEqual(build_agent_thread_id("alice", "paper"), "alice:paper")
        self.assertEqual(build_agent_thread_id("alice", "paper", "task-paper-1"), "alice:paper:task-paper-1")
        self.assertEqual(build_agent_thread_id("alice", "rag"), "alice:rag")
        self.assertEqual(build_agent_thread_id("", "tutor"), "guest_user:tutor")


    def test_save_chat_history_endpoint_logic(self):
        from app.api.endpoints.chat import (
            create_chat_history_message,
            create_chat_history_batch,
            SaveChatHistoryRequest,
            SaveChatHistoryBatchRequest,
            ChatHistoryItem,
        )
        import asyncio

        db = self.SessionLocal()
        try:
            # 1. 测试单条保存
            req = SaveChatHistoryRequest(
                user_id="alice",
                agent_mode="paper",
                role="user",
                content="检索注意力机制",
            )
            res = asyncio.run(create_chat_history_message(req, db=db))
            self.assertEqual(res["status"], "success")
            self.assertEqual(res["data"]["content"], "检索注意力机制")
            self.assertEqual(res["data"]["agent_mode"], "paper")

            # 2. 测试批量保存
            batch_req = SaveChatHistoryBatchRequest(
                user_id="alice",
                agent_mode="paper",
                messages=[
                    ChatHistoryItem(role="user", content="检索 GNN"),
                    ChatHistoryItem(role="assistant", content="检索到 10 篇 GNN 论文", sender_id="agent_paper"),
                ],
            )
            batch_res = asyncio.run(create_chat_history_batch(batch_req, db=db))
            self.assertEqual(batch_res["status"], "success")
            self.assertEqual(len(batch_res["data"]), 2)

            # 3. 验证数据库查询
            history = list_chat_history(db, user_id="alice", agent_mode="paper")
            self.assertEqual(len(history), 3)
            self.assertEqual(history[0]["content"], "检索注意力机制")
            self.assertEqual(history[1]["content"], "检索 GNN")
            self.assertEqual(history[2]["content"], "检索到 10 篇 GNN 论文")
            self.assertEqual(history[2]["sender_id"], "agent_paper")
        finally:
            db.close()

    def test_messages_persist_explicit_task_and_project_boundaries(self):
        db = self.SessionLocal()
        try:
            save_chat_message(
                db,
                user_id="alice",
                agent_mode="paper",
                role="user",
                content="第一轮",
                conversation_id="task-paper-1",
                project_id="proj-paper",
            )
            save_chat_message(
                db,
                user_id="alice",
                agent_mode="paper",
                role="assistant",
                content="回答一",
                conversation_id="task-paper-1",
                project_id="proj-paper",
            )
            save_chat_message(
                db,
                user_id="alice",
                agent_mode="paper",
                role="user",
                content="另一个任务",
                conversation_id="task-paper-2",
                project_id="proj-paper",
            )

            history = list_chat_history(db, user_id="alice", agent_mode="paper")
            self.assertEqual(
                [item["conversation_id"] for item in history],
                ["task-paper-1", "task-paper-1", "task-paper-2"],
            )
            self.assertTrue(all(item["project_id"] == "proj-paper" for item in history))
        finally:
            db.close()

    def test_legacy_history_gets_stable_task_boundaries_without_merging_questions(self):
        db = self.SessionLocal()
        try:
            first = save_chat_message(db, user_id="legacy", agent_mode="chat", role="user", content="问题一")
            save_chat_message(db, user_id="legacy", agent_mode="chat", role="assistant", content="回答一")
            second = save_chat_message(db, user_id="legacy", agent_mode="chat", role="user", content="问题二")
            save_chat_message(db, user_id="legacy", agent_mode="chat", role="assistant", content="回答二")

            history = list_chat_history(db, user_id="legacy", agent_mode="chat")
            self.assertEqual(history[0]["conversation_id"], f"legacy-chat-{first.id}")
            self.assertEqual(history[1]["conversation_id"], history[0]["conversation_id"])
            self.assertEqual(history[2]["conversation_id"], f"legacy-chat-{second.id}")
            self.assertEqual(history[3]["conversation_id"], history[2]["conversation_id"])
            self.assertNotEqual(history[0]["conversation_id"], history[2]["conversation_id"])
        finally:
            db.close()

    def test_save_chat_messages_batch_atomic_service(self):
        from app.services.chat_history import save_chat_messages_batch
        from pydantic import BaseModel

        class DummyItem(BaseModel):
            role: str = "user"
            content: str
            agent_mode: str = "paper"
            sender_id: str | None = None

        db = self.SessionLocal()
        try:
            items = [
                DummyItem(content="查询图神经网络", role="user"),
                DummyItem(content="整理出5篇顶会论文", role="assistant", sender_id="agent_paper"),
            ]
            saved = save_chat_messages_batch(db, user_id="bob", agent_mode="paper", items=items)
            self.assertEqual(len(saved), 2)
            self.assertTrue(all(r.id is not None for r in saved))

            bob_history = list_chat_history(db, user_id="bob", agent_mode="paper")
            self.assertEqual(len(bob_history), 2)
            self.assertEqual(bob_history[0]["content"], "查询图神经网络")
            self.assertEqual(bob_history[1]["content"], "整理出5篇顶会论文")
        finally:
            db.close()

    def test_pydantic_model_boundaries_and_dos_protection(self):
        from app.api.endpoints.chat import SaveChatHistoryBatchRequest, ChatHistoryItem
        from pydantic import ValidationError

        # 1. 验证空消息列表拦截 (min_length=1)
        with self.assertRaises(ValidationError):
            SaveChatHistoryBatchRequest(
                user_id="alice",
                agent_mode="paper",
                messages=[],
            )

        # 2. 验证防 DoS 超过 50 条拦截 (max_length=50)
        with self.assertRaises(ValidationError):
            SaveChatHistoryBatchRequest(
                user_id="alice",
                agent_mode="paper",
                messages=[ChatHistoryItem(role="user", content=f"q{i}") for i in range(51)],
            )

        # 3. 验证非法 role 拦截
        with self.assertRaises(ValidationError):
            ChatHistoryItem(role="hacker_role", content="normal content")

        # 4. 验证空 content 拦截 (min_length=1)
        with self.assertRaises(ValidationError):
            ChatHistoryItem(role="user", content="")


if __name__ == "__main__":
    unittest.main()
