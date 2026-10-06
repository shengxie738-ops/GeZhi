"""In-process ASGI client for actual disconnect/header backpressure tests."""
import asyncio
import json


async def dispatch(app, path, body, token, *, disconnect=None, send_hook=None):
    disconnect = disconnect if disconnect is not None else asyncio.Event()
    output, requested = [], False
    async def receive():
        nonlocal requested
        if not requested:
            requested = True
            return dict(type="http.request", body=json.dumps(body).encode(), more_body=False)
        await disconnect.wait()
        return dict(type="http.disconnect")
    async def send(message):
        if send_hook: await send_hook(message)
        output.append(message)
    scope = dict(type="http", asgi=dict(version="3.0", spec_version="2.0"), http_version="1.1",
        method="POST", scheme="http", path=path, raw_path=path.encode(), query_string=b"", root_path="",
        headers=[(b"content-type", b"application/json"), (b"authorization", ("Bearer " + token).encode())],
        client=("synthetic", 123), server=("synthetic", 80))
    await app(scope, receive, send)
    return output


def response_text(messages):
    return b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body").decode()
