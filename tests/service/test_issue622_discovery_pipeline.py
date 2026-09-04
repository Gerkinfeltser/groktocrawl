"""Deterministic producer/consumer discovery pipeline coverage (#622)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


def _result(url: str) -> dict:
    return {"url": url, "title": url.rsplit("/", 1)[-1], "description": "fixture"}


def _scraper(started: asyncio.Event, urls: list[str]) -> MagicMock:
    scraper = MagicMock()

    async def scrape(url: str, **_kwargs):
        started.set()
        urls.append(url)
        return {
            "success": True,
            "data": {"markdown": f"content for {url}", "source": "fixture"},
        }

    scraper.scrape_with_fallback = AsyncMock(side_effect=scrape)
    return scraper


@pytest.mark.asyncio
async def test_fast_query_starts_scrape_before_slow_query_finishes(monkeypatch):
    from agent.research import discovery

    slow_finished = asyncio.Event()
    scrape_started = asyncio.Event()
    scraped: list[str] = []
    callback_urls: list[str] = []

    async def search(query: str, **_kwargs):
        if query == "slow":
            await slow_finished.wait()
        return ([_result(f"https://{query}.example/page")], "healthy")

    searxng = MagicMock(search=AsyncMock(side_effect=search))
    scraper = _scraper(scrape_started, scraped)
    original_rank = discovery._filter_and_rank_urls
    monkeypatch.setattr(discovery, "_filter_and_rank_urls", lambda urls, **_: urls)

    async def on_artifact(artifact):
        callback_urls.append(artifact.url)

    task = asyncio.create_task(
        discovery._run_multi_query_discover_and_scrape(
            queries=["fast", "slow"],
            urls=None,
            searxng=searxng,
            scraper=scraper,
            source_registry=discovery.SourceRegistry(),
            on_artifact=on_artifact,
        )
    )
    await asyncio.wait_for(scrape_started.wait(), timeout=1)
    assert not slow_finished.is_set()
    assert scraped == ["https://fast.example/page"]

    slow_finished.set()
    result = await asyncio.wait_for(task, timeout=1)
    assert result["target_urls"] == [
        "https://fast.example/page",
        "https://slow.example/page",
    ]
    assert callback_urls == scraped
    monkeypatch.setattr(discovery, "_filter_and_rank_urls", original_rank)


@pytest.mark.asyncio
async def test_failed_query_does_not_cancel_other_query_acquisition():
    from agent.research.discovery import _run_multi_query_discover_and_scrape

    async def search(query: str, **_kwargs):
        if query == "failed":
            raise RuntimeError("fixture search failure")
        return ([_result("https://healthy.example/page")], "healthy")

    scraped: list[str] = []
    searxng = MagicMock(search=AsyncMock(side_effect=search))
    scraper = _scraper(asyncio.Event(), scraped)
    result = await _run_multi_query_discover_and_scrape(
        queries=["failed", "healthy"],
        urls=None,
        searxng=searxng,
        scraper=scraper,
    )

    assert scraped == ["https://healthy.example/page"]
    assert result["target_urls"] == ["https://healthy.example/page"]


@pytest.mark.asyncio
async def test_discovery_cancellation_awaits_search_and_scrape_tasks():
    from agent.research.discovery import _run_multi_query_discover_and_scrape

    cancelled = asyncio.Event()

    async def search(_query: str, **_kwargs):
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    searxng = MagicMock(search=AsyncMock(side_effect=search))
    scraper = _scraper(asyncio.Event(), [])
    task = asyncio.create_task(
        _run_multi_query_discover_and_scrape(
            queries=["one", "two"], urls=None, searxng=searxng, scraper=scraper
        )
    )
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_loop_forwards_source_event_before_discovery_completes():
    from agent.research.loop import _discover_with_progress
    from agent.research.sources import SourceArtifact

    discovery_finished = asyncio.Event()
    artifact = SourceArtifact(
        url="https://fast.example/page", markdown="fixture", source="fixture"
    )

    async def factory(on_artifact):
        await on_artifact(artifact)
        await asyncio.sleep(0.02)
        discovery_finished.set()
        return {"context": "fixture"}

    seen = []
    async for event in _discover_with_progress(factory):
        seen.append(event)
        if event["type"] == "source_scraped":
            assert not discovery_finished.is_set()

    assert seen[0]["type"] == "source_scraped"
    assert seen[-1]["type"] == "_discovery_complete"
