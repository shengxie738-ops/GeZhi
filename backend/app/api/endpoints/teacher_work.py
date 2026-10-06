"""Opt-in private task CRU and first-call chat; later Work stays closed."""
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import APIRouter, Header, Request
from fastapi.routing import APIRoute
from fastapi.responses import JSONResponse
from pydantic import TypeAdapter, ValidationError
from starlette.concurrency import run_in_threadpool
from uuid import UUID

from app.schemas.teacher_work import BODY_LIMIT, ChatCommand, CreateTaskRequest, MessageKey, WorkingPatchRequest

from app.repositories.teacher_work import WorkRepositoryError
from app.services.teacher_work.authorization import WorkAuthorizationError
from app.services.teacher_work.bootstrap import build_request_dependencies, open_teacher_work_request


def _response(status, message, data=None):
    return JSONResponse(status_code=status, content={"code": status, "message": message, "data": data},
                        headers={"Cache-Control": "no-store"})


def _clock():
    return datetime.now(timezone.utc)


class PrivateWorkBodyRoute(APIRoute):
    async def handle(self, scope, receive, send):
        if scope.get("method") not in ("POST", "PATCH"):
            await super().handle(scope, receive, send)
            return
        messages, size = [], 0
        while True:
            message = await receive()
            if message.get("type") == "http.request":
                size += len(message.get("body", b""))
                if size > BODY_LIMIT:
                    await _response(413, "REQUEST_BODY_TOO_LARGE")(scope, receive, send)
                    return
            messages.append(message)
            if message.get("type") != "http.request" or not message.get("more_body", False):
                break
        async def replay():
            return messages.pop(0) if messages else {"type": "http.request", "body": b"", "more_body": False}
        await super().handle(scope, replay, send)


def build_teacher_work_router(*, request_owner_factory, dependencies_factory):
    """Create routes once; construct owner/dependencies inside each request."""
    @asynccontextmanager
    async def lifespan(app):
        yield
        from app.services.teacher_work.private_chat import close_runtime
        await close_runtime()
    router = APIRouter(prefix="/teacher/work", tags=["teacher-work"], route_class=PrivateWorkBodyRoute, lifespan=lifespan)

    def task_operation(authorization, operation, *, task_id=None, body=None, key=None):
        mode = "read" if operation == "private_read" else "write"
        try:
            with request_owner_factory(authorization, mode=mode, operation=operation) as session:
                binding = dependencies_factory(session, authorization=authorization, mode=mode,
                    operation=operation, clock=_clock, new_uuid=uuid4)
                repository = binding.repository
                if operation == "private_create":
                    task_id = repository.create_task(binding.subject, body, key).task_id
                elif operation == "private_update":
                    repository.patch_working(binding.subject, task_id, body)
                snapshot = repository.get_private_snapshot(binding.subject, task_id)
                saved = binding.finish_private_snapshot(snapshot, mode=mode)
                return _response(200, "ok", saved.public_data())
        except (WorkAuthorizationError, WorkRepositoryError) as error:
            return _response(error.status_code, error.code)
        except Exception:
            return _response(503, "TEACHER_WORK_UNAVAILABLE")

    @router.get("/capabilities")
    def capabilities(authorization: str | None = Header(default=None)):
        try:
            with request_owner_factory(authorization, mode="read", operation="private_read") as session:
                binding = dependencies_factory(session, authorization=authorization, mode="read", operation="private_read", clock=_clock, new_uuid=uuid4)
                value = binding.finish_private_capabilities()
                return _response(200, "ok", value.model_dump(mode="json"))
        except (WorkAuthorizationError, WorkRepositoryError) as error:
            return _response(error.status_code, error.code)
        except Exception:
            return _response(503, "TEACHER_WORK_UNAVAILABLE")

    @router.post("/tasks")
    async def create_task(request: Request, authorization: str | None = Header(default=None),
                          idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
        try:
            key = TypeAdapter(MessageKey).validate_python(idempotency_key)
            body = CreateTaskRequest.model_validate_json(await request.body())
            if body.scope != "private" or body.offering_id is not None or any(not getattr(body, name).strip() for name in ("title", "topic", "audience")):
                raise ValueError("private nonblank metadata required")
        except (ValueError, ValidationError):
            return _response(422, "INVALID_PRIVATE_TASK_REQUEST")
        return await run_in_threadpool(task_operation, authorization, "private_create", body=body, key=key)

    @router.get("/tasks/{task_id}")
    def get_task(task_id: str, authorization: str | None = Header(default=None)):
        try:
            parsed = UUID(task_id)
        except ValueError:
            return _response(422, "INVALID_TASK_ID")
        return task_operation(authorization, "private_read", task_id=parsed)

    @router.patch("/tasks/{task_id}/working")
    async def patch_working(task_id: str, request: Request, authorization: str | None = Header(default=None)):
        try:
            parsed = UUID(task_id)
            body = WorkingPatchRequest.model_validate_json(await request.body())
            fields = body.changes.model_fields_set
            if (body.model_fields_set != {"expected_revision", "changes"} or not fields
                    or not fields <= {"requirements", "resource_ids", "target_slide_count"}):
                raise ValueError("private editable fields required")
        except (ValueError, ValidationError):
            return _response(422, "INVALID_PRIVATE_WORKING_REQUEST")
        return await run_in_threadpool(task_operation, authorization, "private_update", task_id=parsed, body=body)

    async def chat_operation(authorization, task_id, operation, *, command=None, key=None, run_id=None, limit=20, before=None):
        from app.services.teacher_work.private_chat import PrivateChatTransactions, request_authorization, get_runtime, public_run
        from app.services.teacher_work.runs import WorkRunError
        token = request_authorization.set(authorization)
        try:
            transactions = PrivateChatTransactions()
            if operation == "history":
                return _response(200, "ok", transactions.history(task_id, limit=limit, before=before).public_data())
            owner = transactions.history(task_id, limit=1).task.owner_subject
            if operation == "send":
                # Exact persisted replay is readable even if provider config has
                # disappeared. Only a newly admitted run can be dispatched.
                observed = transactions.inspect_chat_request(owner, task_id, command, key)
                if observed.admission is not None:
                    run = observed.admission.state.run
                else:
                    run = await get_runtime().execution.start_chat(owner, task_id, command, key)
            elif operation == "run":
                run = transactions.get_chat_run(owner, task_id, run_id).state.run
            else:
                runtime = get_runtime(create=False)
                run = (await runtime.execution.cancel_chat(owner, task_id, run_id) if runtime else
                       transactions.cancel_chat(owner, task_id, run_id).state.run)
            return _response(200, "ok", public_run(run))
        except (WorkAuthorizationError, WorkRepositoryError, WorkRunError) as error:
            return _response(error.status_code, error.code)
        except Exception:
            return _response(503, "TEACHER_WORK_UNAVAILABLE")
        finally:
            request_authorization.reset(token)

    @router.post("/tasks/{task_id}/messages")
    async def send_message(task_id: str, request: Request, authorization: str | None = Header(default=None),
                           idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
        try:
            parsed = UUID(task_id)
            key = TypeAdapter(MessageKey).validate_python(idempotency_key)
            command = ChatCommand.model_validate_json(await request.body())
            if not command.payload.text.strip():
                raise ValueError("nonblank chat input required")
        except (ValueError, ValidationError):
            return _response(422, "INVALID_PRIVATE_CHAT_REQUEST")
        return await chat_operation(authorization, parsed, "send", command=command, key=key)

    @router.get("/tasks/{task_id}/messages")
    async def get_messages(task_id: str, limit: str = "20", before: str | None = None,
                           authorization: str | None = Header(default=None)):
        try:
            parsed, cursor = UUID(task_id), UUID(before) if before is not None else None
            parsed_limit = int(limit)
            if not 1 <= parsed_limit <= 50:
                raise ValueError("bounded history required")
        except ValueError:
            return _response(422, "INVALID_PRIVATE_CHAT_HISTORY_REQUEST")
        return await chat_operation(authorization, parsed, "history", limit=parsed_limit, before=cursor)

    @router.get("/tasks/{task_id}/runs/{run_id}")
    async def get_run(task_id: str, run_id: str, authorization: str | None = Header(default=None)):
        try:
            parsed, run = UUID(task_id), UUID(run_id)
        except ValueError:
            return _response(422, "INVALID_PRIVATE_CHAT_RUN_REQUEST")
        return await chat_operation(authorization, parsed, "run", run_id=run)

    @router.post("/tasks/{task_id}/runs/{run_id}/cancel")
    async def cancel_run(task_id: str, run_id: str, request: Request, authorization: str | None = Header(default=None)):
        try:
            parsed, run = UUID(task_id), UUID(run_id)
            raw = await request.body()
            if raw.strip() and raw.strip() != b"{}":
                raise ValueError("empty cancellation body required")
        except ValueError:
            return _response(422, "INVALID_PRIVATE_CHAT_CANCEL_REQUEST")
        return await chat_operation(authorization, parsed, "cancel", run_id=run)

    return router


router = build_teacher_work_router(request_owner_factory=open_teacher_work_request,
                                   dependencies_factory=build_request_dependencies)
