"""Pure current-assignment evidence; no transport, persistence or local Git.

Only the application establishes task bindings. Source receipt time, commit
presence, caller revision fields and scores cannot establish those bindings.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
import re

_REMOTE = frozenset({"gitea_snapshot", "gitea_webhook", "gitea_merge"})


def validate_git_branch(branch: str) -> str:
    """Accept safe shell-token Git branches, including slash-delimited names."""
    if not isinstance(branch, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", branch):
        raise ValueError("invalid Git branch name")
    if branch in {"HEAD", "@"} or ".." in branch or "//" in branch or branch.endswith(("/", ".")):
        raise ValueError("invalid Git branch name")
    if any(part.startswith(".") or part.endswith(".lock") for part in branch.split("/")):
        raise ValueError("invalid Git branch name")
    return branch


def _time(value):
    if not isinstance(value, str) or not re.match(r"^\d{4}-\d{2}-\d{2}T", value):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return result.astimezone(timezone.utc) if result.tzinfo is not None else None


def _known_repository(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#[1-9][0-9]*", value))


def _member_id(member):
    return str(member.get("username") or member.get("id") or member.get("memberId") or "").strip()


def _established(member):
    return type(member.get("taskRevision")) is int and member["taskRevision"] > 0 and _time(member.get("taskAssignedAt")) is not None


def _branch_reused(member):
    evidence = member.get("taskEvidence") or {}
    if evidence.get("branchReused"):
        return True
    key = evidence.get("repositoryKey") or ""
    return any(row.get("branch") == member.get("branch") and
               (not row.get("repositoryKey") or row.get("repositoryKey") == key)
               for row in member.get("taskHistory") or [])


def reassign_task(member: dict, *, task: str, branch: str, repository_key: str, assigned_at: str) -> dict:
    """Archive the previous assignment on explicit material assignment changes."""
    validate_git_branch(branch)
    assigned = _time(assigned_at)
    if assigned is None or datetime.fromisoformat(assigned_at.replace("Z", "+00:00")).utcoffset().total_seconds() != 0:
        raise ValueError("UTC assignment timestamp required")
    result = deepcopy(member)
    old_evidence = member.get("taskEvidence") or {}
    established = _established(member)
    if established and task == member.get("task") and branch == member.get("branch") and repository_key == old_evidence.get("repositoryKey"):
        return result
    archive = {key: deepcopy(member.get(key)) for key in (
        "taskRevision", "taskAssignedAt", "task", "branch", "taskEvidence", "cloneStatus",
        "pushStatus", "prStatus", "mergeStatus", "progress", "statusLabel")}
    archive["repositoryKey"] = old_evidence.get("repositoryKey") or ""
    archive["bindingStatus"] = "assigned" if established else "legacy_unverified"
    result.setdefault("taskHistory", []).append(archive)
    result.update({"task": task, "branch": branch,
                   "taskRevision": member["taskRevision"] + 1 if established else 1,
                   "taskAssignedAt": assigned_at,
                   "taskEvidence": {"repositoryKey": repository_key, "observations": [], "history": []},
                   "pushStatus": "pending", "prStatus": "not_created", "mergeStatus": "pending",
                   "statusLabel": "已分配", "progress": 10})
    return result


def _assignment_reasons(member, repository_key):
    reasons = []
    if not _established(member):
        reasons.append("legacy_assignment")
    if not _known_repository(repository_key):
        reasons.append("repository_identity_missing")
    evidence = member.get("taskEvidence") or {}
    if evidence.get("repositoryKey") != repository_key:
        reasons.append("assignment_repository_mismatch")
    return reasons


def _observation_reasons(member, row, repository_key, default_branch, *, require_binding):
    reasons = _assignment_reasons(member, repository_key)
    if not _known_repository(row.get("repositoryKey")):
        reasons.append("repository_identity_missing")
    elif row.get("repositoryKey") != repository_key:
        reasons.append("repository_mismatch")
    if not _member_id(member) or row.get("memberId") != _member_id(member):
        reasons.append("member_mismatch")
    if not member.get("branch") or row.get("sourceBranch") != member.get("branch"):
        reasons.append("source_branch_mismatch")
    try:
        validate_git_branch(str(row.get("sourceBranch") or ""))
    except ValueError:
        reasons.append("source_branch_missing_or_invalid")
    if row.get("provenance") not in _REMOTE:
        reasons.append("non_remote_provenance")
    kind = row.get("kind")
    if kind == "pull_request":
        if row.get("headRepositoryKey") != repository_key:
            reasons.append("head_repository_mismatch")
        if row.get("targetBranch") != default_branch or not default_branch:
            reasons.append("target_branch_mismatch")
        if type(row.get("number")) is not int or row["number"] <= 0:
            reasons.append("pr_identity_missing")
        if row.get("current") is False and row.get("status") != "merged":
            reasons.append("not_current_snapshot")
    elif kind in {"push", "commit_snapshot"}:
        if kind != "push" or row.get("reliableSourceTime") is not True or row.get("sourceTimeKind") != "push_event":
            reasons.append("push_time_unverified")
        if not re.fullmatch(r"[0-9a-fA-F]{40,64}", str(row.get("sha") or "")):
            reasons.append("sha_identity_missing")
    else:
        reasons.append("unsupported_event_kind")
    created = _time(row.get("createdAt"))
    assigned = _time(member.get("taskAssignedAt"))
    if created is None:
        reasons.append("creation_time_missing")
    elif assigned is not None and created < assigned:
        reasons.append("creation_before_assignment")
    if _branch_reused(member):
        reasons.append("branch_reused")
    if require_binding:
        bound = row.get("taskBinding")
        if not isinstance(bound, dict) or bound.get("kind") != "local_task_binding":
            reasons.append("revision_binding_missing")
        else:
            if type(bound.get("revision")) is not int or bound.get("revision") != member.get("taskRevision"):
                reasons.append("old_task_revision")
            for key, expected in (("repositoryKey", repository_key), ("memberId", _member_id(member)),
                                  ("sourceBranch", member.get("branch"))):
                if bound.get(key) != expected:
                    reasons.append("binding_identity_mismatch")
            if kind == "pull_request" and (bound.get("targetBranch") != default_branch or _time(bound.get("createdAt")) != created):
                reasons.append("binding_identity_mismatch")
    return sorted(set(reasons))


def bind_task_observation(member: dict, observation: dict, *, repository_key: str,
                          default_branch: str, previous: dict | None = None) -> dict:
    """Establish a PR binding once from exact source facts, never caller revisions.

    Push delivery currently has no trustworthy event-creation boundary. It is
    recorded unbound; an explicitly pre-established local association can be
    retained, but this function never invents one from an incoming payload.
    """
    result = deepcopy(observation)
    previous = previous or {}
    result["firstSeenTaskRevision"] = previous.get("firstSeenTaskRevision", member.get("taskRevision") if _established(member) else None)
    prior_binding = previous.get("taskBinding")
    if isinstance(prior_binding, dict) and prior_binding.get("kind") == "local_task_binding":
        result["taskBinding"] = deepcopy(prior_binding)
        result["bindingReasons"] = _observation_reasons(member, result, repository_key, default_branch, require_binding=True)
        return result
    result["taskBinding"] = None
    reasons = _observation_reasons(member, result, repository_key, default_branch, require_binding=False)
    if result["firstSeenTaskRevision"] != member.get("taskRevision"):
        reasons.append("old_task_revision")
    if result.get("kind") != "pull_request":
        reasons.append("push_time_unverified")
    if not reasons:
        result["taskBinding"] = {"kind": "local_task_binding", "revision": member["taskRevision"],
            "repositoryKey": repository_key, "memberId": _member_id(member),
            "sourceBranch": member["branch"], "targetBranch": default_branch,
            "createdAt": result["createdAt"]}
    result["bindingReasons"] = sorted(set(reasons))
    return result


def _signature(row):
    return json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _observation_key(row):
    kind = row.get("kind") or "unknown"
    identifier = row.get("number") if kind == "pull_request" else row.get("sha")
    return f"{kind}:{row.get('repositoryKey') or 'unknown'}:{identifier or _signature(row)}"


def _sufficient_terminal_merge(row):
    """Recognize a previously sufficient terminal observation, not new authority."""
    bound = row.get("taskBinding")
    created = _time(row.get("createdAt"))
    if row.get("kind") != "pull_request" or row.get("status") != "merged" or row.get("provenance") not in _REMOTE:
        return False
    if not isinstance(bound, dict) or bound.get("kind") != "local_task_binding" or type(bound.get("revision")) is not int or bound["revision"] <= 0:
        return False
    key = row.get("repositoryKey")
    return (_known_repository(key) and row.get("headRepositoryKey") == key and
        bound.get("repositoryKey") == key and type(row.get("number")) is int and row["number"] > 0 and
        bool(row.get("memberId")) and row.get("memberId") == bound.get("memberId") and
        bool(row.get("sourceBranch")) and row.get("sourceBranch") == bound.get("sourceBranch") and
        bool(row.get("targetBranch")) and row.get("targetBranch") == bound.get("targetBranch") and
        created is not None and created == _time(bound.get("createdAt")))


def _latest_observations(rows):
    latest = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = _observation_key(row)
        # An observed remote merge is terminal for this immutable PR identity.
        # Local adapter success need not invent a newer remote timestamp.
        terminal = row.get("kind") == "pull_request" and row.get("status") == "merged" and row.get("provenance") in _REMOTE
        rank = (_sufficient_terminal_merge(row), terminal, _time(row.get("updatedAt")) or _time(row.get("createdAt")) or datetime.min.replace(tzinfo=timezone.utc), _signature(row))
        if key not in latest or rank > latest[key][0]:
            latest[key] = (rank, deepcopy(row))
    return [latest[key][1] for key in sorted(latest)]


def merge_task_observations(member: dict, observations: list[dict], *, replace_pr_snapshot: bool = False) -> dict:
    """Preserve every distinct historical observation; dedupe only current views."""
    result = deepcopy(member)
    evidence = result.setdefault("taskEvidence", {"repositoryKey": ""})
    old = evidence.get("observations") or []
    incoming = deepcopy(observations)
    history = { _signature(row): deepcopy(row) for row in (evidence.get("history") or []) + old + incoming }
    if replace_pr_snapshot:
        incoming_keys = {_observation_key(row) for row in incoming if row.get("kind") == "pull_request"}
        old = [dict(row, current=False) if row.get("kind") == "pull_request" and _observation_key(row) not in incoming_keys else row for row in old]
        # Absence clears stale open presence. Present stale/incomplete rows cannot
        # replace a previously sufficient terminal merge for the same identity.
        evidence["observations"] = _latest_observations(old + incoming)
    else:
        evidence["observations"] = _latest_observations(old + incoming)
    evidence["history"] = [history[key] for key in sorted(history)]
    return result


def reconcile_task_observations(latest_member: dict, observed_member: dict, *,
                                repository_key: str, default_branch: str) -> dict:
    """Combine fetched facts with the latest protected assignment, without binding.

    Only active, already normalized observations reach the current projection.
    History is retained for audit; history-only rows gain no current authority.
    The latest assignment, scores, counters and clone confirmation are retained.
    This in-memory seam makes no claim about transactional serialization.
    """
    current = (latest_member.get("taskEvidence") or {}).get("observations") or []
    observed_evidence = observed_member.get("taskEvidence") or {}
    prior = {_observation_key(row): row for row in current}
    incoming = []
    for row in observed_evidence.get("observations") or []:
        fact = deepcopy(row)
        previous = prior.get(_observation_key(row)) or {}
        bound = previous.get("taskBinding")
        if isinstance(bound, dict) and bound.get("kind") == "local_task_binding":
            fact["taskBinding"] = deepcopy(bound)
            fact["firstSeenTaskRevision"] = previous.get("firstSeenTaskRevision")
        incoming.append(fact)
    result = merge_task_observations(latest_member, incoming)
    evidence = result["taskEvidence"]
    history = {_signature(row): deepcopy(row) for row in
        (evidence.get("history") or []) + list(observed_evidence.get("history") or [])}
    evidence["history"] = [history[key] for key in sorted(history)]
    state = project_task_evidence(result, repository_key=repository_key,
        default_branch=default_branch, observations=evidence.get("observations") or [])
    result["currentTask"] = state
    for field in ("cloneStatus", "pushStatus", "prStatus", "mergeStatus", "progress", "statusLabel"):
        result[field] = state[field]
    return result


def project_task_evidence(member: dict, *, repository_key: str, default_branch: str,
                          observations: list[dict]) -> dict:
    """Project heuristic current workflow only; never change the input record."""
    established = _established(member)
    state = {"revision": member.get("taskRevision") if established else None,
             "bindingStatus": "assigned" if established else "legacy_unverified",
             "cloneStatus": "pending", "pushStatus": "pending", "prStatus": "not_created",
             "mergeStatus": "pending", "progress": 10 if established else 0,
             "statusLabel": "已分配" if established else "任务证据未验证",
             "localSync": "unknown", "tests": "unknown", "nativeReview": "unknown",
             "evidence": [], "unknownReasons": []}
    unknown = set(_assignment_reasons(member, repository_key))
    clone = member.get("cloneEvidence") or {}
    if clone.get("kind") == "student_confirmation" and clone.get("memberId") == _member_id(member) and clone.get("repositoryKey") == repository_key and _time(clone.get("confirmedAt")) is not None:
        state["cloneStatus"] = "done"
        if established:
            state.update({"progress": 35, "statusLabel": "本人确认已拉取"})
    current_prs = []
    unbound_commits = False
    for row in _latest_observations(observations):
        reasons = _observation_reasons(member, row, repository_key, default_branch, require_binding=True)
        reasons = sorted(set(reasons + list(row.get("bindingReasons") or [])))
        unknown.update(reasons)
        state["evidence"].append({**deepcopy(row), "eligible": not reasons, "unknownReasons": reasons})
        if reasons:
            if row.get("kind") in {"push", "commit_snapshot"} and row.get("sourceBranch") == member.get("branch"):
                unbound_commits = True
            continue
        state["bindingStatus"] = "bound"
        if row.get("kind") == "push":
            state.update({"pushStatus": "detected", "prStatus": "needs_pr", "progress": max(state["progress"], 58), "statusLabel": "本任务已检测到 push"})
        elif row.get("kind") == "pull_request":
            current_prs.append(row)
    if any(row.get("status") == "merged" for row in current_prs):
        state.update({"prStatus": "merged", "mergeStatus": "merged", "progress": 100, "statusLabel": "本任务 PR 已合并"})
    elif any(row.get("status") == "open" for row in current_prs):
        state.update({"prStatus": "open", "progress": max(state["progress"], 74), "statusLabel": "本任务 PR 待审核"})
    elif any(row.get("status") == "closed" for row in current_prs):
        state.update({"prStatus": "closed", "statusLabel": "本任务 PR 已关闭（未合并）"})
    elif unbound_commits:
        state["statusLabel"] = "任务分支发现提交，任务归属未确认"
    state["unknownReasons"] = sorted(unknown)
    return state


def summarize_task_states(states: list[dict]) -> dict:
    completed = sum(row.get("mergeStatus") == "merged" for row in states)
    pushed = sum(row.get("pushStatus") == "detected" for row in states)
    return {"totalMembers": len(states), "completedMembers": completed,
            "pendingMembers": len(states) - completed, "pushedMembers": pushed,
            "unsubmittedMembers": len(states) - pushed,
            "openPullRequests": sum(row.get("prStatus") == "open" for row in states),
            "averageProgress": round(sum(row.get("progress", 0) for row in states) / max(len(states), 1))}


def needs_submission_reminder(state: dict) -> bool:
    if state.get("mergeStatus") == "merged" or state.get("prStatus") == "open":
        return False
    return state.get("pushStatus") != "detected" or state.get("prStatus") in {"not_created", "needs_pr", "closed"}


def _raw_repository_key(raw):
    if not isinstance(raw, dict) or type(raw.get("id")) is not int or raw["id"] <= 0:
        return ""
    owner = raw.get("owner") if isinstance(raw.get("owner"), dict) else {}
    name = str(raw.get("name") or "")
    login = str(owner.get("login") or owner.get("username") or "")
    key = f"{login}/{name}#{raw['id']}".lower()
    return key if _known_repository(key) else ""


def pull_request_observation_fields(raw: dict) -> dict:
    """Preserve optional fields from a received PR response, never infer them."""
    base = raw.get("base") if isinstance(raw.get("base"), dict) else {}
    head = raw.get("head") if isinstance(raw.get("head"), dict) else {}
    sha = str(head.get("sha") or "")
    return {"repositoryKey": _raw_repository_key(base.get("repo")),
            "headRepositoryKey": _raw_repository_key(head.get("repo")),
            "headSha": sha if re.fullmatch(r"[0-9a-fA-F]{40,64}", sha) else ""}
