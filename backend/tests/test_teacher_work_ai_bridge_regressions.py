"""Raw bridge source-review regressions plus cancellation/cleanup combinations.

Source prepared only. Candidate2 product bytes and its minimal raw-header
expectation update stay pinned while the two added combinations await RED.
Every dependency/product/async/patch/log operation is lazy and requires a new
independent runtime release. No alternative runner or network fixture is used.
"""
from __future__ import annotations

import ast
import importlib
from pathlib import Path
from types import SimpleNamespace


BACKEND = Path(__file__).resolve().parents[1]
PRIVATE_URL = "https://synthetic-user:synthetic-password@synthetic-provider.invalid/v1/chat/completions?private=synthetic-private-query"
PRIVATE_HEADER = "synthetic-private-response-header"
PRIVATE_EXCEPTION = "synthetic-private-dependency-exception"
EXTERNAL_CANCEL = "synthetic-external-cancel"
DEPENDENCY_LOGGERS = ("httpx", "httpcore.connection", "httpcore.http11",
    "httpcore.http2", "httpcore.proxy", "httpcore.socks")
PRIVATE_MARKERS = (PRIVATE_URL, "synthetic-password", "synthetic-private-query",
    PRIVATE_HEADER, PRIVATE_EXCEPTION, "synthetic-credential-never-send")


def _load():
    source = BACKEND / "app/services/teacher_lesson_prep/ai_client.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)
               and node.name == "LessonPrepAIClient"]
    methods = {node.name for node in classes[0].body if isinstance(node, ast.AsyncFunctionDef)} if classes else set()
    assert "complete_raw" in methods, "Raw regression supplement requires frozen candidate1 transport source"
    # The sibling is the exact frozen original55 source, imported only after
    # this source guard. Its loader isolates config/package and guards httpx.
    helper = importlib.import_module("test_teacher_work_ai_bridge")
    modules = helper._load()
    modules.helper = helper
    modules.logging = importlib.import_module("logging")
    return modules


def _run(modules, cases):
    try:
        modules.asyncio.run(cases())
        assert not modules.logs.overflow, "Regression log observation exceeded its bounded capture"
    finally:
        modules.close()


def _fixtures(modules):
    """Runtime-only narrow standard transport extensions of original55 fakes."""
    helper = modules.helper

    class Clock:
        def __init__(self):
            self.value = 100.0
            self.reads = 0

        def monotonic(self):
            self.reads += 1
            return self.value

        def advance(self, seconds):
            self.value += seconds

    def dependency_log(factory, logger, stage, *, failure=False):
        if not factory.trace:
            return
        headers = {"Authorization": "Bearer " + modules.settings.AI_LESSON_PREP_API_KEY,
                   "X-Private": PRIVATE_HEADER}
        error = RuntimeError(PRIVATE_EXCEPTION + " " + modules.settings.AI_LESSON_PREP_BASE_URL)
        target = modules.logging.getLogger(logger)
        target.log(modules.logging.INFO if logger == "httpx" else modules.logging.DEBUG,
            "fixture[%s/%s] HTTP Request: POST %s headers=%r exception=%r failed=%s",
            factory.label, stage, modules.settings.AI_LESSON_PREP_BASE_URL, headers, error, failure)

    class Response(helper.SyntheticResponse):
        def __init__(self, factory):
            super().__init__(factory)
            self.iteration_entered = False

        async def aiter_bytes(self):
            self.iteration_entered = True
            if self.factory.external_cancel:
                raise modules.asyncio.CancelledError(EXTERNAL_CANCEL)
            if self.factory.fault == "read_error":
                dependency_log(self.factory, "httpcore.http2", "read-failure", failure=True)
                dependency_log(self.factory, "httpcore.socks", "read-failure", failure=True)
            async for chunk in super().aiter_bytes():
                yield chunk

    class Stream(helper.SyntheticStream):
        async def __aenter__(self):
            value = await super().__aenter__()
            if self.client.factory.entered is not None:
                self.client.factory.entered.set()
                await self.client.factory.release.wait()
            return value

        async def __aexit__(self, exc_type, exc, traceback):
            await super().__aexit__(exc_type, exc, traceback)
            dependency_log(self.client.factory, "httpcore.http11", "stream-cleanup", failure=exc is not None)
            dependency_log(self.client.factory, "httpcore.proxy", "stream-cleanup", failure=exc is not None)
            if self.client.factory.advance_at == "stream":
                self.client.factory.clock.advance(self.client.factory.advance_seconds)

    class Client(helper.SyntheticClient):
        def __init__(self, factory, kwargs):
            super().__init__(factory, kwargs)
            self.response = Response(factory)

        async def __aexit__(self, exc_type, exc, traceback):
            await super().__aexit__(exc_type, exc, traceback)
            dependency_log(self.factory, "httpcore.connection", "client-cleanup", failure=exc is not None)
            dependency_log(self.factory, "httpcore.socks", "client-cleanup", failure=exc is not None)
            if self.factory.advance_at == "client":
                self.factory.clock.advance(self.factory.advance_seconds)
            if self.factory.cleanup_error:
                raise modules.httpx.ReadError(PRIVATE_EXCEPTION + " " + PRIVATE_URL)

        async def post(self, url, **kwargs):
            dependency_log(self.factory, "httpx", "request")
            dependency_log(self.factory, "httpcore.http2", "request")
            return await super().post(url, **kwargs)

        def stream(self, method, url, **kwargs):
            dependency_log(self.factory, "httpx", "request")
            dependency_log(self.factory, "httpcore.http2", "request")
            self.factory.requests.append({"operation": "stream", "method": method, "url": url, **kwargs})
            return Stream(self)

    class Factory(helper.SyntheticFactory):
        def __init__(self, *, trace=False, label="raw", constructor_error=False,
                     clock=None, advance_at=None, advance_seconds=0.0,
                     cleanup_error=False, external_cancel=False, entered=None, release=None, **kwargs):
            super().__init__(modules, **kwargs)
            self.trace = trace
            self.label = label
            self.constructor_error = constructor_error
            self.clock = clock
            self.advance_at = advance_at
            self.advance_seconds = advance_seconds
            self.cleanup_error = cleanup_error
            self.external_cancel = external_cancel
            self.entered = entered
            self.release = release
            self.constructor_calls = 0

        def __call__(self, **kwargs):
            self.constructor_calls += 1
            dependency_log(self, "httpx", "constructor", failure=self.constructor_error)
            dependency_log(self, "httpcore.connection", "constructor", failure=self.constructor_error)
            if self.constructor_error:
                raise modules.httpx.ConnectTimeout(PRIVATE_EXCEPTION + " " + PRIVATE_URL)
            client = Client(self, kwargs)
            self.clients.append(client)
            return client

    return SimpleNamespace(Clock=Clock, Factory=Factory)


def _logger_state(modules):
    logging = modules.logging
    names = ("",) + DEPENDENCY_LOGGERS
    return (logging.getLogRecordFactory(), tuple((name,
        logging.getLogger(name).level, logging.getLogger(name).disabled,
        logging.getLogger(name).propagate, tuple(logging.getLogger(name).filters),
        tuple(logging.getLogger(name).handlers),
        tuple((handler, tuple(handler.filters)) for handler in logging.getLogger(name).handlers))
        for name in names), modules.httpx.AsyncClient)


def _private_absent(text, case):
    assert not any(marker in text for marker in PRIVATE_MARKERS), case + ": dependency log leaked raw private fields"


def _external_controls(modules, label):
    start = len(modules.logs.text)
    for name in DEPENDENCY_LOGGERS:
        modules.logging.getLogger(name).log(modules.logging.INFO if name == "httpx" else modules.logging.DEBUG,
            "%s logger=%s actual-url=%s actual-header=%s actual-exception=%r", label, name,
            PRIVATE_URL, PRIVATE_HEADER, RuntimeError(PRIVATE_EXCEPTION))
    text = modules.logs.text[start:]
    for name in DEPENDENCY_LOGGERS:
        assert label + " logger=" + name in text, label + ": concurrent/legacy logger was globally muted"
    assert PRIVATE_URL in text and PRIVATE_HEADER in text and PRIVATE_EXCEPTION in text, label + ": actual control fields were globally redacted"


def _request_count(factory, case):
    assert factory.constructor_calls == 1, case + ": transport retried construction"
    assert len(factory.requests) == 1, case + ": transport retried/skipped request"
    client = factory.clients[0]
    assert client.client_closed and client.stream_closed, case + ": synthetic local transport did not unwind"
    return client.response


def test_raw_dependency_logs_are_task_scoped_with_legacy_controls():
    modules = _load()

    async def cases():
        fixtures = _fixtures(modules)
        modules.settings.AI_LESSON_PREP_BASE_URL = PRIVATE_URL
        logging = modules.logging

        class ExistingFilter(logging.Filter):
            def filter(self, record):
                return True

        sentinel = ExistingFilter()
        targets = [logging.getLogger(name) for name in ("",) + DEPENDENCY_LOGGERS]
        for logger in targets:
            logger.addFilter(sentinel)
        handler = modules.logs
        handler.addFilter(sentinel)
        before = _logger_state(modules)
        try:
            # R1-01: constructor/request and both cleanup boundaries remain
            # private while another actual Task retains dependency log visibility.
            entered, release = modules.asyncio.Event(), modules.asyncio.Event()
            factory = fixtures.Factory(trace=True, entered=entered, release=release,
                payload=modules.helper._envelope("actual raw log control"))
            task = modules.asyncio.create_task(modules.helper._raw(modules, factory))
            start = len(modules.logs.text)
            try:
                await modules.asyncio.wait_for(entered.wait(), timeout=2)
                _private_absent(modules.logs.text[start:], "R1-01 constructor/request")
                state = _logger_state(modules)
                assert state[0] is before[0] and state[2] is before[2], "R1-01 global log/factory identity changed"
                for logger in targets:
                    assert sentinel in logger.filters, "R1-01 pre-existing logger filter was removed"
                assert sentinel in handler.filters, "R1-01 pre-existing handler filter was removed"
                for old, current in zip(before[1], state[1]):
                    assert old[:4] == current[:4], "R1-01 global logger level/disabled/propagate changed"
                _external_controls(modules, "concurrent-task-control")
                start = len(modules.logs.text)
                release.set()
                assert await modules.asyncio.wait_for(task, timeout=2) == "actual raw log control"
                _private_absent(modules.logs.text[start:], "R1-01 cleanup")
                assert factory.requests[0]["url"] == PRIVATE_URL, "R1-01 configured full URL was changed"
                _request_count(factory, "R1-01")
            finally:
                release.set()
                if not task.done():
                    task.cancel()
                await modules.asyncio.gather(task, return_exceptions=True)
            assert _logger_state(modules) == before, "R1-01 logger/filter/factory state was not preserved"

            # R1-02: actual synthetic dependency exception/header fields emitted
            # from a failing raw request and cleanup must remain private too.
            factory = fixtures.Factory(trace=True, fault="read_error")
            start = len(modules.logs.text)
            await modules.helper._error(modules.helper._raw(modules, factory),
                "WORK_AI_UPSTREAM_FAILED", case="R1-02")
            _private_absent(modules.logs.text[start:], "R1-02 request/failure/cleanup")
            _request_count(factory, "R1-02")
            assert _logger_state(modules) == before, "R1-02 logger/filter/factory state changed"

            # R1-03: privacy must start before invoking the injected constructor.
            factory = fixtures.Factory(trace=True, constructor_error=True)
            start = len(modules.logs.text)
            await modules.helper._error(modules.helper._raw(modules, factory),
                "WORK_AI_TIMEOUT", case="R1-03")
            _private_absent(modules.logs.text[start:], "R1-03 constructor failure")
            assert factory.constructor_calls == 1 and not factory.clients and not factory.requests
            assert _logger_state(modules) == before, "R1-03 logger/filter/factory state changed"

            # R1-04: legacy transport still emits its actual marker-bearing
            # dependency records and uses its existing two-field headers.
            factory = fixtures.Factory(trace=True, label="legacy",
                payload=modules.helper._envelope({"content": "legacy actual control"}))
            start = len(modules.logs.text)
            result = await modules.helper._client(modules, factory).complete(
                system_prompt=modules.helper.SYSTEM, user_prompt=modules.helper.PROMPT)
            assert result == {"content": "legacy actual control"}
            visible = modules.logs.text[start:]
            for stage in ("constructor", "request", "client-cleanup"):
                assert "fixture[legacy/" + stage + "]" in visible, "R1-04 legacy records were muted"
            for marker in PRIVATE_MARKERS:
                assert marker in visible, "R1-04 legacy marker-bearing records were redacted"
            assert factory.requests[0]["headers"] == {"Authorization": "Bearer " + modules.helper.KEY,
                "Content-Type": "application/json"}
            assert factory.requests[0]["url"] == PRIVATE_URL
            assert _logger_state(modules) == before, "R1-04 logger/filter/factory state changed"

            # R1-05: no task-local raw privacy state escapes into later callers.
            _external_controls(modules, "after-raw-control")
            assert _logger_state(modules) == before, "R1-05 logger/filter/factory state changed"
        finally:
            for logger in targets:
                logger.removeFilter(sentinel)
            handler.removeFilter(sentinel)

    _run(modules, cases)


def test_raw_envelope_rejects_exponent_overflow():
    modules = _load()

    async def cases():
        raw = ' \n```json\n{"type":"answer","plain_text":"实际 e\u0301"}\n``` '
        prefix = modules.helper._bytes(modules.helper._envelope(raw))[:-1]
        # R2-01..04: constants hooks alone do not catch float exponent overflow.
        for case, metadata in (("R2-01", b'"usage":1e400'), ("R2-02", b'"usage":-1e400'),
            ("R2-03", b'"ignored":{"nested":[{"tokens":1e400}]}'),
            ("R2-04", b'"ignored":{"nested":[{"tokens":-1e400}]}')):
            factory = modules.helper.SyntheticFactory(modules, chunks=[prefix + b"," + metadata + b"}"])
            await modules.helper._error(modules.helper._raw(modules, factory),
                "WORK_AI_INVALID_RESPONSE", case=case)
            assert len(factory.clients) == 1 and len(factory.requests) == 1, case
        # R2-05..08: finite/underflow values remain legal envelope metadata.
        for case, number in (("R2-05", b"1.25"), ("R2-06", b"1e300"),
                             ("R2-07", b"-1e300"), ("R2-08", b"1e-400")):
            factory = modules.helper.SyntheticFactory(modules,
                chunks=[prefix + b',"ignored":{"nested":[' + number + b"]}}"])
            assert await modules.helper._raw(modules, factory) == raw, case
            assert len(factory.clients) == 1 and len(factory.requests) == 1, case

    _run(modules, cases)


def test_raw_deadline_applies_after_error_cleanup():
    modules = _load()

    async def cases():
        fixtures = _fixtures(modules)
        # R3-01..07: advance only the module-local clock, never the loop clock.
        late = (
            ("R3-01", "stream", {"status": 429}, 8.0),
            ("R3-02", "client", {"status": 429}, 7.0),
            ("R3-03", "stream", {"chunks": [b'{"choices":']}, 8.0),
            ("R3-04", "client", {"chunks": [b'{"choices":']}, 8.0),
            ("R3-05", "stream", {"payload": modules.helper._envelope("actual late success")}, 8.0),
            ("R3-06", "client", {"fault": "read_error"}, 8.0),
            ("R3-07", "client", {"cleanup_error": True}, 8.0),
        )
        for case, phase, kwargs, elapsed in late:
            clock = fixtures.Clock()
            factory = fixtures.Factory(clock=clock, advance_at=phase, advance_seconds=elapsed, **kwargs)
            with modules.patch.object(modules.lesson, "time", SimpleNamespace(monotonic=clock.monotonic)):
                await modules.helper._error(modules.helper._raw(modules, factory, timeout=7),
                    "WORK_AI_TIMEOUT", case=case)
            assert clock.value == 100.0 + elapsed and clock.reads >= 2, case
            _request_count(factory, case)
        # R3-08/09: cleanup that stays in budget retains the real failure code.
        for case, kwargs, code in (("R3-08", {"status": 429}, "WORK_AI_RATE_LIMITED"),
            ("R3-09", {"chunks": [b'{"choices":']}, "WORK_AI_INVALID_RESPONSE")):
            clock = fixtures.Clock()
            factory = fixtures.Factory(clock=clock, advance_at="client", advance_seconds=1.0, **kwargs)
            with modules.patch.object(modules.lesson, "time", SimpleNamespace(monotonic=clock.monotonic)):
                await modules.helper._error(modules.helper._raw(modules, factory, timeout=7), code, case=case)
            assert clock.value == 101.0
            _request_count(factory, case)
        # R3-10/11: external cancellation is preserved even after late cleanup.
        for case, phase in (("R3-10", "stream"), ("R3-11", "client")):
            clock = fixtures.Clock()
            factory = fixtures.Factory(clock=clock, advance_at=phase, advance_seconds=8.0, external_cancel=True)
            with modules.patch.object(modules.lesson, "time", SimpleNamespace(monotonic=clock.monotonic)):
                try:
                    await modules.helper._raw(modules, factory, timeout=7)
                except modules.asyncio.CancelledError as error:
                    assert str(error) == EXTERNAL_CANCEL, case
                else:
                    raise AssertionError(case + ": external cancellation was swallowed or replaced")
            assert clock.value == 108.0
            _request_count(factory, case)

    _run(modules, cases)


async def _cancel_cleanup_case(modules, *, case, elapsed):
    fixtures = _fixtures(modules)
    modules.settings.AI_LESSON_PREP_BASE_URL = PRIVATE_URL
    clock = fixtures.Clock()
    factory = fixtures.Factory(trace=True, clock=clock, advance_at="client",
        advance_seconds=elapsed, external_cancel=True, cleanup_error=True)
    before = _logger_state(modules)
    assert modules.lesson._RAW_DEPENDENCY_LOGS_PRIVATE.get() is False, case + ": caller privacy context was already active"
    start = len(modules.logs.text)
    with modules.patch.object(modules.lesson, "time", SimpleNamespace(monotonic=clock.monotonic)):
        try:
            await modules.helper._raw(modules, factory, timeout=7)
        except BaseException as error:
            assert isinstance(error, modules.asyncio.CancelledError), case + ": cleanup replaced external cancellation"
            assert str(error) == EXTERNAL_CANCEL, case + ": original cancellation message changed"
        else:
            raise AssertionError(case + ": external cancellation was swallowed")
        finally:
            _private_absent(modules.logs.text[start:], case + " failure/cleanup")
            assert modules.lesson._RAW_DEPENDENCY_LOGS_PRIVATE.get() is False, case + ": raw privacy context did not reset"
            assert _logger_state(modules) == before, case + ": logger/filter/factory state changed"
            _request_count(factory, case)
            assert clock.value == 100.0 + elapsed, case
            _external_controls(modules, case + " after-cancellation-control")


def test_raw_external_cancel_survives_in_budget_cleanup_failure():
    modules = _load()

    async def cases():
        # R5-01: the body cancellation stays authoritative when client cleanup
        # raises ReadError before the captured deadline; privacy resets too.
        await _cancel_cleanup_case(modules, case="R5-01", elapsed=1.0)

    _run(modules, cases)


def test_raw_external_cancel_survives_expired_cleanup_failure():
    modules = _load()

    async def cases():
        # R5-02: expiry plus ReadError during cleanup still cannot replace an
        # external body cancellation with a controlled timeout/upstream error.
        await _cancel_cleanup_case(modules, case="R5-02", elapsed=8.0)

    _run(modules, cases)


def test_raw_transport_identity_encoding_precedes_iteration():
    modules = _load()

    async def cases():
        fixtures = _fixtures(modules)
        # R4-01..09: nonidentity/unsupported/compound encoding is rejected before
        # entering the decoder-yielding aiter_bytes operation. No gzip is made.
        rejected = ("gzip", "GZip", "deflate", "br", "compress", "gzip, br",
                    "identity, gzip", "x-unsupported", "")
        for index, encoding in enumerate(rejected, 1):
            case = f"R4-{index:02}"
            factory = fixtures.Factory(headers={"Content-Encoding": encoding})
            await modules.helper._error(modules.helper._raw(modules, factory),
                "WORK_AI_INVALID_RESPONSE", case=case)
            response = _request_count(factory, case)
            assert not response.iteration_entered and response.chunks_read == 0, case
        # R4-10..13: omission/identity/case/HTTP whitespace are legal. Exact raw
        # request headers require the one separately approved compatibility delta
        # in original55 only after parent observes this supplement's released RED.
        for index, encoding in enumerate((None, "identity", "Identity", " \tidentity \t"), 10):
            case = f"R4-{index:02}"
            headers = {} if encoding is None else {"Content-Encoding": encoding}
            factory = fixtures.Factory(headers=headers, payload=modules.helper._envelope("actual identity raw"))
            assert await modules.helper._raw(modules, factory) == "actual identity raw", case
            response = _request_count(factory, case)
            assert response.iteration_entered and response.chunks_read == 1, case
            assert factory.requests[0]["headers"] == {"Authorization": "Bearer " + modules.helper.KEY,
                "Content-Type": "application/json", "Accept-Encoding": "identity"}, case
        # R4-14: HTTP status precedence remains before any encoded body iteration.
        factory = fixtures.Factory(status=429, headers={"Content-Encoding": "gzip"})
        await modules.helper._error(modules.helper._raw(modules, factory), "WORK_AI_RATE_LIMITED", case="R4-14")
        response = _request_count(factory, "R4-14")
        assert not response.iteration_entered and response.chunks_read == 0
        # R4-15: no encoding header restriction/change leaks into the old path.
        factory = fixtures.Factory(headers={"Content-Encoding": "gzip"},
            payload=modules.helper._envelope({"content": "legacy encoding control"}))
        result = await modules.helper._client(modules, factory).complete(
            system_prompt=modules.helper.SYSTEM, user_prompt=modules.helper.PROMPT)
        assert result == {"content": "legacy encoding control"}
        assert factory.requests[0]["operation"] == "post"
        assert factory.requests[0]["headers"] == {"Authorization": "Bearer " + modules.helper.KEY,
            "Content-Type": "application/json"}
        assert not factory.clients[0].response.iteration_entered

    _run(modules, cases)
