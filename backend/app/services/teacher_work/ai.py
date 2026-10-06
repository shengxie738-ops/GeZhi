"""Narrow raw lesson-client adapter; no provider/settings activation at import."""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.services.teacher_work.chat import CHAT_SYSTEM_PROMPT_V1

if TYPE_CHECKING:
    from app.services.teacher_lesson_prep.ai_client import LessonPrepAIClient


class LessonPrepWorkAI:
    """Structural WorkAI implementation using an explicitly supplied client."""

    def __init__(self, lesson_client: LessonPrepAIClient):
        self._lesson_client = lesson_client

    async def complete(self, prompt: str, *, max_output_tokens: int, timeout_seconds: int) -> str:
        return await self._lesson_client.complete_raw(system_prompt=CHAT_SYSTEM_PROMPT_V1,
            user_prompt=prompt, max_output_tokens=max_output_tokens, timeout_seconds=timeout_seconds)

    async def complete_proposal(self, prompt: str, *, max_output_tokens: int, timeout_seconds: int) -> str:
        from app.services.teacher_work.proposals import PROPOSAL_SYSTEM_PROMPT_V1
        return await self._lesson_client.complete_raw(system_prompt=PROPOSAL_SYSTEM_PROMPT_V1,
            user_prompt=prompt, max_output_tokens=max_output_tokens, timeout_seconds=timeout_seconds)
