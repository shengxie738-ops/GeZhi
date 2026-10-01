import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.crypto import decrypt_secret, encrypt_secret, mask_api_key
from app.core.database import Base
from app.models.user_custom_ai_model import UserCustomAIModel


class CryptoAndModelTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)

    def test_crypto_roundtrip(self):
        raw_key = "sk-proj-1234567890abcdefABCDEF!@#"
        cipher = encrypt_secret(raw_key)
        self.assertNotEqual(raw_key, cipher)
        self.assertTrue(len(cipher) > 20)

        decrypted = decrypt_secret(cipher)
        self.assertEqual(decrypted, raw_key)

    def test_crypto_empty_and_corrupt(self):
        self.assertEqual(encrypt_secret(""), "")
        self.assertEqual(decrypt_secret(""), "")
        self.assertEqual(decrypt_secret("invalid-corrupted-cipher"), "")

    def test_mask_api_key(self):
        self.assertEqual(mask_api_key("sk-1234567890abcdef"), "sk-****cdef")
        self.assertEqual(mask_api_key("1234"), "****")
        self.assertEqual(mask_api_key("short"), "****")
        self.assertEqual(mask_api_key("12345678"), "12****78")
        self.assertEqual(mask_api_key(""), "")

    def test_user_custom_ai_model_orm(self):
        raw_key = "sk-custom-secret-key-999"
        encrypted = encrypt_secret(raw_key)

        model_record = UserCustomAIModel(
            user_id="test_student_01",
            provider="OpenAI Compatible",
            api_type="Chat Completions API",
            base_url="https://api.my-custom-llm.com/v1",
            encrypted_api_key=encrypted,
            model_ids=["qwen3.8-max", "deepseek-v3"],
            is_active=True,
        )
        self.db.add(model_record)
        self.db.commit()
        self.db.refresh(model_record)

        # 验证数据库读取与解密
        fetched = self.db.query(UserCustomAIModel).filter_by(id=model_record.id).first()
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.user_id, "test_student_01")
        self.assertEqual(fetched.get_decrypted_api_key(), raw_key)
        self.assertEqual(fetched.model_ids, ["qwen3.8-max", "deepseek-v3"])

        # 验证 to_dict 脱敏输出
        data_dict = fetched.to_dict(mask_key=True)
        self.assertEqual(data_dict["api_key"], "sk-****-999")
        self.assertEqual(data_dict["base_url"], "https://api.my-custom-llm.com/v1")
        self.assertEqual(data_dict["provider"], "OpenAI Compatible")


if __name__ == "__main__":
    unittest.main()
