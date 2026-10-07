"""Account-bound versioned CRUD. No provider client or credential read endpoint."""
from fastapi import APIRouter, Request
from sqlalchemy import select
from app.core.database import SessionLocal, engine
from app.core.config import settings
from app.core.security import decode_access_token
from app.core.byok_crypto import load_byok_keyring
from app.models.user_account import UserAccount
from app.schemas.user_model import (
    UserCustomModelCreateRequest,
    UserCustomModelUpdateRequest,
    UserCustomModelDeleteRequest,
    UserModelCheckSelectionRequest,
)
from app.services.byok.errors import ByokError
from app.services.byok.types import AuthenticatedModelActor
from app.services.byok.http_boundary import read_bounded_body, parse_bounded_json
from app.services.byok.schema import observe_byok_schema
from app.services.byok.reservations import CustomTransactionOwner
router = APIRouter(prefix='/user/models', tags=['UserCustomModels'])


def _owner(*, read_only=False):
    with engine.connect() as connection:
        observation = observe_byok_schema(connection)
    if observation is None or not observation.available:
        raise ByokError('BYOK_STORAGE_UNAVAILABLE')
    try:
        keyring = load_byok_keyring(settings.BYOK_ENCRYPTION_ACTIVE_KEY_ID, settings.BYOK_ENCRYPTION_KEYRING)
    except ByokError:
        keyring = None
    return CustomTransactionOwner(
        SessionLocal,
        read_only=read_only,
        keyring=keyring,
        schema_observation=observation
    )


def _actor(request, tx):
    authorization = request.headers.get('authorization', '')
    if not authorization.lower().startswith('bearer '):
        raise ByokError('AUTHENTICATED_ACTOR_REQUIRED')
    try:
        claims = decode_access_token(authorization.split(' ', 1)[1])
    except Exception:
        raise ByokError('AUTHENTICATED_ACTOR_REQUIRED') from None
    subject = claims.get('sub') if isinstance(claims, dict) else None
    if type(subject) is not str or not subject:
        raise ByokError('AUTHENTICATED_ACTOR_REQUIRED')
    query = select(UserAccount).where(UserAccount.username == subject).execution_options(populate_existing=True)
    if not tx.read_only:
        query = query.with_for_update()
    account = tx.session.execute(query).scalar_one_or_none()
    if account is None:
        raise ByokError('AUTHENTICATED_ACTOR_REQUIRED')
    actor = AuthenticatedModelActor.from_current_account(account)
    tx.repository._accounts[actor.subject] = account
    return actor


def _success(value):
    return {'status': 'success', 'data': value.model_dump(mode='json')}


@router.get('', response_model=dict)
async def list_user_custom_models(request: Request):
    with _owner(read_only=True) as tx:
        result = tx.repository.inventory_snapshot(_actor(request, tx))
    return _success(result)


@router.post('', response_model=dict, status_code=201)
async def create_user_custom_model(request: Request):
    command = parse_bounded_json(await read_bounded_body(request), UserCustomModelCreateRequest)
    with _owner() as tx:
        result = tx.repository.create(_actor(request, tx), command)
    return _success(result)


@router.put('/{config_id}', response_model=dict)
async def update_user_custom_model(config_id: str, request: Request):
    command = parse_bounded_json(await read_bounded_body(request), UserCustomModelUpdateRequest)
    with _owner() as tx:
        result = tx.repository.update(_actor(request, tx), config_id, command)
    return _success(result)


@router.delete('/{config_id}', response_model=dict)
async def delete_user_custom_model(config_id: str, request: Request):
    command = parse_bounded_json(await read_bounded_body(request), UserCustomModelDeleteRequest)
    with _owner() as tx:
        result = tx.repository.delete(_actor(request, tx), config_id, command.expected_config_version)
    return _success(result)


@router.post('/test', response_model=dict)
async def test_custom_model_connection():
    # Retired unsafe mask/URL lookup. Separate protected probes arrive in Task 6.
    raise ByokError('MODEL_SELECTION_REQUIRED')


def _teacher_selection_gate(request, command, actor):
    """Observe existing private gates and task authorization in a fresh root.

    Selected custom readiness never inherits global platform credentials. No
    runtime, namespace, lease, model call or probe is created by this read.
    """
    if not command.purpose.startswith('teacher_'):
        return
    if actor.role != 'teacher':
        raise ByokError('MODEL_PURPOSE_NOT_ALLOWED')
    from datetime import datetime, timezone
    from uuid import uuid4
    from app.services.teacher_work.bootstrap import (open_teacher_work_request, build_request_dependencies,
        _require_live_admission, _require_proposal_schema)
    from app.services.teacher_work.private_chat import _runtime_pool_current, provider_configured
    from app.services.teacher_work import private_chat
    from app.services.teacher_work.private_proposals import runtime_available
    from app.services.teacher_work.material_sources import source_configured
    operation = 'private_chat_read' if command.purpose == 'teacher_chat' else 'private_proposal_read'
    authorization = request.headers.get('authorization')
    _require_live_admission('read', operation)
    if command.purpose == 'teacher_chat':
        if not _runtime_pool_current() or (private_chat._runtime is not None and
            (private_chat._runtime.closed or private_chat._runtime.loop.is_closed())):
            raise ByokError('MODEL_CAPACITY_EXCEEDED')
    elif (settings.TEACHER_WORK_PRIVATE_MATERIALS_ENABLED is not True or not source_configured() or not runtime_available()):
        raise ByokError('MODEL_PURPOSE_NOT_ALLOWED')
    if command.model_selection.source == 'platform' and not provider_configured():
        raise ByokError('MODEL_PURPOSE_NOT_ALLOWED')
    # private_read gives the existing immutable snapshot/final authority fence.
    # Proposal's additional physical schema is observed in this same root.
    with open_teacher_work_request(authorization, mode='read', operation='private_read') as session:
        binding = build_request_dependencies(session, authorization=authorization, mode='read', operation='private_read',
            clock=lambda: datetime.now(timezone.utc), new_uuid=uuid4)
        try:
            if binding.subject != actor.subject:
                raise ByokError('AUTHENTICATED_ACTOR_REQUIRED')
            if command.purpose == 'teacher_lesson_outline':
                _require_proposal_schema(binding.transport)
            snapshot = binding.repository.get_private_snapshot(binding.subject, command.task_id)
            if snapshot.task.input_revision != command.revision:
                raise ByokError('MODEL_CONFIG_STALE', fields=('revision',))
            binding.finish_private_snapshot(snapshot, mode='read')
        except BaseException:
            binding._cleanup()
            raise


@router.post('/check-selection', response_model=dict)
async def check_user_model_selection(request: Request):
    from app.services.byok.resolver import check_selection
    command = parse_bounded_json(await read_bounded_body(request), UserModelCheckSelectionRequest)
    with _owner(read_only=True) as tx:
        actor = _actor(request, tx)
        # Server derives policy from the exact discriminator; UI cannot supply it.
        policy = 'custom_only' if command.model_selection.source == 'custom' else 'platform_only'
        result = check_selection(actor, command.model_selection, command.purpose, policy, tx.repository)
    _teacher_selection_gate(request, command, actor)
    return _success(result)


from uuid import UUID
from datetime import datetime, timezone
from app.schemas.user_model import SavedProbeRequest, DraftProbeRequest
from app.services.byok.probes import (PROBE_REGISTRY, ProbeOutcome, saved_identity, draft_identity,
    commit_saved_probe, execute_saved_probe, execute_draft_probe)


def _probe_actor(request):
    """Fresh account authentication only: draft/read/cancel never load saved keys."""
    import hashlib
    import json
    authorization=request.headers.get('authorization','')
    if not authorization.lower().startswith('bearer '):
        raise ByokError('AUTHENTICATED_ACTOR_REQUIRED')
    try:claims=decode_access_token(authorization.split(' ',1)[1])
    except Exception:raise ByokError('AUTHENTICATED_ACTOR_REQUIRED') from None
    subject=claims.get('sub') if type(claims) is dict else None
    if type(subject) is not str or not subject:raise ByokError('AUTHENTICATED_ACTOR_REQUIRED')
    with SessionLocal() as session:
        account=session.execute(select(UserAccount).where(UserAccount.username==subject).execution_options(populate_existing=True)).scalar_one_or_none()
        if account is None:raise ByokError('AUTHENTICATED_ACTOR_REQUIRED')
        actor=AuthenticatedModelActor.from_current_account(account)
        created=account.created_at
        if not isinstance(created,datetime):raise ByokError('AUTHENTICATED_ACTOR_REQUIRED')
        # Only non-secret server account/auth epoch facts participate. Provider
        # Key, JWT signature and token bytes are absent from this fingerprint.
        epoch=hashlib.sha256(json.dumps([created.isoformat(),actor.role,claims.get('iat'),claims.get('jti')],
            separators=(',',':'),allow_nan=False).encode()).hexdigest()
    return actor,epoch


def _probe_operation_id(value):
    try:
        parsed=UUID(value)
        if str(parsed)==value:return parsed
    except (ValueError,TypeError,AttributeError):pass
    raise ByokError('INVALID_INPUT',fields=('operation_id',))


@router.post('/{config_id}/test', response_model=dict, status_code=202)
async def test_saved_model(config_id: str, request: Request):
    command=parse_bounded_json(await read_bounded_body(request),SavedProbeRequest)
    actor,epoch=_probe_actor(request)
    fingerprint=saved_identity(actor,epoch,config_id,command)
    async def work():
        reservation=None
        try:
            with _owner() as tx:
                current=_actor(request,tx)
                if current!=actor:raise ByokError('AUTHENTICATED_ACTOR_REQUIRED')
                reservation=tx.repository.reserve_saved_probe(actor,config_id,command.expected_config_version,
                    command.model_id,command.probe_kind,started_at=datetime.now(timezone.utc))
                keyring=tx.keyring
            commit_saved_probe(reservation,tx.receipt)
            result=await execute_saved_probe(reservation,keyring)
            PROBE_REGISTRY.observe_transport(result)
            # No Session/row is held across provider await. Completion reopens
            # exact owner/config and performs current generation CAS.
            try:
                with _owner() as final:
                    if _actor(request,final)!=actor:raise ByokError('MODEL_CONFIG_STALE')
                    mutation=final.repository.complete_saved_probe(reservation,result,reservation.binding.generation)
                return result.model_copy(update={'inventory_revision':mutation.inventory_revision})
            except Exception as error:
                # Native/storage errors are no proof of actual transport close.
                # Preserve the invocation's safe facts through EVERY ordinary
                # final persistence failure; never inspect its raw exception.
                code=error.code if isinstance(error,ByokError) else 'OUTCOME_UNKNOWN'
                return result.model_copy(update={'status':'outcome_unknown' if code=='OUTCOME_UNKNOWN' else 'failed',
                    'code':code})
        finally:
            if reservation is not None:reservation.pending=None
    return _success(PROBE_REGISTRY.start(actor,command.operation_id,fingerprint,work))


@router.post('/test-draft', response_model=dict, status_code=202)
async def test_draft_model(request: Request):
    command=parse_bounded_json(await read_bounded_body(request),DraftProbeRequest)
    actor,epoch=_probe_actor(request)
    fingerprint=draft_identity(actor,epoch,command)
    async def work():
        nonlocal command
        try:return await execute_draft_probe(actor,command)
        finally:command=None
    return _success(PROBE_REGISTRY.start(actor,command.operation_id,fingerprint,work))


@router.get('/probes/{operation_id}', response_model=dict)
async def read_model_probe(operation_id: str, request: Request):
    actor,epoch=_probe_actor(request)
    return _success(PROBE_REGISTRY.read(actor,_probe_operation_id(operation_id),actor_epoch=epoch))


@router.post('/probes/{operation_id}/cancel', response_model=dict)
async def cancel_model_probe(operation_id: str, request: Request):
    actor,epoch=_probe_actor(request)
    return _success(PROBE_REGISTRY.cancel(actor,_probe_operation_id(operation_id),actor_epoch=epoch))
