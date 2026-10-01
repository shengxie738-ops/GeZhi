import unittest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.main import app
from app.models.user_custom_ai_model import UserCustomAIModel


class UserModelApiTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

        self.token_user_a = create_access_token("student_alice", "student")
        self.headers_user_a = {"Authorization": f"Bearer {self.token_user_a}"}

        self.token_user_b = create_access_token("student_bob", "student")
        self.headers_user_b = {"Authorization": f"Bearer {self.token_user_b}"}

    def tearDown(self):
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=self.engine)

    def test_unauthenticated_access_rejected(self):
        res = self.client.get("/api/user/models")
        self.assertEqual(res.status_code, 401)

    def test_crud_lifecycle_and_masking(self):
        # 1. 创建模型配置
        create_payload = {
            "provider": "OpenAI Compatible",
            "api_type": "Chat Completions API",
            "base_url": "https://api.openai-proxy.com/v1",
            "api_key": "sk-my-super-secret-key-123456",
            "model_ids": ["gpt-4o", "gpt-4o-mini"],
            "is_active": True,
        }
        create_res = self.client.post("/api/user/models", json=create_payload, headers=self.headers_user_a)
        self.assertEqual(create_res.status_code, 201)
        created_data = create_res.json()["data"]
        config_id = created_data["id"]
        self.assertIn("****", created_data["api_key"])
        self.assertNotIn("123456", created_data["api_key"])

        # 2. 查询列表
        list_res = self.client.get("/api/user/models", headers=self.headers_user_a)
        self.assertEqual(list_res.status_code, 200)
        items = list_res.json()["data"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], config_id)
        self.assertEqual(items[0]["model_ids"], ["gpt-4o", "gpt-4o-mini"])
        self.assertTrue("****" in items[0]["api_key"])

        # 3. 隔离性测试：用户 B 查询应为空
        bob_list_res = self.client.get("/api/user/models", headers=self.headers_user_b)
        self.assertEqual(bob_list_res.status_code, 200)
        self.assertEqual(len(bob_list_res.json()["data"]), 0)

        # 4. 越权拦截：用户 B 试图修改用户 A 的模型
        bob_update_res = self.client.put(
            f"/api/user/models/{config_id}",
            json={"model_ids": ["hacked-model"]},
            headers=self.headers_user_b,
        )
        self.assertEqual(bob_update_res.status_code, 404)

        # 5. 用户 A 正常更新，并保留脱敏 Key
        update_res = self.client.put(
            f"/api/user/models/{config_id}",
            json={
                "model_ids": ["gpt-4o", "deepseek-v3"],
                "api_key": items[0]["api_key"],  # 传脱敏值，不应覆盖破坏底层密钥
            },
            headers=self.headers_user_a,
        )
        self.assertEqual(update_res.status_code, 200)
        updated_data = update_res.json()["data"]
        self.assertEqual(updated_data["model_ids"], ["gpt-4o", "deepseek-v3"])

        # 校验底层数据库依然能够解密出初始的秘钥
        db = self.Session()
        db_record = db.query(UserCustomAIModel).filter_by(id=config_id).first()
        self.assertEqual(db_record.get_decrypted_api_key(), "sk-my-super-secret-key-123456")
        db.close()

        # 6. 用户 A 删除模型
        del_res = self.client.delete(f"/api/user/models/{config_id}", headers=self.headers_user_a)
        self.assertEqual(del_res.status_code, 200)

        # 验证删除后列表为空
        list_after_del = self.client.get("/api/user/models", headers=self.headers_user_a)
        self.assertEqual(len(list_after_del.json()["data"]), 0)

    @patch("httpx.AsyncClient.post")
    def test_connection_endpoint(self, mock_post):
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        res = self.client.post(
            "/api/user/models/test",
            json={
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-mock-key-123456",
                "model_id": "gpt-4o",
            },
            headers=self.headers_user_a,
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "success")


if __name__ == "__main__":
    unittest.main()
