"""POST /v2/crawl ``limit`` must bound the crawl (Firecrawl parity).

Regression tests for the accepted-but-ignored ``limit`` parameter found
during mission validation of issues #587/#588/#589: a live
``{"limit": 1}`` crawl processed 236 pages because the engine only
consumes ``max_pages`` and ``max_pages`` defaults to 0 (= unlimited),
so ``min(max_pages, limit)`` collapsed to 0 and ``limit`` bounded
nothing. ``limit`` now feeds a shared resolver that also honors the
LLM-derived page cap from NL→params prompts.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestResolveEffectiveMaxPages:
    """Unit contract for routes.crawl._resolve_effective_max_pages."""

    def test_limit_only_bounds_the_crawl(self):
        from agent.routes.crawl import _resolve_effective_max_pages

        assert _resolve_effective_max_pages(0, 1) == 1

    def test_limit_only_zero_stays_unlimited(self):
        from agent.routes.crawl import _resolve_effective_max_pages

        assert _resolve_effective_max_pages(0, 0) == 0

    def test_limit_only_none_keeps_max_pages(self):
        from agent.routes.crawl import _resolve_effective_max_pages

        assert _resolve_effective_max_pages(7, None) == 7

    def test_both_set_stricter_wins(self):
        from agent.routes.crawl import _resolve_effective_max_pages

        assert _resolve_effective_max_pages(50, 5) == 5
        assert _resolve_effective_max_pages(3, 9) == 3

    def test_non_positive_limit_is_ignored(self):
        from agent.routes.crawl import _resolve_effective_max_pages

        assert _resolve_effective_max_pages(4, -2) == 4


def _crawl_route_request_mock() -> MagicMock:
    request = MagicMock()
    rate_limiter = MagicMock()
    rate_limiter.limit = 100
    rate_limiter.window = 60
    rate_limiter.check = AsyncMock(return_value=(True, 100))
    rate_limiter.retry_after_seconds.return_value = 30
    rate_limiter.reset_at_iso.return_value = "1970-01-01T00:00:00Z"

    state = MagicMock()
    state.rate_limiter = rate_limiter
    state.job_store = MagicMock()
    state.job_store.create_job.return_value = "crawl-job-1"
    state.task_tracker = MagicMock()
    state.task_tracker.create_background_task = MagicMock()
    state.scraper_url = "http://scraper:8001"
    state.llm_base_url = "http://llm:8000"
    state.llm_api_key = "key"
    state.llm_model = "test-model"

    request.app.state = state
    request.headers = MagicMock()
    request.headers.get.return_value = None
    request.client = MagicMock()
    request.client.host = "127.0.0.1"
    return request


class TestCreateCrawlLimitWiring:
    """The route must pass the limit-bounded cap to the crawl engine."""

    @pytest.mark.asyncio
    async def test_limit_only_request_bounds_engine_pages(self):
        """{"url": ..., "limit": 1} reaches the engine as max_pages=1."""
        from agent.models import CrawlRequest
        from agent.routes.crawl import create_crawl

        request = _crawl_route_request_mock()
        body = CrawlRequest(url="https://example.com", limit=1)
        response = MagicMock()
        response.headers = {}

        with patch("agent.worker._process_crawl_async") as process:
            await create_crawl(request, body, response)

        kwargs = process.call_args.kwargs
        assert kwargs["job_id"] == "crawl-job-1"
        assert kwargs["max_pages"] == 1

    @pytest.mark.asyncio
    async def test_default_unlimited_request_stays_unbounded(self):
        """No limit/max_pages keeps today's unlimited default (0)."""
        from agent.models import CrawlRequest
        from agent.routes.crawl import create_crawl

        request = _crawl_route_request_mock()
        body = CrawlRequest(url="https://example.com")
        response = MagicMock()
        response.headers = {}

        with patch("agent.worker._process_crawl_async") as process:
            await create_crawl(request, body, response)

        assert process.call_args.kwargs["max_pages"] == 0

    @pytest.mark.asyncio
    async def test_explicit_max_pages_beats_looser_limit(self):
        """Stricter-wins semantics are preserved when both are set."""
        from agent.models import CrawlRequest
        from agent.routes.crawl import create_crawl

        request = _crawl_route_request_mock()
        body = CrawlRequest(url="https://example.com", max_pages=50, limit=5)
        response = MagicMock()
        response.headers = {}

        with patch("agent.worker._process_crawl_async") as process:
            await create_crawl(request, body, response)

        assert process.call_args.kwargs["max_pages"] == 5

    @pytest.mark.asyncio
    async def test_job_payload_preserves_original_fields(self):
        """The stored payload echoes the raw request (audit surface)."""
        from agent.models import CrawlRequest
        from agent.routes.crawl import create_crawl

        request = _crawl_route_request_mock()
        body = CrawlRequest(url="https://example.com", limit=1)
        response = MagicMock()
        response.headers = {}

        store = request.app.state.job_store
        with patch("agent.worker._process_crawl_async"):
            await create_crawl(request, body, response)

        payload = store.create_job.call_args.kwargs["payload"]
        assert payload["url"] == "https://example.com"
        assert payload["limit"] == 1
