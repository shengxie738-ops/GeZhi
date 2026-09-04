import os
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

os.environ.setdefault("RAGFLOW_API_KEY", "test")
os.environ.setdefault("RAGFLOW_BASE_URL", "http://localhost")
os.environ.setdefault("RAGFLOW_AGENT_ID", "test")
os.environ.setdefault("RAGFLOW_CHAT_ID", "test")
os.environ.setdefault("RAGFLOW_DATASET_ID", "test")
os.environ.setdefault("RAGFLOW_PUBLIC_DATASET_IDS", "")
os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("OPENAI_API_BASE", "http://localhost")

from fastapi.testclient import TestClient
from app.main import app
from app.core.security import create_access_token
from app.services.academic_sources import (
    extract_arxiv_id,
    parse_arxiv_atom,
    normalize_doi_query,
    academic_cache
)
from app.services import academic_sources
from app.core.config import settings

client = TestClient(app)
VALID_TOKEN = create_access_token(subject="test_user", role="student")
AUTH_HEADERS = {"Authorization": f"Bearer {VALID_TOKEN}"}

# 1. arXiv ID 解析单测
@pytest.mark.parametrize(("url", "expected"), [
    ("https://arxiv.org/abs/1706.03762v7", "1706.03762"),
    ("https://arxiv.org/abs/solv-int/9901001v1", "solv-int/9901001"),
    ("http://arxiv.org/abs/2101.00001", "2101.00001"),
    ("https://arxiv.org/pdf/1706.03762.pdf", "1706.03762"),
    ("arxiv:1706.03762v2", "1706.03762"),
    ("math.GT/0309136v1", "math/0309136"),
])
def test_parse_arxiv_id_preserves_old_and_new_formats(url, expected):
    assert extract_arxiv_id(url) == expected


def test_parse_arxiv_atom_extracts_fields_correctly():
    sample_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
      <entry>
        <id>http://arxiv.org/abs/1706.03762v7</id>
        <updated>2023-08-02T01:09:47Z</updated>
        <published>2017-06-12T17:57:34Z</published>
        <title>Attention Is All You Need</title>
        <summary>The dominant sequence transduction models are based on complex recurrent or convolutional neural networks...</summary>
        <author><name>Ashish Vaswani</name></author>
        <author><name>Noam Shazeer</name></author>
        <arxiv:doi xmlns:arxiv="http://arxiv.org/schemas/atom">10.48550/arXiv.1706.03762</arxiv:doi>
        <link href="http://arxiv.org/abs/1706.03762v7" rel="alternate" type="text/html"/>
        <link title="pdf" href="http://arxiv.org/pdf/1706.03762v7" rel="related" type="application/pdf"/>
      </entry>
      <entry>
        <id>http://arxiv.org/abs/2101.00001v1</id>
        <published>2021-01-01T00:00:00Z</published>
        <title>No PDF Link Paper</title>
        <summary>Summary without pdf</summary>
        <author><name>Alice</name></author>
        <link href="http://arxiv.org/abs/2101.00001v1" rel="alternate" type="text/html"/>
      </entry>
    </feed>
    """
    items = parse_arxiv_atom(sample_xml)
    assert len(items) == 2

    first = items[0]
    assert first["sourceId"] == "1706.03762"
    assert first["title"] == "Attention Is All You Need"
    assert first["authors"] == ["Ashish Vaswani", "Noam Shazeer"]
    assert first["year"] == 2017
    assert "dominant sequence" in first["abstract"]
    assert first["doi"] == "10.48550/arxiv.1706.03762"
    assert first["officialUrl"] == "https://arxiv.org/abs/1706.03762"
    assert first["openAccessUrl"] == "https://arxiv.org/pdf/1706.03762"
    assert first["isOpenAccess"] is True

    second = items[1]
    assert second["sourceId"] == "2101.00001"
    assert second["openAccessUrl"] == ""
    assert second["isOpenAccess"] is False


def test_normalize_doi_query():
    assert normalize_doi_query("10.1000/182") == "10.1000/182"
    assert normalize_doi_query("https://doi.org/10.1000/182.") == "10.1000/182"
    assert normalize_doi_query("doi: 10.48550/arXiv.1706.03762") == "10.48550/arxiv.1706.03762"
    assert normalize_doi_query("regular text query") == ""


# 2. 鉴权测试
@pytest.mark.parametrize("path", [
    "/api/academic/openalex/search?query=transformer",
    "/api/academic/crossref/search?query=transformer",
    "/api/academic/arxiv/search?query=transformer",
])
def test_academic_endpoints_require_auth(path):
    # 未携带 token 返回 401
    res = client.get(path)
    assert res.status_code == 401

    # 无效 token 返回 401
    res = client.get(path, headers={"Authorization": "Bearer invalid_token"})
    assert res.status_code == 401


# 3. 参数校验
@pytest.mark.parametrize("query_param,limit_param,expected_status", [
    ("", 10, 422), # 空查询
    ("   ", 10, 422), # 纯空白
    ("a" * 301, 10, 422), # 超长 300 字符
    ("transformer", 0, 422), # limit < 1
    ("transformer", 21, 422), # limit > 20
])
def test_academic_endpoints_query_validation(query_param, limit_param, expected_status):
    res = client.get(
        f"/api/academic/openalex/search?query={query_param}&limit={limit_param}",
        headers=AUTH_HEADERS
    )
    assert res.status_code == expected_status


# 4. OpenAlex 代理测试
@pytest.mark.asyncio
async def test_openalex_proxy_success_and_cache():
    academic_cache.clear()
    fake_results = [{"id": "https://openalex.org/W1", "display_name": "Test Paper"}]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"results": fake_results}

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp

        # 第一次调用
        res1 = client.get("/api/academic/openalex/search?query=deep%20learning&limit=5", headers=AUTH_HEADERS)
        assert res1.status_code == 200
        body1 = res1.json()
        assert body1["source"] == "openalex"
        assert len(body1["items"]) == 1
        assert body1["cached"] is False
        assert mock_get.call_count == 1

        # 第二次相同查询，命中缓存
        res2 = client.get("/api/academic/openalex/search?query=deep%20learning&limit=5", headers=AUTH_HEADERS)
        assert res2.status_code == 200
        body2 = res2.json()
        assert body2["cached"] is True
        assert mock_get.call_count == 1 # 没有再次调上游


@pytest.mark.asyncio
async def test_openalex_cache_key_normalizes_query_case():
    academic_cache.clear()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"results": []}

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        first = client.get("/api/academic/openalex/search?query=Deep%20Learning&limit=5", headers=AUTH_HEADERS)
        second = client.get("/api/academic/openalex/search?query=deep%20learning&limit=5", headers=AUTH_HEADERS)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["cached"] is True
    assert mock_get.call_count == 1


@pytest.mark.asyncio
async def test_openalex_sends_configured_api_key():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"results": []}

    with patch.object(settings, "OPENALEX_API_KEY", "test-openalex-key"), \
            patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        await academic_sources.fetch_openalex("transformer", 5)

    assert mock_get.call_args.kwargs["headers"]["Authorization"] == "Bearer test-openalex-key"


# 5. Crossref 代理测试 (DOI 查询 vs 关键词查询)
@pytest.mark.asyncio
async def test_crossref_proxy_doi_and_keyword_routing():
    academic_cache.clear()
    doi_item = {"DOI": "10.1000/182", "title": ["Specific DOI Paper"]}
    kw_items = [{"DOI": "10.1000/183", "title": ["Keyword Search Paper"]}]

    mock_resp_doi = MagicMock()
    mock_resp_doi.status_code = 200
    mock_resp_doi.json.return_value = {"message": doi_item}

    mock_resp_kw = MagicMock()
    mock_resp_kw.status_code = 200
    mock_resp_kw.json.return_value = {"message": {"items": kw_items}}

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        # 1. DOI 查询命中
        mock_get.return_value = mock_resp_doi
        res = client.get("/api/academic/crossref/search?query=10.1000/182&limit=5", headers=AUTH_HEADERS)
        assert res.status_code == 200
        data = res.json()
        assert data["source"] == "crossref"
        assert len(data["items"]) == 1
        assert data["items"][0]["title"] == ["Specific DOI Paper"]
        # 验证 URL 包含 /works/10.1000%2F182 或 /works/10.1000/182
        called_url = mock_get.call_args[0][0]
        assert "10.1000" in called_url

        # 2. 关键词查询
        academic_cache.clear()
        mock_get.return_value = mock_resp_kw
        res = client.get("/api/academic/crossref/search?query=neural%20networks&limit=5", headers=AUTH_HEADERS)
        assert res.status_code == 200
        data = res.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["title"] == ["Keyword Search Paper"]


@pytest.mark.asyncio
async def test_crossref_sends_polite_pool_identity_and_enforces_gate():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"message": {"items": []}}
    academic_sources._last_crossref_time = 100.0

    with patch.object(settings, "CROSSREF_MAILTO", "research@example.edu"), \
            patch.object(academic_sources.time, "time", side_effect=[100.25, 101.0]), \
            patch.object(academic_sources.asyncio, "sleep", new_callable=AsyncMock) as mock_sleep, \
            patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        await academic_sources.fetch_crossref("transformer", 5)

    mock_sleep.assert_awaited_once_with(0.75)
    assert mock_get.call_args.kwargs["params"]["mailto"] == "research@example.edu"
    assert "mailto:research@example.edu" in mock_get.call_args.kwargs["headers"]["User-Agent"]
    academic_sources._last_crossref_time = 0.0


@pytest.mark.asyncio
async def test_arxiv_enforces_configured_gate():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = ""
    academic_sources._last_arxiv_time = 100.0

    with patch.object(settings, "ARXIV_MIN_INTERVAL_SECONDS", 3.0), \
            patch.object(academic_sources.time, "time", side_effect=[101.0, 104.0]), \
            patch.object(academic_sources.asyncio, "sleep", new_callable=AsyncMock) as mock_sleep, \
            patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        await academic_sources.fetch_arxiv("transformer", 5)

    mock_sleep.assert_awaited_once_with(2.0)
    academic_sources._last_arxiv_time = 0.0


# 6. 异常映射测试 (429, 504, 502)
@pytest.mark.asyncio
async def test_academic_error_mappings():
    academic_cache.clear()

    # 429 速率限制
    mock_429 = MagicMock()
    mock_429.status_code = 429
    mock_429.headers = {"Retry-After": "3"}
    mock_429.text = "Too Many Requests"

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_429
        res = client.get("/api/academic/openalex/search?query=error429", headers=AUTH_HEADERS)
        assert res.status_code == 429
        assert res.headers.get("Retry-After") == "3"

    # 504 超时
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.TimeoutException("Read timeout")
        res = client.get("/api/academic/crossref/search?query=timeout_test", headers=AUTH_HEADERS)
        assert res.status_code == 504

    # arXiv 超时信息必须指出真实失败来源，便于部署排查网络问题
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.TimeoutException("Connect timeout")
        res = client.get("/api/academic/arxiv/search?query=timeout_diagnostic", headers=AUTH_HEADERS)
        assert res.status_code == 504
        assert "arXiv" in res.json()["detail"]
        assert "export.arxiv.org" in res.json()["detail"]

    # 502 上游 500 错误或网络错误
    mock_500 = MagicMock()
    mock_500.status_code = 500
    mock_500.text = "Internal Server Error"
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_500
        res = client.get("/api/academic/arxiv/search?query=upstream_error", headers=AUTH_HEADERS)
        assert res.status_code == 502
