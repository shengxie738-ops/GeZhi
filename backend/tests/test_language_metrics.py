"""评分可信度改造（混合评分）测试。

覆盖四层：
1. 确定性指标纯函数（写作实测 / WAV 实测 / 匹配率 / 填充词）；
2. 融合规则（overall 重算、证据锚定、缺失回退、空转写封顶）；
3. 服务层（analyze_writing / analyze_speaking 在 mock LLM 下输出融合分 + 证据）；
4. 端点落库（evidence / 服务端时长真实写入 session 与 writing_history）。
"""

import asyncio
import base64
import io
import math
import os
import struct
import unittest
import wave
from unittest.mock import patch

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

from app.api.endpoints.language import (
    SpeakingAnalyzeRequest,
    WritingAnalyzeRequest,
    language_overview,
    speaking_analyze,
    writing_analyze,
    writing_history_detail,
    writing_history_list,
)
from app.core.security import create_access_token
from app.models.domain_record import DomainRecord
from app.repositories.json_store import JsonStore
from app.services.language_metrics import (
    EMPTY_TRANSCRIPT_CAP,
    WRITING_OVERALL_WEIGHTS,
    clamp_score,
    filler_count,
    fuse_speaking,
    fuse_writing,
    speaking_metrics,
    wav_audio_metrics,
    word_match_rate,
    writing_metrics,
)
from app.services.language_service import analyze_speaking, analyze_writing


AUTH = f"Bearer {create_access_token('student_metrics_test', 'student')}"


def make_wav(total_seconds: float = 3.0, rate: int = 16000) -> bytes:
    """合成 16-bit 单声道 WAV：0~1s 语音、1~2s 静音、2s 后语音 → 停顿占比约 1/3。"""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        frames = bytearray()
        for index in range(int(total_seconds * rate)):
            t = index / rate
            speaking = t < 1.0 or t >= 2.0
            amp = int(12000 * math.sin(2 * math.pi * 220 * t)) if speaking else 0
            frames += struct.pack("<h", amp)
        wav.writeframes(bytes(frames))
    return buffer.getvalue()


class ClampTest(unittest.TestCase):
    def test_clamp_bounds_and_none(self):
        self.assertEqual(clamp_score(120), 98)
        self.assertEqual(clamp_score(-5), 5)
        self.assertEqual(clamp_score(None), 0)
        self.assertEqual(clamp_score("88"), 88)  # 模型给字符串数字也要能钳
        self.assertEqual(clamp_score("abc"), 0)


class WritingMetricsTest(unittest.TestCase):
    TEXT = "He go to school yesterday. She like reading books. They is happy every day."

    def test_counts_and_density(self):
        issues = [{"type": "grammar"}, {"type": "grammar"}, {"type": "vocabulary"}]
        metrics = writing_metrics(self.TEXT, issues)
        self.assertEqual(metrics["wordCount"], 14)
        self.assertEqual(metrics["sentenceCount"], 3)
        self.assertAlmostEqual(metrics["avgSentenceLength"], round(14 / 3, 1))
        self.assertEqual(metrics["issueCounts"]["grammar"], 2)
        self.assertAlmostEqual(metrics["issueDensity"]["grammar"], round(2 / 14 * 100, 2))
        self.assertEqual(metrics["totalIssues"], 3)
        self.assertTrue(0 < metrics["lexicalDiversity"] <= 1)

    def test_empty_text(self):
        metrics = writing_metrics("", [])
        self.assertEqual(metrics["wordCount"], 0)
        self.assertEqual(metrics["issueDensity"]["grammar"], 0.0)


class FuseWritingTest(unittest.TestCase):
    def test_overall_is_weighted_mean_not_llm_report(self):
        metrics = writing_metrics("word " * 50, [{"type": "grammar"}] * 2)
        fused = fuse_writing({"overall": 99, "grammar": 95, "vocabulary": 90, "coherence": 90, "expression": 92}, metrics)
        expected = round(sum(fused["score"][key] * weight for key, weight in WRITING_OVERALL_WEIGHTS.items()))
        self.assertEqual(fused["score"]["overall"], clamp_score(expected))
        self.assertNotEqual(fused["score"]["overall"], 99)

    def test_grammar_anchored_by_issue_density(self):
        # 50 词 4 处语法问题 → 密度 8/百词 → 证据分 100-72=28 → 钳到 40；与模型分 95 融合 ≈ 68
        metrics = writing_metrics("word " * 50, [{"type": "grammar"}] * 4)
        fused = fuse_writing({"grammar": 95, "vocabulary": 90, "coherence": 90, "expression": 90}, metrics)
        self.assertEqual(fused["score"]["grammar"], clamp_score(95 * 0.5 + 40 * 0.5))
        self.assertIn("证据分 40", fused["scoreBasis"]["grammar"])

    def test_missing_llm_dims_fall_back_to_evidence(self):
        metrics = writing_metrics("word " * 50, [])
        fused = fuse_writing({"grammar": 88}, metrics)  # 模型只回了 grammar
        self.assertEqual(fused["score"]["coherence"], 0)
        self.assertGreater(fused["score"]["grammar"], 0)
        self.assertEqual(fused["evidence"], metrics)
        for key in ("grammar", "vocabulary", "coherence", "expression", "overall"):
            self.assertIn(key, fused["scoreBasis"])


class SpeakingMetricsTest(unittest.TestCase):
    def test_wav_duration_and_pause(self):
        audio = wav_audio_metrics(make_wav(3.0))
        self.assertEqual(audio["durationSec"], 3.0)
        self.assertEqual(audio["audioSource"], "server")
        self.assertTrue(0.15 <= audio["pauseRatio"] <= 0.5, f"停顿占比异常: {audio['pauseRatio']}")

    def test_invalid_wav_returns_none(self):
        self.assertIsNone(wav_audio_metrics(b"not a wav"))
        self.assertIsNone(wav_audio_metrics(None))

    def test_match_rate(self):
        self.assertEqual(word_match_rate("the quick brown fox jumps", "the quick brown fox jumps"), 100.0)
        self.assertEqual(word_match_rate("the quick brown fox jumps", "the quick black fox"), 60.0)
        self.assertEqual(word_match_rate("the quick brown fox", ""), 0.0)
        self.assertIsNone(word_match_rate("", "anything"))

    def test_filler_count(self):
        self.assertEqual(filler_count("um I think uh maybe erm"), 3)
        self.assertEqual(filler_count("no fillers here"), 0)

    def test_speaking_metrics_prefers_server_duration(self):
        wav = make_wav(3.0)
        metrics = speaking_metrics(
            wav_bytes=wav,
            transcript="um the quick brown fox",
            reference_text="the quick brown fox",
            client_duration_sec=99.0,
        )
        self.assertEqual(metrics["durationSec"], 3.0)
        self.assertEqual(metrics["audioSource"], "server")
        self.assertEqual(metrics["fillerCount"], 1)
        self.assertEqual(metrics["matchRate"], 75.0)  # 参考文本 4 词，插入 1 个 um → 1-1/4
        self.assertTrue(metrics["wordsPerMinute"] > 0)

    def test_speaking_metrics_falls_back_to_client(self):
        metrics = speaking_metrics(wav_bytes=b"broken", transcript="hello world", client_duration_sec=12.0)
        self.assertEqual(metrics["durationSec"], 12.0)
        self.assertEqual(metrics["audioSource"], "client")
        self.assertNotIn("pauseRatio", metrics)


class FuseSpeakingTest(unittest.TestCase):
    def test_read_aloud_blends_match_rate(self):
        metrics = speaking_metrics(
            wav_bytes=make_wav(3.0),
            transcript="the quick brown fox",
            reference_text="the quick brown fox jumps over",
            client_duration_sec=0,
        )
        fused = fuse_speaking(
            {"pronunciation": 90, "fluency": 80, "accuracy": 90, "intonation": 85},
            metrics,
            mode="read_aloud",
        )
        match = metrics["matchRate"]
        self.assertEqual(fused["score"]["accuracy"], clamp_score(90 * 0.4 + match * 0.6))
        self.assertEqual(fused["score"]["pronunciation"], clamp_score(90 * 0.6 + match * 0.4))
        expected = round(
            fused["score"]["pronunciation"] * 0.30
            + fused["score"]["fluency"] * 0.25
            + fused["score"]["accuracy"] * 0.25
            + fused["score"]["intonation"] * 0.20
        )
        self.assertEqual(fused["score"]["overall"], clamp_score(expected))

    def test_free_mode_keeps_llm_pronunciation(self):
        metrics = speaking_metrics(wav_bytes=None, transcript="i think it is good", client_duration_sec=10)
        fused = fuse_speaking(
            {"pronunciation": 77, "fluency": 70, "accuracy": 80, "intonation": 75},
            metrics,
            mode="free",
        )
        self.assertEqual(fused["score"]["pronunciation"], 77)  # 自由表达无参考文本锚点
        self.assertIn("模型听辨评定", fused["scoreBasis"]["pronunciation"])

    def test_empty_transcript_caps_overall(self):
        metrics = speaking_metrics(wav_bytes=make_wav(3.0), transcript="", reference_text="anything", client_duration_sec=0)
        fused = fuse_speaking(
            {"pronunciation": 90, "fluency": 90, "accuracy": 90, "intonation": 90},
            metrics,
            mode="read_aloud",
        )
        self.assertLessEqual(fused["score"]["overall"], EMPTY_TRANSCRIPT_CAP)
        self.assertIn("封顶", fused["scoreBasis"]["overall"])

    def test_ideal_wpm_scores_high(self):
        metrics = {"wordsPerMinute": 130, "durationSec": 30, "pauseRatio": 0.05}
        fused = fuse_speaking({"fluency": 60}, metrics, mode="free")
        # 证据分 ≈ 95-2.5 → 与模型分 60 融合被拉高
        self.assertGreater(fused["score"]["fluency"], 70)


class ServiceFusionTest(unittest.TestCase):
    def test_analyze_writing_returns_fused_score_and_evidence(self):
        fake = {
            "score": {"overall": 99, "grammar": 95, "vocabulary": 90, "coherence": 90, "expression": 92},
            "scoreEvidence": {"grammar": "1 处主谓不一致", "coherence": "第二段跳跃"},
            "issues": [
                {
                    "type": "grammar",
                    "original": "He go",
                    "suggestion": "He went",
                    "reasonZh": "过去式",
                    "grammarPoint": "Simple Past Tense",
                }
            ],
            "improvedText": "He went to school.",
        }
        with patch("app.services.language_service.chat_json", return_value=fake) as mock_call:
            data = asyncio.run(analyze_writing("qwen3.7-plus", "He go to school yesterday.", "standard"))
        self.assertEqual(mock_call.call_args.kwargs["temperature"], 0.1)
        self.assertIn("evidence", data)
        self.assertIn("scoreBasis", data)
        expected = round(sum(data["score"][key] * weight for key, weight in WRITING_OVERALL_WEIGHTS.items()))
        self.assertEqual(data["score"]["overall"], clamp_score(expected))
        self.assertEqual(data["evidence"]["issueCounts"]["grammar"], 1)

    def test_analyze_speaking_measures_duration_server_side(self):
        wav = make_wav(3.0)
        fake = {
            "transcript": "um the quick brown fox",
            "scores": {"overall": 90, "pronunciation": 90, "fluency": 85, "accuracy": 90, "intonation": 88},
            "words": [],
            "feedbackZh": "流利",
            "suggestionsZh": [],
        }
        with patch("app.services.language_service.omni_json", return_value=fake) as mock_call:
            data = asyncio.run(
                analyze_speaking(
                    "qwen3.5-omni-flash",
                    audio_base64=base64.b64encode(wav).decode(),
                    mode="read_aloud",
                    reference_text="the quick brown fox",
                    duration_sec=99.0,
                )
            )
        self.assertEqual(mock_call.call_args.kwargs["temperature"], 0.1)
        self.assertEqual(data["durationSec"], 3.0)  # 服务端实测覆盖客户端 99s
        self.assertEqual(data["evidence"]["audioSource"], "server")
        self.assertEqual(data["evidence"]["matchRate"], 75.0)
        self.assertIn("scoreBasis", data)
        self.assertNotEqual(data["scores"]["overall"], 90)  # overall 已按维度重算


class EvidencePersistenceTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        DomainRecord.__table__.create(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()

    def tearDown(self):
        self.db.close()

    def test_writing_session_and_history_store_evidence(self):
        fake = {
            "score": {"overall": 82, "grammar": 91, "vocabulary": 76, "coherence": 81, "expression": 79},
            "evidence": {"wordCount": 5, "issueCounts": {"grammar": 1}},
            "scoreBasis": {"grammar": "代码实测：1 处语法问题"},
            "issues": [],
            "improvedText": "He went.",
            "mode": "standard",
        }
        with patch("app.api.endpoints.language.analyze_writing", return_value=fake):
            asyncio.run(
                writing_analyze(
                    WritingAnalyzeRequest(text="He go to school yesterday.", durationSec=300.0),
                    AUTH,
                    self.db,
                )
            )
        store = JsonStore(self.db)
        sessions = store.list_payloads("language", record_type="session", owner_id="student_metrics_test")
        self.assertEqual(sessions[0]["evidence"]["wordCount"], 5)
        self.assertEqual(sessions[0]["durationSec"], 300.0)  # 写作耗时真实入库
        history = asyncio.run(writing_history_list(AUTH, self.db))["data"]["entries"]
        self.assertEqual(len(history), 1)
        detail = asyncio.run(writing_history_detail(history[0]["id"], AUTH, self.db))["data"]
        self.assertEqual(detail["evidence"]["wordCount"], 5)
        self.assertEqual(detail["scoreBasis"]["grammar"], "代码实测：1 处语法问题")
        self.assertEqual(detail["durationSec"], 300.0)

    def test_speaking_session_stores_server_duration_and_evidence(self):
        fake = {
            "transcript": "hello",
            "scores": {"overall": 80, "pronunciation": 80, "fluency": 80, "accuracy": 80, "intonation": 80},
            "evidence": {"durationSec": 3.0, "audioSource": "server", "wordsPerMinute": 20.0},
            "durationSec": 3.0,
            "words": [],
            "feedbackZh": "",
            "suggestionsZh": [],
            "mode": "free",
        }
        with patch("app.api.endpoints.language.analyze_speaking", return_value=fake):
            asyncio.run(
                speaking_analyze(
                    SpeakingAnalyzeRequest(audioBase64="x" * 200, mode="free", durationSec=99.0),
                    AUTH,
                    self.db,
                )
            )
        store = JsonStore(self.db)
        sessions = store.list_payloads("language", record_type="session", owner_id="student_metrics_test")
        self.assertEqual(sessions[0]["durationSec"], 3.0)  # 服务端实测时长入库，覆盖客户端 99s
        self.assertEqual(sessions[0]["evidence"]["audioSource"], "server")
        overview = asyncio.run(language_overview(AUTH, self.db))
        self.assertGreaterEqual(overview["data"]["today"]["learningMinutes"], 0)


if __name__ == "__main__":
    unittest.main()
