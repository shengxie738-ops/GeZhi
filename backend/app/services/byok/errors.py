"""Fixed public BYOK errors; never include inputs, exceptions or provider bodies."""
from types import MappingProxyType
import re
from uuid import uuid4
from pydantic import ValidationError

PUBLIC_MESSAGES = MappingProxyType({
    'MODEL_SELECTION_REQUIRED': 'Choose an exact model before continuing.',
    'CUSTOM_MODEL_NOT_FOUND': 'The model configuration is unavailable.',
    'MODEL_CONFIG_STALE': 'The model configuration changed. Choose its current version.',
    'MODEL_DISABLED': 'The model configuration is disabled.',
    'CREDENTIAL_REENTRY_REQUIRED': 'Enter a new provider key for this configuration.',
    'BYOK_STORAGE_UNAVAILABLE': 'Secure model storage is unavailable.',
    'CREDENTIAL_UNAVAILABLE': 'The saved provider credential is unavailable.',
    'MODEL_NOT_IN_CONFIG': 'The selected model is not in this configuration.',
    'UNSUPPORTED_ADAPTER': 'The selected protocol adapter is unsupported.',
    'CAPABILITY_UNVERIFIED': 'Verify the required model capability before continuing.',
    'CAPABILITY_UNSUPPORTED': 'The required model capability is unsupported.',
    'DESTINATION_CONSENT_REQUIRED': 'Approve the displayed provider destination before continuing.',
    'ENDPOINT_NOT_ALLOWED': 'The provider endpoint is not allowed.',
    'DNS_REJECTED': 'The provider address could not be safely resolved.',
    'TLS_FAILED': 'The provider secure connection failed.',
    'PROVIDER_REDIRECT_REJECTED': 'Provider redirects are not allowed.',
    'PROVIDER_AUTH_FAILED': 'The provider did not accept the credential.',
    'PROVIDER_MODEL_NOT_FOUND': 'The provider did not accept the selected model.',
    'PROVIDER_RATE_LIMITED': 'The provider rate limit was reached.',
    'PROVIDER_TIMEOUT': 'The provider call exceeded its time limit.',
    'PROVIDER_INVALID_RESPONSE': 'The provider returned an invalid response.',
    'PROVIDER_EMPTY': 'The provider returned no usable content.',
    'PROVIDER_INCOMPLETE': 'The provider response did not complete.',
    'MODEL_ID_MISMATCH': 'The provider response model did not match the selected model.',
    'CANCELLED': 'The model call was cancelled.',
    'OUTCOME_UNKNOWN': 'The model call outcome is unknown. Check its existing status.',
    'INVALID_INPUT': 'Check the indicated input fields.',
    'BODY_TOO_LARGE': 'The request exceeds the allowed size.',
    'MODEL_BUDGET_EXCEEDED': 'The model request exceeds its remaining budget.',
    'MODEL_PURPOSE_NOT_ALLOWED': 'This model operation is not allowed in this context.',
    'MODEL_CAPACITY_EXCEEDED': 'Model capacity is currently unavailable.',
    'PROBE_RATE_LIMITED': 'The probe start limit was reached.',
    'PROBE_OPERATION_CONFLICT': 'This probe operation cannot be reused.',
    'BYOK_EGRESS_UNAVAILABLE': 'The protected provider connection is unavailable.',
    'AUTHENTICATED_ACTOR_REQUIRED': 'A current authenticated account is required.',
})

SAFE_FIELDS = frozenset({'model_selection', 'source', 'model_id', 'config_id', 'config_version',
    'expected_config_version', 'adapter_id', 'base_url', 'api_key', 'name', 'provider', 'provider_label',
    'model_ids', 'response_model_aliases', 'secret_action', 'is_active', 'destination_consent',
    'accepted', 'destination_digest', 'probe_kind', 'operation_id', 'purpose', 'task_id', 'revision',
    'output_tokens', 'timeout_seconds', 'connect_seconds', 'request_bytes', 'envelope_bytes',
    'text_bytes', 'sse_event_bytes', 'tool_arguments_bytes', 'tool_call_count'})
_DEFAULT_STATUS = {'CUSTOM_MODEL_NOT_FOUND': 404, 'MODEL_CONFIG_STALE': 409,
    'BYOK_STORAGE_UNAVAILABLE': 503, 'BYOK_EGRESS_UNAVAILABLE': 503, 'MODEL_CAPACITY_EXCEEDED': 429,
    'PROBE_RATE_LIMITED': 429, 'PROBE_OPERATION_CONFLICT': 409, 'BODY_TOO_LARGE': 413,
    'PROVIDER_RATE_LIMITED': 429, 'PROVIDER_TIMEOUT': 504, 'PROVIDER_AUTH_FAILED': 502,
    'OUTCOME_UNKNOWN': 503, 'AUTHENTICATED_ACTOR_REQUIRED': 401}


class ByokError(Exception):
    __slots__ = ('_code', '_status_code', '_request_id', '_fields')

    @property
    def code(self):
        return self._code

    @property
    def status_code(self):
        return self._status_code

    @property
    def request_id(self):
        return self._request_id

    @property
    def fields(self):
        return self._fields

    def __init__(self, code: str, status_code: int | None = None, request_id: str | None = None, *, fields: tuple[str, ...] = ()):
        if type(code) is not str or code not in PUBLIC_MESSAGES:
            raise ValueError('invalid controlled error code')
        status_code = _DEFAULT_STATUS.get(code, 400) if status_code is None else status_code
        if type(status_code) is not int or not 400 <= status_code <= 599:
            raise ValueError('invalid controlled HTTP status')
        request_id = uuid4().hex if request_id is None else request_id
        if type(request_id) is not str or re.fullmatch(r'[A-Za-z0-9_-]{1,64}', request_id) is None:
            raise ValueError('invalid opaque request identifier')
        if type(fields) is not tuple or len(fields) > len(SAFE_FIELDS) or any(type(f) is not str or f not in SAFE_FIELDS for f in fields):
            raise ValueError('invalid safe field names')
        self._code, self._status_code, self._request_id = code, status_code, request_id
        self._fields = tuple(dict.fromkeys(fields))
        super().__init__(code)


def public_error(error: BaseException) -> dict:
    if isinstance(error, ValidationError):
        fields = []
        for detail in error.errors(include_input=False, include_url=False, include_context=False):
            for part in detail.get('loc', ()):
                if type(part) is str and part in SAFE_FIELDS and part not in fields:
                    fields.append(part)
        error = ByokError('INVALID_INPUT', fields=tuple(fields))
    if not isinstance(error, ByokError):
        error = ByokError('OUTCOME_UNKNOWN')
    result = {'code': error.code, 'message': PUBLIC_MESSAGES[error.code], 'request_id': error.request_id}
    if error.fields:
        result['fields'] = list(error.fields)
    return result
