"""Pure Task 1 contracts; always invoke through run_work_byok_offline.py."""
from dataclasses import FrozenInstanceError, asdict
from datetime import datetime, timezone
import hashlib
import importlib
import json
from pathlib import Path
from types import ModuleType
import sys

import pytest
from pydantic import TypeAdapter, ValidationError

ROOT = Path(__file__).resolve().parents[2]
MODULES = {
    'selection': 'app.schemas.model_selection',
    'types': 'app.services.byok.types',
    'limits': 'app.services.byok.limits',
    'errors': 'app.services.byok.errors',
    'endpoint': 'app.services.byok.endpoint_policy',
}


def feature(name):
    module = MODULES[name]
    assert (ROOT / 'backend' / (module.replace('.', '/') + '.py')).is_file(), f'Task 1 feature missing: {module}'
    return importlib.import_module(module)


def custom(**changes):
    return {'source': 'custom', 'config_id': 'config-a', 'config_version': 1, 'model_id': 'same-id'} | changes


def test_selection_is_strict_and_frozen():
    s = feature('selection')
    adapter = TypeAdapter(s.ModelSelection)
    platform = adapter.validate_python({'source': 'platform', 'model_id': 'same-id'})
    a = adapter.validate_python(custom())
    b = adapter.validate_python(custom(config_id='config-b'))
    assert platform.model_dump() == {'source': 'platform', 'model_id': 'same-id'}
    assert a.config_version == 1
    assert len({platform, a, b}) == 3
    assert adapter.validate_python(custom(model_id='Auto Mode')).source == 'custom'
    for selection in (platform, a):
        with pytest.raises(ValidationError):
            selection.model_id = 'new'
    assert adapter.validate_json(json.dumps(custom())).model_dump() == custom()


@pytest.mark.parametrize('value', [
    {}, {'source': 'platform'}, {'source': 'platform', 'model_id': 1},
    {'source': 'custom', 'model_id': 'same-id'}, custom(config_version=True),
    custom(config_version='1'), custom(config_version=0), custom(config_version=1.0),
    custom(config_id=1), custom(model_id=''), custom(model_id='x\n'),
    custom(model_id='x' * 201), custom(source='CUSTOM'),
    *[custom(**{field: 'synthetic-secret'}) for field in ('owner', 'user_id', 'url', 'api_key', 'adapter_id')],
])
def test_selection_rejects_ambiguous_payload(value):
    with pytest.raises(ValidationError):
        TypeAdapter(feature('selection').ModelSelection).validate_python(value)


def test_model_ids_and_key_validation():
    t = feature('types')
    assert t.normalize_model_ids([' same-id ', 'same-id', 'Same-ID']) == ('same-id', 'Same-ID')
    assert t.validate_api_key('synthetic-token') == 'synthetic-token'
    assert t.validate_api_key('k' * 1024) == 'k' * 1024
    for key in ('', ' ', ' key', 'key ', 'k\n', 'k' * 1025, 123):
        with pytest.raises(feature('errors').ByokError) as caught:
            t.validate_api_key(key)
        assert 'key ' not in str(caught.value)
    for ids in ([], ['x'] * 21, [''], ['x' * 201], ['x\x7f'], 'a', [123]):
        with pytest.raises(feature('errors').ByokError):
            t.normalize_model_ids(ids)
    assert len(t.normalize_model_ids([str(i) for i in range(20)])) == 20
    assert t.normalize_model_ids(['x' * 200]) == ('x' * 200,)


def test_actor_only_from_current_account(monkeypatch):
    t = feature('types')
    # Explicit synthetic ORM identity seam: no ORM/database/startup module executes.
    module = ModuleType('app.models.user_account')
    class UserAccount:
        username = 'synthetic-student'
        role = 'student'
    module.UserAccount = UserAccount
    monkeypatch.setitem(sys.modules, 'app.models.user_account', module)
    actor = t.AuthenticatedModelActor.from_current_account(UserAccount())
    assert actor.subject == 'synthetic-student' and actor.role == 'student'
    with pytest.raises((TypeError, feature('errors').ByokError)):
        t.AuthenticatedModelActor('request-owner', 'teacher')
    with pytest.raises(feature('errors').ByokError):
        t.AuthenticatedModelActor.from_current_account({'username': 'request-owner', 'role': 'teacher'})
    with pytest.raises(FrozenInstanceError):
        actor.subject = 'other'
    for role in ('admin', 'Student', True):
        account = UserAccount()
        account.role = role
        with pytest.raises(feature('errors').ByokError):
            t.AuthenticatedModelActor.from_current_account(account)


def test_endpoint_normalization():
    e = feature('endpoint')
    a = e.normalize_endpoint('https://Provider.Example.:443/v1')
    b = e.normalize_endpoint('https://provider.example/v1/chat/completions')
    assert a == b
    assert (a.base_url, a.endpoint_url, a.host, a.port, a.base_path) == (
        'https://provider.example/v1', 'https://provider.example/v1/chat/completions', 'provider.example', 443, '/v1')
    digest_input = {'adapter_id': 'openai_chat_completions_v1', 'host': 'provider.example', 'port': 443, 'base_path': '/v1'}
    assert a.destination_digest == hashlib.sha256(json.dumps(digest_input, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    assert e.normalize_endpoint('https://provider.example/Api/V1').base_path == '/Api/V1'
    assert e.normalize_endpoint('https://bücher.example/v1').host == 'xn--bcher-kva.example'
    assert e.normalize_endpoint('https://8.8.8.8').endpoint_url == 'https://8.8.8.8/chat/completions'
    assert e.normalize_endpoint('https://[2606:4700:4700::1111]/v1').host == '2606:4700:4700::1111'
    assert e.normalize_endpoint('https://provider.example/v1/chat/completions/chat/completions').base_path == '/v1/chat/completions'
    assert e.normalize_endpoint('https://provider.example/chat/completions/').endpoint_url.endswith('/chat/completions/chat/completions')
    with pytest.raises(FrozenInstanceError):
        a.port = 80


@pytest.mark.parametrize('url', [
    'http://provider.example/v1', 'https://provider.example:80/v1', 'https://provider.example:444/v1',
    'https://user:pass@provider.example/v1', 'https://provider.example/v1?', 'https://provider.example/v1?x=1',
    'https://provider.example/v1#', 'https://provider.example/v1#x', 'https://provider.example\\v1',
    'https://%70rovider.example/v1', 'https://provider.example/a/../v1', 'https://provider.example/a/./v1',
    'https://provider.example/%2e%2e/v1', 'https://provider.example/%2fsecret', 'https://provider.example/%5csecret',
    'https://provider.example/%00', 'https://provider.example/%0a', 'https://provider.example/%252f',
    'https://provider.example/%', 'https://provider.example/%zz', 'https://provider.example\n/v1',
    'https://provider.example/a b', 'https://[fe80::1%25eth0]/v1', 'https://localhost./v1',
    'https://a.localhost./v1', 'https://INTERNAL/v1', 'https://a.local./v1',
    'https://127.0.0.1/v1', 'https://127.1/v1', 'https://0177.0.0.1/v1', 'https://2130706433/v1',
    'https://0x7f000001/v1', 'https://0x8.0x8.0x8.0x8/v1', 'https://8.8.8.08/v1',
    'https://[::ffff:127.0.0.1]/v1', 'https://[::1]/v1', 'https://192.0.2.1/v1',
    'https://provider.example:/v1', 'https://provider.example:0443/v1', 'https:///v1',
    'https://-bad.example', 'https://a..example', 'https://provider.example/v1' + 'x' * 512, 123,
])
def test_endpoint_rejects_unsafe_or_ambiguous_input(url):
    with pytest.raises(feature('errors').ByokError) as caught:
        feature('endpoint').normalize_endpoint(url)
    assert caught.value.code == 'ENDPOINT_NOT_ALLOWED'
    assert 'provider.example' not in str(caught.value)


@pytest.mark.parametrize('address', [
    '0.0.0.0', '10.0.0.1', '100.64.0.1', '127.0.0.1', '169.254.169.254',
    '172.16.0.1', '192.168.0.1', '192.0.0.9', '192.0.2.1', '192.88.99.1',
    '198.18.0.1', '198.51.100.1', '203.0.113.1', '224.0.0.1', '240.0.0.1',
    '255.255.255.255', '::', '::1', 'fc00::1', 'fe80::1', 'ff02::1', '2001:db8::1',
    '2002:0808:0808::1', '64:ff9b::808:808', '::ffff:10.0.0.1', '3fff::1',
    'not-an-ip', '8.8.8.8%zone',
])
def test_special_address_classes_are_rejected(address):
    assert feature('endpoint').is_global_unicast(address) is False


def test_full_dns_set_fails_closed():
    e = feature('endpoint')
    assert e.validate_resolved_addresses(['8.8.8.8', '8.8.8.8', '2606:4700:4700::1111']) == ('8.8.8.8', '2606:4700:4700::1111')
    assert len(e.validate_resolved_addresses([f'8.8.8.{i}' for i in range(1, 17)])) == 16
    for addresses in ([], ['8.8.8.8', '10.0.0.1'], ['8.8.8.8', '::1'], ['x'],
                      [f'8.8.8.{i}' for i in range(1, 18)], '8.8.8.8'):
        with pytest.raises(feature('errors').ByokError) as caught:
            e.validate_resolved_addresses(addresses)
        assert caught.value.code == 'DNS_REJECTED'


def test_destination_consent_requires_exact_digest():
    t, e = feature('types'), feature('endpoint')
    endpoint = e.normalize_endpoint('https://provider.example/v1')
    consent = t.DestinationConsent(accepted=True, destination_digest=endpoint.destination_digest)
    t.validate_destination_consent(consent, endpoint)
    with pytest.raises(ValidationError):
        t.DestinationConsent(accepted=1, destination_digest=endpoint.destination_digest)
    with pytest.raises(ValidationError):
        t.DestinationConsent(accepted=False, destination_digest=endpoint.destination_digest)
    with pytest.raises(feature('errors').ByokError):
        t.validate_destination_consent(consent, e.normalize_endpoint('https://other.example/v1'))


def test_caps_are_frozen():
    l = feature('limits')
    expected = {
        'configs_per_actor': 20, 'models_per_config': 20, 'name_chars': 64, 'provider_label_chars': 64,
        'url_chars': 512, 'key_chars': 1024, 'model_id_chars': 200, 'aliases_per_model': 3,
        'api_body_bytes': 16384, 'dns_addresses': 16, 'connect_seconds': 5,
        'probe_seconds': 15, 'probe_text_tokens': 16, 'probe_capability_tokens': 64,
        'probe_envelope_bytes': 32768, 'probe_text_bytes': 4096, 'probe_active_per_actor': 1,
        'probe_starts_per_minute': 6, 'probe_retention_seconds': 900, 'probe_records_per_actor': 100,
        'probe_records_per_process': 4096, 'probe_record_bytes': 2048,
        'student_total_seconds': 120, 'student_call_seconds': 30, 'student_model_calls': 4,
        'student_output_allowance': 8192, 'student_main_tokens': 4096, 'student_tutor_tokens': 2048,
        'profile_tokens': 512, 'visual_tokens': 1024, 'request_bytes': 131072, 'envelope_bytes': 262144,
        'text_bytes': 131072, 'sse_event_bytes': 32768, 'tool_arguments_bytes': 4096, 'tool_call_count': 3,
        'teacher_call_seconds': 90, 'teacher_output_tokens': 8192, 'teacher_deadline_multiplier': 3,
        'teacher_model_calls': 1, 'student_active_per_actor': 1, 'inference_active_per_process': 4,
        'teacher_active_cap': 4, 'egress_active_per_process': 4, 'retry_after_seconds': 300,
        'provider_retries': 0, 'keepalive_connections': 0, 'http1': True, 'http2': False,
        'proxy': None, 'uds': None, 'follow_redirects': False, 'trust_env': False,
        'profile_enabled_by_default': False, 'visual_text_enabled': False, 'media_enabled': False,
    }
    assert asdict(l.CAPS) == expected
    with pytest.raises(FrozenInstanceError):
        l.CAPS.student_model_calls = 10
    budget = l.WorkCallBudget.student(clock=lambda: 0)
    limits = budget.reserve('student_chat', 4096)
    assert budget.remaining_output_tokens == 8192 - 4096
    assert limits.output_tokens == 4096 and limits.timeout_seconds == 30
    assert limits.connect_seconds == 5
    with pytest.raises(ValidationError):
        limits.output_tokens = 5000
    for field, limit in (('request_bytes', 131072), ('envelope_bytes', 262144), ('text_bytes', 131072),
                         ('sse_event_bytes', 32768), ('tool_arguments_bytes', 4096), ('tool_call_count', 3)):
        assert getattr(limits, field) == limit
        l.check_limit(field, limit, limits)
        with pytest.raises(feature('errors').ByokError):
            l.check_limit(field, limit + 1, limits)


@pytest.mark.parametrize('purpose,cap', [('student_chat',4096), ('student_tutor',2048), ('student_rag',4096),
    ('student_paper',4096), ('student_academic_review',4096), ('profile',512), ('visual_text',1024)])
def test_student_purpose_output_boundary(purpose, cap):
    l = feature('limits')
    assert l.WorkCallBudget.student(clock=lambda:0).reserve(purpose,cap).output_tokens == cap
    with pytest.raises(feature('errors').ByokError):
        l.WorkCallBudget.student(clock=lambda:0).reserve(purpose,cap+1)


def test_budget_has_no_usage_refund_or_auto_retry():
    l, errors = feature('limits'), feature('errors')
    budget = l.WorkCallBudget.student(clock=lambda: 0)
    budget.reserve('student_chat',4096)
    budget.reserve('student_tutor',2048)
    budget.reserve('student_tutor',2048)
    assert budget.remaining_output_tokens == 0
    with pytest.raises(errors.ByokError):
        budget.reserve('profile',1)
    assert not hasattr(budget,'refund')
    budget = l.WorkCallBudget.student(clock=lambda: 0)
    for _ in range(4): budget.reserve('profile',1)
    with pytest.raises(errors.ByokError): budget.reserve('profile',1)
    for tokens in (True, 0, -1, '1', 1.5):
        with pytest.raises(errors.ByokError): l.WorkCallBudget.student(clock=lambda:0).reserve('profile',tokens)
    for purpose in ('unknown','teacher_chat','probe_text'):
        with pytest.raises(errors.ByokError): l.WorkCallBudget.student(clock=lambda:0).reserve(purpose,1)


def test_deadlines_and_teacher_probe_clamps():
    l, errors = feature('limits'), feature('errors')
    now = [10.0]
    budget = l.WorkCallBudget.student(clock=lambda:now[0], task_output_tokens=100, task_call_seconds=20)
    assert budget.reserve('student_chat',100).output_tokens == 100
    budget = l.WorkCallBudget.student(clock=lambda:now[0])
    now[0] = 125.0
    limits = budget.reserve('profile',1)
    assert limits.timeout_seconds == 5 and limits.connect_seconds == 5
    now[0] = 130.0
    with pytest.raises(errors.ByokError): budget.reserve('profile',1)
    teacher = l.WorkCallBudget.teacher(clock=lambda:0, configured_timeout_seconds=500, configured_output_tokens=9000)
    assert teacher.deadline == 270
    assert teacher.reserve('teacher_chat',8192).timeout_seconds == 90
    with pytest.raises(errors.ByokError): teacher.reserve('teacher_lesson_outline',1)
    lower = l.WorkCallBudget.teacher(clock=lambda:0, configured_timeout_seconds=7, configured_output_tokens=12)
    assert lower.deadline == 21 and lower.reserve('teacher_lesson_outline',12).timeout_seconds == 7
    for purpose, cap in [('probe_text',16),('probe_stream',64),('probe_json',64),('probe_tools',64)]:
        probe=l.WorkCallBudget.probe(purpose,clock=lambda:0)
        limits=probe.reserve(purpose,cap)
        assert limits.timeout_seconds==15 and limits.envelope_bytes==32768 and limits.text_bytes==4096
        with pytest.raises(errors.ByokError): probe.reserve(purpose,1)
    with pytest.raises(errors.ByokError): l.WorkCallBudget.probe('unknown',clock=lambda:0)


def test_capability_evidence_and_provenance_are_immutable_and_secret_free():
    t, l = feature('types'), feature('limits')
    evidence=t.CapabilityEvidence(evidence_id='evidence-1',config_version=1,model_id='same-id',
        probe_kind='json',generation=1,checked_at=datetime(2026,10,7,tzinfo=timezone.utc),duration_ms=20)
    attempt=t.ProbeAttempt(config_version=1,model_id='same-id',probe_kind='json',generation=2,
        status='failed',checked_at=datetime(2026,10,7,tzinfo=timezone.utc),duration_ms=10,code='PROVIDER_RATE_LIMITED')
    state=t.ModelCapability(capability='json',state='verified',successful_evidence=evidence,latest_attempt=attempt)
    assert state.successful_evidence.generation==1 and state.latest_attempt.generation==2
    limits=l.WorkCallBudget.student(clock=lambda:0).reserve('student_chat',1)
    endpoint=feature('endpoint').normalize_endpoint('https://provider.example/v1')
    p=t.ModelProvenance(selection=TypeAdapter(feature('selection').ModelSelection).validate_python(custom()),
        destination_digest=endpoint.destination_digest,safe_host=endpoint.host,
        capability_evidence_ids=('evidence-1',),frozen_caps=limits)
    assert p.policy_version=='work-byok@1' and p.adapter_version=='1'
    for field in ('api_key','credential_envelope','owner','url'):
        with pytest.raises(ValidationError): t.ModelProvenance(**(p.model_dump() | {field:'synthetic-key'}))
    with pytest.raises(ValidationError): t.CapabilityEvidence(**(evidence.model_dump() | {'probe_kind':'other'}))
    with pytest.raises(ValidationError): t.ModelCapability(capability='unknown',state='verified')
    with pytest.raises(ValidationError): t.ModelCapability(capability='json',state='imaginary')
    with pytest.raises(ValidationError): state.state='unsupported'
    assert 'synthetic-key' not in p.model_dump_json()


def test_safe_errors_do_not_echo_rejected_inputs_or_provider_exceptions():
    e = feature('errors')
    error=e.ByokError('PROVIDER_AUTH_FAILED',401,'request-opaque',fields=('api_key',))
    body=e.public_error(error)
    assert body=={'code':'PROVIDER_AUTH_FAILED','message':e.PUBLIC_MESSAGES['PROVIDER_AUTH_FAILED'],
                  'request_id':'request-opaque','fields':['api_key']}
    assert e.public_error(ValueError('synthetic-secret Authorization raw provider body'))['code']=='OUTCOME_UNKNOWN'
    for kwargs in ({'code':'made-up'}, {'code':'PROVIDER_AUTH_FAILED','fields':('synthetic-secret',)},
                   {'code':'PROVIDER_AUTH_FAILED','request_id':'secret/url?token=bad'}):
        with pytest.raises(ValueError): e.ByokError(**kwargs)
    expected={'MODEL_SELECTION_REQUIRED','CUSTOM_MODEL_NOT_FOUND','MODEL_CONFIG_STALE','MODEL_DISABLED',
        'CREDENTIAL_REENTRY_REQUIRED','BYOK_STORAGE_UNAVAILABLE','CREDENTIAL_UNAVAILABLE','MODEL_NOT_IN_CONFIG',
        'UNSUPPORTED_ADAPTER','CAPABILITY_UNVERIFIED','CAPABILITY_UNSUPPORTED','DESTINATION_CONSENT_REQUIRED',
        'ENDPOINT_NOT_ALLOWED','DNS_REJECTED','TLS_FAILED','PROVIDER_REDIRECT_REJECTED','PROVIDER_AUTH_FAILED',
        'PROVIDER_MODEL_NOT_FOUND','PROVIDER_RATE_LIMITED','PROVIDER_TIMEOUT','PROVIDER_INVALID_RESPONSE',
        'PROVIDER_EMPTY','PROVIDER_INCOMPLETE','MODEL_ID_MISMATCH','CANCELLED','OUTCOME_UNKNOWN'}
    assert expected <= set(e.PUBLIC_MESSAGES)
    assert all(e.public_error(e.ByokError(code))['code']==code for code in e.PUBLIC_MESSAGES)


def test_legitimate_encoded_paths_preserve_meaning():
    endpoint = feature('endpoint').normalize_endpoint('https://provider.example/Api/a%20b/%25/%3f%23')
    assert endpoint.base_path == '/Api/a%20b/%25/%3F%23'


def test_budget_cannot_be_directly_expanded():
    with pytest.raises(TypeError):
        feature('limits').WorkCallBudget(clock=lambda:0,purposes={'student_chat':999999},total_seconds=999999,
            call_seconds=90,output_allowance=999999,calls=999999)


def test_body_labels_aliases_and_finite_deadlines_boundaries():
    t,l,e=feature('types'),feature('limits'),feature('errors')
    l.validate_api_body_size(b'x'*16384)
    with pytest.raises(e.ByokError) as caught: l.validate_api_body_size(b'x'*16385)
    assert caught.value.status_code==413
    with pytest.raises(e.ByokError): l.validate_api_body_size('x')
    assert t.validate_display_label('n'*64)=='n'*64
    for value in ('n'*65,'',123,'n\n'):
        with pytest.raises(e.ByokError): t.validate_display_label(value)
    aliases=t.normalize_response_model_aliases({'same-id':['alias','Alias','alias']},('same-id',))
    assert aliases['same-id']==('alias','Alias')
    with pytest.raises(TypeError): aliases['other']=('alias',)
    for value in ({'other':['alias']},{'same-id':['a','b','c','d']},{'same-id':['x\n']},['alias']):
        with pytest.raises(e.ByokError): t.normalize_response_model_aliases(value,('same-id',))
    for value in (float('nan'),float('inf'),True):
        with pytest.raises(e.ByokError): l.WorkCallBudget.student(clock=lambda:value)
    for alias in (t.ModelPurpose,t.CredentialState,t.ProbeStatus,t.ModelCompletionState,t.DeliveryState,t.PersistenceState):
        with pytest.raises(ValidationError): TypeAdapter(alias).validate_python('imaginary')


def test_failed_attempt_cannot_be_successful_capability_evidence():
    t=feature('types')
    attempt=t.ProbeAttempt(config_version=1,model_id='same-id',probe_kind='json',generation=1,
        status='failed',checked_at=datetime(2026,10,7,tzinfo=timezone.utc),duration_ms=1,code='PROVIDER_AUTH_FAILED')
    with pytest.raises(ValidationError):
        t.ModelCapability(capability='json',state='verified',successful_evidence=attempt)


def test_pydantic_public_error_only_contains_safe_field_names():
    selection=feature('selection')
    with pytest.raises(ValidationError) as caught:
        TypeAdapter(selection.ModelSelection).validate_python(custom(api_key='synthetic-secret-key',
            **{'secret-key-as-field-name':'synthetic-provider-body'}))
    body=feature('errors').public_error(caught.value)
    assert body['code']=='INVALID_INPUT' and body['fields']==['api_key']
    assert 'synthetic-' not in json.dumps(body) and 'secret-key-as-field-name' not in json.dumps(body)


def test_pool_policy_is_complete_and_initial_versions_are_explicit():
    t,l=feature('types'),feature('limits')
    assert t.INITIAL_CONFIG_VERSION==t.INITIAL_CREDENTIAL_VERSION==t.INITIAL_DESTINATION_CONSENT_VERSION==1
    assert t.INITIAL_INVENTORY_REVISION==0
    assert t.KEY_MASK=='••••••••'
    assert l.CAPS.http1 is True and l.CAPS.http2 is False
    assert l.CAPS.proxy is None and l.CAPS.uds is None and l.CAPS.follow_redirects is False


@pytest.mark.parametrize('url',['https://provider.example:443:443/v1','https://provider.example::443/v1'])
def test_malformed_multiple_port_authority_is_rejected(url):
    with pytest.raises(feature('errors').ByokError): feature('endpoint').normalize_endpoint(url)


def test_error_public_fields_and_cross_field_limits_are_immutable():
    e,l=feature('errors'),feature('limits')
    error=e.ByokError('INVALID_INPUT',fields=('api_key',))
    for field,value in [('code','synthetic-secret'),('status_code',200),('request_id','token'),('fields',('token',))]:
        with pytest.raises((AttributeError,FrozenInstanceError)): setattr(error,field,value)
    # Exception machinery must remain able to attach traceback/context.
    error.__traceback__=None
    valid=l.WorkCallBudget.student(clock=lambda:0).reserve('student_chat',1).model_dump()
    with pytest.raises(ValidationError): l.ModelCallLimits(**(valid|{'timeout_seconds':1.0,'connect_seconds':5.0}))
    with pytest.raises(ValidationError): l.ModelCallLimits(**(valid|{'text_bytes':32768,'envelope_bytes':16384}))


@pytest.mark.parametrize('kind,purpose', [('student','profile'),('teacher','teacher_chat'),('probe','probe_text')])
def test_failed_deadline_observation_cannot_resurrect_budget(kind,purpose):
    limits,errors=feature('limits'),feature('errors')
    now=[0.0]
    factory=getattr(limits.WorkCallBudget,kind)
    budget=factory(purpose,clock=lambda:now[0]) if kind=='probe' else factory(clock=lambda:now[0])
    counters=(budget.remaining_output_tokens,budget.remaining_calls)
    now[0]=budget.deadline
    with pytest.raises(errors.ByokError) as caught: budget.reserve(purpose,1)
    assert caught.value.code=='MODEL_BUDGET_EXCEEDED'
    now[0]=budget.deadline-1
    with pytest.raises(errors.ByokError) as caught: budget.reserve(purpose,1)
    assert caught.value.code=='MODEL_BUDGET_EXCEEDED'
    assert (budget.remaining_output_tokens,budget.remaining_calls)==counters


@pytest.mark.parametrize('kind,purpose,cap', [('student','profile',512),('teacher','teacher_chat',8192),('probe','probe_text',16)])
def test_failed_oversize_observation_remains_monotonic_without_debit(kind,purpose,cap):
    limits,errors=feature('limits'),feature('errors')
    now=[0.0]
    factory=getattr(limits.WorkCallBudget,kind)
    budget=factory(purpose,clock=lambda:now[0]) if kind=='probe' else factory(clock=lambda:now[0])
    counters=(budget.remaining_output_tokens,budget.remaining_calls)
    now[0]=10.0
    with pytest.raises(errors.ByokError): budget.reserve(purpose,cap+1)
    assert (budget.remaining_output_tokens,budget.remaining_calls)==counters
    now[0]=9.0
    with pytest.raises(errors.ByokError): budget.reserve(purpose,1)
    assert (budget.remaining_output_tokens,budget.remaining_calls)==counters
    now[0]=10.0
    assert budget.reserve(purpose,cap).output_tokens==cap
    assert (budget.remaining_output_tokens,budget.remaining_calls)==(counters[0]-cap,counters[1]-1)


def test_failed_clock_observations_neither_lower_watermark_nor_refund_previous_reservations():
    limits,errors=feature('limits'),feature('errors')
    now=[0.0]
    budget=limits.WorkCallBudget.student(clock=lambda:now[0])
    now[0]=1.0
    budget.reserve('student_chat',100)
    counters=(8092,3)
    assert (budget.remaining_output_tokens,budget.remaining_calls)==counters
    now[0]=50.0
    with pytest.raises(errors.ByokError): budget.reserve('profile',513)
    for regressing_time in (49.0,48.0,49.5):
        now[0]=regressing_time
        with pytest.raises(errors.ByokError): budget.reserve('profile',1)
        assert (budget.remaining_output_tokens,budget.remaining_calls)==counters
    now[0]=50.0
    budget.reserve('profile',512)
    counters=(7580,2)
    assert (budget.remaining_output_tokens,budget.remaining_calls)==counters
    for failed_time in (120.0,119.0):
        now[0]=failed_time
        with pytest.raises(errors.ByokError): budget.reserve('profile',1)
        assert (budget.remaining_output_tokens,budget.remaining_calls)==counters
