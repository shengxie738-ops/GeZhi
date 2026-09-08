import unittest
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.endpoints.chat import (
    build_agent_runtime_config,
    find_user_custom_model_credentials,
    get_request_chat_model,
    is_configured_model_unavailable,
)
from app.core.crypto import encrypt_secret
from app.core.database import Base
from app.models.user_custom_ai_model import UserCustomAIModel
from app.schemas.chat import ChatRequest
from app.services.agent_workflow import call_model, resolve_runtime_model_id
from langchain_core.messages import AIMessage, HumanMessage


class CustomModelChatRuntimeTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

        # 预设一条自定义模型数据
        self.raw_key = "sk-custom-secret-key-abcdef"
        self.custom_record = UserCustomAIModel(
            user_id="student_alice",
            provider="OpenAI Compatible",
            api_type="Chat Completions API",
            base_url="https://api.third-party-llm.com/v1",
            encrypted_api_key=encrypt_secret(self.raw_key),
            model_ids=["my-gpt-5-custom", "qwen3.8-custom"],
            is_active=True,
        )
        self.db.add(self.custom_record)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)

    def test_find_user_custom_model_credentials(self):
        # 能够正确命中
        creds = find_user_custom_model_credentials(self.db, "student_alice", "my-gpt-5-custom")
        self.assertIsNotNone(creds)
        base_url, api_key = creds
        self.assertEqual(base_url, "https://api.third-party-llm.com/v1")
        self.assertEqual(api_key, self.raw_key)

        # 另一个不存在的模型
        self.assertIsNone(find_user_custom_model_credentials(self.db, "student_alice", "non-existent-model"))
        # 另一个用户查不到
        self.assertIsNone(find_user_custom_model_credentials(self.db, "student_bob", "my-gpt-5-custom"))

    def test_build_agent_runtime_config_with_custom_model(self):
        req = ChatRequest(
            message="你好",
            agent_model="my-gpt-5-custom",
            agent_mode="chat",
            sessionId="student_alice",
        )
        config = build_agent_runtime_config(
            req,
            thread_id="thread_test_01",
            agent_mode="chat",
            message="你好",
            user_id="student_alice",
            db=self.db,
        )
        conf = config.get("configurable", {})
        self.assertEqual(conf.get("agent_model"), "my-gpt-5-custom")
        self.assertEqual(conf.get("custom_model_base_url"), "https://api.third-party-llm.com/v1")
        self.assertEqual(conf.get("custom_model_api_key"), self.raw_key)

        # 检查是否会被误判为不可用
        unavailable = is_configured_model_unavailable(req, config=config)
        self.assertFalse(unavailable)

    def test_get_request_chat_model_instantiates_chatopenai(self):
        config = {
            "configurable": {
                "agent_model": "my-gpt-5-custom",
                "custom_model_base_url": "https://api.third-party-llm.com/v1",
                "custom_model_api_key": self.raw_key,
            }
        }
        client = get_request_chat_model(config, temperature=0.2)
        self.assertEqual(client.model_name, "my-gpt-5-custom")
        self.assertEqual(str(client.openai_api_base), "https://api.third-party-llm.com/v1")
        self.assertEqual(client.openai_api_key.get_secret_value(), self.raw_key)

    @patch("app.services.agent_workflow.ChatOpenAI")
    def test_call_model_uses_custom_chat_openai(self, mock_chat_openai):
        fake_client = MagicMock()
        fake_bound = MagicMock()
        fake_bound.stream.return_value = [AIMessage(content="自定义模型回复内容")]
        fake_client.bind_tools.return_value = fake_bound
        mock_chat_openai.return_value = fake_client

        state = {"messages": [HumanMessage(content="测试自定义模型提问")]}
        config = {
            "configurable": {
                "agent_id": "agent_tutor",
                "agent_mode": "chat",
                "agent_model": "my-gpt-5-custom",
                "custom_model_base_url": "https://api.third-party-llm.com/v1",
                "custom_model_api_key": self.raw_key,
            }
        }
        result = call_model(state, config=config)
        self.assertIn("messages", result)
        self.assertEqual(result["messages"][0].content, "自定义模型回复内容")
        mock_chat_openai.assert_called_once_with(
            model="my-gpt-5-custom",
            openai_api_key=self.raw_key,
            openai_api_base="https://api.third-party-llm.com/v1",
            base_url="https://api.third-party-llm.com/v1",
            temperature=0.1,
            request_timeout=30.0,
            max_retries=1,
        )


if __name__ == "__main__":
    unittest.main()
