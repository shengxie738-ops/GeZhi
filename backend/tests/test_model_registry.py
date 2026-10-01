import os
import unittest

os.environ.setdefault("RAGFLOW_API_KEY", "test")
os.environ.setdefault("RAGFLOW_BASE_URL", "http://localhost")
os.environ.setdefault("RAGFLOW_AGENT_ID", "test")
os.environ.setdefault("RAGFLOW_CHAT_ID", "test")
os.environ.setdefault("RAGFLOW_DATASET_ID", "test")
os.environ.setdefault("RAGFLOW_PUBLIC_DATASET_IDS", "")
os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("OPENAI_API_BASE", "http://localhost")

from app.services.model_registry import build_chat_model, get_model_config, list_public_models


class FakeChatModel:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class ModelRegistryTest(unittest.TestCase):
    def test_resolves_text_model_from_backend_registry(self):
        config = get_model_config("qwen3.8-max", category="text")

        self.assertEqual(config.model_id, "qwen3.8-max")
        self.assertEqual(config.category, "text")
        self.assertIn("/compatible-mode/v1", config.base_url)
        self.assertTrue(config.api_key)

    def test_spark_models_registered(self):
        spark_ultra = get_model_config("spark Ultra-32K", category="text")
        self.assertEqual(spark_ultra.provider, "讯飞星火")
        self.assertEqual(spark_ultra.api_model, "4.0Ultra")
        self.assertIn("spark-api-open.xf-yun.com", spark_ultra.base_url)

        spark_lite = get_model_config("spark Lite", category="text")
        self.assertEqual(spark_lite.provider, "讯飞星火")
        self.assertEqual(spark_lite.api_model, "lite")

        spark_x = get_model_config("spark-x", category="text")
        self.assertEqual(spark_x.provider, "讯飞星火")
        self.assertEqual(spark_x.api_model, "generalv3.5")

        with self.assertRaises(ValueError):
            get_model_config("mimo-v2.5", category="text")

    def test_disabled_and_unsupported_models_rejected(self):
        # 欠费模型直接删除，不使用任何替代
        for disabled_id in (
            "qwen3.7-plus",
            "qwen3.7-max",
            "qwen3.6-plus",
            "qwen3.6-max-preview",
            "qwen3.5-plus",
            "deepseek-v4-pro",
            "deepseek-v4-flash",
            "mimo-v2.5",
            "qwen-image-2.0",
            "qwen-image-2.0-pro",
            "qwen3.5-omni-flash",
            "qwen3.5-omni-plus",
            "qwen-omni-turbo",
            "qwen3-omni-flash-2025-12-01",
        ):
            with self.subTest(disabled_id=disabled_id):
                with self.assertRaises(ValueError):
                    get_model_config(disabled_id, category="text")
                with self.assertRaises(ValueError):
                    get_model_config(disabled_id, category="omni")

        # 原生直接可用的保留模型
        config_deepseek = get_model_config("deepseek-v4-pro-0813", category="text")
        self.assertEqual(config_deepseek.model_id, "deepseek-v4-pro-0813")

    def test_rejects_unknown_or_wrong_category_model(self):
        for model_id in ("not-a-real-model", "unknown-model-xyz", "glm-4.7"):
            with self.subTest(model_id=model_id):
                with self.assertRaises(ValueError):
                    get_model_config(model_id, category="text")

    def test_public_model_list_does_not_expose_api_keys(self):
        public_models = list_public_models()

        self.assertIn("text", public_models)
        self.assertIn("image", public_models)
        self.assertIn("omni", public_models)
        self.assertTrue(any(model["id"] == "spark Ultra-32K" for model in public_models["text"]))
        self.assertFalse(any(model["id"] == "mimo-v2.5" for model in public_models["text"]))
        self.assertFalse(any(model["id"] == "qwen3.7-plus" for model in public_models["text"]))
        self.assertTrue(any(model["id"] == "qwen3.8-max" for model in public_models["text"]))
        self.assertEqual(public_models["image"], [])
        self.assertEqual(len(public_models["omni"]), 5)
        for expected_id in ("qwen-audio-3.0-asr-flash", "paraformer-v2", "paraformer-v1", "paraformer-mtl-v1", "paraformer-8k-v2"):
            self.assertTrue(any(model["id"] == expected_id for model in public_models["omni"]), f"Missing omni model: {expected_id}")
            cfg = get_model_config(expected_id, category="omni")
            self.assertEqual(cfg.category, "omni")
        # 兼容映射测试
        compat_cfg = get_model_config("paraformer-v", category="omni")
        self.assertEqual(compat_cfg.model_id, "paraformer-v1")
        self.assertFalse(any("api_key" in model for models in public_models.values() for model in models))

    def test_build_chat_model_uses_selected_model_credentials(self):
        client = build_chat_model("qwen3.8-max", temperature=0.25, client_factory=FakeChatModel)

        self.assertEqual(client.kwargs["model"], "qwen3.8-max")
        self.assertEqual(client.kwargs["temperature"], 0.25)
        self.assertEqual(client.kwargs["base_url"], "https://ws-ormgvfkztc6f2p76.cn-beijing.maas.aliyuncs.com/compatible-mode/v1")
        self.assertTrue(client.kwargs["openai_api_key"])

    def test_zhipu_glm_models_use_bigmodel_chat_endpoint(self):
        for model_id in ("glm-4.5-air", "glm-4.6v", "glm-4-flash"):
            with self.subTest(model_id=model_id):
                config = get_model_config(model_id, category="text")
                client = build_chat_model(model_id, client_factory=FakeChatModel)

                self.assertEqual(config.provider, "智谱 AI")
                self.assertEqual(config.base_url, "https://open.bigmodel.cn/api/paas/v4")
                self.assertEqual(client.kwargs["base_url"], "https://open.bigmodel.cn/api/paas/v4")
                self.assertTrue(client.kwargs["openai_api_key"])

    def test_thinking_models_enable_reasoning_via_extra_body(self):
        for model_id in ("qwen3.8-max", "qwen3.7-flash"):
            with self.subTest(model_id=model_id):
                config = get_model_config(model_id, category="text")
                client = build_chat_model(model_id, client_factory=FakeChatModel)

                self.assertEqual(config.provider, "阿里云百炼")
                self.assertIn("/compatible-mode/v1", config.base_url)
                self.assertTrue(config.enable_thinking)
                self.assertEqual(client.kwargs["model"], model_id)
                self.assertEqual(client.kwargs["extra_body"], {"enable_thinking": True})

        non_thinking_client = build_chat_model("kimi-k2.7-code", client_factory=FakeChatModel)
        self.assertNotIn("extra_body", non_thinking_client.kwargs)

        public_models_map = {
            model["id"]: model for model in list_public_models()["text"]
        }
        self.assertEqual(public_models_map["qwen3.8-max"]["enable_thinking"], True)
        self.assertNotIn("enable_thinking", public_models_map["kimi-k2.7-code"])

    def test_kimi_k3_omits_temperature(self):
        client = build_chat_model("kimi-k3", temperature=0.7, client_factory=FakeChatModel)
        self.assertEqual(client.kwargs["model"], "kimi-k3")
        self.assertNotIn("temperature", client.kwargs)


if __name__ == "__main__":
    unittest.main()
