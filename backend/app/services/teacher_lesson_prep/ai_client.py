import asyncio
import json
import re
import time
from typing import Any

import httpx

from app.core.config import settings


RAW_ENVELOPE_LIMIT = 256 * 1024
RAW_CONTENT_LIMIT = 128 * 1024


class LessonPrepAIError(RuntimeError):
    """A bounded Work-facing failure, never an upstream body or exception."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _positive_limit(value: Any) -> int:
    if type(value) is not int or value < 1:
        raise LessonPrepAIError("WORK_AI_UNAVAILABLE")
    return value


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate provider JSON name")
        value[key] = item
    return value


def _nonfinite(value):
    raise ValueError("nonfinite provider JSON value")


class LessonPrepAIClient:
    def __init__(self, client_factory=httpx.AsyncClient):
        self.client_factory = client_factory

    async def complete(self, *, system_prompt: str, user_prompt: str, temperature: float = 0.2,
                       max_output_tokens: int | None = None,
                       timeout_seconds: int | None = None) -> dict[str, Any]:
        content = await self._request_content(system_prompt=system_prompt, user_prompt=user_prompt,
            temperature=temperature, max_output_tokens=max_output_tokens,
            timeout_seconds=timeout_seconds, bounded_raw=False)
        if isinstance(content, dict):
            return content
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("AI response content is empty")
        return self._parse_json(content)

    async def complete_raw(self, *, system_prompt: str, user_prompt: str, temperature: float = 0.2,
                           max_output_tokens: int, timeout_seconds: int) -> str:
        """Return the actual string; strict Work result parsing belongs to Work."""
        return await self._request_content(system_prompt=system_prompt, user_prompt=user_prompt,
            temperature=temperature, max_output_tokens=max_output_tokens,
            timeout_seconds=timeout_seconds, bounded_raw=True)

    async def _request_content(self, *, system_prompt: str, user_prompt: str, temperature: float,
                               max_output_tokens: int | None, timeout_seconds: int | None,
                               bounded_raw: bool) -> Any:
        # Capture one configuration snapshot. Neither caller can choose another
        # endpoint/model/key, and raw limits cannot expand that snapshot's caps.
        key = getattr(settings, "AI_LESSON_PREP_API_KEY", None)
        endpoint = getattr(settings, "AI_LESSON_PREP_BASE_URL", None)
        model = getattr(settings, "AI_LESSON_PREP_MODEL", None)
        configured_tokens = getattr(settings, "AI_LESSON_PREP_MAX_OUTPUT_TOKENS", None)
        configured_timeout = getattr(settings, "AI_LESSON_PREP_TIMEOUT_SECONDS", None)
        if bounded_raw:
            if any(type(value) is not str or not value.strip() for value in (key, endpoint, model)):
                raise LessonPrepAIError("WORK_AI_UNAVAILABLE")
            tokens = min(_positive_limit(configured_tokens), _positive_limit(max_output_tokens), 8192)
            timeout = min(_positive_limit(configured_timeout), _positive_limit(timeout_seconds), 90)
        else:
            if not key:
                raise RuntimeError("AI lesson preparation API key is not configured")
            # Omitted/None options retain the established configured post path,
            # including its legacy dictionary/fence and exception behavior.
            tokens = configured_tokens if max_output_tokens is None else min(
                _positive_limit(configured_tokens), _positive_limit(max_output_tokens))
            timeout = configured_timeout if timeout_seconds is None else min(
                _positive_limit(configured_timeout), _positive_limit(timeout_seconds))
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": tokens,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        if bounded_raw:
            return await self._stream_raw_content(endpoint, headers, payload, timeout)
        async with self.client_factory(timeout=timeout) as client:
            response = await client.post(endpoint, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
        choices = data.get("choices") if isinstance(data, dict) else None
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("AI response does not contain choices")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        return content

    async def _stream_raw_content(self, endpoint: str, headers: dict, payload: dict,
                                  timeout_seconds: int) -> str:
        # asyncio's timeout uses the event-loop monotonic clock. The independent
        # monotonic checks also cover synchronous decoding/cleanup gaps and do
        # not renew the captured budget when UTC or configuration changes.
        deadline = time.monotonic() + timeout_seconds
        try:
            async with asyncio.timeout(timeout_seconds):
                async with self.client_factory(timeout=timeout_seconds, follow_redirects=False) as client:
                    async with client.stream("POST", endpoint, headers=headers, json=payload,
                                             follow_redirects=False) as response:
                        status = response.status_code
                        if status == 429:
                            raise LessonPrepAIError("WORK_AI_RATE_LIMITED")
                        if type(status) is not int or not 200 <= status < 300:
                            raise LessonPrepAIError("WORK_AI_UPSTREAM_FAILED")
                        self._check_content_length(response.headers.get("Content-Length"))
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            if time.monotonic() >= deadline:
                                raise TimeoutError
                            if type(chunk) is not bytes or len(chunk) > RAW_ENVELOPE_LIMIT - len(body):
                                raise LessonPrepAIError("WORK_AI_INVALID_RESPONSE")
                            body.extend(chunk)
                        content = self._decode_raw_content(bytes(body))
                        if time.monotonic() >= deadline:
                            raise TimeoutError
                # A result is not returned until both stream and client have
                # unwound; timing out is not evidence that remote billing stops.
                if time.monotonic() >= deadline:
                    raise TimeoutError
            return content
        except LessonPrepAIError:
            raise
        except (TimeoutError, httpx.TimeoutException):
            raise LessonPrepAIError("WORK_AI_TIMEOUT") from None
        except Exception:
            # Cancellation is a BaseException and propagates after context
            # cleanup. Other upstream faults expose only this allowlisted code.
            raise LessonPrepAIError("WORK_AI_UPSTREAM_FAILED") from None

    @staticmethod
    def _check_content_length(value: Any) -> None:
        if value is None:
            return
        if type(value) is not str:
            raise LessonPrepAIError("WORK_AI_INVALID_RESPONSE")
        text = value.strip()
        if not text or len(text) > 20 or not text.isascii() or not text.isdigit():
            raise LessonPrepAIError("WORK_AI_INVALID_RESPONSE")
        if int(text) > RAW_ENVELOPE_LIMIT:
            raise LessonPrepAIError("WORK_AI_INVALID_RESPONSE")

    @staticmethod
    def _decode_raw_content(body: bytes) -> str:
        try:
            data = json.loads(body.decode("utf-8"), object_pairs_hook=_unique_object,
                              parse_constant=_nonfinite)
            choices = data.get("choices") if type(data) is dict else None
            if type(choices) is not list or not choices or type(choices[0]) is not dict:
                raise ValueError("provider choices required")
            message = choices[0].get("message")
            content = message.get("content") if type(message) is dict else None
            if type(content) is not str or not content.strip() or len(content.encode("utf-8")) > RAW_CONTENT_LIMIT:
                raise ValueError("bounded provider string required")
            return content
        except (TypeError, ValueError, UnicodeError, RecursionError):
            raise LessonPrepAIError("WORK_AI_INVALID_RESPONSE") from None

    @staticmethod
    def _parse_json(content: str) -> dict[str, Any]:
        text = content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s*```$", "", text)
        value = json.loads(text)
        if not isinstance(value, dict):
            raise ValueError("AI response must be a JSON object")
        return value
