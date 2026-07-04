"""Tests for the GroktocrawlClient HTTP client.

Uses httpx.MockTransport to simulate agent-svc responses so that no
running agent-svc is required.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from groktocrawl_client import GroktocrawlClient, _extract_response_detail

# ── helpers ────────────────────────────────────────────────────────


def _json_handler(body: dict[str, Any], status_code: int = 200) -> httpx.Handler:
    """Return a mock handler that responds with JSON."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            json=body,
            request=request,
        )

    return handler


def _make_client(
    responses: dict[tuple[str, str], httpx.Handler],
    api_key: str | None = None,
    default_timeout: float = 5.0,
) -> GroktocrawlClient:
    """Create a GroktocrawlClient backed by a MockTransport.

    *responses* maps (method, path) to handler functions.  Any
    unmatched request returns 404.
    """

    def _dispatch(request: httpx.Request) -> httpx.Response:
        key = (request.method, request.url.path)
        handler = responses.get(key)
        if handler is not None:
            return handler(request)
        return httpx.Response(404, json={"error": "not found"}, request=request)

    transport = httpx.MockTransport(_dispatch)
    client = GroktocrawlClient(
        base_url="http://test:8080",
        api_key=api_key,
        default_timeout=default_timeout,
    )
    # Inject the mock transport *after* construction
    client._client = httpx.AsyncClient(
        base_url=client._base_url,
        headers=client._headers(),
        transport=transport,
    )
    return client


# ═══════════════════════════════════════════════════════════════════
# _extract_response_detail
# ═══════════════════════════════════════════════════════════════════


class TestExtractResponseDetail:
    def test_fastapi_detail_string(self):
        resp = httpx.Response(
            422,
            json={"detail": "Field required"},
            request=httpx.Request("POST", "http://x"),
        )
        assert _extract_response_detail(resp) == "Field required"

    def test_fastapi_detail_list(self):
        resp = httpx.Response(
            422,
            json={
                "detail": [
                    {"msg": "field required", "type": "missing"},
                    {"msg": "value_error", "type": "value_error"},
                ]
            },
            request=httpx.Request("POST", "http://x"),
        )
        detail = _extract_response_detail(resp)
        assert "field required" in detail
        assert "value_error" in detail

    def test_groktocrawl_error_key(self):
        resp = httpx.Response(
            500,
            json={"error": "Internal server failure"},
            request=httpx.Request("POST", "http://x"),
        )
        assert _extract_response_detail(resp) == "Internal server failure"

    def test_groktocrawl_message_key(self):
        resp = httpx.Response(
            400,
            json={"message": "Bad request"},
            request=httpx.Request("POST", "http://x"),
        )
        assert _extract_response_detail(resp) == "Bad request"

    def test_plain_text_fallback(self):
        resp = httpx.Response(
            500,
            content=b"Something broke",
            request=httpx.Request("POST", "http://x"),
        )
        assert _extract_response_detail(resp) == "Something broke"

    def test_non_json_response(self):
        resp = httpx.Response(
            502,
            content=b"<html>Bad Gateway</html>",
            headers={"Content-Type": "text/html"},
            request=httpx.Request("POST", "http://x"),
        )
        assert _extract_response_detail(resp) == "<html>Bad Gateway</html>"


# ═══════════════════════════════════════════════════════════════════
# from_env / constructor
# ═══════════════════════════════════════════════════════════════════


class TestFromEnv:
    def test_defaults(self, monkeypatch):
        monkeypatch.delenv("GROKTOCRAWL_URL", raising=False)
        monkeypatch.delenv("GROKTOCRAWL_API_URL", raising=False)
        monkeypatch.delenv("GROKTOCRAWL_API_KEY", raising=False)
        client = GroktocrawlClient.from_env()
        assert client._base_url == "http://localhost:8080"
        assert client._api_key is None
        assert client._default_timeout == 120.0

    def test_groktocrawl_url(self, monkeypatch):
        monkeypatch.setenv("GROKTOCRAWL_URL", "http://saru:8080")
        monkeypatch.delenv("GROKTOCRAWL_API_URL", raising=False)
        monkeypatch.delenv("GROKTOCRAWL_API_KEY", raising=False)
        client = GroktocrawlClient.from_env()
        assert client._base_url == "http://saru:8080"

    def test_fallback_to_groktocrawl_api_url(self, monkeypatch):
        monkeypatch.delenv("GROKTOCRAWL_URL", raising=False)
        monkeypatch.setenv("GROKTOCRAWL_API_URL", "http://legacy:9090")
        monkeypatch.delenv("GROKTOCRAWL_API_KEY", raising=False)
        client = GroktocrawlClient.from_env()
        assert client._base_url == "http://legacy:9090"

    def test_groktocrawl_url_takes_precedence(self, monkeypatch):
        monkeypatch.setenv("GROKTOCRAWL_URL", "http://new:8080")
        monkeypatch.setenv("GROKTOCRAWL_API_URL", "http://old:8080")
        monkeypatch.delenv("GROKTOCRAWL_API_KEY", raising=False)
        client = GroktocrawlClient.from_env()
        assert client._base_url == "http://new:8080"

    def test_api_key(self, monkeypatch):
        monkeypatch.delenv("GROKTOCRAWL_URL", raising=False)
        monkeypatch.setenv("GROKTOCRAWL_API_KEY", "test-api-token-123")
        client = GroktocrawlClient.from_env()
        assert client._api_key == "test-api-token-123"

    def test_custom_timeout(self, monkeypatch):
        monkeypatch.delenv("GROKTOCRAWL_URL", raising=False)
        monkeypatch.delenv("GROKTOCRAWL_API_KEY", raising=False)
        client = GroktocrawlClient.from_env(default_timeout=30.0)
        assert client._default_timeout == 30.0


# ═══════════════════════════════════════════════════════════════════
# Error propagation — VAL-MCP-G03, G04, G05
# ═══════════════════════════════════════════════════════════════════


class TestErrorPropagation:
    """VAL-MCP-G03: HTTP errors translated to structured errors."""

    @pytest.mark.asyncio
    async def test_http_4xx_becomes_structured_error(self):
        """VAL-MCP-G03: HTTP 4xx returns error with status_code."""
        client = _make_client(
            {
                ("POST", "/v2/scrape"): _json_handler(
                    {"error": "Invalid URL format"},
                    status_code=400,
                ),
            }
        )
        result = await client.scrape("not-a-url")
        assert "error" in result
        assert result["status_code"] == 400
        assert "400" in result["error"]
        assert "Invalid URL format" in result["error"]

    @pytest.mark.asyncio
    async def test_http_5xx_becomes_structured_error(self):
        """VAL-MCP-G03: HTTP 5xx returns error with status_code."""
        client = _make_client(
            {
                ("POST", "/v2/scrape"): _json_handler(
                    {"error": "Scraper down"},
                    status_code=502,
                ),
            }
        )
        result = await client.scrape("https://example.com")
        assert "error" in result
        assert result["status_code"] == 502
        assert "502" in result["error"]

    @pytest.mark.asyncio
    async def test_http_401_auth_failure(self):
        """VAL-MCP-H03: Invalid API key propagates as 401 error."""
        client = _make_client(
            {
                ("GET", "/v2/activity"): _json_handler(
                    {"detail": "Invalid API key"},
                    status_code=401,
                ),
            }
        )
        result = await client.get_activity()
        assert "error" in result
        assert result["status_code"] == 401
        assert "401" in result["error"]

    @pytest.mark.asyncio
    async def test_http_404_job_not_found(self):
        """GET nonexistent job returns not-found error."""
        client = _make_client(
            {
                ("GET", "/v2/crawl/nonexistent"): _json_handler(
                    {"detail": "Job not found"},
                    status_code=404,
                ),
            }
        )
        result = await client.get_crawl_status("nonexistent")
        assert "error" in result
        assert result["status_code"] == 404

    @pytest.mark.asyncio
    async def test_timeout_with_duration_info(self):
        """VAL-MCP-G04: Timeout includes duration and timeout info."""

        def _timeout(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("timed out after 0.1s", request=request)

        transport = httpx.MockTransport(_timeout)
        client = GroktocrawlClient(
            base_url="http://test:8080",
            api_key=None,
            default_timeout=5.0,
        )
        client._client = httpx.AsyncClient(
            base_url=client._base_url,
            headers=client._headers(),
            transport=transport,
        )

        result = await client.scrape("https://example.com")
        assert "error" in result
        assert "timed out" in result["error"].lower()
        assert "timeout" in result["error"].lower()
        assert "5s" in result["error"] or "5.0s" in result["error"]

    @pytest.mark.asyncio
    async def test_connect_error_clean_message(self):
        """VAL-MCP-G05: ConnectError returns clean message without traceback."""

        def _refuse(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused", request=request)

        transport = httpx.MockTransport(_refuse)
        client = GroktocrawlClient(
            base_url="http://down:9999",
            api_key=None,
            default_timeout=5.0,
        )
        client._client = httpx.AsyncClient(
            base_url=client._base_url,
            headers=client._headers(),
            transport=transport,
        )

        result = await client.scrape("https://example.com")
        assert "error" in result
        assert "connection" in result["error"].lower()
        assert "unable to reach server" in result["error"].lower()
        # Must NOT contain a raw traceback
        assert "Traceback" not in result["error"]


# ═══════════════════════════════════════════════════════════════════
# Missing methods — get_crawl_status, cancel_crawl, etc.
# ═══════════════════════════════════════════════════════════════════


class TestStatusMethods:
    @pytest.mark.asyncio
    async def test_get_crawl_status(self):
        client = _make_client(
            {
                ("GET", "/v2/crawl/job-1"): _json_handler(
                    {
                        "status": "completed",
                        "completed": 10,
                        "total": 10,
                    },
                ),
            }
        )
        result = await client.get_crawl_status("job-1")
        assert result["status"] == "completed"
        assert result["completed"] == 10

    @pytest.mark.asyncio
    async def test_cancel_crawl(self):
        client = _make_client(
            {
                ("DELETE", "/v2/crawl/job-1"): _json_handler(
                    {
                        "success": True,
                        "status": "cancelled",
                    },
                ),
            }
        )
        result = await client.cancel_crawl("job-1")
        assert result["success"] is True
        assert result["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_get_crawl_errors(self):
        client = _make_client(
            {
                ("GET", "/v2/crawl/job-1/errors"): _json_handler(
                    {
                        "errors": [{"url": "https://bad.example", "error": "timeout"}],
                        "robots_blocked": [],
                    },
                ),
            }
        )
        result = await client.get_crawl_errors("job-1")
        assert len(result["errors"]) == 1
        assert result["errors"][0]["url"] == "https://bad.example"

    @pytest.mark.asyncio
    async def test_get_agent_status(self):
        client = _make_client(
            {
                ("GET", "/v2/agent/job-1"): _json_handler(
                    {
                        "status": "completed",
                        "data": {"result": "research findings"},
                    },
                ),
            }
        )
        result = await client.get_agent_status("job-1")
        assert result["status"] == "completed"
        assert result["data"]["result"] == "research findings"

    @pytest.mark.asyncio
    async def test_get_extract_status(self):
        client = _make_client(
            {
                ("GET", "/v2/extract/job-1"): _json_handler(
                    {
                        "status": "completed",
                        "data": {"structured": {"key": "value"}},
                    },
                ),
            }
        )
        result = await client.get_extract_status("job-1")
        assert result["status"] == "completed"
        assert result["data"]["structured"]["key"] == "value"

    @pytest.mark.asyncio
    async def test_get_activity(self):
        client = _make_client(
            {
                ("GET", "/v2/activity"): _json_handler(
                    {
                        "active_jobs": 3,
                        "crawls": 1,
                        "agents": 2,
                    },
                ),
            }
        )
        result = await client.get_activity()
        assert result["active_jobs"] == 3


# ═══════════════════════════════════════════════════════════════════
# Auth passthrough — VAL-MCP-H01, H02
# ═══════════════════════════════════════════════════════════════════


class TestAuthPassthrough:
    """VAL-MCP-H01: API key passed through as Authorization header."""

    @pytest.mark.asyncio
    async def test_api_key_in_authorization_header(self):
        """Auth header is set when api_key is provided."""
        captured_headers: dict[str, str] = {}

        def _capture(request: httpx.Request) -> httpx.Response:
            captured_headers.update(dict(request.headers))
            return httpx.Response(200, json={"success": True}, request=request)

        transport = httpx.MockTransport(_capture)
        client = GroktocrawlClient(
            base_url="http://test:8080",
            api_key="my-test-token",
        )
        client._client = httpx.AsyncClient(
            base_url=client._base_url,
            headers=client._headers(),
            transport=transport,
        )

        _ = await client.scrape("https://example.com")
        assert "authorization" in captured_headers
        assert captured_headers["authorization"] == "Bearer my-test-token"

    @pytest.mark.asyncio
    async def test_no_auth_header_without_api_key(self):
        """VAL-MCP-H02: No auth header when API key is not set."""
        captured_headers: dict[str, str] = {}

        def _capture(request: httpx.Request) -> httpx.Response:
            captured_headers.update(dict(request.headers))
            return httpx.Response(200, json={"success": True}, request=request)

        transport = httpx.MockTransport(_capture)
        client = GroktocrawlClient(
            base_url="http://test:8080",
            api_key=None,
        )
        client._client = httpx.AsyncClient(
            base_url=client._base_url,
            headers=client._headers(),
            transport=transport,
        )

        _ = await client.scrape("https://example.com")
        assert "authorization" not in captured_headers


# ═══════════════════════════════════════════════════════════════════
# All 17 tool operations
# ═══════════════════════════════════════════════════════════════════


class TestAllTools:
    """Verify each of the 17 tool operations hits the right endpoint."""

    @pytest.mark.asyncio
    async def test_scrape_endpoint(self):
        client = _make_client(
            {
                ("POST", "/v2/scrape"): _json_handler(
                    {"success": True, "data": {"markdown": "# hello"}}
                ),
            }
        )
        result = await client.scrape("https://example.com")
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_search_endpoint(self):
        client = _make_client(
            {
                ("POST", "/v2/search"): _json_handler(
                    {"data": {"web": [{"url": "https://x.com"}]}}
                ),
            }
        )
        result = await client.search("test query")
        assert len(result["data"]["web"]) == 1

    @pytest.mark.asyncio
    async def test_crawl_creates_and_polls(self):
        call_count = 0

        def _handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if request.method == "POST" and request.url.path == "/v2/crawl":
                return httpx.Response(200, json={"id": "crawl-99"}, request=request)
            if request.method == "GET" and "/v2/crawl/crawl-99" in request.url.path:
                return httpx.Response(
                    200, json={"status": "completed", "data": []}, request=request
                )
            return httpx.Response(404, json={"error": "not found"}, request=request)

        transport = httpx.MockTransport(_handler)
        client = GroktocrawlClient(base_url="http://test:8080", api_key=None)
        client._client = httpx.AsyncClient(
            base_url=client._base_url,
            headers=client._headers(),
            transport=transport,
        )

        result = await client.crawl("https://example.com", max_pages=5)
        assert result["status"] == "completed"
        assert call_count >= 2  # create + at least one poll

    @pytest.mark.asyncio
    async def test_map_endpoint(self):
        client = _make_client(
            {
                ("POST", "/v2/map"): _json_handler(
                    {"links": ["https://a.com", "https://b.com"]}
                ),
            }
        )
        result = await client.map("https://example.com")
        assert len(result["links"]) == 2

    @pytest.mark.asyncio
    async def test_agent_creates_and_polls(self):
        call_count = 0

        def _handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if request.method == "POST" and request.url.path == "/v2/agent":
                return httpx.Response(200, json={"id": "agent-1"}, request=request)
            if request.method == "GET" and "/v2/agent/agent-1" in request.url.path:
                return httpx.Response(
                    200,
                    json={"status": "completed", "data": {"result": "answer"}},
                    request=request,
                )
            return httpx.Response(404, json={"error": "not found"}, request=request)

        transport = httpx.MockTransport(_handler)
        client = GroktocrawlClient(base_url="http://test:8080", api_key=None)
        client._client = httpx.AsyncClient(
            base_url=client._base_url,
            headers=client._headers(),
            transport=transport,
        )

        result = await client.agent("explain gravity")
        assert result["status"] == "completed"
        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_answer_endpoint(self):
        client = _make_client(
            {
                ("POST", "/v2/answer"): _json_handler({"answer": "42", "sources": []}),
            }
        )
        result = await client.answer("life meaning")
        assert result["answer"] == "42"

    @pytest.mark.asyncio
    async def test_extract_creates_and_polls(self):
        call_count = 0

        def _handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if request.method == "POST" and request.url.path == "/v2/extract":
                return httpx.Response(200, json={"id": "ext-1"}, request=request)
            if request.method == "GET" and "/v2/extract/ext-1" in request.url.path:
                return httpx.Response(
                    200,
                    json={"status": "completed", "data": {"key": "val"}},
                    request=request,
                )
            return httpx.Response(404, json={"error": "not found"}, request=request)

        transport = httpx.MockTransport(_handler)
        client = GroktocrawlClient(base_url="http://test:8080", api_key=None)
        client._client = httpx.AsyncClient(
            base_url=client._base_url,
            headers=client._headers(),
            transport=transport,
        )

        result = await client.extract("https://example.com", {"type": "object"})
        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_find_similar_endpoint(self):
        client = _make_client(
            {
                ("POST", "/v2/find-similar"): _json_handler(
                    {"similar": ["https://b.com"]}
                ),
            }
        )
        result = await client.find_similar("https://a.com")
        assert result["similar"] == ["https://b.com"]

    @pytest.mark.asyncio
    async def test_enrich_endpoint(self):
        client = _make_client(
            {
                ("POST", "/v2/enrich"): _json_handler({"summary": "enriched content"}),
            }
        )
        result = await client.enrich("https://example.com")
        assert result["summary"] == "enriched content"

    @pytest.mark.asyncio
    async def test_batch_scrape_creates_and_polls(self):
        call_count = 0

        def _handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if request.method == "POST" and request.url.path == "/v2/batch/scrape":
                return httpx.Response(200, json={"id": "batch-1"}, request=request)
            if (
                request.method == "GET"
                and "/v2/batch/scrape/batch-1" in request.url.path
            ):
                return httpx.Response(
                    200, json={"status": "completed"}, request=request
                )
            return httpx.Response(404, json={"error": "not found"}, request=request)

        transport = httpx.MockTransport(_handler)
        client = GroktocrawlClient(base_url="http://test:8080", api_key=None)
        client._client = httpx.AsyncClient(
            base_url=client._base_url,
            headers=client._headers(),
            transport=transport,
        )

        result = await client.batch_scrape(["https://a.com", "https://b.com"])
        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_generate_llmstxt_creates_and_polls(self):
        call_count = 0

        def _handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if request.method == "POST" and request.url.path == "/v2/generate-llmstxt":
                return httpx.Response(200, json={"id": "llmstxt-1"}, request=request)
            if (
                request.method == "GET"
                and "/v2/generate-llmstxt/llmstxt-1" in request.url.path
            ):
                return httpx.Response(
                    200, json={"status": "completed"}, request=request
                )
            return httpx.Response(404, json={"error": "not found"}, request=request)

        transport = httpx.MockTransport(_handler)
        client = GroktocrawlClient(base_url="http://test:8080", api_key=None)
        client._client = httpx.AsyncClient(
            base_url=client._base_url,
            headers=client._headers(),
            transport=transport,
        )

        result = await client.generate_llmstxt("https://example.com")
        assert result["status"] == "completed"


# ═══════════════════════════════════════════════════════════════════
# VAL-MCP-K04: Recovery after transient outage
# ═══════════════════════════════════════════════════════════════════


class TestRecoveryAfterOutage:
    """VAL-MCP-K04: agent-svc recovery after transient outage."""

    @pytest.mark.asyncio
    async def test_recovery_after_connect_error(self):
        """After a ConnectError, subsequent requests succeed without restart."""
        failures = 0

        def _flaky(request: httpx.Request) -> httpx.Response:
            nonlocal failures
            if failures < 2:
                failures += 1
                raise httpx.ConnectError("Connection refused", request=request)
            return httpx.Response(200, json={"success": True}, request=request)

        transport = httpx.MockTransport(_flaky)
        client = GroktocrawlClient(
            base_url="http://test:8080",
            api_key=None,
            default_timeout=5.0,
        )
        client._client = httpx.AsyncClient(
            base_url=client._base_url,
            headers=client._headers(),
            transport=transport,
        )

        # First two calls fail with connection error
        r1 = await client.scrape("https://example.com")
        assert "error" in r1
        assert "connection" in r1["error"].lower()

        r2 = await client.scrape("https://example.com")
        assert "error" in r2
        assert "connection" in r2["error"].lower()

        # Third call succeeds — recovery without restart
        r3 = await client.scrape("https://example.com")
        assert r3.get("success") is True

        # No need to re-create client
        assert failures == 2
