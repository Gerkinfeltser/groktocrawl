"""CrawlEngine — BFS crawl orchestrator for GroktoCrawl.

Manages a queue of (url, depth) tuples, tracks seen URLs for dedup,
enforces ``max_pages`` and ``max_depth`` limits, uses the shared
``LinkExtractor`` to discover child links, integrates with
``ScraperClient`` for per-page fetching, and writes progress to the
job store for status polling.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from urllib.parse import urlparse, urlunparse

import httpx

from .link_extractor import extract_links, filter_links
from .scraper_client import ScraperClient
from .store import JobStore

logger = logging.getLogger(__name__)


# ── Data types ───────────────────────────────────────────────────


@dataclass
class CrawlOptions:
    """Options controlling crawl behavior.

    Attributes:
        max_pages: Maximum number of pages to scrape (hard stop).
        max_depth: Maximum link-follow depth. Pages at max_depth are
            scraped but their links are not followed.
        include_paths: If set, only URLs whose path matches at least one
            of these glob/regex patterns are scraped.
        exclude_paths: URLs whose path matches any of these glob/regex
            patterns are excluded (takes precedence over include).
        ignore_query_parameters: If True, query-string variants of the
            same base URL are collapsed to one fetch.
        regex_on_full_url: If True, include/exclude paths are treated as
            regex patterns (default: glob).
        allow_subdomains: If True, follow links to subdomains.
        allow_external_links: If True, follow links to external domains.
    """

    max_pages: int = 10
    max_depth: int = 2
    include_paths: list[str] | None = None
    exclude_paths: list[str] | None = None
    ignore_query_parameters: bool = False
    regex_on_full_url: bool = False
    allow_subdomains: bool = False
    allow_external_links: bool = False


@dataclass
class CrawlResult:
    """Result of a crawl run."""

    pages: list[dict] = field(default_factory=list)
    total: int = 0
    completed: int = 0
    errors: list[dict] = field(default_factory=list)


# ── Public functions ─────────────────────────────────────────────


def _clean_path(path: str) -> str:
    """Clean up a URL path by collapsing dot segments and normalizing.

    Collapses ``/./`` and ``/../`` segments, and reduces ``/.`` at the
    end to ``/``.
    """
    import posixpath

    if not path:
        return "/"

    # posixpath.normpath collapses dot segments
    cleaned = posixpath.normpath(path)

    # normpath strips trailing slash, but root should remain /
    if not cleaned:
        return "/"

    return cleaned


def normalize_url(url: str, ignore_query_parameters: bool = False) -> str:
    """Normalize a URL for dedup within a crawl run.

    Steps:
        1. Strip fragment identifier.
        2. Lowercase scheme and host.
        3. Remove default ports (80 for http, 443 for https).
        4. Normalize trailing slash (remove for non-root paths).
        5. Collapse ``/./`` and ``/../`` path segments.
        6. Optionally strip query string entirely.
        7. Sort query parameters if keeping them.

    Args:
        url: The URL to normalize.
        ignore_query_parameters: If True, strip the query string.

    Returns:
        Normalized URL string.
    """
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    hostname = parsed.hostname.lower() if parsed.hostname else ""
    port = parsed.port
    path = _clean_path(parsed.path or "/")

    # Build netloc without default ports
    netloc = hostname
    if port is not None and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    ):
        netloc = f"{hostname}:{port}"

    # Normalize trailing slash for non-root paths
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    # Handle query parameters
    if ignore_query_parameters:
        query = ""
    else:
        # Sort query params for consistency
        parsed_qs = parsed.query
        if parsed_qs:
            params = sorted(parsed_qs.split("&"))
            query = "&".join(params)
        else:
            query = ""

    normalized = urlunparse((scheme, netloc, path, parsed.params, query, ""))
    return normalized


async def fetch_html(url: str, timeout: float = 15.0) -> str | None:
    """Fetch raw HTML from a URL for link extraction purposes.

    This is a lightweight HTTP GET that follows redirects and returns
    the response text. It is used by ``CrawlEngine`` to discover child
    links from scraped pages, separate from the content scraping done
    via ``ScraperClient``.

    Args:
        url: The URL to fetch.
        timeout: HTTP request timeout in seconds.

    Returns:
        The response text (HTML), or ``None`` if the fetch failed.
    """
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                return resp.text
            logger.debug("fetch_html got status %d for %s", resp.status_code, url)
            return None
    except Exception as e:
        logger.debug("fetch_html failed for %s: %s", url, e)
        return None


def _match_path(
    url: str,
    include_paths: list[str] | None,
    exclude_paths: list[str] | None,
    regex_on_full_url: bool = False,
) -> bool:
    """Check whether a URL passes include/exclude path filters.

    Args:
        url: The full URL to check.
        include_paths: If set, URL must match at least one pattern.
        exclude_paths: If set, URL must not match any pattern
            (takes precedence).
        regex_on_full_url: If True, patterns are regex; else glob.

    Returns:
        True if the URL should be crawled (passes all filters).
    """
    import re

    target = url if regex_on_full_url else urlparse(url).path

    if regex_on_full_url:
        # Regex mode
        if exclude_paths:
            for pattern in exclude_paths:
                try:
                    if re.search(pattern, target):
                        return False
                except re.error:
                    continue
        if include_paths:
            for pattern in include_paths:
                try:
                    if re.search(pattern, target):
                        return True
                except re.error:
                    continue
            return False  # include_paths set but none matched
    else:
        # Glob mode — convert glob patterns to regex
        if exclude_paths:
            for pattern in exclude_paths:
                regex = _glob_to_regex(pattern)
                try:
                    if re.search(regex, target):
                        return False
                except re.error:
                    continue
        if include_paths:
            for pattern in include_paths:
                regex = _glob_to_regex(pattern)
                try:
                    if re.search(regex, target):
                        return True
                except re.error:
                    continue
            return False  # include_paths set but none matched

    return True  # No include_paths constraint, or passed all


def _glob_to_regex(pattern: str) -> str:
    """Convert a simple glob pattern to an anchored regex pattern.

    Supports ``*`` (match any chars except ``/``), ``**`` (match any
    chars including ``/``), and ``?`` (match single char).

    The returned pattern is anchored with ``^`` and ``$`` so that
    ``re.search`` matches the full target string, not a substring.
    """
    i, n = 0, len(pattern)
    inner: list[str] = []
    while i < n:
        c = pattern[i]
        if c == "*" and i + 1 < n and pattern[i + 1] == "*":
            inner.append(".*")
            i += 2
        elif c == "*":
            inner.append("[^/]*")
            i += 1
        elif c == "?":
            inner.append(".")
            i += 1
        elif c in ".^$+{}[]\\|()":
            inner.append("\\" + c)
            i += 1
        else:
            inner.append(c)
            i += 1
    return "^" + "".join(inner) + "$"


# ── CrawlEngine ──────────────────────────────────────────────────


class CrawlEngine:
    """BFS crawl orchestrator.

    Usage::

        engine = CrawlEngine(scraper_client, options=CrawlOptions(max_pages=5))
        result = await engine.run("https://example.com", job_id="...")
    """

    def __init__(
        self,
        scraper_client: ScraperClient,
        store: JobStore | None = None,
        options: CrawlOptions | None = None,
    ):
        self.scraper = scraper_client
        self.store = store
        self.options = options or CrawlOptions()
        self._seen: set[str] = set()
        self._queue: deque[tuple[str, int]] = deque()
        self._pages: list[dict] = []
        self._errors: list[dict] = []
        self._cancel_flag: bool = False
        self._update_interval: float = 1.0
        self._html_client: httpx.AsyncClient | None = None

    async def _get_html(self, url: str) -> str | None:
        """Get HTML for a URL, using an internal persistent client."""
        if self._html_client is None:
            self._html_client = httpx.AsyncClient(follow_redirects=True, timeout=15.0)
        try:
            resp = await self._html_client.get(url)
            if resp.status_code == 200:
                return resp.text
            return None
        except Exception:
            return None

    async def close(self) -> None:
        """Close the internal HTTP client."""
        if self._html_client is not None:
            await self._html_client.aclose()
            self._html_client = None

    async def run(self, start_url: str, job_id: str | None = None) -> CrawlResult:
        """Execute a BFS crawl starting from ``start_url``.

        Args:
            start_url: The URL to begin crawling from.
            job_id: Optional job ID for periodic store updates.

        Returns:
            A ``CrawlResult`` with scraped pages, totals, and errors.
        """
        parsed_start = urlparse(start_url)
        base_domain = parsed_start.hostname.lower() if parsed_start.hostname else ""

        # Seed the BFS queue
        self._queue.append((start_url, 0))
        last_store_update = time.monotonic()

        while self._queue and len(self._pages) < self.options.max_pages:
            if self._cancel_flag:
                logger.info("Crawl cancelled via cancel flag")
                break

            url, depth = self._queue.popleft()
            normalized = self.normalize_url(url)

            # Dedup check
            if normalized in self._seen:
                logger.debug("Skipping already-seen URL: %s", url)
                continue

            # Max depth check: pages at max_depth are scraped but not
            # followed; pages beyond max_depth are skipped entirely.
            if depth > self.options.max_depth:
                logger.debug("Skipping URL beyond max_depth: %s (depth=%d)", url, depth)
                continue

            # Mark as seen immediately to prevent re-enqueue
            self._seen.add(normalized)

            # Path filter check
            if not _match_path(
                url,
                self.options.include_paths,
                self.options.exclude_paths,
                self.options.regex_on_full_url,
            ):
                logger.debug("Skipping URL excluded by path filter: %s", url)
                continue

            # Scrape the page
            result = await self.scraper.scrape(url)

            if not result.get("success"):
                error_msg = result.get("error", "Unknown scrape error")
                self._errors.append({"url": url, "error": error_msg})
                logger.warning("Scrape failed for %s: %s", url, error_msg)

                # Start URL failure — return error immediately
                if depth == 0:
                    logger.error("Start URL scrape failed: %s", error_msg)
                    result_obj = CrawlResult(
                        pages=[],
                        total=0,
                        completed=0,
                        errors=self._errors,
                    )
                    await self.close()
                    return result_obj
                continue

            # Record successful page
            data = result.get("data", {})
            page = {
                "url": url,
                "markdown": data.get("markdown", ""),
            }
            self._pages.append(page)

            # Discover child links if within max_depth
            if depth < self.options.max_depth:
                html = await self._get_html(url)
                if html:
                    child_links = extract_links(html, url)
                    child_links = filter_links(
                        child_links,
                        base_domain=base_domain,
                        allow_subdomains=self.options.allow_subdomains,
                        allow_external_links=self.options.allow_external_links,
                    )
                    for child_url in child_links:
                        child_normalized = self.normalize_url(child_url)
                        if child_normalized not in self._seen:
                            self._queue.append((child_url, depth + 1))

            # Periodic job store update
            if self.store is not None and job_id is not None:
                now = time.monotonic()
                if now - last_store_update >= self._update_interval:
                    self._update_store(job_id)
                    last_store_update = now

        # Final store update
        if self.store is not None and job_id is not None:
            self._update_store(job_id)

        await self.close()

        return CrawlResult(
            pages=self._pages,
            total=len(self._pages) + len(self._queue),
            completed=len(self._pages),
            errors=self._errors,
        )

    def normalize_url(self, url: str) -> str:
        """Normalize a URL using this engine's options."""
        return normalize_url(
            url, ignore_query_parameters=self.options.ignore_query_parameters
        )

    def cancel(self) -> None:
        """Signal the crawl to stop at the next opportunity."""
        self._cancel_flag = True

    def _update_store(self, job_id: str) -> None:
        """Write current progress to the job store."""
        if self.store is None:
            return
        try:
            payload = {
                "completed": len(self._pages),
                "total": len(self._pages) + len(self._queue),
                "pages": self._pages,
                "errors": self._errors,
            }
            self.store.complete_job(job_id, payload)
        except Exception:
            logger.warning("Failed to update job store", exc_info=True)
