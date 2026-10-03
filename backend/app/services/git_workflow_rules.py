"""
git_workflow_rules.py — 纯函数 Git 工作流规则校验器
不访问网络，便于单测。

规则码（见指导书 4.3）：
    PUSH_TO_DEFAULT_BRANCH     push 到配置的默认/保护分支（需核对 PR）  error
    BRANCH_NAME_INVALID        分支名不包含 feature/feat/fix/docs/test/hotfix  warn
    COMMIT_MESSAGE_TOO_SHORT   message 去空白 < 8 字符  warn
    COMMIT_MESSAGE_EMPTY       message 为空  error
    AUTHOR_UNMATCHED           作者未绑定 / unmatched  warn
    PR_BASE_NOT_DEFAULT        PR base 不是 defaultBranch  warn
    PR_HEAD_NAME_INVALID       PR head 分支命名不合规  warn
    MEMBER_NOT_IN_TEAM         作者的规范账号 ID 不在 memberProgress  warn
"""

from __future__ import annotations

from typing import Any

# 合规分支前缀
_VALID_BRANCH_PREFIXES = ("feature", "feat", "fix", "docs", "test", "hotfix")

# 严重等级对应扣分
_DEDUCT = {"error": 20, "warn": 10}


def _branch_name_valid(branch: str) -> bool:
    """检查分支名是否以合规前缀开头（不区分大小写）。"""
    b = branch.strip().lower()
    return any(b == p or b.startswith(f"{p}/") or b.startswith(f"{p}-") for p in _VALID_BRANCH_PREFIXES)


def _commit_message_check(message: str) -> str | None:
    """返回违规码或 None（无违规）。"""
    stripped = (message or "").strip()
    if not stripped:
        return "COMMIT_MESSAGE_EMPTY"
    if len(stripped) < 8:
        return "COMMIT_MESSAGE_TOO_SHORT"
    return None


def normalize_event_type(event_type: str) -> str:
    return "pull_request" if event_type.startswith("pull_request") else event_type


def branch_from_ref(value: str) -> str:
    value = str(value or "").strip()
    return value.removeprefix("refs/heads/")


def pr_branch(pr: dict[str, Any], side: str) -> str:
    data = pr.get(side) or {}
    value = data.get("ref") or data.get("label") or pr.get(f"{side}_branch") or ""
    return branch_from_ref(str(value).split(":", 1)[-1])


def _member_in_team(author: str, project: dict[str, Any]) -> bool:
    """Only stable account identifiers establish membership; display names do not."""
    members = project.get("memberProgress") or []
    for m in members:
        identifiers = {str(m.get(key) or "").strip() for key in ("id", "campusUserId", "username")}
        if author and author.strip() in identifiers:
            return True
    return False


def evaluate_git_workflow(
    *,
    event_type: str,
    payload: dict[str, Any],
    project: dict[str, Any],
    matched_member: dict[str, Any] | None = None,
    author_match_source: str = "",
) -> dict[str, Any]:
    """返回 workflowRuleResult（见指导书 4.1）。

    Parameters
    ----------
    event_type:
        "push" 或 "pull_request"
    payload:
        Gitea Webhook payload dict
    project:
        DomainRecord payload（含 repository / memberProgress 等字段）
    matched_member:
        match_campus_user_from_gitea_event 返回值（可选）；
        None 时默认 source=unmatched
    author_match_source:
        "matched" / "unmatched" / "" 三种值
    """
    from app.utils.datetime import format_chinese_datetime

    passed: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []

    event_type = normalize_event_type(event_type)
    repo = project.get("repository") or {}
    default_branch = str(repo.get("defaultBranch") or "main")

    def _add_violation(code: str, severity: str, message: str, hint: str, evidence: dict | None = None):
        violations.append({
            "code": code,
            "severity": severity,
            "message": message,
            "hint": hint,
            "evidence": evidence or {},
        })

    def _add_passed(code: str, message: str):
        passed.append({"code": code, "message": message})

    # ── push 事件校验 ────────────────────────────────────────────
    if event_type == "push":
        ref = str(payload.get("ref") or "")
        branch = branch_from_ref(ref)
        commits = payload.get("commits") or []

        # 规则: PUSH_TO_DEFAULT_BRANCH
        protected = set(repo.get("protectedBranches") or []) | {default_branch}
        if branch in protected:
            _add_violation(
                "PUSH_TO_DEFAULT_BRANCH", "error",
                f"检测到向受保护/默认分支 {branch} 的 push；仅凭消息或 parents 无法确认经过 PR 审核",
                f"请在功能分支开发，通过 Pull Request 合并到 {default_branch}；如为平台合并请核对 PR 记录",
                {"branch": branch, "defaultBranch": default_branch, "prVerification": "unavailable"},
            )
        else:
            # 规则: BRANCH_NAME_INVALID
            if _branch_name_valid(branch):
                _add_passed("BRANCH_NAME_INVALID", f"分支名 {branch} 符合 feature/fix/docs/test 约定")
            else:
                _add_violation(
                    "BRANCH_NAME_INVALID",
                    "warn",
                    f"分支名 {branch!r} 不符合 feature/feat/fix/docs/test/hotfix 约定",
                    "请使用 feature/xxx 或 fix/xxx 命名后再推送",
                    {"branch": branch},
                )

        # 规则: commit message 相关
        for commit in commits:
            if not isinstance(commit, dict):
                continue
            msg = str(commit.get("message") or "").strip()
            sha_short = str(commit.get("id") or "")[:8]
            code = _commit_message_check(msg)
            if code == "COMMIT_MESSAGE_EMPTY":
                _add_violation(
                    "COMMIT_MESSAGE_EMPTY",
                    "error",
                    f"commit {sha_short} 提交说明为空",
                    "每次提交必须有清晰的说明，例如 'fix: 修复空输入边界条件'",
                    {"sha": sha_short, "message": msg},
                )
            elif code == "COMMIT_MESSAGE_TOO_SHORT":
                _add_violation(
                    "COMMIT_MESSAGE_TOO_SHORT",
                    "warn",
                    f"commit {sha_short} 提交说明过短（{len(msg)} 字符），看不出改动目的",
                    "提交说明至少 8 个字符，用动词开头描述本次改动",
                    {"sha": sha_short, "message": msg, "length": len(msg)},
                )
            else:
                _add_passed("COMMIT_HAS_MESSAGE", f"commit {sha_short} 提交说明非空且满足长度约定")

        # 规则: AUTHOR_UNMATCHED
        member = matched_member or {}
        source = str(member.get("matchSource") or author_match_source or "unmatched")
        matched = bool(member.get("campusUserId")) and source not in ("unmatched", "")
        if not matched:
            _add_violation(
                "AUTHOR_UNMATCHED",
                "warn",
                "提交作者未能匹配到校园用户，可能未绑定 Gitea 账号",
                "请在「个人设置 → Gitea 账号绑定」完成账号关联",
                {"source": source},
            )
        else:
            _add_passed("AUTHOR_UNMATCHED", "提交作者已成功匹配到校园用户")

        # 规则: MEMBER_NOT_IN_TEAM
        author_name = str((matched_member or {}).get("displayName") or "")
        if matched and not _member_in_team(str(member.get("campusUserId") or ""), project):
            _add_violation(
                "MEMBER_NOT_IN_TEAM",
                "warn",
                f"作者 {author_name!r} 不在团队成员列表（未自动添加成员）",
                "请确认提交者已加入该团队项目，或由队长在团队页面手动添加成员",
                {"author": author_name},
            )

    # ── pull_request 事件校验 ─────────────────────────────────────
    elif event_type == "pull_request":
        pr = payload.get("pull_request") or {}
        head_branch = pr_branch(pr, "head")
        base_branch = pr_branch(pr, "base")

        # 规则: PR_BASE_NOT_DEFAULT
        base_name = base_branch.split(":")[-1] if ":" in base_branch else base_branch
        if base_name and base_name != default_branch:
            _add_violation(
                "PR_BASE_NOT_DEFAULT",
                "warn",
                f"PR 目标分支是 {base_name!r}，应合并到 {default_branch}",
                f"创建 PR 时请将 base 分支选为 {default_branch}",
                {"base": base_name, "defaultBranch": default_branch},
            )
        elif base_name:
            _add_passed("PR_BASE_NOT_DEFAULT", f"PR base 分支正确指向 {default_branch}")

        # 规则: PR_HEAD_NAME_INVALID
        head_name = head_branch.split(":")[-1] if ":" in head_branch else head_branch
        if head_name and not _branch_name_valid(head_name):
            _add_violation(
                "PR_HEAD_NAME_INVALID",
                "warn",
                f"PR 来源分支 {head_name!r} 命名不规范",
                "来源分支应使用 feature/xxx、fix/xxx 等命名",
                {"head": head_name},
            )
        elif head_name:
            _add_passed("PR_HEAD_NAME_INVALID", f"PR head 分支 {head_name!r} 命名规范")

    # ── 计算得分 ──────────────────────────────────────────────────
    deduct = sum(_DEDUCT.get(v["severity"], 0) for v in violations)
    score = max(0, 100 - deduct)

    return {
        "eventType": event_type,
        "evaluatedAt": format_chinese_datetime(),
        "score": score,
        "scoreExplanation": {"baseline": 100, "deductions": [{"code": v["code"], "points": _DEDUCT.get(v["severity"], 0)} for v in violations], "scope": "Git workflow heuristics only; not algorithm correctness, security, CI or learning mastery"},
        "passed": passed,
        "violations": violations,
    }
