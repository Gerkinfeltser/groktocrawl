"""POST /v2/agent ``max_credits`` must bound the research loop.

Regression tests for the accepted-but-ignored ``max_credits`` parameter
found during mission validation of issues #587/#588/#589: the request
model accepted it and echoed it into the job payload, but nothing in
the worker or research code consumed it, so a job could scrape an
unbounded number of sources regardless of the requested budget.

Semantics (1 credit ≈ one successfully scraped source page, matching
the crawl engine's per-page credit accounting): when ``max_credits``
is set, discovery stops admitting new scrapes once the credit count is
reached. The default (None) keeps today's unbounded behavior.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_scraper(markdown: str = "content") -> MagicMock:
    scraper = MagicMock()
    scraper.base_url = "http://scraper"

    async def _scrape(url: str, **kwargs) -> dict:
        return {"success": True, "data": {"markdown": markdown, "source": "test"}}

    scraper.scrape_with_fallback = AsyncMock(side_effect=_scrape)
    scraper.scrape = AsyncMock(side_effect=_scrape)
    scraper.close = AsyncMock()
    return scraper


class TestRunResearchMaxCredits:
    """run_research honors max_credits as a scrape-count budget."""

    @pytest.mark.asyncio
    async def test_max_credits_bounds_scraped_sources(self):
        """A 2-credit budget stops discovery at 2 scraped sources."""
        from agent.research.loop import run_research

        searxng = MagicMock()

        async def _search(query: str, **kwargs):
            results = [
                {"url": f"https://s{i}.com", "title": f"S{i}", "description": "d"}
                for i in range(10)
            ]
            return results, MagicMock()

        searxng.search = AsyncMock(side_effect=_search)
        searxng.close = AsyncMock()

        llm = MagicMock()
        llm.generate = AsyncMock(return_value="answer [1]")
        llm.close = AsyncMock()

        scraper = _make_scraper()

        with (
            patch("agent.research.loop.SearXNGClient", return_value=searxng),
            patch("agent.research.loop.ScraperClient", return_value=scraper),
            patch("agent.research.loop.LLMClient", return_value=llm),
        ):
            result = await run_research(
                prompt="question",
                llm_model="m",
                max_searches_per_request=1,
                max_credits=2,
            )

        assert result["result"] == "answer [1]"
        # Budget honored: exactly 2 pages scraped even though 10 candidates
        # were discovered.
        assert len(result["source_details"]) == 2

    @pytest.mark.asyncio
    async def test_default_unbounded_keeps_full_discovery(self):
        """Without max_credits the pipeline scrapes as before."""
        from agent.research.loop import run_research

        searxng = MagicMock()

        async def _search(query: str, **kwargs):
            results = [
                {"url": f"https://s{i}.com", "title": f"S{i}", "description": "d"}
                for i in range(6)
            ]
            return results, MagicMock()

        searxng.search = AsyncMock(side_effect=_search)
        searxng.close = AsyncMock()

        llm = MagicMock()
        llm.generate = AsyncMock(return_value="answer [1]")
        llm.close = AsyncMock()

        scraper = _make_scraper()

        with (
            patch("agent.research.loop.SearXNGClient", return_value=searxng),
            patch("agent.research.loop.ScraperClient", return_value=scraper),
            patch("agent.research.loop.LLMClient", return_value=llm),
        ):
            result = await run_research(
                prompt="question",
                llm_model="m",
                max_searches_per_request=1,
            )

        assert result["result"] == "answer [1]"
        # Unchanged default behavior: discovery fills its min_sources quota
        # (plus speculative in-flight scrapes), never fewer.
        assert len(result["source_details"]) == 3
        assert len(scraper.scrape_with_fallback.call_args_list) >= 3


class TestAgentWorkerMaxCreditsWiring:
    """The agent route/worker must thread max_credits to run_research."""

    @pytest.mark.asyncio
    async def test_route_passes_max_credits_to_worker(self):
        """POST /v2/agent forwards body.max_credits into the background job."""
        from unittest.mock import MagicMock

        from agent.models import AgentRequest
        from agent.routes.agent import create_agent

        request = MagicMock()
        rate_limiter = MagicMock()
        rate_limiter.limit = 100
        rate_limiter.window = 60
        rate_limiter.check = AsyncMock(return_value=(True, 100))
        state = MagicMock()
        state.rate_limiter = rate_limiter
        state.max_searches_per_request = 5
        state.research_memory = MagicMock()
        state.research_memory.query = AsyncMock(return_value={"hit": False})
        state.job_store = MagicMock()
        state.job_store.create_job.return_value = "job-credits"
        state.task_tracker = MagicMock()
        request.app.state = state
        request.headers = MagicMock()
        request.headers.get.return_value = None
        request.client = MagicMock()
        request.client.host = "127.0.0.1"

        body = AgentRequest(prompt="hello", stream=False, max_credits=7)
        response = MagicMock()
        response.headers = {}

        with (
            patch(
                "agent.routes.agent._lookup_agent_cache",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "agent.routes.agent._handle_agent_streaming",
                new=AsyncMock(return_value=None),
            ),
            patch("agent.worker._process_agent_async") as process,
        ):
            await create_agent(request, body, response)

        assert process.call_args.kwargs["max_credits"] == 7

    @pytest.mark.asyncio
    async def test_worker_passes_max_credits_to_run_research(self):
        """_process_agent_async forwards max_credits into run_research."""
        from agent.worker import _process_agent_async

        mock_store = MagicMock()
        mock_run_research = AsyncMock(
            return_value={"result": "ok", "sources": [], "source_details": []}
        )
        mock_research_memory = MagicMock()
        mock_research_memory.query = AsyncMock(return_value={"hit": False})
        mock_research_memory.store = AsyncMock(return_value="mem-1")
        mock_metrics = MagicMock()
        mock_metrics.counter.return_value.inc = MagicMock()
        mock_metrics.histogram.return_value.observe = MagicMock()

        with (
            patch("agent.worker.JobStore", return_value=mock_store),
            patch("agent.worker.run_research", mock_run_research),
            patch("agent.worker.deliver_webhook", AsyncMock()),
            patch("agent.worker.METRICS", mock_metrics),
            patch(
                "agent.worker.load_settings",
                return_value=MagicMock(
                    valkey_host="valkey",
                    valkey_port=6379,
                    valkey_db=0,
                    crawl_max_duration_seconds=1800,
                    crawl_idle_timeout_seconds=300,
                ),
            ),
        ):
            await _process_agent_async(
                job_id="job-credits",
                prompt="p",
                urls=None,
                schema_=None,
                llm_base_url="http://llm:8000",
                llm_api_key="k",
                llm_model="m",
                searxng_url="http://searxng",
                scraper_url="http://scraper",
                max_credits=4,
            )

        assert mock_run_research.call_args.kwargs["max_credits"] == 4
