"""临时质检脚本：确定性 / 日期范围 / 分布 / 样例 payload（不写库）。"""
import json
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for k, v in {
    "RAGFLOW_API_KEY": "t", "RAGFLOW_BASE_URL": "http://localhost",
    "RAGFLOW_AGENT_ID": "t", "RAGFLOW_CHAT_ID": "t", "RAGFLOW_DATASET_ID": "t",
    "RAGFLOW_PUBLIC_DATASET_IDS": "", "OPENAI_API_KEY": "t", "OPENAI_API_BASE": "http://localhost",
}.items():
    os.environ[k] = v

from app.demo_data.class_students_sixdim_seed import A_CLASS_STUDENTS, generate_class_students_data
from scripts.inject_class_students_sixdim_data import build_context_from_snapshot

snapshot = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
ctx = build_context_from_snapshot(snapshot)
g1 = generate_class_students_data(ctx)
g2 = generate_class_students_data(ctx)


def digest(g):
    return json.dumps(
        {"s": g.submissions, "e": g.exam_attempts, "m": g.mistakes, "p": g.profile_updates, "f": g.forum_replies},
        ensure_ascii=False, sort_keys=True, default=str,
    )


print("deterministic:", digest(g1) == digest(g2))
print("counts: subs", len(g1.submissions), "exams", len(g1.exam_attempts), "mistakes",
      len(g1.mistakes), "replies", len(g1.forum_replies), "profiles", len(g1.profile_updates))

bad = [s for s in g1.submissions if not any(m in s["submittedAt"] for m in ("2026-06", "2026-07", "2026-08"))
       or s["submittedAt"] >= "2026-08-17"]
print("date-range bad =", len(bad))
late = [s for s in g1.submissions if s["submittedAt"] >= "2026-08-01"]
print("august submissions:", len(late))

c = Counter(s["studentId"] for s in g1.submissions)
print("A类提交数:", sorted(c[k] for k in A_CLASS_STUDENTS if k in c))
print("B类补交数:", sorted(c[k] for k in c if k not in A_CLASS_STUDENTS))
print("字母成绩分布:", dict(Counter(s["grade"] for s in g1.submissions)))
diag = [s["diagnosis"]["scores"] for s in g1.submissions]
for key in ("alina", "codeninja", "profx"):
    vals = [d[key] for d in diag]
    print(f"{key}: min={min(vals)} max={max(vals)} avg={round(sum(vals)/len(vals),1)}")

attempts = g1.exam_attempts
obj = [a["objectiveScore"] / a["maxObjectiveScore"] * 100 for a in attempts if a.get("objectiveScore")]
prog = [a["programmingScore"] for a in attempts if a.get("programmingScore") is not None]
print(f"客观题得分率: min={min(obj):.0f} max={max(obj):.0f} avg={sum(obj)/len(obj):.0f}")
print(f"编程分: min={min(prog)} max={max(prog)} avg={sum(prog)/len(prog):.0f}")

unmastered = Counter()
for m in g1.mistakes:
    sid = m["studentId"]
    if not m.get("mastered"):
        unmastered[sid] += 1
print("未掌握错题数分布:", dict(Counter(unmastered.values())))

rng = __import__("random").Random(7)
sample = rng.choice([s for s in g1.submissions if s["studentId"] == "23001020122"])
print("\n=== 样例提交 ===")
print(json.dumps(sample, ensure_ascii=False, indent=1)[:1800])
sample2 = rng.choice(g1.mistakes)
print("\n=== 样例错题 ===")
print(json.dumps(sample2, ensure_ascii=False, indent=1)[:1200])
sample3 = rng.choice(g1.forum_replies)
print("\n=== 样例回帖 ===")
print(json.dumps(sample3, ensure_ascii=False, indent=1)[:600])
