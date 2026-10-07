"""Task 5 bounded protocol fixtures: no real provider or credentials."""
import importlib
import json
import pickle
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[2]


def feature():
    assert (ROOT/'backend/app/services/byok/adapter.py').is_file(), 'Task 5 adapter missing'
    return importlib.import_module('app.services.byok.adapter')


def run(coro):
    from work_byok_adapter_fakes import run
    return run(coro)


def response(content='Hello',finish='stop',model='same-id',**extra):
    return {'model':model,'choices':[{'index':0,'message':{'role':'assistant','content':content},'finish_reason':finish}]}|extra


def execute(monkeypatch,payload,**kwargs):
    m=feature(); from work_byok_adapter_fakes import invoke
    return run(invoke(m,monkeypatch,payload,**kwargs))


@pytest.mark.parametrize('payload,code',[
    (b'<html>login</html>','PROVIDER_INVALID_RESPONSE'),(b'{"error":{"message":"SYNTHETIC"}}','PROVIDER_INVALID_RESPONSE'),
    ({'model':'same-id','choices':[]},'PROVIDER_INVALID_RESPONSE'),(response(content=None),'PROVIDER_EMPTY'),
    (response(content=''),'PROVIDER_EMPTY'),(response(finish='strange'),'PROVIDER_INVALID_RESPONSE'),
    (response(model='other'),'MODEL_ID_MISMATCH'),(b'{"model":"same-id","model":"same-id","choices":[]}','PROVIDER_INVALID_RESPONSE'),
    (b'{"model":"same-id","choices":[],"usage":NaN}','PROVIDER_INVALID_RESPONSE'),(b'\xff','PROVIDER_INVALID_RESPONSE')])
def test_response_validation(monkeypatch,payload,code):
    m=feature()
    with pytest.raises(m.ByokError,match=code):execute(monkeypatch,payload)


@pytest.mark.parametrize('finish',['length','content_filter'])
def test_nonstop_is_incomplete_not_complete(monkeypatch,finish):
    result,_=execute(monkeypatch,response(finish=finish))
    assert result.model_state=='incomplete' and result.content=='Hello'


def test_complete_usage_unknown_and_request_owned_bytes(monkeypatch):
    result,f=execute(monkeypatch,response())
    assert result.model_state=='complete' and result.usage is None and result.content=='Hello'
    assert f.calls==1 and f.closed and f.sent['headers']['Accept-Encoding']=='identity'
    assert type(f.sent['content']) is bytes
    data=json.loads(f.sent['content']); assert data['max_tokens']==4096 and 'temperature' not in data and 'api_key' not in data


@pytest.mark.parametrize('model,aliases,ok',[('same-id',(),True),('fixed-alias',('fixed-alias',),True),('other',('fixed-alias',),False)])
def test_exact_response_model_aliases(monkeypatch,model,aliases,ok):
    m=feature()
    if ok:assert execute(monkeypatch,response(model=model),aliases=aliases)[0].model_state=='complete'
    else:
        with pytest.raises(m.ByokError,match='MODEL_ID_MISMATCH'):execute(monkeypatch,response(model=model),aliases=aliases)


@pytest.mark.parametrize('text,ok',[('{"ok":true}',True),('{"ok":false}',False),('{}',False),('  ',False),('{"ok":true,"ok":true}',False),('{"ok":NaN}',False)])
def test_json_probe_exact_object(monkeypatch,text,ok):
    m=feature()
    if ok:assert execute(monkeypatch,response(content=text),purpose='probe_json')[0].model_state=='complete'
    else:
        with pytest.raises(m.ByokError):execute(monkeypatch,response(content=text),purpose='probe_json')


def tool(name='byok_probe',arguments='{"ok":true}',id='call-1'):
    return {'id':id,'type':'function','function':{'name':name,'arguments':arguments}}


def test_tool_handshake_is_not_final_text(monkeypatch):
    payload=response(content=None,finish='tool_calls'); payload['choices'][0]['message']['tool_calls']=[tool()]
    result,_=execute(monkeypatch,payload,purpose='probe_tools')
    assert result.model_state=='incomplete' and result.tool_calls[0].name=='byok_probe' and result.content is None
    payload['choices'][0]['message']['tool_calls']=[tool(name='execute_python_code')]
    result,_=execute(monkeypatch,payload,purpose='student_tutor')
    assert result.model_state=='incomplete' and result.tool_calls


@pytest.mark.parametrize('calls',[[tool(name='unknown')],[tool(arguments='{"ok":true,"ok":true}')],[tool(arguments='{"ok":NaN}')],
    [tool(arguments='x'*4097)],[tool(id='call-'+str(i)) for i in range(4)],[]])
def test_invalid_tools_rejected_before_dispatch(monkeypatch,calls):
    m=feature(); payload=response(content=None,finish='tool_calls'); payload['choices'][0]['message']['tool_calls']=calls
    with pytest.raises(m.ByokError):execute(monkeypatch,payload,purpose='student_tutor')


def chunk(text=None,finish=None,tools=None,model='same-id'):
    delta={} if text is None else {'content':text}
    if tools is not None:delta['tool_calls']=tools
    return {'model':model,'choices':[{'index':0,'delta':delta,'finish_reason':finish}]}


def sse(*chunks,done=True,newline='\n',space=' '):
    data=''.join('data:'+space+json.dumps(c,ensure_ascii=False)+newline+newline for c in chunks)
    if done:data+='data:'+space+'[DONE]'+newline+newline
    return data.encode('utf-8')


def stream_execute(monkeypatch,payload,**kwargs):
    kwargs.setdefault('purpose','probe_stream')
    return execute(monkeypatch,payload,stream=True,headers={'content-type':'text/event-stream'},**kwargs)


@pytest.mark.parametrize('newline,space',[('\n',' '),('\r\n',''),('\r\n',' ')])
def test_sse_fragments_terminal_and_bounds(monkeypatch,newline,space):
    raw=sse(chunk('你'),chunk('好'),chunk(finish='stop'),newline=newline,space=space)
    events,f=stream_execute(monkeypatch,[raw[i:i+1] for i in range(len(raw))])
    assert ''.join(e.content or '' for e in events if e.kind=='delta')=='你好'
    assert events[-1].kind=='terminal' and events[-1].result.model_state=='complete' and f.closed


@pytest.mark.parametrize('payload',[sse(chunk('partial'),done=False),sse(chunk('partial'),done=True),b'data: '+b'x'*32769+b'\n\n',
    sse(chunk('ok'),chunk(finish='stop'))[:-3],b'data: \xff\n\n',sse(chunk('ok',model='other'),chunk(finish='stop'))])
def test_sse_missing_terminal_truncated_or_invalid_rejected(monkeypatch,payload):
    m=feature()
    with pytest.raises(m.ByokError):stream_execute(monkeypatch,payload)


def test_secret_invocation_refuses_default_repr_trace_serialization(monkeypatch):
    m=feature(); from work_byok_adapter_fakes import reservation
    reserved,f=reservation(m)
    async def check():
        async with m.open_invocation(reserved,f.ring) as inv:
            assert 'SYNTHETIC' not in repr(inv)
            for op in (lambda:str(inv),lambda:pickle.dumps(inv),lambda:json.dumps(inv),lambda:inv.model_dump(),lambda:inv.trace_attributes()):
                with pytest.raises(TypeError):op()
            return inv
    inv=run(check())
    with pytest.raises(m.ByokError):run(m.ChatCompletionsAdapter().complete(inv,m.ModelRequest(messages=({'role':'user','content':'Synthetic'},),purpose='student_chat',limits=f.caps),deadline=30))
    with pytest.raises(m.ByokError):run(check())


def test_pending_cannot_decrypt(monkeypatch):
    m=feature(); from work_byok_adapter_fakes import reservation
    pending,f=reservation(m,committed=False)
    spy=[]; monkeypatch.setattr(m,'decrypt_credential',lambda *a,**k:spy.append('decrypt'))
    async def attempt():
        async with m.open_invocation(pending,f.ring):pass
    with pytest.raises(m.ByokError):run(attempt())
    assert spy==[]


@pytest.mark.parametrize('payload',[json.dumps(response(content='\ud800')).encode(),response(finish=[]),response(content='{\"ok\":1}')])
def test_invalid_unicode_finish_and_nonboolean_probe_fail_safe(monkeypatch,payload):
    m=feature(); purpose='probe_json' if type(payload) is dict and payload['choices'][0]['message']['content']=='{"ok":1}' else 'student_chat'
    with pytest.raises(m.ByokError,match='PROVIDER_INVALID_RESPONSE'):execute(monkeypatch,payload,purpose=purpose)


def test_probe_tools_requires_actual_boolean(monkeypatch):
    m=feature(); payload=response(content=None,finish='tool_calls');payload['choices'][0]['message']['tool_calls']=[tool(arguments='{"ok":1}')]
    with pytest.raises(m.ByokError,match='PROVIDER_INVALID_RESPONSE'):execute(monkeypatch,payload,purpose='probe_tools')


def test_read_error_is_safe_one_call_with_terminal_close(monkeypatch):
    m=feature(); seen=[]
    with pytest.raises(m.ByokError,match='OUTCOME_UNKNOWN') as error:
        execute(monkeypatch,[RuntimeError('SYNTHETIC upstream body credential')],seen=seen)
    assert seen[0].calls==1 and seen[0].closed
    assert 'SYNTHETIC' not in repr(error.value)


def test_stream_tool_fragments_remain_intermediate_until_validated(monkeypatch):
    first={'index':0,'id':'call-1','type':'function','function':{'name':'byok_','arguments':'{"ok":'}}
    second={'index':0,'function':{'name':'probe','arguments':'true}'}}
    events,f=stream_execute(monkeypatch,sse(chunk(tools=[first]),chunk(tools=[second]),chunk(finish='tool_calls')),purpose='probe_tools')
    assert [e.kind for e in events]==['tool_delta','tool_delta','terminal']
    assert events[-1].result.model_state=='incomplete' and events[-1].result.tool_calls[0].arguments=={'ok':True} and f.closed


@pytest.mark.parametrize('damage',['unknown','duplicate','oversize','too_many','gap','id_duplicate'])
def test_stream_tool_validation_before_any_dispatch(monkeypatch,damage):
    m=feature()
    additions=[{'index':0}|tool()]
    if damage=='unknown':additions[0]['function']['name']='unknown'
    elif damage=='duplicate':additions[0]['function']['arguments']='{"ok":true,"ok":false}'
    elif damage=='oversize':additions[0]['function']['arguments']='x'*4097
    elif damage=='too_many':additions=[{'index':i}|tool(id='call-'+str(i)) for i in range(4)]
    elif damage=='gap':additions[0]['index']=1
    elif damage=='id_duplicate':additions=[{'index':i}|tool() for i in range(2)]
    with pytest.raises(m.ByokError):stream_execute(monkeypatch,sse(chunk(tools=additions),chunk(finish='tool_calls')),purpose='probe_tools')


def test_stream_text_utf8_cap_and_unknown_finish(monkeypatch):
    m=feature()
    for payload in (sse(chunk('x'*5000),chunk(finish='stop')),sse(chunk('ok'),chunk(finish='unknown'))):
        with pytest.raises(m.ByokError):stream_execute(monkeypatch,payload,purpose='probe_stream')


def test_complete_validated_usage_never_invents_zero(monkeypatch):
    result,_=execute(monkeypatch,response(usage={'prompt_tokens':2,'completion_tokens':3,'total_tokens':5}))
    assert result.usage.completion_tokens==3
    m=feature()
    for usage in ({'completion_tokens':3},{'prompt_tokens':True,'completion_tokens':3,'total_tokens':4}, {'prompt_tokens':2,'completion_tokens':3,'total_tokens':6}):
        with pytest.raises(m.ByokError,match='PROVIDER_INVALID_RESPONSE'):execute(monkeypatch,response(usage=usage))


@pytest.mark.parametrize('damage',['owner','config','credential_version','ciphertext'])
def test_final_committed_credential_binding_fail_closed(monkeypatch,damage):
    m=feature();from work_byok_adapter_fakes import reservation,run
    from app.core.byok_crypto import encrypt_credential,CredentialEnvelope
    reserved,f=reservation(m);snapshot=reserved._snapshot
    envelope=encrypt_credential('SYNTHETIC-SWAP',owner_subject='other' if damage=='owner' else snapshot.owner_subject,
        config_id='other' if damage=='config' else snapshot.config_id,
        credential_version=2 if damage=='credential_version' else snapshot.credential_version,keyring=f.ring)
    if damage=='ciphertext':envelope=CredentialEnvelope(envelope.format_version,envelope.key_id,envelope.ciphertext[:-5]+'xxxxx')
    # Construct an immutable repository snapshot containing synthetic mismatched
    # authenticated envelope, never forge a receipt or caller authority.
    swapped=f.m.repo.LockedConfig(snapshot.owner_subject,snapshot.config_id,snapshot.config_version,snapshot.credential_version,
        snapshot.endpoint,snapshot.model_ids,snapshot.response_model_aliases,envelope)
    reserved._snapshot=swapped
    async def attempt():
        async with m.open_invocation(reserved,f.ring):raise AssertionError('invalid binding entered invocation')
    with pytest.raises(m.ByokError,match='CREDENTIAL_UNAVAILABLE'):run(attempt())
    assert reserved._consumed


@pytest.mark.parametrize('damage',['model','destination','caps'])
def test_final_reservation_provenance_binding_before_decrypt(monkeypatch,damage):
    m=feature();from work_byok_adapter_fakes import reservation,run
    reserved,f=reservation(m)
    if damage=='model':reserved.selection=reserved.selection.model_copy(update={'model_id':'other'})
    elif damage=='destination':reserved.provenance=reserved.provenance.model_copy(update={'destination_digest':'0'*64})
    else:reserved.caps=reserved.caps.model_copy(update={'output_tokens':1})
    calls=[];monkeypatch.setattr(m,'decrypt_credential',lambda *a,**k:calls.append('decrypt'))
    async def attempt():
        async with m.open_invocation(reserved,f.ring):pass
    with pytest.raises(m.ByokError):run(attempt())
    assert calls==[]


def test_adapter_uses_production_opener_and_global_lease_without_retry_cache():
    m=feature();import ast
    text=(ROOT/'backend/app/services/byok/adapter.py').read_text()
    assert 'open_protected_client' in text and 'EGRESS_CAPACITY.acquire()' in text
    assert all(word not in text for word in ('AsyncOpenAI','ChatOpenAI','lru_cache','find_user_custom_model_credentials','get_cached_chat_model'))
    tree=ast.parse(text)
    assert not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in ('post','request','send') for n in ast.walk(tree))


def test_normal_stream_requires_verified_stream_evidence(monkeypatch):
    m=feature()
    with pytest.raises(m.ByokError,match='CAPABILITY_UNVERIFIED'):
        stream_execute(monkeypatch,sse(chunk('ok'),chunk(finish='stop')),purpose='student_chat')
    events,_=stream_execute(monkeypatch,sse(chunk('ok'),chunk(finish='stop')),purpose='student_chat',stream_verified=True)
    assert events[-1].result.model_state=='complete'


def test_committed_capability_proof_is_immutable_and_fully_bound():
    m=feature();from work_byok_adapter_fakes import reservation
    from pydantic import ValidationError
    reserved,f=reservation(m,stream_verified=True)
    proofs=reserved._snapshot.capability_evidence
    assert proofs and all(type(p).__name__=='CapabilityProof' for p in proofs)
    proof=next(p for p in proofs if p.probe_kind=='stream')
    assert proof.owner_subject==reserved._snapshot.owner_subject and proof.config_id==reserved.selection.config_id
    assert proof.credential_version==reserved._snapshot.credential_version and proof.destination_digest==reserved.provenance.destination_digest
    with pytest.raises(ValidationError):proof.probe_kind='tools'


def test_r1_unadmitted_stream_proof_cannot_authorize_dispatch(monkeypatch):
    m=feature();from work_byok_adapter_fakes import reservation,run,FakeHTTP
    old,f=reservation(m,stream_verified=True)
    provenance=old.provenance.model_copy(update={'capability_evidence_ids':()})
    with f.owner() as tx:pending=tx.repository.reserve_custom_call(f.actor,old.selection,'student_chat',f.caps,provenance)
    current=f.m.reservations.commit_custom_reservation(pending,tx.receipt)
    fake=FakeHTTP(sse(chunk('ok'),chunk(finish='stop')),headers={'content-type':'text/event-stream'})
    monkeypatch.setattr(m,'open_protected_client',fake.opener)
    async def attempt():
        async with m.open_invocation(current,f.ring) as inv:
            request=m.ModelRequest(messages=({'role':'user','content':'Synthetic'},),purpose='student_chat',limits=f.caps,stream=True)
            with pytest.raises(m.ByokError,match='CAPABILITY_UNVERIFIED'):
                [event async for event in m.ChatCompletionsAdapter(clock=lambda:0).stream(inv,request,deadline=30)]
    run(attempt());assert fake.calls==0 and m.EGRESS_CAPACITY.active==0


@pytest.mark.parametrize('calls',[{},False,0,''])
@pytest.mark.parametrize('finish',['stop','length','content_filter'])
def test_r1_falsy_tool_calls_wrong_type_is_invalid(monkeypatch,calls,finish):
    m=feature();payload=response(finish=finish);payload['choices'][0]['message']['tool_calls']=calls
    with pytest.raises(m.ByokError,match='PROVIDER_INVALID_RESPONSE'):execute(monkeypatch,payload)


@pytest.mark.parametrize('calls',[None,[]])
def test_r1_optional_null_or_empty_tool_list_is_not_malformed(monkeypatch,calls):
    payload=response();payload['choices'][0]['message']['tool_calls']=calls
    result,_=execute(monkeypatch,payload)
    assert result.model_state=='complete' and result.tool_calls==()


def test_r1_foreign_configured_model_proof_is_retained_but_cannot_authorize_stream(monkeypatch):
    m=feature();from work_byok_adapter_fakes import reservation,run,FakeHTTP
    old,f=reservation(m,stream_verified=True);snapshot=old._snapshot
    proof=next(p for p in snapshot.capability_evidence if p.probe_kind=='stream')
    foreign=proof.model_copy(update={'model_id':'other-model'})
    old._snapshot=f.m.repo.LockedConfig(snapshot.owner_subject,snapshot.config_id,snapshot.config_version,snapshot.credential_version,
        snapshot.endpoint,('same-id','other-model'),snapshot.response_model_aliases,snapshot.envelope,(foreign,))
    fake=FakeHTTP(sse(chunk('ok'),chunk(finish='stop')),headers={'content-type':'text/event-stream'})
    monkeypatch.setattr(m,'open_protected_client',fake.opener)
    async def attempt():
        async with m.open_invocation(old,f.ring) as inv:
            assert 'stream' not in inv._verified_capabilities
            request=m.ModelRequest(messages=({'role':'user','content':'Synthetic'},),purpose='student_chat',limits=f.caps,stream=True)
            with pytest.raises(m.ByokError,match='CAPABILITY_UNVERIFIED'):
                [event async for event in m.ChatCompletionsAdapter(clock=lambda:0).stream(inv,request,deadline=30)]
    run(attempt());assert fake.calls==0
