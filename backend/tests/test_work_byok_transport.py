"""Socket-fenced Task 3 tests: real guard/HTTP core; synthetic streams only.

The event loop below has no self-pipe; no socket audit fence is weakened.
Actual sockets/TLS have their separate explicitly authorized harness.
"""
import asyncio
import importlib
import ipaddress
import math
from pathlib import Path
import ssl
from unittest.mock import Mock

import anyio
import httpcore
import httpx
import pytest
from work_byok_offline import FakeClock

ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ipaddress.ip_address('9.9.9.9')
PUBLIC2 = ipaddress.ip_address('8.8.8.8')
HOST = 'provider.example'


def feature():
    assert (ROOT / 'backend/app/services/byok/transport.py').is_file(), 'Task 3 protected transport missing'
    return importlib.import_module('app.services.byok.transport')


class SocketlessLoop(asyncio.SelectorEventLoop):
    def _make_self_pipe(self):
        pass
    def _close_self_pipe(self):
        pass
    def _write_to_self(self):
        pass


def run(coro):
    loop = SocketlessLoop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
        asyncio.set_event_loop(None)


class Resolver:
    def __init__(self, *answers, clock=None, delay=0):
        self.answers = answers or ((PUBLIC,),)
        self.hostname_lookup_count = 0
        self.deadlines = []
        self.clock, self.delay = clock, delay
    async def resolve(self, host, *, deadline):
        assert host == HOST
        self.deadlines.append(deadline)
        self.hostname_lookup_count += 1
        if self.clock:
            self.clock.advance(self.delay)
        return self.answers[min(self.hostname_lookup_count - 1, len(self.answers) - 1)]


class Stream(httpcore.AsyncNetworkStream):
    def __init__(self, peer=(str(PUBLIC), 443), response=None, clock=None, read_delay=0, fail_write=False, fail_tls=False):
        self.peer = peer
        self.response = response if response is not None else b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}'
        self.clock, self.read_delay = clock, read_delay
        self.fail_write, self.fail_tls = fail_write, fail_tls
        self.http_write_count = self.tls_count = self.close_count = 0
        self.writes, self.timeouts, self.sni = [], [], []
        self.closed = False
        self.close_error = False
        self.close_gate = None
        self.close_started = None
    async def read(self, max_bytes, timeout=None):
        self.timeouts.append(timeout)
        if self.clock:
            self.clock.advance(self.read_delay)
        result, self.response = self.response[:max_bytes], self.response[max_bytes:]
        return result
    async def write(self, buffer, timeout=None):
        assert not self.closed
        self.timeouts.append(timeout)
        if buffer:
            self.http_write_count += 1
            self.writes.append(buffer)
        if self.fail_write:
            raise httpcore.WriteError('SYNTHETIC-RAW-KEY-must-not-leak')
    async def aclose(self):
        self.close_count += 1
        if self.close_started:
            self.close_started.set()
        if self.close_gate and not self.close_gate.is_set():
            await self.close_gate.wait()
        if self.close_error:
            raise RuntimeError('SYNTHETIC-RAW-KEY-close-error')
        self.closed = True
    async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        self.tls_count += 1
        self.sni.append(server_hostname)
        assert ssl_context.check_hostname and ssl_context.verify_mode == ssl.CERT_REQUIRED
        self.timeouts.append(timeout)
        if self.fail_tls:
            raise httpcore.ConnectError('SYNTHETIC-TLS-RAW-KEY')
        return self
    def get_extra_info(self, name):
        if name == 'server_addr':
            return self.peer
        return None


class Dialer:
    def __init__(self, *streams, clock=None, delay=0):
        self.streams = list(streams or (Stream(),))
        self.received_addresses, self.deadlines = [], []
        self.clock, self.delay = clock, delay
    async def connect(self, address, port, *, deadline):
        assert type(address) in (ipaddress.IPv4Address, ipaddress.IPv6Address)
        assert port == 443
        self.received_addresses.append(address)
        self.deadlines.append(deadline)
        if self.clock:
            self.clock.advance(self.delay)
        result = self.streams.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def endpoint():
    return importlib.import_module('app.services.byok.endpoint_policy').normalize_endpoint('https://' + HOST + '/v1')


def limits():
    return importlib.import_module('app.services.byok.limits').WorkCallBudget.student(clock=FakeClock()).reserve('student_chat', 32)


def backend(m, resolver=None, dialer=None, clock=None, deadline=30):
    return m.GuardedNetworkBackend(endpoint(), deadline=deadline, connect_seconds=5,
        resolver=resolver or Resolver(), dialer=dialer or Dialer(), clock=clock or FakeClock())


def transport(m, b, lease=None, clock=None, deadline=30):
    return m.ProtectedTransport(endpoint(), limits(), deadline=deadline,
        egress_lease=lease or m.EgressCapacity().acquire(), network_backend=b, clock=clock or b.clock)


def rejected(code):
    return pytest.raises(importlib.import_module('app.services.byok.errors').ByokError, match='^' + code + '$')


@pytest.mark.parametrize('values', [(), ('10.1.2.3',), ('127.0.0.1',), ('100.64.0.1',), ('192.0.2.1',),
    ('::ffff:9.9.9.9',), ('fd00::1',), ('fe80::1',), ('2001:db8::1',), ('224.1.1.1',), ('::',),
    ('9.9.9.9', '192.168.1.1'), ('9.9.9.9', 'fd00::1'), tuple('11.0.0.' + str(i) for i in range(1, 18))])
def test_all_dns_answers_and_numeric_only_dial(values):
    m = feature()
    resolver = Resolver(tuple(ipaddress.ip_address(v) for v in values))
    d = Dialer()
    with rejected('DNS_REJECTED'):
        run(backend(m, resolver, d).connect_tcp(HOST, 443, 5))
    assert d.received_addresses == []
    assert resolver.hostname_lookup_count == 1


def test_all_dns_answers_numeric_validated_full_set_and_deduplicated():
    m = feature()
    values = tuple(ipaddress.ip_address('11.0.0.' + str(i)) for i in range(1, 17))
    resolver = Resolver(values + (values[0],))
    streams = [httpcore.ConnectError('synthetic-connect-failure') for _ in values[:-1]] + [Stream(peer=(str(values[-1]), 443))]
    d = Dialer(*streams)
    b = backend(m, resolver, d)
    async def exercise():
        s = await b.connect_tcp(HOST, 443, 5)
        await s.aclose()
    run(exercise())
    assert d.received_addresses == list(values)
    assert resolver.hostname_lookup_count == 1


def test_rebinding_does_not_resolve_hostname_twice():
    m = feature()
    resolver = Resolver((PUBLIC,), (ipaddress.ip_address('127.0.0.1'),))
    d = Dialer()
    b = backend(m, resolver, d)
    async def exercise():
        s = await b.connect_tcp(HOST, 443, 5)
        with rejected('BYOK_EGRESS_UNAVAILABLE'):
            await b.connect_tcp(HOST, 443, 5)
        await s.aclose()
    run(exercise())
    assert resolver.hostname_lookup_count == 1
    assert d.received_addresses == [PUBLIC]


@pytest.mark.parametrize('peer', [(str(PUBLIC2), 443), ('127.0.0.1', 443), None, (), (str(PUBLIC), 8443), ('bad', 443)])
def test_peer_mismatch_closes_before_tls_and_http(peer):
    m = feature()
    raw = Stream(peer=peer)
    with rejected('DNS_REJECTED'):
        run(backend(m, dialer=Dialer(raw)).connect_tcp(HOST, 443, 5))
    assert raw.closed
    assert raw.tls_count == 0
    assert raw.http_write_count == 0


def test_original_sni_cert_host_no_proxy_redirect(monkeypatch):
    m = feature()
    monkeypatch.setenv('HTTPS_PROXY', 'http://127.0.0.1:8888')
    monkeypatch.setenv('ALL_PROXY', 'http://127.0.0.1:9999')
    raw = Stream()
    resolver, d = Resolver((PUBLIC,)), Dialer(raw)
    t = transport(m, backend(m, resolver, d))
    trace = Mock()
    async def exercise():
        async with httpx.AsyncClient(transport=t, trust_env=False, follow_redirects=False) as client:
            response = await client.post(endpoint().endpoint_url, headers={'Host': 'evil.example', 'Accept-Encoding': 'gzip'}, content=b'{}',
                extensions={'sni_hostname': 'evil.example', 'trace': trace, 'timeout': {'connect': 999, 'read': 999}})
            assert response.status_code == 200
            assert response.content == b'{}'
    run(exercise())
    wire = b''.join(raw.writes)
    assert b'Host: ' + HOST.encode() in wire
    assert b'evil.example' not in wire
    assert b'Accept-Encoding: identity' in wire
    assert raw.sni == [HOST]
    assert resolver.hostname_lookup_count == 1
    assert d.received_addresses == [PUBLIC]
    assert raw.closed
    assert trace.call_count == 0
    assert t.pool_policy == {'max_connections': 1, 'max_keepalive_connections': 0, 'http1': True, 'http2': False,
        'retries': 0, 'proxy': None, 'uds': None}


@pytest.mark.parametrize('status', [301, 302, 303, 307, 308])
def test_redirect_is_closed_and_never_followed_even_same_host(status):
    m = feature()
    raw = Stream(response=f'HTTP/1.1 {status} Redirect\r\nLocation: https://{HOST}/v1/chat/completions\r\nContent-Length: 999\r\n\r\n'.encode())
    d = Dialer(raw)
    t = transport(m, backend(m, dialer=d))
    async def exercise():
        async with httpx.AsyncClient(transport=t, trust_env=False, follow_redirects=True) as client:
            with rejected('PROVIDER_REDIRECT_REJECTED'):
                await client.post(endpoint().endpoint_url, content=b'{}')
    run(exercise())
    assert raw.closed
    assert d.received_addresses == [PUBLIC]
    assert sum(w.startswith(b'POST ') for w in raw.writes) == 1


@pytest.mark.parametrize('kind', ['write', 'tls', 'read'])
def test_failures_never_reconnect_or_expose_raw_errors(kind):
    m = feature()
    raw = Stream(fail_write=kind == 'write', fail_tls=kind == 'tls', response=b'broken' if kind == 'read' else None)
    d = Dialer(raw, Stream())
    t = transport(m, backend(m, dialer=d))
    async def exercise():
        async with httpx.AsyncClient(transport=t, trust_env=False) as client:
            with rejected('TLS_FAILED' if kind == 'tls' else 'OUTCOME_UNKNOWN') as error:
                await client.post(endpoint().endpoint_url, content=b'{}')
            assert 'SYNTHETIC' not in str(error.value)
    run(exercise())
    assert d.received_addresses == [PUBLIC]
    assert raw.closed


@pytest.mark.parametrize('stage', ['dns', 'tcp', 'body'])
def test_deadline_shared_across_dns_tcp_tls_send_body_cleanup(stage):
    m = feature()
    clock = FakeClock()
    raw = Stream(clock=clock, read_delay=31 if stage == 'body' else 0)
    resolver = Resolver(clock=clock, delay=5 if stage == 'dns' else 0)
    d = Dialer(raw, clock=clock, delay=5 if stage == 'tcp' else 0)
    b = backend(m, resolver, d, clock)
    t = transport(m, b, clock=clock)
    async def exercise():
        async with httpx.AsyncClient(transport=t, trust_env=False) as client:
            with rejected('PROVIDER_TIMEOUT'):
                await client.post(endpoint().endpoint_url, content=b'{}')
    run(exercise())
    assert resolver.deadlines == [5]
    if stage != 'dns':
        assert d.deadlines == [5]
        assert raw.closed
    else:
        assert d.received_addresses == []


def test_remaining_deadline_never_resets_between_reads_or_caller_delay():
    m = feature()
    clock = FakeClock()
    raw = Stream()
    b = backend(m, dialer=Dialer(raw), clock=clock, deadline=4)
    async def exercise():
        s = await b.connect_tcp(HOST, 443, 5)
        await s.start_tls(ssl.create_default_context(), HOST, 50)
        await s.write(b'first', 50)
        clock.advance(3)
        await s.read(1, 50)
        clock.advance(1)
        with rejected('PROVIDER_TIMEOUT'):
            await s.read(1, 50)
        await s.aclose()
    run(exercise())
    assert raw.timeouts == [4, 4, 1]
    assert raw.closed


@pytest.mark.parametrize('deadline', [float('nan'), float('inf'), -1, True])
def test_invalid_or_expired_deadlines_fail_before_dns(deadline):
    m = feature()
    r, d = Resolver(), Dialer()
    with rejected('PROVIDER_TIMEOUT'):
        b = backend(m, r, d, deadline=deadline)
        run(b.connect_tcp(HOST, 443, 5))
    assert r.hostname_lookup_count == 0
    assert d.received_addresses == []


def test_four_egress_leases_no_queue_and_release_after_actual_close():
    m = feature()
    cap = m.EgressCapacity()
    leases = [cap.acquire() for _ in range(4)]
    with rejected('MODEL_CAPACITY_EXCEEDED'):
        cap.acquire()
    raw = Stream()
    b = backend(m, dialer=Dialer(raw))
    t = transport(m, b, lease=leases[0])
    async def exercise():
        raw.close_gate, raw.close_started = anyio.Event(), anyio.Event()
        async with httpx.AsyncClient(transport=t, trust_env=False) as client:
            async with client.stream('POST', endpoint().endpoint_url, content=b'{}') as response:
                assert response.status_code == 200
                async with anyio.create_task_group() as tg:
                    tg.start_soon(response.aclose)
                    await raw.close_started.wait()
                    assert cap.active == 4
                    with rejected('MODEL_CAPACITY_EXCEEDED'):
                        cap.acquire()
                    raw.close_gate.set()
        assert raw.closed
        assert cap.active == 3
    run(exercise())
    replacement = cap.acquire()
    assert cap.active == 4
    assert replacement is not leases[0]


def test_failed_close_retains_lease_and_can_be_retried():
    m = feature()
    cap = m.EgressCapacity()
    lease = cap.acquire()
    raw = Stream()
    raw.close_error = True
    b = backend(m, dialer=Dialer(raw))
    t = transport(m, b, lease)
    async def exercise():
        await b.connect_tcp(HOST, 443, 5)
        with rejected('BYOK_EGRESS_UNAVAILABLE'):
            await t.aclose()
        assert cap.active == 1
        assert not raw.closed
        raw.close_error = False
        await t.aclose()
        assert cap.active == 0
    run(exercise())


def test_cancel_closes_provider_stream_before_releasing_capacity():
    m = feature()
    cap = m.EgressCapacity()
    raw = Stream()
    b = backend(m, dialer=Dialer(raw))
    t = transport(m, b, cap.acquire())
    async def exercise():
        await b.connect_tcp(HOST, 443, 5)
        with anyio.CancelScope() as scope:
            scope.cancel()
            await t.aclose()
        assert raw.closed
        assert cap.active == 0
    run(exercise())


def test_request_single_use_origin_fence_and_unix_options_are_rejected():
    m = feature()
    raw = Stream()
    b = backend(m, dialer=Dialer(raw))
    t = transport(m, b)
    async def exercise():
        with rejected('ENDPOINT_NOT_ALLOWED'):
            await b.connect_tcp('evil.example', 443, 5)
        with rejected('ENDPOINT_NOT_ALLOWED'):
            await b.connect_tcp(HOST, 443, 5, local_address='127.0.0.1')
        with rejected('ENDPOINT_NOT_ALLOWED'):
            await b.connect_tcp(HOST, 443, 5, socket_options=[(1, 2, 3)])
        with rejected('BYOK_EGRESS_UNAVAILABLE'):
            await b.connect_unix_socket('/synthetic.sock', 5)
        async with httpx.AsyncClient(transport=t, trust_env=False) as client:
            with rejected('ENDPOINT_NOT_ALLOWED'):
                await client.post('https://evil.example/v1/chat/completions', content=b'{}')
            assert raw.http_write_count == 0
            await client.post(endpoint().endpoint_url, content=b'{}')
            with rejected('BYOK_EGRESS_UNAVAILABLE'):
                await client.post(endpoint().endpoint_url, content=b'{}')
    run(exercise())
    assert raw.closed


@pytest.mark.parametrize('encoding', ['gzip', 'br', 'deflate', 'identity, gzip'])
def test_nonidentity_encoding_rejected_before_body_iteration(encoding):
    m = feature()
    raw = Stream(response=('HTTP/1.1 200 OK\r\nContent-Encoding: ' + encoding + '\r\nContent-Length: 999\r\n\r\n').encode())
    t = transport(m, backend(m, dialer=Dialer(raw)))
    async def exercise():
        async with httpx.AsyncClient(transport=t, trust_env=False) as client:
            with rejected('PROVIDER_INVALID_RESPONSE'):
                await client.post(endpoint().endpoint_url, content=b'{}')
    run(exercise())
    assert raw.closed


def test_actual_raw_envelope_limit_counts_chunked_not_just_content_length():
    m = feature()
    raw = Stream(response=b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n40001\r\n' + b'x' * (256 * 1024 + 1) + b'\r\n0\r\n\r\n')
    t = transport(m, backend(m, dialer=Dialer(raw)))
    async def exercise():
        async with httpx.AsyncClient(transport=t, trust_env=False) as client:
            with rejected('MODEL_BUDGET_EXCEEDED'):
                await client.post(endpoint().endpoint_url, content=b'{}')
    run(exercise())
    assert raw.closed


def test_production_opener_has_fixed_safe_stack_and_releases_unused_lease(monkeypatch):
    m = feature()
    cap = m.EGRESS_CAPACITY
    async def exercise():
        async with m.open_protected_client(endpoint(), limits(), deadline=__import__('time').monotonic() + 30,
                egress_lease=cap.acquire()) as client:
            assert client.trust_env is False
            assert client.follow_redirects is False
            assert client.headers['accept-encoding'] == 'identity'
            assert isinstance(client._transport, m.ProtectedTransport)
        assert cap.active == 0
    run(exercise())


def test_numeric_dialer_refuses_hostnames_and_versions_fail_closed(monkeypatch):
    m = feature()
    async def exercise():
        with rejected('BYOK_EGRESS_UNAVAILABLE'):
            await m.NumericDialer().connect(HOST, 443, deadline=30)
    run(exercise())
    monkeypatch.setattr(m.importlib.metadata, 'version', lambda name: '999.0')
    with rejected('BYOK_EGRESS_UNAVAILABLE'):
        m.NumericDialer()


def test_closing_during_pending_dial_never_releases_capacity_early():
    m = feature()
    cap = m.EgressCapacity()
    raw = Stream()
    started = None
    class PendingDialer(Dialer):
        async def connect(self, address, port, *, deadline):
            started.set()
            await anyio.sleep_forever()
    b = backend(m, dialer=PendingDialer(raw))
    t = transport(m, b, cap.acquire())
    async def exercise():
        nonlocal started
        started = anyio.Event()
        async def connect():
            with rejected('CANCELLED'):
                await b.connect_tcp(HOST, 443, 5)
        async with anyio.create_task_group() as tg:
            tg.start_soon(connect)
            await started.wait()
            await t.aclose()
            assert b.terminal
            assert cap.active == 0
    run(exercise())


def test_production_opener_requires_shared_process_capacity():
    m = feature()
    cap = m.EgressCapacity()
    async def exercise():
        with rejected('BYOK_EGRESS_UNAVAILABLE'):
            async with m.open_protected_client(endpoint(), limits(), deadline=__import__('time').monotonic() + 30,
                    egress_lease=cap.acquire()):
                raise AssertionError('independent capacity bypassed process cap')
        assert cap.active == 0
    run(exercise())


def test_pool_flags_are_passed_to_actual_public_pool(monkeypatch):
    m = feature()
    real_pool = httpcore.AsyncConnectionPool
    received = []
    def pool(**kwargs):
        received.append(kwargs)
        return real_pool(**kwargs)
    monkeypatch.setattr(httpcore, 'AsyncConnectionPool', pool)
    t = transport(m, backend(m))
    run(t.aclose())
    for name, value in t.pool_policy.items():
        assert received[0][name] == value
    assert received[0]['network_backend'] is t._backend
    assert received[0]['local_address'] is None


def test_read_after_close_is_unavailable_without_raw_read():
    m = feature()
    raw = Stream()
    async def exercise():
        s = await backend(m, dialer=Dialer(raw)).connect_tcp(HOST, 443, 5)
        await s.aclose()
        with rejected('BYOK_EGRESS_UNAVAILABLE'):
            await s.read(1)
    run(exercise())
    assert raw.timeouts == []


def test_httpcore_logs_and_callbacks_never_receive_synthetic_key_or_provider_body(caplog):
    import logging
    m = feature()
    sentinel = 'SYNTHETIC-RAW-KEY-provider-echo'
    raw = Stream(response=('HTTP/1.1 ' + sentinel + '\r\n\r\n').encode())
    t = transport(m, backend(m, dialer=Dialer(raw)))
    caplog.set_level(logging.DEBUG, logger='httpcore')
    caplog.set_level(logging.DEBUG, logger='httpx')
    async def exercise():
        async with httpx.AsyncClient(transport=t, trust_env=False) as client:
            with rejected('OUTCOME_UNKNOWN'):
                await client.post(endpoint().endpoint_url, content=b'{}', headers={'Authorization': 'Bearer ' + sentinel})
    run(exercise())
    assert sentinel not in caplog.text
    assert 'provider.example' not in caplog.text


def test_pending_cleanup_expired_deadline_retains_capacity_until_verified_close():
    m = feature()
    cap = m.EgressCapacity()
    clock = FakeClock()
    raw = Stream()
    b = backend(m, dialer=Dialer(raw), clock=clock)
    t = transport(m, b, cap.acquire(), clock=clock)
    async def exercise():
        raw.close_gate = anyio.Event()
        await b.connect_tcp(HOST, 443, 5)
        clock.advance(30)
        with rejected('BYOK_EGRESS_UNAVAILABLE'):
            await t.aclose()
        assert cap.active == 1 and not b.terminal
        raw.close_gate.set()
        await t.aclose()
        assert cap.active == 0 and raw.closed
    run(exercise())


def test_peer_metadata_exception_is_safe_and_actual_stream_closes():
    m = feature()
    class BadMetadata(Stream):
        def get_extra_info(self, name):
            if name == 'server_addr':
                raise RuntimeError('SYNTHETIC-RAW-KEY-metadata')
            return super().get_extra_info(name)
    raw = BadMetadata()
    with rejected('BYOK_EGRESS_UNAVAILABLE'):
        run(backend(m, dialer=Dialer(raw)).connect_tcp(HOST, 443, 5))
    assert raw.closed and raw.tls_count == 0 and raw.http_write_count == 0


def test_released_egress_lease_does_not_retain_transport_or_request():
    m = feature()
    lease = m.EgressCapacity().acquire()
    t = transport(m, backend(m), lease)
    run(t.aclose())
    assert lease._transport is None


def test_public_resolver_complete_a_aaaa_and_numeric_literal(monkeypatch):
    m = feature()
    received = []
    async def lookup(host, port, **kwargs):
        received.append((host, port, kwargs))
        return [(2, 1, 6, '', ('9.9.9.9', 443)), (10, 1, 6, '', ('2606:4700:4700::1111', 443, 0, 0))]
    monkeypatch.setattr(anyio, 'getaddrinfo', lookup)
    async def exercise():
        r = m.PublicResolver(clock=FakeClock())
        addresses = await r.resolve(HOST, deadline=5)
        assert addresses == (PUBLIC, ipaddress.ip_address('2606:4700:4700::1111'))
        assert await r.resolve(str(PUBLIC), deadline=5) == (PUBLIC,)
    run(exercise())
    assert len(received) == 1
    assert received[0][2]['family'] == 0 and received[0][2]['flags'] == 0


@pytest.mark.parametrize('family,address', [(2, 'fd00::1'), (10, '9.9.9.9'), (0, '9.9.9.9'), (2, '10.0.0.1')])
def test_public_resolver_never_filters_unsafe_or_unclassifiable_records(monkeypatch, family, address):
    m = feature()
    async def lookup(*args, **kwargs):
        return [(2, 1, 6, '', ('9.9.9.9', 443)), (family, 1, 6, '', (address, 443))]
    monkeypatch.setattr(anyio, 'getaddrinfo', lookup)
    with rejected('DNS_REJECTED'):
        run(m.PublicResolver(clock=FakeClock()).resolve(HOST, deadline=5))


def test_oversized_request_is_rejected_before_resolution_or_http_write():
    m = feature()
    r, d = Resolver(), Dialer()
    t = transport(m, backend(m, r, d))
    async def exercise():
        async with httpx.AsyncClient(transport=t, trust_env=False) as client:
            with rejected('MODEL_BUDGET_EXCEEDED'):
                await client.post(endpoint().endpoint_url, content=b'x' * (128 * 1024 + 1))
    run(exercise())
    assert r.hostname_lookup_count == 0 and d.received_addresses == []


def test_insecure_test_context_is_rejected_without_any_network():
    m = feature()
    def insecure():
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    with rejected('TLS_FAILED'):
        m.ProtectedTransport(endpoint(), limits(), deadline=30, egress_lease=m.EgressCapacity().acquire(),
            network_backend=backend(m), ssl_context_factory=insecure, clock=FakeClock())


def test_transport_closed_while_preparing_request_cannot_dial_later():
    m = feature()
    r, d = Resolver(), Dialer()
    t = transport(m, backend(m, r, d))
    async def exercise():
        preparing, resume = anyio.Event(), anyio.Event()
        class OwnedBody(httpx.AsyncByteStream):
            async def __aiter__(self):
                preparing.set()
                await resume.wait()
                yield b'{}'
            async def aclose(self):
                pass
        async with httpx.AsyncClient(transport=t, trust_env=False) as client:
            async def send():
                with rejected('BYOK_EGRESS_UNAVAILABLE'):
                    await client.send(httpx.Request('POST', endpoint().endpoint_url, stream=OwnedBody()))
            async with anyio.create_task_group() as tg:
                tg.start_soon(send)
                await preparing.wait()
                await t.aclose()
                resume.set()
    run(exercise())
    assert r.hostname_lookup_count == 0 and d.received_addresses == []


def test_closed_backend_and_stream_cannot_start_connections_or_tls():
    m = feature()
    r, d = Resolver(), Dialer()
    b = backend(m, r, d)
    raw = Stream()
    async def exercise():
        await b.aclose()
        with rejected('BYOK_EGRESS_UNAVAILABLE'):
            await b.connect_tcp(HOST, 443, 5)
        other = backend(m, dialer=Dialer(raw))
        s = await other.connect_tcp(HOST, 443, 5)
        await s.aclose()
        with rejected('BYOK_EGRESS_UNAVAILABLE'):
            await s.start_tls(ssl.create_default_context(), HOST, 5)
    run(exercise())
    assert r.hostname_lookup_count == 0 and d.received_addresses == []
    assert raw.tls_count == 0


@pytest.mark.parametrize('tcp_delay,tls_delay', [(0, 5), (2, 3), (0, 6)])
def test_tls_finishing_at_or_after_shared_connect_deadline_never_sends(tcp_delay, tls_delay):
    m = feature()
    clock = FakeClock()
    class BoundaryTLS(Stream):
        async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
            result = await super().start_tls(ssl_context, server_hostname, timeout)
            clock.advance(tls_delay)
            return result
    raw = BoundaryTLS()
    d, cap = Dialer(raw, clock=clock, delay=tcp_delay), m.EgressCapacity()
    t = transport(m, backend(m, dialer=d, clock=clock), cap.acquire(), clock=clock)
    async def exercise():
        async with httpx.AsyncClient(transport=t, trust_env=False) as client:
            with rejected('PROVIDER_TIMEOUT'):
                await client.post(endpoint().endpoint_url, content=b'{}')
        assert raw.http_write_count == 0 and raw.closed and cap.active == 0
    run(exercise())
    assert d.received_addresses == [PUBLIC]


@pytest.mark.parametrize('wrapped', [False, True])
def test_buffer_rejection_closes_original_producer_iterator_and_stream(wrapped):
    m = feature()
    r, d, cap = Resolver(), Dialer(), m.EgressCapacity()
    t = transport(m, backend(m, r, d), cap.acquire())
    class Producer(httpx.AsyncByteStream):
        def __init__(self):
            self.iterator_started = self.iterator_closed = self.stream_closed = False
        async def __aiter__(self):
            self.iterator_started = True
            try:
                yield b'x' * (128 * 1024 + 1)
                yield b'not-reached'
            finally:
                self.iterator_closed = True
        async def aclose(self):
            self.stream_closed = True
    body = Producer()
    async def exercise():
        async with httpx.AsyncClient(transport=t, trust_env=False) as client:
            request = client.build_request('POST', endpoint().endpoint_url, content=body) if wrapped else httpx.Request('POST', endpoint().endpoint_url, stream=body)
            with rejected('BYOK_EGRESS_UNAVAILABLE' if wrapped else 'MODEL_BUDGET_EXCEEDED'):
                await client.send(request)
            if wrapped:
                assert not body.iterator_started and not body.iterator_closed and not body.stream_closed
            else:
                assert body.iterator_closed and body.stream_closed
            assert cap.active == 0
        assert r.hostname_lookup_count == 0 and d.received_addresses == []
    run(exercise())


@pytest.mark.parametrize('mode', ['error', 'timeout', 'cancel'])
def test_owned_request_producer_cleanup_on_error_timeout_and_cancel(mode):
    m = feature()
    clock = FakeClock()
    r, d, cap = Resolver(), Dialer(), m.EgressCapacity()
    t = transport(m, backend(m, r, d, clock=clock), cap.acquire(), clock=clock)
    class Producer(httpx.AsyncByteStream):
        iterator_closed = stream_closed = False
        started = None
        async def __aiter__(self):
            try:
                if mode == 'timeout':
                    clock.advance(30)
                    yield b'{}'
                elif mode == 'error':
                    yield b'partial'
                    raise RuntimeError('SYNTHETIC-RAW-KEY-producer-error')
                else:
                    self.started.set()
                    await anyio.sleep_forever()
                    yield b'not-reached'
            finally:
                self.iterator_closed = True
        async def aclose(self):
            self.stream_closed = True
    body = Producer()
    async def exercise():
        body.started = anyio.Event()
        async with httpx.AsyncClient(transport=t, trust_env=False) as client:
            async def send():
                await client.send(httpx.Request('POST', endpoint().endpoint_url, stream=body))
            if mode == 'cancel':
                async with anyio.create_task_group() as tg:
                    tg.start_soon(send)
                    await body.started.wait()
                    tg.cancel_scope.cancel()
            else:
                with rejected('PROVIDER_TIMEOUT' if mode == 'timeout' else 'OUTCOME_UNKNOWN'):
                    await send()
            assert body.iterator_closed and body.stream_closed and cap.active == 0
        assert r.hostname_lookup_count == 0 and d.received_addresses == []
    run(exercise())


def test_request_producer_cleanup_failure_is_safe_and_transport_lease_is_truthful():
    m = feature()
    clock = FakeClock()
    r, d, cap = Resolver(), Dialer(), m.EgressCapacity()
    t = transport(m, backend(m, r, d, clock=clock), cap.acquire(), clock=clock)
    class Producer(httpx.AsyncByteStream):
        iterator_closed = stream_close_attempted = stream_closed = False
        async def __aiter__(self):
            try:
                clock.advance(30)
                yield b'{}'
            finally:
                self.iterator_closed = True
        async def aclose(self):
            self.stream_close_attempted = True
            await anyio.sleep_forever()
            self.stream_closed = True
    body = Producer()
    async def exercise():
        async with httpx.AsyncClient(transport=t, trust_env=False) as client:
            with rejected('BYOK_EGRESS_UNAVAILABLE'):
                await client.send(httpx.Request('POST', endpoint().endpoint_url, stream=body))
            assert body.iterator_closed and body.stream_close_attempted and not body.stream_closed
            assert cap.active == 0 and t._backend.terminal
        assert r.hostname_lookup_count == 0 and d.received_addresses == []
    run(exercise())


def test_owned_request_iterator_acquisition_failure_still_closes_owner():
    m = feature()
    r, d, cap = Resolver(), Dialer(), m.EgressCapacity()
    t = transport(m, backend(m, r, d), cap.acquire())
    class Producer(httpx.AsyncByteStream):
        stream_closed = False
        def __aiter__(self):
            raise RuntimeError('SYNTHETIC-RAW-KEY-iterator-acquisition')
        async def aclose(self):
            self.stream_closed = True
    body = Producer()
    async def exercise():
        async with httpx.AsyncClient(transport=t, trust_env=False) as client:
            with rejected('OUTCOME_UNKNOWN'):
                await client.send(httpx.Request('POST', endpoint().endpoint_url, stream=body))
            assert body.stream_closed
            assert cap.active == 0 and t._backend.terminal
        assert r.hostname_lookup_count == 0 and d.received_addresses == []
    run(exercise())
