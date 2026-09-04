"""Discovery + scrape functions for the research agent."""

import asyncio
import logging
import time

from ..barrier_guard import is_barrier_flagged, log_refusal
from ..metrics import METRICS
from ..scraper_client import ScraperClient
from ..searxng_client import SearXNGClient
from .scoring import _filter_and_rank_urls, _is_video_platform_url
from .sources import (
    SourceArtifact,
    SourceRegistry,
    artifacts_to_documents_and_details,
    normalize_source_url,
)

logger = logging.getLogger(__name__)


def _rerank_artifact_flagged(artifact: SourceArtifact) -> bool:
    """Whether a rerank-reuse artifact carries barrier-flagged content.

    Rerank artifacts lose the scraper's ``warning``/``quality`` envelope (only
    markdown survives), so flagging is re-derived from the content itself via
    the shared challenge-marker check in barrier_guard (#586).
    """
    from ..barrier_guard import markdown_is_challenge

    return markdown_is_challenge(artifact.markdown)


async def _scrape_single(
    url: str,
    scraper: ScraperClient,
    semaphore: asyncio.Semaphore,
    url_timeout: int = 70,
    scrape_options: dict | None = None,
) -> SourceArtifact | None:
    """Scrape a single URL with a semaphore for concurrency control.

    Returns a ``SourceArtifact`` carrying the fetched Markdown, or None on
    failure. Barrier-flagged payloads (success-with-warning or block-fail
    quality) are refused — the source is never ingested (#586).
    """
    async with semaphore:
        try:
            logger.info("Scraping: %s", url)
            result = await asyncio.wait_for(
                scraper.scrape_with_fallback(url, scrape_options=scrape_options),
                timeout=url_timeout,
            )
            if result.get("success") and result.get("data", {}).get("markdown"):
                if is_barrier_flagged(result):
                    log_refusal(url, result)
                    return None
                md = result["data"]["markdown"]
                return SourceArtifact(
                    url=url,
                    markdown=md,
                    source=result["data"].get("source", "unknown"),
                    char_count=len(md),
                    cache_state="live",
                    fetched_at=time.time(),
                    fetch_options=scrape_options,
                )
            else:
                logger.warning("Failed to scrape %s: %s", url, result.get("error"))
                return None
        except TimeoutError:
            logger.warning("Timeout scraping %s after %ss", url, url_timeout)
            return None
        except Exception as e:
            logger.warning("Error scraping %s: %s", url, e)
            return None


async def _scrape_urls(
    urls: list[str],
    scraper: ScraperClient,
    min_sources: int = 3,
    max_attempts: int | None = None,
    max_concurrent: int = 5,
    scrape_options: dict | None = None,
    source_registry: SourceRegistry | None = None,
) -> list[SourceArtifact]:
    """Scrape URLs with bounded concurrency and return ``SourceArtifact``s.

    Tries URLs in batches until ``min_sources`` are successfully scraped
    or the list is exhausted (whichever comes first).
    Uses a semaphore (default ``max_concurrent`` = 5) with per-URL timeout (70s).
    ``max_attempts`` sets an upper bound on how many URLs are tried.
    Cancelled speculative tasks are awaited before returning so no pending
    coroutine is left behind.
    """
    artifacts: list[SourceArtifact] = []
    urls_to_scrape: list[str] = []
    seen_keys: set[str] = set()
    for url in urls:
        key = normalize_source_url(url)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        if source_registry is not None:
            reused = source_registry.get(url, scrape_options)
            if reused is not None:
                artifacts.append(reused)
                METRICS.counter(
                    "fetches_deduped_total",
                    "Total scrapes avoided by reusing already-fetched content",
                    ["reason"],
                ).inc({"reason": "research_registry"})
                continue
        urls_to_scrape.append(url)

    # A compatible artifact satisfies the source quota without consuming a
    # credit or launching speculative work. Failed attempts are intentionally
    # absent from the registry and remain in this fresh list for retry.
    if len(artifacts) >= min_sources or not urls_to_scrape:
        return artifacts

    urls = urls_to_scrape
    max_attempts = max_attempts or len(urls)
    semaphore = asyncio.Semaphore(max_concurrent)
    url_timeout = 70  # Accommodates scrape_with_fallback (20s generic + 45s browser)

    # Process URLs in batches — launch concurrent tasks, collect results,
    # stop when min_sources is reached or max_attempts exhausted
    pending = list(urls)
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
            tasks.add(task)

        if not tasks:
            break

        # Wait for at least one task to complete
        done, tasks = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

        for task in done:
            artifact = task.result()
            if artifact is not None:
                if source_registry is not None:
                    artifact = source_registry.register(artifact, scrape_options)
                artifacts.append(artifact)
                if len(artifacts) >= min_sources:
                    # Cancel remaining speculative tasks and await them so no
                    # pending task is destroyed (or races browser cleanup).
                    for t in tasks:
                        t.cancel()
                    if tasks:
                        await asyncio.gather(*tasks, return_exceptions=True)
                    return artifacts

    return artifacts


def _dedupe_urls(urls: list[str]) -> list[str]:
    """Keep first URL spelling while deduplicating conservative identities."""
    seen: set[str] = set()
    result: list[str] = []
    for url in urls:
        key = normalize_source_url(url)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(url)
    return result


def _apply_credit_budget(
    urls: list[str],
    max_credits: int | None,
    source_registry: SourceRegistry | None,
    scrape_options: dict | None,
) -> list[str]:
    """Bound only novel acquisitions; compatible registry hits are free."""
    if max_credits is None or max_credits < 0:
        return urls
    if source_registry is None:
        return urls[:max_credits]

    result: list[str] = []
    novel = 0
    for url in urls:
        if source_registry.get(url, scrape_options) is None:
            if novel >= max_credits:
                continue
            novel += 1
        result.append(url)
    return result


def _discovery_result(
    *,
    search_results: list[dict],
    target_urls: list[str],
    artifacts: list[SourceArtifact],
    source_registry: SourceRegistry | None,
    reusable_keys: set[str],
    pass_number: int | None = None,
) -> dict:
    """Project discovery with unique context and acquisition accounting."""
    all_artifacts = (
        source_registry.artifacts() if source_registry is not None else artifacts
    )
    documents, source_details = artifacts_to_documents_and_details(all_artifacts)
    context = "\n\n---\n\n".join(documents) if documents else ""
    novel_artifacts = [
        artifact
        for artifact in artifacts
        if normalize_source_url(artifact.url) not in reusable_keys
    ]
    reused_artifacts = [
        artifact
        for artifact in artifacts
        if normalize_source_url(artifact.url) in reusable_keys
    ]
    if pass_number is not None:
        METRICS.counter(
            "research_novel_sources_total",
            "Successfully acquired novel sources by research pass",
            ["pass"],
        ).inc({"pass": str(pass_number)}, len(novel_artifacts))
    return {
        "search_results": search_results,
        "target_urls": target_urls,
        "documents": documents,
        "source_details": source_details,
        "context": context,
        "artifacts": all_artifacts,
        "new_artifacts": novel_artifacts,
        "reused_artifacts": reused_artifacts,
        "novel_sources": [artifact.url for artifact in novel_artifacts],
        "reused_sources": [artifact.url for artifact in reused_artifacts],
        "credits_used": len(novel_artifacts),
        "fetches_deduped": len(reused_artifacts),
    }


async def _scrape_with_fallback(
    urls: list[str],
    scraper: ScraperClient,
    min_sources: int = 3,
    scrape_options: dict | None = None,
    source_registry: SourceRegistry | None = None,
) -> list[SourceArtifact]:
    """Scrape URLs with video-platform fallback strategy.

    Splits URLs into preferred (text-based) and deprioritized (video-platform).
    Scrapes preferred URLs first. If fewer than ``min_sources`` artifacts are
    obtained, falls back to deprioritized URLs.

    Returns a list of ``SourceArtifact``s.
    """
    preferred = [u for u in urls if not _is_video_platform_url(u)]
    deprioritized = [u for u in urls if _is_video_platform_url(u)]

    artifacts = await _scrape_urls(
        preferred,
        scraper,
        min_sources=min_sources,
        max_attempts=len(preferred) or 10,
        scrape_options=scrape_options,
        source_registry=source_registry,
    )
    logger.info(
        "Scrape with fallback: %d docs from %d preferred URLs (min_sources=%d)",
        len(artifacts),
        len(preferred),
        min_sources,
    )

    if len(artifacts) < min_sources and deprioritized:
        remaining = min_sources - len(artifacts)
        extra = await _scrape_urls(
            deprioritized,
            scraper,
            min_sources=remaining,
            max_attempts=remaining * 2,
            scrape_options=scrape_options,
            source_registry=source_registry,
        )
        artifacts.extend(extra)

    return artifacts


async def _run_multi_query_discover_and_scrape(
    queries: list[str],
    urls: list[str] | None,
    searxng: SearXNGClient,
    scraper: ScraperClient,
    max_searches_per_request: int = 5,
    scrape_options: dict | None = None,
    max_credits: int | None = None,
    source_registry: SourceRegistry | None = None,
    pass_number: int | None = None,
) -> dict:
    """Search multiple sub-queries, deduplicate URLs, scrape, and merge context.

    Iterates over ``queries`` (truncated to ``max_searches_per_request``),
    running a search for each. Collects all unique URLs across all queries
    (deduplicating by URL, keeping the first occurrence for richer metadata),
    then scrapes the union. Merges documents into a single context block
    organized by query.

    When ``max_credits`` is set (1 credit ≈ one successfully scraped page),
    the candidate list handed to the scraper is truncated to that budget so
    discovery can never exceed the requested credit allowance.

    Returns the same dict shape as ``_run_research_discover_and_scrape()``:
        search_results, target_urls, documents, source_details, context
    """
    source_registry = source_registry or SourceRegistry()
    target_urls = _dedupe_urls(list(urls) if urls else [])
    all_search_results: list[dict] = []
    seen_urls: set[str] = {normalize_source_url(url) for url in target_urls}

    # Truncate to search budget
    budget = min(len(queries), max_searches_per_request)
    queries_to_run = queries[:budget]

    if not target_urls and queries_to_run:
        logger.info(
            "Multi-query research: running %d search queries (budget=%d)",
            len(queries_to_run),
            max_searches_per_request,
        )

        search_tasks = [
            searxng.search(q, limit=10, raise_on_rate_limit=True)
            for q in queries_to_run
        ]
        search_results_list = await asyncio.gather(
            *search_tasks, return_exceptions=True
        )
        for i, (query, result_tuple) in enumerate(  # type: ignore[misc]
            zip(queries_to_run, search_results_list, strict=False), start=1
        ):
            logger.info("  [%d/%d] Searching: %s", i, len(queries_to_run), query)
            if isinstance(result_tuple, Exception):
                from ..exceptions import RetryableRateLimitError

                if isinstance(result_tuple, RetryableRateLimitError):
                    # A downstream capacity condition affects the whole job,
                    # not a single query: propagate so the worker schedules a
                    # bounded retry (ADR-0053). Other search failures degrade
                    # gracefully as before.
                    raise result_tuple
                logger.warning("Search failed for %s: %s", query, result_tuple)
                continue
            results, _health = result_tuple  # type: ignore[misc]
            for r in results:
                url = r.get("url", "")
                normalized = normalize_source_url(url)
                if url and normalized not in seen_urls:
                    seen_urls.add(normalized)
                    all_search_results.append(r)
                    target_urls.append(url)

    if not target_urls and not queries_to_run:
        return _discovery_result(
            search_results=[],
            target_urls=[],
            artifacts=[],
            source_registry=source_registry,
            reusable_keys=set(),
            pass_number=pass_number,
        )

    # Score and rank URLs before scraping (F1: source pre-filtering)
    target_urls = _dedupe_urls(_filter_and_rank_urls(target_urls, max_urls=20))
    reusable_keys = {
        normalize_source_url(url)
        for url in target_urls
        if source_registry.get(url, scrape_options) is not None
    }
    target_urls = _apply_credit_budget(
        target_urls, max_credits, source_registry, scrape_options
    )
    artifacts = await _scrape_with_fallback(
        target_urls,
        scraper,
        min_sources=3,
        scrape_options=scrape_options,
        source_registry=source_registry,
    )
    return _discovery_result(
        search_results=all_search_results,
        target_urls=target_urls,
        artifacts=artifacts,
        source_registry=source_registry,
        reusable_keys=reusable_keys,
        pass_number=pass_number,
    )


async def _run_research_discover_and_scrape(
    prompt: str,
    urls: list[str] | None,
    searxng: SearXNGClient,
    scraper: ScraperClient,
    max_searches_per_request: int = 5,
    scrape_options: dict | None = None,
    max_credits: int | None = None,
    source_registry: SourceRegistry | None = None,
    pass_number: int | None = None,
) -> dict:
    """Search → filter → scrape → context-building phase for research.

    Shared by ``run_research`` and ``run_research_stream``. Uses
    ``_scrape_urls()`` for batch scraping; the stream variant yields
    progress events from the returned source_details after the call.

    When ``max_credits`` is set (1 credit ≈ one successfully scraped page),
    the candidate list handed to the scraper is truncated to that budget so
    discovery can never exceed the requested credit allowance.
    """
    source_registry = source_registry or SourceRegistry()
    target_urls = _dedupe_urls(list(urls) if urls else [])
    search_results: list[dict] = []
    if not target_urls:
        logger.info("No URLs provided. Searching for: %s", prompt)
        search_results, _health = await searxng.search(
            prompt, limit=10, raise_on_rate_limit=True
        )
        target_urls = _dedupe_urls([r["url"] for r in search_results if r.get("url")])

    # Score and rank URLs before scraping (F1: source pre-filtering)
    target_urls = _dedupe_urls(_filter_and_rank_urls(target_urls, max_urls=20))
    reusable_keys = {
        normalize_source_url(url)
        for url in target_urls
        if source_registry.get(url, scrape_options) is not None
    }
    target_urls = _apply_credit_budget(
        target_urls, max_credits, source_registry, scrape_options
    )
    artifacts = await _scrape_with_fallback(
        target_urls,
        scraper,
        min_sources=3,
        scrape_options=scrape_options,
        source_registry=source_registry,
    )
    return _discovery_result(
        search_results=search_results,
        target_urls=target_urls,
        artifacts=artifacts,
        source_registry=source_registry,
        reusable_keys=reusable_keys,
        pass_number=pass_number,
    )


async def _scrape_answer_sources(
    target_urls: list[str],
    rerank_artifacts: list[SourceArtifact],
    scraper: ScraperClient,
    num_sources: int,
) -> list[SourceArtifact]:
    """Scrape only answer sources whose content was not already fetched.

    Reuses Markdown carried by ``rerank_artifacts``, scrapes the remaining
    preferred (non-video) URLs, and falls back to video-platform URLs only
    when the ``num_sources`` quota is still unmet. Returns ordered artifacts
    (preferred in rank order, then any video fallback), deduplicated by URL
    and bounded to ``num_sources``.

    Barrier-flagged rerank artifacts are dropped (#586): their markdown came
    from bare ``scraper.scrape()`` calls that bypassed the shared refusal
    seam, so they are re-gated here before reaching the answer context.
    """
    # Search results can repeat the same URL (keyword mode returns up to
    # 2x num_sources entries, many of them duplicates). Deduplicate first so
    # one artifact per URL is produced and the quota cannot be exceeded.
    seen_urls: set[str] = set()
    deduped_urls: list[str] = []
    for u in target_urls:
        if u not in seen_urls:
            seen_urls.add(u)
            deduped_urls.append(u)
    target_urls = deduped_urls

    reused: dict[str, SourceArtifact] = {}
    for artifact in rerank_artifacts:
        if not artifact.markdown:
            continue
        if _rerank_artifact_flagged(artifact):
            log_refusal(
                artifact.url,
                {
                    "warning": None,
                    "data": {"quality": {"checks": {"block_detected": "fail"}}},
                },
            )
            continue
        reused[artifact.url] = artifact
    dedup_counter = METRICS.counter(
        "fetches_deduped_total",
        "Total scrapes avoided by reusing already-fetched content",
        ["reason"],
    )
    for _ in reused:
        dedup_counter.inc({"reason": "rerank_reuse"})

    preferred = [u for u in target_urls if not _is_video_platform_url(u)]
    deprioritized = [u for u in target_urls if _is_video_platform_url(u)]

    if deprioritized:
        logger.info(
            "Answer: %d preferred + %d video-platform URLs (deprioritized)",
            len(preferred),
            len(deprioritized),
        )

    missing_preferred = [u for u in preferred if u not in reused]
    fresh_preferred = await _scrape_urls(
        missing_preferred,
        scraper,
        min_sources=max(0, num_sources - len(reused)),
        max_attempts=len(missing_preferred) or 1,
    )
    fresh_by_url = {a.url: a for a in fresh_preferred}

    preferred_artifacts = [
        preferred_artifact
        for u in preferred
        if (preferred_artifact := reused.get(u) or fresh_by_url.get(u)) is not None
    ][:num_sources]
    artifacts = list(preferred_artifacts)

    if len(artifacts) < num_sources and deprioritized:
        logger.info(
            "Answer: %d/%d from preferred sources, falling back to video-platform URLs",
            len(artifacts),
            num_sources,
        )
        missing_video = [u for u in deprioritized if u not in reused]
        remaining = num_sources - len(artifacts)
        fresh_video = await _scrape_urls(
            missing_video,
            scraper,
            min_sources=remaining,
            max_attempts=remaining * 2,
        )
        video_by_url = {a.url: a for a in fresh_video}
        for u in deprioritized:
            if len(artifacts) >= num_sources:
                break
            video_artifact = reused.get(u) or video_by_url.get(u)
            if video_artifact is not None:
                artifacts.append(video_artifact)

    return artifacts


def _build_answer_context(
    search_results: list[dict],
    artifacts: list[SourceArtifact],
) -> dict:
    """Build answer context blocks and the citation source map from artifacts."""
    documents, source_details = artifacts_to_documents_and_details(artifacts)

    context_parts = []
    for i, artifact in enumerate(artifacts, start=1):
        title = next(
            (
                r.get("title", "")
                for r in search_results
                if r.get("url") == artifact.url
            ),
            "",
        )
        context_parts.append(
            f"[{i}] Source: {artifact.url}\nTitle: {title}\n\n{artifact.to_document()}"
        )

    context = "\n\n---\n\n".join(context_parts) if context_parts else ""

    # source_map is ordered to match context_parts so that the ``[N]`` markers
    # the LLM sees map 1:1 onto source_map[N-1].
    source_map: list[dict[str, str]] = []
    for artifact in artifacts:
        title = next(
            (
                r.get("title", "")
                for r in search_results
                if r.get("url") == artifact.url
            ),
            "",
        )
        relevance = next(
            (
                r.get("description", "")
                for r in search_results
                if r.get("url") == artifact.url
            ),
            "",
        )
        source_map.append({"url": artifact.url, "title": title, "relevance": relevance})

    return {
        "context_parts": context_parts,
        "documents": documents,
        "source_details": source_details,
        "context": context,
        "source_map": source_map,
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

    Shared by ``run_answer`` and ``run_answer_stream``. Reranking may fetch
    candidate content concurrently; that content is reused here so a URL is
    not scraped twice. Returns all intermediate data needed by both callers
    to proceed to LLM synthesis and citation parsing.
    """
    from .rerank import _rerank_answer_sources

    search_results: list[dict] = []
    logger.info("Answer: searching for: %s", query)
    if retrieval_mode == "hybrid_vector":
        # Defer web search to the hybrid planner, which runs SearXNG and
        # Qdrant discovery concurrently (web is not searched twice).
        search_results = []
    else:
        search_results, _health = await searxng.search(
            query, limit=num_sources * 2, raise_on_rate_limit=True
        )

    rerank_artifacts: list[SourceArtifact] = []
    if retrieval_mode != "keyword":
        search_results, rerank_artifacts = await _rerank_answer_sources(
            search_results,
            query,
            retrieval_mode,
            semantic_url,
            scraper.base_url,
            num_sources,
            searxng=searxng,
        )

    target_urls = [r["url"] for r in search_results if r.get("url")]
    artifacts = await _scrape_answer_sources(
        target_urls, rerank_artifacts, scraper, num_sources
    )

    return {
        "search_results": search_results,
        **_build_answer_context(search_results, artifacts),
    }
