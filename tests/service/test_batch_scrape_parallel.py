"""Tests for parallel batch scrape scheduling (ADR-0051)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


async def _run_batch(
    urls: list[str],
    scrape_side_effect,
    *,
    max_concurrency: int = 3,
    job_id: str = "batch-parallel",
):
    from agent.worker import _process_batch_scrape_async

    mock_store = MagicMock()
    mock_store.get_job.return_value = {"status": "processing"}
    mock_store.get_completed.return_value = len(urls)
    mock_scraper = MagicMock()
    mock_scraper.scrape = AsyncMock(side_effect=scrape_side_effect)
    mock_scraper.close = AsyncMock()
    mock_deliver_webhook = AsyncMock()
    mock_metrics = MagicMock()
    mock_metrics.counter.return_value.inc = MagicMock()
    mock_metrics.histogram.return_value.observe = MagicMock()

    with (
        patch("agent.worker.JobStore", return_value=mock_store),
        patch("agent.worker.ScraperClient", return_value=mock_scraper),
        patch("agent.worker.deliver_webhook", mock_deliver_webhook),
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
        patch("agent.worker._index_batch_async", AsyncMock()),
    ):
        await _process_batch_scrape_async(
            job_id=job_id,
            urls=urls,
            scraper_url="http://scraper:8001",
            max_concurrency=max_concurrency,
        )

    return mock_store, mock_scraper


def _success(url: str, title: str = "T") -> dict:
    return {
        "success": True,
        "data": {"markdown": f"# {url}", "metadata": {"og": {"title": title}}},
    }


@pytest.mark.asyncio
async def test_pages_are_order_preserving_under_parallelism():
    """Results are index-keyed so pages stay in input URL order."""
    urls = [f"https://x.com/{i}" for i in range(4)]

    async def _scrape(url: str, **kwargs) -> dict:
        # Reverse-completion: later URLs finish first.
        await asyncio.sleep(0.04 - (int(url.rsplit("/", 1)[1]) * 0.01))
        return _success(url)

    store, _scraper = await _run_batch(urls, _scrape, max_concurrency=4)

    payload = store.complete_job.call_args[0][1]
    assert [p["url"] for p in payload["pages"]] == urls


@pytest.mark.asyncio
async def test_concurrency_is_bounded_by_max_concurrency():
    """Scheduling is bounded by min(max_concurrency, global fetch budget)."""
    urls = [f"https://x.com/{i}" for i in range(8)]
    active = 0
    peak = 0

    async def _scrape(url: str, **kwargs) -> dict:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return _success(url)

    _store, _scraper = await _run_batch(urls, _scrape, max_concurrency=2)
    assert peak == 2


@pytest.mark.asyncio
async def test_errors_are_order_preserving():
    """Error entries also follow input order under parallelism."""
    urls = ["https://x.com/a", "https://x.com/b", "https://x.com/c"]

    async def _scrape(url: str, **kwargs) -> dict:
        if url.endswith("/b"):
            raise ConnectionError("boom")
        await asyncio.sleep(0.01)
        return _success(url)

    store, _scraper = await _run_batch(urls, _scrape, max_concurrency=3)

    payload = store.complete_job.call_args[0][1]
    assert [p["url"] for p in payload["pages"]] == [
        "https://x.com/a",
        "https://x.com/c",
    ]
    assert [e["url"] for e in payload["errors"]] == ["https://x.com/b"]
    assert "boom" in payload["errors"][0]["error"]


@pytest.mark.asyncio
async def test_partial_results_still_complete_job():
    """A batch with failures still calls complete_job (not fail_job)."""
    urls = ["https://x.com/a", "https://x.com/b"]

    async def _scrape(url: str, **kwargs) -> dict:
        if url.endswith("/b"):
            raise ConnectionError("boom")
        return _success(url)

    store, _scraper = await _run_batch(urls, _scrape, max_concurrency=2)

    store.complete_job.assert_called_once()
    store.fail_job.assert_not_called()
    payload = store.complete_job.call_args[0][1]
    assert len(payload["pages"]) == 1
    assert len(payload["errors"]) == 1


@pytest.mark.asyncio
async def test_large_batch_creates_bounded_tasks_not_per_url():
    """A large batch creates a bounded worker pool, not one task per URL."""
    urls = [f"https://x.com/{i}" for i in range(40)]
    max_concurrency = 3

    async def _scrape(url: str, **kwargs) -> dict:
        raise ConnectionError("boom")

    created = 0
    real_create_task = asyncio.create_task

    def _spy(coro, **kwargs):
        nonlocal created
        created += 1
        return real_create_task(coro, **kwargs)

    with patch("asyncio.create_task", side_effect=_spy):
        store, _scraper = await _run_batch(
            urls, _scrape, max_concurrency=max_concurrency
        )

    # 3 workers (and no background index task, since every scrape errored).
    assert created == max_concurrency

    # Every URL is still processed through the bounded workers.
    payload = store.complete_job.call_args[0][1]
    assert payload["total"] == len(urls)
    assert len(payload["errors"]) == len(urls)


@pytest.mark.asyncio
async def test_store_status_check_is_bounded_not_up_front_burst():
    """Per-URL store checks run inside bounded workers, not as an up-front burst."""
    from agent.worker import _process_batch_scrape_async

    urls = [f"https://x.com/{i}" for i in range(20)]
    max_concurrency = 3

    get_job_calls = 0
    scrape_started = asyncio.Event()
    release = asyncio.Event()

    def _count_get_job(_job_id: str) -> dict:
        nonlocal get_job_calls
        get_job_calls += 1
        return {"status": "processing"}

    mock_store = MagicMock()
    mock_store.get_job = MagicMock(side_effect=_count_get_job)
    mock_store.get_completed.return_value = len(urls)

    mock_scraper = MagicMock()

    async def _scrape(url: str, **kwargs) -> dict:
        scrape_started.set()
        await release.wait()
        return _success(url)

    mock_scraper.scrape = AsyncMock(side_effect=_scrape)
    mock_scraper.close = AsyncMock()
    mock_deliver_webhook = AsyncMock()
    mock_metrics = MagicMock()
    mock_metrics.counter.return_value.inc = MagicMock()
    mock_metrics.histogram.return_value.observe = MagicMock()

    with (
        patch("agent.worker.JobStore", return_value=mock_store),
        patch("agent.worker.ScraperClient", return_value=mock_scraper),
        patch("agent.worker.deliver_webhook", mock_deliver_webhook),
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
        patch("agent.worker._index_batch_async", AsyncMock()),
    ):
        task = asyncio.create_task(
            _process_batch_scrape_async(
                job_id="batch-burst",
                urls=urls,
                scraper_url="http://scraper:8001",
                max_concurrency=max_concurrency,
            )
        )
        await asyncio.wait_for(scrape_started.wait(), timeout=1.0)

        # At most the up-front check plus one check per running worker — never
        # one synchronous get_job per URL before the concurrency limit applies.
        assert get_job_calls <= max_concurrency + 1

        release.set()
        await task

    # Every URL still received its per-URL cancellation/status check.
    assert mock_store.get_job.call_count == len(urls) + 1
