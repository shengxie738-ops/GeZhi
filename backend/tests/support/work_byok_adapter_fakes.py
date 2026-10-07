"""Private offline fixtures. Mock HTTP proves protocol only, never SSRF/TLS."""
import asyncio
from contextlib import asynccontextmanager
import json
from types import SimpleNamespace


class SocketlessLoop(asyncio.SelectorEventLoop):
    def _make_self_pipe(self):self._ssock=self._csock=None
    def _close_self_pipe(self):pass
    def _write_to_self(self):pass


def run(coro):
    loop=SocketlessLoop()
    try:return loop.run_until_complete(coro)
    finally:loop.close()


def reservation(m,*,purpose='student_chat',aliases=(),committed=True,stream_verified=False):
    from work_byok_repository_fakes import fixture
    from app.services.byok.capabilities import purpose_limits
    from app.services.byok.endpoint_policy import normalize_endpoint
    from app.services.byok.types import ModelProvenance
    f=fixture();endpoint=normalize_endpoint('https://provider.example/v1')
    if purpose.startswith('teacher_'):
        f.rows['user_accounts']['synthetic-owner'].role='teacher'
        from app.services.byok.types import AuthenticatedModelActor
        f.actor=AuthenticatedModelActor.from_current_account(f.rows['user_accounts']['synthetic-owner'])
    with f.owner() as tx:
        created=tx.repository.create(f.actor,f.create({'name':'Synthetic','provider':'Synthetic','adapter_id':'openai_chat_completions_v1',
            'base_url':endpoint.base_url,'model_ids':['same-id'],'response_model_aliases':{'same-id':list(aliases)},
            'secret_action':'replace','api_key':'SYNTHETIC-T5-NOT-A-CREDENTIAL',
            'destination_consent':{'accepted':True,'destination_digest':endpoint.destination_digest}}))
    f.caps=purpose_limits(purpose)
    evidence=()
    if purpose in {'student_tutor','teacher_chat','teacher_lesson_outline'}:
        f.seed_evidence(created.config_id)
        f.configs[created.config_id].capability_evidence[0]['probe_kind']='tools' if purpose=='student_tutor' else 'json'
        evidence=('synthetic-evidence',)
    if stream_verified:
        if not evidence:f.seed_evidence(created.config_id)
        entry=dict(f.configs[created.config_id].capability_evidence[0])
        entry['probe_kind']='stream';entry['evidence_id']='stream-evidence'
        f.configs[created.config_id].capability_evidence.append(entry)
        evidence=tuple(sorted((*evidence,'stream-evidence')))
    selected=f.selection(created.config_id,1)
    provenance=ModelProvenance(selection=selected,destination_digest=endpoint.destination_digest,safe_host=endpoint.host,
        frozen_caps=f.caps,capability_evidence_ids=evidence)
    with f.owner() as tx:
        pending=tx.repository.reserve_custom_call(f.actor,selected,purpose,f.caps,provenance)
    return (f.m.reservations.commit_custom_reservation(pending,tx.receipt) if committed else pending),f


class FakeHTTP:
    def __init__(self,payload,*,status=200,headers=None,now=None,advance=0,close_gate=None,body_gate=None):
        self.status_code=status
        self.headers={'content-type':'application/json'}|(headers or {})
        self.payload=[json.dumps(payload,ensure_ascii=False).encode()] if type(payload) is dict else [payload] if type(payload) is bytes else payload
        self.calls=self.iterations=0;self.closed=False;self.sent=None;self.egress=None;self.now=now;self.advance=advance
        self.close_gate,self.body_gate=close_gate,body_gate
        self.close_started=asyncio.Event();self.body_started=asyncio.Event()
    async def aiter_raw(self):
        self.iterations+=1
        self.body_started.set()
        if self.body_gate is not None:await self.body_gate.wait()
        if self.now is not None:self.now[0]+=self.advance
        for chunk in self.payload:
            if isinstance(chunk,Exception):raise chunk
            yield chunk
    @asynccontextmanager
    async def stream(self,method,url,**kwargs):
        self.calls+=1;self.sent=kwargs | {'headers':dict(kwargs['headers'])}
        try:yield self
        finally:
            # Response closes through the opener's actual transport owner below.
            pass
    async def aclose(self):
        import anyio
        with anyio.CancelScope(shield=True):
            self.close_started.set()
            if self.close_gate is not None:await self.close_gate.wait()
            self.closed=True
            if self.egress is not None:self.egress._release(self)
    @asynccontextmanager
    async def opener(self,endpoint,limits,*,deadline,egress_lease):
        self.egress=egress_lease;self.egress._bind(self)
        try:yield self
        finally:await self.aclose()


def specs(purpose):
    name='byok_probe' if purpose=='probe_tools' else 'execute_python_code'
    return ({'type':'function','function':{'name':name,'parameters':{'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok'],'additionalProperties':False}}},) if purpose in {'probe_tools','student_tutor'} else ()


async def invoke(m,monkeypatch,payload,*,purpose='student_chat',aliases=(),stream=False,headers=None,status=200,seen=None,advance=0.0,content='Synthetic',stream_verified=False):
    # Test helper imports asyncio only on the socketless loop; no provider call.
    reserved,f=reservation(m,purpose=purpose,aliases=aliases,stream_verified=stream_verified)
    request=m.ModelRequest(messages=({'role':'user','content':content},),purpose=purpose,limits=f.caps,stream=stream,tool_specs=specs(purpose))
    now=[0.0]
    fake=None
    if len(content.encode()) <= f.caps.request_bytes:
        fake=FakeHTTP(payload,status=status,headers=headers,now=now,advance=advance)
        monkeypatch.setattr(m,'open_protected_client',fake.opener)
        if seen is not None:seen.append(fake)
    async with m.open_invocation(reserved,f.ring) as inv:
        adapter=m.ChatCompletionsAdapter(clock=lambda:now[0])
        if stream:result=[event async for event in adapter.stream(inv,request,deadline=f.caps.timeout_seconds)]
        else:result=await adapter.complete(inv,request,deadline=f.caps.timeout_seconds)
    return result,fake


async def cancellation_case(m,monkeypatch):
    import anyio
    reserved,f=reservation(m)
    close_gate,body_gate=asyncio.Event(),asyncio.Event()
    fake=FakeHTTP(b'',close_gate=close_gate,body_gate=body_gate)
    monkeypatch.setattr(m,'open_protected_client',fake.opener)
    request=m.ModelRequest(messages=({'role':'user','content':'Synthetic'},),purpose='student_chat',limits=f.caps)
    start=m.EGRESS_CAPACITY.active;inference=m.INFERENCE_CAPACITY.active
    async def work():
        async with m.open_invocation(reserved,f.ring) as inv:
            await m.ChatCompletionsAdapter(clock=lambda:0.0).complete(inv,request,deadline=30.0)
    async with anyio.create_task_group() as group:
        group.start_soon(work)
        await fake.body_started.wait()
        assert m.EGRESS_CAPACITY.active==start+1 and m.INFERENCE_CAPACITY.active==inference+1
        group.cancel_scope.cancel()
        with anyio.CancelScope(shield=True):
            await fake.close_started.wait()
            assert not fake.closed and m.EGRESS_CAPACITY.active==start+1 and m.INFERENCE_CAPACITY.active==inference+1
            close_gate.set()
    assert fake.closed and m.EGRESS_CAPACITY.active==start and m.INFERENCE_CAPACITY.active==inference
