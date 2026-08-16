"""一次性修正：把"截止日当天但晚于截止时刻"的注入提交改为白天时段。

背景：class_students_sixdim_seed 的 _ts 统一取晚间 19:00-23:38，
而 target-teacher-su-* 作业截止为当日 18:00，导致约半数提交显示迟交数小时。
本脚本只调整 submittedAt/gradedAt/diagnosis.generatedAt 的时刻部分：
  - 提交日期 < 截止日期：不动（晚间提交合理）
  - 提交日期 > 截止日期（拖延型故意迟交 1 天以上）：不动（真实感保留）
  - 提交日期 == 截止日期 且 时刻 > 截止时刻：改判当天 10:00-17:29（确定性哈希选时刻）
只处理 2026-08-17 之后创建的注入记录，谢渝(23001020119)与其他历史数据不动。
幂等：重跑时已合规的时间不会再次变化。
"""
import json
import os
import sys
from datetime import datetime, time, timedelta, timezone

sys.path.insert(0, "/app")
for k, v in {
    "RAGFLOW_API_KEY": "t", "RAGFLOW_BASE_URL": "http://localhost",
    "RAGFLOW_AGENT_ID": "t", "RAGFLOW_CHAT_ID": "t", "RAGFLOW_DATASET_ID": "t",
    "RAGFLOW_PUBLIC_DATASET_IDS": "", "OPENAI_API_KEY": "t", "OPENAI_API_BASE": "http://localhost",
}.items():
    os.environ.setdefault(k, v)

from sqlalchemy import text

from app.core.database import SessionLocal
from app.repositories.json_store import JsonStore

CHINA_TZ = timezone(timedelta(hours=8))
CUTOFF = "2026-08-17"
PROTECTED = "23001020119"


def stable_hash(value: str) -> int:
    h = 2166136261
    for ch in value.encode("utf-8"):
        h = ((h ^ ch) * 16777619) & 0xFFFFFFFF
    return h


def parse_deadline(raw) -> datetime | None:
    if not raw:
        return None
    s = str(raw).strip().replace("Z", "")
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=CHINA_TZ) if dt.tzinfo is None else dt
        except ValueError:
            continue
    return None


def parse_ts(raw) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw))
        return dt if dt.tzinfo else dt.replace(tzinfo=CHINA_TZ)
    except ValueError:
        return None


def daytime_adjust(record_key: str, day: datetime) -> time:
    minutes = 10 * 60 + stable_hash(record_key) % (7 * 60 + 30)  # 10:00-17:29
    hour, minute = divmod(minutes, 60)
    return time(hour, minute)


def main() -> int:
    db = SessionLocal()
    store = JsonStore(db)
    deadlines = {}
    for hw in store.list_payloads("homework", "homework"):
        dl = parse_deadline(hw.get("deadline"))
        if dl:
            deadlines[str(hw.get("id"))] = dl

    rows = db.execute(text(
        "SELECT id, record_key, owner_id, created_at, payload FROM domain_records "
        "WHERE module='homework' AND record_type='submission' "
        "AND created_at >= :cutoff AND owner_id <> :protected"
    ), {"cutoff": CUTOFF, "protected": PROTECTED}).fetchall()
    print(f"待检注入提交: {len(rows)} 条")

    fixed = kept_day_late = kept_early = already_ok = 0
    for row in rows:
        payload = json.loads(row.payload)
        hw_id = str(payload.get("homeworkId") or "")
        dl = deadlines.get(hw_id)
        ts = parse_ts(payload.get("submittedAt"))
        if not dl or not ts:
            already_ok += 1
            continue
        if ts.date() < dl.date():
            kept_early += 1
            continue
        if ts.date() > dl.date():
            kept_day_late += 1
            continue
        if ts <= dl:
            already_ok += 1
            continue
        # 截止日当天迟交数小时 → 改为当天白天
        new_ts = datetime.combine(ts.date(), daytime_adjust(row.record_key, ts), tzinfo=CHINA_TZ)
        payload["submittedAt"] = new_ts.isoformat()
        payload["gradedAt"] = (new_ts + timedelta(hours=1 + stable_hash(row.record_key + "g") % 20)).isoformat()
        diag = payload.get("diagnosis")
        if isinstance(diag, dict):
            diag["generatedAt"] = payload["gradedAt"]
        store.upsert("homework", "submission", row.record_key, payload,
                     owner_id=payload.get("studentId") or "", status="graded")
        fixed += 1

    print(json.dumps({
        "改为白天提交": fixed,
        "早于截止日(保留晚间)": kept_early,
        "拖延迟交1天以上(保留)": kept_day_late,
        "已合规/无截止": already_ok,
    }, ensure_ascii=False))
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
