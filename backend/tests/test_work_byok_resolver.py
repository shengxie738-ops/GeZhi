"""Task 5 exact metadata routing; simulated SQL only, never native DB proof."""
import ast
import importlib
import json
from pathlib import Path
from unittest.mock import Mock
import pytest
ROOT = Path(__file__).resolve().parents[2]


def feature():
    assert (ROOT/'backend/app/services/byok/resolver.py').is_file(), 'Task 5 resolver missing'
    return importlib.import_module('app.services.byok.resolver')


def setup_config():
    from work_byok_repository_fakes import fixture
    from app.services.byok.endpoint_policy import normalize_endpoint
    f=fixture()
    command={'name':'Synthetic','provider':'Synthetic','adapter_id':'openai_chat_completions_v1','base_url':'https://provider.example/v1',
        'model_ids':['same-id'],'response_model_aliases':{},'secret_action':'replace','api_key':'SYNTHETIC-T5-NOT-A-CREDENTIAL',
        'destination_consent':{'accepted':True,'destination_digest':normalize_endpoint('https://provider.example/v1').destination_digest}}
    with f.owner() as tx:
        a=tx.repository.create(f.actor,f.create(command))
        b=tx.repository.create(f.actor,f.create(command))
    return f,a,b


def test_same_id_exact_owner_reference(monkeypatch):
    m=feature(); f,a,b=setup_config()
    from app.schemas.model_selection import PlatformSelection
    spy=Mock(return_value={'model_id':'same-id','capabilities':('text','tools','json','stream')})
    decrypt=Mock(side_effect=AssertionError('metadata decrypted'))
    monkeypatch.setattr(importlib.import_module('app.core.byok_crypto'),'decrypt_credential',decrypt)
    with f.reader() as tx:
        tx.repository.platform_metadata=spy
        one=m.resolve_selection(f.actor,f.selection(a.config_id,1),'student_chat','custom_only',tx.repository)
        two=m.resolve_selection(f.actor,f.selection(b.config_id,1),'student_chat','custom_only',tx.repository)
        platform=m.resolve_selection(f.actor,PlatformSelection(source='platform',model_id='same-id'),'student_chat','platform_only',tx.repository)
        assert one.selection.config_id==a.config_id and two.selection.config_id==b.config_id
        assert platform.selection.source=='platform' and spy.call_count==1
        with pytest.raises(f.error,match='CUSTOM_MODEL_NOT_FOUND'):
            m.resolve_selection(f.other,f.selection(a.config_id,1),'teacher_chat','custom_only',tx.repository)
    assert decrypt.call_count==0
    exact=[s for s in f.statements if getattr(s,'is_select',False) and 'user_custom_ai_models' in str(s)]
    assert any('user_custom_ai_models.id =' in str(s) and 'user_custom_ai_models.user_id =' in str(s) for s in exact)


@pytest.mark.parametrize('change,code',[
    ('missing','CUSTOM_MODEL_NOT_FOUND'),('inactive','MODEL_DISABLED'),('stale','MODEL_CONFIG_STALE'),
    ('badKey','CREDENTIAL_UNAVAILABLE'),('membership','MODEL_NOT_IN_CONFIG'),('consent','DESTINATION_CONSENT_REQUIRED'),
    ('adapter','UNSUPPORTED_ADAPTER'),('legacy','CREDENTIAL_REENTRY_REQUIRED'),('capability','CAPABILITY_UNVERIFIED')])
def test_custom_failure_never_platform(change,code):
    m=feature(); f,a,_=setup_config(); row=f.configs[a.config_id]; version=1; purpose='student_chat'
    if change=='missing':del f.configs[a.config_id]
    elif change=='inactive':row.is_active=False
    elif change=='stale':version=2
    elif change=='badKey':row.credential_state='decrypt_failed'
    elif change=='membership':row.model_ids=['another']
    elif change=='consent':row.destination_digest='0'*64
    elif change=='adapter':row.adapter_id='native-other'
    elif change=='legacy':row.credential_state='legacy_reentry_required'
    elif change=='capability':purpose='student_tutor'
    platform_spy=Mock(side_effect=AssertionError('platform fallback'))
    with f.reader() as tx:
        tx.repository.platform_metadata=platform_spy
        with pytest.raises(f.error,match=code):m.resolve_selection(f.actor,f.selection(a.config_id,version),purpose,'custom_only',tx.repository)
    assert platform_spy.call_count==0


@pytest.mark.parametrize('purpose,expected',[('student_chat',{'text'}),('student_tutor',{'tools'}),('teacher_chat',{'json'}),
    ('teacher_lesson_outline',{'json'}),('probe_text',{'text'}),('probe_stream',{'stream'}),('probe_tools',{'tools'}),('probe_json',{'json'})])
def test_capability_required_by_purpose(purpose,expected):
    feature(); m=importlib.import_module('app.services.byok.capabilities')
    assert m.required_capabilities(purpose)==frozenset(expected)


@pytest.mark.parametrize('kind',['text','stream','tools','json'])
def test_probe_does_not_require_existing_evidence(kind):
    m=feature(); f,a,_=setup_config()
    with f.reader() as tx:
        result=m.resolve_selection(f.actor,f.selection(a.config_id,1),'probe_'+kind,'custom_only',tx.repository)
    assert result.ready and result.provenance.capability_evidence_ids==()


@pytest.mark.parametrize('damage',['none','text_only','declared','policy','adapter_version','config_version','other_model'])
def test_advanced_capability_requires_current_exact_evidence(damage):
    m=feature(); f,a,_=setup_config(); f.seed_evidence(a.config_id)
    ev=f.configs[a.config_id].capability_evidence[0]
    if damage=='none':f.configs[a.config_id].capability_evidence=[]
    elif damage=='declared':ev['state']='declared'
    elif damage!='text_only':ev['probe_kind']='tools'; ev[{'policy':'policy_version','adapter_version':'adapter_version','config_version':'config_version','other_model':'model_id'}[damage]]={'policy':'old','adapter_version':'2','config_version':2,'other_model':'other'}[damage]
    with f.reader() as tx:
        with pytest.raises(f.error,match='CAPABILITY_UNVERIFIED'):m.resolve_selection(f.actor,f.selection(a.config_id,1),'student_tutor','custom_only',tx.repository)


def test_current_evidence_and_readiness_observation():
    m=feature(); f,a,_=setup_config(); f.seed_evidence(a.config_id)
    f.configs[a.config_id].capability_evidence[0]['probe_kind']='tools'
    with f.reader() as tx:
        result=m.resolve_selection(f.actor,f.selection(a.config_id,1),'student_tutor','custom_only',tx.repository)
        assert result.ready and result.provenance.capability_evidence_ids==('synthetic-evidence',)
        observation=m.check_selection(f.actor,f.selection(a.config_id,1),'student_tutor','custom_only',tx.repository)
        f.configs[a.config_id].capability_evidence=[]
    with f.reader() as tx:
        observation=m.check_selection(f.actor,f.selection(a.config_id,1),'student_tutor','custom_only',tx.repository)
    assert not observation.ready and observation.missing_capabilities==('tools',)


@pytest.mark.parametrize('data',[{'api_key':'SYNTHETIC'},{'base_url':'https://other.example'},{'revision':True},{'task_id':'not-a-uuid'},{'purpose':'other'}])
def test_read_only_check_selection_strict_request(data):
    feature(); from app.schemas.user_model import UserModelCheckSelectionRequest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):UserModelCheckSelectionRequest.model_validate({'model_selection':{'source':'platform','model_id':'same-id'},'purpose':'student_chat'}|data)


def test_check_selection_route_is_read_only_and_server_policy():
    feature(); text=(ROOT/'backend/app/api/endpoints/user_models.py').read_text()
    assert "@router.post('/check-selection'" in text
    tree=ast.parse(text); fn=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='check_user_model_selection')
    body=ast.unparse(fn)
    assert '_owner(read_only=True)' in body and 'check_selection' in body and '_teacher_selection_gate' in body
    assert 'reserve_custom_call' not in body and 'open_invocation' not in body


def test_platform_port_exact_id_and_no_alias_resolution():
    feature(); tree=ast.parse((ROOT/'backend/app/services/model_registry.py').read_text())
    functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='get_platform_model_metadata_exact']
    assert len(functions)==1
    ns={'_MODEL_CONFIGS':{'exact':type('C',(),{'category':'text','model_id':'exact'})()},'ByokError':importlib.import_module('app.services.byok.errors').ByokError}
    exec(compile(ast.Module(body=functions,type_ignores=[]),'platform-exact','exec'),ns)
    assert ns[functions[0].name]('exact')['model_id']=='exact'
    for value in (' alias ','alias',None):
        with pytest.raises(ns['ByokError']):ns[functions[0].name](value)


@pytest.mark.parametrize('purpose',['student_chat','student_tutor'])
def test_explicit_unsupported_capability_is_fail_closed(purpose):
    m=feature();f,a,_=setup_config();kind='text' if purpose=='student_chat' else 'tools'
    row=f.configs[a.config_id]
    row.probe_generations={'synthetic':{'generation':1,'latest_attempt':{
        'config_version':1,'adapter_id':'openai_chat_completions_v1','adapter_version':'1','policy_version':'work-byok@1',
        'model_id':'same-id','probe_kind':kind,'generation':1,'checked_at':'2026-10-07T00:00:00Z','duration_ms':1,
        'status':'failed','code':'CAPABILITY_UNSUPPORTED'}}}
    with f.reader() as tx:
        checked=m.check_selection(f.actor,f.selection(a.config_id,1),purpose,'custom_only',tx.repository)
        assert checked.capability_states[kind]=='unsupported' and checked.missing_capabilities==(kind,)
        with pytest.raises(f.error,match='CAPABILITY_UNSUPPORTED'):m.resolve_selection(f.actor,f.selection(a.config_id,1),purpose,'custom_only',tx.repository)


def test_check_selection_actual_route_closes_read_root(monkeypatch):
    m=feature(); f,a,_=setup_config()
    from work_byok_adapter_fakes import run
    tree=ast.parse((ROOT/'backend/app/api/endpoints/user_models.py').read_text())
    fn=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='check_user_model_selection')
    fn.decorator_list=[];fn.args.args[0].annotation=None
    from app.services.byok.http_boundary import read_bounded_body,parse_bounded_json
    from app.schemas.user_model import UserModelCheckSelectionRequest
    opened=[];gates=[]
    def owner(*,read_only):
        assert read_only;tx=f.reader();opened.append(tx);return tx
    def gate(request,command,actor):
        assert opened[0].session.closed and not opened[0].session.active
        gates.append(command.purpose)
    ns={'_owner':owner,'_actor':lambda request,tx:f.actor,'_teacher_selection_gate':gate,
        'read_bounded_body':read_bounded_body,'parse_bounded_json':parse_bounded_json,'UserModelCheckSelectionRequest':UserModelCheckSelectionRequest,
        '_success':lambda result:result.model_dump(mode='json')}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'route','exec'),ns)
    class Request:
        headers={}
        async def stream(self):yield json.dumps({'model_selection':f.selection(a.config_id,1).model_dump(),'purpose':'student_chat'}).encode()
    result=run(ns[fn.name](Request()))
    assert result['ready'] and result['selection']['config_id']==a.config_id and gates==['student_chat']
    assert not opened[0].session.committed and opened[0].session.locks==[]


@pytest.mark.parametrize('purpose,damage',[('teacher_chat','disabled'),('teacher_chat','runtime'),('teacher_chat','revision'),('teacher_chat','wrong_owner'),
    ('teacher_chat','schema'),('teacher_lesson_outline','proposal_disabled'),('teacher_lesson_outline','material_disabled'),
    ('teacher_lesson_outline','proposal_schema'),('teacher_lesson_outline','source'),('teacher_lesson_outline','proposal_runtime'),
    ('teacher_chat','none'),('teacher_lesson_outline','none')])
def test_teacher_check_selection_preserves_fresh_private_global_gates(purpose,damage):
    feature()
    from contextlib import contextmanager
    import builtins
    from types import SimpleNamespace
    tree=ast.parse((ROOT/'backend/app/api/endpoints/user_models.py').read_text())
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_teacher_selection_gate')
    error=importlib.import_module('app.services.byok.errors').ByokError
    events=[];settings=SimpleNamespace(TEACHER_WORK_PRIVATE_MATERIALS_ENABLED=damage!='material_disabled')
    def live(mode,operation):
        events.append(('live',mode,operation))
        if damage=='disabled' or damage=='proposal_disabled':raise error('MODEL_PURPOSE_NOT_ALLOWED')
    def proposal_schema(transport):
        events.append('proposal_schema')
        if damage=='proposal_schema':raise error('BYOK_STORAGE_UNAVAILABLE')
    @contextmanager
    def owner(authorization,*,mode,operation):
        assert authorization=='Bearer synthetic' and mode=='read' and operation=='private_read'
        events.append('fresh_open')
        try:yield object()
        finally:events.append('fresh_closed')
    task=SimpleNamespace(input_revision=2 if damage=='revision' else 1)
    snapshot=SimpleNamespace(task=task)
    def dependencies(session,**kwargs):
        events.append('current_account_private_schema')
        if damage=='schema':raise error('BYOK_STORAGE_UNAVAILABLE')
        return SimpleNamespace(subject='other' if damage=='wrong_owner' else 'synthetic-owner',transport=object(),
            repository=SimpleNamespace(get_private_snapshot=lambda subject,task_id:events.append('task_authorization') or snapshot),
            finish_private_snapshot=lambda value,mode:events.append('final_authority_read'),_cleanup=lambda:events.append('cleanup'))
    bootstrap=SimpleNamespace(open_teacher_work_request=owner,build_request_dependencies=dependencies,_require_live_admission=live,_require_proposal_schema=proposal_schema)
    chat=SimpleNamespace(_runtime_pool_current=lambda:damage!='runtime',provider_configured=lambda:False,_runtime=None)
    modules={'app.services.teacher_work.bootstrap':bootstrap,'app.services.teacher_work.private_chat':chat,
        'app.services.teacher_work':SimpleNamespace(private_chat=chat),
        'app.services.teacher_work.private_proposals':SimpleNamespace(runtime_available=lambda:damage!='proposal_runtime'),
        'app.services.teacher_work.material_sources':SimpleNamespace(source_configured=lambda:damage!='source')}
    def imports(name,globals=None,locals=None,fromlist=(),level=0):
        return modules[name] if name in modules else builtins.__import__(name,globals,locals,fromlist,level)
    ns={'ByokError':error,'settings':settings,'__builtins__':dict(vars(builtins),__import__=imports)}
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'teacher-check-gate','exec'),ns)
    request=SimpleNamespace(headers={'authorization':'Bearer synthetic'})
    command=SimpleNamespace(purpose=purpose,revision=1,task_id=object(),model_selection=SimpleNamespace(source='custom'))
    actor=SimpleNamespace(role='teacher',subject='synthetic-owner')
    if damage=='none':
        ns[fn.name](request,command,actor)
        assert 'final_authority_read' in events and events[-1]=='fresh_closed'
    else:
        with pytest.raises(error):ns[fn.name](request,command,actor)
        if 'fresh_open' in events:assert events[-1]=='fresh_closed'
    # custom success never needs provider_configured; these doubles return false.
    assert not any(x=='provider_call' for x in events)


def test_read_exact_metadata_does_not_create_inventory_or_lock():
    m=feature();f,a,_=setup_config();del f.rows['user_model_inventories'][f.actor.subject]
    before=f.state()
    with f.reader() as tx:
        with pytest.raises(f.error,match='CREDENTIAL_REENTRY_REQUIRED'):m.resolve_selection(f.actor,f.selection(a.config_id,1),'student_chat','custom_only',tx.repository)
    assert f.state()==before and tx.session.locks==[] and not tx.session.committed


def test_provenance_retains_all_current_optional_capability_proofs():
    m=feature();f,a,_=setup_config();f.seed_evidence(a.config_id)
    stream=dict(f.configs[a.config_id].capability_evidence[0]);stream['probe_kind']='stream';stream['evidence_id']='stream-proof'
    f.configs[a.config_id].capability_evidence.append(stream)
    with f.reader() as tx:resolved=m.resolve_selection(f.actor,f.selection(a.config_id,1),'student_chat','custom_only',tx.repository)
    assert resolved.provenance.capability_evidence_ids==('stream-proof','synthetic-evidence')


def r1_unsupported(row, kind='text'):
    row.probe_generations={'synthetic':{'generation':1,'latest_attempt':{
        'config_version':row.config_version,'adapter_id':'openai_chat_completions_v1','adapter_version':'1','policy_version':'work-byok@1',
        'model_id':'same-id','probe_kind':kind,'generation':1,'checked_at':'2026-10-07T00:00:00Z','duration_ms':1,
        'status':'failed','code':'CAPABILITY_UNSUPPORTED'}}}


@pytest.mark.parametrize('when',['before_reserve','before_commit'])
def test_r1_unsupported_text_blocks_reservation_and_final_commit(when):
    m=feature();f,a,_=setup_config();selection=f.selection(a.config_id,1);provenance=f.provenance(selection)
    if when=='before_reserve':r1_unsupported(f.configs[a.config_id])
    pending=None
    with pytest.raises(f.error,match='CAPABILITY_UNSUPPORTED'):
        with f.owner() as tx:
            pending=tx.repository.reserve_custom_call(f.actor,selection,'student_chat',f.caps,provenance)
            if when=='before_commit':r1_unsupported(tx.repository._locked[f.actor.subject,a.config_id])
    assert tx.receipt is None and tx.session.closed and not tx.session.committed
    if pending is not None:
        assert pending._consumed and pending._snapshot is None
        with pytest.raises(f.error):f.m.reservations.commit_custom_reservation(pending,tx.receipt)


@pytest.mark.parametrize('change',['remove','replace'])
def test_r1_advanced_proof_rechecked_at_final_commit(change):
    m=feature();f,a,_=setup_config();f.seed_evidence(a.config_id)
    f.configs[a.config_id].capability_evidence[0]['probe_kind']='tools'
    selection=f.selection(a.config_id,1)
    with f.reader() as tx:resolved=m.resolve_selection(f.actor,selection,'student_tutor','custom_only',tx.repository)
    with pytest.raises(f.error,match='CAPABILITY_UNVERIFIED'):
        with f.owner() as tx:
            pending=tx.repository.reserve_custom_call(f.actor,selection,'student_tutor',resolved.limits,resolved.provenance)
            row=tx.repository._locked[f.actor.subject,a.config_id]
            if change=='remove':row.capability_evidence=[]
            else:row.capability_evidence[0]['evidence_id']='different-evidence'
    assert tx.receipt is None and pending._consumed and pending._snapshot is None


@pytest.mark.parametrize('kind',['text','tools'])
def test_r1_latest_failed_attempt_retains_successful_admission(kind):
    m=feature();f,a,_=setup_config();f.seed_evidence(a.config_id)
    f.configs[a.config_id].capability_evidence[0]['probe_kind']=kind
    r1_unsupported(f.configs[a.config_id],kind)
    purpose='student_chat' if kind=='text' else 'student_tutor';selection=f.selection(a.config_id,1)
    with f.reader() as tx:resolved=m.resolve_selection(f.actor,selection,purpose,'custom_only',tx.repository)
    with f.owner() as tx:pending=tx.repository.reserve_custom_call(f.actor,selection,purpose,resolved.limits,resolved.provenance)
    committed=f.m.reservations.commit_custom_reservation(pending,tx.receipt)
    assert committed.purpose==purpose and not committed._consumed


def test_r1_unsupported_capability_can_be_explicitly_retested():
    m=feature();f,a,_=setup_config();r1_unsupported(f.configs[a.config_id]);selection=f.selection(a.config_id,1)
    with f.reader() as tx:resolved=m.resolve_selection(f.actor,selection,'probe_text','custom_only',tx.repository)
    with f.owner() as tx:pending=tx.repository.reserve_custom_call(f.actor,selection,'probe_text',resolved.limits,resolved.provenance)
    assert f.m.reservations.commit_custom_reservation(pending,tx.receipt).purpose=='probe_text'


@pytest.mark.parametrize('kind',['text','stream'])
@pytest.mark.parametrize('when',['before_reserve','before_commit'])
def test_r1_admitted_optional_evidence_ids_must_still_match_current_proof(kind,when):
    m=feature();f,a,_=setup_config();f.seed_evidence(a.config_id)
    f.configs[a.config_id].capability_evidence[0]['probe_kind']=kind
    selection=f.selection(a.config_id,1)
    with f.reader() as tx:resolved=m.resolve_selection(f.actor,selection,'student_chat','custom_only',tx.repository)
    if when=='before_reserve':f.configs[a.config_id].capability_evidence[0]['evidence_id']='new-generation-proof'
    pending=None
    with pytest.raises(f.error,match='CAPABILITY_UNVERIFIED'):
        with f.owner() as tx:
            pending=tx.repository.reserve_custom_call(f.actor,selection,'student_chat',resolved.limits,resolved.provenance)
            if when=='before_commit':tx.repository._locked[f.actor.subject,a.config_id].capability_evidence[0]['evidence_id']='new-generation-proof'
    assert tx.receipt is None and not tx.session.committed and tx.session.closed
    if pending is not None:assert pending._snapshot is None and pending._consumed
