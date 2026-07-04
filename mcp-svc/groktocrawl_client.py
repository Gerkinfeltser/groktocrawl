"""HTTP client for the GroktoCrawl agent-svc API."""

import logging
import os
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def _extract_response_detail(response: httpx.Response) -> str:
    """Extract a human-readable detail from an error response body.

    Tries JSON first (looking for ``detail``, ``error``, or ``message``
    keys), then falls back to the raw text (truncated).
    """
    try:
        body = response.json()
        if isinstance(body, dict):
            # FastAPI-style validation errors have a 'detail' key
            if "detail" in body:
                detail = body["detail"]
                if isinstance(detail, list):
                    # FastAPI validation errors: detail is a list of error objects
                    return "; ".join(str(d.get("msg", str(d))) for d in detail[:3])
                if isinstance(detail, str):
                    return detail[:500]
            # GroktoCrawl-style errors
            for key in ("error", "message"):
                if key in body and isinstance(body[key], str):
                    return body[key][:500]
        return response.text[:300]
    except (ValueError, TypeError):
        return response.text[:300]


class GroktocrawlClient:
    """Async HTTP client for all GroktoCrawl API endpoints.

    Wraps httpx.AsyncClient with typed convenience methods for each
    endpoint.  Every method returns a ``dict`` — on HTTP or transport
    errors the dict contains an ``error`` key with a human-readable
    message and (when applicable) a ``status_code`` key.

    Usage::

        async with GroktocrawlClient.from_env() as client:
            result = await client.scrape("https://example.com")
    """

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        default_timeout: float = 120.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._default_timeout = default_timeout
        self._client: httpx.AsyncClient | None = None

    @classmethod
    def from_env(cls, default_timeout: float = 120.0) -> "GroktocrawlClient":
        """Create a client from environment variables.

        Reads ``GROKTOCRAWL_URL`` for the agent-svc base URL (falls back
        to ``GROKTOCRAWL_API_URL`` for backward compatibility, then
        ``http://localhost:8080``).  Reads ``GROKTOCRAWL_API_KEY`` for
        the optional API key.
        """
        base_url = os.environ.get(
            "GROKTOCRAWL_URL",
            os.environ.get("GROKTOCRAWL_API_URL", "http://localhost:8080"),
        )
        api_key = os.environ.get("GROKTOCRAWL_API_KEY") or None
        return cls(base_url=base_url, api_key=api_key, default_timeout=default_timeout)

    async def __aenter__(self) -> "GroktocrawlClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

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
                timeout=httpx.Timeout(self._default_timeout),
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ── helpers ─────────────────────────────────────────────────

    def _error_result(self, msg: str, *, status_code: int | None = None) -> dict:
        result: dict[str, Any] = {"error": msg}
        if status_code is not None:
            result["status_code"] = status_code
        return result

    async def _request(
        self, method: str, path: str, json_data: dict | None = None
    ) -> dict:
        """Unified request helper with structured error handling.

        Discriminates between HTTP errors, timeouts, connection failures,
        and other transport errors — each producing a descriptive error
        dict with appropriate detail.
        """
        client = await self._client_ctx()
        start = time.monotonic()
        try:
            resp = await client.request(method, path, json=json_data)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            duration = time.monotonic() - start
            status_code = exc.response.status_code
            detail = _extract_response_detail(exc.response)
            logger.warning(
                "HTTP %s for %s %s (%.1fs)",
                status_code,
                method,
                path,
                duration,
            )
            return self._error_result(
                f"HTTP {status_code}: {detail}",
                status_code=status_code,
            )
        except httpx.TimeoutException:
            duration = time.monotonic() - start
            logger.error(
                "Timeout (%.1fs) for %s %s (threshold: %.0fs)",
                duration,
                method,
                path,
                self._default_timeout,
            )
            return self._error_result(
                f"Request timed out after {duration:.1f}s "
                f"(timeout: {self._default_timeout:.0f}s) for "
                f"{method.upper()} {path}"
            )
        except httpx.ConnectError as exc:
            logger.error("Connection failed for %s %s: %s", method, path, exc)
            return self._error_result(
                f"Connection failed: unable to reach server at "
                f"{self._base_url} — is agent-svc running?"
            )
        except Exception as exc:
            logger.error("Request failed for %s %s: %s", method, path, exc)
            return self._error_result(str(exc))

    async def _post(self, path: str, json_data: dict | None = None) -> dict:
        return await self._request("POST", path, json_data)

    async def _get(self, path: str) -> dict:
        return await self._request("GET", path)

    async def _delete(self, path: str) -> dict:
        return await self._request("DELETE", path)

    # ── API methods ─────────────────────────────────────────────

    async def scrape(
        self,
        url: str,
        formats: list[str] | None = None,
        only_main_content: bool = True,
    ) -> dict:
        """Scrape a URL to markdown."""
        body: dict[str, Any] = {"url": url}
        if formats:
            body["formats"] = formats
        if not only_main_content:
            body["only_main_content"] = only_main_content
        return await self._post("/v2/scrape", body)

    async def search(
        self,
        query: str,
        limit: int = 5,
        sources: list[str] | None = None,
        search_type: str | None = None,
    ) -> dict:
        """Web search with optional source filtering and search type."""
        body: dict[str, Any] = {"query": query, "limit": limit}
        if sources:
            body["sources"] = sources
        if search_type:
            body["search_type"] = search_type
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
        self,
        question: str,
        num_sources: int = 5,
        output_schema: dict | None = None,
    ) -> dict:
        """Grounded Q&A — synchronous."""
        body: dict[str, Any] = {"query": question, "num_sources": num_sources}
        if output_schema:
            body["output_schema"] = output_schema
        return await self._post("/v2/answer", body)

    # ── Non-polling job creation methods ────────────────────────

    async def create_crawl(
        self,
        url: str,
        max_pages: int | None = None,
        max_depth: int | None = None,
    ) -> dict:
        """Create a crawl job without polling for completion.

        Returns the agent-svc response containing the job ``id``.
        Use :meth:`get_crawl_status` to poll for results.
        """
        body: dict[str, Any] = {"url": url}
        if max_pages is not None:
            body["max_pages"] = max_pages
        if max_depth is not None:
            body["max_depth"] = max_depth
        return await self._post("/v2/crawl", body)

    async def create_extract(
        self,
        urls: list[str],
        prompt: str | None = None,
        schema: dict | None = None,
    ) -> dict:
        """Create an extract job without polling for completion.

        Returns the agent-svc response containing the job ``id``.
        Use :meth:`get_extract_status` to poll for results.
        """
        body: dict[str, Any] = {"urls": urls}
        if prompt:
            body["prompt"] = prompt
        if schema:
            body["schema"] = schema
        return await self._post("/v2/extract", body)

    async def create_batch_scrape(self, urls: list[str]) -> dict:
        """Create a batch scrape job without polling for completion.

        Returns the agent-svc response containing the job ``id``.
        Use :meth:`get_batch_scrape_status` to poll for results.
        """
        return await self._post("/v2/batch/scrape", {"urls": urls})

    async def create_llmstxt(
        self,
        url: str,
        max_pages: int | None = None,
    ) -> dict:
        """Create an llms.txt generation job without polling.

        Returns the agent-svc response containing the job ``id``.
        Use :meth:`get_llmstxt_status` to poll for results.
        """
        body: dict[str, Any] = {"url": url}
        if max_pages is not None:
            body["max_pages"] = max_pages
        return await self._post("/v2/generate-llmstxt", body)

    async def get_batch_scrape_status(self, job_id: str) -> dict:
        """Get the current status of a batch scrape job."""
        return await self._get(f"/v2/batch/scrape/{job_id}")

    async def get_llmstxt_status(self, job_id: str) -> dict:
        """Get the current status of an llms.txt generation job."""
        return await self._get(f"/v2/generate-llmstxt/{job_id}")

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
            content_type = dl_resp.headers.get(
                "content-type", "application/octet-stream"
            )

            # Upload to parse endpoint
            parse_resp = await client.post(
                "/v2/parse",
                files={"file": (filename, dl_resp.content, content_type)},
            )
            parse_resp.raise_for_status()
            return parse_resp.json()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "HTTP %s for parse of %s", exc.response.status_code, file_url
            )
            return {
                "error": f"HTTP {exc.response.status_code}: {exc.response.text[:300]}"
            }
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

    # ── status / cancellation / activity tools ──────────────────

    async def get_crawl_status(self, job_id: str) -> dict:
        """Get the current status of a crawl job.

        Args:
            job_id: The crawl job ID returned by :meth:`crawl`.

        Returns:
            Status dict with ``status``, ``completed``, ``total``,
            ``data``, and other crawl-specific fields.
        """
        return await self._get(f"/v2/crawl/{job_id}")

    async def cancel_crawl(self, job_id: str) -> dict:
        """Cancel an in-progress crawl job.

        Args:
            job_id: The crawl job ID to cancel.

        Returns:
            Confirmation dict with ``success`` and ``status`` fields.
        """
        return await self._delete(f"/v2/crawl/{job_id}")

    async def get_crawl_errors(self, job_id: str) -> dict:
        """Get per-URL errors for a crawl job.

        Args:
            job_id: The crawl job ID.

        Returns:
            Error listing with ``errors`` array and
            ``robots_blocked`` array.
        """
        return await self._get(f"/v2/crawl/{job_id}/errors")

    async def get_agent_status(self, job_id: str) -> dict:
        """Get the current status of an agent research job.

        Args:
            job_id: The agent job ID returned by :meth:`agent`.

        Returns:
            Status dict with ``status``, ``data``, ``source_details``,
            and other agent-specific fields.
        """
        return await self._get(f"/v2/agent/{job_id}")

    async def get_extract_status(self, job_id: str) -> dict:
        """Get the current status of an extract job.

        Args:
            job_id: The extract job ID returned by :meth:`extract`.

        Returns:
            Status dict with ``status``, ``data``, and extraction results.
        """
        return await self._get(f"/v2/extract/{job_id}")

    async def get_activity(self) -> dict:
        """Get recent API activity / job queue status.

        Returns:
            Activity listing with active jobs across all job types.
        """
        return await self._get("/v2/activity")

    async def resolve_citations(
        self,
        text: str,
        sources: list[dict],
        style: str = "inline",
    ) -> dict:
        """Resolve compact citation IDs to full source cards.

        Calls POST /v2/citations/resolve on the GroktoCrawl API.

        Args:
            text: The markdown text containing citation markers (e.g. ``[1]``).
            sources: List of source dicts with ``url`` and ``title`` keys.
            style: Citation style — ``inline`` (no transformation) or
                ``compact`` (replaces ``[N]`` with ``[N](url)``).

        Returns:
            Dict with ``resolved_text``, ``citations`` array, and
            ``citation_count``.
        """
        body: dict[str, Any] = {
            "text": text,
            "sources": sources,
            "style": style,
        }
        return await self._post("/v2/citations/resolve", body)

    # ── utility tools ───────────────────────────────────────────

    async def health(self) -> dict:
        """Server health check."""
        return await self._get("/health")

    async def browser_create(self, ttl: int = 300) -> dict:
        """Create a browser session."""
        return await self._post("/v2/browser", {"ttl": ttl})

    async def browser_action(self, session_id: str, action: str, **kwargs: Any) -> dict:
        """Execute an action in a browser session."""
        body: dict[str, Any] = {"action": action}
        body.update(kwargs)
        return await self._post(f"/v2/browser/{session_id}/execute", body)

    async def browser_destroy(self, session_id: str) -> dict:
        """Destroy a browser session."""
        return await self._delete(f"/v2/browser/{session_id}")

    async def monitor_create(self, url: str, schedule: str) -> dict:
        """Create a change monitor."""
        return await self._post("/v2/monitor", {"url": url, "schedule": schedule})

    async def monitor_list(self) -> dict:
        """List all monitors."""
        return await self._get("/v2/monitor")

    async def monitor_delete(self, monitor_id: str) -> dict:
        """Delete a monitor."""
        return await self._delete(f"/v2/monitor/{monitor_id}")
