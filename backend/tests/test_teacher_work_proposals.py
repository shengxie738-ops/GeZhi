"""Strict proposal shaping and independent extension contract, no startup/SQL."""
from datetime import datetime, timedelta, timezone
import importlib
import json
from uuid import UUID
import pytest
from pydantic import ValidationError
from app.schemas.teacher_work import WorkTaskDTO, WorkMessageDTO
from app.services.teacher_work.types import WorkContext, canonical_digest, canonical_json_bytes
from tests.test_teacher_work_private_materials import lesson, slides
NOW=datetime(2026,10,6,tzinfo=timezone.utc)
TASK_ID=UUID(int=2)
SOURCE_ID=UUID(int=4)
def schema():return importlib.import_module('app.schemas.teacher_work_proposals')
def helpers():return importlib.import_module('app.services.teacher_work.proposals')
def task():
    return WorkTaskDTO(task_id=TASK_ID,owner_subject='owner',owner_storage_id=UUID(int=1),title='标题',topic='主题',audience='学生',duration_minutes=45,target_slide_count=8,lesson_draft_id='draft',input_revision=1,working_revision=2,created_at=NOW,updated_at=NOW)
def message(message_id=SOURCE_ID,role='assistant',text='Chosen reply',offset=0):
    return WorkMessageDTO(message_id=message_id,task_id=TASK_ID,owner='owner',role=role,plain_text=text,run_id=UUID(int=7) if role=='assistant' else None,result_type='answer' if role=='assistant' else None,omitted_context=False if role=='assistant' else None,created_at=NOW+timedelta(seconds=offset))
def command():return schema().ProposalCommand(skill_ref='lesson_outline@1',input_revision=1,expected_revision=2,source_message_id=SOURCE_ID)
def frozen(history=None,**kw):
    return helpers().prepare_proposal_context(WorkContext('owner',UUID(int=1),TASK_ID,None,None,1,2),command(),task(),'Requirements',(('resource','a'*64),),history or (message(),),source_digest='b'*64,**kw)
def parse(data=None):return helpers().parse_material_proposal(json.dumps(data or {'lesson':lesson(),'slides':slides()},ensure_ascii=False),frozen=frozen(),created_at=NOW)
@pytest.mark.parametrize('change',[{'unknown':1},{'input_revision':True},{'expected_revision':0},{'skill_ref':'lesson_package@1'},{'source_message_id':'00000000-0000-0000-0000-00000000000A'},{'source_message_id':'urn:uuid:00000000-0000-0000-0000-000000000004'}])
def test_command_exact_strict_canonical(change):
    body={'skill_ref':'lesson_outline@1','input_revision':1,'expected_revision':2,'source_message_id':str(SOURCE_ID),**change}
    with pytest.raises(ValueError):schema().ProposalCommand.model_validate_json(json.dumps(body))
def test_frozen_context_is_immutable_canonical_and_ends_selected_reply():
    item=frozen((message(UUID(int=3),'user','Earlier question',-1),message(),message(UUID(int=5),'user','Later',1)))
    body=json.loads(item.context_json)
    assert body['transcript'][-1]==message().model_dump(mode='json') and len(body['transcript'])==2
    assert body['task_brief']['duration_minutes']==45 and body['task_brief']['target_slide_count']==8
    assert body['source_fingerprints']==[{'resource_id':'resource','sha256':'a'*64}]
    assert item.input_digest==canonical_digest(body) and item.context_json==canonical_json_bytes(body).decode()
    with pytest.raises(ValidationError):item.context_json='modified'
def test_context_whole_message_truncation_and_explicit_omission():
    item=frozen((message(UUID(int=3),'user','x'*23000,-1),message()))
    assert item.omitted_context and json.loads(item.context_json)['omitted_context'] is True
    assert json.loads(item.context_json)['transcript']==[json.loads(frozen().context_json)['transcript'][0]]
    assert len(item.context_json)<=24000 and frozen(history_omitted=True).omitted_context is True
@pytest.mark.parametrize('defect',['oversized_selected','foreign','order','duplicate','missing','unclassified'])
def test_context_refuses_ineligible_and_unbounded_inputs(defect):
    item=message();history=(item,)
    if defect=='oversized_selected':history=(message(text='x'*24000),)
    if defect=='foreign':history=(item.model_copy(update={'owner':'foreign'}),)
    if defect=='order':history=(message(UUID(int=3),'user',offset=1),item)
    if defect=='duplicate':history=(item,item)
    if defect=='missing':history=(message(UUID(int=9)),)
    if defect=='unclassified':history=(item.model_copy(update={'result_type':None,'omitted_context':None}),)
    with pytest.raises(helpers().ProposalPreparationError):frozen(history)
def test_parser_binds_server_metadata_and_exact_wire():
    result=parse()
    assert set(result.model_dump())=={'skill_ref','input_revision','source_message_id','input_digest','source_digest','omitted_context','lesson','slides','created_at'}
    assert result.source_message_id==SOURCE_ID and result.source_digest=='b'*64
    assert result.lesson.citations==() and all(s.source_note=='' and not s.evidence_refs for s in result.slides)
@pytest.mark.parametrize('defect',['evidence','citations','source_note','extra','duration','count','xml','density','content_bytes'])
def test_parser_refuses_invalid_actual_candidate(defect):
    data={'lesson':lesson(),'slides':slides()}
    if defect=='evidence':data['slides'][0]['evidence_refs']=[str(UUID(int=9))]
    if defect=='citations':data['lesson']['citations']=[{'name':'Invented'}]
    if defect=='source_note':data['slides'][0]['source_note']='Made up provenance'
    if defect=='extra':data['source_snapshots']=[]
    if defect=='duration':data['lesson']['duration_minutes']=44;data['lesson']['teaching_flow'][0]['minutes']=44
    if defect=='count':data['slides']=slides(6)
    if defect=='xml':data['lesson']['summary']='bad\x00text'
    if defect=='density':data['slides'][0]['body']=['\n'*80]
    if defect=='content_bytes':data['lesson']['objectives']=['字'*2000]*20;data['lesson']['key_points']=['字'*2000]*20
    with pytest.raises(helpers().ProposalPreparationError) as error:parse(data)
    assert error.value.code=='INVALID_MATERIAL_PROPOSAL_RESPONSE'
@pytest.mark.parametrize('raw',['{"lesson":{},"lesson":{},"slides":[]}','{"lesson":{},"slides":[],"x":NaN}','{"lesson":{},"slides":[],"x":1e999}','```json\n{}\n```','x'*262145],ids=['duplicate','NaN','overflow','fence','oversized'])
def test_parser_refuses_duplicate_nonfinite_salvage_and_full_envelope(raw):
    with pytest.raises(helpers().ProposalPreparationError):helpers().parse_material_proposal(raw,frozen=frozen(),created_at=NOW)
def test_freshness_run_and_capabilities_exactness():
    s=schema()
    with pytest.raises(ValueError):s.ProposalFreshness(adoptable=True,reason='SOURCE_UNAVAILABLE')
    with pytest.raises(ValueError):s.ProposalFreshness(adoptable=False,reason=None)
    assert s.ProposalFreshness(adoptable=False,reason='SOURCE_UNAVAILABLE').reason=='SOURCE_UNAVAILABLE'
    data=dict(run_id=UUID(int=8),task_id=TASK_ID,input_revision=1,source_message_id=SOURCE_ID,input_digest='a'*64,source_digest='b'*64,stage='PENDING',attempt=1,provider_call_count=0,deadline=NOW,cancelled_at=None,error_code=None,omitted_context=False,proposal_available=False,receipt=None)
    assert s.ProposalRun(**data).kind=='outline'
    with pytest.raises(ValueError):s.ProposalRun(**{**data,'proposal_available':True})
    caps=s.ProposalCapabilities(generate=False,read=True,cancel=True,provider_configured=False,external_provider_verified=False,reasons={'generate':'provider_unconfigured'},limits=s.ProposalLimits())
    assert caps.limits.max_context_characters==24000
    with pytest.raises(ValueError):s.ProposalLimits(max_context_characters=10)
    with pytest.raises(ValueError):s.ProposalCapabilities(**{**caps.model_dump(),'reasons':{'provider_configured':'provider_unconfigured'}})
def test_extension_exact_shape_independent_ledger_and_core_unchanged():
    from app.services.teacher_work.schema_v3 import TEACHER_WORK_CONTRACT_HASH as before
    extension=importlib.import_module('app.services.teacher_work.proposal_schema')
    models=importlib.import_module('app.models.teacher_work_proposals')
    from app.services.teacher_work.schema_v3 import TEACHER_WORK_CONTRACT_HASH as after
    table=models.MaterialProposalRecord.__table__
    assert before==after and tuple(c.name for c in table.primary_key)==('run_id','record_type','record_key')
    assert set(table.columns.keys())=={'run_id','record_type','record_key','owner','task_id','payload','created_at','outline_id'}
    assert extension.PROPOSAL_COMPONENT=='teacher_work_material_proposals' and extension.PROPOSAL_SCHEMA_VERSION==1
    assert set(extension.PROPOSAL_SCHEMA_CONTRACT['tables'])=={'teacher_work_material_proposal_records','teacher_work_schema_versions'}
    assert extension.PROPOSAL_CONTRACT_HASH==canonical_digest(extension.PROPOSAL_SCHEMA_CONTRACT) and len(extension.proposal_mysql_tables())==1

@pytest.mark.parametrize('defect',['brief_extra','brief_wrong_type','brief_missing','fingerprint_extra','fingerprint_wrong_type','fingerprint_duplicate'])
def test_frozen_context_decoder_refuses_corrupt_metadata(defect):
    item=frozen();data=json.loads(item.context_json)
    if defect=='brief_extra':data['task_brief']['caller_model']='bad'
    if defect=='brief_wrong_type':data['task_brief']['title']=1
    if defect=='brief_missing':del data['task_brief']['requirements']
    if defect=='fingerprint_extra':data['source_fingerprints'][0]['content']='invented'
    if defect=='fingerprint_wrong_type':data['source_fingerprints'][0]['resource_id']=False
    if defect=='fingerprint_duplicate':data['source_fingerprints'].append(data['source_fingerprints'][0])
    values={**item.model_dump(),'context_json':canonical_json_bytes(data).decode(),'input_digest':canonical_digest(data)}
    with pytest.raises(ValueError):schema().FrozenProposalInput.model_validate(values)


def test_context_revalidates_server_work_context():
    ctx=WorkContext('owner',UUID(int=1),TASK_ID,None,None,1,2)
    object.__setattr__(ctx,'input_revision',True)
    with pytest.raises(helpers().ProposalPreparationError):helpers().prepare_proposal_context(ctx,command(),task(),'Requirements',(('resource','a'*64),),(message(),),source_digest='b'*64)


def test_context_exact_24000_character_boundary():
    base=len(frozen((message(text='x'),)).context_json)-1
    limit=message(text='x'*(24000-base))
    item=frozen((limit,))
    assert len(item.context_json)==24000 and item.omitted_context is False
    with pytest.raises(helpers().ProposalPreparationError) as error:frozen((limit.model_copy(update={'plain_text':limit.plain_text+'x'}),))
    assert error.value.code=='PROPOSAL_CONTEXT_TOO_LARGE'


@pytest.mark.parametrize('defect',['xml','density'])
def test_stored_result_wire_refuses_exporter_unsafe_text(defect):
    values=parse().model_dump()
    if defect=='xml':values['lesson']=values['lesson']|{'summary':'bad\x00text'}
    else:values['slides'][0]['body']=('\n'*80,)
    with pytest.raises(ValueError):schema().MaterialProposal.model_validate(values)


@pytest.mark.parametrize('defect',['foreign','duplicate','receipt','count','extra'])
def test_proposal_run_list_exact_owned_bounded_wire(defect):
    data=dict(run_id=UUID(int=8),task_id=TASK_ID,input_revision=1,source_message_id=SOURCE_ID,input_digest='a'*64,source_digest='b'*64,stage='PENDING',attempt=1,provider_call_count=0,deadline=NOW,cancelled_at=None,error_code=None,omitted_context=False,proposal_available=False,receipt=None)
    if defect=='foreign':data['task_id']=UUID(int=99)
    if defect=='receipt':data['receipt']=schema().ProposalReceipt(replayed=True)
    runs=(schema().ProposalRun(**data),)
    if defect=='duplicate':runs=runs*2
    if defect=='count':runs=tuple(schema().ProposalRun(**{**data,'run_id':UUID(int=100+i)}) for i in range(21))
    values={'task_id':TASK_ID,'runs':runs}
    if defect=='extra':values['next_before']=None
    with pytest.raises(ValueError):schema().ProposalRunList(**values)


def test_proposal_run_list_empty_and_json_roundtrip():
    empty=schema().ProposalRunList(task_id=TASK_ID,runs=())
    assert empty.model_dump(mode='json')=={'task_id':str(TASK_ID),'runs':[]}
    data=dict(run_id=UUID(int=8),task_id=TASK_ID,input_revision=1,source_message_id=SOURCE_ID,input_digest='a'*64,source_digest='b'*64,stage='PENDING',attempt=1,provider_call_count=0,deadline=NOW,cancelled_at=None,error_code=None,omitted_context=False,proposal_available=False,receipt=None)
    item=schema().ProposalRunList(task_id=TASK_ID,runs=(schema().ProposalRun(**data),))
    assert schema().ProposalRunList.model_validate_json(item.model_dump_json())==item


def test_capabilities_external_verification_is_strict_false():
    with pytest.raises(ValueError):schema().ProposalCapabilities(generate=True,read=True,cancel=True,
        provider_configured=True,external_provider_verified=0,reasons={},limits=schema().ProposalLimits())
