# Glossary

| Term | Definition |
|------|------------|
| ADR | Architecture Decision Record. Documents significant architectural decisions in `docs/adr/`. |
| Agent | The autonomous web research endpoint (`POST /v2/agent`) that searches, scrapes, and synthesizes information. |
| BGE-M3 | BAAI's general embedding model used by semantic-svc for text embeddings and reranking. |
| FlareSolverr | Optional proxy service that bypasses Cloudflare challenges for JavaScript-rendered pages. |
| GTE-Qwen2 | Alternative embedding model family supported by semantic-svc. |
| llms.txt | A markdown file at a site's root that describes the site for LLMs (per llmstxt.org spec). |
| Named vectors | Qdrant feature allowing multiple embedding models to coexist in the same collection. |
| Ofelia | Docker-native cron scheduler that runs monitor checks on a schedule. |
| Politeness protocol | Optional rate-limiting system that respects robots.txt Crawl-delay directives. |
| Qdrant | Vector database used by semantic-svc for persistent vector storage and similarity search. |
| Quality gates | Post-extraction checks for boilerplate detection, completeness, and block page detection. |
| Retrieval modes | Five search modes: keyword, semantic, hybrid, vector, hybrid_vector. |
| SearXNG | Self-hosted meta search engine that aggregates results from multiple search sources. |
| Tier pipeline | Three-tier scraping strategy: llms.txt, content negotiation, Playwright. |
| Valkey | Redis-compatible key-value store used for job queue, cache, and storage. |
