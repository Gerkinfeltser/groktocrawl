"""SearXNG JSON API client."""

import logging

import httpx

logger = logging.getLogger(__name__)

# ── Firecrawl v2 → SearXNG category translation ────────────────
# Maps Firecrawl v2 search dimensions (sources, categories) to
# SearXNG-native category names. Unknown values pass through for
# forward compatibility. See ADR-0013 and issue #85.

_SOURCES_MAP = {
    "news": "news",
    "images": "images",
    "web": "general",
    "video": "videos",
    "social": "general",
}

_CATEGORIES_MAP = {
    "research": "science",
    "github": "it",
    "pdf": "general",
    "news": "news",
    "science": "science",
    "it": "it",
    "general": "general",
}


class SearXNGClient:
    """Client for the SearXNG search engine JSON API."""

    def __init__(self, base_url: str = "http://searxng:8080"):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=15,
            headers={"User-Agent": "GroktoCrawl/0.1", "Accept": "text/html,application/json", "X-Forwarded-For": "127.0.0.1"},
        )

    @staticmethod
    def _translate(
        sources: list[str] | None,
        categories: list[str] | None,
    ) -> list[str]:
        """Translate Firecrawl v2 sources/categories to SearXNG category names.

        Merges both dimensions into a single SearXNG categories list.
        Unknown values pass through for forward compatibility.
        Returns ``[\"general\"]`` if no mapping produces a category.
        """
        result: list[str] = []
        if sources:
            for s in sources:
                mapped = _SOURCES_MAP.get(s, s)
                if mapped and mapped not in result:
                    result.append(mapped)
        if categories:
            for c in categories:
                mapped = _CATEGORIES_MAP.get(c, c)
                if mapped and mapped not in result:
                    result.append(mapped)
        return result if result else ["general"]

    async def search(
        self,
        query: str,
        limit: int = 10,
        categories: list[str] | None = None,
        sources: list[str] | None = None,
    ) -> list[dict]:
        """Search the web and return structured results.

        Uses SearXNG's JSON API. When categories is None, defaults to "general".
        ``sources`` and ``categories`` are merged via ``_translate()`` before
        being passed to SearXNG.

        Returns a list of dicts with keys: url, title, description, engine.
        """
        effective_categories = self._translate(sources, categories)
        params = {
            "q": query,
            "format": "json",
            "language": "en",
            "pageno": 1,
        }
        params["categories"] = ",".join(effective_categories)

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
