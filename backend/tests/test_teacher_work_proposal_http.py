"""Narrow strict request parser and proposal error envelope tests, no DB/config."""
import json
import pytest
from tests.test_teacher_work_proposal_persistence import body

@pytest.mark.parametrize('raw',[b'{"origin_proposal_run_id":null,"origin_proposal_run_id":null}', b'{"a":NaN}',b'{"a":1e999}',b'{"a":{"b":1,"b":2}}'])
def test_entire_material_save_rejects_ambiguous_json(raw):
    from app.api.endpoints.teacher_work_proposals import parse_strict_request
    from app.schemas.teacher_work import PrivateMaterialSaveRequest
    with pytest.raises(ValueError):parse_strict_request(PrivateMaterialSaveRequest,raw)

def test_manual_save_omission_and_null_remain_compatible():
    from app.api.endpoints.teacher_work_proposals import parse_strict_request
    from app.schemas.teacher_work import PrivateMaterialSaveRequest
    for extra in ({},{'origin_proposal_run_id':None}):
        value=parse_strict_request(PrivateMaterialSaveRequest,json.dumps(body(**extra)).encode())
        assert value.origin_proposal_run_id is None

@pytest.mark.parametrize('status,code',[(503,'private credential'),(403,'POLICY_CHANGED'),(409,'PROPOSAL_DEADLINE_EXPIRED'),(422,'INVALID_MATERIAL_PROPOSAL_REQUEST'),(503,'WORK_AI_UNAVAILABLE')])
def test_public_errors_exact_namespace_whitelist(status,code):
    from app.api.endpoints.teacher_work_proposals import error_response
    from app.services.teacher_work.runs import WorkRunError
    response=error_response(WorkRunError(code,status));data=json.loads(response.body)
    allowed=code in ('INVALID_MATERIAL_PROPOSAL_REQUEST','WORK_AI_UNAVAILABLE')
    assert response.status_code==(status if allowed else 503)
    assert data==dict(code=response.status_code,message=code if allowed else 'MATERIAL_PROPOSAL_STATE_UNAVAILABLE',data=None)

def test_unknown_locator_only_actual_canonical_uuid():
    from app.api.endpoints.teacher_work_proposals import error_response
    from app.services.teacher_work.proposal_execution import ProposalExecutionError
    from uuid import UUID
    for locator in (None,'not uuid',UUID(int=8)):
        response=error_response(ProposalExecutionError('COMMIT_OUTCOME_UNKNOWN',run_id=locator))
        assert json.loads(response.body)['data']==({'run_id':str(locator)} if type(locator) is UUID else None)

def test_sibling_router_exact_six_routes_in_custom_factory():
    # Endpoint AST registration remains untouched; sibling has its own six routes.
    from app.api.endpoints.teacher_work import build_teacher_work_router
    router=build_teacher_work_router(request_owner_factory=None,dependencies_factory=None)
    from fastapi import FastAPI
    app=FastAPI();app.include_router(router)
    actual={(path,(method.upper(),)) for path,methods in app.openapi()['paths'].items() if 'material-proposals' in path for method in methods}
    prefix='/teacher/work'
    assert actual=={(prefix+path,(method,)) for method,path in [('GET','/material-proposals/capabilities'),
        ('POST','/tasks/{task_id}/material-proposals'),('GET','/tasks/{task_id}/material-proposals/runs'),
        ('GET','/tasks/{task_id}/material-proposals/runs/{run_id}'),('GET','/tasks/{task_id}/material-proposals/runs/{run_id}/proposal'),
        ('POST','/tasks/{task_id}/material-proposals/runs/{run_id}/cancel')]}


def test_deep_raw_json_is_controlled_request_error():
    from app.api.endpoints.teacher_work_proposals import parse_strict_request
    from app.schemas.teacher_work_proposals import ProposalCancelCommand
    with pytest.raises(ValueError):parse_strict_request(ProposalCancelCommand,b'['*10000+b'0'+b']'*10000)
