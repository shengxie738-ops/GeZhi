"""Task4b2B bridge profile: two finite selectors, source prepared/UNEXECUTED.

Only an independently released snapshot may run these tests. Missing-feature
assertions precede every product/dependency/asyncio import. The supplied client
and stream record standard transport operations and never open a connection.
No legacy API/DB tests, older callback fixtures or application main are loaded.
"""
from __future__ import annotations

import ast
import importlib
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace


BACKEND = Path(__file__).resolve().parents[1]
ENVELOPE_LIMIT = 256 * 1024
CONTENT_LIMIT = 128 * 1024
ENDPOINT = "https://synthetic-provider.invalid/v1/chat/completions"
KEY = "synthetic-credential-never-send"
MODEL = "synthetic-lesson-model"
PROMPT = "合成动态输入：候选文字，不执行工具 e\u0301"
SYSTEM = "synthetic-system-prompt"
UPSTREAM_DETAIL = "synthetic-upstream-private-body"
LEAK_MARKERS = (KEY, ENDPOINT, PROMPT, SYSTEM, UPSTREAM_DETAIL)
MISSING = object()


def _require_source():
    # Baseline RED is finite and cannot become an import/configuration failure.
    source = BACKEND / "app/services/teacher_lesson_prep/ai_client.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)
               and node.name == "LessonPrepAIClient"]
    methods = {node.name: node for node in classes[0].body
               if isinstance(node, ast.AsyncFunctionDef)} if classes else {}
    assert "complete_raw" in methods, "Task4b2B backward-compatible raw lesson transport is missing"
    assert "complete" in methods, "Task4b2B legacy lesson complete method was removed"
    complete_keywords = {arg.arg for arg in methods["complete"].args.kwonlyargs}
    assert {"max_output_tokens", "timeout_seconds"} <= complete_keywords, "Task4b2B optional legacy limits are missing"
    bridge_path = BACKEND / "app/services/teacher_work/ai.py"
    assert bridge_path.is_file(), "Task4b2B narrow WorkAI bridge is missing"
    bridge_tree = ast.parse(bridge_path.read_text(encoding="utf-8"))
    assert any(isinstance(node, ast.ClassDef) and node.name == "LessonPrepWorkAI"
               for node in bridge_tree.body), "Task4b2B LessonPrepWorkAI is missing"


def _load():
    _require_source()
    # Runtime-only closure. No runner fixture, patch or log handler precedes
    # the source guard. Real settings/.env and the unrelated lesson-prep package
    # initializer/catalog/retriever are not loaded.
    asyncio = importlib.import_module("asyncio")
    httpx = importlib.import_module("httpx")
    clock = importlib.import_module("time")
    contextlib = importlib.import_module("contextlib")
    logging = importlib.import_module("logging")
    patch = importlib.import_module("unittest.mock").patch
    scope = contextlib.ExitStack()

    def scoped_module(name, value):
        previous = sys.modules.get(name, MISSING)

        def restore():
            if previous is MISSING:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous

        scope.callback(restore)
        if value is MISSING:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = value

    def scoped_import(name):
        parent_name, _, attribute = name.rpartition(".")
        parent_before = sys.modules.get(parent_name)
        previous = getattr(parent_before, attribute, MISSING) if parent_before is not None else MISSING
        value = importlib.import_module(name)
        parent_after = sys.modules.get(parent_name)

        def restore():
            if parent_after is not None:
                if previous is MISSING:
                    if hasattr(parent_after, attribute):
                        delattr(parent_after, attribute)
                else:
                    setattr(parent_after, attribute, previous)

        scope.callback(restore)
        return value

    class BoundedLogCapture(logging.Handler):
        def __init__(self):
            super().__init__()
            self.text = ""
            self.leaked = False
            self.overflow = False

        def emit(self, record):
            message = self.format(record)
            self.leaked = self.leaked or any(marker in message for marker in LEAK_MARKERS)
            remaining = 32768 - len(self.text)
            if len(message) + 1 > remaining:
                self.overflow = True
            self.text += (message + "\n")[:max(0, remaining)]

    try:
        settings = SimpleNamespace(AI_LESSON_PREP_API_KEY=KEY,
            AI_LESSON_PREP_BASE_URL=ENDPOINT, AI_LESSON_PREP_MODEL=MODEL,
            AI_LESSON_PREP_MAX_OUTPUT_TOKENS=49152, AI_LESSON_PREP_TIMEOUT_SECONDS=180)
        config = ModuleType("app.core.config")
        config.settings = settings
        package = ModuleType("app.services.teacher_lesson_prep")
        package.__path__ = [str(BACKEND / "app/services/teacher_lesson_prep")]
        scoped_module("app.core.config", config)
        scoped_module("app.services.teacher_lesson_prep", package)
        scoped_module("app.services.teacher_lesson_prep.ai_client", MISSING)
        scoped_module("app.services.teacher_work.ai", MISSING)

        def forbidden_default_client(*args, **kwargs):
            raise AssertionError("Actual httpx.AsyncClient construction is outside this synthetic profile")

        scope.enter_context(patch.object(httpx, "AsyncClient", forbidden_default_client))
        logs = BoundedLogCapture()
        root = logging.getLogger()
        previous_level = root.level
        scope.callback(root.setLevel, previous_level)
        root.setLevel(logging.DEBUG)
        root.addHandler(logs)
        scope.callback(root.removeHandler, logs)
        return SimpleNamespace(asyncio=asyncio, httpx=httpx, clock=clock, settings=settings,
            patch=patch, logs=logs, close=scope.close,
            lesson=scoped_import("app.services.teacher_lesson_prep.ai_client"),
            bridge=scoped_import("app.services.teacher_work.ai"),
            chat=importlib.import_module("app.services.teacher_work.chat"))
    except BaseException:
        scope.close()
        raise


def _envelope(content=MISSING):
    message = {} if content is MISSING else {"content": content}
    return {"choices": [{"message": message}]}


def _bytes(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class SyntheticHeaders:
    def __init__(self, values):
        self.values = {key.lower(): value for key, value in values.items()}

    def get(self, key, default=None):
        return self.values.get(key.lower(), default)


class SyntheticResponse:
    """Only status/json/aiter_bytes operations used by the approved transport."""
    def __init__(self, factory):
        self.factory = factory
        self.headers = SyntheticHeaders(factory.headers)
        self.status_seen = False
        self.json_reads = 0
        self.chunks_read = 0
        self.byte_count = 0
        self.waiting = False

    @property
    def status_code(self):
        self.status_seen = True
        return self.factory.status

    @property
    def is_success(self):
        return 200 <= self.status_code < 300

    def raise_for_status(self):
        if not self.is_success:
            raise self.factory.m.httpx.HTTPStatusError(UPSTREAM_DETAIL + KEY + ENDPOINT,
                request=SimpleNamespace(url=ENDPOINT), response=self)

    def json(self):
        assert self.status_seen, "Legacy extraction happened before HTTP status checking"
        self.json_reads += 1
        return self.factory.payload

    async def aiter_bytes(self):
        assert self.status_seen, "Raw extraction happened before HTTP status checking"
        if self.factory.fault == "read_timeout":
            raise self.factory.m.httpx.ReadTimeout(UPSTREAM_DETAIL + KEY + ENDPOINT)
        if self.factory.fault == "read_error":
            raise self.factory.m.httpx.ReadError(UPSTREAM_DETAIL + KEY + ENDPOINT)
        if self.factory.wall_clock is not None:
            self.waiting = True
            self.factory.wall_clock.seconds -= 3600
            # A pending in-memory future is terminated by the production total
            # deadline. No sleep, HTTP operation, thread or external callback.
            await self.factory.m.asyncio.get_running_loop().create_future()
        for chunk in self.factory.chunks:
            self.chunks_read += 1
            self.byte_count += len(chunk)
            yield chunk


class SyntheticStream:
    def __init__(self, client):
        self.client = client

    async def __aenter__(self):
        if self.client.factory.fault == "stream_timeout":
            raise self.client.factory.m.httpx.ConnectTimeout(UPSTREAM_DETAIL + KEY + ENDPOINT)
        self.client.stream_entered = True
        return self.client.response

    async def __aexit__(self, exc_type, exc, traceback):
        self.client.stream_closed = True


class SyntheticClient:
    def __init__(self, factory, kwargs):
        self.factory = factory
        self.kwargs = kwargs
        self.response = SyntheticResponse(factory)
        self.client_entered = False
        self.client_closed = False
        self.stream_entered = False
        self.stream_closed = False

    async def __aenter__(self):
        if self.factory.fault == "client_timeout":
            raise self.factory.m.httpx.ConnectTimeout(UPSTREAM_DETAIL + KEY + ENDPOINT)
        self.client_entered = True
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        self.client_closed = True

    async def post(self, url, **kwargs):
        self.factory.requests.append({"operation": "post", "url": url, **kwargs})
        return self.response

    def stream(self, method, url, **kwargs):
        self.factory.requests.append({"operation": "stream", "method": method, "url": url, **kwargs})
        return SyntheticStream(self)


class SyntheticFactory:
    """Explicit per-call injected factory, with no provider/decision logic."""
    def __init__(self, modules, *, payload=None, chunks=None, headers=None,
                 status=200, fault=None, wall_clock=None):
        self.m = modules
        self.payload = _envelope("synthetic raw") if payload is None else payload
        self.chunks = [_bytes(self.payload)] if chunks is None else chunks
        self.headers = {} if headers is None else headers
        self.status = status
        self.fault = fault
        self.wall_clock = wall_clock
        self.clients = []
        self.requests = []

    def __call__(self, **kwargs):
        client = SyntheticClient(self, kwargs)
        self.clients.append(client)
        return client


def _client(modules, factory):
    return modules.lesson.LessonPrepAIClient(client_factory=factory)


def _raw(modules, factory, *, tokens=8192, timeout=90):
    return _client(modules, factory).complete_raw(system_prompt=SYSTEM, user_prompt=PROMPT,
        temperature=0.7, max_output_tokens=tokens, timeout_seconds=timeout)


def _request(factory, *, tokens, timeout, raw=True, system=SYSTEM, temperature=0.7):
    assert len(factory.clients) == 1, "A single call created an unexpected extra transport"
    assert len(factory.requests) == 1, "A single call retried or skipped dispatch"
    client = factory.clients[0]
    request = factory.requests[0]
    assert request["operation"] == ("stream" if raw else "post")
    if raw:
        assert request["method"] == "POST"
        assert client.response.json_reads == 0, "Raw transport used permissive response.json()"
    assert request["url"] == ENDPOINT
    assert request["headers"] == {"Authorization": "Bearer " + KEY, "Content-Type": "application/json"}
    assert request["json"] == {"model": MODEL, "messages": [
        {"role": "system", "content": system}, {"role": "user", "content": PROMPT}],
        "temperature": temperature, "max_tokens": tokens, "response_format": {"type": "json_object"}}
    assert client.kwargs["timeout"] == timeout
    assert client.kwargs.get("follow_redirects", False) is False
    assert request.get("follow_redirects", False) is False
    assert client.client_closed
    if raw and client.stream_entered:
        assert client.stream_closed
    return client.response


async def _error(operation, code, *, case):
    try:
        await operation
    except Exception as error:
        assert getattr(error, "code", None) == code, (case, type(error).__name__, "wrong controlled code")
        assert str(error) == code and error.args == (code,), (case, "public error contains upstream detail")
        assert error.__cause__ is None, (case, "public error chains upstream detail")
        assert not any(marker in repr(error) for marker in LEAK_MARKERS), (case, "repr leaks upstream detail")
    else:
        raise AssertionError(case + ": transport unexpectedly succeeded")


def _parser_error(modules, raw, *, case):
    try:
        modules.chat.parse_chat_result(raw, allowed_result_refs=frozenset(), omitted_context=False)
    except modules.chat.ChatPreparationError as error:
        assert error.code == "INVALID_CHAT_RESULT", case
    else:
        raise AssertionError(case + ": bridge erased strict-parser rejection evidence")


def _execute(modules, cases):
    try:
        modules.asyncio.run(cases())
        assert not modules.logs.leaked, "Transport logs contain private synthetic detail"
        assert not modules.logs.overflow, "Bounded log capture overflowed; sanitization observation is incomplete"
    finally:
        modules.close()


def test_lesson_raw_bridge_preserves_content_and_legacy_complete():
    modules = _load()

    async def cases():
        # C18-01/02/03: the actual narrow adapter must keep the supplied client,
        # fixed Work system prompt and byte-equivalent decoded raw string.
        raw_cases = (
            ("C18-01", ' \n{"type":"answer","plain_text":"实际中文 e\u0301 <b>工具名只是候选</b>"} \t', False),
            ("C18-02", '{"type":"answer","type":"skill_suggestion","plain_text":"实际中文 e\u0301"}', True),
            ("C18-03", '```json\n{"type":"answer","plain_text":"实际中文 e\u0301"}\n```', True),
        )
        for case, raw, rejects in raw_cases:
            factory = SyntheticFactory(modules, payload=_envelope(raw))
            adapter = modules.bridge.LessonPrepWorkAI(_client(modules, factory))
            result = await adapter.complete(PROMPT, max_output_tokens=8192, timeout_seconds=90)
            assert type(result) is str and result == raw, case
            _request(factory, tokens=8192, timeout=90,
                system=modules.chat.CHAT_SYSTEM_PROMPT_V1, temperature=0.2)
            if rejects:
                _parser_error(modules, result, case=case)
            else:
                parsed = modules.chat.parse_chat_result(result, allowed_result_refs=frozenset(), omitted_context=True)
                assert parsed.plain_text == "实际中文 e\u0301 <b>工具名只是候选</b>" and parsed.omitted_context is True

        # C18-04/05/06: no-limit legacy defaults remain above Work caps; dict,
        # Markdown fence and existing duplicate-name parsing remain compatible.
        legacy_cases = (
            ("C18-04", {"content": "原字典中文"}, {"content": "原字典中文"}),
            ("C18-05", '```JSON\n{"content":"旧 fenced 中文"}\n```', {"content": "旧 fenced 中文"}),
            ("C18-06", '{"content":"前值","content":"后值"}', {"content": "后值"}),
        )
        for case, content, expected in legacy_cases:
            factory = SyntheticFactory(modules, payload=_envelope(content))
            result = await _client(modules, factory).complete(system_prompt=SYSTEM, user_prompt=PROMPT, temperature=0.7)
            assert result == expected, case
            _request(factory, tokens=49152, timeout=180, raw=False)

        # C18-07: explicit None has the same no-limit legacy behavior.
        factory = SyntheticFactory(modules, payload=_envelope({"content": "原字典"}))
        result = await _client(modules, factory).complete(system_prompt=SYSTEM, user_prompt=PROMPT,
            temperature=0.7, max_output_tokens=None, timeout_seconds=None)
        assert result == {"content": "原字典"}
        _request(factory, tokens=49152, timeout=180, raw=False)

        # C18-08: the optional legacy arguments are consumed, not ignored.
        factory = SyntheticFactory(modules, payload=_envelope({"content": "有界旧行为"}))
        result = await _client(modules, factory).complete(system_prompt=SYSTEM, user_prompt=PROMPT,
            temperature=0.7, max_output_tokens=123, timeout_seconds=4)
        assert result == {"content": "有界旧行为"}
        operation = factory.requests[0]["operation"]
        assert operation in {"post", "stream"}
        _request(factory, tokens=123, timeout=4, raw=operation == "stream")

        # C18-09..16: raw mode never coerces or salvages content.
        invalid_contents = (MISSING, None, {}, [], 1, True, "", " \n\t ")
        for index, content in enumerate(invalid_contents, 9):
            factory = SyntheticFactory(modules, payload=_envelope(content))
            await _error(_raw(modules, factory), "WORK_AI_INVALID_RESPONSE", case=f"C18-{index:02}")
            _request(factory, tokens=8192, timeout=90)

    _execute(modules, cases)


def test_lesson_raw_transport_clamps_bounds_and_sanitizes_errors():
    modules = _load()

    async def cases():
        # C19-01..04: configuration, Work caps and supplied remaining seconds.
        limits = ((1024, 7, 8192, 90, 1024, 7), (49152, 180, 100000, 180, 8192, 90),
                  (8192, 90, 1234, 3, 1234, 3), (1024, 7, 1, 1, 1, 1))
        for index, (configured_tokens, configured_timeout, tokens, timeout, expected_tokens, expected_timeout) in enumerate(limits, 1):
            modules.settings.AI_LESSON_PREP_MAX_OUTPUT_TOKENS = configured_tokens
            modules.settings.AI_LESSON_PREP_TIMEOUT_SECONDS = configured_timeout
            factory = SyntheticFactory(modules, payload=_envelope("实际 raw 中文"))
            assert await _raw(modules, factory, tokens=tokens, timeout=timeout) == "实际 raw 中文", f"C19-{index:02}"
            _request(factory, tokens=expected_tokens, timeout=expected_timeout)
        modules.settings.AI_LESSON_PREP_MAX_OUTPUT_TOKENS = 49152
        modules.settings.AI_LESSON_PREP_TIMEOUT_SECONDS = 180

        # C19-05..13: malformed/missing settings fail before client creation.
        bad_settings = (("AI_LESSON_PREP_API_KEY", ""), ("AI_LESSON_PREP_BASE_URL", ""),
            ("AI_LESSON_PREP_MODEL", ""), ("AI_LESSON_PREP_MAX_OUTPUT_TOKENS", 0),
            ("AI_LESSON_PREP_MAX_OUTPUT_TOKENS", True), ("AI_LESSON_PREP_MAX_OUTPUT_TOKENS", "8192"),
            ("AI_LESSON_PREP_TIMEOUT_SECONDS", 0), ("AI_LESSON_PREP_TIMEOUT_SECONDS", True),
            ("AI_LESSON_PREP_TIMEOUT_SECONDS", 1.5))
        for index, (name, value) in enumerate(bad_settings, 5):
            old = getattr(modules.settings, name)
            setattr(modules.settings, name, value)
            factory = SyntheticFactory(modules)
            try:
                await _error(_raw(modules, factory), "WORK_AI_UNAVAILABLE", case=f"C19-{index:02}")
                assert factory.clients == [] and factory.requests == [], f"C19-{index:02}"
            finally:
                setattr(modules.settings, name, old)

        # C19-14: exactly 256 KiB accumulated envelope bytes are accepted.
        envelope = _bytes(_envelope("exact envelope"))
        exact = envelope + b" " * (ENVELOPE_LIMIT - len(envelope))
        factory = SyntheticFactory(modules, chunks=[exact[:65536], exact[65536:]],
            headers={"Content-Length": str(ENVELOPE_LIMIT)})
        assert await _raw(modules, factory) == "exact envelope"
        response = _request(factory, tokens=8192, timeout=90)
        assert response.byte_count == ENVELOPE_LIMIT and response.chunks_read == 2

        # C19-15..18: declared and actual byte bounds, even absent/misreported length.
        bound_cases = (
            ("C19-15", {"Content-Length": str(ENVELOPE_LIMIT + 1)}, [envelope], 0),
            ("C19-16", {}, [b" " * ENVELOPE_LIMIT, b" ", b"unread-tail"], 2),
            ("C19-17", {"Content-Length": "1"}, [b" " * ENVELOPE_LIMIT, b" ", b"unread-tail"], 2),
            ("C19-18", {"Content-Length": str(ENVELOPE_LIMIT)}, [b" " * ENVELOPE_LIMIT, b" ", b"unread-tail"], 2),
        )
        for case, headers, chunks, read_count in bound_cases:
            factory = SyntheticFactory(modules, chunks=chunks, headers=headers)
            await _error(_raw(modules, factory), "WORK_AI_INVALID_RESPONSE", case=case)
            response = _request(factory, tokens=8192, timeout=90)
            assert response.chunks_read == read_count, case

        # C19-19..22: decoded model content is bounded by UTF-8 bytes, not chars.
        unicode_exact = "中" * (CONTENT_LIMIT // 3) + "a" * (CONTENT_LIMIT % 3)
        for case, content, accepted in (("C19-19", "a" * CONTENT_LIMIT, True),
            ("C19-20", "a" * (CONTENT_LIMIT + 1), False), ("C19-21", unicode_exact, True),
            ("C19-22", unicode_exact + "a", False)):
            factory = SyntheticFactory(modules, payload=_envelope(content))
            if accepted:
                assert await _raw(modules, factory) == content, case
            else:
                await _error(_raw(modules, factory), "WORK_AI_INVALID_RESPONSE", case=case)
            _request(factory, tokens=8192, timeout=90)

        # C19-23..31: strict UTF-8/provider envelope decoding before content use.
        malformed = (
            b"\xff", b'{"choices":',
            b'{"choices":[],"choices":[{"message":{"content":"erased duplicate"}}]}',
            b'{"choices":[{"message":{"content":"first","content":"second"}}]}',
            b'{"choices":[{"message":{"content":"ok"}}],"usage":NaN}',
            b'{"choices":[{"message":{"content":"ok"}}],"usage":Infinity}',
            b"[]", b'{"choices":[]}', b'{"choices":[1]}',
        )
        for index, body in enumerate(malformed, 23):
            factory = SyntheticFactory(modules, chunks=[body])
            await _error(_raw(modules, factory), "WORK_AI_INVALID_RESPONSE", case=f"C19-{index:02}")
            _request(factory, tokens=8192, timeout=90)

        # C19-32..34: status rejection precedes body extraction and never retries.
        for case, status, code in (("C19-32", 429, "WORK_AI_RATE_LIMITED"),
            ("C19-33", 503, "WORK_AI_UPSTREAM_FAILED"), ("C19-34", 302, "WORK_AI_UPSTREAM_FAILED")):
            factory = SyntheticFactory(modules, status=status, chunks=[UPSTREAM_DETAIL.encode("utf-8")],
                headers={"Location": "https://synthetic-redirect.invalid/", "X-Private": KEY})
            await _error(_raw(modules, factory), code, case=case)
            response = _request(factory, tokens=8192, timeout=90)
            assert response.chunks_read == 0 and response.json_reads == 0, case

        # C19-35..38: client-open, stream-open and read timeout/upstream faults.
        for case, fault, code in (("C19-35", "client_timeout", "WORK_AI_TIMEOUT"),
            ("C19-36", "stream_timeout", "WORK_AI_TIMEOUT"), ("C19-37", "read_timeout", "WORK_AI_TIMEOUT"),
            ("C19-38", "read_error", "WORK_AI_UPSTREAM_FAILED")):
            factory = SyntheticFactory(modules, fault=fault)
            await _error(_raw(modules, factory), code, case=case)
            assert len(factory.clients) == 1, case
            assert len(factory.requests) == (0 if fault == "client_timeout" else 1), case
            client = factory.clients[0]
            if client.client_entered:
                assert client.client_closed, case
            if client.stream_entered:
                assert client.stream_closed, case

        # C19-39: a stream without its own timeout still hits the monotonic total
        # deadline while UTC reverses. The two-second test watchdog is distinct
        # from the required one-second production timeout; no sleep is used.
        wall = SimpleNamespace(seconds=1791150000.0)
        factory = SyntheticFactory(modules, wall_clock=wall)
        with modules.patch.object(modules.clock, "time", lambda: wall.seconds):
            try:
                await modules.asyncio.wait_for(
                    _error(_raw(modules, factory, timeout=1), "WORK_AI_TIMEOUT", case="C19-39"), timeout=2)
            except TimeoutError:
                raise AssertionError("C19-39: test watchdog expired; production has no bounded total deadline") from None
        response = _request(factory, tokens=8192, timeout=1)
        assert response.waiting and wall.seconds == 1791146400.0

    _execute(modules, cases)
