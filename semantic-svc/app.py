"""Semantic search service — embedding, reranking, and vector index.

Phase 1 endpoints (existing):
- POST /embed — vectorize query and document texts via BGE-M3
- POST /rerank — cross-encode query against documents via BGE-reranker-v2-m3

Phase 2 endpoints (new):
- POST /index — embed and store a page in the persistent vector index
- POST /search/vector — query the vector index by semantic similarity
- DELETE /index/{url_hash} — remove a page from the index
- GET /index/stats — index size and configuration

Models are loaded lazily on first request and cached in-process.
"""

import hashlib
import logging
import os

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from qdrant_client import QdrantClient, models
from sentence_transformers import SentenceTransformer, CrossEncoder
import numpy as np

logger = logging.getLogger(__name__)

app = FastAPI(title="semantic-svc")

# ── Model config ──────────────────────────────────────────────────
EMBED_MODEL_NAME = "BAAI/bge-m3"
RERANK_MODEL_NAME = "BAAI/bge-reranker-v2-m3"
EMBED_DIM = 1024

_embed_model: SentenceTransformer | None = None
_rerank_model: CrossEncoder | None = None
_qdrant: QdrantClient | None = None
_qdrant_ready: bool = False

COLLECTION_NAME = "groktocrawl_pages"
MAX_DOCS = int(os.getenv("VECTOR_INDEX_MAX_DOCS", "250000"))
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")


def _get_embed_model() -> SentenceTransformer:
    global _embed_model
    if _embed_model is None:
        _embed_model = SentenceTransformer(EMBED_MODEL_NAME)
    return _embed_model


def _get_rerank_model() -> CrossEncoder:
    global _rerank_model
    if _rerank_model is None:
        _rerank_model = CrossEncoder(RERANK_MODEL_NAME)
    return _rerank_model


def _url_hash(url: str) -> str:
    """Deterministic point ID from URL."""
    return hashlib.sha256(url.encode()).hexdigest()


async def _ensure_qdrant() -> QdrantClient:
    """Lazy-init Qdrant client and collection."""
    global _qdrant, _qdrant_ready
    if _qdrant is None:
        _qdrant = QdrantClient(url=QDRANT_URL)
    if not _qdrant_ready:
        try:
            collections = _qdrant.get_collections()
            if COLLECTION_NAME not in [c.name for c in collections.collections]:
                _qdrant.create_collection(
                    collection_name=COLLECTION_NAME,
                    vectors_config=models.VectorParams(
                        size=EMBED_DIM,
                        distance=models.Distance.COSINE,
                    ),
                )
                logger.info("Created Qdrant collection '%s'", COLLECTION_NAME)
            _qdrant_ready = True
        except Exception as e:
            logger.error("Qdrant init failed: %s", e)
            raise HTTPException(503, "Vector index unavailable")
    return _qdrant


async def _evict_if_needed(qdrant: QdrantClient):
    """LRU eviction if the index exceeds MAX_DOCS."""
    count = qdrant.count(COLLECTION_NAME).count
    if count <= MAX_DOCS:
        return
    excess = count - MAX_DOCS
    # Qdrant doesn't track access time natively, so we approximate LRU
    # by deleting the oldest points by point ID (sequential UUIDs would
    # be ideal, but URL hashes are random — we use a simple overshoot).
    # For Phase 2: delete excess + 10% buffer to avoid thrashing.
    to_delete = excess + max(100, int(MAX_DOCS * 0.02))
    all_points = qdrant.scroll(
        COLLECTION_NAME, limit=to_delete, with_payload=False, with_vectors=False
    )[0]
    if all_points:
        ids = [p.id for p in all_points]
        qdrant.delete(COLLECTION_NAME, points_selector=models.PointIdsList(points=ids))
        logger.info("LRU eviction: removed %d documents (index at %d / %d)",
                     len(ids), qdrant.count(COLLECTION_NAME).count, MAX_DOCS)


# ── Request/Response models ──────────────────────────────────────

class EmbedRequest(BaseModel):
    model: str = "BGE-M3"
    input: list[str]


class EmbedResponse(BaseModel):
    embeddings: list[list[float]]


class RerankRequest(BaseModel):
    query: str
    documents: list[str]
    top_k: int = 5


class RerankResult(BaseModel):
    index: int
    score: float


class RerankResponse(BaseModel):
    results: list[RerankResult]


class IndexRequest(BaseModel):
    url: str
    title: str = ""
    content: str


class IndexResponse(BaseModel):
    status: str
    url_hash: str


class VectorSearchRequest(BaseModel):
    query: str
    limit: int = 5


class VectorSearchResult(BaseModel):
    url: str
    title: str
    score: float


class VectorSearchResponse(BaseModel):
    results: list[VectorSearchResult]


class IndexStatsResponse(BaseModel):
    total_docs: int
    max_docs: int


# ── Endpoints ────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/embed", response_model=EmbedResponse)
async def embed(body: EmbedRequest):
    """Embed one or more texts into normalized vectors."""
    model = _get_embed_model()
    embeddings = model.encode(body.input, normalize_embeddings=True)
    return EmbedResponse(embeddings=embeddings.tolist())


@app.post("/rerank", response_model=RerankResponse)
async def rerank(body: RerankRequest):
    """Cross-encode a query against documents, returning top-k."""
    model = _get_rerank_model()
    pairs = [[body.query, doc] for doc in body.documents]
    scores = model.predict(pairs)
    indices = np.argsort(scores)[::-1][:body.top_k]
    results = [
        RerankResult(index=int(i), score=float(scores[i]))
        for i in indices
    ]
    return RerankResponse(results=results)


# ── Phase 2: Vector Index ────────────────────────────────────────

@app.post("/index", response_model=IndexResponse, status_code=201)
async def index_page(body: IndexRequest):
    """Embed and store a page in the persistent vector index.

    URL is used as the point ID — re-indexing the same URL
    updates the existing vector rather than creating a duplicate.
    """
    qdrant = await _ensure_qdrant()
    model = _get_embed_model()

    # Embed the content
    embedding = model.encode(
        body.content[:2000], normalize_embeddings=True
    ).tolist()

    point_id = _url_hash(body.url)

    qdrant.upsert(
        collection_name=COLLECTION_NAME,
        points=[
            models.PointStruct(
                id=point_id,
                vector=embedding,
                payload={
                    "url": body.url,
                    "title": body.title,
                    "indexed_at": "",
                },
            )
        ],
    )

    await _evict_if_needed(qdrant)

    return IndexResponse(status="indexed", url_hash=point_id)


@app.post("/search/vector", response_model=VectorSearchResponse)
async def search_vector(body: VectorSearchRequest):
    """Search the vector index by semantic similarity."""
    qdrant = await _ensure_qdrant()
    model = _get_embed_model()

    query_embedding = model.encode(
        body.query, normalize_embeddings=True
    ).tolist()

    hits = qdrant.search(
        collection_name=COLLECTION_NAME,
        query_vector=query_embedding,
        limit=body.limit,
    )

    results = [
        VectorSearchResult(
            url=h.payload.get("url", ""),
            title=h.payload.get("title", ""),
            score=float(h.score),
        )
        for h in hits
    ]
    return VectorSearchResponse(results=results)


@app.delete("/index/{url_hash}")
async def delete_index(url_hash: str):
    """Remove a page from the vector index by URL hash."""
    qdrant = await _ensure_qdrant()
    qdrant.delete(
        COLLECTION_NAME,
        points_selector=models.PointIdsList(points=[url_hash]),
    )
    return {"status": "deleted"}


@app.get("/index/stats", response_model=IndexStatsResponse)
async def index_stats():
    """Return index size and configuration."""
    qdrant = await _ensure_qdrant()
    count = qdrant.count(COLLECTION_NAME).count
    return IndexStatsResponse(total_docs=count, max_docs=MAX_DOCS)
