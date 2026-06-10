# Vector indexing

Active contributors: groktopus

## Purpose

The vector index provides persistent semantic search across all scraped pages. Every scrape, crawl, and batch scrape operation fire-and-forgets a page into the Qdrant vector database, enabling semantic retrieval without re-fetching content from the web.

## How it works

### Indexing pipeline

```mermaid
flowchart TD
    SCRAPE[Scrape / Crawl / Batch\ncomplete] --> HOOK[Fire-and-forget\nindexing hook in agent-svc]
    HOOK --> SVC[semantic-svc\nPOST /index or /index/batch]
    SVC --> EMBED[BGE-M3 embed\ncontent[:2000 chars]]
    EMBED --> PAYLOAD[Enrich payload:\nurl, title, domain_category,\ncrawl_count, access_count,\nfirst_indexed_at]
    PAYLOAD --> UPSERT[Qdrant upsert\nuint64 point ID\nfrom URL hash]
    UPSERT --> CHECK{docs > 250K?}
    CHECK -->|yes| SCORE[Score-based eviction\nretention_score =\ndomain_mult x recency\n+ access_boost + crawl_boost]
    SCORE --> EVICT[Delete lowest-scored\ndocuments]
    CHECK -->|no| DONE[Done]
```

### Retention scoring

When the index exceeds 250,000 documents, pages are scored by a composite function:

- **domain_multiplier**: 0.3 (news) to 1.2 (docs/reference), based on URL classification
- **recency_factor**: decays exponentially from 1.0 (today) to 0.1 (90+ days)
- **access_boost**: up to 1.0 for frequently returned search results
- **crawl_boost**: up to 1.0 for frequently re-crawled pages (monitors, recurring jobs)

News and social content evicts first. Reference and docs content persists longest.

### Embedding model migration

Named vectors in Qdrant allow multiple embedding models to coexist. Migration follows a state machine:

1. **backfill**: re-index all existing docs with the new model
2. **dual_write**: index new pages with both old and new models
3. **cutover**: switch search queries to the new model
4. **complete**: old vectors retained for rollback safety

Controlled via endpoints on semantic-svc: `POST /index/migrate/start`, `GET /index/migrate/status`, `POST /index/migrate/cutover`.

### Batch ingestion

For large crawls, `POST /index/batch` (via Qdrant gRPC) is ~200x faster than per-page indexing. Batch scrape and crawl workers accumulate pages and fire a single batch call.

## Key source files

| File | Purpose |
|---|---|
| `semantic-svc/app.py` | All vector index endpoints and Qdrant operations |
| `agent-svc/agent/semantic_client.py` | Client for semantic-svc from agent-svc |
| `agent-svc/agent/worker.py` | `_index_page_async()` and `_index_batch_async()` hooks |
