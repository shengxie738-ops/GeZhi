"""Internal one-shot worker; no application caller or unsandboxed fallback.

Kernel/environment checks are defense in depth, NOT independent certification
of Docker or a replacement for host image/namespace/kill/reap qualification.
The only entrypoint rejects the ordinary host before reading stdin. No env flag,
boolean, caller token or command-line option bypasses bootstrap. Real native
qualification is still required before any deployment can trust this worker.
"""
from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
from hashlib import sha256
import importlib.util
import os
from pathlib import Path
import resource
import stat
import sys

if __package__:
    from . import courseware_wire as wire
else:
    # Isolated Python does not put the script directory on sys.path. This is
    # one fixed image asset path, never cwd or a value supplied by a request.
    sys.path.insert(0, '/opt/parser')
    import courseware_wire as wire

PARSER_SHA256 = '60d12bdda6eeb0c3fb26a9d83748b358a1b3feff31f63257f63952275225db8f'
RUNTIME_ENV = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'LANG': 'C.UTF-8',
               'TZ': 'UTC', 'HOME': '/nonexistent'}
_CGROUP = Path('/sys/fs/cgroup')
_ASSETS = Path('/opt/parser')
_ALLOWED_MOUNTS = frozenset({
    '/', '/proc', '/dev', '/dev/pts', '/sys', '/sys/fs/cgroup',
    '/etc/resolv.conf', '/etc/hostname', '/etc/hosts',
    '/proc/bus', '/proc/fs', '/proc/irq', '/proc/sys', '/proc/sysrq-trigger',
    '/proc/acpi', '/proc/interrupts', '/proc/kcore', '/proc/keys',
    '/proc/latency_stats', '/proc/timer_list', '/proc/scsi', '/sys/firmware',
})

class BootstrapUnavailable(Exception):
    def __init__(self, code='ISOLATION_UNAVAILABLE'):
        self.code = code if code in ('ISOLATION_UNAVAILABLE', 'HARD_LIMITS_UNAVAILABLE') else 'ISOLATION_UNAVAILABLE'
        super().__init__(self.code)

def _read_fixed(path: Path, maximum: int = 65536) -> str:
    with path.open('rb') as stream:
        content = stream.read(maximum+1)
    if len(content) > maximum:
        raise BootstrapUnavailable()
    return content.decode('ascii', errors='strict')

def _positive_number(path: Path) -> int:
    text = _read_fixed(path, 64).strip()
    if not text.isascii() or not text.isdecimal() or len(text) > 12:
        raise BootstrapUnavailable('HARD_LIMITS_UNAVAILABLE')
    return int(text)

def _verify_cgroup_limits(limits: tuple[int, ...]) -> None:
    wire.validate_limits(limits)
    if _positive_number(_CGROUP/'pids.max') != 1:
        raise BootstrapUnavailable('HARD_LIMITS_UNAVAILABLE')
    memory = _positive_number(_CGROUP/'memory.max')
    if not 1 <= memory <= limits[13] or _positive_number(_CGROUP/'memory.swap.max') != 0:
        raise BootstrapUnavailable('HARD_LIMITS_UNAVAILABLE')
    cpu = _read_fixed(_CGROUP/'cpu.max', 64).split()
    if len(cpu) != 2 or any(not x.isdecimal() or len(x)>12 for x in cpu):
        raise BootstrapUnavailable('HARD_LIMITS_UNAVAILABLE')
    quota, period = map(int, cpu)
    if not 1 <= quota <= period <= 1000000:
        raise BootstrapUnavailable('HARD_LIMITS_UNAVAILABLE')

def _verify_environment() -> None:
    # These checks happen before any attacker-controlled byte is consumed.
    if (sys.platform != 'linux' or os.getpid() != 1 or
            os.getuid() != 65532 or os.geteuid() != 65532 or
            os.getgid() != 65532 or os.getegid() != 65532 or
            set(os.getgroups()) - {65532} or not sys.flags.isolated or
            not sys.flags.dont_write_bytecode or dict(os.environ) != RUNTIME_ENV or
            Path(__file__).absolute() != _ASSETS/'courseware_worker.py' or
            Path.cwd() != _ASSETS):
        raise BootstrapUnavailable()
    for path in (_ASSETS, _ASSETS/'courseware_worker.py',
                 _ASSETS/'courseware_wire.py', _ASSETS/'courseware_extract.py'):
        info = path.lstat()
        expected = stat.S_ISDIR(info.st_mode) if path == _ASSETS else stat.S_ISREG(info.st_mode)
        if not expected or info.st_uid != 0 or info.st_mode & 0o022 or (path != _ASSETS and info.st_nlink != 1):
            raise BootstrapUnavailable()
    status = {}
    for line in _read_fixed(Path('/proc/self/status')).splitlines():
        key, sep, value = line.partition(':')
        if sep:
            status[key] = value.strip()
    for field in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb'):
        if not status.get(field) or int(status[field],16) != 0:
            raise BootstrapUnavailable()
    if any(status.get(field) != expected for field, expected in
           (('NoNewPrivs','1'), ('Seccomp','2'), ('Threads','1'))):
        raise BootstrapUnavailable()
    if _read_fixed(Path('/proc/self/cgroup'), 256).strip() != '0::/':
        raise BootstrapUnavailable()
    root_seen = cgroup_seen = False
    for line in _read_fixed(Path('/proc/self/mountinfo')).splitlines():
        before, separator, after = line.partition(' - ')
        values, filesystem = before.split(), after.split()
        if not separator or len(values)<6 or len(filesystem)<3 or values[4] not in _ALLOWED_MOUNTS:
            raise BootstrapUnavailable()
        if values[4] == '/':
            root_seen = 'ro' in values[5].split(',')
        if values[4] == '/sys/fs/cgroup':
            cgroup_seen = filesystem[0]=='cgroup2' and 'ro' in values[5].split(',')
    if not root_seen or not cgroup_seen:
        raise BootstrapUnavailable()
    interfaces = []
    for line in _read_fixed(Path('/proc/net/dev'),4096).splitlines()[2:]:
        if ':' not in line:
            raise BootstrapUnavailable()
        interfaces.append(line.split(':',1)[0].strip())
    if interfaces != ['lo'] or len(_read_fixed(Path('/proc/net/route'),4096).splitlines()) != 1:
        raise BootstrapUnavailable()
    # listdir's temporary fd can appear in its own proc listing, but is closed
    # when listdir returns. Any *live* extra descriptor is rejected.
    live_fds = set()
    for name in os.listdir('/proc/self/fd'):
        if not name.isdecimal():
            raise BootstrapUnavailable()
        try:
            target = os.readlink('/proc/self/fd/'+name)
        except FileNotFoundError:
            continue
        live_fds.add(int(name))
        if int(name) not in (0,1,2) or not target.startswith('pipe:['):
            raise BootstrapUnavailable()
    if live_fds != {0,1,2}:
        raise BootstrapUnavailable()
    _verify_cgroup_limits(wire.LIMIT_CAPS)

def _establish_limits(limits: tuple[int, ...]) -> None:
    """Called after the 69-byte validated header, before body or parser import."""
    wire.validate_limits(limits)
    try:
        settings = ((resource.RLIMIT_AS, limits[13]), (resource.RLIMIT_CPU, limits[12]),
                    (resource.RLIMIT_NOFILE, 32), (resource.RLIMIT_CORE, 0),
                    (resource.RLIMIT_FSIZE, 0))
        for kind, maximum in settings:
            resource.setrlimit(kind, (maximum, maximum))
            if resource.getrlimit(kind) != (maximum, maximum):
                raise BootstrapUnavailable('HARD_LIMITS_UNAVAILABLE')
        _verify_cgroup_limits(limits)
    except (OSError, ValueError, OverflowError):
        raise BootstrapUnavailable('HARD_LIMITS_UNAVAILABLE') from None

def _extract_request(request: wire.WireRequest) -> wire.WireResponse:
    # Sole fixed image copy. Hash is from the accepted dormant foundation.
    path = _ASSETS/'courseware_extract.py'
    with path.open('rb') as source:
        content = source.read(65537)
    if len(content)>65536 or sha256(content).hexdigest()!=PARSER_SHA256:
        raise BootstrapUnavailable()
    spec = importlib.util.spec_from_file_location('_gezhi_courseware_extract', path)
    if spec is None or spec.loader is None:
        raise BootstrapUnavailable()
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    # Execute the exact bytes just hashed. SourceFileLoader.exec_module may
    # read a timestamp-valid .pyc even under -B, or reopen changed source.
    # module_from_spec supplies metadata and registration supports dataclasses.
    exec(compile(content, str(path), 'exec', dont_inherit=True), module.__dict__)
    limits = module.ExtractionLimits(**dict(zip(wire.LIMIT_NAMES, request.limits)))
    try:
        pages = module.extract_pages_untrusted(request.data, request.extension, limits)
    except module.ExtractionError as error:
        return wire.WireResponse(error_code=wire.WireProtocolError(getattr(error,'code',None)).code)
    return wire.WireResponse(tuple(wire.WirePage(page.page,page.text) for page in pages))

@contextmanager
def _discard_parser_diagnostics():
    """Discard Python and native writes without retaining document diagnostics.

    This process-global boundary is only for the single-threaded, one-shot
    worker. Bootstrap's inherited-fd verification must run before it opens fds.
    ExitStack restores every saved descriptor even if setup or parsing fails.
    """
    original_streams = (sys.stdout, sys.stderr, sys.__stdout__, sys.__stderr__)
    with open(os.devnull, 'w', encoding='utf-8') as discard, ExitStack() as restore:
        for target in (1, 2):
            saved = os.dup(target)
            restore.callback(os.close, saved)
            restore.callback(os.dup2, saved, target)
            os.dup2(discard.fileno(), target)
        with redirect_stdout(discard), redirect_stderr(discard):
            try:
                yield
            finally:
                # A dependency can retain the original Python stream object.
                # Flush its finite buffer while fd 1/2 still point to /dev/null.
                for stream in original_streams:
                    if stream is not None:
                        stream.flush()

def _serve_once(source, sink) -> int:
    status = 1
    try:
        try:
            _verify_environment()
        except (OSError, ValueError, UnicodeError):
            raise BootstrapUnavailable() from None
        header = wire.read_request_header(source)
        _establish_limits(header.limits)
        request = wire.read_request_body(source, header)
        with _discard_parser_diagnostics():
            response = _extract_request(request)
        output = wire.encode_response(response, request.limits)
        status = 0 if response.error_code is None else 1
    except BootstrapUnavailable as error:
        output = wire.error_response(error.code); status = 78
    except wire.WireProtocolError as error:
        output = wire.error_response(error.code)
    except MemoryError:
        output = wire.error_response('RESOURCE_LIMIT')
    except Exception:
        output = wire.error_response('EXTRACTION_FAILED')
    try:
        wire.write_all(sink, output)
        sink.flush()
    except Exception:
        # Never append a second frame after a partial failed write.
        return 1
    return status

def main() -> int:
    status = _serve_once(sys.stdin.buffer, sys.stdout.buffer)
    # The protocol frame has been flushed. Keep process-exit hooks and native
    # stdio buffers on /dev/null through interpreter shutdown; a context-only
    # redirect would allow their delayed diagnostics onto the restored pipes.
    try:
        with open(os.devnull, 'wb') as discard:
            os.dup2(discard.fileno(), 1)
            os.dup2(discard.fileno(), 2)
    except Exception:
        # Returning would run exit hooks and flush native stdio onto any pipe
        # whose redirect failed. The frame is already flushed; fail the one-shot
        # process without interpreter teardown or additional output.
        os._exit(1)
    return status

if __name__ == '__main__':
    raise SystemExit(main())
