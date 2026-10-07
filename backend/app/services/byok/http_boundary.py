"""Manual 16 KiB body cap, duplicate-safe strict JSON, fixed errors only."""
import json
from pydantic import ValidationError
from app.services.byok.errors import ByokError, public_error
from app.services.byok.limits import CAPS, validate_api_body_size


def _pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            raise ValueError('duplicate field')
        result[key] = value
    return result


def _constant(value):
    raise ValueError('invalid JSON constant')


def parse_bounded_json(raw, schema):
    validate_api_body_size(raw)
    try:
        data = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs, parse_constant=_constant)
        if type(data) is not dict:
            raise ValueError('object required')
        return schema.model_validate(data)
    except ValidationError as error:
        safe = public_error(error)
        raise ByokError('INVALID_INPUT', 422, fields=tuple(safe.get('fields', ()))) from None
    except ByokError:
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ByokError('INVALID_INPUT', 422) from None


async def read_bounded_body(request):
    declared = request.headers.get('content-length')
    if declared is not None:
        try:
            if not declared.isascii() or not declared.isdecimal():
                raise ValueError('invalid length')
            if int(declared) > CAPS.api_body_bytes:
                raise ByokError('BODY_TOO_LARGE')
        except ValueError:
            raise ByokError('INVALID_INPUT', 422) from None
    chunks = bytearray()
    async for chunk in request.stream():
        if len(chunks) + len(chunk) > CAPS.api_body_bytes:
            raise ByokError('BODY_TOO_LARGE')
        chunks.extend(chunk)
    return bytes(chunks)


def safe_http_error(error):
    status = error.status_code if isinstance(
        error,
        ByokError
    ) else 422 if isinstance(
        error,
        ValidationError
    ) else 503
    return (status, {'status': 'error', 'error': public_error(error)})


def install_byok_http_boundary(app):
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse

    async def controlled(request, error):
        status, body = safe_http_error(error)
        return JSONResponse(status_code=status, content=body)

    async def validation(request, error):
        if '/user/models' in request.url.path:
            return JSONResponse(
                status_code=422,
                content={'status': 'error', 'error': public_error(ByokError('INVALID_INPUT', 422))}
            )
        from fastapi.exception_handlers import request_validation_exception_handler
        return await request_validation_exception_handler(request, error)
    app.add_middleware(ByokBoundaryMiddleware)
    app.add_exception_handler(ByokError, controlled)
    app.add_exception_handler(ValidationError, controlled)
    app.add_exception_handler(RequestValidationError, validation)


class ByokBoundaryMiddleware:
    """Stop raw exception propagation from BYOK HTTP, including unknown failures.

    Provider/DB/Pydantic exceptions are mapped here rather than reaching the
    server error logger. We never inspect or stringify the original exception.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get('type') != 'http' or not scope.get(
            'path',
            ''
        ).startswith(('/api/user/models', '/user/models')):
            return await self.app(scope, receive, send)
        from app.services.byok.observability import byok_log_context
        started = False

        async def guarded_send(message):
            nonlocal started
            if message['type'] == 'http.response.start':
                started = True
            await send(message)
        with byok_log_context():
            try:
                await self.app(scope, receive, guarded_send)
            except Exception as error:
                if started:
                    # The response cannot be rewritten, but raw exceptions still
                    # must not escape to logging/telemetry. CRUD never streams.
                    return
                status, body = safe_http_error(error)
                await send({
                    'type': 'http.response.start',
                    'status': status,
                    'headers': [(b'content-type', b'application/json')]
                })
                await send({
                    'type': 'http.response.body',
                    'body': json.dumps(body, separators=(',', ':')).encode(),
                    'more_body': False
                })
