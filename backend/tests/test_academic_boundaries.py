"""Independent read-only counterexamples, synthetic HTTP only; run via QA socket-denying runner."""
import asyncio,json
from pathlib import Path
from urllib.parse import quote
import httpx
from fastapi import FastAPI
from app.services import academic_sources as s
from app.api.endpoints import academic as r
from app.api.deps import get_auth_payload

CLIENT=httpx.AsyncClient

def setup(monkeypatch, fixture):
    s.academic_cache.clear();s._provider_gates.clear()
    calls=[]
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200,json=fixture)
    def fake_client(*args,**kwargs):
        kwargs['transport']=httpx.MockTransport(handler)
        return CLIENT(*args,**kwargs)
    monkeypatch.setattr(s.httpx,'AsyncClient',fake_client)
    app=FastAPI();app.include_router(r.router)
    app.dependency_overrides[get_auth_payload]=lambda:{'sub':'offline-synthetic'}
    return app,calls


def test_exact_doi_suffix_preserves_transport_and_rejects_wrong_identity(monkeypatch):
    fixture={'message':{'DOI':'10.9999/unrelated','title':['Unrelated fixture']}}
    app,calls=setup(monkeypatch,fixture)
    async def run():
        async with CLIENT(transport=httpx.ASGITransport(app=app),base_url='http://offline') as client:
            for identifier in ['10.1234/a://b','10.1234/a/../b']:
                for query in [identifier,'https://doi.org/'+quote(identifier,safe='')]:
                    response=await client.get('/academic/crossref/search',params={'query':query})
                    assert response.status_code==502
                    assert response.json()['detail']['code']=='invalid_response'
                    assert calls[-1].split('/works/')[1]==quote(identifier,safe='')
    asyncio.run(run())


def test_malformed_inner_crossref_not_cached(monkeypatch):
    app,calls=setup(monkeypatch,{'message':{'items':[{'title':[{'broken':1}],'DOI':'not-a-doi'}]}})
    async def run():
        async with CLIENT(transport=httpx.ASGITransport(app=app),base_url='http://offline') as client:
            for _ in range(2):
                response=await client.get('/academic/crossref/search',params={'query':'fixture'})
                assert response.status_code==502
                assert response.json()['detail']['code']=='invalid_response'
        assert len(calls)==2
    asyncio.run(run())


def test_expanded_query_passes_route_boundary_and_oversized_is_explicit(monkeypatch):
    app,calls=setup(monkeypatch,{'message':{'items':[]},'results':[]})
    async def run():
        async with CLIENT(transport=httpx.ASGITransport(app=app),base_url='http://offline') as client:
            for source in ['crossref','openalex','arxiv']:
                response=await client.get(f'/academic/{source}/search',params={'query':'graph neural networks '*20})
                # arXiv deliberately receives JSON and rejects it after reaching transport.
                assert response.status_code==(502 if source=='arxiv' else 200)
                response=await client.get(f'/academic/{source}/search',params={'query':'x'*4097})
                assert response.status_code==422
        assert len(calls)==3
    asyncio.run(run())


def test_query_limit_is_effective_and_lossless():
    from fastapi import HTTPException
    import pytest
    assert s.plan_academic_query('x'*4096)['effectiveQuery']=='x'*4096
    original='图神经网络'*60
    effective=s.plan_academic_query(original)['effectiveQuery']
    assert len(original)==300 and len(effective)>300
    assert effective.count('graph neural networks')==60
    with pytest.raises(HTTPException) as error:
        s.plan_academic_query('图神经网络'*500)
    assert error.value.detail['code']=='query_too_long'


def test_valid_exact_doi_suffix_reaches_correct_path(monkeypatch):
    identifier='10.1234/a://b/../c'
    app,calls=setup(monkeypatch,{'message':{'DOI':identifier,'title':['Exact fixture']}})
    async def run():
        async with CLIENT(transport=httpx.ASGITransport(app=app),base_url='http://offline') as client:
            response=await client.get('/academic/crossref/search',params={'query':identifier})
            assert response.status_code==200
            assert response.json()['queryType']=='doi'
            assert response.json()['items'][0]['DOI']==identifier
            assert calls[0].split('/works/')[1]==quote(identifier,safe='')
    asyncio.run(run())


def test_malformed_optional_crossref_metadata_rejected():
    import pytest
    from fastapi import HTTPException
    for extra in [{'author':[{'given':{'bad':1},'family':'Smith'}]}, {'abstract':{'bad':'abstract'}}, {'container-title':[{'bad':1}]}]:
        with pytest.raises(HTTPException) as error:
            s._record_list([{'title':['Valid title'],'DOI':'10.1234/a',**extra}], 'crossref')
        assert error.value.detail['code']=='invalid_response'
