"""Offline finite Engine/pipe doubles. Never invokes Docker or a real container."""
from __future__ import annotations

from importlib import import_module
import io
import json
import os
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    subject = import_module('app.services.teacher_work.courseware_docker_transport')
except ModuleNotFoundError as error:
    if error.name != 'app.services.teacher_work.courseware_docker_transport':
        raise
    subject = None
from app.services.teacher_work.courseware_extract import ExtractionLimits, ExtractionError
from app.services.teacher_work import courseware_parser_lifecycle as life


class SocketDouble:
    def __init__(self, response, fragment=3, short_write=7):
        self.response = io.BytesIO(response)
        self.fragment = fragment
        self.short_write = short_write
        self.sent = bytearray()
        self.closed = False

    def recv(self, count):
        if not 0 < count <= 65536:
            raise AssertionError('unbounded socket read')
        return self.response.read(min(count, self.fragment))

    def send(self, data):
        n = min(len(data), self.short_write)
        self.sent.extend(data[:n])
        return n

    def settimeout(self, value):
        pass

    def close(self):
        self.closed = True


class PipeProcess:
    """Finite real pipes around a process double; no external executable."""
    def __init__(self, output=b'', diagnostic=b'', exit_code=0):
        ir, iw = os.pipe()
        outr, outw = os.pipe()
        errr, errw = os.pipe()
        self.stdin = os.fdopen(iw, 'wb', buffering=0)
        self.stdout = os.fdopen(outr, 'rb', buffering=0)
        self.stderr = os.fdopen(errr, 'rb', buffering=0)
        self.received = bytearray()
        self.exit_code = exit_code
        self.done = threading.Event()
        self.killed = False
        self.reaped = False

        def work():
            try:
                with os.fdopen(ir, 'rb', buffering=0) as source:
                    while True:
                        data = source.read(31)
                        if not data:
                            break
                        self.received.extend(data)
                for fd, data in ((outw, output), (errw, diagnostic)):
                    try:
                        view = memoryview(data)
                        while view:
                            view = view[os.write(fd, view[:19]):]
                    except BrokenPipeError:
                        pass
                    finally:
                        os.close(fd)
            finally:
                self.done.set()
        self.thread = threading.Thread(target=work)
        self.thread.start()

    def poll(self):
        return self.exit_code if self.done.is_set() else None

    def kill(self):
        self.killed = True
        self.exit_code = -9

    def wait(self, timeout=None):
        if not self.done.wait(timeout):
            raise TimeoutError('double wait timeout')
        self.thread.join()
        self.reaped = True
        return self.exit_code

    def dispose(self):
        for stream in (self.stdin, self.stdout, self.stderr):
            if not stream.closed:
                stream.close()
        self.wait(timeout=2)


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(subject, 'bounded transport missing')
        self.transport = subject.DockerTransport()
        self.cancel = threading.Event()
        self.deadline = time.monotonic() + 2
        self.daemon = life.DaemonIdentity('native-daemon', 'a' * 64)
        self.intent = life.CreateIntent('gezhi-parser-' + 'b' * 32,
            'c' * 64, 'sha256:' + 'd' * 64, self.daemon, 'e' * 32)
        self.limits = ExtractionLimits()

    def process(self, **kwargs):
        proc = PipeProcess(**kwargs)
        self.addCleanup(proc.dispose)
        return proc

    def request(self, sock):
        with patch.object(self.transport, '_connect', return_value=sock):
            return self.transport._request('GET', '/v1.51/info', None,
                self.deadline, self.cancel)

    def test_fragmented_content_length_and_short_writes(self):
        body = b'{"ID":"owned"}'
        sock = SocketDouble(b'HTTP/1.1 200 OK\r\nContent-Length: ' +
            str(len(body)).encode() + b'\r\n\r\n' + body)
        result = self.request(sock)
        self.assertEqual(result, (200, body))
        self.assertEqual(bytes(sock.sent),
            b'GET /v1.51/info HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\nContent-Length: 0\r\n\r\n')
        self.assertTrue(sock.closed)

    def test_fragmented_chunked_response(self):
        sock = SocketDouble(b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n'
            b'2\r\n{}\r\n0\r\n\r\n', fragment=1)
        self.assertEqual(self.request(sock), (200, b'{}'))

    def test_control_and_header_limits_and_malformed_frames(self):
        samples = [
            b'HTTP/1.1 200 OK\r\nContent-Length: 999999999\r\n\r\n',
            b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\nfffffff\r\n',
            b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\nContent-Length: 3\r\n\r\n{}',
            b'HTTP/1.1 200 OK\r\nContent-Length: 3\r\n\r\n{}',
            b'HTTP/1.1 200 OK\r\nX: ' + b'x' * 9000,
        ]
        for blob in samples:
            sock = SocketDouble(blob, fragment=512)
            with self.subTest(size=len(blob)), self.assertRaises(ExtractionError):
                self.request(sock)
            self.assertTrue(sock.closed)

    def test_error_diagnostics_are_discarded(self):
        sock = SocketDouble(b'HTTP/1.1 404 Not Found\r\nContent-Length: 16\r\n\r\nPRIVATE_DOCUMENT')
        self.assertEqual(self.request(sock), (404, b''))

    def test_cancel_and_expired_requests_do_not_connect(self):
        with patch.object(self.transport, '_connect') as connect:
            self.cancel.set()
            with self.assertRaises(ExtractionError):
                self.transport._request('GET', '/v1.51/info', None,
                    self.deadline, self.cancel)
            self.cancel.clear()
            with self.assertRaises(TimeoutError):
                self.transport._request('GET', '/v1.51/info', None,
                    time.monotonic() - 1, self.cancel)
            connect.assert_not_called()

    def test_fixed_create_recipe_has_no_mounts_and_clean_entrypoint(self):
        seen = []
        def request(method, path, body, deadline, cancel):
            seen.append((method, path, json.loads(body)))
            return 201, json.dumps({'Id': 'f' * 64}).encode()
        with patch.object(self.transport, '_request', side_effect=request):
            self.assertEqual(self.transport.create(self.intent, self.limits,
                self.deadline, self.cancel), 'f' * 64)
        method, path, body = seen[0]
        self.assertEqual(method, 'POST')
        self.assertEqual(path, '/v1.51/containers/create?name=' + self.intent.name)
        config = body['HostConfig']
        self.assertEqual(config['NetworkMode'], 'none')
        self.assertTrue(config['ReadonlyRootfs'])
        self.assertEqual(config['CapDrop'], ['ALL'])
        self.assertEqual(config['SecurityOpt'], ['no-new-privileges'])
        self.assertEqual(config['PidsLimit'], 1)
        self.assertEqual(config['Memory'], self.limits.max_memory_bytes)
        self.assertEqual(config['MemorySwap'], config['Memory'])
        self.assertFalse(config.get('Binds'))
        self.assertFalse(config.get('Mounts'))
        self.assertFalse(config.get('Privileged', False))
        self.assertEqual(body['User'], '65532:65532')
        self.assertEqual(body['Entrypoint'], ['/usr/bin/env'])
        self.assertEqual(body['Cmd'][:1], ['-i'])
        self.assertEqual(body['Cmd'][-4:], ['/usr/local/bin/python', '-I', '-B',
            '/opt/parser/courseware_worker.py'])

    def test_create_requires_full_id_and_never_interprets_error_as_rejection(self):
        for status, body in ((201, b'{"Id":"short"}'), (500, b''), (409, b'')):
            with self.subTest(status=status), patch.object(self.transport,
                    '_request', return_value=(status, body)), self.assertRaises(ExtractionError):
                self.transport.create(self.intent, self.limits, self.deadline, self.cancel)

    def test_pipe_exchange_short_reads_writes_and_reap(self):
        proc = self.process(output=b'finite protocol')
        with patch.object(subject.os, 'write', wraps=os.write) as write:
            result = self.transport.exchange(proc, b'owned input' * 100, 64,
                self.deadline, self.cancel)
        self.assertEqual(result.stdout, b'finite protocol')
        self.assertEqual(proc.received, b'owned input' * 100)
        self.assertTrue(proc.reaped)
        self.assertTrue(all(len(call.args[1]) <= 65536 for call in write.call_args_list))
        self.assertTrue(all(s.closed for s in (proc.stdin, proc.stdout, proc.stderr)))

    def test_pipe_stdout_and_stderr_caps_are_independent(self):
        for output, diag in ((b'x' * 65, b''), (b'', b'z' * (8192 + 1))):
            proc = self.process(output=output, diagnostic=diag)
            with self.subTest(stdout=len(output), stderr=len(diag)), self.assertRaises(ExtractionError):
                self.transport.exchange(proc, b'x', 64, self.deadline, self.cancel)
            self.assertTrue(proc.reaped)
            self.assertTrue(all(s.closed for s in (proc.stdin, proc.stdout, proc.stderr)))

    def test_any_stderr_is_not_retained_in_result(self):
        proc = self.process(output=b'frame', diagnostic=b'PRIVATE_DOCUMENT')
        result = self.transport.exchange(proc, b'x', 64, self.deadline, self.cancel)
        self.assertEqual(result.stderr_bytes, 16)
        self.assertNotIn('PRIVATE_DOCUMENT', repr(result))

    def test_attach_uses_fixed_argv_env_and_never_document_arguments(self):
        ownership = life.OwnershipEvidence('f' * 64, self.intent.name,
            self.intent.owner_token, self.intent.image_id, self.daemon)
        with patch.object(subject.subprocess, 'Popen', return_value=object()) as launch:
            self.transport.start(ownership, self.deadline, self.cancel)
        args, options = launch.call_args
        self.assertEqual(args[0], ['/usr/local/bin/docker', '--host',
            'unix:///var/run/docker.sock', 'start', '--attach', '--interactive', 'f' * 64])
        self.assertFalse(options.get('shell', False))
        self.assertTrue(options['close_fds'])
        self.assertEqual(options['env'], subject.HOST_ENV)

    def test_exchange_cancel_and_deadline_still_reap_owned_cli(self):
        for cancelled in (True, False):
            proc = self.process(output=b'finite')
            event = threading.Event()
            if cancelled:
                event.set()
            with self.subTest(cancelled=cancelled), self.assertRaises((ExtractionError, TimeoutError)):
                self.transport.exchange(proc, b'owned', 64,
                    time.monotonic() + (2 if cancelled else -1), event)
            self.assertTrue(proc.reaped)
            self.assertTrue(all(s.closed for s in (proc.stdin, proc.stdout, proc.stderr)))

    def test_exchange_actual_short_writes(self):
        proc = self.process(output=b'finite')
        original = os.write
        def short(fd, data):
            return original(fd, data[:2])
        with patch.object(subject.os, 'write', side_effect=short):
            result = self.transport.exchange(proc, b'owned' * 20, 64, self.deadline, self.cancel)
        self.assertEqual(proc.received, b'owned' * 20)
        self.assertEqual(result.stdout, b'finite')

    def test_reap_failure_does_not_skip_worker_cleanup(self):
        ownership = life.OwnershipEvidence('f' * 64, self.intent.name,
            self.intent.owner_token, self.intent.image_id, self.daemon)
        operations = []
        stopped = False
        def request(method, path, body, deadline, cancel):
            nonlocal stopped
            operations.append((method, path))
            if path.endswith('/json'):
                if any(m == 'DELETE' for m, p in operations):
                    return 404, b''
                return 200, json.dumps({'Id': ownership.container_id, 'Name': '/' + ownership.name,
                    'Image': ownership.image_id, 'Config': {'Labels': {'gezhi.parser.owner': ownership.owner_token}},
                    'State': {'Running': not stopped, 'Pid': 301 if not stopped else 0}}).encode()
            if '/kill?' in path:
                stopped = True
                return 204, b''
            if '/wait?' in path:
                return 200, b'{"StatusCode":137}'
            return 204, b''
        with (patch.object(self.transport, 'reap', side_effect=OSError('uncertain reap')),
                patch.object(self.transport, 'current_daemon', return_value=self.daemon),
                patch.object(self.transport, '_request', side_effect=request)):
            receipt = self.transport.cleanup(ownership, None, object(), self.deadline)
        self.assertFalse(receipt.cli_reaped)
        self.assertTrue(any('/kill?' in path for method, path in operations))
        self.assertFalse(receipt.removed)
        self.assertFalse(any(method == 'DELETE' for method, path in operations))
        self.assertFalse(receipt.cgroup_empty)

    def test_capture_rechecks_ownership_before_kernel_access(self):
        ownership = life.OwnershipEvidence('f' * 64, self.intent.name,
            self.intent.owner_token, self.intent.image_id, self.daemon)
        data = {'Id': ownership.container_id, 'Name': '/unrelated', 'Image': ownership.image_id,
            'Config': {'Labels': {'gezhi.parser.owner': ownership.owner_token}},
            'State': {'Running': True, 'Pid': 301}}
        with (patch.object(self.transport, '_inspect_raw', return_value=data),
                patch.object(subject, '_start_ticks') as ticks,
                patch.object(subject, '_kernel') as kernel, self.assertRaises(ExtractionError)):
            self.transport.capture_identity(ownership, self.limits, self.deadline, self.cancel)
        ticks.assert_not_called()
        kernel.assert_not_called()

    def test_invalid_exchange_arguments_still_reap_cli(self):
        for data, cap in (('private', 64), (b'owned', '64'), (b'owned', 1)):
            proc = self.process(output=b'finite')
            with self.subTest(data_type=type(data).__name__, cap=cap), self.assertRaises(ExtractionError):
                self.transport.exchange(proc, data, cap, self.deadline, self.cancel)
            self.assertTrue(proc.reaped)

    def test_owned_descriptor_close_error_still_consumes_other_descriptor(self):
        self.assertIsNotNone(getattr(subject, '_close_owned', None))
        first, second = os.pipe()
        calls = []
        original = os.close
        def uncertain(fd):
            calls.append(fd)
            original(fd)
            if fd == first:
                raise OSError('close returned error after consuming descriptor')
        with patch.object(subject.os, 'close', side_effect=uncertain):
            with self.assertRaises(ExtractionError):
                subject._close_owned((first, second))
        self.assertEqual(calls, [first, second])
        for fd in (first, second):
            with self.assertRaises(OSError):
                os.fstat(fd)

    def test_cleanup_rechecks_identity_before_removal(self):
        ownership = life.OwnershipEvidence('f' * 64, self.intent.name,
            self.intent.owner_token, self.intent.image_id, self.daemon)
        good = {'Id': ownership.container_id, 'Name': '/' + ownership.name,
            'Image': ownership.image_id, 'Config': {'Labels': {'gezhi.parser.owner': ownership.owner_token}},
            'State': {'Running': False, 'Pid': 0}}
        bad = dict(good, Name='/unrelated')
        calls = []
        def request(method, path, body, deadline, cancel):
            calls.append(method)
            return 200, b'{"StatusCode":0}'
        with (patch.object(self.transport, 'current_daemon', return_value=self.daemon),
                patch.object(self.transport, '_inspect_raw', side_effect=[good, bad]),
                patch.object(self.transport, '_request', side_effect=request)):
            receipt = self.transport.cleanup(ownership, None, None, self.deadline)
        self.assertNotIn('DELETE', calls)
        self.assertFalse(receipt.removed)

    def test_daemon_outage_attempts_exact_pidfd_termination_and_keeps_receipt_partial(self):
        self.assertIsNotNone(getattr(subject, 'signal', None), 'pidfd termination missing')
        ownership = life.OwnershipEvidence('f' * 64, self.intent.name,
            self.intent.owner_token, self.intent.image_id, self.daemon)
        identity = life.WorkerIdentity(301, 42000, '/owned/cgroup', 19, 821)
        # Finite fd/observation double. No signal is delivered to any process.
        fd = os.open(os.devnull, os.O_RDONLY)
        self.addCleanup(lambda: os.close(fd))
        self.transport._watches[ownership.container_id] = (identity, fd, fd, fd)
        with (patch.object(self.transport, 'current_daemon', side_effect=TimeoutError()),
                patch.object(subject.signal, 'pidfd_send_signal') as terminate,
                patch.object(self.transport, '_gone_and_empty', return_value=(True, True))):
            receipt = self.transport.cleanup(ownership, identity, None, self.deadline)
        terminate.assert_called_once_with(fd, subject.signal.SIGKILL)
        self.assertTrue(receipt.identity_gone)
        self.assertTrue(receipt.cgroup_empty)
        self.assertFalse(receipt.wait_completed)
        self.assertFalse(receipt.removed)

    def test_capture_builds_identity_from_kernel_and_pins_handles_before_input(self):
        self.assertIsNotNone(getattr(subject, 'signal', None), 'pidfd identity capture missing')
        ownership = life.OwnershipEvidence('f' * 64, self.intent.name,
            self.intent.owner_token, self.intent.image_id, self.daemon)
        data = {'Id': ownership.container_id, 'Name': '/' + ownership.name,
            'Image': ownership.image_id, 'Config': {'Labels': {'gezhi.parser.owner': ownership.owner_token}},
            'State': {'Running': True, 'Pid': 301}}
        opened = {}
        real_open, real_close = os.open, os.close
        def open_double(path, flags, **kwargs):
            fd = real_open(os.devnull, os.O_RDONLY)
            opened[fd] = str(path)
            return fd
        def close_double(fd):
            opened.pop(fd, None)
            real_close(fd)
        def read_double(fd, maximum):
            self.assertLessEqual(maximum, 257)
            return {'cpu.max': b'100000 100000', 'pids.max': b'1',
                'memory.max': b'268435456', 'memory.swap.max': b'0'}[opened[fd]]
        status = b'CapInh:0\nCapPrm:0\nCapEff:0\nCapBnd:0\nCapAmb:0\nNoNewPrivs:1\nSeccomp:2\nThreads:1\n'
        def kernel(path, maximum):
            return b'0::/owned/cgroup' if path.endswith('/cgroup') else status
        try:
            with (patch.object(self.transport, '_inspect_raw', return_value=data),
                    patch.object(subject, '_start_ticks', return_value=42000),
                    patch.object(subject, '_kernel', side_effect=kernel),
                    patch.object(subject.os, 'open', side_effect=open_double),
                    patch.object(subject.os, 'close', side_effect=close_double),
                    patch.object(subject.os, 'read', side_effect=read_double),
                    patch.object(subject.os, 'fstat', return_value=SimpleNamespace(st_dev=19, st_ino=821)),
                    patch.object(subject.os, 'readlink', side_effect=lambda p: 'parent' if '/self/' in p else 'worker'),
                    patch.object(subject.os, 'pidfd_open', side_effect=lambda pid, flags: open_double('pidfd', 0)),
                    patch.object(subject.signal, 'pidfd_send_signal') as permission):
                identity = self.transport.capture_identity(ownership, self.limits, self.deadline, self.cancel)
                self.assertEqual(identity, life.WorkerIdentity(301, 42000, '/owned/cgroup', 19, 821))
                watch = self.transport._watches[ownership.container_id]
                self.assertEqual(len(watch), 4)
                self.assertEqual(set(opened.values()), {'cgroup', 'cgroup.events', 'pidfd'})
                permission.assert_called_once_with(watch[3], 0)
        finally:
            for fd in list(opened):
                real_close(fd)
            self.transport._watches.clear()

    def test_engine_stopped_flags_cannot_replace_kernel_exit_proof(self):
        ownership = life.OwnershipEvidence('f' * 64, self.intent.name,
            self.intent.owner_token, self.intent.image_id, self.daemon)
        identity = life.WorkerIdentity(301, 42000, '/owned/cgroup', 19, 821)
        fd = os.open(os.devnull, os.O_RDONLY)
        self.addCleanup(lambda: os.close(fd))
        self.transport._watches[ownership.container_id] = (identity, fd, fd, fd)
        data = {'Id': ownership.container_id, 'Name': '/' + ownership.name,
            'Image': ownership.image_id, 'Config': {'Labels': {'gezhi.parser.owner': ownership.owner_token}},
            'State': {'Running': False, 'Pid': 0}}
        operations = []
        def request(method, path, body, deadline, cancel):
            operations.append(method)
            return (200, b'{"StatusCode":0}') if method == 'POST' else (204, b'')
        with (patch.object(self.transport, 'current_daemon', return_value=self.daemon),
                patch.object(self.transport, '_inspect_raw', return_value=data),
                patch.object(self.transport, '_request', side_effect=request),
                patch.object(self.transport, '_gone_and_empty', return_value=(False, False)),
                patch.object(subject.signal, 'pidfd_send_signal') as terminate):
            receipt = self.transport.cleanup(ownership, identity, None, time.monotonic() - 1)
        self.assertNotIn('DELETE', operations)
        terminate.assert_called_once_with(fd, subject.signal.SIGKILL)
        self.assertFalse(receipt.identity_gone)
        self.assertFalse(receipt.cgroup_empty)


    def _owned(self):
        return life.OwnershipEvidence('f' * 64, self.intent.name,
            self.intent.owner_token, self.intent.image_id, self.daemon)

    def _state(self, ownership, running=False, **state):
        return {'Id': ownership.container_id, 'Name': '/' + ownership.name,
            'Image': ownership.image_id,
            'Config': {'Labels': {'gezhi.parser.owner': ownership.owner_token}},
            'State': {'Running': running, 'Pid': 301 if running else 0,
                      'Status': 'running' if running else 'created', **state}}

    def test_capture_waits_for_matching_running_observation_before_kernel(self):
        ownership = self._owned()
        facts = [self._state(ownership), self._state(ownership, True)]
        # Kernel-access sentinel proves readiness passed only at the second fact.
        with (patch.object(self.transport, '_inspect_raw', side_effect=facts) as inspect,
              patch.object(subject, '_start_ticks', side_effect=RuntimeError('kernel sentinel')) as ticks):
            with self.assertRaisesRegex(RuntimeError, 'kernel sentinel'):
                self.transport.capture_identity(ownership, self.limits, self.deadline, self.cancel)
        self.assertEqual(inspect.call_count, 2)
        ticks.assert_called_once_with(301)

    def test_readiness_cancellation_after_first_observation_never_touches_kernel(self):
        ownership = self._owned()
        def observe(*args):
            self.cancel.set()
            return self._state(ownership)
        with (patch.object(self.transport, '_inspect_raw', side_effect=observe) as inspect,
              patch.object(subject, '_start_ticks') as ticks):
            with self.assertRaises(ExtractionError):
                self.transport.capture_identity(ownership, self.limits, self.deadline, self.cancel)
        self.assertEqual(inspect.call_count, 1)
        ticks.assert_not_called()

    def test_readiness_reuses_absolute_deadline(self):
        ownership = self._owned()
        now = [10.0]
        observed_deadlines = []
        def observe(cid, deadline, cancel):
            observed_deadlines.append(deadline)
            return self._state(ownership)
        def wait(seconds):
            self.assertGreater(seconds, 0)
            self.assertLessEqual(seconds, .01)
            now[0] += seconds
            return False
        with (patch.object(subject.time, 'monotonic', side_effect=lambda: now[0]),
              patch.object(self.cancel, 'wait', side_effect=wait),
              patch.object(self.transport, '_inspect_raw', side_effect=observe),
              patch.object(subject, '_start_ticks') as ticks):
            with self.assertRaises(TimeoutError):
                self.transport.capture_identity(ownership, self.limits, 10.025, self.cancel)
        self.assertGreater(len(observed_deadlines), 1)
        self.assertEqual(set(observed_deadlines), {10.025})
        self.assertLessEqual(now[0], 10.025)
        ticks.assert_not_called()

    def test_readiness_rechecks_ownership_at_each_delayed_observation(self):
        ownership = self._owned()
        wrong = dict(self._state(ownership, True), Name='/unrelated')
        with (patch.object(self.transport, '_inspect_raw', side_effect=[self._state(ownership), wrong]) as inspect,
              patch.object(subject, '_start_ticks') as ticks):
            with self.assertRaises(ExtractionError):
                self.transport.capture_identity(ownership, self.limits, self.deadline, self.cancel)
        self.assertEqual(inspect.call_count, 2)
        ticks.assert_not_called()

    def test_startup_terminal_or_error_facts_refuse_without_readiness_retry(self):
        ownership = self._owned()
        for state in ({'Status': 'exited'}, {'Status': 'dead'}, {'Error': 'synthetic'},
                      {'Dead': True}, {'Paused': True}, {'Restarting': True}):
            with self.subTest(state=state):
                with (patch.object(self.transport, '_inspect_raw', return_value=self._state(ownership, **state)) as inspect,
                      patch.object(self.cancel, 'wait') as wait,
                      patch.object(subject, '_start_ticks') as ticks):
                    with self.assertRaises(ExtractionError):
                        self.transport.capture_identity(ownership, self.limits, self.deadline, self.cancel)
                self.assertEqual(inspect.call_count, 1)
                wait.assert_not_called()
                ticks.assert_not_called()

    def test_cli_exit_before_readiness_refuses_without_input_or_kernel(self):
        ownership = self._owned()
        attached = SimpleNamespace(poll=lambda: 1)
        with patch.object(subject.subprocess, 'Popen', return_value=attached):
            self.transport.start(ownership, self.deadline, self.cancel)
        with (patch.object(self.transport, '_inspect_raw', return_value=self._state(ownership, True)) as inspect,
              patch.object(self.cancel, 'wait') as wait,
              patch.object(subject, '_start_ticks') as ticks):
            with self.assertRaises(ExtractionError):
                self.transport.capture_identity(ownership, self.limits, self.deadline, self.cancel)
        self.assertLessEqual(inspect.call_count, 1)
        wait.assert_not_called()
        ticks.assert_not_called()

    def test_failed_reap_defers_delete_then_exact_retry_finishes(self):
        ownership = self._owned()
        identity = life.WorkerIdentity(301, 42000, '/owned/cgroup', 19, 821)
        removed = False
        operations = []
        def inspect(*args):
            return None if removed else self._state(ownership, Status='exited')
        def request(method, path, *args):
            nonlocal removed
            operations.append((method, path))
            if method == 'DELETE':
                removed = True
                return 204, b''
            return 200, b'{"StatusCode":0}'
        with (patch.object(self.transport, 'current_daemon', return_value=self.daemon),
              patch.object(self.transport, '_inspect_raw', side_effect=inspect),
              patch.object(self.transport, '_request', side_effect=request),
              patch.object(self.transport, '_gone_and_empty', return_value=(True, True)),
              patch.object(self.transport, '_emergency_stop'),
              patch.object(self.transport, 'reap', side_effect=[False, True])):
            first = self.transport.cleanup(ownership, identity, object(), self.deadline)
            self.assertTrue(first.wait_completed and first.stopped and first.identity_gone and first.cgroup_empty)
            self.assertFalse(first.cli_reaped or first.removed or first.not_found)
            self.assertFalse(removed)
            second = self.transport.cleanup(ownership, identity, object(), self.deadline)
        self.assertTrue(all((second.wait_completed, second.stopped, second.identity_gone,
            second.cgroup_empty, second.cli_reaped, second.removed, second.not_found)))
        self.assertEqual(sum(method == 'DELETE' for method, path in operations), 1)

    def test_delayed_pinned_proof_rechecks_and_removes_within_same_budget(self):
        ownership = self._owned()
        identity = life.WorkerIdentity(301, 42000, '/owned/cgroup', 19, 821)
        removed = False
        observed = []
        operations = []
        def inspect(cid, deadline, cancel):
            observed.append(('inspect', deadline))
            return None if removed else self._state(ownership, Status='exited')
        def request(method, path, body, deadline, cancel):
            nonlocal removed
            operations.append((method, path, deadline))
            if method == 'DELETE':
                removed = True
                return 204, b''
            return 200, b'{"StatusCode":0}'
        with (patch.object(self.transport, 'current_daemon', return_value=self.daemon),
              patch.object(self.transport, '_inspect_raw', side_effect=inspect),
              patch.object(self.transport, '_request', side_effect=request),
              patch.object(self.transport, '_gone_and_empty', side_effect=[(False, False), (True, True)]),
              patch.object(self.transport, '_emergency_stop') as emergency,
              patch.object(self.transport, 'reap', return_value=True)):
            receipt = self.transport.cleanup(ownership, identity, None, self.deadline)
        self.assertTrue(all((receipt.wait_completed, receipt.stopped, receipt.identity_gone,
            receipt.cgroup_empty, receipt.cli_reaped, receipt.removed, receipt.not_found)))
        emergency.assert_called_once()
        self.assertEqual(sum(method == 'DELETE' for method, path, deadline in operations), 1)
        self.assertGreaterEqual(len(observed), 4)  # Initial, stopped, fresh removal, exact404.
        self.assertTrue(all(deadline <= self.deadline for method, path, deadline in operations))

    def test_delayed_proof_does_not_remove_after_fresh_ownership_mismatch(self):
        ownership = self._owned()
        identity = life.WorkerIdentity(301, 42000, '/owned/cgroup', 19, 821)
        stopped = self._state(ownership, Status='exited')
        wrong = dict(stopped, Name='/unrelated')
        with (patch.object(self.transport, 'current_daemon', return_value=self.daemon),
              patch.object(self.transport, '_inspect_raw', side_effect=[stopped, stopped, wrong]),
              patch.object(self.transport, '_request', return_value=(200, b'{"StatusCode":0}')) as request,
              patch.object(self.transport, '_gone_and_empty', side_effect=[(False, False), (True, True)]),
              patch.object(self.transport, '_emergency_stop'),
              patch.object(self.transport, 'reap', return_value=True)):
            receipt = self.transport.cleanup(ownership, identity, None, self.deadline)
        self.assertFalse(receipt.removed or receipt.not_found)
        self.assertFalse(any(call.args[0] == 'DELETE' for call in request.call_args_list))


if __name__ == '__main__':
    unittest.main()
