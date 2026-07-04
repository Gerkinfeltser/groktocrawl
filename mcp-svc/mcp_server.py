"""MCP server exposing GroktoCrawl tools via Model Context Protocol.

Uses FastMCP from the official mcp SDK (v1.x) with Streamable HTTP
transport.  Tools are thin wrappers around GroktocrawlClient which
proxies to the agent-svc API.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from browser_handler import BrowserHandler
from groktocrawl_client import GroktocrawlClient
from session_store import SessionStore

logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────

API_URL = os.environ.get("GROKTOCRAWL_API_URL", "http://localhost:8080")
API_KEY = os.environ.get("GROKTOCRAWL_API_KEY") or None
PORT = int(os.environ.get("PORT", "8083"))

# ── Shared state ───────────────────────────────────────────────────

_client = GroktocrawlClient(base_url=API_URL, api_key=API_KEY)
_session_store = SessionStore()
_browser_handler = BrowserHandler(client=_client, session_store=_session_store)

# ── FastMCP server ─────────────────────────────────────────────────

server = FastMCP("groktocrawl-mcp")


# ── Tools: Phase 1 (core) ────────────────────────────────────────


@server.tool()
async def scrape(url: str, formats: list[str] | None = None) -> dict[str, Any]:
    """Scrape a URL and return its content as markdown.

    Args:
        url: The URL to scrape (must be http:// or https://).
        formats: Optional list of output formats. Default is ['markdown'].
            Supported: markdown, html, links, screenshot, rawHtml,
            screenshot@fullPage, images.
    """
    _session_store.cleanup_expired()
    result = await _client.scrape(url=url, formats=formats)
    return result


@server.tool()
async def search(
    query: str,
    limit: int = 5,
    sources: list[str] | None = None,
) -> dict[str, Any]:
    """Search the web for a query.

    Args:
        query: The search query string.
        limit: Maximum number of results to return (default 5).
        sources: Optional source type filters (e.g. ['web', 'news', 'images']).
    """
    _session_store.cleanup_expired()
    result = await _client.search(query=query, limit=limit, sources=sources)
    return result


@server.tool()
async def agent(
    prompt: str,
    model: str | None = None,
    output_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run autonomous research: search → scrape → synthesize.

    Creates a research job, polls until complete, and returns the
    synthesized answer with cited sources.

    Args:
        prompt: What the agent should research (max 100k chars).
        model: Optional per-request LLM override (e.g. 'gpt-4o').
        output_schema: Optional JSON Schema for structured output.
    """
    _session_store.cleanup_expired()
    result = await _client.agent(
        prompt=prompt, model=model, output_schema=output_schema
    )
    return result


@server.tool()
async def answer(
    question: str,
    output_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Grounded Q&A: search → scrape → LLM answer with inline citations.

    Synchronous single-turn endpoint designed for 1-3s latency.

    Args:
        question: Natural language question (max 10k chars).
        output_schema: Optional JSON Schema for structured output.
    """
    _session_store.cleanup_expired()
    result = await _client.answer(question=question, output_schema=output_schema)
    return result


@server.tool()
async def crawl(
    url: str,
    max_pages: int | None = None,
    max_depth: int | None = None,
) -> dict[str, Any]:
    """Recursively crawl a website, returning all discovered pages.

    Creates a crawl job, polls until complete, and returns scraped
    pages with metadata.

    Args:
        url: The starting URL to crawl (must be http:// or https://).
        max_pages: Maximum pages to scrape (default unlimited).
        max_depth: Maximum link-follow depth (default 2).
    """
    _session_store.cleanup_expired()
    result = await _client.crawl(url=url, max_pages=max_pages, max_depth=max_depth)
    return result


@server.tool()
async def map(url: str, limit: int = 100) -> dict[str, Any]:
    """Discover all URLs linked from a page.

    Args:
        url: The page URL to map (must be http:// or https://).
        limit: Maximum number of links to return (default 100).
    """
    _session_store.cleanup_expired()
    result = await _client.map(url=url, limit=limit)
    return result


@server.tool()
async def extract(
    url: str,
    schema: dict[str, Any],
) -> dict[str, Any]:
    """Extract structured data from a URL using a JSON Schema.

    Creates an extract job, polls until complete, and returns the
    structured data.

    Args:
        url: The URL to extract data from.
        schema: JSON Schema describing the desired output structure.
    """
    _session_store.cleanup_expired()
    result = await _client.extract(url=url, schema=schema)
    return result


@server.tool()
async def parse(file_url: str) -> dict[str, Any]:
    """Parse a document (PDF, DOCX, etc.) to markdown.

    Downloads the file from the given URL and sends it to the parse
    service.

    Args:
        file_url: URL of the document file to parse.
    """
    _session_store.cleanup_expired()
    result = await _client.parse(file_url=file_url)
    return result


@server.tool()
async def batch_scrape(urls: list[str]) -> dict[str, Any]:
    """Scrape multiple URLs in a single batch job.

    Creates a batch scrape job, polls until complete, and returns
    all results.

    Args:
        urls: List of URLs to scrape.
    """
    _session_store.cleanup_expired()
    result = await _client.batch_scrape(urls=urls)
    return result


@server.tool()
async def find_similar(url: str) -> dict[str, Any]:
    """Find pages semantically similar to a given URL.

    Uses vector embeddings to discover related content.

    Args:
        url: The reference URL to find similar pages for.
    """
    _session_store.cleanup_expired()
    result = await _client.find_similar(url=url)
    return result


@server.tool()
async def enrich(url: str) -> dict[str, Any]:
    """Enrich a URL with web-sourced structured data.

    Searches for additional context and extracts structured fields.

    Args:
        url: The URL or entity to enrich.
    """
    _session_store.cleanup_expired()
    result = await _client.enrich(url=url)
    return result


@server.tool()
async def generate_llmstxt(url: str) -> dict[str, Any]:
    """Generate an llms.txt file for a website.

    Crawls the site and produces a structured markdown file listing
    key pages for LLM consumption.

    Args:
        url: The website URL to generate llms.txt for.
    """
    _session_store.cleanup_expired()
    result = await _client.generate_llmstxt(url=url)
    return result


@server.tool()
async def health() -> dict[str, Any]:
    """Check the GroktoCrawl server health status."""
    _session_store.cleanup_expired()
    result = await _client.health()
    return result


# ── Tools: Phase 2 (browser + monitor) ───────────────────────────


@server.tool()
async def browser_session_create(ttl: int = 300) -> dict[str, Any]:
    """Create a new browser session for interactive page control.

    Args:
        ttl: Session time-to-live in seconds (30-3600, default 300).
    """
    _session_store.cleanup_expired()
    result = await _browser_handler.create_session(ttl=ttl)
    return result


@server.tool()
async def browser_session_action(
    session_id: str,
    action: str,
    url: str | None = None,
    selector: str | None = None,
    text: str | None = None,
    script: str | None = None,
    timeout: int = 10000,
) -> dict[str, Any]:
    """Execute an action in an existing browser session.

    Args:
        session_id: The browser session ID from browser_session_create.
        action: Action type: navigate, click, type, screenshot, scroll,
            wait, getContent, executeScript.
        url: URL for navigate action.
        selector: CSS selector for click/type/select actions.
        text: Text to type for write/type action.
        script: JavaScript for executeScript action.
        timeout: Action timeout in milliseconds (default 10000).
    """
    _session_store.cleanup_expired()
    kwargs: dict[str, Any] = {}
    if url is not None:
        kwargs["url"] = url
    if selector is not None:
        kwargs["selector"] = selector
    if text is not None:
        kwargs["text"] = text
    if script is not None:
        kwargs["script"] = script
    if timeout != 10000:
        kwargs["timeout"] = timeout
    result = await _browser_handler.execute_action(
        session_id=session_id, action=action, **kwargs
    )
    return result


@server.tool()
async def browser_session_destroy(session_id: str) -> dict[str, Any]:
    """Destroy a browser session and free its resources.

    Args:
        session_id: The browser session ID to destroy.
    """
    _session_store.cleanup_expired()
    result = await _browser_handler.destroy_session(session_id=session_id)
    return result


@server.tool()
async def monitor_create(url: str, schedule: str) -> dict[str, Any]:
    """Create a change monitor that periodically checks a URL for updates.

    Args:
        url: The URL to monitor for changes.
        schedule: Cron expression for check frequency (e.g. '0 */6 * * *').
    """
    _session_store.cleanup_expired()
    result = await _client.monitor_create(url=url, schedule=schedule)
    return result


@server.tool()
async def monitor_list() -> dict[str, Any]:
    """List all active change monitors."""
    _session_store.cleanup_expired()
    result = await _client.monitor_list()
    return result


@server.tool()
async def monitor_delete(monitor_id: str) -> dict[str, Any]:
    """Delete a change monitor by ID.

    Args:
        monitor_id: The monitor ID to delete.
    """
    _session_store.cleanup_expired()
    result = await _client.monitor_delete(monitor_id=monitor_id)
    return result


# ── Auth middleware ────────────────────────────────────────────────


class _AuthMiddleware:
    """ASGI middleware that enforces Bearer token auth when
    GROKTOCRAWL_API_KEY is set in the environment.
    """

    def __init__(self, app: Any, api_key: str) -> None:
        self._app = app
        self._api_key = api_key

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        # Extract Authorization header from the ASGI scope
        headers = dict(scope.get("headers", []))
        auth_bytes = headers.get(b"authorization", b"")
        auth_str = auth_bytes.decode() if auth_bytes else ""

        if not auth_str.startswith("Bearer ") or auth_str[7:] != self._api_key:
            # Return 401
            body = json.dumps({"error": "Unauthorized"}).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        await self._app(scope, receive, send)


# ── Entrypoint ─────────────────────────────────────────────────────


def main() -> None:
    """Start the MCP server with Streamable HTTP transport."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info(
        "Starting groktocrawl-mcp on port %s (API: %s)",
        PORT,
        API_URL,
    )
    if API_KEY:
        logger.info("API key auth enabled")
        import uvicorn

        app = server.streamable_http_app()
        app.add_middleware(_AuthMiddleware, api_key=API_KEY)
        uvicorn.run(app, host="0.0.0.0", port=PORT)
    else:
        logger.info("No API key set — auth disabled")
        server.run(transport="streamable-http", host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()
