"""HTTP client for the GroktoCrawl agent-svc API."""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class GroktocrawlClient:
    """Async HTTP client for all GroktoCrawl API endpoints.

    Wraps httpx.AsyncClient with typed convenience methods for each
    endpoint.  Every method returns a ``dict`` — on HTTP or transport
    errors the dict contains an ``error`` key with a human-readable
    message.
    """

    def __init__(self, base_url: str, api_key: str | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client: httpx.AsyncClient | None = None

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {}
        if self._api_key:
            h["Authorization"] = f"Bearer {self._api_key}"
        return h

    async def _client_ctx(self) -> httpx.AsyncClient:
        """Return (and lazily initialise) the shared AsyncClient."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers=self._headers(),
                timeout=httpx.Timeout(120.0),
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ── helpers ─────────────────────────────────────────────────

    async def _post(self, path: str, json_data: dict | None = None) -> dict:
        client = await self._client_ctx()
        try:
            resp = await client.post(path, json=json_data)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            logger.warning("HTTP %s for %s %s", exc.response.status_code, "POST", path)
            return {"error": f"HTTP {exc.response.status_code}: {exc.response.text[:300]}"}
        except Exception as exc:
            logger.error("Request failed for %s %s: %s", "POST", path, exc)
            return {"error": str(exc)}

    async def _get(self, path: str) -> dict:
        client = await self._client_ctx()
        try:
            resp = await client.get(path)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            logger.warning("HTTP %s for %s %s", exc.response.status_code, "GET", path)
            return {"error": f"HTTP {exc.response.status_code}: {exc.response.text[:300]}"}
        except Exception as exc:
            logger.error("Request failed for %s %s: %s", "GET", path, exc)
            return {"error": str(exc)}

    async def _delete(self, path: str) -> dict:
        client = await self._client_ctx()
        try:
            resp = await client.delete(path)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            logger.warning("HTTP %s for %s %s", exc.response.status_code, "DELETE", path)
            return {"error": f"HTTP {exc.response.status_code}: {exc.response.text[:300]}"}
        except Exception as exc:
            logger.error("Request failed for %s %s: %s", "DELETE", path, exc)
            return {"error": str(exc)}

    @staticmethod
    def _error_result(msg: str) -> dict:
        return {"error": msg}

    # ── API methods ─────────────────────────────────────────────

    async def scrape(self, url: str, formats: list[str] | None = None) -> dict:
        """Scrape a URL to markdown."""
        body: dict[str, Any] = {"url": url}
        if formats:
            body["formats"] = formats
        return await self._post("/v2/scrape", body)

    async def search(
        self,
        query: str,
        limit: int = 5,
        sources: list[str] | None = None,
    ) -> dict:
        """Web search with optional source filtering."""
        body: dict[str, Any] = {"query": query, "limit": limit}
        if sources:
            body["sources"] = sources
        return await self._post("/v2/search", body)

    async def agent(
        self,
        prompt: str,
        model: str | None = None,
        output_schema: dict | None = None,
    ) -> dict:
        """Autonomous research agent — create job and poll until complete."""
        body: dict[str, Any] = {"prompt": prompt}
        if model and model != "default":
            body["model"] = model
        if output_schema:
            body["output_schema"] = output_schema

        create_result = await self._post("/v2/agent", body)
        if "error" in create_result:
            return create_result
        job_id = create_result.get("id")
        if not job_id:
            return self._error_result("Agent create: missing job id in response")

        # Poll for completion (max 120 seconds)
        import asyncio

        deadline = asyncio.get_event_loop().time() + 120
        while asyncio.get_event_loop().time() < deadline:
            status = await self._get(f"/v2/agent/{job_id}")
            if "error" in status:
                return status
            st = status.get("status", "processing")
            if st in ("completed", "failed", "cancelled"):
                return status
            await asyncio.sleep(1.0)
        return self._error_result("Agent job timed out after 120s")

    async def answer(
        self, question: str, output_schema: dict | None = None
    ) -> dict:
        """Grounded Q&A — synchronous."""
        body: dict[str, Any] = {"query": question}
        if output_schema:
            body["output_schema"] = output_schema
        return await self._post("/v2/answer", body)

    async def crawl(
        self,
        url: str,
        max_pages: int | None = None,
        max_depth: int | None = None,
    ) -> dict:
        """Crawl a website — create job and poll until complete."""
        body: dict[str, Any] = {"url": url}
        if max_pages is not None:
            body["max_pages"] = max_pages
        if max_depth is not None:
            body["max_depth"] = max_depth

        create_result = await self._post("/v2/crawl", body)
        if "error" in create_result:
            return create_result
        job_id = create_result.get("id")
        if not job_id:
            return self._error_result("Crawl create: missing job id in response")

        import asyncio

        deadline = asyncio.get_event_loop().time() + 300
        while asyncio.get_event_loop().time() < deadline:
            status = await self._get(f"/v2/crawl/{job_id}")
            if "error" in status:
                return status
            st = status.get("status", "processing")
            if st in ("completed", "failed", "cancelled"):
                return status
            await asyncio.sleep(2.0)
        return self._error_result("Crawl job timed out after 300s")

    async def map(self, url: str, limit: int = 100) -> dict:
        """Discover URLs on a site."""
        return await self._post("/v2/map", {"url": url, "limit": limit})

    async def extract(self, url: str, schema: dict) -> dict:
        """Structured extraction from URLs."""
        body: dict[str, Any] = {"urls": [url], "schema": schema}
        create_result = await self._post("/v2/extract", body)
        if "error" in create_result:
            return create_result
        job_id = create_result.get("id")
        if not job_id:
            return self._error_result("Extract create: missing job id in response")

        import asyncio

        deadline = asyncio.get_event_loop().time() + 120
        while asyncio.get_event_loop().time() < deadline:
            status = await self._get(f"/v2/extract/{job_id}")
            if "error" in status:
                return status
            st = status.get("status", "processing")
            if st in ("completed", "failed", "cancelled"):
                return status
            await asyncio.sleep(1.0)
        return self._error_result("Extract job timed out after 120s")

    async def parse(self, file_url: str) -> dict:
        """Parse a document (file at URL) to markdown.

        Downloads the file and sends it to the parse endpoint as
        multipart form data.
        """
        import os

        client = await self._client_ctx()
        try:
            # Download the file first
            dl_resp = await client.get(file_url)
            dl_resp.raise_for_status()

            filename = os.path.basename(file_url.rsplit("?", 1)[0]) or "file"
            content_type = dl_resp.headers.get("content-type", "application/octet-stream")

            # Upload to parse endpoint
            parse_resp = await client.post(
                "/v2/parse",
                files={"file": (filename, dl_resp.content, content_type)},
            )
            parse_resp.raise_for_status()
            return parse_resp.json()
        except httpx.HTTPStatusError as exc:
            logger.warning("HTTP %s for parse of %s", exc.response.status_code, file_url)
            return {"error": f"HTTP {exc.response.status_code}: {exc.response.text[:300]}"}
        except Exception as exc:
            logger.error("Parse failed for %s: %s", file_url, exc)
            return {"error": str(exc)}

    async def batch_scrape(self, urls: list[str]) -> dict:
        """Scrape multiple URLs in batch."""
        create_result = await self._post("/v2/batch/scrape", {"urls": urls})
        if "error" in create_result:
            return create_result
        job_id = create_result.get("id")
        if not job_id:
            return self._error_result("Batch scrape: missing job id in response")

        import asyncio

        deadline = asyncio.get_event_loop().time() + 300
        while asyncio.get_event_loop().time() < deadline:
            status = await self._get(f"/v2/batch/scrape/{job_id}")
            if "error" in status:
                return status
            st = status.get("status", "processing")
            if st in ("completed", "failed", "cancelled"):
                return status
            await asyncio.sleep(2.0)
        return self._error_result("Batch scrape timed out after 300s")

    async def find_similar(self, url: str) -> dict:
        """Find pages similar to a given URL."""
        return await self._post("/v2/find-similar", {"url": url})

    async def enrich(self, url: str) -> dict:
        """Enrich content for a URL."""
        # The enrich endpoint expects "items" (list of dicts with entity data)
        # and "fields" (description of what to extract).
        # We construct a minimal enrichment request treating the URL as a
        # single-item entity.
        return await self._post(
            "/v2/enrich",
            {
                "items": [{"url": url}],
                "fields": {"summary": {"description": "A concise summary"}},
            },
        )

    async def generate_llmstxt(self, url: str) -> dict:
        """Generate an llms.txt file for a website."""
        create_result = await self._post("/v2/generate-llmstxt", {"url": url})
        if "error" in create_result:
            return create_result
        job_id = create_result.get("id")
        if not job_id:
            return self._error_result("Generate LLMs.txt: missing job id in response")

        import asyncio

        deadline = asyncio.get_event_loop().time() + 120
        while asyncio.get_event_loop().time() < deadline:
            status = await self._get(f"/v2/generate-llmstxt/{job_id}")
            if "error" in status:
                return status
            st = status.get("status", "processing")
            if st in ("completed", "failed"):
                return status
            await asyncio.sleep(1.0)
        return self._error_result("Generate LLMs.txt timed out after 120s")

    async def health(self) -> dict:
        """Server health check."""
        return await self._get("/health")

    async def browser_create(self, ttl: int = 300) -> dict:
        """Create a browser session."""
        return await self._post("/v2/browser", {"ttl": ttl})

    async def browser_action(
        self, session_id: str, action: str, **kwargs: Any
    ) -> dict:
        """Execute an action in a browser session."""
        body: dict[str, Any] = {"action": action}
        body.update(kwargs)
        return await self._post(f"/v2/browser/{session_id}/execute", body)

    async def browser_destroy(self, session_id: str) -> dict:
        """Destroy a browser session."""
        return await self._delete(f"/v2/browser/{session_id}")

    async def monitor_create(self, url: str, schedule: str) -> dict:
        """Create a change monitor."""
        return await self._post(
            "/v2/monitor", {"url": url, "schedule": schedule}
        )

    async def monitor_list(self) -> dict:
        """List all monitors."""
        return await self._get("/v2/monitor")

    async def monitor_delete(self, monitor_id: str) -> dict:
        """Delete a monitor."""
        return await self._delete(f"/v2/monitor/{monitor_id}")
