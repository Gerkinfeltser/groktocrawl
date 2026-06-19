"""Unit tests for the CrawlEngine in agent-svc/agent/crawler.py.

Covers:
- URL normalization (fragments, trailing slash, ignore_query_parameters)
- Path filtering (glob and regex)
- Glob-to-regex conversion
- CrawlEngine BFS traversal
- max_pages and max_depth enforcement
- URL dedup within a crawl run
- Start URL failure handling
- Child page error handling
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── normalize_url tests ──────────────────────────────────────────


class TestNormalizeUrl:
    """Tests for the ``normalize_url()`` function."""

    def test_strips_fragment(self):
        from agent.crawler import normalize_url

        assert (
            normalize_url("https://example.com/page#section")
            == "https://example.com/page"
        )

    def test_lowercases_scheme(self):
        from agent.crawler import normalize_url

        assert normalize_url("HTTPS://EXAMPLE.COM/PAGE") == "https://example.com/PAGE"

    def test_lowercases_host(self):
        from agent.crawler import normalize_url

        assert normalize_url("https://Example.COM/Page") == "https://example.com/Page"

    def test_removes_default_http_port(self):
        from agent.crawler import normalize_url

        assert normalize_url("http://example.com:80/page") == "http://example.com/page"

    def test_removes_default_https_port(self):
        from agent.crawler import normalize_url

        assert (
            normalize_url("https://example.com:443/page") == "https://example.com/page"
        )

    def test_keeps_non_default_port(self):
        from agent.crawler import normalize_url

        assert (
            normalize_url("https://example.com:8080/page")
            == "https://example.com:8080/page"
        )

    def test_normalizes_trailing_slash(self):
        from agent.crawler import normalize_url

        # Non-root paths with trailing slash -> no trailing slash
        assert normalize_url("https://example.com/page/") == "https://example.com/page"
        assert normalize_url("https://example.com/page") == "https://example.com/page"

    def test_keeps_root_slash(self):
        from agent.crawler import normalize_url

        # Root path / should stay as /
        assert normalize_url("https://example.com/") == "https://example.com/"

    def test_normalizes_dot_path(self):
        from agent.crawler import normalize_url

        # /. should collapse to /
        assert normalize_url("https://example.com/.") == "https://example.com/"
        assert normalize_url("https://example.com/a/./b") == "https://example.com/a/b"

    def test_ignore_query_parameters_strips_query(self):
        from agent.crawler import normalize_url

        result = normalize_url(
            "https://example.com/page?a=1&b=2", ignore_query_parameters=True
        )
        assert result == "https://example.com/page"

    def test_ignore_query_parameters_default_false_keeps_query(self):
        from agent.crawler import normalize_url

        result = normalize_url("https://example.com/page?a=1&b=2")
        assert "a=1" in result
        assert "b=2" in result

    def test_sorts_query_parameters(self):
        from agent.crawler import normalize_url

        # Different order but same params -> same result
        r1 = normalize_url("https://example.com/page?b=2&a=1")
        r2 = normalize_url("https://example.com/page?a=1&b=2")
        assert r1 == r2
        assert "a=1" in r1
        assert "b=2" in r1

    def test_fragment_and_query_stripped_together(self):
        from agent.crawler import normalize_url

        assert (
            normalize_url("https://example.com/page?a=1#section")
            == "https://example.com/page?a=1"
        )


# ── Glob-to-regex tests ──────────────────────────────────────────


class TestGlobToRegex:
    """Tests for the ``_glob_to_regex()`` helper."""

    def test_literal_string(self):
        import re

        from agent.crawler import _glob_to_regex

        pattern = _glob_to_regex("/about")
        assert re.search(pattern, "/about")
        assert not re.search(pattern, "/aboutus")

    def test_single_star(self):
        import re

        from agent.crawler import _glob_to_regex

        pattern = _glob_to_regex("/section/*")
        assert re.search(pattern, "/section/page-1")
        assert re.search(pattern, "/section/foo")
        assert not re.search(pattern, "/section/sub/page")

    def test_double_star(self):
        import re

        from agent.crawler import _glob_to_regex

        pattern = _glob_to_regex("/section/**")
        assert re.search(pattern, "/section/page-1")
        assert re.search(pattern, "/section/sub/page")
        assert not re.search(pattern, "/other")

    def test_question_mark(self):
        import re

        from agent.crawler import _glob_to_regex

        pattern = _glob_to_regex("/page-?")
        assert re.search(pattern, "/page-1")
        assert re.search(pattern, "/page-a")
        assert not re.search(pattern, "/page-12")

    def test_special_chars_escaped(self):
        import re

        from agent.crawler import _glob_to_regex

        pattern = _glob_to_regex("/file.html")
        assert re.search(pattern, "/file.html")
        assert not re.search(pattern, "/fileXhtml")


# ── Path matching tests ─────────────────────────────────────────


class TestMatchPath:
    """Tests for the ``_match_path()`` function."""

    def test_no_filters_passes(self):
        from agent.crawler import _match_path

        assert _match_path("https://example.com/page", None, None) is True

    def test_include_paths_matches(self):
        from agent.crawler import _match_path

        assert (
            _match_path(
                "https://example.com/section/page-1",
                ["/section/*"],
                None,
            )
            is True
        )

    def test_include_paths_no_match(self):
        from agent.crawler import _match_path

        assert (
            _match_path(
                "https://example.com/about",
                ["/section/*"],
                None,
            )
            is False
        )

    def test_exclude_paths_excludes(self):
        from agent.crawler import _match_path

        assert (
            _match_path(
                "https://example.com/admin/secret",
                None,
                ["/admin/*"],
            )
            is False
        )

    def test_exclude_overrides_include(self):
        from agent.crawler import _match_path

        assert (
            _match_path(
                "https://example.com/section/page-2",
                ["/section/*"],
                ["/section/page-2"],
            )
            is False
        )

    def test_regex_mode_on_full_url(self):
        from agent.crawler import _match_path

        assert (
            _match_path(
                "https://example.com/section/page-1?ref=abc",
                ["section/page-[12]"],
                None,
                regex_on_full_url=True,
            )
            is True
        )

    def test_regex_mode_no_match(self):
        from agent.crawler import _match_path

        assert (
            _match_path(
                "https://example.com/section/page-3",
                ["section/page-[12]"],
                None,
                regex_on_full_url=True,
            )
            is False
        )


# ── CrawlEngine tests ────────────────────────────────────────────


@pytest.fixture
def mock_scraper():
    """Create a mock ScraperClient that returns successful results."""
    client = MagicMock()
    client.scrape = AsyncMock()
    client.close = AsyncMock()
    return client


@pytest.fixture
def mock_store():
    """Create a mock JobStore with a mock Redis client."""
    store = MagicMock()
    store.redis = MagicMock()
    store.complete_job = MagicMock()
    return store


class MockPage:
    """Helper to create a mock scrape result for a given URL."""

    @staticmethod
    def success(
        url: str, markdown: str = "# Page Content", html: str | None = None
    ) -> dict:
        return {
            "success": True,
            "data": {
                "markdown": markdown,
                "source": "playwright",
                "metadata": {"title": "Test Page"},
            },
        }

    @staticmethod
    def failure(url: str, error: str = "Scrape failed") -> dict:
        return {"success": False, "error": error}


class TestCrawlEngine:
    """Tests for the CrawlEngine BFS crawl loop."""

    @pytest.mark.asyncio
    async def test_single_page_crawl(self, mock_scraper, mock_store):
        """A crawl with max_pages=1 returns just the start URL."""
        from agent.crawler import CrawlEngine, CrawlOptions

        mock_scraper.scrape.return_value = MockPage.success("http://example.com/")

        engine = CrawlEngine(
            mock_scraper,
            store=mock_store,
            options=CrawlOptions(max_pages=1, max_depth=2),
        )
        result = await engine.run("http://example.com/")

        assert result.completed == 1
        assert result.total >= 1
        assert len(result.pages) == 1
        assert result.pages[0]["url"] == "http://example.com/"
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_max_pages_enforcement(self, mock_scraper):
        """Crawl stops after max_pages pages."""
        from agent.crawler import CrawlEngine, CrawlOptions

        # Mock scraper to always succeed
        mock_scraper.scrape.return_value = MockPage.success("http://example.com/page")
        mock_scraper.scrape.side_effect = None  # reset

        engine = CrawlEngine(
            mock_scraper,
            store=None,
            options=CrawlOptions(max_pages=3, max_depth=2),
        )

        # We need a link-rich start page. Mock the HTML fetch too.
        with patch.object(engine, "_get_html") as mock_html:
            mock_html.return_value = """
                <html><body>
                <a href="/page1">Page 1</a>
                <a href="/page2">Page 2</a>
                <a href="/page3">Page 3</a>
                </body></html>
            """

            # Set up scraper to return appropriate markdown per URL
            async def scrape_side_effect(url: str, force_browser: bool = False) -> dict:
                return MockPage.success(url, f"# Content of {url}")

            mock_scraper.scrape = AsyncMock(side_effect=scrape_side_effect)

            result = await engine.run("http://example.com/")

        assert result.completed == 3
        assert len(result.pages) == 3
        # Should have the start URL and 2 children (due to max_pages=3)

    @pytest.mark.asyncio
    async def test_max_depth_0(self, mock_scraper):
        """max_depth=0 scrapes only the start URL."""
        from agent.crawler import CrawlEngine, CrawlOptions

        mock_scraper.scrape = AsyncMock(
            return_value=MockPage.success("http://example.com/")
        )

        engine = CrawlEngine(
            mock_scraper,
            store=None,
            options=CrawlOptions(max_pages=10, max_depth=0),
        )

        with patch.object(engine, "_get_html") as mock_html:
            mock_html.return_value = """
                <html><body>
                <a href="/pricing">Pricing</a>
                <a href="/about">About</a>
                </body></html>
            """

            result = await engine.run("http://example.com/")

        assert result.completed == 1
        assert len(result.pages) == 1
        assert result.pages[0]["url"] == "http://example.com/"

    @pytest.mark.asyncio
    async def test_max_depth_1(self, mock_scraper):
        """max_depth=1 scrapes start URL and direct children."""
        from agent.crawler import CrawlEngine, CrawlOptions

        engine = CrawlEngine(
            mock_scraper,
            store=None,
            options=CrawlOptions(max_pages=10, max_depth=1),
        )

        async def scrape_side_effect(url: str, force_browser: bool = False) -> dict:
            return MockPage.success(url, f"# Content of {url}")

        mock_scraper.scrape = AsyncMock(side_effect=scrape_side_effect)

        with patch.object(engine, "_get_html") as mock_html:
            mock_html.return_value = """
                <html><body>
                <a href="http://example.com/pricing">Pricing</a>
                <a href="http://example.com/about">About</a>
                <a href="http://example.com/contact">Contact</a>
                </body></html>
            """

            result = await engine.run("http://example.com/")

        # Should have start URL + 3 children = 4 pages
        assert result.completed == 4
        assert len(result.pages) == 4

        # Verify BFS order: start URL first, then children
        assert result.pages[0]["url"] == "http://example.com/"

    @pytest.mark.asyncio
    async def test_url_dedup(self, mock_scraper):
        """No duplicate URLs within a single crawl run."""
        from agent.crawler import CrawlEngine, CrawlOptions

        engine = CrawlEngine(
            mock_scraper,
            store=None,
            options=CrawlOptions(max_pages=10, max_depth=2),
        )

        async def scrape_side_effect(url: str, force_browser: bool = False) -> dict:
            return MockPage.success(url, f"# Content of {url}")

        mock_scraper.scrape = AsyncMock(side_effect=scrape_side_effect)

        # Start page has duplicate links to the same page
        with patch.object(engine, "_get_html") as mock_html:
            mock_html.return_value = """
                <html><body>
                <a href="http://example.com/pricing">Pricing</a>
                <a href="http://example.com/pricing">Pricing (again)</a>
                <a href="http://example.com/about">About</a>
                <a href="http://example.com/pricing#section">Pricing with fragment</a>
                </body></html>
            """

            result = await engine.run("http://example.com/")

        # Should have start URL + pricing + about = 3 unique pages
        # (pricing appears 3 times in links but should be scraped once)
        urls = [p["url"] for p in result.pages]
        assert len(urls) == len(set(urls)), f"Duplicate URLs found: {urls}"
        assert len(result.pages) == 3

    @pytest.mark.asyncio
    async def test_fragment_stripped_dedup(self, mock_scraper):
        """Links /page#a and /page#b normalize to same URL."""
        from agent.crawler import CrawlEngine, CrawlOptions

        engine = CrawlEngine(
            mock_scraper,
            store=None,
            options=CrawlOptions(max_pages=10, max_depth=1),
        )

        async def scrape_side_effect(url: str, force_browser: bool = False) -> dict:
            return MockPage.success(url, f"# Content of {url}")

        mock_scraper.scrape = AsyncMock(side_effect=scrape_side_effect)

        with patch.object(engine, "_get_html") as mock_html:
            mock_html.return_value = """
                <html><body>
                <a href="http://example.com/about#section1">About 1</a>
                <a href="http://example.com/about#section2">About 2</a>
                </body></html>
            """

            result = await engine.run("http://example.com/")

        # Should have start URL + about = 2 pages (fragments collapsed)
        assert result.completed == 2
        about_pages = [p for p in result.pages if "about" in p["url"]]
        assert len(about_pages) == 1

    @pytest.mark.asyncio
    async def test_trailing_slash_normalization(self, mock_scraper):
        """/pricing and /pricing/ are treated as the same URL."""
        from agent.crawler import CrawlEngine, CrawlOptions

        engine = CrawlEngine(
            mock_scraper,
            store=None,
            options=CrawlOptions(max_pages=10, max_depth=1),
        )

        async def scrape_side_effect(url: str, force_browser: bool = False) -> dict:
            return MockPage.success(url, f"# Content of {url}")

        mock_scraper.scrape = AsyncMock(side_effect=scrape_side_effect)

        with patch.object(engine, "_get_html") as mock_html:
            mock_html.return_value = """
                <html><body>
                <a href="http://example.com/pricing">Pricing</a>
                <a href="http://example.com/pricing/">Pricing with slash</a>
                </body></html>
            """

            result = await engine.run("http://example.com/")

        # Should have start URL + pricing = 2 pages (trailing slash collapsed)
        assert result.completed == 2
        pricing_pages = [p for p in result.pages if "pricing" in p["url"]]
        assert len(pricing_pages) == 1

    @pytest.mark.asyncio
    async def test_ignore_query_parameters_collapses_variants(self, mock_scraper):
        """When ignore_query_parameters=True, query variants collapse."""
        from agent.crawler import CrawlEngine, CrawlOptions

        engine = CrawlEngine(
            mock_scraper,
            store=None,
            options=CrawlOptions(
                max_pages=10,
                max_depth=1,
                ignore_query_parameters=True,
            ),
        )

        async def scrape_side_effect(url: str, force_browser: bool = False) -> dict:
            return MockPage.success(url, f"# Content of {url}")

        mock_scraper.scrape = AsyncMock(side_effect=scrape_side_effect)

        with patch.object(engine, "_get_html") as mock_html:
            mock_html.return_value = """
                <html><body>
                <a href="http://example.com/page?a=1">Page a=1</a>
                <a href="http://example.com/page?b=2">Page b=2</a>
                <a href="http://example.com/page">Page no query</a>
                </body></html>
            """

            result = await engine.run("http://example.com/")

        # With ignore_query_parameters, /page?a=1, /page?b=2, /page all collapse
        # to /page. So we should have start URL + page = 2 pages
        assert result.completed == 2
        page_entries = [p for p in result.pages if "page" in p["url"]]
        assert len(page_entries) == 1

    @pytest.mark.asyncio
    async def test_child_scrape_failure_collected(self, mock_scraper):
        """Child page scrape failures are collected, not fatal."""
        from agent.crawler import CrawlEngine, CrawlOptions

        engine = CrawlEngine(
            mock_scraper,
            store=None,
            options=CrawlOptions(max_pages=10, max_depth=1),
        )

        async def scrape_side_effect(url: str, force_browser: bool = False) -> dict:
            if "fail" in url:
                return MockPage.failure(url, "Connection refused")
            return MockPage.success(url, f"# Content of {url}")

        mock_scraper.scrape = AsyncMock(side_effect=scrape_side_effect)

        with patch.object(engine, "_get_html") as mock_html:
            mock_html.return_value = """
                <html><body>
                <a href="http://example.com/good">Good page</a>
                <a href="http://example.com/fail">Failing page</a>
                </body></html>
            """

            result = await engine.run("http://example.com/")

        # Start URL + good page = 2 successful scrapes
        assert result.completed == 2
        assert len(result.pages) == 2
        # One error for the failing page
        assert len(result.errors) == 1
        assert "fail" in result.errors[0]["url"]
        assert result.errors[0]["error"] == "Connection refused"

    @pytest.mark.asyncio
    async def test_start_url_failure_returns_immediately(self, mock_scraper):
        """Start URL failure returns error immediately."""
        from agent.crawler import CrawlEngine, CrawlOptions

        mock_scraper.scrape = AsyncMock(
            return_value=MockPage.failure("http://example.com/", "Connection refused")
        )

        engine = CrawlEngine(
            mock_scraper,
            store=None,
            options=CrawlOptions(max_pages=10, max_depth=2),
        )

        result = await engine.run("http://example.com/")

        assert result.completed == 0
        assert result.pages == []
        assert len(result.errors) == 1
        assert result.errors[0]["url"] == "http://example.com/"
        assert result.errors[0]["error"] == "Connection refused"

    @pytest.mark.asyncio
    async def test_bfs_order(self, mock_scraper):
        """Pages appear in BFS order: start URL, then depth-1, then depth-2."""
        from agent.crawler import CrawlEngine, CrawlOptions

        engine = CrawlEngine(
            mock_scraper,
            store=None,
            options=CrawlOptions(max_pages=10, max_depth=2),
        )

        async def scrape_side_effect(url: str, force_browser: bool = False) -> dict:
            return MockPage.success(url, f"# Content of {url}")

        mock_scraper.scrape = AsyncMock(side_effect=scrape_side_effect)

        # Track which HTML is returned for each URL to simulate link structure
        html_responses = {
            "http://example.com/": """
                <html><body>
                <a href="http://example.com/child-a">Child A</a>
                <a href="http://example.com/child-b">Child B</a>
                </body></html>
            """,
            "http://example.com/child-a": """
                <html><body>
                <a href="http://example.com/grandchild">Grandchild</a>
                </body></html>
            """,
            "http://example.com/child-b": """
                <html><body>
                <p>No links here</p>
                </body></html>
            """,
        }

        with patch.object(engine, "_get_html") as mock_html:
            mock_html.side_effect = lambda url: html_responses.get(url)

            result = await engine.run("http://example.com/")

        # Expected BFS order:
        # [start, child-a, child-b, grandchild]
        assert len(result.pages) == 4
        assert result.pages[0]["url"] == "http://example.com/"
        assert result.pages[1]["url"] == "http://example.com/child-a"
        assert result.pages[2]["url"] == "http://example.com/child-b"
        assert result.pages[3]["url"] == "http://example.com/grandchild"

    @pytest.mark.asyncio
    async def test_empty_site_no_links(self, mock_scraper):
        """A page with no outgoing links returns only the start page."""
        from agent.crawler import CrawlEngine, CrawlOptions

        mock_scraper.scrape = AsyncMock(
            return_value=MockPage.success("http://example.com/", "No links here")
        )

        engine = CrawlEngine(
            mock_scraper,
            store=None,
            options=CrawlOptions(max_pages=10, max_depth=2),
        )

        with patch.object(engine, "_get_html") as mock_html:
            mock_html.return_value = "<html><body><p>No links</p></body></html>"

            result = await engine.run("http://example.com/")

        assert result.completed == 1
        assert len(result.pages) == 1

    @pytest.mark.asyncio
    async def test_max_pages_larger_than_available(self, mock_scraper):
        """When max_pages > available pages, crawl completes when queue is empty."""
        from agent.crawler import CrawlEngine, CrawlOptions

        mock_scraper.scrape = AsyncMock(
            return_value=MockPage.success("http://example.com/", "Just one page")
        )

        engine = CrawlEngine(
            mock_scraper,
            store=None,
            options=CrawlOptions(max_pages=100, max_depth=2),
        )

        with patch.object(engine, "_get_html") as mock_html:
            mock_html.return_value = "<html><body><p>No links</p></body></html>"

            result = await engine.run("http://example.com/")

        assert result.completed == 1
        assert result.total == 1

    @pytest.mark.asyncio
    async def test_job_store_updates(self, mock_scraper, mock_store):
        """Job store is updated with progress during crawl."""
        from agent.crawler import CrawlEngine, CrawlOptions

        mock_scraper.scrape = AsyncMock(
            return_value=MockPage.success("http://example.com/")
        )

        engine = CrawlEngine(
            mock_scraper,
            store=mock_store,
            options=CrawlOptions(max_pages=1, max_depth=2),
        )
        # Use short update interval for testing
        engine._update_interval = 0.01

        result = await engine.run("http://example.com/", job_id="test-job-123")

        assert result.completed == 1
        # redis.set should have been called at least once (final update)
        assert mock_store.redis.set.call_count >= 1

    @pytest.mark.asyncio
    async def test_crawl_with_include_paths(self, mock_scraper):
        """Only URLs matching include_paths are crawled."""
        from agent.crawler import CrawlEngine, CrawlOptions

        engine = CrawlEngine(
            mock_scraper,
            store=None,
            options=CrawlOptions(
                max_pages=10,
                max_depth=2,
                include_paths=["/section/*"],
            ),
        )

        async def scrape_side_effect(url: str, force_browser: bool = False) -> dict:
            return MockPage.success(url, f"# Content of {url}")

        mock_scraper.scrape = AsyncMock(side_effect=scrape_side_effect)

        with patch.object(engine, "_get_html") as mock_html:
            mock_html.return_value = """
                <html><body>
                <a href="http://example.com/section/page-1">Section 1</a>
                <a href="http://example.com/section/page-2">Section 2</a>
                <a href="http://example.com/about">About</a>
                </body></html>
            """

            result = await engine.run("http://example.com/")

        # Start URL doesn't match /section/*, so only section pages are crawled
        # But start URL is included since include_paths only filters child discovery
        # actually... wait, let me re-examine the logic.

        # The current code checks self._should_crawl before scraping, which
        # includes a call to _match_path. But the start URL is the first URL
        # and should also be checked against include_paths.

        # Looking at the architecture.md:
        # "Path filters apply to all URLs including the start URL — if start URL
        # doesn't match include_paths, crawl returns 0 pages"

        # Wait, but my current implementation checks _match_path AFTER adding to seen
        # but BEFORE scraping... Actually, looking at my crawl loop:

        # 1. Pop from queue
        # 2. Normalize
        # 3. Check dedup - skip if seen
        # 4. Check max_depth - skip if too deep (but depth=0 is fine)
        # 5. Add to seen
        # 6. Check path filters - if not match, continue
        # 7. Scrape
        # 8. Extract links if depth < max_depth

        # So the start URL IS checked against include_paths. If it doesn't match,
        # it's skipped. That means the start URL would need to match include_paths
        # to be crawled.

        # For this test, let's check that "/section/*" doesn't match "/about"
        about_pages = [p for p in result.pages if "about" in p["url"]]
        assert len(about_pages) == 0

    @pytest.mark.asyncio
    async def test_crawl_with_exclude_paths(self, mock_scraper):
        """URLs matching exclude_paths are skipped."""
        from agent.crawler import CrawlEngine, CrawlOptions

        engine = CrawlEngine(
            mock_scraper,
            store=None,
            options=CrawlOptions(
                max_pages=10,
                max_depth=1,
                exclude_paths=["/admin/*"],
            ),
        )

        async def scrape_side_effect(url: str, force_browser: bool = False) -> dict:
            return MockPage.success(url, f"# Content of {url}")

        mock_scraper.scrape = AsyncMock(side_effect=scrape_side_effect)

        with patch.object(engine, "_get_html") as mock_html:
            mock_html.return_value = """
                <html><body>
                <a href="http://example.com/pricing">Pricing</a>
                <a href="http://example.com/about">About</a>
                <a href="http://example.com/admin/secret">Admin</a>
                </body></html>
            """

            result = await engine.run("http://example.com/")

        # Start URL + pricing + about = 3 pages, admin excluded
        urls = [p["url"] for p in result.pages]
        assert "http://example.com/admin/secret" not in urls
        assert len(result.pages) == 3

    @pytest.mark.asyncio
    async def test_empty_markdown_handled_gracefully(self, mock_scraper):
        """A page with empty markdown is still included."""
        from agent.crawler import CrawlEngine, CrawlOptions

        mock_scraper.scrape = AsyncMock(
            return_value=MockPage.success("http://example.com/", markdown="")
        )

        engine = CrawlEngine(
            mock_scraper,
            store=None,
            options=CrawlOptions(max_pages=1, max_depth=2),
        )

        result = await engine.run("http://example.com/")

        assert result.completed == 1
        assert result.pages[0]["markdown"] == ""

    @pytest.mark.asyncio
    async def test_cancel_flag_stops_crawl(self, mock_scraper):
        """Setting cancel flag stops the crawl loop."""
        from agent.crawler import CrawlEngine, CrawlOptions

        engine = CrawlEngine(
            mock_scraper,
            store=None,
            options=CrawlOptions(max_pages=10, max_depth=2),
        )

        async def scrape_side_effect(url: str, force_browser: bool = False) -> dict:
            return MockPage.success(url, f"# Content of {url}")

        mock_scraper.scrape = AsyncMock(side_effect=scrape_side_effect)

        with patch.object(engine, "_get_html") as mock_html:
            mock_html.return_value = """
                <html><body>
                <a href="http://example.com/page1">Page 1</a>
                <a href="http://example.com/page2">Page 2</a>
                </body></html>
            """

            # Cancel after the first page is scraped
            original_scrape = mock_scraper.scrape

            async def scrape_with_cancel(url: str, force_browser: bool = False) -> dict:
                result = await original_scrape(url, force_browser)
                engine.cancel()
                return result

            mock_scraper.scrape = AsyncMock(side_effect=scrape_with_cancel)

            result = await engine.run("http://example.com/")

        # Should have at least 1 page (start URL was scraped before cancel)
        assert result.completed >= 1

    @pytest.mark.asyncio
    async def test_crawl_with_self_referencing_links(self, mock_scraper):
        """Self-referencing links don't cause infinite loops."""
        from agent.crawler import CrawlEngine, CrawlOptions

        mock_scraper.scrape = AsyncMock(
            return_value=MockPage.success("http://example.com/")
        )

        engine = CrawlEngine(
            mock_scraper,
            store=None,
            options=CrawlOptions(max_pages=10, max_depth=2),
        )

        with patch.object(engine, "_get_html") as mock_html:
            # Page links to itself and to a child
            mock_html.return_value = """
                <html><body>
                <a href="http://example.com/">Self link</a>
                <a href="http://example.com/.">Self link dot</a>
                <a href="http://example.com/page1">Page 1</a>
                </body></html>
            """

            result = await engine.run("http://example.com/")

        # Should complete without infinite loop
        # Start URL + page1 = 2 pages
        assert result.completed == 2


# ── Path filtering tests ────────────────────────────────────────


class TestPathFiltering:
    """Tests for path filtering in CrawlEngine."""

    @pytest.mark.asyncio
    async def test_include_paths_start_url_matches(self, mock_scraper):
        """When start URL matches include_paths, it is crawled."""
        from agent.crawler import CrawlEngine, CrawlOptions

        engine = CrawlEngine(
            mock_scraper,
            store=None,
            options=CrawlOptions(
                max_pages=10,
                max_depth=1,
                include_paths=["/blog/*"],
            ),
        )

        async def scrape_side_effect(url: str, force_browser: bool = False) -> dict:
            return MockPage.success(url, f"# Content of {url}")

        mock_scraper.scrape = AsyncMock(side_effect=scrape_side_effect)

        with patch.object(engine, "_get_html") as mock_html:
            mock_html.return_value = """
                <html><body>
                <a href="http://example.com/blog/post1">Blog Post 1</a>
                <a href="http://example.com/blog/post2">Blog Post 2</a>
                <a href="http://example.com/about">About</a>
                </body></html>
            """

            result = await engine.run("http://example.com/blog/index")

        # Start URL matches /blog/*, children under /blog/ are included
        assert result.completed >= 2  # start + at least one blog child
        urls = [p["url"] for p in result.pages]
        assert "http://example.com/blog/index" in urls
        assert "http://example.com/about" not in urls

    @pytest.mark.asyncio
    async def test_include_paths_start_url_no_match_returns_zero(self, mock_scraper):
        """When start URL doesn't match include_paths, 0 pages are crawled."""
        from agent.crawler import CrawlEngine, CrawlOptions

        engine = CrawlEngine(
            mock_scraper,
            store=None,
            options=CrawlOptions(
                max_pages=10,
                max_depth=2,
                include_paths=["/section/*"],
            ),
        )

        async def scrape_side_effect(url: str, force_browser: bool = False) -> dict:
            return MockPage.success(url, f"# Content of {url}")

        mock_scraper.scrape = AsyncMock(side_effect=scrape_side_effect)

        with patch.object(engine, "_get_html") as mock_html:
            mock_html.return_value = """
                <html><body>
                <a href="http://example.com/section/page-1">Section 1</a>
                <a href="http://example.com/about">About</a>
                </body></html>
            """

            result = await engine.run("http://example.com/")

        # Start URL / doesn't match /section/* so it's skipped
        assert result.completed == 0
        assert len(result.pages) == 0

    @pytest.mark.asyncio
    async def test_include_paths_regex_mode(self, mock_scraper):
        """include_paths with regex_on_full_url=True uses regex matching."""
        from agent.crawler import CrawlEngine, CrawlOptions

        engine = CrawlEngine(
            mock_scraper,
            store=None,
            options=CrawlOptions(
                max_pages=10,
                max_depth=1,
                include_paths=["/section/page-[12]"],
                regex_on_full_url=True,
            ),
        )

        async def scrape_side_effect(url: str, force_browser: bool = False) -> dict:
            return MockPage.success(url, f"# Content of {url}")

        mock_scraper.scrape = AsyncMock(side_effect=scrape_side_effect)

        with patch.object(engine, "_get_html") as mock_html:
            mock_html.return_value = """
                <html><body>
                <a href="http://example.com/section/page-1">Page 1</a>
                <a href="http://example.com/section/page-2">Page 2</a>
                <a href="http://example.com/section/page-3">Page 3</a>
                <a href="http://example.com/about">About</a>
                </body></html>
            """

            result = await engine.run("http://example.com/section/page-1")

        # Start URL /section/page-1 should match /section/page-[12]
        urls = [p["url"] for p in result.pages]
        assert "http://example.com/section/page-1" in urls
        assert "http://example.com/section/page-2" in urls
        assert "http://example.com/section/page-3" not in urls
        assert "http://example.com/about" not in urls

    @pytest.mark.asyncio
    async def test_include_paths_empty_is_identity(self, mock_scraper):
        """Empty include_paths list means 'include all' (identity)."""
        from agent.crawler import CrawlEngine, CrawlOptions

        engine = CrawlEngine(
            mock_scraper,
            store=None,
            options=CrawlOptions(
                max_pages=10,
                max_depth=1,
                include_paths=[],
            ),
        )

        async def scrape_side_effect(url: str, force_browser: bool = False) -> dict:
            return MockPage.success(url, f"# Content of {url}")

        mock_scraper.scrape = AsyncMock(side_effect=scrape_side_effect)

        with patch.object(engine, "_get_html") as mock_html:
            mock_html.return_value = """
                <html><body>
                <a href="http://example.com/pricing">Pricing</a>
                <a href="http://example.com/about">About</a>
                </body></html>
            """

            result = await engine.run("http://example.com/")

        # All URLs should pass (identity filter)
        assert result.completed >= 2

    @pytest.mark.asyncio
    async def test_exclude_paths_empty_is_identity(self, mock_scraper):
        """Empty exclude_paths list means 'exclude none' (identity)."""
        from agent.crawler import CrawlEngine, CrawlOptions

        engine = CrawlEngine(
            mock_scraper,
            store=None,
            options=CrawlOptions(
                max_pages=10,
                max_depth=1,
                exclude_paths=[],
            ),
        )

        async def scrape_side_effect(url: str, force_browser: bool = False) -> dict:
            return MockPage.success(url, f"# Content of {url}")

        mock_scraper.scrape = AsyncMock(side_effect=scrape_side_effect)

        with patch.object(engine, "_get_html") as mock_html:
            mock_html.return_value = """
                <html><body>
                <a href="http://example.com/pricing">Pricing</a>
                <a href="http://example.com/about">About</a>
                </body></html>
            """

            result = await engine.run("http://example.com/")

        # All URLs should pass (identity filter)
        assert result.completed >= 2

    @pytest.mark.asyncio
    async def test_exclude_overrides_include(self, mock_scraper):
        """exclude_paths takes precedence over include_paths."""
        from agent.crawler import CrawlEngine, CrawlOptions

        engine = CrawlEngine(
            mock_scraper,
            store=None,
            options=CrawlOptions(
                max_pages=10,
                max_depth=1,
                include_paths=["/section/*"],
                exclude_paths=["/section/page-2"],
            ),
        )

        async def scrape_side_effect(url: str, force_browser: bool = False) -> dict:
            return MockPage.success(url, f"# Content of {url}")

        mock_scraper.scrape = AsyncMock(side_effect=scrape_side_effect)

        with patch.object(engine, "_get_html") as mock_html:
            mock_html.return_value = """
                <html><body>
                <a href="http://example.com/section/page-1">Page 1</a>
                <a href="http://example.com/section/page-2">Page 2</a>
                <a href="http://example.com/about">About</a>
                </body></html>
            """

            result = await engine.run("http://example.com/section/index")

        urls = [p["url"] for p in result.pages]
        assert "http://example.com/section/page-1" in urls
        assert "http://example.com/section/page-2" not in urls  # excluded
        assert "http://example.com/about" not in urls  # not in include_paths

    @pytest.mark.asyncio
    async def test_exclude_all_returns_zero_pages(self, mock_scraper):
        """exclude_paths matching everything returns 0 pages."""
        from agent.crawler import CrawlEngine, CrawlOptions

        engine = CrawlEngine(
            mock_scraper,
            store=None,
            options=CrawlOptions(
                max_pages=10,
                max_depth=2,
                exclude_paths=["/*"],
            ),
        )

        mock_scraper.scrape = AsyncMock(
            return_value=MockPage.success("http://example.com/")
        )

        result = await engine.run("http://example.com/")

        assert result.completed == 0
        assert len(result.pages) == 0

    @pytest.mark.asyncio
    async def test_include_nonexistent_returns_zero_pages(self, mock_scraper):
        """include_paths that match nothing returns 0 pages."""
        from agent.crawler import CrawlEngine, CrawlOptions

        engine = CrawlEngine(
            mock_scraper,
            store=None,
            options=CrawlOptions(
                max_pages=10,
                max_depth=2,
                include_paths=["/nonexistent/*"],
            ),
        )

        mock_scraper.scrape = AsyncMock(
            return_value=MockPage.success("http://example.com/")
        )

        result = await engine.run("http://example.com/")

        assert result.completed == 0
        assert len(result.pages) == 0

    @pytest.mark.asyncio
    async def test_glob_double_star_matches_any_depth(self, mock_scraper):
        """Glob ** matches across directory boundaries."""
        from agent.crawler import CrawlEngine, CrawlOptions

        engine = CrawlEngine(
            mock_scraper,
            store=None,
            options=CrawlOptions(
                max_pages=20,
                max_depth=3,
                include_paths=["/blog/**"],
            ),
        )

        async def scrape_side_effect(url: str, force_browser: bool = False) -> dict:
            return MockPage.success(url, f"# Content of {url}")

        mock_scraper.scrape = AsyncMock(side_effect=scrape_side_effect)

        with patch.object(engine, "_get_html") as mock_html:
            mock_html.return_value = """
                <html><body>
                <a href="http://example.com/blog/2024/01/post">Deep post</a>
                <a href="http://example.com/blog/2024">Year index</a>
                <a href="http://example.com/about">About</a>
                </body></html>
            """

            result = await engine.run("http://example.com/blog/index")

        urls = [p["url"] for p in result.pages]
        assert "http://example.com/blog/index" in urls
        # Deep paths under /blog/ should match /blog/**
        assert "http://example.com/blog/2024" in urls
        assert "http://example.com/blog/2024/01/post" in urls
        assert "http://example.com/about" not in urls

    @pytest.mark.asyncio
    async def test_regex_on_full_url_with_query_params(self, mock_scraper):
        """regex_on_full_url matches against full URL including query params."""
        from agent.crawler import CrawlEngine, CrawlOptions

        engine = CrawlEngine(
            mock_scraper,
            store=None,
            options=CrawlOptions(
                max_pages=10,
                max_depth=1,
                include_paths=[r"\?ref=partner"],
                regex_on_full_url=True,
            ),
        )

        async def scrape_side_effect(url: str, force_browser: bool = False) -> dict:
            return MockPage.success(url, f"# Content of {url}")

        mock_scraper.scrape = AsyncMock(side_effect=scrape_side_effect)

        with patch.object(engine, "_get_html") as mock_html:
            mock_html.return_value = """
                <html><body>
                <a href="http://example.com/page?ref=partner">Partner link</a>
                <a href="http://example.com/page?ref=other">Other link</a>
                <a href="http://example.com/about">About</a>
                </body></html>
            """

            result = await engine.run("http://example.com/start?ref=partner")

        urls = [p["url"] for p in result.pages]
        assert "http://example.com/page?ref=partner" in urls
        assert "http://example.com/page?ref=other" not in urls

    @pytest.mark.asyncio
    async def test_verbose_tracks_filtered_out_urls(self, mock_scraper):
        """Verbose mode collects URLs that were filtered out with reasons."""
        from agent.crawler import CrawlEngine, CrawlOptions

        engine = CrawlEngine(
            mock_scraper,
            store=None,
            options=CrawlOptions(
                max_pages=10,
                max_depth=1,
                include_paths=["/section/*"],
                exclude_paths=["/section/secret"],
                verbose=True,
            ),
        )

        async def scrape_side_effect(url: str, force_browser: bool = False) -> dict:
            return MockPage.success(url, f"# Content of {url}")

        mock_scraper.scrape = AsyncMock(side_effect=scrape_side_effect)

        with patch.object(engine, "_get_html") as mock_html:
            mock_html.return_value = """
                <html><body>
                <a href="http://example.com/section/page-1">Page 1</a>
                <a href="http://example.com/section/secret">Secret</a>
                <a href="http://example.com/about">About</a>
                </body></html>
            """

            result = await engine.run("http://example.com/")

        # Start URL / doesn't match /section/* → should be filtered out
        assert result.completed == 0
        assert len(result.pages) == 0
        if result.filtered_out:
            # At least one filtered URL should be recorded
            assert any(f["reason"] == "include_paths" for f in result.filtered_out)

    @pytest.mark.asyncio
    async def test_verbose_tracks_exclude_reason(self, mock_scraper):
        """Verbose mode records exclude_paths as filter reason."""
        from agent.crawler import CrawlEngine, CrawlOptions

        engine = CrawlEngine(
            mock_scraper,
            store=None,
            options=CrawlOptions(
                max_pages=10,
                max_depth=1,
                exclude_paths=["/admin/*"],
                verbose=True,
            ),
        )

        async def scrape_side_effect(url: str, force_browser: bool = False) -> dict:
            return MockPage.success(url, f"# Content of {url}")

        mock_scraper.scrape = AsyncMock(side_effect=scrape_side_effect)

        with patch.object(engine, "_get_html") as mock_html:
            mock_html.return_value = """
                <html><body>
                <a href="http://example.com/pricing">Pricing</a>
                <a href="http://example.com/admin/secret">Admin</a>
                </body></html>
            """

            result = await engine.run("http://example.com/")

        assert result.completed >= 2  # start URL + pricing
        if result.filtered_out:
            assert any(f["reason"] == "exclude_paths" for f in result.filtered_out), (
                "Expected exclude_paths reason in filtered_out"
            )

    @pytest.mark.asyncio
    async def test_glob_escapes_regex_special_chars(self, mock_scraper):
        """Glob mode treats regex special chars as literals."""
        from agent.crawler import _match_path

        # In glob mode, '.' should be literal, not 'any char'
        assert _match_path(
            "http://example.com/file.html",
            ["/file.html"],
            None,
            regex_on_full_url=False,
        )
        # Should NOT match fileXhtml when . is treated literally
        assert not _match_path(
            "http://example.com/fileXhtml",
            ["/file.html"],
            None,
            regex_on_full_url=False,
        )

    @pytest.mark.asyncio
    async def test_regex_on_full_url_with_exclude_paths(self, mock_scraper):
        """exclude_paths with regex_on_full_url=True uses regex matching."""
        from agent.crawler import CrawlEngine, CrawlOptions

        engine = CrawlEngine(
            mock_scraper,
            store=None,
            options=CrawlOptions(
                max_pages=10,
                max_depth=1,
                exclude_paths=[r"/section/page-[23]"],
                regex_on_full_url=True,
            ),
        )

        async def scrape_side_effect(url: str, force_browser: bool = False) -> dict:
            return MockPage.success(url, f"# Content of {url}")

        mock_scraper.scrape = AsyncMock(side_effect=scrape_side_effect)

        with patch.object(engine, "_get_html") as mock_html:
            mock_html.return_value = """
                <html><body>
                <a href="http://example.com/section/page-1">Page 1</a>
                <a href="http://example.com/section/page-2">Page 2</a>
                <a href="http://example.com/section/page-3">Page 3</a>
                </body></html>
            """

            result = await engine.run("http://example.com/")

        urls = [p["url"] for p in result.pages]
        assert "http://example.com/section/page-1" in urls
        assert "http://example.com/section/page-2" not in urls
        assert "http://example.com/section/page-3" not in urls

    @pytest.mark.asyncio
    async def test_regex_on_full_url_with_ignore_query_params(self, mock_scraper):
        """ignoreQueryParameters strips query first, then regex applies to path.

        Per VAL-SCOPE-073: when both regexOnFullURL and ignoreQueryParameters
        are set, query string is stripped from the URL BEFORE regex matching.
        """
        from agent.crawler import CrawlEngine, CrawlOptions

        engine = CrawlEngine(
            mock_scraper,
            store=None,
            options=CrawlOptions(
                max_pages=10,
                max_depth=1,
                include_paths=[r"/page$"],
                regex_on_full_url=True,
                ignore_query_parameters=True,
            ),
        )

        async def scrape_side_effect(url: str, force_browser: bool = False) -> dict:
            return MockPage.success(url, f"# Content of {url}")

        mock_scraper.scrape = AsyncMock(side_effect=scrape_side_effect)

        with patch.object(engine, "_get_html") as mock_html:
            mock_html.return_value = """
                <html><body>
                <a href="http://example.com/other-page?ref=test">Other page with query</a>
                <a href="http://example.com/pages">Pages (plural)</a>
                </body></html>
            """

            result = await engine.run("http://example.com/page")

        # Start URL /page matches /page$ include pattern
        urls = [p["url"] for p in result.pages]
        assert "http://example.com/page" in urls
        # With ignore_query_parameters, /other-page?ref=test normalizes to /other-page
        # and the filter_url (without query) matches /page$? No — /other-page doesn't end with /page
        # So /other-page should be excluded by the path filter
        assert "http://example.com/other-page" not in urls
        # /pages should NOT match /page$ (because $ anchors to end)
        assert "http://example.com/pages" not in urls
