"""Fail-closed code execution boundary.

There is no verified isolated runner in this deployment. Never execute untrusted
programs on the application host: a subprocess, timeout, or blacklist is not a
sandbox. A future runner requires a separately reviewed isolation boundary.
"""
from typing import Any

EXECUTION_UNAVAILABLE_MESSAGE = "代码执行不可用：尚未部署经过验证的隔离执行服务；未运行代码，也未判定正确性。"


class ExecutionUnavailableError(RuntimeError):
    """No isolated execution capability is available."""


class CodeSandbox:
    # 支持的比较模式：exact(精确)、tolerance(浮点容差)、ignore_case(忽略大小写)、ignore_ws(忽略空白差异)
    COMPARE_MODES = {"exact", "tolerance", "ignore_case", "ignore_ws"}

    @staticmethod
    def _compare_outputs(actual: str, expected: str, mode: str = "exact", tolerance: float = 1e-6) -> bool:
        """根据比较模式判断输出是否匹配"""
        if mode == "exact":
            return actual == expected

        if mode == "ignore_case":
            return actual.lower() == expected.lower()

        if mode == "ignore_ws":
            return " ".join(actual.split()) == " ".join(expected.split())

        if mode == "tolerance":
            # 尝试将两个输出按行分割，逐行比较浮点数
            actual_lines = actual.strip().splitlines()
            expected_lines = expected.strip().splitlines()
            if len(actual_lines) != len(expected_lines):
                return False
            for a_line, e_line in zip(actual_lines, expected_lines):
                a_tokens = a_line.strip().split()
                e_tokens = e_line.strip().split()
                if len(a_tokens) != len(e_tokens):
                    return False
                for a_tok, e_tok in zip(a_tokens, e_tokens):
                    try:
                        if abs(float(a_tok) - float(e_tok)) > tolerance:
                            return False
                    except ValueError:
                        if a_tok != e_tok:
                            return False
            return True

        # 未知模式降级为精确比较
        return actual == expected

    def run(self, code: str, language: str, test_cases: list[dict[str, Any]]) -> dict[str, Any]:
        """Return an explicit ungraded result without evaluating submitted code."""
        return {
            "status": "unavailable",
            "available": False,
            "errorCode": "execution_unavailable",
            "passed": 0,
            "total": len(test_cases),
            "results": [],
            "error": EXECUTION_UNAVAILABLE_MESSAGE,
        }

    def _execute(self, code: str, language: str, inputs: list[str]) -> str:
        """Compatibility entry point; host execution is deliberately forbidden."""
        raise ExecutionUnavailableError(EXECUTION_UNAVAILABLE_MESSAGE)
