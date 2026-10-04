"""B1 HTTP adapter; isolated router tests never import the aggregate application.

Task4 course/lifecycle/local-role routes and recovery use strict DTOs, the
dedicated dependency and the accepted commit-before-response helper.
"""
import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.user_account import UserAccount
from app.schemas.teaching import (
    CourseQuery, OfferingDTO, OfferingPageDTO, OfferingQuery, PageQuery,
    ReceiptQuery, WriteResultDTO,
)
from app.services.current_identity import resolve_current_account
from app.services.teaching import access
from app.services.teaching.sessions import open_teaching_session
from app.services.teaching.types import ScopeRef, TeachingAction, exact_identifier
from app.services.teaching.writes import execute_write, find_receipt, get_receipt, require_clean_transaction

logger = logging.getLogger(__name__)


def _response(status, message, data=None):
    return JSONResponse(status_code=status, content={"code": status, "message": message, "data": data},
                        headers={"Cache-Control": "no-store"})


def _domain_error(exc, data=None):
    # Only narrow machine-code reasons are public, never arbitrary exception text.
    reason = exc.detail if isinstance(exc.detail, str) and exc.detail.replace("_", "").isalnum() else "unauthenticated" if exc.status_code == 401 else "request_failed"
    if exc.status_code == 404:
        reason = "not_found"
    elif exc.status_code == 401:
        reason = "unauthenticated"
    return _response(exc.status_code, reason, data)


def _private_error():
    correlation = str(uuid4())
    import sys
    exception_type = sys.exc_info()[0]
    logger.error("Teaching private error correlation=%s exception_class=%s",
                 correlation, exception_type.__name__ if exception_type else "UnknownError")
    return _response(500, "internal_error", {"correlation_id": correlation})


class TeachingRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()
        async def handle(request):
            try:
                response = await original(request)
                response.headers["Cache-Control"] = "no-store"
                return response
            except HTTPException as exc:
                return _domain_error(exc)
            except (RequestValidationError, ValidationError):
                return _response(422, "validation_error")
            except (OperationalError, IntegrityError):
                return _response(503, "database_unavailable")
            except Exception:
                return _private_error()
        return handle


router = APIRouter(prefix="/teaching", tags=["teaching"], route_class=TeachingRoute)


def get_teaching_db():
    # No import-time connection/startup and no legacy get_db/SessionLocal reuse.
    from app.core.database import engine
    with open_teaching_session(engine) as db:
        yield db


def get_teaching_account(
    authorization: str | None = Header(default=None), db: Session = Depends(get_teaching_db),
) -> UserAccount:
    if not isinstance(db, Session):
        raise TypeError("explicit dedicated Session required")
    return resolve_current_account(authorization, db)


async def get_teaching_request_account(
    authorization: str | None = Header(default=None), db: Session = Depends(get_teaching_db),
) -> UserAccount:
    # Keep the exported synchronous helper compatible with explicit direct
    # callers. Request identity and endpoint SQL share the same request thread
    # and dedicated Session; no fake current-account dependency is introduced.
    # Synchronous SQL latency/event-loop responsiveness is a separate gate.
    return get_teaching_account(authorization, db)


def _query(request, dto):
    pairs = list(request.query_params.multi_items())
    if len(pairs) != len({key for key, value in pairs}):
        raise HTTPException(422, "validation_error")
    values = dict(pairs)
    if "limit" in values:
        value = values["limit"]
        if (not value.isascii() or not value.isdecimal() or len(value) > 3
                or value != str(int(value))):
            raise HTTPException(422, "validation_error")
        values["limit"] = int(value)
    return dto.model_validate(values)


def _no_query(request):
    if request.query_params:
        raise HTTPException(422, "validation_error")


def _require_offering_id(offering_id):
    # Match the accepted detail-reader hidden-object boundary before building
    # ScopeRef or querying management rows. Malformed IDs reveal no existence.
    if not exact_identifier(offering_id, 36):
        raise HTTPException(404, "not_found")


def _read_data(result):
    values = result.model_dump(mode="json")
    offerings = values["items"] if isinstance(result, OfferingPageDTO) else [values] if isinstance(result, OfferingDTO) else []
    for offering in offerings:
        # Configured authority remains visible, but the unmodified production
        # write-safety gate prevents every write action from being operational.
        offering["access"]["available_actions"] = []
    return values


@router.get("/capabilities")
async def read_capabilities(request: Request, account: UserAccount = Depends(get_teaching_request_account), db: Session = Depends(get_teaching_db)):
    _no_query(request)
    values = access.get_capabilities(db, account.username).model_dump(mode="json")
    values["can_create_course"] = False
    return _response(200, "ok", values)


@router.get("/courses")
async def read_courses(request: Request, account: UserAccount = Depends(get_teaching_request_account), db: Session = Depends(get_teaching_db)):
    return _response(200, "ok", _read_data(access.list_courses(db, account.username, _query(request, CourseQuery))))


@router.get("/offerings")
async def read_offerings(request: Request, account: UserAccount = Depends(get_teaching_request_account), db: Session = Depends(get_teaching_db)):
    return _response(200, "ok", _read_data(access.list_offerings(db, account.username, _query(request, OfferingQuery))))


@router.get("/courses/{course_id}")
async def read_course(course_id: str, request: Request, account: UserAccount = Depends(get_teaching_request_account), db: Session = Depends(get_teaching_db)):
    _no_query(request)
    return _response(200, "ok", _read_data(access.get_course(db, account.username, course_id)))


@router.get("/offerings/{offering_id}")
async def read_offering(offering_id: str, request: Request, account: UserAccount = Depends(get_teaching_request_account), db: Session = Depends(get_teaching_db)):
    _no_query(request)
    return _response(200, "ok", _read_data(access.get_offering(db, account.username, offering_id)))


@router.get("/offerings/{offering_id}/enrollment")
async def read_own_enrollment(offering_id: str, request: Request, account: UserAccount = Depends(get_teaching_request_account), db: Session = Depends(get_teaching_db)):
    _no_query(request)
    return _response(200, "ok", _read_data(access.get_own_enrollment(db, account.username, offering_id)))


@router.get("/offerings/{offering_id}/roster")
async def read_roster(offering_id: str, request: Request, account: UserAccount = Depends(get_teaching_request_account), db: Session = Depends(get_teaching_db)):
    query = _query(request, PageQuery)
    _require_offering_id(offering_id)
    return _response(200, "ok", _read_data(access.get_roster(db, account.username, offering_id, query)))


@router.get("/offerings/{offering_id}/roles")
async def read_roles(offering_id: str, request: Request, account: UserAccount = Depends(get_teaching_request_account), db: Session = Depends(get_teaching_db)):
    _no_query(request)
    _require_offering_id(offering_id)
    return _response(200, "ok", _read_data(access.get_roles(db, account.username, offering_id)))


def _write_data(result):
    return WriteResultDTO(receipt=result.receipt, result=result.result, replayed=result.replayed).model_dump(mode="json")


def _recovery_data(intent):
    # Only the original receipt lookup tuple is disclosed. No request body,
    # actor/profile, credentials, raw exception text or client/server hash.
    query = ReceiptQuery(action=intent.action.value, scope_type=intent.scope.kind,
                         scope_id=intent.scope.id, key=intent.idempotency_key)
    return {"recovery": query.model_dump(mode="json")}


def commit_write(db: Session, intent, authorization_scope, mutation):
    """Serialize provisionally, then commit once, then construct the success HTTP.

    A failed/ambiguous commit never warrants a new idempotency key. Recovery uses
    the same actor/action/scope/key and remains subject to current authorization.
    """
    recovery = None
    try:
        recovery = _recovery_data(intent)
        result = execute_write(db, intent, authorization_scope, mutation)
        data = _write_data(result)
        require_clean_transaction(db)
    except HTTPException as exc:
        db.rollback()
        return _domain_error(exc, recovery if exc.status_code == 503 else None)
    except Exception:
        db.rollback()
        return _private_error()
    try:
        db.commit()
    except SQLAlchemyError:
        try:
            db.rollback()
        finally:
            return _response(503, "write_outcome_unknown", recovery)
    except Exception:
        db.rollback()
        return _private_error()
    return _response(200 if result.replayed else result.receipt.http_status, "ok", data)


@router.get("/receipts")
async def recover_by_key(request: Request, account: UserAccount = Depends(get_teaching_request_account), db: Session = Depends(get_teaching_db)):
    pairs = list(request.query_params.multi_items())
    if len(pairs) != len({key for key, value in pairs}):
        raise HTTPException(422, "validation_error")
    query = ReceiptQuery.model_validate(dict(pairs))
    inputs = access._inputs(db)
    reason = access._availability(inputs)
    if reason:
        raise HTTPException(503, reason)
    try:
        scope = ScopeRef(inputs.institution_id, query.scope_type, query.scope_id)
    except ValueError:
        raise HTTPException(422, "validation_error")
    result = find_receipt(db, account.username, TeachingAction(query.action), scope, query.key)
    return _response(200, "ok", _write_data(result))


@router.get("/receipts/{receipt_id}")
async def recover_by_id(receipt_id: str, request: Request, account: UserAccount = Depends(get_teaching_request_account), db: Session = Depends(get_teaching_db)):
    _no_query(request)
    if not exact_identifier(receipt_id, 36):
        raise HTTPException(404, "not_found")
    result = get_receipt(db, account.username, receipt_id)
    return _response(200, "ok", _write_data(result))


# Task4 mutation adapters retain the unconditional production safety gate.
from app.schemas.teaching import (
    CreateCourseCommand, UpdateCourseCommand, CreateOfferingCommand,
    UpdateOfferingCommand, TransitionOfferingCommand, SetRoleCommand,
)
from app.services.teaching.courses import prepare_course_write
from app.services.teaching.roles import prepare_role_write


def _course_command(db, account, purpose, command, key, target_id=None):
    intent, operation = prepare_course_write(db, account.username, purpose, command, key, target_id)
    return commit_write(db, intent, intent.scope, operation)


@router.post("/courses")
async def create_course(command: CreateCourseCommand, key: str = Header(alias="Idempotency-Key"),
                        account: UserAccount = Depends(get_teaching_request_account), db: Session = Depends(get_teaching_db)):
    return _course_command(db, account, "course_create", command, key)


@router.patch("/courses/{course_id}")
async def update_course(course_id: str, command: UpdateCourseCommand, key: str = Header(alias="Idempotency-Key"),
                        account: UserAccount = Depends(get_teaching_request_account), db: Session = Depends(get_teaching_db)):
    return _course_command(db, account, "course_update", command, key, course_id)


@router.post("/courses/{course_id}/offerings")
async def create_offering(course_id: str, command: CreateOfferingCommand, key: str = Header(alias="Idempotency-Key"),
                          account: UserAccount = Depends(get_teaching_request_account), db: Session = Depends(get_teaching_db)):
    return _course_command(db, account, "offering_create", command, key, course_id)


@router.patch("/offerings/{offering_id}")
async def update_offering(offering_id: str, command: UpdateOfferingCommand, key: str = Header(alias="Idempotency-Key"),
                          account: UserAccount = Depends(get_teaching_request_account), db: Session = Depends(get_teaching_db)):
    return _course_command(db, account, "offering_update", command, key, offering_id)


@router.post("/offerings/{offering_id}/transitions")
async def transition_offering(offering_id: str, command: TransitionOfferingCommand, key: str = Header(alias="Idempotency-Key"),
                              account: UserAccount = Depends(get_teaching_request_account), db: Session = Depends(get_teaching_db)):
    return _course_command(db, account, "offering_transition", command, key, offering_id)


@router.put("/offerings/{offering_id}/roles/{subject_id}")
async def set_role(offering_id: str, subject_id: str, command: SetRoleCommand, key: str = Header(alias="Idempotency-Key"),
                    account: UserAccount = Depends(get_teaching_request_account), db: Session = Depends(get_teaching_db)):
    intent, operation = prepare_role_write(db, account.username, offering_id, subject_id, command, key)
    return commit_write(db, intent, intent.scope, operation)


# Task5 roster adapters retain original receipt and full-set contracts.
from app.schemas.teaching import RosterPreviewCommand, RosterApplicationCommand, PreviewChangesQuery
from app.services.teaching.rosters import prepare_roster_write, get_roster_preview, list_roster_preview_changes


@router.post("/offerings/{offering_id}/roster-previews")
async def create_roster_preview(offering_id: str, command: RosterPreviewCommand,
                                key: str = Header(alias="Idempotency-Key"),
                                account: UserAccount = Depends(get_teaching_request_account), db: Session = Depends(get_teaching_db)):
    intent, operation = prepare_roster_write(db, account.username, offering_id, "preview", command, key)
    return commit_write(db, intent, intent.scope, operation)


@router.post("/offerings/{offering_id}/roster-applications")
async def create_roster_application(offering_id: str, command: RosterApplicationCommand,
                                    key: str = Header(alias="Idempotency-Key"),
                                    account: UserAccount = Depends(get_teaching_request_account), db: Session = Depends(get_teaching_db)):
    intent, operation = prepare_roster_write(db, account.username, offering_id, "apply", command, key)
    return commit_write(db, intent, intent.scope, operation)


@router.get("/offerings/{offering_id}/roster-previews/{preview_id}")
async def read_roster_preview(offering_id: str, preview_id: str, request: Request,
                              account: UserAccount = Depends(get_teaching_request_account), db: Session = Depends(get_teaching_db)):
    if request.query_params:
        raise HTTPException(422, "validation_error")
    result = get_roster_preview(db, account.username, offering_id, preview_id)
    return _response(200, "ok", result.model_dump(mode="json"))


@router.get("/offerings/{offering_id}/roster-previews/{preview_id}/changes")
async def read_roster_preview_changes(offering_id: str, preview_id: str, request: Request,
                                      account: UserAccount = Depends(get_teaching_request_account), db: Session = Depends(get_teaching_db)):
    pairs = list(request.query_params.multi_items())
    if len(pairs) != len({key for key, value in pairs}):
        raise HTTPException(422, "validation_error")
    values = dict(pairs)
    if "limit" in values:
        limit = values["limit"]
        if not limit.isascii() or not limit.isdecimal() or len(limit) > 3:
            raise HTTPException(422, "validation_error")
        values["limit"] = int(limit)
    query = PreviewChangesQuery.model_validate(values)
    result = list_roster_preview_changes(db, account.username, offering_id, preview_id, query)
    return _response(200, "ok", result.model_dump(mode="json"))
