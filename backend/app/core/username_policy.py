"""用户名与学号格式约束。

学情决策台的学生画像直接聚合 user_accounts 中所有学生账号，历史上
自动化测试（codex_*、BrowserDeepCheck、乱码用户名等）通过用户中心
接口静默建号，污染了班级画像。此模块统一约束：

- 学生用户名/学号：纯数字学号，或包含中文的姓名
- 教师用户名：中文/字母/数字/下划线/连字符，禁止乱码与标点垃圾
"""

import re

# 纯数字学号（现有学生的学号均为数字，如 23001020119）
NUMERIC_ID_RE = re.compile(r"^[0-9]{4,20}$")

# 学生姓名：中文、间隔号、字母、数字、下划线、连字符（单字姓氏如"谢"合法）
STUDENT_NAME_RE = re.compile(r"^[\u4e00-\u9fa5·0-9A-Za-z_\-]{1,30}$")

# 教师用户名：至少 2 位，中文/字母/数字/下划线/连字符，禁止乱码与标点垃圾
TEACHER_USERNAME_RE = re.compile(r"^[\u4e00-\u9fa5·A-Za-z0-9_\-]{2,30}$")

CHINESE_CHAR_RE = re.compile(r"[\u4e00-\u9fa5]")


def has_chinese(text: str | None) -> bool:
    return bool(CHINESE_CHAR_RE.search(text or ""))


def is_valid_student_username(username: str | None) -> bool:
    """学生用户名合法：纯数字学号，或包含中文的姓名（含单字姓氏）。

    用于注册校验与画像聚合过滤，排除 codex_*、testuser、?? 等
    不符合中文教学场景的账号。
    """
    username = (username or "").strip()
    if not username:
        return False
    if NUMERIC_ID_RE.match(username):
        return True
    return has_chinese(username) and bool(STUDENT_NAME_RE.match(username))


def is_valid_teacher_username(username: str | None) -> bool:
    """教师用户名合法：仅允许中文/字母/数字/下划线/连字符（2-30 位）。"""
    return bool(TEACHER_USERNAME_RE.match((username or "").strip()))
