"""为班级全体学生注入六维图谱数据并做同源验收。

用法：
  python scripts/inject_class_students_sixdim_data.py                 # 生产注入 + 验收
  python scripts/inject_class_students_sixdim_data.py --verify-only   # 只验收不写入
  python scripts/inject_class_students_sixdim_data.py --simulate snapshot.json
                                                            # 用库快照离线模拟验收（不连库）

幂等：全部固定 record_key upsert，重跑结果一致。
验收直接调用教师端/学生端同源 _compute_radar_values（--simulate 模式用快照
叠加生成的数据模拟同一套计算），确保注入的是后端真实数据而非前端演示数据。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

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

from app.api.endpoints.analytics import GRADE_LETTER_MAP, _compute_radar_values  # noqa: E402
from app.core.username_policy import is_valid_student_username  # noqa: E402
from app.demo_data.class_students_sixdim_seed import (  # noqa: E402
    A_CLASS_STUDENTS,
    PROTECTED_USER,
    StudentContext,
    generate_class_students_data,
)

DIM_NAMES = ["规划一致性", "代码质量与工程", "理论逻辑完备度", "学术论坛活跃度", "专注度均值", "Checkpoint完成率"]
EXPECTED_TARGET_RADAR = [89, 90, 87, 100, 80, 100]


# ---------------------------------------------------------------------------
# 快照 → 上下文（离线模拟用）
# ---------------------------------------------------------------------------

def build_context_from_snapshot(snapshot: dict) -> StudentContext:
    students = [
        {"username": u["username"], "real_name": u["real_name"] or u["username"], "class_name": u["class_name"] or ""}
        for u in snapshot["users"]
        if u.get("role") == "student" and is_valid_student_username(u["username"])
    ]
    profiles = {p["user_id"]: {"knowledge": p["knowledge"], "pace": p["pace"]} for p in snapshot["profiles"]}
    homeworks: dict[str, dict[str, Any]] = {}
    submission_hwids: dict[str, set[str]] = {}
    submission_keys: set[str] = set()
    attempt_examids: dict[str, set[str]] = {}
    attempt_keys: set[str] = set()
    mistake_keys: set[str] = set()
    forum_posts: dict[str, dict[str, Any]] = {}
    for rec in snapshot["records"]:
        module, rtype = rec["module"], rec["record_type"]
        payload = rec["payload"]
        if module == "homework" and rtype == "homework":
            homeworks[str(payload.get("id") or rec["record_key"])] = payload
        elif module == "homework" and rtype == "submission":
            sid = str(payload.get("studentId") or "")
            if sid:
                submission_hwids.setdefault(sid, set()).add(str(payload.get("homeworkId") or ""))
            submission_keys.add(str(payload.get("id") or rec["record_key"]))
        elif module == "exams" and rtype == "attempt":
            sid = str(payload.get("studentId") or "")
            if sid:
                attempt_examids.setdefault(sid, set()).add(str(payload.get("examId") or ""))
            attempt_keys.add(str(payload.get("id") or rec["record_key"]))
        elif module == "exams" and rtype == "mistake":
            mistake_keys.add(str(payload.get("id") or rec["record_key"]))
        elif module == "forum" and rtype == "post":
            forum_posts[str(payload.get("id") or rec["record_key"])] = {
                "createdAt": str(payload.get("createdAt") or ""),
                "replyIds": {str(r.get("id")) for r in (payload.get("replies") or [])},
            }
    return StudentContext(
        students=students, profiles=profiles, homeworks=homeworks,
        submission_hwids=submission_hwids, submission_keys=submission_keys,
        attempt_examids=attempt_examids, attempt_keys=attempt_keys,
        mistake_keys=mistake_keys, forum_posts=forum_posts,
    )


# ---------------------------------------------------------------------------
# 模拟 Store：快照记录 + 生成数据叠加（复用真实 _compute_radar_values）
# ---------------------------------------------------------------------------

class SimStore:
    """实现 _compute_radar_values 用到的 list_payloads 接口。"""

    def __init__(self, snapshot: dict, generated) -> None:
        by_bucket: dict[tuple[str, str], list[tuple[str, str, dict]]] = {}
        for rec in snapshot["records"]:
            payload = rec["payload"]
            payload.setdefault("id", rec["record_key"])
            by_bucket.setdefault((rec["module"], rec["record_type"]), []).append(
                (rec["owner_id"], rec["created_at"], payload)
            )
        for payload in generated.submissions:
            by_bucket.setdefault(("homework", "submission"), []).append(
                (payload["studentId"], payload["submittedAt"], payload)
            )
        for payload in generated.exam_attempts:
            by_bucket.setdefault(("exams", "attempt"), []).append(
                (payload["studentId"], payload["submittedAt"], payload)
            )
        for payload in generated.mistakes:
            by_bucket.setdefault(("exams", "mistake"), []).append(
                (payload["studentId"], payload["createdAt"], payload)
            )
        for item in generated.forum_replies:
            bucket = by_bucket.setdefault(("forum", "post"), [])
            for entry in bucket:
                if entry[2].get("id") == item["postId"]:
                    replies = list(entry[2].get("replies") or [])
                    if not any(str(r.get("id")) == item["reply"]["id"] for r in replies):
                        entry[2]["replies"] = replies + [item["reply"]]
                    break
        self._buckets = by_bucket
        self._profiles = {}
        for p in snapshot["profiles"]:
            self._profiles[p["user_id"]] = SimpleNamespace(
                knowledge=p["knowledge"] or 50, pace=p["pace"] or 50
            )
        for sid, fields in generated.profile_updates.items():
            base = self._profiles.get(sid) or SimpleNamespace(knowledge=50, pace=50)
            self._profiles[sid] = SimpleNamespace(
                knowledge=fields.get("knowledge", base.knowledge),
                pace=fields.get("pace", base.pace),
            )

    def list_payloads(self, module, record_type=None, owner_id=None, status=None):
        rows: list[dict] = []
        for (m, t), entries in self._buckets.items():
            if module != m or record_type is not None and t != record_type:
                continue
            for owner, _created, payload in entries:
                if owner_id is None or owner == owner_id:
                    rows.append(payload)
        return rows

    def profile_for(self, sid: str):
        return self._profiles.get(sid)


def collect_metrics(store, students, profiles):
    all_homeworks = store.list_payloads("homework", "homework")
    forum_posts = store.list_payloads("forum", "post")
    rows = []
    for student in students:
        username = student["username"]
        profile = profiles(username) if callable(profiles) else profiles.get(username)
        metrics = _compute_radar_values(
            username, student["real_name"] or username, profile, store,
            all_homeworks=all_homeworks, forum_posts=forum_posts,
        )
        rows.append({
            "username": username,
            "name": student["real_name"],
            "className": student["class_name"],
            "radarValues": metrics["radarValues"],
            "progress": metrics["progress"],
            "focus": metrics["focus"],
            "alert": metrics["progress"] < 50 or metrics["focus"] < 50,
        })
    return rows


def class_radar(rows: list[dict]) -> list[int]:
    if not rows:
        return [0] * 6
    out = []
    for idx in range(6):
        values = [r["radarValues"][idx] for r in rows if len(r["radarValues"]) > idx]
        out.append(round(sum(values) / len(values)) if values else 0)
    return out


def fmt_radar(values: list[int]) -> str:
    return "[" + ", ".join(f"{v:>3}" for v in values) + "]"


def verify(rows: list[dict]) -> tuple[bool, list[str]]:
    checks: list[tuple[str, bool, str]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append((name, ok, detail))

    global_radar = class_radar(rows)
    add(
        "全局六维 ∈ [58,78] 且无 <55/0",
        all(58 <= v <= 78 for v in global_radar) and all(v >= 55 and v != 0 for v in global_radar),
        f"全局 = {fmt_radar(global_radar)}",
    )
    class_23006 = class_radar([r for r in rows if r["className"] == "23006"])
    add(
        "23006 班六维 ∈ [58,80]",
        all(58 <= v <= 80 for v in class_23006),
        f"23006 = {fmt_radar(class_23006)}",
    )
    bad_students = [
        r for r in rows
        if any(v == 0 for v in r["radarValues"])
        or any(v < 20 for i, v in enumerate(r["radarValues"]) if i != 3)
        or r["radarValues"][3] < 5
    ]
    add(
        "每个学生每维 ≥20（论坛 ≥5，不得 0）",
        not bad_students,
        "全部达标" if not bad_students else "不达标: " + "; ".join(
            f"{r['name']}({r['username']}){fmt_radar(r['radarValues'])}" for r in bad_students[:6]
        ),
    )
    target_row = next((r for r in rows if r["username"] == PROTECTED_USER), None)
    target_ok = bool(target_row) and target_row["radarValues"] == EXPECTED_TARGET_RADAR
    add(
        f"谢渝雷达保持 {EXPECTED_TARGET_RADAR}",
        target_ok,
        fmt_radar(target_row["radarValues"]) if target_row else "未找到谢渝",
    )
    alerts = [r for r in rows if r["alert"]]
    add("学生卡片 alert 人数 ≤ 5", len(alerts) <= 5,
        f"alert {len(alerts)} 人" + ("：" + "、".join(r["name"] for r in alerts[:6]) if alerts else ""))

    zero_dims = sum(1 for r in rows for v in r["radarValues"] if v == 0)
    print("\n=== 验收结果 ===")
    for name, ok, detail in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}\n       {detail}")
    print(f"零值维度统计（54 人 × 6 维）: {zero_dims} 个")
    print(f"alert 学生: {len(alerts)} 人")
    all_ok = all(ok for _, ok, _ in checks)
    print(f"总体判定: {'PASS' if all_ok else 'FAIL'}")
    return all_ok, [f"{'PASS' if ok else 'FAIL'}|{name}|{detail}" for name, ok, detail in checks]


def print_report(rows: list[dict], summary: dict | None) -> None:
    print("\n=== 班级六维雷达（后端同源计算） ===")
    global_radar = class_radar(rows)
    print(f"{'全局(54人均值)':<16} {fmt_radar(global_radar)}")
    classes: list[str] = []
    for r in rows:
        if r["className"] not in classes:
            classes.append(r["className"])
    for cls in classes:
        sub = [r for r in rows if r["className"] == cls]
        print(f"{f'{cls}({len(sub)}人)':<16} {fmt_radar(class_radar(sub))}")

    print("\n=== 学生六维明细 ===")
    print(f"{'学号':<14}{'姓名':<7}{'班级':<10}{'六维雷达':<34}{'进度':>4}{'专注':>4}  alert")
    for r in rows:
        print(
            f"{r['username']:<14}{r['name']:<7}{r['className']:<10}"
            f"{fmt_radar(r['radarValues']):<34}{r['progress']:>4}{r['focus']:>4}  {'Y' if r['alert'] else '-'}"
        )

    if summary:
        print("\n=== 注入摘要 ===")
        print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> int:
    args = sys.argv[1:]
    verify_only = "--verify-only" in args
    simulate_path = None
    if "--simulate" in args:
        simulate_path = args[args.index("--simulate") + 1]

    if simulate_path:
        snapshot = json.loads(Path(simulate_path).read_text(encoding="utf-8"))
        context = build_context_from_snapshot(snapshot)
        generated = generate_class_students_data(context)
        store = SimStore(snapshot, generated)
        rows = collect_metrics(store, context.students, store.profile_for)
        totals = {
            "classA": {"students": generated.stats["classA"]["students"], **{k: generated.stats["classA"][k] for k in ("submissions", "exams", "mistakes", "profilesCreated")}},
            "classB": generated.stats["classB"],
            "extraReplies": generated.stats["extraReplies"],
            "totals": {
                "submissions": len(generated.submissions),
                "examAttempts": len(generated.exam_attempts),
                "mistakes": len(generated.mistakes),
                "forumReplies": len(generated.forum_replies),
                "profileUpdates": len(generated.profile_updates),
            },
        }
        print(f"[simulate] 基于快照 {simulate_path}（{len(context.students)} 名学生）")
        print_report(rows, totals)
        ok, _ = verify(rows)
        return 0 if ok else 1

    from app.core.database import SessionLocal
    from app.demo_data.class_students_sixdim_seed import (
        apply_class_students_data,
        build_context_from_db,
    )

    db = SessionLocal()
    try:
        context = build_context_from_db(db)
        summary: dict | None = None
        if not verify_only:
            generated = generate_class_students_data(context)
            summary = apply_class_students_data(db, generated)
        students = context.students
        store_for_metrics = db
        # 直接复用生产同源计算（与 _student_cards 相同的数据面）
        from app.models.student_profile import StudentProfile
        from app.repositories.json_store import JsonStore

        json_store = JsonStore(db)
        profiles = {p.user_id: p for p in db.query(StudentProfile).all()}
        all_homeworks = json_store.list_payloads("homework", "homework")
        forum_posts = json_store.list_payloads("forum", "post")
        rows = []
        for student in students:
            username = student["username"]
            metrics = _compute_radar_values(
                username,
                student["real_name"] or username,
                profiles.get(username),
                json_store,
                all_homeworks=all_homeworks,
                forum_posts=forum_posts,
            )
            rows.append({
                "username": username,
                "name": student["real_name"],
                "className": student["class_name"],
                "radarValues": metrics["radarValues"],
                "progress": metrics["progress"],
                "focus": metrics["focus"],
                "alert": metrics["progress"] < 50 or metrics["focus"] < 50,
            })
        print(f"[live] 生产库验收（{len(students)} 名学生）")
        print_report(rows, summary)
        ok, _ = verify(rows)
        return 0 if ok else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
