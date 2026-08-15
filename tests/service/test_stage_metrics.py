"""Regression tests for stage-level latency and capacity telemetry.

Validates metric names, units, bounded label sets, and stage boundaries for
the research pipeline, scrape-cache lookups, and streaming TTFB/TTFT signals
added by issue #528. Uses the global ``common.metrics.METRICS`` singleton and
asserts presence of expected lines in the OpenMetrics output (labels are
always sorted alphabetically by the exporter).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from common.metrics import METRICS


def _metrics_text() -> str:
    return METRICS.generate_openmetrics()


def _hist_count(stream_type: str) -> float:
    """Return the observed ``_count`` for the TTFB histogram of *stream_type*."""
    text = _metrics_text()
    marker = (
        f'groktocrawl_time_to_first_event_seconds_count{{stream_type="{stream_type}"}}'
    )
    if marker not in text:
        return 0.0
    tail = text[text.index(marker) + len(marker) :].lstrip()
    return float(tail.split()[0])


# ── LLM stage telemetry ───────────────────────────────────────────


class _FakeLLMResp:
    status_code = 200

    def json(self):
        return {"choices": [{"message": {"content": "ok"}}]}


class _FakeLLMClient:
    async def post(self, *_args, **_kwargs):
        return _FakeLLMResp()

    async def aclose(self):
        return None


@pytest.mark.asyncio
async def test_llm_call_metrics_are_bounded_by_stage(monkeypatch):
    from agent.llm import LLMClient

    client = LLMClient("http://llm.test", "", "model")
    monkeypatch.setattr(client, "_client", _FakeLLMClient())

    await client.generate("system", "user", stage="synthesis")
    await client.close()

    text = _metrics_text()
    assert "# TYPE groktocrawl_llm_calls_total counter" in text
    assert 'groktocrawl_llm_calls_total{outcome="success",stage="synthesis"}' in text
    assert "# TYPE groktocrawl_llm_call_seconds histogram" in text
    assert 'groktocrawl_llm_call_seconds_count{stage="synthesis"}' in text


# ── Search query telemetry ────────────────────────────────────────


class _FakeSearchResp:
    status_code = 200

    def json(self):
        return {"results": [], "engines": []}


class _FakeSearchClient:
    async def get(self, *_args, **_kwargs):
        return _FakeSearchResp()

    async def aclose(self):
        return None


@pytest.mark.asyncio
async def test_search_query_metrics_are_bounded_by_engine(monkeypatch):
    from agent.searxng_client import SearXNGClient

    searxng = SearXNGClient("http://searxng.test")
    monkeypatch.setattr(searxng, "_client", _FakeSearchClient())

    await searxng.search("test query")
    await searxng.close()

    text = _metrics_text()
    assert (
        'groktocrawl_search_queries_total{engine="searxng",outcome="success"}' in text
    )
    assert "# TYPE groktocrawl_search_query_seconds histogram" in text


# ── Research memory lookup outcomes ───────────────────────────────


@pytest.mark.asyncio
async def test_research_memory_lookup_records_error_outcome(monkeypatch):
    from agent.research_memory import ResearchMemory

    memory = ResearchMemory(
        redis_url="redis://localhost:6379/0", semantic_url="http://semantic.test"
    )

    async def raise_embed(_text: str) -> list[float]:
        raise RuntimeError("semantic unavailable")

    monkeypatch.setattr(memory, "_embed", raise_embed)

    result = await memory.query(prompt="test prompt")
    await memory.close()

    assert result == {"hit": False}
    text = _metrics_text()
    assert "# TYPE groktocrawl_research_memory_lookup_total counter" in text
    assert 'groktocrawl_research_memory_lookup_total{outcome="error"}' in text
    assert "# TYPE groktocrawl_research_memory_lookup_seconds histogram" in text


# ── Crawl scrape-cache lookup outcomes ────────────────────────────


def test_crawl_cache_bypass_records_miss_outcome():
    from agent.crawl_cache import CrawlCache

    cache = CrawlCache("redis://localhost:6379/0")
    use_cached, data, error = cache.check_cache(
        "https://example.test", max_age_ms=None, min_age_ms=None
    )

    assert (use_cached, data, error) == (False, None, None)
    text = _metrics_text()
    assert "# TYPE groktocrawl_scrape_cache_lookup_total counter" in text
    assert 'groktocrawl_scrape_cache_lookup_total{outcome="miss"}' in text


# ── Streaming TTFB / TTFT ─────────────────────────────────────────


def test_stream_timing_records_ttfb_and_ttft():
    from common.stage_metrics import StreamTiming

    timing = StreamTiming("agent")
    timing.on_first_event()
    timing.on_first_token()
    timing.on_first_event()  # idempotent
    timing.on_first_token()  # idempotent

    text = _metrics_text()
    assert "# TYPE groktocrawl_time_to_first_event_seconds histogram" in text
    assert 'groktocrawl_time_to_first_event_seconds_count{stream_type="agent"}' in text
    assert "# TYPE groktocrawl_time_to_first_token_seconds histogram" in text
    assert 'groktocrawl_time_to_first_token_seconds_count{stream_type="agent"}' in text


# ── Adapter dispatch telemetry ────────────────────────────────────


@pytest.mark.asyncio
async def test_adapter_dispatch_metrics_use_group_not_url():
    import re

    from scraper.adapters.base import AdapterRegistry, AdapterResult

    class FakeAdapter:
        name = "fake"
        priority = 100
        patterns = [re.compile(r"^https?://example\.test/")]

        async def can_handle(self, url: str) -> bool:
            return True

        async def scrape(self, url: str, ctx):
            return AdapterResult(success=True, markdown="ok", source="fake", url=url)

    registry = AdapterRegistry()
    registry.register(FakeAdapter())

    result = await registry.dispatch("https://example.test/page", object())
    assert result is not None

    text = _metrics_text()
    assert (
        'groktocrawl_adapter_dispatch_total{adapter_group="fake",outcome="hit"}' in text
    )


# ── Bounded-label guard: no raw URLs as labels ────────────────────


def test_stage_metrics_never_use_raw_urls_as_label_values():
    # Confirm the exporter renders only the bounded enum-like label values
    # passed to the collector, never raw URLs or free-form content.
    from common.metrics import MetricsCollector

    collector = MetricsCollector()
    collector.histogram(
        "groktocrawl_research_plan_seconds", "plan latency", []
    ).observe({}, 0.1)
    collector.counter(
        "groktocrawl_llm_calls_total",
        "llm calls",
        ["stage", "outcome"],
    ).inc({"stage": "plan", "outcome": "success"})
    collector.gauge("groktocrawl_active_jobs", "active jobs", ["type"]).set(
        {"type": "agent"}, 1.0
    )

    text = collector.generate_openmetrics()
    assert "https://" not in text
    assert "example.test" not in text
    assert 'groktocrawl_llm_calls_total{outcome="success",stage="plan"}' in text


# ── TTFB timing boundaries (crawl / agent streams) ────────────────


@pytest.mark.asyncio
async def test_crawl_stream_ttfb_fires_on_first_page_event(monkeypatch):
    import agent.crawl_stream as cs
    from agent.crawler import CrawlResult

    push_gate = asyncio.Event()

    class FakeEngine:
        def __init__(self, scraper, store=None, options=None):
            self._scraped_count = 0
            self._queue: list = []

        async def run(self, url, job_id=None, page_callback=None, error_callback=None):
            await push_gate.wait()
            await page_callback(
                job_id, {"url": url, "markdown": "# hi", "metadata": {}}
            )
            return CrawlResult(pages=[], total=1, completed=1)

        async def close(self):
            return None

    class FakeScraper:
        async def close(self):
            return None

    monkeypatch.setattr(cs, "CrawlEngine", FakeEngine)
    monkeypatch.setattr(cs, "ScraperClient", lambda url: FakeScraper())
    monkeypatch.setattr(cs, "deliver_webhook", AsyncMock())

    store = MagicMock()
    store.get_job.return_value = None

    gen = cs.crawl_event_stream(
        job_id="j",
        url="https://example.test",
        max_pages=1,
        max_depth=1,
        scraper_url="http://scraper.test",
        store=store,
    )

    before = _hist_count("crawl")
    task = asyncio.create_task(gen.__anext__())
    await asyncio.sleep(0)

    # While the engine is still waiting to push its first page, TTFB must not
    # have fired yet (the old loop-entry instrumentation recorded it here).
    assert _hist_count("crawl") == before

    push_gate.set()
    first = await task
    assert '"type": "page"' in first
    assert _hist_count("crawl") == before + 1

    await gen.aclose()


@pytest.mark.asyncio
async def test_agent_stream_ttfb_ignores_planning_sentinels(monkeypatch):
    import agent.research.streaming as streaming
    from agent.models import CitationStyle

    async def _sentinel_then_done(*_args, **_kwargs):
        yield {"type": "status", "state": "planning"}
        yield {
            "type": "research_plan",
            "strategy": "deep",
            "queries": ["q"],
            "reasoning": "",
        }
        yield {
            "type": "done",
            "result": "ok",
            "sources": [],
            "source_details": [],
            "latency_ms": 1,
        }

    monkeypatch.setattr(streaming, "run_research_stream", _sentinel_then_done)

    before = _hist_count("agent")
    chunks = [
        chunk
        async for chunk in streaming.stream_research_live(
            prompt="q",
            urls=None,
            schema=None,
            searxng_url="http://s",
            scraper_url="http://sc",
            llm_base_url="http://llm",
            llm_api_key="k",
            llm_model="m",
            requested_model=None,
            max_searches_per_request=5,
            include_images=False,
            citation_style=CitationStyle.inline,
        )
    ]
    after = _hist_count("agent")

    assert chunks[-1] == "data: [DONE]\n\n"
    assert after == before + 1
