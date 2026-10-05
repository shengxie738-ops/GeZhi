"""Pure observation boundary for the separate, unimplemented repository coach.

Receiving a commit is not evidence of branch-rule compliance, tests or review.
Receipt identity and timestamps are supplied by the repository service.
"""


def build_repository_observation_feedback(commit: dict, branch: str) -> dict:
    """Describe the analysis boundary without judging or mutating the inputs."""
    return {
        "status": "incomplete",
        "analysisMode": "observation_only",
        "providerInvoked": False,
        "evidence": {"complete": False},
        "fallbackReason": "repository_coach_not_implemented",
        "summary": "已收到提交记录；此仓库尚未执行 Git 教练分析，不能据此判断分支规范、测试或审核状态。",
    }
