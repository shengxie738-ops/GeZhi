"""Opt-in private first-call runtime. No global Session, credentials or client I/O.

Only an Authorization header is propagated by ContextVar into a new supervisor.
Every synchronous operation re-resolves the account and finalizes its fresh root;
no Session or binding survives a provider await. No restart/recovery dispatcher.
"""
import asyncio
from contextvars import ContextVar
from datetime import datetime, timezone
import time
from uuid import uuid4

from app.schemas.teacher_work import ChatCommand, ChatTaskBrief, PrivateChatCapabilities
from app.services.teacher_work.authorization import WorkAuthorizationError
from app.services.teacher_work.chat_execution import ChatExecutionContext, TeacherChatExecution
from app.services.teacher_work.runs import WorkRunError


request_authorization = ContextVar("private_chat_authorization", default=None)
_runtime = None


def _now():
    return datetime.now(timezone.utc)


def provider_configured():
    from app.core.config import settings
    return (all(type(getattr(settings, key)) is str and bool(getattr(settings, key).strip())
                for key in ("AI_LESSON_PREP_API_KEY", "AI_LESSON_PREP_BASE_URL", "AI_LESSON_PREP_MODEL"))
            and all(type(getattr(settings, key)) is int and getattr(settings, key) > 0
                for key in ("AI_LESSON_PREP_MAX_OUTPUT_TOKENS", "AI_LESSON_PREP_TIMEOUT_SECONDS")))


def _runtime_pool_current():
    from app.core.config import settings
    from app.services.teacher_work.execution_capacity import _shared_capacity
    capacity = settings.TEACHER_WORK_MAX_ACTIVE_RUNS
    return (type(capacity) is int and capacity > 0 and
        (_runtime is None or (_runtime.pool is _shared_capacity and _runtime.pool.loop is _runtime.loop
            and _runtime.pool.capacity == min(capacity,4))))


def chat_capabilities():
    from app.core.config import settings
    if settings.TEACHER_WORK_PRIVATE_CHAT_ENABLED is not True:
        return PrivateChatCapabilities(), "private_chat_disabled"
    configured = provider_configured()
    capacity = settings.TEACHER_WORK_MAX_ACTIVE_RUNS
    available = (type(capacity) is int and capacity > 0 and _runtime_pool_current()
                 and (_runtime is None or not _runtime.closed and not _runtime.loop.is_closed()))
    return PrivateChatCapabilities(send=configured and available, history=True, read_run=True, cancel=True,
        provider_configured=configured), ("chat_runtime_unavailable" if not available else None if configured else "ai_ready")


class PrivateChatTransactions:
    """Strict synchronous ports: returned candidates already committed/closed."""
    def _binding(self, mode):
        from app.services.teacher_work.bootstrap import open_teacher_work_request, build_request_dependencies
        from contextlib import contextmanager
        @contextmanager
        def opened():
            authorization = request_authorization.get()
            operation = "private_chat_read" if mode == "read" else "private_chat_write"
            with open_teacher_work_request(authorization, mode=mode, operation=operation) as session:
                binding = build_request_dependencies(session, authorization=authorization, mode=mode,
                    operation=operation, clock=_now, new_uuid=uuid4)
                yield binding
        return opened()

    def history(self, task_id, *, limit=20, before=None):
        with self._binding("read") as binding:
            value = binding.repository.get_private_chat_history(binding.subject, task_id, limit=limit, before=before)
            return binding.finish_private_history(value)

    def _operation(self, name, owner, *args, **kwargs):
        mode = "read" if name in ("inspect_chat_request", "get_chat_run") else "write"
        with self._binding(mode) as binding:
            if owner != binding.subject:
                raise WorkAuthorizationError("NOT_FOUND", 404)
            if name == "reserve_chat_call" and not provider_configured():
                raise WorkRunError("WORK_AI_UNAVAILABLE", 503)
            value = getattr(binding.repository, name)(owner, *args, **kwargs)
            return binding.finish_chat_outcome(value, mode=mode)

    def inspect_chat_request(self, owner, task_id, command, key):
        return self._operation("inspect_chat_request", owner, task_id, command, key)

    def admit_chat(self, owner, task_id, command, key, **kwargs):
        return self._operation("admit_chat", owner, task_id, command, key, **kwargs)

    def reserve_chat_call(self, owner, task_id, run_id, **kwargs):
        return self._operation("reserve_chat_call", owner, task_id, run_id, **kwargs)

    def get_chat_run(self, owner, task_id, run_id):
        return self._operation("get_chat_run", owner, task_id, run_id)

    def cancel_chat(self, owner, task_id, run_id):
        return self._operation("cancel_chat", owner, task_id, run_id)

    def fail_pending_chat(self, owner, task_id, run_id, **kwargs):
        return self._operation("fail_pending_chat", owner, task_id, run_id, **kwargs)

    def _context_operation(self, name, original, *args):
        with self._binding("write") as binding:
            if original.actor_subject != binding.subject:
                raise WorkAuthorizationError("NOT_FOUND", 404)
            value = getattr(binding.repository, name)(original, *args)
            return binding.finish_chat_outcome(value, mode="write")

    def complete_prepared_chat_call(self, prepared):
        with self._binding("write") as binding:
            if prepared.original_ctx.actor_subject != binding.subject:
                raise WorkAuthorizationError("NOT_FOUND", 404)
            value = binding.repository.complete_prepared_chat_call(prepared)
            return binding.finish_chat_outcome(value, mode="write")

    def fail_chat_call(self, original, token, error):
        return self._context_operation("fail_chat_call", original, token, error)

    def expire_chat_call(self, original, token):
        return self._context_operation("expire_chat_call", original, token)

    def load(self, admission):
        with self._binding("read") as binding:
            if binding.subject != admission.context.actor_subject:
                raise WorkAuthorizationError("NOT_FOUND", 404)
            snapshot = binding.repository.get_private_snapshot(binding.subject, admission.context.task_id)
            if snapshot.task.input_revision != admission.context.input_revision:
                raise WorkRunError("STALE_INPUT_REVISION", 409)
            history = binding.repository.get_private_chat_history(binding.subject, admission.context.task_id,
                limit=12, exclude=admission.user_message.message_id)
            brief = ChatTaskBrief(task_id=snapshot.task.task_id, input_revision=snapshot.task.input_revision,
                title=snapshot.task.title, topic=snapshot.task.topic, audience=snapshot.task.audience,
                requirements=snapshot.working.requirements)
            command = ChatCommand(kind="chat", skill_ref=None, input_revision=admission.context.input_revision,
                payload={"text": admission.user_message.plain_text, "client_message_key": admission.user_message.client_message_key})
            saved = binding.finish_private_history(history)
            return ChatExecutionContext(command=command, history=saved.messages, evidence=(), task_brief=brief)


class _Clock:
    utc_now = staticmethod(_now)
    monotonic = staticmethod(time.monotonic)

    async def wait_until(self, deadline):
        await asyncio.sleep(max(0, deadline - time.monotonic()))


class PrivateChatRuntime:
    def __init__(self):
        from app.core.config import settings
        from app.services.teacher_lesson_prep.ai_client import LessonPrepAIClient
        from app.services.teacher_work.ai import LessonPrepWorkAI
        self.loop = asyncio.get_running_loop()
        self.closed = False
        self.transactions = PrivateChatTransactions()
        self.ai = LessonPrepWorkAI(LessonPrepAIClient())
        capacity = settings.TEACHER_WORK_MAX_ACTIVE_RUNS
        if type(capacity) is not int or capacity < 1:
            raise WorkRunError("WORK_EXECUTION_UNAVAILABLE", 503)
        from app.services.teacher_work.execution_capacity import get_shared_capacity
        try:
            self.pool = get_shared_capacity(capacity)
        except WorkRunError:
            raise WorkRunError("CHAT_RUNTIME_UNAVAILABLE", 503) from None
        self.pool.owners.add(self)
        self.execution = TeacherChatExecution(transactions=self.transactions, context_source=self.transactions,
            ai=self.ai, clock=_Clock(), process_instance=uuid4(), new_uuid=uuid4,
            configured_output_tokens=settings.AI_LESSON_PREP_MAX_OUTPUT_TOKENS,
            configured_timeout_seconds=settings.AI_LESSON_PREP_TIMEOUT_SECONDS, capacity=min(capacity, 4), pool=self.pool)

    async def close(self):
        """Stop only owned local tasks, preserving uncertain durable leases."""
        self.closed = True
        tasks = tuple(local.supervisor for local in self.execution._runs.values() if local.supervisor is not None)
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


def get_runtime(*, create=True):
    global _runtime
    if _runtime is not None:
        if _runtime.closed or _runtime.loop is not asyncio.get_running_loop():
            raise WorkRunError("CHAT_RUNTIME_UNAVAILABLE", 503)
        if create and not _runtime_pool_current():
            raise WorkRunError("CHAT_RUNTIME_UNAVAILABLE", 503)
        return _runtime
    if not create:
        return None
    if not provider_configured():
        raise WorkRunError("WORK_AI_UNAVAILABLE", 503)
    _runtime = PrivateChatRuntime()
    return _runtime


async def close_runtime():
    if _runtime is not None:
        await _runtime.close()


def public_run(run):
    if run.kind != "chat":
        raise WorkRunError("INVALID_CHAT_RUN", 503)
    return run.model_dump(mode="json", include={"run_id", "task_id", "kind", "input_revision", "stage", "attempt",
        "provider_call_count", "deadline", "cancelled_at", "error_code"})
