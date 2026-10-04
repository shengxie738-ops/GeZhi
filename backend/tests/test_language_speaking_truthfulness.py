"""Finite source-only oral truthfulness contract; run through the frozen guard.

Extract only reviewed AST definitions, never import application modules. Provider
objects are inert and persistence names are non-callable objects, not callbacks.
Removing the ASR guard, restoring missing-score defaults, or exposing provider
exceptions must make these tests fail. Synthetic success checks code-path
compatibility only; they do not establish a real audio assessor's availability.
"""
import array
import ast
import asyncio
import base64
import copy
import hashlib
import io
import json
import math
from pathlib import Path
import re
from types import SimpleNamespace
import wave

from fastapi import HTTPException
import pytest


ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "backend/app/services/language_service.py"
ENDPOINT = ROOT / "backend/app/api/endpoints/language.py"
ASR_MODELS = (
    "qwen-audio-3.0-asr-flash", "paraformer-v2", "paraformer-v1",
    "paraformer-mtl-v1", "paraformer-8k-v2", "paraformer-v",
)
ASR_UNAVAILABLE = "当前模型仅支持语音转写，无法评测发音和语调，未生成评分"
PROVIDER_PRIVATE = "synthetic-private-provider-detail"
SYNTHETIC_AUDIO = "c3ludGhldGlj"  # Non-audio placeholder, never sent externally.
DIMENSIONS = ("pronunciation", "fluency", "accuracy", "intonation")
VALID_RESULT = {
    "transcript": "We learn together",
    "scores": {"overall": 99, "pronunciation": 82, "fluency": 78,
               "accuracy": 85, "intonation": 79},
    "scoreEvidence": {"intonation": "synthetic audio assessment"},
    "words": [], "feedbackZh": "synthetic result", "suggestionsZh": [],
}
SERVICE_FUNCTIONS = frozenset({
    "extract_json", "chat_json", "omni_json", "analyze_speaking",
    "analyze_reading", "explain_vocabulary", "analyze_writing",
    "optimize_writing", "build_learning_advice",
})
METRICS_FUNCTIONS = frozenset({
    "_num", "clamp_score", "word_list", "writing_metrics",
    "_evidence_grammar", "_evidence_vocabulary", "_blend", "fuse_writing",
    "wav_audio_metrics", "filler_count", "word_match_rate", "speaking_metrics",
    "_evidence_fluency", "fuse_speaking",
})


def _load_definitions(path, names, namespace):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    # Constants and exact named definitions only: no source imports/startup.
    nodes = [copy.deepcopy(node) for node in tree.body
             if isinstance(node, ast.Assign)
             or isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
             and node.name in names]
    assert {node.name for node in nodes if hasattr(node, "name")} == names
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)


def _service(*, result=None, error=None, asr_error=False, raw_response=None):
    events = []
    result = copy.deepcopy(VALID_RESULT if result is None else result)
    namespace = {"asyncio": asyncio, "base64": base64, "json": json,
                 "math": math, "re": re, "array": array, "io": io, "wave": wave}
    _load_definitions(ROOT / "backend/app/services/language_metrics.py",
                      METRICS_FUNCTIONS, namespace)

    def get_config(model_id, *, category):
        assert category == "omni"
        return SimpleNamespace(model_id="paraformer-v1" if model_id == "paraformer-v" else model_id)

    async def transcribe(*args):
        events.append("asr")
        if asr_error:
            raise RuntimeError(PROVIDER_PRIVATE)
        return "We learn together", [{"text": "learn"}]

    async def create(**kwargs):
        events.append(("audio", kwargs))
        if error is not None:
            raise error
        content = raw_response if raw_response is not None else json.dumps(result)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    def build_audio(model_id):
        events.append("audio-client")
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), "synthetic-provider-model"

    class TextModel:
        def bind(self, **kwargs):
            events.append(("text-bind", kwargs))
            return self

        async def ainvoke(self, messages):
            events.append(("text", messages))
            if asr_error:
                raise RuntimeError(PROVIDER_PRIVATE)
            return SimpleNamespace(content=json.dumps(result))

    namespace.update({"get_model_config": get_config, "build_omni_client": build_audio,
                      "build_chat_model": lambda *a, **k: TextModel(),
                      "SystemMessage": lambda **k: SimpleNamespace(**k),
                      "HumanMessage": lambda **k: SimpleNamespace(**k),
                      "transcribe_audio_speech": transcribe})
    _load_definitions(SERVICE, SERVICE_FUNCTIONS, namespace)
    return namespace, events


def _endpoint(namespace, model_id):
    node = copy.deepcopy(next(node for node in ast.parse(ENDPOINT.read_text()).body
                              if isinstance(node, ast.AsyncFunctionDef) and node.name == "speaking_analyze"))
    node.decorator_list = []
    # Strip only dependency defaults/type annotations; keep the complete body.
    for arg in node.args.args:
        arg.annotation = None
    node.args.defaults = [ast.Constant(None) for _ in node.args.defaults]
    node.returns = None
    namespace.update({"HTTPException": HTTPException,
                      "require_user": lambda *a: "synthetic-user",
                      "resolve_language_model": lambda *a, **k: model_id,
                      "JsonStore": object(), "_save_session": object()})
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                 str(ENDPOINT), "exec"), namespace)
    request = SimpleNamespace(model=model_id, audioBase64=SYNTHETIC_AUDIO,
                              audioFormat="wav", mode="read_aloud",
                              referenceText="We learn together", topic="", durationSec=2.0)
    return namespace["speaking_analyze"](request, None, object())


def _outcome(coroutine):
    try:
        return asyncio.run(coroutine)
    except Exception as exc:
        return exc


@pytest.mark.parametrize("model_id", ASR_MODELS)
@pytest.mark.parametrize("asr_error", (False, True))
def test_asr_models_reject_before_transcription_or_text_fallback(model_id, asr_error):
    namespace, events = _service(asr_error=asr_error)
    outcome = _outcome(namespace["omni_json"](model_id, prompt="synthetic task", audio_base64=SYNTHETIC_AUDIO))
    assert isinstance(outcome, ValueError), "ASR cannot produce an acoustic assessment success"
    assert str(outcome) == ASR_UNAVAILABLE
    assert events == [], "Unsupported assessment must stop before any provider client"


@pytest.mark.parametrize("model_id", ASR_MODELS)
def test_asr_failure_composes_to_502_before_persistence(model_id):
    namespace, events = _service(asr_error=True)
    outcome = _outcome(_endpoint(namespace, model_id))
    assert isinstance(outcome, HTTPException), "Service rejection must precede non-callable persistence sentinels"
    assert outcome.status_code == 502
    assert outcome.detail == "口语评测失败：" + ASR_UNAVAILABLE
    assert events == []


@pytest.mark.parametrize("error", (RuntimeError(PROVIDER_PRIVATE),
                                   ValueError(PROVIDER_PRIVATE), TimeoutError(PROVIDER_PRIVATE)))
def test_audio_provider_errors_fail_closed_without_private_detail(error):
    namespace, events = _service(error=error)
    outcome = _outcome(_endpoint(namespace, "synthetic-audio-assessor"))
    assert isinstance(outcome, HTTPException)
    assert outcome.status_code == 502
    assert outcome.detail == "口语评测失败：口语评测暂不可用，未生成评分"
    assert PROVIDER_PRIVATE not in outcome.detail
    assert [event for event in events if event == "asr"] == []


INVALID_RESULTS = [
    {"scores": VALID_RESULT["scores"]},
    {**VALID_RESULT, "transcript": None},
    {**VALID_RESULT, "transcript": 123},
    {**VALID_RESULT, "scores": None},
    {**VALID_RESULT, "scores": []},
    {**VALID_RESULT, "scores": "invalid"},
    *[{**VALID_RESULT, "scores": {k: v for k, v in VALID_RESULT["scores"].items() if k != dimension}}
      for dimension in DIMENSIONS],
    *[{**VALID_RESULT, "scores": {**VALID_RESULT["scores"], "pronunciation": value}}
      for value in (None, "82", True, float("nan"), float("inf"), float("-inf"))],
]


@pytest.mark.parametrize("result", INVALID_RESULTS)
def test_invalid_audio_results_do_not_become_fused_score_success(result):
    namespace, _ = _service(result=result)
    outcome = _outcome(_endpoint(namespace, "synthetic-audio-assessor"))
    assert isinstance(outcome, HTTPException), "Malformed assessment must not become a score payload"
    assert outcome.status_code == 502
    assert outcome.detail == "口语评测失败：口语评测结果无效，未生成评分"


@pytest.mark.parametrize("raw_response", ("", "not-json", "{unclosed"))
def test_malformed_audio_json_is_safe_unavailable(raw_response):
    namespace, _ = _service(raw_response=raw_response)
    outcome = _outcome(_endpoint(namespace, "synthetic-audio-assessor"))
    assert isinstance(outcome, HTTPException)
    assert outcome.status_code == 502
    assert outcome.detail == "口语评测失败：口语评测暂不可用，未生成评分"


@pytest.mark.parametrize("result", (None, [], "invalid"))
def test_non_object_assessment_boundary_result_is_rejected(result):
    namespace, _ = _service()

    async def malformed_audio_boundary(*args, **kwargs):
        return result

    namespace["omni_json"] = malformed_audio_boundary
    outcome = _outcome(_endpoint(namespace, "synthetic-audio-assessor"))
    assert isinstance(outcome, HTTPException)
    assert outcome.status_code == 502
    assert outcome.detail == "口语评测失败：口语评测结果无效，未生成评分"


@pytest.mark.parametrize("mode", ("read_aloud", "free"))
@pytest.mark.parametrize("transcript", ("We learn together", ""))
def test_valid_audio_result_preserves_recording_and_fusion(mode, transcript):
    result = {**VALID_RESULT, "transcript": transcript}
    # Model overall is ignored, even absent; dimensions remain mandatory.
    result["scores"] = {k: v for k, v in VALID_RESULT["scores"].items() if k != "overall"}
    namespace, events = _service(result=result)
    outcome = _outcome(namespace["analyze_speaking"](
        "synthetic-audio-assessor", audio_base64=SYNTHETIC_AUDIO, audio_format="wav",
        mode=mode, reference_text="We learn together", duration_sec=2.0))
    assert isinstance(outcome, dict)
    expected_metrics = namespace["speaking_metrics"](
        wav_bytes=base64.b64decode(SYNTHETIC_AUDIO), transcript=transcript,
        reference_text="We learn together" if mode == "read_aloud" else "", client_duration_sec=2.0)
    expected = namespace["fuse_speaking"](result["scores"], expected_metrics, mode, result["scoreEvidence"])
    assert outcome["scores"] == expected["score"]
    assert outcome["evidence"] == expected["evidence"]
    assert outcome["scoreBasis"] == expected["scoreBasis"]
    assert outcome["transcript"] == transcript and outcome["mode"] == mode
    if not transcript:
        assert outcome["scores"]["overall"] <= 25
    request = next(event[1] for event in events if isinstance(event, tuple) and event[0] == "audio")
    assert request["messages"][0]["content"][1] == {
        "type": "input_audio", "input_audio": {"data": "data:audio/wav;base64," + SYNTHETIC_AUDIO, "format": "wav"}}
    assert request["temperature"] == 0.1 and request["max_tokens"] == 4000


def test_failure_boundary_is_structurally_before_persistence():
    endpoint = next(node for node in ast.parse(ENDPOINT.read_text()).body
                    if isinstance(node, ast.AsyncFunctionDef) and node.name == "speaking_analyze")
    boundary = next(node for node in endpoint.body if isinstance(node, ast.Try))
    assert not boundary.orelse and not boundary.finalbody
    assert len(boundary.handlers) == 2
    assert all(len(handler.body) == 1 and isinstance(handler.body[0], ast.Raise)
               for handler in boundary.handlers)
    boundary_index = endpoint.body.index(boundary)
    for node in ast.walk(boundary):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"JsonStore", "_save_session"}
    for index, statement in enumerate(endpoint.body):
        for node in ast.walk(statement):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"JsonStore", "_save_session"}:
                assert index > boundary_index
    assert ast.unparse(endpoint.body[-1]).startswith("return {'status': 'success'")


@pytest.mark.parametrize("method", ("analyze_reading", "explain_vocabulary", "analyze_writing",
                                    "optimize_writing", "build_learning_advice"))
def test_text_practice_methods_keep_using_text_client(method):
    text_result = {"summaryZh": "synthetic summary", "meaningZh": "synthetic meaning",
                   "score": {"grammar": 80, "vocabulary": 75, "coherence": 78, "expression": 82},
                   "issues": [], "improvedText": "We learn together", "plan": []}
    namespace, events = _service(result=text_result)
    args = {"analyze_reading": ("text-model", "We learn together"),
            "explain_vocabulary": ("text-model", "learn", "We learn together"),
            "analyze_writing": ("text-model", "We learn together"),
            "optimize_writing": ("text-model", "We learn together"),
            "build_learning_advice": ("text-model", {"sessions": 1})}[method]
    outcome = _outcome(namespace[method](*args))
    assert isinstance(outcome, dict)
    assert len([event for event in events if isinstance(event, tuple) and event[0] == "text"]) == 1
    assert "asr" not in events and "audio-client" not in events


def test_text_transcription_configuration_and_endpoint_sources_unchanged():
    expected_files = {
        "backend/app/services/model_registry.py": "d75d199fab6da049e12c73e8a78e03af7798bee27838c97383bfb2b65444bbc1",
        "backend/app/services/default_agents.py": "3408e0d477cc28c8657ddecccf26552e78579195e228e5ce0bf1d15b84d049e8",
        "backend/app/services/language_metrics.py": "baf3ba440c3afee6171ba502ded74afb9328133fdcdce7206eef6fa8a85c9c04",
        "backend/app/api/endpoints/language.py": "7b6a377042f91b5a3341db7bb6d935cfcb46d56f1c8fb742819c4ea42c2b848e",
    }
    expected_functions = {
        "extract_json": "1e67093c28da614e8661da285884401d823d8b960968110472b3c0eca5d9381c",
        "chat_json": "2cec8f07afa589cc5d30bee6262c2bc204d46dff0e3c45fe793533109d7e172d",
        "_sync_request_json": "e0c9bfaf45e20a0e7d5c581e34f4ef576a5484380d3a417360f3c91a8e0613b9",
        "transcribe_audio_speech": "5b5b6923caaa7240af1a8b007f7db3a574998a4716fb9f46126d8a7dadfbf3d6",
        "analyze_reading": "f42cbb71cb8fd09171f5a293797ddee5775ddabd10b98d1a5b4e6e66f54592f8",
        "explain_vocabulary": "2384123a4580b663a303b37199b8ea0edf69f8fce9674662f43028e8f78379de",
        "analyze_writing": "6c3aefd721f2e8ee89945bef81813b1eab132ee351a80a3bf202761d738fa9a4",
        "optimize_writing": "9783e73e942eb0fdc949eb3361fa2e9303997aab62d9f8daf53be8527ab07191",
        "build_learning_advice": "ff9921b730ef5db72933c6610220c50a273932b782bfa277fca216924e3c4c49",
    }
    for path, expected in expected_files.items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected
    source = SERVICE.read_text()
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in expected_functions:
            assert hashlib.sha256(ast.get_source_segment(source, node).encode()).hexdigest() == expected_functions[node.name]
