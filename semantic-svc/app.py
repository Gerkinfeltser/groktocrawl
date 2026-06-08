"""Semantic search service — embedding, reranking, and vector index.

Phase 1 endpoints (existing):
- POST /embed — vectorize query and document texts via BGE-M3
- POST /rerank — cross-encode query against documents via BGE-reranker-v2-m3

Phase 2 endpoints (new):
- POST /index — embed and store a page in the persistent vector index
- POST /search/vector — query the vector index by semantic similarity
- DELETE /index/{url_hash} — remove a page from the index
- GET /index/stats — index size and configuration

Phase 3 (this file):
- Smarter eviction: domain-based TTLs, crawl-frequency weighting, access boosting
- Domain classification of indexed URLs
- Access tracking on search result retrieval
- Retention score computed at eviction time
"""

import asyncio
import datetime
import hashlib
import logging
import math
import os
import urllib.parse

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


# ── Domain classification ─────────────────────────────────────────

# Domain patterns for retention categories
_DOCS_DOMAINS = {
    "readthedocs.io", "readthedocs.org",
}
_REFERENCE_DOMAINS = {
    "wikipedia.org", "stackoverflow.com", "stackexchange.com",
    "github.com", "gitlab.com",
}
_NEWS_DOMAINS = {
    "reuters.com", "nytimes.com", "cnn.com", "bbc.com", "bbc.co.uk",
    "bloomberg.com", "apnews.com", "npr.org", "theguardian.com",
    "wsj.com", "washingtonpost.com", "economist.com",
    "cnbc.com", "abcnews.go.com", "cbsnews.com", "nbcnews.com",
    "usatoday.com", "politico.com", "axios.com", "thehill.com",
}
_SOCIAL_DOMAINS = {
    "reddit.com", "twitter.com", "x.com", "youtube.com",
    "instagram.com", "tiktok.com", "threads.net",
    "bluesky", "bsky.app",
}
_BLOG_DOMAINS = {
    "medium.com", "substack.com", "ghost.io", "wordpress.com",
    "blogger.com", "blogspot.com",
}


def _compute_domain_category(url: str) -> str:
    """Classify a URL's domain into a retention category.

    Categories (in eviction-priority order):
        news (0.3), social (0.4), blog (0.6), api (0.7),
        unknown (0.8), reference (1.0), docs (1.2)
    """
    try:
        netloc = urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return "unknown"

    if not netloc:
        return "unknown"

    # Strip leading www. for consistent matching
    if netloc.startswith("www."):
        netloc = netloc[4:]

    # Prefix-based: docs./learn./help./api./developer.
    if netloc.startswith(("docs.", "learn.", "help.")):
        return "docs"
    if netloc.startswith(("api.", "developer.")):
        return "api"
    if netloc.startswith("blog."):
        return "blog"

    # Substring-based matches
    for d in _DOCS_DOMAINS:
        if d in netloc:
            return "docs"
    for d in _REFERENCE_DOMAINS:
        if d in netloc:
            return "reference"
    for d in _NEWS_DOMAINS:
        if d in netloc:
            return "news"
    for d in _SOCIAL_DOMAINS:
        if d in netloc:
            return "social"
    for d in _BLOG_DOMAINS:
        if d in netloc:
            return "blog"

    return "unknown"


# ── Retention scoring ─────────────────────────────────────────────

_DOMAIN_MULTIPLIERS = {
    "news": 0.3,
    "social": 0.4,
    "blog": 0.6,
    "api": 0.7,
    "unknown": 0.8,
    "reference": 1.0,
    "docs": 1.2,
}

_RECENCY_HALF_LIFE_DAYS = 90.0  # recency factor halves every ~63 days


def _compute_retention_score(payload: dict) -> float:
    """Compute retention score from a Qdrant point's payload.

    Higher score = more valuable to keep. Eviction targets lowest scores.

    score = domain_multiplier * recency_factor + access_boost + crawl_boost

    domain_multiplier: 0.3 (news) – 1.2 (docs)
    recency_factor:    decays from 1.0 (today) to 0.1 (90+ days)
    access_boost:      min(access_count, 100) * 0.01, max 1.0
    crawl_boost:       min(crawl_count, 20) * 0.05, max 1.0

    Worked examples:
      News, indexed today, never accessed:   0.3 * 1.00 = 0.30
      News, indexed 90d ago, never accessed: 0.3 * 0.37 = 0.11
      Docs, indexed 90d ago, accessed 50x:   1.2 * 0.37 + 0.50 = 0.94
      Docs, indexed 90d ago, accessed 50x, crawled 20x:
                                             1.2 * 0.37 + 0.50 + 1.00 = 1.94
    """
    category = payload.get("domain_category", "unknown")
    domain_mult = _DOMAIN_MULTIPLIERS.get(category, 0.8)

    # Recency: decay from 1.0 (indexed today) toward 0.1 (90+ days ago)
    raw_date = payload.get("last_indexed_at", "")
    if raw_date:
        try:
            last_indexed = datetime.datetime.fromisoformat(raw_date)
            days_since = (datetime.datetime.now(datetime.timezone.utc) - last_indexed).days
            days_since = max(0, days_since)
            recency_factor = math.exp(-days_since / _RECENCY_HALF_LIFE_DAYS)
            recency_factor = max(0.1, min(1.0, recency_factor))
        except (ValueError, TypeError):
            recency_factor = 0.5
    else:
        recency_factor = 0.5  # No date → middle-of-the-road priority

    # Access boost: pages returned in search results get a retention boost
    access_count = payload.get("access_count", 0)
    access_boost = min(int(access_count), 100) * 0.01

    # Crawl boost: frequently re-indexed pages (monitors, recurring) stay longer
    crawl_count = payload.get("crawl_count", 0)
    crawl_boost = min(int(crawl_count), 20) * 0.05

    return round(domain_mult * recency_factor + access_boost + crawl_boost, 4)


# ── Model helpers ─────────────────────────────────────────────────

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


def _url_hash(url: str) -> int:
    """Deterministic point ID from URL — first 64 bits of SHA-256 as uint64."""
    h = hashlib.sha256(url.encode()).hexdigest()
    return int(h[:16], 16)


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


# ── Scoring-based eviction (Phase 3) ──────────────────────────────

async def _evict_if_needed(qdrant: QdrantClient):
    """Scoring-based eviction if the index exceeds MAX_DOCS.

    Scrolls all points with payloads (no vectors needed), computes a
    retention score for each, and deletes the lowest-scoring documents
    until the index is under the cap plus a buffer to avoid thrashing.

    Domain-based TTLs, crawl-frequency weighting, and access-frequency
    boosting are handled by _compute_retention_score().
    """
    count = qdrant.count(COLLECTION_NAME).count
    if count <= MAX_DOCS:
        return

    excess = count - MAX_DOCS
    # Buffer: delete excess + 2% to avoid thrashing on re-index
    target_delete = excess + max(100, int(MAX_DOCS * 0.02))

    logger.info(
        "Index over capacity (%d / %d), scoring eviction candidates...",
        count, MAX_DOCS,
    )

    # Scroll all points with payloads (no vectors — much faster)
    scored_points: list[tuple[float, int]] = []
    next_offset: int | None = None
    page_size = 2000

    while len(scored_points) < target_delete or next_offset is not None:
        page, next_offset = qdrant.scroll(
            COLLECTION_NAME,
            limit=page_size,
            offset=next_offset,
            with_payload=True,
            with_vectors=False,
        )
        if not page:
            break
        for point in page:
            if point.payload is None:
                continue
            score = _compute_retention_score(point.payload)
            scored_points.append((score, point.id))

        # Once we have enough candidates and there are more pages,
        # keep going until we've seen all points
        if next_offset is None:
            break

    # Sort by score ascending (lowest = best eviction candidate)
    scored_points.sort(key=lambda x: x[0])

    # Delete the lowest-scoring points
    to_delete = [pid for _, pid in scored_points[:target_delete]]

    if to_delete:
        qdrant.delete(
            COLLECTION_NAME,
            points_selector=models.PointIdsList(points=to_delete),
        )
        new_count = qdrant.count(COLLECTION_NAME).count
        logger.info(
            "Scored eviction: removed %d documents (score range: %.4f – %.4f). "
            "Index at %d / %d",
            len(to_delete),
            scored_points[0][0] if scored_points else 0,
            scored_points[min(len(scored_points), target_delete) - 1][0]
            if scored_points else 0,
            new_count, MAX_DOCS,
        )
    else:
        logger.info("No eviction candidates found")


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
    url_hash: int


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


# ── Phase 2/3: Vector Index ──────────────────────────────────────

def _now_iso() -> str:
    """Return current UTC timestamp as ISO 8601 string."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _build_index_payload(url: str, title: str, existing_payload: dict | None) -> dict:
    """Build enriched payload for a new or updated index entry.

    Preserves first_indexed_at, access_count, and last_accessed_at from
    existing payload on re-index. Increments crawl_count.
    """
    now = _now_iso()
    domain_category = _compute_domain_category(url)

    if existing_payload:
        # Re-index: preserve first_indexed_at, access metadata
        first_indexed = existing_payload.get("first_indexed_at", now)
        access_count = int(existing_payload.get("access_count", 0))
        last_accessed = existing_payload.get("last_accessed_at", "")
        crawl_count = int(existing_payload.get("crawl_count", 0)) + 1
    else:
        # First index: all fresh
        first_indexed = now
        access_count = 0
        last_accessed = ""
        crawl_count = 1

    payload = {
        "url": url,
        "title": title,
        "domain_category": domain_category,
        "first_indexed_at": first_indexed,
        "last_indexed_at": now,
        "crawl_count": crawl_count,
        "access_count": access_count,
        "last_accessed_at": last_accessed,
    }

    # Compute and store retention score for cache (recalculated on eviction too)
    payload["retention_score"] = _compute_retention_score(payload)
    return payload


@app.post("/index", response_model=IndexResponse, status_code=201)
async def index_page(body: IndexRequest):
    """Embed and store a page in the persistent vector index.

    URL is used as the point ID — re-indexing the same URL
    updates the existing vector rather than creating a duplicate.

    Phase 3: enriches payload with domain category, crawl/access
    tracking metadata, and retention score.
    """
    qdrant = await _ensure_qdrant()
    model = _get_embed_model()

    # Check if this URL already exists (to preserve access metadata)
    point_id = _url_hash(body.url)
    existing_payload = None
    try:
        existing = qdrant.retrieve(
            COLLECTION_NAME,
            ids=[point_id],
            with_payload=True,
            with_vectors=False,
        )
        if existing and existing[0].payload:
            existing_payload = existing[0].payload
    except Exception:
        pass  # Best-effort — treat as new on failure

    # Embed the content
    embedding = model.encode(
        body.content[:2000], normalize_embeddings=True
    ).tolist()

    # Build enriched payload
    payload = _build_index_payload(body.url, body.title, existing_payload)

    qdrant.upsert(
        collection_name=COLLECTION_NAME,
        points=[
            models.PointStruct(
                id=point_id,
                vector=embedding,
                payload=payload,
            )
        ],
    )

    await _evict_if_needed(qdrant)

    return IndexResponse(status="indexed", url_hash=point_id)


@app.post("/search/vector", response_model=VectorSearchResponse)
async def search_vector(body: VectorSearchRequest):
    """Search the vector index by semantic similarity.

    Phase 3: after returning results, fires a background task to
    increment access_count and update last_accessed_at for the
    returned results.
    """
    qdrant = await _ensure_qdrant()
    model = _get_embed_model()

    query_embedding = model.encode(
        body.query, normalize_embeddings=True
    ).tolist()

    hits = qdrant.query_points(
        collection_name=COLLECTION_NAME,
        query=query_embedding,
        limit=body.limit,
    ).points

    results = [
        VectorSearchResult(
            url=h.payload.get("url", ""),
            title=h.payload.get("title", ""),
            score=float(h.score),
        )
        for h in hits
    ]

    # Fire-and-forget access tracking (Phase 3)
    if hits:
        asyncio.ensure_future(_track_access(qdrant, hits))

    return VectorSearchResponse(results=results)


async def _track_access(qdrant: QdrantClient, hits: list) -> None:
    """Increment access_count and update last_accessed_at for search results.

    Fire-and-forget — failure is logged but never propagated.
    """
    now = _now_iso()
    try:
        for hit in hits:
            point_id = hit.id
            payload = hit.payload or {}
            current_count = int(payload.get("access_count", 0))
            # Use set_payload instead of overwrite to avoid losing concurrent updates
            # We set only the access-related fields
            qdrant.set_payload(
                COLLECTION_NAME,
                points=[point_id],
                payload={
                    "access_count": current_count + 1,
                    "last_accessed_at": now,
                },
            )
        logger.debug("Tracked access for %d search results", len(hits))
    except Exception:
        logger.debug("Failed to track access for search results", exc_info=True)


@app.delete("/index/{url_hash}")
async def delete_index(url_hash: int):
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
