"""Answer source reranking for the answer pipeline."""

import asyncio
import logging
import time

from common.stage_metrics import observe_elapsed

from ..scraper_client import ScraperClient
from ..searxng_client import SearXNGClient
from ..semantic_client import SemanticClient
from .sources import SourceArtifact

logger = logging.getLogger(__name__)

_RANK_SECONDS = "groktocrawl_research_rank_seconds"
_RANK_SECONDS_HELP = "URL ranking/reranking latency by mode"

# Bounded concurrency for candidate scraping during ranking, mirroring the
# ``_scrape_urls`` default.
_RERANK_MAX_CONCURRENT = 5


async def _scrape_candidates(
    urls: list[str],
    scraper: ScraperClient,
    max_concurrent: int = _RERANK_MAX_CONCURRENT,
) -> list[SourceArtifact]:
    """Scrape candidate URLs concurrently with a bounded semaphore.

    The returned artifact list preserves ``urls`` order. A failed or empty
    scrape produces an artifact with ``markdown=None`` so callers can tell
    "no content" from "not attempted".
    """
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _scrape_one(url: str) -> SourceArtifact:
        async with semaphore:
            try:
                scraped = await scraper.scrape(url)
            except Exception as e:
                logger.warning("Rerank scrape failed for %s: %s", url, e)
                return SourceArtifact(url=url)
            if scraped.get("success"):
                markdown = scraped.get("data", {}).get("markdown", "") or ""
                return SourceArtifact(
                    url=url,
                    markdown=markdown,
                    source=scraped.get("data", {}).get("source", "unknown"),
                    char_count=len(markdown),
                    fetched_at=time.time(),
                )
            return SourceArtifact(url=url)

    return list(await asyncio.gather(*[_scrape_one(url) for url in urls]))


async def _rerank_answer_sources(
    search_results: list[dict],
    query: str,
    retrieval_mode: str,
    semantic_url: str,
    scraper_url: str,
    limit: int,
    max_concurrent: int = _RERANK_MAX_CONCURRENT,
    searxng: SearXNGClient | None = None,
) -> tuple[list[dict], list[SourceArtifact]]:
    """Rerank or augment search results for the answer pipeline.

    Returns ``(ranked_results, artifacts)``. For semantic and hybrid modes the
    artifacts carry the candidate Markdown fetched concurrently during ranking
    so final synthesis can reuse it instead of scraping again.
    """
    if retrieval_mode == "keyword" or (
        not search_results and retrieval_mode != "hybrid_vector"
    ):
        return search_results, []

    started = time.monotonic()
    semantic = SemanticClient(semantic_url)
    scraper = ScraperClient(scraper_url)
    try:
        if retrieval_mode in ("semantic", "hybrid"):
            candidates = search_results[:limit]
            artifacts = await _scrape_candidates(
                [r["url"] for r in candidates], scraper, max_concurrent
            )
            contents = [
                artifact.markdown[:2000] if artifact.markdown else ""
                for artifact in artifacts
            ]

            if retrieval_mode == "semantic":
                embeddings = await semantic.embed([query, *contents])
                similarities = [
                    sum(a * b for a, b in zip(embeddings[0], emb, strict=False))
                    for emb in embeddings[1:]
                ]
                order = sorted(
                    range(len(similarities)),
                    key=lambda i: similarities[i],
                    reverse=True,
                )
                return (
                    [candidates[i] for i in order],
                    [artifacts[i] for i in order],
                )

            # Hybrid mode ranks the fetched content, not search-result
            # descriptions, so the scrape is never performed just to be
            # discarded.
            reranked = await semantic.rerank(query, contents, top_k=limit)
            order = [item["index"] for item in reranked]
            return (
                [candidates[i] for i in order if i < len(candidates)],
                [artifacts[i] for i in order if i < len(artifacts)],
            )

        elif retrieval_mode == "vector":
            vector_results = await semantic.search_vector(query, limit=limit)
            return [
                {"url": r["url"], "title": r["title"], "description": ""}
                for r in vector_results
            ], []

        elif retrieval_mode == "hybrid_vector":
            from .hybrid import plan_hybrid_retrieval

            plan = await plan_hybrid_retrieval(
                query=query,
                limit=limit,
                searxng=searxng,
                semantic=semantic,
                web_results=search_results or None,
                scraper=scraper,
                # The answer pipeline retries whole requests on downstream
                # capacity conditions (ADR-0053); /v2/search keeps the
                # degrading default.
                raise_on_rate_limit=True,
            )
            return plan.results, plan.artifacts

        return search_results, []
    finally:
        observe_elapsed(_RANK_SECONDS, _RANK_SECONDS_HELP, {"mode": "rerank"}, started)
        await semantic.close()
        await scraper.close()
