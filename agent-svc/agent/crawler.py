"""CrawlEngine — BFS crawl orchestrator for GroktoCrawl.

Manages a queue of (url, depth) tuples, tracks seen URLs for dedup,
enforces ``max_pages`` and ``max_depth`` limits, uses the shared
``LinkExtractor`` to discover child links, integrates with
``ScraperClient`` for per-page fetching, and writes progress to the
job store for status polling.
"""

from __future__ import annotations

import collections.abc
import json
import logging
import posixpath
import re
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
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
        verbose: If True, track filtered-out URLs with reasons.
        allow_subdomains: If True, follow links to subdomains.
        allow_external_links: If True, follow links to external domains.
    """

    max_pages: int = 10
    max_depth: int = 2
    include_paths: list[str] | None = None
    exclude_paths: list[str] | None = None
    ignore_query_parameters: bool = False
    regex_on_full_url: bool = False
    verbose: bool = False
    allow_subdomains: bool = False
    allow_external_links: bool = False
    max_duration_seconds: int = 1800
    idle_timeout_seconds: int = 300


@dataclass
class CrawlResult:
    """Result of a crawl run."""

    pages: list[dict] = field(default_factory=list)
    total: int = 0
    completed: int = 0
    errors: list[dict] = field(default_factory=list)
    filtered_out: list[dict] = field(default_factory=list)


# ── Public functions ─────────────────────────────────────────────


def _clean_path(path: str) -> str:
    """Clean up a URL path by collapsing dot segments and normalizing.

    Collapses ``/./`` and ``/../`` segments, and reduces ``/.`` at the
    end to ``/``.
    """
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


def _matches_pattern(
    target: str, pattern: str, regex_on_full_url: bool = False
) -> bool:
    """Check whether ``target`` matches a single path pattern.

    Args:
        target: The string (path or full URL) to check.
        pattern: The glob or regex pattern to match against.
        regex_on_full_url: If True, ``pattern`` is a regex; else glob.

    Returns:
        True if the target matches the pattern.
    """
    if regex_on_full_url:
        try:
            return bool(re.search(pattern, target))
        except re.error:
            return False
    else:
        regex = _glob_to_regex(pattern)
        try:
            return bool(re.search(regex, target))
        except re.error:
            return False


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
        self._filtered_out: list[dict] = []
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

    async def run(
        self,
        start_url: str,
        job_id: str | None = None,
        page_callback: collections.abc.Callable[
            [str, dict], collections.abc.Awaitable[None]
        ]
        | None = None,
    ) -> CrawlResult:
        """Execute a BFS crawl starting from ``start_url``.

        Args:
            start_url: The URL to begin crawling from.
            job_id: Optional job ID for periodic store updates and
                cancellation checking.
            page_callback: Optional async callback invoked after each
                successful page scrape, receiving (job_id, page_dict).

        Returns:
            A ``CrawlResult`` with scraped pages, totals, and errors.
        """
        parsed_start = urlparse(start_url)
        base_domain = parsed_start.hostname.lower() if parsed_start.hostname else ""

        # Seed the BFS queue
        self._queue.append((start_url, 0))
        last_store_update = time.monotonic()
        crawl_start_time = time.monotonic()
        last_completion_time = crawl_start_time

        while self._queue and len(self._pages) < self.options.max_pages:
            if self._cancel_flag:
                logger.info("Crawl cancelled via cancel flag")
                break

            # Cooperative cancellation: check Redis for cancelled status
            # between pages (checked before each page scrape).
            if self.store is not None and job_id is not None:
                job_meta = self.store.get_job(job_id)
                if job_meta and job_meta.get("status") == "cancelled":
                    self._cancel_flag = True
                    logger.info("Crawl %s cancelled via Redis status check", job_id)
                    break

            # Maximum duration timeout check
            now = time.monotonic()
            elapsed = now - crawl_start_time
            if elapsed > self.options.max_duration_seconds:
                logger.warning(
                    "Crawl %s exceeded max duration of %ds (elapsed=%.1fs)",
                    job_id,
                    self.options.max_duration_seconds,
                    elapsed,
                )
                raise TimeoutError(
                    f"Crawl exceeded max duration of {self.options.max_duration_seconds}s"
                )

            # Idle timeout (stuck-crawl) check
            idle_elapsed = now - last_completion_time
            if idle_elapsed > self.options.idle_timeout_seconds:
                logger.warning(
                    "Crawl %s idle for %ds (timeout=%ds) — killing zombie crawl",
                    job_id,
                    idle_elapsed,
                    self.options.idle_timeout_seconds,
                )
                raise TimeoutError(
                    f"Crawl idle for {idle_elapsed:.0f}s — "
                    f"exceeded idle timeout of {self.options.idle_timeout_seconds}s"
                )

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

            # Determine the URL for path filtering.
            # When ignore_query_parameters is True, strip query params
            # before matching so that patterns match against the path
            # only (VAL-SCOPE-073).
            filter_url = (
                urlparse(url)._replace(query="").geturl()
                if self.options.ignore_query_parameters
                else url
            )
            if not _match_path(
                filter_url,
                self.options.include_paths,
                self.options.exclude_paths,
                self.options.regex_on_full_url,
            ):
                if self.options.verbose:
                    filter_reason = self._get_filter_reason(filter_url)
                    if filter_reason:
                        self._filtered_out.append(filter_reason)
                logger.debug("Skipping URL excluded by path filter: %s", url)
                continue

            # Scrape the page with timing
            scrape_start = time.monotonic()
            result = await self.scraper.scrape(url)
            scrape_duration_ms = int((time.monotonic() - scrape_start) * 1000)

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

            # Record successful page with enriched metadata
            data = result.get("data", {})
            metadata = data.get("metadata") or {}
            og = metadata.get("og") or {}
            meta = metadata.get("meta") or {}
            title = (
                og.get("title")
                or meta.get("title")
                or data.get("title")
                or metadata.get("title")
                or ""
            )
            description = (
                og.get("description")
                or meta.get("description")
                or metadata.get("description")
                or ""
            )
            source = data.get("source", "unknown")
            status_code = metadata.get("statusCode") or data.get("status_code") or 200
            content_type = (
                metadata.get("content-type")
                or metadata.get("contentType")
                or "text/html"
            )
            scraped_at = datetime.now(UTC).isoformat()

            page = {
                "url": url,
                "markdown": data.get("markdown", ""),
                "metadata": {
                    "title": title,
                    "description": description,
                    "source": source,
                },
                "title": title,
                "status_code": status_code,
                "content_type": content_type,
                "scraped_at": scraped_at,
                "duration_ms": scrape_duration_ms,
            }
            self._pages.append(page)
            last_completion_time = time.monotonic()

            # Fire per-page webhook callback
            if page_callback is not None and job_id is not None:
                try:
                    await page_callback(job_id, page)
                except Exception:
                    logger.warning(
                        "Page callback failed for %s (job %s)",
                        url,
                        job_id,
                        exc_info=True,
                    )

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
            filtered_out=self._filtered_out,
        )

    def normalize_url(self, url: str) -> str:
        """Normalize a URL using this engine's options."""
        return normalize_url(
            url, ignore_query_parameters=self.options.ignore_query_parameters
        )

    def cancel(self) -> None:
        """Signal the crawl to stop at the next opportunity."""
        self._cancel_flag = True

    def _get_filter_reason(self, url: str) -> dict | None:
        """Determine which path filter excluded a URL and why.

        Only called when ``verbose`` is True and the URL has already
        been determined to NOT pass ``_match_path()``.

        Returns:
            A dict with ``url``, ``reason``, and ``pattern`` keys, or
            ``None`` if no filter reason could be determined.
        """
        target = url if self.options.regex_on_full_url else urlparse(url).path

        # Check exclude_paths first (they bypass include_paths)
        if self.options.exclude_paths:
            for pattern in self.options.exclude_paths:
                if _matches_pattern(target, pattern, self.options.regex_on_full_url):
                    return {
                        "url": url,
                        "reason": "exclude_paths",
                        "pattern": pattern,
                    }

        # Check include_paths
        if self.options.include_paths:
            for pattern in self.options.include_paths:
                if _matches_pattern(target, pattern, self.options.regex_on_full_url):
                    # Would match include, so not excluded by include
                    return {
                        "url": url,
                        "reason": "include_paths",
                        "pattern": None,
                    }
            # No include_paths matched
            return {
                "url": url,
                "reason": "include_paths",
                "pattern": None,
            }

        return None

    def _update_store(self, job_id: str) -> None:
        """Write current progress to the job data key (not meta).

        Updates only the ``data`` key in Valkey so the job's ``meta``
        status (``processing``) remains unchanged during the crawl.
        The caller's final ``store.complete_job()`` call sets both the
        final data and the ``completed`` status.
        """
        if self.store is None:
            return
        try:
            payload = {
                "completed": len(self._pages),
                "total": len(self._pages) + len(self._queue),
                "pages": self._pages,
                "errors": self._errors,
            }
            # Write data key directly without changing meta status
            self.store.redis.set(
                f"job:{job_id}:data",
                json.dumps(payload),
                ex=86400,
            )
        except Exception:
            logger.warning("Failed to update job store", exc_info=True)
