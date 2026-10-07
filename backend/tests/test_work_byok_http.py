"""Task 4 HTTP boundary and Stage A closure without whole-app imports."""
import asyncio
import ast
import importlib
import json
import logging
from pathlib import Path
import pytest
from pydantic import TypeAdapter, ValidationError
ROOT = Path(__file__).resolve().parents[2]
KEY = 'SYNTHETIC-T4-REJECTED-KEY'


class SocketlessLoop(asyncio.SelectorEventLoop):

    def _make_self_pipe(self):
        self._ssock = None
        self._csock = None

    def _close_self_pipe(self):
        pass

    def _write_to_self(self):
        pass


def run(coro):
    loop = SocketlessLoop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def feature():
    assert (ROOT / 'backend/app/services/byok/http_boundary.py').is_file(), 'Task 4 bounded HTTP missing'
    return importlib.import_module('app.services.byok.http_boundary')


def test_list_never_decrypts_and_validation_never_echoes():
    m = feature()
    from app.schemas.model_selection import ModelSelection
    with pytest.raises(ValidationError) as exc:
        TypeAdapter(ModelSelection).validate_python({'source': KEY, 'api_key': KEY})
    status, body = m.safe_http_error(exc.value)
    assert status == 422 and KEY not in json.dumps(body) and (body['error']['code'] == 'INVALID_INPUT')


@pytest.mark.parametrize(
    'body',
    [b'{"api_key":"SYNTHETIC-T4-REJECTED-KEY",}', b'{"api_key":"a","api_key":"SYNTHETIC-T4-REJECTED-KEY"}', b'{"api_key":NaN}', b'{"expected_config_version":true}', b'[]', b'null', b'"SYNTHETIC-T4-REJECTED-KEY"', b'\xff']
)


def test_strict_bounded_parse_no_echo(body):
    m = feature()
    from app.schemas.user_model import UserCustomModelDeleteRequest
    with pytest.raises(m.ByokError) as exc:
        m.parse_bounded_json(body, UserCustomModelDeleteRequest)
    status, response = m.safe_http_error(exc.value)
    assert KEY not in repr(response) and status in (400, 422)


def test_body_cap_exact_and_streamed_plus_one():
    m = feature()
    from app.schemas.user_model import UserCustomModelDeleteRequest
    body = b'{"expected_config_version":1}'
    padded = body + b' ' * (16384 - len(body))
    assert m.parse_bounded_json(padded, UserCustomModelDeleteRequest).expected_config_version == 1
    with pytest.raises(m.ByokError, match='BODY_TOO_LARGE'):
        m.parse_bounded_json(padded + b' ', UserCustomModelDeleteRequest)

    class Request:
        headers = {}

        async def stream(self):
            yield (b'x' * 8192)
            yield (b'x' * 8193)
    with pytest.raises(m.ByokError, match='BODY_TOO_LARGE'):
        run(m.read_bounded_body(Request()))


@pytest.mark.parametrize(
    'sink',
    ['app.services.byok.adapter', 'httpx', 'httpcore.connection', 'langchain.callbacks', 'langchain_core.tracers', 'opentelemetry', 'sentry_sdk', 'app.api.endpoints.user_models']
)


def test_deny_by_default_logs_and_trace_sinks(sink):
    feature()
    m = importlib.import_module('app.services.byok.observability')
    record = logging.LogRecord(sink, logging.ERROR, 'provider-url', 1, KEY, (KEY,), None)
    record.url = 'https://provider.example/secret'
    record.body = KEY
    record.authorization = KEY
    assert m.ByokPrivacyFilter().filter(record) is False
    record = m.safe_log_record(
        request_id='opaque-id',
        code='INVALID_INPUT',
        http_status=422,
        config_id='synthetic-config',
        config_version=1
    )
    assert m.ByokPrivacyFilter().filter(record)
    assert KEY not in repr(record.__dict__)
    with pytest.raises(ValueError):
        m.safe_log_record(body=KEY)


def test_legacy_test_raw_http_mask_lookup_and_decrypt_closed():
    feature()
    tree = ast.parse((ROOT / 'backend/app/api/endpoints/user_models.py').read_text())
    fn = next((n for n in tree.body if isinstance(
        n,
        (ast.FunctionDef, ast.AsyncFunctionDef)
    ) and n.name == 'test_custom_model_connection'))
    namespace = {'ByokError': importlib.import_module('app.services.byok.errors').ByokError}
    fn.decorator_list = []
    fn.args = ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[])
    exec(
        compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), 'closure', 'exec'),
        namespace
    )
    with pytest.raises(namespace['ByokError'], match='MODEL_SELECTION_REQUIRED'):
        run(namespace[fn.name]())
    text = (ROOT / 'backend/app/api/endpoints/user_models.py').read_text()
    assert 'httpx' not in text and 'decrypt_secret' not in text and ('mask_api_key' not in text)


def test_bare_id_custom_same_id_platform_cannot_decrypt_or_fallback():
    feature()
    tree = ast.parse((ROOT / 'backend/app/api/endpoints/chat.py').read_text())
    selected = []
    for name in (
        'find_user_custom_model_credentials',
        'build_agent_runtime_config',
        'get_request_chat_model'
    ):
        node = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name))
        node.decorator_list = []
        for arg in node.args.args + node.args.kwonlyargs:
            arg.annotation = None
        node.returns = None
        selected.append(node)
    errors = importlib.import_module('app.services.byok.errors')
    called = []
    ns = {
        'ByokError': errors.ByokError,
        'resolve_request_agent_id': lambda *a: called.append('agent'),
        'get_default_agent_prompt': lambda *a: called.append('prompt'),
        'resolve_runtime_model_id': lambda *a: called.append('platform'),
        'build_chat_model': lambda *a,
        **k: called.append('platform'),
        'ChatOpenAI': lambda **k: called.append('raw-http'),
        'paper_remaining_seconds': lambda: 10
    }
    exec(
        compile(ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[])), 'closure', 'exec'),
        ns
    )
    for name in ('same-id', 'Auto Mode', 'platform-looking-id'):
        request = type('Request', (), {'agent_model': name})()
        with pytest.raises(errors.ByokError, match='MODEL_SELECTION_REQUIRED'):
            ns['build_agent_runtime_config'](
                request,
                thread_id='t',
                agent_mode='chat',
                message='Synthetic',
                user_id='owner',
                db=object()
            )
    with pytest.raises(errors.ByokError, match='MODEL_SELECTION_REQUIRED'):
        ns['find_user_custom_model_credentials'](object(), 'owner', 'same-id')
    with pytest.raises(errors.ByokError, match='UNSUPPORTED_ADAPTER'):
        ns['get_request_chat_model']({'configurable': {
            'custom_model_api_key': KEY,
            'custom_model_base_url': 'https://provider.example',
            'agent_model': 'same-id'
        }})
    assert called == []


def test_app_registration_and_routes_success_status_contract():
    feature()
    text = (ROOT / 'backend/app/main.py').read_text()
    assert 'install_byok_http_boundary(app)' in text and 'install_byok_privacy_filters()' in text
    routes = (ROOT / 'backend/app/api/endpoints/user_models.py').read_text()
    assert 'status_code=201' in routes and 'UserCustomModelDeleteRequest' in routes
    assert 'Request' in routes and 'read_bounded_body' in routes


def test_http_middleware_handles_unknown_raw_exception_without_upstream_log():
    m = feature()
    secret = KEY + ' https://provider.example/private-body'

    async def app(scope, receive, send):
        raise RuntimeError(secret)
    output = []

    async def send(message):
        output.append(message)

    async def receive():
        return {'type': 'http.request', 'body': b'', 'more_body': False}
    middleware = m.ByokBoundaryMiddleware(app)
    run(middleware({'type': 'http', 'path': '/api/user/models', 'headers': []}, receive, send))
    assert output[0]['status'] == 503 and secret not in repr(output)
    assert b'OUTCOME_UNKNOWN' in output[1]['body']


def test_http_query_rejection_and_safe_logging_factory(monkeypatch):
    m = feature()
    privacy = importlib.import_module('app.services.byok.observability')
    previous = logging.getLogRecordFactory()
    monkeypatch.setattr(logging, '_logRecordFactory', previous)
    privacy.install_byok_privacy_filters()
    logger = logging.getLogger('httpcore.new_unregistered_child')
    record = logger.makeRecord(logger.name, logging.ERROR, 'secret-url', 1, KEY, (KEY,), None)
    assert KEY not in repr(record.__dict__)
    assert privacy.ByokPrivacyFilter().filter(record) is False


def test_actual_router_crud_versions_snapshot_failclosed_errors(monkeypatch):
    feature()
    from work_byok_repository_fakes import fixture, Session
    from fastapi import FastAPI
    import httpx
    f = fixture()
    m = f.m
    config = type(m.database_module)('app.core.config')
    config.settings = type(
        'Settings',
        (),
        {'BYOK_ENCRYPTION_ACTIVE_KEY_ID': 'synthetic', 'BYOK_ENCRYPTION_KEYRING': json.dumps({'synthetic': 'AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8='})}
    )()
    security = type(m.database_module)('app.core.security')
    security.decode_access_token = lambda token: {
        'sub': 'synthetic-other' if token == 'other' else 'synthetic-owner',
        'role': 'FORGED'
    }
    monkeypatch.setitem(__import__('sys').modules, 'app.core.config', config)
    monkeypatch.setitem(__import__('sys').modules, 'app.core.security', security)
    m.database_module.SessionLocal = lambda: Session(f)

    class Connection:

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass
    m.database_module.engine = type('Engine', (), {'connect': lambda self: Connection()})()
    routes = importlib.import_module('app.api.endpoints.user_models')
    monkeypatch.setattr(routes, 'observe_byok_schema', lambda connection: f.observation)
    app = FastAPI()
    app.include_router(routes.router, prefix='/api')
    feature().install_byok_http_boundary(app)
    from test_work_byok_repository import request

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url='http://synthetic.test'
        ) as client:
            headers = {'Authorization': 'Bearer owner'}
            created = await client.post('/api/user/models', json=request(), headers=headers)
            assert created.status_code == 201
            data = created.json()['data']
            id = data['config_id']
            assert data['config_version'] == 1 and data['inventory_revision'] == 1 and ('api_key' not in repr(data))
            listing = await client.get('/api/user/models', headers=headers)
            assert listing.status_code == 200 and listing.json()['data']['inventory_revision'] == 1
            alien = await client.delete(
                '/api/user/models/' + id,
                json={'expected_config_version': 1},
                headers={'Authorization': 'Bearer other'}
            ) if False else await client.request(
                'DELETE',
                '/api/user/models/' + id,
                json={'expected_config_version': 1},
                headers={'Authorization': 'Bearer other'}
            )
            assert alien.status_code == 404 and alien.json()['error']['code'] == 'CUSTOM_MODEL_NOT_FOUND'
            updated = await client.put(
                '/api/user/models/' + id,
                json={'expected_config_version': 1, 'secret_action': 'keep', 'name': 'New name'},
                headers=headers
            )
            assert updated.status_code == 200 and updated.json()['data']['config_version'] == 2
            stale = await client.put(
                '/api/user/models/' + id,
                json={'expected_config_version': 1, 'secret_action': 'keep', 'name': 'Stale'},
                headers=headers
            )
            assert stale.status_code == 409
            invalid = await client.post(
                '/api/user/models',
                json=request(api_key=KEY, secret_action='keep'),
                headers=headers
            )
            assert invalid.status_code == 422 and KEY not in invalid.text
            overflow = await client.post('/api/user/models', content=b'x' * 16385, headers=headers)
            assert overflow.status_code == 413
            retired = await client.post(
                '/api/user/models/test',
                json={'api_key': KEY, 'base_url': 'https://provider.example'},
                headers=headers
            )
            assert retired.json()['error']['code'] == 'MODEL_SELECTION_REQUIRED'
            deleted = await client.request(
                'DELETE',
                '/api/user/models/' + id,
                json={'expected_config_version': 2},
                headers=headers
            )
            assert deleted.status_code == 200 and deleted.json()['data']['config_version'] == 3 and (deleted.json()['data']['inventory_revision'] == 3)
            f.observation = None
            unavailable = await client.get('/api/user/models', headers=headers)
            assert unavailable.status_code == 503 and unavailable.json()['error']['code'] == 'BYOK_STORAGE_UNAVAILABLE'
    run(scenario())


def test_explicit_legacy_override_rejected_at_common_request_entry_before_search():
    feature()
    tree = ast.parse((ROOT / 'backend/app/api/endpoints/chat.py').read_text())
    fn = next((n for n in tree.body if isinstance(
        n,
        ast.FunctionDef
    ) and n.name == '_validate_task_identity'))
    fn.args.args[0].annotation = None
    fn.returns = None
    errors = importlib.import_module('app.services.byok.errors')
    calls = []
    namespace = {
        'ByokError': errors.ByokError,
        'clean_message_content': lambda x: calls.append('content') or 'Synthetic',
        'resolve_agent_mode': lambda x: calls.append('mode') or 'chat',
        '_resolve_student_work_skill': lambda x: calls.append('skill')
    }
    exec(
        compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), 'entry', 'exec'),
        namespace
    )
    request = type(
        'Request',
        (),
        {'agent_model': 'same-id', 'message': 'Synthetic', 'conversation_id': None}
    )()
    with pytest.raises(errors.ByokError, match='MODEL_SELECTION_REQUIRED'):
        namespace[fn.name](request)
    assert calls == []
    for name in ('chat', 'chat_stream', 'stream_chat_events'):
        route = next((n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == name))
        firstcall = next((n for n in ast.walk(ast.Module(body=route.body, type_ignores=[])) if isinstance(
            n,
            ast.Call
        )))
        assert isinstance(firstcall.func, ast.Name) and firstcall.func.id == '_validate_task_identity'


def test_platform_facade_exact_id_preserved_unknown_custom_not_defaulted():
    feature()
    tree = ast.parse((ROOT / 'backend/app/api/endpoints/chat.py').read_text())
    fn = next((n for n in tree.body if isinstance(
        n,
        ast.FunctionDef
    ) and n.name == 'build_openai_runtime_config'))
    fn.args.args[0].annotation = None
    fn.returns = None
    errors = importlib.import_module('app.services.byok.errors')
    calls = []
    namespace = {
        'ByokError': errors.ByokError,
        'has_model': lambda id,
        category: id == 'exact-platform-id',
        'resolve_runtime_model_id': lambda *args: calls.append('fallback') or 'exact-platform-id'
    }
    exec(
        compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), 'facade', 'exec'),
        namespace
    )
    for model in ('same-custom-id', 'Auto Mode', ''):
        req = type('Request', (), {'model': model})()
        with pytest.raises(errors.ByokError, match='MODEL_SELECTION_REQUIRED'):
            namespace[fn.name](req, thread_id='t', message='Synthetic')
    req = type('Request', (), {'model': 'exact-platform-id'})()
    assert namespace[fn.name](
        req,
        thread_id='t',
        message='Synthetic'
    )['configurable']['agent_model'] == 'exact-platform-id'
    assert calls == []


@pytest.mark.parametrize('logger_name', ['app.r1_unregistered', 'httpcore.r1_future_child'])
@pytest.mark.parametrize('sink_position', ['root', 'new_child'])
def test_r1_logging_extras_never_reach_actual_sinks(logger_name, sink_position, monkeypatch):
    feature()
    privacy = importlib.import_module('app.services.byok.observability')
    records = []

    class Sink(logging.Handler):
        def emit(self, record):
            records.append(dict(record.__dict__))

    monkeypatch.setattr(logging, '_logRecordFactory', logging.getLogRecordFactory())
    monkeypatch.setattr(logging.Logger, 'makeRecord', logging.Logger.makeRecord)
    monkeypatch.setattr(logging.Logger, 'handle', logging.Logger.handle)
    privacy.install_byok_privacy_filters()
    # New child logger/handler are created AFTER installation.
    logger = logging.getLogger(logger_name)
    target = logging.getLogger() if sink_position == 'root' else logger
    sink = Sink()
    target.addHandler(sink)
    try:
        with privacy.byok_log_context():
            logger.error(KEY, extra={'body': KEY, 'url': 'https://provider.example/private-path'})
        assert records == []
        record = logger.makeRecord(logger.name, logging.ERROR, 'unsafe-url', 1, KEY, (), None,
                                   extra={'body': KEY, 'url': 'https://provider.example/private-path'})
        if logger_name.startswith('httpcore'):
            assert KEY not in repr(record.__dict__)
            assert 'https://provider.example/private-path' not in repr(record.__dict__)
    finally:
        target.removeHandler(sink)


def test_r1_approved_structured_record_still_reaches_root_sink(monkeypatch):
    feature()
    privacy = importlib.import_module('app.services.byok.observability')
    records = []

    class Sink(logging.Handler):
        def emit(self, record):
            records.append(dict(record.__dict__))

    monkeypatch.setattr(logging, '_logRecordFactory', logging.getLogRecordFactory())
    monkeypatch.setattr(logging.Logger, 'makeRecord', logging.Logger.makeRecord)
    monkeypatch.setattr(logging.Logger, 'handle', logging.Logger.handle)
    privacy.install_byok_privacy_filters()
    logger = logging.getLogger('app.services.byok.approved')
    root = logging.getLogger()
    sink = Sink()
    root.addHandler(sink)
    try:
        logger.handle(privacy.safe_log_record(code='INVALID_INPUT', request_id='opaque-r1', http_status=422))
        assert len(records) == 1 and records[0]['code'] == 'INVALID_INPUT'
        assert KEY not in repr(records)
    finally:
        root.removeHandler(sink)
