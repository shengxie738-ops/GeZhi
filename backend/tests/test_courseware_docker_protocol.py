"""Offline codec/bootstrap tests only; never proof of Docker confinement."""
from dataclasses import fields
from importlib import import_module
from io import BytesIO, StringIO
import struct
import os
import sys
import tempfile
import subprocess
import importlib.util
import importlib._bootstrap_external
from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
from types import SimpleNamespace
from pathlib import Path
import unittest
from unittest.mock import patch
try:
    wire=import_module('parser_worker.courseware_wire')
    worker=import_module('parser_worker.courseware_worker')
except ModuleNotFoundError:
    wire=worker=None

class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(wire,'bounded wire implementation missing')
        self.assertIsNotNone(worker,'worker bootstrap implementation missing')
        self.limits=tuple(wire.LIMIT_CAPS)
    def request(self,data=b'%PDF-owned',extension='.pdf',limits=None):
        return wire.WireRequest(extension,limits or self.limits,data)
    def test_contract_parity_header_roundtrip(self):
        from app.services.teacher_work import courseware_extract as old
        self.assertEqual(wire.LIMIT_NAMES,tuple(f.name for f in fields(old.ExtractionLimits)))
        self.assertEqual(wire.LIMIT_CAPS,tuple(old._LIMIT_CAPS.values()))
        self.assertEqual(wire.ERROR_CODES,old._ERROR_CODES)
        for ext in ('.pdf','.pptx'):
            value=self.request(extension=ext);encoded=wire.encode_request(value)
            self.assertEqual(len(encoded),69+len(value.data))
            self.assertEqual(wire.read_request(BytesIO(encoded)),value)
    def test_exact_types_limits(self):
        for value in (True,0,-1,2**32,'1'):
            limits=list(self.limits);limits[0]=value
            with self.subTest(value=value),self.assertRaises(wire.WireProtocolError):wire.encode_request(self.request(limits=tuple(limits)))
        for data in ('text',bytearray(b'a'),b''):
            with self.assertRaises(wire.WireProtocolError):wire.encode_request(self.request(data=data))
        for ext in ('pdf','.PDF','.ppt',None):
            with self.assertRaises(wire.WireProtocolError):wire.encode_request(self.request(extension=ext))
    def test_header_stops_before_body(self):
        source=BytesIO(wire.encode_request(self.request()));header=wire.read_request_header(source)
        self.assertEqual(source.tell(),69)
        self.assertEqual(wire.read_request_body(source,header),self.request())
    def test_request_malformed_and_bounded_short_reads(self):
        encoded=wire.encode_request(self.request())
        class Short(BytesIO):
            def read(self,n=-1):
                if not 0<n<=65536:raise AssertionError('unbounded read')
                return super().read(min(n,2))
        self.assertEqual(wire.read_request(Short(encoded)),self.request())
        cases=[encoded[:n] for n in range(len(encoded))]+[encoded+b'x',encoded+encoded,b'BADMAGIC'+encoded[8:],encoded[:8]+b'\3'+encoded[9:],encoded[:9]+struct.pack('>I',0xffffffff)+encoded[13:]]
        for value in cases:
            with self.subTest(length=len(value)),self.assertRaises(wire.WireProtocolError):wire.read_request(BytesIO(value))
    def test_responses_roundtrip_and_error_floor(self):
        value=wire.WireResponse((wire.WirePage(1,'汉字'),wire.WirePage(2,'')))
        self.assertEqual(wire.read_response(BytesIO(wire.encode_response(value,self.limits)),self.limits),value)
        tiny=list(self.limits);tiny[1]=1;tiny[4]=1
        self.assertEqual(wire.response_transport_cap(tuple(tiny)),43)
        for code in wire.ERROR_CODES:
            blob=wire.error_response(code);self.assertLessEqual(len(blob),43)
            self.assertEqual(wire.read_response(BytesIO(blob),self.limits).error_code,code)
        self.assertEqual(wire.read_response(BytesIO(wire.error_response('secret')),self.limits).error_code,'EXTRACTION_FAILED')
    def test_response_page_and_text_validation(self):
        for pages in ((),[],(wire.WirePage(True,'a'),),(wire.WirePage(2,'a'),),(wire.WirePage(1,' '),),(wire.WirePage(1,'\ud800'),)):
            with self.assertRaises(wire.WireProtocolError):wire.encode_response(wire.WireResponse(pages),self.limits)
        with self.assertRaises(wire.WireProtocolError):wire.encode_response(wire.WireResponse((wire.WirePage(1,'a'),),'CORRUPT_SOURCE'),self.limits)
        for index,value in ((1,1),(2,1),(3,1),(4,2)):
            limits=list(self.limits);limits[index]=value
            with self.assertRaises(wire.WireProtocolError):wire.encode_response(wire.WireResponse((wire.WirePage(1,'汉字'),wire.WirePage(2,'b'))),tuple(limits))
    def test_response_malformed_and_writes(self):
        valid=wire.encode_response(wire.WireResponse((wire.WirePage(1,'a'),)),self.limits)
        cases=[valid[:n] for n in range(len(valid))]+[valid+b'x',valid+valid,valid[:8]+b'\x99'+valid[9:],valid[:13]+struct.pack('>I',0xffffffff)+valid[17:],valid[:-1]+b'\xff']
        for value in cases:
            with self.assertRaises(wire.WireProtocolError):wire.read_response(BytesIO(value),self.limits)
        class Short(BytesIO):
            def write(self,data):return super().write(data[:2])
        out=Short();wire.write_all(out,valid);self.assertEqual(out.getvalue(),valid)
        class Broken:
            def write(self,data):return None
        with self.assertRaises(wire.WireProtocolError):wire.write_all(Broken(),valid)
    def test_real_default_host_refusal_before_input(self):
        class NoRead:
            def read(self,n):raise AssertionError('host worker read input')
        out=BytesIO()
        with patch.object(worker,'_extract_request',side_effect=AssertionError('no parser')):self.assertEqual(worker._serve_once(NoRead(),out),78)
        self.assertEqual(wire.read_response(BytesIO(out.getvalue()),self.limits).error_code,'ISOLATION_UNAVAILABLE')
    def test_environment_header_limits_body_parser_order(self):
        events=[]
        class Observed(BytesIO):
            def read(self,n):events.append(('read',self.tell(),n));return super().read(n)
        source=Observed(wire.encode_request(self.request()))
        def environment():events.append(('environment',))
        def limits(value):self.assertEqual(source.tell(),69);events.append(('limits',))
        def extract(value):events.append(('extract',));return wire.WireResponse((wire.WirePage(1,'owned'),))
        with patch.object(worker,'_verify_environment',environment),patch.object(worker,'_establish_limits',limits),patch.object(worker,'_extract_request',extract):self.assertEqual(worker._serve_once(source,BytesIO()),0)
        self.assertEqual(events[0],('environment',));i=events.index(('limits',));j=events.index(('extract',))
        self.assertTrue(all(x[1]<69 for x in events[1:i] if x[0]=='read'))
        self.assertTrue(any(x[0]=='read' and x[1]==69 for x in events[i:j]))
    def test_limit_failure_stops_body(self):
        source=BytesIO(wire.encode_request(self.request()));out=BytesIO()
        with patch.object(worker,'_verify_environment'),patch.object(worker,'_establish_limits',side_effect=worker.BootstrapUnavailable('HARD_LIMITS_UNAVAILABLE')),patch.object(worker,'_extract_request',side_effect=AssertionError('no parser')):self.assertEqual(worker._serve_once(source,out),78)
        self.assertEqual(source.tell(),69)
    def test_resource_hard_soft_establishment(self):
        actual={}
        def setlimit(kind,value):actual[kind]=value
        def getlimit(kind):return actual.get(kind,(self.limits[12],self.limits[12]))
        with patch.object(worker.resource,'setrlimit',setlimit),patch.object(worker.resource,'getrlimit',getlimit),patch.object(worker,'_verify_cgroup_limits') as verify:worker._establish_limits(self.limits)
        self.assertEqual(actual[worker.resource.RLIMIT_AS],(self.limits[13],)*2)
        self.assertEqual(actual[worker.resource.RLIMIT_CPU],(self.limits[12],)*2)
        verify.assert_called_once_with(self.limits)
    def test_worker_exception_sanitized(self):
        out=BytesIO()
        with patch.object(worker,'_verify_environment'),patch.object(worker,'_establish_limits'),patch.object(worker,'_extract_request',side_effect=RuntimeError('SECRET')):self.assertEqual(worker._serve_once(BytesIO(wire.encode_request(self.request())),out),1)
        self.assertNotIn(b'SECRET',out.getvalue())
        self.assertEqual(wire.read_response(BytesIO(out.getvalue()),self.limits).error_code,'EXTRACTION_FAILED')
    def kernel_fixture(self, *, changes=None, fds=('0','1','2')):
        texts={
            '/proc/self/status':'CapInh: 0\nCapPrm: 0\nCapEff: 0\nCapBnd: 0\nCapAmb: 0\nNoNewPrivs: 1\nSeccomp: 2\nThreads: 1\n',
            '/proc/self/cgroup':'0::/\n',
            '/proc/self/mountinfo':'1 0 0:1 / / ro - overlay overlay ro\n2 1 0:2 / /sys/fs/cgroup ro - cgroup2 cgroup ro\n',
            '/proc/net/dev':'header\nheader\n lo: 0 0 0\n',
            '/proc/net/route':'header\n',
            '/sys/fs/cgroup/pids.max':'1', '/sys/fs/cgroup/memory.max':str(self.limits[13]),
            '/sys/fs/cgroup/memory.swap.max':'0','/sys/fs/cgroup/cpu.max':'100000 100000',
        }
        texts.update(changes or {})
        stack=ExitStack()
        def fake_stat(path):return SimpleNamespace(st_mode=0o40555 if path==Path('/opt/parser') else 0o100444,st_uid=0,st_nlink=1)
        stack.enter_context(patch.object(worker,'_read_fixed',side_effect=lambda path,*args:texts[str(path)]))
        stack.enter_context(patch.object(worker,'__file__','/opt/parser/courseware_worker.py'))
        stack.enter_context(patch.object(worker.sys,'flags',SimpleNamespace(isolated=1,dont_write_bytecode=1)))
        stack.enter_context(patch.dict(worker.os.environ,worker.RUNTIME_ENV,clear=True))
        for name,value in (('getpid',1),('getuid',65532),('geteuid',65532),('getgid',65532),('getegid',65532)):
            stack.enter_context(patch.object(worker.os,name,return_value=value))
        stack.enter_context(patch.object(worker.os,'getgroups',return_value=[65532]))
        stack.enter_context(patch.object(Path,'cwd',return_value=Path('/opt/parser')))
        stack.enter_context(patch.object(Path,'lstat',fake_stat))
        stack.enter_context(patch.object(worker.os,'listdir',return_value=list(fds)))
        stack.enter_context(patch.object(worker.os,'readlink',return_value='pipe:[123]'))
        return stack
    def test_real_environment_verifier_accepts_only_exact_observations(self):
        # Kernel syscalls are replaced, not the production verifier. This tests
        # acceptance logic only, never actual host isolation.
        with self.kernel_fixture():worker._verify_environment()
        cases=[{'/proc/self/status':'CapInh: 1'}, {'/proc/self/cgroup':'0::/host'},
               {'/proc/self/mountinfo':'1 0 0:1 / / rw - overlay overlay rw'},
               {'/proc/net/dev':'h\nh\neth0: 0'}, {'/proc/net/route':'h\nexternal route'},
               {'/sys/fs/cgroup/pids.max':'2'}, {'/sys/fs/cgroup/memory.max':'max'},
               {'/sys/fs/cgroup/memory.swap.max':'1'}, {'/sys/fs/cgroup/cpu.max':'max 100000'}]
        for changes in cases:
            with self.subTest(changes=changes),self.kernel_fixture(changes=changes),self.assertRaises(worker.BootstrapUnavailable):worker._verify_environment()
        for fds in ((),('0','1'),('0','1','2','7')):
            with self.subTest(fds=fds),self.kernel_fixture(fds=fds),self.assertRaises(worker.BootstrapUnavailable):worker._verify_environment()
    def test_missing_kernel_observation_is_unavailable_before_header(self):
        source=BytesIO(wire.encode_request(self.request()));out=BytesIO()
        with patch.object(worker,'_verify_environment',side_effect=OSError('PRIVATE')):
            self.assertEqual(worker._serve_once(source,out),78)
        self.assertEqual(source.tell(),0)
        self.assertEqual(wire.read_response(BytesIO(out.getvalue()),self.limits).error_code,'ISOLATION_UNAVAILABLE')
    def test_eof_requires_exact_bytes(self):
        encoded=wire.encode_request(self.request())
        class WrongEOF(BytesIO):
            def read(self,n):
                value=super().read(n)
                return bytearray() if value==b'' else value
        with self.assertRaises(wire.WireProtocolError):wire.read_request(WrongEOF(encoded))

class WorkerReviewRegressionTests(unittest.TestCase):
    """Owned fixtures only; bootstrap/limits replaced, never sandbox qualification."""
    @contextmanager
    def assets(self, *, divergent_cache=False):
        source = (Path(__file__).resolve().parents[1] /
                  'app/services/teacher_work/courseware_extract.py').read_bytes()
        self.assertEqual(worker.sha256(source).hexdigest(), worker.PARSER_SHA256)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'courseware_extract.py'
            path.write_bytes(source)
            if divergent_cache:
                info = path.stat()
                cached = Path(importlib.util.cache_from_source(str(path)))
                cached.parent.mkdir()
                code = compile("raise RuntimeError('OWNED_DIVERGENT_CACHE')", str(path), 'exec')
                cached.write_bytes(importlib._bootstrap_external._code_to_timestamp_pyc(
                    code, int(info.st_mtime), info.st_size))
            with patch.object(worker, '_ASSETS', root):
                yield path

    def request(self, *, malformed=False):
        from tests.test_teacher_work_courseware_extract import pdf_bytes
        data = pdf_bytes(['owned'])
        if malformed:
            data = data.rstrip()[:-1]  # %%EOF -> %%EO, reproduces pypdf diagnostic
        return wire.WireRequest('.pdf', wire.LIMIT_CAPS, data)

    def serve(self, request, sink):
        with patch.object(worker, '_verify_environment'), patch.object(worker, '_establish_limits'):
            return worker._serve_once(BytesIO(wire.encode_request(request)), sink)

    def test_exact_source_executes_instead_of_divergent_timestamp_cache(self):
        request = self.request()
        with self.assets(divergent_cache=True):
            response = worker._extract_request(request)
        self.assertEqual(response, wire.WireResponse((wire.WirePage(1, 'owned'),)))

    def test_execution_uses_already_verified_bytes_if_source_path_changes(self):
        request = self.request()
        original = importlib.util.spec_from_file_location
        with self.assets() as path:
            def replace_after_hash(name, location):
                path.write_text("raise RuntimeError('OWNED_REOPENED_SOURCE')")
                return original(name, location)
            with patch.object(worker.importlib.util, 'spec_from_file_location', replace_after_hash):
                response = worker._extract_request(request)
        self.assertEqual(response, wire.WireResponse((wire.WirePage(1, 'owned'),)))

    def test_divergent_source_hash_denies_before_execution(self):
        request = self.request()
        with self.assets() as path:
            path.write_text("raise RuntimeError('OWNED_DIVERGENT_SOURCE')")
            with self.assertRaises(worker.BootstrapUnavailable):
                worker._extract_request(request)

    def test_real_malformed_pdf_has_no_stderr_diagnostics(self):
        request = self.request(malformed=True)
        stderr, sink = StringIO(), BytesIO()
        with self.assets(), redirect_stderr(stderr):
            status = self.serve(request, sink)
        self.assertEqual(stderr.getvalue(), '')
        self.assertEqual(status, 0)
        self.assertEqual(wire.read_response(BytesIO(sink.getvalue()), wire.LIMIT_CAPS),
                         wire.WireResponse((wire.WirePage(1, 'owned'),)))

    def test_python_diagnostics_discarded_on_success_and_failure(self):
        for failure in (False, True):
            with self.subTest(failure=failure):
                stdout, stderr, sink = StringIO(), StringIO(), BytesIO()
                def noisy(request):
                    print('OWNED_STDOUT_DIAGNOSTIC')
                    print('OWNED_STDERR_DIAGNOSTIC', file=sys.stderr)
                    if failure:
                        raise RuntimeError('OWNED_EXCEPTION')
                    return wire.WireResponse((wire.WirePage(1, 'owned'),))
                with redirect_stdout(stdout), redirect_stderr(stderr), patch.object(worker, '_extract_request', noisy):
                    status = self.serve(self.request(), sink)
                self.assertEqual((stdout.getvalue(), stderr.getvalue()), ('', ''))
                self.assertEqual(status, int(failure))
                response = wire.read_response(BytesIO(sink.getvalue()), wire.LIMIT_CAPS)
                self.assertEqual(response.error_code, 'EXTRACTION_FAILED' if failure else None)

    def test_entrypoint_discards_late_native_and_exit_hook_diagnostics(self):
        # Owned fresh interpreter only; no container/service or resource syscall.
        script = """
import atexit, ctypes, os, sys
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
from parser_worker import courseware_worker as worker, courseware_wire as wire
libc = ctypes.CDLL(None)
def noisy(request):
    libc.printf(b'OWNED_BUFFERED_NATIVE_STDOUT')
    atexit.register(os.write, 2, b'OWNED_EXIT_STDERR')
    atexit.register(os.write, 1, b'OWNED_EXIT_STDOUT')
    return wire.WireResponse((wire.WirePage(1, 'owned'),))
with patch.object(worker, '_verify_environment'), patch.object(worker, '_establish_limits'), patch.object(worker, '_extract_request', noisy):
    raise SystemExit(worker.main())
"""
        request = wire.WireRequest('.pdf', wire.LIMIT_CAPS, b'%PDF-owned')
        result = subprocess.run([sys.executable, '-I', '-B', '-c', script,
                                 str(Path(__file__).resolve().parents[1])],
                                input=wire.encode_request(request), capture_output=True,
                                timeout=10, check=False)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, b'')
        self.assertEqual(wire.read_response(BytesIO(result.stdout), wire.LIMIT_CAPS),
                         wire.WireResponse((wire.WirePage(1, 'owned'),)))

    def test_terminal_discard_failures_hard_exit_without_late_diagnostics(self):
        # Hard-exit paths run only in bounded owned subprocesses, never here.
        script = """
import atexit, ctypes, os, sys
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
from parser_worker import courseware_worker as worker, courseware_wire as wire
mode = sys.argv[2]
libc = ctypes.CDLL(None)
original_open, original_dup2, original_serve = open, os.dup2, worker._serve_once
terminal = False
def serve(source, sink):
    global terminal
    status = original_serve(source, sink)
    terminal = True
    return status
def fail_open(*args, **kwargs):
    if terminal and mode == 'open':
        raise OSError('OWNED_TERMINAL_OPEN_FAILURE')
    return original_open(*args, **kwargs)
def fail_dup2(source, target, *args, **kwargs):
    if terminal and mode == 'dup' + str(target):
        raise OSError('OWNED_TERMINAL_DUP_FAILURE')
    return original_dup2(source, target, *args, **kwargs)
def noisy(request):
    libc.printf(b'OWNED_BUFFERED_NATIVE_STDOUT')
    atexit.register(os.write, 2, b'OWNED_EXIT_STDERR')
    atexit.register(os.write, 1, b'OWNED_EXIT_STDOUT')
    return wire.WireResponse((wire.WirePage(1, 'owned'),))
with patch.object(worker, '_verify_environment'), patch.object(worker, '_establish_limits'), patch.object(worker, '_extract_request', noisy), patch.object(worker, '_serve_once', serve), patch.object(worker, 'open', fail_open, create=True), patch.object(worker.os, 'dup2', fail_dup2):
    raise SystemExit(worker.main())
"""
        request = wire.WireRequest('.pdf', wire.LIMIT_CAPS, b'%PDF-owned')
        for mode in ('open', 'dup1', 'dup2'):
            with self.subTest(mode=mode):
                result = subprocess.run([sys.executable, '-I', '-B', '-c', script,
                                         str(Path(__file__).resolve().parents[1]), mode],
                                        input=wire.encode_request(request), capture_output=True,
                                        timeout=10, check=False)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stderr, b'')
                self.assertEqual(wire.read_response(BytesIO(result.stdout), wire.LIMIT_CAPS),
                                 wire.WireResponse((wire.WirePage(1, 'owned'),)))

    def test_discard_setup_failure_never_calls_parser(self):
        request = self.request()
        for fail_on in (1, 2):
            with self.subTest(fail_on=fail_on):
                original_dup, calls = os.dup, []
                def broken_dup(fd):
                    calls.append(fd)
                    if len(calls) == fail_on:
                        raise OSError('OWNED_DESCRIPTOR_FAILURE')
                    return original_dup(fd)
                sink = BytesIO()
                with patch.object(worker.os, 'dup', broken_dup), patch.object(worker, '_extract_request') as parser:
                    status = self.serve(request, sink)
                parser.assert_not_called()
                self.assertEqual(status, 1)
                self.assertEqual(wire.read_response(BytesIO(sink.getvalue()), wire.LIMIT_CAPS).error_code,
                                 'EXTRACTION_FAILED')

    def test_native_descriptor_diagnostics_discarded_and_descriptors_restored(self):
        # Actual process-local descriptor writes, no host limits or security changes.
        request, sink = self.request(), BytesIO()
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr, ExitStack() as restore:
            for target, capture in ((1, stdout), (2, stderr)):
                original = os.dup(target)
                restore.callback(os.close, original)
                restore.callback(os.dup2, original, target)
                os.dup2(capture.fileno(), target)
            def noisy(request):
                os.write(1, b'OWNED_NATIVE_STDOUT')
                os.write(2, b'OWNED_NATIVE_STDERR')
                print('OWNED_BUFFERED_STDOUT', file=sys.__stdout__, end='')
                return wire.WireResponse((wire.WirePage(1, 'owned'),))
            with patch.object(worker, '_extract_request', noisy):
                status = self.serve(request, sink)
            os.write(1, b'OUT_RESTORED')
            os.write(2, b'ERR_RESTORED')
            stdout.seek(0); stderr.seek(0)
            self.assertEqual(stdout.read(), b'OUT_RESTORED')
            self.assertEqual(stderr.read(), b'ERR_RESTORED')
        self.assertEqual(status, 0)
        self.assertIsNone(wire.read_response(BytesIO(sink.getvalue()), wire.LIMIT_CAPS).error_code)

if __name__=='__main__':unittest.main()
