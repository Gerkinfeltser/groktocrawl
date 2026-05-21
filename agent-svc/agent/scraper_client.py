"""HTTP client to the scraper service."""

import logging

import httpx

logger = logging.getLogger(__name__)


class ScraperClient:
    """Client for the scraper-svc HTTP API."""

    def __init__(self, base_url: str = "http://scraper-svc:8001"):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=60)

    async def scrape(self, url: str) -> dict:
        """Scrape a URL via the scraper service.

        Returns dict with keys: success, data (with markdown, source), error.
        """
        try:
            resp = await self._client.post(
                f"{self.base_url}/scrape",
                json={"url": url},
            )
            return resp.json()
        except httpx.TimeoutException:
            logger.warning("Scraper timed out for %s", url)
            return {"success": False, "error": f"Scraper timed out for {url}"}
        except Exception as e:
            logger.error("Scraper client error for %s: %s", url, e)
            return {"success": False, "error": str(e)}

    async def close(self):
        await self._client.aclose()
