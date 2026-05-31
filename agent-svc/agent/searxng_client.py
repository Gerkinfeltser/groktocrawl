"""SearXNG JSON API client."""

import logging

import httpx

logger = logging.getLogger(__name__)


class SearXNGClient:
    """Client for the SearXNG search engine JSON API."""

    def __init__(self, base_url: str = "http://searxng:8080"):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=15,
            headers={"User-Agent": "GroktoCrawl/0.1", "Accept": "text/html,application/json", "X-Forwarded-For": "127.0.0.1"},
        )

    async def search(self, query: str, limit: int = 10, categories: list[str] | None = None) -> list[dict]:
        """Search the web and return structured results.

        Uses SearXNG's JSON API. When categories is None, defaults to "general".
        Multiple categories (e.g. ["news", "science"]) are comma-separated per
        the SearXNG API convention.

        Returns a list of dicts with keys: url, title, description, engine.
        """
        params = {
            "q": query,
            "format": "json",
            "language": "en",
            "pageno": 1,
        }
        if categories:
            params["categories"] = ",".join(categories)
        else:
            params["categories"] = "general"

        try:
            resp = await self._client.get(
                f"{self.base_url}/search",
                params=params,
            )
            if resp.status_code != 200:
                logger.warning("SearXNG returned %d: %s", resp.status_code, resp.text[:200])
                return []

            data = resp.json()
            results = []
            for item in data.get("results", []):
                results.append({
                    "url": item.get("url", ""),
                    "title": item.get("title", ""),
                    "description": item.get("content", ""),
                    "engine": item.get("engine", ""),
                })

            return results[:limit]

        except httpx.TimeoutException:
            logger.warning("SearXNG search timed out for query: %s", query)
            return []
        except Exception as e:
            logger.error("SearXNG search failed: %s", e)
            return []

    async def close(self):
        await self._client.aclose()
