"""
academic.py - 学术检索薄代理路由端点
为 OpenAlex、Crossref、arXiv 提供同源代理、鉴权防护、参数校验与缓存封装
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_auth_payload
from app.core.config import settings
from app.services.academic_sources import (
    academic_cache,
    MAX_EFFECTIVE_QUERY_LENGTH,
    fetch_openalex,
    fetch_crossref,
    fetch_arxiv,
    plan_academic_query,
    compile_arxiv_query
)

router = APIRouter(prefix="/academic", tags=["academic"])


def _normalized_cache_query(query: str) -> str:
    """缓存键不区分大小写，并折叠用户输入中的重复空白。"""
    return " ".join(query.split()).casefold()


@router.get("/openalex/search")
async def search_openalex(
    query: str = Query(..., min_length=1, max_length=MAX_EFFECTIVE_QUERY_LENGTH, description="搜索题名、关键词或 DOI"),
    limit: int = Query(default=10, ge=1, le=20, description="单次返回结果数上限 1-20"),
    auth: dict = Depends(get_auth_payload)
):
    clean_query = query.strip()
    if not clean_query:
        raise HTTPException(status_code=422, detail="Query cannot be blank")

    plan = plan_academic_query(clean_query, "openalex")
    cache_key = f"openalex:{plan['queryType']}:{_normalized_cache_query(plan['effectiveQuery'])}:{limit}"
    items, cached = await academic_cache.get_or_fetch(
        cache_key, lambda: fetch_openalex(plan["effectiveQuery"], limit),
        ttl_seconds=settings.ACADEMIC_CACHE_TTL_SECONDS,
    )
    return {"source": "openalex", "items": items, "cached": cached, **plan}


@router.get("/crossref/search")
async def search_crossref(
    query: str = Query(..., min_length=1, max_length=MAX_EFFECTIVE_QUERY_LENGTH, description="搜索题名、关键词或 DOI"),
    limit: int = Query(default=10, ge=1, le=20, description="单次返回结果数上限 1-20"),
    auth: dict = Depends(get_auth_payload)
):
    clean_query = query.strip()
    if not clean_query:
        raise HTTPException(status_code=422, detail="Query cannot be blank")

    plan = plan_academic_query(clean_query, "crossref")
    cache_key = f"crossref:{plan['queryType']}:{_normalized_cache_query(plan['effectiveQuery'])}:{limit}"
    items, cached = await academic_cache.get_or_fetch(
        cache_key, lambda: fetch_crossref(plan["effectiveQuery"], limit),
        ttl_seconds=settings.ACADEMIC_CACHE_TTL_SECONDS,
    )
    return {"source": "crossref", "items": items, "cached": cached, **plan}


@router.get("/arxiv/search")
async def search_arxiv(
    query: str = Query(..., min_length=1, max_length=MAX_EFFECTIVE_QUERY_LENGTH, description="搜索预印本题名、关键词或 ID"),
    limit: int = Query(default=10, ge=1, le=20, description="单次返回结果数上限 1-20"),
    auth: dict = Depends(get_auth_payload)
):
    clean_query = query.strip()
    if not clean_query:
        raise HTTPException(status_code=422, detail="Query cannot be blank")

    plan = plan_academic_query(clean_query, "arxiv")
    # Boolean operators/quoted text are case-sensitive query intent in arXiv syntax.
    cache_query = compile_arxiv_query(plan["effectiveQuery"]) if plan["queryType"] == "keywords" else plan["effectiveQuery"]
    cache_key = f"arxiv:{plan['queryType']}:{cache_query}:{limit}"
    items, cached = await academic_cache.get_or_fetch(
        cache_key, lambda: fetch_arxiv(plan["effectiveQuery"], limit),
        ttl_seconds=settings.ARXIV_CACHE_TTL_SECONDS,
    )
    return {"source": "arxiv", "items": items, "cached": cached, **plan}
