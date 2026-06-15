"""Worker entrypoint and processing functions for GroktoCrawl jobs."""

import asyncio
import logging
import time
from typing import Any

from .metrics import METRICS
from .research import run_extract, run_research
from .scraper_client import ScraperClient
from .settings import load_settings
from .store import JobStore
from .webhook import deliver_webhook

logger = logging.getLogger(__name__)


def _get_worker_settings():
    return load_settings()


async def _process_agent_async(
    job_id: str,
    prompt: str,
    urls: list[str] | None,
    schema_: dict[str, Any] | None,
    llm_base_url: str,
    llm_api_key: str,
    llm_model: str,
    searxng_url: str,
    scraper_url: str,
    webhook_config: dict[str, Any] | None = None,
    requested_model: str | None = None,
) -> None:
    settings = _get_worker_settings()
    store = JobStore(
        f"redis://{settings.valkey_host}:{settings.valkey_port}/{settings.valkey_db}"
    )
    start = time.monotonic()
    METRICS.counter("jobs_submitted_total", "Total jobs submitted", ["type"]).inc(
        {"type": "agent"}
    )
    try:
        result = await run_research(
            prompt=prompt,
            urls=urls,
            schema=schema_,
            searxng_url=searxng_url,
            scraper_url=scraper_url,
            llm_base_url=llm_base_url,
            llm_api_key=llm_api_key,
            llm_model=llm_model,
            requested_model=requested_model,
        )
        store.complete_job(job_id, result)
        await deliver_webhook(webhook_config, "completed", job_id, result)
        elapsed = time.monotonic() - start
        METRICS.histogram(
            "job_duration_seconds", "Job processing duration", ["type", "status"]
        ).observe({"type": "agent", "status": "completed"}, elapsed)
        METRICS.counter("jobs_completed_total", "Total completed jobs", ["type"]).inc(
            {"type": "agent"}
        )
        logger.info("Agent job %s completed in %.2fs", job_id, elapsed)
    except Exception as e:
        logger.exception("Agent job %s failed", job_id)
        store.fail_job(job_id, str(e))
        await deliver_webhook(webhook_config, "failed", job_id, {"error": str(e)})
        elapsed = time.monotonic() - start
        METRICS.histogram(
            "job_duration_seconds", "Job processing duration", ["type", "status"]
        ).observe({"type": "agent", "status": "failed"}, elapsed)
        METRICS.counter("jobs_failed_total", "Total failed jobs", ["type"]).inc(
            {"type": "agent"}
        )


async def _process_crawl_async(
    job_id: str,
    url: str,
    max_pages: int,
    max_depth: int,
    scraper_url: str,
    webhook_config: dict[str, Any] | None = None,
    task_tracker: Any = None,
) -> None:
    settings = _get_worker_settings()
    store = JobStore(
        f"redis://{settings.valkey_host}:{settings.valkey_port}/{settings.valkey_db}"
    )
    scraper = ScraperClient(scraper_url)
    start = time.monotonic()
    METRICS.counter("jobs_submitted_total", "Total jobs submitted", ["type"]).inc(
        {"type": "crawl"}
    )
    try:
        result = await scraper.scrape(url)
        pages = []
        if result.get("success"):
            data = result["data"]
            pages.append({"url": url, "markdown": data.get("markdown", "")})
            # Extract title from metadata if available
            metadata = data.get("metadata") or {}
            og = metadata.get("og") or {}
            meta = metadata.get("meta") or {}
            title = og.get("title") or meta.get("title") or data.get("title", "")
            if task_tracker is not None:
                task_tracker.create_background_task(
                    _index_page_async(url, title, data.get("markdown", "")[:2000])
                )
            else:
                asyncio.create_task(
                    _index_page_async(url, title, data.get("markdown", "")[:2000])
                )
        payload = {"completed": len(pages), "total": 1, "pages": pages}
        store.complete_job(job_id, payload)
        await deliver_webhook(webhook_config, "completed", job_id, payload)
        elapsed = time.monotonic() - start
        METRICS.histogram(
            "job_duration_seconds", "Job processing duration", ["type", "status"]
        ).observe({"type": "crawl", "status": "completed"}, elapsed)
        METRICS.counter("jobs_completed_total", "Total completed jobs", ["type"]).inc(
            {"type": "crawl"}
        )
    except Exception as e:
        logger.exception("Crawl job %s failed", job_id)
        store.fail_job(job_id, str(e))
        await deliver_webhook(webhook_config, "failed", job_id, {"error": str(e)})
        elapsed = time.monotonic() - start
        METRICS.histogram(
            "job_duration_seconds", "Job processing duration", ["type", "status"]
        ).observe({"type": "crawl", "status": "failed"}, elapsed)
        METRICS.counter("jobs_failed_total", "Total failed jobs", ["type"]).inc(
            {"type": "crawl"}
        )
    finally:
        await scraper.close()


async def _process_batch_scrape_async(
    job_id: str,
    urls: list[str],
    scraper_url: str,
    webhook_config: dict[str, Any] | None = None,
    task_tracker: Any = None,
) -> None:
    settings = _get_worker_settings()
    store = JobStore(
        f"redis://{settings.valkey_host}:{settings.valkey_port}/{settings.valkey_db}"
    )
    scraper = ScraperClient(scraper_url)
    start = time.monotonic()
    METRICS.counter("jobs_submitted_total", "Total jobs submitted", ["type"]).inc(
        {"type": "batch_scrape"}
    )
    try:
        pages = []
        _index_batch = []
        for url in urls:
            result = await scraper.scrape(url)
            if result.get("success"):
                data = result["data"]
                pages.append({"url": url, "markdown": data.get("markdown", "")})
                metadata = data.get("metadata") or {}
                og = metadata.get("og") or {}
                meta = metadata.get("meta") or {}
                title = og.get("title") or meta.get("title") or data.get("title", "")
                # Accumulate for batch indexing (ADR-0030) instead of per-page
                _index_batch.append(
                    {
                        "url": url,
                        "title": title,
                        "content": data.get("markdown", "")[:2000],
                    }
                )
        if _index_batch:
            if task_tracker is not None:
                task_tracker.create_background_task(_index_batch_async(_index_batch))
            else:
                asyncio.create_task(_index_batch_async(_index_batch))
        payload = {"completed": len(pages), "total": len(urls), "pages": pages}
        store.complete_job(job_id, payload)
        await deliver_webhook(webhook_config, "completed", job_id, payload)
        elapsed = time.monotonic() - start
        METRICS.histogram(
            "job_duration_seconds", "Job processing duration", ["type", "status"]
        ).observe({"type": "batch_scrape", "status": "completed"}, elapsed)
        METRICS.counter("jobs_completed_total", "Total completed jobs", ["type"]).inc(
            {"type": "batch_scrape"}
        )
    except Exception as e:
        logger.exception("Batch scrape job %s failed", job_id)
        store.fail_job(job_id, str(e))
        await deliver_webhook(webhook_config, "failed", job_id, {"error": str(e)})
        elapsed = time.monotonic() - start
        METRICS.histogram(
            "job_duration_seconds", "Job processing duration", ["type", "status"]
        ).observe({"type": "batch_scrape", "status": "failed"}, elapsed)
        METRICS.counter("jobs_failed_total", "Total failed jobs", ["type"]).inc(
            {"type": "batch_scrape"}
        )
    finally:
        await scraper.close()


async def _process_extract_async(
    job_id: str,
    urls: list[str],
    prompt: str | None,
    schema_: dict[str, Any] | None,
    llm_base_url: str,
    llm_api_key: str,
    llm_model: str,
    scraper_url: str,
    webhook_config: dict[str, Any] | None = None,
) -> None:
    settings = _get_worker_settings()
    store = JobStore(
        f"redis://{settings.valkey_host}:{settings.valkey_port}/{settings.valkey_db}"
    )
    start = time.monotonic()
    METRICS.counter("jobs_submitted_total", "Total jobs submitted", ["type"]).inc(
        {"type": "extract"}
    )
    try:
        result = await run_extract(
            urls=urls,
            prompt=prompt,
            schema=schema_,
            scraper_url=scraper_url,
            llm_base_url=llm_base_url,
            llm_api_key=llm_api_key,
            llm_model=llm_model,
        )
        store.complete_job(job_id, result)
        await deliver_webhook(webhook_config, "completed", job_id, result)
        elapsed = time.monotonic() - start
        METRICS.histogram(
            "job_duration_seconds", "Job processing duration", ["type", "status"]
        ).observe({"type": "extract", "status": "completed"}, elapsed)
        METRICS.counter("jobs_completed_total", "Total completed jobs", ["type"]).inc(
            {"type": "extract"}
        )
    except Exception as e:
        logger.exception("Extract job %s failed", job_id)
        store.fail_job(job_id, str(e))
        await deliver_webhook(webhook_config, "failed", job_id, {"error": str(e)})
        elapsed = time.monotonic() - start
        METRICS.histogram(
            "job_duration_seconds", "Job processing duration", ["type", "status"]
        ).observe({"type": "extract", "status": "failed"}, elapsed)
        METRICS.counter("jobs_failed_total", "Total failed jobs", ["type"]).inc(
            {"type": "extract"}
        )


async def _process_llmstxt_async(
    job_id: str,
    url: str,
    max_pages: int,
    scraper_url: str,
    webhook_config: dict[str, Any] | None = None,
) -> None:
    settings = _get_worker_settings()
    store = JobStore(
        f"redis://{settings.valkey_host}:{settings.valkey_port}/{settings.valkey_db}"
    )
    start = time.monotonic()
    METRICS.counter("jobs_submitted_total", "Total jobs submitted", ["type"]).inc(
        {"type": "llmstxt"}
    )
    try:
        from .llmstxt import generate_llmstxt

        result = await generate_llmstxt(url, max_pages, scraper_url)
        store.complete_job(job_id, result)
        await deliver_webhook(webhook_config, "completed", job_id, result)
        elapsed = time.monotonic() - start
        METRICS.histogram(
            "job_duration_seconds", "Job processing duration", ["type", "status"]
        ).observe({"type": "llmstxt", "status": "completed"}, elapsed)
        METRICS.counter("jobs_completed_total", "Total completed jobs", ["type"]).inc(
            {"type": "llmstxt"}
        )
    except Exception as e:
        logger.exception("LLMs.txt job %s failed", job_id)
        store.fail_job(job_id, str(e))
        await deliver_webhook(webhook_config, "failed", job_id, {"error": str(e)})
        elapsed = time.monotonic() - start
        METRICS.histogram(
            "job_duration_seconds", "Job processing duration", ["type", "status"]
        ).observe({"type": "llmstxt", "status": "failed"}, elapsed)
        METRICS.counter("jobs_failed_total", "Total failed jobs", ["type"]).inc(
            {"type": "llmstxt"}
        )


async def _index_page_async(url: str, title: str, content: str) -> None:
    """Fire-and-forget index a page in the vector index.

    Failure is logged but never propagated — indexing is best-effort.
    """
    try:
        from .semantic_client import SemanticClient

        settings = load_settings()
        semantic_url = settings.semantic_url
        client = SemanticClient(semantic_url)
        await client.index_page(url, title, content)
        await client.close()
        logger.debug("Indexed %s", url)
    except Exception:
        logger.debug("Failed to index %s (vector index unavailable or full)", url)


async def _index_batch_async(pages: list[dict]) -> None:
    """Fire-and-forget batch-index multiple pages.

    Ref: ADR-0030. For large crawls, this is ~200x faster than
    calling _index_page_async() per page.
    """
    if not pages:
        return
    try:
        from .semantic_client import SemanticClient

        settings = load_settings()
        semantic_url = settings.semantic_url
        client = SemanticClient(semantic_url)
        await client.index_batch(pages)
        await client.close()
        logger.debug("Batch-indexed %d pages", len(pages))
    except Exception:
        logger.debug(
            "Failed to batch-index %d pages (vector index unavailable)", len(pages)
        )
