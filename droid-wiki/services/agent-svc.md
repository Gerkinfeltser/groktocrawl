# agent-svc

Active contributors: groktopus

## Purpose

The agent service is the main API entry point for GroktoCrawl. It exposes all Firecrawl v2-compatible endpoints, manages async job processing, and orchestrates the research agent loop. It runs as a FastAPI application on port 8080.

## Directory layout

```
agent-svc/
├── Dockerfile
├── pyproject.toml
└── agent/
    ├── app.py              # FastAPI app factory, wires dependencies
    ├── api.py              # Route handlers (all endpoints)
    ├── models.py           # Pydantic request/response schemas
    ├── worker.py           # Async job processor functions
    ├── research.py         # Research agent loop (search, scrape, LLM)
    ├── scraper_client.py   # HTTP client to scraper-svc
    ├── searxng_client.py   # Search API client for SearXNG
    ├── llm.py              # OpenAI-compatible LLM client
    ├── llmstxt.py          # llms.txt generator
    ├── semantic_client.py  # HTTP client to semantic-svc
    ├── store.py            # Job CRUD backed by Valkey
    ├── webhook.py          # Webhook delivery with retry
    ├── auth.py             # Optional API key authentication
    ├── health.py           # Dependency health probes
    ├── metrics.py          # In-memory metrics collector
    └── monitor.py          # Scheduled change detection
```

## Key abstractions

| Abstraction | File | Description |
|---|---|---|
| `create_app()` | `agent/app.py` | FastAPI factory that wires all dependencies into `app.state` |
| `router` | `agent/api.py` | APIRouter with all endpoint handlers |
| `JobStore` | `agent/store.py` | Valkey-backed create/read/complete/fail for async jobs |
| `LLMClient` | `agent/llm.py` | OpenAI-compatible chat completion client |
| `SearXNGClient` | `agent/searxng_client.py` | SearXNG JSON API client with category translation |
| `ScraperClient` | `agent/scraper_client.py` | HTTP client to scraper-svc |
| `SemanticClient` | `agent/semantic_client.py` | HTTP client to semantic-svc for embed/rerank/index |
| `MetricsCollector` | `agent/metrics.py` | Thread-safe counter/histogram/gauge registry |
| `run_research()` | `agent/research.py` | Core research loop: search, scrape, LLM synthesis |
| `deliver_webhook()` | `agent/webhook.py` | HMAC-signed webhook delivery with exponential backoff |

## How it works

### Request lifecycle

1. A request arrives at one of the 17+ endpoints registered on the APIRouter in `api.py`
2. All routes (except `/health` and `/metrics`) pass through `verify_api_key()` in `auth.py` as a FastAPI dependency
3. A request ID middleware attaches a UUID to each request and logs start/completion with duration
4. Synchronous endpoints (scrape, search, map, answer) process inline
5. Async endpoints (agent, crawl, extract, batch scrape, llmstxt) create a job in Valkey via `JobStore`, then fire an `asyncio.create_task()` to process in the background
6. The security warning middleware adds an `X-Security-Warning` header when no API key is configured

### Job processing

Jobs are processed inline with `asyncio.create_task()` inside the API process, avoiding the need for a separate RQ worker container. Each job type has its own processing function in `worker.py`:

- `_process_agent_async()` -- runs the research loop, stores the result
- `_process_crawl_async()` -- scrapes a URL (crawl implementation is single-page for now)
- `_process_batch_scrape_async()` -- scrapes multiple URLs sequentially
- `_process_extract_async()` -- scrapes URLs and extracts structured data via LLM
- `_process_llmstxt_async()` -- generates an llms.txt file for a website

Each processor records metrics on submission, completion, and failure. Webhooks are delivered on completion or failure when configured.

### SSE streaming

The agent and answer endpoints support Server-Sent Events streaming. When `stream: true` is set, the response bypasses job creation and runs inline as an async generator:

1. Discovery phase: `sources_pending`, `source_scraped` events
2. Synthesis phase: `token` events from LLM output
3. Final: `done` event with the complete result, sources, and latency

## Entry points for modification

To add a new endpoint, add the route handler in `api.py`, add request/response models in `models.py`, and add a processing function in `worker.py`. For async endpoints (those returning a job ID), the handler must create a job via `JobStore.create_job()`, fire `asyncio.create_task()` with the processing function, and accept a `webhook` field for completion notifications.
