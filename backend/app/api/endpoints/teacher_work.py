"""Default-closed private task CRU; later Work operations remain unavailable."""
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Header, Request
from fastapi.routing import APIRoute
from fastapi.responses import JSONResponse
from pydantic import TypeAdapter, ValidationError
from starlette.concurrency import run_in_threadpool
from uuid import UUID

from app.schemas.teacher_work import BODY_LIMIT, CreateTaskRequest, MessageKey, WorkingPatchRequest

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
    router = APIRouter(prefix="/teacher/work", tags=["teacher-work"], route_class=PrivateWorkBodyRoute)

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

    return router


router = build_teacher_work_router(request_owner_factory=open_teacher_work_request,
                                   dependencies_factory=build_request_dependencies)
