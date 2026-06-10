# Agent research

Active contributors: groktopus

## Purpose

The agent endpoint (`POST /v2/agent`) is GroktoCrawl's autonomous web research capability. It searches the web, scrapes relevant pages, and synthesizes findings using an LLM -- all in a single API call. It is the project's flagship feature.

## How it works

### Sync flow (create, poll, retrieve)

1. `POST /v2/agent` creates a job in Valkey and returns a job ID
2. `_process_agent_async()` in `worker.py` runs the research loop in the background:
   - Searches SearXNG if no seed URLs are provided
   - Scrapes each URL through the scraper-svc pipeline (with concurrency limits)
   - Feeds scraped content into the LLM with a system prompt
   - Stores the synthesized result in Valkey
3. `GET /v2/agent/{job_id}` returns the status and result
4. Optional webhook fires on completion or failure

### SSE streaming flow

When `stream: true` is set, the endpoint bypasses job creation and runs inline:

```
POST /v2/agent {"prompt": "...", "stream": true}
→ SSE event stream:
  → data: {"type": "sources_pending", "sources": [...]}   -- search results found
  → data: {"type": "source_scraped", "url": "...", ...}   -- each page scraped
  → data: {"type": "token", "content": "..."}              -- LLM token output
  → data: {"type": "done", "result": "...", "sources": [...], "latency_ms": N}
  → data: [DONE]
```

### System prompt

The agent uses a fixed `SYSTEM_PROMPT` in `research.py` that instructs the LLM to:

- Evaluate source quality (official docs > established outlets > blogs > aggregators)
- Synthesize across multiple pages, detecting contradictions
- Cite sources by URL for every factual claim
- Flag uncertainty when sources are thin or incomplete
- Never use pre-training knowledge to fill gaps -- answer only from provided context

### Grounded Q&A (`POST /v2/answer`)

A lighter-weight synchronous endpoint that bridges search and agent: search, scrape top results, LLM synthesis with citations. Designed for 1-3s latency. Supports SSE streaming.

### Structured extraction (`POST /v2/extract`)

Scrapes provided URLs and extracts structured data matching a user-provided JSON Schema. Uses the `EXTRACT_SYSTEM_PROMPT` for LLM guidance.

## Key source files

| File | Purpose |
|---|---|
| `agent-svc/agent/research.py` | Research loop: `run_research()`, `run_research_stream()`, `run_answer()`, `run_extract()` |
| `agent-svc/agent/worker.py` | Async job processors for agent, crawl, extract, batch scrape |
| `agent-svc/agent/llm.py` | OpenAI-compatible LLM client with streaming |
| `agent-svc/agent/api.py` | Route handlers for agent, answer, extract endpoints |
| `agent-svc/agent/searxng_client.py` | Search client for source discovery |
| `agent-svc/agent/scraper_client.py` | Scrape client for content extraction |
