import json
import re
from datetime import datetime, timezone, timedelta
from math import isfinite
from statistics import mean
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.deps import ensure_self_or_teacher, get_auth_payload, require_teacher, teacher_student_ids
from app.core.database import get_db
from app.core.miniprogram_response import api_response, is_miniprogram_client, page_items
from app.core.responses import ok
from app.core.username_policy import is_valid_student_username
from app.models.student_profile import StudentProfile
from app.models.user_account import UserAccount
from app.models.domain_record import DomainRecord
from app.repositories.json_store import JsonStore, atomic_store, make_record_key
from app.core.config import settings
from app.utils.datetime import utc_now_iso

router = APIRouter()
RADAR_INDICATORS = [
    {"name": "规划一致性", "max": 100},
    {"name": "代码质量与工程", "max": 100},
    {"name": "理论逻辑完备度", "max": 100},
    {"name": "学术论坛活跃度", "max": 100},
    {"name": "专注度均值", "max": 100},
    {"name": "Checkpoint完成率", "max": 100},
]
SourceRead = dict[str, Any]
StoredRecord = dict[str, Any]


class FreePayload(BaseModel):
    class Config:
        extra = "allow"


def _parse_recorded_timezone_declaration(value: Any) -> timezone | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if value == "UTC":
        return timezone.utc
    match = re.fullmatch(r"([+-])([0-9]{2}):([0-9]{2})", value)
    if not match:
        return None
    sign, hours, minutes = match.groups()
    hours, minutes = int(hours), int(minutes)
    if minutes > 59 or hours > 14 or (hours == 14 and minutes != 0):
        return None
    return timezone(timedelta(minutes=(hours * 60 + minutes) * (1 if sign == "+" else -1)))


def _timezone_label(tz: timezone | None) -> str | None:
    if tz is None:
        return None
    minutes = int(tz.utcoffset(None).total_seconds() / 60)
    if minutes == 0:
        return "UTC"
    return f"{'+' if minutes >= 0 else '-'}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d}"


def _parse_recorded_instant(value: Any, *, naive_timezone: timezone | None = None) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        if naive_timezone is None:
            return None
        value = value.replace(tzinfo=naive_timezone)
    return value.astimezone(timezone.utc)


def _read_metric_records(db: Session, module: str, record_type: str, *, owner_ids: set[str] | None,
                         recorded_timezone: timezone | None = None) -> SourceRead:
    result = {"available": True, "source": f"{module}/{record_type}", "records": [], "reason": None,
              "recordedTimezone": recorded_timezone, "recordedTimezoneDeclaration": _timezone_label(recorded_timezone)}
    if owner_ids is not None and not owner_ids:
        return result
    try:
        query = db.query(DomainRecord).filter(DomainRecord.module == module, DomainRecord.record_type == record_type)
        if owner_ids is not None:
            query = query.filter(DomainRecord.owner_id.in_(owner_ids))
        rows = query.all()
    except SQLAlchemyError:
        result.update(available=False, reason="source_unavailable")
        return result
    selected = {}
    for row in rows:
        key = (row.module, row.record_type, row.record_key, row.owner_id)
        # Ordering metadata only: this never enables UTC time-placement for a naive row.
        instant = _parse_recorded_instant(row.updated_at, naive_timezone=recorded_timezone)
        stamp = instant.isoformat() if instant is not None else (row.updated_at.isoformat() if isinstance(row.updated_at, datetime) else str(row.updated_at or ""))
        order = (stamp, row.id or 0)
        if key not in selected or order > selected[key][0]:
            selected[key] = (order, row)
    for _, row in sorted(selected.values(), key=lambda pair: pair[1].id or 0):
        decode_error = False
        try:
            payload = json.loads(row.payload)
        except (json.JSONDecodeError, TypeError):
            payload, decode_error = {}, True
        if not isinstance(payload, dict):
            payload, decode_error = {}, True
        result["records"].append({"dbId": row.id, "module": row.module, "recordType": row.record_type,
            "recordKey": row.record_key, "ownerId": row.owner_id, "role": row.role, "status": row.status,
            "createdAt": row.created_at, "updatedAt": row.updated_at, "payload": payload, "decodeError": decode_error})
    return result


def _observed_mean(values: list[Any]) -> int | None:
    valid = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool) and isfinite(v) and 0 <= v <= 100]
    return round(mean(valid)) if valid else None


def _metric_evidence(*, evidence_status: str, provenance_status: str, source: str, label: str,
                     sample_count: int, reason: str | None = None, window: dict | None = None,
                     raw_mean: int | float | None = None) -> dict[str, Any]:
    if evidence_status not in {"measured", "self_reported", "inferred", "unavailable"} or provenance_status not in {"verified_server", "legacy_unknown", "demo", "mixed"}:
        raise ValueError("Unsupported metric evidence status")
    if evidence_status == "unavailable":
        raw_mean = None
    return {"evidenceStatus": evidence_status, "provenanceStatus": provenance_status, "source": source,
            "label": label, "sampleCount": sample_count, "rawMean": raw_mean, "reason": reason, "window": window}


def _unavailable(source: str, label: str, reason: str) -> dict[str, Any]:
    return _metric_evidence(evidence_status="unavailable", provenance_status="legacy_unknown", source=source,
                            label=label, sample_count=0, reason=reason)


def _inventory_evidence(source: SourceRead, label: str, count: int | None, *, provenance="legacy_unknown") -> dict[str, Any]:
    return _metric_evidence(evidence_status="measured" if count is not None else "unavailable", provenance_status=provenance,
        source=source["source"], label=label, sample_count=count if count is not None else 0,
        raw_mean=count, reason="complete_record_read" if count is not None else source.get("reason") or "malformed_record")


def _activity_window(*, now: datetime, tz: timezone = timezone.utc) -> dict[str, Any]:
    if tz != timezone.utc:
        raise ValueError("Analytics windows support UTC only")
    instant = _parse_recorded_instant(now)
    if instant is None:
        raise ValueError("An aware now is required")
    end = instant.replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=7)
    iso = lambda value: value.isoformat().replace("+00:00", "Z")
    return {"timezone": "UTC", "startInclusive": iso(start), "endExclusive": iso(end), "asOf": iso(instant)}


def _activity_series(students: list[dict[str, Any]], sources: list[SourceRead], *, now: datetime,
                     tz: timezone = timezone.utc) -> dict[str, Any]:
    window = _activity_window(now=now, tz=tz)
    start = _parse_recorded_instant(window["startInclusive"])
    end = _parse_recorded_instant(window["endExclusive"])
    instant = _parse_recorded_instant(now)
    owners = {s["username"] for s in students if isinstance(s.get("username"), str) and s["username"]}
    daily, hourly = [set() for _ in range(7)], [set() for _ in range(24)]
    seen, count, valid, invalid, excluded = set(), 0, 0, 0, 0
    complete = True
    reasons, used_declarations = [], set()
    for source in sources:
        if not source["available"]:
            complete = False; reasons.append("source_unavailable")
        for row in source["records"]:
            if (row.get("module"), row.get("recordType")) not in {("homework", "submission"), ("exams", "attempt")}:
                excluded += 1
                continue
            owner = row.get("ownerId")
            if not owner or owner not in owners:
                excluded += 1; continue
            key = (row.get("module"), row.get("recordType"), row.get("recordKey"), owner)
            if key in seen:
                continue
            seen.add(key); count += 1
            if row.get("decodeError"):
                complete = False; reasons.append("malformed_record"); continue
            created = row.get("createdAt")
            dt = _parse_recorded_instant(created, naive_timezone=source.get("recordedTimezone"))
            if dt is None:
                invalid += 1; complete = False
                naive = isinstance(created, datetime) and created.tzinfo is None
                if isinstance(created, str):
                    try:
                        naive = datetime.fromisoformat(created.replace("Z", "+00:00")).tzinfo is None
                    except ValueError:
                        naive = False
                reasons.append(source.get("timezoneReason", "recorded_timezone_unconfigured") if naive else "invalid_recorded_timestamp")
                continue
            if (isinstance(created, datetime) and created.tzinfo is None) or (isinstance(created, str) and datetime.fromisoformat(created.replace("Z", "+00:00")).tzinfo is None):
                used_declarations.add(source.get("recordedTimezoneDeclaration"))
            if dt > instant or not start <= dt < end:
                excluded += 1; continue
            valid += 1
            daily[(dt.date() - start.date()).days].add(owner); hourly[dt.hour].add(owner)
    total = count if all(s["available"] for s in sources) else None
    denom = len(owners)
    reason = reasons[0] if reasons else ("empty_roster" if not denom else "complete_record_read")
    declaration = next(iter(used_declarations)) if len(used_declarations) == 1 else None
    evidence = _metric_evidence(evidence_status="measured" if complete else "unavailable", provenance_status="legacy_unknown",
        source="homework/submission+exams/attempt", label="按首次保存时间；历史来源未核验，可能包含演示或导入记录",
        sample_count=valid, reason=reason, window=window)
    evidence.update(coverageComplete=complete, validRecordCount=valid, invalidTimestampCount=invalid,
        excludedRecordCount=excluded, denominatorCount=denom, timeBasis="DomainRecord.created_at", verifiedSampleCount=0,
        recordedTimezone=declaration, recordedTimezoneSource="operator_declaration" if declaration else None)
    inventory = _metric_evidence(evidence_status="measured" if total is not None else "unavailable", provenance_status="legacy_unknown",
        source="homework/submission+exams/attempt", label="已保存提交类记录；历史来源未核验，可能包含演示或导入记录及未确认完成状态",
        sample_count=total if total is not None else 0, raw_mean=total,
        reason="complete_record_read" if total is not None else "source_unavailable")
    return {"weeklyActivityDates": [(start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)],
        "weeklyActivityCounts": [len(v) for v in daily] if complete else [None] * 7,
        "weeklyActivityRates": [round(len(v) / denom * 100) for v in daily] if complete and denom else [None] * 7,
        "weeklyActivityEvidence": evidence, "hourlyActiveData": [len(v) for v in hourly] if complete else [None] * 24,
        "hourlyActiveEvidence": {**evidence, "label": "近七个完整 UTC 日：该小时首次保存提交类记录的账号数；历史来源未核验"},
        "recordedSubmissionCount": total, "recordedSubmissionEvidence": inventory,
        "hourlyFocusData": [None] * 24, "hourlyFocusEvidence": _unavailable("focus", "未测量", "no_focus_measurement_source"),
        "hourlyBehaviors": [], "hourlyBehaviorsEvidence": _unavailable("behavior", "暂无行为证据", "no_behavior_measurement_source")}


def _recorded_policy() -> tuple[timezone | None, str]:
    raw = settings.ANALYTICS_RECORDED_TIMEZONE
    tz = _parse_recorded_timezone_declaration(raw)
    reason = "recorded_timezone_unconfigured" if not isinstance(raw, str) or not raw.strip() else "invalid_recorded_timezone_declaration"
    return tz, reason


def _scoped_source(db: Session, module: str, kind: str, owners: set[str] | None, *, policy=None) -> SourceRead:
    tz, reason = policy if policy is not None else _recorded_policy()
    source = _read_metric_records(db, module, kind, owner_ids=owners, recorded_timezone=tz)
    source["timezoneReason"] = reason
    return source


def _source_count(source: SourceRead) -> int | None:
    return len(source["records"]) if source["available"] and not any(r["decodeError"] for r in source["records"]) else None


def _forum_counts(db: Session, username: str) -> tuple[int | None, int | None]:
    posts = _read_metric_records(db, "forum", "post", owner_ids=None)
    sidecars = _read_metric_records(db, "forum", "reply_identity", owner_ids={username})
    if _source_count(posts) is None or _source_count(sidecars) is None:
        return None, None
    authorities = set()
    for row in sidecars["records"]:
        data = row["payload"]; post_id, reply_id = data.get("postId"), data.get("replyId")
        if (isinstance(post_id, str) and isinstance(reply_id, str) and row["recordKey"] == reply_id
            and row["ownerId"] == username and row["role"] == "student"
            and data.get("authorId") == username and data.get("authorRole") == row["role"]):
            authorities.add((post_id, reply_id))
    post_keys, reply_keys = set(), set()
    for row in posts["records"]:
        if row["ownerId"] == username and row["role"] == "student":
            post_keys.add(row["recordKey"])
        replies = row["payload"].get("replies")
        if isinstance(replies, list):
            for reply in replies:
                reply_id = reply.get("id") if isinstance(reply, dict) else None
                if isinstance(reply_id, str) and reply_id and (row["recordKey"], reply_id) in authorities:
                    reply_keys.add((row["recordKey"], reply_id))
    return len(post_keys), len(reply_keys)


def _recorded_grade_facts(submissions: SourceRead, attempts: SourceRead) -> list[dict[str, Any]]:
    """Saved facts are separate from progress and the six academic dimensions."""
    facts = []
    def numeric(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) and value >= 0
    def append(kind, value, source, label, *, maximum=None, inferred=False):
        facts.append({"kind": kind, "value": value, "maximum": maximum,
            "recordEvidence": _metric_evidence(evidence_status="inferred" if inferred else "measured",
                provenance_status="legacy_unknown", source=source, label=label + "；来源未核验，不构成进度或掌握度测量",
                sample_count=1, raw_mean=value if numeric(value) else None)})
    for row in submissions["records"]:
        if row["decodeError"]:
            continue
        grade = row["payload"].get("grade")
        if isinstance(grade, str) and grade.strip():
            append("letter_grade", grade, "homework/submission.grade", "已保存等级文本（未转换为百分数）")
        elif numeric(grade):
            append("numeric_grade", grade, "homework/submission.grade", "已保存成绩字段（量表未核验）")
    for row in attempts["records"]:
        if row["decodeError"]:
            continue
        data = row["payload"]
        score = data.get("objectiveScore")
        maximum = data.get("maxObjectiveScore", data.get("objectiveMax"))
        if numeric(score) and numeric(maximum) and maximum > 0 and score <= maximum:
            append("objective_percentage", round(score / maximum * 100), "exams/attempt.objectiveScore/maxObjectiveScore",
                   "按已保存分数和满分推算的客观题得分率", maximum=maximum, inferred=True)
        for key, kind in [("programmingScore", "programming_raw_score"), ("totalScore", "exam_raw_score")]:
            if numeric(data.get(key)):
                append(kind, data[key], "exams/attempt." + key, "已保存原始分数（不进入100分雷达）")
    return facts


def _student_card(account: UserAccount, profile: StudentProfile | None, db: Session, *, policy) -> dict[str, Any]:
    username = account.username
    submissions = _scoped_source(db, "homework", "submission", {username}, policy=policy)
    mistakes = _scoped_source(db, "exams", "mistake", {username}, policy=policy)
    attempts = _scoped_source(db, "exams", "attempt", {username}, policy=policy)
    values, evidence = [], {}
    for indicator, score_key in zip(RADAR_INDICATORS[:3], ["alina", "codeninja", "profx"]):
        scores = []
        for row in submissions["records"]:
            diagnosis = row["payload"].get("diagnosis")
            raw_scores = diagnosis.get("scores") if isinstance(diagnosis, dict) else None
            value = raw_scores.get(score_key) if isinstance(raw_scores, dict) else None
            if _observed_mean([value]) is not None:
                scores.append(value)
        value = _observed_mean(scores) if _source_count(submissions) is not None else None
        values.append(value)
        evidence[indicator["name"]] = _metric_evidence(evidence_status="inferred" if value is not None else "unavailable",
            provenance_status="legacy_unknown", source=f"diagnosis.scores.{score_key}", label="已记录诊断分数；推断，来源未核验",
            sample_count=len(scores), raw_mean=value, reason=None if value is not None else "no_verified_diagnostic_measurement")
    post_count, reply_count = _forum_counts(db, username)
    forum_score = min(100, 10 * post_count + 5 * reply_count) if post_count is not None and reply_count is not None and post_count + reply_count else None
    values += [forum_score, None, None]
    evidence[RADAR_INDICATORS[3]["name"]] = _metric_evidence(evidence_status="inferred" if forum_score is not None else "unavailable",
        provenance_status="verified_server" if post_count is not None else "legacy_unknown", source="forum/post+reply_identity",
        label="推断贡献指数（发帖×10+回帖×5，最高100）；不是学术能力测量", sample_count=(post_count or 0)+(reply_count or 0), raw_mean=forum_score,
        reason=None if forum_score is not None else "no_contribution_index_observations")
    focus_evidence = _unavailable("focus", "专注度未测量", "no_focus_measurement_source")
    progress_evidence = _unavailable("progress", "进度未测量", "assignment_denominator_unavailable")
    evidence[RADAR_INDICATORS[4]["name"]] = focus_evidence
    evidence[RADAR_INDICATORS[5]["name"]] = _unavailable("checkpoint", "Checkpoint未测量", "assignment_denominator_unavailable")
    mistake_count = len(mistakes["records"]) if mistakes["available"] else None
    mistake_evidence = _inventory_evidence(mistakes, "已保存错题记录数；来源未核验", mistake_count)
    mistake_evidence.update(factCoverageComplete=_source_count(mistakes) is not None,
        unreadableRecordCount=sum(row["decodeError"] for row in mistakes["records"]))
    forum_source = {"source": "forum/post+reply_identity", "reason": "source_unavailable"}
    return {"id": username, "userId": username, "username": username, "name": account.real_name or username,
        "className": account.class_name or "", "goal": getattr(profile, "goal", "") if profile else "",
        "goalEvidence": _unavailable("profile.goal", "已保存画像文本", "profile_text_not_measurement"),
        "progress": None, "progressEvidence": progress_evidence, "focus": None, "focusEvidence": focus_evidence,
        "activeRate": None, "activeRateEvidence": focus_evidence, "status": "unknown", "currentAgent": None, "agentName": None,
        "alert": None, "alertEvidence": _unavailable("risk", "风险评估未启用", "risk_model_not_defined"),
        "errorCount": mistake_count, "errorCountEvidence": mistake_evidence,
        "unmasteredCount": None, "forumCount": post_count, "replyCount": reply_count,
        "forumCountEvidence": _inventory_evidence(forum_source, "已保存且作者身份核验的论坛发帖数", post_count, provenance="verified_server"),
        "replyCountEvidence": _inventory_evidence(forum_source, "已保存且作者身份核验的论坛回复数", reply_count, provenance="verified_server"),
        "checkpointRate": None, "radarValues": values, "radarEvidence": evidence,
        "recordedGrades": _recorded_grade_facts(submissions, attempts)}


def _canonical_student_ids(db: Session, requested: set[str]) -> set[str]:
    if not requested:
        return set()
    return {row.username for row in db.query(UserAccount).filter(UserAccount.role == "student", UserAccount.username.in_(requested)).all()
            if is_valid_student_username(row.username)}


def _student_cards(db: Session, student_ids: set[str], *, policy=None) -> list[dict[str, Any]]:
    policy = policy if policy is not None else _recorded_policy()
    allowed = _canonical_student_ids(db, student_ids)
    if not allowed:
        return []
    students = db.query(UserAccount).filter(UserAccount.username.in_(allowed)).order_by(UserAccount.created_at.asc(), UserAccount.username.asc()).all()
    profiles = {row.user_id: row for row in db.query(StudentProfile).filter(StudentProfile.user_id.in_(allowed)).all()}
    return [_student_card(row, profiles.get(row.username), db, policy=policy) for row in students]


def _class_radar_values(students: list[dict[str, Any]]) -> list[int | None]:
    result = []
    for i, indicator in enumerate(RADAR_INDICATORS):
        samples = [s["radarValues"][i] for s in students
            if s["radarEvidence"][indicator["name"]]["evidenceStatus"] == "measured"
            and s["radarEvidence"][indicator["name"]]["provenanceStatus"] == "verified_server"]
        result.append(_observed_mean(samples))
    return result


def _class_radar_evidence(students: list[dict[str, Any]], *, reason="no_verified_dimension_measurement") -> dict[str, Any]:
    return {indicator["name"]: {**_unavailable("class_radar", indicator["name"] + "未测量", reason), "studentCount": len(students)} for indicator in RADAR_INDICATORS}


def _teacher_records(store: JsonStore, record_type: str, teacher_id: str, *, policy=None) -> list[dict[str, Any]]:
    allowed = _canonical_student_ids(store.db, teacher_student_ids(teacher_id))
    source = _scoped_source(store.db, "analytics", record_type, {teacher_id}, policy=policy)
    if _source_count(source) is None:
        raise HTTPException(status_code=503, detail="analytics_source_unavailable")
    records = []
    for row in source["records"]:
        data = dict(row["payload"])
        data["id"] = row["recordKey"]
        recipients = data.get("studentIds")
        valid = isinstance(recipients, list) and bool(recipients) and all(isinstance(v, str) and v in allowed for v in recipients)
        if not valid:
            # Never expose a foreign target. A malformed interaction has an unavailable denominator.
            if record_type != "interaction" or (isinstance(recipients, list) and any(isinstance(v, str) and v not in allowed for v in recipients)):
                continue
            data["studentIds"] = []
        if record_type in {"advice", "action"}:
            data["recordEvidence"] = _unavailable("analytics/" + record_type, "历史记录；依据未核验", "historical_basis_unverified")
        records.append(data)
    return records


def _project_interactions(db: Session, teacher_id: str, *, policy=None) -> list[dict[str, Any]]:
    policy = policy if policy is not None else _recorded_policy()
    records = _teacher_records(JsonStore(db), "interaction", teacher_id, policy=policy)
    allowed = _canonical_student_ids(db, teacher_student_ids(teacher_id))
    completions = _scoped_source(db, "analytics", "interaction_completion", allowed, policy=policy)
    readable = _source_count(completions) is not None
    for record in records:
        ids = record.get("studentIds")
        valid = isinstance(ids, list) and bool(ids) and all(isinstance(v, str) and v in allowed for v in ids)
        recipients = set(ids) if valid else set()
        iid = record.get("id")
        valid = valid and isinstance(iid, str) and bool(iid)
        completed = {row["ownerId"] for row in completions["records"] if row["ownerId"] in recipients and row["payload"].get("interactionId") == iid} if readable and valid else None
        denominator = len(recipients) if valid and readable else None
        numerator = len(completed) if completed is not None else None
        record.update(recipientCount=denominator, completionRecordCount=numerator, completedCount=numerator,
            completionRate=round(numerator / denominator * 100) if denominator else None,
            completionEvidence=_metric_evidence(evidence_status="self_reported" if numerator is not None else "unavailable",
                provenance_status="legacy_unknown", source="analytics/interaction_completion", label="已记录交互完成率；账号自报完成，来源未核验",
                sample_count=numerator or 0, raw_mean=None, reason=None if numerator is not None else "completion_denominator_or_source_unavailable"))
    return records


def _weak_points(db: Session, students: list[dict[str, Any]], *, policy=None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source = _scoped_source(db, "exams", "mistake", {s["username"] for s in students}, policy=policy)
    if _source_count(source) is None:
        return [], _inventory_evidence(source, "已记录错题暂不可用", None)
    items = []
    for row in source["records"][:6]:
        data = row["payload"]
        repeats = data.get("wrongCount", data.get("count"))
        repeats = repeats if isinstance(repeats, (int, float)) and not isinstance(repeats, bool) and isfinite(repeats) and repeats >= 0 else None
        items.append({"id": f"mistake-{row['dbId']}", "topic": data.get("questionTitle") or data.get("title") or data.get("topic") or "未命名已记录错题",
            "subject": data.get("subject") or "", "category": "已记录错题", "details": data.get("analysis") or data.get("details") or "",
            "errorRate": None, "recordCount": 1, "affectedStudentCount": 1, "repeatCount": repeats,
            "recordEvidence": _inventory_evidence(source, "已保存错题及分析文本；来源未核验", 1)})
    return items, _inventory_evidence(source, "当前显示的已记录错题数；来源未核验", len(items))


def _optional_teacher_list(db: Session, teacher: str, kind: str, *, policy=None) -> tuple[list, dict]:
    try:
        values = _project_interactions(db, teacher, policy=policy) if kind == "interaction" else _teacher_records(JsonStore(db), kind, teacher, policy=policy)
        return values, _metric_evidence(evidence_status="measured", provenance_status="legacy_unknown", source="analytics/" + kind,
            label="已保存记录列表；历史依据未核验", sample_count=len(values), reason="complete_record_read")
    except HTTPException as error:
        if error.status_code != 503:
            raise
        return [], _unavailable("analytics/" + kind, "记录来源暂不可用", "source_unavailable")


def _analytics_now() -> datetime:
    return datetime.now(timezone.utc)


@router.get("/analytics/overview")
async def get_overview_stats(payload: dict = Depends(require_teacher), db: Session = Depends(get_db)):
    now = _analytics_now()
    policy = _recorded_policy()
    students = _student_cards(db, teacher_student_ids(payload["sub"]), policy=policy)
    owners = {s["username"] for s in students}
    activity = _activity_series(students, [_scoped_source(db, "homework", "submission", owners, policy=policy), _scoped_source(db, "exams", "attempt", owners, policy=policy)], now=now)
    advices, advice_evidence = _optional_teacher_list(db, payload["sub"], "advice", policy=policy)
    actions, action_evidence = _optional_teacher_list(db, payload["sub"], "action", policy=policy)
    interactions, interaction_evidence = _optional_teacher_list(db, payload["sub"], "interaction", policy=policy)
    weak_points, weak_evidence = _weak_points(db, students, policy=policy)
    pairs = [(r["completionRecordCount"], r["recipientCount"]) for r in interactions if r.get("recipientCount") is not None and r.get("completionRecordCount") is not None]
    denom = sum(v[1] for v in pairs)
    response = round(sum(v[0] for v in pairs) / denom * 100) if denom else None
    summary = {"studentCount": len(students), "studentCountEvidence": _metric_evidence(evidence_status="measured", provenance_status="verified_server",
        source="current_canonical_roster", label="当前已分配规范学生账号数", sample_count=len(students), raw_mean=len(students)),
        "averageProgress": None, "averageProgressEvidence": _unavailable("progress", "进度未测量", "assignment_denominator_unavailable"),
        "averageFocus": None, "averageFocusEvidence": _unavailable("focus", "专注度未测量", "no_focus_measurement_source"), "activeInterventions": len([r for r in interactions if r.get("status") == "running"]) if interaction_evidence["evidenceStatus"] != "unavailable" else None,
        "activeInterventionsEvidence": interaction_evidence, "responseRate": response,
        "responseRateEvidence": _metric_evidence(evidence_status="self_reported" if response is not None else "unavailable", provenance_status="legacy_unknown",
            source="analytics/interaction_completion", label="已记录交互完成率；账号自报完成", sample_count=sum(v[0] for v in pairs), raw_mean=response, reason=None if response is not None else "no_valid_completion_denominator"),
        "recordedSubmissionCount": activity.pop("recordedSubmissionCount"), "recordedSubmissionEvidence": activity.pop("recordedSubmissionEvidence")}
    return ok({"radarIndicators": RADAR_INDICATORS, "classRadarValues": _class_radar_values(students), "classRadarEvidence": _class_radar_evidence(students),
        **activity, "weakPoints": weak_points, "weakPointsEvidence": weak_evidence, "summary": summary,
        "aiAdvices": advices, "aiAdvicesEvidence": advice_evidence, "actionQueue": actions, "actionQueueEvidence": action_evidence,
        "interactionRecords": interactions, "interactionRecordsEvidence": interaction_evidence})


@router.get("/analytics/students")
async def get_student_list(payload: dict = Depends(require_teacher), db: Session = Depends(get_db)):
    return ok(_student_cards(db, teacher_student_ids(payload["sub"])))


@router.get("/analytics/students/search")
async def search_students(q: str = "", payload: dict = Depends(require_teacher), db: Session = Depends(get_db)):
    keyword = (q or "").strip().lower()
    students = _student_cards(db, teacher_student_ids(payload["sub"]))
    if not keyword:
        return ok({"query": q, "matches": [], "total": 0})
    scored = []
    for item in students:
        name, username, class_name = (str(item.get(k) or "").lower() for k in ["name", "username", "className"])
        score = 0 if keyword in {name, username} else (1 if name.startswith(keyword) or username.startswith(keyword) else 2)
        if keyword in name or keyword in username or keyword in class_name:
            scored.append((score, item))
    scored.sort(key=lambda pair: (pair[0], str(pair[1].get("name") or ""), pair[1]["username"]))
    matches = [item for _, item in scored]
    return ok({"query": q, "matches": matches, "total": len(matches), "bestMatch": matches[0] if matches else None})


@router.get("/analytics/students/me")
async def get_my_radar(user_id: str = "", payload: dict = Depends(get_auth_payload), db: Session = Depends(get_db)):
    username = (user_id or "").strip()
    if not username:
        raise HTTPException(status_code=400, detail="user_id is required")
    ensure_self_or_teacher(username, payload)
    matched = next(iter(_student_cards(db, {username})), None)
    if matched is None:
        raise HTTPException(status_code=404, detail="Student not found")
    return ok({**matched, "studentId": username, "radarIndicators": RADAR_INDICATORS, "classRadarValues": [None] * 6,
               "classRadarEvidence": _class_radar_evidence([], reason="class_comparison_scope_unavailable")})


@router.get("/analytics/students/{student_id}")
async def get_student_details(student_id: str, payload: dict = Depends(get_auth_payload), db: Session = Depends(get_db)):
    ensure_self_or_teacher(student_id, payload)
    policy = _recorded_policy()
    matched = next(iter(_student_cards(db, {student_id}, policy=policy)), None)
    if matched is None:
        raise HTTPException(status_code=404, detail="Student not found")
    mistakes = _scoped_source(db, "exams", "mistake", {student_id}, policy=policy)
    errors = []
    for row in mistakes["records"]:
        if row["decodeError"]:
            continue
        item = row["payload"]; count = item.get("wrongCount")
        count = count if isinstance(count, (int, float)) and not isinstance(count, bool) and isfinite(count) and count >= 0 else None
        errors.append({"id": f"mistake-{row['dbId']}", "topic": item.get("questionTitle") or item.get("title") or "",
            "severity": None, "count": count, "date": item.get("lastWrongAt") or item.get("createdAt") or None,
            "recordEvidence": _inventory_evidence(mistakes, "已保存错题文本及自报日期；来源未核验", 1)})
    # The inspected producers do not establish a trustworthy event chronology.
    return ok({**matched, "studentId": student_id, "radarIndicators": RADAR_INDICATORS, "errors": errors,
        "timeline": [], "timelineEvidence": _unavailable("timeline", "暂无可展示的已记录时间线", "verified_chronology_unavailable")})


@router.post("/analytics/students/{student_id}/nudge")
async def send_nudge_message(student_id: str, payload: FreePayload, auth: dict = Depends(get_auth_payload), db: Session = Depends(get_db)):
    ensure_self_or_teacher(student_id, auth)
    if not _student_cards(db, {student_id}):
        raise HTTPException(status_code=404, detail="Student not found")
    data = payload.model_dump(); record_id = make_record_key("nudge")
    JsonStore(db).upsert("analytics", "nudge", record_id, {"id": record_id, "studentId": student_id,
        "message": data.get("message", ""), "createdAt": utc_now_iso(), "status": "sent"}, owner_id=student_id, status="sent")
    return ok({"success": True, "nudgedAt": utc_now_iso(), "studentId": student_id})


@router.get("/analytics/advices")
async def get_ai_intervention_advices(payload: dict = Depends(require_teacher), db: Session = Depends(get_db)):
    return ok(_teacher_records(JsonStore(db), "advice", payload["sub"]))


@router.get("/analytics/action-queue")
async def get_action_queue(payload: dict = Depends(require_teacher), db: Session = Depends(get_db)):
    return ok(_teacher_records(JsonStore(db), "action", payload["sub"]))


@router.get("/analytics/interactions")
async def get_interaction_records(payload: dict = Depends(require_teacher), db: Session = Depends(get_db),
    x_gezhi_client: str | None = Header(default=None, alias="X-Gezhi-Client")):
    interactions = _project_interactions(db, payload["sub"])
    if is_miniprogram_client(x_gezhi_client):
        return api_response(page_items(interactions, limit=len(interactions) or 20))
    return ok(interactions)


@router.post("/analytics/interactions")
async def dispatch_student_interaction(payload: FreePayload, auth: dict = Depends(require_teacher), db: Session = Depends(get_db)):
    with atomic_store(db):
        data = payload.model_dump()
        record_id = make_record_key("ir")
        target = data.get("target") or {}
        target_label = target.get("label") if isinstance(target, dict) else str(target or "all")
        student_ids = target.get("studentIds", []) if isinstance(target, dict) else []
        allowed = {s["username"] for s in _student_cards(db, teacher_student_ids(auth["sub"]))}
        if not isinstance(student_ids, list):
            raise HTTPException(status_code=400, detail="studentIds must be a list")
        student_ids = sorted({str(sid) for sid in student_ids}) if student_ids else sorted(allowed)
        if not student_ids or not set(student_ids).issubset(allowed):
            raise HTTPException(status_code=403, detail="no assigned students for this target")
        initial_count = len(student_ids)
        record = {
            "id": record_id,
            "type": data.get("type"),
            "title": data.get("title") or data.get("topic") or "Interaction task",
            "targetLabel": target_label or "all",
            "studentIds": student_ids,
            "completionRate": 0,
            "unreadCount": initial_count,
            "pendingCount": initial_count,
            "completedCount": 0,
            "createdAt": utc_now_iso(),
            "status": data.get("status") or "running",
            "nextAction": data.get("nextAction") or "Track student response.",
            "payload": data.get("payload") or {},
            "source": data.get("source") or {},
        }
        JsonStore(db).upsert("analytics", "interaction", record_id, record, owner_id=auth["sub"], status=record["status"])

        # 个人提醒同步写入 analytics/nudge，学生仪表盘可直接拉取
        if data.get("type") == "nudge" and student_ids:
            message = (data.get("payload") or {}).get("desc") or data.get("title") or "教师学习提醒"
            for owner_id in student_ids:
                nudge_id = make_record_key("nudge")
                JsonStore(db).upsert(
                    "analytics",
                    "nudge",
                    nudge_id,
                    {
                        "id": nudge_id,
                        "studentId": owner_id,
                        "message": message,
                        "interactionId": record_id,
                        "createdAt": utc_now_iso(),
                        "status": "sent",
                    },
                    owner_id=owner_id,
                    status="sent",
                )

        return ok({"success": True, "record": record})


@router.patch("/analytics/interactions/{record_id}")
async def update_interaction_record(record_id: str, payload: FreePayload, auth: dict = Depends(require_teacher), db: Session = Depends(get_db)):
    with atomic_store(db):
        store = JsonStore(db)
        existing = next((r for r in _teacher_records(store, "interaction", auth["sub"]) if r["id"] == record_id), None)
        if existing is None:
            raise HTTPException(status_code=404, detail="Interaction record not found")
        data = {key: value for key, value in payload.model_dump().items()
                if key in {"status", "nextAction", "message", "unreadCount"}}
        updated = store.patch("analytics", "interaction", record_id, data, owner_id=auth["sub"])

        # 如果是补发提醒（更新 unreadCount），写入通知记录供学生端拉取
        if "unreadCount" in data:
            existing = updated or existing
            notification_id = make_record_key("notif")
            store.upsert("dashboard", "notification", notification_id, {
                "id": notification_id,
                "type": "interaction_reminder",
                "interactionId": record_id,
                "title": existing.get("title") or "教师补发提醒",
                "targetLabel": existing.get("targetLabel") or "全班",
                "studentIds": existing.get("studentIds") or [],
                "message": data.get("message") or "教师针对此任务发送了新的提醒，请及时查看。",
                "createdAt": utc_now_iso(),
            }, status="unread")

        return ok({"success": True, "record": updated or {"id": record_id, **data}})


@router.post("/analytics/dispatch")
async def dispatch_intervention_task(payload: FreePayload, auth: dict = Depends(require_teacher), db: Session = Depends(get_db)):
    result = await dispatch_student_interaction(payload, auth, db)
    result["data"]["dispatchedAt"] = utc_now_iso()
    return result


@router.post("/analytics/interactions/{record_id}/complete")
async def mark_interaction_complete(record_id: str, payload: FreePayload, auth: dict = Depends(get_auth_payload), db: Session = Depends(get_db)):
    """学生标记交互任务完成，自动更新 completionRate 等计数（防重复提交）"""
    with atomic_store(db):
        store = JsonStore(db)
        record = store.get_payload("analytics", "interaction", record_id)
        if not record:
            raise HTTPException(status_code=404, detail="Interaction record not found")

        data = payload.model_dump()
        user_id = str(data.get("userId") or data.get("studentId") or auth["sub"])
        ensure_self_or_teacher(user_id, auth)
        if user_id not in (record.get("studentIds") or []):
            raise HTTPException(status_code=403, detail="not an interaction recipient")

        # 防重复提交：检查该学生是否已完成此任务
        completion_id = f"{record_id}:{user_id}"
        existing_completion = store.get_payload("analytics", "interaction_completion", completion_id)
        if existing_completion:
            # 已完成过，直接返回当前状态
            return ok({
                "success": True,
                "alreadyCompleted": True,
                "completionRate": record.get("completionRate", 0),
                "completedCount": record.get("completedCount", 0),
            })

        # 更新计数
        completed = record.get("completedCount", 0) + 1
        pending = max(0, record.get("pendingCount", 0) - 1)
        unread = max(0, record.get("unreadCount", 0) - 1)
        total = completed + pending
        completion_rate = round(completed / total * 100) if total > 0 else 0

        patch = {
            "completedCount": completed,
            "pendingCount": pending,
            "unreadCount": unread,
            "completionRate": completion_rate,
            "status": "completed" if pending == 0 else "running",
        }
        store.patch("analytics", "interaction", record_id, patch)

        # 记录学生完成状态
        store.upsert("analytics", "interaction_completion", completion_id, {
            "id": completion_id,
            "interactionId": record_id,
            "userId": user_id,
            "completedAt": utc_now_iso(),
            "result": data.get("result", {}),
        }, owner_id=user_id, status="completed")

        return ok({"success": True, "completionRate": completion_rate, "completedCount": completed})




@router.post("/analytics/advices/generate")
async def generate_ai_advices(payload: FreePayload = None, auth: dict = Depends(require_teacher), db: Session = Depends(get_db)):
    raise HTTPException(status_code=503, detail="analytics_generation_unavailable")


@router.post("/analytics/action-queue/generate")
async def generate_action_queue(payload: FreePayload = None, auth: dict = Depends(require_teacher), db: Session = Depends(get_db)):
    raise HTTPException(status_code=503, detail="analytics_generation_unavailable")
