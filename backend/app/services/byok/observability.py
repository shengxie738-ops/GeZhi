"""Deny-by-default BYOK/provider logs. New telemetry sinks need acceptance.

No exception/string/body/URL/model/domain is an allowed structured field.
Reverse proxy body logging is outside Python and remains a deployment gate.
"""
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from app.services.byok.errors import PUBLIC_MESSAGES
_IN_BYOK = ContextVar('byok_private_logging', default=False)
_SAFE_LOG_AUTHORITY = object()


@contextmanager
def byok_log_context():
    token = _IN_BYOK.set(True)
    try:
        yield
    finally:
        _IN_BYOK.reset(token)
_ALLOWED = frozenset({
    'request_id',
    'code',
    'adapter_version',
    'duration_ms',
    'http_status',
    'config_id',
    'config_version',
    'call_count'
})
_PREFIXES = (
    'app.services.byok',
    'app.repositories.user_models',
    'app.api.endpoints.user_models',
    'httpx',
    'httpcore',
    'langchain',
    'langchain_core',
    'opentelemetry',
    'sentry_sdk'
)
_STANDARD = frozenset(logging.LogRecord('', 0, '', 0, '', (), None).__dict__) | {'_byok_safe'}


class ByokPrivacyFilter(logging.Filter):

    def filter(self, record):
        if getattr(record, '_byok_safe', None) is not _SAFE_LOG_AUTHORITY:
            return False
        return set(record.__dict__) <= _STANDARD | _ALLOWED and record.exc_info is None and (record.exc_text is None) and (record.args == ())


def safe_log_record(**fields):
    if set(fields) - _ALLOWED:
        raise ValueError('only approved safe log fields are allowed')
    if fields.get('code') not in PUBLIC_MESSAGES:
        raise ValueError('controlled code required')
    for name, value in fields.items():
        if name in {'request_id', 'config_id'}:
            if type(value) is not str or not 1 <= len(value) <= 128 or (not all((c.isascii() and (c.isalnum() or c in '_-') for c in value))):
                raise ValueError('opaque ID required')
        elif name == 'adapter_version':
            if value != '1':
                raise ValueError('approved adapter version required')
        elif name != 'code' and (type(value) is not int or value < 0):
            raise ValueError('safe nonnegative count required')
    record = logging.LogRecord('app.services.byok', logging.INFO, '', 0, fields['code'], (), None)
    record._byok_safe = _SAFE_LOG_AUTHORITY
    for name, value in fields.items():
        setattr(record, name, value)
    return record


def _private_record(record):
    return record.name.startswith(_PREFIXES) or _IN_BYOK.get()


def _redact_untrusted_record(record):
    # Logger.makeRecord merges extra AFTER the factory. Strip every extra field
    # after that merge; an allowlisted-looking raw extra is not approved data.
    for name in tuple(record.__dict__):
        if name not in _STANDARD:
            del record.__dict__[name]
    record._byok_safe = False
    record.name = 'app.services.byok'
    record.msg = 'BYOK_EVENT_REDACTED'
    record.args = ()
    record.exc_info = None
    record.exc_text = None
    record.stack_info = None
    record.pathname = ''
    record.filename = ''
    record.module = ''
    record.funcName = None
    return record


def install_byok_privacy_filters():
    guard = ByokPrivacyFilter()
    for name in _PREFIXES:
        logger = logging.getLogger(name)
        logger.addFilter(guard)
        for handler in logger.handlers:
            handler.addFilter(guard)
    for name, logger in logging.Logger.manager.loggerDict.items():
        if isinstance(logger, logging.Logger) and name.startswith(_PREFIXES):
            logger.addFilter(guard)

    previous_factory = logging.getLogRecordFactory()
    if not getattr(previous_factory, '_byok_privacy', False):
        def factory(*args, **kwargs):
            record = previous_factory(*args, **kwargs)
            return _redact_untrusted_record(record) if _private_record(record) else record
        factory._byok_privacy = True
        logging.setLogRecordFactory(factory)

    previous_make_record = logging.Logger.makeRecord
    if not getattr(previous_make_record, '_byok_privacy', False):
        def make_record(logger, *args, **kwargs):
            record = previous_make_record(logger, *args, **kwargs)
            return _redact_untrusted_record(record) if _private_record(record) else record
        make_record._byok_privacy = True
        logging.Logger.makeRecord = make_record

    previous_handle = logging.Logger.handle
    if not getattr(previous_handle, '_byok_privacy', False):
        def handle(logger, record):
            # This gate precedes the logger's own handlers and root propagation,
            # including loggers/handlers created after installation. Only records
            # from the validated constructor carry server approval authority.
            if _private_record(record) and not guard.filter(record):
                return
            return previous_handle(logger, record)
        handle._byok_privacy = True
        logging.Logger.handle = handle
