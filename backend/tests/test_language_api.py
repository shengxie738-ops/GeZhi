import asyncio
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

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.endpoints.language import (
    ProgressRequest,
    ReadingAnalyzeRequest,
    ReadingMarkRequest,
    SpeakingAnalyzeRequest,
    UserArticleRenameRequest,
    VocabularyExplainRequest,
    WordbookAddRequest,
    WordbookPatchRequest,
    WritingAnalyzeRequest,
    add_word,
    delete_user_article,
    delete_word,
    import_user_article,
    language_insights,
    language_insights_advice,
    language_overview,
    list_user_articles,
    list_wordbook,
    mark_article_read,
    reading_analyze,
    reading_progress,
    record_progress,
    rename_user_article,
    resolve_language_model,
    speaking_analyze,
    unmark_article_read,
    update_word,
    vocabulary_explain,
    writing_analyze,
    writing_optimize,
    WritingOptimizeRequest,
    writing_history_delete,
    writing_history_detail,
    writing_history_list,
)
from app.core.security import create_access_token
from app.models.domain_record import DomainRecord
from app.repositories.json_store import JsonStore
from app.services.default_agents import get_default_agents
from app.services.language_service import extract_json
from app.services.model_registry import build_chat_model, get_model_config, list_public_models


AUTH = f"Bearer {create_access_token('student_lang_test', 'student')}"


class LanguageApiTestBase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        DomainRecord.__table__.create(bind=self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.db = self.SessionLocal()

    def tearDown(self):
        self.db.close()


class ModelRegistryOmniTest(unittest.TestCase):
    def test_expired_omni_models_removed_from_registry(self):
        for model_id in ("qwen3.5-omni-flash", "qwen3.5-omni-plus", "qwen-omni-turbo", "qwen3-omni-flash-2025-12-01"):
            with self.assertRaises(ValueError):
                get_model_config(model_id, category="omni")

    def test_new_omni_models_registered_and_listed_publicly(self):
        models = list_public_models()
        self.assertIn("omni", models)
        self.assertEqual(len(models["omni"]), 5)
        for expected_id in ("qwen-audio-3.0-asr-flash", "paraformer-v2", "paraformer-v1", "paraformer-mtl-v1", "paraformer-8k-v2"):
            self.assertTrue(any(m["id"] == expected_id for m in models["omni"]), f"Missing omni model: {expected_id}")

    def test_omni_model_rejected_for_text_chat(self):
        with self.assertRaises(ValueError):
            build_chat_model("qwen-audio-3.0-asr-flash")

    def test_text_model_rejected_for_omni_category(self):
        with self.assertRaises(ValueError):
            get_model_config("qwen3.7-plus", category="omni")


class LanguageAgentsTest(unittest.TestCase):
    def test_default_agents_include_language_and_speaking(self):
        agents = {agent["id"]: agent for agent in get_default_agents()}
        foreign = agents["agent_foreign_language"]
        self.assertEqual(foreign["modelCategory"], "text")
        self.assertTrue(foreign["model"])
        speaking = agents["agent_speaking"]
        self.assertEqual(speaking["modelCategory"], "omni")
        self.assertEqual(speaking["model"], "qwen-audio-3.0-asr-flash")


class ExtractJsonTest(unittest.TestCase):
    def test_plain_json(self):
        self.assertEqual(extract_json('{"a": 1}'), {"a": 1})

    def test_fenced_json(self):
        self.assertEqual(extract_json('```json\n{"a": {"b": 2}}\n```'), {"a": {"b": 2}})

    def test_json_with_braces_inside_strings(self):
        self.assertEqual(extract_json('说明 {"text": "包含 } 花括号", "n": 3} 结束'), {"text": "包含 } 花括号", "n": 3})

    def test_invalid_raises(self):
        with self.assertRaises(ValueError):
            extract_json("no json here")


class ModelCategoryGuardTest(LanguageApiTestBase):
    def test_text_endpoint_rejects_omni_model(self):
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(vocabulary_explain(VocabularyExplainRequest(word="go", model="qwen3.5-omni-flash"), AUTH, self.db))
        self.assertEqual(ctx.exception.status_code, 400)

    def test_speaking_endpoint_rejects_text_model(self):
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(speaking_analyze(SpeakingAnalyzeRequest(audioBase64="x" * 200, model="qwen3.7-plus"), AUTH, self.db))
        self.assertEqual(ctx.exception.status_code, 400)

    def test_resolution_follows_user_agent_config(self):
        from app.api.endpoints.agents import AgentConfigPayload, save_agent_config

        asyncio.run(save_agent_config("agent_foreign_language", AgentConfigPayload(model="glm-5.2"), self.db))
        resolved = resolve_language_model(self.db, "agent_foreign_language", None, category="text")
        self.assertEqual(resolved, "glm-5.2")

    def test_resolution_rejects_wrong_category_from_saved_config(self):
        store = JsonStore(self.db)
        store.upsert("agents", "config", "agent_foreign_language", {"id": "agent_foreign_language", "model": "qwen3.5-omni-flash"}, owner_id="system")
        resolved = resolve_language_model(self.db, "agent_foreign_language", None, category="text")
        self.assertEqual(resolved, "qwen3.7-flash")  # 回落默认文本模型


class WordbookApiTest(LanguageApiTestBase):
    def test_wordbook_crud_flow(self):
        added = asyncio.run(
            add_word(
                WordbookAddRequest(word="Significantly", meaningZh="显著地", cefr="B2", examples=["It helps."]),
                AUTH,
                self.db,
            )
        )
        self.assertEqual(added["data"]["id"], "significantly")
        self.assertEqual(added["data"]["proficiency"], 0)

        words = asyncio.run(list_wordbook(AUTH, self.db))
        self.assertEqual(len(words["data"]), 1)

        updated = asyncio.run(update_word("significantly", WordbookPatchRequest(proficiency=3), AUTH, self.db))
        self.assertEqual(updated["data"]["proficiency"], 3)

        deleted = asyncio.run(delete_word("significantly", AUTH, self.db))
        self.assertTrue(deleted["data"]["deleted"])
        words = asyncio.run(list_wordbook(AUTH, self.db))
        self.assertEqual(len(words["data"]), 0)

    def test_wordbook_requires_auth(self):
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(list_wordbook(None, self.db))
        self.assertEqual(ctx.exception.status_code, 401)


class AnalyzeEndpointsTest(LanguageApiTestBase):
    def test_reading_analyze_returns_structured_data(self):
        fake = {
            "level": "B2",
            "estimatedReadingMinutes": 4,
            "wordCount": 637,
            "keyVocabulary": [{"word": "transform", "meaningZh": "转变", "cefr": "B2"}],
            "complexSentences": [],
            "summaryZh": "AI 改变生活",
            "questions": [{"question": "Main idea?", "options": ["A", "B", "C", "D"], "answerIndex": 0, "explanationZh": ""}],
        }
        with patch("app.api.endpoints.language.analyze_reading", return_value=fake):
            result = asyncio.run(
                reading_analyze(ReadingAnalyzeRequest(text="Artificial intelligence has transformed education." * 2), AUTH, self.db)
            )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"]["level"], "B2")
        self.assertEqual(result["data"]["model"], "qwen3.7-flash")
        self.assertGreater(result["data"]["wordCount"], 5)

    def test_writing_analyze_saves_session(self):
        fake = {
            "score": {"overall": 82, "grammar": 91, "vocabulary": 76, "coherence": 81, "expression": 79},
            "issues": [
                {
                    "type": "grammar",
                    "original": "He go",
                    "suggestion": "He went",
                    "reasonZh": "过去式",
                    "grammarPoint": "Simple Past Tense",
                    "start": 0,
                    "end": 5,
                }
            ],
            "improvedText": "He went to school yesterday.",
            "mode": "standard",
        }
        with patch("app.api.endpoints.language.analyze_writing", return_value=fake):
            result = asyncio.run(
                writing_analyze(WritingAnalyzeRequest(text="He go to school yesterday."), AUTH, self.db)
            )
        self.assertEqual(result["data"]["issues"][0]["end"], 5)
        overview = asyncio.run(language_overview(AUTH, self.db))
        self.assertEqual(overview["data"]["today"]["exercises"], 1)

    def test_speaking_analyze_rejects_when_omni_model_unavailable(self):
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(
                speaking_analyze(
                    SpeakingAnalyzeRequest(audioBase64="x" * 200, mode="read_aloud", referenceText="He went to school yesterday.", model="qwen3.5-omni-flash"),
                    AUTH,
                    self.db,
                )
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("不是全模态模型", ctx.exception.detail)

    def test_speaking_analyze_saves_session(self):
        fake = {
            "transcript": "He went to school yesterday.",
            "scores": {"overall": 82, "pronunciation": 86, "fluency": 74, "accuracy": 91, "intonation": 77},
            "words": [{"word": "school", "status": "minor", "problemsZh": ["/k/ 不清晰"]}],
            "feedbackZh": "整体流利",
            "suggestionsZh": ["练习短元音"],
            "mode": "read_aloud",
        }
        with patch("app.api.endpoints.language.resolve_language_model", return_value="mock-omni-model"), \
             patch("app.api.endpoints.language.analyze_speaking", return_value=fake) as mock_call:
            res = asyncio.run(
                speaking_analyze(
                    SpeakingAnalyzeRequest(audioBase64="x" * 200, mode="read_aloud", referenceText="He went to school yesterday."),
                    AUTH,
                    self.db,
                )
            )
            self.assertEqual(mock_call.call_args.args[0], "mock-omni-model")
            self.assertEqual(res["data"]["scores"]["overall"], 82)


class WritingHistoryApiTest(LanguageApiTestBase):
    def _analyze(self, text="He go to school yesterday."):
        fake = {
            "score": {"overall": 82, "grammar": 91, "vocabulary": 76, "coherence": 81, "expression": 79},
            "issues": [
                {
                    "type": "grammar",
                    "original": "He go",
                    "suggestion": "He went",
                    "reasonZh": "过去式",
                    "grammarPoint": "Simple Past Tense",
                    "start": 0,
                    "end": 5,
                }
            ],
            "improvedText": "",
            "mode": "standard",
        }
        with patch("app.api.endpoints.language.analyze_writing", return_value=fake):
            return asyncio.run(writing_analyze(WritingAnalyzeRequest(text=text), AUTH, self.db))

    def test_writing_analyze_saves_full_history(self):
        analyze_res = self._analyze("He go to school yesterday.")
        self.assertIn("historyId", analyze_res["data"])
        entries = asyncio.run(writing_history_list(AUTH, self.db))["data"]["entries"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["mode"], "standard")
        self.assertEqual(entries[0]["score"]["overall"], 82)
        self.assertEqual(entries[0]["issueCount"], 1)
        self.assertEqual(entries[0]["preview"], "He go to school yesterday.")
        detail = asyncio.run(writing_history_detail(entries[0]["id"], AUTH, self.db))["data"]
        self.assertEqual(detail["text"], "He go to school yesterday.")
        self.assertEqual(detail["wordCount"], 5)

    def test_writing_optimize_updates_database(self):
        analyze_res = self._analyze("He go to school yesterday.")
        history_id = analyze_res["data"]["historyId"]
        
        # 初始状态未优化，improvedText 为 ""
        detail_before = asyncio.run(writing_history_detail(history_id, AUTH, self.db))["data"]
        self.assertEqual(detail_before.get("improvedText", ""), "")

        # 调用优化接口
        fake_opt = {"improvedText": "He went to school yesterday and enjoyed his classes.", "mode": "standard"}
        with patch("app.api.endpoints.language.optimize_writing", return_value=fake_opt):
            opt_res = asyncio.run(
                writing_optimize(
                    WritingOptimizeRequest(
                        text="He go to school yesterday.",
                        mode="standard",
                        issues=[{"original": "He go", "suggestion": "He went", "reasonZh": "过去式"}],
                        historyId=history_id,
                    ),
                    AUTH,
                    self.db,
                )
            )
        self.assertEqual(opt_res["data"]["improvedText"], "He went to school yesterday and enjoyed his classes.")
        
        # 验证数据库中真实 patch 更新成功
        detail_after = asyncio.run(writing_history_detail(history_id, AUTH, self.db))["data"]
        self.assertEqual(detail_after.get("improvedText"), "He went to school yesterday and enjoyed his classes.")

    def test_writing_history_newest_first(self):
        self._analyze("First draft.")
        self._analyze("Second draft.")
        entries = asyncio.run(writing_history_list(AUTH, self.db))["data"]["entries"]
        self.assertEqual(len(entries), 2)
        self.assertIn("Second", entries[0]["preview"])
        self.assertIn("First", entries[1]["preview"])

    def test_writing_history_delete_and_404(self):
        self._analyze()
        entry_id = asyncio.run(writing_history_list(AUTH, self.db))["data"]["entries"][0]["id"]
        deleted = asyncio.run(writing_history_delete(entry_id, AUTH, self.db))
        self.assertTrue(deleted["data"]["deleted"])
        self.assertEqual(asyncio.run(writing_history_list(AUTH, self.db))["data"]["entries"], [])
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(writing_history_delete(entry_id, AUTH, self.db))
        self.assertEqual(ctx.exception.status_code, 404)
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(writing_history_detail(entry_id, AUTH, self.db))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_writing_history_owner_isolated(self):
        self._analyze()
        other = "Bearer " + create_access_token("other_student", "student")
        self.assertEqual(asyncio.run(writing_history_list(other, self.db))["data"]["entries"], [])
        own_id = asyncio.run(writing_history_list(AUTH, self.db))["data"]["entries"][0]["id"]
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(writing_history_detail(own_id, other, self.db))
        self.assertEqual(ctx.exception.status_code, 404)
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(writing_history_delete(own_id, other, self.db))
        self.assertEqual(ctx.exception.status_code, 404)


class ReadingProgressApiTest(LanguageApiTestBase):
    def test_mark_list_unmark_flow(self):
        marked = asyncio.run(mark_article_read(ReadingMarkRequest(articleId="sample-ocean"), AUTH, self.db))
        self.assertEqual(marked["data"]["articleId"], "sample-ocean")
        # 幂等：重复标记返回已有记录
        again = asyncio.run(mark_article_read(ReadingMarkRequest(articleId="sample-ocean"), AUTH, self.db))
        self.assertEqual(again["data"]["id"], marked["data"]["id"])
        progress = asyncio.run(reading_progress(AUTH, self.db))["data"]["readArticleIds"]
        self.assertEqual(progress, ["sample-ocean"])
        deleted = asyncio.run(unmark_article_read("sample-ocean", AUTH, self.db))
        self.assertTrue(deleted["data"]["deleted"])
        self.assertEqual(asyncio.run(reading_progress(AUTH, self.db))["data"]["readArticleIds"], [])

    def test_unmark_missing_returns_404(self):
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(unmark_article_read("sample-sleep", AUTH, self.db))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_reading_progress_requires_auth(self):
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(reading_progress(None, self.db))
        self.assertEqual(ctx.exception.status_code, 401)

    def test_reading_progress_owner_isolated(self):
        asyncio.run(mark_article_read(ReadingMarkRequest(articleId="sample-ocean"), AUTH, self.db))
        other = "Bearer " + create_access_token("other_student", "student")
        self.assertEqual(asyncio.run(reading_progress(other, self.db))["data"]["readArticleIds"], [])


class UserArticleApiTest(LanguageApiTestBase):
    LONG_TEXT = (
        "Artificial intelligence is transforming the way students learn languages. "
        "Modern tools can analyze pronunciation in real time and offer instant feedback, "
        "which makes practice more efficient than ever before. Teachers report that learners "
        "who use such tools speak more confidently and make fewer repeated mistakes. "
        "However, technology works best when combined with human guidance and daily practice."
    )

    def _make_docx(self, text):
        from docx import Document
        from io import BytesIO

        buffer = BytesIO()
        doc = Document()
        for line in text.split("\n"):
            doc.add_paragraph(line)
        doc.save(buffer)
        return buffer.getvalue()

    class FakeUploadFile:
        def __init__(self, filename, content):
            self.filename = filename
            self._content = content

        async def read(self):
            return self._content

    def test_import_and_list(self):
        result = asyncio.run(
            import_user_article(self.FakeUploadFile("my_essay.docx", self._make_docx(self.LONG_TEXT)), AUTH, self.db)
        )
        self.assertEqual(result["data"]["title"], "my_essay")
        self.assertGreater(result["data"]["wordCount"], 10)
        self.assertIn("Artificial intelligence", result["data"]["text"])

        records = asyncio.run(list_user_articles(AUTH, self.db))["data"]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["title"], "my_essay")

    def test_rename(self):
        saved = asyncio.run(
            import_user_article(self.FakeUploadFile("a.docx", self._make_docx(self.LONG_TEXT)), AUTH, self.db)
        )["data"]
        renamed = asyncio.run(
            rename_user_article(saved["id"], UserArticleRenameRequest(title="我的第一篇作文"), AUTH, self.db)
        )["data"]
        self.assertEqual(renamed["title"], "我的第一篇作文")

    def test_delete_and_404(self):
        saved = asyncio.run(
            import_user_article(self.FakeUploadFile("a.docx", self._make_docx(self.LONG_TEXT)), AUTH, self.db)
        )["data"]
        deleted = asyncio.run(delete_user_article(saved["id"], AUTH, self.db))
        self.assertTrue(deleted["data"]["deleted"])
        self.assertEqual(asyncio.run(list_user_articles(AUTH, self.db))["data"], [])
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(delete_user_article(saved["id"], AUTH, self.db))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_rejects_wrong_extension(self):
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(import_user_article(self.FakeUploadFile("notes.txt", b"hello"), AUTH, self.db))
        self.assertEqual(ctx.exception.status_code, 400)

    def test_rejects_short_text(self):
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(import_user_article(self.FakeUploadFile("short.docx", self._make_docx("Too short.")), AUTH, self.db))
        self.assertEqual(ctx.exception.status_code, 400)

    def test_owner_isolated(self):
        saved = asyncio.run(
            import_user_article(self.FakeUploadFile("a.docx", self._make_docx(self.LONG_TEXT)), AUTH, self.db)
        )["data"]
        other = "Bearer " + create_access_token("other_student", "student")
        self.assertEqual(asyncio.run(list_user_articles(other, self.db))["data"], [])
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(rename_user_article(saved["id"], UserArticleRenameRequest(title="x"), other, self.db))
        self.assertEqual(ctx.exception.status_code, 404)
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(delete_user_article(saved["id"], other, self.db))
        self.assertEqual(ctx.exception.status_code, 404)


class InsightsApiTest(LanguageApiTestBase):
    def test_progress_and_insights_aggregation(self):
        asyncio.run(record_progress(ProgressRequest(type="reading", durationSec=300, correct=4, total=5, wordCount=637, level="B2"), AUTH, self.db))
        asyncio.run(record_progress(ProgressRequest(type="vocab", durationSec=60, reviewed=8), AUTH, self.db))
        asyncio.run(
            add_word(WordbookAddRequest(word="transform", cefr="B2"), AUTH, self.db)
        )

        overview = asyncio.run(language_overview(AUTH, self.db))
        self.assertEqual(overview["data"]["streak"], 1)
        self.assertEqual(overview["data"]["today"]["learningMinutes"], 6)
        self.assertEqual(overview["data"]["today"]["wordsLearned"], 1)

        insights = asyncio.run(language_insights(AUTH, self.db))
        data = insights["data"]
        self.assertEqual(data["readingTrend"][0]["rate"], 80)
        self.assertTrue(data["hasSessions"])
        self.assertEqual(data["totals"]["words"], 1)
        self.assertEqual(data["vocabularyCefr"].get("B2"), 1)
        self.assertNotIn("advice", data, "聚合端点应秒回，不等待 LLM 建议")

        fake_advice = {"summaryZh": "坚持", "weaknesses": ["时态"], "plan": ["每日跟读"]}
        with patch("app.api.endpoints.language.build_learning_advice", return_value=fake_advice):
            advice = asyncio.run(language_insights_advice(AUTH, self.db))
        self.assertEqual(advice["data"]["weaknesses"], ["时态"])

        empty_advice = asyncio.run(language_insights_advice("Bearer " + create_access_token("no_such_user", "student"), self.db))
        self.assertEqual(empty_advice["data"]["plan"], [])


if __name__ == "__main__":
    unittest.main()
