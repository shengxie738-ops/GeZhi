"""Task 2 credential boundary. Fixtures are fixed SYNTHETIC material only.

Run through the registered offline runner, never application startup/config.
Changing the binding, strict parser, metadata-only path or secret guard breaks
the corresponding behavior assertion below; no test asserts a mock's output.
"""
import ast
from dataclasses import FrozenInstanceError
import importlib
import json
import logging
from pathlib import Path
import pickle
import sys
import traceback
from types import ModuleType
from unittest.mock import Mock

import pytest
from cryptography.fernet import Fernet
from pydantic import BaseModel, ConfigDict

ROOT = Path(__file__).resolve().parents[2]
SYNTHETIC_KEY = 'AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8='
SYNTHETIC_OLD_KEY = 'ICEiIyQlJicoKSorLC0uLzAxMjM0NTY3ODk6Ozw9Pj8='
SYNTHETIC_API_KEY = 'SYNTHETIC-NOT-A-CREDENTIAL-task2-sentinel-秘密'
OWNER = 'synthetic-owner'
CONFIG = 'synthetic-config'


def feature():
    path = ROOT / 'backend/app/core/byok_crypto.py'
    assert path.is_file(), 'Task 2 dedicated credential boundary missing'
    return importlib.import_module('app.core.byok_crypto')


def ring(active='new', entries=None):
    return feature().load_byok_keyring(active, json.dumps(entries or {'new': SYNTHETIC_KEY, 'old': SYNTHETIC_OLD_KEY}))


def encrypt(key=SYNTHETIC_API_KEY, keyring=None, **changes):
    return feature().encrypt_credential(key, **({'owner_subject': OWNER, 'config_id': CONFIG, 'credential_version': 1, 'keyring': keyring or ring()} | changes))


def decrypt(envelope, keyring=None, **changes):
    return feature().decrypt_credential(envelope, **({'owner_subject': OWNER, 'config_id': CONFIG, 'credential_version': 1, 'keyring': keyring or ring()} | changes))


def error_code(code):
    return pytest.raises(importlib.import_module('app.services.byok.errors').ByokError, match='^' + code + '$')


@pytest.mark.parametrize('active,raw', [
    (None, None), ('', ''), ('new', None), (None, '{}'), ('new', '{}'),
    ('new', '[]'), ('new', 'null'), ('new', 'true'), ('new', 'broken'),
    ('absent', json.dumps({'new': SYNTHETIC_KEY})),
    ('new', json.dumps({'new': ''})), ('new', json.dumps({'new': 1})),
    ('new', json.dumps({'new': SYNTHETIC_KEY[:-1]})),
    ('new', json.dumps({'new': SYNTHETIC_KEY + '\n'})),
    ('new', json.dumps({'new': SYNTHETIC_KEY.replace('=', 'A')})),
    ('new', json.dumps({'new': 'VTOxYMqoo3C8jJgtXnC0RgzlZ_gEkqIRKAvyhobL8_w='})),
    ('new', json.dumps({'new': 'AoKDUWUqzEkXX5T_gtQUD8JhQTL1P3J-049SXZj0gPI='})),
    ('new', json.dumps({'new': 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA='})),
    ('new', json.dumps({'new': '__________________________________________8='})),
    ('new', '{"new":"' + SYNTHETIC_KEY + '","new":"' + SYNTHETIC_OLD_KEY + '"}'),
    ('new', '{"new":NaN}'), ('new', '{"new":Infinity}'),
    ('new', json.dumps({'new': SYNTHETIC_KEY, 'bad id': SYNTHETIC_OLD_KEY})),
    ('new', json.dumps({'new': SYNTHETIC_KEY, 'é': SYNTHETIC_OLD_KEY})),
    ('new', json.dumps({'new': SYNTHETIC_KEY, 'x' * 65: SYNTHETIC_OLD_KEY})),
    ('new', json.dumps({'new': SYNTHETIC_KEY, 'bad': 'invalid-inactive-key'})),
    ('k0', json.dumps({f'k{i}': SYNTHETIC_KEY for i in range(17)})),
    ('new', ' ' * 8193), (123, json.dumps({'new': SYNTHETIC_KEY})),
    ('new', {'new': SYNTHETIC_KEY}),
])
def test_keyring_missing_invalid_public_example_fail_closed(active, raw, monkeypatch):
    m = feature()
    for app_secret in ('synthetic-app-secret-a', 'synthetic-app-secret-b'):
        monkeypatch.setenv('APP_SECRET_KEY', app_secret)
        with error_code('BYOK_STORAGE_UNAVAILABLE'):
            m.load_byok_keyring(active, raw)


def test_keyring_is_independent_of_app_secret_and_strictly_bounded(monkeypatch):
    m = feature()
    monkeypatch.setenv('APP_SECRET_KEY', 'synthetic-app-secret-a')
    keyring = ring()
    envelope = encrypt(keyring=keyring)
    monkeypatch.setenv('APP_SECRET_KEY', 'synthetic-app-secret-b')
    recovered = decrypt(envelope, keyring=ring())
    with recovered.invocation_scope():
        assert recovered.header_value() == SYNTHETIC_API_KEY
    assert keyring.active_key_id == 'new'
    assert keyring.status.available is True
    assert keyring.status.key_ids == frozenset({'new', 'old'})
    assert len(m.load_byok_keyring('k0', json.dumps({f'k{i}': SYNTHETIC_KEY for i in range(16)})).status.key_ids) == 16
    assert m.load_byok_keyring('x' * 64, json.dumps({'x' * 64: SYNTHETIC_KEY})).active_key_id == 'x' * 64
    with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
        keyring.active_key_id = 'old'
    assert SYNTHETIC_KEY not in repr(keyring)
    assert SYNTHETIC_OLD_KEY not in repr(keyring)
    assert SYNTHETIC_KEY not in repr(keyring.status)


def test_envelope_bound_to_owner_config_version():
    m = feature()
    envelope = encrypt()
    assert envelope.format_version == 1
    assert envelope.key_id == 'new'
    assert SYNTHETIC_API_KEY not in repr(envelope)
    assert SYNTHETIC_API_KEY not in envelope.ciphertext
    with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
        envelope.key_id = 'old'
    for binding in ({'owner_subject': 'synthetic-other'}, {'config_id': 'synthetic-other'}, {'credential_version': 2}):
        with error_code('CREDENTIAL_UNAVAILABLE'):
            decrypt(envelope, **binding)
    for invalid in (
        m.CredentialEnvelope(2, 'new', envelope.ciphertext),
        m.CredentialEnvelope(True, 'new', envelope.ciphertext),
        m.CredentialEnvelope(1, 'absent', envelope.ciphertext),
        m.CredentialEnvelope(1, 'new', envelope.ciphertext[:-6] + 'AAAAAA'),
        m.CredentialEnvelope(1, 'new', ''),
        m.CredentialEnvelope(1, 'new', 'x' * 8193),
        {'format_version': 1, 'key_id': 'new', 'ciphertext': envelope.ciphertext},
    ):
        with error_code('CREDENTIAL_UNAVAILABLE'):
            decrypt(invalid)
    with error_code('BYOK_STORAGE_UNAVAILABLE'):
        decrypt(envelope, keyring=m.ByokKeyringStatus(available=False))


@pytest.mark.parametrize('api_key', ['', ' ', ' synthetic', 'synthetic ', 'x\n', 'x\x00', 'x' * 1025, 1, None])
def test_encrypt_rejects_invalid_api_keys(api_key):
    feature()
    with error_code('INVALID_INPUT'):
        encrypt(api_key)


@pytest.mark.parametrize('binding', [
    {'owner_subject': ''}, {'owner_subject': ' owner'}, {'owner_subject': 'x\n'},
    {'owner_subject': 'x' * 256}, {'owner_subject': 1},
    {'config_id': ''}, {'config_id': 'bad id'}, {'config_id': 'x' * 129},
    {'config_id': 1}, {'credential_version': 0}, {'credential_version': True},
    {'credential_version': '1'},
])
def test_encrypt_rejects_invalid_binding(binding):
    feature()
    with error_code('INVALID_INPUT'):
        encrypt(**binding)


@pytest.mark.parametrize('payload', [
    '{}', '[]', 'null', '{"api_key":NaN}',
    json.dumps({'owner_subject': OWNER, 'config_id': CONFIG, 'credential_version': True, 'api_key': SYNTHETIC_API_KEY}),
    json.dumps({'owner_subject': OWNER, 'config_id': CONFIG, 'credential_version': 1, 'api_key': ''}),
    json.dumps({'owner_subject': OWNER, 'config_id': CONFIG, 'credential_version': 1, 'api_key': ' ' + SYNTHETIC_API_KEY}),
    json.dumps({'owner_subject': OWNER, 'config_id': CONFIG, 'credential_version': 1, 'api_key': SYNTHETIC_API_KEY, 'extra': 'forbidden'}),
    '{"owner_subject":"' + OWNER + '","config_id":"' + CONFIG + '","credential_version":1,"api_key":"x","api_key":"y"}',
    '{"owner_subject":"' + OWNER + '","config_id":"' + CONFIG + '","credential_version":1,"api_key":1}',
    'not-json-' + SYNTHETIC_API_KEY,
])
def test_authenticated_plaintext_is_strict_json(payload):
    m = feature()
    ciphertext = Fernet(SYNTHETIC_KEY).encrypt(payload.encode()).decode()
    with error_code('CREDENTIAL_UNAVAILABLE'):
        decrypt(m.CredentialEnvelope(1, 'new', ciphertext))


def test_rotated_old_id_reads_without_reencryption_and_new_writes_use_active_id():
    old_envelope = encrypt(keyring=ring(active='old'))
    assert old_envelope.key_id == 'old'
    before = old_envelope.ciphertext
    recovered = decrypt(old_envelope, keyring=ring(active='new'))
    with recovered.invocation_scope():
        assert recovered.header_value() == SYNTHETIC_API_KEY
    assert old_envelope.ciphertext == before
    assert encrypt(keyring=ring(active='new')).key_id == 'new'
    with error_code('CREDENTIAL_UNAVAILABLE'):
        decrypt(old_envelope, keyring=ring(entries={'new': SYNTHETIC_KEY}))


def test_legacy_never_calls_old_decrypt(monkeypatch):
    old = ModuleType('app.core.crypto')
    legacy_decrypt_spy = Mock(side_effect=AssertionError('legacy decrypt must never run'))
    old.decrypt_secret = legacy_decrypt_spy
    monkeypatch.setitem(sys.modules, 'app.core.crypto', old)
    m = feature()
    for status in (ring().status, m.ByokKeyringStatus(available=False)):
        assert m.credential_metadata_state('synthetic-legacy-ciphertext', status) == 'legacy_reentry_required'
        with error_code('CREDENTIAL_REENTRY_REQUIRED'):
            decrypt('synthetic-legacy-ciphertext')
    assert legacy_decrypt_spy.call_count == 0
    assert m.credential_metadata_state(None, ring().status) == 'missing'
    assert m.credential_metadata_state('', ring().status) == 'missing'


def test_metadata_reads_and_keep_candidate_never_decrypt(monkeypatch):
    m = feature()
    keyring = ring()
    envelope = encrypt(keyring=keyring)
    original_ciphertext = envelope.ciphertext
    decrypt_spy = Mock(side_effect=AssertionError('metadata must not decrypt'))
    monkeypatch.setattr(Fernet, 'decrypt', decrypt_spy)
    assert m.credential_metadata_state(envelope, keyring.status) == 'ready'
    assert m.credential_metadata_state(envelope, m.ByokKeyringStatus(available=False)) == 'key_id_unavailable'
    assert m.credential_metadata_state(envelope, ring(entries={'old': SYNTHETIC_OLD_KEY}, active='old').status) == 'key_id_unavailable'
    assert m.credential_metadata_state(m.CredentialEnvelope(2, 'new', envelope.ciphertext), keyring.status) == 'decrypt_failed'
    assert m.credential_metadata_state(m.CredentialEnvelope(1, 'new', ''), keyring.status) == 'missing'
    # A syntactically valid corrupted token is still metadata-ready; dispatch
    # provides authentication. Keep means retaining these bytes unchanged.
    corrupt = m.CredentialEnvelope(1, 'new', envelope.ciphertext[:-6] + 'AAAAAA')
    assert m.credential_metadata_state(corrupt, keyring.status) == 'ready'
    assert envelope.ciphertext == original_ciphertext
    assert decrypt_spy.call_count == 0


def test_secret_repr_and_error_capture_redacted(caplog):
    m = feature()
    secret_value = decrypt(encrypt())
    assert SYNTHETIC_API_KEY not in repr(secret_value)
    assert not hasattr(secret_value, '__dict__')
    for operation in (lambda: str(secret_value), lambda: pickle.dumps(secret_value),
                      lambda: json.dumps(secret_value), lambda: secret_value.model_dump(),
                      lambda: secret_value.model_dump_json(), lambda: secret_value.header_value()):
        with pytest.raises(TypeError) as caught:
            operation()
        assert SYNTHETIC_API_KEY not in str(caught.value)
        assert SYNTHETIC_API_KEY not in repr(caught.value)
        assert SYNTHETIC_API_KEY not in ''.join(traceback.format_exception(caught.value))
    class Carrier(BaseModel):
        model_config = ConfigDict(arbitrary_types_allowed=True)
        secret: m.SecretValue
    carrier = Carrier(secret=secret_value)
    assert SYNTHETIC_API_KEY not in repr(carrier)
    assert SYNTHETIC_API_KEY not in repr(carrier.model_dump())
    with pytest.raises(Exception) as caught:
        carrier.model_dump_json()
    assert SYNTHETIC_API_KEY not in repr(caught.value)
    with caplog.at_level(logging.INFO):
        logging.getLogger('synthetic-task2').info('secret=%r', secret_value)
    assert SYNTHETIC_API_KEY not in caplog.text
    with secret_value.invocation_scope():
        assert secret_value.header_value() == SYNTHETIC_API_KEY
    assert secret_value.closed is True
    with pytest.raises(TypeError):
        secret_value.header_value()
    with pytest.raises(TypeError):
        with secret_value.invocation_scope():
            pass


def test_secret_scope_exception_wipes_value_and_redacts_error():
    value = decrypt(encrypt())
    with pytest.raises(RuntimeError, match='synthetic invocation failure'):
        with value.invocation_scope():
            raise RuntimeError('synthetic invocation failure')
    assert value.closed is True
    assert SYNTHETIC_API_KEY not in repr(value)
    with pytest.raises(TypeError):
        value.header_value()


def test_crypto_failures_public_error_and_traceback_are_redacted():
    m = feature()
    payload = 'broken-json-' + SYNTHETIC_API_KEY
    envelope = m.CredentialEnvelope(1, 'new', Fernet(SYNTHETIC_KEY).encrypt(payload.encode()).decode())
    with error_code('CREDENTIAL_UNAVAILABLE') as caught:
        decrypt(envelope)
    errors = importlib.import_module('app.services.byok.errors')
    captured = repr(caught.value) + str(caught.value) + ''.join(traceback.format_exception(caught.value)) + json.dumps(errors.public_error(caught.value))
    assert SYNTHETIC_API_KEY not in captured
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ is True


def test_config_defaults_and_dependency_contract_are_static_and_nonsecret():
    feature()
    # Do not import config.py: Settings() would read .env. Inspect exact AST.
    tree = ast.parse((ROOT / 'backend/app/core/config.py').read_text())
    settings = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Settings')
    fields = {n.target.id: n for n in settings.body if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)}
    assert ast.literal_eval(fields['BYOK_ENCRYPTION_ACTIVE_KEY_ID'].value) == ''
    raw = fields['BYOK_ENCRYPTION_KEYRING'].value
    assert isinstance(raw, ast.Call) and isinstance(raw.func, ast.Name) and raw.func.id == 'Field'
    opts = {kw.arg: ast.literal_eval(kw.value) for kw in raw.keywords}
    assert opts == {'default': '', 'repr': False, 'exclude': True}
    requirements = (ROOT / 'backend/requirements.txt').read_text().splitlines()
    assert requirements.count('cryptography==50.0.0') == 1
    source = ast.parse((ROOT / 'backend/app/core/byok_crypto.py').read_text())
    imports = [n.module for n in ast.walk(source) if isinstance(n, ast.ImportFrom)]
    assert 'app.core.config' not in imports and 'app.core.crypto' not in imports
    assert all('APP_SECRET_KEY' not in ast.unparse(n) for n in ast.walk(source) if isinstance(n, ast.Name))
