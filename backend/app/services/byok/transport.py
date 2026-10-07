"""Per-call, fail-closed HTTPS egress through public HTTPX/httpcore interfaces.

Only the production opener is an application construction path. Its resolver,
public AnyIO dialer and certificate roots are fixed. Constructor dependencies
are seams for offline/controlled tests, never settings, environment or UI flags.
A successful local test is not evidence of provider or deployment compatibility.
"""
from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
import importlib.metadata
import ipaddress
import math
import logging
import socket
import ssl
import threading
import time
from types import MappingProxyType

import anyio
import certifi
import httpcore
import httpx

from app.services.byok.endpoint_policy import NormalizedEndpoint, normalize_endpoint, validate_resolved_addresses
from app.services.byok.errors import ByokError
from app.services.byok.limits import CAPS, ModelCallLimits, check_limit

_STACK = {'httpx': '0.28.1', 'httpcore': '1.0.9', 'anyio': '4.14.2'}


_QUIET_STACK = ContextVar('byok_protected_http_io', default=False)


class _ProtectedLogFilter(logging.Filter):
    def filter(self, record):
        return not _QUIET_STACK.get()


# Known locked-stack logger names. Parent logger filters do not filter child
# records, so attach to emitters too. Other task contexts keep their logging.
for _logger_name in ('httpx', 'httpcore', 'httpcore.connection', 'httpcore.http11',
                     'httpcore.http2', 'httpcore.proxy', 'httpcore.socks'):
    _logger = logging.getLogger(_logger_name)
    if not any(isinstance(f, _ProtectedLogFilter) for f in _logger.filters):
        _logger.addFilter(_ProtectedLogFilter())


@contextmanager
def _quiet_stack():
    token = _QUIET_STACK.set(True)
    try:
        yield
    finally:
        _QUIET_STACK.reset(token)


def _check_stack():
    try:
        if any(importlib.metadata.version(name) != version for name, version in _STACK.items()):
            raise RuntimeError()
        if not all(hasattr(httpcore.AsyncNetworkStream, name) for name in ('read', 'write', 'aclose', 'start_tls', 'get_extra_info')):
            raise RuntimeError()
        if not isinstance(httpcore.AnyIOBackend(), httpcore.AsyncNetworkBackend):
            raise RuntimeError()
    except Exception:
        raise ByokError('BYOK_EGRESS_UNAVAILABLE') from None


def _endpoint(value):
    if not isinstance(value, NormalizedEndpoint) or normalize_endpoint(value.endpoint_url) != value:
        raise ByokError('ENDPOINT_NOT_ALLOWED')
    return value


class _Deadline:
    def __init__(self, deadline, clock=time.monotonic):
        self.clock = clock
        self.last = None
        if type(deadline) not in (int, float) or not math.isfinite(deadline):
            raise ByokError('PROVIDER_TIMEOUT')
        self.deadline = float(deadline)
        self.remaining()

    def now(self):
        now = self.clock()
        if type(now) not in (int, float) or not math.isfinite(now) or (self.last is not None and now < self.last):
            raise ByokError('PROVIDER_TIMEOUT')
        self.last = now
        return now

    def remaining(self, cap=None):
        remaining = self.deadline - self.now()
        if cap is not None:
            if type(cap) not in (int, float) or not math.isfinite(cap) or cap <= 0:
                raise ByokError('PROVIDER_TIMEOUT')
            remaining = min(remaining, cap)
        if remaining <= 0:
            raise ByokError('PROVIDER_TIMEOUT')
        return remaining

    async def call(self, function, *args, cap=None, _check_after=True, **kwargs):
        duration = self.remaining(cap)
        try:
            with anyio.fail_after(duration):
                result = await function(*args, **kwargs)
            if _check_after:
                self.remaining()
            return result
        except TimeoutError:
            raise ByokError('PROVIDER_TIMEOUT') from None

    def cleanup_remaining(self):
        try:
            return max(0, self.deadline - self.now())
        except ByokError:
            return 0


class EgressCapacity:
    """Non-queued process capacity. Only terminal transport close releases it."""
    def __init__(self, maximum=CAPS.egress_active_per_process):
        if type(maximum) is not int or not 1 <= maximum <= CAPS.egress_active_per_process:
            raise ValueError('invalid egress capacity')
        self.maximum = maximum
        self._lock = threading.Lock()
        self._leases = set()

    @property
    def active(self):
        with self._lock:
            return len(self._leases)

    def acquire(self):
        with self._lock:
            if len(self._leases) >= self.maximum:
                raise ByokError('MODEL_CAPACITY_EXCEEDED')
            lease = EgressLease(self, _LEASE_FACTORY)
            self._leases.add(lease)
            return lease


_LEASE_FACTORY = object()


class EgressLease:
    def __init__(self, capacity, token):
        if token is not _LEASE_FACTORY:
            raise TypeError('use the egress capacity boundary')
        self._capacity, self._transport, self._released = capacity, None, False

    def _bind(self, transport):
        with self._capacity._lock:
            if self._released or self not in self._capacity._leases or self._transport is not None:
                raise ByokError('BYOK_EGRESS_UNAVAILABLE')
            self._transport = transport

    def _release(self, transport):
        with self._capacity._lock:
            if self._released:
                return
            if self._transport is not transport:
                raise ByokError('BYOK_EGRESS_UNAVAILABLE')
            self._capacity._leases.remove(self)
            self._released = True
            self._transport = None

    def __repr__(self):
        return '<EgressLease>'


EGRESS_CAPACITY = EgressCapacity()


class PublicResolver:
    """One complete AF_UNSPEC A/AAAA lookup; no address-config filtering."""
    def __init__(self, *, clock=time.monotonic):
        self.clock = clock

    async def resolve(self, host: str, *, deadline: float):
        budget = _Deadline(deadline, self.clock)
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None
        if literal is not None:
            return tuple(ipaddress.ip_address(a) for a in validate_resolved_addresses((str(literal),)))
        try:
            records = await budget.call(anyio.getaddrinfo, host, 443, family=socket.AF_UNSPEC,
                type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP, flags=0)
            values = []
            for family, sock_type, proto, canonical, sockaddr in records:
                if family not in (socket.AF_INET, socket.AF_INET6) or sock_type != socket.SOCK_STREAM:
                    raise ValueError()
                value = ipaddress.ip_address(sockaddr[0])
                if (family == socket.AF_INET) != isinstance(value, ipaddress.IPv4Address):
                    raise ValueError()
                values.append(str(value))
            return tuple(ipaddress.ip_address(a) for a in validate_resolved_addresses(values))
        except ByokError:
            raise
        except Exception:
            raise ByokError('DNS_REJECTED') from None


class NumericDialer:
    """Accept address objects only; public AnyIO gets a canonical numeric string.

    Policy validation belongs to GuardedNetworkBackend. This primitive can be
    tested against loopback without allowing a loopback application endpoint.
    AnyIO's numeric path and native peer metadata need a separate connection gate.
    """
    def __init__(self, *, network_backend=None, clock=time.monotonic):
        _check_stack()
        self._backend = httpcore.AnyIOBackend() if network_backend is None else network_backend
        self.clock = clock

    async def connect(self, address, port: int, *, deadline: float):
        if type(address) not in (ipaddress.IPv4Address, ipaddress.IPv6Address) or type(port) is not int or not 1 <= port <= 65535:
            raise ByokError('BYOK_EGRESS_UNAVAILABLE')
        budget = _Deadline(deadline, self.clock)
        raw = await budget.call(self._backend.connect_tcp, host=str(address), port=port,
            timeout=budget.remaining(), local_address=None, socket_options=None, _check_after=False)
        try:
            budget.remaining()
            return raw
        except BaseException:
            await _close_raw(raw, budget)
            raise


async def _close_raw(stream, budget):
    """Shield cancellation, share the deadline, then force terminal close.

    Expiration never grants new network time. A cancelled close uses AnyIO's
    public force-close contract and a single administrative checkpoint so an
    already scheduled local socket close can run. Unverified closure retains
    capacity; it cannot be converted into a successful release.
    """
    completed = False
    try:
        raw_socket = stream.get_extra_info('socket')
    except Exception:
        raw_socket = None
    with anyio.CancelScope(shield=True):
        try:
            with anyio.move_on_after(budget.cleanup_remaining()) as scope:
                await stream.aclose()
                completed = True
            if scope.cancel_called and not completed:
                class CompletionClose:
                    async def aclose(self):
                        nonlocal completed
                        await stream.aclose()
                        completed = True
                await anyio.aclose_forcefully(CompletionClose())
            if raw_socket is not None and raw_socket.fileno() != -1:
                await anyio.lowlevel.cancel_shielded_checkpoint()
                completed = raw_socket.fileno() == -1
            if not completed:
                raise ByokError('BYOK_EGRESS_UNAVAILABLE')
        except ByokError:
            raise
        except Exception:
            raise ByokError('BYOK_EGRESS_UNAVAILABLE') from None


class _GuardedStream(httpcore.AsyncNetworkStream):
    def __init__(self, stream, endpoint, budget, connect_deadline):
        self._stream, self._endpoint, self._budget = stream, endpoint, budget
        self._connect_deadline = connect_deadline
        self.closed = False
        self._tls = False

    async def aclose(self):
        if not self.closed:
            await _close_raw(self._stream, self._budget)
            self.closed = True

    async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        try:
            if self.closed or self._tls:
                raise ByokError('BYOK_EGRESS_UNAVAILABLE')
            if server_hostname != self._endpoint.host or not ssl_context.check_hostname or ssl_context.verify_mode != ssl.CERT_REQUIRED:
                raise ByokError('TLS_FAILED')
            remaining = self._budget.remaining(min(self._connect_deadline - self._budget.now(), timeout or CAPS.connect_seconds))
            self._stream = await self._budget.call(self._stream.start_tls, ssl_context=ssl_context,
                server_hostname=self._endpoint.host, timeout=remaining, cap=remaining, _check_after=False)
            # The post-return check must include DNS/TCP/TLS's shared connect
            # deadline, even if an injected clock advanced without an await.
            self._budget.remaining(self._connect_deadline - self._budget.now())
            self._tls = True
            return self
        except BaseException as error:
            await self.aclose()
            if isinstance(error, ByokError):
                raise error from None
            if isinstance(error, (TimeoutError, httpcore.TimeoutException)):
                raise ByokError('PROVIDER_TIMEOUT') from None
            if isinstance(error, Exception):
                raise ByokError('TLS_FAILED') from None
            raise

    async def write(self, buffer, timeout=None):
        try:
            if self.closed or not self._tls:
                raise ByokError('BYOK_EGRESS_UNAVAILABLE')
            remaining = self._budget.remaining(timeout)
            await self._budget.call(self._stream.write, buffer, timeout=remaining, cap=remaining)
        except BaseException as error:
            await self.aclose()
            if isinstance(error, ByokError):
                raise error from None
            if isinstance(error, (TimeoutError, httpcore.TimeoutException)):
                raise ByokError('PROVIDER_TIMEOUT') from None
            if isinstance(error, Exception):
                raise ByokError('OUTCOME_UNKNOWN') from None
            raise

    async def read(self, max_bytes, timeout=None):
        try:
            if self.closed or not self._tls:
                raise ByokError('BYOK_EGRESS_UNAVAILABLE')
            remaining = self._budget.remaining(timeout)
            return await self._budget.call(self._stream.read, max_bytes, timeout=remaining, cap=remaining)
        except BaseException as error:
            await self.aclose()
            if isinstance(error, ByokError):
                raise error from None
            if isinstance(error, (TimeoutError, httpcore.TimeoutException)):
                raise ByokError('PROVIDER_TIMEOUT') from None
            if isinstance(error, Exception):
                raise ByokError('OUTCOME_UNKNOWN') from None
            raise

    def get_extra_info(self, info):
        return self._stream.get_extra_info(info)

    def __repr__(self):
        return '<GuardedNetworkStream>'


class GuardedNetworkBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, endpoint: NormalizedEndpoint, *, deadline: float, connect_seconds=CAPS.connect_seconds,
                 resolver=None, dialer=None, clock=time.monotonic):
        self.endpoint = _endpoint(endpoint)
        if type(connect_seconds) not in (int, float) or not math.isfinite(connect_seconds) or not 0 < connect_seconds <= CAPS.connect_seconds:
            raise ByokError('PROVIDER_TIMEOUT')
        self.clock, self._budget = clock, _Deadline(deadline, clock)
        self._connect_seconds = connect_seconds
        self._resolver = PublicResolver(clock=clock) if resolver is None else resolver
        self._dialer = NumericDialer(clock=clock) if dialer is None else dialer
        self._attempted, self._streams = False, []
        self._connecting, self._connect_scope, self._connect_done = False, None, None
        self._closing = False

    async def connect_tcp(self, host, port, timeout, local_address=None, socket_options=None):
        if host != self.endpoint.host or type(port) is not int or port != self.endpoint.port or local_address is not None or socket_options:
            raise ByokError('ENDPOINT_NOT_ALLOWED')
        if self._attempted or self._closing:
            raise ByokError('BYOK_EGRESS_UNAVAILABLE')
        self._attempted = True
        self._connecting = True
        self._connect_done = anyio.Event()
        try:
            with anyio.CancelScope() as scope:
                self._connect_scope = scope
                return await self._connect_validated(host, port, timeout)
            raise ByokError('CANCELLED')
        finally:
            self._connecting = False
            self._connect_done.set()

    async def _connect_validated(self, host, port, timeout):
        connect_deadline = min(self._budget.deadline, self._budget.now() + self._connect_seconds)
        if timeout is not None:
            self._budget.remaining(timeout)
            connect_deadline = min(connect_deadline, self._budget.now() + timeout)
        connect = _Deadline(connect_deadline, self.clock)
        try:
            answers = await connect.call(self._resolver.resolve, host, deadline=connect_deadline)
            if type(answers) is not tuple or any(type(a) not in (ipaddress.IPv4Address, ipaddress.IPv6Address) for a in answers):
                raise ByokError('DNS_REJECTED')
            addresses = tuple(ipaddress.ip_address(a) for a in validate_resolved_addresses(tuple(str(a) for a in answers)))
            for address in addresses:
                connect.remaining()
                try:
                    raw = await connect.call(self._dialer.connect, address, port, deadline=connect_deadline, _check_after=False)
                except (httpcore.ConnectError, httpcore.ConnectTimeout, OSError):
                    connect.remaining()
                    continue
                stream = _GuardedStream(raw, self.endpoint, self._budget, connect_deadline)
                self._streams.append(stream)
                connect.remaining()
                try:
                    peer = raw.get_extra_info('server_addr')
                    if type(peer) is not tuple or len(peer) not in (2, 4) or type(peer[0]) is not str or type(peer[1]) is not int or peer[1] != port:
                        raise ByokError('DNS_REJECTED')
                    peer_address = ipaddress.ip_address(peer[0])
                    validated_peer = validate_resolved_addresses((str(peer_address),))
                    if peer_address not in addresses or not validated_peer:
                        raise ByokError('DNS_REJECTED')
                except (ValueError, TypeError, ByokError):
                    await stream.aclose()
                    raise ByokError('DNS_REJECTED') from None
                return stream
            raise ByokError('BYOK_EGRESS_UNAVAILABLE')
        except BaseException as error:
            await self._close_streams()
            if isinstance(error, ByokError):
                raise
            if isinstance(error, Exception):
                raise ByokError('BYOK_EGRESS_UNAVAILABLE') from None
            raise

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise ByokError('BYOK_EGRESS_UNAVAILABLE')

    async def sleep(self, seconds):
        raise ByokError('BYOK_EGRESS_UNAVAILABLE')

    async def _close_streams(self):
        for stream in self._streams:
            await stream.aclose()

    async def aclose(self):
        self._closing = True
        with anyio.CancelScope(shield=True):
            if self._connecting:
                self._connect_scope.cancel()
                with anyio.move_on_after(self._budget.cleanup_remaining()):
                    await self._connect_done.wait()
                if self._connecting:
                    await anyio.lowlevel.cancel_shielded_checkpoint()
                if self._connecting:
                    raise ByokError('BYOK_EGRESS_UNAVAILABLE')
            await self._close_streams()

    @property
    def terminal(self):
        return not self._connecting and all(stream.closed for stream in self._streams)


class _ResponseStream(httpx.AsyncByteStream):
    def __init__(self, stream, transport):
        self._stream, self._transport = stream, transport
        self._closed = False

    async def __aiter__(self):
        total = 0
        iterator = self._stream.__aiter__()
        try:
            while True:
                try:
                    with _quiet_stack():
                        part = await self._transport._budget.call(iterator.__anext__)
                except StopAsyncIteration:
                    break
                total += len(part)
                check_limit('envelope_bytes', total, self._transport.limits)
                yield part
        except BaseException as error:
            if isinstance(error, (ByokError, anyio.get_cancelled_exc_class())):
                raise
            if isinstance(error, httpcore.TimeoutException):
                raise ByokError('PROVIDER_TIMEOUT') from None
            if isinstance(error, Exception):
                raise ByokError('OUTCOME_UNKNOWN') from None
            raise
        finally:
            try:
                with _quiet_stack(), anyio.CancelScope(shield=True):
                    await iterator.aclose()
            finally:
                await self.aclose()

    async def aclose(self):
        if not self._closed:
            # The pool stream removes its request and closes idle connections.
            # Even if that close fails, transport tracks the actual raw streams.
            try:
                with _quiet_stack(), anyio.CancelScope(shield=True):
                    await self._stream.aclose()
            finally:
                await self._transport.aclose()
            self._closed = True


async def _close_owned_request_body(iterator, stream, budget):
    """Close both public owned resources without extending the call deadline.

    A returned aclose verifies its declared ownership contract, not hostile
    Python object internals. Failure is reported safely; provider transport
    closure and its egress lease remain a separate actual-network fact.
    """
    failed = False
    seen = set()
    with anyio.CancelScope(shield=True):
        for resource in (iterator, stream):
            if id(resource) in seen:
                continue
            seen.add(id(resource))
            close = getattr(resource, 'aclose', None)
            if close is None:
                continue  # An explicit stream owner must close its iterator.
            completed = False
            try:
                with anyio.move_on_after(budget.cleanup_remaining()) as scope:
                    await close()
                    completed = True
                if scope.cancel_called and not completed:
                    class CompletionClose:
                        async def aclose(self):
                            nonlocal completed
                            await close()
                            completed = True
                    await anyio.aclose_forcefully(CompletionClose())
            except Exception:
                failed = True
            if not completed:
                failed = True
        if failed:
            raise ByokError('BYOK_EGRESS_UNAVAILABLE')


class ProtectedTransport(httpx.AsyncBaseTransport):
    pool_policy = MappingProxyType({'max_connections': 1, 'max_keepalive_connections': 0, 'http1': True,
        'http2': False, 'retries': 0, 'proxy': None, 'uds': None})

    def __init__(self, endpoint: NormalizedEndpoint, limits: ModelCallLimits, *, deadline, egress_lease,
                 network_backend=None, ssl_context_factory=None, clock=time.monotonic):
        _check_stack()
        self.endpoint, self.limits = _endpoint(endpoint), limits
        if not isinstance(limits, ModelCallLimits) or not isinstance(egress_lease, EgressLease):
            raise ByokError('BYOK_EGRESS_UNAVAILABLE')
        self._budget = _Deadline(deadline, clock)
        self._budget.deadline = min(self._budget.deadline, self._budget.now() + limits.timeout_seconds)
        self._backend = GuardedNetworkBackend(endpoint, deadline=self._budget.deadline,
            connect_seconds=limits.connect_seconds, clock=clock) if network_backend is None else network_backend
        if not isinstance(self._backend, GuardedNetworkBackend) or self._backend.endpoint != endpoint:
            raise ByokError('BYOK_EGRESS_UNAVAILABLE')
        self._backend._budget.deadline = min(self._backend._budget.deadline, self._budget.deadline)
        self._budget = self._backend._budget
        # Explicit certifi roots ignore SSL_CERT_FILE/SSL_CERT_DIR and trust_env.
        context = ssl.create_default_context(cafile=certifi.where()) if ssl_context_factory is None else ssl_context_factory()
        if not context.check_hostname or context.verify_mode != ssl.CERT_REQUIRED:
            raise ByokError('TLS_FAILED')
        self._pool = httpcore.AsyncConnectionPool(ssl_context=context, max_connections=1, max_keepalive_connections=0,
            keepalive_expiry=0, http1=True, http2=False, retries=0, proxy=None, uds=None, local_address=None,
            network_backend=self._backend)
        self._lease, self._claimed, self._closed = egress_lease, False, False
        self._lease._bind(self)

    async def handle_async_request(self, request):
        with _quiet_stack():
            return await self._handle_async_request(request)

    async def _handle_async_request(self, request):
        if str(request.url) != self.endpoint.endpoint_url or request.method != 'POST':
            raise ByokError('ENDPOINT_NOT_ALLOWED')
        if self._claimed or self._closed:
            raise ByokError('BYOK_EGRESS_UNAVAILABLE')
        self._claimed = True
        try:
            if not isinstance(request.stream, httpx.AsyncByteStream):
                raise ByokError('BYOK_EGRESS_UNAVAILABLE')
            # Production adapters supply bounded serialized JSON bytes. An
            # immutable public ByteStream is owned; other streams must expose
            # their own public aclose contract. HTTPX's content=async-producer
            # wrapper inherits a no-op aclose and hides its original producer.
            # Reject it before creating/advancing an iterator; do not unwrap it.
            if type(request.stream) is not httpx.ByteStream and type(request.stream).aclose is httpx.AsyncByteStream.aclose:
                raise ByokError('BYOK_EGRESS_UNAVAILABLE')
            # Bound and close the complete constructed request before any dial.
            content = bytearray()
            iterator = None
            try:
                iterator = request.stream.__aiter__()
                while True:
                    try:
                        part = await self._budget.call(iterator.__anext__)
                    except StopAsyncIteration:
                        break
                    content.extend(part)
                    check_limit('request_bytes', len(content), self.limits)
            finally:
                await _close_owned_request_body(iterator, request.stream, self._budget)
            if self._closed:
                raise ByokError('BYOK_EGRESS_UNAVAILABLE')
            headers = [(k, v) for k, v in request.headers.raw if k.lower() not in (b'host', b'accept-encoding')]
            host = self.endpoint.host
            headers += [(b'Host', ('[' + host + ']' if ':' in host else host).encode('ascii')), (b'Accept-Encoding', b'identity')]
            remaining = self._budget.remaining()
            # Do not forward caller trace/SNI/timeouts or any arbitrary extensions.
            core_request = httpcore.Request(method=request.method,
                url=httpcore.URL(scheme=request.url.raw_scheme, host=request.url.raw_host,
                    port=request.url.port, target=request.url.raw_path),
                headers=headers, content=bytes(content), extensions={'timeout': {
                    'connect': min(remaining, self.limits.connect_seconds), 'read': remaining,
                    'write': remaining, 'pool': remaining}})
            response = await self._budget.call(self._pool.handle_async_request, core_request)
            if 300 <= response.status <= 399:
                await response.aclose()
                raise ByokError('PROVIDER_REDIRECT_REJECTED')
            encodings = [v.strip().lower() for k, v in response.headers if k.lower() == b'content-encoding']
            if any(value not in (b'', b'identity') for value in encodings):
                await response.aclose()
                raise ByokError('PROVIDER_INVALID_RESPONSE')
            lengths = [v for k, v in response.headers if k.lower() == b'content-length']
            if lengths:
                try:
                    if len(set(lengths)) != 1 or not lengths[0].isdigit():
                        raise ValueError()
                    check_limit('envelope_bytes', int(lengths[0]), self.limits)
                except ValueError:
                    raise ByokError('PROVIDER_INVALID_RESPONSE') from None
            return httpx.Response(status_code=response.status, headers=response.headers,
                stream=_ResponseStream(response.stream, self), extensions={
                    k: v for k, v in response.extensions.items() if k in ('http_version', 'reason_phrase')})
        except BaseException as error:
            await self.aclose()
            if isinstance(error, (ByokError, anyio.get_cancelled_exc_class())):
                raise
            if isinstance(error, (TimeoutError, httpcore.TimeoutException)):
                raise ByokError('PROVIDER_TIMEOUT') from None
            if isinstance(error, Exception):
                raise ByokError('OUTCOME_UNKNOWN') from None
            raise

    async def aclose(self):
        if self._closed:
            return
        with _quiet_stack(), anyio.CancelScope(shield=True):
            try:
                await self._pool.aclose()
            finally:
                await self._backend.aclose()
            if not self._backend.terminal:
                raise ByokError('BYOK_EGRESS_UNAVAILABLE')
            self._closed = True
            self._lease._release(self)

    def __repr__(self):
        return '<ProtectedTransport>'


@asynccontextmanager
async def open_protected_client(endpoint: NormalizedEndpoint, limits: ModelCallLimits, *, deadline, egress_lease):
    """Fixed production construction. The caller reserves process egress first."""
    transport = None
    try:
        if not isinstance(egress_lease, EgressLease) or egress_lease._capacity is not EGRESS_CAPACITY:
            raise ByokError('BYOK_EGRESS_UNAVAILABLE')
        transport = ProtectedTransport(endpoint, limits, deadline=deadline, egress_lease=egress_lease)
        with _quiet_stack():
            async with httpx.AsyncClient(transport=transport, trust_env=False, follow_redirects=False,
                    http1=True, http2=False, timeout=None, headers={'Accept-Encoding': 'identity'}) as client:
                yield client
    finally:
        if transport is not None:
            await transport.aclose()
        elif isinstance(egress_lease, EgressLease) and egress_lease._transport is None:
            # Construction failed before any possible dial; no actual socket exists.
            egress_lease._release(None)
