"""Detached strict proposal candidates and manual compatibility boundaries."""
import json
from uuid import UUID
import pytest
from app.schemas.teacher_work import PrivateMaterialSaveRequest
from app.services.teacher_work.types import canonical_digest
from tests.test_teacher_work_private_materials import lesson, slides


def body(**extra):
    return dict(expected_revision=1,input_revision=1,expected_outline_revision=0,lesson=lesson(),slides=slides(),**extra)


def test_manual_origin_is_optional_canonical_and_historical_digest_unchanged():
    from app.repositories.teacher_work_materials import material_request_digest
    omitted=PrivateMaterialSaveRequest.model_validate_json(json.dumps(body()))
    null=PrivateMaterialSaveRequest.model_validate_json(json.dumps(body(origin_proposal_run_id=None)))
    old=canonical_digest(body())
    assert material_request_digest(omitted)==material_request_digest(null)==old
    origin=PrivateMaterialSaveRequest.model_validate_json(json.dumps(body(origin_proposal_run_id=str(UUID(int=1)))))
    assert material_request_digest(origin)!=old
    for value in ('00000000000000000000000000000001','00000000-0000-0000-0000-00000000000A',1):
        with pytest.raises(ValueError):PrivateMaterialSaveRequest.model_validate_json(json.dumps(body(origin_proposal_run_id=value)))


def test_proposal_helpers_exist_without_sql_or_settings_imports():
    from app.services.teacher_work import proposal_persistence as module
    assert all(hasattr(module,name) for name in ('ProposalState','ProposalOutcome','ProposalObservation','ProposalAdmission',
        'ProposalReservation','PreparedProposal','ProposalReadOutcome','ProposalListOutcome','ProposalInputRecord','ProposalLineage'))


def state():
    from app.services.teacher_work.proposal_persistence import ProposalInputRecord,ProposalState
    from app.services.teacher_work.run_persistence import StoredRunState
    from app.schemas.teacher_work import RunDTO
    from tests.test_teacher_work_proposals import task,command,frozen,NOW
    from app.services.teacher_work.proposal_persistence import task_context
    from datetime import timedelta
    t=task();record=ProposalInputRecord(task_context(t),command(),frozen())
    run=RunDTO(run_id=UUID(int=8),owner=t.owner_subject,task_id=t.task_id,kind='outline',skill_ref='lesson_outline@1',
        input_revision=1,idempotency_key='key',request_digest=canonical_digest(command().model_dump(mode='json')),
        stage='PENDING',attempt=1,provider_call_count=0,deadline=NOW+timedelta(seconds=90))
    return ProposalState(StoredRunState(run,0,None),record)


@pytest.mark.parametrize('change',[dict(stage='OUTLINE_RUNNING'),dict(stage='COMPLETE'),dict(stage='FAILED'),
    dict(stage='CANCELLED'),dict(kind='chat',skill_ref=None),dict(attempt=2),dict(provider_call_count=2),dict(outline_revision=1),
    dict(result_version_id=UUID(int=9)),dict(request_digest='a'*64),dict(error_code='WORK_AI_TIMEOUT'),dict(input_revision=2)])
def test_proposal_state_rejects_incoherent_budget_stage_bindings(change):
    from app.services.teacher_work.proposal_persistence import ProposalState
    from app.services.teacher_work.run_persistence import StoredRunState
    s=state()
    with pytest.raises(Exception):ProposalState(StoredRunState(s.run.model_copy(update=change),0,None),s.input_record)


def test_exact_input_record_envelope_detects_original_namespace_and_request_mutation():
    from app.services.teacher_work.proposal_persistence import ProposalInputRecord,task_context
    from tests.test_teacher_work_proposals import task,command,frozen
    record=ProposalInputRecord(task_context(task()),command(),frozen())
    assert ProposalInputRecord.decode(record.payload())==record
    for key in ('context','command','frozen'):
        data=record.payload();data[key]['unknown']=1
        with pytest.raises(Exception):ProposalInputRecord.decode(data)
    data=record.payload();data['command']['expected_revision']=1
    with pytest.raises(Exception):ProposalInputRecord.decode(data)
    object.__setattr__(record.original_ctx,'owner_storage_id',UUID(int=99))
    with pytest.raises(Exception):record.__post_init__()


def test_prepared_proposal_result_is_detached_exact_and_mutation_detected():
    from app.services.teacher_work.proposal_persistence import PreparedProposal
    from app.services.teacher_work.run_persistence import ProviderCallToken
    from tests.test_teacher_work_proposals import parse
    s=state();token=ProviderCallToken(s.run.run_id,1,1,2,UUID(int=10))
    p=PreparedProposal(s.input_record.original_ctx,token,s.frozen,parse())
    p.__post_init__()
    object.__setattr__(p.proposal,'input_digest','a'*64)
    with pytest.raises(Exception):p.__post_init__()


def test_real_manual_preparation_counts_reserved_key_timestamp_and_preserves_opaque_extras():
    from copy import deepcopy
    from datetime import datetime,timezone
    from app.repositories.teacher_work_materials import prepare_manual_save,material_request_digest
    from app.services.teacher_work.types import canonical_json_bytes
    from tests.test_teacher_work_proposals import task
    from app.repositories.teacher_work import WorkRepositoryError
    t=task();request=PrivateMaterialSaveRequest.model_validate_json(json.dumps({**body(),'expected_revision':2}))
    payload=dict(content={**lesson(),'opaque':'kept'},teacher_work=dict(requirements='Requirements',private_material_receipts=[]),
        resource_ids=['resource'],updated_at='old',opaque='')
    original=deepcopy(payload);key='😀'*128
    def prepare(data):
        return prepare_manual_save(data,t,request,key,records=[],digest=material_request_digest(request),
            outline_id=UUID(int=9),now=datetime(9999,12,31,23,59,59,999999,tzinfo=timezone.utc),fingerprints=(('resource','a'*64),))
    prepared=prepare(payload)
    assert payload==original and prepared[0]['content']['opaque']=='kept' and prepared[2].skill_versions==()
    assert prepared[0]['updated_at']=='9999-12-31T23:59:59.999999+00:00'
    assert len(key)==128 and len(key.encode())==512
    size=len(canonical_json_bytes(prepared[0]));payload['opaque']='x'*(65535-size)
    assert len(canonical_json_bytes(prepare(payload)[0]))==65535
    payload['opaque']+='x'
    with pytest.raises(WorkRepositoryError) as error:prepare(payload)
    assert error.value.code=='PRIVATE_DRAFT_TOO_LARGE'


def test_projection_never_bypasses_existing_sixty_four_receipt_limit():
    from copy import deepcopy
    from datetime import datetime,timezone
    from app.repositories.teacher_work_materials import prepare_manual_save,material_request_digest
    from app.repositories.teacher_work import WorkRepositoryError
    from tests.test_teacher_work_proposals import task
    request=PrivateMaterialSaveRequest.model_validate_json(json.dumps(body()))
    payload=dict(content=lesson(),teacher_work=dict(requirements='Requirements'),resource_ids=['resource'])
    records=[dict(operation='save',key=str(i),request_digest='a'*64,outline_id=str(UUID(int=i+1)),approval_id=None,
        input_revision=1,working_revision=1) for i in range(64)]
    with pytest.raises(WorkRepositoryError) as error:prepare_manual_save(payload,task(),request,'key',records=records,
        digest=material_request_digest(request),outline_id=UUID(int=99),now=datetime.now(timezone.utc),fingerprints=(('resource','a'*64),))
    assert error.value.code=='MATERIAL_RECEIPT_LIMIT' and len(records)==64


def test_default_off_proposal_gate_preserves_private_task_and_chat_rejections():
    import ast
    from pathlib import Path
    from types import SimpleNamespace
    from app.services.teacher_work.authorization import WorkAuthorizationError
    root=Path(__file__).resolve().parents[1]
    config=ast.parse((root/'app/core/config.py').read_text())
    field=next(node for node in ast.walk(config) if isinstance(node,ast.AnnAssign) and
        isinstance(node.target,ast.Name) and node.target.id=='TEACHER_WORK_PRIVATE_MATERIAL_PROPOSALS_ENABLED')
    assert ast.literal_eval(field.value) is False
    tree=ast.parse((root/'app/services/teacher_work/bootstrap.py').read_text())
    guard=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='_require_live_admission')
    guard.body=[ast.Pass() if isinstance(node,ast.ImportFrom) else node for node in guard.body]
    settings=SimpleNamespace(TEACHER_WORK_PRIVATE_TASKS_ENABLED=True,TEACHER_WORK_PRIVATE_CHAT_ENABLED=False,
        TEACHER_WORK_PRIVATE_MATERIALS_ENABLED=True,TEACHER_WORK_PRIVATE_EXPORTS_ENABLED=False,
        TEACHER_WORK_PRIVATE_MATERIAL_PROPOSALS_ENABLED=False)
    namespace=dict(settings=settings,WorkAuthorizationError=WorkAuthorizationError)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[guard],type_ignores=[])),'proposal-gate','exec'),namespace)
    call=namespace['_require_live_admission']
    with pytest.raises(WorkAuthorizationError) as error:call('read','private_proposal_read')
    assert error.value.code=='PRIVATE_MATERIAL_PROPOSALS_DISABLED'
    settings.TEACHER_WORK_PRIVATE_TASKS_ENABLED=False
    with pytest.raises(WorkAuthorizationError) as error:call('read','private_proposal_read')
    assert error.value.code=='TEACHER_WORK_LIVE_GATES_UNVERIFIED'
    settings.TEACHER_WORK_PRIVATE_TASKS_ENABLED=True
    with pytest.raises(WorkAuthorizationError) as error:call('write','private_chat_write')
    assert error.value.code=='PRIVATE_CHAT_DISABLED'
    call('write','private_material_save')
