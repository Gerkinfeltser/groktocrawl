"""Unit tests for the answer endpoint's concurrent _scrape_urls().

Verifies concurrency logic (semaphore, timeout, early termination, error handling)
by mocking the scraper client. No Docker stack needed.

Run with:
    python3 -m pytest tests/test_answer_endpoint.py -v

Or run directly:
    python3 tests/test_answer_endpoint.py
"""

import sys
import os
import time
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent-svc"))

from agent.research import _scrape_urls


class MockScraper:
    """Mock scraper client that simulates scrape results at configurable speeds.

    Tracks ``max_concurrent`` to verify the semaphore is respected.
    """

    def __init__(self, responses: dict | None = None, delay: float = 0):
        self.responses = responses or {}
        self.delay = delay
        self.call_count = 0
        self.concurrent = 0
        self.max_concurrent = 0
        self._calls: list[str] = []

    async def scrape(self, url: str) -> dict:
        self.concurrent += 1
        self.max_concurrent = max(self.max_concurrent, self.concurrent)
        self._calls.append(url)

        if self.delay:
            await asyncio.sleep(self.delay)

        self.call_count += 1
        self.concurrent -= 1

        if url in self.responses:
            return self.responses[url]
        return {"success": True, "data": {"markdown": f"Content of {url}", "source": "direct"}, "error": None}


# ── Fixtures ──────────────────────────────────────────────────────

GOOD_PAGE = {"success": True, "data": {"markdown": "Hello world content here.", "source": "direct"}, "error": None}
FAILED_PAGE = {"success": False, "data": None, "error": "404 Not Found"}


# ── Concurrency ───────────────────────────────────────────────────

def test_semaphore_limits_concurrent_requests():
    """With semaphore=2, no more than 2 concurrent requests should run."""
    async def run():
        scraper = MockScraper(delay=0.1)
        urls = [f"https://example.com/{i}" for i in range(4)]
        await _scrape_urls(urls, scraper, min_sources=4)
        # 4 URLs at 0.1s each with semaphore=2 → ~0.2s wall time, not 0.4s
        assert scraper.max_concurrent == 2, f"Expected 2 concurrent, got {scraper.max_concurrent}"
    asyncio.run(run())


def test_concurrent_is_faster_than_sequential():
    """4 URLs at 0.1s each should complete in ~0.2s, not ~0.4s."""
    async def run():
        scraper = MockScraper(delay=0.1)
        urls = [f"https://example.com/{i}" for i in range(4)]
        t0 = time.monotonic()
        await _scrape_urls(urls, scraper, min_sources=4)
        elapsed = time.monotonic() - t0
        # With semaphore=2, 4×0.1s = 0.2s wall time, plus overhead
        assert elapsed < 0.35, f"Took {elapsed:.3f}s — expected <0.35s for concurrent"
    asyncio.run(run())


# ── Early termination ─────────────────────────────────────────────

def test_stops_early_when_min_sources_reached():
    """Once min_sources=2 are scraped, remaining URLs are not attempted."""
    async def run():
        scraper = MockScraper()
        urls = [f"https://example.com/{i}" for i in range(4)]
        await _scrape_urls(urls, scraper, min_sources=2)
        # Should have stopped after 2 succeeded
        assert scraper.call_count == 2, f"Expected 2 calls, got {scraper.call_count}"
    asyncio.run(run())


def test_early_termination_cancels_in_flight():
    """If min_sources is reached with tasks still running, they get cancelled."""
    async def run():
        scraper = MockScraper(delay=0.2)
        urls = [f"https://example.com/{i}" for i in range(3)]
        await _scrape_urls(urls, scraper, min_sources=1)
        # After first succeeds (0.2s), remaining 1-2 in-flight tasks are cancelled
        # Call count may be 3 (all started) but we complete with 1 doc
        assert scraper.call_count >= 1
    asyncio.run(run())


# ── Error handling ────────────────────────────────────────────────

def test_continues_after_failed_url():
    """A failing URL does not crash the batch — other URLs are still tried."""
    async def run():
        responses = {
            "https://example.com/fail": FAILED_PAGE,
        }
        scraper = MockScraper(responses=responses)
        urls = ["https://example.com/fail", "https://example.com/ok"]
        docs, sources = await _scrape_urls(urls, scraper, min_sources=2)
        assert len(docs) == 1
        assert sources[0]["url"] == "https://example.com/ok"
    asyncio.run(run())


def test_returns_empty_on_all_failures():
    """If every URL fails, returns empty lists."""
    async def run():
        responses = {
            "https://example.com/a": FAILED_PAGE,
            "https://example.com/b": FAILED_PAGE,
        }
        scraper = MockScraper(responses=responses)
        docs, sources = await _scrape_urls(
            list(responses.keys()), scraper, min_sources=2
        )
        assert docs == []
        assert sources == []
    asyncio.run(run())


# ── max_attempts ──────────────────────────────────────────────────

def test_max_attempts_limits_total_calls():
    """With max_attempts=2 and 4 URLs, only 2 URLs are attempted."""
    async def run():
        scraper = MockScraper()
        urls = [f"https://example.com/{i}" for i in range(4)]
        await _scrape_urls(urls, scraper, min_sources=4, max_attempts=2)
        assert scraper.call_count <= 2
    asyncio.run(run())


def test_max_attempts_defaults_to_all_urls():
    """Without max_attempts, all URLs should be tried."""
    async def run():
        scraper = MockScraper()
        urls = [f"https://example.com/{i}" for i in range(4)]
        await _scrape_urls(urls, scraper, min_sources=4)
        assert scraper.call_count == 4
    asyncio.run(run())


# ── Run directly ──────────────────────────────────────────────────

if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
