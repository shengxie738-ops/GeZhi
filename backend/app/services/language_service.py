"""外语训练模块的 LLM 编排层。

铁律（对齐产品规格）：
- 所有 AI 返回结果必须结构化（JSON），禁止把大段自然语言直接透传给前端；
- 纯文本任务（阅读分析 / 词汇解释 / 写作批改 / 学习建议）只允许文本模型；
- 口语评测独占全模态 omni 模型，音频经 input_audio(data URI) 传入；
- 模型不可用时抛 ValueError，由端点转成 4xx 提示，绝不静默换模型。
"""

import base64
import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

from app.services.language_metrics import fuse_speaking, fuse_writing, speaking_metrics, writing_metrics
from app.services.model_registry import build_chat_model, build_omni_client

FOREIGN_AGENT_ID = "agent_foreign_language"
SPEAKING_AGENT_ID = "agent_speaking"

READING_MAX_CHARS = 9000
WRITING_MAX_CHARS = 6000
OMNI_JSON_MAX_TOKENS = 4000


# ---------------------------------------------------------------- JSON 工具

def extract_json(text: str) -> dict:
    """从模型回复中提取首个平衡的 JSON 对象；失败抛 ValueError。"""
    if not text:
        raise ValueError("empty model response")
    cleaned = re.sub(r"```(?:json)?", "", text).strip().strip("`")
    start = cleaned.find("{")
    if start < 0:
        raise ValueError("model response contains no JSON object")
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(cleaned)):
        char = cleaned[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return json.loads(cleaned[start : index + 1])
    raise ValueError("model response contains unbalanced JSON")


async def chat_json(model_id: str, *, system: str, user: str, temperature: float = 0.2, max_tokens: int = 4000) -> dict:
    """文本模型的结构化 JSON 调用（build_chat_model 已限定 category=text）。"""
    model = build_chat_model(model_id, temperature=temperature).bind(max_tokens=max_tokens)
    response = await model.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
    content = response.content if isinstance(response.content, str) else "".join(
        part.get("text", "") for part in response.content if isinstance(part, dict)
    )
    return extract_json(content)


async def omni_json(
    model_id: str,
    *,
    prompt: str,
    audio_base64: str | None = None,
    audio_format: str = "wav",
    temperature: float = 0.2,
) -> dict:
    """全模态模型的结构化 JSON 调用；音频以 data URI 形式传入（阿里 MaaS 要求）。"""
    client, provider_model = build_omni_client(model_id)
    content: list[dict] = [{"type": "text", "text": prompt}]
    if audio_base64:
        content.append(
            {
                "type": "input_audio",
                "input_audio": {"data": f"data:audio/{audio_format};base64,{audio_base64}", "format": audio_format},
            }
        )
    response = await client.chat.completions.create(
        model=provider_model,
        messages=[{"role": "user", "content": content}],
        extra_body={"modalities": ["text"]},
        temperature=temperature,
        max_tokens=OMNI_JSON_MAX_TOKENS,
    )
    message = response.choices[0].message if response.choices else None
    return extract_json(getattr(message, "content", None) or "")


# ---------------------------------------------------------------- 阅读理解

READING_SYSTEM = (
    "你是外语阅读理解分析引擎。输出严格 JSON，禁止任何 JSON 之外的文字。"
    "中文讲解，英文原文保留。"
)

READING_SCHEMA_HINT = """{
  "level": "CEFR 等级，A1/A2/B1/B2/C1/C2 之一",
  "estimatedReadingMinutes": 3,
  "keyVocabulary": [{"word": "significantly", "phonetic": "/sɪɡˈnɪfɪkəntli/", "meaningZh": "显著地", "cefr": "B2"}],
  "complexSentences": [{"sentence": "原句", "analysisZh": "句法结构拆解与理解难点（80字内）"}],
  "summaryZh": "文章主旨概括（60字内）",
  "questions": [{"question": "英文阅读理解题", "options": ["A选项", "B选项", "C选项", "D选项"], "answerIndex": 0, "explanationZh": "解析"}]
}"""


async def analyze_reading(model_id: str, text: str, language: str = "en") -> dict:
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", text)
    prompt = (
        f"分析下面这篇{language.upper()}文章，严格按 schema 输出 JSON：\n{READING_SCHEMA_HINT}\n"
        "要求：keyVocabulary 挑 8~14 个超纲/学术核心词；complexSentences 挑 3~6 个最复杂句；"
        "questions 出 4~5 道四选一阅读理解题（考查主旨/细节/推理），answerIndex 为 0~3。\n"
        f"【文章】\n{text[:READING_MAX_CHARS]}"
    )
    data = await chat_json(model_id, system=READING_SYSTEM, user=prompt, max_tokens=8000)
    data.setdefault("level", "B1")
    data.setdefault("estimatedReadingMinutes", max(1, round(len(words) / 160)))
    data.setdefault("keyVocabulary", [])
    data.setdefault("complexSentences", [])
    data.setdefault("summaryZh", "")
    data.setdefault("questions", [])
    data["wordCount"] = len(words)
    return data


# ---------------------------------------------------------------- 词汇解释

VOCAB_SYSTEM = (
    "你是词典编纂引擎。依据句子语境解释目标词，输出严格 JSON，禁止任何 JSON 之外的文字。"
)

VOCAB_SCHEMA_HINT = """{
  "word": "significantly",
  "phonetic": "/sɪɡˈnɪfɪkəntli/",
  "partOfSpeech": "adverb",
  "meaningZh": "显著地；明显地",
  "meaningEn": "to a large or important degree",
  "cefr": "B2",
  "synonyms": ["considerably", "substantially"],
  "examples": ["Technology has significantly changed our lives."]
}"""


async def explain_vocabulary(model_id: str, word: str, sentence: str = "") -> dict:
    context = f"\n【出现的句子】\n{sentence}" if sentence else ""
    prompt = f"解释英文单词 “{word}” 在语境中的含义，严格按 schema 输出 JSON：\n{VOCAB_SCHEMA_HINT}\n{context}"
    data = await chat_json(model_id, system=VOCAB_SYSTEM, user=prompt)
    data.setdefault("word", word)
    for key, default in (("phonetic", ""), ("partOfSpeech", ""), ("meaningZh", ""), ("meaningEn", ""), ("cefr", ""), ):
        data.setdefault(key, default)
    data.setdefault("synonyms", [])
    data.setdefault("examples", [])
    return data


# ---------------------------------------------------------------- 写作批改

WRITING_SYSTEM = (
    "你是英语写作批改引擎。输出严格 JSON，禁止任何 JSON 之外的文字。"
    "issue 的 original 必须是原文的连续精确子串（逐字符一致，含原始大小写与标点），否则无法定位。"
    "评分必须逐档对号，禁止凭整体印象给分。"
)

WRITING_SCHEMA_HINT = """{
  "score": {"overall": 82, "grammar": 91, "vocabulary": 76, "coherence": 81, "expression": 79},
  "scoreEvidence": {"grammar": "第二段 'He go' 等共2处主谓不一致", "vocabulary": "重复使用 important 4 次",
                    "coherence": "第三段缺少过渡句导致话题跳跃", "expression": "'more and more' 偏口语"},
  "issues": [{"type": "grammar|vocabulary|expression|style", "original": "He go", "suggestion": "He went",
              "reasonZh": "yesterday 表示过去时间，动词应用过去式", "grammarPoint": "Simple Past Tense"}],
  "improvedText": "完整改写后的文章"
}"""

WRITING_RUBRIC = """评分分档锚定（必须逐档对号，scoreEvidence 引用原文具体片段作依据）：
- grammar：90+ 全文无语法错误；80-89 偶发轻微错误；70-79 有明显时态/主谓/冠词错误；60-69 错误密集；<60 严重妨碍理解
- vocabulary：90+ 精准且多样；80-89 偶有重复；70-79 基础但正确；60-69 贫乏或误用；<60 大量误用
- coherence：90+ 衔接自然逻辑清晰；80-89 偶有跳跃；70-79 段落松散；<70 结构混乱
- expression：90+ 地道自然；80-89 基本自然；70-79 生硬；<70 中式直译感强
注意：overall 由系统按维度加权重算，你给出的 overall 仅作参考。"""


async def analyze_writing(model_id: str, text: str, mode: str = "standard") -> dict:
    mode_rules = {
        "light": "Light：仅纠正明确语法错误，最大程度保留用户原始表达，不做风格升级。",
        "standard": "Standard：纠正全部语法错误，并将不自然表达优化为自然表达。",
        "advanced": "Advanced：接近母语者/Academic Writing 水准全面重写，升级词汇与句式多样性。",
    }
    rule = mode_rules.get(mode, mode_rules["standard"])
    prompt = (
        f"按修改强度批改下面这篇英语作文。强度定义：{rule}\n"
        f"严格按 schema 输出 JSON：\n{WRITING_SCHEMA_HINT}\n{WRITING_RUBRIC}\n"
        "要求：issues 覆盖语法(grammar)/词汇(vocabulary)/表达(expression)/风格(style)四类问题，"
        "original 必须逐字符取自原文；improvedText 为整篇改写。\n"
        f"【作文】\n{text[:WRITING_MAX_CHARS]}"
    )
    # 评分类调用温度降到 0.1：同稿重复批改的波动主要来自温度
    data = await chat_json(model_id, system=WRITING_SYSTEM, user=prompt, temperature=0.1, max_tokens=6000)
    score = data.get("score") or {}
    for key in ("overall", "grammar", "vocabulary", "coherence", "expression"):
        score.setdefault(key, 0)
    data["score"] = score
    issues = []
    for issue in data.get("issues") or []:
        original = str(issue.get("original") or "")
        start = text.find(original) if original else -1
        if not original or start < 0:
            continue  # 定位不到原文的问题丢弃，避免前端错位标记
        issues.append(
            {
                "type": issue.get("type") if issue.get("type") in ("grammar", "vocabulary", "expression", "style") else "expression",
                "start": start,
                "end": start + len(original),
                "original": original,
                "suggestion": str(issue.get("suggestion") or ""),
                "reasonZh": str(issue.get("reasonZh") or ""),
                "grammarPoint": str(issue.get("grammarPoint") or ""),
            }
        )
    data["issues"] = issues
    data["improvedText"] = ""  # 批改阶段不强制生成改写，交由用户点击“多维优化作文”按需生成
    data["mode"] = mode
    # 混合评分：错误密度/词汇多样性等代码实测证据与模型判断融合，overall 一律重算
    fused = fuse_writing(data["score"], writing_metrics(text, issues), data.get("scoreEvidence"))
    data["score"], data["evidence"], data["scoreBasis"] = fused["score"], fused["evidence"], fused["scoreBasis"]
    return data


# ---------------------------------------------------------------- 写作多维优化
OPTIMIZE_SYSTEM = (
    "你是英语资深写作导师与母语润色专家。输出严格 JSON，禁止任何 JSON 之外的文字。"
    "你的任务是对学生的英文作文进行多维度深度重写与精修，严格遵循两阶段重写原则。"
)

OPTIMIZE_SCHEMA_HINT = """{
  "improvedText": "结合所有建议并经过多维度升华后的完整英文作文"
}"""


async def optimize_writing(
    model_id: str,
    text: str,
    mode: str = "standard",
    issues: list[dict] | None = None,
) -> dict:
    mode_rules = {
        "light": "Light：仅纠正明确语法错误，最大程度保留用户原始表达，不做过度风格升级。",
        "standard": "Standard：纠正全部语法错误，并将不自然表达优化为自然地道的书面语。",
        "advanced": "Advanced：达到母语者/Academic Writing 高水准全面重写，大幅升级学术词汇与句式多样性。",
    }
    rule = mode_rules.get(mode, mode_rules["standard"])

    issues_text_lines = []
    if issues:
        for idx, item in enumerate(issues, start=1):
            orig = item.get("original", "")
            sug = item.get("suggestion", "")
            reason = item.get("reasonZh", "")
            issues_text_lines.append(f"{idx}. [{item.get('type', 'issue').upper()}] 原文: \"{orig}\" -> 建议修改: \"{sug}\" (理由: {reason})")
    issues_summary = "\n".join(issues_text_lines) if issues_text_lines else "（无额外逐项标记，请直接进行多维优化）"

    prompt = (
        f"请对以下学生英文作文进行【两阶段多维度优化重写】。\n"
        f"【修改强度目标】：{rule}\n\n"
        f"【第一阶段：基底采纳】\n"
        f"必须彻底吸纳并修复以下第一步生成的 ISSUES 诊断建议：\n{issues_summary}\n\n"
        f"【第二阶段：多维全局升华】\n"
        f"在解决上述问题的基础上，对整篇文章进行全局多维度优化升级：\n"
        f"1. Coherence（连贯性）：优化段落过渡与衔接逻辑，添加恰当的逻辑连接词；\n"
        f"2. Lexical Sophistication（词汇升级）：消除基础词重复，采用更地道、精准的高级书面词汇；\n"
        f"3. Syntactic Diversity（句式多样性）：结合分词短语、从句与复合句式，避免句型单调；\n"
        f"4. Fluency & Tone（母语语感）：消除中式直译与生硬语法，使行文地道流畅。\n\n"
        f"严格按 JSON schema 输出：\n{OPTIMIZE_SCHEMA_HINT}\n\n"
        f"【学生原始作文】\n{text[:WRITING_MAX_CHARS]}"
    )

    data = await chat_json(model_id, system=OPTIMIZE_SYSTEM, user=prompt, temperature=0.2, max_tokens=6000)
    improved_text = str(data.get("improvedText") or "").strip()
    if not improved_text:
        # 后备处理：若模型未按字段返回，尝试读取原始文本或做保底
        improved_text = text
    return {
        "improvedText": improved_text,
        "mode": mode,
    }


# ---------------------------------------------------------------- 口语评测

SPEAKING_SCHEMA_HINT = """{
  "transcript": "学生所说英文的逐字转写",
  "scores": {"overall": 82, "pronunciation": 86, "fluency": 74, "accuracy": 91, "intonation": 77},
  "scoreEvidence": {"pronunciation": "technology 的 /n/ 鼻音偏弱", "fluency": "第2句后出现长达2秒的停顿",
                    "accuracy": "时态混用 went/go", "intonation": "疑问句未升调"},
  "words": [{"word": "communicate", "status": "correct|minor|wrong", "problemsZh": ["/k/ 音不够清晰", "主重音偏弱"]}],
  "feedbackZh": "整体口语表现点评（120字内）",
  "suggestionsZh": ["针对性练习建议1", "针对性练习建议2"]
}"""

SPEAKING_RUBRIC = """评分分档锚定（必须逐档对号，scoreEvidence 写明具体现象）：
- pronunciation：90+ 清晰准确；80-89 少量偏差；70-79 多处音素偏差；<70 严重口音妨碍理解
- fluency：90+ 语流顺畅节奏自然；80-89 偶有停顿；70-79 频繁停顿/重复；<70 断续难连贯
- accuracy：跟读模式以与参考文本的偏离为准；自由模式看语法与用词错误密度
- intonation：90+ 语调起伏自然贴切；80-89 略平；<70 机械无重音
注意：overall 由系统按维度加权重算，你给出的 overall 仅作参考。"""


async def analyze_speaking(
    model_id: str,
    *,
    audio_base64: str,
    audio_format: str = "wav",
    mode: str = "read_aloud",
    reference_text: str = "",
    topic: str = "",
    duration_sec: float = 0.0,
) -> dict:
    if mode == "read_aloud":
        task_desc = f"训练模式：Read Aloud 跟读。参考文本：\n{reference_text[:2000]}"
    else:
        task_desc = f"训练模式：Free Speaking 自由表达。题目：{topic or 'Free talk about your day'}"
    try:
        wav_bytes = base64.b64decode(audio_base64) if audio_base64 else None
    except Exception:
        wav_bytes = None  # 解码失败不阻断评测：时长回落客户端上报值
    prompt = (
        "你是口语评测引擎。听这段学生英语录音，严格按 schema 输出 JSON（禁止任何 JSON 之外的文字）：\n"
        f"{SPEAKING_SCHEMA_HINT}\n{SPEAKING_RUBRIC}\n{task_desc}\n"
        "要求：words 覆盖转写文本中的实词（跳过 a/the/of 等功能词），跟读模式下 status 表示与参考文本及标准发音的偏离；"
        "发音/语调问题需具体到音素或重音；scores 各项 0~100 整数；transcript 为逐字转写（含 uh/um 等填充词）。\n"
        "语速与停顿由系统从音频实测，你的 fluency 分数侧重节奏与连贯性。"
    )
    # 评分类调用温度降到 0.1：同一段录音重复评测的波动主要来自温度
    data = await omni_json(
        model_id,
        prompt=prompt,
        audio_base64=audio_base64,
        audio_format=audio_format,
        temperature=0.1,
    )
    data.setdefault("transcript", "")
    scores = data.get("scores") or {}
    for key in ("overall", "pronunciation", "fluency", "accuracy", "intonation"):
        scores.setdefault(key, 0)
    data["scores"] = scores
    data.setdefault("words", [])
    data.setdefault("feedbackZh", "")
    data.setdefault("suggestionsZh", [])
    data["mode"] = mode
    # 混合评分：语速/停顿/参考文本匹配率等代码实测证据与模型判断融合，overall 一律重算；
    # 时长以服务端 WAV 实测为准（不信任客户端上报），供学习时长统计使用
    metrics = speaking_metrics(
        wav_bytes=wav_bytes,
        transcript=data["transcript"],
        reference_text=reference_text if mode == "read_aloud" else "",
        client_duration_sec=duration_sec,
    )
    fused = fuse_speaking(data["scores"], metrics, mode, data.get("scoreEvidence"))
    data["scores"], data["evidence"], data["scoreBasis"] = fused["score"], fused["evidence"], fused["scoreBasis"]
    data["durationSec"] = metrics["durationSec"]
    return data


# ---------------------------------------------------------------- 学习建议

INSIGHTS_SYSTEM = (
    "你是外语学习画像引擎。基于聚合后的学习数据输出个性化建议，严格 JSON，禁止任何 JSON 之外的文字。"
)

INSIGHTS_SCHEMA_HINT = """{
  "summaryZh": "本周学习画像一句话总结（60字内）",
  "weaknesses": ["薄弱点1", "薄弱点2", "薄弱点3"],
  "plan": ["具体可执行的训练建议1", "训练建议2", "训练建议3"]
}"""


async def build_learning_advice(model_id: str, profile: dict) -> dict:
    prompt = (
        "基于以下学习画像数据生成个性化训练建议，严格按 schema 输出 JSON：\n"
        f"{INSIGHTS_SCHEMA_HINT}\n【学习画像】\n"
        f"{json.dumps(profile, ensure_ascii=False, default=str)[:6000]}"
    )
    data = await chat_json(model_id, system=INSIGHTS_SYSTEM, user=prompt, temperature=0.4)
    data.setdefault("summaryZh", "")
    data.setdefault("weaknesses", [])
    data.setdefault("plan", [])
    return data
