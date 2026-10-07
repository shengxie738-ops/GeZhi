"""Task 5 adapter deadline, encoding, capacity and no-retry boundaries."""
import importlib
import pytest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]


def feature():
    assert (ROOT/'backend/app/services/byok/adapter.py').is_file(), 'Task 5 adapter missing'
    return importlib.import_module('app.services.byok.adapter')


def invoke(monkeypatch,payload,**kwargs):
    m=feature(); from work_byok_adapter_fakes import invoke,run
    return run(invoke(m,monkeypatch,payload,**kwargs))


def valid():
    return b'{"model":"same-id","choices":[{"message":{"role":"assistant","content":"ok"},"finish_reason":"stop"}]}'


@pytest.mark.parametrize('headers',[{'content-encoding':'gzip'},{'content-encoding':'br'},{'content-type':'text/html'},{'content-length':'999999999'},{'content-length':'-1'}])
def test_encoding_and_header_caps_before_body(monkeypatch,headers):
    m=feature(); seen=[]
    with pytest.raises(m.ByokError):invoke(monkeypatch,valid(),headers=headers,seen=seen)
    assert seen and seen[0].iterations==0 and seen[0].closed and seen[0].calls==1


@pytest.mark.parametrize('headers',[{}, {'content-length':'1'}])
def test_missing_or_false_content_length_does_not_bypass_cap(monkeypatch,headers):
    m=feature(); seen=[]
    with pytest.raises(m.ByokError,match='MODEL_BUDGET_EXCEEDED'):
        invoke(monkeypatch,[b' '*131072,b' '*131073],headers=headers,seen=seen)
    assert seen[0].closed


@pytest.mark.parametrize('status,code',[(401,'PROVIDER_AUTH_FAILED'),(403,'PROVIDER_AUTH_FAILED'),(404,'PROVIDER_MODEL_NOT_FOUND'),(429,'PROVIDER_RATE_LIMITED'),(500,'OUTCOME_UNKNOWN'),(503,'OUTCOME_UNKNOWN')])
def test_timeout_retry_after_and_capacity_no_retry(monkeypatch,status,code):
    m=feature(); seen=[]
    with pytest.raises(m.ByokError,match=code):invoke(monkeypatch,valid(),status=status,seen=seen,headers={'retry-after':'99999'})
    assert seen[0].calls==1 and seen[0].iterations==0 and seen[0].closed


@pytest.mark.parametrize('value,expected',[('0',0),('300',300),('301',300),('5',5),('-1',None),('NaN',None),('Wed, 21 Oct 2015 07:28:00 GMT',None),('',None)])
def test_retry_after_bounded_hint(value,expected):
    assert feature().parse_retry_after(value)==expected


@pytest.mark.parametrize('purpose,timeout,total',[('probe_text',15,15),('student_chat',30,120),('teacher_chat',90,270)])
def test_timeout_policy_and_remaining_clamp(purpose,timeout,total):
    feature(); from app.services.byok.limits import WorkCallBudget
    now=[0.0]; factory=WorkCallBudget.probe(purpose,clock=lambda:now[0]) if purpose.startswith('probe') else WorkCallBudget.teacher(clock=lambda:now[0]) if purpose.startswith('teacher') else WorkCallBudget.student(clock=lambda:now[0])
    assert factory.deadline==total
    now[0]=total-2.0
    assert factory.reserve(purpose,1).timeout_seconds==2.0


def test_parse_and_body_deadline_includes_remaining(monkeypatch):
    m=feature(); seen=[]
    with pytest.raises(m.ByokError,match='PROVIDER_TIMEOUT'):invoke(monkeypatch,valid(),advance=31.0,seen=seen)
    assert seen[0].closed and seen[0].calls==1


def test_cancel_actual_close_before_capacity_release(monkeypatch):
    m=feature(); from work_byok_adapter_fakes import cancellation_case,run
    run(cancellation_case(m,monkeypatch))


def test_request_cap_before_network_or_decrypt(monkeypatch):
    m=feature(); seen=[]
    with pytest.raises(m.ByokError,match='MODEL_BUDGET_EXCEEDED'):invoke(monkeypatch,valid(),content='x'*131073,seen=seen)
    assert seen==[]


def test_retry_after_hint_reaches_safe_public_error(monkeypatch):
    m=feature();from app.services.byok.errors import public_error
    with pytest.raises(m.ByokError) as error:invoke(monkeypatch,valid(),status=429,headers={'retry-after':'99999'})
    assert public_error(error.value)['retry_after_seconds']==300


def test_adapter_student_actor_process_capacity_and_probe_separation():
    m=feature();capacity=m.InferenceCapacity()
    first=capacity.acquire('same','student_chat')
    with pytest.raises(m.ByokError,match='MODEL_CAPACITY_EXCEEDED'):capacity.acquire('same','student_tutor')
    # Profile/visual are calls in the same student request scope too.
    with pytest.raises(m.ByokError,match='MODEL_CAPACITY_EXCEEDED'):capacity.acquire('same','profile')
    for i in range(3):capacity.acquire('other-'+str(i),'teacher_chat')
    with pytest.raises(m.ByokError,match='MODEL_CAPACITY_EXCEEDED'):capacity.acquire('last','teacher_chat')
    assert capacity.active==4


def test_unknown_or_failed_actual_close_retains_both_capacities(monkeypatch):
    m=feature();from work_byok_adapter_fakes import reservation,run,FakeHTTP
    from contextlib import asynccontextmanager
    async def scenario():
        reserved,f=reservation(m);fake=FakeHTTP(valid())
        egress=m.EGRESS_CAPACITY.active;inference=m.INFERENCE_CAPACITY.active
        @asynccontextmanager
        async def opener(endpoint,limits,*,deadline,egress_lease):
            fake.egress=egress_lease;egress_lease._bind(fake)
            try:yield fake
            finally:raise m.ByokError('BYOK_EGRESS_UNAVAILABLE')
        monkeypatch.setattr(m,'open_protected_client',opener)
        async with m.open_invocation(reserved,f.ring) as inv:
            request=m.ModelRequest(messages=({'role':'user','content':'Synthetic'},),purpose='student_chat',limits=f.caps)
            with pytest.raises(m.ByokError,match='BYOK_EGRESS_UNAVAILABLE'):
                await m.ChatCompletionsAdapter(clock=lambda:0).complete(inv,request,deadline=30)
        assert m.EGRESS_CAPACITY.active==egress+1 and m.INFERENCE_CAPACITY.active==inference+1
        # Test owner confirms later actual close; production does not pretend
        # uncertain terminal is closed and cannot invent an early release.
        await fake.aclose()
        for lease in list(m.INFERENCE_CAPACITY._active):m.INFERENCE_CAPACITY.release_after_terminal(lease,fake.egress)
        assert m.EGRESS_CAPACITY.active==egress and m.INFERENCE_CAPACITY.active==inference
    run(scenario())
