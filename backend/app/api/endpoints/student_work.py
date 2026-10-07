"""Read-only student Work discovery; current-account auth grants no new powers."""
from fastapi import APIRouter, Depends, Response
from app.api.deps import get_auth_payload
from app.core.database import get_db
from sqlalchemy.orm import Session
from app.services.chat_batch_schema import paper_batch_readiness
from app.services.student_work_capabilities import student_work_capabilities

router = APIRouter(prefix="/student/work", tags=["student-work"])


@router.get("/capabilities")
def get_capabilities(response: Response, auth: dict = Depends(get_auth_payload), db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers['X-Gezhi-Paper-Batch-Available'] = str(paper_batch_readiness(db)['available']).lower()
    return student_work_capabilities()
