"""Deterministic student instructions, never a local Git or integration runner.

The service supplies current-task projection and owns canonical receipt context.
Commands are examples with adjacent conditions; unknown local facts stay unknown.
"""
from datetime import datetime
import re
from urllib.parse import quote, urlencode, urlsplit

from app.services.student_git_workflow import validate_git_branch

_REMOTE = {"gitea_snapshot", "gitea_webhook", "gitea_merge"}
_PREFLIGHT = "先检查工作区；有未提交改动、detached HEAD、merge/rebase 进行中或不确定时，先保留工作并求助，不切换分支。"


def _member_id(member):
    return str(member.get("username") or member.get("id") or member.get("memberId") or "").strip()


def _repository_key(repository):
    owner = str(repository.get("giteaOwner") or "").strip()
    name = str(repository.get("giteaRepo") or repository.get("repoName") or "").strip()
    identity = repository.get("giteaRepositoryId")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", owner) or not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
        return ""
    if type(identity) is not int or identity <= 0:
        return ""
    return f"{owner}/{name}#{identity}".lower()


def _branch(value):
    try:
        return validate_git_branch(value)
    except (TypeError, ValueError):
        return ""


def _repository_url(repository, field):
    """Only verified configured credential-free HTTP(S) repository URLs."""
    value = repository.get(field)
    if repository.get("externalVerified") is not True or not _repository_key(repository) or not isinstance(value, str):
        return ""
    if not value or re.search(r"[\s<>\"'`\\]", value):
        return ""
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or not re.fullmatch(r"[A-Za-z0-9.-]+", parsed.hostname) or parsed.username or parsed.password:
            return ""
        if parsed.query or parsed.fragment or parsed.port is not None and not 0 < parsed.port < 65536:
            return ""
    except ValueError:
        return ""
    owner = str(repository.get("giteaOwner") or "")
    name = str(repository.get("giteaRepo") or repository.get("repoName") or "")
    ending = f"/{owner}/{name}" + (".git" if field == "cloneUrl" else "")
    path = parsed.path.rstrip("/")
    if not path.endswith(ending) or any(part in {".", ".."} for part in path.split("/")):
        return ""
    # Percent-escaped paths must not introduce hidden tokens or path components.
    if "%" in path or not re.fullmatch(r"/[A-Za-z0-9._/-]+", path):
        return ""
    return value.rstrip("/")


def _confirmation(member, state, repository_key):
    proof = member.get("cloneEvidence") or {}
    value = proof.get("confirmedAt")
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else None
    except ValueError:
        timestamp = None
    return (state.get("cloneStatus") == "done" and proof.get("kind") == "student_confirmation"
            and proof.get("memberId") == _member_id(member) and bool(repository_key)
            and proof.get("repositoryKey") == repository_key and timestamp is not None and timestamp.tzinfo is not None)


def _context(member, state, repository_key):
    revision = member.get("taskRevision")
    return (type(revision) is int and revision > 0 and state.get("revision") == revision
            and state.get("bindingStatus") in {"assigned", "bound"} and bool(repository_key)
            and (member.get("taskEvidence") or {}).get("repositoryKey") == repository_key)


def _observations(member, state, repository_key, branch, base):
    if not _context(member, state, repository_key) or not branch or not base or branch == base:
        return []
    result = []
    for row in state.get("evidence") or []:
        if not isinstance(row, dict):
            continue
        binding = row.get("taskBinding") or {}
        if (row.get("eligible") is not True or row.get("unknownReasons") or row.get("provenance") not in _REMOTE
                or row.get("repositoryKey") != repository_key or row.get("memberId") != _member_id(member)
                or row.get("sourceBranch") != branch or binding.get("kind") != "local_task_binding"
                or binding.get("revision") != member.get("taskRevision")
                or binding.get("repositoryKey") != repository_key or binding.get("memberId") != _member_id(member)
                or binding.get("sourceBranch") != branch):
            continue
        if row.get("kind") == "pull_request":
            if (row.get("headRepositoryKey") != repository_key or row.get("targetBranch") != base
                    or binding.get("targetBranch") != base or type(row.get("number")) is not int or row["number"] <= 0
                    or not row.get("createdAt") or binding.get("createdAt") != row.get("createdAt")):
                continue
        elif row.get("kind") != "push":
            continue
        result.append(row)
    return result


def _detail(command, *, kind="preflight", condition="在本人终端检查，不代表系统已验证本机状态。", copyable=True):
    return {"command": command, "kind": kind, "copyable": copyable, "condition": condition}


def _card(identity, title, description, *, details=None, preconditions=None, label="系统未验证", status="unknown", evidence="unknown", hint="", action_url=""):
    details = details or []
    result = {"id": identity, "title": title, "description": description, "status": status,
              "statusLabel": label, "evidenceKind": evidence, "preconditions": preconditions or [],
              "commands": [entry["command"] for entry in details], "commandDetails": details, "nextHint": hint,
              # Compatibility display only; copy/navigation use the structured fields.
              "command": "\n".join(entry["command"] for entry in details)}
    if action_url:
        result["actionUrl"] = action_url
    return result


def build_student_git_guidance(repository: dict, member: dict | None, task_state: dict) -> list[dict]:
    """Return fresh advisory cards without changing inputs or doing any I/O."""
    member = member or {}
    state = task_state or {}
    key = _repository_key(repository)
    branch, base = _branch(member.get("branch")), _branch(repository.get("defaultBranch"))
    safe_task = bool(_member_id(member) and branch and base and branch != base)
    context = _context(member, state, key)
    observations = _observations(member, state, key, branch, base)
    prs = [row for row in observations if row.get("kind") == "pull_request"]
    merged = state.get("mergeStatus") == "merged" and any(row.get("status") == "merged" for row in prs)
    opened = any(row.get("status") == "open" for row in prs)
    pushed = state.get("pushStatus") == "detected" and any(row.get("kind") == "push" for row in observations)
    clone_confirmed = _confirmation(member, state, key)
    clone_url, html_url = _repository_url(repository, "cloneUrl"), _repository_url(repository, "htmlUrl")
    assignment_notice = ("当前任务证据未验证，请队长确认任务版本与任务分支。" if not context else "本机分支、提交和工作区状态仍需本人检查。")
    if branch and base and branch == base:
        assignment_notice = "任务分支与默认分支相同，请队长分配独立任务分支；不向默认分支直接推送。"
    elif not safe_task:
        assignment_notice = "任务分支或默认分支缺失／未验证，不能生成任务变更命令；请队长核对分配。"
    checks = [_detail("git status --short --branch"), _detail("git branch --show-current")]
    branch_details = list(checks)
    if safe_task:
        branch_details.extend([
            _detail("git fetch origin", condition="先确认 origin 指向该仓库，再读取远端引用。"),
            _detail(f"git switch {base} && git pull --ff-only origin {base}", kind="mutation", condition="仅在任务分支不存在、工作区干净且没有 merge/rebase 时；shell 必须支持 &&，切换失败时不更新，分叉时停止。"),
            _detail(f"git switch {branch}", kind="mutation", condition="仅在本人检查确认任务分支已存在、工作区干净时使用。"),
            _detail(f"git switch -c {branch}", kind="mutation", condition=f"仅在本人确认任务分支不存在、已成功更新并位于默认分支 {base} 时使用。"),
        ])
    commit_details = [_detail("git diff"), _detail("git diff --cached")]
    if safe_task:
        commit_details.extend([
            _detail("git add -- <本次改动文件>", kind="template", copyable=False, condition="先替换文件占位符，仅选择本次改动文件；此示例不能直接复制执行。"),
            _detail('git commit -m "<说明本次改动目的>"', kind="template", copyable=False, condition="先替换提交说明占位符，说明改变的内容与目的；不要宣称未经执行的测试通过。"),
        ])
    push_details = [_detail(f"git push -u origin {branch}", kind="mutation", condition="先确认当前分支正是任务分支、改动已提交且 origin 正确；非快进拒绝时停止并求助。") ] if safe_task else []
    action_url = (f"{html_url}/pulls/new?{urlencode({'head': branch, 'base': base}, quote_via=quote)}" if html_url and safe_task else "")
    conflict_details = list(checks)
    if safe_task:
        conflict_details.extend([
            _detail(f"git switch {branch}", kind="mutation", condition="仅在任务分支已存在、工作区干净且没有 merge/rebase 进行中时。"),
            _detail("git fetch origin", condition="先确认 origin 指向该仓库。"),
            _detail(f"git merge origin/{base}", kind="mutation", condition="仅在已确认位于任务分支且工作区干净时，主动选择合入默认分支。"),
            _detail("git add -- <已解决冲突的文件>", kind="template", copyable=False, condition="检查冲突标记、编辑选择的文件，替换占位符；仅暂存已解决冲突的文件。"),
            _detail('git commit -m "<说明冲突解决>"', kind="template", copyable=False, condition="仅在相关项目测试已由本人执行、冲突全部解决且 merge 进行中时，替换说明并完成合并提交。"),
            _detail(f"git push -u origin {branch}", kind="mutation", condition="普通推送新 head，随后请求重新审核；非快进拒绝时停止。"),
            _detail("git merge --abort", kind="mutation", condition="仅在 merge 确实进行中且无法安全解决时；先保留未提交工作并求助。"),
        ])
    conflict_proof = state.get("conflictEvidence") or {}
    current_head = next((row.get("headSha") for row in sorted(prs, key=lambda row: str(row.get("updatedAt") or ""), reverse=True)
                         if row.get("status") == "open" and re.fullmatch(r"[0-9a-fA-F]{40,64}", str(row.get("headSha") or ""))), "")
    observed_conflict = bool(context and current_head and conflict_proof.get("verified") is True
        and conflict_proof.get("source") == "gitea" and conflict_proof.get("repositoryKey") == key
        and conflict_proof.get("memberId") == _member_id(member) and conflict_proof.get("taskRevision") == member.get("taskRevision")
        and conflict_proof.get("sourceBranch") == branch and conflict_proof.get("targetBranch") == base
        and conflict_proof.get("headSha") == current_head and conflict_proof.get("status") == "conflicting")
    post_details = list(checks)
    if safe_task:
        post_details.append(_detail(f"git switch {base} && git pull --ff-only origin {base}", kind="mutation",
                                   condition="先保留工作，确认工作区干净且没有 merge/rebase；仅用于支持 && 的 shell，切换失败不执行 pull，分叉时停止并求助。"))
    return [
        _card("clone", "拉取代码", "在本人电脑拉取仓库；远端提交不能证明本机 clone。", details=[_detail(f"git clone -- {clone_url}", kind="mutation", condition="先检查已验证仓库地址与本机目标目录；不要覆盖已有工作目录。")] if clone_url else [],
              preconditions=["仓库 clone 地址未验证，暂不可复制。" if not clone_url else "仓库地址来自已验证配置，不含凭据。"],
              label="本人确认已拉取" if clone_confirmed else "本机拉取待本人确认（系统未验证）", status="done" if clone_confirmed else "unknown", evidence="student_confirmation" if clone_confirmed else "unknown", hint="拉取并检查后，使用“我已完成拉取”记录本人确认。"),
        _card("branch", "检查并选择任务分支", "先检查本机状态，再区分已有分支与新建分支；不能根据远端数据猜测本机分支。", details=branch_details,
              preconditions=[_PREFLIGHT, assignment_notice], label="本机分支未知", hint="已有分支用 switch；不存在时先更新默认分支，再新建任务分支。"),
        _card("commit", "检查并提交选择的文件", "检查差异与暂存区，只提交本次任务的文件。", details=commit_details,
              preconditions=[assignment_notice, "确认当前任务分支；检查秘密信息、无关文件与合适的项目测试。测试指导不是测试执行证据。"], label="本机提交与测试未知", hint="替换文件及提交说明占位符；确认差异后再提交。"),
        _card("push", "普通推送任务分支", "普通推送需要本人检查本机分支和提交；刷新成功或 PR 存在不能证明新 push 已投递。", details=push_details,
              preconditions=[_PREFLIGHT, assignment_notice, "确认实际当前分支、已提交改动与 origin；非快进拒绝时停止，先核对远端改动并求助。"],
              label="本任务已检测到 push" if pushed else "本任务 push 证据未知", status="done" if pushed else "unknown", evidence="remote_observation" if pushed else "unknown", hint="系统尚无可靠 push 证据时，仍可在本人核对实际推送后手动创建 PR。"),
        _card("pull_request", "手动发起 Pull Request", "核对当前任务 head 与配置默认 base，再打开 Gitea 原生 PR 页面。", preconditions=[assignment_notice, "先检查本机任务分支、工作区与实际推送；系统 push 证据未知不阻止本人核实后手动创建 PR。", f"核对 head={branch} → base={base}。" if safe_task else "任务分支／默认分支未验证。", "仓库 PR 地址未验证，链接不可用。" if not action_url else "创建 PR 前确认实际远端任务分支存在。"],
              label="本任务 PR 已合并" if merged else "本任务 PR 已打开" if opened else "PR 状态未知／待本人核对", status="done" if merged else "current" if action_url else "unknown", evidence="remote_observation" if merged or opened else "unknown", hint="手动创建不会补造已 push 证据；提交检查范围、测试证据及待确认事项。", action_url=action_url),
        _card("review", "检查改动并请求审核", "学生检查差异、测试证据与修改要求；队长核对当前任务、分支、base、head 和未解决事项。", preconditions=["学习系统初审记录与 Gitea 原生审核分别记录。", "原生审核：未知；CI：未知；本机测试：未知。", "工作流分数 100 或学习系统建议不能代替原生审核、测试和合并决定。"], label="审核、CI 与测试证据未知", hint="补充真实检查证据；修改后请重新审核新 head。"),
        _card("conflict", "冲突处理指导", (f"Gitea 当前 head {current_head} 检测到冲突；来源 gitea。" if observed_conflict else "如 Gitea 显示冲突，可按此步骤处理；系统目前没有当前 head 的冲突证据。"), details=conflict_details,
              preconditions=[_PREFLIGHT, assignment_notice, "检查冲突标记，编辑选择的文件，仅暂存已解决文件，运行相关项目测试，完成合并提交，普通推送并请求重新审核。"], label="当前 head 检测到冲突" if observed_conflict else "冲突状态未知（条件指导）", evidence="remote_observation" if observed_conflict else "unknown", hint="不能安全解决时保留工作并求助；abort 仅适用于 merge 进行中。"),
        _card("merge", "核对远端 PR 合并", "远端合并只描述本任务的远端 PR 工作流；不证明实现验收、学习掌握、测试或本机同步。", preconditions=["队长先核对任务版本、分支、base、当前 head、原生审核／测试证据与未解决事项。", "原生审核、CI、本机测试缺失时保持未知；学习系统推荐与真实远端合并操作分开。"], label="本任务 PR 已合并" if merged else "本任务远端合并未知", status="done" if merged else "unknown", evidence="remote_observation" if merged else "unknown", hint="远端已合并后，仍需本人单独执行并确认本机同步。"),
        _card("post_merge", "合并后在本人电脑同步", "保留本机工作，切换到已验证默认分支后仅快进更新；远端快照不能确认此动作。", details=post_details,
              preconditions=[_PREFLIGHT, assignment_notice, "先确认本任务远端 PR 已合并；工作区干净并保留已有工作，默认分支分叉时停止并求助。"], label="待本人在本机同步（系统未验证）", hint="切换失败必须停止；不要自动覆盖改动或删除分支。"),
    ]
