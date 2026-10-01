"""临时脚本：dump 学情相关表快照为 JSON（供本地模拟，不写库）。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

for key, val in {
    "RAGFLOW_API_KEY": "test", "RAGFLOW_BASE_URL": "http://localhost",
    "RAGFLOW_AGENT_ID": "test", "RAGFLOW_CHAT_ID": "test",
    "RAGFLOW_DATASET_ID": "test", "RAGFLOW_PUBLIC_DATASET_IDS": "",
    "OPENAI_API_KEY": "test", "OPENAI_API_BASE": "http://localhost",
}.items():
    os.environ.setdefault(key, val)

from app.core.database import SessionLocal  # noqa: E402
from app.models.domain_record import DomainRecord  # noqa: E402
from app.models.student_profile import StudentProfile  # noqa: E402
from app.models.user_account import UserAccount  # noqa: E402


def main() -> int:
    db = SessionLocal()
    try:
        users = [
            {"username": u.username, "real_name": u.real_name, "class_name": u.class_name or "", "role": u.role}
            for u in db.query(UserAccount).all()
        ]
        profiles = [
            {"user_id": p.user_id, "knowledge": p.knowledge, "pace": p.pace}
            for p in db.query(StudentProfile).all()
        ]
        records = []
        for r in (
            db.query(DomainRecord)
            .filter(
                DomainRecord.module.in_(["homework", "exams", "forum"]),
                DomainRecord.record_type.in_(["homework", "submission", "attempt", "mistake", "post", "exam"]),
            )
            .all()
        ):
            try:
                payload = json.loads(r.payload)
            except Exception:
                payload = {}
            records.append({
                "module": r.module, "record_type": r.record_type, "record_key": r.record_key,
                "owner_id": r.owner_id or "", "status": r.status or "",
                "created_at": r.created_at.isoformat() if r.created_at else "",
                "payload": payload,
            })
        out = {"users": users, "profiles": profiles, "records": records}
        print(json.dumps(out, ensure_ascii=False))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
