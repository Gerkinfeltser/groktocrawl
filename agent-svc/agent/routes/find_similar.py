"""Find-similar route handler — semantic similarity search for a URL."""

import logging
import time

from fastapi import APIRouter, Request

from ..models import FindSimilarRequest, FindSimilarResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/v2/find-similar", response_model=FindSimilarResponse)
async def find_similar(request: Request, body: FindSimilarRequest):
    """Find semantically similar pages for a given URL.

    Two search modes:
    - ``qdrant`` (default): Scrapes the URL, embeds its content, and
      searches the local Qdrant vector index for similar pages.
    - ``web``: Scrapes the URL, extracts keywords, searches the open web
      via SearXNG, then reranks results by cosine similarity against
      the query URL's embedding.
    """
    from ..research import run_find_similar

    start = time.monotonic()
    results = await run_find_similar(
        url=body.url,
        limit=body.limit,
        search_mode=body.search_mode,
        scraper_url=request.app.state.scraper_url,
        semantic_url=request.app.state.semantic_url,
        searxng_url=request.app.state.searxng_url,
    )
    latency = (time.monotonic() - start) * 1000

    return FindSimilarResponse(
        data=results,  # type: ignore[arg-type]
        query_url=body.url,
        search_mode=body.search_mode,
        latency_ms=round(latency, 1),
    )
