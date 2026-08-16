"""临时诊断脚本：输出全部学生当前六维雷达基线与数据缺口（不写库）。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("RAGFLOW_API_KEY", "test")
os.environ.setdefault("RAGFLOW_BASE_URL", "http://localhost")
os.environ.setdefault("RAGFLOW_AGENT_ID", "test")
os.environ.setdefault("RAGFLOW_CHAT_ID", "test")
os.environ.setdefault("RAGFLOW_DATASET_ID", "test")
os.environ.setdefault("RAGFLOW_PUBLIC_DATASET_IDS", "")
os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("OPENAI_API_BASE", "http://localhost")

from app.core.database import SessionLocal  # noqa: E402
from app.models.student_profile import StudentProfile  # noqa: E402
from app.models.user_account import UserAccount  # noqa: E402
from app.repositories.json_store import JsonStore  # noqa: E402
from app.core.username_policy import is_valid_student_username  # noqa: E402
from app.api.endpoints.analytics import _compute_radar_values  # noqa: E402


def main() -> int:
    db = SessionLocal()
    try:
        students = [
            s for s in db.query(UserAccount).filter(UserAccount.role == "student").all()
            if is_valid_student_username(s.username)
        ]
        profiles = {p.user_id: p for p in db.query(StudentProfile).all()}
        store = JsonStore(db)
        all_homeworks = store.list_payloads("homework", "homework")
        forum_posts = store.list_payloads("forum", "post")
        daily = [h for h in all_homeworks if h.get("type") == "daily"]

        rows = []
        for s in sorted(students, key=lambda x: (x.class_name or "", x.username)):
            metrics = _compute_radar_values(
                s.username, s.real_name or s.username, profiles.get(s.username), store,
                all_homeworks=all_homeworks, forum_posts=forum_posts,
            )
            rows.append({
                "user": s.username,
                "name": s.real_name,
                "cls": s.class_name,
                "radar": metrics["radarValues"],
                "evidence": {k: v["label"] for k, v in metrics["radarEvidence"].items()},
            })
        print(json.dumps({"dailyCount": len(daily), "students": rows}, ensure_ascii=False, indent=1))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
