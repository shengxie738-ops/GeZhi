"""
academic.py - 学术检索薄代理路由端点
为 OpenAlex、Crossref、arXiv 提供同源代理、鉴权防护、参数校验与缓存封装
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_auth_payload
from app.core.config import settings
from app.services.academic_sources import (
    academic_cache,
    fetch_openalex,
    fetch_crossref,
    fetch_arxiv
)

router = APIRouter(prefix="/academic", tags=["academic"])


@router.get("/openalex/search")
async def search_openalex(
    query: str = Query(..., min_length=1, max_length=300, description="搜索题名、关键词或 DOI"),
    limit: int = Query(default=10, ge=1, le=20, description="单次返回结果数上限 1-20"),
    auth: dict = Depends(get_auth_payload)
):
    clean_query = query.strip()
    if not clean_query:
        raise HTTPException(status_code=422, detail="Query cannot be blank")

    cache_key = f"openalex:{clean_query}:{limit}"
    cached = academic_cache.get(cache_key)
    if cached is not None:
        return {"source": "openalex", "items": cached, "cached": True}

    items = await fetch_openalex(clean_query, limit)
    academic_cache.set(cache_key, items, ttl_seconds=settings.ACADEMIC_CACHE_TTL_SECONDS)
    return {"source": "openalex", "items": items, "cached": False}


@router.get("/crossref/search")
async def search_crossref(
    query: str = Query(..., min_length=1, max_length=300, description="搜索题名、关键词或 DOI"),
    limit: int = Query(default=10, ge=1, le=20, description="单次返回结果数上限 1-20"),
    auth: dict = Depends(get_auth_payload)
):
    clean_query = query.strip()
    if not clean_query:
        raise HTTPException(status_code=422, detail="Query cannot be blank")

    cache_key = f"crossref:{clean_query}:{limit}"
    cached = academic_cache.get(cache_key)
    if cached is not None:
        return {"source": "crossref", "items": cached, "cached": True}

    items = await fetch_crossref(clean_query, limit)
    academic_cache.set(cache_key, items, ttl_seconds=settings.ACADEMIC_CACHE_TTL_SECONDS)
    return {"source": "crossref", "items": items, "cached": False}


@router.get("/arxiv/search")
async def search_arxiv(
    query: str = Query(..., min_length=1, max_length=300, description="搜索预印本题名、关键词或 ID"),
    limit: int = Query(default=10, ge=1, le=20, description="单次返回结果数上限 1-20"),
    auth: dict = Depends(get_auth_payload)
):
    clean_query = query.strip()
    if not clean_query:
        raise HTTPException(status_code=422, detail="Query cannot be blank")

    cache_key = f"arxiv:{clean_query}:{limit}"
    cached = academic_cache.get(cache_key)
    if cached is not None:
        return {"source": "arxiv", "items": cached, "cached": True}

    items = await fetch_arxiv(clean_query, limit)
    academic_cache.set(cache_key, items, ttl_seconds=settings.ARXIV_CACHE_TTL_SECONDS)
    return {"source": "arxiv", "items": items, "cached": False}
