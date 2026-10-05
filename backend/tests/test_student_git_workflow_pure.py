"""A-only deterministic evidence contract and AST wiring guards.

Only student_git_workflow.py is executed. All service, adapter and callback
source is parsed as data. Fixtures are synthetic and prove no transport,
transaction, database, provider, local Git, clone, tests or native review.
"""
import ast
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "backend/app/services/student_git_workflow.py"
SERVICE = ROOT / "backend/app/services/team_git_service.py"
ADAPTER = ROOT / "backend/app/services/gitea_service.py"
REPO = "campus/p#71"
BRANCH = "feature/u/task-r2"
BASE = "develop"
ASSIGNED = "2026-10-05T00:00:00Z"
CREATED = "2026-10-05T00:01:00Z"
UPDATED = "2026-10-05T00:02:00Z"
SHA = "a" * 40


def member(**changes):
    value = {"id": "u", "username": "u", "name": "Synthetic student",
             "task": "Task two", "branch": BRANCH, "taskRevision": 2,
             "taskAssignedAt": ASSIGNED, "taskHistory": [],
             "taskEvidence": {"repositoryKey": REPO, "observations": [], "history": []},
             "cloneStatus": "pending", "pushStatus": "pending",
             "prStatus": "not_created", "mergeStatus": "pending", "progress": 10,
             "commitCount": 6, "prCount": 2, "mergedPrCount": 1,
             "score": 100, "contribution": 44}
    value.update(changes)
    return value


def observation(**changes):
    value = {"kind": "pull_request", "repositoryKey": REPO,
             "headRepositoryKey": REPO, "memberId": "u", "sourceBranch": BRANCH,
             "targetBranch": BASE, "number": 9, "headSha": SHA,
             "createdAt": CREATED, "updatedAt": UPDATED, "status": "open",
             "provenance": "gitea_snapshot", "current": True}
    value.update(changes)
    return value


def binding(revision=2, **changes):
    value = {"kind": "local_task_binding", "revision": revision,
             "repositoryKey": REPO, "memberId": "u", "sourceBranch": BRANCH,
             "targetBranch": BASE, "createdAt": CREATED}
    value.update(changes)
    return value


def tree(path):
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def function(parsed, name):
    matches = [n for n in parsed.body if isinstance(n, ast.FunctionDef) and n.name == name]
    if not matches:
        raise AssertionError(f"Missing required source boundary: {name}")
    return matches[0]


def calls(target):
    return [ast.unparse(n.func) for n in ast.walk(target) if isinstance(n, ast.Call)]


def assigned_keys(target):
    result = []
    for node in ast.walk(target):
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for item in targets:
                if isinstance(item, ast.Subscript) and isinstance(item.slice, ast.Constant):
                    result.append((ast.unparse(item.value), item.slice.value))
    return result


class CurrentTaskEvidenceTests(unittest.TestCase):
    def workflow(self):
        self.assertTrue(HELPER.is_file(), "A contract missing: pure student_git_workflow.py")
        spec = importlib.util.spec_from_file_location("student_git_workflow_a_only", HELPER)
        value = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(value)
        return value

    def project(self, who=None, rows=None, repository_key=REPO):
        return self.workflow().project_task_evidence(who or member(), repository_key=repository_key,
                                                    default_branch=BASE, observations=rows or [])

    def bind(self, row=None, who=None, previous=None):
        return self.workflow().bind_task_observation(who or member(), row or observation(),
            repository_key=REPO, default_branch=BASE, previous=previous)

    def assert_not_merged(self, state):
        self.assertEqual(state["mergeStatus"], "pending")
        self.assertLess(state["progress"], 100)

    def test_A01_reassignment_archives_old_merge_resets_current_and_preserves_input(self):
        old = member(task="Task one", branch="feature/u/task-r1", taskRevision=1,
                     taskAssignedAt="2026-10-04T00:00:00Z", pushStatus="detected",
                     prStatus="merged", mergeStatus="merged", progress=100)
        old["taskEvidence"]["observations"] = [observation(status="merged", taskBinding=binding(1))]
        old["cloneEvidence"] = {"kind": "student_confirmation", "repositoryKey": REPO,
                                "memberId": "u", "confirmedAt": "2026-10-04T00:03:00Z"}
        original = json.dumps(old, sort_keys=True, ensure_ascii=False)
        result = self.workflow().reassign_task(old, task="Task two", branch=BRANCH,
                                                repository_key=REPO, assigned_at=ASSIGNED)
        self.assertEqual(json.dumps(old, sort_keys=True, ensure_ascii=False), original)
        self.assertEqual(result["taskRevision"], 2)
        self.assertEqual(result["taskAssignedAt"], ASSIGNED)
        self.assertEqual([result[k] for k in ("pushStatus", "prStatus", "mergeStatus", "progress")],
                         ["pending", "not_created", "pending", 10])
        history = result["taskHistory"][-1]
        self.assertEqual(history["taskRevision"], 1)
        self.assertEqual(history["task"], "Task one")
        self.assertEqual(history["branch"], "feature/u/task-r1")
        self.assertEqual(history["repositoryKey"], REPO)
        self.assertEqual(history["taskEvidence"], old["taskEvidence"])
        for key in ("commitCount", "prCount", "mergedPrCount", "score", "contribution", "cloneEvidence"):
            self.assertEqual(result[key], old[key], key)
        result["taskHistory"][-1]["taskEvidence"]["observations"].clear()
        self.assertEqual(len(old["taskEvidence"]["observations"]), 1)

    def test_A02_same_branch_new_task_increments_but_identical_assignment_is_idempotent(self):
        who = member()
        same = self.workflow().reassign_task(who, task=who["task"], branch=BRANCH,
                                            repository_key=REPO, assigned_at=UPDATED)
        self.assertEqual(same, who)
        changed = self.workflow().reassign_task(who, task="Different task", branch=BRANCH,
                                                repository_key=REPO, assigned_at=UPDATED)
        self.assertEqual(changed["taskRevision"], 3)
        self.assertEqual(changed["progress"], 10)
        self.assertEqual(len(changed["taskHistory"]), 1)

    def test_A02_first_explicit_legacy_assignment_establishes_boundary_even_if_text_matches(self):
        legacy = member(pushStatus="detected", prStatus="merged", mergeStatus="merged", progress=100)
        for key in ("taskRevision", "taskAssignedAt", "taskHistory", "taskEvidence"):
            legacy.pop(key)
        result = self.workflow().reassign_task(legacy, task=legacy["task"], branch=BRANCH,
                                               repository_key=REPO, assigned_at=ASSIGNED)
        self.assertEqual(result["taskRevision"], 1)
        self.assertEqual(result["progress"], 10)
        self.assertEqual(result["taskHistory"][0]["mergeStatus"], "merged")
        self.assertEqual(result["taskHistory"][0]["bindingStatus"], "legacy_unverified")
        self.assertNotIn("taskRevision", legacy)

    def test_A02_changed_repository_identity_is_material_assignment_change(self):
        result = self.workflow().reassign_task(member(), task="Task two", branch=BRANCH,
                                               repository_key="campus/p#72", assigned_at=UPDATED)
        self.assertEqual(result["taskRevision"], 3)
        self.assertEqual(result["taskEvidence"]["repositoryKey"], "campus/p#72")

    def test_A03_unsafe_branch_rejected_without_mutation(self):
        who = member()
        original = deepcopy(who)
        for unsafe in ("feature/u;echo x", "-x", "a..b", "a//b", "a/", "a.lock", "a/.b", "a/b.lock/c", "a@{b", "a\\b", "a b", "a\nb"):
            with self.subTest(branch=unsafe), self.assertRaises(ValueError):
                self.workflow().reassign_task(who, task="Other", branch=unsafe,
                                             repository_key=REPO, assigned_at=UPDATED)
        self.assertEqual(who, original)
        self.assertEqual(self.workflow().validate_git_branch(BRANCH), BRANCH)

    def test_A04_bound_push_open_and_merged_projection_have_truthful_milestones(self):
        push = observation(kind="push", status="detected", sha=SHA,
                           provenance="gitea_webhook", reliableSourceTime=True,
                           sourceTimeKind="push_event", taskBinding=binding())
        self.assertEqual(self.project(rows=[push])["progress"], 58)
        opened = self.bind()
        self.assertEqual(opened["taskBinding"]["revision"], 2)
        state = self.project(rows=[push, opened])
        self.assertEqual([state["prStatus"], state["progress"]], ["open", 74])
        merged = self.bind(observation(status="merged"), previous=opened)
        state = self.project(rows=[push, merged])
        self.assertEqual([state["mergeStatus"], state["progress"]], ["merged", 100])
        self.assertEqual(state["statusLabel"], "本任务 PR 已合并")
        for key in ("localSync", "tests", "nativeReview"):
            self.assertEqual(state[key], "unknown")

    def test_A04_open_pr_does_not_manufacture_push_delivery(self):
        state = self.project(rows=[self.bind()])
        self.assertEqual(state["prStatus"], "open")
        self.assertEqual(state["pushStatus"], "pending")

    def test_A05_mismatched_or_unverified_evidence_never_advances_current_merge(self):
        cases = [({"taskBinding": binding(1)}, "old_task_revision"),
                 ({"sourceBranch": "feature/u/old"}, "source_branch_mismatch"),
                 ({"targetBranch": "main"}, "target_branch_mismatch"),
                 ({"repositoryKey": "campus/p#72"}, "repository_mismatch"),
                 ({"headRepositoryKey": "other/p#81"}, "head_repository_mismatch"),
                 ({"memberId": "v"}, "member_mismatch"),
                 ({"memberId": "", "creator": "Synthetic student"}, "member_mismatch"),
                 ({"provenance": "demo"}, "non_remote_provenance"),
                 ({"provenance": "legacy_unverified"}, "non_remote_provenance"),
                 ({"taskBinding": None}, "revision_binding_missing"),
                 ({"repositoryKey": "campus/p#legacy"}, "repository_identity_missing")]
        for changes, reason in cases:
            row = observation(status="merged", taskBinding=binding())
            row.update(changes)
            with self.subTest(reason=reason):
                state = self.project(rows=[row])
                self.assert_not_merged(state)
                self.assertIn(reason, state["unknownReasons"])
                self.assertEqual(len(state["evidence"]), 1)

    def test_A06_pr_before_assignment_or_missing_creation_never_binds(self):
        for created, reason in (("2026-10-04T23:59:59Z", "creation_before_assignment"),
                                ("", "creation_time_missing"), ("15:23", "creation_time_missing")):
            with self.subTest(created=created):
                row = self.bind(observation(createdAt=created, updatedAt=UPDATED))
                self.assertIsNone(row["taskBinding"])
                self.assertIn(reason, row["bindingReasons"])
                self.assert_not_merged(self.project(rows=[row]))

    def test_A06_existing_local_binding_survives_status_updates_and_cannot_be_relabelled(self):
        old = observation(taskBinding=binding(1), firstSeenTaskRevision=1)
        original = deepcopy(old)
        newer = self.bind(observation(status="merged", taskRevision=2,
                                     boundTaskRevision=2), previous=old)
        self.assertEqual(newer["taskBinding"], old["taskBinding"])
        self.assertEqual(newer["firstSeenTaskRevision"], 1)
        self.assertEqual(old, original)
        self.assert_not_merged(self.project(rows=[newer]))

    def test_A06_callback_revision_fields_cannot_supply_local_binding(self):
        row = self.bind(observation(createdAt="", taskRevision=2, boundTaskRevision=2,
                                    taskBinding=binding(), firstSeenTaskRevision=2))
        self.assertIsNone(row["taskBinding"])
        self.assertIn("creation_time_missing", row["bindingReasons"])

    def test_A06_prior_unbound_pr_cannot_become_current_after_reassignment(self):
        previous = observation(taskBinding=None, firstSeenTaskRevision=1)
        row = self.bind(previous=previous)
        self.assertIsNone(row["taskBinding"])
        self.assertIn("old_task_revision", row["bindingReasons"])

    def test_A07_reused_branch_blocks_new_pr_binding_and_new_push(self):
        who = member(taskHistory=[{"taskRevision": 1, "branch": BRANCH, "repositoryKey": REPO}])
        row = self.bind(who=who)
        self.assertIsNone(row["taskBinding"])
        self.assertIn("branch_reused", row["bindingReasons"])
        push = observation(kind="push", sha=SHA, provenance="gitea_webhook")
        result = self.workflow().bind_task_observation(who, push, repository_key=REPO,
                                                        default_branch=BASE)
        self.assertIsNone(result["taskBinding"])
        self.assert_not_merged(self.project(who, [result]))

    def test_A08_closed_unmerged_pr_is_not_complete(self):
        state = self.project(rows=[self.bind(observation(status="closed"))])
        self.assertEqual(state["prStatus"], "closed")
        self.assert_not_merged(state)

    def test_A08_empty_pr_snapshot_clears_current_open_and_keeps_durable_history(self):
        opened = self.bind()
        who = member()
        who["taskEvidence"]["observations"] = [opened]
        original = deepcopy(who)
        result = self.workflow().merge_task_observations(who, [], replace_pr_snapshot=True)
        self.assertEqual(who, original)
        self.assertTrue(result["taskEvidence"]["history"])
        state = self.project(result, result["taskEvidence"]["observations"])
        self.assertEqual(state["prStatus"], "not_created")
        self.assert_not_merged(state)
        self.assertEqual(state["evidence"][0]["number"], 9)

    def test_A08_absent_later_snapshot_does_not_erase_observed_merged_history(self):
        merged = self.bind(observation(status="merged"))
        who = member()
        who["taskEvidence"]["observations"] = [merged]
        result = self.workflow().merge_task_observations(who, [], replace_pr_snapshot=True)
        state = self.project(result, result["taskEvidence"]["observations"])
        self.assertEqual(state["mergeStatus"], "merged")
        self.assertTrue(result["taskEvidence"]["history"])

    def test_A09_commit_snapshot_does_not_verify_push_or_clone(self):
        who = member(cloneStatus="done")
        snapshot = observation(kind="commit_snapshot", sha=SHA, createdAt=CREATED,
                               taskBinding=binding())
        state = self.project(who, [snapshot])
        self.assertEqual([state["pushStatus"], state["progress"]], ["pending", 10])
        self.assertEqual(state["cloneStatus"], "pending")
        self.assertIn("push_time_unverified", state["unknownReasons"])
        self.assertEqual(who["cloneStatus"], "done")

    def test_A09_student_clone_confirmation_is_explicit_and_repository_scoped(self):
        who = member(cloneStatus="done", cloneEvidence={"kind": "student_confirmation",
            "repositoryKey": REPO, "memberId": "u", "confirmedAt": CREATED})
        state = self.project(who)
        self.assertEqual([state["cloneStatus"], state["progress"]], ["done", 35])
        who["cloneEvidence"]["repositoryKey"] = "campus/p#72"
        self.assertEqual(self.project(who)["cloneStatus"], "pending")

    def test_A09_unverified_push_time_and_refresh_receipt_cannot_bind(self):
        row = self.bind(observation(kind="push", sha=SHA, createdAt=CREATED,
                                    observedAt=UPDATED, provenance="gitea_webhook"))
        self.assertIsNone(row["taskBinding"])
        self.assertIn("push_time_unverified", row["bindingReasons"])
        state = self.project(rows=[row])
        self.assertEqual(state["statusLabel"], "任务分支发现提交，任务归属未确认")
        self.assertEqual(state["pushStatus"], "pending")

    def test_A10_old_revision_arriving_late_stays_historical(self):
        old = observation(status="merged", taskBinding=binding(1), updatedAt="2026-10-06T00:00:00Z")
        state = self.project(rows=[old])
        self.assert_not_merged(state)
        self.assertIn("old_task_revision", state["evidence"][0]["unknownReasons"])

    def test_A10_projection_is_order_and_duplicate_invariant(self):
        opened = self.bind()
        closed = self.bind(observation(status="closed", updatedAt="2026-10-05T00:03:00Z"), previous=opened)
        expected = self.project(rows=[opened, closed])
        actual = self.project(rows=[closed, opened, closed, opened])
        self.assertEqual(actual, expected)
        self.assertEqual(actual["prStatus"], "closed")

    def test_A10_durable_merge_deduplicates_without_incrementing_lifetime_counts(self):
        row = self.bind()
        who = member()
        once = self.workflow().merge_task_observations(who, [row])
        twice = self.workflow().merge_task_observations(once, [row, row])
        self.assertEqual(twice, once)
        for key in ("commitCount", "prCount", "mergedPrCount", "score", "contribution"):
            self.assertEqual(twice[key], who[key])
        self.assertEqual(len(twice["taskEvidence"]["observations"]), 1)

    def test_A10_history_is_not_truncated_by_display_window(self):
        rows = [observation(number=i, taskBinding=binding()) for i in range(1, 42)]
        result = self.workflow().merge_task_observations(member(), rows)
        self.assertEqual(len(result["taskEvidence"]["observations"]), 41)
        self.assertEqual(len(result["taskEvidence"]["history"]), 41)

    def test_A11_legacy_merge_flags_remain_unverified_and_get_projection_is_pure(self):
        who = member(source="gitea", mergeStatus="merged", prStatus="merged", progress=100)
        for key in ("taskRevision", "taskAssignedAt", "taskHistory", "taskEvidence"):
            who.pop(key)
        original = deepcopy(who)
        state = self.project(who)
        self.assertEqual(state["bindingStatus"], "legacy_unverified")
        self.assert_not_merged(state)
        self.assertEqual(who, original)
        self.assertNotIn("taskRevision", who)

    def test_A11_unknown_repository_id_cannot_complete_even_with_matching_slug(self):
        state = self.project(rows=[observation(status="merged", taskBinding=binding())],
                             repository_key="campus/p#legacy")
        self.assert_not_merged(state)
        self.assertIn("repository_identity_missing", state["unknownReasons"])

    def test_A12_summary_and_reminders_use_current_task_projection_not_score(self):
        pending = self.project(member(source="gitea", mergeStatus="merged", progress=100))
        complete = self.project(rows=[self.bind(observation(status="merged"))])
        summary = self.workflow().summarize_task_states([pending, complete])
        self.assertEqual([summary["completedMembers"], summary["pendingMembers"]], [1, 1])
        self.assertEqual(summary["averageProgress"], 55)
        self.assertTrue(self.workflow().needs_submission_reminder(pending))
        self.assertFalse(self.workflow().needs_submission_reminder(complete))

    def test_A13_raw_optional_pr_identity_and_head_fields_are_literal_only(self):
        raw_repo = {"id": 71, "name": "p", "owner": {"login": "campus"}}
        raw = {"base": {"repo": raw_repo}, "head": {"repo": raw_repo, "sha": SHA}}
        original = deepcopy(raw)
        fields = self.workflow().pull_request_observation_fields(raw)
        self.assertEqual(fields["repositoryKey"], REPO)
        self.assertEqual(fields["headRepositoryKey"], REPO)
        self.assertEqual(fields["headSha"], SHA)
        self.assertEqual(raw, original)
        absent = self.workflow().pull_request_observation_fields({"base": {}, "head": {}})
        self.assertEqual([absent[k] for k in ("repositoryKey", "headRepositoryKey", "headSha")], ["", "", ""])
        for invalid in (True, 0, -1, "71"):
            with self.subTest(id=invalid):
                raw["base"]["repo"]["id"] = invalid
                self.assertEqual(self.workflow().pull_request_observation_fields(raw)["repositoryKey"], "")


    def test_A14_terminal_merge_survives_sequential_stale_open_snapshot(self):
        workflow = self.workflow()
        merged = self.bind(observation(status="merged"))
        incoming = self.bind(observation(status="open", updatedAt=CREATED), previous=merged)
        before = workflow.merge_task_observations(member(), [merged], replace_pr_snapshot=True)
        original = deepcopy(before)
        after = workflow.merge_task_observations(before, [incoming], replace_pr_snapshot=True)
        state = self.project(after, after["taskEvidence"]["observations"])
        self.assertEqual([state["mergeStatus"], state["progress"]], ["merged", 100])
        self.assertEqual(before, original)
        self.assertIn(incoming, after["taskEvidence"]["history"])
        self.assertIn(merged, after["taskEvidence"]["history"])
        self.assertEqual(after["taskEvidence"]["observations"][0]["taskBinding"], merged["taskBinding"])

    def test_A14_terminal_merge_survives_later_incomplete_snapshot_without_inventing_fields(self):
        workflow = self.workflow()
        merged = self.bind(observation(status="merged"))
        for status in ("open", "merged"):
            with self.subTest(status=status):
                incoming = self.bind(observation(status=status, headRepositoryKey="", targetBranch="", createdAt="", updatedAt="2026-10-05T00:04:00Z"), previous=merged)
                before = workflow.merge_task_observations(member(), [merged], replace_pr_snapshot=True)
                original = deepcopy(before)
                after = workflow.merge_task_observations(before, [incoming], replace_pr_snapshot=True)
                state = self.project(after, after["taskEvidence"]["observations"])
                self.assertEqual([state["mergeStatus"], state["progress"]], ["merged", 100])
                self.assertEqual(before, original)
                self.assertIn(incoming, after["taskEvidence"]["history"])
                self.assertIn(merged, after["taskEvidence"]["history"])
                self.assertEqual(incoming["headRepositoryKey"], "")
                self.assertEqual(incoming["targetBranch"], "")
                self.assertEqual(incoming["createdAt"], "")
                self.assertEqual(after["taskEvidence"]["observations"][0]["taskBinding"], merged["taskBinding"])

    def test_A15_same_revision_reconciliation_preserves_fetched_evidence_and_latest_fields(self):
        workflow = self.workflow()
        self.assertTrue(callable(getattr(workflow, "reconcile_task_observations", None)), "Missing pure latest-assignment evidence reconciliation")
        opened = self.bind()
        latest = member(score=97, commitCount=99)
        latest["taskEvidence"]["observations"] = [opened]
        commit = observation(kind="commit_snapshot", sha=SHA, provenance="gitea_snapshot", taskBinding=None,
                             firstSeenTaskRevision=2, sourceTimeKind="commit_time")
        observed = workflow.merge_task_observations(member(), [opened, commit])
        before_latest, before_observed = deepcopy(latest), deepcopy(observed)
        result = workflow.reconcile_task_observations(latest, observed, repository_key=REPO, default_branch=BASE)
        self.assertEqual(latest, before_latest)
        self.assertEqual(observed, before_observed)
        for key in ("taskRevision", "taskAssignedAt", "task", "branch", "taskHistory", "score", "commitCount", "prCount", "mergedPrCount", "contribution"):
            self.assertEqual(result[key], latest[key], key)
        self.assertIn(commit, result["taskEvidence"]["history"])
        self.assertTrue(any(row.get("sha") == SHA for row in result["taskEvidence"]["observations"]))
        self.assertEqual(result["currentTask"]["prStatus"], "open")
        self.assertEqual(result["currentTask"]["pushStatus"], "pending")
        self.assertEqual(result["currentTask"]["cloneStatus"], "pending")
        self.assertEqual(next(row for row in result["taskEvidence"]["observations"] if row.get("number") == 9 and row.get("kind") == "pull_request")["taskBinding"], opened["taskBinding"])

    def test_A15_late_prior_revision_evidence_is_retained_without_rebinding_latest_assignment(self):
        workflow = self.workflow()
        self.assertTrue(callable(getattr(workflow, "reconcile_task_observations", None)), "Missing pure latest-assignment evidence reconciliation")
        old = member()
        merged = self.bind(observation(status="merged"))
        observed = workflow.merge_task_observations(old, [merged])
        latest = workflow.reassign_task(old, task="Task three", branch="feature/u/task-r3",
                                       repository_key=REPO, assigned_at="2026-10-05T00:03:00Z")
        latest.update({"score": 97, "commitCount": 99})
        before_latest, before_observed = deepcopy(latest), deepcopy(observed)
        result = workflow.reconcile_task_observations(latest, observed, repository_key=REPO, default_branch=BASE)
        self.assertEqual(latest, before_latest)
        self.assertEqual(observed, before_observed)
        for key in ("taskRevision", "taskAssignedAt", "task", "branch", "taskHistory", "score", "commitCount", "prCount", "mergedPrCount", "contribution"):
            self.assertEqual(result[key], latest[key], key)
        self.assertIn(merged, result["taskEvidence"]["history"])
        row = next(row for row in result["taskEvidence"]["observations"] if row.get("number") == 9)
        self.assertEqual(row["taskBinding"], merged["taskBinding"])
        self.assertEqual(row["firstSeenTaskRevision"], 2)
        self.assertEqual(result["currentTask"]["revision"], 3)
        self.assert_not_merged(result["currentTask"])
        self.assertIn("old_task_revision", result["currentTask"]["unknownReasons"])



class TaskEvidenceWiringTests(unittest.TestCase):
    def test_A_static_helper_is_pure_standard_library_only(self):
        self.assertTrue(HELPER.is_file(), "Missing production pure helper")
        imports = [n for n in ast.walk(tree(HELPER)) if isinstance(n, (ast.Import, ast.ImportFrom))]
        allowed = {"__future__", "copy", "datetime", "json", "re", "typing"}
        for node in imports:
            names = [node.module] if isinstance(node, ast.ImportFrom) else [x.name for x in node.names]
            self.assertTrue(all(name in allowed for name in names), names)
        names = calls(tree(HELPER))
        forbidden = ("open", "exec", "eval", "__import__", "compile", "subprocess", "socket", "requests", "sqlite", "Session", "Gitea", "provider")
        self.assertFalse(any(any(part in name for part in forbidden) for name in names), names)

    def test_A03_assignment_and_issue_writer_route_through_same_pure_reassignment(self):
        parsed = tree(SERVICE)
        for name in ("assign_member_task", "_apply_gitea_issues_to_project"):
            target = function(parsed, name)
            self.assertIn("reassign_task", calls(target), name)
            self.assertFalse(any(owner == "member" and key in {"task", "branch"}
                                 for owner, key in assigned_keys(target)), name)
        target = function(parsed, "assign_member_task")
        self.assertIn("require_project_action", calls(target))
        self.assertIn("_save_external_changes", calls(target))

    def test_A_writers_share_projection_and_do_not_directly_promote_current_flags(self):
        parsed = tree(SERVICE)
        for name in ("_apply_gitea_prs_to_project", "_apply_gitea_commits_to_project", "apply_gitea_webhook", "review_pull_request"):
            target = function(parsed, name)
            self.assertTrue(set(calls(target)).intersection({"_project_current_task_evidence", "_record_task_observations"}), name)
            self.assertFalse(any(owner == "member" and key in {"pushStatus", "prStatus", "mergeStatus", "progress"}
                                 for owner, key in assigned_keys(target)), name)
        sync = function(parsed, "sync_project_from_gitea")
        sequence = calls(sync)
        self.assertLess(sequence.index("_apply_gitea_issues_to_project"), sequence.index("_apply_gitea_prs_to_project"))
        self.assertIn("_project_current_task_evidence", sequence)

    def test_A09_only_explicit_clone_action_creates_student_confirmation_provenance(self):
        parsed = tree(SERVICE)
        target = function(parsed, "confirm_clone")
        self.assertIn("student_confirmation", ast.unparse(target))
        for name in ("_apply_gitea_commits_to_project", "apply_gitea_webhook"):
            self.assertFalse(any(owner == "member" and key == "cloneStatus"
                                 for owner, key in assigned_keys(function(parsed, name))), name)
            self.assertNotIn("student_confirmation", ast.unparse(function(parsed, name)))

    def test_A_enrichment_summary_and_reminders_consume_current_projection(self):
        parsed = tree(SERVICE)
        self.assertIn("_project_current_task_evidence", calls(function(parsed, "_enrich")))
        self.assertIn("summarize_task_states", calls(function(parsed, "_team_summary")))
        self.assertIn("needs_submission_reminder", calls(function(parsed, "remind_unsubmitted_members")))
        self.assertNotIn("任务已完成", ast.unparse(function(parsed, "_current_user_progress")))

    def test_A_webhook_uses_observed_pr_branch_and_creation_not_assignment_or_receipt(self):
        target = function(tree(SERVICE), "apply_gitea_webhook")
        for node in ast.walk(target):
            if isinstance(node, ast.Assign) and any(isinstance(x, ast.Name) and x.id in {"source_branch", "target_branch"} for x in node.targets):
                value = ast.unparse(node.value)
                self.assertNotIn("member.get", value)
                self.assertNotIn("repo.get", value)
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and key.value == "createdAt":
                        self.assertNotIn("_now_label", ast.unparse(value))
        self.assertIn("bind_task_observation", calls(function(tree(SERVICE), "_record_task_observations")))

    def test_A_adapter_preserves_only_existing_raw_pr_optional_fields(self):
        parsed = tree(ADAPTER)
        klass = next(n for n in parsed.body if isinstance(n, ast.ClassDef) and n.name == "GiteaService")
        target = next(n for n in klass.body if isinstance(n, ast.FunctionDef) and n.name == "list_pull_requests")
        self.assertIn("pull_request_observation_fields", calls(target))
        self.assertEqual(calls(target).count("requests.get"), 1)

    def test_A_remote_merge_permissions_and_C_review_provenance_remain(self):
        target = function(tree(SERVICE), "review_pull_request")
        self.assertIn("gitea_svc.merge_pull_request", calls(target))
        self.assertIn("require_project_action", calls(target))
        self.assertIn("_project_can_review_pull_requests", calls(target))
        self.assertIn("learning_system", ast.unparse(target))
        self.assertIn("nativeReview", ast.unparse(target))
        self.assertIn("_save_external_changes", calls(target))


    def test_A15_sync_captures_fetched_evidence_and_reconciles_after_protected_restoration(self):
        target = function(tree(SERVICE), "sync_project_from_gitea")
        self.assertIn("reconcile_task_observations", calls(target))
        source = ast.unparse(target)
        self.assertIn("observed_members", source)
        self.assertLess(source.index("observed_members ="), source.rindex("member.update(protected"))
        self.assertGreater(source.index("reconcile_task_observations("), source.rindex("member.update(protected"))
        helper_calls = [node for node in ast.walk(target) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "reconcile_task_observations"]
        self.assertEqual(len(helper_calls), 1)
        self.assertEqual(ast.unparse(helper_calls[0].args[0]), "member")
        self.assertIn("observed_members", ast.unparse(helper_calls[0].args[1]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
