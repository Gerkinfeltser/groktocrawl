# semantic-svc

Active contributors: groktopus

## Purpose

The semantic service provides text embeddings, cross-encoder reranking, and persistent vector search via Qdrant. It runs as a FastAPI application on port 8003 and is the backbone of GroktoCrawl's semantic and hybrid search modes.

## Directory layout

```
semantic-svc/
├── Dockerfile
├── pyproject.toml
├── app.py        # All endpoints: embed, rerank, index, search, migrate, metrics
└── metrics.py    # In-memory OpenMetrics collector (duplicated from agent-svc)
```

## Key abstractions

| Abstraction | Description |
|---|---|
| `SentenceTransformer` | BGE-M3 embedding model (configurable via `EMBED_MODEL_NAME`) |
| `CrossEncoder` | BGE-reranker-v2-m3 for query-document relevance scoring |
| `QdrantClient` | Client for Qdrant vector database at `qdrant:6333` |
| Named vectors | Multi-model coexistence in the same collection (e.g. `v_bge-m3`, `v_bge-m4`) |
| Migration state | In-memory state machine: idle, backfilling, dual_write, cutover, complete |

## How it works

### Phases

The service was built across four phases, each adding new capabilities:

**Phase 1 -- Embedding and reranking**: `POST /embed` vectorizes text via BGE-M3. `POST /rerank` cross-encodes a query against documents for relevance scoring.

**Phase 2 -- Vector index**: `POST /index` embeds and stores pages in Qdrant. `POST /search/vector` queries by semantic similarity. `DELETE /index/{url_hash}` removes pages. `GET /index/stats` reports index size.

**Phase 3 -- Smart retention**: When the index exceeds `VECTOR_INDEX_MAX_DOCS` (default 250,000), pages are scored by a composite function: `domain_multiplier * recency_factor + access_boost + crawl_boost`. News and social content evicts first; reference and docs content persists longest. Access tracking updates `access_count` and `last_accessed_at` after search queries.

**Phase 4 -- Model migration**: Named vectors enable multi-model coexistence. Migration follows a state machine: backfill (re-index with new model) -> dual_write (index with both models) -> cutover (switch queries). Old vectors are retained after cutover for rollback safety.

### Integration with search

The service is called by agent-svc for semantic and hybrid retrieval modes:

- **semantic mode**: SearXNG results are scraped, embedded, and cosine-reranked
- **vector mode**: queries Qdrant directly
- **hybrid_vector mode**: SearXNG and Qdrant results are merged and deduplicated by URL

## Integration points

- Called by agent-svc's `SemanticClient` for embed, rerank, index, and search operations
- Stores vectors in Qdrant
- Indexing is fire-and-forget from scrape/crawl/batch jobs -- failures never block the original operation

## Entry points for modification

To change the embedding model, set `EMBED_MODEL_NAME`, `EMBED_DIM`, and `ACTIVE_EMBED_MODEL` env vars. To add new index metrics, modify the `METRICS` singleton in `metrics.py`. Content eviction logic lives in the `_evict_if_needed()` function.
