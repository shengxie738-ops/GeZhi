"""Server-owned assessment visibility and deadline rules."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import math
from fastapi import HTTPException


PRIVATE_QUESTION_FIELDS = {'correctAnswer', 'correctAnswers', 'answer', 'answers', 'solution', 'solutions', 'explanation', 'explanations', 'testCases', 'hiddenTests', 'privateTests', 'referenceCode', 'standardAnswer'}


def student_assessment_view(value):
    if isinstance(value, dict):
        return {key: student_assessment_view(item) for key, item in value.items() if key not in PRIVATE_QUESTION_FIELDS}
    if isinstance(value, list):
        return [student_assessment_view(item) for item in value]
    return deepcopy(value)


def parse_time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        # Browser datetime-local values in this Chinese-language product are local school time.
        if parsed.tzinfo is None:
            from zoneinfo import ZoneInfo
            parsed = parsed.replace(tzinfo=ZoneInfo('Asia/Shanghai'))
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail='Invalid assessment timestamp')


def deadline(exam, attempt=None):
    try:
        duration = float(exam.get('durationMinutes', 60))
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError()
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail='Invalid exam duration')
    starts = parse_time(exam.get('startsAt'))
    personal = parse_time((attempt or {}).get('startedAt'))
    candidates = [value for value in (parse_time(exam.get('endsAt')), starts + timedelta(minutes=duration) if starts else None, personal + timedelta(minutes=duration) if personal else None) if value]
    return min(candidates) if candidates else None


def assert_exam_open(exam, attempt=None):
    if not exam:
        raise HTTPException(status_code=404, detail='Exam not found')
    if exam.get('status') not in {'scheduled', 'upcoming', 'running', 'active'}:
        raise HTTPException(status_code=409, detail='Exam is not open')
    now = datetime.now(timezone.utc)
    starts = parse_time(exam.get('startsAt'))
    if starts and now < starts:
        raise HTTPException(status_code=409, detail='Exam has not started')
    end = deadline(exam, attempt)
    if end and now >= end:
        raise HTTPException(status_code=403, detail='Exam deadline has passed')


def attempt_receipt(exam, attempt):
    end = deadline(exam, attempt)
    return {key: attempt.get(key) for key in ('attemptId', 'startedAt', 'status', 'answers', 'progress', 'submittedAt')} | {
        'deadlineAt': end.isoformat() if end else None,
        'remainingSeconds': max(0, int((end-datetime.now(timezone.utc)).total_seconds())) if end else None,
    }


def submission_receipt(attempt):
    return {key: attempt.get(key) for key in ('attemptId', 'status', 'submittedAt', 'objectiveScore', 'correctCount', 'wrongCount', 'programmingStatus', 'late')}



def atomic_exam_mutation(handler):
    """Serialize mutations on the existing exam row, including new attempts.

    MySQL SELECT FOR UPDATE coordinates independent server workers; every
    JsonStore write in this request commits together only after success.
    """
    from functools import wraps
    from inspect import signature
    from app.repositories.json_store import JsonStore, atomic_store
    from app.models.domain_record import DomainRecord

    handler_signature = signature(handler)

    @wraps(handler)
    async def wrapped(*args, **kwargs):
        bound = handler_signature.bind(*args, **kwargs)
        bound.apply_defaults()
        values = bound.arguments
        db = values["db"]
        exam_id = values.get("exam_id")
        if not exam_id:
            attempt = JsonStore(db).get_payload("exams", "attempt", values.get("attempt_id"))
            if not attempt:
                raise HTTPException(status_code=404, detail="Attempt not found")
            exam_id = attempt.get("examId")
        with atomic_store(db):
            record = db.query(DomainRecord).filter(
                DomainRecord.module == "exams", DomainRecord.record_type == "exam",
                DomainRecord.record_key == exam_id,
            ).order_by(DomainRecord.id.desc()).with_for_update().first()
            if not record:
                raise HTTPException(status_code=404, detail="Exam not found")
            return await handler(*args, **kwargs)
    return wrapped



def validate_exam_publication(exam):
    status = exam.get("status", "draft")
    if status not in {"draft", "scheduled", "upcoming", "running", "active", "completed"}:
        raise HTTPException(status_code=422, detail="Invalid exam status")
    # Validate all supplied values even on drafts; drafts may omit the start.
    deadline(exam)
    starts = parse_time(exam.get("startsAt"))
    ends = parse_time(exam.get("endsAt"))
    if status != "draft" and starts is None:
        raise HTTPException(status_code=422, detail="A published exam requires a start time")
    if ends and starts and ends <= starts:
        raise HTTPException(status_code=422, detail="Exam end must be after its start")
