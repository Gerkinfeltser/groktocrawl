"""HTTP client to the scraper service."""

import logging
import time

import httpx

from .metrics import METRICS

logger = logging.getLogger(__name__)


class ScraperClient:
    """Client for the scraper-svc HTTP API."""

    def __init__(self, base_url: str = "http://scraper-svc:8001"):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=60)

    async def scrape(self, url: str) -> dict:
        """Scrape a URL via the scraper service.

        Returns dict with keys: success, data (with markdown, source), error.
        Records scrape latency metrics by source tier.
        """
        start = time.monotonic()
        try:
            resp = await self._client.post(
                f"{self.base_url}/scrape",
                json={"url": url},
            )
            result = resp.json()
            elapsed = time.monotonic() - start
            source = (result.get("data") or {}).get("source", "unknown")
            METRICS.histogram(
                "scrape_duration_seconds", "Scrape latency by source tier",
                ["tier"],
            ).observe({"tier": source}, elapsed)
            METRICS.counter("scrapes_total", "Total scrapes by tier", ["tier"]).inc({"tier": source})
            return result
        except httpx.TimeoutException:
            elapsed = time.monotonic() - start
            logger.warning("Scraper timed out for %s", url)
            METRICS.histogram("scrape_duration_seconds", "Scrape latency by source tier", ["tier"]).observe({"tier": "timeout"}, elapsed)
            return {"success": False, "error": f"Scraper timed out for {url}"}
        except Exception as e:
            elapsed = time.monotonic() - start
            logger.error("Scraper client error for %s: %s", url, e)
            METRICS.histogram("scrape_duration_seconds", "Scrape latency by source tier", ["tier"]).observe({"tier": "error"}, elapsed)
            return {"success": False, "error": str(e)}

    async def close(self):
        await self._client.aclose()
