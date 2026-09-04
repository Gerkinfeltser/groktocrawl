"""Regression coverage for request-scoped cross-pass source reuse (#624)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


def _scraper_for(markdown_by_url: dict[str, str | None]) -> MagicMock:
    scraper = MagicMock()
    scraper.base_url = "http://scraper"
    scraper.calls: list[tuple[str, dict | None]] = []

    async def scrape_with_fallback(
        url: str, scrape_options: dict | None = None
    ) -> dict:
        scraper.calls.append((url, scrape_options))
        markdown = markdown_by_url.get(url, f"markdown for {url}")
        if markdown is None:
            return {"success": False, "error": "fixture failure"}
        return {
            "success": True,
            "data": {"markdown": markdown, "source": "fixture"},
        }

    scraper.scrape_with_fallback = AsyncMock(side_effect=scrape_with_fallback)
    return scraper


def test_source_identity_is_conservative():
    from agent.research.sources import normalize_source_url

    assert (
        normalize_source_url("HTTPS://EXAMPLE.COM:443/docs/#section")
        == "https://example.com/docs"
    )
    assert normalize_source_url(
        "https://example.com/docs?a=1&b=2"
    ) != normalize_source_url("https://example.com/docs?b=2&a=1")
    assert normalize_source_url("https://example.com/Docs") != normalize_source_url(
        "https://example.com/docs"
    )


@pytest.mark.asyncio
async def test_registry_reuses_alias_without_duplicate_context():
    from agent.research.discovery import _scrape_urls
    from agent.research.sources import SourceRegistry

    scraper = _scraper_for({})
    registry = SourceRegistry()
    first = await _scrape_urls(
        ["https://example.com/page/"],
        scraper,
        min_sources=1,
        source_registry=registry,
    )
    second = await _scrape_urls(
        ["HTTPS://EXAMPLE.COM:443/page/#part"],
        scraper,
        min_sources=1,
        source_registry=registry,
    )

    assert len(first) == len(second) == 1
    assert len(scraper.calls) == 1
    assert len(registry.artifacts()) == 1
    assert registry.context().count("markdown for") == 1


@pytest.mark.asyncio
async def test_failed_acquisition_is_retryable_and_not_registered():
    from agent.research.discovery import _scrape_urls
    from agent.research.sources import SourceRegistry

    scraper = _scraper_for({"https://retry.example/page": None})
    registry = SourceRegistry()
    failed = await _scrape_urls(
        ["https://retry.example/page"],
        scraper,
        min_sources=1,
        source_registry=registry,
    )

    # Replace the failing fixture with a coroutine so this is a real retry,
    # rather than a cache hit.
    async def recovered(url: str, scrape_options: dict | None = None) -> dict:
        scraper.calls.append((url, scrape_options))
        return {"success": True, "data": {"markdown": "recovered", "source": "fixture"}}

    scraper.scrape_with_fallback.side_effect = recovered
    retried = await _scrape_urls(
        ["https://retry.example/page"],
        scraper,
        min_sources=1,
        source_registry=registry,
    )

    assert failed == []
    assert len(retried) == 1
    assert len(scraper.calls) == 2
    assert registry.artifacts()[0].markdown == "recovered"


@pytest.mark.asyncio
async def test_changed_scrape_options_force_new_acquisition():
    from agent.research.discovery import _scrape_urls
    from agent.research.sources import SourceRegistry

    scraper = _scraper_for({})
    registry = SourceRegistry()
    url = "https://example.com/page"
    await _scrape_urls(
        [url],
        scraper,
        min_sources=1,
        source_registry=registry,
        scrape_options={"formats": ["markdown"]},
    )
    await _scrape_urls(
        [url],
        scraper,
        min_sources=1,
        source_registry=registry,
        scrape_options={"formats": ["markdown", "images"]},
    )

    assert len(scraper.calls) == 2
    assert len(registry.artifacts()) == 1


@pytest.mark.asyncio
async def test_discovery_accounts_novel_and_reused_sources_with_credit_budget():
    from agent.research.discovery import (
        _run_multi_query_discover_and_scrape,
        _scrape_urls,
    )
    from agent.research.sources import SourceRegistry

    searxng = MagicMock()
    searxng.search = AsyncMock(
        return_value=(
            [
                {"url": "HTTPS://EXAMPLE.COM:443/old/#x", "title": "old"},
                {"url": "https://new.example/page", "title": "new"},
            ],
            MagicMock(),
        )
    )
    scraper = _scraper_for({})
    registry = SourceRegistry()
    await _scrape_urls(
        ["https://example.com/old"],
        scraper,
        min_sources=1,
        source_registry=registry,
    )

    result = await _run_multi_query_discover_and_scrape(
        queries=["gap"],
        urls=None,
        searxng=searxng,
        scraper=scraper,
        max_credits=1,
        source_registry=registry,
        pass_number=2,
    )

    assert len(scraper.calls) == 2
    assert result["credits_used"] == 1
    assert result["novel_sources"] == ["https://new.example/page"]
    assert len(result["reused_sources"]) == 1
    assert len(result["source_details"]) == 2
    assert result["context"].count("Source:") == 2
