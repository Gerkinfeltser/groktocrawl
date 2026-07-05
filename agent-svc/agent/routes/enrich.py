"""Enrich route handler — enrich entities with web-sourced structured data."""

import logging
import time

from fastapi import APIRouter, Request

from ..models import EnrichRequest, EnrichResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/v2/enrich", response_model=EnrichResponse)
async def enrich(request: Request, body: EnrichRequest):
    """Enrich a list of entities with web-sourced structured data.

    Each item is processed independently: search → scrape → LLM extraction.
    Returns ``{value, source}`` pairs for each requested field.
    """
    from ..research import run_enrich_pipeline

    start = time.monotonic()
    result = await run_enrich_pipeline(
        items=body.items,
        fields=body.fields,
        source_hint=body.source_hint,
        effort=body.effort,
        searxng_url=request.app.state.searxng_url,
        scraper_url=request.app.state.scraper_url,
        llm_base_url=request.app.state.llm_base_url,
        llm_api_key=request.app.state.llm_api_key,
        llm_model=request.app.state.llm_model,
    )
    latency = (time.monotonic() - start) * 1000
    return EnrichResponse(
        data=result,
        latency_ms=round(latency, 1),
        items_enriched=len(body.items),
        fields_per_item=len(body.fields),
    )
