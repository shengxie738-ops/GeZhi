"""Offline boundary tests; never execute submitted programs or import AI clients."""
import ast
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("execution_boundary", ROOT / "app/services/code_sandbox.py")
sandbox_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sandbox_module)


class ExecutionBoundaryTests(unittest.TestCase):
    def test_run_is_unavailable_without_invoking_execution(self):
        for language in ("python", "javascript", "unknown"):
            with self.subTest(language=language), patch.object(sandbox_module.CodeSandbox, "_execute", return_value="ok") as execute:
                result = sandbox_module.CodeSandbox().run("print('ok')", language, [{"expected": "ok"}])
                self.assertEqual(result.get("status"), "unavailable")
                self.assertIs(result.get("available"), False)
                self.assertEqual(result.get("errorCode"), "execution_unavailable")
                self.assertEqual(result["passed"], 0)
                self.assertEqual(result["results"], [])
                self.assertTrue(result["error"])
                execute.assert_not_called()

    def test_empty_tests_do_not_report_success(self):
        result = sandbox_module.CodeSandbox().run("", "python", [])
        self.assertEqual(result.get("status"), "unavailable")
        self.assertTrue(result["error"])

    def test_direct_execution_is_disabled(self):
        self.assertTrue(hasattr(sandbox_module, "ExecutionUnavailableError"))
        with self.assertRaises(sandbox_module.ExecutionUnavailableError):
            sandbox_module.CodeSandbox()._execute("print('ok')", "python", [])

    def test_agent_tool_cannot_start_process(self):
        tree = ast.parse((ROOT / "app/services/agent_workflow.py").read_text())
        fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "execute_python_code")
        self.assertFalse(any(isinstance(node, ast.Name) and node.id in {"subprocess", "tempfile"} for node in ast.walk(fn)))
        fn.decorator_list = []
        namespace = {"EXECUTION_UNAVAILABLE_MESSAGE": "代码执行不可用", "CodeSandbox": sandbox_module.CodeSandbox}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), "agent_tool", "exec"), namespace)
        result = namespace["execute_python_code"]("print('ok')")
        self.assertIn("不可用", result)
        self.assertNotIn("运行成功", result)


class DiagnosisUnavailableTests(unittest.IsolatedAsyncioTestCase):
    def workflow(self):
        from types import SimpleNamespace
        tree = ast.parse((ROOT / "app/services/learning_diagnosis/workflow.py").read_text())
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and any(getattr(child, "name", "") == "submit_task" for child in node.body))
        methods = [node for node in cls.body if getattr(node, "name", "") in {"submit_task", "preview_task_execution"}]
        namespace = {}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ClassDef(name="Workflow", bases=[], keywords=[], body=methods, decorator_list=[])], type_ignores=[])), "diagnosis_boundary", "exec"), namespace)
        instance = namespace["Workflow"]()
        instance.store = SimpleNamespace(get_session=lambda *args: {"id": "session"})
        instance._current_task = lambda *args: {"task_type": "CODING_PRACTICE", "content_payload": {"test_cases": [{"expected": "ok"}]}}
        instance.code_sandbox = sandbox_module.CodeSandbox()
        def reject_evidence(*args, **kwargs):
            raise AssertionError("Unavailable execution must not become learning evidence")
        instance.sandbox_adapter = SimpleNamespace(normalize=reject_evidence)
        return instance

    async def test_submit_does_not_record_failure_or_advance_learning(self):
        result = await self.workflow().submit_task("session", "student", "task", "print('ok')")
        self.assertEqual(result["status"], "EXECUTION_UNAVAILABLE")
        self.assertEqual(result["errorCode"], "execution_unavailable")
        self.assertNotIn("evidence_id", result)
        self.assertNotIn("snapshot", result)

    async def test_non_coding_task_keeps_existing_submission_path(self):
        from unittest.mock import AsyncMock
        for task_type in ("KNOWLEDGE_REVIEW", "GUIDED_PRACTICE"):
            instance = self.workflow()
            task = {"task_type": task_type}
            instance._current_task = lambda *args: task
            instance._submit_non_coding_task = AsyncMock(return_value={"status": "RECORDED", "evidence_id": "text-evidence"})
            with patch.object(instance.code_sandbox, "run") as run:
                result = await instance.submit_task("session", "student", "task", "", answer="A valid explanation", hint_level=1)
                self.assertEqual(result["status"], "RECORDED")
                instance._submit_non_coding_task.assert_awaited_once_with({"id": "session"}, task, "A valid explanation", 1, False)
                run.assert_not_called()

    def test_preview_does_not_report_student_failure(self):
        result = self.workflow().preview_task_execution("session", "student", "task", "print('ok')")
        self.assertEqual(result["status"], "EXECUTION_UNAVAILABLE")
        self.assertEqual(result["test_summary"]["failed"], 0)
        self.assertEqual(result["test_summary"]["unrun"], 1)


if __name__ == "__main__":
    unittest.main()
