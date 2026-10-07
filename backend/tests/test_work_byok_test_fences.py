"""Bootstrap tests run only this file; all other BYOK tests use the runner."""
from pathlib import Path
import importlib
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / 'backend/tests/run_work_byok_offline.py'
HELPER = ROOT / 'backend/tests/support/work_byok_offline.py'


def _inside_or_launch(name):
    assert RUNNER.is_file(), 'offline runner is not implemented'
    assert HELPER.is_file(), 'offline fence helper is not implemented'
    if os.environ.get('WORK_BYOK_OFFLINE_CHILD') == '1':
        return True
    completed = subprocess.run([sys.executable, '-I', str(RUNNER), '--test',
        f'backend/tests/test_work_byok_test_fences.py::{name}'],
        capture_output=True, text=True, env={'PATH': os.defpath})
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return False


def test_runner_blocks_socket_and_startup():
    if not _inside_or_launch('test_runner_blocks_socket_and_startup'):
        return
    from work_byok_offline import OfflineViolation, expect_denied
    import socket
    import httpx
    for action in (lambda: socket.socket(), lambda: socket.getaddrinfo('example.com', 443),
                   lambda: httpx.get('https://example.com'),
                   lambda: importlib.import_module('app.main'),
                   lambda: importlib.import_module('app.core.init_db'),
                   lambda: importlib.import_module('app.core.database'),
                   lambda: importlib.import_module('openai'),
                   lambda: subprocess.run([sys.executable, '-c', 'pass'])):
        with expect_denied():
            try:
                action()
            except OfflineViolation:
                pass
            else:
                raise AssertionError('an unregistered side effect was allowed')


def test_no_parent_dotenv_or_mixed_source():
    if not _inside_or_launch('test_no_parent_dotenv_or_mixed_source'):
        return
    from work_byok_offline import OfflineViolation, expect_denied, source_report
    import app
    assert Path.cwd() != ROOT
    assert Path(os.environ['HOME']).parent == Path.cwd()
    assert not any(k in os.environ for k in ('HTTP_PROXY', 'ALL_PROXY', 'DATABASE_URL',
                                            'APP_SECRET_KEY', 'PYTHONPATH', 'PYTEST_ADDOPTS'))
    assert all(Path(p).resolve() == ROOT / 'backend/app' for p in app.__path__)
    report = source_report()
    assert report['source_pin_mismatches'] == []
    assert report['real_environment_accesses'] == []
    for path in (ROOT.parent / '.env', ROOT.parent / '.git/config', Path('/root/.codex/sessions/test')):
        with expect_denied():
            try:
                path.read_text()
            except OfflineViolation:
                pass
            else:
                raise AssertionError('a forbidden filesystem read was allowed')


def test_synthetic_scenario_records_only_registered_ports():
    if not _inside_or_launch('test_synthetic_scenario_records_only_registered_ports'):
        return
    from work_byok_offline import OfflineScenario, OfflineViolation, expect_denied
    scene = OfflineScenario()
    assert scene.actor.username == 'synthetic-student'
    assert scene.db.rows == {}
    scene.clock.advance(3)
    assert scene.clock() == 3
    scene.custom('main', {'text': 'synthetic'})
    assert len(scene.custom.calls) == 1
    assert scene.platform.calls == []
    with expect_denied():
        try:
            scene.custom('unregistered', {})
        except OfflineViolation:
            pass
        else:
            raise AssertionError('unregistered model port accepted')


def test_source_fence_detects_injected_mixed_module_and_denies_source_mutation():
    if not _inside_or_launch('test_source_fence_detects_injected_mixed_module_and_denies_source_mutation'):
        return
    from types import ModuleType
    from work_byok_offline import OfflineViolation, expect_denied, source_report
    foreign=ModuleType('app.foreign')
    foreign.__file__=str(ROOT.parent/'foreign.py')
    sys.modules['app.foreign']=foreign
    try:
        assert source_report()['source_pin_mismatches']==['app.foreign']
    finally:
        del sys.modules['app.foreign']
    assert source_report()['source_pin_mismatches']==[]
    for action in (lambda: (ROOT/'new-file').write_text('forbidden'),
                   lambda: (ROOT/'nonexistent-source-mutation-marker').unlink(),
                   lambda: os.chdir(ROOT)):
        with expect_denied():
            try:
                action()
            except OfflineViolation:
                pass
            else:
                raise AssertionError('source mutation was allowed')


def test_native_db_connections_are_fenced():
    if not _inside_or_launch('test_native_db_connections_are_fenced'):
        return
    from work_byok_offline import OfflineViolation, expect_denied
    import work_byok_offline
    assert getattr(work_byok_offline, 'NATIVE_DB_FENCED', False), 'native connection fence is missing'
    import sqlite3
    with expect_denied():
        try:
            sqlite3.connect(':memory:')
        except OfflineViolation:
            pass
        else:
            raise AssertionError('native database execution was allowed')
