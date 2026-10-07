"""One frozen server policy and monotonic, non-refundable request allowances."""
from __future__ import annotations
from dataclasses import dataclass
import math
import time
from typing import Annotated, Callable
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.services.byok.errors import ByokError


@dataclass(frozen=True)
class FrozenCaps:
    configs_per_actor: int = 20
    models_per_config: int = 20
    name_chars: int = 64
    provider_label_chars: int = 64
    url_chars: int = 512
    key_chars: int = 1024
    model_id_chars: int = 200
    aliases_per_model: int = 3
    api_body_bytes: int = 16 * 1024
    dns_addresses: int = 16
    connect_seconds: int = 5
    probe_seconds: int = 15
    probe_text_tokens: int = 16
    probe_capability_tokens: int = 64
    probe_envelope_bytes: int = 32 * 1024
    probe_text_bytes: int = 4 * 1024
    probe_active_per_actor: int = 1
    probe_starts_per_minute: int = 6
    probe_retention_seconds: int = 15 * 60
    probe_records_per_actor: int = 100
    probe_records_per_process: int = 4096
    probe_record_bytes: int = 2 * 1024
    student_total_seconds: int = 120
    student_call_seconds: int = 30
    student_model_calls: int = 4
    student_output_allowance: int = 8192
    student_main_tokens: int = 4096
    student_tutor_tokens: int = 2048
    profile_tokens: int = 512
    visual_tokens: int = 1024
    request_bytes: int = 128 * 1024
    envelope_bytes: int = 256 * 1024
    text_bytes: int = 128 * 1024
    sse_event_bytes: int = 32 * 1024
    tool_arguments_bytes: int = 4 * 1024
    tool_call_count: int = 3
    teacher_call_seconds: int = 90
    teacher_output_tokens: int = 8192
    teacher_deadline_multiplier: int = 3
    teacher_model_calls: int = 1
    student_active_per_actor: int = 1
    inference_active_per_process: int = 4
    teacher_active_cap: int = 4
    egress_active_per_process: int = 4
    retry_after_seconds: int = 300
    provider_retries: int = 0
    keepalive_connections: int = 0
    http1: bool = True
    http2: bool = False
    proxy: None = None
    uds: None = None
    follow_redirects: bool = False
    trust_env: bool = False
    profile_enabled_by_default: bool = False
    visual_text_enabled: bool = False
    media_enabled: bool = False


CAPS = FrozenCaps()
PositiveInt = Annotated[int, Field(strict=True, gt=0)]


class ModelCallLimits(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra='forbid', hide_input_in_errors=True)
    output_tokens: Annotated[int, Field(strict=True, ge=1, le=CAPS.teacher_output_tokens)]
    timeout_seconds: Annotated[float, Field(gt=0, le=CAPS.teacher_call_seconds, allow_inf_nan=False)]
    connect_seconds: Annotated[float, Field(gt=0, le=CAPS.connect_seconds, allow_inf_nan=False)]
    request_bytes: Annotated[int, Field(strict=True, ge=1, le=CAPS.request_bytes)]
    envelope_bytes: Annotated[int, Field(strict=True, ge=1, le=CAPS.envelope_bytes)]
    text_bytes: Annotated[int, Field(strict=True, ge=1, le=CAPS.text_bytes)]
    sse_event_bytes: Annotated[int, Field(strict=True, ge=1, le=CAPS.sse_event_bytes)]
    tool_arguments_bytes: Annotated[int, Field(strict=True, ge=1, le=CAPS.tool_arguments_bytes)]
    tool_call_count: Annotated[int, Field(strict=True, ge=0, le=CAPS.tool_call_count)]

    @model_validator(mode='after')
    def internally_bounded(self):
        if self.connect_seconds > self.timeout_seconds or self.text_bytes > self.envelope_bytes or self.sse_event_bytes > self.envelope_bytes:
            raise ValueError('inconsistent model call limits')
        return self


_STUDENT_PURPOSE_CAPS = {'student_chat': CAPS.student_main_tokens, 'student_tutor': CAPS.student_tutor_tokens,
    'student_rag': CAPS.student_main_tokens, 'student_paper': CAPS.student_main_tokens,
    'student_academic_review': CAPS.student_main_tokens, 'profile': CAPS.profile_tokens, 'visual_text': CAPS.visual_tokens}
_PROBE_PURPOSE_CAPS = {'probe_text': CAPS.probe_text_tokens, 'probe_stream': CAPS.probe_capability_tokens,
    'probe_json': CAPS.probe_capability_tokens, 'probe_tools': CAPS.probe_capability_tokens}


def _positive(value):
    if type(value) is not int or value <= 0:
        raise ByokError('INVALID_INPUT')
    return value


_BUDGET_FACTORY_TOKEN = object()


class WorkCallBudget:
    """Server-owned allowance. Reservation debits requested caps even on failure.

    Capability/readiness/disabled-flow admission is separate. No usage refund,
    provider retry or optional-step scheduling is performed by this contract.
    """
    def __init__(self, *, clock, purposes, total_seconds, call_seconds, output_allowance, calls, probe=False, _token=None):
        if _token is not _BUDGET_FACTORY_TOKEN:
            raise TypeError('use a server policy budget factory')
        self._clock = clock
        self._purpose_caps = dict(purposes)
        self._last_now = self._now()
        self._deadline = self._last_now + total_seconds
        self._call_seconds = call_seconds
        self._remaining_output_tokens = output_allowance
        self._remaining_calls = calls
        self._probe = probe

    def _now(self):
        now = self._clock()
        if type(now) not in (int, float) or not math.isfinite(now):
            raise ByokError('MODEL_BUDGET_EXCEEDED')
        return now

    @classmethod
    def student(cls, *, clock: Callable = time.monotonic, task_output_tokens: int = CAPS.student_output_allowance,
                task_call_seconds: int = CAPS.student_call_seconds, task_total_seconds: int = CAPS.student_total_seconds,
                task_model_calls: int = CAPS.student_model_calls, adapter_output_tokens: int = CAPS.teacher_output_tokens):
        adapter_cap = _positive(adapter_output_tokens)
        return cls(_token=_BUDGET_FACTORY_TOKEN, clock=clock, purposes={p: min(cap, adapter_cap) for p, cap in _STUDENT_PURPOSE_CAPS.items()},
            total_seconds=min(_positive(task_total_seconds), CAPS.student_total_seconds),
            call_seconds=min(_positive(task_call_seconds), CAPS.student_call_seconds),
            output_allowance=min(_positive(task_output_tokens), CAPS.student_output_allowance),
            calls=min(_positive(task_model_calls), CAPS.student_model_calls))

    @classmethod
    def teacher(cls, *, clock: Callable = time.monotonic, configured_timeout_seconds: int = CAPS.teacher_call_seconds,
                configured_output_tokens: int = CAPS.teacher_output_tokens, adapter_output_tokens: int = CAPS.teacher_output_tokens):
        timeout = min(_positive(configured_timeout_seconds), CAPS.teacher_call_seconds)
        output = min(_positive(configured_output_tokens), _positive(adapter_output_tokens), CAPS.teacher_output_tokens)
        return cls(_token=_BUDGET_FACTORY_TOKEN, clock=clock, purposes={'teacher_chat': output, 'teacher_lesson_outline': output},
            total_seconds=CAPS.teacher_deadline_multiplier * timeout, call_seconds=timeout,
            output_allowance=output, calls=CAPS.teacher_model_calls)

    @classmethod
    def probe(cls, purpose: str, *, clock: Callable = time.monotonic):
        if type(purpose) is not str or purpose not in _PROBE_PURPOSE_CAPS:
            raise ByokError('MODEL_PURPOSE_NOT_ALLOWED')
        output = _PROBE_PURPOSE_CAPS[purpose]
        return cls(_token=_BUDGET_FACTORY_TOKEN, clock=clock, purposes={purpose: output}, total_seconds=CAPS.probe_seconds,
            call_seconds=CAPS.probe_seconds, output_allowance=output, calls=1, probe=True)

    @property
    def remaining_output_tokens(self):
        return self._remaining_output_tokens

    @property
    def remaining_calls(self):
        return self._remaining_calls

    @property
    def deadline(self):
        return self._deadline

    def reserve(self, purpose: str, output_tokens: int) -> ModelCallLimits:
        if type(purpose) is not str or purpose not in self._purpose_caps:
            raise ByokError('MODEL_PURPOSE_NOT_ALLOWED')
        output_tokens = _positive(output_tokens)
        now = self._now()
        if now < self._last_now:
            raise ByokError('MODEL_BUDGET_EXCEEDED')
        # Every finite clock observation advances the high-water mark, even
        # when this reservation is rejected. Failed admissions do not debit
        # call/output allowances and cannot resurrect time or refund usage.
        self._last_now = now
        remaining = self._deadline - now
        if remaining <= 0 or self._remaining_calls < 1 or output_tokens > min(self._purpose_caps[purpose], self._remaining_output_tokens):
            raise ByokError('MODEL_BUDGET_EXCEEDED')
        limits = ModelCallLimits(output_tokens=output_tokens, timeout_seconds=float(min(self._call_seconds, remaining)),
            connect_seconds=float(min(CAPS.connect_seconds, self._call_seconds, remaining)),
            request_bytes=CAPS.request_bytes, envelope_bytes=CAPS.probe_envelope_bytes if self._probe else CAPS.envelope_bytes,
            text_bytes=CAPS.probe_text_bytes if self._probe else CAPS.text_bytes, sse_event_bytes=CAPS.sse_event_bytes,
            tool_arguments_bytes=CAPS.tool_arguments_bytes, tool_call_count=CAPS.tool_call_count)
        self._remaining_output_tokens -= output_tokens
        self._remaining_calls -= 1
        return limits


def check_limit(field: str, amount: int, limits: ModelCallLimits) -> None:
    if field not in {'request_bytes', 'envelope_bytes', 'text_bytes', 'sse_event_bytes', 'tool_arguments_bytes', 'tool_call_count'} or type(amount) is not int or amount < 0:
        raise ByokError('INVALID_INPUT')
    if amount > getattr(limits, field):
        raise ByokError('MODEL_BUDGET_EXCEEDED', fields=(field,))


def validate_api_body_size(raw: bytes) -> None:
    if type(raw) is not bytes:
        raise ByokError('INVALID_INPUT')
    if len(raw) > CAPS.api_body_bytes:
        raise ByokError('BODY_TOO_LARGE')
