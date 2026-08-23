"""Route-level tests for find-similar error propagation (issue #588).

Exercises the real route wiring — ``agent.routes.router`` with the real
``groktocrawl_error_handler`` registered for ``GroktoCrawlError``, the same
minimal harness used by ``tests/service/test_rate_limit_contract.py`` — to
prove that a raised :class:`SemanticError` renders as HTTP 502 with the
standard ``ErrorResponse`` body and never as a success-shaped payload.

Also pins the healthy-path contracts: a successful vector search still
returns mapped results, a genuinely empty index still yields
``success:true, data:[]``, and the OpenAPI success schema for
``POST /v2/find-similar`` is unchanged.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agent.app import groktocrawl_error_handler
from agent.exceptions import GroktoCrawlError, SemanticError
from agent.routes import router
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _build_app() -> FastAPI:
    """Minimal real harness mirroring create_app's error-handler wiring."""
    app = FastAPI()
    app.state.rate_limiter = MagicMock()
    app.state.job_store = MagicMock()
    app.state.max_searches_per_request = 5
    app.state.task_tracker = MagicMock()
    app.state.llm_base_url = "http://llm.test/v1"
    app.state.llm_api_key = ""
    app.state.llm_model = "test-model"
    app.state.searxng_url = "http://searxng.test"
    app.state.scraper_url = "http://scraper.test"
    app.state.semantic_url = "http://semantic.test"
    app.state.research_memory = MagicMock()
    app.add_exception_handler(GroktoCrawlError, groktocrawl_error_handler)
    app.include_router(router)
    return app


@pytest.fixture
def client():
    return TestClient(_build_app())


def _patched_research(search_vector):
    """Patch the research-layer SemanticClient used by run_find_similar."""

    class _FakeSemantic:
        def __init__(self, base_url=""):
            pass

        async def search_vector(self, query, limit=5):
            return await search_vector(query, limit)

        async def embed(self, texts):
            return [[0.0] * 3 for _ in texts]

        async def close(self):
            pass

    class _FakeScraper:
        def __init__(self, base_url=""):
            pass

        async def scrape(self, url):
            return {
                "success": True,
                "data": {"markdown": "# Herbs", "metadata": {"title": "Herbs"}},
            }

        async def close(self):
            pass

    class _FakeSearx:
        def __init__(self, base_url=""):
            pass

        async def search(self, query, limit=5):
            return [], {}

        async def close(self):
            pass

    return (
        patch("agent.research.similar.ScraperClient", _FakeScraper),
        patch("agent.semantic_client.SemanticClient", _FakeSemantic),
        patch("agent.research.similar.SearXNGClient", _FakeSearx),
    )


class TestFindSimilarSemanticErrorContract:
    def test_semantic_error_renders_502_with_standard_error_body(self, client):
        """A raised SemanticError surfaces as 502 + ErrorResponse shape."""
        patches = _patched_research(
            AsyncMock(side_effect=SemanticError("semantic-svc vector search failed"))
        )
        with patches[0], patches[1], patches[2]:
            resp = client.post(
                "/v2/find-similar",
                json={"url": "https://example.com/herbs"},
            )

        assert resp.status_code == 502
        body = resp.json()
        assert body["success"] is False
        assert body["error"] == "semantic-svc vector search failed"
        assert body["error_code"] == "SEMANTIC_SERVICE_ERROR"
        # No success-model keys may leak into the error body.
        for key in ("query_url", "search_mode", "latency_ms", "data"):
            assert key not in body

    def test_semantic_error_propagates_through_route_without_local_handling(
        self, client
    ):
        """The route has no local try/except; the handler does the rendering.

        A GroktoCrawlError raised inside run_find_similar must reach the
        registered handler unchanged (status/error_code preserved).
        """
        err = SemanticError("upstream down")
        patches = _patched_research(AsyncMock(side_effect=err))
        with patches[0], patches[1], patches[2]:
            resp = client.post(
                "/v2/find-similar",
                json={"url": "https://example.com/herbs", "limit": 3},
            )

        assert resp.status_code == err.status_code == 502
        assert resp.json()["error_code"] == "SEMANTIC_SERVICE_ERROR"


class TestFindSimilarHealthyContracts:
    def test_success_still_returns_mapped_results(self, client):
        """A healthy vector search keeps returning mapped results."""

        async def _ok(query, limit):
            assert limit == 10  # FindSimilarRequest default
            return [
                {"url": "https://a.com", "title": "A", "content": "c" * 250},
                {"url": "https://b.com", "title": "B"},
            ]

        patches = _patched_research(_ok)
        with patches[0], patches[1], patches[2]:
            resp = client.post(
                "/v2/find-similar",
                json={"url": "https://example.com/herbs"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["query_url"] == "https://example.com/herbs"
        assert body["search_mode"] == "qdrant"
        assert isinstance(body["latency_ms"], float)
        assert len(body["data"]) == 2
        first, second = body["data"]
        assert first["url"] == "https://a.com"
        assert first["description"] == "c" * 200  # truncated at 200 chars
        assert second["description"] == ""  # no content key -> empty

    def test_genuinely_empty_index_returns_success_with_empty_data(self, client):
        """A clean empty result is success, never an error (issue #588)."""

        async def _empty(query, limit):
            return []

        patches = _patched_research(_empty)
        with patches[0], patches[1], patches[2]:
            resp = client.post(
                "/v2/find-similar",
                json={"url": "https://example.com/unindexed"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"] == []
        assert "error_code" not in body


class TestFindSimilarOpenApiSchema:
    def test_openapi_success_schema_is_find_similar_response(self):
        """No schema drift: success response stays FindSimilarResponse."""
        spec = _build_app().openapi()
        operation = spec["paths"]["/v2/find-similar"]["post"]
        declared = {
            int(code): models for code, models in operation["responses"].items()
        }
        assert 200 in declared
        success_ref = declared[200]["content"]["application/json"]["schema"][
            "$ref"
        ].split("/")[-1]
        assert success_ref == "FindSimilarResponse"
