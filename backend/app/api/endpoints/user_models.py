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
