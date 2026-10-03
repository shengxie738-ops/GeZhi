"""Offline regression fixtures: query fidelity, provider integrity and bounded work."""
import asyncio
from datetime import datetime, timezone
from email.utils import format_datetime
from urllib.parse import quote

import httpx
import pytest
from fastapi import HTTPException
from app.services import academic_sources as sources
from app.api.endpoints import academic as routes

EMPTY_ATOM = '<feed xmlns="http://www.w3.org/2005/Atom"/>'
VALID_ATOM = '''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
<id>http://arxiv.org/abs/1706.03762v7</id><title>Attention Is All You Need</title>
<published>2017-06-12T00:00:00Z</published><summary>Source abstract</summary>
<link title="pdf" href="http://arxiv.org/pdf/1706.03762v7" type="application/pdf"/>
</entry></feed>'''
LEGACY_DOI = '10.1002/(SICI)1099-0844(199912)17:4<290::AID-CBF849>3.0.CO;2-P'


@pytest.mark.parametrize('value,expected', [
    ('10.1000/test(abc)', '10.1000/test(abc)'),
    (LEGACY_DOI, LEGACY_DOI.lower()),
    ('https://doi.org/' + quote(LEGACY_DOI, safe=''), LEGACY_DOI.lower()),
    ('doi: 10.1000/test.;', '10.1000/test.;'),
    ('https://doi.org/10.1000/182.', '10.1000/182.'),
    ('see 10.1000/182 for details', ''),
    ('https://evil.example/10.1000/182', ''),
])
def test_exact_doi_is_suffix_safe_and_never_extracted_from_prose(value, expected):
    assert sources.normalize_doi_query(value) == expected


@pytest.mark.parametrize('value,expected', [
    ('1706.03762v7', '1706.03762v7'),
    ('https://arxiv.org/pdf/1706.03762v7.pdf', '1706.03762v7'),
    ('arxiv:math.GT/0309136v1', 'math.GT/0309136v1'),
    ('solv-int/9901001', 'solv-int/9901001'),
    ('https://evil.example/abs/1706.03762', ''),
    ('2024', ''), ('1713.03762', ''), ('nonsense', ''),
])
def test_strict_arxiv_identifier_preserves_lookup_version(value, expected):
    assert sources.normalize_arxiv_identifier(value) == expected


@pytest.mark.parametrize('value,expected', [
    ('2024年图神经网络用于药物发现', '2024年 graph neural networks 用于药物发现'),
    ('机器学习 cancer 2024', 'machine learning cancer 2024'),
    ('大语言模型医疗幻觉', 'large language models 医疗幻觉'),
    ('图神经网络和深度学习', 'graph neural networks 和 deep learning'),
    ('"图神经网络" traffic', '"图神经网络" traffic'),
])
def test_query_translation_replaces_spans_without_losing_qualifiers(value, expected):
    assert sources.sanitize_academic_search_query(value) == expected


@pytest.mark.parametrize('body,code,status', [
    ('<not xml', 'invalid_response', 502),
    ('', 'invalid_response', 502),
    ('<html><body>Error</body></html>', 'invalid_response', 502),
    ('<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/api/errors#incorrect_id_format</id><title>Error</title></entry></feed>', 'invalid_query', 422),
    ('<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>https://arxiv.org/abs/not-an-id</id><title>Fake</title></entry></feed>', 'invalid_response', 502),
])
def test_invalid_arxiv_payload_is_never_a_successful_empty_or_fake_paper(body, code, status):
    with pytest.raises(HTTPException) as raised:
        sources.parse_arxiv_atom(body)
    assert raised.value.status_code == status
    assert raised.value.detail['source'] == 'arxiv'
    assert raised.value.detail['code'] == code


def test_valid_empty_atom_and_versioned_links_remain_distinct():
    assert sources.parse_arxiv_atom(EMPTY_ATOM) == []
    paper = sources.parse_arxiv_atom(VALID_ATOM)[0]
    assert paper['arxivId'] == '1706.03762'
    assert paper['arxivVersion'] == 'v7'
    assert paper['officialUrl'].endswith('/1706.03762v7')
    assert paper['openAccessUrl'].endswith('/1706.03762v7')


@pytest.fixture
def transport(monkeypatch):
    original = httpx.AsyncClient
    seen = []
    replies = []
    async def handle(request):
        seen.append(request)
        reply = replies.pop(0) if replies else httpx.Response(200, text=EMPTY_ATOM)
        if isinstance(reply, Exception):
            raise reply
        return reply
    monkeypatch.setattr(sources.httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs))
    # A fresh set of per-worker gates and no cache contamination across cases.
    if hasattr(sources, '_provider_gates'):
        monkeypatch.setattr(sources, '_provider_gates', {})
    sources.academic_cache.clear()
    return seen, replies


@pytest.mark.asyncio
@pytest.mark.parametrize('value,identifier', [
    ('1706.03762', '1706.03762'),
    ('https://arxiv.org/abs/1706.03762v7', '1706.03762v7'),
    ('https://arxiv.org/pdf/math.GT/0309136v1.pdf', 'math.GT/0309136v1'),
])
async def test_exact_arxiv_uses_id_list_not_keyword_search(transport, value, identifier):
    seen, replies = transport
    replies.append(httpx.Response(200, text=VALID_ATOM.replace("1706.03762v7", identifier if "v" in identifier else identifier + "v1")))
    await sources.fetch_arxiv(value)
    assert seen[0].url.params['id_list'] == identifier
    assert 'search_query' not in seen[0].url.params


@pytest.mark.asyncio
@pytest.mark.parametrize('value,expected', [
    ('graph neural networks traffic forecasting', '(all:graph AND all:neural AND all:networks AND all:traffic AND all:forecasting)'),
    ('"graph neural networks" traffic', '(all:"graph neural networks" AND all:traffic)'),
    ('research: traffic', '(all:"research:" AND all:traffic)'),
    ('ti:"graph neural networks" AND cat:cs.LG', 'ti:"graph neural networks" AND cat:cs.LG'),
])
async def test_arxiv_compiler_separates_valid_advanced_syntax_from_plain_text(transport, value, expected):
    seen, replies = transport
    replies.append(httpx.Response(200, text=EMPTY_ATOM))
    await sources.fetch_arxiv(value)
    assert seen[0].url.params['search_query'] == expected


@pytest.mark.asyncio
async def test_exact_crossref_doi_preserved_and_404_is_truthful(transport):
    seen, replies = transport
    replies.append(httpx.Response(404, text='Resource not found'))
    with pytest.raises(HTTPException) as raised:
        await sources.fetch_crossref(LEGACY_DOI)
    assert quote(LEGACY_DOI.lower(), safe='') in str(seen[0].url)
    assert raised.value.status_code == 404
    assert raised.value.detail['source'] == 'crossref'
    assert raised.value.detail['code'] == 'not_found'


@pytest.mark.asyncio
@pytest.mark.parametrize('data', [{}, {'results': None}, {'results': {}}, {'results': [None]}])
async def test_openalex_malformed_success_json_is_not_empty_success(transport, data):
    _, replies = transport
    replies.append(httpx.Response(200, json=data))
    with pytest.raises(HTTPException) as raised:
        await sources.fetch_openalex('deep learning')
    assert raised.value.status_code == 502
    assert raised.value.detail['code'] == 'invalid_response'


@pytest.mark.asyncio
async def test_openalex_anonymous_and_bearer_both_remain_supported(transport, monkeypatch):
    seen, replies = transport
    for key in ['', 'test-only-key']:
        monkeypatch.setattr(sources.settings, 'OPENALEX_API_KEY', key)
        replies.append(httpx.Response(200, json={'results': []}))
        await sources.fetch_openalex('deep learning')
    assert 'authorization' not in seen[0].headers
    assert seen[1].headers['authorization'] == 'Bearer test-only-key'
    assert 'api_key' not in seen[1].url.params


@pytest.mark.asyncio
async def test_failed_arxiv_response_is_not_cached(transport):
    seen, replies = transport
    replies.extend([httpx.Response(200, text='<broken'), httpx.Response(200, text=EMPTY_ATOM)])
    with pytest.raises(HTTPException):
        await routes.search_arxiv(query='transformer', limit=5, auth={})
    response = await routes.search_arxiv(query='transformer', limit=5, auth={})
    assert response['cached'] is False
    assert response['items'] == []
    assert len(seen) == 2


@pytest.mark.asyncio
async def test_route_discloses_lossless_effective_query_without_claiming_year_filter(transport):
    _, replies = transport
    replies.append(httpx.Response(200, json={'results': []}))
    response = await routes.search_openalex(query='机器学习 cancer 2024', limit=5, auth={})
    assert response['originalQuery'] == '机器学习 cancer 2024'
    assert response['effectiveQuery'] == 'machine learning cancer 2024'
    assert response['queryType'] == 'keywords'
    assert response['queryPlanning']['structuredFiltersApplied'] == []


@pytest.mark.asyncio
async def test_same_cache_miss_coalesces_and_waiter_cancellation_does_not_cancel_owner(monkeypatch):
    entered, finish = asyncio.Event(), asyncio.Event()
    calls = 0
    async def provider(*args):
        nonlocal calls
        calls += 1
        entered.set()
        await finish.wait()
        return [{'id': 'paper'}]
    monkeypatch.setattr(routes, 'fetch_openalex', provider)
    sources.academic_cache.clear()
    owner = asyncio.create_task(routes.search_openalex(query='singleflight', limit=5, auth={}))
    await entered.wait()
    waiter = asyncio.create_task(routes.search_openalex(query='Singleflight', limit=5, auth={}))
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    finish.set()
    response = await owner
    assert response['items'] == [{'id': 'paper'}]
    assert calls == 1
    assert (await routes.search_openalex(query='singleflight', limit=5, auth={}))['cached'] is True


@pytest.mark.asyncio
async def test_end_to_end_budget_includes_queue_and_network(monkeypatch):
    started = asyncio.Event()
    original = httpx.AsyncClient
    calls = 0
    async def handler(request):
        nonlocal calls
        calls += 1
        started.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(sources.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(sources.settings, 'ACADEMIC_HTTP_TIMEOUT_SECONDS', .03)
    if hasattr(sources, '_provider_gates'):
        monkeypatch.setattr(sources, '_provider_gates', {})
    owner = asyncio.create_task(sources.fetch_crossref('first'))
    await started.wait()
    queued = asyncio.create_task(sources.fetch_crossref('second'))
    for task in [owner, queued]:
        with pytest.raises(HTTPException) as raised:
            await asyncio.wait_for(task, .2)
        assert raised.value.status_code == 504
        assert raised.value.detail['source'] == 'crossref'
    assert calls == 1


class Clock:
    def __init__(self):
        self.now = 100.0
        self.waits = []
    def monotonic(self):
        return self.now
    async def sleep(self, seconds):
        self.waits.append(seconds)
        self.now += seconds


@pytest.mark.asyncio
async def test_retry_respects_provider_spacing_and_numeric_cooldown(transport, monkeypatch):
    seen, replies = transport
    clock = Clock()
    monkeypatch.setattr(sources, '_monotonic', clock.monotonic, raising=False)
    monkeypatch.setattr(sources, '_sleep', clock.sleep, raising=False)
    replies.extend([httpx.Response(429, headers={'Retry-After': '5'}), httpx.Response(200, text=EMPTY_ATOM)])
    assert await sources.fetch_arxiv('transformer') == []
    assert len(seen) == 2
    assert clock.waits == [5.0]


@pytest.mark.asyncio
@pytest.mark.parametrize('header', ['60', format_datetime(datetime(2030, 1, 1, 0, 1, tzinfo=timezone.utc), usegmt=True)])
async def test_long_retry_after_is_not_truncated_and_cooldown_survives_call(transport, monkeypatch, header):
    seen, replies = transport
    clock = Clock()
    monkeypatch.setattr(sources, '_monotonic', clock.monotonic, raising=False)
    monkeypatch.setattr(sources, '_sleep', clock.sleep, raising=False)
    monkeypatch.setattr(sources, '_wall_time', lambda: datetime(2030, 1, 1, tzinfo=timezone.utc).timestamp(), raising=False)
    replies.append(httpx.Response(429, headers={'Retry-After': header}))
    for _ in range(2):
        with pytest.raises(HTTPException) as raised:
            await sources.fetch_openalex('cooldown')
        assert raised.value.status_code == 429
        assert raised.value.detail['retryAfter'] == 60
        assert raised.value.headers['Retry-After'] == '60'
    assert len(seen) == 1
    assert not clock.waits


@pytest.mark.parametrize('normalizer,value', [
    (sources.normalize_doi_query, 'https://doi.org:bad/10.1000/a'),
    (sources.normalize_arxiv_identifier, 'https://arxiv.org:bad/abs/1706.03762'),
    (sources.normalize_doi_query, 'https://[bad/10.1000/a'),
    (sources.normalize_arxiv_identifier, 'https://[bad/abs/1706.03762'),
])
def test_malformed_identifier_url_is_invalid_instead_of_a_server_error(normalizer, value):
    assert normalizer(value) == ''


def test_quoted_whitespace_is_not_rewritten():
    assert sources.sanitize_academic_search_query('"A  B" 图神经网络') == '"A  B" graph neural networks'


@pytest.mark.asyncio
async def test_arxiv_cache_key_preserves_boolean_syntax_intent(monkeypatch):
    observed = []
    async def provider(query, limit):
        observed.append(query)
        return [{'title': query}]
    monkeypatch.setattr(routes, 'fetch_arxiv', provider)
    sources.academic_cache.clear()
    first = await routes.search_arxiv(query='ti:foo AND ti:bar', limit=5, auth={})
    second = await routes.search_arxiv(query='ti:foo and ti:bar', limit=5, auth={})
    assert len(observed) == 2
    assert second['cached'] is False
    assert second['items'] != first['items']


@pytest.mark.parametrize('query,expected', [
    ('graph neural networks -survey', '(all:graph AND all:neural AND all:networks ANDNOT all:survey)'),
    ('graph -"survey paper"', '(all:graph ANDNOT all:"survey paper")'),
    ('图神经网络 -深度学习', '(all:graph AND all:neural AND all:networks ANDNOT all:"deep learning")'),
])
def test_arxiv_negative_terms_never_become_positive_requirements(query, expected):
    assert sources.compile_arxiv_query(sources.sanitize_academic_search_query(query)) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize('provider,query,source', [
    (sources.fetch_arxiv, 'doi:10.1000/182', 'arxiv'),
    (sources.fetch_crossref, 'arxiv:1706.03762', 'crossref'),
    (sources.fetch_openalex, 'arxiv:1706.03762', 'openalex'),
])
async def test_exact_identifier_is_not_silently_downgraded_by_an_incompatible_source(transport, provider, query, source):
    seen, _ = transport
    with pytest.raises(HTTPException) as raised:
        await provider(query)
    assert raised.value.status_code == 422
    assert raised.value.detail['source'] == source
    assert raised.value.detail['code'] == 'unsupported_identifier'
    assert seen == []


@pytest.mark.parametrize('body', [
    '<feed xmlns="http://www.w3.org/2005/Atom"><entry xmlns=""><id>1706.03762</id><title>Not Atom</title></entry></feed>',
    '<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>https://[bad/abs/1706.03762</id><title>Bad URL</title></entry></feed>',
])
def test_invalid_entry_namespace_or_url_is_provider_error(body):
    with pytest.raises(HTTPException) as raised:
        sources.parse_arxiv_atom(body)
    assert raised.value.status_code == 502
    assert raised.value.detail['code'] == 'invalid_response'


@pytest.mark.asyncio
@pytest.mark.parametrize('provider,query,source', [
    (sources.fetch_openalex, 'https://doi.org:bogus/10.1000/abc', 'openalex'),
    (sources.fetch_arxiv, 'https://arxiv.org:bogus/abs/1706.03762', 'arxiv'),
])
async def test_malformed_official_identifier_url_is_rejected_before_any_request(transport, provider, query, source):
    seen, _ = transport
    with pytest.raises(HTTPException) as raised:
        await provider(query)
    assert raised.value.status_code == 422
    assert raised.value.detail['source'] == source
    assert raised.value.detail['code'] == 'invalid_identifier'
    assert seen == []


@pytest.mark.asyncio
async def test_failed_coalesced_request_is_removed_and_can_be_retried(monkeypatch):
    entered, finish = asyncio.Event(), asyncio.Event()
    calls = 0
    async def provider(query, limit):
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            await finish.wait()
            raise sources._source_error('openalex', 'invalid_response', 'Synthetic malformed provider response')
        return [{'id': 'valid'}]
    monkeypatch.setattr(routes, 'fetch_openalex', provider)
    sources.academic_cache.clear()
    first = asyncio.create_task(routes.search_openalex(query='retry-flight', limit=5, auth={}))
    await entered.wait()
    second = asyncio.create_task(routes.search_openalex(query='retry-flight', limit=5, auth={}))
    await asyncio.sleep(0)
    finish.set()
    results = await asyncio.gather(first, second, return_exceptions=True)
    assert all(isinstance(result, HTTPException) for result in results)
    assert calls == 1
    response = await routes.search_openalex(query='retry-flight', limit=5, auth={})
    assert response['cached'] is False
    assert response['items'] == [{'id': 'valid'}]
    assert calls == 2


@pytest.mark.asyncio
async def test_short_retry_after_still_respects_arxiv_minimum_spacing(transport, monkeypatch):
    seen, replies = transport
    clock = Clock()
    monkeypatch.setattr(sources, '_monotonic', clock.monotonic)
    monkeypatch.setattr(sources, '_sleep', clock.sleep)
    monkeypatch.setattr(sources.settings, 'ARXIV_MIN_INTERVAL_SECONDS', 3)
    replies.extend([httpx.Response(429, headers={'Retry-After': '1'}), httpx.Response(200, text=EMPTY_ATOM)])
    assert await sources.fetch_arxiv('spaced-retry') == []
    assert len(seen) == 2
    assert clock.waits == [3.0]


@pytest.mark.asyncio
async def test_provider_gate_never_overlaps_slow_successful_attempts(monkeypatch):
    first_entered, release = asyncio.Event(), asyncio.Event()
    original = httpx.AsyncClient
    active, maximum, calls = 0, 0, 0
    async def handler(request):
        nonlocal active, maximum, calls
        active += 1
        calls += 1
        maximum = max(maximum, active)
        first_entered.set()
        await release.wait()
        active -= 1
        return httpx.Response(200, json={'results': []})
    monkeypatch.setattr(sources.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(sources, '_provider_gates', {})
    first = asyncio.create_task(sources.fetch_openalex('one'))
    await first_entered.wait()
    second = asyncio.create_task(sources.fetch_openalex('two'))
    await asyncio.sleep(0)
    release.set()
    assert await asyncio.gather(first, second) == [[], []]
    assert calls == 2
    assert maximum == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('response,status,code', [
    (httpx.Response(404), 502, 'upstream_error'),
    (httpx.Response(403), 502, 'upstream_auth_error'),
    (httpx.Response(400), 422, 'invalid_query'),
    (httpx.Response(500), 502, 'upstream_error'),
])
async def test_keyword_provider_errors_are_truthful_and_source_specific(transport, response, status, code):
    _, replies = transport
    replies.append(response)
    with pytest.raises(HTTPException) as raised:
        await sources.fetch_openalex('ordinary keyword')
    assert raised.value.status_code == status
    assert raised.value.detail['source'] == 'openalex'
    assert raised.value.detail['code'] == code


@pytest.mark.asyncio
async def test_openalex_exact_doi_uses_filter_not_a_keyword(transport):
    seen, replies = transport
    replies.append(httpx.Response(200, json={'results': [{'doi': 'https://doi.org/10.1000/a', 'title': 'Exact DOI fixture'}]}))
    await sources.fetch_openalex('doi:10.1000/a')
    assert seen[0].url.params['filter'] == 'doi:https://doi.org/10.1000/a'
    assert 'search' not in seen[0].url.params


@pytest.mark.asyncio
async def test_openalex_exact_doi_cannot_accept_an_unrelated_record(transport):
    _, replies = transport
    replies.append(httpx.Response(200, json={'results': [{'doi': 'https://doi.org/10.1000/b'}]}))
    with pytest.raises(HTTPException) as raised:
        await sources.fetch_openalex('10.1000/a')
    assert raised.value.status_code == 502
    assert raised.value.detail['code'] == 'invalid_response'


@pytest.mark.asyncio
async def test_valid_unquoted_chinese_arxiv_field_query_is_preserved(transport):
    seen, replies = transport
    replies.append(httpx.Response(200, text=EMPTY_ATOM))
    query = 'ti:图神经网络 AND cat:cs.LG'
    await sources.fetch_arxiv(query)
    assert seen[0].url.params['search_query'] == query


@pytest.mark.parametrize('query,expected', [
    ("'深度学习' 2024", "'深度学习' 2024"),
    ("'A  B' 图神经网络", "'A  B' graph neural networks"),
])
def test_single_quoted_explicit_text_is_not_retranslated(query, expected):
    assert sources.sanitize_academic_search_query(query) == expected


def test_single_quoted_plain_arxiv_phrase_compiles_to_supported_quote_syntax():
    assert sources.compile_arxiv_query("'graph neural networks' -'review paper'") == '(all:"graph neural networks" ANDNOT all:"review paper")'
