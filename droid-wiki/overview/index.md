# GroktoCrawl

GroktoCrawl is a self-hosted, MIT-licensed alternative to Firecrawl. It implements the Firecrawl v2 API surface -- scrape, search, map, crawl, extract, browser sessions, monitors, and the Agent endpoint (autonomous web research) -- without closed-source dependencies. Everything runs in Docker on your own hardware with a single `docker compose up`.

The project is built around a set of Python FastAPI microservices coordinated by Valkey (Redis-compatible) for job storage and queueing. It uses SearXNG for real web search, Qdrant for vector search, and Playwright for JavaScript-rendered page scraping. You bring your own LLM or use the built-in fixture services.

Key features: a three-tier smart scraper (llms.txt, content negotiation, Playwright), site-specific content adapters (YouTube, GitHub, Bluesky, Substack), an autonomous research agent with SSE streaming, grounded Q&A endpoint, semantic search with vector indexing, scheduled change monitors, and a full Firecrawl v2 API surface that works with existing Firecrawl SDKs and tooling.

## Quick links

- [Architecture](architecture.md) -- system components and data flows
- [Getting started](getting-started.md) -- prerequisites, install, build, test
- [Glossary](glossary.md) -- project-specific terms
- [How to contribute](../how-to-contribute/index.md)
- [API reference](../api/index.md)
