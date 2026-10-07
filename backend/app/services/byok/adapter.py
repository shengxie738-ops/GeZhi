"""Single-use bounded Chat Completions over the fixed protected HTTP client.

No SDK, credential client cache, retry, tool execution or result persistence.
Only post-commit invocation may expose a credential to transport headers. SSE
and JSON share exact response-model, strict JSON, text/tool and deadline gates.
"""
from __future__ import annotations
import codecs
from contextlib import asynccontextmanager, aclosing
import json
import math
import re
import threading
import time
from uuid import uuid4
from typing import Annotated, Literal, AsyncIterator
import anyio
from pydantic import Field
from app.core.byok_crypto import decrypt_credential
from app.schemas.model_selection import CustomSelection, ModelID
from app.services.byok.capabilities import purpose_limits, current_evidence, CapabilityProof
from app.services.byok.endpoint_policy import normalize_endpoint
from app.services.byok.errors import ByokError
from app.services.byok.limits import CAPS, ModelCallLimits, check_limit
from app.services.byok.reservations import CommittedCustomReservation, consume_committed_snapshot
from app.services.byok.transport import EGRESS_CAPACITY, open_protected_client
from app.services.byok.types import SafeFrozenModel, ModelPurpose, ModelCompletionState, ADAPTER_ID, ADAPTER_VERSION, POLICY_VERSION

_TUTOR_TOOLS = frozenset({'query_data_structure_knowledge','execute_python_code','generate_algorithm_diagram'})
_PROBE_TOOL = 'byok_probe'
_INVOCATION_AUTHORITY = object()


class ModelRequest(SafeFrozenModel):
    messages: Annotated[tuple[dict,...], Field(min_length=1,max_length=128)]
    purpose: ModelPurpose
    limits: ModelCallLimits
    stream: bool = False
    tool_specs: Annotated[tuple[dict,...], Field(max_length=CAPS.tool_call_count)] = ()
    response_format: dict | None = None


class ModelToolCall(SafeFrozenModel):
    id: Annotated[str, Field(min_length=1,max_length=128,pattern=r'^[A-Za-z0-9_-]+$')]
    name: Annotated[str, Field(min_length=1,max_length=128,pattern=r'^[A-Za-z0-9_]+$')]
    arguments: dict


class ModelUsage(SafeFrozenModel):
    prompt_tokens: Annotated[int, Field(strict=True,ge=0)]
    completion_tokens: Annotated[int, Field(strict=True,ge=0)]
    total_tokens: Annotated[int, Field(strict=True,ge=0)]


class ModelResult(SafeFrozenModel):
    model_state: ModelCompletionState
    content: str | None
    response_model: ModelID
    tool_calls: tuple[ModelToolCall,...] = ()
    usage: ModelUsage | None = None
    request_id: Annotated[str, Field(pattern=r'^[A-Za-z0-9_-]{1,64}$')]


class TextDeltaEvent(SafeFrozenModel):
    kind: Literal['delta'] = 'delta'
    content: str


class ToolDeltaEvent(SafeFrozenModel):
    kind: Literal['tool_delta'] = 'tool_delta'
    tool_index: Annotated[int, Field(strict=True,ge=0,lt=CAPS.tool_call_count)]
    name_fragment: str = ''
    arguments_fragment: str = ''


class TerminalEvent(SafeFrozenModel):
    kind: Literal['terminal'] = 'terminal'
    result: ModelResult


ModelEvent = TextDeltaEvent | ToolDeltaEvent | TerminalEvent


class SecretInvocation:
    __slots__ = ('selection','purpose','limits','provenance','endpoint','aliases','_subject','_verified_capabilities','_secret','_authority','_claimed','_closed','_transport_reachable','_transport_closed')

    def __init__(self, *args, **kwargs):
        raise TypeError('invocations require a committed reservation')

    def __repr__(self):
        return 'SecretInvocation(<redacted>)'

    def __str__(self):
        raise TypeError('secret invocation string conversion is forbidden')

    def __reduce__(self):
        raise TypeError('secret invocation serialization is forbidden')

    def __reduce_ex__(self, protocol):
        raise TypeError('secret invocation serialization is forbidden')

    def model_dump(self, *args, **kwargs):
        raise TypeError('secret invocation serialization is forbidden')

    def model_dump_json(self, *args, **kwargs):
        raise TypeError('secret invocation serialization is forbidden')

    def trace_attributes(self):
        raise TypeError('secret invocation tracing is forbidden')


@asynccontextmanager
async def open_invocation(reservation: CommittedCustomReservation, keyring) -> AsyncIterator[SecretInvocation]:
    if not isinstance(reservation, CommittedCustomReservation):
        raise ByokError('OUTCOME_UNKNOWN')
    snapshot = consume_committed_snapshot(reservation)
    selection = reservation.selection
    try:
        if (snapshot is None or not isinstance(selection,CustomSelection) or snapshot.config_id != selection.config_id
            or snapshot.config_version != selection.config_version or selection.model_id not in snapshot.model_ids
            or type(snapshot.owner_subject) is not str or not snapshot.owner_subject
            or reservation.provenance.selection != selection or reservation.provenance.frozen_caps != reservation.caps
            or (reservation.provenance.adapter_id,reservation.provenance.adapter_version,reservation.provenance.policy_version) != (ADAPTER_ID,ADAPTER_VERSION,POLICY_VERSION)):
            raise ByokError('MODEL_CONFIG_STALE')
        endpoint = normalize_endpoint(snapshot.endpoint.endpoint_url)
        if endpoint != snapshot.endpoint or reservation.provenance.destination_digest != endpoint.destination_digest or reservation.provenance.safe_host != endpoint.host:
            raise ByokError('DESTINATION_CONSENT_REQUIRED')
        aliases = tuple(snapshot.response_model_aliases.get(selection.model_id,()))
        if len(aliases) > CAPS.aliases_per_model:
            raise ByokError('MODEL_CONFIG_STALE')
        proofs = snapshot.capability_evidence
        if type(proofs) is not tuple or any(not isinstance(proof, CapabilityProof) or
            (proof.owner_subject,proof.config_id,proof.config_version,proof.credential_version,proof.destination_digest,
                proof.adapter_id,proof.adapter_version,proof.policy_version) !=
            (snapshot.owner_subject,snapshot.config_id,snapshot.config_version,snapshot.credential_version,endpoint.destination_digest,
                ADAPTER_ID,ADAPTER_VERSION,POLICY_VERSION) for proof in proofs):
            raise ByokError('CAPABILITY_UNVERIFIED')
        secret = decrypt_credential(snapshot.envelope,owner_subject=snapshot.owner_subject,config_id=snapshot.config_id,
            credential_version=snapshot.credential_version,keyring=keyring)
        invocation = object.__new__(SecretInvocation)
        invocation.selection,invocation.purpose,invocation.limits,invocation.provenance = selection,reservation.purpose,reservation.caps,reservation.provenance
        invocation.endpoint,invocation.aliases,invocation._subject = endpoint,aliases,snapshot.owner_subject
        # Current proof alone is not admitted authority. Only exact selected
        # model evidence IDs carried by the frozen provenance authorize use.
        # Config snapshots may legitimately retain other configured models.
        admitted_ids = frozenset(reservation.provenance.capability_evidence_ids)
        invocation._verified_capabilities = frozenset(current_evidence(
            tuple(proof.model_dump() for proof in proofs if proof.evidence_id in admitted_ids), selection
        ))
        invocation._authority,invocation._claimed,invocation._closed = _INVOCATION_AUTHORITY,False,False
        invocation._transport_reachable,invocation._transport_closed = False,True
        with secret.invocation_scope() as scoped:
            invocation._secret = scoped
            try:
                yield invocation
            finally:
                invocation._closed = True
                invocation._secret = None
    except ByokError:
        raise
    except (ValueError,TypeError,AttributeError):
        raise ByokError('CREDENTIAL_UNAVAILABLE') from None
    finally:
        snapshot = None


class InferenceCapacity:
    """Process inference and one student request per actor; no queue.

    Existing teacher owner/shared-run lease remains the caller's authority.
    This lower shared process cap cannot enlarge or release that durable lease.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._active = {}

    @property
    def active(self):
        with self._lock:
            return len(self._active)

    def acquire(self, subject, purpose):
        with self._lock:
            if len(self._active) >= CAPS.inference_active_per_process or (not purpose.startswith(('teacher_','probe_')) and
                any(s == subject and not p.startswith(('teacher_','probe_')) for s,p in self._active.values())):
                raise ByokError('MODEL_CAPACITY_EXCEEDED')
            lease = object()
            self._active[lease] = (subject,purpose)
            return lease

    def release_after_terminal(self, lease, egress):
        if not egress._released:
            return  # Actual closure is uncertain: retaining capacity is fail-closed.
        with self._lock:
            self._active.pop(lease,None)


INFERENCE_CAPACITY = InferenceCapacity()


class _CallDeadline:
    def __init__(self, deadline, cap, clock):
        self.clock,self.last = clock,None
        if type(deadline) not in (int,float) or not math.isfinite(deadline):
            raise ByokError('PROVIDER_TIMEOUT')
        now = self.now()
        self.deadline = min(float(deadline), now + cap)
        self.remaining()

    def now(self):
        now = self.clock()
        if type(now) not in (int,float) or not math.isfinite(now) or (self.last is not None and now < self.last):
            raise ByokError('PROVIDER_TIMEOUT')
        self.last = now
        return now

    def remaining(self):
        remaining = self.deadline - self.now()
        if remaining <= 0:
            raise ByokError('PROVIDER_TIMEOUT')
        return remaining

    async def call(self, fn, *args, **kwargs):
        try:
            with anyio.fail_after(self.remaining()):
                result = await fn(*args, **kwargs)
            self.remaining()
            return result
        except TimeoutError:
            raise ByokError('PROVIDER_TIMEOUT') from None


def parse_retry_after(value):
    if type(value) is not str or not re.fullmatch(r'[0-9]{1,10}',value):
        return None
    return min(int(value),CAPS.retry_after_seconds)


def _pairs(values):
    result = {}
    for key,value in values:
        if key in result:
            raise ValueError('duplicate JSON field')
        result[key] = value
    return result


def _float(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError('nonfinite JSON number')
    return value


def _constant(value):
    raise ValueError('nonfinite JSON constant')


def _json(raw):
    try:
        value = json.loads(raw,object_pairs_hook=_pairs,parse_constant=_constant,parse_float=_float)
        def depth(entry, level=0):
            if level > 32:
                raise ValueError('bounded JSON depth required')
            if type(entry) is dict:
                for key,item in entry.items():
                    key.encode('utf-8')
                    depth(item,level+1)
            elif type(entry) is list:
                for item in entry:depth(item,level+1)
            elif type(entry) is str:
                entry.encode('utf-8')
        depth(value)
        return value
    except (ValueError,TypeError,UnicodeError,RecursionError,OverflowError):
        raise ByokError('PROVIDER_INVALID_RESPONSE') from None


def _prepare(invocation, request):
    if (not isinstance(invocation,SecretInvocation) or invocation._authority is not _INVOCATION_AUTHORITY
        or invocation._closed or invocation._claimed or invocation._secret is None):
        raise ByokError('OUTCOME_UNKNOWN')
    if not isinstance(request,ModelRequest) or request.purpose != invocation.purpose:
        raise ByokError('MODEL_PURPOSE_NOT_ALLOWED')
    if request.stream and not request.purpose.startswith('probe_') and 'stream' not in invocation._verified_capabilities:
        raise ByokError('CAPABILITY_UNVERIFIED')
    allowed = purpose_limits(request.purpose)
    for name,value in request.limits.model_dump().items():
        if value > min(getattr(invocation.limits,name),getattr(allowed,name)):
            raise ByokError('MODEL_BUDGET_EXCEEDED')
    messages = request.messages
    for message in messages:
        if (type(message) is not dict or not set(message).issubset({'role','content','tool_calls','tool_call_id','name'})
            or message.get('role') not in {'system','user','assistant','tool'} or 'content' not in message
            or (message['content'] is not None and type(message['content']) is not str)):
            raise ByokError('INVALID_INPUT')
    body = {'model':invocation.selection.model_id,'messages':messages,'max_tokens':request.limits.output_tokens,'stream':request.stream}
    specs = request.tool_specs
    allowlist = frozenset((_PROBE_TOOL,)) if request.purpose == 'probe_tools' else _TUTOR_TOOLS if request.purpose == 'student_tutor' else frozenset()
    names = set()
    for spec in specs:
        if (type(spec) is not dict or set(spec) != {'type','function'} or spec['type'] != 'function'
            or type(spec['function']) is not dict or not set(spec['function']).issubset({'name','description','parameters','strict'})
            or spec['function'].get('name') not in allowlist or type(spec['function'].get('parameters')) is not dict
            or spec['function']['name'] in names):
            raise ByokError('INVALID_INPUT')
        names.add(spec['function']['name'])
    if request.purpose in {'probe_tools','student_tutor'} and not specs:
        raise ByokError('INVALID_INPUT')
    if specs:
        body['tools'] = specs
        if request.purpose == 'probe_tools':body['tool_choice'] = {'type':'function','function':{'name':_PROBE_TOOL}}
    response_format = request.response_format
    if request.purpose in {'probe_json','teacher_chat','teacher_lesson_outline'}:
        if response_format is not None and response_format != {'type':'json_object'}:
            raise ByokError('INVALID_INPUT')
        body['response_format'] = {'type':'json_object'}
    elif response_format is not None:
        raise ByokError('MODEL_PURPOSE_NOT_ALLOWED')
    try:
        raw = json.dumps(body,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8')
    except (TypeError,ValueError,UnicodeError,RecursionError):
        raise ByokError('INVALID_INPUT') from None
    check_limit('request_bytes',len(raw),request.limits)
    invocation._claimed = True
    return raw,frozenset(names)


def _headers(response, stream, limits):
    status = response.status_code
    if 300 <= status <= 399:
        raise ByokError('PROVIDER_REDIRECT_REJECTED')
    if status in (401,403):
        raise ByokError('PROVIDER_AUTH_FAILED')
    if status == 404:
        raise ByokError('PROVIDER_MODEL_NOT_FOUND')
    if status == 429:
        # Hint is bounded independently and never triggers a retry or body read.
        error = ByokError('PROVIDER_RATE_LIMITED', retry_after_seconds=parse_retry_after(response.headers.get('retry-after')))
        raise error
    if not 200 <= status <= 299:
        raise ByokError('OUTCOME_UNKNOWN')
    encoding = response.headers.get('content-encoding','').strip().lower()
    if encoding not in ('','identity'):
        raise ByokError('PROVIDER_INVALID_RESPONSE')
    media = response.headers.get('content-type','').split(';',1)[0].strip().lower()
    if media != ('text/event-stream' if stream else 'application/json'):
        raise ByokError('PROVIDER_INVALID_RESPONSE')
    declared = response.headers.get('content-length')
    if declared is not None:
        if type(declared) is not str or not re.fullmatch(r'[0-9]{1,20}',declared):
            raise ByokError('PROVIDER_INVALID_RESPONSE')
        check_limit('envelope_bytes',int(declared),limits)


def _model(value, invocation):
    model = value.get('model')
    if type(model) is not str or not model:
        raise ByokError('PROVIDER_INVALID_RESPONSE')
    if model not in (invocation.selection.model_id,*invocation.aliases):
        raise ByokError('MODEL_ID_MISMATCH')
    return model


def _usage(value):
    if value is None:
        return None
    if type(value) is not dict or not all(k in value for k in ('prompt_tokens','completion_tokens','total_tokens')):
        raise ByokError('PROVIDER_INVALID_RESPONSE')
    try:
        result = ModelUsage(**{k:value[k] for k in ('prompt_tokens','completion_tokens','total_tokens')})
    except Exception:
        raise ByokError('PROVIDER_INVALID_RESPONSE') from None
    if result.total_tokens != result.prompt_tokens + result.completion_tokens:
        raise ByokError('PROVIDER_INVALID_RESPONSE')
    return result


def _probe_object(value):
    return type(value) is dict and set(value) == {'ok'} and type(value['ok']) is bool and value['ok'] is True


def _tools(calls, names, limits, purpose):
    if type(calls) is not list or not calls:
        raise ByokError('PROVIDER_INVALID_RESPONSE')
    check_limit('tool_call_count',len(calls),limits)
    result, ids = [],set()
    for call in calls:
        if (type(call) is not dict or set(call) != {'id','type','function'} or call['type'] != 'function'
            or type(call['function']) is not dict or set(call['function']) != {'name','arguments'}
            or call['function']['name'] not in names or type(call['function']['arguments']) is not str):
            raise ByokError('PROVIDER_INVALID_RESPONSE')
        raw = call['function']['arguments']
        check_limit('tool_arguments_bytes',len(raw.encode('utf-8')),limits)
        arguments = _json(raw)
        if type(arguments) is not dict or (purpose == 'probe_tools' and not _probe_object(arguments)):
            raise ByokError('PROVIDER_INVALID_RESPONSE')
        try:
            item = ModelToolCall(id=call['id'],name=call['function']['name'],arguments=arguments)
        except Exception:
            raise ByokError('PROVIDER_INVALID_RESPONSE') from None
        if item.id in ids:
            raise ByokError('PROVIDER_INVALID_RESPONSE')
        ids.add(item.id);result.append(item)
    if purpose == 'probe_tools' and len(result) != 1:
        raise ByokError('PROVIDER_INVALID_RESPONSE')
    return tuple(result)


def _result(content,finish,model,calls,usage,names,request,request_id):
    if content is not None and type(content) is not str:
        raise ByokError('PROVIDER_INVALID_RESPONSE')
    if content is not None:
        check_limit('text_bytes',len(content.encode('utf-8')),request.limits)
    if type(finish) is not str:
        raise ByokError('PROVIDER_INVALID_RESPONSE')
    if calls is not None and type(calls) is not list:
        raise ByokError('PROVIDER_INVALID_RESPONSE')
    if finish == 'tool_calls':
        tools = _tools(calls,names,request.limits,request.purpose)
        return ModelResult(model_state='incomplete',content=content,response_model=model,tool_calls=tools,usage=usage,request_id=request_id)
    if calls:
        raise ByokError('PROVIDER_INVALID_RESPONSE')
    if finish in {'length','content_filter'}:
        return ModelResult(model_state='incomplete',content=content,response_model=model,usage=usage,request_id=request_id)
    if finish != 'stop':
        raise ByokError('PROVIDER_INVALID_RESPONSE')
    if content is None or not content.strip():
        raise ByokError('PROVIDER_EMPTY')
    if request.purpose == 'probe_tools':
        raise ByokError('PROVIDER_INVALID_RESPONSE')
    if request.purpose in {'probe_json','teacher_chat','teacher_lesson_outline'}:
        obj = _json(content)
        if type(obj) is not dict or not obj or (request.purpose == 'probe_json' and not _probe_object(obj)):
            raise ByokError('PROVIDER_INVALID_RESPONSE')
    return ModelResult(model_state='complete',content=content,response_model=model,usage=usage,request_id=request_id)


async def _raw_chunks(response,budget,limits):
    total = 0
    iterator = response.aiter_raw().__aiter__()
    try:
        while True:
            try:chunk = await budget.call(iterator.__anext__)
            except StopAsyncIteration:break
            if type(chunk) is not bytes:
                raise ByokError('PROVIDER_INVALID_RESPONSE')
            total += len(chunk)
            check_limit('envelope_bytes',total,limits)
            yield chunk
    finally:
        # Outer client/response owner closes the actual network. This optional
        # iterator close must not cancel or bypass that shielded transport close.
        with anyio.CancelScope(shield=True):
            close = getattr(iterator,'aclose',None)
            if close is not None:await close()


async def _sse_data(response,budget,limits):
    decoder = codecs.getincrementaldecoder('utf-8')('strict')
    line,event_size,parts = '',0,[]
    async with aclosing(_raw_chunks(response,budget,limits)) as chunks:
        async for raw in chunks:
            try:text = decoder.decode(raw)
            except UnicodeError:raise ByokError('PROVIDER_INVALID_RESPONSE') from None
            for char in text:
                event_size += len(char.encode('utf-8'))
                check_limit('sse_event_bytes',event_size,limits)
                if char == '\n':
                    current = line[:-1] if line.endswith('\r') else line
                    line = ''
                    if current == '':
                        if parts:yield '\n'.join(parts)
                        parts,event_size = [],0
                    elif current.startswith(':'):
                        pass
                    else:
                        field,sep,value = current.partition(':')
                        if sep and value.startswith(' '):value=value[1:]
                        if field == 'data':parts.append(value)
                        elif field not in {'event','id','retry'}:
                            # SSE permits unknown fields; they carry no authority.
                            pass
                else:line += char
            budget.remaining()
    try:tail = decoder.decode(b'',final=True)
    except UnicodeError:raise ByokError('PROVIDER_INVALID_RESPONSE') from None
    if tail or line or parts:
        raise ByokError('PROVIDER_INCOMPLETE')


class ChatCompletionsAdapter:
    def __init__(self, *, clock=time.monotonic):
        self.clock = clock

    @asynccontextmanager
    async def _response(self,invocation,request,raw,budget):
        inference = None
        if not request.purpose.startswith('probe_'):
            inference = INFERENCE_CAPACITY.acquire(invocation._subject,request.purpose)
        try:egress = EGRESS_CAPACITY.acquire()
        except BaseException:
            if inference is not None:
                # No transport can exist before egress acquisition.
                with INFERENCE_CAPACITY._lock:INFERENCE_CAPACITY._active.pop(inference,None)
            raise
        try:
            invocation._transport_closed = False
            async with open_protected_client(invocation.endpoint,request.limits,deadline=budget.deadline,egress_lease=egress) as client:
                # The header exists only in this private transport critical scope.
                headers = {'Authorization':'Bearer '+invocation._secret.header_value(),'Content-Type':'application/json',
                    'Accept':'text/event-stream' if request.stream else 'application/json','Accept-Encoding':'identity'}
                try:
                    async with client.stream('POST',invocation.endpoint.endpoint_url,headers=headers,content=raw) as response:
                        budget.remaining()
                        invocation._transport_reachable = True
                        _headers(response,request.stream,request.limits)
                        yield response
                finally:
                    headers.clear()
        finally:
            invocation._transport_closed = egress._released
            if inference is not None:INFERENCE_CAPACITY.release_after_terminal(inference,egress)

    async def complete(self,invocation: SecretInvocation,request:ModelRequest,*,deadline:float) -> ModelResult:
        if request.stream:
            raise ByokError('INVALID_INPUT')
        raw,names = _prepare(invocation,request)
        budget = _CallDeadline(deadline,request.limits.timeout_seconds,self.clock)
        request_id = uuid4().hex
        try:
            async with self._response(invocation,request,raw,budget) as response:
                body = bytearray()
                async with aclosing(_raw_chunks(response,budget,request.limits)) as chunks:
                    async for chunk in chunks:body.extend(chunk)
                try:text = body.decode('utf-8')
                except UnicodeError:raise ByokError('PROVIDER_INVALID_RESPONSE') from None
                data = _json(text)
                if type(data) is not dict or 'error' in data:
                    raise ByokError('PROVIDER_INVALID_RESPONSE')
                model = _model(data,invocation)
                choices = data.get('choices')
                if type(choices) is not list or len(choices) != 1 or type(choices[0]) is not dict:
                    raise ByokError('PROVIDER_INVALID_RESPONSE')
                choice = choices[0];message = choice.get('message')
                if type(message) is not dict or message.get('role') != 'assistant' or 'content' not in message:
                    raise ByokError('PROVIDER_INVALID_RESPONSE')
                result = _result(message['content'],choice.get('finish_reason'),model,message.get('tool_calls'),
                    _usage(data.get('usage')),names,request,request_id)
                budget.remaining()
            budget.remaining()
            return result
        except BaseException as error:
            if isinstance(error,(ByokError,anyio.get_cancelled_exc_class())):raise
            if isinstance(error,TimeoutError):raise ByokError('PROVIDER_TIMEOUT') from None
            if isinstance(error,Exception):raise ByokError('OUTCOME_UNKNOWN') from None
            raise

    async def stream(self,invocation: SecretInvocation,request:ModelRequest,*,deadline:float) -> AsyncIterator[ModelEvent]:
        if not request.stream:
            raise ByokError('INVALID_INPUT')
        raw,names = _prepare(invocation,request)
        budget = _CallDeadline(deadline,request.limits.timeout_seconds,self.clock)
        request_id = uuid4().hex
        content,tool_parts,finish,model,usage,done = [],{},None,None,None,False
        text_bytes = 0
        try:
            async with self._response(invocation,request,raw,budget) as response:
                async with aclosing(_sse_data(response,budget,request.limits)) as events:
                    async for event in events:
                        if done:
                            raise ByokError('PROVIDER_INVALID_RESPONSE')
                        if event == '[DONE]':
                            if finish is None:raise ByokError('PROVIDER_INCOMPLETE')
                            done = True
                            continue
                        data = _json(event)
                        if type(data) is not dict or 'error' in data:
                            raise ByokError('PROVIDER_INVALID_RESPONSE')
                        current_model = _model(data,invocation)
                        if model is not None and model != current_model:
                            raise ByokError('MODEL_ID_MISMATCH')
                        model = current_model
                        if data.get('usage') is not None:usage=_usage(data['usage'])
                        choices = data.get('choices')
                        if choices == [] and finish is not None and data.get('usage') is not None:continue
                        if type(choices) is not list or len(choices) != 1 or type(choices[0]) is not dict or finish is not None:
                            raise ByokError('PROVIDER_INVALID_RESPONSE')
                        choice = choices[0]
                        if choice.get('index',0) != 0 or type(choice.get('index',0)) is not int:
                            raise ByokError('PROVIDER_INVALID_RESPONSE')
                        delta = choice.get('delta')
                        if type(delta) is not dict or (delta.get('role') is not None and delta['role'] != 'assistant'):
                            raise ByokError('PROVIDER_INVALID_RESPONSE')
                        part = delta.get('content')
                        if part is not None:
                            if type(part) is not str:raise ByokError('PROVIDER_INVALID_RESPONSE')
                            text_bytes += len(part.encode('utf-8'));check_limit('text_bytes',text_bytes,request.limits)
                            content.append(part)
                            if part:yield TextDeltaEvent(content=part)
                        additions = delta.get('tool_calls')
                        if additions is not None:
                            if type(additions) is not list or not additions:raise ByokError('PROVIDER_INVALID_RESPONSE')
                            for addition in additions:
                                if type(addition) is not dict or not set(addition).issubset({'index','id','type','function'}):
                                    raise ByokError('PROVIDER_INVALID_RESPONSE')
                                index = addition.get('index')
                                if type(index) is not int or not 0 <= index < request.limits.tool_call_count:
                                    raise ByokError('MODEL_BUDGET_EXCEEDED')
                                state = tool_parts.setdefault(index,{'id':'','type':'function','function':{'name':'','arguments':''}})
                                fn = addition.get('function',{})
                                if type(fn) is not dict or not set(fn).issubset({'name','arguments'}):raise ByokError('PROVIDER_INVALID_RESPONSE')
                                for field in ('id','type'):
                                    if field in addition:
                                        if type(addition[field]) is not str:raise ByokError('PROVIDER_INVALID_RESPONSE')
                                        if field == 'id':
                                            state['id'] += addition[field]
                                            if len(state['id']) > 128:raise ByokError('PROVIDER_INVALID_RESPONSE')
                                        elif addition[field] != 'function':raise ByokError('PROVIDER_INVALID_RESPONSE')
                                for field in ('name','arguments'):
                                    value = fn.get(field,'')
                                    if type(value) is not str:raise ByokError('PROVIDER_INVALID_RESPONSE')
                                    state['function'][field] += value
                                    if field == 'name' and len(state['function'][field]) > 128:raise ByokError('PROVIDER_INVALID_RESPONSE')
                                check_limit('tool_arguments_bytes',len(state['function']['arguments'].encode('utf-8')),request.limits)
                                yield ToolDeltaEvent(tool_index=index,name_fragment=fn.get('name',''),arguments_fragment=fn.get('arguments',''))
                        reason = choice.get('finish_reason')
                        if reason is not None:
                            if type(reason) is not str:raise ByokError('PROVIDER_INVALID_RESPONSE')
                            finish = reason
                if not done or finish is None or model is None:
                    raise ByokError('PROVIDER_INCOMPLETE')
                if tool_parts and set(tool_parts) != set(range(len(tool_parts))):
                    raise ByokError('PROVIDER_INVALID_RESPONSE')
                result = _result(''.join(content) if content else None,finish,model,
                    [tool_parts[i] for i in sorted(tool_parts)] if tool_parts else None,usage,names,request,request_id)
                budget.remaining()
            budget.remaining()
            yield TerminalEvent(result=result)
        except BaseException as error:
            if isinstance(error,(ByokError,anyio.get_cancelled_exc_class())):raise
            if isinstance(error,TimeoutError):raise ByokError('PROVIDER_TIMEOUT') from None
            if isinstance(error,Exception):raise ByokError('OUTCOME_UNKNOWN') from None
            raise


@asynccontextmanager
async def open_draft_probe_invocation(actor, command):
    """Only a validated explicit draft probe grants this single-use Key scope."""
    from app.core.byok_crypto import SecretValue
    from app.schemas.user_model import DraftProbeRequest
    from app.services.byok.types import AuthenticatedModelActor, validate_destination_consent
    if not isinstance(actor, AuthenticatedModelActor) or not isinstance(command, DraftProbeRequest):
        raise ByokError('INVALID_INPUT')
    endpoint = normalize_endpoint(command.base_url)
    validate_destination_consent(command.destination_consent, endpoint)
    purpose = 'probe_' + command.probe_kind
    invocation = object.__new__(SecretInvocation)
    # Draft identity intentionally is not a CustomSelection or saved config ID.
    from types import SimpleNamespace
    invocation.selection = SimpleNamespace(model_id=command.model_id)
    invocation.purpose, invocation.limits = purpose, purpose_limits(purpose)
    invocation.provenance = None
    invocation.endpoint, invocation.aliases = endpoint, tuple(command.response_model_aliases.get(command.model_id, ()))
    invocation._subject, invocation._verified_capabilities = actor.subject, frozenset()
    invocation._authority, invocation._claimed, invocation._closed = _INVOCATION_AUTHORITY, False, False
    invocation._transport_reachable, invocation._transport_closed = False, True
    secret = SecretValue(command.api_key)
    with secret.invocation_scope() as scoped:
        invocation._secret = scoped
        try:
            yield invocation
        finally:
            invocation._closed, invocation._secret = True, None
