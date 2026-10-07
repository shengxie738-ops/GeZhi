"""Dedicated versioned BYOK credentials, independent of application secrets.

Configuration is supplied explicitly; importing this module never loads
settings, legacy crypto or environment files. There is no key generation,
derivation, default encryption key, legacy decrypt or batch re-encryption.
Metadata readiness does not authenticate ciphertext. Only a committed-call
invocation may decrypt and enter SecretValue.invocation_scope().
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
from dataclasses import dataclass, field
import json
import re
from types import MappingProxyType
from typing import Mapping
import unicodedata

from cryptography.fernet import Fernet, InvalidToken

from app.services.byok.errors import ByokError
from app.services.byok.types import CredentialState, validate_api_key

FORMAT_VERSION = 1
MAX_KEYRING_KEYS = 16
MAX_KEYRING_BYTES = 8192
MAX_CIPHERTEXT_BYTES = 8192
_KEY_ID = re.compile(r'[A-Za-z0-9._-]{1,64}', re.ASCII)
_CONFIG_ID = re.compile(r'[A-Za-z0-9_-]{1,128}', re.ASCII)
_FERNET_KEY = re.compile(r'[A-Za-z0-9_-]{43}=', re.ASCII)
_TOKEN = re.compile(r'[A-Za-z0-9_-]+={0,2}', re.ASCII)
_PLAINTEXT_FIELDS = frozenset({'owner_subject', 'config_id', 'credential_version', 'api_key'})
# Reject-only fingerprints of public repository fallbacks and trivial examples.
# None is ever selected, generated, derived or used for encryption.
_PUBLIC_EXAMPLE_KEYS = frozenset({
    'VTOxYMqoo3C8jJgtXnC0RgzlZ_gEkqIRKAvyhobL8_w=',
    'AoKDUWUqzEkXX5T_gtQUD8JhQTL1P3J-049SXZj0gPI=',
    'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=',
    '__________________________________________8=',
})


def _reject_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON field')
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError('non-finite JSON value')


def _strict_json(value):
    return json.loads(value, object_pairs_hook=_reject_duplicates, parse_constant=_reject_constant)


@dataclass(frozen=True)
class ByokKeyringStatus:
    """Safe key-ID availability, never key bytes or a decryption capability."""
    available: bool
    key_ids: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ByokKeyring:
    active_key_id: str
    _keys: Mapping[str, Fernet] = field(repr=False, compare=False)

    @property
    def status(self) -> ByokKeyringStatus:
        return ByokKeyringStatus(available=True, key_ids=frozenset(self._keys))


@dataclass(frozen=True, repr=False)
class CredentialEnvelope:
    """Stored ciphertext DTO, distinct from legacy bare ciphertext strings."""
    format_version: int
    key_id: str
    ciphertext: str

    def __repr__(self):
        return 'CredentialEnvelope(<redacted>)'


class SecretValue:
    """Non-serializable, one-use header source with best-effort memory clearing.

Never pass this object or its extracted string to callbacks, logs, queues or
durable DTOs. The extracted Python string cannot be securely erased; callers
must use it only for the single invocation and close its transport afterward.
"""
    __slots__ = ('__value', '__scope_open', '__closed')

    def __init__(self, value: str):
        validate_api_key(value)
        self.__value = bytearray(value.encode('utf-8'))
        self.__scope_open = False
        self.__closed = False

    def __repr__(self):
        return 'SecretValue(<redacted>)'

    def __str__(self):
        raise TypeError('secret string conversion is forbidden')

    def __reduce__(self):
        raise TypeError('secret serialization is forbidden')

    def __reduce_ex__(self, protocol):
        raise TypeError('secret serialization is forbidden')

    def model_dump(self, *args, **kwargs):
        raise TypeError('secret serialization is forbidden')

    def model_dump_json(self, *args, **kwargs):
        raise TypeError('secret serialization is forbidden')

    @property
    def closed(self) -> bool:
        return self.__closed

    def close(self) -> None:
        if not self.__closed:
            self.__value[:] = b'\x00' * len(self.__value)
            self.__value.clear()
            self.__scope_open = False
            self.__closed = True

    @contextmanager
    def invocation_scope(self):
        if self.__closed or self.__scope_open:
            raise TypeError('secret invocation scope is unavailable')
        self.__scope_open = True
        try:
            yield self
        finally:
            self.close()

    def header_value(self) -> str:
        if self.__closed or not self.__scope_open:
            raise TypeError('secret header requires its invocation scope')
        return self.__value.decode('utf-8')


def load_byok_keyring(active_key_id: str | None, raw_keyring: str | None) -> ByokKeyring:
    """Validate the entire bounded keyring; any invalid entry fails closed."""
    try:
        if type(active_key_id) is not str or _KEY_ID.fullmatch(active_key_id) is None:
            raise ValueError('invalid active key ID')
        if type(raw_keyring) is not str or not 1 <= len(raw_keyring.encode('utf-8')) <= MAX_KEYRING_BYTES:
            raise ValueError('invalid keyring input')
        entries = _strict_json(raw_keyring)
        if type(entries) is not dict or not 1 <= len(entries) <= MAX_KEYRING_KEYS or active_key_id not in entries:
            raise ValueError('invalid keyring mapping')
        keys = {}
        for key_id, value in entries.items():
            if type(key_id) is not str or _KEY_ID.fullmatch(key_id) is None:
                raise ValueError('invalid key ID')
            if type(value) is not str or _FERNET_KEY.fullmatch(value) is None or value in _PUBLIC_EXAMPLE_KEYS:
                raise ValueError('invalid encryption key')
            decoded = base64.b64decode(value, altchars=b'-_', validate=True)
            if len(decoded) != 32 or base64.urlsafe_b64encode(decoded).decode('ascii') != value:
                raise ValueError('noncanonical encryption key')
            keys[key_id] = Fernet(value.encode('ascii'))
        return ByokKeyring(active_key_id, MappingProxyType(keys))
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ByokError('BYOK_STORAGE_UNAVAILABLE') from None


def _usable_keyring(keyring) -> ByokKeyring:
    if not isinstance(keyring, ByokKeyring) or keyring.active_key_id not in keyring._keys:
        raise ByokError('BYOK_STORAGE_UNAVAILABLE') from None
    return keyring


def _valid_binding(owner_subject, config_id, credential_version) -> bool:
    return (
        type(owner_subject) is str and 1 <= len(owner_subject) <= 255
        and owner_subject == owner_subject.strip()
        and not any(unicodedata.category(char) in {'Cc', 'Cf', 'Cs'} for char in owner_subject)
        and type(config_id) is str and _CONFIG_ID.fullmatch(config_id) is not None
        and type(credential_version) is int and credential_version >= 1
    )


def _envelope_structure(envelope) -> bool:
    return (
        isinstance(envelope, CredentialEnvelope)
        and type(envelope.format_version) is int and envelope.format_version == FORMAT_VERSION
        and type(envelope.key_id) is str and _KEY_ID.fullmatch(envelope.key_id) is not None
        and type(envelope.ciphertext) is str
        and 100 <= len(envelope.ciphertext) <= MAX_CIPHERTEXT_BYTES
        and _TOKEN.fullmatch(envelope.ciphertext) is not None
    )


def encrypt_credential(api_key: str, *, owner_subject: str, config_id: str,
                       credential_version: int, keyring: ByokKeyring) -> CredentialEnvelope:
    keyring = _usable_keyring(keyring)
    validate_api_key(api_key)
    if not _valid_binding(owner_subject, config_id, credential_version):
        raise ByokError('INVALID_INPUT') from None
    try:
        plaintext = json.dumps({'owner_subject': owner_subject, 'config_id': config_id,
            'credential_version': credential_version, 'api_key': api_key},
            ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
        ciphertext = keyring._keys[keyring.active_key_id].encrypt(plaintext).decode('ascii')
        if len(ciphertext) > MAX_CIPHERTEXT_BYTES:
            raise ValueError('credential envelope exceeds its bound')
        return CredentialEnvelope(FORMAT_VERSION, keyring.active_key_id, ciphertext)
    except (ValueError, TypeError, UnicodeError, OverflowError):
        raise ByokError('CREDENTIAL_UNAVAILABLE') from None


def credential_metadata_state(envelope, keyring_status: ByokKeyringStatus) -> CredentialState:
    """Metadata only. A nonempty legacy string always requires fresh entry.

None/empty means missing; integrations with a separate legacy field pass its
bare ciphertext here. Unknown formats are unavailable, never legacy decrypt.
Already discovered decrypt_failed flags remain the record owner's authority;
this function does not authenticate or clear those flags on list/keep reads.
"""
    if envelope is None or (type(envelope) is str and not envelope):
        return 'missing'
    if type(envelope) is str:
        return 'legacy_reentry_required'
    if isinstance(envelope, CredentialEnvelope) and type(envelope.ciphertext) is str and not envelope.ciphertext:
        return 'missing'
    if not _envelope_structure(envelope):
        return 'decrypt_failed'
    if not isinstance(keyring_status, ByokKeyringStatus) or keyring_status.available is not True or type(keyring_status.key_ids) is not frozenset or envelope.key_id not in keyring_status.key_ids:
        return 'key_id_unavailable'
    return 'ready'


def decrypt_credential(envelope: CredentialEnvelope, *, owner_subject: str,
                       config_id: str, credential_version: int, keyring: ByokKeyring) -> SecretValue:
    if type(envelope) is str and envelope:
        raise ByokError('CREDENTIAL_REENTRY_REQUIRED') from None
    keyring = _usable_keyring(keyring)
    if not _valid_binding(owner_subject, config_id, credential_version) or not _envelope_structure(envelope) or envelope.key_id not in keyring._keys:
        raise ByokError('CREDENTIAL_UNAVAILABLE') from None
    try:
        plaintext = keyring._keys[envelope.key_id].decrypt(envelope.ciphertext.encode('ascii'))
        data = _strict_json(plaintext.decode('utf-8'))
        if type(data) is not dict or data.keys() != _PLAINTEXT_FIELDS:
            raise ValueError('invalid credential fields')
        if not _valid_binding(data['owner_subject'], data['config_id'], data['credential_version']):
            raise ValueError('invalid credential binding')
        if (data['owner_subject'], data['config_id'], data['credential_version']) != (owner_subject, config_id, credential_version):
            raise ValueError('credential binding does not match')
        validate_api_key(data['api_key'])
        return SecretValue(data['api_key'])
    except (InvalidToken, ValueError, TypeError, UnicodeError, RecursionError, ByokError):
        raise ByokError('CREDENTIAL_UNAVAILABLE') from None
