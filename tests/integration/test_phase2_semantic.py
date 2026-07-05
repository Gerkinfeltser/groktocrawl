"""Integration tests for Phase 1 & 2 semantic search features.

Run inside the Docker network with:
    docker compose exec agent-svc python3 /app/tests/test_phase2_semantic.py

Requires the full stack: agent-svc, semantic-svc, searxng, scraper-svc, qdrant.
"""

import os
import time

import httpx

AGENT = os.getenv("AGENT_BASE_URL", "http://agent-svc:8080")
SEMANTIC = os.getenv("SEMANTIC_BASE_URL", "http://semantic-svc:8003")


def wait_for(url: str, path: str = "/health", timeout_s: int = 120):
    deadline = time.time() + timeout_s
    last_err = None
    while time.time() < deadline:
        try:
            r = httpx.get(url + path, timeout=2)
            if r.status_code == 200:
                return r
        except Exception as e:
            last_err = e
        time.sleep(2)
    raise RuntimeError(f"Timed out waiting for {url}{path}: {last_err}")


# ── Phase 1: Embedding & Reranking ───────────────────────────────


def test_embed_endpoint_returns_1024_dim_vectors():
    """POST /embed returns L2-normalized 1024-dim BGE-M3 vectors."""
    resp = httpx.post(
        SEMANTIC + "/embed",
        json={"input": ["hello world", "test sentence"]},
        timeout=120,
    )
    assert resp.status_code == 200
    data = resp.json()
    embeddings = data["embeddings"]
    assert len(embeddings) == 2
    for emb in embeddings:
        assert len(emb) == 1024
        # L2-normalized → magnitude ≈ 1.0
        mag = sum(x * x for x in emb) ** 0.5
        assert 0.99 < mag < 1.01, f"Expected unit vector, got magnitude {mag}"


def test_rerank_endpoint_ranks_relevant_higher():
    """POST /rerank puts relevant documents before irrelevant ones."""
    resp = httpx.post(
        SEMANTIC + "/rerank",
        json={
            "query": "machine learning algorithms",
            "documents": [
                "how to bake a chocolate cake",
                "supervised and unsupervised learning methods",
                "the history of ancient Rome",
                "neural networks and deep learning explained",
            ],
            "top_k": 3,
        },
        timeout=120,
    )
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert len(results) == 3
    # The two ML-related docs should rank above the cake and Rome docs
    ml_indices = {1, 3}  # indices of ML docs
    for r in results[:2]:
        assert r["index"] in ml_indices, (
            f"Expected ML doc in top 2, got index {r['index']}"
        )


# ── Phase 1: Search Retrieval Modes ──────────────────────────────


def test_keyword_mode_is_default_and_backward_compatible():
    """Keyword mode (default) returns results without semantic-svc dependency."""
    resp = httpx.post(
        AGENT + "/v2/search",
        json={"query": "fixture pricing", "limit": 3},
        timeout=120,
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["success"] is True
    assert len(payload["data"]["web"]) >= 1
    for result in payload["data"]["web"]:
        assert "url" in result
        assert "title" in result


def test_semantic_retrieval_mode_returns_results():
    """Semantic mode reranks by cosine similarity and returns results."""
    resp = httpx.post(
        AGENT + "/v2/search",
        json={
            "query": "fixture pricing information",
            "limit": 2,
            "retrieval_mode": "semantic",
        },
        timeout=300,
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["success"] is True
    assert len(payload["data"]["web"]) >= 1
    # Each result must have url and title
    for r in payload["data"]["web"]:
        assert r["url"], "Result missing URL"
        assert r["title"], "Result missing title"


def test_hybrid_retrieval_mode_returns_results():
    """Hybrid mode cross-encodes and returns results."""
    resp = httpx.post(
        AGENT + "/v2/search",
        json={
            "query": "fixture pricing options",
            "limit": 2,
            "retrieval_mode": "hybrid",
        },
        timeout=300,
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["success"] is True
    assert len(payload["data"]["web"]) >= 1


# ── Phase 2: Vector Index ────────────────────────────────────────


def test_index_endpoint_stores_and_retrieves():
    """Index a page, then search for it by semantic similarity."""
    # Index a distinctive test page
    idx_resp = httpx.post(
        SEMANTIC + "/index",
        json={
            "url": "https://fixture.test/unique-page-9944",
            "title": "Quantum Computing for Distributed Systems",
            "content": (
                "This page discusses quantum computing algorithms applied to "
                "distributed systems, including Shor's algorithm and Grover's "
                "search in the context of consensus protocols and leader election."
            ),
        },
        timeout=120,
    )
    assert idx_resp.status_code == 201
    idx_data = idx_resp.json()
    assert idx_data["status"] == "indexed"
    assert "url_hash" in idx_data

    # Search for it with a semantically related query
    search_resp = httpx.post(
        SEMANTIC + "/search/vector",
        json={"query": "quantum algorithms for consensus", "limit": 3},
        timeout=120,
    )
    assert search_resp.status_code == 200
    results = search_resp.json()["results"]
    assert len(results) >= 1
    # Our indexed page should be in the results
    urls = [r["url"] for r in results]
    assert "https://fixture.test/unique-page-9944" in urls, (
        f"Indexed page not found in search results: {urls}"
    )


def test_index_stats_reports_counts():
    """GET /index/stats returns total_docs and max_docs."""
    resp = httpx.get(SEMANTIC + "/index/stats", timeout=30)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_docs"] >= 1  # at least our test page
    assert data["max_docs"] == 250000


def test_delete_index_removes_page():
    """DELETE /index/{url_hash} removes a page from the index."""
    # Index a page
    idx_resp = httpx.post(
        SEMANTIC + "/index",
        json={
            "url": "https://fixture.test/delete-me-7721",
            "title": "Temporary Page",
            "content": "This page will be deleted.",
        },
        timeout=120,
    )
    url_hash = idx_resp.json()["url_hash"]

    # Delete it
    del_resp = httpx.delete(SEMANTIC + f"/index/{url_hash}", timeout=30)
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "deleted"

    # Verify it's gone
    search_resp = httpx.post(
        SEMANTIC + "/search/vector",
        json={"query": "temporary page", "limit": 5},
        timeout=120,
    )
    results = search_resp.json()["results"]
    urls = [r["url"] for r in results]
    assert "https://fixture.test/delete-me-7721" not in urls


# ── Phase 2: Vector Search Modes ─────────────────────────────────


def test_vector_retrieval_mode_queries_qdrant():
    """Vector mode queries Qdrant without SearXNG."""
    # First, index content via semantic-svc so there's something to find
    httpx.post(
        SEMANTIC + "/index",
        json={
            "url": "https://fixture.test/vector-test-3321",
            "title": "Advanced Fixture Testing",
            "content": (
                "Comprehensive guide to fixture-based testing with pytest, "
                "including parametrization, conftest.py patterns, and mock strategies."
            ),
        },
        timeout=120,
    )

    resp = httpx.post(
        AGENT + "/v2/search",
        json={
            "query": "pytest fixture patterns",
            "limit": 2,
            "retrieval_mode": "vector",
        },
        timeout=120,
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["success"] is True
    assert len(payload["data"]["web"]) >= 1
    # Should find our indexed fixture page
    urls = [r["url"] for r in payload["data"]["web"]]
    assert "https://fixture.test/vector-test-3321" in urls


def test_hybrid_vector_mode_merges_sources():
    """Hybrid vector mode queries SearXNG + Qdrant and merges results."""
    resp = httpx.post(
        AGENT + "/v2/search",
        json={
            "query": "pytest fixtures and testing",
            "limit": 5,
            "retrieval_mode": "hybrid_vector",
        },
        timeout=300,
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["success"] is True
    assert len(payload["data"]["web"]) >= 1
    # Results should have no duplicate URLs (dedup working)
    urls = [r["url"] for r in payload["data"]["web"]]
    assert len(urls) == len(set(urls)), f"Duplicate URLs found: {urls}"


def test_reindex_same_url_updates_not_duplicates():
    """Indexing the same URL twice updates the vector, doesn't create a duplicate."""
    url = "https://fixture.test/reindex-test-5588"

    # Index twice with different content
    httpx.post(
        SEMANTIC + "/index",
        json={
            "url": url,
            "title": "First",
            "content": "original content about databases",
        },
        timeout=120,
    )

    httpx.post(
        SEMANTIC + "/index",
        json={
            "url": url,
            "title": "Second",
            "content": "updated content about graph theory",
        },
        timeout=120,
    )

    # Search — should find the page but not twice
    resp = httpx.post(
        SEMANTIC + "/search/vector",
        json={
            "query": "graph theory and networks",
            "limit": 10,
        },
        timeout=120,
    )

    results = resp.json()["results"]
    matches = [r for r in results if r["url"] == url]
    assert len(matches) <= 1, (
        f"Duplicate indexed: found {len(matches)} entries for {url}"
    )


if __name__ == "__main__":
    import sys

    tests = [
        fn
        for name, fn in sorted(globals().items())
        if name.startswith("test_") and callable(fn)
    ]
    passed = 0
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
            passed += 1
        except Exception as e:
            print(f"FAIL {fn.__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed, {len(tests)} total")
    sys.exit(1 if failed else 0)
