"""Semantic search service — embedding and reranking.

Provides two endpoints for the ad-hoc semantic search pipeline (Phase 1):
- POST /embed — vectorize query and document texts via BGE-M3
- POST /rerank — cross-encode query against documents via BGE-reranker-v2-m3

Models are loaded lazily on first request and cached in-process.
"""

from fastapi import FastAPI
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer, CrossEncoder
import numpy as np

app = FastAPI(title="semantic-svc")

# ── Model config ──────────────────────────────────────────────────
EMBED_MODEL_NAME = "BAAI/bge-m3"
RERANK_MODEL_NAME = "BAAI/bge-reranker-v2-m3"

_embed_model: SentenceTransformer | None = None
_rerank_model: CrossEncoder | None = None


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


# ── Endpoints ────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/embed", response_model=EmbedResponse)
async def embed(body: EmbedRequest):
    """Embed one or more texts into vectors.

    Returns normalized (unit-length) embeddings suitable for cosine
    similarity comparison via dot product.
    """
    model = _get_embed_model()
    embeddings = model.encode(body.input, normalize_embeddings=True)
    return EmbedResponse(embeddings=embeddings.tolist())


@app.post("/rerank", response_model=RerankResponse)
async def rerank(body: RerankRequest):
    """Cross-encode a query against a set of documents.

    Returns top-k results with relevance scores. More accurate than
    cosine reranking but slower — O(N) cross-encoder calls.
    """
    model = _get_rerank_model()
    pairs = [[body.query, doc] for doc in body.documents]
    scores = model.predict(pairs)
    indices = np.argsort(scores)[::-1][:body.top_k]
    results = [
        RerankResult(index=int(i), score=float(scores[i]))
        for i in indices
    ]
    return RerankResponse(results=results)
