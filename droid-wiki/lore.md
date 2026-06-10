# Lore

## Origins (May 21, 2026)

GroktoCrawl began with a vision document (`VISION.md`) and an initial commit that set up the project skeleton. The project was conceived as a genuinely simple, self-contained, MIT-licensed alternative to Firecrawl -- one that could implement the full Firecrawl API surface including the Agent endpoint, which Firecrawl keeps closed-source in their self-hosted offering.

The name "GroktoCrawl" combines "grok" (to understand deeply) with "crawl", reflecting the project's philosophy: understand what the web needs from an extraction tool, not just replicate the architecture of an existing product.

## Era 1: Foundation and core API (May 21 -- May 24)

The first week established the architectural foundation:

- Agent service (`agent-svc`) with FastAPI, Valkey job store, and all core endpoints
- Three-tier scraper service (`scraper-svc`) with llms.txt, content negotiation, and Playwright
- Browser service (`browser-svc`) for headless Playwright sessions
- Parse service (`parse-svc`) for PDF/DOCX/PPTX/XLSX conversion
- Fixture services for local development (search-svc, llm-svc, test-site)
- Docker Compose stack with 8 containers
- The CLI tool for interacting with all endpoints

## Era 2: Adapters and content quality (May 24 -- Jun 5)

This era focused on improving content extraction quality:

- **Adapter framework** (ADR-0001 through ADR-0009): site-specific content handlers for YouTube, Bluesky, GitHub, and Substack
- **Five-tier scraper** with LLM recovery tier (ADR-0010)
- **Stealth Playwright configuration** for anti-detection (ADR-0011)
- **Webhook delivery** for async job completion (ADR-0012)
- **Search architecture** with vertical categories (ADR-0013)
- **Binary content detection** for non-HTML responses (ADR-0014)
- **Barrier classification** for block page detection (ADR-0015)
- **Extraction quality gates** for boilerplate and completeness (ADR-0016)

## Era 3: Agent features and observability (Jun 5 -- Jun 8)

Major feature expansion with releases v0.2.0 through v0.5.0:

- **Grounded Q&A** (`POST /v2/answer`) with citations (ADR-0017)
- **Observability infrastructure**: structured JSON logging, `/metrics` endpoint, health probes (ADR-0018)
- **Intelligent scrape cache** with ETag/Last-Modified revalidation (ADR-0019)
- **Proxy support** with SSRF guardrails (ADR-0020)
- **Web portal** with search bar UI (ADR-0021)
- **Agent SSE streaming** for real-time progress (ADR-0022)
- **Search type spectrum**: fast and rich modes (ADR-0023)
- **Artifact pyramid** CLI output format (ADR-0024)

## Era 4: Semantic search and vector indexing (Jun 8 -- Jun 9)

The most recent era (v0.6.0) added vector search capabilities:

- **Semantic search** with BGE-M3 embedding and cross-encoder reranking (ADR-0025)
- **Persistent vector index** in Qdrant (ADR-0026)
- **Smart index retention** with domain-weighted scoring (ADR-0027)
- **Embedding model migration path** using named vectors (ADR-0028)
- **Service-level metrics** for semantic-svc (ADR-0029)
- **Batch vector ingestion** via Qdrant gRPC for 200x speedup (ADR-0030)

## Longest-standing features

- The core `smart_scrape()` function and three-tier pipeline have survived all refactors since the project's first week
- The adapter framework architecture (pre-pipeline hook, regex dispatch, fallback chains) from ADR-0001 through ADR-0009 remains structurally unchanged
- The Valkey-backed job store has been used consistently across all job types

## Growth trajectory

The project grew rapidly from a skeleton to a full-featured Firecrawl alternative in 20 days, spanning 5 tagged releases (v0.2.0 through v0.6.0). The codebase expanded from ~5,000 lines to ~25,000 lines, adding 6 service modules and a vector database.
