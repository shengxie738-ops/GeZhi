"""Exact six-route private proposal sibling, bounded strict JSON namespace."""
import json
from uuid import UUID, uuid4
from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from pydantic import TypeAdapter
from app.schemas.teacher_work import BODY_LIMIT, MessageKey
from app.schemas.teacher_work_proposals import ProposalCommand, ProposalCancelCommand
from app.services.teacher_work.chat import _unique_object, _nonfinite
from app.services.teacher_work.types import canonical_json_bytes
from app.services.teacher_work.proposals import validate_proposal_envelope

_ERRORS = {
    401: {'INVALID_CURRENT_IDENTITY'},
    403: {'CURRENT_TEACHER_REQUIRED', 'CURRENT_AUTHORITY_DENIED'},
    404: {'NOT_FOUND'},
    413: {'REQUEST_BODY_TOO_LARGE'},
    422: {'INVALID_MATERIAL_PROPOSAL_REQUEST', 'INVALID_MATERIAL_PROPOSAL_CANCEL_REQUEST', 'PROPOSAL_CONTEXT_TOO_LARGE'},
    409: {'IDEMPOTENCY_CONFLICT','REVISION_CONFLICT','STALE_INPUT_REVISION','SOURCE_MESSAGE_INELIGIBLE',
          'SOURCE_CHANGED','OWNER_RUN_BUSY','PROPOSAL_RUN_LIMIT','PROPOSAL_NOT_READY'},
    429: {'INSTANCE_BUSY'},
    503: {'PRIVATE_MATERIAL_PROPOSALS_DISABLED','TEACHER_WORK_LIVE_GATES_UNVERIFIED','TEACHER_WORK_SCHEMA_UNAVAILABLE',
          'PROPOSAL_SCHEMA_UNAVAILABLE','PRIVATE_MATERIALS_DISABLED','MATERIAL_SOURCES_UNAVAILABLE','WORK_AI_UNAVAILABLE',
          'PROPOSAL_RUNTIME_UNAVAILABLE','MATERIAL_PROPOSAL_STATE_UNAVAILABLE','COMMIT_OUTCOME_UNKNOWN'},
}


def response(status,message,data=None):
    raw = {'code':status,'message':message,'data':data}
    if len(canonical_json_bytes(raw)) > BODY_LIMIT:
        raw = {'code':503,'message':'MATERIAL_PROPOSAL_STATE_UNAVAILABLE','data':None}
        status = 503
    return JSONResponse(status_code=status,content=raw,headers={'Cache-Control':'no-store'})


def error_response(error):
    status,code = getattr(error,'status_code',None),getattr(error,'code',None)
    if type(status) is not int or type(code) is not str or code not in _ERRORS.get(status,set()):
        status,code = 503,'MATERIAL_PROPOSAL_STATE_UNAVAILABLE'
    run_id = getattr(error,'run_id',None)
    data = {'run_id':str(run_id)} if code == 'COMMIT_OUTCOME_UNKNOWN' and type(run_id) is UUID else None
    return response(status,code,data)


def parse_strict_request(model,raw):
    if type(raw) is not bytes or len(raw) > BODY_LIMIT:
        raise ValueError('bounded raw body required')
    try:
        value = json.loads(raw,object_pairs_hook=_unique_object,parse_constant=_nonfinite)
        # JSON validation retains strict UUID JSON representation behavior.
        return model.model_validate_json(canonical_json_bytes(value))
    except (RecursionError,UnicodeError):
        raise ValueError('invalid raw JSON request') from None


def canonical_uuid(raw):
    value = UUID(raw)
    if str(value) != raw:
        raise ValueError('canonical UUID required')
    return value


def mount_material_proposals_router(router, *, request_owner_factory, dependencies_factory):
    from app.api.endpoints.teacher_work import PrivateWorkBodyRoute, _clock
    sibling = APIRouter(route_class=PrivateWorkBodyRoute)

    @sibling.get('/material-proposals/capabilities')
    def capabilities(authorization: str | None = Header(default=None)):
        try:
            with request_owner_factory(authorization,mode='read',operation='private_read') as session:
                binding = dependencies_factory(session,authorization=authorization,mode='read',operation='private_read',clock=_clock,new_uuid=uuid4)
                value = binding.finish_proposal_capabilities()
                validate_proposal_envelope(value.model_dump(mode='json'))
                return response(200,'ok',value.model_dump(mode='json'))
        except Exception as error:
            return error_response(error)

    async def operation(authorization,task_id,name,*,run_id=None,body=None,key=None):
        from app.services.teacher_work.private_proposals import PrivateProposalTransactions, request_authorization, get_runtime
        from app.services.teacher_work.proposal_persistence import public_run
        token = request_authorization.set(authorization)
        try:
            port = PrivateProposalTransactions(request_owner_factory=request_owner_factory,dependencies_factory=dependencies_factory)
            owner = port.subject()
            if name == 'generate':
                observed = port.inspect(owner,task_id,body,key)
                if observed.admission is not None:
                    value = public_run(observed.admission,replayed=True)
                else:
                    value = await get_runtime(transactions=port).execution.start_proposal(owner,task_id,body,key)
            elif name == 'list':
                value = port.list_runs(owner,task_id).runs
            elif name == 'read':
                value = port.read_proposal(owner,task_id,run_id).read
            elif name == 'get':
                value = public_run(port.get(owner,task_id,run_id))
            else:
                runtime = get_runtime(create=False,transactions=port)
                value = (await runtime.execution.cancel_proposal(owner,task_id,run_id) if runtime else public_run(port.cancel(owner,task_id,run_id)))
            type(value).model_validate(value.model_dump())
            data = value.model_dump(mode='json')
            validate_proposal_envelope(data)
            return response(200,'ok',data)
        except Exception as error:
            return error_response(error)
        finally:
            request_authorization.reset(token)

    @sibling.post('/tasks/{task_id}/material-proposals')
    async def generate(task_id: str, request: Request, authorization: str | None = Header(default=None),
                       idempotency_key: str | None = Header(default=None,alias='Idempotency-Key')):
        try:
            task = canonical_uuid(task_id)
            key = TypeAdapter(MessageKey).validate_python(idempotency_key)
            if not key.strip():
                raise ValueError('nonblank idempotency key required')
            body = parse_strict_request(ProposalCommand,await request.body())
            if request.query_params:
                raise ValueError()
        except (ValueError,TypeError,UnicodeError,RecursionError):
            return response(422,'INVALID_MATERIAL_PROPOSAL_REQUEST')
        return await operation(authorization,task,'generate',body=body,key=key)

    @sibling.get('/tasks/{task_id}/material-proposals/runs')
    async def list_runs(task_id: str, request: Request, authorization: str | None = Header(default=None)):
        try:
            task = canonical_uuid(task_id)
            if request.query_params:
                raise ValueError()
        except ValueError:
            return response(422,'INVALID_MATERIAL_PROPOSAL_REQUEST')
        return await operation(authorization,task,'list')

    @sibling.get('/tasks/{task_id}/material-proposals/runs/{run_id}')
    async def get_run(task_id: str, run_id: str, authorization: str | None = Header(default=None)):
        try:
            task,run = canonical_uuid(task_id),canonical_uuid(run_id)
        except ValueError:
            return response(422,'INVALID_MATERIAL_PROPOSAL_REQUEST')
        return await operation(authorization,task,'get',run_id=run)

    @sibling.get('/tasks/{task_id}/material-proposals/runs/{run_id}/proposal')
    async def read_proposal(task_id: str, run_id: str, authorization: str | None = Header(default=None)):
        try:
            task,run = canonical_uuid(task_id),canonical_uuid(run_id)
        except ValueError:
            return response(422,'INVALID_MATERIAL_PROPOSAL_REQUEST')
        return await operation(authorization,task,'read',run_id=run)

    @sibling.post('/tasks/{task_id}/material-proposals/runs/{run_id}/cancel')
    async def cancel(task_id: str, run_id: str, request: Request, authorization: str | None = Header(default=None)):
        try:
            task,run = canonical_uuid(task_id),canonical_uuid(run_id)
            parse_strict_request(ProposalCancelCommand,await request.body())
            if request.query_params:
                raise ValueError()
        except (ValueError,TypeError,UnicodeError,RecursionError):
            return response(422,'INVALID_MATERIAL_PROPOSAL_CANCEL_REQUEST')
        return await operation(authorization,task,'cancel',run_id=run)
    router.include_router(sibling)
