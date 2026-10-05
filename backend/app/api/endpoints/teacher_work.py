"""Closed source-only Work router; no unsupplied functional task/read routes."""
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse

from app.repositories.teacher_work import WorkRepositoryError
from app.services.teacher_work.authorization import WorkAuthorizationError
from app.services.teacher_work.bootstrap import build_request_dependencies, open_teacher_work_request


def _response(status, message):
    return JSONResponse(status_code=status, content={"code": status, "message": message, "data": None},
                        headers={"Cache-Control": "no-store"})


def _clock():
    return datetime.now(timezone.utc)


def build_teacher_work_router(*, request_owner_factory, dependencies_factory):
    """Create routes once; construct owner/dependencies inside each request."""
    router = APIRouter(prefix="/teacher/work", tags=["teacher-work"])

    @router.get("/capabilities")
    def capabilities(authorization: str | None = Header(default=None)):
        try:
            with request_owner_factory(authorization, mode="read") as session:
                dependencies_factory(session, authorization=authorization, mode="read", clock=_clock, new_uuid=uuid4)
                # This partial source slice has no verified live capability.
                return _response(503, "TEACHER_WORK_UNAVAILABLE")
        except (WorkAuthorizationError, WorkRepositoryError) as error:
            return _response(error.status_code, error.code)
        except Exception:
            return _response(503, "TEACHER_WORK_UNAVAILABLE")

    return router


router = build_teacher_work_router(request_owner_factory=open_teacher_work_request,
                                   dependencies_factory=build_request_dependencies)
