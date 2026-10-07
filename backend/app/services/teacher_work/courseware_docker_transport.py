"""Dormant fixed-local Docker transport. No application caller or host setup.

This implements bounded operations, not native runtime qualification. HTTP error
bodies and stderr are discarded. Only exact owned IDs can be killed or removed.
Incomplete observations return incomplete cleanup, never invented acknowledgments.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
import os
import re
import selectors
import signal
import socket
import stat
import struct
import subprocess
import threading
import time

from .courseware_extract import ExtractionError, ExtractionLimits
from .courseware_parser_lifecycle import (
    CleanupReceipt, CreateIntent, DaemonIdentity, OwnershipEvidence, WorkerIdentity,
)

SOCKET_PATH = '/var/run/docker.sock'
API = '/v1.51'
CONTROL_CAP = 64 * 1024
HEADER_CAP = 8192
STDERR_CAP = 8192
HOST_ENV = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'LANG': 'C.UTF-8',
            'TZ': 'UTC', 'HOME': '/nonexistent', 'DOCKER_CONFIG': '/nonexistent'}
WORKER_CMD = ['-i', 'PATH=/usr/local/bin:/usr/bin:/bin', 'LANG=C.UTF-8',
              'TZ=UTC', 'HOME=/nonexistent', '/usr/local/bin/python', '-I', '-B',
              '/opt/parser/courseware_worker.py']
_CID = re.compile(r'[0-9a-f]{64}\Z')


@dataclass(frozen=True)
class ProcessResult:
    stdout: bytes = field(repr=False)
    exit_code: int
    stderr_bytes: int


class CreateNotSent(ExtractionError):
    """Transport knows no byte of the create request was sent. Not CLI failure."""
    def __init__(self):
        super().__init__('ISOLATION_UNAVAILABLE')


def _check(deadline: float, cancellation: threading.Event) -> None:
    if cancellation.is_set():
        raise ExtractionError('RUNNER_FAILED')
    if time.monotonic() >= deadline:
        raise TimeoutError()


def _json(raw: bytes):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError()
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=pairs)
    except (ValueError, UnicodeError, RecursionError):
        raise ExtractionError('ISOLATION_UNAVAILABLE') from None


def _kernel(path: str, maximum: int) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        result = os.read(fd, maximum + 1)
        if len(result) > maximum:
            raise ExtractionError('ISOLATION_UNAVAILABLE')
        return result
    finally:
        os.close(fd)


def _start_ticks(pid: int) -> int:
    raw = _kernel(f'/proc/{pid}/stat', 4096)
    try:
        return int(raw[raw.rindex(b')') + 2:].split()[19])
    except (ValueError, IndexError):
        raise ExtractionError('ISOLATION_UNAVAILABLE') from None


def _close_owned(descriptors):
    """Consume each slot once even if close reports an uncertain error."""
    failed = False
    for fd in descriptors:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                failed = True
    if failed:
        raise ExtractionError('ISOLATION_UNAVAILABLE')


def _belongs(data, ownership):
    return (type(data) is dict and data.get('Id') == ownership.container_id and
            data.get('Name') == '/' + ownership.name and data.get('Image') == ownership.image_id and
            data.get('Config', {}).get('Labels', {}).get('gezhi.parser.owner') == ownership.owner_token)


class _Reader:
    def __init__(self, sock, deadline, cancellation):
        self.sock, self.deadline, self.cancellation = sock, deadline, cancellation
        self.buffer = bytearray()

    def recv(self, count):
        while True:
            _check(self.deadline, self.cancellation)
            self.sock.settimeout(min(.05, max(.001, self.deadline - time.monotonic())))
            try:
                return self.sock.recv(min(count, 65536))
            except socket.timeout:
                continue

    def exact(self, count):
        result = bytearray()
        while len(result) < count:
            if self.buffer:
                n = min(count - len(result), len(self.buffer))
                result.extend(self.buffer[:n])
                del self.buffer[:n]
            else:
                data = self.recv(min(4096, count - len(result)))
                if not data:
                    raise ExtractionError('ISOLATION_UNAVAILABLE')
                result.extend(data)
        return bytes(result)

    def line(self, maximum):
        while True:
            index = self.buffer.find(b'\r\n')
            if index >= 0:
                if index + 2 > maximum:
                    raise ExtractionError('OUTPUT_LIMIT')
                result = bytes(self.buffer[:index + 2])
                del self.buffer[:index + 2]
                return result
            if len(self.buffer) >= maximum:
                raise ExtractionError('OUTPUT_LIMIT')
            data = self.recv(min(4096, maximum - len(self.buffer)))
            if not data:
                raise ExtractionError('ISOLATION_UNAVAILABLE')
            self.buffer.extend(data)


class DockerTransport:
    """One owner/session, fixed executable/socket. Constructor performs no IO."""
    def __init__(self):
        self._peer = None
        self._expected_peer = None
        self._watches = {}
        self._starts = {}

    def _connect(self, deadline, cancellation):
        _check(deadline, cancellation)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            before = os.stat(SOCKET_PATH)
            if not stat.S_ISSOCK(before.st_mode):
                raise ExtractionError('ISOLATION_UNAVAILABLE')
            sock.settimeout(min(.1, max(.001, deadline - time.monotonic())))
            sock.connect(SOCKET_PATH)
            pid, uid, gid = struct.unpack('3i', sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            after = os.stat(SOCKET_PATH)
            if pid <= 0 or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                raise ExtractionError('ISOLATION_UNAVAILABLE')
            self._peer = (before.st_dev, before.st_ino, pid, uid, gid, _start_ticks(pid))
            if self._expected_peer is not None and self._peer != self._expected_peer:
                raise ExtractionError('ISOLATION_UNAVAILABLE')
            return sock
        except BaseException:
            sock.close()
            raise

    def _request(self, method, path, body, deadline, cancellation):
        """Internal finite HTTP/1.x; no redirects/retry/auth/config or diagnostics."""
        creating = method == 'POST' and path.startswith(API + '/containers/create?name=')
        sock = None
        sent = 0
        try:
            _check(deadline, cancellation)
            if method not in ('GET', 'POST', 'DELETE') or not re.fullmatch(r'/v1\.51/[A-Za-z0-9_/?=.-]+', path):
                raise ExtractionError('INVALID_INPUT')
            payload = b'' if body is None else body
            if type(payload) is not bytes or len(payload) > CONTROL_CAP:
                raise ExtractionError('INVALID_INPUT')
            header = (f'{method} {path} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n'
                f'Content-Length: {len(payload)}\r\n' +
                ('Content-Type: application/json\r\n' if payload else '') + '\r\n').encode('ascii')
            sock = self._connect(deadline, cancellation)
            for part in (header, payload):
                view = memoryview(part)
                while view:
                    _check(deadline, cancellation)
                    sock.settimeout(min(.05, max(.001, deadline - time.monotonic())))
                    try:
                        n = sock.send(view[:65536])
                    except socket.timeout:
                        continue
                    if type(n) is not int or not 1 <= n <= len(view):
                        raise ExtractionError('ISOLATION_UNAVAILABLE')
                    sent += n
                    view = view[n:]
            reader = _Reader(sock, deadline, cancellation)
            line = reader.line(HEADER_CAP)
            match = re.fullmatch(rb'HTTP/1\.[01] ([0-9]{3}) [^\r\n]*\r\n', line)
            if match is None:
                raise ExtractionError('ISOLATION_UNAVAILABLE')
            status = int(match[1])
            headers, used = {}, len(line)
            while True:
                line = reader.line(HEADER_CAP - used)
                used += len(line)
                if line == b'\r\n':
                    break
                key, sep, value = line[:-2].partition(b':')
                key = key.lower()
                if not sep or key in headers or not re.fullmatch(rb'[a-z0-9-]+', key):
                    raise ExtractionError('ISOLATION_UNAVAILABLE')
                headers[key] = value.strip()
            length, chunked = headers.get(b'content-length'), headers.get(b'transfer-encoding')
            if (length is not None and chunked is not None) or (chunked is not None and chunked != b'chunked'):
                raise ExtractionError('ISOLATION_UNAVAILABLE')
            output, consumed = bytearray(), 0
            def consume(data):
                nonlocal consumed
                consumed += len(data)
                if consumed > CONTROL_CAP:
                    raise ExtractionError('OUTPUT_LIMIT')
                if 200 <= status < 300:
                    output.extend(data)
            if length is not None:
                if not length.isdigit() or len(length) > 9 or int(length) > CONTROL_CAP:
                    raise ExtractionError('OUTPUT_LIMIT')
                remaining = int(length)
                while remaining:
                    data = reader.exact(min(4096, remaining))
                    consume(data)
                    remaining -= len(data)
            elif chunked:
                framing = 0
                while True:
                    line = reader.line(64)
                    framing += len(line)
                    if framing > HEADER_CAP or not re.fullmatch(rb'[0-9a-fA-F]{1,8}\r\n', line):
                        raise ExtractionError('OUTPUT_LIMIT')
                    count = int(line[:-2], 16)
                    if count > CONTROL_CAP - consumed:
                        raise ExtractionError('OUTPUT_LIMIT')
                    if count == 0:
                        if reader.line(2) != b'\r\n':
                            raise ExtractionError('ISOLATION_UNAVAILABLE')
                        break
                    consume(reader.exact(count))
                    if reader.exact(2) != b'\r\n':
                        raise ExtractionError('ISOLATION_UNAVAILABLE')
                    framing += 2
            elif status not in (204, 304):
                if reader.buffer:
                    consume(bytes(reader.buffer))
                    reader.buffer.clear()
                while True:
                    data = reader.recv(min(4096, CONTROL_CAP - consumed + 1))
                    if not data:
                        break
                    consume(data)
            return status, bytes(output)
        except BaseException as error:
            if creating and sent == 0:
                raise CreateNotSent() from None
            if isinstance(error, (ExtractionError, TimeoutError, KeyboardInterrupt, SystemExit)):
                raise
            raise ExtractionError('ISOLATION_UNAVAILABLE') from None
        finally:
            if sock is not None:
                sock.close()

    def current_daemon(self, deadline, cancellation):
        status, raw = self._request('GET', API + '/info', None, deadline, cancellation)
        data = _json(raw) if status == 200 else {}
        if (type(data) is not dict or data.get('OSType') != 'linux' or
                data.get('Architecture') not in ('amd64', 'x86_64') or
                data.get('CgroupVersion') != '2' or
                not all(data.get(k) is True for k in ('MemoryLimit', 'SwapLimit', 'CpuCfsPeriod', 'CpuCfsQuota', 'PidsLimit')) or
                'name=seccomp,profile=builtin' not in data.get('SecurityOptions', ()) or self._peer is None):
            raise ExtractionError('HARD_LIMITS_UNAVAILABLE')
        fingerprint = sha256(json.dumps(self._peer, separators=(',', ':')).encode()).hexdigest()
        daemon = DaemonIdentity(data.get('ID'), fingerprint)
        self._expected_peer = self._peer
        return daemon

    @staticmethod
    def _recipe(intent, limits):
        if type(intent) is not CreateIntent or type(limits) is not ExtractionLimits:
            raise ExtractionError('INVALID_INPUT')
        intent.__post_init__()
        limits.__post_init__()
        return {
            'Image': intent.image_id, 'User': '65532:65532', 'WorkingDir': '/opt/parser',
            'Entrypoint': ['/usr/bin/env'], 'Cmd': list(WORKER_CMD),
            'OpenStdin': True, 'StdinOnce': True, 'AttachStdin': True,
            'AttachStdout': True, 'AttachStderr': True, 'Tty': False,
            'Labels': {'gezhi.parser.owner': intent.owner_token},
            'HostConfig': {'NetworkMode': 'none', 'ReadonlyRootfs': True,
                'CapDrop': ['ALL'], 'CapAdd': [], 'SecurityOpt': ['no-new-privileges'],
                'PidsLimit': 1, 'CpuPeriod': 100000, 'CpuQuota': 100000,
                'Memory': limits.max_memory_bytes, 'MemorySwap': limits.max_memory_bytes,
                'CgroupnsMode': 'private', 'IpcMode': 'private', 'PidMode': '',
                'UTSMode': '', 'Privileged': False, 'AutoRemove': False,
                'RestartPolicy': {'Name': 'no'}, 'LogConfig': {'Type': 'none'}},
        }

    def create(self, intent, limits, deadline, cancellation):
        body = json.dumps(self._recipe(intent, limits), separators=(',', ':')).encode()
        status, raw = self._request('POST', API + '/containers/create?name=' + intent.name,
            body, deadline, cancellation)
        data = _json(raw) if status == 201 else {}
        cid = data.get('Id') if type(data) is dict else None
        if type(cid) is not str or _CID.fullmatch(cid) is None:
            # Even a CLI / server rejection is ambiguous without pre-create proof.
            raise ExtractionError('ISOLATION_UNAVAILABLE')
        return cid

    def _inspect_raw(self, cid, deadline, cancellation):
        if type(cid) is not str or _CID.fullmatch(cid) is None:
            raise ExtractionError('INVALID_INPUT')
        status, raw = self._request('GET', API + '/containers/' + cid + '/json',
            None, deadline, cancellation)
        if status == 404:
            return None
        if status != 200:
            raise ExtractionError('ISOLATION_UNAVAILABLE')
        data = _json(raw)
        if type(data) is not dict or data.get('Id') != cid:
            raise ExtractionError('ISOLATION_UNAVAILABLE')
        return data

    def inspect(self, intent, cid, limits, deadline, cancellation):
        if self.current_daemon(deadline, cancellation) != intent.daemon:
            raise ExtractionError('ISOLATION_UNAVAILABLE')
        data = self._inspect_raw(cid, deadline, cancellation)
        recipe = self._recipe(intent, limits)
        if data is None:
            raise ExtractionError('ISOLATION_UNAVAILABLE')
        config, host = data.get('Config', {}), data.get('HostConfig', {})
        keys = ('User', 'WorkingDir', 'Entrypoint', 'Cmd', 'OpenStdin', 'StdinOnce', 'Tty')
        if (data.get('Image') != intent.image_id or data.get('Name') != '/' + intent.name or
                config.get('Labels', {}).get('gezhi.parser.owner') != intent.owner_token or
                any(config.get(k) != recipe[k] for k in keys) or
                any(host.get(k) != v for k, v in recipe['HostConfig'].items() if k not in ('RestartPolicy', 'LogConfig')) or
                host.get('RestartPolicy', {}).get('Name') != 'no' or
                host.get('LogConfig', {}).get('Type') != 'none' or
                any(host.get(k) for k in ('Binds', 'Mounts', 'Devices', 'DeviceRequests', 'VolumesFrom')) or
                data.get('Mounts')):
            raise ExtractionError('ISOLATION_UNAVAILABLE')
        return OwnershipEvidence(cid, intent.name, intent.owner_token, intent.image_id, intent.daemon)

    def start(self, ownership, deadline, cancellation):
        ownership.__post_init__()
        _check(deadline, cancellation)
        attached = subprocess.Popen(['/usr/local/bin/docker', '--host', 'unix://' + SOCKET_PATH,
            'start', '--attach', '--interactive', ownership.container_id],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=dict(HOST_ENV), close_fds=True, shell=False, bufsize=0)
        self._starts[ownership.container_id] = (ownership, attached)
        return attached

    @staticmethod
    def reap(attached):
        if attached is None:
            return True
        try:
            if attached.poll() is None:
                attached.kill()
        finally:
            for stream in (attached.stdin, attached.stdout, attached.stderr):
                if stream is not None and not stream.closed:
                    stream.close()
        try:
            attached.wait(timeout=1)
            return True
        except (OSError, TimeoutError, subprocess.TimeoutExpired):
            return False

    def exchange(self, attached, data, stdout_cap, deadline, cancellation):
        output, diagnostics, offset = bytearray(), 0, 0
        try:
            if (type(data) is not bytes or len(data) > 69 + 10 * 1024 * 1024 or
                    type(stdout_cap) is not int or not 43 <= stdout_cap <= 1049787):
                raise ExtractionError('INVALID_INPUT')
            with selectors.DefaultSelector() as selector:
                for stream, kind in ((attached.stdin, 'input'), (attached.stdout, 'output'), (attached.stderr, 'error')):
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_WRITE if kind == 'input' else selectors.EVENT_READ, kind)
                while selector.get_map():
                    _check(deadline, cancellation)
                    for key, mask in selector.select(min(.05, max(.001, deadline - time.monotonic()))):
                        stream, kind = key.fileobj, key.data
                        try:
                            if kind == 'input':
                                n = os.write(stream.fileno(), memoryview(data)[offset:offset + 65536])
                                if n <= 0:
                                    raise ExtractionError('RUNNER_FAILED')
                                offset += n
                                if offset == len(data):
                                    selector.unregister(stream)
                                    stream.close()
                            else:
                                cap = stdout_cap if kind == 'output' else STDERR_CAP
                                used = len(output) if kind == 'output' else diagnostics
                                chunk = os.read(stream.fileno(), min(65536, cap - used + 1))
                                if not chunk:
                                    selector.unregister(stream)
                                elif len(chunk) > cap - used:
                                    raise ExtractionError('OUTPUT_LIMIT')
                                elif kind == 'output':
                                    output.extend(chunk)
                                else:
                                    diagnostics += len(chunk)
                        except BlockingIOError:
                            continue
                while attached.poll() is None:
                    _check(deadline, cancellation)
                    time.sleep(.005)
                _check(deadline, cancellation)
                return ProcessResult(bytes(output), attached.poll(), diagnostics)
        except (BrokenPipeError, OSError):
            raise ExtractionError('RUNNER_FAILED') from None
        finally:
            if not self.reap(attached):
                raise ExtractionError('ISOLATION_UNAVAILABLE')

    def capture_identity(self, ownership, limits, deadline, cancellation):
        ownership.__post_init__()
        # Popen only starts the fixed CLI; it does not acknowledge container
        # readiness. Every retry uses the original absolute job deadline and
        # revalidates exact ownership before considering any readiness fact.
        while True:
            _check(deadline, cancellation)
            started = self._starts.get(ownership.container_id)
            if started is not None and (started[0] != ownership or started[1].poll() is not None):
                raise ExtractionError('ISOLATION_UNAVAILABLE')
            data = self._inspect_raw(ownership.container_id, deadline, cancellation)
            _check(deadline, cancellation)
            if not _belongs(data, ownership):
                raise ExtractionError('ISOLATION_UNAVAILABLE')
            state = data.get('State')
            if (type(state) is not dict or type(state.get('Running')) is not bool or
                    type(state.get('Pid')) is not int or state['Pid'] < 0 or
                    state.get('Error') or state.get('Dead') or state.get('Paused') or
                    state.get('Restarting') or
                    state.get('Status') not in (None, 'created', 'running')):
                raise ExtractionError('ISOLATION_UNAVAILABLE')
            if started is not None and started[1].poll() is not None:
                raise ExtractionError('ISOLATION_UNAVAILABLE')
            if state['Running'] and state['Pid'] > 0:
                pid = state['Pid']
                break
            if not state['Running'] and state['Pid'] != 0:
                raise ExtractionError('ISOLATION_UNAVAILABLE')
            _check(deadline, cancellation)
            cancellation.wait(min(.01, max(0, deadline - time.monotonic())))
        _check(deadline, cancellation)
        ticks = _start_ticks(pid)
        raw = _kernel(f'/proc/{pid}/cgroup', 2048).decode('ascii').strip()
        if not raw.startswith('0::/') or '\n' in raw:
            raise ExtractionError('ISOLATION_UNAVAILABLE')
        path = raw[3:]
        if path == '/' or any(p in ('', '.', '..') for p in path[1:].split('/')):
            raise ExtractionError('ISOLATION_UNAVAILABLE')
        WorkerIdentity(pid, ticks, path, 0, 1)
        directory = os.open('/sys/fs/cgroup', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
        event_fd = pid_fd = -1
        try:
            for part in path[1:].split('/'):
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory)
                previous, directory = directory, child
                os.close(previous)
            info = os.fstat(directory)
            identity = WorkerIdentity(pid, ticks, path, info.st_dev, info.st_ino)
            status = _kernel(f'/proc/{pid}/status', 65536).decode('ascii')
            observed = dict(line.split(':', 1) for line in status.splitlines() if ':' in line)
            if (any(int(observed.get(k, '1').strip(), 16) for k in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb')) or
                    any(observed.get(k, '').strip() != v for k, v in (('NoNewPrivs', '1'), ('Seccomp', '2'), ('Threads', '1')))):
                raise ExtractionError('ISOLATION_UNAVAILABLE')
            for ns in ('mnt', 'pid', 'net', 'ipc', 'uts', 'cgroup'):
                if os.readlink(f'/proc/{pid}/ns/{ns}') == os.readlink(f'/proc/self/ns/{ns}'):
                    raise ExtractionError('ISOLATION_UNAVAILABLE')
            def control(name):
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory)
                try:
                    value = os.read(fd, 257)
                    if len(value) > 256:
                        raise ExtractionError('HARD_LIMITS_UNAVAILABLE')
                    return value.decode('ascii').strip()
                finally:
                    os.close(fd)
            cpu = control('cpu.max').split()
            if (control('pids.max') != '1' or control('memory.swap.max') != '0' or
                    not control('memory.max').isdigit() or not 1 <= int(control('memory.max')) <= limits.max_memory_bytes or
                    len(cpu) != 2 or not all(x.isdigit() for x in cpu) or not 1 <= int(cpu[0]) <= int(cpu[1]) <= 1000000):
                raise ExtractionError('HARD_LIMITS_UNAVAILABLE')
            event_fd = os.open('cgroup.events', os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory)
            if not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
                raise ExtractionError('ISOLATION_UNAVAILABLE')
            pid_fd = os.pidfd_open(pid, 0)
            # Permission observation only, before document input. No granting or
            # numeric-PID fallback; a denied signal path prevents streaming.
            signal.pidfd_send_signal(pid_fd, 0)
            if _start_ticks(pid) != ticks:
                raise ExtractionError('ISOLATION_UNAVAILABLE')
            _check(deadline, cancellation)
            if ownership.container_id in self._watches:
                raise ExtractionError('ISOLATION_UNAVAILABLE')
            self._watches[ownership.container_id] = (identity, directory, event_fd, pid_fd)
            directory = event_fd = pid_fd = -1
            return identity
        finally:
            _close_owned((pid_fd, event_fd, directory))

    def _gone_and_empty(self, cid, identity):
        watch = self._watches.get(cid)
        if identity is None or watch is None or watch[0] != identity:
            return None if identity is None else False, False
        try:
            try:
                gone = _start_ticks(identity.pid) != identity.start_time_ticks
            except FileNotFoundError:
                gone = True
            info = os.fstat(watch[1])
            raw = os.pread(watch[2], 257, 0)
            values = dict(line.split() for line in raw.splitlines()) if len(raw) <= 256 else {}
            empty = ((info.st_dev, info.st_ino) == (identity.cgroup_device, identity.cgroup_inode)
                     and values.get(b'populated') == b'0')
            return gone, empty
        except (OSError, ValueError):
            return False, False

    def cleanup(self, ownership, identity, attached, deadline):
        """Fresh job-independent cancellation; exact observations, no name lookup."""
        cancellation = threading.Event()
        ownership.__post_init__()
        try:
            cli_reaped = self.reap(attached)
        except Exception:
            cli_reaped = False
        wait_completed = stopped = removed = not_found = exit_observed = False
        gone, empty = None if identity is None else False, False
        # Reserve part of the finite cleanup budget for the pinned local signal
        # path. A daemon timeout must not consume the entire termination budget.
        control_deadline = max(time.monotonic(), deadline - 1)
        try:
            if self.current_daemon(control_deadline, cancellation) != ownership.daemon:
                raise ExtractionError('ISOLATION_UNAVAILABLE')
            data = self._inspect_raw(ownership.container_id, control_deadline, cancellation)
            if data is None:
                raise ExtractionError('ISOLATION_UNAVAILABLE')
            if not _belongs(data, ownership):
                raise ExtractionError('ISOLATION_UNAVAILABLE')
            if data.get('State', {}).get('Running') is True:
                status, _ = self._request('POST', API + '/containers/' + ownership.container_id + '/kill?signal=KILL',
                    None, control_deadline, cancellation)
                if status not in (204, 409):
                    raise ExtractionError('ISOLATION_UNAVAILABLE')
            status, raw = self._request('POST', API + '/containers/' + ownership.container_id + '/wait?condition=not-running',
                None, control_deadline, cancellation)
            waited = _json(raw) if status == 200 else {}
            wait_completed = (type(waited) is dict and type(waited.get('StatusCode')) is int
                              and 0 <= waited['StatusCode'] <= 255 and not waited.get('Error'))
            exit_observed = wait_completed
            data = self._inspect_raw(ownership.container_id, control_deadline, cancellation)
            if not _belongs(data, ownership):
                raise ExtractionError('ISOLATION_UNAVAILABLE')
            stopped = data is not None and data.get('State', {}).get('Running') is False and data.get('State', {}).get('Pid') == 0
            gone, empty = self._gone_and_empty(ownership.container_id, identity)
        except (Exception,):
            # Partial facts remain partial. Never echo server or host diagnostics.
            pass
        finally:
            if identity is not None and not (stopped and wait_completed and gone and empty):
                # Retain a final control window in this same absolute budget so
                # delayed pinned exit evidence can still lead to exact removal.
                self._emergency_stop(ownership.container_id, identity, deadline - .2)
                gone, empty = self._gone_and_empty(ownership.container_id, identity)
            # Failed reap must not erase the daemon's wait/stopped facts via
            # DELETE/404. The next exact-owner cleanup can reap and observe again.
            if cli_reaped and stopped and wait_completed and (identity is None or (gone and empty)):
                try:
                    _check(deadline, cancellation)
                    if self.current_daemon(deadline, cancellation) != ownership.daemon:
                        raise ExtractionError('ISOLATION_UNAVAILABLE')
                    data = self._inspect_raw(ownership.container_id, deadline, cancellation)
                    if (not _belongs(data, ownership) or
                            data.get('State', {}).get('Running') is not False or
                            data.get('State', {}).get('Pid') != 0):
                        raise ExtractionError('ISOLATION_UNAVAILABLE')
                    status, _ = self._request('DELETE', API + '/containers/' + ownership.container_id,
                        None, deadline, cancellation)
                    removed = status == 204
                    not_found = removed and self._inspect_raw(ownership.container_id, deadline, cancellation) is None
                except Exception:
                    pass
            # Preserve exact observation handles while cleanup is incomplete.
            # A retry must not reconstruct evidence from a recycled path.
            if all((wait_completed, stopped, removed, not_found, empty, cli_reaped,
                    gone if identity is not None else True, exit_observed)):
                watch = self._watches.pop(ownership.container_id, None)
                self._starts.pop(ownership.container_id, None)
                if watch is not None:
                    _close_owned(watch[1:])
        return CleanupReceipt(ownership.container_id, wait_completed, stopped, removed,
            not_found, empty, cli_reaped, gone, exit_observed, identity)

    def _emergency_stop(self, cid, identity, deadline):
        """Attempt exact pinned process termination; never assert daemon cleanup."""
        watch = self._watches.get(cid)
        if watch is None or watch[0] != identity or len(watch) != 4:
            return
        try:
            signal.pidfd_send_signal(watch[3], signal.SIGKILL)
        except ProcessLookupError:
            pass
        except (OSError, ValueError):
            return
        while time.monotonic() < deadline:
            gone, empty = self._gone_and_empty(cid, identity)
            if gone and empty:
                return
            time.sleep(min(.01, max(0, deadline - time.monotonic())))
