"""Synthetic OpenAI-compatible HTTP transport, never a model/auth/SQL mock."""
import asyncio
import json

import httpx


CONTENT = "Synthetic paper analysis: metadata and supplied abstract only."


class PaperTransport:
    def __init__(self, *, reason="stop", content=CONTENT, status=200, delay=0):
        self.reason, self.content, self.status, self.delay = reason, content, status, delay
        self.calls = []
        self.entered = asyncio.Event()
        self.release = None
        self.on_request = None
        self.sql_checkouts = lambda: 0
        self.tool_calls = None
        self.function_call = None

    def record(self, request):
        body = json.loads(request.content)
        self.calls.append({"url": str(request.url), "body": body,
                           "synthetic": True, "sql_checkouts": self.sql_checkouts(),
                           "timeout": request.extensions.get("timeout")})
        return body

    def response(self, request, body, *, asynchronous, http_module=httpx):
        if self.status != 200:
            return http_module.Response(self.status, request=request,
                json={"error": {"message": "SYNTHETIC PRIVATE UPSTREAM DETAIL", "type": "server_error"}})
        if body.get("stream"):
            chunks = [dict(id="synthetic-paper", object="chat.completion.chunk", model=body["model"],
                choices=[dict(index=0, delta={"content": self.content}, finish_reason=None)])]
            if self.tool_calls:
                chunks[0]["choices"][0]["delta"]["tool_calls"] = [{"index": i, **tool} for i, tool in enumerate(self.tool_calls)]
            if self.function_call:
                chunks[0]["choices"][0]["delta"]["function_call"] = self.function_call
            if self.reason is not None:
                chunks.append(dict(id="synthetic-paper", object="chat.completion.chunk", model=body["model"],
                    choices=[dict(index=0, delta={}, finish_reason=self.reason)]))
            payload = [b"data: " + json.dumps(chunk).encode() + b"\n\n" for chunk in chunks]
            payload.append(b"data: [DONE]\n\n")
            if asynchronous:
                delay = self.delay
                class Events(http_module.AsyncByteStream):
                    async def __aiter__(self):
                        if delay:
                            await asyncio.sleep(delay)
                        for part in payload:
                            yield part
                stream = Events()
            else:
                stream = http_module.ByteStream(b"".join(payload))
            return http_module.Response(200, request=request, headers={"content-type": "text/event-stream"}, stream=stream)
        message = {"role": "assistant", "content": self.content}
        if self.tool_calls: message["tool_calls"] = self.tool_calls
        if self.function_call: message["function_call"] = self.function_call
        return http_module.Response(200, request=request, json=dict(id="synthetic-paper", object="chat.completion",
            model=body["model"], choices=[dict(index=0, message=message,
                finish_reason=self.reason)], usage=dict(prompt_tokens=1, completion_tokens=1, total_tokens=2)))

    async def handle_async(self, request, *, http_module=httpx):
        body = self.record(request)
        self.entered.set()
        if self.on_request:
            override = await self.on_request(request)
            if override is not None:
                scripted = PaperTransport(reason=override.get("reason", "stop"), content=override["content"])
                return scripted.response(request, body, asynchronous=True, http_module=http_module)
        if self.release:
            await self.release.wait()
        if self.delay and not body.get("stream"):
            await asyncio.sleep(self.delay)
        return self.response(request, body, asynchronous=True, http_module=http_module)

    def handle_sync(self, request, *, http_module=httpx):
        return self.response(request, self.record(request), asynchronous=False, http_module=http_module)

    def install(self, monkeypatch):
        # Some supported SDK versions use their httpx2 default client, while
        # LangChain/custom clients use httpx. Patch both actual HTTP boundaries.
        from openai import _base_client
        sdk_http = getattr(_base_client, "httpx", None) or getattr(_base_client, "httpx2")
        modules = {httpx, sdk_http}
        for module in modules:
            async def asynchronous(_transport, request, _module=module):
                return await self.handle_async(request, http_module=_module)
            def synchronous(_transport, request, _module=module):
                return self.handle_sync(request, http_module=_module)
            monkeypatch.setattr(module.AsyncHTTPTransport, "handle_async_request", asynchronous)
            monkeypatch.setattr(module.HTTPTransport, "handle_request", synchronous)
