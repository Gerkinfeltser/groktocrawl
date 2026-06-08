# Semantic Search Pipeline — Embedding-Based Retrieval (Phase 1: Ad-Hoc Reranking)

* Status: proposed
* Deciders: magnus, jasper
* Date: 2026-06-09

Technical Story: GroktoCrawl's search is keyword-only via SearXNG. Complex, conceptual, or descriptive queries that don't match exact keywords produce poor results. The gap between what a user means and what keyword engines find is the single largest quality ceiling for the search product. A self-hosted semantic reranking pipeline using open-weight embedding models can close this gap without external API dependencies.

## Context and Problem Statement

GroktoCrawl's search pipeline is purely lexical:

```
User Query -> SearXNG (keyword) -> ranked by keyword match -> results
```

This produces poor results for queries like:
- "tools for self-hosted web archiving and monitoring" -> misses results that use words like "crawling", "snapshot", "change detection"
- "lightweight AI agent frameworks for personal use" -> misses results that say "local LLM harness", "single-user agent runtime"
- "emerging open source alternatives to proprietary cloud services" -> relies on exact phrases rather than conceptual similarity

The existing search type spectrum (ADR-0023) added `rich` mode (keyword -> scrape -> LLM synthesis) but that requires an LLM call and doesn't fundamentally change retrieval -- it enriches already-retrieved results. What's needed is a retrieval strategy that could return different URLs entirely -- ones that keyword search would never surface because the language differs.

Exa (exa.ai) demonstrated that embedding-based semantic search over billions of web pages can dramatically outperform keyword engines on retrieval quality benchmarks. While we cannot match their index scale, the architecture of self-hosted embedding models + reranking is a proven pattern.

### Phase Strategy

The full vision is a two-phase approach:

| Phase | What | Dependency | Complexity |
|---|---|---|---|
| **Phase 1** (this ADR) | Ad-hoc semantic reranking | Embedding model only | Low -- no persistent storage |
| **Phase 2** (future ADR) | Indexed vector search | Vector DB + background pipeline | High -- persistent index, refresh cycles |

**Phase 1** reranks SearXNG results by semantic similarity to the query. It cannot surface URLs SearXNG didn't find, but it reorders what SearXNG returns to put semantically relevant results first. This alone dramatically improves result quality for conceptual queries -- the right results are often in SearXNG's result set, just buried below keyword-matched noise.

**Phase 2** builds a persistent vector index of all pages GroktoCrawl has ever scraped, enabling retrieval from the crawl corpus independently of SearXNG. This turns GroktoCrawl into a learning search engine -- the more you use it, the better it gets. Phase 2 is out of scope for this ADR.

## Decision Drivers

* Must be **self-hosted** -- no external API dependency, no Exa API key required
* Must use **open-weight models** -- BGE-M3, BGE-reranker-v2-m3, or equivalent (MIT/Apache 2.0 licensed)
* Must **reuse existing infrastructure** -- SearXNG for initial retrieval, scraper-svc for content extraction
* Must be **opt-in and backward compatible** -- existing callers see zero change
* Must run on **CPU only** -- no GPU requirement (embeddings on CPU are fast enough for ad-hoc reranking of 5-10 documents)
* Must follow existing **service-per-concern** architecture -- new capability = new service, not function creep in agent-svc
* Must support `/v2/search` in Phase 1; `/v2/answer` integration deferred to follow-up

## Considered Options

### A. Semantic reranking as new `retrieval_mode` on existing endpoints *(chosen)*

Add a `retrieval_mode` field to `SearchRequest`:
- `keyword` (default) -- current behavior, zero change
- `semantic` -- SearXNG -> scrape -> embed -> rerank by cosine similarity -> return
- `hybrid` -- both keyword and semantic paths, merged via cross-encoder reranker

New service `semantic-svc`: small FastAPI service wrapping sentence-transformers with two endpoints:
- `POST /embed` -- embed query text + document texts -> return embeddings
- `POST /rerank` -- cross-encode query against documents -> return relevance scores

**Pipeline (semantic mode):**
1. Run SearXNG keyword search (existing)
2. Scrape top-N results to get full page content
3. Embed query + result contents via semantic-svc
4. Rerank by cosine similarity
5. Return reranked results

**Pipeline (hybrid mode):**
1. Run SearXNG keyword search
2. Scrape top-N results
3. Embed query + results
4. Cross-encode query against each result
5. Merge keyword rank + semantic score -> final ranking

**Positive:**
- Reuses 100% of existing infrastructure (SearXNG, scraper-svc)
- New service is isolated -- embedding model is the only new dependency
- Opt-in via field -- zero impact on existing callers
- BGE-M3 runs on CPU, ~2GB RAM, ~100ms per embedding
- Phase 2 can add vector DB to semantic-svc without changing the API contract

**Negative:**
- Adds scraping latency on every semantic/hybrid search (1-3s for 5 results)
- Embedding model adds ~2GB RAM to deployment footprint
- Cross-encoder reranker adds latency in hybrid mode (~50ms per document pair on CPU)
- semantic-svc is another container to maintain and deploy
- Phase 1 can only rerank what SearXNG finds -- it cannot surface new URLs (Phase 2 solves this)

### B. Embedding model integrated directly into agent-svc

Add sentence-transformers as a dependency of agent-svc. No new service.

**Positive:**
- Simpler deployment -- no new container
- No inter-service HTTP call latency

**Negative:**
- Violates service-per-concern architecture
- Embedding model competes for memory with LLM calls in the same process
- Can't scale embedding independently of the API server
- Adds ~2GB baseline RAM to agent-svc even when semantic search isn't used
- Rejected: violates architectural principle established by 5 existing services

### C. External embedding API (OpenAI embeddings, Cohere, etc.)

Use a cloud embedding API instead of a local model.

**Positive:**
- Zero infrastructure change
- Higher quality embeddings (frontier models)

**Negative:**
- Violates self-hosted requirement
- Recurring cost per query
- Network latency for every semantic search
- Privacy concern: query text leaves the self-hosted environment
- Rejected: core design principle is self-hosted

## Decision Outcome

Chosen option: **A. Semantic reranking as new `retrieval_mode`**.

### Architecture

```
                          +------------------+
                          |   agent-svc      |
                          |   (existing)     |
                          +---+------+-------+
                              |      |
              +---------------+      +---------------+
              v                                      v
    +------------------+                  +------------------+
    |   searxng        |                  |  semantic-svc    |
    |   (existing)     |                  |  (new)           |
    |                  |                  |                  |
    | keyword search   |                  | POST /embed      |
    | -> 10-20 URLs    |                  | POST /rerank     |
    +------------------+                  |                  |
                                          | BGE-M3 (embed)   |
                                          | BGE-reranker-v2  |
                                          +------------------+
```

**semantic-svc endpoints:**

| Endpoint | Method | Input | Output | Latency (CPU) |
|---|---|---|---|---|
| `/health` | GET | -- | `{"status": "ok"}` | <1ms |
| `/embed` | POST | `{"input": ["text1", "text2", ...]}` | `{"embeddings": [[float], ...]}` | ~100ms/doc |
| `/rerank` | POST | `{"query": "...", "documents": ["...", ...], "top_k": 5}` | `{"results": [{"index": 0, "score": 0.87}, ...]}` | ~50ms/doc pair |

### Positive Consequences

* Dramatically better retrieval for conceptual, descriptive, and niche queries
* Self-hosted -- no external API dependency, no recurring cost
* Opt-in -- zero impact on existing callers
* New service follows existing architecture pattern (one concern per service)
* Phase 2 can add vector DB without changing the API contract

### Negative Consequences

* Adds 1-3s latency for semantic/hybrid searches (scraping + embedding)
* Embedding model adds ~2GB RAM to deployment
* New service = new container to build, deploy, and monitor
* Cross-encoder reranker in hybrid mode is slower than cosine reranking
* Phase 1 can only rerank what SearXNG finds (not add new URLs)

### Risks

* **Cold start latency:** First request loads the embedding model (~5-10s). Mitigated by model preload at Docker build time.
* **Content quality for embedding:** Short search result descriptions produce poor embeddings. Mitigated by scraping full page content before embedding.
* **RAM pressure:** BGE-M3 is ~2GB. On a machine already running SearXNG, scraper-svc, agent-svc, and valkey, this could be tight. Mitigated by model size selection -- BGE-small-en (384-dim, ~130MB) is an acceptable fallback for lower-RAM deployments.

## Implementation Scope (This PR)

**In scope:**
- New `semantic-svc` Docker service with BGE-M3 embedding model
- `retrieval_mode` field on `SearchRequest`
- Semantic reranking pipeline in agent-svc (SearXNG -> scrape -> embed -> rerank)
- Hybrid mode with cross-encoder reranker
- `semantic_url` app state in agent-svc
- `.env.sample` update for `SEMANTIC_URL`
- docker-compose.yml update for semantic-svc
- ADR-0025 (this document)

**Out of scope (Phase 2, future ADR):**
- Persistent vector index (Chroma/Qdrant/pgvector)
- Background indexer pipeline (embed on scrape/crawl)
- Vector search as a retrieval source (alongside SearXNG)
- Index refresh and staleness management
- `/v2/answer` endpoint integration

## Links

* Issue: [#60](https://github.com/groktopus/groktocrawl/issues/60)
* Reference architecture: Exa API 2.0 ([exa.ai/blog/exa-api-2-0](https://exa.ai/blog/exa-api-2-0))
* Embedding model: [BGE-M3](https://huggingface.co/BAAI/bge-m3) (MIT license, 1024-dim, multilingual)
* Reranker: [BGE-reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3) (MIT license)
* Related ADRs: [ADR-0013](0013-search-architecture-with-vertical-categories.md), [ADR-0017](0017-grounded-qa-endpoint.md), [ADR-0023](0023-search-type-spectrum-fast-and-rich.md)
