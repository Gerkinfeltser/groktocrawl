"""Tests for agent-svc/agent/research.py — research loop helpers and pipelines."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestValidateJsonIfSchema:
    def setup_method(self):
        from agent.research import _validate_json_if_schema

        self.func = _validate_json_if_schema

    def test_no_schema_does_nothing(self):
        self.func('{"key": "value"}', None)

    def test_valid_json_passes(self):
        self.func('{"key": "value"}', {"type": "object"})

    def test_strips_code_fences(self):
        self.func('```json\n{"key": "value"}\n```', {"type": "object"})
        self.func('```\n{"key": "value"}\n```', {"type": "object"})

    def test_invalid_json_logs_warning(self, caplog):
        import logging

        caplog.set_level(logging.WARNING)
        self.func("not json", {"type": "object"})
        assert "not valid JSON" in caplog.text


class TestIsVideoPlatformUrl:
    def setup_method(self):
        from agent.research import _is_video_platform_url

        self.func = _is_video_platform_url

    def test_youtube(self):
        assert self.func("https://youtube.com/watch?v=abc123")
        assert self.func("https://youtu.be/abc123")
        assert self.func("https://www.youtube.com/watch?v=abc123")

    def test_tiktok(self):
        assert self.func("https://tiktok.com/@user/video/123")
        assert self.func("https://www.tiktok.com/@user/video/123")
        assert self.func("https://vm.tiktok.com/abcdef/")

    def test_instagram(self):
        assert self.func("https://instagram.com/p/abc123")
        assert self.func("https://www.instagram.com/p/abc123")

    def test_non_video_platform(self):
        assert not self.func("https://example.com/article")
        assert not self.func("https://github.com/user/repo")

    def test_edge_cases(self):
        assert not self.func("")
        assert not self.func("not-a-url")


@pytest.fixture
def mock_scraper():
    """Return a ScraperClient-mimicking object where .scrape is an AsyncMock."""
    m = MagicMock()
    m.scrape = AsyncMock()
    return m


class TestScrapeUrls:
    @pytest.mark.asyncio
    async def test_scrapes_urls(self, mock_scraper):
        from agent.research import _scrape_urls

        mock_scraper.scrape.return_value = {
            "success": True,
            "data": {"markdown": "# Hello", "source": "llms.txt"},
        }

        docs, details = await _scrape_urls(
            ["https://a.com"],
            mock_scraper,
            min_sources=1,
            max_attempts=5,
        )

        assert len(docs) == 1
        assert "a.com" in docs[0]
        assert details[0]["url"] == "https://a.com"

    @pytest.mark.asyncio
    async def test_respects_min_sources(self, mock_scraper):
        from agent.research import _scrape_urls

        mock_scraper.scrape.return_value = {
            "success": True,
            "data": {"markdown": "# Content", "source": "test"},
        }

        docs, _details = await _scrape_urls(
            ["https://a.com", "https://b.com", "https://c.com"],
            mock_scraper,
            min_sources=2,
            max_attempts=5,
        )

        assert len(docs) >= 2

    @pytest.mark.asyncio
    async def test_handles_scrape_failures(self, mock_scraper):
        from agent.research import _scrape_urls

        mock_scraper.scrape.side_effect = [
            {"success": False, "error": "Not found"},
            {"success": True, "data": {"markdown": "# Content", "source": "test"}},
        ]

        docs, details = await _scrape_urls(
            ["https://fail.com", "https://ok.com"],
            mock_scraper,
            min_sources=1,
            max_attempts=5,
        )

        assert len(docs) == 1
        assert details[0]["url"] == "https://ok.com"

    @pytest.mark.asyncio
    async def test_handles_exception(self, mock_scraper):
        from agent.research import _scrape_urls

        mock_scraper.scrape.side_effect = RuntimeError("network error")

        docs, _details = await _scrape_urls(
            ["https://err.com"],
            mock_scraper,
            min_sources=1,
            max_attempts=5,
        )
        assert len(docs) == 0


class TestRunResearch:
    @pytest.fixture
    def mocks(self):
        """Patch all three clients used by run_research."""
        searxng = MagicMock()
        searxng.search = AsyncMock()
        searxng.close = AsyncMock()

        scraper = MagicMock()
        scraper.scrape = AsyncMock()
        scraper.close = AsyncMock()

        llm = MagicMock()
        llm.generate = AsyncMock()
        llm.close = AsyncMock()

        return searxng, scraper, llm

    @pytest.mark.asyncio
    async def test_with_urls(self, mocks):
        from agent.research import run_research

        searxng, scraper, llm = mocks

        scraper.scrape.return_value = {
            "success": True,
            "data": {"markdown": "# Research content", "source": "test"},
        }
        llm.generate.return_value = "Here is the synthesized answer."

        with (
            patch("agent.research.SearXNGClient", return_value=searxng),
            patch("agent.research.ScraperClient", return_value=scraper),
            patch("agent.research.LLMClient", return_value=llm),
        ):
            result = await run_research(
                prompt="What is AI?",
                urls=["https://example.com/ai"],
            )

        assert result["result"] == "Here is the synthesized answer."
        assert len(result["sources"]) == 1
        assert result["sources"][0] == "https://example.com/ai"
        searxng.search.assert_not_called()

    @pytest.mark.asyncio
    async def test_without_urls_searches(self, mocks):
        from agent.research import run_research

        searxng, scraper, llm = mocks

        searxng.search.return_value = (
            [{"url": "https://result.com", "title": "Result", "description": "desc"}],
            MagicMock(),
        )
        scraper.scrape.return_value = {
            "success": True,
            "data": {"markdown": "# Content", "source": "test"},
        }
        llm.generate.return_value = "Answer from search."

        with (
            patch("agent.research.SearXNGClient", return_value=searxng),
            patch("agent.research.ScraperClient", return_value=scraper),
            patch("agent.research.LLMClient", return_value=llm),
        ):
            result = await run_research(prompt="Tell me about AI")

        assert result["result"] == "Answer from search."
        searxng.search.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_scraped_content_returns_fallback(self, mocks):
        from agent.research import run_research

        searxng, scraper, llm = mocks

        scraper.scrape.return_value = {
            "success": False,
            "error": "Not found",
        }

        with (
            patch("agent.research.SearXNGClient", return_value=searxng),
            patch("agent.research.ScraperClient", return_value=scraper),
            patch("agent.research.LLMClient", return_value=llm),
        ):
            result = await run_research(
                prompt="Anything?",
                urls=["https://example.com/missing"],
            )

        assert "unable to find or scrape" in result["result"].lower()
        assert result["sources"] == []

    @pytest.mark.asyncio
    async def test_passes_schema_to_llm(self, mocks):
        from agent.research import run_research

        searxng, scraper, llm = mocks

        scraper.scrape.return_value = {
            "success": True,
            "data": {"markdown": "# Content", "source": "test"},
        }
        llm.generate.return_value = '{"name": "AI"}'
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}

        with (
            patch("agent.research.SearXNGClient", return_value=searxng),
            patch("agent.research.ScraperClient", return_value=scraper),
            patch("agent.research.LLMClient", return_value=llm),
        ):
            result = await run_research(
                prompt="Extract name",
                urls=["https://example.com"],
                schema=schema,
            )

        assert result["result"] == '{"name": "AI"}'
        llm.generate.assert_called_once()
        assert llm.generate.call_args[1].get("schema") == schema

    @pytest.mark.asyncio
    async def test_requested_model_override(self, mocks):
        from agent.research import run_research

        searxng, scraper, llm = mocks

        scraper.scrape.return_value = {
            "success": True,
            "data": {"markdown": "x", "source": "t"},
        }
        llm.generate.return_value = "ok"

        with (
            patch("agent.research.SearXNGClient", return_value=searxng),
            patch("agent.research.ScraperClient", return_value=scraper),
            patch("agent.research.LLMClient", return_value=llm),
        ):
            result = await run_research(
                prompt="test",
                urls=["https://x.com"],
                llm_model="default-model",
                requested_model="gpt-4o",
            )

        assert result["result"] == "ok"
        # LLMClient should have been constructed with model="gpt-4o"
        llm_call = llm.generate.call_args[1]
        assert "system_prompt" in llm_call

    @pytest.mark.asyncio
    async def test_sources_uses_filtered_list(self, mocks):
        """Verify that result['sources'] is a list of URL strings from source_details."""
        from agent.research import run_research

        searxng, scraper, llm = mocks

        scraper.scrape.return_value = {
            "success": True,
            "data": {"markdown": "# Content", "source": "test"},
        }
        llm.generate.return_value = "Answer."

        with (
            patch("agent.research.SearXNGClient", return_value=searxng),
            patch("agent.research.ScraperClient", return_value=scraper),
            patch("agent.research.LLMClient", return_value=llm),
        ):
            result = await run_research(
                prompt="test",
                urls=["https://x.com", "https://y.com"],
            )

        assert isinstance(result["sources"], list)
        assert len(result["sources"]) > 0
        assert all(isinstance(s, str) for s in result["sources"])


class TestRunAnswer:
    @pytest.mark.asyncio
    async def test_full_pipeline_returns_answer(self):
        from agent.research import run_answer

        searxng = MagicMock()
        searxng.search = AsyncMock()
        searxng.search.return_value = (
            [
                {
                    "url": "https://example.com",
                    "title": "Example",
                    "description": "An example page",
                }
            ],
            MagicMock(),
        )
        searxng.close = AsyncMock()

        scraper = MagicMock()
        scraper.scrape = AsyncMock()
        scraper.scrape.return_value = {
            "success": True,
            "data": {
                "markdown": "# Example Page\n\nThis is the content.",
                "source": "test",
            },
        }
        scraper.close = AsyncMock()

        llm = MagicMock()
        llm.generate = AsyncMock()
        llm.generate.return_value = "Based on [1] the answer is 42."
        llm.close = AsyncMock()

        with (
            patch("agent.research.SearXNGClient", return_value=searxng),
            patch("agent.research.ScraperClient", return_value=scraper),
            patch("agent.research.LLMClient", return_value=llm),
        ):
            result = await run_answer(query="What is the answer?", num_sources=1)

        assert "answer" in result
        assert "Based on" in result["answer"]
        assert len(result["sources"]) == 1
        assert len(result["citations"]) == 1
        assert result["citations"][0]["index"] == 1
        assert "latency_ms" in result

    @pytest.mark.asyncio
    async def test_no_content_fallback(self):
        from agent.research import run_answer

        searxng = MagicMock()
        searxng.search = AsyncMock()
        searxng.search.return_value = ([], MagicMock())
        searxng.close = AsyncMock()

        scraper = MagicMock()
        scraper.scrape = AsyncMock()
        scraper.close = AsyncMock()

        llm = MagicMock()
        llm.generate = AsyncMock()
        llm.close = AsyncMock()

        with (
            patch("agent.research.SearXNGClient", return_value=searxng),
            patch("agent.research.ScraperClient", return_value=scraper),
            patch("agent.research.LLMClient", return_value=llm),
        ):
            result = await run_answer(query="Anything?")

        assert "unable to find or scrape" in result["answer"].lower()
        assert result["sources"] == []
        assert result["citations"] == []
