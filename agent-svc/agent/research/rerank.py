"""Answer source reranking for the answer pipeline."""

import logging

from ..scraper_client import ScraperClient
from ..semantic_client import SemanticClient

logger = logging.getLogger(__name__)


async def _rerank_answer_sources(
    search_results: list[dict],
    query: str,
    retrieval_mode: str,
    semantic_url: str,
    scraper_url: str,
    limit: int,
) -> list[dict]:
    """Rerank or augment search results for the answer pipeline."""
    if retrieval_mode == "keyword" or not search_results:
        return search_results

    semantic = SemanticClient(semantic_url)
    scraper = ScraperClient(scraper_url)
    try:
        if retrieval_mode in ("semantic", "hybrid"):
            urls_to_scrape = [r["url"] for r in search_results[:limit]]
            contents = []
            for url in urls_to_scrape:
                try:
                    scraped = await scraper.scrape(url)
                    c = (
                        scraped.get("data", {}).get("markdown", "")
                        if scraped.get("success")
                        else ""
                    )
                    contents.append(c[:2000])
                except Exception:
                    contents.append("")

            if retrieval_mode == "semantic":
                embeddings = await semantic.embed([query, *contents])
                similarities = [
                    sum(a * b for a, b in zip(embeddings[0], emb, strict=False))
                    for emb in embeddings[1:]
                ]
                ranked = sorted(
                    range(len(similarities)),
                    key=lambda i: similarities[i],
                    reverse=True,
                )
                return [search_results[i] for i in ranked if i < len(search_results)]
            else:
                reranked = await semantic.rerank(
                    query,
                    [r.get("description", "") for r in search_results[:limit]],
                    top_k=limit,
                )
                new_order = [item["index"] for item in reranked]
                return [search_results[i] for i in new_order if i < len(search_results)]

        elif retrieval_mode == "vector":
            vector_results = await semantic.search_vector(query, limit=limit)
            return [
                {"url": r["url"], "title": r["title"], "description": ""}
                for r in vector_results
            ]

        elif retrieval_mode == "hybrid_vector":
            vector_results = await semantic.search_vector(query, limit=limit)
            seen: set[str] = set()
            merged: list[dict] = []
            for r in search_results[:limit]:
                if r["url"] not in seen:
                    seen.add(r["url"])
                    merged.append(r)
            for r in vector_results:
                if r["url"] not in seen:
                    seen.add(r["url"])
                    merged.append(
                        {"url": r["url"], "title": r["title"], "description": ""}
                    )
            return merged[:limit]

        return search_results
    finally:
        await semantic.close()
        await scraper.close()
