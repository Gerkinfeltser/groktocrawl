"""Discovery + scrape functions for the research agent."""

import asyncio
import logging

from common.url import extract_domain

from ..scraper_client import ScraperClient
from ..searxng_client import SearXNGClient
from .scoring import _filter_and_rank_urls, _is_video_platform_url

logger = logging.getLogger(__name__)


async def _scrape_single(
    url: str,
    scraper: ScraperClient,
    semaphore: asyncio.Semaphore,
    url_timeout: int = 70,
    scrape_options: dict | None = None,
) -> tuple[str | None, dict | None]:
    """Scrape a single URL with a semaphore for concurrency control.

    Returns (document_text, source_detail_dict) or (None, None) on failure.
    """
    async with semaphore:
        try:
            logger.info("Scraping: %s", url)
            result = await asyncio.wait_for(
                scraper.scrape_with_fallback(url, scrape_options=scrape_options),
                timeout=url_timeout,
            )
            if result.get("success") and result.get("data", {}).get("markdown"):
                md = result["data"]["markdown"]
                domain = extract_domain(url)
                doc = f"Source: {url} (domain: {domain})\n\n{md[:8000]}"
                src = {
                    "url": url,
                    "source": result["data"].get("source", "unknown"),
                    "char_count": len(md),
                }
                return doc, src
            else:
                logger.warning("Failed to scrape %s: %s", url, result.get("error"))
                return None, None
        except TimeoutError:
            logger.warning("Timeout scraping %s after %ss", url, url_timeout)
            return None, None
        except Exception as e:
            logger.warning("Error scraping %s: %s", url, e)
            return None, None


async def _scrape_urls(
    urls: list[str],
    scraper: ScraperClient,
    min_sources: int = 3,
    max_attempts: int | None = None,
    max_concurrent: int = 5,
    scrape_options: dict | None = None,
) -> tuple[list[str], list[dict]]:
    """Scrape URLs with bounded concurrency and return (documents, source_details).

    Tries URLs in batches until ``min_sources`` are successfully scraped
    or the list is exhausted (whichever comes first).
    Uses a semaphore (default ``max_concurrent`` = 5) with per-URL timeout (20s).
    ``max_attempts`` sets an upper bound on how many URLs are tried.
    """
    documents: list[str] = []
    source_details: list[dict] = []
    max_attempts = max_attempts or len(urls)
    semaphore = asyncio.Semaphore(max_concurrent)
    url_timeout = 70  # Accommodates scrape_with_fallback (20s generic + 45s browser)

    # Process URLs in batches — launch concurrent tasks, collect results,
    # stop when min_sources is reached or max_attempts exhausted
    pending = list(urls)
    task_to_url: dict[asyncio.Task, str] = {}
    tasks: set[asyncio.Task] = set()
    attempts = 0

    while pending or tasks:
        # Fill slots up to our budget
        while len(tasks) < max_concurrent and pending and attempts < max_attempts:
            url = pending.pop(0)
            attempts += 1
            task = asyncio.create_task(
                _scrape_single(url, scraper, semaphore, url_timeout, scrape_options)
            )
            task_to_url[task] = url
            tasks.add(task)

        if not tasks:
            break

        # Wait for at least one task to complete
        done, tasks = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

        for task in done:
            doc, src = task.result()
            if doc and src:
                documents.append(doc)
                source_details.append(src)
                if len(documents) >= min_sources:
                    # Cancel remaining tasks and stop
                    for t in tasks:
                        t.cancel()
                    tasks.clear()
                    return documents, source_details

    return documents, source_details


async def _scrape_with_fallback(
    urls: list[str],
    scraper: ScraperClient,
    min_sources: int = 3,
    scrape_options: dict | None = None,
) -> tuple[list[str], list[dict]]:
    """Scrape URLs with video-platform fallback strategy.

    Splits URLs into preferred (text-based) and deprioritized (video-platform).
    Scrapes preferred URLs first. If fewer than ``min_sources`` documents are
    obtained, falls back to deprioritized URLs.

    Returns (documents, source_details).
    """
    preferred = [u for u in urls if not _is_video_platform_url(u)]
    deprioritized = [u for u in urls if _is_video_platform_url(u)]

    documents, source_details = await _scrape_urls(
        preferred,
        scraper,
        min_sources=min_sources,
        max_attempts=len(preferred) or 10,
        scrape_options=scrape_options,
    )
    logger.info(
        "Scrape with fallback: %d docs from %d preferred URLs (min_sources=%d)",
        len(documents),
        len(preferred),
        min_sources,
    )

    if len(documents) < min_sources and deprioritized:
        remaining = min_sources - len(documents)
        extra_docs, extra_details = await _scrape_urls(
            deprioritized,
            scraper,
            min_sources=remaining,
            max_attempts=remaining * 2,
            scrape_options=scrape_options,
        )
        documents.extend(extra_docs)
        source_details.extend(extra_details)

    return documents, source_details


async def _run_multi_query_discover_and_scrape(
    queries: list[str],
    urls: list[str] | None,
    searxng: SearXNGClient,
    scraper: ScraperClient,
    max_searches_per_request: int = 5,
    scrape_options: dict | None = None,
) -> dict:
    """Search multiple sub-queries, deduplicate URLs, scrape, and merge context.

    Iterates over ``queries`` (truncated to ``max_searches_per_request``),
    running a search for each. Collects all unique URLs across all queries
    (deduplicating by URL, keeping the first occurrence for richer metadata),
    then scrapes the union. Merges documents into a single context block
    organized by query.

    Returns the same dict shape as ``_run_research_discover_and_scrape()``:
        search_results, target_urls, documents, source_details, context
    """
    target_urls = list(urls) if urls else []
    all_search_results: list[dict] = []
    seen_urls: set[str] = set(target_urls)

    # Truncate to search budget
    budget = min(len(queries), max_searches_per_request)
    queries_to_run = queries[:budget]

    if not target_urls and queries_to_run:
        logger.info(
            "Multi-query research: running %d search queries (budget=%d)",
            len(queries_to_run),
            max_searches_per_request,
        )

        search_tasks = [searxng.search(q, limit=10) for q in queries_to_run]
        search_results_list = await asyncio.gather(
            *search_tasks, return_exceptions=True
        )
        for i, (query, result_tuple) in enumerate(  # type: ignore[misc]
            zip(queries_to_run, search_results_list, strict=False), start=1
        ):
            logger.info("  [%d/%d] Searching: %s", i, len(queries_to_run), query)
            if isinstance(result_tuple, Exception):
                logger.warning("Search failed for %s: %s", query, result_tuple)
                continue
            results, _health = result_tuple  # type: ignore[misc]
            for r in results:
                url = r.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_search_results.append(r)
                    target_urls.append(url)

    if not target_urls and not queries_to_run:
        return {
            "search_results": [],
            "target_urls": [],
            "documents": [],
            "source_details": [],
            "context": "",
        }

    # Score and rank URLs before scraping (F1: source pre-filtering)
    target_urls = _filter_and_rank_urls(target_urls, max_urls=20)
    documents, source_details = await _scrape_with_fallback(
        target_urls, scraper, min_sources=3, scrape_options=scrape_options
    )
    context = "\n\n---\n\n".join(documents) if documents else ""

    return {
        "search_results": all_search_results,
        "target_urls": target_urls,
        "documents": documents,
        "source_details": source_details,
        "context": context,
    }


async def _run_research_discover_and_scrape(
    prompt: str,
    urls: list[str] | None,
    searxng: SearXNGClient,
    scraper: ScraperClient,
    max_searches_per_request: int = 5,
    scrape_options: dict | None = None,
) -> dict:
    """Search → filter → scrape → context-building phase for research.

    Shared by ``run_research`` and ``run_research_stream``. Uses
    ``_scrape_urls()`` for batch scraping; the stream variant yields
    progress events from the returned source_details after the call.
    """
    target_urls = list(urls) if urls else []
    search_results: list[dict] = []
    if not target_urls:
        logger.info("No URLs provided. Searching for: %s", prompt)
        search_results, _health = await searxng.search(prompt, limit=10)
        target_urls = [r["url"] for r in search_results if r.get("url")]

    # Score and rank URLs before scraping (F1: source pre-filtering)
    target_urls = _filter_and_rank_urls(target_urls, max_urls=20)
    documents, source_details = await _scrape_with_fallback(
        target_urls, scraper, min_sources=3, scrape_options=scrape_options
    )
    context = "\n\n---\n\n".join(documents) if documents else ""

    return {
        "search_results": search_results,
        "target_urls": target_urls,
        "documents": documents,
        "source_details": source_details,
        "context": context,
    }


async def _run_answer_discover_and_scrape(
    query: str,
    num_sources: int,
    retrieval_mode: str,
    searxng: SearXNGClient,
    scraper: ScraperClient,
    semantic_url: str,
    llm_base_url: str,
    llm_api_key: str,
    llm_model: str,
    requested_model: str | None,
    max_searches_per_request: int = 5,
) -> dict:
    """Search → rerank → filter → scrape → context-building for answer.

    Shared by ``run_answer`` and ``run_answer_stream``. Returns all
    intermediate data needed by both callers to proceed to LLM synthesis
    and citation parsing.
    """
    from .rerank import _rerank_answer_sources

    search_results: list[dict] = []
    logger.info("Answer: searching for: %s", query)
    search_results, _health = await searxng.search(query, limit=num_sources * 2)

    if retrieval_mode != "keyword":
        search_results = await _rerank_answer_sources(
            search_results,
            query,
            retrieval_mode,
            semantic_url,
            scraper.base_url,
            num_sources,
        )

    target_urls = [r["url"] for r in search_results if r.get("url")]

    # Step 2: Scrape (prefer text sources, use video platforms as fallback)
    preferred = [u for u in target_urls if not _is_video_platform_url(u)]
    deprioritized = [u for u in target_urls if _is_video_platform_url(u)]

    if deprioritized:
        logger.info(
            "Answer: %d preferred + %d video-platform URLs (deprioritized)",
            len(preferred),
            len(deprioritized),
        )

    documents, source_details = await _scrape_urls(
        preferred,
        scraper,
        min_sources=num_sources,
        max_attempts=num_sources * 2,
    )

    if len(documents) < num_sources and deprioritized:
        logger.info(
            "Answer: %d/%d from preferred sources, falling back to video-platform URLs",
            len(documents),
            num_sources,
        )
        remaining = num_sources - len(documents)
        more_docs, more_details = await _scrape_urls(
            deprioritized,
            scraper,
            min_sources=remaining,
            max_attempts=remaining * 2,
        )
        documents.extend(more_docs)
        source_details.extend(more_details)

    # Step 3: Build context with source markers
    context_parts = []
    for i, (doc, detail) in enumerate(
        zip(documents, source_details, strict=False), start=1
    ):
        url = detail["url"]
        title = next(
            (r.get("title", "") for r in search_results if r.get("url") == url), ""
        )
        context_parts.append(f"[{i}] Source: {url}\nTitle: {title}\n\n{doc}")

    context = "\n\n---\n\n".join(context_parts) if context_parts else ""

    # Step 4: Build source_map for citation resolution
    source_map: list[dict[str, str]] = []
    for r in search_results:
        if r.get("url") in [s["url"] for s in source_details]:
            source_map.append(
                {
                    "url": r["url"],
                    "title": r.get("title", ""),
                    "relevance": r.get("description", ""),
                }
            )

    return {
        "search_results": search_results,
        "context_parts": context_parts,
        "documents": documents,
        "source_details": source_details,
        "context": context,
        "source_map": source_map,
    }
