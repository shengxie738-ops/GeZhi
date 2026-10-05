"""B-only finite pure guidance and AST wiring contract.

Only the new guidance builder and its frozen A branch-validator dependency
may execute. Services/components are source data. All inputs are synthetic;
this establishes no local Git, provider, DB, callback, native review or UI.
"""
import ast
from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "backend/app/services/student_git_guidance.py"
WORKFLOW = ROOT / "backend/app/services/student_git_workflow.py"
SERVICE = ROOT / "backend/app/services/team_git_service.py"
REPO_KEY = "campus/p#71"
BRANCH = "feature/u/task-r2"
BASE = "develop"
SHA = "a" * 40
OTHER_SHA = "b" * 40
REQUIRED = {"clone", "branch", "commit", "push", "pull_request", "merge", "review", "post_merge", "conflict"}


def repository(**changes):
    value = {"repoName": "p", "giteaRepo": "p", "giteaOwner": "campus",
             "giteaRepositoryId": 71, "externalVerified": True, "defaultBranch": BASE,
             "cloneUrl": "https://git.synthetic.invalid/gitea/campus/p.git",
             "htmlUrl": "https://git.synthetic.invalid/gitea/campus/p"}
    value.update(changes)
    return value


def member(**changes):
    value = {"id": "u", "username": "u", "name": "Synthetic student", "task": "Task two",
             "branch": BRANCH, "taskRevision": 2, "taskAssignedAt": "2026-10-05T00:00:00Z",
             "taskEvidence": {"repositoryKey": REPO_KEY, "observations": [], "history": []},
             "cloneStatus": "done", "pushStatus": "detected", "prStatus": "merged",
             "mergeStatus": "merged", "progress": 100, "score": 100}
    value.update(changes)
    return value


def task_state(**changes):
    value = {"revision": 2, "bindingStatus": "assigned", "cloneStatus": "pending",
             "pushStatus": "pending", "prStatus": "not_created", "mergeStatus": "pending",
             "progress": 10, "statusLabel": "已分配", "evidence": [], "unknownReasons": [],
             "localSync": "unknown", "tests": "unknown", "nativeReview": "unknown"}
    value.update(changes)
    return value


def pr_evidence(**changes):
    value = {"kind": "pull_request", "repositoryKey": REPO_KEY, "headRepositoryKey": REPO_KEY,
             "memberId": "u", "sourceBranch": BRANCH, "targetBranch": BASE, "number": 9,
             "headSha": SHA, "createdAt": "2026-10-05T00:01:00Z", "updatedAt": "2026-10-05T00:02:00Z",
             "status": "open", "provenance": "gitea_snapshot", "eligible": True, "unknownReasons": [],
             "taskBinding": {"kind": "local_task_binding", "revision": 2, "repositoryKey": REPO_KEY,
                             "memberId": "u", "sourceBranch": BRANCH, "targetBranch": BASE,
                             "createdAt": "2026-10-05T00:01:00Z"}}
    value.update(changes)
    return value


def function(source, name):
    found = [node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == name]
    if not found:
        raise AssertionError(f"Missing required source boundary: {name}")
    return found[0]


class StudentGitGuidanceTests(unittest.TestCase):
    def builder(self):
        self.assertTrue(HELPER.is_file(), "B contract missing: pure student_git_guidance.py")
        spec = importlib.util.spec_from_file_location("student_git_guidance_b_only", HELPER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(callable(getattr(module, "build_student_git_guidance", None)), "B pure builder API missing")
        return module.build_student_git_guidance

    def cards(self, repo=None, who=None, state=None):
        values = self.builder()(repository() if repo is None else repo,
                                member() if who is None else who,
                                task_state() if state is None else state)
        self.assertIsInstance(values, list)
        return {card["id"]: card for card in values}

    def texts(self, cards):
        return "\n".join(str(card.get(key, "")) for card in cards.values()
                         for key in ("description", "statusLabel", "nextHint", "preconditions"))

    def commands(self, cards):
        return [command for card in cards.values() for command in card["commands"]]

    def test_B01_original_ids_and_additive_instruction_contract_are_present(self):
        cards = self.cards()
        self.assertTrue(REQUIRED <= set(cards))
        for card in cards.values():
            self.assertIsInstance(card["evidenceKind"], str)
            self.assertIsInstance(card["statusLabel"], str)
            self.assertIsInstance(card["preconditions"], list)
            self.assertTrue(all(isinstance(item, str) for item in card["preconditions"]))
            self.assertIsInstance(card["commands"], list)
            self.assertEqual(card["commands"], [entry["command"] for entry in card["commandDetails"]])

    def test_B02_raw_legacy_merged_flags_and_scores_never_complete_cards(self):
        cards = self.cards(state=task_state(revision=None, bindingStatus="legacy_unverified"))
        for key in ("push", "pull_request", "merge", "review", "post_merge"):
            self.assertNotEqual(cards[key]["status"], "done", key)
        self.assertIn("未验证", self.texts(cards))

    def test_B03_configured_base_and_assigned_branch_drive_commands_and_pr_link(self):
        cards = self.cards()
        commands = "\n".join(self.commands(cards))
        self.assertIn(f"git push -u origin {BRANCH}", commands)
        self.assertIn(f"git switch {BASE} && git pull --ff-only origin {BASE}", commands)
        self.assertNotIn(" main", commands)
        self.assertEqual(cards["pull_request"]["actionUrl"],
                         "https://git.synthetic.invalid/gitea/campus/p/pulls/new?head=feature%2Fu%2Ftask-r2&base=develop")

    def test_B03_nonmember_never_borrows_repository_or_other_member_task_branch(self):
        cards = self.cards(repo=repository(taskBranch="feature/other"), who={})
        self.assertFalse(cards["pull_request"].get("actionUrl"))
        commands = "\n".join(self.commands(cards))
        self.assertNotIn("feature/other", commands)
        self.assertNotIn(BRANCH, commands)
        self.assertNotIn("feature/task", commands)
        self.assertIn("任务", self.texts(cards))

    def test_B04_missing_or_unverified_urls_disable_only_their_actions(self):
        for changes in ({"cloneUrl": ""}, {"htmlUrl": ""}, {"externalVerified": False}):
            with self.subTest(changes=changes):
                cards = self.cards(repo=repository(**changes))
                if changes.get("cloneUrl") == "" or changes.get("externalVerified") is False:
                    self.assertFalse(cards["clone"]["commands"])
                if changes.get("htmlUrl") == "" or changes.get("externalVerified") is False:
                    self.assertFalse(cards["pull_request"].get("actionUrl"))
                self.assertIn("未验证", self.texts(cards))
                self.assertNotIn("undefined", "\n".join(self.commands(cards)))

    def test_B04_credential_shell_and_wrong_repository_urls_are_not_actionable(self):
        urls = ["https://user:secret@git.synthetic.invalid/gitea/campus/p",
                "javascript:alert(1)", "https://git.synthetic.invalid/gitea/campus/other",
                "https://git.synthetic.invalid/gitea/campus/p?token=secret",
                "https://git.synthetic.invalid/gitea/campus/p\n;echo x"]
        for url in urls:
            with self.subTest(url=url):
                cards = self.cards(repo=repository(htmlUrl=url, cloneUrl=url + ".git"))
                self.assertFalse(cards["clone"]["commands"])
                self.assertFalse(cards["pull_request"].get("actionUrl"))
                self.assertNotIn("secret", self.texts(cards))

    def test_B04_unsafe_task_or_default_reference_never_enters_any_command(self):
        bad = ["feature/u;echo x", "-option", "HEAD", "a..b", "bad name", "x.lock", "x\nexit"]
        for branch in bad:
            for field in ("task", "default"):
                with self.subTest(branch=branch, field=field):
                    cards = self.cards(repo=repository(defaultBranch=branch) if field == "default" else repository(),
                                       who=member(branch=branch) if field == "task" else member())
                    self.assertFalse(cards["pull_request"].get("actionUrl"))
                    self.assertFalse(cards["push"]["commands"])
                    self.assertTrue(all(branch not in command for command in self.commands(cards)))
                    self.assertIn("分支", self.texts(cards))

    def test_B04_assigned_default_branch_is_not_a_task_mutation_target(self):
        cards = self.cards(who=member(branch=BASE))
        self.assertFalse(cards["push"]["commands"])
        self.assertFalse(cards["pull_request"].get("actionUrl"))
        self.assertTrue(all(entry["kind"] == "preflight" for entry in cards["branch"]["commandDetails"]))
        self.assertIn("默认分支", self.texts(cards))

    def test_B05_manual_pr_remains_available_while_push_delivery_is_unknown(self):
        cards = self.cards(state=task_state(unknownReasons=["push_time_unverified"]))
        self.assertTrue(cards["pull_request"]["actionUrl"])
        self.assertNotEqual(cards["pull_request"]["status"], "locked")
        self.assertNotEqual(cards["push"]["status"], "done")
        self.assertTrue(any("实际推送" in text for text in cards["pull_request"]["preconditions"]))
        self.assertTrue(any("本机" in text for text in cards["pull_request"]["preconditions"]))
        self.assertFalse(cards["pull_request"]["commands"])

    def test_B06_bound_remote_merge_does_not_complete_local_sync_review_or_tests(self):
        state = task_state(bindingStatus="bound", prStatus="merged", mergeStatus="merged", progress=100,
                           evidence=[pr_evidence(status="merged")])
        cards = self.cards(state=state)
        self.assertEqual(cards["merge"]["statusLabel"], "本任务 PR 已合并")
        self.assertEqual(cards["merge"]["evidenceKind"], "remote_observation")
        self.assertEqual(cards["merge"]["status"], "done")
        self.assertNotEqual(cards["post_merge"]["status"], "done")
        self.assertIn("系统未验证", cards["post_merge"]["statusLabel"])
        self.assertIn("未知", cards["review"]["statusLabel"])
        self.assertNotIn("测试通过", self.texts(cards))

    def test_B06_revision_or_binding_mismatch_cannot_show_remote_merge_success(self):
        for changes in ({"revision": 1}, {"bindingStatus": "legacy_unverified"}):
            cards = self.cards(state=task_state(**changes, mergeStatus="merged", prStatus="merged",
                                               evidence=[pr_evidence(status="merged")]))
            self.assertNotEqual(cards["merge"]["status"], "done")

    def test_B07_preflight_and_branch_existence_are_explicit(self):
        cards = self.cards()
        branch = cards["branch"]
        self.assertIn("git status --short --branch", branch["commands"])
        self.assertIn("git branch --show-current", branch["commands"])
        existing = next(entry for entry in branch["commandDetails"] if entry["command"] == f"git switch {BRANCH}")
        new = next(entry for entry in branch["commandDetails"] if entry["command"] == f"git switch -c {BRANCH}")
        self.assertIn("已存在", existing["condition"])
        self.assertIn("不存在", new["condition"])
        self.assertEqual(existing["kind"], "mutation")
        self.assertIn("detached HEAD", self.texts(cards))
        self.assertIn("merge/rebase", self.texts(cards))
        self.assertIn("未提交", self.texts(cards))

    def test_B07_selected_file_templates_are_visible_but_not_copyable(self):
        cards = self.cards()
        commit = cards["commit"]
        self.assertIn("git diff", commit["commands"])
        self.assertIn("git diff --cached", commit["commands"])
        selected = next(entry for entry in commit["commandDetails"] if entry["command"].startswith("git add -- "))
        self.assertEqual(selected["command"], "git add -- <本次改动文件>")
        self.assertFalse(selected["copyable"])
        self.assertEqual(selected["kind"], "template")
        self.assertIn("占位", selected["condition"])
        self.assertIn("秘密", self.texts(cards))

    def test_B07_post_merge_switch_failure_cannot_fall_through_to_pull(self):
        cards = self.cards()
        post = cards["post_merge"]
        update = next(entry for entry in post["commandDetails"] if "git pull" in entry["command"])
        self.assertEqual(update["command"], f"git switch {BASE} && git pull --ff-only origin {BASE}")
        self.assertIn("&&", update["condition"])
        self.assertIn("分叉", self.texts(cards))
        self.assertIn("保留", self.texts(cards))

    def test_B07_no_destructive_bare_pull_blanket_add_or_implicit_rebase(self):
        cards = self.cards(state=task_state(mergeStatus="merged", prStatus="merged",
                                           bindingStatus="bound", evidence=[pr_evidence(status="merged")]))
        commands = "\n".join(self.commands(cards))
        for unsafe in ("git pull origin", "git add .", "git add -A", "git push --force", "git push -f",
                       "git reset", "git branch -d", "git branch -D", "git rebase", "git stash"):
            self.assertNotIn(unsafe, commands)

    def test_B08_unknown_conflict_is_conditional_instruction(self):
        cards = self.cards(state=task_state(bindingStatus="bound", prStatus="open", evidence=[pr_evidence()]))
        conflict = cards["conflict"]
        self.assertIn("如 Gitea 显示冲突", conflict["description"])
        self.assertNotIn("检测到冲突", conflict["statusLabel"])
        self.assertEqual(conflict["evidenceKind"], "unknown")
        self.assertIn("git fetch origin", conflict["commands"])
        self.assertIn(f"git merge origin/{BASE}", conflict["commands"])
        abort = next(entry for entry in conflict["commandDetails"] if entry["command"] == "git merge --abort")
        self.assertIn("merge", abort["condition"])
        self.assertIn("进行中", abort["condition"])
        self.assertIn("重新审核", self.texts(cards))

    def test_B08_only_current_head_bound_conflict_evidence_is_observed(self):
        evidence = {"verified": True, "source": "gitea", "repositoryKey": REPO_KEY, "memberId": "u",
                    "taskRevision": 2, "sourceBranch": BRANCH, "targetBranch": BASE,
                    "headSha": SHA, "status": "conflicting"}
        state = task_state(bindingStatus="bound", prStatus="open", evidence=[pr_evidence()], conflictEvidence=evidence)
        cards = self.cards(state=state)
        self.assertEqual(cards["conflict"]["evidenceKind"], "remote_observation")
        self.assertIn("检测到冲突", cards["conflict"]["statusLabel"])
        self.assertIn(SHA, self.texts(cards))
        self.assertIn("gitea", self.texts(cards))
        for field, wrong in (("headSha", OTHER_SHA), ("taskRevision", 1), ("repositoryKey", "campus/p#72"),
                             ("memberId", "other"), ("verified", False)):
            changed = {**evidence, field: wrong}
            cards = self.cards(state={**state, "conflictEvidence": changed})
            self.assertEqual(cards["conflict"]["evidenceKind"], "unknown", field)

    def test_B09_score_and_learning_assessment_do_not_supply_native_ci_or_test_approval(self):
        cards = self.cards(who=member(score=100, teacherReviewStatus="approved",
                                     reviewScope="learning_system", reviewComment="synthetic recommendation"))
        text = self.texts(cards)
        for expected in ("学习系统初审记录", "原生审核：未知", "CI：未知", "本机测试：未知"):
            self.assertIn(expected, text)
        self.assertNotEqual(cards["review"]["status"], "done")
        self.assertNotIn("允许合并", text)
        self.assertNotIn("测试通过", text)

    def test_B09_clone_requires_repository_scoped_student_confirmation(self):
        unconfirmed = self.cards(state=task_state(cloneStatus="done"))
        self.assertNotEqual(unconfirmed["clone"]["status"], "done")
        proof = {"kind": "student_confirmation", "memberId": "u", "repositoryKey": REPO_KEY,
                 "confirmedAt": "2026-10-05T00:03:00Z"}
        confirmed = self.cards(who=member(cloneEvidence=proof), state=task_state(cloneStatus="done"))
        self.assertEqual(confirmed["clone"]["statusLabel"], "本人确认已拉取")
        self.assertEqual(confirmed["clone"]["evidenceKind"], "student_confirmation")
        self.assertNotIn("本机已验证", self.texts(confirmed))

    def test_B10_builder_does_not_mutate_repository_member_or_task_projection(self):
        repo, who, state = repository(), member(), task_state(unknownReasons=["push_time_unverified"])
        before = deepcopy((repo, who, state))
        self.builder()(repo, who, state)
        self.assertEqual((repo, who, state), before)


class StudentGitGuidanceWiringTests(unittest.TestCase):
    def test_B_helper_reuses_A_validator_and_has_no_application_io_imports(self):
        self.assertTrue(HELPER.is_file(), "B contract missing: pure student_git_guidance.py")
        tree = ast.parse(HELPER.read_text(encoding="utf-8"))
        imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
        dependencies = [(node.module, [name.name for name in node.names]) for node in imports if isinstance(node, ast.ImportFrom)]
        self.assertIn(("app.services.student_git_workflow", ["validate_git_branch"]), dependencies)
        for node in imports:
            names = [node.module or ""] if isinstance(node, ast.ImportFrom) else [name.name for name in node.names]
            for name in names:
                self.assertIn(name.split(".")[0], {"copy", "datetime", "re", "urllib", "app", "typing", "__future__"})
        self.assertFalse(any(isinstance(node, ast.Call) and ast.unparse(node.func) in {"open", "eval", "exec"}
                             for node in ast.walk(tree)))

    def test_B_workflow_wrapper_passes_projected_current_task_to_pure_builder(self):
        source = SERVICE.read_text(encoding="utf-8")
        node = function(source, "_workflow_steps")
        calls = [call for call in ast.walk(node) if isinstance(call, ast.Call)
                 and ast.unparse(call.func) == "build_student_git_guidance"]
        self.assertEqual(len(calls), 1, "Existing workflow wrapper must delegate to the B pure builder")
        text = ast.unparse(node)
        self.assertIn("currentTask", text)
        self.assertNotIn("_repo_urls", text)
        self.assertNotIn("git pull origin", text)
        self.assertNotIn("git add .", text)

    def test_B_enrichment_emits_canonical_context_without_replacing_A_projection(self):
        source = SERVICE.read_text(encoding="utf-8")
        node = function(source, "_enrich")
        assignments = [item for item in ast.walk(node) if isinstance(item, ast.Assign)
                       and any(isinstance(target, ast.Subscript) and ast.unparse(target) == "result['workflowGuidance']"
                               for target in item.targets)]
        self.assertEqual(len(assignments), 1, "Guidance receipts require an explicit context envelope")
        text = ast.unparse(assignments[0].value)
        self.assertIn("_canonical_member_id", text)
        self.assertIn("_repository_task_key", text)
        for field in ("version", "memberId", "taskRevision", "repositoryKey"):
            self.assertIn(field, text)
        self.assertIn("_project_current_task_evidence(result)", ast.unparse(node))
        self.assertNotIn("studentId", text)


if __name__ == "__main__":
    unittest.main()
