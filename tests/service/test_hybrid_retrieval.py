"""Tests for the concurrent, cache-assisted hybrid retrieval planner.

Covers ``agent-svc/agent/research/hybrid.py``:

- concurrent, independently timeout-bounded web + vector discovery
- deterministic blend with the floor guarantee (no web-first starvation)
- URL normalization and overlap deduplication (provenance ``both``)
- Qdrant-only candidates surviving a full web budget
- provenance fields on every acquired artifact
- cache-hit vs live-scrape acquisition provenance
- graceful degradation (semantic down → keyword-only; web down → vector-only)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from agent.admission import AdmissionController
from agent.crawl_cache import CrawlCache
from agent.research.hybrid import plan_hybrid_retrieval


def _admission() -> AdmissionController:
    return AdmissionController(
        limits={"lightweight_fetch": 64, "browser": 32, "llm": 32}
    )


def _searxng(results: list[dict]) -> MagicMock:
    searxng = MagicMock()
    searxng.search = AsyncMock(return_value=(results, MagicMock()))
    return searxng


def _semantic(results: list[dict]) -> MagicMock:
    semantic = MagicMock()
    semantic.search_vector = AsyncMock(return_value=results)
    return semantic


def _make_cache() -> CrawlCache:
    """Build a dict-backed CrawlCache (mirrors test_crawl_cache.py mock pattern)."""
    store: dict[str, str] = {}

    mock = MagicMock()
    mock.get.side_effect = lambda key: store.get(key)
    mock.set.side_effect = lambda key, value, ex=None: store.update({key: value})
    mock.delete.side_effect = lambda key: store.pop(key, None)

    cache = CrawlCache("redis://localhost:6379/0")
    cache.redis = mock
    return cache


class FakeScraper:
    """Duck-typed scraper used by ``_scrape_urls`` (scrape_with_fallback)."""

    def __init__(self) -> None:
        self.scraped: list[str] = []

    async def scrape_with_fallback(self, url: str, **kwargs) -> dict:
        self.scraped.append(url)
        return {
            "success": True,
            "data": {"markdown": f"md {url}", "source": "test"},
        }

    async def close(self) -> None:
        pass


def _web(n: int) -> list[dict]:
    return [
        {"url": f"https://w{i}.com", "title": f"W{i}", "description": f"d{i}"}
        for i in range(n)
    ]


def _vec(n: int, offset: int = 0) -> list[dict]:
    return [
        {"url": f"https://v{i}.com", "title": f"V{i}", "score": 0.9 - i * 0.05}
        for i in range(offset, offset + n)
    ]


# ── Concurrent, timeout-bounded discovery ────────────────────────


@pytest.mark.asyncio
async def test_discovery_branches_run_concurrently():
    """Web and vector discovery overlap in time (not sequential)."""
    state = {"active": 0, "max_active": 0}

    async def slow_web(*_args, **_kwargs):
        state["active"] += 1
        state["max_active"] = max(state["max_active"], state["active"])
        await asyncio.sleep(0.05)
        state["active"] -= 1
        return [{"url": "https://w.com", "title": "W"}], MagicMock()

    async def slow_vector(*_args, **_kwargs):
        state["active"] += 1
        state["max_active"] = max(state["max_active"], state["active"])
        await asyncio.sleep(0.05)
        state["active"] -= 1
        return [{"url": "https://v.com", "title": "V"}]

    searxng = MagicMock()
    searxng.search = slow_web
    semantic = MagicMock()
    semantic.search_vector = slow_vector

    plan = await plan_hybrid_retrieval(
        "q", 5, searxng=searxng, semantic=semantic, admission=_admission()
    )

    assert state["max_active"] == 2
    assert {r["url"] for r in plan.results} == {"https://w.com", "https://v.com"}


@pytest.mark.asyncio
async def test_web_timeout_yields_vector_only():
    """A web branch that exceeds its timeout is dropped; vector results remain."""

    async def slow_web(*_args, **_kwargs):
        await asyncio.sleep(0.5)
        return [{"url": "https://w.com", "title": "W"}], MagicMock()

    searxng = MagicMock()
    searxng.search = slow_web
    semantic = _semantic(_vec(2))

    plan = await plan_hybrid_retrieval(
        "q",
        5,
        searxng=searxng,
        semantic=semantic,
        admission=_admission(),
        web_timeout=0.05,
    )

    assert [r["url"] for r in plan.results] == ["https://v0.com", "https://v1.com"]
    assert plan.web_count == 0


@pytest.mark.asyncio
async def test_vector_timeout_yields_web_only():
    """A vector branch that exceeds its timeout is dropped; web results remain."""

    async def slow_vector(*_args, **_kwargs):
        await asyncio.sleep(0.5)
        return [{"url": "https://v.com", "title": "V"}]

    searxng = _searxng(_web(2))
    semantic = MagicMock()
    semantic.search_vector = slow_vector

    plan = await plan_hybrid_retrieval(
        "q",
        5,
        searxng=searxng,
        semantic=semantic,
        admission=_admission(),
        vector_timeout=0.05,
    )

    assert [r["url"] for r in plan.results] == ["https://w0.com", "https://w1.com"]


# ── Deterministic blend / floor guarantee ────────────────────────


@pytest.mark.asyncio
async def test_web_full_vector_empty():
    """A full web budget with no vector results yields the web order."""
    plan = await plan_hybrid_retrieval(
        "q",
        5,
        searxng=_searxng(_web(5)),
        semantic=_semantic([]),
        admission=_admission(),
    )
    assert [r["url"] for r in plan.results] == [f"https://w{i}.com" for i in range(5)]
    assert all(r["retrieval"] == "web" for r in plan.results)


@pytest.mark.asyncio
async def test_vector_full_web_empty():
    """A full vector budget with no web results yields the vector order."""
    plan = await plan_hybrid_retrieval(
        "q",
        5,
        searxng=_searxng([]),
        semantic=_semantic(_vec(5)),
        admission=_admission(),
    )
    assert [r["url"] for r in plan.results] == [f"https://v{i}.com" for i in range(5)]
    assert all(r["retrieval"] == "vector" for r in plan.results)


@pytest.mark.asyncio
async def test_both_full_interleaves_deterministically():
    """Two full budgets interleave round-robin (web first), deterministically."""
    plan = await plan_hybrid_retrieval(
        "q",
        5,
        searxng=_searxng(_web(5)),
        semantic=_semantic(_vec(5)),
        admission=_admission(),
    )
    assert [r["url"] for r in plan.results] == [
        "https://w0.com",
        "https://v0.com",
        "https://w1.com",
        "https://v1.com",
        "https://w2.com",
    ]


@pytest.mark.asyncio
async def test_overlapping_urls_normalized_and_deduped():
    """Canonically-equivalent URLs collapse to one candidate (provenance both)."""
    web = [
        {"url": "https://Example.com/a/", "title": "A", "description": "desc a"},
        {"url": "https://example.com/b", "title": "B", "description": "desc b"},
        {"url": "https://example.com/c", "title": "C", "description": "desc c"},
    ]
    vector = [
        {"url": "https://example.com/a", "title": "A", "score": 0.95},
        {"url": "https://example.com/d", "title": "D", "score": 0.8},
    ]
    plan = await plan_hybrid_retrieval(
        "q",
        4,
        searxng=_searxng(web),
        semantic=_semantic(vector),
        admission=_admission(),
    )

    urls = [r["url"] for r in plan.results]
    # The overlap "a" keeps web's original URL; floors run before interleave.
    assert urls == [
        "https://Example.com/a/",
        "https://example.com/b",
        "https://example.com/d",
        "https://example.com/c",
    ]
    by_url = {r["url"]: r for r in plan.results}
    assert by_url["https://Example.com/a/"]["retrieval"] == "both"
    assert by_url["https://Example.com/a/"]["score"] == 0.95
    assert by_url["https://example.com/b"]["retrieval"] == "web"
    assert by_url["https://example.com/d"]["retrieval"] == "vector"


@pytest.mark.asyncio
async def test_qdrant_only_candidate_survives_full_web_budget():
    """The floor guarantee lets a Qdrant-only candidate into a full web set."""
    web = _web(5)
    vector = [
        {"url": "https://w0.com", "title": "W0", "score": 0.9},  # overlap
        {"url": "https://qdrant-only.com", "title": "Q", "score": 0.85},  # new
    ]
    plan = await plan_hybrid_retrieval(
        "q",
        5,
        searxng=_searxng(web),
        semantic=_semantic(vector),
        admission=_admission(),
    )

    urls = [r["url"] for r in plan.results]
    assert "https://qdrant-only.com" in urls
    by_url = {r["url"]: r for r in plan.results}
    assert by_url["https://qdrant-only.com"]["retrieval"] == "vector"
    # Exact deterministic order: web floor of 3, then the reserved vector slot
    # (the diversity floor emits the vector-only URL before the round-robin
    # interleave pulls in w3).
    assert urls == [
        "https://w0.com",
        "https://w1.com",
        "https://w2.com",
        "https://qdrant-only.com",
        "https://w3.com",
    ]


@pytest.mark.asyncio
async def test_no_overlap_full_web_budget_keeps_vector_only_candidate():
    """A vector-only candidate survives a full, non-overlapping web budget."""
    web = _web(5)
    vector = [{"url": "https://v0.com", "title": "V0", "score": 0.9}]
    plan = await plan_hybrid_retrieval(
        "q",
        5,
        searxng=_searxng(web),
        semantic=_semantic(vector),
        admission=_admission(),
    )

    urls = [r["url"] for r in plan.results]
    assert "https://v0.com" in urls
    by_url = {r["url"]: r for r in plan.results}
    assert by_url["https://v0.com"]["retrieval"] == "vector"
    # Deterministic order: web floor of 4 (w0..w3), then the reserved vector slot.
    assert urls == [
        "https://w0.com",
        "https://w1.com",
        "https://w2.com",
        "https://w3.com",
        "https://v0.com",
    ]


@pytest.mark.asyncio
async def test_no_overlap_full_vector_budget_keeps_web_only_candidate():
    """A web-only candidate survives a full, non-overlapping vector budget."""
    web = [{"url": "https://w0.com", "title": "W0", "description": "d"}]
    vector = _vec(5)
    plan = await plan_hybrid_retrieval(
        "q",
        5,
        searxng=_searxng(web),
        semantic=_semantic(vector),
        admission=_admission(),
    )

    urls = [r["url"] for r in plan.results]
    assert "https://w0.com" in urls
    by_url = {r["url"]: r for r in plan.results}
    assert by_url["https://w0.com"]["retrieval"] == "web"
    assert urls == [
        "https://w0.com",
        "https://v0.com",
        "https://v1.com",
        "https://v2.com",
        "https://v3.com",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("web", "vector", "limit", "expected"),
    [
        # Identical rank orders: the round-robin interleave must not emit the
        # overlapping URL at the shared pointer twice.
        (
            [
                {"url": "https://a.com", "title": "a"},
                {"url": "https://b.com", "title": "b"},
                {"url": "https://c.com", "title": "c"},
            ],
            [
                {"url": "https://a.com", "score": 0.9},
                {"url": "https://b.com", "score": 0.8},
                {"url": "https://c.com", "score": 0.7},
            ],
            4,
            ["https://a.com", "https://b.com", "https://c.com"],
        ),
        # Two overlapping top results under a tight budget.
        (
            [
                {"url": "https://a.com", "title": "a"},
                {"url": "https://x.com", "title": "x"},
            ],
            [
                {"url": "https://a.com", "score": 0.9},
                {"url": "https://y.com", "score": 0.8},
            ],
            2,
            ["https://a.com", "https://y.com"],
        ),
    ],
)
async def test_interleave_never_emits_duplicate_urls(web, vector, limit, expected):
    """Overlapping top results interleave without ever duplicating a URL."""
    plan = await plan_hybrid_retrieval(
        "q",
        limit,
        searxng=_searxng(web),
        semantic=_semantic(vector),
        admission=_admission(),
    )

    urls = [r["url"] for r in plan.results]
    assert urls == expected
    assert len(urls) == len(set(urls))


@pytest.mark.asyncio
async def test_malformed_urls_fall_back_and_do_not_crash():
    """Malformed result URLs degrade to raw text instead of aborting retrieval."""
    web = [
        {"url": "http://host:abc", "title": "bad port"},
        {"url": "http://[::1/path", "title": "bad ipv6"},
        {"url": "https://good.com", "title": "good"},
    ]
    plan = await plan_hybrid_retrieval(
        "q",
        5,
        searxng=_searxng(web),
        semantic=_semantic([]),
        admission=_admission(),
    )

    # The two malformed URLs fall back to their raw text; the healthy candidate
    # is still returned alongside them.
    assert [r["url"] for r in plan.results] == [
        "http://host:abc",
        "http://[::1/path",
        "https://good.com",
    ]
    assert all(r["retrieval"] == "web" for r in plan.results)


# ── Cache-assisted acquisition + provenance ──────────────────────


def _cache_entry(markdown: str) -> dict:
    return {"success": True, "data": {"markdown": markdown, "source": "tier1"}}


@pytest.mark.asyncio
async def test_cache_hit_vs_live_scrape_provenance():
    """Fresh cache content is reused; misses are live-scraped."""
    cache = _make_cache()
    cache.set("https://w0.com", _cache_entry("# Cached content"), ttl_ms=60000)

    scraper = FakeScraper()
    plan = await plan_hybrid_retrieval(
        "q",
        2,
        searxng=_searxng(_web(2)),
        semantic=_semantic([]),
        admission=_admission(),
        scraper=scraper,
        cache=cache,
        cache_max_age_ms=60000,
    )

    by_url = {a.url: a for a in plan.artifacts}
    assert by_url["https://w0.com"].cache_state == "from_cache"
    assert by_url["https://w0.com"].cache_age_ms is not None
    assert by_url["https://w0.com"].markdown == "# Cached content"
    assert by_url["https://w1.com"].cache_state == "live"
    assert by_url["https://w1.com"].cache_age_ms is None
    assert by_url["https://w1.com"].markdown == "md https://w1.com"
    # Only the cache miss was live-scraped.
    assert scraper.scraped == ["https://w1.com"]


@pytest.mark.asyncio
async def test_provenance_fields_present_on_every_artifact():
    """Every acquired artifact records retrieval, score, cache state, and age."""
    web = [
        {"url": "https://a.com", "title": "A", "description": "d"},
        {"url": "https://b.com", "title": "B", "description": "d"},
    ]
    vector = [
        {"url": "https://a.com", "title": "A", "score": 0.9},
        {"url": "https://c.com", "title": "C", "score": 0.7},
    ]
    plan = await plan_hybrid_retrieval(
        "q",
        3,
        searxng=_searxng(web),
        semantic=_semantic(vector),
        admission=_admission(),
        scraper=FakeScraper(),
        cache=_make_cache(),
        cache_max_age_ms=60000,
    )

    assert len(plan.artifacts) == 3
    for artifact in plan.artifacts:
        assert artifact.retrieval in ("web", "vector", "both")
        assert artifact.score is None or isinstance(artifact.score, float)
        assert artifact.cache_state in ("live", "from_cache")
        assert artifact.cache_age_ms is None or isinstance(artifact.cache_age_ms, int)


# ── Graceful degradation ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_semantic_down_falls_back_to_keyword_only():
    """A failing semantic service yields the exact web (keyword) result order."""
    web = _web(3)
    semantic = MagicMock()
    semantic.search_vector = AsyncMock(side_effect=Exception("semantic down"))

    plan = await plan_hybrid_retrieval(
        "q",
        5,
        searxng=_searxng(web),
        semantic=semantic,
        admission=_admission(),
    )

    assert [r["url"] for r in plan.results] == [f"https://w{i}.com" for i in range(3)]
    assert all(r["retrieval"] == "web" for r in plan.results)


@pytest.mark.asyncio
async def test_searxng_timeout_yields_vector_only():
    """A failing web branch yields vector-only results."""
    searxng = MagicMock()
    searxng.search = AsyncMock(side_effect=TimeoutError())

    plan = await plan_hybrid_retrieval(
        "q",
        5,
        searxng=searxng,
        semantic=_semantic(_vec(2)),
        admission=_admission(),
    )

    assert [r["url"] for r in plan.results] == ["https://v0.com", "https://v1.com"]
    assert all(r["retrieval"] == "vector" for r in plan.results)
