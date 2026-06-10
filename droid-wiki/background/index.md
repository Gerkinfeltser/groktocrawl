# Background

GroktoCrawl's architecture is guided by a set of documented Architecture Decision Records (ADRs). This section covers the key design decisions and pitfalls.

## Design decisions

### Why MIT license

The project chose MIT over AGPL (which Firecrawl uses for self-hosted) to maximize adoption. MIT allows forking, embedding, and commercial use without legal friction. See the [VISION.md](https://github.com/groktopus/groktocrawl/blob/main/VISION.md) for the full rationale.

### Why inline async workers

Jobs are processed with `asyncio.create_task()` inside the API process instead of a separate RQ worker. This reduces complexity to a single container. For production deployments with high throughput, a separate worker container can be added later.

### Why three-tier scraping

The tier pipeline (llms.txt -> content negotiation -> Playwright) was designed to respect the web's agent-friendly signals before falling back to heavyweight browser rendering. This makes the scraper fast for LLM-friendly sites and gracefully degrades for JavaScript-heavy ones.

### Why adapters run before tiers

Adapters are checked before the tier pipeline, not after. This allows optimized extraction for known sites (YouTube transcripts, GitHub API) without going through generic HTML parsing. If the adapter fails, the generic pipeline runs as normal.

### Why Valkey over Redis

Valkey is a Redis-compatible fork under the Linux Foundation. It offers identical semantics and a liberal BSD-3-Clause license, avoiding Redis's license change to SSPL.

### Why Qdrant

Qdrant was chosen over Chroma, Pinecone, and Weaviate for its named vectors feature (essential for model migration), pure Rust performance, and permissive Apache 2.0 license.

## Pitfalls and danger zones

- **The adapter registry requires an internet connection for `pkg_resources` entry point scanning in some configurations.** Auto-registration via the `@adapter` decorator is the safer path.
- **The LLM recovery tier adds significant latency (20-60s) and cost.** It is a last resort, not a default path.
- **Inline job processing blocks the event loop during long-running jobs.** For high throughput, restore the RQ queue and separate the worker.
- **Semantic search modes rely on a running semantic-svc and Qdrant.** Without these, semantic, hybrid, vector, and hybrid_vector modes will error.
