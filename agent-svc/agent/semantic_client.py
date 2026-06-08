"""Async HTTP client for semantic-svc."""

import logging

import httpx

logger = logging.getLogger(__name__)


class SemanticClient:
    """Client for the semantic-svc embedding and reranking service."""

    def __init__(self, base_url: str = "http://semantic-svc:8003"):
        self.base_url = base_url.rstrip("/")
        self._client: httpx.AsyncClient | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=30,
                headers={"User-Agent": "GroktoCrawl/0.6"},
            )
        return self._client

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed one or more texts into normalized vectors.

        Returns a list of embedding vectors, each a list of floats.
        Vectors are L2-normalized — cosine similarity = dot product.
        """
        client = await self._ensure_client()
        resp = await client.post(
            f"{self.base_url}/embed",
            json={"input": texts},
        )
        resp.raise_for_status()
        return resp.json()["embeddings"]

    async def rerank(
        self, query: str, documents: list[str], top_k: int = 5
    ) -> list[dict]:
        """Cross-encode a query against documents and return top-k.

        Returns list of {"index": int, "score": float}, sorted by
        score descending. More accurate than cosine similarity but
        slower — O(N) cross-encoder calls.
        """
        client = await self._ensure_client()
        resp = await client.post(
            f"{self.base_url}/rerank",
            json={"query": query, "documents": documents, "top_k": top_k},
        )
        resp.raise_for_status()
        return resp.json()["results"]

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    # ── Phase 2: Vector Index ────────────────────────────────────

    async def index_page(self, url: str, title: str, content: str) -> dict:
        """Index a page in the persistent vector index.

        Re-indexing the same URL updates the existing vector.
        """
        client = await self._ensure_client()
        resp = await client.post(
            f"{self.base_url}/index",
            json={"url": url, "title": title, "content": content},
        )
        resp.raise_for_status()
        return resp.json()

    async def search_vector(
        self, query: str, limit: int = 5
    ) -> list[dict]:
        """Search the vector index by semantic similarity.

        Returns list of {"url": str, "title": str, "score": float}.
        """
        client = await self._ensure_client()
        resp = await client.post(
            f"{self.base_url}/search/vector",
            json={"query": query, "limit": limit},
        )
        resp.raise_for_status()
        return resp.json()["results"]
