"""Academic provider adapters with lossless queries and process-local bounded work."""

import asyncio
import logging
import math
import re
import time
import weakref
from datetime import timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote, unquote, urlsplit
import xml.etree.ElementTree as ET

import httpx
from fastapi import HTTPException

from app.core.config import settings

logger = logging.getLogger(__name__)
USER_AGENT = "GezhiAcademicSearch/1.0 (+https://gezhisystem.com)"
MAX_EFFECTIVE_QUERY_LENGTH = 4096
DOI_REGEX = re.compile(r"10\.\d{4,9}/[^\s\x00-\x1f\x7f]+", re.I)
_monotonic = time.monotonic
_wall_time = time.time
_sleep = asyncio.sleep


def _source_error(source, code, message, status=502, retry_after=None):
    detail = {"source": source.lower(), "code": code, "message": message}
    headers = None
    if retry_after is not None:
        seconds = max(0, math.ceil(retry_after))
        detail["retryAfter"] = seconds
        headers = {"Retry-After": str(seconds)}
    return HTTPException(status_code=status, detail=detail, headers=headers)


class AcademicCache:
    """Bounded successful-result cache and per-event-loop in-flight coalescing."""
    def __init__(self, max_size=256):
        self.max_size = max_size
        self._cache = {}
        self._inflight = weakref.WeakKeyDictionary()

    def _cleanup_expired(self):
        now = _monotonic()
        for key, (expires, _) in list(self._cache.items()):
            if expires <= now:
                self._cache.pop(key, None)
        for key in sorted(self._cache, key=lambda k: self._cache[k][0])[:max(0, len(self._cache) - self.max_size)]:
            self._cache.pop(key, None)

    def get(self, key):
        entry = self._cache.get(key)
        if entry and entry[0] > _monotonic():
            return entry[1]
        self._cache.pop(key, None)
        return None

    def set(self, key, value, ttl_seconds):
        self._cache[key] = (_monotonic() + max(0, ttl_seconds), value)
        self._cleanup_expired()

    async def get_or_fetch(self, key, loader, ttl_seconds):
        cached = self.get(key)
        if cached is not None:
            return cached, True
        flights = self._inflight.setdefault(asyncio.get_running_loop(), {})
        task = flights.get(key)
        if task is None:
            async def load():
                value = await loader()
                self.set(key, value, ttl_seconds)
                return value
            task = asyncio.create_task(load())
            flights[key] = task
            def finished(done):
                if flights.get(key) is done:
                    flights.pop(key, None)
                # A disconnected/cancelled waiter must not leave unobserved errors.
                if not done.cancelled():
                    done.exception()
            task.add_done_callback(finished)
        # Cancelling one HTTP caller never cancels another caller's shared fetch.
        return await asyncio.shield(task), False

    def clear(self):
        self._cache.clear()


academic_cache = AcademicCache()


def normalize_doi_query(query):
    """Normalize only a whole DOI/official DOI URL; never delete suffix punctuation."""
    if not isinstance(query, str):
        return ""
    cleaned = query.strip()
    if cleaned.startswith("<http") and cleaned.endswith(">"):
        cleaned = cleaned[1:-1]
    if re.match(r"^https?://", cleaned, re.I):
        try:
            parsed = urlsplit(cleaned)
            port = parsed.port
        except ValueError:
            return ""
        if parsed.scheme.lower() not in {"http", "https"} or (parsed.hostname or "").lower() not in {"doi.org", "dx.doi.org"}:
            return ""
        if parsed.username or parsed.password or port not in {None, 80, 443}:
            return ""
        # Literal URL query/fragment is not DOI path data; percent-encoded characters are.
        cleaned = unquote(parsed.path.lstrip("/"))
    else:
        cleaned = re.sub(r"^doi:\s*", "", cleaned, flags=re.I)
    return cleaned.lower() if DOI_REGEX.fullmatch(cleaned) else ""


def normalize_arxiv_identifier(value):
    """Strict lookup identifier, preserving requested version and legacy category."""
    if not value:
        return ""
    cleaned = str(value).strip()
    if "://" in cleaned:
        try:
            parsed = urlsplit(cleaned)
            port = parsed.port
        except ValueError:
            return ""
        if parsed.scheme.lower() not in {"http", "https"} or (parsed.hostname or "").lower() not in {"arxiv.org", "www.arxiv.org", "export.arxiv.org"}:
            return ""
        if parsed.username or parsed.password or port not in {None, 80, 443}:
            return ""
        match = re.fullmatch(r"/(?:abs|pdf)/(.+)", parsed.path)
        if not match:
            return ""
        cleaned = unquote(match.group(1))
    cleaned = re.sub(r"^arxiv:\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\.pdf$", "", cleaned, flags=re.I)
    new = re.fullmatch(r"(\d{2}(?:0[1-9]|1[0-2])\.\d{4,5})(v[1-9]\d*)?", cleaned)
    if new and new.group(1)[:4] >= "0704":
        return new.group(0)
    old = re.fullmatch(r"([a-zA-Z][a-zA-Z-]*)(\.[a-zA-Z][a-zA-Z-]*)?/((?:\d{2})(?:0[1-9]|1[0-2])\d{3})(v[1-9]\d*)?", cleaned)
    if old:
        return f"{old.group(1).lower()}{old.group(2) or ''}/{old.group(3)}{old.group(4) or ''}"
    return ""


def extract_arxiv_id(value):
    """Versionless identity; invalid strings have no scholarly identity."""
    identifier = normalize_arxiv_identifier(value)
    identifier = re.sub(r"v\d+$", "", identifier)
    return re.sub(r"\.[A-Za-z-]+/", "/", identifier)


def parse_arxiv_atom(xml_text):
    """Reject provider errors/malformed payloads, preserving valid empty feeds."""
    ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    try:
        root = ET.fromstring(xml_text)
    except (ET.ParseError, TypeError, ValueError):
        raise _source_error("arxiv", "invalid_response", "arXiv returned malformed Atom XML")
    if root.tag != "{http://www.w3.org/2005/Atom}feed":
        raise _source_error("arxiv", "invalid_response", "arXiv returned a non-Atom feed")
    items = []
    def text(entry, name):
        node = entry.find(name, ns)
        return " ".join("".join(node.itertext()).split()) if node is not None else ""
    if any(child.tag.rsplit("}", 1)[-1] == "entry" and child.tag != "{http://www.w3.org/2005/Atom}entry" for child in root):
        raise _source_error("arxiv", "invalid_response", "arXiv returned a non-Atom paper entry")
    for entry in root.findall("atom:entry", ns):
        id_text = text(entry, "atom:id")
        try:
            parsed_id = urlsplit(id_text)
        except ValueError:
            raise _source_error("arxiv", "invalid_response", "arXiv returned an invalid entry URL")
        if (parsed_id.hostname or "").lower() in {"arxiv.org", "export.arxiv.org"} and parsed_id.path == "/api/errors":
            raise _source_error("arxiv", "invalid_query", "arXiv rejected the query or identifier; check its syntax", 422)
        identifier = normalize_arxiv_identifier(id_text)
        title = text(entry, "atom:title")
        if not identifier or not title:
            raise _source_error("arxiv", "invalid_response", "arXiv returned an entry without a valid paper ID/title")
        identity = extract_arxiv_id(identifier)
        version_match = re.search(r"v\d+$", identifier)
        published = text(entry, "atom:published")
        year_match = re.match(r"\d{4}", published)
        pdf_url = ""
        for link in entry.findall("atom:link", ns):
            if link.get("title", "").lower() == "pdf" or link.get("type", "").lower() == "application/pdf":
                href_id = normalize_arxiv_identifier(link.get("href", ""))
                if href_id and extract_arxiv_id(href_id) == identity:
                    pdf_url = f"https://arxiv.org/pdf/{identifier}"
                break
        items.append({
            "sourceId": identity, "title": title,
            "authors": [text(author, "atom:name") for author in entry.findall("atom:author", ns) if text(author, "atom:name")],
            "year": int(year_match.group()) if year_match else None,
            "abstract": text(entry, "atom:summary"), "doi": normalize_doi_query(text(entry, "arxiv:doi")),
            "arxivId": identity, "arxivVersion": version_match.group() if version_match else "",
            "officialUrl": f"https://arxiv.org/abs/{identifier}", "openAccessUrl": pdf_url,
            "isOpenAccess": bool(pdf_url), "venue": "arXiv", "workType": "preprint",
        })
    return items


class _ProviderGate:
    """One active attempt per provider in this worker; all retries are paced."""
    def __init__(self):
        self.next_start = 0.0
        self.cooldown_until = 0.0
        self._locks = weakref.WeakKeyDictionary()

    def lock(self):
        return self._locks.setdefault(asyncio.get_running_loop(), asyncio.Lock())


_provider_gates = {}
_SOURCE_LABELS = {"openalex": "OpenAlex", "crossref": "Crossref", "arxiv": "arXiv"}


def _retry_after_seconds(value):
    try:
        seconds = float(value)
        if math.isfinite(seconds):
            return max(0.0, seconds)
    except (TypeError, ValueError):
        pass
    try:
        date = parsedate_to_datetime(value)
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        return max(0.0, date.timestamp() - _wall_time())
    except (TypeError, ValueError, OverflowError):
        return 1.0


def _timeout_error(source, url):
    return _source_error(source, "timeout", f"{_SOURCE_LABELS[source]} request deadline exceeded ({urlsplit(url).netloc}); queue, network and retries share the same budget", 504)


async def _execute_request_with_retry(client, url, params=None, headers=None, source_name="", *, deadline=None, exact_lookup=False):
    source = source_name.lower()
    gate = _provider_gates.setdefault(source, _ProviderGate())
    budget = settings.ARXIV_HTTP_TIMEOUT_SECONDS if source == "arxiv" else settings.ACADEMIC_HTTP_TIMEOUT_SECONDS
    deadline = deadline if deadline is not None else _monotonic() + budget
    interval = settings.ARXIV_MIN_INTERVAL_SECONDS if source == "arxiv" else (1.0 if source == "crossref" else 0.0)
    for attempt in range(2):
        async with gate.lock():
            now = _monotonic()
            remaining = deadline - now
            if remaining <= 0:
                raise _timeout_error(source, url)
            cooldown = max(0.0, gate.cooldown_until - now)
            wait = max(0.0, gate.next_start - now, cooldown)
            if cooldown >= remaining:
                raise _source_error(source, "rate_limited", f"{_SOURCE_LABELS[source]} rate limit cooldown exceeds the request budget", 429, cooldown)
            if wait >= remaining:
                raise _timeout_error(source, url)
            if wait:
                await _sleep(wait)
            gate.next_start = _monotonic() + max(0.0, interval)
            try:
                resp = await client.get(url, params=params, headers=headers)
            except httpx.TimeoutException:
                raise _timeout_error(source, url)
            except httpx.RequestError:
                raise _source_error(source, "connection_error", f"{_SOURCE_LABELS[source]} connection failed ({urlsplit(url).netloc})")
            if resp.status_code == 429:
                cooldown = _retry_after_seconds(resp.headers.get("Retry-After"))
                gate.cooldown_until = max(gate.cooldown_until, _monotonic() + cooldown)
        if resp.status_code == 429:
            cooldown = max(0.0, gate.cooldown_until - _monotonic())
            if attempt == 0 and max(cooldown, gate.next_start - _monotonic()) < deadline - _monotonic():
                continue
            raise _source_error(source, "rate_limited", f"{_SOURCE_LABELS[source]} rate limit exceeded; retry after its cooldown", 429, cooldown)
        if resp.status_code == 404 and exact_lookup:
            raise _source_error(source, "not_found", f"{_SOURCE_LABELS[source]} has no record for that exact identifier", 404)
        if resp.status_code in {400, 422}:
            raise _source_error(source, "invalid_query", f"{_SOURCE_LABELS[source]} rejected the query or identifier; check its syntax", 422)
        if resp.status_code >= 400:
            code = "upstream_auth_error" if resp.status_code in {401, 403} else "upstream_error"
            raise _source_error(source, code, f"{_SOURCE_LABELS[source]} returned HTTP {resp.status_code}")
        return resp


async def _bounded_fetch(source, url, budget, operation):
    try:
        return await asyncio.wait_for(operation(_monotonic() + max(.001, budget)), timeout=max(.001, budget))
    except TimeoutError:
        raise _timeout_error(source, url)


def _json_payload(response, source):
    try:
        data = response.json()
    except (ValueError, TypeError):
        raise _source_error(source, "invalid_response", f"{_SOURCE_LABELS[source]} returned invalid JSON")
    if not isinstance(data, dict):
        raise _source_error(source, "invalid_response", f"{_SOURCE_LABELS[source]} returned an invalid response object")
    return data


def _record_list(value, source):
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise _source_error(source, "invalid_response", f"{_SOURCE_LABELS[source]} returned an invalid records list")
    for item in value:
        title = item.get("title", item.get("display_name"))
        if source == "crossref" and isinstance(title, list):
            title = title[0] if title and all(isinstance(part, str) for part in title) else None
        if not isinstance(title, str) or not title.strip():
            raise _source_error(source, "invalid_response", f"{_SOURCE_LABELS[source]} returned an invalid paper title")
        def optional_text(value):
            return value is None or isinstance(value, str)
        text_fields = ("abstract", "type", "URL", "publisher") if source == "crossref" else ("abstract", "display_name", "type", "type_crossref")
        valid_metadata = all(optional_text(item.get(field)) for field in text_fields)
        if source == "crossref":
            venue = item.get("container-title")
            valid_metadata = valid_metadata and (optional_text(venue) or isinstance(venue, list) and all(isinstance(v, str) for v in venue))
            authors = item.get("author")
            valid_metadata = valid_metadata and (authors is None or isinstance(authors, list) and all(isinstance(a, dict) and all(optional_text(a.get(k)) for k in ("given", "family", "name")) for a in authors))
        else:
            authors = item.get("authorships")
            valid_metadata = valid_metadata and (authors is None or isinstance(authors, list) and all(isinstance(a, dict) and isinstance(a.get("author", {}), dict) and optional_text(a.get("author", {}).get("display_name")) for a in authors))
        number_fields = ("is-referenced-by-count",) if source == "crossref" else ("publication_year", "cited_by_count")
        for field in number_fields:
            number = item.get(field)
            if number is not None and number != "":
                try:
                    valid_metadata = valid_metadata and type(number) in (int, float, str) and math.isfinite(float(number))
                except (ValueError, TypeError, OverflowError):
                    valid_metadata = False
        if not valid_metadata:
            raise _source_error(source, "invalid_response", f"{_SOURCE_LABELS[source]} returned malformed optional paper metadata")
        doi = item.get("DOI" if source == "crossref" else "doi")
        if doi not in (None, "") and not normalize_doi_query(doi):
            raise _source_error(source, "invalid_response", f"{_SOURCE_LABELS[source]} returned an invalid DOI")
        if source == "openalex" and item.get("id") not in (None, ""):
            if not isinstance(item["id"], str) or not re.fullmatch(r"https://openalex\.org/W[0-9]+", item["id"]):
                raise _source_error(source, "invalid_response", "OpenAlex returned an invalid work ID")
    return value

BACKEND_TERM_TRANSLATIONS = [
    ("金融量化与算法交易", "quantitative finance algorithmic trading"),
    ("量化投资与资产配置", "quantitative investment asset allocation"),
    ("金融量化", "quantitative finance"),
    ("量化金融", "quantitative finance"),
    ("量化交易", "quantitative trading"),
    ("算法交易", "algorithmic trading"),
    ("量化投资", "quantitative investment"),
    ("金融工程", "financial engineering"),
    ("资产定价", "asset pricing"),
    ("期权定价", "option pricing"),
    ("高频交易", "high frequency trading"),
    ("风险管理", "risk management"),
    ("投资组合优化", "portfolio optimization"),
    ("信用风险", "credit risk"),
    ("市场微观结构", "market microstructure"),
    ("检索增强生成", "retrieval augmented generation"),
    ("生成对抗网络", "generative adversarial networks"),
    ("深度强化学习", "deep reinforcement learning"),
    ("大语言模型", "large language models"),
    ("语言大模型", "large language models"),
    ("图卷积网络", "graph convolutional networks"),
    ("图神经网络", "graph neural networks"),
    ("自监督学习", "self-supervised learning"),
    ("多模态学习", "multimodal learning"),
    ("注意力机制", "attention mechanism"),
    ("时间序列分析", "time series analysis"),
    ("知识图谱", "knowledge graphs"),
    ("自然语言处理", "natural language processing"),
    ("计算机视觉", "computer vision"),
    ("深度学习", "deep learning"),
    ("强化学习", "reinforcement learning"),
    ("机器学习", "machine learning"),
    ("人工智能", "artificial intelligence"),
    ("神经网络", "neural networks"),
]


def sanitize_academic_search_query(query):
    """Terminology replacement, not full translation. Preserve all unmatched text."""
    if not query:
        return ""
    original = str(query).strip()
    if normalize_doi_query(original) or normalize_arxiv_identifier(original) or _valid_arxiv_advanced(original):
        return original
    # Quoted spans may be exact titles/phrases and must not be rewritten.
    terms = dict(BACKEND_TERM_TRANSLATIONS)
    pattern = re.compile(r"(-?)(" + "|".join(re.escape(term) for term in sorted(terms, key=len, reverse=True)) + ")")
    spans = re.split(r'''("[^"]*"|'[^']*')''', original)
    for index in range(0, len(spans), 2):
        spans[index] = pattern.sub(
            lambda m: ' -"' + terms[m.group(2)] + '" ' if m.group(1) else " " + terms[m.group(2)] + " ",
            spans[index],
        )
        spans[index] = re.sub(r"\s+", " ", spans[index])
    return "".join(spans).strip()


def plan_academic_query(query, source=None):
    original = str(query or "").strip()
    doi = normalize_doi_query(original)
    arxiv = normalize_arxiv_identifier(original)
    query_type = "doi" if doi else "arxiv" if arxiv else "keywords"
    if not doi and (re.match(r"^doi:", original, re.I) or re.match(r"^https?://(?:dx\.)?doi\.org(?::[^/]*)?(?:/|$)", original, re.I)):
        raise _source_error(source or "crossref", "invalid_identifier", "Invalid exact DOI identifier", 422)
    if not arxiv and (re.match(r"^arxiv:", original, re.I) or re.match(r"^https?://(?:www\.|export\.)?arxiv\.org(?::[^/]*)?/(?:abs|pdf)/", original, re.I)):
        raise _source_error(source or "arxiv", "invalid_identifier", "Invalid exact arXiv identifier", 422)
    if source and ((query_type == "arxiv" and source != "arxiv") or (query_type == "doi" and source == "arxiv")):
        supported = "arXiv" if query_type == "arxiv" else "Crossref or OpenAlex"
        raise _source_error(source, "unsupported_identifier", f"Use {supported} for that exact identifier", 422)
    effective = doi or arxiv or sanitize_academic_search_query(original)
    if len(original) > MAX_EFFECTIVE_QUERY_LENGTH or len(effective) > MAX_EFFECTIVE_QUERY_LENGTH:
        raise _source_error(source or "crossref", "query_too_long", f"Effective query must not exceed {MAX_EFFECTIVE_QUERY_LENGTH} characters; no text was truncated", 422)
    return {"originalQuery": original, "effectiveQuery": effective, "queryType": query_type,
            "queryPlanning": {"kind": "exact-identifier" if query_type != "keywords" else "terminology-replacement",
                              "structuredFiltersApplied": [], "unmatchedQualifiersRetained": True}}


_ARXIV_FIELDS = {"ti", "au", "abs", "co", "jr", "cat", "rn", "id", "all", "submittedDate", "lastUpdatedDate"}


def _valid_arxiv_advanced(query):
    """Validate a bounded field/Boolean grammar; punctuation alone is not syntax."""
    tokens = re.findall(r'"[^"]*"|\[.*?\]|[^\s():]+:|\bANDNOT\b|\bAND\b|\bOR\b|[()]|[^\s()]+', query)
    # The tokenizer must consume all non-whitespace input without dropping punctuation.
    if re.sub(r"\s+", "", "".join(tokens)) != re.sub(r"\s+", "", query):
        return False
    position = 0
    def term():
        nonlocal position
        if position >= len(tokens):
            return False
        if tokens[position] == "(":
            position += 1
            if not expression() or position >= len(tokens) or tokens[position] != ")":
                return False
            position += 1
            return True
        field = tokens[position]
        if not field.endswith(":") or field[:-1] not in _ARXIV_FIELDS:
            return False
        position += 1
        if position >= len(tokens) or tokens[position] in {"AND", "OR", "ANDNOT", "(", ")"} or tokens[position].endswith(":"):
            return False
        position += 1
        return True
    def expression():
        nonlocal position
        if not term():
            return False
        while position < len(tokens) and tokens[position] in {"AND", "OR", "ANDNOT"}:
            position += 1
            if not term():
                return False
        return True
    return expression() and position == len(tokens)


def compile_arxiv_query(query):
    if _valid_arxiv_advanced(query):
        return query
    if query.count('"') % 2:
        raise _source_error("arxiv", "invalid_query", "Unbalanced quotes in arXiv query", 422)
    tokens = re.findall(r'''-?(?:"[^"]+"|'[^']+')|[^\s]+''', query)
    positives, exclusions = [], []
    for token in tokens:
        excluded = token.startswith("-") and len(token) > 1
        token = token[1:] if excluded else token
        if token.startswith('"') and token.endswith('"'):
            value = token
        elif token.startswith("'") and token.endswith("'"):
            value = '"' + token[1:-1] + '"'
        elif re.fullmatch(r"[\w.-]+", token):
            value = token
        else:
            value = '"' + token.replace('"', '').replace("\\", " ") + '"'
        (exclusions if excluded else positives).append("all:" + value)
    if not positives:
        raise _source_error("arxiv", "invalid_query", "arXiv query needs at least one positive term", 422)
    compiled = " AND ".join(positives) + "".join(" ANDNOT " + clause for clause in exclusions)
    return "(" + compiled + ")" if len(positives) > 1 or exclusions else compiled



async def fetch_openalex(query, limit=10):
    plan = plan_academic_query(query, "openalex")
    headers = {"User-Agent": USER_AGENT}
    if settings.OPENALEX_API_KEY:
        headers["Authorization"] = f"Bearer {settings.OPENALEX_API_KEY}"
    params = {"per-page": limit}
    if plan["queryType"] == "doi":
        params["filter"] = "doi:https://doi.org/" + plan["effectiveQuery"]
    else:
        params["search"] = plan["effectiveQuery"]
    url = "https://api.openalex.org/works"
    budget = settings.ACADEMIC_HTTP_TIMEOUT_SECONDS
    async def load(deadline):
        async with httpx.AsyncClient(timeout=max(.001, budget), follow_redirects=True) as client:
            response = await _execute_request_with_retry(client, url, params, headers, "OpenAlex", deadline=deadline)
            items = _record_list(_json_payload(response, "openalex").get("results"), "openalex")
            if plan["queryType"] == "doi":
                if not items:
                    raise _source_error("openalex", "not_found", "OpenAlex has no record for that exact DOI", 404)
                if any(normalize_doi_query(item.get("doi")) != plan["effectiveQuery"] for item in items):
                    raise _source_error("openalex", "invalid_response", "OpenAlex returned a different or invalid DOI record")
            return items
    return await _bounded_fetch("openalex", url, budget, load)


async def fetch_crossref(query, limit=10):
    plan = plan_academic_query(query, "crossref")
    doi = plan["effectiveQuery"] if plan["queryType"] == "doi" else ""
    headers = {"User-Agent": USER_AGENT + (f" (mailto:{settings.CROSSREF_MAILTO})" if settings.CROSSREF_MAILTO else "")}
    url = "https://api.crossref.org/works" + ("/" + quote(doi, safe="") if doi else "")
    params = {} if doi else {"query.bibliographic": plan["effectiveQuery"], "rows": limit}
    if settings.CROSSREF_MAILTO:
        params["mailto"] = settings.CROSSREF_MAILTO
    budget = settings.ACADEMIC_HTTP_TIMEOUT_SECONDS
    async def load(deadline):
        async with httpx.AsyncClient(timeout=max(.001, budget), follow_redirects=True) as client:
            response = await _execute_request_with_retry(client, url, params, headers, "Crossref", deadline=deadline, exact_lookup=bool(doi))
            message = _json_payload(response, "crossref").get("message")
            if not isinstance(message, dict):
                raise _source_error("crossref", "invalid_response", "Crossref returned an invalid message object")
            if doi:
                if normalize_doi_query(message.get("DOI")) != doi or not message.get("title"):
                    raise _source_error("crossref", "invalid_response", "Crossref returned a different or invalid DOI record")
                return _record_list([message], "crossref")
            return _record_list(message.get("items"), "crossref")
    return await _bounded_fetch("crossref", url, budget, load)


async def fetch_arxiv(query, limit=10):
    plan = plan_academic_query(query, "arxiv")
    identifier = plan["effectiveQuery"] if plan["queryType"] == "arxiv" else ""
    params = {"id_list": identifier, "max_results": limit} if identifier else {
        "search_query": compile_arxiv_query(plan["effectiveQuery"]), "start": 0, "max_results": limit, "sortBy": "relevance"}
    url = "https://export.arxiv.org/api/query"
    budget = settings.ARXIV_HTTP_TIMEOUT_SECONDS
    async def load(deadline):
        async with httpx.AsyncClient(timeout=max(.001, budget), follow_redirects=True) as client:
            response = await _execute_request_with_retry(client, url, params, {"User-Agent": USER_AGENT}, "arXiv", deadline=deadline, exact_lookup=bool(identifier))
            items = parse_arxiv_atom(response.text)
            if identifier:
                if not items:
                    raise _source_error("arxiv", "not_found", "arXiv has no record for that exact identifier", 404)
                if any(item["arxivId"] != extract_arxiv_id(identifier) for item in items):
                    raise _source_error("arxiv", "invalid_response", "arXiv returned a different exact identifier")
                version = re.search(r"v\d+$", identifier)
                if version and any(item["arxivVersion"] != version.group() for item in items):
                    raise _source_error("arxiv", "invalid_response", "arXiv returned a different requested version")
            return items
    return await _bounded_fetch("arxiv", url, budget, load)
