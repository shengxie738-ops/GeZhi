"""Read-only student Work discovery; current-account auth grants no new powers."""
from fastapi import APIRouter, Depends, Response
from app.api.deps import get_auth_payload
from app.services.student_work_capabilities import student_work_capabilities

router = APIRouter(prefix="/student/work", tags=["student-work"])


@router.get("/capabilities")
def get_capabilities(response: Response, auth: dict = Depends(get_auth_payload)):
    response.headers["Cache-Control"] = "private, no-store"
    return student_work_capabilities()
