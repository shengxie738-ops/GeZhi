"""外语训练工作台 API。

路由前缀由 api.py 以 "" 挂载，实际路径形如 /api/language/...。
所有端点需 Bearer 认证；文本任务强制文本模型，口语任务强制全模态 omni 模型。
"""

from datetime import datetime
from io import BytesIO
from typing import Optional

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.repositories.json_store import JsonStore
from app.services.default_agents import get_default_agents
from app.services.language_service import (
    FOREIGN_AGENT_ID,
    SPEAKING_AGENT_ID,
    analyze_reading,
    analyze_speaking,
    analyze_writing,
    optimize_writing,
    build_learning_advice,
    explain_vocabulary,
)
from app.services.model_registry import has_model

router = APIRouter()

LANGUAGE_MODULE = "language"
SESSION_TYPE = "session"
WORD_TYPE = "word"
WRITING_HISTORY_TYPE = "writing_history"
ARTICLE_READ_TYPE = "article_read"
USER_ARTICLE_TYPE = "user_article"
CATEGORY_LABEL = {"text": "文本", "omni": "全模态"}


def require_user(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="not authenticated")
    token_payload = decode_access_token(authorization.split(" ", 1)[1])
    username = token_payload.get("sub") if token_payload else None
    if not username:
        raise HTTPException(status_code=401, detail="invalid token")
    return username


def resolve_language_model(
    db: Session,
    agent_id: str,
    requested_model: Optional[str],
    *,
    category: str,
) -> str:
    """文本端点只接受 text 模型，口语端点只接受 omni 模型（先校验用户请求，再读智能体配置）。"""
    if requested_model:
        if has_model(requested_model, category=category):
            return requested_model
        raise HTTPException(
            status_code=400,
            detail=f"模型 {requested_model} 不是{CATEGORY_LABEL.get(category, category)}模型，无法用于该功能",
        )
    store = JsonStore(db)
    saved = store.get_payload("agents", "config", agent_id, owner_id="system")
    if saved and has_model(saved.get("model"), category=category):
        return saved["model"]
    default = next((agent for agent in get_default_agents() if agent["id"] == agent_id), None)
    if default and has_model(default.get("model"), category=category):
        return default["model"]
    raise HTTPException(status_code=400, detail=f"智能体 {agent_id} 未配置可用的{CATEGORY_LABEL.get(category, category)}模型")


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _save_session(store: JsonStore, username: str, payload: dict) -> dict:
    payload = {**payload, "createdAt": payload.get("createdAt") or _now_iso()}
    record_key = f"lang-{int(datetime.now().timestamp() * 1000)}-{username}"
    return store.create(LANGUAGE_MODULE, SESSION_TYPE, {**payload, "id": record_key}, prefix="lang", owner_id=username)


# ---------------------------------------------------------------- 请求模型

class ReadingAnalyzeRequest(BaseModel):
    text: str = Field(min_length=20, max_length=12000)
    language: str = "en"
    model: Optional[str] = None


class VocabularyExplainRequest(BaseModel):
    word: str = Field(min_length=1, max_length=80)
    sentence: str = ""
    model: Optional[str] = None


class WordbookAddRequest(BaseModel):
    word: str = Field(min_length=1, max_length=80)
    phonetic: str = ""
    meaningZh: str = ""
    meaningEn: str = ""
    cefr: str = ""
    partOfSpeech: str = ""
    examples: list[str] = []
    sentence: str = ""


class WordbookPatchRequest(BaseModel):
    proficiency: int = Field(ge=0, le=3)


class WritingAnalyzeRequest(BaseModel):
    text: str = Field(min_length=5, max_length=8000)
    mode: str = "standard"
    durationSec: float = Field(default=0.0, ge=0, le=7200)  # 前端追踪的真实写作耗时，供学习时长统计
    model: Optional[str] = None


class WritingOptimizeRequest(BaseModel):
    text: str = Field(min_length=5, max_length=8000)
    mode: str = "standard"
    issues: list[dict] = []
    historyId: Optional[str] = None
    model: Optional[str] = None


class SpeakingAnalyzeRequest(BaseModel):
    audioBase64: str = Field(min_length=100)
    audioFormat: str = "wav"
    mode: str = "read_aloud"
    referenceText: str = ""
    topic: str = ""
    durationSec: float = 0.0
    model: Optional[str] = None


class ProgressRequest(BaseModel):
    type: str = Field(pattern="^(reading|vocab)$")
    durationSec: float = 0.0
    title: str = ""
    correct: Optional[int] = None
    total: Optional[int] = None
    wordCount: Optional[int] = None
    level: str = ""
    reviewed: Optional[int] = None


class ReadingMarkRequest(BaseModel):
    articleId: str = Field(min_length=1, max_length=100)


class UserArticleRenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=100)


# ---------------------------------------------------------------- 阅读理解

@router.post("/language/reading/analyze")
async def reading_analyze(
    request: ReadingAnalyzeRequest,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    username = require_user(authorization)
    model_id = resolve_language_model(db, FOREIGN_AGENT_ID, request.model, category="text")
    try:
        data = await analyze_reading(model_id, request.text, request.language)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=f"阅读分析失败：{exc}")
    except Exception as exc:  # noqa: BLE001 - 上游模型/网络错误统一转为可读提示
        raise HTTPException(status_code=502, detail=f"阅读分析服务暂不可用：{exc}")
    return {"status": "success", "data": {**data, "model": model_id}}


# ---------------------------------------------------------------- 词汇

@router.post("/language/vocabulary/explain")
async def vocabulary_explain(
    request: VocabularyExplainRequest,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    require_user(authorization)
    model_id = resolve_language_model(db, FOREIGN_AGENT_ID, request.model, category="text")
    try:
        data = await explain_vocabulary(model_id, request.word.strip(), request.sentence)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=f"词汇解释失败：{exc}")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"词汇解释服务暂不可用：{exc}")
    return {"status": "success", "data": {**data, "model": model_id}}


@router.get("/language/wordbook")
async def list_wordbook(authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    username = require_user(authorization)
    store = JsonStore(db)
    words = store.list_payloads(LANGUAGE_MODULE, record_type=WORD_TYPE, owner_id=username)
    return {"status": "success", "data": words}


@router.post("/language/wordbook")
async def add_word(request: WordbookAddRequest, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    username = require_user(authorization)
    store = JsonStore(db)
    word = request.word.strip()
    record_key = word.lower()
    existing = store.get_payload(LANGUAGE_MODULE, WORD_TYPE, record_key, owner_id=username)
    if existing:
        return {"status": "success", "data": existing}
    payload = {
        "id": record_key,
        "word": word,
        "phonetic": request.phonetic,
        "meaningZh": request.meaningZh,
        "meaningEn": request.meaningEn,
        "cefr": request.cefr,
        "partOfSpeech": request.partOfSpeech,
        "examples": request.examples or [],
        "sourceSentence": request.sentence,
        "proficiency": 0,
        "reviewCount": 0,
        "createdAt": _now_iso(),
        "lastReviewedAt": "",
    }
    saved = store.upsert(LANGUAGE_MODULE, WORD_TYPE, record_key, payload, owner_id=username)
    return {"status": "success", "data": saved}


@router.patch("/language/wordbook/{word}")
async def update_word(word: str, request: WordbookPatchRequest, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    username = require_user(authorization)
    store = JsonStore(db)
    existing = store.get_payload(LANGUAGE_MODULE, WORD_TYPE, word.lower(), owner_id=username)
    if existing is None:
        raise HTTPException(status_code=404, detail="生词不存在")
    patch = {
        "proficiency": request.proficiency,
        "reviewCount": int(existing.get("reviewCount") or 0) + 1,
        "lastReviewedAt": _now_iso(),
    }
    updated = store.patch(LANGUAGE_MODULE, WORD_TYPE, word.lower(), patch, owner_id=username)
    if updated is None:
        raise HTTPException(status_code=404, detail="生词不存在")
    return {"status": "success", "data": updated}


@router.delete("/language/wordbook/{word}")
async def delete_word(word: str, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    username = require_user(authorization)
    store = JsonStore(db)
    deleted = store.delete(LANGUAGE_MODULE, WORD_TYPE, word.lower())
    if not deleted:
        raise HTTPException(status_code=404, detail="生词不存在")
    return {"status": "success", "data": {"deleted": word}}


# ---------------------------------------------------------------- 写作训练

@router.post("/language/writing/analyze")
async def writing_analyze(
    request: WritingAnalyzeRequest,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    username = require_user(authorization)
    model_id = resolve_language_model(db, FOREIGN_AGENT_ID, request.model, category="text")
    try:
        data = await analyze_writing(model_id, request.text, request.mode)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=f"写作批改失败：{exc}")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"写作批改服务暂不可用：{exc}")
    store = JsonStore(db)
    _save_session(
        store,
        username,
        {
            "type": "writing",
            "mode": data.get("mode", request.mode),
            "durationSec": request.durationSec,
            "score": data.get("score", {}),
            "evidence": data.get("evidence", {}),
            "issues": data.get("issues", []),
            "textPreview": request.text[:120],
        },
    )
    # 完整写作历史独立存储（原文全文 + AI 改写全文），与学习 session 分离：删除历史不影响画像统计
    history_key = f"lang-{int(datetime.now().timestamp() * 1000)}-{username}"
    store.create(
        LANGUAGE_MODULE,
        WRITING_HISTORY_TYPE,
        {
            "id": history_key,
            "type": "writing",
            "mode": data.get("mode", request.mode),
            "model": model_id,
            "score": data.get("score", {}),
            "evidence": data.get("evidence", {}),
            "scoreBasis": data.get("scoreBasis", {}),
            "issues": data.get("issues", []),
            "text": request.text,
            "improvedText": data.get("improvedText", ""),
            "durationSec": request.durationSec,
            "wordCount": len(request.text.split()),
            "preview": request.text[:120],
            "createdAt": _now_iso(),
        },
        prefix="lang",
        owner_id=username,
    )
    return {"status": "success", "data": {**data, "historyId": history_key, "model": model_id}}


@router.post("/language/writing/optimize")
async def writing_optimize(
    request: WritingOptimizeRequest,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    username = require_user(authorization)
    model_id = resolve_language_model(db, FOREIGN_AGENT_ID, request.model, category="text")
    try:
        data = await optimize_writing(model_id, request.text, request.mode, request.issues)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=f"多维优化失败：{exc}")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"多维优化服务暂不可用：{exc}")

    store = JsonStore(db)
    improved_text = data.get("improvedText", "")
    target_history_id = request.historyId

    if target_history_id:
        existing = store.get_payload(LANGUAGE_MODULE, WRITING_HISTORY_TYPE, target_history_id, owner_id=username)
        if existing:
            store.patch(LANGUAGE_MODULE, WRITING_HISTORY_TYPE, target_history_id, {"improvedText": improved_text}, owner_id=username)
    else:
        recent_records = store.list_payloads(LANGUAGE_MODULE, record_type=WRITING_HISTORY_TYPE, owner_id=username)
        if recent_records:
            target_history_id = recent_records[0].get("id")
            store.patch(LANGUAGE_MODULE, WRITING_HISTORY_TYPE, target_history_id, {"improvedText": improved_text}, owner_id=username)

    return {
        "status": "success",
        "data": {
            "improvedText": improved_text,
            "historyId": target_history_id,
            "mode": data.get("mode", request.mode),
            "model": model_id,
        },
    }


# ---------------------------------------------------------------- 写作历史

@router.get("/language/writing/history")
async def writing_history_list(authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    """写作历史摘要列表（新→旧），详情按需单独拉取，避免列表携带全文。"""
    username = require_user(authorization)
    store = JsonStore(db)
    records = store.list_payloads(LANGUAGE_MODULE, record_type=WRITING_HISTORY_TYPE, owner_id=username)
    entries = [
        {
            "id": record.get("id"),
            "createdAt": record.get("createdAt", ""),
            "mode": record.get("mode", "standard"),
            "score": record.get("score", {}),
            "wordCount": record.get("wordCount", 0),
            "preview": record.get("preview", ""),
            "issueCount": len(record.get("issues") or []),
        }
        for record in records
    ]
    return {"status": "success", "data": {"entries": entries}}


@router.get("/language/writing/history/{record_id}")
async def writing_history_detail(record_id: str, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    username = require_user(authorization)
    store = JsonStore(db)
    record = store.get_payload(LANGUAGE_MODULE, WRITING_HISTORY_TYPE, record_id, owner_id=username)
    if record is None:
        raise HTTPException(status_code=404, detail="历史记录不存在")
    return {"status": "success", "data": record}


@router.delete("/language/writing/history/{record_id}")
async def writing_history_delete(record_id: str, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    username = require_user(authorization)
    store = JsonStore(db)
    record = store.get_payload(LANGUAGE_MODULE, WRITING_HISTORY_TYPE, record_id, owner_id=username)
    if record is None:
        raise HTTPException(status_code=404, detail="历史记录不存在")
    store.delete(LANGUAGE_MODULE, WRITING_HISTORY_TYPE, record_id)
    return {"status": "success", "data": {"deleted": record_id}}


# ---------------------------------------------------------------- 已读标记

@router.get("/language/reading/progress")
async def reading_progress(authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    """当前用户已标记为「已读」的文章 id 列表。"""
    username = require_user(authorization)
    store = JsonStore(db)
    records = store.list_payloads(LANGUAGE_MODULE, record_type=ARTICLE_READ_TYPE, owner_id=username)
    return {"status": "success", "data": {"readArticleIds": [record.get("articleId") or record.get("id") for record in records]}}


@router.post("/language/reading/progress")
async def mark_article_read(request: ReadingMarkRequest, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    username = require_user(authorization)
    store = JsonStore(db)
    article_id = request.articleId.strip()
    existing = store.get_payload(LANGUAGE_MODULE, ARTICLE_READ_TYPE, article_id, owner_id=username)
    if existing:
        return {"status": "success", "data": existing}
    payload = {"id": article_id, "articleId": article_id, "createdAt": _now_iso()}
    saved = store.upsert(LANGUAGE_MODULE, ARTICLE_READ_TYPE, article_id, payload, owner_id=username)
    return {"status": "success", "data": saved}


@router.delete("/language/reading/progress/{article_id}")
async def unmark_article_read(article_id: str, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    username = require_user(authorization)
    store = JsonStore(db)
    record = store.get_payload(LANGUAGE_MODULE, ARTICLE_READ_TYPE, article_id, owner_id=username)
    if record is None:
        raise HTTPException(status_code=404, detail="该文章未标记已读")
    store.delete(LANGUAGE_MODULE, ARTICLE_READ_TYPE, article_id)
    return {"status": "success", "data": {"deleted": article_id}}


# ---------------------------------------------------------------- 用户导入文章

@router.get("/language/reading/user-articles")
async def list_user_articles(authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    """用户自行导入的 Word 文章列表（含全文，按导入时间新→旧）。"""
    username = require_user(authorization)
    store = JsonStore(db)
    records = store.list_payloads(LANGUAGE_MODULE, record_type=USER_ARTICLE_TYPE, owner_id=username)
    return {"status": "success", "data": records}


@router.post("/language/reading/user-articles")
async def import_user_article(
    file: UploadFile = File(...),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """导入 .docx Word 文档，解析出文章文本后入库（不落盘文件）。"""
    username = require_user(authorization)
    filename = (file.filename or "").strip()
    if not filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="仅支持 .docx 格式的 Word 文档")
    try:
        content = await file.read()
    except Exception:
        raise HTTPException(status_code=400, detail="读取文件失败，请重试")
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文档过大（上限 10MB）")
    try:
        from docx import Document

        doc = Document(BytesIO(content))
        text = "\n".join(paragraph.text for paragraph in doc.paragraphs).strip()
    except Exception:
        raise HTTPException(status_code=400, detail="无法解析该 Word 文档，请确认文件未损坏")
    if len(text) < 60:
        raise HTTPException(status_code=400, detail="文档中的英文文章太短（至少 60 个字符）")
    text = text[:12000]
    title = (filename.rsplit(".", 1)[0] or "未命名文章")[:100]
    store = JsonStore(db)
    payload = {
        "type": "user_article",
        "title": title,
        "text": text,
        "wordCount": len(text.split()),
        "preview": text[:120],
        "createdAt": _now_iso(),
    }
    saved = store.create(LANGUAGE_MODULE, USER_ARTICLE_TYPE, payload, prefix="ua", owner_id=username)
    return {"status": "success", "data": saved}


@router.patch("/language/reading/user-articles/{record_id}")
async def rename_user_article(record_id: str, request: UserArticleRenameRequest, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    """重命名用户导入的文章。"""
    username = require_user(authorization)
    title = request.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="标题不能为空")
    store = JsonStore(db)
    updated = store.patch(LANGUAGE_MODULE, USER_ARTICLE_TYPE, record_id, {"title": title}, owner_id=username)
    if updated is None:
        raise HTTPException(status_code=404, detail="文章不存在")
    return {"status": "success", "data": updated}


@router.delete("/language/reading/user-articles/{record_id}")
async def delete_user_article(record_id: str, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    username = require_user(authorization)
    store = JsonStore(db)
    record = store.get_payload(LANGUAGE_MODULE, USER_ARTICLE_TYPE, record_id, owner_id=username)
    if record is None:
        raise HTTPException(status_code=404, detail="文章不存在")
    store.delete(LANGUAGE_MODULE, USER_ARTICLE_TYPE, record_id)
    return {"status": "success", "data": {"deleted": record_id}}


# ---------------------------------------------------------------- 口语训练

@router.post("/language/speaking/analyze")
async def speaking_analyze(
    request: SpeakingAnalyzeRequest,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    username = require_user(authorization)
    model_id = resolve_language_model(db, SPEAKING_AGENT_ID, request.model, category="omni")
    try:
        data = await analyze_speaking(
            model_id,
            audio_base64=request.audioBase64,
            audio_format=request.audioFormat,
            mode="free" if request.mode == "free" else "read_aloud",
            reference_text=request.referenceText,
            topic=request.topic,
            duration_sec=request.durationSec,
        )
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=f"口语评测失败：{exc}")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"口语评测服务暂不可用：{exc}")
    store = JsonStore(db)
    _save_session(
        store,
        username,
        {
            "type": "speaking",
            "mode": data.get("mode", request.mode),
            # 服务端从 WAV 实测的时长优先（不信任客户端上报），无音频解析结果时回落客户端值
            "durationSec": data.get("durationSec") or request.durationSec,
            "scores": data.get("scores", {}),
            "evidence": data.get("evidence", {}),
            "transcript": data.get("transcript", ""),
            "words": [
                word for word in data.get("words", []) if word.get("status") in ("minor", "wrong")
            ],
            "topic": request.topic,
        },
    )
    return {"status": "success", "data": {**data, "model": model_id}}


# ---------------------------------------------------------------- 学习记录

@router.post("/language/progress")
async def record_progress(request: ProgressRequest, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    username = require_user(authorization)
    store = JsonStore(db)
    payload = {"type": request.type, "durationSec": request.durationSec, "title": request.title}
    if request.type == "reading":
        payload.update(
            {
                "correct": request.correct if request.correct is not None else 0,
                "total": request.total if request.total is not None else 0,
                "wordCount": request.wordCount or 0,
                "level": request.level,
            }
        )
    else:
        payload["reviewed"] = request.reviewed or 0
    saved = _save_session(store, username, payload)
    return {"status": "success", "data": saved}


def _session_date(payload: dict) -> str:
    return str(payload.get("createdAt") or "")[:10]


def _build_overview(sessions: list[dict], words: list[dict]) -> dict:
    from datetime import timedelta

    today = datetime.now().strftime("%Y-%m-%d")
    today_sessions = [s for s in sessions if _session_date(s) == today]
    week_start = (datetime.now() - timedelta(days=datetime.now().weekday())).strftime("%Y-%m-%d")
    week_minutes = round(sum(float(s.get("durationSec") or 0) for s in sessions if _session_date(s) >= week_start) / 60)
    active_dates = { _session_date(s) for s in sessions if _session_date(s) }
    streak = 0
    cursor = datetime.now()
    if today not in active_dates:
        cursor = cursor - timedelta(days=1)
    while cursor.strftime("%Y-%m-%d") in active_dates:
        streak += 1
        cursor = cursor - timedelta(days=1)
    return {
        "today": {
            "learningMinutes": round(sum(float(s.get("durationSec") or 0) for s in today_sessions) / 60),
            "exercises": len([s for s in today_sessions if s.get("type") in ("reading", "writing", "speaking")]),
            "wordsLearned": len([w for w in words if str(w.get("createdAt") or "")[:10] == today]),
            "reviewed": sum(int(s.get("reviewed") or 0) for s in today_sessions if s.get("type") == "vocab"),
        },
        "week": {"minutes": week_minutes, "goalMinutes": 120},
        "streak": streak,
        "totals": {
            "words": len(words),
            "mastered": len([w for w in words if int(w.get("proficiency") or 0) >= 3]),
            "sessions": len(sessions),
        },
    }


@router.get("/language/overview")
async def language_overview(authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    username = require_user(authorization)
    store = JsonStore(db)
    sessions = store.list_payloads(LANGUAGE_MODULE, record_type=SESSION_TYPE, owner_id=username)
    words = store.list_payloads(LANGUAGE_MODULE, record_type=WORD_TYPE, owner_id=username)
    return {"status": "success", "data": _build_overview(sessions, words)}


def _aggregate_errors(sessions: list[dict]) -> list[dict]:
    counter: dict[str, int] = {}
    for session in sessions:
        if session.get("type") == "writing":
            for issue in session.get("issues") or []:
                key = issue.get("grammarPoint") or {
                    "grammar": "Grammar", "vocabulary": "Vocabulary", "expression": "Expression", "style": "Style"
                }.get(issue.get("type"), "Expression")
                counter[key] = counter.get(key, 0) + 1
        elif session.get("type") == "speaking":
            for word in session.get("words") or []:
                for problem in word.get("problemsZh") or []:
                    counter[problem[:30]] = counter.get(problem[:30], 0) + 1
    ranked = sorted(counter.items(), key=lambda item: item[1], reverse=True)
    return [{"name": name, "count": count} for name, count in ranked[:10]]


@router.get("/language/insights")
async def language_insights(authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    username = require_user(authorization)
    store = JsonStore(db)
    sessions = list(reversed(store.list_payloads(LANGUAGE_MODULE, record_type=SESSION_TYPE, owner_id=username)))
    words = store.list_payloads(LANGUAGE_MODULE, record_type=WORD_TYPE, owner_id=username)

    writing_trend = [
        {"date": _session_date(s), "overall": (s.get("score") or {}).get("overall") or 0}
        for s in sessions if s.get("type") == "writing"
    ]
    speaking_trend = [
        {"date": _session_date(s), "overall": (s.get("scores") or {}).get("overall") or 0}
        for s in sessions if s.get("type") == "speaking"
    ]
    reading_trend = [
        {
            "date": _session_date(s),
            "correct": s.get("correct") or 0,
            "total": s.get("total") or 0,
            "rate": round((s.get("correct") or 0) / (s.get("total") or 1) * 100),
        }
        for s in sessions if s.get("type") == "reading"
    ]
    cefr_counts: dict[str, int] = {}
    for word in words:
        cefr = str(word.get("cefr") or "").upper()
        if cefr:
            cefr_counts[cefr] = cefr_counts.get(cefr, 0) + 1

    overview = _build_overview(list(reversed(sessions)), words)
    errors = _aggregate_errors(list(reversed(sessions)))
    return {
        "status": "success",
        "data": {
            "overview": overview,
            "highFrequencyErrors": errors,
            "writingTrend": writing_trend[-12:],
            "speakingTrend": speaking_trend[-12:],
            "readingTrend": reading_trend[-12:],
            "vocabularyCefr": cefr_counts,
            "totals": overview["totals"],
            "hasSessions": bool(sessions),
        },
    }


@router.get("/language/insights/advice")
async def language_insights_advice(authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    """LLM 学习建议单独成端点：聚合画像秒回，建议异步补充，避免整页等待。"""
    username = require_user(authorization)
    store = JsonStore(db)
    sessions = list(reversed(store.list_payloads(LANGUAGE_MODULE, record_type=SESSION_TYPE, owner_id=username)))
    words = store.list_payloads(LANGUAGE_MODULE, record_type=WORD_TYPE, owner_id=username)
    if not sessions:
        return {"status": "success", "data": {"summaryZh": "", "weaknesses": [], "plan": []}}

    reversed_sessions = list(reversed(sessions))
    writing_trend = [
        {"date": _session_date(s), "overall": (s.get("score") or {}).get("overall") or 0}
        for s in sessions if s.get("type") == "writing"
    ]
    speaking_trend = [
        {"date": _session_date(s), "overall": (s.get("scores") or {}).get("overall") or 0}
        for s in sessions if s.get("type") == "speaking"
    ]
    profile = {
        "overview": _build_overview(reversed_sessions, words),
        "highFrequencyErrors": _aggregate_errors(reversed_sessions),
        "writingTrend": writing_trend[-12:],
        "speakingTrend": speaking_trend[-12:],
        "readingTrend": [],
        "vocabularyCefr": {},
        "writingSamples": [
            {"date": _session_date(s), "issues": (s.get("issues") or [])[:5]} for s in sessions if s.get("type") == "writing"
        ][:6],
    }
    model_id = resolve_language_model(db, FOREIGN_AGENT_ID, None, category="text")
    try:
        advice = await build_learning_advice(model_id, profile)
    except Exception as exc:  # noqa: BLE001 - 建议生成失败返回空建议而非报错
        advice = {"summaryZh": "", "weaknesses": [], "plan": [], "error": str(exc)}
    return {"status": "success", "data": advice}
