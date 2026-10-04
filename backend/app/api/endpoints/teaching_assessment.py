"""Strict finite B2 HTTP adapter; source/synthetic readiness only.

Reads retain B1's dedicated dependency. The seven B2 mutations use one
explicit B2 request owner, the real current-account resolver, no-store errors
and the shared guarded commit-before-success helper. Every production write remains
unconditionally refused by the shared write-safety gate. No startup or activation.
"""
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.endpoints.teaching import (
    TeachingRoute, _no_query, _query, _response, commit_write, commit_owned_b2_write, get_teaching_account,
    get_teaching_db, get_teaching_request_account,
)
from app.models.user_account import UserAccount
from app.schemas.teaching_assessment import (
    AssessmentPageQuery, ConfirmReleaseCommand, CreateAssignmentCommand,
    CreateSubmissionCommand, FreezeAssignmentCommand, RecipientPageQuery,
    ReleasePreviewCommand, ReplaceAssignmentDraftCommand,
    ReplacePrivateDraftCommand, SubmissionHistoryQuery, TeacherSubmissionQuery,
)
from app.services.teaching import assignments, releases, submissions
from app.services.teaching.types import exact_identifier
from app.services.teaching.sessions import B2RequestOwner, open_b2_teaching_session

router = APIRouter(prefix='/teaching', tags=['teaching-assessment'], route_class=TeachingRoute)


async def get_b2_write_owner():
    # No test-support import, switch, startup or second identity Session.
    from app.core.database import engine
    with open_b2_teaching_session(engine) as owner:
        yield owner


def get_b2_db(owner: B2RequestOwner = Depends(get_b2_write_owner)) -> Session:
    return owner.session


async def get_b2_request_account(
    authorization: str | None = Header(default=None), db: Session = Depends(get_b2_db),
) -> UserAccount:
    return get_teaching_account(authorization, db)


def _paths(*identifiers):
    if any(not exact_identifier(identifier, 36) for identifier in identifiers):
        raise HTTPException(404, 'not_found')


def _read(result):
    return _response(200, 'ok', result.model_dump(mode='json'))


def _assignment_write(db, account, purpose, command, key, owner, *, offering_id=None, assignment_id=None):
    intent, operation = assignments.prepare_assignment_write(
        db, account.username, offering_id, assignment_id, purpose, command, key)
    return commit_owned_b2_write(owner, intent, intent.scope, operation)


def _release_write(db, account, assignment_id, purpose, command, key, owner):
    intent, operation = releases.prepare_release_write(
        db, account.username, assignment_id, purpose, command, key)
    return commit_owned_b2_write(owner, intent, intent.scope, operation)


@router.get('/offerings/{offering_id}/assignments')
async def list_assignments(offering_id: str, request: Request,
                           account: UserAccount = Depends(get_teaching_request_account), db: Session = Depends(get_teaching_db)):
    _paths(offering_id)
    return _read(assignments.list_assignments(db, account.username, offering_id, _query(request, AssessmentPageQuery)))


@router.post('/offerings/{offering_id}/assignments')
async def create_assignment(offering_id: str, request: Request, command: CreateAssignmentCommand,
                            key: str = Header(alias='Idempotency-Key'),
                            account: UserAccount = Depends(get_b2_request_account), db: Session = Depends(get_b2_db),
                            owner: B2RequestOwner = Depends(get_b2_write_owner)):
    _no_query(request); _paths(offering_id)
    return _assignment_write(db, account, 'create', command, key, owner, offering_id=offering_id)


@router.get('/assignments/{assignment_id}/draft')
async def read_assignment_draft(assignment_id: str, request: Request,
                                account: UserAccount = Depends(get_teaching_request_account), db: Session = Depends(get_teaching_db)):
    _no_query(request); _paths(assignment_id)
    return _read(assignments.get_assignment_draft(db, account.username, assignment_id))


@router.patch('/assignments/{assignment_id}/draft')
async def replace_assignment_draft(assignment_id: str, request: Request, command: ReplaceAssignmentDraftCommand,
                                   key: str = Header(alias='Idempotency-Key'),
                                   account: UserAccount = Depends(get_b2_request_account), db: Session = Depends(get_b2_db),
                            owner: B2RequestOwner = Depends(get_b2_write_owner)):
    _no_query(request); _paths(assignment_id)
    return _assignment_write(db, account, 'replace_public', command, key, owner, assignment_id=assignment_id)


@router.get('/assignments/{assignment_id}/private-draft')
async def read_private_draft(assignment_id: str, request: Request,
                             account: UserAccount = Depends(get_teaching_request_account), db: Session = Depends(get_teaching_db)):
    _no_query(request); _paths(assignment_id)
    return _read(assignments.get_private_spec(db, account.username, assignment_id, None))


@router.put('/assignments/{assignment_id}/private-draft')
async def replace_private_draft(assignment_id: str, request: Request, command: ReplacePrivateDraftCommand,
                                key: str = Header(alias='Idempotency-Key'),
                                account: UserAccount = Depends(get_b2_request_account), db: Session = Depends(get_b2_db),
                            owner: B2RequestOwner = Depends(get_b2_write_owner)):
    _no_query(request); _paths(assignment_id)
    return _assignment_write(db, account, 'replace_private', command, key, owner, assignment_id=assignment_id)


@router.get('/assignments/{assignment_id}/versions')
async def list_assignment_versions(assignment_id: str, request: Request,
                                   account: UserAccount = Depends(get_teaching_request_account), db: Session = Depends(get_teaching_db)):
    _paths(assignment_id)
    return _read(assignments.list_assignment_versions(db, account.username, assignment_id, _query(request, AssessmentPageQuery)))


@router.post('/assignments/{assignment_id}/versions')
async def freeze_assignment(assignment_id: str, request: Request, command: FreezeAssignmentCommand,
                            key: str = Header(alias='Idempotency-Key'),
                            account: UserAccount = Depends(get_b2_request_account), db: Session = Depends(get_b2_db),
                            owner: B2RequestOwner = Depends(get_b2_write_owner)):
    _no_query(request); _paths(assignment_id)
    return _assignment_write(db, account, 'freeze', command, key, owner, assignment_id=assignment_id)


@router.get('/assignments/{assignment_id}/versions/{version_id}')
async def read_assignment_version(assignment_id: str, version_id: str, request: Request,
                                  account: UserAccount = Depends(get_teaching_request_account), db: Session = Depends(get_teaching_db)):
    _no_query(request); _paths(assignment_id, version_id)
    return _read(assignments.get_assignment_version(db, account.username, assignment_id, version_id))


@router.get('/assignments/{assignment_id}/versions/{version_id}/private-spec')
async def read_private_spec(assignment_id: str, version_id: str, request: Request,
                            account: UserAccount = Depends(get_teaching_request_account), db: Session = Depends(get_teaching_db)):
    _no_query(request); _paths(assignment_id, version_id)
    return _read(assignments.get_private_spec(db, account.username, assignment_id, version_id))


@router.post('/assignments/{assignment_id}/release-previews')
async def preview_release(assignment_id: str, request: Request, command: ReleasePreviewCommand,
                          key: str = Header(alias='Idempotency-Key'),
                          account: UserAccount = Depends(get_b2_request_account), db: Session = Depends(get_b2_db),
                            owner: B2RequestOwner = Depends(get_b2_write_owner)):
    _no_query(request); _paths(assignment_id)
    return _release_write(db, account, assignment_id, 'preview', command, key, owner)


@router.get('/assignments/{assignment_id}/release-previews/{preview_id}')
async def read_release_preview(assignment_id: str, preview_id: str, request: Request,
                               account: UserAccount = Depends(get_teaching_request_account), db: Session = Depends(get_teaching_db)):
    _no_query(request); _paths(assignment_id, preview_id)
    return _read(releases.get_release_preview(db, account.username, assignment_id, preview_id))


@router.get('/assignments/{assignment_id}/release-previews/{preview_id}/recipients')
async def list_preview_recipients(assignment_id: str, preview_id: str, request: Request,
                                  account: UserAccount = Depends(get_teaching_request_account), db: Session = Depends(get_teaching_db)):
    _paths(assignment_id, preview_id)
    return _read(releases.list_release_preview_recipients(db, account.username, assignment_id, preview_id, _query(request, RecipientPageQuery)))


@router.post('/assignments/{assignment_id}/releases')
async def confirm_release(assignment_id: str, request: Request, command: ConfirmReleaseCommand,
                          key: str = Header(alias='Idempotency-Key'),
                          account: UserAccount = Depends(get_b2_request_account), db: Session = Depends(get_b2_db),
                            owner: B2RequestOwner = Depends(get_b2_write_owner)):
    _no_query(request); _paths(assignment_id)
    return _release_write(db, account, assignment_id, 'confirm', command, key, owner)


@router.get('/offerings/{offering_id}/releases')
async def list_releases(offering_id: str, request: Request,
                        account: UserAccount = Depends(get_teaching_request_account), db: Session = Depends(get_teaching_db)):
    _paths(offering_id)
    return _read(releases.list_releases(db, account.username, offering_id, _query(request, AssessmentPageQuery)))


@router.get('/releases/{release_id}')
async def read_release(release_id: str, request: Request,
                       account: UserAccount = Depends(get_teaching_request_account), db: Session = Depends(get_teaching_db)):
    _no_query(request); _paths(release_id)
    return _read(releases.get_release(db, account.username, release_id))


@router.get('/releases/{release_id}/recipients')
async def list_historical_recipients(release_id: str, request: Request,
                                    account: UserAccount = Depends(get_teaching_request_account), db: Session = Depends(get_teaching_db)):
    _paths(release_id)
    return _read(releases.list_historical_recipients(db, account.username, release_id, _query(request, RecipientPageQuery)))


@router.post('/releases/{release_id}/submissions')
async def create_submission(release_id: str, request: Request, command: CreateSubmissionCommand,
                             key: str = Header(alias='Idempotency-Key'),
                             account: UserAccount = Depends(get_b2_request_account), db: Session = Depends(get_b2_db),
                            owner: B2RequestOwner = Depends(get_b2_write_owner)):
    _no_query(request); _paths(release_id)
    intent, operation = submissions.prepare_submission_write(db, account.username, release_id, command, key)
    return commit_owned_b2_write(owner, intent, intent.scope, operation)


@router.get('/releases/{release_id}/my-submission-head')
async def read_own_submission_head(release_id: str, request: Request,
                                   account: UserAccount = Depends(get_teaching_request_account), db: Session = Depends(get_teaching_db)):
    _no_query(request); _paths(release_id)
    return _read(submissions.get_submission_head(db, account.username, release_id))


@router.get('/releases/{release_id}/my-submissions')
async def list_own_submissions(release_id: str, request: Request,
                               account: UserAccount = Depends(get_teaching_request_account), db: Session = Depends(get_teaching_db)):
    _paths(release_id)
    return _read(submissions.list_own_submission_history(db, account.username, release_id, _query(request, SubmissionHistoryQuery)))


@router.get('/releases/{release_id}/submissions')
async def list_teacher_submissions(release_id: str, request: Request,
                                   account: UserAccount = Depends(get_teaching_request_account), db: Session = Depends(get_teaching_db)):
    _paths(release_id)
    return _read(submissions.list_release_submissions(db, account.username, release_id, _query(request, TeacherSubmissionQuery)))


@router.get('/submissions/{submission_id}')
async def read_submission(submission_id: str, request: Request,
                          account: UserAccount = Depends(get_teaching_request_account), db: Session = Depends(get_teaching_db)):
    _no_query(request); _paths(submission_id)
    return _read(submissions.get_submission(db, account.username, submission_id))
