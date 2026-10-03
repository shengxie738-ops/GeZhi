"""Pure bounded Task3 cursor positions. A cursor never conveys authority.

Only the two current catalog projections and immutable assignment versions are
supported. Later assessment list kinds require a separate reviewed extension.
"""
import base64
import binascii
import json
import re

from fastapi import HTTPException

from app.services.teaching.types import exact_identifier

_KINDS = frozenset({'assignment_catalog_author','assignment_catalog_release','assignment_versions'})
_ALPHABET = re.compile(r'[A-Za-z0-9_-]+\Z', re.ASCII)
_MAX_POSITION = 9223372036854775807
_MAX_DECODED_BYTES = 6144
_MAX_ENCODED_BYTES = 8192


def _invalid():
    raise HTTPException(422, 'invalid_cursor')


def _bindings(kind, object_id, actor_id):
    if (type(kind) is not str or kind not in _KINDS
            or not exact_identifier(object_id,36) or not exact_identifier(actor_id)):
        _invalid()


def _position(payload, kind, object_id, actor_id):
    field = 'after_version_number' if kind == 'assignment_versions' else 'after_id'
    if (type(payload) is not dict or set(payload) != {'v','kind','object_id','actor_id',field}
            or type(payload['v']) is not int or payload['v'] != 1
            or payload['kind'] != kind or payload['object_id'] != object_id or payload['actor_id'] != actor_id):
        _invalid()
    value = payload[field]
    if field == 'after_id':
        if not exact_identifier(value,36):
            _invalid()
    elif type(value) is not int or not 1 <= value <= _MAX_POSITION:
        _invalid()
    return {field:value}


def encode_cursor(kind, object_id, actor_id, **position):
    """Emit exactly this kind's required position field, without unused keys."""
    _bindings(kind,object_id,actor_id)
    payload = {'v':1,'kind':kind,'object_id':object_id,'actor_id':actor_id,**position}
    _position(payload,kind,object_id,actor_id)
    raw = json.dumps(payload,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
    encoded = base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')
    if len(raw) > _MAX_DECODED_BYTES or len(encoded) > _MAX_ENCODED_BYTES:
        _invalid()
    return encoded


def _unique_object(pairs):
    result = {}
    for key,value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError('JSON constant forbidden')


def decode_cursor(cursor, kind, object_id, actor_id):
    """Strictly decode an untrusted position bound to current route and actor."""
    _bindings(kind,object_id,actor_id)
    if cursor is None:
        return None
    if type(cursor) is not str or len(cursor) > _MAX_ENCODED_BYTES or not _ALPHABET.fullmatch(cursor):
        _invalid()
    try:
        raw = base64.b64decode(cursor+'='*((-len(cursor))%4),altchars=b'-_',validate=True)
        if len(raw) > _MAX_DECODED_BYTES or base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=') != cursor:
            _invalid()
        payload = json.loads(raw.decode('utf-8'),object_pairs_hook=_unique_object,parse_constant=_reject_constant)
    except (binascii.Error,UnicodeError,ValueError,TypeError,RecursionError):
        _invalid()
    return _position(payload,kind,object_id,actor_id)
