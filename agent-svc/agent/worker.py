"""Worker entrypoint and processing functions for GroktoCrawl jobs."""

import asyncio
import logging
import os
from typing import Any

from .research import run_research, run_extract
from .scraper_client import ScraperClient
from .store import JobStore

logger = logging.getLogger(__name__)


def get_env(name: str, default: str) -> str:
    return os.getenv(name, default)


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
) -> None:
    store = JobStore(get_env("VALKEY_URL", "redis://valkey:6379/0"))
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
        )
        store.complete_job(job_id, result)
    except Exception as e:
        logger.exception("Agent job %s failed", job_id)
        store.fail_job(job_id, str(e))


async def _process_crawl_async(
    job_id: str,
    url: str,
    max_pages: int,
    max_depth: int,
    scraper_url: str,
) -> None:
    store = JobStore(get_env("VALKEY_URL", "redis://valkey:6379/0"))
    scraper = ScraperClient(scraper_url)
    try:
        result = await scraper.scrape(url)
        pages = []
        if result.get("success"):
            pages.append({"url": url, "markdown": result["data"].get("markdown", "")})
        store.complete_job(job_id, {"completed": len(pages), "total": 1, "pages": pages})
    except Exception as e:
        logger.exception("Crawl job %s failed", job_id)
        store.fail_job(job_id, str(e))
    finally:
        await scraper.close()


async def _process_batch_scrape_async(job_id: str, urls: list[str], scraper_url: str) -> None:
    store = JobStore(get_env("VALKEY_URL", "redis://valkey:6379/0"))
    scraper = ScraperClient(scraper_url)
    try:
        pages = []
        for url in urls:
            result = await scraper.scrape(url)
            if result.get("success"):
                pages.append({"url": url, "markdown": result["data"].get("markdown", "")})
        store.complete_job(job_id, {"completed": len(pages), "total": len(urls), "pages": pages})
    except Exception as e:
        logger.exception("Batch scrape job %s failed", job_id)
        store.fail_job(job_id, str(e))
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
) -> None:
    store = JobStore(get_env("VALKEY_URL", "redis://valkey:6379/0"))
    try:
        result = await run_extract(
            urls=urls, prompt=prompt, schema=schema_,
            scraper_url=scraper_url, llm_base_url=llm_base_url,
            llm_api_key=llm_api_key, llm_model=llm_model,
        )
        store.complete_job(job_id, result)
    except Exception as e:
        logger.exception("Extract job %s failed", job_id)
        store.fail_job(job_id, str(e))


def process_agent_job(
    job_id: str,
    prompt: str,
    urls: list[str] | None = None,
    schema_: dict[str, Any] | None = None,
    llm_base_url: str = "https://api.openai.com/v1",
    llm_api_key: str = "",
    llm_model: str = "gpt-4o-mini",
    searxng_url: str = "http://searxng:8080",
    scraper_url: str = "http://scraper-svc:8001",
) -> None:
    asyncio.run(_process_agent_async(job_id, prompt, urls, schema_, llm_base_url, llm_api_key, llm_model, searxng_url, scraper_url))


def process_crawl_job(
    job_id: str,
    url: str,
    max_pages: int = 10,
    max_depth: int = 2,
    scraper_url: str = "http://scraper-svc:8001",
) -> None:
    asyncio.run(_process_crawl_async(job_id, url, max_pages, max_depth, scraper_url))


def process_batch_scrape(
    job_id: str,
    urls: list[str],
    scraper_url: str = "http://scraper-svc:8001",
) -> None:
    asyncio.run(_process_batch_scrape_async(job_id, urls, scraper_url))


if __name__ == "__main__":
    print("GroktoCrawl worker starting...")
