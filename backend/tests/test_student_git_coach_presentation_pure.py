"""C-only: standard-library observation tests and AST wiring guards.

Never imports or executes service, endpoint, callback, DB, worker or provider code.
"""
import ast
import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "backend/app/services/repository_git_observation.py"
SERVICE = ROOT / "backend/app/services/team_git_service.py"
REPOSITORY_SERVICE = ROOT / "backend/app/services/code_repository_service.py"
ENDPOINT = ROOT / "backend/app/api/endpoints/code_repository.py"
SUMMARY = "已收到提交记录；此仓库尚未执行 Git 教练分析，不能据此判断分支规范、测试或审核状态。"


def parsed(path):
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def function(tree, name):
    return next(node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name)


def string(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def assignment_key(node):
    if isinstance(node, ast.Subscript):
        return string(node.slice)
    return None


class RepositoryObservationTests(unittest.TestCase):
    def observation(self, branch):
        self.assertTrue(HELPER.is_file(), "Missing pure repository observation boundary")
        spec = importlib.util.spec_from_file_location("repository_git_observation_c_only", HELPER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        commit = {"id": "a" * 40, "message": "synthetic change", "author": {"username": "u"}}
        original = copy.deepcopy(commit)
        result = module.build_repository_observation_feedback(commit, branch)
        self.assertEqual(commit, original)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["analysisMode"], "observation_only")
        self.assertIs(result["providerInvoked"], False)
        self.assertIs(result["evidence"]["complete"], False)
        self.assertEqual(result["fallbackReason"], "repository_coach_not_implemented")
        self.assertEqual(result["summary"], SUMMARY)
        self.assertNotIn("score", result)
        self.assertNotIn("mistakes", result)
        self.assertNotIn("suggestions", result)
        self.assertNotIn("nativeReview", result)
        return result

    def test_C05_default_branch_does_not_manufacture_rule_approval(self):
        self.observation("main")

    def test_C05_invalid_branch_does_not_manufacture_rule_approval(self):
        self.observation("badbranch")

    def test_C05_feature_branch_does_not_manufacture_rule_approval(self):
        self.observation("feature/u")

    def test_C05_observation_helper_is_standard_library_only(self):
        self.assertTrue(HELPER.is_file(), "Missing pure repository observation boundary")
        tree = parsed(HELPER)
        imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
        for node in imports:
            names = [node.module] if isinstance(node, ast.ImportFrom) else [item.name for item in node.names]
            self.assertTrue(all(name in {"__future__", "typing", "copy"} for name in names), names)
        calls = [ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)]
        self.assertTrue(set(calls).issubset({"str", "dict", "commit.get", "deepcopy"}), calls)


class PresentationWiringTests(unittest.TestCase):
    def test_C07_repository_feedback_calls_observation_helper_and_removes_fixed_approval(self):
        tree = parsed(REPOSITORY_SERVICE)
        target = function(tree, "_queue_git_coach_feedback")
        calls = [node for node in ast.walk(target) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "build_repository_observation_feedback"]
        self.assertEqual(len(calls), 1)
        self.assertEqual([ast.unparse(arg) for arg in calls[0].args], ["commit", "branch"])
        imported = [node for node in tree.body if isinstance(node, ast.ImportFrom) and node.module == "app.services.repository_git_observation"]
        self.assertTrue(any(item.name == "build_repository_observation_feedback" for node in imported for item in node.names))
        self.assertNotIn("branch naming is acceptable", ast.unparse(target))
        self.assertNotIn("fallback", [string(node) for node in ast.walk(target)])

    def test_C07_remote_merge_does_not_infer_teacher_approval(self):
        tree = parsed(SERVICE)
        target = function(tree, "_apply_gitea_prs_to_project")
        for node in ast.walk(target):
            if isinstance(node, ast.Assign) and any(assignment_key(item) == "teacherReviewStatus" for item in node.targets):
                self.assertNotIn("approved", ast.unparse(node.value))
        legacy = function(tree, "_ensure_pull_requests_from_member_progress")
        for node in ast.walk(legacy):
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if string(key) == "teacherReviewStatus":
                        self.assertNotIn("approved", ast.unparse(value))

    def test_C07_local_recommendation_and_changes_mark_learning_system_scope(self):
        target = function(parsed(SERVICE), "review_pull_request")
        branches = [node for node in ast.walk(target) if isinstance(node, ast.If) and isinstance(node.test, ast.Compare) and isinstance(node.test.left, ast.Name) and node.test.left.id == "action"]
        for action in ("recommend_merge", "request_changes"):
            branch = next(node for node in branches if action in ast.unparse(node.test))
            writes = [node for statement in branch.body for node in ast.walk(statement) if isinstance(node, ast.Assign) and any(assignment_key(item) == "reviewScope" for item in node.targets)]
            self.assertTrue(any(string(node.value) == "learning_system" for node in writes), action)

    def test_C07_webhook_snapshots_do_not_reset_saved_local_assessments(self):
        tree = parsed(SERVICE)
        target = function(tree, "apply_gitea_webhook")
        protected = {"leaderReviewStatus", "leaderReviewer", "leaderReviewedAt", "teacherReviewStatus", "teacherReviewer", "teacherReviewedAt", "reviewComment", "reviewScope", "nativeReview"}
        for call in [node for node in ast.walk(target) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_upsert_pr"]:
            for node in ast.walk(call):
                if isinstance(node, ast.Dict):
                    self.assertFalse(protected.intersection(string(key) for key in node.keys), "Remote snapshot must not overwrite local assessment defaults")

    def test_C07_noop_repository_enqueue_is_not_scheduled_as_analysis(self):
        target = function(parsed(REPOSITORY_SERVICE), "enqueue_code_repository_git_coach_feedback")
        substantive = [node for node in target.body if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Constant) or not isinstance(node.value.value, str)]
        self.assertEqual(len(substantive), 1)
        self.assertIsInstance(substantive[0], ast.Return)
        self.assertIsNone(substantive[0].value.value)
        endpoint = function(parsed(ENDPOINT), "receive_code_repository_webhook")
        self.assertFalse(any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_task" and any(isinstance(arg, ast.Name) and arg.id == "enqueue_code_repository_git_coach_feedback" for arg in node.args) for node in ast.walk(endpoint)))

    def test_C07_explicit_merge_adapter_and_permissions_remain(self):
        target = function(parsed(SERVICE), "review_pull_request")
        calls = {ast.unparse(node.func) for node in ast.walk(target) if isinstance(node, ast.Call)}
        self.assertIn("gitea_svc.merge_pull_request", calls)
        self.assertIn("_project_can_review_pull_requests", calls)
        self.assertIn("require_project_action", calls)


if __name__ == "__main__":
    unittest.main(verbosity=2)
