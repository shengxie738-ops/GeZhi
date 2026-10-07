#!/usr/bin/env python3
"""Credential-free, loopback-only Task 3 connection gate, separate from pytest.

Synthetic public DNS answers/peer seams are named in each case. The native
connection actually goes to loopback, which production policy must reject.
No application startup, provider connection or deployment security claim.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import ipaddress
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[3]
PUBLIC = ipaddress.ip_address('9.9.9.9')
HOST = 'provider.example'


def isolate(args):
    with tempfile.TemporaryDirectory(prefix='gezhi-task3-connection-') as directory:
        temp = Path(directory)
        (temp / 'home').mkdir()
        report = temp / 'connection.json'
        env = {'PATH': os.defpath, 'HOME': str(temp / 'home'), 'TMPDIR': str(temp), 'LANG': 'C.UTF-8',
            'LC_ALL': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1', 'TASK3_CONTROLLED_CONNECTION_CHILD': '1'}
        result = subprocess.run([sys.executable, '-I', str(Path(__file__).resolve()), '--_child',
            '--source-root', str(args.source_root), '--report-json', str(report)], env=env, cwd=temp,
            capture_output=True, text=True)
        print(result.stdout, end='')
        print(result.stderr, end='', file=sys.stderr)
        data = json.loads(report.read_text()) if report.is_file() else {'status': 'blocked', 'exit_code': result.returncode,
            'blocker': 'controlled child ended before producing connection evidence'}
        if args.report_json:
            args.report_json.parent.mkdir(parents=True, exist_ok=True)
            args.report_json.write_text(json.dumps(data, indent=2) + '\n')
        return result.returncode


def fence(root):
    state = {'external_dns_calls': 0, 'external_connections': 0, 'loopback_connections': 0}
    forbidden_parts = {'.git', '.env', 'sessions', 'secrets', '.aws'}
    def audit(event, args):
        if event == 'socket.getaddrinfo':
            # Numeric getaddrinfo is also forbidden, proving the native dial path.
            state['external_dns_calls'] += 1
            raise RuntimeError('CONTROLLED_DNS_FORBIDDEN')
        if event in ('socket.connect', 'socket.bind'):
            address = args[1]
            if isinstance(address, tuple):
                try:
                    allowed = ipaddress.ip_address(address[0]).is_loopback
                except ValueError:
                    allowed = False
            else:
                allowed = False
            if not allowed:
                state['external_connections'] += 1
                raise RuntimeError('CONTROLLED_NON_LOOPBACK_FORBIDDEN')
            if event == 'socket.connect':
                state['loopback_connections'] += 1
        if event in ('subprocess.Popen', 'os.system', 'sqlite3.connect', 'sqlite3.connect/handle'):
            raise RuntimeError('CONTROLLED_UNREGISTERED_IO')
        if event == 'open' and args and not isinstance(args[0], int):
            path = Path(os.fsdecode(args[0])).resolve()
            if any(part in forbidden_parts or part.startswith('.env.') for part in path.parts):
                raise RuntimeError('CONTROLLED_FORBIDDEN_FILE')
            mode, flags = args[1], args[2]
            writing = (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT))
            if writing and not path.is_relative_to(Path.cwd()):
                raise RuntimeError('CONTROLLED_WRITE_OUTSIDE_TEMP')
    sys.addaudithook(audit)
    return state


async def cases(backend_root):
    import anyio
    import httpcore
    import httpx
    from app.services.byok import transport as m
    from app.services.byok.endpoint_policy import normalize_endpoint, is_global_unicast
    from app.services.byok.errors import ByokError
    from app.services.byok.limits import WorkCallBudget

    fixtures = backend_root / 'tests/fixtures/byok_tls'
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(fixtures / 'server.pem', fixtures / 'server-key.pem')
    state = {'sni': [], 'requests': [], 'request_received': None, 'status': 200, 'stall': False}
    server_context.set_servername_callback(lambda sock, host, context: state['sni'].append(host))
    server_context.set_alpn_protocols(['http/1.1'])

    async def serve(reader, writer):
        try:
            data = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 5)
            length = next((int(line.split(b':', 1)[1]) for line in data.split(b'\r\n') if line.lower().startswith(b'content-length:')), 0)
            if length:
                await reader.readexactly(length)
            state['requests'].append(data.decode('ascii'))
            if state['request_received']:
                state['request_received'].set()
            if state['stall']:
                await reader.read()
            else:
                status = state['status']
                response = ('HTTP/1.1 ' + str(status) + ' Test\r\nContent-Length: 2\r\nConnection: close\r\n' +
                    ('Location: https://provider.example/v1/chat/completions\r\n' if status == 302 else '') + '\r\n{}').encode()
                writer.write(response)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError, TimeoutError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, ssl.SSLError):
                pass

    listening = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listening.bind(('127.0.0.1', 0))
    listening.listen(16)
    listening.setblocking(False)
    server = await asyncio.start_server(serve, sock=listening, ssl=server_context, ssl_handshake_timeout=5)
    local_port = listening.getsockname()[1]
    records = []
    accepted_tasks = set()
    # The asyncio TLS protocol may report expected unknown-CA/host failures.
    # Capture only type names, never exception strings or request metadata.
    loop = asyncio.get_running_loop()
    loop_errors = []
    loop.set_exception_handler(lambda loop, context: loop_errors.append(type(context.get('exception')).__name__))

    class Resolver:
        def __init__(self):
            self.hostname_lookup_count = 0
        async def resolve(self, host, *, deadline):
            self.hostname_lookup_count += 1
            return (PUBLIC,)

    class NativeRecordingBackend(httpcore.AnyIOBackend):
        def __init__(self):
            self.received_numeric_hosts = []
        async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
            ipaddress.ip_address(host)  # Assertion: canonical numeric host only.
            self.received_numeric_hosts.append(host)
            return await super().connect_tcp(host, port, timeout, local_address, socket_options)

    class PeerSeam(httpcore.AsyncNetworkStream):
        def __init__(self, raw, peer):
            self.raw, self.peer = raw, peer
            self.actual_peer = raw.get_extra_info('server_addr')
            self.socket = raw.get_extra_info('socket')
            self.tls_count, self.http_write_count = 0, 0
            self.tls_verified = False
            self.context_flags = []
        async def read(self, max_bytes, timeout=None):
            return await self.raw.read(max_bytes, timeout)
        async def write(self, buffer, timeout=None):
            if buffer:
                self.http_write_count += 1
            await self.raw.write(buffer, timeout)
        async def aclose(self):
            await self.raw.aclose()
        async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
            self.tls_count += 1
            self.context_flags.append({'check_hostname': ssl_context.check_hostname,
                'verify_mode': int(ssl_context.verify_mode), 'server_hostname': server_hostname})
            self.raw = await self.raw.start_tls(ssl_context, server_hostname, timeout)
            self.tls_verified = True
            assert self.raw.get_extra_info('ssl_object').selected_alpn_protocol() == 'http/1.1'
            return self
        def get_extra_info(self, name):
            return self.peer if name == 'server_addr' else self.raw.get_extra_info(name)

    class ControlledDialer:
        def __init__(self, mode='synthetic_peer'):
            self.mode, self.received_addresses, self.streams = mode, [], []
            self.native = NativeRecordingBackend()
            self.numeric = m.NumericDialer(network_backend=self.native)
        async def connect(self, address, port, *, deadline):
            self.received_addresses.append(str(address))
            assert address == PUBLIC and port == 443
            raw = await self.numeric.connect(ipaddress.ip_address('127.0.0.1'), local_port, deadline=deadline)
            actual = raw.get_extra_info('server_addr')
            peer = (str(PUBLIC), 443) if self.mode == 'synthetic_peer' else actual
            if self.mode == 'missing_peer':
                peer = None
            elif self.mode == 'mismatched_peer':
                peer = ('8.8.8.8', 443)
            wrapped = PeerSeam(raw, peer)
            self.streams.append(wrapped)
            return wrapped

    def trusted_context():
        return ssl.create_default_context(cafile=fixtures / 'ca.pem')

    async def native_numeric(address, family):
        # A second non-TLS listener proves numeric AnyIO/native behavior by family.
        listener = socket.socket(family, socket.SOCK_STREAM)
        listener.bind((address, 0))
        listener.listen(4)
        listener.setblocking(False)
        def discard(reader, writer):
            writer.close()
        plain_server = await asyncio.start_server(discard, sock=listener)
        native = NativeRecordingBackend()
        try:
            dialer = m.NumericDialer(network_backend=native)
            stream = await dialer.connect(ipaddress.ip_address(address), listener.getsockname()[1], deadline=time.monotonic() + 5)
            peer, raw_socket = stream.get_extra_info('server_addr'), stream.get_extra_info('socket')
            assert ipaddress.ip_address(peer[0]) == ipaddress.ip_address(address)
            await stream.aclose()
            assert raw_socket.fileno() == -1
            assert native.received_numeric_hosts == [address]
            return {'native_numeric_address': address, 'native_peer_ip': peer[0], 'socket_terminal': True,
                'hostname_dns_queries': 0, 'real_socket': True, 'synthetic_peer': False}
        finally:
            plain_server.close()
            await plain_server.wait_closed()

    async def case(name, *, mode='synthetic_peer', host=HOST, inject_ca=True, expected=None, cancel=False, status=200):
        state.update(sni=[], requests=[], request_received=asyncio.Event(), status=status, stall=cancel)
        resolver, dialer, cap = Resolver(), ControlledDialer(mode), m.EgressCapacity()
        ep = normalize_endpoint('https://' + host + '/v1')
        deadline = time.monotonic() + 8
        limits = WorkCallBudget.student().reserve('student_chat', 16)
        backend = m.GuardedNetworkBackend(ep, deadline=deadline, resolver=resolver, dialer=dialer)
        transport = m.ProtectedTransport(ep, limits, deadline=deadline, egress_lease=cap.acquire(), network_backend=backend,
            ssl_context_factory=trusted_context if inject_ca else None)
        outcome = None
        try:
            async with httpx.AsyncClient(transport=transport, trust_env=False, follow_redirects=True, timeout=None) as client:
                if cancel:
                    task = asyncio.create_task(client.post(ep.endpoint_url, content=b'{}'))
                    await asyncio.wait_for(state['request_received'].wait(), 5)
                    assert cap.active == 1
                    task.cancel()
                    try:
                        await task
                        raise AssertionError('cancel did not propagate')
                    except asyncio.CancelledError:
                        outcome = 'CANCELLED'
                else:
                    try:
                        response = await client.post(ep.endpoint_url, content=b'{}')
                        assert response.status_code == 200 and response.content == b'{}'
                        outcome = 'complete'
                    except ByokError as error:
                        outcome = error.code
            assert outcome == (expected or ('CANCELLED' if cancel else 'complete'))
            assert resolver.hostname_lookup_count == 1
            assert dialer.received_addresses == [str(PUBLIC)]
            assert dialer.native.received_numeric_hosts == ['127.0.0.1']
            assert cap.active == 0 and backend.terminal
            assert all(s.socket.fileno() == -1 for s in dialer.streams)
            streams = dialer.streams
            if mode != 'synthetic_peer':
                assert sum(s.tls_count for s in streams) == 0
                assert sum(s.http_write_count for s in streams) == 0
                assert state['requests'] == []
            elif outcome in ('TLS_FAILED',):
                assert state['requests'] == []
            else:
                assert len(state['requests']) == 1
                assert 'Host: ' + host + '\r\n' in state['requests'][0]
                assert 'Accept-Encoding: identity\r\n' in state['requests'][0]
                assert 'Authorization:' not in state['requests'][0]
                assert state['sni'] == [host]
            return {'name': name, 'status': 'passed', 'outcome': outcome,
                'real_socket': True, 'real_tls_handshake_attempted': sum(s.tls_count for s in streams) > 0,
                'tls_verification_succeeded': all(s.tls_verified for s in streams),
                'synthetic_peer': mode == 'synthetic_peer', 'peer_mode': mode,
                'actual_peer_ips': [s.actual_peer[0] for s in streams],
                'guarded_peer_ips': [s.peer[0] if s.peer else None for s in streams],
                'resolver_hostname_lookups': resolver.hostname_lookup_count,
                'guarded_numeric_candidates': dialer.received_addresses,
                'native_numeric_addresses': dialer.native.received_numeric_hosts,
                'sni_observed': state['sni'], 'request_count': len(state['requests']),
                'pre_tls_http_write_count': sum(s.http_write_count for s in streams) if mode != 'synthetic_peer' else 0,
                'tls_flags': [flags for s in streams for flags in s.context_flags],
                'socket_terminal': True, 'capacity_after_close': cap.active}
        finally:
            await transport.aclose()

    matrix = [
        ('native_numeric_ipv4_no_dns', lambda: native_numeric('127.0.0.1', socket.AF_INET)),
        ('native_numeric_ipv6_no_dns', lambda: native_numeric('::1', socket.AF_INET6)),
        ('synthetic_peer_sni_host_trusted_test_ca', lambda: case('synthetic_peer_sni_host_trusted_test_ca')),
        ('synthetic_peer_certificate_hostname_mismatch', lambda: case('synthetic_peer_certificate_hostname_mismatch', host='wrong.example', expected='TLS_FAILED')),
        ('synthetic_peer_default_roots_reject_test_ca', lambda: case('synthetic_peer_default_roots_reject_test_ca', inject_ca=False, expected='TLS_FAILED')),
        ('actual_loopback_peer_rejected_before_tls_http', lambda: case('actual_loopback_peer_rejected_before_tls_http', mode='actual_loopback_peer', expected='DNS_REJECTED')),
        ('missing_peer_rejected_before_tls_http', lambda: case('missing_peer_rejected_before_tls_http', mode='missing_peer', expected='DNS_REJECTED')),
        ('mismatched_peer_rejected_before_tls_http', lambda: case('mismatched_peer_rejected_before_tls_http', mode='mismatched_peer', expected='DNS_REJECTED')),
        ('synthetic_peer_cancel_closes_actual_transport', lambda: case('synthetic_peer_cancel_closes_actual_transport', cancel=True)),
        ('synthetic_peer_redirect_one_request', lambda: case('synthetic_peer_redirect_one_request', status=302, expected='PROVIDER_REDIRECT_REJECTED')),
    ]
    try:
        assert is_global_unicast('127.0.0.1') is False and is_global_unicast('::1') is False
        for name, function in matrix:
            try:
                result = await function()
                records.append({'name': name, 'status': 'passed'} | result)
                print('PASS ' + name)
            except BaseException as error:
                records.append({'name': name, 'status': 'failed', 'error_type': type(error).__name__,
                    'controlled_code': error.code if isinstance(error, ByokError) else None})
                print('FAIL ' + name + ' (' + type(error).__name__ + ')')
                # A failed real-connection item is a gate, never a default-client fallback.
                break
    finally:
        server.close()
        await server.wait_closed()
        await asyncio.sleep(0)
    return records, loop_errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--report-json', type=Path)
    parser.add_argument('--_child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.source_root = args.source_root.resolve()
    if args.source_root != ROOT / 'backend':
        parser.error('source-root must be this candidate backend')
    if not args._child:
        return isolate(args)
    if os.environ.get('TASK3_CONTROLLED_CONNECTION_CHILD') != '1' or Path.cwd().is_relative_to(ROOT):
        parser.error('isolated child required')
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(args.source_root))
    manifest = json.loads((ROOT / 'docs/work-byok-source-manifest.json').read_text())
    mismatches = [e['path'] for e in manifest['source_pins'] if hashlib.sha256((ROOT / e['path']).read_bytes()).hexdigest() != e['sha256']]
    if mismatches:
        print('SOURCE_PIN_MISMATCH')
        return 2
    # Load known vendor stack before fencing native library loading; no app import.
    import anyio, httpcore, httpx  # noqa
    io = fence(ROOT)
    records, loop_errors = asyncio.run(cases(args.source_root))
    success = len(records) == 10 and all(item['status'] == 'passed' for item in records) and not io['external_dns_calls'] and not io['external_connections']
    report = {'schema': 'work-byok-controlled-connection@1', 'status': 'passed' if success else 'failed',
        'exit_code': 0 if success else 1, 'cases': records, 'io': io, 'source_root': str(ROOT),
        'interpreter': sys.executable, 'dependencies': {n: importlib.metadata.version(n) for n in ('httpx', 'httpcore', 'anyio')},
        'source_pin_mismatches': mismatches, 'real_credentials_used': False, 'external_provider_verified': False,
        'deployment_firewall_verified': False, 'application_startup': False, 'expected_tls_loop_error_types': loop_errors,
        'synthetic_fixture_public_seeds': ['bytes(range(32)) test-only CA', 'bytes(range(32,64)) test-only server'],
        'manifest_sha256': hashlib.sha256((ROOT / 'docs/work-byok-source-manifest.json').read_bytes()).hexdigest()}
    if args.report_json:
        args.report_json.write_text(json.dumps(report, indent=2) + '\n')
    return report['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
