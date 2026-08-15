"""Regression tests for stage-level latency and capacity telemetry.

Validates metric names, units, bounded label sets, and stage boundaries for
the research pipeline, scrape-cache lookups, and streaming TTFB/TTFT signals
added by issue #528. Uses the global ``common.metrics.METRICS`` singleton and
asserts presence of expected lines in the OpenMetrics output (labels are
always sorted alphabetically by the exporter).
"""

from __future__ import annotations

import pytest

from common.metrics import METRICS


def _metrics_text() -> str:
    return METRICS.generate_openmetrics()


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


# ── Scraper tier/outcome telemetry ────────────────────────────────


@pytest.mark.asyncio
async def test_scrape_tier_metrics_are_bounded(monkeypatch):
    import scraper.app as app

    async def fake_smart_scrape(*_args, **_kwargs):
        return {
            "markdown": "content " * 100,
            "source": "content-negotiation",
            "url": "https://example.test",
        }

    monkeypatch.setattr(app, "smart_scrape", fake_smart_scrape)
    await app.scrape(app.ScrapeRequest(url="https://example.test"))

    text = _metrics_text()
    assert "# TYPE groktocrawl_scrape_tier_total counter" in text
    assert (
        'groktocrawl_scrape_tier_total{outcome="success",tier="content-negotiation"}'
        in text
    )
    assert "# TYPE groktocrawl_scrape_tier_duration_seconds histogram" in text


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


# ── Browser-svc capacity signals ──────────────────────────────────


def test_browser_active_sessions_and_destroyed_reason_metrics():
    import browser_svc.app as bapp

    bapp._sessions.clear()
    bapp._update_active_sessions_gauge()
    bapp._record_session_destroyed("expired")

    text = _metrics_text()
    assert "# TYPE groktocrawl_browser_active_sessions gauge" in text
    assert "groktocrawl_browser_active_sessions " in text
    assert 'groktocrawl_browser_sessions_destroyed_total{reason="expired"}' in text


@pytest.mark.asyncio
async def test_browser_destroy_expired_records_reason(monkeypatch):
    import browser_svc.app as bapp
    from browser_svc.app import SessionData

    bapp._sessions.clear()
    session = SessionData(object(), object(), object(), ttl=300, playwright=object())
    bapp._sessions["sid"] = session

    async def cleanup(*_args, **_kwargs):
        return None

    monkeypatch.setattr(bapp, "_cleanup_resources", cleanup)

    await bapp._destroy_session("sid", reason="expired")

    text = _metrics_text()
    assert 'groktocrawl_browser_sessions_destroyed_total{reason="expired"}' in text
    assert "browser_sessions_expired_total " in text


@pytest.mark.asyncio
async def test_browser_execute_expired_records_reason(monkeypatch):
    import browser_svc.app as bapp
    from browser_svc.app import BrowserExecuteRequest, SessionData

    bapp._sessions.clear()
    session = SessionData(object(), object(), object(), ttl=-1, playwright=object())
    bapp._sessions["sid"] = session

    destroyed: list[tuple[str, str]] = []

    async def fake_destroy(sid, reason="deleted"):
        destroyed.append((sid, reason))

    monkeypatch.setattr(bapp, "_destroy_session", fake_destroy)

    with pytest.raises(bapp.HTTPException, match="Session expired"):
        await bapp.execute_action(
            "sid", BrowserExecuteRequest(action="navigate", url="https://example.test")
        )
    assert destroyed == [("sid", "expired")]


@pytest.mark.asyncio
async def test_browser_list_expired_records_reason(monkeypatch):
    import browser_svc.app as bapp
    from browser_svc.app import SessionData

    bapp._sessions.clear()
    session = SessionData(object(), object(), object(), ttl=-1, playwright=object())
    bapp._sessions["sid"] = session

    destroyed: list[tuple[str, str]] = []

    async def fake_destroy(sid, reason="deleted"):
        destroyed.append((sid, reason))

    monkeypatch.setattr(bapp, "_destroy_session", fake_destroy)

    result = await bapp.list_browsers()
    assert destroyed == [("sid", "expired")]
    assert result.success is True


@pytest.mark.asyncio
async def test_browser_create_success_records_active_sessions(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    import browser_svc.app as bapp
    from browser_svc.app import BrowserCreateRequest

    bapp._sessions.clear()

    page = MagicMock()
    page.add_init_script = AsyncMock()
    context = MagicMock()
    context.new_page = AsyncMock(return_value=page)
    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    controller = MagicMock()
    controller.chromium.launch = AsyncMock(return_value=browser)
    factory = MagicMock()
    factory.start = AsyncMock(return_value=controller)
    monkeypatch.setattr(bapp, "async_playwright", MagicMock(return_value=factory))

    await bapp.create_browser(BrowserCreateRequest())

    assert len(bapp._sessions) == 1
    text = _metrics_text()
    assert "groktocrawl_browser_active_sessions 1.0" in text
    assert "browser_sessions_created_total " in text


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
