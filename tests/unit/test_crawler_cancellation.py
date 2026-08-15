"""Focused tests for CrawlEngine cancellation teardown (ADR-0051)."""

import asyncio
from unittest.mock import MagicMock

import pytest


@pytest.mark.asyncio
async def test_cancel_and_await_tasks_awaits_pending_tasks():
    from agent.crawler import CrawlEngine, CrawlOptions

    engine = CrawlEngine(MagicMock(), options=CrawlOptions(max_pages=10))

    started = asyncio.Event()

    async def _pending_work() -> None:
        started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            raise

    task = asyncio.create_task(_pending_work())
    await started.wait()
    engine._pending_tasks.add(task)

    await engine._cancel_and_await_tasks()

    assert task.done()  # awaited, not left pending
    assert not engine._pending_tasks


@pytest.mark.asyncio
async def test_run_finally_awaits_children_on_forced_cancel():
    from agent.crawler import CrawlEngine, CrawlOptions

    scraper = MagicMock()
    scraper.scrape = MagicMock(return_value=None)

    engine = CrawlEngine(scraper, options=CrawlOptions(max_pages=1, max_depth=0))

    async def _scrape(*args, **kwargs):
        return {"success": True, "data": {"markdown": "# x", "metadata": {}}}

    scraper.scrape.side_effect = _scrape

    # Cancel the engine mid-run via a task to exercise the finally teardown.
    task = asyncio.create_task(engine.run("http://example.com/"))

    # Let the crawl dispatch the start URL, then force-cancel the owning task.
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # The engine must have cleaned up its internal HTML client and tasks.
    assert engine._html_client is None
    assert not engine._pending_tasks
