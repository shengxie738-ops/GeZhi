"""外语评分的确定性证据层（评分可信度改造 · 混合评分方案）。

原则：
- 指标全部由代码从作文原文 / 录音 WAV 实测得出：可复现、可单测、可审计；
- LLM 只承担机器测不出的判断（连贯、地道、语调自然度、发音质量），其分数
  仅作为融合输入，绝不直接采信模型给出的 overall；
- overall 一律由维度分按固定权重重算；
- 阈值与权重集中为模块级常量并注明依据，调整需有据可查。
"""

import array
import io
import math
import re
import wave

SCORE_FLOOR, SCORE_CEIL = 5, 98  # 0 分保留给「未产出内容」，正常评分不触底也不给满分

WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]*")
FILLERS = {"uh", "um", "umm", "uhh", "er", "erm", "hmm", "mhm"}

# ---------------- 写作融合参数 ----------------
# overall 权重：表达与连贯合计过半（训练目标），语法是硬约束，词汇最依赖主观判断故权重最低
WRITING_OVERALL_WEIGHTS = {"grammar": 0.25, "vocabulary": 0.20, "coherence": 0.25, "expression": 0.30}
# 语法证据锚：每百词 1 处语法问题扣 9 分（1 处→91、2 处→82、5 处→55）
GRAMMAR_PENALTY_PER_100 = 9.0
GRAMMAR_FUSION = 0.5  # 错误数量是硬事实，但「什么算错」仍需模型判断，各半
# 词汇证据锚：TTR（型符比）0.40 为及格线，每 +0.01 加 1.2 分
VOCAB_TTR_BASE, VOCAB_TTR_SCALE = 60.0, 120.0
VOCAB_FUSION = 0.25  # TTR 受篇幅影响（短文天然偏高），只做轻锚定

# ---------------- 口语融合参数 ----------------
SPEAKING_OVERALL_WEIGHTS = {"pronunciation": 0.30, "fluency": 0.25, "accuracy": 0.25, "intonation": 0.20}
# 语速证据锚：110~160 wpm 为理想带（满分带 95），带外按离中心距离线性扣分
WPM_IDEAL_LOW, WPM_IDEAL_HIGH = 110.0, 160.0
WPM_IDEAL_CENTER = (WPM_IDEAL_LOW + WPM_IDEAL_HIGH) / 2
WPM_IDEAL_SCORE = 95.0
WPM_PENALTY_PER_WPM = 0.85  # 每偏离 1 wpm 扣 0.85（慢 40 wpm ≈ 扣 34 分）
FLUENCY_FUSION = 0.5
PAUSE_PENALTY_PER_PERCENT = 0.5  # 停顿占比每 1% 扣 0.5（30% 静音 ≈ 扣 15）
EVIDENCE_FLOOR, EVIDENCE_CEIL = 40, 96  # 证据分区间：证据再差也留底线，再好不给满分
# 跟读模式：参考文本词级匹配率是发音/内容准确度的硬证据
MATCH_PRON_WEIGHT, MATCH_ACC_WEIGHT = 0.4, 0.6
EMPTY_TRANSCRIPT_CAP = 25  # 转写为空说明几乎没有有效语音，总分封顶


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def clamp_score(value, floor: int = SCORE_FLOOR, ceil: int = SCORE_CEIL) -> int:
    number = _num(value)
    if number is None:
        return 0
    return int(round(max(floor, min(ceil, number))))


def word_list(text: str) -> list[str]:
    return [word.lower() for word in WORD_RE.findall(text or "")]


# ---------------------------------------------------------------- 写作实测指标

def writing_metrics(text: str, issues: list[dict] | None) -> dict:
    words = word_list(text)
    word_count = len(words)
    sentences = [chunk for chunk in re.split(r"[.!?]+", text or "") if word_list(chunk)]
    ttr = len(set(words)) / word_count if word_count else 0.0
    counts = {}
    density = {}
    for issue_type in ("grammar", "vocabulary", "expression", "style"):
        count = sum(1 for issue in issues or [] if issue.get("type") == issue_type)
        counts[issue_type] = count
        density[issue_type] = round(count / word_count * 100, 2) if word_count else 0.0
    return {
        "wordCount": word_count,
        "sentenceCount": len(sentences),
        "avgSentenceLength": round(word_count / len(sentences), 1) if sentences else 0.0,
        "lexicalDiversity": round(ttr, 3),
        "issueCounts": counts,
        "issueDensity": density,
        "totalIssues": len(issues or []),
    }


def _evidence_grammar(metrics: dict) -> int:
    density = (metrics.get("issueDensity") or {}).get("grammar") or 0.0
    return clamp_score(100 - density * GRAMMAR_PENALTY_PER_100, EVIDENCE_FLOOR, EVIDENCE_CEIL)


def _evidence_vocabulary(metrics: dict) -> int:
    ttr = _num(metrics.get("lexicalDiversity")) or 0.0
    return clamp_score(VOCAB_TTR_BASE + (ttr - 0.40) * VOCAB_TTR_SCALE, EVIDENCE_FLOOR, EVIDENCE_CEIL)


def _blend(llm_value, evidence_value, evidence_weight: float) -> int:
    """模型分与证据分加权融合；任一侧缺失时退回另一侧，两侧皆缺记 0。"""
    llm = _num(llm_value)
    if llm is None and evidence_value is None:
        return 0
    if llm is None:
        return clamp_score(evidence_value)
    if evidence_value is None:
        return clamp_score(llm)
    return clamp_score(llm * (1 - evidence_weight) + evidence_value * evidence_weight)


def fuse_writing(llm_score: dict | None, metrics: dict, llm_evidence: dict | None = None) -> dict:
    """写作评分融合：grammar/ vocabulary 锚定实测证据，coherence/expression 由模型评定，
    overall 按固定权重重算。返回 {score, evidence, scoreBasis}，scoreBasis 为逐维度中文依据。"""
    llm_score = llm_score or {}
    llm_evidence = llm_evidence or {}
    grammar_ev = _evidence_grammar(metrics)
    vocab_ev = _evidence_vocabulary(metrics)
    score = {
        "grammar": _blend(llm_score.get("grammar"), grammar_ev, GRAMMAR_FUSION),
        "vocabulary": _blend(llm_score.get("vocabulary"), vocab_ev, VOCAB_FUSION),
        "coherence": clamp_score(llm_score.get("coherence")),
        "expression": clamp_score(llm_score.get("expression")),
    }
    score["overall"] = clamp_score(round(sum(score[key] * weight for key, weight in WRITING_OVERALL_WEIGHTS.items())))
    counts = metrics.get("issueCounts") or {}
    density = metrics.get("issueDensity") or {}
    basis = {
        "grammar": (
            f"代码实测：{counts.get('grammar', 0)} 处语法问题 / {metrics.get('wordCount', 0)} 词"
            f"（每百词 {density.get('grammar', 0)}）→ 证据分 {grammar_ev}，与模型分融合权重 50%"
        ),
        "vocabulary": (
            f"代码实测：词汇多样性 TTR {metrics.get('lexicalDiversity', 0)} → 证据分 {vocab_ev}，"
            f"融合权重 25%（TTR 受篇幅影响，仅轻锚定）"
        ),
        "coherence": f"模型评定：{llm_evidence['coherence']}" if llm_evidence.get("coherence") else "由模型按衔接与逻辑评定（代码无此项锚点）",
        "expression": f"模型评定：{llm_evidence['expression']}" if llm_evidence.get("expression") else "由模型按地道与自然度评定（代码无此项锚点）",
        "overall": "总分 = 语法25% + 词汇20% + 连贯25% + 表达30% 加权重算，不采信模型直报总分",
    }
    return {"score": score, "evidence": metrics, "scoreBasis": basis}


# ---------------------------------------------------------------- 口语实测指标

def wav_audio_metrics(wav_bytes: bytes | None) -> dict | None:
    """从 WAV 字节实测时长与停顿占比；解析失败返回 None（调用方回落客户端上报时长）。
    停顿判定：20ms 窗 RMS 能量 VAD，阈值取最大窗能量的 15%（相对阈值，抗录音音量差异）。"""
    if not wav_bytes:
        return None
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
            channels = wav.getnchannels()
            sampwidth = wav.getsampwidth()
            framerate = wav.getframerate()
            raw = wav.readframes(wav.getnframes())
    except Exception:
        return None
    if framerate <= 0 or not raw:
        return None
    frames = len(raw) // (channels * sampwidth) if channels * sampwidth else 0
    if frames <= 0:
        return None
    metrics: dict = {
        "durationSec": round(frames / framerate, 2),
        "sampleRate": framerate,
        "audioSource": "server",
    }
    if sampwidth != 2:
        metrics["pauseRatio"] = None  # 仅支持 16-bit PCM 的 VAD；其余格式只实测时长
        return metrics
    samples = array.array("h")
    samples.frombytes(raw)
    mono = samples[::channels] if channels > 1 else samples
    window = max(1, int(framerate * 0.02))
    energies = []
    for start in range(0, len(mono), window):
        chunk = mono[start : start + window]
        acc = 0
        for sample in chunk:
            acc += sample * sample
        energies.append(math.sqrt(acc / len(chunk)) if chunk else 0.0)
    peak = max(energies, default=0.0)
    if peak <= 0:
        metrics["pauseRatio"] = 1.0  # 全程静音
    else:
        threshold = peak * 0.15
        speech_ratio = sum(1 for energy in energies if energy > threshold) / len(energies)
        metrics["pauseRatio"] = round(1 - speech_ratio, 3)
    return metrics


def filler_count(transcript: str) -> int:
    return sum(1 for word in word_list(transcript) if word in FILLERS)


def word_match_rate(reference: str, transcript: str) -> float | None:
    """参考文本与转写的词级 Levenshtein 匹配率（0~100）。参考为空返回 None。"""
    ref = word_list(reference)
    if not ref:
        return None
    hyp = word_list(transcript)
    prev = list(range(len(hyp) + 1))
    for i, r_word in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h_word in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r_word != h_word))
        prev = cur
    distance = prev[-1]
    return round(max(0.0, 1 - distance / len(ref)) * 100, 1)


def speaking_metrics(
    *,
    wav_bytes: bytes | None,
    transcript: str,
    reference_text: str = "",
    client_duration_sec: float = 0.0,
) -> dict:
    """口语实测指标：时长优先取服务端 WAV 实测（不信任客户端上报），无音频解析结果时回落客户端值。"""
    audio = wav_audio_metrics(wav_bytes)
    duration = (audio or {}).get("durationSec") or max(0.0, _num(client_duration_sec) or 0.0)
    words = word_list(transcript)
    wpm = round(len(words) / (duration / 60), 1) if duration >= 1.0 and words else 0.0
    metrics = {
        "durationSec": round(duration, 1),
        "audioSource": (audio or {}).get("audioSource") if audio else ("client" if duration > 0 else "none"),
        "transcriptWordCount": len(words),
        "wordsPerMinute": wpm,
        "fillerCount": filler_count(transcript),
        "matchRate": None,
    }
    if audio and audio.get("pauseRatio") is not None:
        metrics["pauseRatio"] = audio["pauseRatio"]
    if reference_text:
        rate = word_match_rate(reference_text, transcript)
        if rate is not None:
            metrics["matchRate"] = rate
    return metrics


def _evidence_fluency(metrics: dict):
    wpm = _num(metrics.get("wordsPerMinute")) or 0.0
    duration = _num(metrics.get("durationSec")) or 0.0
    if duration < 1.0 or wpm <= 0:
        return None  # 无可靠时长/转写时不编造证据
    if WPM_IDEAL_LOW <= wpm <= WPM_IDEAL_HIGH:
        base = WPM_IDEAL_SCORE
    else:
        base = 100 - min(55.0, abs(wpm - WPM_IDEAL_CENTER) * WPM_PENALTY_PER_WPM)
    pause_percent = (_num(metrics.get("pauseRatio")) or 0.0) * 100
    return clamp_score(base - pause_percent * PAUSE_PENALTY_PER_PERCENT, EVIDENCE_FLOOR, EVIDENCE_CEIL)


def fuse_speaking(llm_scores: dict | None, metrics: dict, mode: str, llm_evidence: dict | None = None) -> dict:
    """口语评分融合：跟读模式的 pronunciation/accuracy 锚定参考文本匹配率，
    fluency 锚定语速与停顿实测，intonation 由模型评定，overall 按固定权重重算。"""
    llm_scores = llm_scores or {}
    llm_evidence = llm_evidence or {}
    match = _num(metrics.get("matchRate"))
    read_aloud = mode == "read_aloud" and match is not None
    fluency_ev = _evidence_fluency(metrics)
    score = {
        "pronunciation": _blend(llm_scores.get("pronunciation"), match if read_aloud else None, MATCH_PRON_WEIGHT),
        "fluency": _blend(llm_scores.get("fluency"), fluency_ev, FLUENCY_FUSION),
        "accuracy": _blend(llm_scores.get("accuracy"), match if read_aloud else None, MATCH_ACC_WEIGHT),
        "intonation": clamp_score(llm_scores.get("intonation")),
    }
    overall = clamp_score(round(sum(score[key] * weight for key, weight in SPEAKING_OVERALL_WEIGHTS.items())))
    empty_transcript = (metrics.get("transcriptWordCount") or 0) == 0
    if empty_transcript:
        overall = min(overall, EMPTY_TRANSCRIPT_CAP)
    score["overall"] = overall
    pause_ratio = metrics.get("pauseRatio")
    basis = {
        "pronunciation": (
            f"代码实测：参考文本词级匹配率 {match}% → 证据分即匹配率，融合权重 {int(MATCH_PRON_WEIGHT * 100)}%"
            if read_aloud else "由模型听辨评定（自由表达无参考文本锚点）"
        ),
        "fluency": (
            f"代码实测：语速 {metrics.get('wordsPerMinute', 0)} wpm、停顿占比 {round((_num(pause_ratio) or 0) * 100)}% "
            f"→ 证据分 {fluency_ev}，与模型分融合权重 50%"
            if fluency_ev is not None else "音频实测不可用（时长或转写缺失），采用模型评定"
        ),
        "accuracy": (
            f"代码实测：参考文本词级匹配率 {match}% → 证据分即匹配率，融合权重 {int(MATCH_ACC_WEIGHT * 100)}%"
            if read_aloud else "由模型按语法与用词准确性评定"
        ),
        "intonation": f"模型评定：{llm_evidence['intonation']}" if llm_evidence.get("intonation") else "由模型按语调起伏与重音评定（代码无此项锚点）",
        "overall": "总分 = 发音30% + 流利25% + 准确25% + 语调20% 加权重算，不采信模型直报总分"
        + ("；转写为空，总分已封顶" if empty_transcript else ""),
    }
    return {"score": score, "evidence": metrics, "scoreBasis": basis}
