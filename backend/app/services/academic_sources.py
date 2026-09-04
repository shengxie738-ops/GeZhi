"""
academic_sources.py - 学术数据源代理服务
提供 OpenAlex、Crossref、arXiv 的安全调用、缓存、限速门控与数据转换
"""

import asyncio
import logging
import re
import time
from urllib.parse import quote, urlsplit
import xml.etree.ElementTree as ET

import httpx
from fastapi import HTTPException

from app.core.config import settings

logger = logging.getLogger(__name__)

USER_AGENT = "GezhiAcademicSearch/1.0 (+https://gezhisystem.com)"
DOI_REGEX = re.compile(r"10\.\d{4,9}/[-._;()/:a-zA-Z0-9]+", re.I)


class AcademicCache:
    """有界内存缓存，上限 256 项，超时自动清理"""
    def __init__(self, max_size: int = 256):
        self.max_size = max_size
        self._cache: dict[str, tuple[float, any]] = {}

    def _cleanup_expired(self):
        now = time.time()
        expired_keys = [k for k, (exp, _) in self._cache.items() if exp < now]
        for k in expired_keys:
            del self._cache[k]
        if len(self._cache) > self.max_size:
            sorted_keys = sorted(self._cache.keys(), key=lambda k: self._cache[k][0])
            for k in sorted_keys[: len(self._cache) - self.max_size]:
                del self._cache[k]

    def get(self, key: str):
        if key in self._cache:
            exp, val = self._cache[key]
            if exp >= time.time():
                return val
            del self._cache[key]
        return None

    def set(self, key: str, val: any, ttl_seconds: int):
        self._cache[key] = (time.time() + ttl_seconds, val)
        self._cleanup_expired()

    def clear(self):
        self._cache.clear()


academic_cache = AcademicCache()

# 限速锁与时间戳
_crossref_lock = asyncio.Lock()
_last_crossref_time = 0.0

_arxiv_lock = asyncio.Lock()
_last_arxiv_time = 0.0


def normalize_doi_query(query: str) -> str:
    """识别并规范化 DOI 查询"""
    if not query:
        return ""
    cleaned = query.strip()
    cleaned = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", cleaned, flags=re.I)
    cleaned = re.sub(r"^doi:\s*", "", cleaned, flags=re.I)
    m = DOI_REGEX.search(cleaned)
    if not m:
        return ""
    doi = m.group(0).lower().rstrip("-._;()/:,")
    return doi


def extract_arxiv_id(abs_url: str) -> str:
    """从 URL 或字符串中提取规范化 arXiv ID，剔除版本号并支持新旧格式"""
    if not abs_url:
        return ""
    cleaned = abs_url.strip()
    path = urlsplit(cleaned).path if ("://" in cleaned) else cleaned
    raw_id = path.split("/abs/", 1)[1] if "/abs/" in path else path
    raw_id = raw_id.split("/pdf/", 1)[1] if "/pdf/" in raw_id else raw_id
    raw_id = re.sub(r"^arxiv:\s*", "", raw_id, flags=re.I)
    raw_id = re.sub(r"\.pdf$", "", raw_id, flags=re.I)
    raw_id = re.sub(r"v\d+$", "", raw_id)

    # 新格式: 1706.03762
    new_m = re.match(r"^(\d{4}\.\d{4,5})$", raw_id)
    if new_m:
        return new_m.group(1)

    # 旧格式: math.GT/0309136 -> math/0309136, solv-int/9901001
    old_m = re.match(r"^([a-zA-Z\-]+)(?:\.[a-zA-Z\-]+)?/(\d{7})$", raw_id)
    if old_m:
        return f"{old_m.group(1).lower()}/{old_m.group(2)}"

    return raw_id


def parse_arxiv_atom(xml_text: str) -> list[dict]:
    """解析 arXiv Atom XML 响应为标准字段列表"""
    items = []
    if not xml_text or not xml_text.strip():
        return items

    try:
        root = ET.fromstring(xml_text)
    except Exception as e:
        logger.error("Failed to parse arXiv Atom XML: %s", e)
        return items

    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom"
    }

    for entry in root.findall("atom:entry", ns):
        id_elem = entry.find("atom:id", ns)
        id_text = id_elem.text.strip() if id_elem is not None and id_elem.text else ""
        arxiv_id = extract_arxiv_id(id_text)

        title_elem = entry.find("atom:title", ns)
        title = " ".join(title_elem.text.split()) if title_elem is not None and title_elem.text else ""

        authors = []
        for author in entry.findall("atom:author", ns):
            name_elem = author.find("atom:name", ns)
            if name_elem is not None and name_elem.text:
                authors.append(name_elem.text.strip())

        published_elem = entry.find("atom:published", ns)
        year = None
        if published_elem is not None and published_elem.text:
            m = re.match(r"(\d{4})", published_elem.text)
            if m:
                year = int(m.group(1))

        summary_elem = entry.find("atom:summary", ns)
        abstract = " ".join(summary_elem.text.split()) if summary_elem is not None and summary_elem.text else ""

        doi_elem = entry.find("arxiv:doi", ns)
        doi = normalize_doi_query(doi_elem.text) if doi_elem is not None and doi_elem.text else ""

        pdf_url = ""
        for link in entry.findall("atom:link", ns):
            title_attr = link.attrib.get("title", "").lower()
            type_attr = link.attrib.get("type", "").lower()
            href = link.attrib.get("href", "").strip()
            if title_attr == "pdf" or type_attr == "application/pdf":
                if "arxiv.org" in href and arxiv_id:
                    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
                elif href:
                    pdf_url = href.replace("http://", "https://")
                break

        official_url = f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else ""

        items.append({
            "sourceId": arxiv_id,
            "title": title,
            "authors": authors,
            "year": year,
            "abstract": abstract,
            "doi": doi,
            "arxivId": arxiv_id,
            "officialUrl": official_url,
            "openAccessUrl": pdf_url,
            "isOpenAccess": bool(pdf_url),
            "venue": "arXiv",
            "workType": "preprint"
        })

    return items


def _upstream_timeout_detail(source_name: str, url: str) -> str:
    source = source_name or "学术来源"
    host = urlsplit(url).netloc or url
    return f"{source} 上游请求超时（{host}）；请检查服务器到该官方接口的网络连通性"


async def _execute_request_with_retry(
    client: httpx.AsyncClient,
    url: str,
    params: dict = None,
    headers: dict = None,
    source_name: str = ""
) -> httpx.Response:
    """执行 HTTP 请求，支持超时 504 映射与 429 退避单次重试"""
    try:
        resp = await client.get(url, params=params, headers=headers)
    except httpx.TimeoutException as e:
        logger.warning("Upstream timeout for %s: %s", url, e)
        raise HTTPException(status_code=504, detail=_upstream_timeout_detail(source_name, url))
    except Exception as e:
        logger.error("Upstream request error for %s: %s", url, e)
        raise HTTPException(status_code=502, detail=f"Upstream service connection error: {str(e)}")

    if resp.status_code == 429:
        retry_after = resp.headers.get("Retry-After")
        wait_seconds = 1.0
        if retry_after:
            try:
                wait_seconds = min(float(retry_after), 3.0)
            except ValueError:
                wait_seconds = 1.0
        logger.warning("Upstream 429 for %s, backing off for %s seconds", url, wait_seconds)
        await asyncio.sleep(wait_seconds)

        # 重试一次
        try:
            resp = await client.get(url, params=params, headers=headers)
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail=_upstream_timeout_detail(source_name, url))
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Upstream service connection error: {str(e)}")

        if resp.status_code == 429:
            retry_headers = {}
            if resp.headers.get("Retry-After"):
                retry_headers["Retry-After"] = resp.headers.get("Retry-After")
            raise HTTPException(status_code=429, detail="Upstream rate limit exceeded", headers=retry_headers)

    if resp.status_code >= 400:
        logger.error("Upstream returned error %s for %s: %s", resp.status_code, url, resp.text)
        raise HTTPException(status_code=502, detail=f"Upstream returned HTTP {resp.status_code}")

    return resp


async def fetch_openalex(query: str, limit: int = 10) -> list[dict]:
    """通过 OpenAlex API 查询作品"""
    headers = {"User-Agent": USER_AGENT}
    if settings.OPENALEX_API_KEY:
        headers["Authorization"] = f"Bearer {settings.OPENALEX_API_KEY}"

    params = {
        "search": query,
        "per-page": limit
    }

    url = "https://api.openalex.org/works"
    async with httpx.AsyncClient(timeout=settings.ACADEMIC_HTTP_TIMEOUT_SECONDS, follow_redirects=True) as client:
        resp = await _execute_request_with_retry(client, url, params=params, headers=headers, source_name="OpenAlex")
        try:
            data = resp.json()
            return data.get("results", [])
        except Exception as e:
            logger.error("Failed to parse OpenAlex JSON: %s", e)
            raise HTTPException(status_code=502, detail="Invalid JSON from OpenAlex")


async def fetch_crossref(query: str, limit: int = 10) -> list[dict]:
    """通过 Crossref REST API 查询，含 1 秒门控与 DOI 精确查询分流"""
    global _last_crossref_time

    # 限速门控 (>= 1.0s)
    async with _crossref_lock:
        now = time.time()
        elapsed = now - _last_crossref_time
        if elapsed < 1.0:
            await asyncio.sleep(1.0 - elapsed)
        _last_crossref_time = time.time()

    headers = {
        "User-Agent": f"GezhiAcademicSearch/1.0 (+https://gezhisystem.com; mailto:{settings.CROSSREF_MAILTO or 'support@gezhisystem.com'})"
    }

    doi = normalize_doi_query(query)
    async with httpx.AsyncClient(timeout=settings.ACADEMIC_HTTP_TIMEOUT_SECONDS, follow_redirects=True) as client:
        if doi:
            # DOI 精确查询
            url = f"https://api.crossref.org/works/{quote(doi, safe='')}"
            params = {}
            if settings.CROSSREF_MAILTO:
                params["mailto"] = settings.CROSSREF_MAILTO
            resp = await _execute_request_with_retry(client, url, params=params, headers=headers, source_name="Crossref")
            try:
                data = resp.json()
                msg = data.get("message")
                return [msg] if msg else []
            except Exception as e:
                logger.error("Failed to parse Crossref DOI JSON: %s", e)
                raise HTTPException(status_code=502, detail="Invalid JSON from Crossref")
        else:
            # 关键词检索
            url = "https://api.crossref.org/works"
            params = {
                "query.bibliographic": query,
                "rows": limit
            }
            if settings.CROSSREF_MAILTO:
                params["mailto"] = settings.CROSSREF_MAILTO
            resp = await _execute_request_with_retry(client, url, params=params, headers=headers, source_name="Crossref")
            try:
                data = resp.json()
                return data.get("message", {}).get("items", [])
            except Exception as e:
                logger.error("Failed to parse Crossref search JSON: %s", e)
                raise HTTPException(status_code=502, detail="Invalid JSON from Crossref")


async def fetch_arxiv(query: str, limit: int = 10) -> list[dict]:
    """通过 arXiv API 查询，含 3 秒门控与 Atom XML 解析"""
    global _last_arxiv_time

    # 门控 (>= ARXIV_MIN_INTERVAL_SECONDS)
    async with _arxiv_lock:
        now = time.time()
        elapsed = now - _last_arxiv_time
        interval = getattr(settings, "ARXIV_MIN_INTERVAL_SECONDS", 3.0)
        if elapsed < interval:
            await asyncio.sleep(interval - elapsed)
        _last_arxiv_time = time.time()

    headers = {"User-Agent": USER_AGENT}
    url = "https://export.arxiv.org/api/query"
    clean_query = query.strip()
    if ":" in clean_query or '"' in clean_query:
        search_query = clean_query
    elif " " in clean_query:
        search_query = f'ti:"{clean_query}" OR all:"{clean_query}"'
    else:
        search_query = f'all:{clean_query}'

    params = {
        "search_query": search_query,
        "start": 0,
        "max_results": limit,
        "sortBy": "relevance"
    }


    async with httpx.AsyncClient(timeout=settings.ARXIV_HTTP_TIMEOUT_SECONDS, follow_redirects=True) as client:
        resp = await _execute_request_with_retry(client, url, params=params, headers=headers, source_name="arXiv")
        return parse_arxiv_atom(resp.text)
