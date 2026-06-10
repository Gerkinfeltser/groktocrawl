# Services

GroktoCrawl is composed of 8 core containers and 2 optional services, all managed by `docker-compose.yml`. Only the agent API, portal, semantic service, and SearXNG expose host ports -- internal services communicate via Docker internal DNS.

Active contributors: groktopus

## Available services

- [agent-svc](agent-svc.md) -- main FastAPI API and async job workers
- [scraper-svc](scraper-svc.md) -- URL to markdown conversion pipeline
- [browser-svc](browser-svc.md) -- Playwright headless browser sessions
- [semantic-svc](semantic-svc.md) -- embeddings, reranking, and vector index
- [portal-svc](portal-svc.md) -- web UI for human users
- [parse-svc](parse-svc.md) -- PDF, DOCX, PPTX, XLSX to markdown
- [search-svc](../reference/dependencies.md) -- search fixture for local testing
- [llm-svc](../reference/dependencies.md) -- LLM fixture for local testing
