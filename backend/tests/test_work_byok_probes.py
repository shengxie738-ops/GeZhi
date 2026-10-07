"""Task 6 synthetic operation lifetimes, exact saved/draft identity and CAS.

Actual adapters and repositories run over the accepted socketless HTTP and
SQL-statement simulators. This is not native database/provider acceptance.
"""
import asyncio
import ast
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID
import pytest
ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 7, tzinfo=timezone.utc)


def feature():
    assert (ROOT/'backend/app/services/byok/probes.py').is_file(), 'Task 6 protected probe lifecycle missing'
    return importlib.import_module('app.services.byok.probes')


def run(coro):
    from work_byok_adapter_fakes import run
    return run(coro)


def uid(n=1):
    return UUID(int=n)


def setup_config():
    from work_byok_repository_fakes import fixture
    from app.services.byok.endpoint_policy import normalize_endpoint
    f=fixture(); ep=normalize_endpoint('https://provider.example/v1')
    def create(key):
        with f.owner() as tx:
            result=tx.repository.create(f.actor,f.create({'name':'Synthetic','provider':'Synthetic','adapter_id':'openai_chat_completions_v1',
                'base_url':ep.base_url,'model_ids':['same-id'],'secret_action':'replace','api_key':key,
                'destination_consent':{'accepted':True,'destination_digest':ep.destination_digest}}))
        return result
    return f,create('SYNTHETIC-T6-A'),create('SYNTHETIC-T6-B')


def saved(n=1,kind='text',**extra):
    from app.schemas.user_model import SavedProbeRequest
    return SavedProbeRequest.model_validate({'expected_config_version':1,'model_id':'same-id','probe_kind':kind,'operation_id':str(uid(n))}|extra)


def draft(n=1,kind='text',**extra):
    from app.schemas.user_model import DraftProbeRequest
    from app.services.byok.endpoint_policy import normalize_endpoint
    ep=normalize_endpoint('https://provider.example/v1')
    return DraftProbeRequest.model_validate({'adapter_id':'openai_chat_completions_v1','base_url':ep.base_url,'api_key':'SYNTHETIC-T6-DRAFT',
        'model_id':'same-id','probe_kind':kind,'destination_consent':{'accepted':True,'destination_digest':ep.destination_digest},
        'draft_revision':1,'operation_id':str(uid(n))}|extra)


def identity(m,f,kind='text',revision=1):
    return m.ProbeIdentity(actor_subject=f.actor.subject,actor_epoch='synthetic-epoch',source='draft',draft_revision=revision,
        model_id='same-id',probe_kind=kind,destination_digest='a'*64,adapter_id='openai_chat_completions_v1')


def ok(m,kind='text'):
    return m.ProbeOutcome(status='usable_for_text' if kind=='text' else 'capability_verified',transport_reachable=True,
        checked_at=NOW,duration_ms=2)


def response(content='OK',finish='stop',model='same-id'):
    return {'model':model,'choices':[{'index':0,'message':{'role':'assistant','content':content},'finish_reason':finish}]}


@pytest.mark.parametrize('damage',[{'base_url':'https://provider.example/v1'},{'api_key':'****'},{'mask':'****'},{'model_id':''},{'model_id':None},{'operation_id':'1'},{'draft_revision':1},{'expected_config_version':True}])
def test_saved_config_not_url_mask_lookup(damage):
    feature()
    with pytest.raises(Exception):saved(**damage)


def test_saved_exact_same_url_two_keys_and_postcommit(monkeypatch):
    m=feature();f,a,b=setup_config();adapter=importlib.import_module('app.services.byok.adapter')
    from work_byok_adapter_fakes import FakeHTTP
    from app.core.byok_crypto import decrypt_credential
    seen=[];sessions=[]
    def decrypt(*args,**kwargs):
        assert sessions and all(s.closed and s.committed for s in sessions)
        seen.append(kwargs['config_id']);return decrypt_credential(*args,**kwargs)
    monkeypatch.setattr(adapter,'decrypt_credential',decrypt)
    async def check():
        for config,key in ((a,'SYNTHETIC-T6-A'),(b,'SYNTHETIC-T6-B')):
            with f.owner() as tx:pending=tx.repository.reserve_saved_probe(f.actor,config.config_id,1,'same-id','text',started_at=NOW)
            sessions.append(tx.session)
            reserved=m.commit_saved_probe(pending,tx.receipt)
            fake=FakeHTTP(response());monkeypatch.setattr(adapter,'open_protected_client',fake.opener)
            out=await m.execute_saved_probe(reserved,f.ring,clock=lambda:0.0,wall_clock=lambda:NOW)
            assert out.status=='usable_for_text' and out.transport_reachable and fake.calls==1 and fake.closed
            assert fake.sent['headers']['Authorization']=='Bearer '+key
    run(check());assert seen==[a.config_id,b.config_id]


@pytest.mark.parametrize('kind',['text','stream','json','tools'])
def test_draft_no_saved_lookup_and_exact_prompt_caps(monkeypatch,kind):
    m=feature();f,_,_=setup_config();adapter=importlib.import_module('app.services.byok.adapter')
    from work_byok_adapter_fakes import FakeHTTP
    spy=Mock(side_effect=AssertionError('draft looked up saved key'))
    monkeypatch.setattr(f.m.repo.UserModelRepository,'lock_exact_config',spy)
    if kind=='stream':
        from test_work_byok_adapter import sse,chunk
        payload=sse(chunk('OK'),chunk(finish='stop'));headers={'content-type':'text/event-stream'}
    elif kind=='tools':
        payload=response(None,'tool_calls');payload['choices'][0]['message']['tool_calls']=[{'id':'call-1','type':'function','function':{'name':'byok_probe','arguments':'{"ok":true}'}}];headers=None
    else:payload=response('{"ok":true}' if kind=='json' else 'OK');headers=None
    fake=FakeHTTP(payload,headers=headers);monkeypatch.setattr(adapter,'open_protected_client',fake.opener)
    command=draft(kind=kind)
    out=run(m.execute_draft_probe(f.actor,command,clock=lambda:0.0,wall_clock=lambda:NOW))
    body=json.loads(fake.sent['content']);assert spy.call_count==0 and fake.calls==1 and fake.closed
    assert out.status==('usable_for_text' if kind=='text' else 'capability_verified')
    assert body['max_tokens']==(16 if kind=='text' else 64) and body['stream']==(kind=='stream')
    assert body['messages'][0]['content']==m.PROBE_PROMPTS[kind]
    assert m.PROBE_PROMPTS['text']=='Reply exactly OK.'
    assert 'SYNTHETIC' not in json.dumps(out.model_dump(mode='json')) and not f.configs[next(iter(f.configs))].capability_evidence
    if kind=='tools':
        fn=body['tools'][0]['function'];assert fn['name']=='byok_probe' and fn['strict'] is True
        assert fn['parameters']=={'type':'object','properties':{'ok':{'type':'boolean','const':True}},'required':['ok'],'additionalProperties':False}


@pytest.mark.parametrize('kind,content,finish,status,code',[
    ('text','Other','stop','failed','PROVIDER_INVALID_RESPONSE'),('text','OK','length','failed','PROVIDER_INCOMPLETE'),
    ('json','{"ok":false}','stop','failed','PROVIDER_INVALID_RESPONSE'),('tools','OK','stop','failed','PROVIDER_INVALID_RESPONSE')])
def test_probe_exact_result_and_nonterminal_failure(monkeypatch,kind,content,finish,status,code):
    m=feature();f,_,_=setup_config();adapter=importlib.import_module('app.services.byok.adapter')
    from work_byok_adapter_fakes import FakeHTTP
    fake=FakeHTTP(response(content,finish));monkeypatch.setattr(adapter,'open_protected_client',fake.opener)
    out=run(m.execute_draft_probe(f.actor,draft(kind=kind),clock=lambda:0.0,wall_clock=lambda:NOW))
    assert out.status==status and out.code==code and out.transport_reachable and fake.calls==1


@pytest.mark.parametrize('status,code',[(401,'PROVIDER_AUTH_FAILED'),(429,'PROVIDER_RATE_LIMITED'),(503,'OUTCOME_UNKNOWN')])
def test_http_failure_reachable_never_unsupported(monkeypatch,status,code):
    m=feature();f,_,_=setup_config();adapter=importlib.import_module('app.services.byok.adapter')
    from work_byok_adapter_fakes import FakeHTTP
    fake=FakeHTTP(b'SYNTHETIC-RAW-ERROR',status=status);monkeypatch.setattr(adapter,'open_protected_client',fake.opener)
    out=run(m.execute_draft_probe(f.actor,draft(),clock=lambda:0.0,wall_clock=lambda:NOW))
    assert out.code==code and out.transport_reachable and out.status in {'failed','outcome_unknown'} and fake.calls==1 and fake.iterations==0
    assert 'RAW' not in out.model_dump_json()


@pytest.mark.parametrize('late_status',['usable_for_text','failed'])
def test_probe_generation_cas(late_status):
    m=feature();f,a,_=setup_config()
    with f.owner() as tx:first=tx.repository.reserve_saved_probe(f.actor,a.config_id,1,'same-id','text',started_at=NOW)
    with f.owner() as tx:second=tx.repository.reserve_saved_probe(f.actor,a.config_id,1,'same-id','text',started_at=NOW)
    with f.owner() as tx:result=tx.repository.complete_saved_probe(second,ok(m),second.binding.generation)
    before=f.state()
    late=ok(m) if late_status=='usable_for_text' else m.ProbeOutcome(status='failed',code='PROVIDER_AUTH_FAILED',checked_at=NOW,duration_ms=3)
    with pytest.raises(f.error,match='MODEL_CONFIG_STALE'):
        with f.owner() as tx:tx.repository.complete_saved_probe(first,late,second.binding.generation)
    assert f.state()==before and result.config_version==1 and result.data.capability_evidence[0]['generation']==second.binding.generation


@pytest.mark.parametrize('damage',['version','credential','consent','active','generation','owner'])
def test_completion_cas_all_bindings(damage):
    m=feature();f,a,_=setup_config()
    with f.owner() as tx:pending=tx.repository.reserve_saved_probe(f.actor,a.config_id,1,'same-id','text',started_at=NOW)
    row=f.configs[a.config_id]
    if damage=='version':row.config_version+=1
    elif damage=='credential':row.credential_version+=1
    elif damage=='consent':row.consent_version+=1
    elif damage=='active':row.is_active=False
    elif damage=='owner':row.user_id=f.other.subject
    else:row.probe_generations[next(iter(row.probe_generations))]['generation']+=1
    before=f.state()
    with pytest.raises(f.error):
        with f.owner() as tx:tx.repository.complete_saved_probe(pending,ok(m),pending.binding.generation)
    assert f.state()==before


def test_failed_attempt_preserves_success_inventory_atomic():
    m=feature();f,a,_=setup_config()
    with f.owner() as tx:p=tx.repository.reserve_saved_probe(f.actor,a.config_id,1,'same-id','text',started_at=NOW)
    with f.owner() as tx:first=tx.repository.complete_saved_probe(p,ok(m),p.binding.generation)
    with f.owner() as tx:p=tx.repository.reserve_saved_probe(f.actor,a.config_id,1,'same-id','text',started_at=NOW)
    with f.owner() as tx:result=tx.repository.complete_saved_probe(p,m.ProbeOutcome(status='failed',code='PROVIDER_RATE_LIMITED',checked_at=NOW,duration_ms=1),p.binding.generation)
    assert result.inventory_revision==first.inventory_revision+2 and result.data.capability_evidence==first.data.capability_evidence
    assert result.data.latest_attempts[0]['status']=='failed' and result.data.latest_attempts[0]['code']=='PROVIDER_RATE_LIMITED'


def test_operation_id_dedup_cancel_unknown_retention():
    m=feature();f,_,_=setup_config();now=[0.0];registry=m.ProbeRegistry(clock=lambda:now[0],wall_clock=lambda:NOW)
    async def check():
        calls=[];gate=asyncio.Event()
        async def work():calls.append(1);await gate.wait();return ok(m)
        first=registry.start(f.actor,uid(),identity(m,f),work)
        await asyncio.sleep(0)
        duplicate=registry.start(f.actor,uid(),identity(m,f),lambda:(_ for _ in ()).throw(AssertionError('new key was read')))
        assert duplicate==first and len(calls)==1
        with pytest.raises(f.error,match='PROBE_OPERATION_CONFLICT'):registry.start(f.actor,uid(),identity(m,f,revision=2),work)
        with pytest.raises(f.error) as caught:registry.read(f.other,uid())
        assert caught.value.status_code==404
        assert registry.cancel(f.actor,uid()).status=='cancelled'
        assert registry.cancel(f.actor,uid()).status=='cancelled'
        await registry.wait(f.actor,uid())
        assert registry.read(f.actor,uid()).status=='cancelled' and len(calls)==1
        now[0]=900
        with pytest.raises(f.error) as caught:registry.read(f.actor,uid())
        assert caught.value.status_code==404 and len(calls)==1
        with pytest.raises(f.error):registry.cancel(f.actor,uid(999))
        assert len(calls)==1
    run(check())


def test_probe_rate_capacity_and_cost_caps():
    m=feature();f,_,_=setup_config();now=[0.0];registry=m.ProbeRegistry(clock=lambda:now[0],wall_clock=lambda:NOW)
    async def check():
        gate=asyncio.Event()
        async def blocked():await gate.wait();return ok(m)
        registry.start(f.actor,uid(),identity(m,f),blocked)
        with pytest.raises(f.error,match='MODEL_CAPACITY_EXCEEDED'):registry.start(f.actor,uid(2),identity(m,f),blocked)
        gate.set();await registry.wait(f.actor,uid())
        for n in range(2,7):
            async def complete():return ok(m)
            registry.start(f.actor,uid(n),identity(m,f),complete);await registry.wait(f.actor,uid(n))
        with pytest.raises(f.error,match='PROBE_RATE_LIMITED') as caught:registry.start(f.actor,uid(7),identity(m,f),complete)
        assert caught.value.status_code==429 and caught.value.retry_after_seconds==60
        now[0]=60;registry.start(f.actor,uid(7),identity(m,f),complete);await registry.wait(f.actor,uid(7))
        assert all(len(s.model_dump_json().encode())<=2048 for s in registry.states())
    run(check())
    from app.services.byok.capabilities import purpose_limits
    for kind in ('text','stream','json','tools'):
        cap=purpose_limits('probe_'+kind)
        assert cap.timeout_seconds==15 and cap.connect_seconds==5 and cap.output_tokens==(16 if kind=='text' else 64)
        assert cap.envelope_bytes==32768 and cap.text_bytes==4096


def test_registry_metadata_bounds_active_never_evicted():
    m=feature();f,_,_=setup_config();now=[0.0];registry=m.ProbeRegistry(clock=lambda:now[0],wall_clock=lambda:NOW)
    async def check():
        gate=asyncio.Event()
        async def block():await gate.wait();return ok(m)
        registry.start(f.actor,uid(),identity(m,f),block)
        now[0]=901
        assert registry.read(f.actor,uid()).status=='checking'
        gate.set();await registry.wait(f.actor,uid())
        now[0]=1801
        with pytest.raises(f.error):registry.read(f.actor,uid())
    run(check())
    bad=identity(m,f).model_copy(update={'actor_epoch':'x'*3000})
    async def oversized():
        with pytest.raises(f.error):registry.start(f.actor,uid(2),bad,lambda:None)
    run(oversized())


def test_cancel_does_not_release_actor_until_transport_actual_close(monkeypatch):
    m=feature();f,_,_=setup_config();adapter=importlib.import_module('app.services.byok.adapter')
    from work_byok_adapter_fakes import FakeHTTP
    async def check():
        close_gate,body_gate=asyncio.Event(),asyncio.Event()
        fake=FakeHTTP(response(),body_gate=body_gate,close_gate=close_gate);monkeypatch.setattr(adapter,'open_protected_client',fake.opener)
        reg=m.ProbeRegistry(clock=lambda:0.0,wall_clock=lambda:NOW)
        reg.start(f.actor,uid(),identity(m,f),lambda:m.execute_draft_probe(f.actor,draft(),clock=lambda:0.0,wall_clock=lambda:NOW))
        await fake.body_started.wait();reg.cancel(f.actor,uid());await fake.close_started.wait()
        assert not fake.closed
        with pytest.raises(f.error,match='MODEL_CAPACITY_EXCEEDED'):reg.start(f.actor,uid(2),identity(m,f),lambda:ok(m))
        reg.cancel(f.actor,uid());close_gate.set();await reg.wait(f.actor,uid())
        assert fake.closed and reg.read(f.actor,uid()).status=='cancelled'
    run(check())


def test_routes_exact_methods_no_unsafe_lookup():
    feature();tree=ast.parse((ROOT/'backend/app/api/endpoints/user_models.py').read_text())
    routes={n.name:ast.unparse(n) for n in tree.body if isinstance(n,ast.AsyncFunctionDef)}
    assert "'/test-draft'" in routes['test_draft_model']
    assert "'/{config_id}/test'" in routes['test_saved_model']
    assert "'/probes/{operation_id}'" in routes['read_model_probe']
    assert "'/probes/{operation_id}/cancel'" in routes['cancel_model_probe']
    assert 'reserve_saved_probe' in routes['test_saved_model'] and 'PROBE_REGISTRY.start' in routes['test_saved_model']
    assert '_probe_actor' in routes['test_draft_model'] and '_owner' not in routes['test_draft_model']
    assert 'MODEL_SELECTION_REQUIRED' in routes['test_custom_model_connection']


def test_pending_saved_probe_final_generation_and_consent_rechecked():
    m=feature();f,a,_=setup_config()
    for damage in ('generation','consent'):
        with pytest.raises(f.error,match='MODEL_CONFIG_STALE'):
            with f.owner() as tx:
                p=tx.repository.reserve_saved_probe(f.actor,a.config_id,1,'same-id','text',started_at=NOW)
                row=tx.repository._locked[f.actor.subject,a.config_id]
                if damage=='consent':row.consent_version+=1
                else:row.probe_generations[next(iter(row.probe_generations))]['generation']+=1
        assert tx.receipt is None and p.pending._snapshot is None and p.pending._consumed


def test_uncertain_transport_close_never_usable_or_releases_slot():
    m=feature();f,_,_=setup_config();reg=m.ProbeRegistry(clock=lambda:0.0,wall_clock=lambda:NOW)
    async def check():
        async def uncertain():return ok(m).model_copy(update={'transport_closed':False})
        reg.start(f.actor,uid(),identity(m,f),uncertain);await reg.wait(f.actor,uid())
        assert reg.read(f.actor,uid()).status=='outcome_unknown'
        with pytest.raises(f.error,match='MODEL_CAPACITY_EXCEEDED'):reg.start(f.actor,uid(2),identity(m,f),uncertain)
    run(check())


def test_cancel_before_first_turn_is_terminal_without_dispatch():
    m=feature();f,_,_=setup_config();reg=m.ProbeRegistry(clock=lambda:0.0,wall_clock=lambda:NOW);calls=[]
    async def check():
        async def work():calls.append(1);return ok(m)
        reg.start(f.actor,uid(),identity(m,f),work);reg.cancel(f.actor,uid());await reg.wait(f.actor,uid())
        await asyncio.sleep(0)
        assert calls==[] and reg.read(f.actor,uid()).status=='cancelled'
        reg.start(f.actor,uid(2),identity(m,f),work);await reg.wait(f.actor,uid(2));assert calls==[1]
    run(check())


@pytest.mark.parametrize('scope,count',[('actor',100),('process',4096)])
def test_registry_exact_count_capacity_no_factory_dispatch(scope,count):
    m=feature();f,_,_=setup_config();reg=m.ProbeRegistry(clock=lambda:0.0,wall_clock=lambda:NOW)
    # Accepted-window metadata fixture, not a real provider or a bypass port.
    for n in range(count):
        owner=f.actor.subject if scope=='actor' else 'synthetic-owner-'+str(n)
        state=m.ProbeState(operation_id=uid(n+100),identity=identity(m,f),checked_at=NOW,status='failed',code='PROVIDER_AUTH_FAILED')
        reg._records[(owner,uid(n+100))]=m._Record(state,finished_at=0.0)
    calls=[]
    async def check():
        async def work():calls.append(1);return ok(m)
        with pytest.raises(f.error,match='MODEL_CAPACITY_EXCEEDED'):reg.start(f.actor,uid(),identity(m,f),work)
        assert calls==[]
        reg._records.pop(next(iter(reg._records)))
        reg.start(f.actor,uid(),identity(m,f),work);await reg.wait(f.actor,uid());assert calls==[1]
    run(check())


def test_safe_record_exact_2k_boundary():
    m=feature();f,_,_=setup_config();reg=m.ProbeRegistry(clock=lambda:0.0,wall_clock=lambda:NOW)
    def state(subject,model):
        ident=m.ProbeIdentity(actor_subject=subject,actor_epoch='a'*128,source='draft',draft_revision=1,
            model_id=model,probe_kind='text',destination_digest='a'*64,response_model_aliases=('a'*200,'b'*200,'c'*200))
        return m.ProbeState(operation_id=uid(),identity=ident,checked_at=NOW)
    base=state('a'*255,'a'*200)
    missing=2048-len(base.model_dump_json().encode());assert 0<=missing<=455
    subject='é'*min(missing,255)+'a'*(255-min(missing,255))
    model='é'*max(0,missing-255)+'a'*(200-max(0,missing-255))
    exact=state(subject,model);assert len(exact.model_dump_json().encode())==2048;reg._size(exact)
    too_long=exact.model_copy(update={'duration_ms':10})
    assert len(too_long.model_dump_json().encode())==2049
    with pytest.raises(f.error,match='MODEL_CAPACITY_EXCEEDED'):reg._size(too_long)


def test_epoch_fences_read_cancel_and_reuse():
    m=feature();f,_,_=setup_config();reg=m.ProbeRegistry(clock=lambda:0.0,wall_clock=lambda:NOW)
    async def check():
        async def work():return ok(m)
        reg.start(f.actor,uid(),identity(m,f),work);await reg.wait(f.actor,uid())
        for action in (reg.read,reg.cancel):
            with pytest.raises(f.error) as caught:action(f.actor,uid(),actor_epoch='later-auth-epoch')
            assert caught.value.status_code==404
        with pytest.raises(f.error,match='PROBE_OPERATION_CONFLICT'):
            reg.start(f.actor,uid(),identity(m,f).model_copy(update={'actor_epoch':'later-auth-epoch'}),work)
    run(check())


def route_function(name,namespace):
    tree=ast.parse((ROOT/'backend/app/api/endpoints/user_models.py').read_text())
    fn=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name==name)
    fn.decorator_list=[]
    for arg in fn.args.args:arg.annotation=None
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'shipped-probe-route','exec'),namespace)
    return namespace[name]


class SyntheticRequest:
    headers={}
    def __init__(self,data):self.data=data
    async def stream(self):yield json.dumps(self.data).encode()


def route_namespace(m,f):
    from app.services.byok.http_boundary import read_bounded_body,parse_bounded_json
    from app.schemas.user_model import SavedProbeRequest,DraftProbeRequest
    return {'read_bounded_body':read_bounded_body,'parse_bounded_json':parse_bounded_json,
        'SavedProbeRequest':SavedProbeRequest,'DraftProbeRequest':DraftProbeRequest,
        'PROBE_REGISTRY':m.ProbeRegistry(clock=lambda:0.0,wall_clock=lambda:NOW),
        'ProbeOutcome':m.ProbeOutcome,'ByokError':f.error,'datetime':datetime,'timezone':timezone,
        '_probe_actor':lambda request:(f.actor,'synthetic-epoch'),'_owner':f.owner,'_actor':lambda request,tx:f.actor,
        'saved_identity':m.saved_identity,'draft_identity':m.draft_identity,'commit_saved_probe':m.commit_saved_probe,
        'execute_saved_probe':m.execute_saved_probe,'execute_draft_probe':m.execute_draft_probe,
        '_success':lambda value:value.model_dump(mode='json'),
        '_probe_operation_id':lambda value:UUID(value)}


def test_executed_saved_route_one_commit_call_fresh_completion_duplicate(monkeypatch):
    m=feature();f,a,_=setup_config();adapter=importlib.import_module('app.services.byok.adapter')
    from work_byok_adapter_fakes import FakeHTTP
    fake=FakeHTTP(response());monkeypatch.setattr(adapter,'open_protected_client',fake.opener)
    ns=route_namespace(m,f);route=route_function('test_saved_model',ns)
    data={'expected_config_version':1,'model_id':'same-id','probe_kind':'text','operation_id':str(uid())}
    before=f.rows['user_model_inventories'][f.actor.subject].inventory_revision
    async def check():
        first=await route(a.config_id,SyntheticRequest(data));assert first['status']=='checking'
        out=await ns['PROBE_REGISTRY'].wait(f.actor,uid())
        assert out.status=='usable_for_text' and out.inventory_revision==before+2 and fake.calls==1
        # A replacement/deletion after completion cannot make a duplicate read a
        # new envelope or dispatch with today's Key.
        f.configs[a.config_id].credential_version+=1
        lookup=Mock(side_effect=AssertionError('duplicate opened saved owner'))
        ns['_owner']=lookup
        duplicate=await route(a.config_id,SyntheticRequest(data))
        assert duplicate['status']=='usable_for_text' and fake.calls==1 and lookup.call_count==0
    run(check())
    assert f.configs[a.config_id].capability_evidence[0]['probe_kind']=='text'


def test_executed_draft_duplicate_changed_key_not_used_and_no_owner(monkeypatch):
    m=feature();f,_,_=setup_config();adapter=importlib.import_module('app.services.byok.adapter')
    from work_byok_adapter_fakes import FakeHTTP
    fake=FakeHTTP(response());monkeypatch.setattr(adapter,'open_protected_client',fake.opener)
    ns=route_namespace(m,f);lookup=Mock(side_effect=AssertionError('draft opened saved owner'));ns['_owner']=lookup
    route=route_function('test_draft_model',ns)
    command=draft();data=command.model_dump(mode='json')|{'api_key':'SYNTHETIC-T6-FIRST'}
    async def check():
        await route(SyntheticRequest(data));await ns['PROBE_REGISTRY'].wait(f.actor,uid())
        duplicate=await route(SyntheticRequest(data|{'api_key':'SYNTHETIC-T6-SECOND'}))
        assert duplicate['status']=='usable_for_text' and fake.calls==1
        assert fake.sent['headers']['Authorization']=='Bearer SYNTHETIC-T6-FIRST' and lookup.call_count==0
        with pytest.raises(f.error,match='PROBE_OPERATION_CONFLICT'):
            await route(SyntheticRequest(data|{'draft_revision':2,'api_key':'SYNTHETIC-T6-SECOND'}))
        assert fake.calls==1
    run(check())


def test_executed_saved_stale_completion_is_not_evidence(monkeypatch):
    m=feature();f,a,_=setup_config();adapter=importlib.import_module('app.services.byok.adapter')
    from work_byok_adapter_fakes import FakeHTTP
    async def check():
        body_gate=asyncio.Event();fake=FakeHTTP(response(),body_gate=body_gate);monkeypatch.setattr(adapter,'open_protected_client',fake.opener)
        ns=route_namespace(m,f);route=route_function('test_saved_model',ns)
        data={'expected_config_version':1,'model_id':'same-id','probe_kind':'text','operation_id':str(uid())}
        await route(a.config_id,SyntheticRequest(data));await fake.body_started.wait()
        f.configs[a.config_id].config_version+=1;body_gate.set()
        out=await ns['PROBE_REGISTRY'].wait(f.actor,uid())
        assert out.status=='failed' and out.code=='MODEL_CONFIG_STALE' and not f.configs[a.config_id].capability_evidence
        assert fake.calls==1 and fake.closed
    run(check())


def test_closed_unknown_cannot_certify_saved_success():
    m=feature();f,a,_=setup_config()
    with f.owner() as tx:p=tx.repository.reserve_saved_probe(f.actor,a.config_id,1,'same-id','text',started_at=NOW)
    before=f.state()
    with pytest.raises(f.error,match='OUTCOME_UNKNOWN'):
        with f.owner() as tx:tx.repository.complete_saved_probe(p,ok(m).model_copy(update={'transport_closed':False}),p.binding.generation)
    assert f.state()==before


def test_final_cas_failure_preserves_uncertain_transport_slot(monkeypatch):
    m=feature();f,a,_=setup_config();ns=route_namespace(m,f)
    async def uncertain(*args,**kwargs):
        f.configs[a.config_id].config_version+=1
        return m.ProbeOutcome(status='outcome_unknown',code='OUTCOME_UNKNOWN',checked_at=NOW,duration_ms=1,transport_closed=False)
    ns['execute_saved_probe']=uncertain;route=route_function('test_saved_model',ns)
    data={'expected_config_version':1,'model_id':'same-id','probe_kind':'text','operation_id':str(uid())}
    async def check():
        await route(a.config_id,SyntheticRequest(data));await ns['PROBE_REGISTRY'].wait(f.actor,uid())
        assert ns['PROBE_REGISTRY'].read(f.actor,uid()).status=='outcome_unknown'
        with pytest.raises(f.error,match='MODEL_CAPACITY_EXCEEDED'):await route(a.config_id,SyntheticRequest(data|{'operation_id':str(uid(2))}))
    run(check())


def test_actor_role_change_cannot_expand_active_or_rate_limit():
    m=feature();f,_,_=setup_config();reg=m.ProbeRegistry(clock=lambda:0.0,wall_clock=lambda:NOW)
    async def check():
        gate=asyncio.Event()
        async def blocked():await gate.wait();return ok(m)
        reg.start(f.actor,uid(),identity(m,f),blocked)
        f.change_role('teacher')
        from app.services.byok.types import AuthenticatedModelActor
        changed=AuthenticatedModelActor.from_current_account(f.rows['user_accounts'][f.actor.subject])
        with pytest.raises(f.error,match='MODEL_CAPACITY_EXCEEDED'):reg.start(changed,uid(2),identity(m,f).model_copy(update={'actor_role':changed.role}),blocked)
        gate.set();await reg.wait(f.actor,uid())
        async def complete():return ok(m)
        for n in range(2,7):
            reg.start(changed,uid(n),identity(m,f).model_copy(update={'actor_role':changed.role}),complete);await reg.wait(changed,uid(n))
        with pytest.raises(f.error,match='PROBE_RATE_LIMITED'):reg.start(f.actor,uid(7),identity(m,f),complete)
    run(check())


@pytest.mark.parametrize('kind,size,expected',[('text',4096,'PROVIDER_INVALID_RESPONSE'),('text',4097,'MODEL_BUDGET_EXCEEDED')])
def test_actual_probe_content_cost_boundary(monkeypatch,kind,size,expected):
    m=feature();f,_,_=setup_config();adapter=importlib.import_module('app.services.byok.adapter')
    from work_byok_adapter_fakes import FakeHTTP
    fake=FakeHTTP(response('X'*size));monkeypatch.setattr(adapter,'open_protected_client',fake.opener)
    out=run(m.execute_draft_probe(f.actor,draft(kind=kind),clock=lambda:0.0,wall_clock=lambda:NOW))
    assert out.code==expected and fake.calls==1 and fake.closed


@pytest.mark.parametrize('extra,success',[(0,True),(1,False)])
def test_actual_probe_envelope_32k_boundary(monkeypatch,extra,success):
    m=feature();f,_,_=setup_config();adapter=importlib.import_module('app.services.byok.adapter')
    from work_byok_adapter_fakes import FakeHTTP
    payload=response()|{'padding':''};raw=json.dumps(payload).encode();payload['padding']='X'*(32768+extra-len(raw))
    raw=json.dumps(payload).encode();assert len(raw)==32768+extra
    fake=FakeHTTP(raw);monkeypatch.setattr(adapter,'open_protected_client',fake.opener)
    out=run(m.execute_draft_probe(f.actor,draft(),clock=lambda:0.0,wall_clock=lambda:NOW))
    assert (out.status=='usable_for_text')==success and fake.calls==1 and fake.closed
    if not success:assert out.code=='MODEL_BUDGET_EXCEEDED'


@pytest.mark.parametrize('advance',[14.999,15.0,15.001])
def test_actual_probe_monotonic_15s_boundary(monkeypatch,advance):
    m=feature();f,_,_=setup_config();adapter=importlib.import_module('app.services.byok.adapter')
    from work_byok_adapter_fakes import FakeHTTP
    now=[0.0];fake=FakeHTTP(response(),now=now,advance=advance);monkeypatch.setattr(adapter,'open_protected_client',fake.opener)
    out=run(m.execute_draft_probe(f.actor,draft(),clock=lambda:now[0],wall_clock=lambda:NOW))
    assert fake.calls==1 and fake.closed
    assert (out.status=='usable_for_text')==(advance<15)
    if advance>=15:assert out.code=='PROVIDER_TIMEOUT'


def test_stream_requires_actual_terminal_and_network_unknown_no_retry(monkeypatch):
    m=feature();f,_,_=setup_config();adapter=importlib.import_module('app.services.byok.adapter')
    from work_byok_adapter_fakes import FakeHTTP
    from test_work_byok_adapter import sse,chunk
    fake=FakeHTTP(sse(chunk('OK'),done=False),headers={'content-type':'text/event-stream'})
    monkeypatch.setattr(adapter,'open_protected_client',fake.opener)
    out=run(m.execute_draft_probe(f.actor,draft(kind='stream'),clock=lambda:0.0,wall_clock=lambda:NOW))
    assert out.status=='failed' and out.code=='PROVIDER_INCOMPLETE' and out.transport_reachable and fake.calls==1 and fake.closed
    from contextlib import asynccontextmanager
    calls=[]
    @asynccontextmanager
    async def unavailable(*args,**kwargs):
        calls.append(1);kwargs['egress_lease']._release(None)
        raise RuntimeError('SYNTHETIC PRIVATE TRANSPORT BODY')
        yield
    monkeypatch.setattr(adapter,'open_protected_client',unavailable)
    out=run(m.execute_draft_probe(f.actor,draft(),clock=lambda:0.0,wall_clock=lambda:NOW))
    assert out.status=='outcome_unknown' and out.code=='OUTCOME_UNKNOWN' and not out.transport_reachable and calls==[1]
    assert 'PRIVATE' not in out.model_dump_json()



@pytest.mark.parametrize('model,aliases,expected',[('alias',{'same-id':['alias']},'usable_for_text'),('other',{'same-id':['alias']},'failed')])
def test_draft_exact_declared_response_alias(monkeypatch,model,aliases,expected):
    m=feature();f,_,_=setup_config();adapter=importlib.import_module('app.services.byok.adapter')
    from work_byok_adapter_fakes import FakeHTTP
    fake=FakeHTTP(response(model=model));monkeypatch.setattr(adapter,'open_protected_client',fake.opener)
    out=run(m.execute_draft_probe(f.actor,draft(response_model_aliases=aliases),clock=lambda:0.0,wall_clock=lambda:NOW))
    assert out.status==expected
    if expected=='failed':assert out.code=='MODEL_ID_MISMATCH'


def test_draft_secret_scope_clears_and_cannot_serialize():
    m=feature();f,_,_=setup_config();import pickle
    async def check():
        async with m.adapter.open_draft_probe_invocation(f.actor,draft()) as inv:
            secret=inv._secret;assert secret.header_value()=='SYNTHETIC-T6-DRAFT'
            with pytest.raises(TypeError):pickle.dumps(inv)
            with pytest.raises(TypeError):inv.model_dump()
        assert secret.closed and inv._secret is None and inv._closed
        with pytest.raises(TypeError):secret.header_value()
    run(check())


def test_pending_saved_probe_without_receipt_zero_dispatch(monkeypatch):
    m=feature();f,a,_=setup_config();adapter=importlib.import_module('app.services.byok.adapter')
    spy=Mock(side_effect=AssertionError('uncommitted dispatch'));monkeypatch.setattr(adapter,'open_protected_client',spy)
    with f.owner() as tx:p=tx.repository.reserve_saved_probe(f.actor,a.config_id,1,'same-id','text',started_at=NOW)
    with pytest.raises(f.error,match='OUTCOME_UNKNOWN'):m.commit_saved_probe(p,None)
    out=run(m.execute_saved_probe(p,f.ring,clock=lambda:0.0,wall_clock=lambda:NOW))
    assert out.status=='outcome_unknown' and not out.transport_reachable and spy.call_count==0


def test_admission_reserves_terminal_metadata_headroom():
    m=feature();f,_,_=setup_config();reg=m.ProbeRegistry(clock=lambda:0.0,wall_clock=lambda:NOW)
    from app.services.byok.types import AuthenticatedModelActor
    def ident(subject,model):
        return m.ProbeIdentity(actor_subject=subject,actor_epoch='a'*128,source='draft',draft_revision=1,model_id=model,
            probe_kind='text',destination_digest='a'*64,response_model_aliases=('a'*200,'b'*200,'c'*200))
    base=ident('a'*255,'a'*200)
    missing=2048-len(m.ProbeState(operation_id=uid(),identity=base,checked_at=NOW).model_dump_json().encode())
    subject='é'*min(missing,255)+'a'*(255-min(missing,255))
    model='é'*max(0,missing-255)+'a'*(200-max(0,missing-255));large=ident(subject,model)
    actor=AuthenticatedModelActor.from_current_account(f.m.account(username=subject,role='student'))
    calls=[]
    async def check():
        async def fail():calls.append(1);raise f.error('PROVIDER_INVALID_RESPONSE')
        with pytest.raises(f.error,match='MODEL_CAPACITY_EXCEEDED'):reg.start(actor,uid(),large,fail)
        assert calls==[] and reg.states()==()
    run(check())


@pytest.mark.parametrize('source',['saved','draft'])
def test_r1_retained_id_role_change_never_redispatches_or_replaces_key(monkeypatch,source):
    m=feature();f,a,_=setup_config();adapter=importlib.import_module('app.services.byok.adapter')
    from work_byok_adapter_fakes import FakeHTTP
    from app.services.byok.types import AuthenticatedModelActor
    fake=FakeHTTP(response());monkeypatch.setattr(adapter,'open_protected_client',fake.opener)
    ns=route_namespace(m,f);current=[f.actor]
    ns['_probe_actor']=lambda request:(current[0],'synthetic-epoch')
    ns['_actor']=lambda request,tx:current[0]
    route=route_function('test_saved_model' if source=='saved' else 'test_draft_model',ns)
    data=({'expected_config_version':1,'model_id':'same-id','probe_kind':'text','operation_id':str(uid())} if source=='saved'
        else draft().model_dump(mode='json')|{'api_key':'SYNTHETIC-T6-FIRST'})
    async def invoke():
        return await route(a.config_id,SyntheticRequest(data)) if source=='saved' else await route(SyntheticRequest(data))
    async def check():
        await invoke();await ns['PROBE_REGISTRY'].wait(f.actor,uid())
        assert fake.calls==1
        f.change_role('teacher');current[0]=AuthenticatedModelActor.from_current_account(f.rows['user_accounts'][f.actor.subject])
        if source=='draft':data['api_key']='SYNTHETIC-T6-SECOND'
        owner=Mock(wraps=f.owner);ns['_owner']=owner
        code=None
        try:await invoke()
        except f.error as error:code=error.code
        else:await ns['PROBE_REGISTRY'].wait(current[0],uid())
        assert code=='PROBE_OPERATION_CONFLICT'
        assert fake.calls==1 and owner.call_count==0
        # A role change changes identity/visibility, never the retained ID namespace.
        with pytest.raises(f.error) as caught:ns['PROBE_REGISTRY'].read(current[0],uid(),actor_epoch='synthetic-epoch')
        assert caught.value.status_code==404
    run(check())


@pytest.mark.parametrize('closed',[False,True])
@pytest.mark.parametrize('when',['begin','complete','commit','close'])
def test_r1_generic_completion_failure_preserves_actual_close_and_safe_state(monkeypatch,closed,when):
    m=feature();f,a,_=setup_config();ns=route_namespace(m,f);opened=[]
    class FinalOwner:
        def __enter__(self):
            if when=='begin':raise RuntimeError('SYNTHETIC PRIVATE STORAGE INPUT')
            def complete(*args):
                if when=='complete':raise RuntimeError('SYNTHETIC PRIVATE STORAGE INPUT')
                return SimpleNamespace(inventory_revision=99)
            self.repository=SimpleNamespace(complete_saved_probe=complete);return self
        def __exit__(self,*args):
            if when in {'commit','close'}:raise RuntimeError('SYNTHETIC PRIVATE STORAGE INPUT')
    def owner():
        opened.append(1)
        return f.owner() if len(opened)==1 else FinalOwner()
    ns['_owner']=owner
    async def outcome(*args,**kwargs):
        return m.ProbeOutcome(status='outcome_unknown' if not closed else 'usable_for_text',code='OUTCOME_UNKNOWN' if not closed else None,
            transport_reachable=True,checked_at=NOW,duration_ms=2,transport_closed=closed)
    ns['execute_saved_probe']=outcome;route=route_function('test_saved_model',ns)
    data={'expected_config_version':1,'model_id':'same-id','probe_kind':'text','operation_id':str(uid())}
    async def check():
        await route(a.config_id,SyntheticRequest(data));out=await ns['PROBE_REGISTRY'].wait(f.actor,uid())
        assert out.status=='outcome_unknown' and out.code=='OUTCOME_UNKNOWN' and out.transport_reachable
        assert 'PRIVATE' not in out.model_dump_json() and not f.configs[a.config_id].capability_evidence
        async def next_call():return ok(m)
        if not closed:
            with pytest.raises(f.error,match='MODEL_CAPACITY_EXCEEDED'):
                ns['PROBE_REGISTRY'].start(f.actor,uid(2),identity(m,f),next_call)
        else:
            ns['PROBE_REGISTRY'].start(f.actor,uid(2),identity(m,f),next_call)
            assert (await ns['PROBE_REGISTRY'].wait(f.actor,uid(2))).status=='usable_for_text'
    run(check())


@pytest.mark.parametrize('closed',[False,True])
def test_r1_finalization_cancellation_keeps_actual_close_truth(closed):
    m=feature();f,a,_=setup_config();ns=route_namespace(m,f);opened=[]
    class FinalOwner:
        def __enter__(self):
            self.repository=SimpleNamespace(complete_saved_probe=lambda *args:(_ for _ in ()).throw(asyncio.CancelledError()))
            return self
        def __exit__(self,*args):return False
    def owner():
        opened.append(1);return f.owner() if len(opened)==1 else FinalOwner()
    ns['_owner']=owner
    async def outcome(*args,**kwargs):
        return m.ProbeOutcome(status='outcome_unknown' if not closed else 'usable_for_text',code='OUTCOME_UNKNOWN' if not closed else None,
            transport_reachable=True,checked_at=NOW,duration_ms=2,transport_closed=closed)
    ns['execute_saved_probe']=outcome;route=route_function('test_saved_model',ns)
    data={'expected_config_version':1,'model_id':'same-id','probe_kind':'text','operation_id':str(uid())}
    async def check():
        await route(a.config_id,SyntheticRequest(data));out=await ns['PROBE_REGISTRY'].wait(f.actor,uid())
        assert out.status==('cancelled' if closed else 'outcome_unknown') and out.transport_reachable
        assert out.code==('CANCELLED' if closed else 'OUTCOME_UNKNOWN') and not f.configs[a.config_id].capability_evidence
        async def next_call():return ok(m)
        if not closed:
            with pytest.raises(f.error,match='MODEL_CAPACITY_EXCEEDED'):ns['PROBE_REGISTRY'].start(f.actor,uid(2),identity(m,f),next_call)
        else:
            ns['PROBE_REGISTRY'].start(f.actor,uid(2),identity(m,f),next_call);await ns['PROBE_REGISTRY'].wait(f.actor,uid(2))
    run(check())


@pytest.mark.parametrize('closed',[False,True])
@pytest.mark.parametrize('when',['begin','complete'])
def test_r1_actual_adapter_close_truth_survives_generic_final_storage(monkeypatch,closed,when):
    m=feature();f,a,_=setup_config();adapter=importlib.import_module('app.services.byok.adapter')
    from work_byok_adapter_fakes import FakeHTTP
    class UncertainClose(FakeHTTP):
        async def aclose(self):
            self.close_started.set();raise RuntimeError('SYNTHETIC PRIVATE CLOSE FAILURE')
    fake=FakeHTTP(response()) if closed else UncertainClose(response())
    monkeypatch.setattr(adapter,'open_protected_client',fake.opener)
    ns=route_namespace(m,f);opened=[]
    def owner():
        opened.append(1)
        if len(opened)==2 and when=='begin':raise RuntimeError('SYNTHETIC PRIVATE OWNER FAILURE')
        return f.owner()
    ns['_owner']=owner
    if when=='complete':
        monkeypatch.setattr(f.m.repo.UserModelRepository,'complete_saved_probe',Mock(side_effect=RuntimeError('SYNTHETIC PRIVATE QUERY FAILURE')))
    route=route_function('test_saved_model',ns)
    data={'expected_config_version':1,'model_id':'same-id','probe_kind':'text','operation_id':str(uid())}
    async def check():
        try:
            await route(a.config_id,SyntheticRequest(data));out=await ns['PROBE_REGISTRY'].wait(f.actor,uid())
            assert out.status=='outcome_unknown' and out.code=='OUTCOME_UNKNOWN' and out.transport_reachable
            assert fake.calls==1 and fake.closed==closed and fake.egress._released==closed
            assert 'PRIVATE' not in out.model_dump_json() and not f.configs[a.config_id].capability_evidence
            if not closed:
                with pytest.raises(f.error,match='MODEL_CAPACITY_EXCEEDED'):
                    await route(a.config_id,SyntheticRequest(data|{'operation_id':str(uid(2))}))
            else:assert not ns['PROBE_REGISTRY']._tasks
        finally:
            # Only fixture cleanup confirms a later actual close, after assertions.
            fake.closed=True
            if fake.egress is not None and not fake.egress._released:fake.egress._release(fake)
            tasks=list(ns['PROBE_REGISTRY']._tasks.values())
            for task in tasks:
                if not task.done():task.cancel()
            for task in tasks:
                if not task.done():
                    try:await task
                    except asyncio.CancelledError:pass
    run(check())
