"""为班级全体学生注入"能力协同六维图谱"真实后端数据（普通大学生水平 60-75 分档）。

目标：教师端学情决策台的班级六维雷达与学生个人画像从"大量兜底值/0"变为
真实可信的普通班级水平。数据全部写入 MySQL（domain_records / student_profiles），
与前端真实 API（/analytics/overview 同源 _compute_radar_values）口径一致。

分三类处理（谢渝 23001020119 为已达标的优秀生，禁碰）：
  A 类（22 人，全量注入）：23006 班 20 人 + 谢晨希(谢) + 谢生
      - 补齐 9-11/13 个 daily Checkpoint 提交（带三智能体诊断分）
      - 2-3 场真实考试（客观题得分率 55-75%，编程分 50-75）
      - 错题本 2-5 条（多数已掌握，1-2 条未掌握）
      - 画像 knowledge/pace 提升至 60-70
  B 类（31 人，补交作业）：20230001-20230031
      - 已有提交/考试/错题一律不动，仅在未交过的 daily 作业里补交 3-5 份
      - 每人新增 1-2 条错题（1 条未掌握），使专注度回落到真实带
      - 在已有帖子下追加 2-4 条回复（authorUsername=学号 精确匹配）
  论坛补强：谢晨希/谢生追加回复；23006 班 A 类学生论坛数据已有，不动。

生成原则：人设驱动（学号哈希确定性 RNG，幂等重跑结果一致），
每道题答案按质量分 3 档（对 / 基本对但含糊 / 半错），
诊断消息与教师评语区分"基本正确但没说透 / 建议补充 XX"等普通学生口吻。
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.domain_record import DomainRecord
from app.models.student_profile import StudentProfile
from app.repositories.json_store import JsonStore

CHINA_TZ = timezone(timedelta(hours=8))
CUTOFF_DATE = date(2026, 8, 16)  # 所有生成时间必须早于 2026-08-17

PROTECTED_USER = "23001020119"  # 谢渝，已达标优秀生，禁碰

# A 类学生（全量注入）。谢晨希的 username 是"谢"，谢生 username="谢生"。
A_CLASS_STUDENTS: list[str] = [
    "23001020120", "23001020121", "23001020122", "23001020123", "23001020124",
    "23001020125", "23001020126", "23001020127", "23001020131", "23001020132",
    "23001020133", "23001020134", "23001020135", "23001020136",
    "23004020128", "23004020129", "23004020130", "23004020131", "23004020132",
    "23004020133",
    "谢",
    "谢生",
]


# ---------------------------------------------------------------------------
# 人设
# ---------------------------------------------------------------------------

PERSONA_WEIGHTS = [("diligent", 30), ("normal", 40), ("procrastinator", 20), ("uneven", 10)]

PERSONA_LABEL = {
    "diligent": "勤奋型",
    "normal": "普通型",
    "procrastinator": "拖延型",
    "uneven": "偏科型",
}


def _weighted_choice(rng: random.Random, weighted: list[tuple[str, int]]) -> str:
    total = sum(weight for _, weight in weighted)
    pick = rng.uniform(0, total)
    acc = 0.0
    for key, weight in weighted:
        acc += weight
        if pick <= acc:
            return key
    return weighted[-1][0]


def persona_for(student_id: str) -> str:
    rng = random.Random(f"gezhi-persona-2026|{student_id}")
    return _weighted_choice(rng, PERSONA_WEIGHTS)


# ---------------------------------------------------------------------------
# 13 个 daily 作业规格（id → 出题内容与三档答案/消息）
# tier 1 = 对，2 = 基本对但含糊，3 = 半错
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HomeworkSpec:
    hw_id: str
    subject: str  # DS/DB/FE/CO/PY/NET/AI/SE/OS
    title: str
    topic: str
    created: date
    deadline: date
    answers: dict[int, dict[str, str]]
    q_results: dict[int, dict[str, bool]]
    msgs: dict[int, dict[str, str]]  # alina/codeninja/profx/comment


def _d(month: int, day: int) -> date:
    return date(2026, month, day)


HOMEWORK_SPECS: dict[str, HomeworkSpec] = {}

HOMEWORK_SPECS["demo-hw-ds-linked-stack"] = HomeworkSpec(
    hw_id="demo-hw-ds-linked-stack", subject="DS",
    title="链表指针更新与栈递归现场复盘", topic="链表指针顺序与递归调用栈",
    created=_d(6, 22), deadline=_d(7, 4),
    answers={
        1: {
            "q1": "避免节点丢失",
            "q2": "栈",
            "q3": "function reverseList(head) {\n  let prev = null, curr = head;\n  while (curr) {\n    const next = curr.next;\n    curr.next = prev;\n    prev = curr;\n    curr = next;\n  }\n  return prev;\n}",
        },
        2: {
            "q1": "避免节点丢失",
            "q2": "函数调用栈",
            "q3": "function reverseList(head) {\n  let prev = null, curr = head;\n  while (curr) {\n    const next = curr.next;\n    curr.next = prev;\n    prev = curr;\n    curr = next;\n  }\n  return prev;\n}",
        },
        3: {
            "q1": "避免节点丢失",
            "q2": "队列",
            "q3": "function reverseList(head) {\n  const arr = [];\n  for (let p = head; p; p = p.next) arr.push(p);\n  for (let i = arr.length - 1; i > 0; i--) arr[i].next = arr[i - 1];\n  arr[0].next = null;\n  return arr[arr.length - 1];\n}",
        },
    },
    q_results={
        1: {"q1": True, "q2": True, "q3": True},
        2: {"q1": True, "q2": True, "q3": True},
        3: {"q1": True, "q2": False, "q3": False},
    },
    msgs={
        1: {
            "alina": "按时完成，链表专题节奏保持得不错，可以衔接数据库作业。",
            "codeninja": "三指针推进顺序正确，空表边界处理完整；建议再写一个递归版对比空间开销。",
            "profx": "『先备份 next 再改指向』的原因表述清楚，指针与栈的联系理解到位。",
            "comment": "反转实现完整，先存 next 再改指向没有跳步。建议补上空表、单节点两个用例的自测说明。",
        },
        2: {
            "alina": "截止当天傍晚才提交，节奏偏紧，建议提前一天动笔。",
            "codeninja": "代码能通过主要用例，但变量命名随意（p/prev 混用），空表返回值没有交代。",
            "profx": "概念复述基本正确，『为什么必须先保存 next』只答了一句，原理没有展开。",
            "comment": "思路是对的，但第二题答『函数调用栈』不如直接答『栈』准确；代码补一下空表说明和自测记录。",
        },
        3: {
            "alina": "本次作业有遗留问题，第二题概念记混，建议当天订正。",
            "codeninja": "用数组缓存再反向拼接，能出结果但额外空间 O(n)，不满足题目 O(1) 空间要求。",
            "profx": "把保存递归现场的结构答成了队列，栈（后进先出）与队列（先进先出）需要重新区分。",
            "comment": "第 2 题把『栈』写成了『队列』，订正概念后连同满足 O(1) 空间的迭代版一起重新提交。",
        },
    },
)

HOMEWORK_SPECS["demo-hw-db-index-join"] = HomeworkSpec(
    hw_id="demo-hw-db-index-join", subject="DB",
    title="SQL 多表查询与 B+ 树索引分析", topic="JOIN 条件与 B+ 树叶子节点",
    created=_d(6, 24), deadline=_d(7, 2),
    answers={
        1: {
            "q1": "叶子节点",
            "q2": "覆盖索引把查询需要的字段全部放进了索引的叶子节点，扫描索引即可返回结果，不需要再按主键回聚簇索引取整行，所以减少了回表。",
            "q3": "SELECT course_id, student_id, score\nFROM (\n  SELECT course_id, student_id, score,\n         ROW_NUMBER() OVER (PARTITION BY course_id ORDER BY score DESC) AS rn\n  FROM scores\n) t\nWHERE rn <= 3;",
        },
        2: {
            "q1": "叶子节点",
            "q2": "查询要的列都在索引里，查索引就够了，不用再回表去扫整行数据，具体机制说不清楚，大概是这个意思。",
            "q3": "SELECT course_id, student_id, score\nFROM (\n  SELECT course_id, student_id, score,\n         ROW_NUMBER() OVER (ORDER BY score DESC) AS rn\n  FROM scores\n) t\nWHERE rn <= 3;",
        },
        3: {
            "q1": "内部节点",
            "q2": "覆盖索引就是主键索引，因为主键覆盖了所有查询。",
            "q3": "SELECT course_id, student_id, score\nFROM scores\nGROUP BY course_id\nORDER BY score DESC\nLIMIT 3;",
        },
    },
    q_results={
        1: {"q1": True, "q2": True, "q3": True},
        2: {"q1": True, "q2": True, "q3": False},
        3: {"q1": False, "q2": False, "q3": False},
    },
    msgs={
        1: {
            "alina": "数据库专题第二次作业质量稳定，继续保持这个复习节奏。",
            "codeninja": "窗口函数 PARTITION BY 用法规范，SQL 书写清晰；建议对 course_id 建复合索引并说明理由。",
            "profx": "覆盖索引『免回表』的本质抓住了，B+ 树叶子链表与范围扫描的联系表述完整。",
            "comment": "Top-N 查询的窗口函数写法正确，覆盖索引解释到位。可以把执行计划验证的结果附在作业里。",
        },
        2: {
            "alina": "作业压着截止时间提交，建议把 SQL 练习挪到白天精力好的时段。",
            "codeninja": "窗口函数漏了 PARTITION BY course_id，得到的是全局前三名而不是每门课前三名。",
            "profx": "覆盖索引的大方向说对了，但『免回表』的因果链没有讲清，和主键索引的区别也混了。",
            "comment": "第 3 题窗口函数少了 PARTITION BY，仔细对比题目『每门课前三名』；覆盖索引建议对照课件 B+ 树示意图再梳理一遍。",
        },
        3: {
            "alina": "本次作业错误较多，索引部分需要回炉，建议先订正再往下学。",
            "codeninja": "GROUP BY + LIMIT 的写法既不分组取 Top-N 也无法保证正确性，SQL 基础需要补。",
            "profx": "B+ 树记录位置答成了内部节点，覆盖索引与主键索引的概念混淆。",
            "comment": "索引三题里概念题错了两道：B+ 树数据在叶子节点、覆盖索引是二级索引的一种。订正后用窗口函数重写第 3 题。",
        },
    },
)

HOMEWORK_SPECS["demo-hw-fe-reactive"] = HomeworkSpec(
    hw_id="demo-hw-fe-reactive", subject="FE",
    title="Vue 响应式系统 Proxy 与 Reflect", topic="Proxy receiver 与依赖收集",
    created=_d(6, 26), deadline=_d(6, 30),
    answers={
        1: {
            "q1": "修复 getter this 指向",
            "q2": "track；trigger",
            "q3": "function reactive(target) {\n  return new Proxy(target, {\n    get(target, key, receiver) {\n      track(target, key);\n      return Reflect.get(target, key, receiver);\n    },\n    set(target, key, value, receiver) {\n      const old = target[key];\n      const ok = Reflect.set(target, key, value, receiver);\n      if (ok && old !== value) trigger(target, key);\n      return ok;\n    }\n  });\n}",
        },
        2: {
            "q1": "修复 getter this 指向",
            "q2": "收集依赖；触发更新",
            "q3": "function reactive(target) {\n  return new Proxy(target, {\n    get(target, key) {\n      track(target, key);\n      return target[key];\n    },\n    set(target, key, value) {\n      target[key] = value;\n      trigger(target, key);\n      return true;\n    }\n  });\n}",
        },
        3: {
            "q1": "减少闭包",
            "q2": "trigger；track",
            "q3": "function reactive(target) {\n  return new Proxy(target, {\n    get(target, key) {\n      return target[key];\n    },\n    set(target, key, value) {\n      target[key] = value;\n      return true;\n    }\n  });\n}",
        },
    },
    q_results={
        1: {"q1": True, "q2": True, "q3": True},
        2: {"q1": True, "q2": True, "q3": True},
        3: {"q1": False, "q2": False, "q3": False},
    },
    msgs={
        1: {
            "alina": "前端专题作业按时完成，学习曲线把握平稳。",
            "codeninja": "receiver 和旧值判断这两个细节都保留了，依赖收集逻辑完整，代码质量不错。",
            "profx": "track/trigger 的时机解释准确，effect 嵌套场景可以再补充一句。",
            "comment": "最小 reactive 实现规范，新旧值比较避免了无谓触发。可以了解一下 WeakMap 嵌套存依赖的优化。",
        },
        2: {
            "alina": "作业完成时间比上一份晚，响应式这块卡了就早点问。",
            "codeninja": "实现能跑通基本场景，但 get/set 都没用 receiver，遇到 getter 继承场景会取错 this。",
            "profx": "track/trigger 用中文复述了一遍，考试要能落到术语本身；receiver 的作用说得含糊。",
            "comment": "基本对，但两处没说透：receiver 的价值、为什么 set 前要记录旧值。对照示例里的继承 getter 用例补一个说明。",
        },
        3: {
            "alina": "响应式专题明显没消化，建议看回放补笔记后再订正。",
            "codeninja": "set 里没有调 trigger，依赖永远收集了不更新，响应式实现不成立。",
            "profx": "receiver 的作用答错，track 与 trigger 的时机也写反了，概念需要重新梳理。",
            "comment": "这次作业三题都有硬伤：track/trigger 写反、get 里漏收集依赖。先把课件第 3 节过一遍再重做。",
        },
    },
)

HOMEWORK_SPECS["demo-hw-co-cache"] = HomeworkSpec(
    hw_id="demo-hw-co-cache", subject="CO",
    title="Cache 映射策略与缺失率分析", topic="Cache 直接映射与地址拆分",
    created=_d(6, 30), deadline=_d(6, 26),  # 库里 deadline 早于 createdAt（演示数据原样），按迟交处理
    answers={
        1: {
            "q1": "冲突缺失",
            "q2": "按 32 位地址、直接映射、64 行、块大小 16B 计算：offset = log2(16) = 4 位，index = log2(64) = 6 位，tag 取高 22 位。例：0x0000C120 的二进制低 10 位为 01_0001_0000，index = 0b010001 = 17，tag 为高 22 位 0x00030。",
        },
        2: {
            "q1": "冲突缺失",
            "q2": "块大小 16B 所以低 4 位是 offset，剩下的位里再分 index 和 tag，具体各占几位要看行数，这道题我按 64 行算的 index 是 6 位，tag 是剩下的位。",
        },
        3: {
            "q1": "TLB 失效",
            "q2": "tag 在最高位，index 在中间，offset 我按 8 位算的（一个块 8 字节），0x0000C120 的 index 是 0x12。",
        },
    },
    q_results={
        1: {"q1": True, "q2": True},
        2: {"q1": True, "q2": True},
        3: {"q1": False, "q2": False},
    },
    msgs={
        1: {
            "alina": "计组作业完成质量稳定，Cache 专题可以收尾了。",
            "codeninja": "位拆解过程完整，二进制到十六进制换算没有跳步，建议封装成函数复用。",
            "profx": "对三段划分（tag/index/offset）的原理表述准确，可直接映射与组相联的对比再展开一句更好。",
            "comment": "tag/index/offset 拆解完整。下次可以在答案里标注映射后的命中组号，方便复查。",
        },
        2: {
            "alina": "作业拖到迟交才补上，计组建议不要攒着。",
            "codeninja": "计算过程跳跃，中间的位数字母含义没写，复查起来吃力。",
            "profx": "思路方向对，但『为什么 index 位数由行数决定』没有说明，公式记忆不牢。",
            "comment": "方向对但过程含糊：offset/index/tag 各自由什么决定要写清楚（块大小→offset、行数→index）。把例题的二进制展开补上。",
        },
        3: {
            "alina": "Cache 专题这次失分明显，需要重点补弱。",
            "codeninja": "offset 位数按块大小算，你按 8 字节算成 3 位又写成 8 位，计算前后矛盾。",
            "profx": "直接映射最常见的缺失类型答成了 TLB 失效，概念混淆。",
            "comment": "冲突缺失是直接映射的典型问题，你选成了 TLB 失效；地址拆分重做一遍，offset 位数 = log2(块大小)。",
        },
    },
)

HOMEWORK_SPECS["hw-1783166758091-1aa25a4a"] = HomeworkSpec(
    hw_id="hw-1783166758091-1aa25a4a", subject="DS",
    title="二叉树", topic="二叉树遍历与队列层序",
    created=_d(7, 4), deadline=_d(7, 6),
    answers={1: {}, 2: {}, 3: {}},
    q_results={1: {}, 2: {}, 3: {}},
    msgs={
        1: {
            "alina": "周末前完成，作业节奏稳定。",
            "codeninja": "四种遍历的迭代实现都过了用例，层序遍历用队列标记层的写法标准。",
            "profx": "遍历序列与树结构的对应关系理解扎实。",
            "comment": "二叉树作业提交完整，四种遍历全部通过。层序遍历用 size 标记每层节点数的技巧掌握得不错。",
        },
        2: {
            "alina": "拖到截止当晚才提交，下次留出调试时间。",
            "codeninja": "遍历结果基本正确，中序迭代的栈退出条件写得绕，可以简化。",
            "profx": "前中后序的访问时机大致清楚，『左根右』这类口诀之外的原因没展开。",
            "comment": "结果对，但中序迭代的写法有冗余分支，参考课件标准写法简化一遍；说明部分太简略。",
        },
        3: {
            "alina": "本次作业未完全通过，遍历顺序需要重新核对。",
            "codeninja": "后序遍历把『左右根』实现成了『右左根』，两组用例未通过。",
            "profx": "对后序访问根节点的时机理解有偏差。",
            "comment": "后序遍历顺序写反了：是左→右→根。订正后连同递归版一起重新提交。",
        },
    },
)

HOMEWORK_SPECS["target-teacher-su-hw-ds-stack-queue"] = HomeworkSpec(
    hw_id="target-teacher-su-hw-ds-stack-queue", subject="DS",
    title="栈与队列基础概念随堂练习", topic="栈与队列访问规则",
    created=_d(7, 14), deadline=_d(7, 15),
    answers={
        1: {"q1": "后进先出", "q2": "先进先出（FIFO）"},
        2: {"q1": "后进先出", "q2": "FIFO"},
        3: {"q1": "先进先出", "q2": "后进先出"},
    },
    q_results={
        1: {"q1": True, "q2": True},
        2: {"q1": True, "q2": True},
        3: {"q1": False, "q2": False},
    },
    msgs={
        1: {
            "alina": "随堂练习完成迅速，基础概念巩固良好。",
            "codeninja": "作答简洁准确，无多余表述。",
            "profx": "栈与队列的访问规则表述规范。",
            "comment": "概念题全对。答题备注里补充循环队列判满条件的说明，看得出课后有延伸。",
        },
        2: {
            "alina": "随堂练习按时完成，正确率可以接受。",
            "codeninja": "作答正确，第二题只写了缩写 FIFO，建议带上中文全称。",
            "profx": "概念正确，表述偏简，术语完整性一般。",
            "comment": "全对。第二题只写 FIFO 略显省事，规范写法是『先进先出（FIFO）』。",
        },
        3: {
            "alina": "概念题全错，栈和队列完全没有区分开，课后必须补。",
            "codeninja": "两题答案写反，属于概念性错误而非笔误。",
            "profx": "栈（后进先出）与队列（先进先出）的规则记忆混乱。",
            "comment": "两题正好写反：栈是后进先出，队列是先进先出。用『弹夹/排队』各记一个场景，订正后重交。",
        },
    },
)

HOMEWORK_SPECS["target-teacher-su-hw-db-index"] = HomeworkSpec(
    hw_id="target-teacher-su-hw-db-index", subject="DB",
    title="B+ 树索引与覆盖索引小测", topic="B+ 树叶子节点与覆盖索引",
    created=_d(7, 14), deadline=_d(7, 16),
    answers={
        1: {"q1": "叶子节点", "q2": "覆盖索引"},
        2: {"q1": "叶子节点", "q2": "联合索引"},
        3: {"q1": "日志节点", "q2": "聚簇索引"},
    },
    q_results={
        1: {"q1": True, "q2": True},
        2: {"q1": True, "q2": False},
        3: {"q1": False, "q2": False},
    },
    msgs={
        1: {
            "alina": "数据库索引专题持续保持正确率，可以进入查询优化内容。",
            "codeninja": "概念转译准确，能结合例子说明。",
            "profx": "对 B+ 树结构与索引命中路径的理解稳定。",
            "comment": "全对。结合上次作业的覆盖索引解释，这块知识已经形成闭环。",
        },
        2: {
            "alina": "按时完成，有一处概念需要澄清。",
            "codeninja": "第一题正确，第二题答成了联合索引，两者不是一回事。",
            "profx": "覆盖索引的定义（查询字段都能从索引取得）记忆不牢。",
            "comment": "第二题应为『覆盖索引』：判断标准是查询字段能否全部从索引取得，和是不是联合索引无关。",
        },
        3: {
            "alina": "索引专题概念错误集中，建议回看课件再做一遍。",
            "codeninja": "两个概念题均错误，随机选择痕迹明显。",
            "profx": "B+ 树节点分工与覆盖索引定义都没有掌握。",
            "comment": "B+ 树真实记录在叶子节点（内部节点只放索引键）；能免回表的叫覆盖索引。两个概念订正后重做。",
        },
    },
)

HOMEWORK_SPECS["target-teacher-su-hw-python-basic"] = HomeworkSpec(
    hw_id="target-teacher-su-hw-python-basic", subject="PY",
    title="Python 列表与字典基础题", topic="字典哈希查找与列表推导式",
    created=_d(7, 14), deadline=_d(7, 17),
    answers={
        1: {"q1": "dict", "q2": "方括号 []"},
        2: {"q1": "dict", "q2": "[]"},
        3: {"q1": "set", "q2": "圆括号 ()"},
    },
    q_results={
        1: {"q1": True, "q2": True},
        2: {"q1": True, "q2": True},
        3: {"q1": False, "q2": False},
    },
    msgs={
        1: {
            "alina": "Python 基础练习正确率 100%，节奏良好。",
            "codeninja": "作答准确，主动补充了 dict 按键查找 O(1) 的原因说明。",
            "profx": "对哈希查找复杂度的理解到位。",
            "comment": "基础扎实。dict 按键查找 O(1) 的原因（哈希表）在答案里主动做了说明，很好。",
        },
        2: {
            "alina": "练习按时完成，正确率可以。",
            "codeninja": "全对，作答偏简，没有展开说明。",
            "profx": "结论正确，原理层面没有体现。",
            "comment": "全对。下次把『为什么 dict 查找快』用一句话带上，体现理解而不是记忆。",
        },
        3: {
            "alina": "Python 基础需要补，两个概念都选错了。",
            "codeninja": "set 不能按键值对查找；列表推导式用方括号不是圆括号（圆括号是生成器）。",
            "profx": "容器类型的适用场景与推导式语法都混淆了。",
            "comment": "按键快速查找用 dict；列表推导式是方括号 []，圆括号是生成器表达式。两个点记到错题本。",
        },
    },
)

HOMEWORK_SPECS["target-teacher-su-hw-network-http"] = HomeworkSpec(
    hw_id="target-teacher-su-hw-network-http", subject="NET",
    title="HTTP 状态码与请求方法练习", topic="HTTP 状态码与 REST 方法",
    created=_d(7, 14), deadline=_d(7, 18),
    answers={
        1: {"q1": "资源未找到", "q2": "POST"},
        2: {"q1": "资源未找到", "q2": "PUT"},
        3: {"q1": "未认证", "q2": "GET"},
    },
    q_results={
        1: {"q1": True, "q2": True},
        2: {"q1": True, "q2": False},
        3: {"q1": False, "q2": False},
    },
    msgs={
        1: {
            "alina": "网络专题练习按时完成，正确率稳定。",
            "codeninja": "状态码语义理解准确。",
            "profx": "REST 语义与请求方法的对应关系表述正确。",
            "comment": "全对。对 401 与 404 的区别在备注里做了区分说明，继续保持。",
        },
        2: {
            "alina": "按时完成，一处方法语义需要注意。",
            "codeninja": "状态码正确；创建资源答 PUT，REST 语义里常规创建用 POST。",
            "profx": "POST/PUT 的幂等性区别没有掌握。",
            "comment": "第二题常规答案是 POST：PUT 多用于整体替换且幂等，POST 用于创建。把幂等性这个区别记下来。",
        },
        3: {
            "alina": "网络基础概念错误较多，需要系统补一遍。",
            "codeninja": "404 与 401 混淆；GET 不能携带创建语义，答题像在凑选项。",
            "profx": "常见状态码（2xx/4xx）与请求方法语义均未掌握。",
            "comment": "404 = 资源未找到，401 = 未认证，别混；创建资源用 POST。建议把 2xx/4xx 常见码抄一遍。",
        },
    },
)

HOMEWORK_SPECS["target-teacher-su-hw-ai-attention"] = HomeworkSpec(
    hw_id="target-teacher-su-hw-ai-attention", subject="AI",
    title="Attention 机制选择与填空", topic="注意力缩放与 QKV",
    created=_d(7, 14), deadline=_d(7, 19),
    answers={
        1: {"q1": "避免 Softmax 过饱和", "q2": "QKV"},
        2: {"q1": "避免 Softmax 过饱和", "q2": "Q K V"},
        3: {"q1": "减少参数量", "q2": "KV"},
    },
    q_results={
        1: {"q1": True, "q2": True},
        2: {"q1": True, "q2": True},
        3: {"q1": False, "q2": False},
    },
    msgs={
        1: {
            "alina": "对上次 Attention 薄弱点完成了针对性补强。",
            "codeninja": "概念选择正确，公式复查通过。",
            "profx": "QKV 各自的作用表述清楚，softmax 饱和问题理解到位。",
            "comment": "全对。相比上次 milestone 作业，缩放因子的理解这次理顺了，能看到进步。",
        },
        2: {
            "alina": "按时完成，公式部分仍需巩固。",
            "codeninja": "选择正确；填空写法松散（Q K V 加空格），规范写法 QKV。",
            "profx": "缩放因子作用正确，但『为什么除以 sqrt(d_k) 而不是 d_k』没有展开。",
            "comment": "基本对。缩放因子解释再进一步：点积随维度增大而增大，除以 sqrt(d_k) 把方差拉回 1 量级，防止 softmax 梯度消失。",
        },
        3: {
            "alina": "Attention 专题概念错误集中，建议重看对应章节视频。",
            "codeninja": "缩放因子作用选成减少参数量，QKV 少写了 Q。",
            "profx": "缩放目的（防 softmax 过饱和）与 QKV 三元组均未掌握。",
            "comment": "两题都有问题：除以 sqrt(d_k) 是为了让点积不过大、softmax 不饱和；Q/K/V 三个都要写全。订正后重交。",
        },
    },
)

HOMEWORK_SPECS["target-teacher-su-hw-software-test"] = HomeworkSpec(
    hw_id="target-teacher-su-hw-software-test", subject="SE",
    title="单元测试与 Pull Request Review", topic="单元测试目标与 PR 规范",
    created=_d(7, 14), deadline=_d(7, 20),
    answers={
        1: {"q1": "验证最小功能单元行为", "q2": "风险点"},
        2: {"q1": "验证最小功能单元行为", "q2": "影响范围"},
        3: {"q1": "替代所有人工测试", "q2": "测试范围"},
    },
    q_results={
        1: {"q1": True, "q2": True},
        2: {"q1": True, "q2": True},
        3: {"q1": False, "q2": False},
    },
    msgs={
        1: {
            "alina": "工程实践专题与团队项目经验形成了联动。",
            "codeninja": "对最小功能单元边界的把握准确，测试粒度设计合理。",
            "profx": "单元测试目标的表述无歧义，PR 规范理解完整。",
            "comment": "全对。结合团队项目 PR 写的自测说明很规范，『变更范围/自测结果/风险点』三段式用起来了。",
        },
        2: {
            "alina": "按时完成，PR 规范表述可以更标准。",
            "codeninja": "概念正确；第二题答案『影响范围』可用但不如『风险点』贴合模板。",
            "profx": "单元测试目标正确，PR 三要素记忆略有偏差。",
            "comment": "基本对。PR 三要素标准说法是变更范围、自测结果、风险点，你写的『影响范围』意思接近但建议统一术语。",
        },
        3: {
            "alina": "软件工程概念偏差大，需要从课件第 1 章补起。",
            "codeninja": "单元测试不可能替代所有人工测试，概念题选错。",
            "profx": "对单元测试定位（最小功能单元）与 PR 规范都没有掌握。",
            "comment": "单元测试的核心是验证最小功能单元，不是替代人工测试；PR 第三要素是风险点。两个概念订正后重做。",
        },
    },
)

HOMEWORK_SPECS["target-teacher-su-hw-os-process"] = HomeworkSpec(
    hw_id="target-teacher-su-hw-os-process", subject="OS",
    title="进程线程与同步互斥练习", topic="线程共享资源与同步机制",
    created=_d(7, 14), deadline=_d(7, 21),
    answers={
        1: {"q1": "地址空间", "q2": "信号量"},
        2: {"q1": "地址空间", "q2": "信号量（semaphore）"},
        3: {"q1": "独立页表", "q2": "原子指令"},
    },
    q_results={
        1: {"q1": True, "q2": True},
        2: {"q1": True, "q2": True},
        3: {"q1": False, "q2": False},
    },
    msgs={
        1: {
            "alina": "操作系统概念题正确率保持高位。",
            "codeninja": "竞态举例恰当，体现了工程直觉。",
            "profx": "互斥锁与信号量的适用差异表述清楚。",
            "comment": "全对。线程共享地址空间带来的同步问题，答案里举了计数器竞态的例子，理解到位。",
        },
        2: {
            "alina": "按时完成，正确率稳定。",
            "codeninja": "作答正确，第二题带了英文备注，习惯不错。",
            "profx": "概念正确，互斥锁/信号量差异的一句解释可以补上。",
            "comment": "全对。补一句『互斥锁保证互斥访问，信号量还能控制资源数目』会更完整。",
        },
        3: {
            "alina": "操作系统专题概念混乱，进程/线程边界没分清。",
            "codeninja": "线程不拥有独立页表（共享进程地址空间）；保护临界区常规答信号量。",
            "profx": "进程与线程的资源归属关系理解错误。",
            "comment": "线程共享的是进程的地址空间，不是独立页表；临界区保护常见机制是互斥锁和信号量。订正后重交。",
        },
    },
)

HOMEWORK_SPECS["target-teacher-su-hw-frontend-vue"] = HomeworkSpec(
    hw_id="target-teacher-su-hw-frontend-vue", subject="FE",
    title="Vue 响应式原理基础练习", topic="Vue3 Proxy 与 track/trigger",
    created=_d(7, 14), deadline=_d(7, 22),
    answers={
        1: {"q1": "Proxy", "q2": "trigger"},
        2: {"q1": "Proxy 对象", "q2": "trigger"},
        3: {"q1": "defineProperty", "q2": "update"},
    },
    q_results={
        1: {"q1": True, "q2": True},
        2: {"q1": True, "q2": True},
        3: {"q1": False, "q2": False},
    },
    msgs={
        1: {
            "alina": "前端响应式专题完成闭环，可进入组件化内容。",
            "codeninja": "track/trigger 概念转译准确无误。",
            "profx": "对 Vue 3 响应式演进（defineProperty → Proxy）的动因理解到位。",
            "comment": "全对。与之前 reactive 手写实现呼应，Proxy 拦截与依赖收集已经掌握。",
        },
        2: {
            "alina": "按时完成，术语可以再精确。",
            "codeninja": "答案正确，『Proxy 对象』的写法可以直接写 Proxy。",
            "profx": "概念正确，与 defineProperty 时代的对比没提。",
            "comment": "全对。补一句 Vue 2 用 defineProperty、Vue 3 换 Proxy 的原因（数组/新增属性监听），答案更完整。",
        },
        3: {
            "alina": "前端响应式概念还停留在 Vue 2，需要更新。",
            "codeninja": "Vue 3 响应式基于 Proxy 不是 defineProperty；触发更新叫 trigger 不是 update。",
            "profx": "响应式演进脉络没有跟上。",
            "comment": "Vue 3 用 Proxy 实现响应式，触发更新叫 trigger。把 Vue 2/3 响应式差异整理成一页笔记。",
        },
    },
)

DAILY_HOMEWORK_ORDER = sorted(HOMEWORK_SPECS.values(), key=lambda spec: spec.deadline)


# ---------------------------------------------------------------------------
# 考试规格（3 场已开考的真实考试；ai-stage 状态 scheduled 未开考，不用）
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ExamSpec:
    exam_id: str
    title: str
    exam_day: date
    has_objective: bool
    has_programming: bool


EXAM_SPECS: dict[str, ExamSpec] = {
    "demo-exam-ds-midterm": ExamSpec("demo-exam-ds-midterm", "数据结构期中综合考试", _d(6, 25), True, True),
    "demo-exam-db-closed": ExamSpec("demo-exam-db-closed", "数据库系统原理闭卷测验", _d(6, 28), True, False),
    "demo-exam-code-practical": ExamSpec("demo-exam-code-practical", "计算机程序设计上机考试", _d(7, 1), False, True),
}

EXAM_SUMMARIES: dict[str, dict[int, str]] = {
    "demo-exam-ds-midterm": {
        1: "客观题扣分集中在哈希冲突处理一题；编程题链表反转一遍过，二叉树层序最后十分钟调通。",
        2: "客观题链表和栈的部分扣了两题，KMP 的 next 数组没算完；编程题做出两道半，最后一题超时。",
        3: "客观题图和排序的概念题混了几道；编程题完整做出的只有一道，其余有思路但没调通。",
    },
    "demo-exam-db-closed": {
        1: "范式判断基本全对，扣分集中在可串行化调度的冲突边判定。",
        2: "B+ 树与索引题答得尚可，事务隔离级别有两题记混，封锁协议的推导没有写完。",
        3: "索引类型混淆丢分较多，隔离级别基本靠猜；后半段大题空了两小问。",
    },
    "demo-exam-code-practical": {
        1: "四道编程题过三道：两数之和用哈希一遍过，LRU 用 Map 写完还剩 15 分钟检查。",
        2: "编程题过两道半：括号匹配一次过，LRU 的 get 写对了 put 忘了更新顺序，最后一题只过一半用例。",
        3: "编程题完整过一道半：第一题边界写错调了半小时，LRU 没来得及写完，交卷时还有用例没跑。",
    },
}


# ---------------------------------------------------------------------------
# 错题池（schema 对齐 target-23001020119-mistake-01）
# ---------------------------------------------------------------------------

MISTAKE_POOL: list[dict[str, Any]] = [
    {
        "questionId": "class-mq-01", "questionType": "概念题",
        "questionTitle": "循环队列判满条件 (rear+1)%N==front 与 size 变量的取舍",
        "studentAnswer": "判满用 rear==front，判空用 (rear+1)%N==front，两个条件反了也能过。",
        "correctAnswer": "牺牲一格方案：rear 的下一个位置是 front 时判满，即 (rear+1)%capacity==front；front==rear 判空。或者维护 size 变量区分空满。",
        "errorReason": "把判空和判满的条件写反，循环队列下标取模的边界没有真正理解。",
        "knowledgeTags": ["队列", "取模运算"],
        "subject": "数据结构与算法", "sourceTitle": "数据结构期中综合考试",
    },
    {
        "questionId": "class-mq-02", "questionType": "概念题",
        "questionTitle": "B+ 树真实数据记录保存在哪种节点",
        "studentAnswer": "内部节点和叶子节点都存数据，这样查询更快。",
        "correctAnswer": "B+ 树内部节点只存索引键用于导航，真实记录（或记录指针）全部在叶子节点，叶子节点间用链表串联支持范围扫描。",
        "errorReason": "把 B+ 树与 B 树混淆：B 树所有节点都可能存数据，B+ 树只有叶子存。",
        "knowledgeTags": ["B+ 树", "数据库索引"],
        "subject": "数据库系统原理", "sourceTitle": "数据库系统原理闭卷测验",
    },
    {
        "questionId": "class-mq-03", "questionType": "概念题",
        "questionTitle": "覆盖索引为什么能减少回表",
        "studentAnswer": "覆盖索引就是主键索引，查主键当然不用回表。",
        "correctAnswer": "覆盖索引指查询所需字段全部包含在二级索引的叶子节点中，扫描索引即可返回结果，无需按主键回聚簇索引取整行。",
        "errorReason": "把覆盖索引等同于聚簇索引/主键索引，忽略『查询字段是否都在索引里』这一判断标准。",
        "knowledgeTags": ["覆盖索引", "回表"],
        "subject": "数据库系统原理", "sourceTitle": "SQL 多表查询与 B+ 树索引分析",
    },
    {
        "questionId": "class-mq-04", "questionType": "编程题",
        "questionTitle": "手写 reactive 时 get/set 的正确拦截写法",
        "studentAnswer": "get 里直接 return target[key]，set 里 target[key]=value 就行，效果一样。",
        "correctAnswer": "get 应使用 Reflect.get(target, key, receiver) 修复 getter 的 this 指向；set 应在更新前后比较旧值并调用 trigger 触发依赖更新。",
        "errorReason": "没有传 receiver，继承 getter 场景会取错 this；set 里漏了 trigger，响应式更新不会发生。",
        "knowledgeTags": ["Vue3", "Proxy", "Reflect"],
        "subject": "高级前端程序设计", "sourceTitle": "Vue 响应式系统 Proxy 与 Reflect",
    },
    {
        "questionId": "class-mq-05", "questionType": "计算题",
        "questionTitle": "直接映射 Cache 地址的 tag/index/offset 位拆分",
        "studentAnswer": "offset 我按 8 位算的，index 取地址中间 8 位，tag 是剩下的。",
        "correctAnswer": "offset 位数 = log2(块大小)，index 位数 = log2(行数)，tag 取地址高位剩余部分；如 16B 块、64 行的 32 位地址为 4+6+22。",
        "errorReason": "offset/index 位数应由块大小与行数决定，而不是固定 8 位，位拆分公式记忆错误。",
        "knowledgeTags": ["Cache", "地址拆分"],
        "subject": "计算机组成原理", "sourceTitle": "Cache 映射策略与缺失率分析",
    },
    {
        "questionId": "class-mq-06", "questionType": "概念题",
        "questionTitle": "Scaled Dot-Product Attention 除以 sqrt(d_k) 的目的",
        "studentAnswer": "为了减少注意力矩阵的参数量，让模型更小。",
        "correctAnswer": "点积随维度增大而变大，过大输入会让 softmax 进入饱和区、梯度消失；除以 sqrt(d_k) 把方差拉回 1 量级，保持梯度稳定。",
        "errorReason": "缩放因子作用于数值分布而非参数量，概念张冠李戴。",
        "knowledgeTags": ["Attention", "Softmax"],
        "subject": "人工智能技术基础", "sourceTitle": "Attention 机制选择与填空",
    },
    {
        "questionId": "class-mq-07", "questionType": "概念题",
        "questionTitle": "HTTP 401 与 404 状态码的语义区分",
        "studentAnswer": "404 是服务器错误，401 是请求格式不对。",
        "correctAnswer": "404 表示资源未找到（客户端 URL 对应资源不存在）；401 表示未认证（缺少或无效的身份凭证）；500 才是服务器内部错误。",
        "errorReason": "把 404 当成 5xx 类错误，401 与 400 的语义混用。",
        "knowledgeTags": ["HTTP", "状态码"],
        "subject": "计算机网络", "sourceTitle": "HTTP 状态码与请求方法练习",
    },
    {
        "questionId": "class-mq-08", "questionType": "概念题",
        "questionTitle": "信号量与互斥锁保护临界区的差异",
        "studentAnswer": "两个是一个东西，都是加锁，名字不同而已。",
        "correctAnswer": "互斥锁保证对临界区的互斥访问（0/1）；信号量还可表示资源数目，支持 P/V 操作实现同步与互斥，计数可大于 1。",
        "errorReason": "忽略信号量的计数语义与同步能力，把两者完全等同。",
        "knowledgeTags": ["操作系统", "同步互斥"],
        "subject": "操作系统", "sourceTitle": "进程线程与同步互斥练习",
    },
    {
        "questionId": "class-mq-09", "questionType": "编程题",
        "questionTitle": "Python 二维 dp 数组的正确初始化",
        "studentAnswer": "dp = [[0] * n] * m，简洁好用。",
        "correctAnswer": "* m 复制的是同一个内层列表的引用，应使用列表推导 dp = [[0] * n for _ in range(m)]，否则改动一行会连带所有行。",
        "errorReason": "浅拷贝语义没掌握，乘法复制嵌套列表会共享引用。",
        "knowledgeTags": ["Python", "浅拷贝"],
        "subject": "Python 程序设计", "sourceTitle": "Python 列表与字典基础题",
    },
    {
        "questionId": "class-mq-10", "questionType": "编程题",
        "questionTitle": "迭代反转单链表时 next 指针的备份时机",
        "studentAnswer": "先 curr.next = prev 再取 next，少一行代码。",
        "correctAnswer": "必须先保存 next = curr.next，再修改 curr.next = prev，否则后续节点指针被覆盖导致断链。",
        "errorReason": "指针修改顺序错误导致链表断裂，属于链表操作高频失误。",
        "knowledgeTags": ["链表", "指针操作"],
        "subject": "数据结构与算法", "sourceTitle": "链表指针更新与栈递归现场复盘",
    },
    {
        "questionId": "class-mq-11", "questionType": "编程题",
        "questionTitle": "窗口函数 Top-N 中 ROW_NUMBER 与 RANK 的选择",
        "studentAnswer": "随便用哪个，编号不一样而已，取前 3 名结果一样。",
        "correctAnswer": "并列分数时 ROW_NUMBER 会给不同序号（可能并列第 3 被挤掉），RANK 会保留并列；『每门课前三名』若含并列应用 RANK 或 DENSE_RANK 并明确规则。",
        "errorReason": "忽略并列场景下三个窗口函数的行为差异。",
        "knowledgeTags": ["SQL", "窗口函数"],
        "subject": "数据库系统原理", "sourceTitle": "SQL 多表查询与 B+ 树索引分析",
    },
    {
        "questionId": "class-mq-12", "questionType": "概念题",
        "questionTitle": "线程共享同一进程的哪类资源",
        "studentAnswer": "线程有自己的独立页表和栈，基本不共享什么。",
        "correctAnswer": "同进程内线程共享地址空间（代码段、数据段、堆）、打开的文件等资源；各自拥有独立的栈和寄存器上下文。",
        "errorReason": "把线程资源归属与进程混同，忽略共享地址空间正是需要同步机制的原因。",
        "knowledgeTags": ["操作系统", "线程"],
        "subject": "操作系统", "sourceTitle": "进程线程与同步互斥练习",
    },
]


# ---------------------------------------------------------------------------
# 论坛回复语料（仅追加到已有帖子，不新建帖子）
# ---------------------------------------------------------------------------

POST_REPLY_BANK: dict[str, list[str]] = {
    "demo-post-bplus-leaf": [
        "课上老师画的那个目录/内容区的比喻和你说的一致，我后来就靠这个记：内部节点管导航，叶子节点管存数据。",
        "补充一个易错点：B 树内部节点也能存数据，考试别和 B+ 树记混了，我上周就栽在这。",
        "mark，正好期末复习到索引这章，顺着楼主的思路把范围查询串叶子节点那段又过了一遍。",
    ],
    "demo-post-two-sum-map": [
        "同感先查再写最稳，我一开始边写边查，重复数字直接给我返回了两倍索引。",
        "这题我面试被追问过：为什么不能用双重循环，复杂度差在哪，建议大家把 O(n) 和 O(n^2) 的对比也记一下。",
        "谢谢楼主，我一直是先放进去再找，看完才反应过来要先找再放，差一个判断顺序。",
    ],
    "demo-post-pr-review": [
        "我们组也吃过这个亏，后来 PR 模板里固定加了异常码和空数据两项，漏一项队长直接打回。",
        "学到了，之前自测只测 happy path，验收的时候空列表直接 500，当场社死。",
        "补充一点：mock 数据别只造一两条，边界（0 条、满页、越界页）都造一组，review 的时候说服力完全不一样。",
    ],
    "demo-post-reactive-receiver": [
        "receiver 这个参数我之前也一直忽略，直到写继承 getter 的时候才发现 this 指向不对，楼主这个例子很直观。",
        "看完去手敲了一遍，不传 receiver 的时候 getter 里的 this 是原始对象，代理就白做了。",
        "这个帖子收藏了，正好下周要交手写 reactive 的作业，先来这里对齐概念。",
    ],
    "demo-post-attention-dim": [
        "我的记法是 Q 和 K 算相似度（n×n），再乘 V 回到 n×d_v，把每一步的行列标出来就不会错。",
        "同求更直观的记法，我每次都靠背，一到推导题就露馅。",
        "分享一个土办法：拿 3 个词的句子手算一遍小矩阵，算完对维度就有感觉了，比背公式管用。",
    ],
    "demo-post-cache-index": [
        "index 位数 = log2(行数)，offset = log2(块大小)，剩下是 tag，我拿这个公式套就很少错了。",
        "我也是老在 index 上翻车，后来把地址先转二进制再一段段切开标注，错误率才降下来。",
        "打卡，正好错题本里就有这条，再看一遍楼主的方法。",
    ],
    "demo-post-team-git": [
        "深有同感，我们组第一周各写各的分支名，合并的时候全靠猜，统一之后世界清净了。",
        "我们组用的 feature/xxx + fix/xxx 前缀，配合 PR 标题，翻历史记录方便很多。",
        "补一句：分支命名统一了，commit message 也要约束，不然后面 revert 找不到提交。",
    ],
    "demo-post-sql-window": [
        "窗口函数真的救大命，以前写每科前三名用三层嵌套自连接，改完执行计划直接少两个全表扫描。",
        "提醒一下用 ROW_NUMBER 还是 RANK 要想清楚并列分数，我上次就是没注意，第三名并列被挤掉了。",
        "学完这章才明白 GROUP BY 和 OVER 的区别，一个是折叠行一个是保留行，恍然大悟。",
    ],
    "demo-post-lru-cache": [
        "上机考试刚写过，直接 Map 的插入有序版本能过，但面试官一般会追问双向链表版。",
        "双向链表版我老是挂在头尾哨兵上，后来统一加 dummy 头尾节点才写顺。",
        "楼主这个取舍说到点子上了，课程 OJ 用 Map 够，真要考手写还是得练链表版。",
    ],
    "gen-post-1783245572283-0": [
        "红黑树我只记住了叔叔节点看颜色，红改色黑旋转，具体哪一步旋转每次都要重新推……",
        "同卡旋转，后来把插入的三种 case 画成一张流程图贴桌上，好多了。",
        "背个口诀：叔叔红就变色往上走，叔叔黑就旋转，LL/RR 单旋，LR/RL 双旋。",
    ],
    "gen-post-1783245572376-1": [
        "直观体现就是缓存行，数组顺序遍历比跳着访问快好几倍，计组实验跑过对比。",
        "全相联冲突小但硬件比较成本高，直接映射快但容易冲突缺失，工程里都是折中的组相联。",
        "看完这篇把缺失三分类（ compulsory/capacity/conflict ）又复习了一遍。",
    ],
    "gen-post-1783245572381-2": [
        "我的理解：Q 是查询、K 是被匹配的键、V 是内容，同一个矩阵等于自己跟自己匹配，区分度就没了。",
        "加上如果共用矩阵，点积相当于自相关，softmax 输出会很尖锐，注意力就退化了。",
        "mark，这块我quiz刚好错了，顺着评论区补一补。",
    ],
    "gen-post-1783245572386-3": [
        "DP 状态想不出来的时候，先猜状态是前 i 个/前 i-j 个的性质，再倒推转移，比硬想有效。",
        "我的笨办法：先写暴力递归，画调用树找重复子问题，状态定义自然就出来了。",
        "蓝桥杯 DP 我练了 30 道才有点手感，量变到质变是真的。",
    ],
    "ops-post-20260607-02-b66722": [
        "叔叔红的情况本质是把『双黑缺陷』往上抛，直到遇到黑节点能吸收为止，我是这么理解的。",
        "同问，课件那页我看三遍了还是晕，坐等大佬的白话版。",
        "变色是为了保持黑高，旋转是为了恢复 BST 性质，两个动作各司其职就好记了。",
    ],
    "ops-post-20260610-05-a32091": [
        "我的判断口诀：下一条指令马上要用就走 forwarding，用到之前还要等写回完成才 stall。",
        "load-use 冒险是必 stall 的，forwarding 救不了，这点考试老考。",
        "这道题我期中错了，评论区这个口诀比课件好记。",
    ],
    "ops-post-20260613-07-9a7226": [
        "先把经典背包问题手推一遍，状态和转移都是固定套路，比赛时先套模板再变形。",
        "状态定义从『最后一步』倒推：最后一步选或不选，选了之后子问题是什么。",
        "组队训练我们队 DP 全靠一个人扛，看来得全员补了。",
    ],
    "ops-post-20260619-12-2e3373": [
        "答辩可视化我们组的经验：演示链路一条线走通 + 一个核心亮点的深度动画，评委观感最好。",
        "花架子真不如把数据流转画清楚，我们去年吃了只堆 UI 的亏。",
        "mark，下个月中期汇报正好用上。",
    ],
    "ops-post-20260620-13-b79fe1": [
        "链表题我现在的 checklist：空表、单节点、头节点、尾节点，四个过一遍基本不会错。",
        "哑结点大法好，加了 dummy 之后头节点特判全部消失。",
        "同感，指针题的 bug 十个有八个在边界。",
    ],
    "ops-post-20260626-19-2751f2": [
        "因为直接置空会截断后面的探测序列，后来查找会误判不存在；要用墓碑标记删除。",
        "这个点我也错过，开放寻址的删除是真陷阱。",
        "难怪书上强调删除要特殊处理，原来是探测链的原因，懂了。",
    ],
    "ops-post-20260701-24-ac4a2e": [
        "commit message 里带上为什么改，比写改了什么更救命，三个月后回看全靠它。",
        "我们组还规定一个 PR 只做一件事，review 效率翻倍。",
        "深有体会，上周找一个历史提交翻了两小时。",
    ],
    "forum-showcase-post-01": [
        "顺着楼主的问题把 B+ 树那节又看了一遍，叶子链表就是为了范围扫描不用回到根，这下记牢了。",
        "期末考过类似的，答随机 I/O 减少这一点就给分了。",
        "mark，正好在复习索引章节。",
    ],
    "forum-showcase-post-03": [
        "递归出口我是先把最小子问题写出来（空/单节点），再写递归式，漏出口的情况少多了。",
        "推荐画调用树，出口漏没漏一目了然。",
        "同款困扰，出口和重复计算一起治：记忆化加上之后我的递归题正确率上来了。",
    ],
    "forum-showcase-post-09": [
        "DP 想不出状态就先写暴力，画递归树找重复子问题，亲测有效。",
        "打卡，最近按分类刷（背包/区间/线性），比乱刷有感觉。",
        "我们队去年省二的经验：DP 是第一优先级，性价比最高。",
    ],
    "target-23001020119-forum-post-01": [
        "迭代法最后 return prev 不是 curr 这个点，我 debug 了一晚上才反应过来，感谢整理。",
        "头插法确实稳，我期中就是头插一遍过的。",
        "收藏了，三种写法的坑总结得很全，正好复习周。",
    ],
    "target-23001020119-forum-post-04": [
        "这个坑我踩过一模一样的，dp 整列一起变，查了半天。",
        "copy.deepcopy 性能不行的时候，用 [row[:] for row in matrix] 也行。",
        "书上看一行字没感觉，踩一次坑终身难忘，真实。",
    ],
    "target-23001020119-forum-post-06": [
        "懒删除那条是精髓，我第一次写就想在堆里删元素。",
        "稠密图朴素 O(n^2) 反而快这个补充很关键，别无脑堆优化。",
        "模板借走了，下周队内训练正好练最短路。",
    ],
}

# 楼主占位（用于挑选回帖对象时排除楼主本人是回复者自己）
_POST_OWNER: dict[str, str] = {}


# ---------------------------------------------------------------------------
# 画像文本
# ---------------------------------------------------------------------------

PROFILE_TEXTS: dict[str, dict[str, str]] = {
    "diligent": {
        "cognitive": "目标驱动型，习惯先列计划再执行，偏好多刷题巩固",
        "error_pattern": "偶发失误集中在边界条件与术语记忆，订正后同类错误基本不再犯",
        "goal": "把数据结构和数据库基础打牢，期末争取前 30%，下学期想参加蓝桥杯",
        "background": "计算机科学与技术",
    },
    "normal": {
        "cognitive": "渐进理解型，先看例子再理解原理，容易眼高手低",
        "error_pattern": "概念题常『对但说不清』，编程题边界用例经常漏，二叉树递归出口容易写漏",
        "goal": "把数据结构补扎实，期末不挂科，争取中上水平",
        "background": "计算机科学与技术",
    },
    "procrastinator": {
        "cognitive": "间歇冲刺型，截止前效率高，平时容易松懈",
        "error_pattern": "赶工导致低级失误多：变量名抄错、忘写返回值，栈/队列、track/trigger 等概念容易混",
        "goal": "先改掉赶截止的毛病，作业不再拖到最后一晚，期末稳过",
        "background": "软件工程",
    },
    "uneven": {
        "cognitive": "偏科明显型，擅长的科目钻研得深，弱科容易放羊",
        "error_pattern": "弱科概念容易混（索引类型、隔离级别、状态码），强科基本不失手",
        "goal": "数据库是短板，暑假把索引和事务补一遍，期末目标 75+",
        "background": "软件工程",
    },
}


# ---------------------------------------------------------------------------
# 上下文（从 DB 或快照构建）
# ---------------------------------------------------------------------------

@dataclass
class StudentContext:
    students: list[dict[str, str]]  # {username, real_name, class_name}
    profiles: dict[str, dict[str, int]]  # username -> {knowledge, pace}
    homeworks: dict[str, dict[str, Any]]  # hw_id -> {title, type, createdAt}
    submission_hwids: dict[str, set[str]]  # username -> 已提交作业id集合（任意状态）
    submission_keys: set[str]
    attempt_examids: dict[str, set[str]]
    attempt_keys: set[str]
    mistake_keys: set[str]
    forum_posts: dict[str, dict[str, Any]]  # post_id -> {createdAt(str), replyIds: set}
    seed_markers: set[str] = field(default_factory=set)  # 已注入过本套数据的学生


def build_context_from_db(db: Session) -> StudentContext:
    from app.models.user_account import UserAccount
    from app.core.username_policy import is_valid_student_username

    store = JsonStore(db)
    students = [
        {"username": u.username, "real_name": u.real_name or u.username, "class_name": u.class_name or ""}
        for u in db.query(UserAccount).filter(UserAccount.role == "student").all()
        if is_valid_student_username(u.username)
    ]
    profiles = {
        p.user_id: {"knowledge": int(p.knowledge or 50), "pace": int(p.pace or 50)}
        for p in db.query(StudentProfile).all()
    }
    homeworks = {
        h["id"]: h for h in store.list_payloads("homework", "homework")
    }
    submission_hwids: dict[str, set[str]] = {}
    submission_keys: set[str] = set()
    for sub in store.list_payloads("homework", "submission"):
        sid = str(sub.get("studentId") or "")
        hwid = str(sub.get("homeworkId") or "")
        if sid:
            submission_hwids.setdefault(sid, set()).add(hwid)
        submission_keys.add(str(sub.get("id") or ""))
    attempt_examids: dict[str, set[str]] = {}
    attempt_keys: set[str] = set()
    for att in store.list_payloads("exams", "attempt"):
        sid = str(att.get("studentId") or "")
        eid = str(att.get("examId") or "")
        if sid:
            attempt_examids.setdefault(sid, set()).add(eid)
        attempt_keys.add(str(att.get("id") or ""))
    mistake_keys = {
        str(m.get("id") or "") for m in store.list_payloads("exams", "mistake")
    }
    forum_posts: dict[str, dict[str, Any]] = {}
    for post in store.list_payloads("forum", "post"):
        forum_posts[str(post.get("id"))] = {
            "createdAt": str(post.get("createdAt") or ""),
            "replyIds": {str(r.get("id")) for r in (post.get("replies") or [])},
        }
    seed_markers = {
        str(record.record_key)[len("class-sixdim-"):]
        for record in db.query(DomainRecord)
        .filter(
            DomainRecord.module == "analytics",
            DomainRecord.record_type == "seed_marker",
            DomainRecord.record_key.like("class-sixdim-%"),
        )
        .all()
    }
    return StudentContext(
        students=students, profiles=profiles, homeworks=homeworks,
        submission_hwids=submission_hwids, submission_keys=submission_keys,
        attempt_examids=attempt_examids, attempt_keys=attempt_keys,
        mistake_keys=mistake_keys, forum_posts=forum_posts,
        seed_markers=seed_markers,
    )


# ---------------------------------------------------------------------------
# 生成
# ---------------------------------------------------------------------------

@dataclass
class GeneratedData:
    submissions: list[dict[str, Any]] = field(default_factory=list)  # payload 含 id/studentId
    exam_attempts: list[dict[str, Any]] = field(default_factory=list)
    mistakes: list[dict[str, Any]] = field(default_factory=list)
    profile_updates: dict[str, dict[str, Any]] = field(default_factory=dict)
    forum_replies: list[dict[str, Any]] = field(default_factory=list)  # {postId, reply}
    markers: list[str] = field(default_factory=list)  # 已处理学生（幂等标记）
    stats: dict[str, Any] = field(default_factory=dict)


def _ts(d: date, rng: random.Random, persona: str, deadline_day: bool = False) -> str:
    """晚间为主、周末下午也有的提交时间；截止日当天改为白天（10:00-17:29），
    避免晚间时刻越过当日 18:00 类截止线造成"全班迟交"的假象。"""
    if deadline_day:
        hour = rng.randint(10, 17)
        minute = rng.randint(0, 29) if hour == 17 else rng.randint(0, 59)
        return datetime.combine(d, time(hour, minute), tzinfo=CHINA_TZ).isoformat()
    if d.weekday() >= 5 and rng.random() < 0.35:
        hour = rng.randint(14, 17)
        minute = rng.randint(0, 59)
    else:
        windows = {
            "diligent": (19, 0, 20, 30),
            "normal": (19, 40, 21, 40),
            "procrastinator": (21, 30, 23, 38),
            "uneven": (20, 0, 22, 0),
        }
        h1, m1, h2, m2 = windows[persona]
        start_minutes = h1 * 60 + m1
        end_minutes = h2 * 60 + m2
        total = rng.randint(start_minutes, end_minutes)
        hour, minute = divmod(total, 60)
    return datetime.combine(d, time(hour, minute), tzinfo=CHINA_TZ).isoformat()


def _persona_score_base(persona: str) -> dict[str, int]:
    return {
        "diligent": {"alina": 68, "codeninja": 70, "profx": 67},
        "normal": {"alina": 62, "codeninja": 64, "profx": 62},
        "procrastinator": {"alina": 58, "codeninja": 59, "profx": 58},
        "uneven": {"alina": 62, "codeninja": 63, "profx": 62},
    }[persona]


TIER_DELTA = {1: 3, 2: 0, 3: -4}


def _tier_weights(persona: str, subject: str, strong: str, weak: str) -> list[int]:
    if persona == "uneven":
        if subject == strong:
            return [50, 40, 10]
        if subject == weak:
            return [10, 35, 55]
        return [30, 45, 25]
    return {
        "diligent": [45, 40, 15],
        "normal": [30, 45, 25],
        "procrastinator": [20, 40, 40],
    }[persona]


def _pick_tier(rng: random.Random, weights: list[int]) -> int:
    return int(_weighted_choice(rng, [(str(i + 1), w) for i, w in enumerate(weights)]))


def _stable_hash(text: str) -> int:
    """跨进程稳定的哈希（Python 内建 hash 受 PYTHONHASHSEED 影响，不可用于幂等生成）。"""
    value = 2166136261
    for ch in text.encode("utf-8"):
        value = ((value ^ ch) * 16777619) & 0xFFFFFFFF
    return value


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _grade_letter(avg_score: int, rng: random.Random) -> str:
    if avg_score >= 71 and rng.random() < 0.6:
        return "B"
    if avg_score < 61 and rng.random() < 0.65:
        return "D"
    return "C"


def _submission_dates(specs: list[HomeworkSpec], persona: str, rng: random.Random) -> dict[str, date]:
    """按 deadline 顺序给选定作业排提交日期：相邻间隔 1-3 天，勤快的早交，
    拖延的压线甚至迟交（迟交可拖到 8 月上旬，整体铺开 6 月下旬-8 月中旬）。"""
    lead = {"diligent": (1, 3), "normal": (0, 2), "procrastinator": (0, 1), "uneven": (0, 2)}[persona]
    late_allowance = {"diligent": 2, "normal": 4, "procrastinator": 18, "uneven": 6}[persona]
    dates: dict[str, date] = {}
    prev: date | None = None
    for spec in specs:
        base = spec.deadline - timedelta(days=rng.randint(*lead))
        if persona == "procrastinator" and rng.random() < 0.45:
            base = spec.deadline + timedelta(days=rng.randint(1, 16))
        earliest = spec.created + timedelta(days=1)
        if prev is not None:
            earliest = max(earliest, prev + timedelta(days=1))
        candidate = max(base, earliest)
        latest = max(spec.deadline, spec.created) + timedelta(days=late_allowance)
        if candidate > latest:
            candidate = min(latest, max(earliest, spec.deadline))
        if candidate > CUTOFF_DATE:
            candidate = CUTOFF_DATE
        dates[spec.hw_id] = candidate
        prev = candidate
    return dates


def _gen_submission_payload(
    spec: HomeworkSpec, tier: int, scores: dict[str, int], grade: str,
    student: dict[str, str], submitted_at: str, msgs: dict[str, str],
) -> dict[str, Any]:
    submission_id = f"{spec.hw_id}:{student['username']}"
    return {
        "id": submission_id,
        "studentId": student["username"],
        "studentName": student["real_name"],
        "className": student["class_name"],
        "homeworkId": spec.hw_id,
        "homeworkTitle": spec.title,
        "submittedAt": submitted_at,
        "answers": dict(spec.answers[tier]),
        "file": f"{student['username']}-{spec.hw_id}.zip",
        "status": "graded",
        "grade": grade,
        "teacherComment": msgs["comment"],
        "diagnosis": {
            "scores": dict(scores),
            "alinaMsg": f"Alina诊断：{msgs['alina']}",
            "codeninjaMsg": f"CodeNinja诊断：{msgs['codeninja']}",
            "profxMsg": f"Prof. X诊断：{msgs['profx']}",
            "generatedAt": submitted_at,
            "source": "ai",
        },
        "classInsight": "本次作业共性问题已经同步到错题本和教师学情决策台。",
        "questionResults": dict(spec.q_results[tier]),
        "gradedAt": submitted_at,
    }


def _gen_exam_payload(
    exam: ExamSpec, band: int, student: dict[str, str], rng: random.Random,
) -> dict[str, Any]:
    band_delta = {1: 4, 2: 0, 3: -5}[band]
    attempt_id = f"{exam.exam_id}:{student['username']}"
    payload: dict[str, Any] = {
        "id": attempt_id,
        "examId": exam.exam_id,
        "examTitle": exam.title,
        "studentId": student["username"],
        "studentName": student["real_name"],
        "className": student["class_name"],
        "status": "graded",
        "submittedAt": None,
        "durationMinutes": None,
        "summary": EXAM_SUMMARIES[exam.exam_id][band],
    }
    obj = _clamp(31 + band_delta + rng.randint(-4, 4), 26, 38)  # /50 → 52%-76%
    if exam.has_objective:
        payload["objectiveScore"] = obj
        payload["maxObjectiveScore"] = 50
    if exam.has_programming:
        prog = _clamp(60 + band_delta + rng.randint(-8, 8), 48, 76)
        payload["programmingScore"] = prog
        payload["totalScore"] = _clamp(round(obj * 0.5 + prog * 0.5) if exam.has_objective else prog, 50, 76)
    else:
        payload["totalScore"] = _clamp(obj + rng.randint(0, 12), 52, 76)
    return payload


def _gen_mistake_payload(
    item: dict[str, Any], student: dict[str, str], idx: int,
    *, mastered: bool, wrong_count: int, rng: random.Random,
) -> dict[str, Any]:
    sid = student["username"]
    mistake_id = f"class-{sid}-mistake-{idx:02d}"
    created = _d(6, 25) + timedelta(days=rng.randint(0, 24))
    if created > CUTOFF_DATE - timedelta(days=2):
        created = CUTOFF_DATE - timedelta(days=rng.randint(3, 20))
    last_wrong = created + timedelta(days=rng.randint(0, 5))
    mastered_at = None
    review_count = 0
    review_log: list[str] = []
    if mastered:
        mastered_at = last_wrong + timedelta(days=rng.randint(4, 14))
        if mastered_at > CUTOFF_DATE:
            mastered_at = CUTOFF_DATE - timedelta(days=rng.randint(1, 5))
        review_count = rng.randint(2, 3)
        review_log = [
            f"学生于 {mastered_at.isoformat()} 完成订正并通过同类题自测，确认掌握（复习 {review_count} 轮）。"
        ]
    def _iso(d: date) -> str:
        hour = rng.randint(19, 22)
        minute = rng.randint(0, 59)
        return datetime.combine(d, time(hour, minute), tzinfo=CHINA_TZ).isoformat()

    payload = {
        "id": mistake_id,
        "studentId": sid,
        "studentName": student["real_name"],
        "className": student["class_name"],
        "examId": f"class-review-{sid}",
        "examTitle": "课后订正与错题复盘",
        "subject": item["subject"],
        "questionId": item["questionId"],
        "questionType": item["questionType"],
        "questionTitle": item["questionTitle"],
        "studentAnswer": item["studentAnswer"],
        "correctAnswer": item["correctAnswer"],
        "errorReason": item["errorReason"],
        "knowledgeTags": list(item["knowledgeTags"]),
        "wrongCount": wrong_count,
        "lastWrongAt": _iso(last_wrong),
        "mastered": mastered,
        "aiAnalysis": {
            "diagnosis": f"你的答案与正确思路的偏差在于：{item['errorReason']}",
            "concept": item["correctAnswer"],
            "practice": "先把正确结论抄进错题本，再完成 2 道同类题自测，隔 3 天复测一次。",
            "path": ["重看原题", "对比错误答案", "补边界清单", "完成同类题", "写入错题本"],
            "source": "seeded",
            "agentId": "agent_mistake_analyst",
            "agentName": "错题分析师",
            "knowledgeTags": list(item["knowledgeTags"]),
            "reviewLog": review_log,
            "masteredAt": _iso(mastered_at) if mastered_at else None,
        },
        "source": {"type": "homework", "title": item["sourceTitle"]},
        "createdAt": _iso(created),
        "updatedAt": _iso(mastered_at or last_wrong),
    }
    if mastered_at:
        payload["masteredAt"] = _iso(mastered_at)
        payload["reviewCount"] = review_count
    return payload


def _daily_count(persona: str, rng: random.Random) -> int:
    return {
        "diligent": rng.choice([10, 11]),
        "normal": rng.choice([9, 10]),
        "procrastinator": 9,
        "uneven": 10,
    }[persona]


def _b_extra_count(persona: str, rng: random.Random) -> int:
    return {"diligent": 5, "normal": 4, "procrastinator": 3, "uneven": 4}[persona]


def _reply_count(persona: str, rng: random.Random) -> int:
    return {
        "diligent": rng.choice([3, 4]),
        "normal": 3,
        "procrastinator": rng.choice([2, 3]),
        "uneven": 3,
    }[persona]


def _strong_weak_subjects(rng: random.Random) -> tuple[str, str]:
    subjects = ["DS", "DB", "FE", "CO", "PY", "NET", "AI", "SE", "OS"]
    strong = rng.choice(subjects)
    weak = rng.choice([s for s in subjects if s != strong])
    return strong, weak


def generate_class_students_data(context: StudentContext) -> GeneratedData:
    data = GeneratedData()
    by_username = {s["username"]: s for s in context.students}
    stats = {
        "protected": PROTECTED_USER,
        "classA": {"students": 0, "submissions": 0, "exams": 0, "mistakes": 0, "profilesCreated": 0},
        "classB": {"students": 0, "submissions": 0, "mistakes": 0, "replies": 0},
        "extraReplies": 0,
    }

    # ---- A 类：全量注入 ----
    for sid in A_CLASS_STUDENTS:
        student = by_username.get(sid)
        if not student or sid == PROTECTED_USER or sid in context.seed_markers:
            continue
        rng = random.Random(f"classA|{sid}")
        persona = persona_for(sid)
        strong, weak = _strong_weak_subjects(rng)
        stats["classA"]["students"] += 1

        # 1) 作业提交
        existing = context.submission_hwids.get(sid, set())
        pool = [spec for spec in DAILY_HOMEWORK_ORDER if spec.hw_id not in existing]
        count = min(_daily_count(persona, rng), len(pool))
        selected = sorted(rng.sample(pool, count), key=lambda s: s.deadline)
        dates = _submission_dates(selected, persona, rng)
        for spec in selected:
            weights = _tier_weights(persona, spec.subject, strong, weak)
            tier = _pick_tier(rng, weights)
            base = _persona_score_base(persona)
            delta = TIER_DELTA[tier]
            if persona == "uneven":
                delta += 6 if spec.subject == strong else (-6 if spec.subject == weak else 0)
            scores = {
                key: _clamp(base[key] + delta + rng.randint(-3, 3), 55, 78)
                for key in ("alina", "codeninja", "profx")
            }
            avg_score = sum(scores.values()) // 3
            grade = _grade_letter(avg_score, rng)
            submitted_at = _ts(dates[spec.hw_id], rng, persona, deadline_day=(dates[spec.hw_id] == spec.deadline))
            data.submissions.append(
                _gen_submission_payload(spec, tier, scores, grade, student, submitted_at, spec.msgs[tier])
            )
            stats["classA"]["submissions"] += 1

        # 2) 考试（2-3 场，至少一场含编程分）
        attempted = context.attempt_examids.get(sid, set())
        exam_pool = [e for e in EXAM_SPECS.values() if e.exam_id not in attempted]
        prog_pool = [e for e in exam_pool if e.has_programming]
        if prog_pool:
            chosen = [rng.choice(prog_pool)]
            others = [e for e in exam_pool if e not in chosen]
            extra_n = {"diligent": 2, "normal": rng.choice([1, 2]), "procrastinator": 1, "uneven": rng.choice([1, 2])}[persona]
            chosen += rng.sample(others, min(extra_n, len(others)))
        else:
            chosen = rng.sample(exam_pool, min(2, len(exam_pool)))
        for exam in chosen:
            band_weights = _tier_weights(persona, "XX", strong, weak)
            band = _pick_tier(rng, band_weights)
            payload = _gen_exam_payload(exam, band, student, rng)
            start_h = rng.randint(9, 10)
            start_m = rng.randint(5, 40)
            duration = {"demo-exam-ds-midterm": rng.randint(78, 95), "demo-exam-db-closed": rng.randint(62, 82), "demo-exam-code-practical": rng.randint(95, 135)}[exam.exam_id]
            end_total = start_h * 60 + start_m + duration
            eh, em = divmod(end_total, 60)
            payload["submittedAt"] = datetime.combine(exam.exam_day, time(eh, em), tzinfo=CHINA_TZ).isoformat()
            payload["durationMinutes"] = duration
            data.exam_attempts.append(payload)
            stats["classA"]["exams"] += 1

        # 3) 错题本（2-5 条，留 1-2 条未掌握）
        total_n = {"diligent": rng.choice([2, 3]), "normal": rng.choice([3, 4]), "procrastinator": rng.choice([4, 5]), "uneven": 3}[persona]
        unmastered_n = {"diligent": 1, "normal": 2, "procrastinator": rng.choice([2, 3]), "uneven": 2}[persona]
        items = rng.sample(MISTAKE_POOL, total_n)
        existing_keys = {k for k in context.mistake_keys if k.startswith(f"class-{sid}-mistake-")}
        idx = 0
        for pos, item in enumerate(items, start=1):
            idx = pos
            mistake_id = f"class-{sid}-mistake-{idx:02d}"
            while mistake_id in existing_keys:
                idx += 1
                mistake_id = f"class-{sid}-mistake-{idx:02d}"
            mastered = pos <= total_n - unmastered_n
            wrong_count = 1
            if not mastered and rng.random() < 0.45:
                wrong_count = 2
            data.mistakes.append(_gen_mistake_payload(item, student, idx, mastered=mastered, wrong_count=wrong_count, rng=rng))
            stats["classA"]["mistakes"] += 1

        # 4) 画像（60-70 带内；未掌握错题数已定，pace 不再抬高）
        knowledge = _clamp({"diligent": 70, "normal": 65, "procrastinator": 61, "uneven": 66}[persona] + rng.randint(-2, 3), 60, 72)
        pace = _clamp({"diligent": 65, "normal": 62, "procrastinator": 60, "uneven": 63}[persona] + rng.randint(-2, 2), 60, 68)
        texts = PROFILE_TEXTS[persona]
        data.profile_updates[sid] = {"knowledge": knowledge, "pace": pace, **texts}
        if sid not in context.profiles:
            stats["classA"]["profilesCreated"] += 1
        data.markers.append(sid)

    # ---- B 类：补交作业 + 错题 + 论坛回复 ----
    a_set = set(A_CLASS_STUDENTS) | {PROTECTED_USER}
    for student in context.students:
        sid = student["username"]
        if sid in a_set or sid in context.seed_markers:
            continue
        rng = random.Random(f"classB|{sid}")
        persona = persona_for(sid)
        strong, weak = _strong_weak_subjects(rng)
        stats["classB"]["students"] += 1

        existing = context.submission_hwids.get(sid, set())
        pool = [spec for spec in DAILY_HOMEWORK_ORDER if spec.hw_id not in existing]
        count = min(_b_extra_count(persona, rng), len(pool))
        selected = sorted(rng.sample(pool, count), key=lambda s: s.deadline)
        dates = _submission_dates(selected, persona, rng)
        for spec in selected:
            weights = _tier_weights(persona, spec.subject, strong, weak)
            tier = _pick_tier(rng, weights)
            base = _persona_score_base("normal")
            delta = TIER_DELTA[tier]
            if persona == "uneven":
                delta += 5 if spec.subject == strong else (-5 if spec.subject == weak else 0)
            scores = {
                key: _clamp(base[key] + delta + rng.randint(-3, 3), 60, 75)
                for key in ("alina", "codeninja", "profx")
            }
            grade = _grade_letter(sum(scores.values()) // 3, rng)
            submitted_at = _ts(dates[spec.hw_id], rng, persona, deadline_day=(dates[spec.hw_id] == spec.deadline))
            data.submissions.append(
                _gen_submission_payload(spec, tier, scores, grade, student, submitted_at, spec.msgs[tier])
            )
            stats["classB"]["submissions"] += 1

        # 错题：未掌握 1-2 条 + 少量已掌握（把专注度拉回真实带）
        unmastered_b = 1 + (1 if rng.random() < 0.45 else 0)
        extra_mastered = 1 if rng.random() < 0.6 else 0
        mistake_n = unmastered_b + extra_mastered
        items = rng.sample(MISTAKE_POOL, mistake_n)
        existing_keys = {k for k in context.mistake_keys if k.startswith(f"class-{sid}-mistake-")}
        idx = 0
        for pos, item in enumerate(items, start=1):
            idx = pos
            mistake_id = f"class-{sid}-mistake-{idx:02d}"
            while mistake_id in existing_keys:
                idx += 1
                mistake_id = f"class-{sid}-mistake-{idx:02d}"
            mastered = pos <= extra_mastered
            wrong_count = 1
            if not mastered and rng.random() < 0.4:
                wrong_count = 2
            data.mistakes.append(_gen_mistake_payload(item, student, idx, mastered=mastered, wrong_count=wrong_count, rng=rng))
            stats["classB"]["mistakes"] += 1

        # 论坛回复（已有帖子下，authorUsername=学号）
        reply_n = _reply_count(persona, rng)
        post_ids = [pid for pid in POST_REPLY_BANK if pid in context.forum_posts]
        picked = rng.sample(post_ids, min(reply_n, len(post_ids)))
        for seq, post_id in enumerate(picked, start=1):
            content_bank = POST_REPLY_BANK[post_id]
            content = content_bank[(_stable_hash(sid) % 97 + seq) % len(content_bank)]
            reply_id = f"class-{sid}-reply-{post_id}-{seq:02d}"
            post_created = context.forum_posts[post_id].get("createdAt") or ""
            low = date(2026, 7, 1)
            try:
                low = max(low, datetime.fromisoformat(post_created.replace("Z", "+08:00")).date() + timedelta(days=1))
            except ValueError:
                pass
            high = min(CUTOFF_DATE, low + timedelta(days=35))
            reply_date = low + timedelta(days=rng.randint(0, max(0, (high - low).days)))
            hour, minute = (rng.randint(14, 17) if reply_date.weekday() >= 5 and rng.random() < 0.3 else rng.randint(19, 22)), rng.randint(0, 59)
            data.forum_replies.append({
                "postId": post_id,
                "reply": {
                    "id": reply_id,
                    "author": student["real_name"],
                    "authorUsername": sid,
                    "avatar": f"/static/avatars/{sid}.jpg",
                    "isAi": False,
                    "content": content,
                    "createdAt": datetime.combine(reply_date, time(hour, minute), tzinfo=CHINA_TZ).isoformat(),
                    "likes": rng.randint(0, 3),
                },
            })
            stats["classB"]["replies"] += 1
        data.markers.append(sid)

    # ---- 谢晨希 / 谢生 论坛补回复 ----
    for sid in ("谢", "谢生"):
        student = by_username.get(sid)
        if not student or sid in context.seed_markers:
            continue
        rng = random.Random(f"forumBoost|{sid}")
        post_ids = [pid for pid in POST_REPLY_BANK if pid in context.forum_posts]
        picked = rng.sample(post_ids, min(3, len(post_ids)))
        for seq, post_id in enumerate(picked, start=1):
            content_bank = POST_REPLY_BANK[post_id]
            content = content_bank[(_stable_hash(sid) % 89 + seq) % len(content_bank)]
            reply_id = f"class-{sid}-reply-{post_id}-{seq:02d}"
            post_created = context.forum_posts[post_id].get("createdAt") or ""
            low = date(2026, 7, 5)
            try:
                low = max(low, datetime.fromisoformat(post_created.replace("Z", "+08:00")).date() + timedelta(days=1))
            except ValueError:
                pass
            high = min(CUTOFF_DATE, low + timedelta(days=35))
            reply_date = low + timedelta(days=rng.randint(0, max(0, (high - low).days)))
            hour = rng.randint(19, 22)
            minute = rng.randint(0, 59)
            data.forum_replies.append({
                "postId": post_id,
                "reply": {
                    "id": reply_id,
                    "author": student["real_name"],
                    "authorUsername": sid,
                    "avatar": f"/static/avatars/{sid}.jpg",
                    "isAi": False,
                    "content": content,
                    "createdAt": datetime.combine(reply_date, time(hour, minute), tzinfo=CHINA_TZ).isoformat(),
                    "likes": rng.randint(0, 2),
                },
            })
            stats["extraReplies"] += 1

    data.stats = stats
    return data


# ---------------------------------------------------------------------------
# 注入（幂等：固定 record_key upsert / 回复按 id 查重）
# ---------------------------------------------------------------------------

def apply_class_students_data(db: Session, data: GeneratedData) -> dict[str, Any]:
    store = JsonStore(db)
    for payload in data.submissions:
        store.upsert(
            "homework", "submission", payload["id"], payload,
            owner_id=payload["studentId"], status="graded",
        )
    for payload in data.exam_attempts:
        store.upsert(
            "exams", "attempt", payload["id"], payload,
            owner_id=payload["studentId"], status="graded",
        )
    for payload in data.mistakes:
        store.upsert(
            "exams", "mistake", payload["id"], payload,
            owner_id=payload["studentId"], status="active",
        )

    posts_touched: set[str] = set()
    for item in data.forum_replies:
        post_id = item["postId"]
        payload = store.get_payload("forum", "post", post_id)
        if not payload:
            continue
        replies = list(payload.get("replies") or [])
        reply = item["reply"]
        if any(str(r.get("id")) == reply["id"] for r in replies):
            continue
        replies.append(reply)
        payload["replies"] = replies
        payload["views"] = int(payload.get("views") or 0) + 3
        store.upsert("forum", "post", post_id, payload, owner_id="", status="active")
        posts_touched.add(post_id)

    for sid, fields in data.profile_updates.items():
        profile = db.query(StudentProfile).filter(StudentProfile.user_id == sid).first()
        if not profile:
            profile = StudentProfile(user_id=sid)
            db.add(profile)
        for key, value in fields.items():
            setattr(profile, key, value)
    db.commit()

    # 幂等标记：重跑时跳过已注入学生，保证"重跑结果一致、不产生重复行"
    for sid in data.markers:
        store.upsert(
            "analytics", "seed_marker", f"class-sixdim-{sid}",
            {
                "id": f"class-sixdim-{sid}",
                "seed": "class_students_sixdim",
                "version": 1,
                "studentId": sid,
                "markedAt": "2026-08-17T00:00:00+08:00",
            },
            owner_id=sid, status="done",
        )

    return {
        **data.stats,
        "forumPostsTouched": len(posts_touched),
        "totals": {
            "submissions": len(data.submissions),
            "examAttempts": len(data.exam_attempts),
            "mistakes": len(data.mistakes),
            "forumReplies": len(data.forum_replies),
            "profileUpdates": len(data.profile_updates),
        },
    }


def seed_class_students_sixdim_data(db: Session) -> dict[str, Any]:
    context = build_context_from_db(db)
    data = generate_class_students_data(context)
    return apply_class_students_data(db, data)
