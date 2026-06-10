"""Tests for agent-svc/agent/searxng_client.py — SearXNG client.

Tests category translation, engine health parsing, and search API calls.
"""

import httpx
import pytest


@pytest.fixture
def client():
    from agent.searxng_client import SearXNGClient

    return SearXNGClient(base_url="http://searxng.test")


class TestTranslate:
    def setup_method(self):
        from agent.searxng_client import SearXNGClient

        self.translate = SearXNGClient._translate

    def test_empty_sources_and_categories_defaults_to_general(self):
        assert self.translate(None, None) == ["general"]

    def test_empty_lists_defaults_to_general(self):
        assert self.translate([], []) == ["general"]

    def test_maps_sources_to_categories(self):
        result = self.translate(["news", "web", "images"], None)
        assert "news" in result
        assert "general" in result  # web -> general, images not mapped
        # images maps to nothing known, should pass through as "images"
        assert "images" in result

    def test_maps_categories(self):
        result = self.translate(None, ["research", "github"])
        assert "science" in result  # research -> science
        assert "it" in result  # github -> it

    def test_dedupes_categories(self):
        result = self.translate(["news"], ["news"])
        assert result.count("news") == 1
        assert len(result) == 1

    def test_passes_unknown_values_through(self):
        result = self.translate(["custom-engine"], None)
        assert "custom-engine" in result

    def test_merges_sources_and_categories(self):
        result = self.translate(["news"], ["research"])
        assert "news" in result
        assert "science" in result


class TestParseEngineHealth:
    def setup_method(self):
        from agent.searxng_client import SearXNGClient

        self.parse = SearXNGClient._parse_engine_health

    def test_all_engines_healthy(self):
        data = {
            "engines": [
                {"engine": "google", "results": 10},
                {"engine": "brave", "results": 5},
            ]
        }
        health = self.parse(data, [{"url": "x"}])
        assert health.engines_total == 2
        assert health.engines_responding == 2
        assert health.empty_result is False
        assert health.degraded is False
        assert "Healthy" in health.detail

    def test_no_engine_status(self):
        data = {"engines": []}
        health = self.parse(data, [])
        assert health.engines_total == 0
        assert health.engines_responding == 0
        assert health.empty_result is False
        assert health.degraded is False
        assert "No engine status" in health.detail

    def test_degraded_when_fewer_than_half_respond(self):
        data = {
            "engines": [
                {"engine": "google", "results": 10},
                {"engine": "brave", "results": 0},
                {"engine": "duckduckgo", "results": 0},
            ]
        }
        health = self.parse(data, [{"url": "https://example.com"}])
        assert health.engines_total == 3
        assert health.engines_responding == 1
        assert health.degraded is True
        assert "Degraded" in health.detail

    def test_empty_result_when_engines_respond_no_urls(self):
        """Engines responded but returned no results with valid URLs."""
        data = {
            "engines": [
                {"engine": "google", "results": 1},
            ]
        }
        # Results exist but have no URL
        health = self.parse(data, [{"url": ""}])
        assert health.engines_responding == 1
        assert health.empty_result is True
        assert "no results" in health.detail


class TestSearch:
    @pytest.mark.asyncio
    async def test_successful_search(self, client):
        mock_data = {
            "results": [
                {
                    "url": "https://a.com",
                    "title": "Page A",
                    "content": "Desc A",
                    "engine": "google",
                },
                {
                    "url": "https://b.com",
                    "title": "Page B",
                    "content": "Desc B",
                    "engine": "brave",
                },
            ],
            "engines": [
                {"engine": "google", "results": 1},
                {"engine": "brave", "results": 1},
            ],
        }

        with pytest.MonkeyPatch.context() as mp:

            async def mock_get(url, params=None):
                import types

                r = types.SimpleNamespace()
                r.status_code = 200
                r.json = lambda: mock_data
                return r

            mp.setattr(client._client, "get", mock_get)

            results, health = await client.search("test query")
            assert len(results) == 2
            assert results[0]["url"] == "https://a.com"
            assert health.engines_total == 2
            assert health.engines_responding == 2

    @pytest.mark.asyncio
    async def test_non_200_response(self, client):
        with pytest.MonkeyPatch.context() as mp:

            async def mock_get(url, params=None):
                import types

                r = types.SimpleNamespace()
                r.status_code = 500
                r.text = "Server Error"
                return r

            mp.setattr(client._client, "get", mock_get)

            results, health = await client.search("test")
            assert results == []
            assert "HTTP 500" in health.detail

    @pytest.mark.asyncio
    async def test_timeout_returns_empty(self, client):

        with pytest.MonkeyPatch.context() as mp:

            async def mock_get(url, params=None):
                raise httpx.TimeoutException("timed out")

            mp.setattr(client._client, "get", mock_get)

            results, health = await client.search("test")
            assert results == []
            assert "timed out" in health.detail.lower()

    @pytest.mark.asyncio
    async def test_general_exception_returns_empty(self, client):
        with pytest.MonkeyPatch.context() as mp:

            async def mock_get(url, params=None):
                raise ValueError("something broke")

            mp.setattr(client._client, "get", mock_get)

            results, health = await client.search("test")
            assert results == []
            assert "failed" in health.detail.lower()

    @pytest.mark.asyncio
    async def test_respects_limit(self, client):
        mock_data = {
            "results": [
                {
                    "url": f"https://{i}.com",
                    "title": f"Page {i}",
                    "content": "",
                    "engine": "google",
                }
                for i in range(20)
            ],
            "engines": [],
        }

        with pytest.MonkeyPatch.context() as mp:

            async def mock_get(url, params=None):
                import types

                r = types.SimpleNamespace()
                r.status_code = 200
                r.json = lambda: mock_data
                return r

            mp.setattr(client._client, "get", mock_get)

            results, _ = await client.search("test query", limit=5)
            assert len(results) == 5

    @pytest.mark.asyncio
    async def test_passes_categories_param(self, client):
        with pytest.MonkeyPatch.context() as mp:
            captured_params = {}

            async def mock_get(url, params=None):
                captured_params.update(params or {})
                import types

                r = types.SimpleNamespace()
                r.status_code = 200
                r.json = lambda: {"results": [], "engines": []}
                return r

            mp.setattr(client._client, "get", mock_get)

            await client.search("test query", categories=["news", "research"])
            assert "categories" in captured_params
            assert captured_params["categories"] == "news,science"

    @pytest.mark.asyncio
    async def test_close(self, client):
        with pytest.MonkeyPatch.context() as mp:
            closed = False

            async def mock_close():
                nonlocal closed
                closed = True

            mp.setattr(client._client, "aclose", mock_close)

            await client.close()
            assert closed
