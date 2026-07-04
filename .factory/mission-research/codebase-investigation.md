# GroktoCrawl Agent-Svc Codebase Investigation

> Generated: 2026-07-03 | Mission: Pre-phase planning for 5-phase feature addition

---

## 1. `agent-svc/agent/models.py` — Request/Response Models

### Key Patterns
- Uses **Pydantic v2** with `BaseModel`, `ConfigDict`, `Field`, validators
- **CamelCase aliasing** via `alias_generator=to_camel` and `populate_by_name=True`
- **`extra="allow"`** on `ScrapeOptions` for forward-compatible passthrough
- Consistent pattern: `success: bool = True`, `error: str | None = None` on responses
- `ErrorResponse` with `error_code` and `details` list for validation errors
- Field validators with `@field_validator` and model validators with `@model_validator(mode="after")`

### All Request/Response Models (46 models)

| Model | Role | Key Fields |
|-------|------|------------|
| `AgentRequest` | POST /v2/agent | `prompt` (max 100k), `urls`, `schema_` (alias="schema"), `model`, `stream`, `webhook`, `include_images`, `max_credits`, `strict_constrain_to_urls` |
| `AgentCreateResponse` | Response | `success`, `id` |
| `AgentStatusResponse` | GET /v2/agent/{id} | `status` (processing/completed/failed/cancelled), `data`, `error`, `expires_at`, `credits_used` |
| `AgentCancelResponse` | DELETE | `success` |
| `AnswerRequest` | POST /v2/answer | `query` (max 10k), `search_type`, `retrieval_mode`, `num_sources` (1-20), `model`, `stream` |
| `AnswerResponse` | Response | `answer`, `sources: list[Source]`, `citations: list[Citation]`, `search_type`, `latency_ms` |
| `SearchRequest` | POST /v2/search | `query`, `limit`, `search_type` (fast/rich/deep), `retrieval_mode` (keyword/semantic/hybrid/vector/hybrid_vector), `categories`, `sources`, `output_schema`, `system_prompt`, `contents`, `stream` |
| `SearchResponse` | Response | `data: dict` (web/images/news), `output`, `query_variations` |
| `SearchResult` | Item | `url`, `title`, `description`, `highlights`, `summary`, `extras`, `markdown` |
| `ScrapeOptions` | Nested options | `formats`, `only_main_content`, `include_tags`, `exclude_tags`, `wait_for`, `mobile`, `timeout`, `headers`, `max_age`, `min_age`, `actions`, `location`, `proxy`, `block_ads`, `parsers` |
| `CrawlRequest` | POST /v2/crawl | `url`, `max_pages`, `max_depth`, `limit`, `sitemap` (include/skip/only), `include_paths`, `exclude_paths`, `regex_on_full_url`, `scrape_options`, `prompt`, `stream`, `webhook`, etc. |
| `CrawlStatusResponse` | GET /v2/crawl/{id} | `status`, `completed`, `total`, `credits_used`, `data` (paginated), `next`, `created_at`, `completed_at`, `expires_at`, `duration` |
| `ExtractRequest` | POST /v2/extract | `urls`, `prompt`, `schema_`, `model`, `webhook` |
| `ExtractCreateResponse` / `ExtractStatusResponse` | CRUD | `id` / `status`, `data`, `error`, `expires_at` |
| `FindSimilarRequest/Response` | /v2/find-similar | `url`, `limit`, `search_mode`, `contents` |
| `MapRequest/Response` | /v2/map | `url`, `limit`, `search`, `allow_subdomains`, `allow_external_links` |
| `EnrichRequest/Response` | /v2/enrich | `items`, `fields`, `source_hint`, `effort` |
| `LLMsTextRequest/CreateResponse/StatusResponse` | /v2/generate-llmstxt | `url`, `max_pages`, `webhook` |
| `ParamsPreviewRequest/Response` | /v2/crawl/params-preview | `url`, `prompt` → derived params |
| `CrawlActiveItem/Response` | /v2/crawl/active | Crawl-specific fields |
| `CrawlErrorItem/ErrorsResponse` | /v2/crawl/{id}/errors | Error types, robots_blocked |
| `MonitorCreateRequest` | /v2/monitor | `url`, `schedule`, `webhook`, `monitor_type` (scrape/search), `search_config` |
| `MonitorResponse` | Response | `id`, `monitor_type`, `url`/`search_config`, `schedule`, `webhook`, `last_checked`, `last_result`, `created_at` |
| `BatchScrapeRequest/StatusResponse/ErrorsResponse` | /v2/batch/scrape | `urls`, `max_concurrency`, `webhook` |
| `BrowserCreate/Execute/List/Delete` | /v2/browser | Session management |
| `ParseResponse` | /v2/parse | Uploaded file → markdown |
| `ActivityItem/Response` | /v2/activity | Unified job feed |
| `ConcurrencyCheckResponse` | GET /v2/concurrency-check | `max_concurrency`, `current` |
| `VerbosityLevel`, `SectionCategory`, `ContentsOptions`, `ExtrasOptions`, `ErrorDetail`, `ErrorResponse`, `Source`, `Citation`, `ImageSearchResult` | Supporting types | Various helper models |

### What Needs to Change for New Features

- **Phase 1 (Structured Output & Compact Citations):**
  - `AgentRequest` and `AnswerRequest` already have `schema_` fields for structured output.
  - `AnswerRequest` already supports per-request model override via `model: str = "default"`.
  - May need new `Citation` model variants or `CompactCitation` model.
  - May need to add a `compact_citations: bool` flag.

- **Phase 2 (Session Protocol):**
  - Need new models: `SessionCreateRequest`, `SessionResponse`, `SessionMessage`, `SessionContext`.
  - Session metadata stored in Valkey — need `SessionStore` alongside `JobStore`.
  - `AgentRequest` may need `session_id` field.

- **Phase 3 (Plan-Consent & Depth Injection):**
  - Research plan already exists (`_generate_research_plan`), may need to expose plan as user-facing.
  - Need models for plan consent: `ResearchPlan`, `PlanConsentRequest`, `DepthInjectionConfig`.
  - Agent loop already has multi-pass gap detection — leverage existing infrastructure.

- **Phase 4 (Research Memory / Semantic Cache):**
  - Leverage existing `semantic-svc` (Qdrant) for semantic embeddings.
  - Reference `ScrapeOptions.max_age`/`min_age` for cache semantics pattern.
  - New models for memory config, cache policies.

- **Phase 5 (MCP Server):**
  - New FastAPI app or router.
  - Tool definitions as Pydantic models.
  - Leverage existing clients (`ScraperClient`, `SearXNGClient`, `LLMClient`).

---

## 2. `agent-svc/agent/api.py` — Routes

### All Endpoints (2023 lines)

| Method | Endpoint | Flow Pattern |
|--------|----------|-------------|
| GET | `/v2/activity` | Read from store, return list |
| POST | `/v2/scrape` | Sync: call scraper → index → return |
| POST | `/v2/agent` | **Dual-path:** stream=SSE inline OR create job + background task |
| GET/DELETE | `/v2/agent/{job_id}` | Store lookup |
| POST | `/v2/crawl` | **Dual-path:** stream=SSE OR create job + `_process_crawl_async` |
| GET | `/v2/crawl/active` | Store SCAN filtered by kind+status |
| GET | `/v2/crawl/{job_id}` | Store lookup + pagination logic |
| GET | `/v2/crawl/{job_id}/stream` | SSE replay of completed crawl |
| GET | `/v2/crawl/{job_id}/errors` | Extract errors from stored data |
| DELETE | `/v2/crawl/{job_id}` | Store.cancel_job() |
| POST | `/v2/crawl/params-preview` | Sync: NL→params via LLM |
| POST | `/v2/batch/scrape` | Create job + background task |
| GET/DELETE | `/v2/batch/scrape/{job_id}` | Store CRUD |
| POST | `/v1/search` | Sync: SearXNG → flat results |
| POST | `/v2/search` | **Dual-path:** stream=SSE OR sync with multi-mode routing (deep/rich/fast, vector/hybrid/semantic/kw) |
| POST | `/v2/find-similar` | Sync: qdrant or web modes |
| POST | `/v2/answer` | **Dual-path:** stream=SSE OR sync |
| POST | `/v2/enrich` | Sync: batch search→scrape→LLM |
| POST | `/v2/extract` | Create job + background task |
| GET | `/v2/extract/{job_id}` | Store lookup |
| POST | `/v2/map` | Sync: fetch page → extract links |
| POST/GET/PATCH/DELETE | `/v2/monitor*` | Monitor CRUD + trigger |
| POST/GET/DELETE | `/v2/browser*` | Proxy to browser-svc |
| PUT | `/v2/parse/upload/{id}` | Upload to Valkey |
| POST | `/v2/parse` | File → parse-svc |
| POST | `/v2/generate-llmstxt` | Create job + background |
| GET | `/v2/generate-llmstxt/{job_id}` | Store lookup |

### Pattern for Adding New Endpoints

Per AGENTS.md:
1. Add route handler in `api.py`
2. Add request/response models in `models.py`
3. **If async (returns job ID): MUST accept `webhook` field** and fire via `deliver_webhook()`
4. Rebuild agent-svc image
5. Add test in `test_stack.py`

### Dual-Path Pattern (for streaming)

The codebase has a standard pattern for endpoints supporting both sync and streaming:

```python
if body.stream:
    # SSE path: run inline, return StreamingResponse
    async def event_stream():
        async for event in some_stream_fn(...):
            yield f"data: {json.dumps(event)}\n\n"
        yield "data: [DONE]\n\n"
    return StreamingResponse(event_stream(), media_type="text/event-stream")
else:
    # Sync path: create job, background task, return job ID
    job_id = store.create_job(kind="...", payload=body.model_dump())
    request.app.state.task_tracker.create_background_task(
        _process_xxx_async(job_id=job_id, ...)
    )
    return XxxCreateResponse(id=job_id)
```

### Rate Limiting Pattern
- Per-client IP via `_get_client_ip(request)` reading `X-Forwarded-For` header
- Valkey-backed sliding window via `rate_limiter.check(f"{client_ip}:search")`
- Response headers: `X-Search-Rate-Remaining`, `X-Search-Budget`

### App State Dependencies

All endpoints access services via `request.app.state`:
- `request.app.state.job_store` (JobStore)
- `request.app.state.scraper_client` (ScraperClient) — for sync scrape endpoint
- `request.app.state.scraper_url` (string) — for async endpoints
- `request.app.state.searxng_url` (string)
- `request.app.state.llm_base_url`, `.llm_api_key`, `.llm_model` (strings)
- `request.app.state.semantic_url` (string)
- `request.app.state.task_tracker` (TaskTracker)
- `request.app.state.rate_limiter` (RateLimiter)
- `request.app.state.max_searches_per_request` (int)

---

## 3. `agent-svc/agent/llm.py` — LLM Client

### Key Class: `LLMClient`

```python
class LLMClient:
    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self._client = httpx.AsyncClient(timeout=120)

    async def generate(system_prompt, user_prompt, context=None, schema=None) -> str
    async def generate_stream(system_prompt, user_prompt, context=None) -> AsyncGenerator[dict]
    async def check_health() -> bool
    async def close() -> None
```

### Structured Output Support
- **Already supported** via `schema` parameter in `generate()`.
- Uses `response_format: {"type": "json_object"}` and injects schema into system prompt.
- Pattern:
  ```python
  if schema:
      body["response_format"] = {"type": "json_object"}
      messages[0]["content"] += (
          f"\n\nYou MUST respond with valid JSON matching this schema:\n"
          f"{json.dumps(schema, indent=2)}"
      )
  ```
- **Limitation:** Uses `json_object` mode, not `json_schema` (strict mode). For Phase 1, may want to upgrade to strict `json_schema` with `name` parameter for better structured output compliance.

### Streaming Pattern
- Yields `dict` events: `{"type": "token", "content": ...}`, `{"type": "done", "full_content": ...}`, `{"type": "error", "content": ...}`
- Handles `data: [DONE]` termination
- Streaming does NOT currently support schema — `generate_stream` has no `schema` param. Only non-streaming `generate()` supports schema.

### Provider-Agnostic
- OpenAI-compatible endpoint at `{base_url}/chat/completions`
- Supports `enable_thinking` extension (Anthropic/DeepSeek) via settings
- Model override: `effective_model = requested_model if requested_model != "default" else llm_model`

### What Needs to Change
- **Phase 1:** Add `json_schema` strict mode support; add schema support to `generate_stream`
- **Phase 3:** May need different system prompts for plan-consent phase
- **Phase 4:** May need embedding-cost-aware routing decisions (which model to query)

---

## 4. `agent-svc/agent/worker.py` — Job Processing

### Key Functions

```python
async def _run_job_with_observability(job_id, job_type, store, webhook_config, work_fn, cleanup_fn=None)
    # Encapsulates: metrics recording, store.complete_job/fail_job, webhook delivery, cleanup
    # This is the shared scaffolding for ALL worker functions

async def _process_agent_async(job_id, prompt, urls, schema_, llm_*, searxng_url, scraper_url, webhook_config, requested_model, include_images)
    # Creates JobStore → calls run_research() → complete_job()

async def _process_crawl_async(job_id, url, max_pages, max_depth, scraper_url, webhook_config, task_tracker, ...)
    # Creates JobStore + CrawlEngine → engine.run() → per-page webhooks → complete_job()

async def _process_batch_scrape_async(job_id, urls, scraper_url, webhook_config, task_tracker)
    # Per-URL scrape loop with cancellation support

async def _process_extract_async(job_id, urls, prompt, schema_, llm_*, scraper_url, webhook_config)
    # Calls run_extract()

async def _process_llmstxt_async(job_id, url, max_pages, scraper_url, webhook_config)
    # Calls generate_llmstxt()
```

### Flow Patterns

**Agent flow:** `POST /v2/agent` → `create_job()` → `_process_agent_async()` → `run_research()` (plan→search→scrape→LLM→gaps) → `complete_job()` → `deliver_webhook()`

**Crawl flow:** `POST /v2/crawl` → `create_job()` → `_process_crawl_async()` → `CrawlEngine.run()` → per-page callbacks + webhooks → `complete_job()`

**Observability scaffold:** `_run_job_with_observability()` handles metrics, store operations, webhook delivery. Used by all worker functions except `_process_crawl_async` (which has custom lifecycle webhooks).

### What Needs to Change
- **Phase 1:** May need new worker function for structured output that handles schema validation pre/post-LLM
- **Phase 2:** New worker functions for session management (session create, message, context list)
- **Phase 3:** Enhance `_process_agent_async` with plan consent step between Phase 0 (planning) and Phase 1 (research)
- **Phase 4:** Memory-aware worker that checks semantic cache before scraping
- **Phase 5:** MCP server lives outside worker pattern — separate process or inline

---

## 5. `agent-svc/agent/research.py` — Agent Research Loop

### Architecture

The research loop is the heart of the agent. It has this flow:

```
Phase 0: Query Intelligence (_generate_research_plan)
    → LLM analyzes prompt → returns strategy (deep/focused) + focused_queries

Phase 1: Discovery (_run_research_discover_and_scrape or _run_multi_query_discover_and_scrape)
    → Search (single or multi-query) → Filter/rank URLs → Scrape → Build context

Phase 2: Synthesis (LLM.generate with context + schema)
    → LLM produces answer from context

Gap Detection (_detect_gaps)
    → LLM analyzes context for missing topics → triggers Pass 2

Pass 2 (if gaps found):
    → Search gap topics → Scrape → Append to combined context → Re-synthesize
```

### System Prompts

- **`SYSTEM_PROMPT`** (~60 lines): "determined web research agent" — identity, source quality evaluation, synthesis rules, integrity (cite-only, no fabrication), output quality guidelines
- **`EXTRACT_SYSTEM_PROMPT`** (~10 lines): structured data extraction from web content
- **`QUERY_INTELLIGENCE_SYSTEM_PROMPT`**: research planning agent that decomposes broad prompts into focused queries
- **`ANSWER_SYSTEM_PROMPT`**: Q&A agent with inline citation markers [1], [2]
- **`RICH_SEARCH_SYSTEM_PROMPT`**: search result enrichment engine
- **`HIGHLIGHTS_SYSTEM_PROMPT`** / **`SUMMARY_SYSTEM_PROMPT`**: content extraction helpers
- **`DEEP_SEARCH_GAP_PROMPT`**: search coverage analyst
- **`ENRICH_SYSTEM_PROMPT`**: structured data extractor for enrich pipeline

### Key Functions

```python
async def run_research(prompt, urls, schema, searxng_url, scraper_url, llm_*, requested_model, include_images) -> dict
    # Main research loop: plan → search → scrape → think → answer (2-pass)

async def run_research_stream(prompt, ...) -> AsyncGenerator
    # Streaming version — yields SSE-suitable dicts

async def run_answer(query, num_sources, search_type, retrieval_mode, ...) -> dict
    # Grounded Q&A: search → scrape → LLM → citations

async def run_answer_stream(query, ...) -> AsyncGenerator

async def run_extract(urls, prompt, schema, scraper_url, llm_*) -> dict
    # Extract structured data from given URLs (no search step)

async def run_enrich_pipeline(items, fields, source_hint, effort, ...) -> list[dict]
    # Batch enrichment: search → scrape → LLM extraction per item

async def run_deep_search(query, limit, ...) -> dict
    # Multi-pass search with LLM gap analysis

async def run_rich_search(search_results, query, limit, output_schema, ...) -> dict
    # Enrich search results with full-page content

async def run_find_similar(url, limit, search_mode, ...) -> list[dict]
    # Semantic similarity search (qdrant or web mode)

async def run_search_stream(query, ...) -> AsyncGenerator
    # Streaming version of /v2/search

async def _generate_research_plan(prompt, llm) -> dict
    # Phase 0: LLM analyzes prompt, generates research plan
    # Returns: {reasoning, research_strategy, focused_queries}

async def _scrape_urls(urls, scraper, min_sources, max_attempts, ...) -> tuple[list[str], list[dict]]
    # Concurrent scrape with bounded semaphore, early-stop at min_sources

async def _detect_gaps(combined_context, llm) -> list[str]
    # LLM-based gap detection — returns list of missing topic strings

def _filter_and_rank_urls(urls, max_urls) -> list[str]
    # Score URLs by domain authority, path depth, penalty for social media/login pages

async def process_contents_for_results(results, query, contents_options, llm_client, scraper_client) -> list[dict]
    # Apply highlights/summary/extras per search result
```

### Multi-Pass Research
- Default: 1 pass. Gap detection may trigger a 2nd pass (capped at 2).
- Pass 2 searches gap topics discovered by LLM analysis of Pass 1 context.
- Combined context from both passes is used for final synthesis.

### What Needs to Change
- **Phase 1:** Research loop already supports `schema`. May need compact citation formatting (e.g., [1](url) instead of just [1]).
- **Phase 2:** Wrap research loop in a session context — store conversation history, allow follow-up queries with prior context.
- **Phase 3:** Expose `_generate_research_plan` results as user-facing plan for consent. Allow user to modify queries/strategy before research runs. Add depth injection (recursive sub-topic exploration).
- **Phase 4:** Check semantic cache before scraping; store research results in memory for cross-session retrieval.
- **Phase 5:** Expose research functions as MCP tools.

---

## 6. `agent-svc/agent/store.py` — Valkey-Backed Job Storage

### Key Class: `JobStore`

```python
class JobStore:
    def __init__(self, redis_url: str)
    def create_job(kind, payload) -> str           # UUID v4, sets meta+data+completed keys
    def get_job(job_id) -> dict | None             # Gets meta, attaches data if available
    def complete_job(job_id, data) -> None         # Only transitions processing→completed
    def fail_job(job_id, error) -> None            # Only transitions processing→failed
    def cancel_job(job_id) -> bool                 # Returns True if cancelled
    def increment_completed(job_id) -> int         # Atomic INCR for crawl progress
    def get_completed(job_id) -> int               # Read atomic counter
    def update_job_progress(job_id, pages, total, errors, ...) -> None  # Writes data key
    def list_active_jobs(kind, status, limit) -> list[dict]  # SCAN-based listing
    def count_active_jobs(kind) -> int             # SCAN-based counting
```

### Key Schema
```
job:{id}:meta     → JSON {id, kind, status, created_at, expires_at, completed_at, payload}
job:{id}:data     → JSON {completed, total, pages, errors, robots_blocked, filtered_out}
job:{id}:completed → INTEGER (atomic counter, INCR-based)
```

### Concurrency Safety
- `complete_job()` and `fail_job()` only transition from `processing` — prevent overwriting `cancelled` status
- `increment_completed()` uses Valkey `INCR` for atomic counter
- Data writes use `SET` (not GETSET) — the completed count comes from atomic counter, not list length

### TTL
- 24 hours (86400 seconds) for all job keys

### What Needs to Change
- **Phase 2:** New `SessionStore` class with similar pattern for session keys: `session:{id}:meta`, `session:{id}:messages`, `session:{id}:context`
- **Phase 4:** New `MemoryStore` for semantic cache entries: `memory:{hash}:entry` with TTL policies

---

## 7. `agent-svc/agent/scraper_client.py` — Scraper Client

### Key Class: `ScraperClient`

```python
class ScraperClient:
    def __init__(self, base_url: str)
        # httpx.AsyncClient with timeout=60, max_connections=100

    async def scrape(url, force_browser=False, ignore_robots_txt=False, robots_user_agent=None, scrape_options=None) -> dict
        # POST {base_url}/scrape with JSON body
        # Records metrics by source tier (tier label in histogram)

    async def scrape_with_fallback(url, generic_timeout=20s, browser_timeout=45s, scrape_options=None) -> dict
        # Try fast path first, fall back to browser-scrape on failure/empty

    async def scrape_urls_batch(urls, max_concurrent=5, url_timeout=20s, min_sources=10) -> list[dict]
        # Concurrent batch scrape with early-stop at min_sources

    async def close() -> None
```

### Interface
- POST to `{scraper_url}/scrape` with `{"url": "...", ...}`
- Returns: `{"success": bool, "data": {"markdown": str, "source": str, ...}, "error": str}`

### What Needs to Change
- No significant changes needed for new phases — scraper client is a stable abstraction.
- Phase 4 may benefit from caching-aware scrape (already partially supported via `max_age`/`min_age`).

---

## 8. `agent-svc/agent/searxng_client.py` — Search Client

### Key Class: `SearXNGClient`

```python
class SearXNGClient:
    def __init__(self, base_url: str, max_searches: int = 5)
        # httpx.AsyncClient with timeout=15, UA header, X-Forwarded-For

    async def search(query, limit=10, categories=None, sources=None) -> tuple[list[dict], SearchHealth]
        # GET {base_url}/search?q=...&format=json&...
        # Enforces per-request search budget (raises RateLimitedError)
        # Translates Firecrawl v2 sources/categories to SearXNG categories
        # Returns: (results, health)

    @staticmethod _translate(sources, categories) -> list[str]
        # Maps web→general, news→news, images→images, video→videos, social→general
        # Maps research→science, github→it, pdf→general, etc.

    @staticmethod _parse_engine_health(data, results) -> SearchHealth
        # Analyzes engine status from SearXNG response

    async def close() -> None
```

### Search Budget Pattern
- Each `SearXNGClient` instance has `_max_searches` limit
- `_search_count` increments per call
- Raises `RateLimitedError` when budget exhausted
- This is separate from the per-client IP rate limiter in `api.py`

### What Needs to Change
- Phase 5 (MCP): May want to expose search as a tool with rate limiting configuration
- No other significant changes needed

---

## 9. `agent-svc/agent/webhook.py` — Webhook Delivery

### Key Function

```python
async def deliver_webhook(webhook_config, event, job_id, data, task_tracker, success, error) -> None
```

### Features
- **Events filter:** Respects `webhook.events` list — only fires for matching events
- **Metadata echo:** `webhook.metadata` is echoed in every payload (VAL-PARITY-009)
- **Deduplication:** Each delivery gets unique UUID v4 `webhookId` (VAL-PARITY-011)
- **HMAC signing:** Optional `X-Webhook-Signature: sha256=...` header via `WEBHOOK_SECRET`
- **Retry with backoff:** 3 attempts with 2s, 4s delays
- **Payload format:** `{type, id, webhookId, success, error, data, metadata}`
- **TaskTracker integration:** When `task_tracker` is provided, webhook delivery is spawned as tracked background task

### Lifecycle Webhooks (for Crawl)
- `crawl.started` — before any page scraping
- `crawl.page` — after each page (data=[page])
- `crawl.completed` — on completion (data=[])
- `crawl.failed` — on exception (data=[], error string)

### What Needs to Change
- All new async endpoints MUST use `deliver_webhook()` for completion/failure events
- Pattern: `deliver_webhook(webhook_config, "completed", job_id, result)` in worker
- Session protocol (Phase 2) may need session-specific events

---

## 10. `docker-compose.yml` — Services

### All Services

| Service | Image | Port | Role |
|---------|-------|------|------|
| `valkey` | valkey/valkey:8-alpine | internal | Key-value store (job metadata, cache) |
| `slopsearx` | ghcr.io/magnus919/slopsearx | 8081:8080 | Search engine (SearXNG fork) |
| `search-svc` | local build | 8010:8010 | Fixture search (profile: fixture) |
| `llm-svc` | local build | 8011:8011 | Fixture LLM (profile: fixture) |
| `test-site` | local build | 8005:8000 | Fixture website (profile: fixture) |
| `tier3-fixture` | local build | 8006:8000 | Tier 3 fixture (profile: fixture) |
| `scraper-svc` | local build / ghcr | 8001:8001 | URL→markdown scraper |
| `browser-svc` | local build / ghcr | internal | Browser session management |
| `flare-solverr` | ghcr.io/flaresolverr | 8191 | CAPTCHA solver (profile: flare-solverr) |
| `semantic-svc` | local build / ghcr | 8003:8003 | Vector embeddings + Qdrant |
| `qdrant` | qdrant/qdrant:v1.18.2 | internal | Vector database |
| `agent-svc` | local build / ghcr | 8080:8080 | **Main API** — depends on valkey, slopsearx, scraper-svc, semantic-svc |
| `ofelia` | mcuadros/ofelia | internal | Cron job scheduler |
| `portal-svc` | local build / ghcr | 8082:8081 | Web portal UI |
| `parse-svc` | local build | internal | File parsing (PDF, etc.) |

### Valkey Configuration
- Image: `valkey/valkey:8-alpine`
- Volume: `valkey_data:/data`
- Health check: `valkey-cli ping` every 5s
- No exposed ports — internal only
- URL: `redis://valkey:6379/0` (default)

### Volumes
```
valkey_data:    Valkey persistence
qdrant_data:    Qdrant vector store persistence
hf-cache:       HuggingFace model cache (external: true)
```

---

## 11. `.env.sample` — Environment Variables

### LLM Configuration
| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_API_KEY` | (fixture) | LLM provider API key |
| `LLM_BASE_URL` | http://llm-svc:8011/v1 | OpenAI-compatible endpoint |
| `LLM_MODEL` | fixture-model | Model name |
| `LLM_ENABLE_THINKING` | false | Enable thinking/reasoning for DeepSeek/Anthropic |

### API Authentication
| Variable | Description |
|----------|-------------|
| `API_KEY` | Optional Bearer token / X-API-Key auth |

### Internal Service URLs
| Variable | Default |
|----------|---------|
| `VALKEY_URL` | redis://valkey:6379/0 |
| `SEARXNG_URL` | http://slopsearx:8080 |
| `SCRAPER_URL` | http://scraper-svc:8001 |
| `SEMANTIC_URL` | http://semantic-svc:8003 |
| `QDRANT_URL` | http://qdrant:6333 |

### Scrape/Crawl Controls
| Variable | Default |
|----------|---------|
| `SCRAPER_PROXY_URL` | (none) |
| `AGENT_MAX_SEARCHES_PER_REQUEST` | 5 |
| `AGENT_SEARCH_RATE_LIMIT` | 10/60s |
| `CRAWL_MAX_DURATION_SECONDS` | 1800 |
| `CRAWL_IDLE_TIMEOUT_SECONDS` | 300 |

### Vector Index
| Variable | Default |
|----------|---------|
| `VECTOR_INDEX_MAX_DOCS` | 250000 |
| `EMBED_MODEL_NAME` | BAAI/bge-m3 |
| `EMBED_DIM` | 1024 |
| `ACTIVE_EMBED_MODEL` | v_bge-m3 |
| `NEAR_DUP_THRESHOLD` | 0.95 |
| `NEAR_DUP_MODE` | skip |

### Intelligent Scrape Cache (ADR-0019)
| Variable | Default |
|----------|---------|
| `SCRAPE_CACHE_TTL` | 3600 |
| `SCRAPE_CACHE_MIN_TTL` | 60 |
| `SCRAPE_CACHE_MAX_TTL` | 86400 |
| `SCRAPE_CACHE_STABLE_MULTIPLIER` | 2.0 |
| `SCRAPE_CACHE_VOLATILE_CAP` | 300 |
| `SCRAPE_CACHE_DOMAIN_TTLS` | (JSON dict) |

### Adapter API Keys
- `ADAPTER_YOUTUBE_API_KEY`, `GITHUB_TOKEN`, `ADAPTER_NVD_API_KEY`
- Security adapters: `ADAPTER_ABUSEIPDB_API_KEY`, `ADAPTER_OTX_API_KEY`, `ADAPTER_SHODAN_API_KEY`, `ADAPTER_HIBP_API_KEY`, `ADAPTER_CENSYS_API_ID/_SECRET`, `ADAPTER_VIRUSTOTAL_API_KEY`, `ADAPTER_VULNCHECK_API_KEY`

### Politeness
- `SCRAPER_POLITENESS_ENABLED`, `SCRAPER_POLITENESS_CRAWL_DELAY`, `SCRAPER_POLITENESS_ROBOTS_TTL`

### What Needs to Change
- **Phase 2:** May need `SESSION_TTL` for session storage TTL
- **Phase 4:** May need `RESEARCH_MEMORY_TTL`, `RESEARCH_MEMORY_SIMILARITY_THRESHOLD`
- **Phase 5:** May need `MCP_SERVER_PORT`

---

## 12. `tests/test_stack.py` — Integration Tests

### Test Structure (~3500 lines, ~90 test functions)

Tests are organized by feature area with clear prefixes:
- `test_services_health` — health endpoint verification
- `test_scraper_*` — scraper functionality (llms.txt, markdown, playwright, meta)
- `test_agent_*` — agent endpoints, streaming
- `test_crawl_*` — crawl endpoints, streaming, SSE, reconnection
- `test_search_*` — search modes (fast, rich, deep, output schema)
- `test_answer_*` — answer endpoint, citations, streaming
- `test_github_adapter_*` — GitHub adapter tests
- `test_nvd_adapter_*` / `test_cveorg_adapter_*` — CVE adapter tests
- `test_security_adapters_*` — 10 security adapter tests
- `test_gutenberg_adapter_*` — Gutenberg adapter tests
- `test_*_monitor_*` — search/scrape monitor tests
- `test_*_batch_*` — batch scrape tests
- `test_activity_*` — activity feed tests
- `test_near_dup_*` — near-duplicate detection tests
- `test_*_error_*` — error response tests (404, 422)
- `test_browser_*` — browser session tests
- `test_parse_*` — file parse tests

### Test Patterns
- Uses `pytest` with `httpx` for HTTP requests
- `require_docker` marker: skips test if Docker stack not running
- `wait_for()` helper: polls a URL until it responds 200
- `AGENT`, `SCRAPER`, `SEARCH`, `LLM`, `TEST_SITE`, `TIER3_SITE`, `SEMANTIC` — env-configurable URLs
- Many external-service tests marked `@pytest.mark.xfail(strict=False, reason="...")` for CI resilience
- Test a full endpoint lifecycle: POST create → GET status → DELETE cancel
- Streaming tests parse SSE events from response body

### What Needs to Change
- New tests needed for each phase:
  - Phase 1: `test_agent_structured_output`, `test_answer_compact_citations`
  - Phase 2: `test_session_create`, `test_session_message`, `test_session_context`
  - Phase 3: `test_agent_plan_consent`, `test_agent_plan_modification`, `test_agent_depth_injection`
  - Phase 4: `test_research_memory_cache_hit`, `test_research_memory_expiry`
  - Phase 5: `test_mcp_tools_list`, `test_mcp_tool_call`

---

## Cross-Cutting Observations

### Existing Infrastructure to Leverage

1. **Valkey/Redis** — Already available as `valkey:8-alpine`. JobStore is a clean CRUD pattern. Can extend with additional key patterns for sessions, memory, rate limiting.

2. **LLM Client** — OpenAI-compatible, already supports streaming and structured output (json_object mode). Can be extended with strict json_schema mode.

3. **Scraper Client** — Stable abstraction over scraper-svc. Supports fallback strategies, batch scraping.

4. **Search Client** — SearXNG (via slopsearx). Budget-aware, multi-source.

5. **Semantic Service** — Qdrant vector database. Already used for vector search, reranking, find-similar, near-duplicate detection. Perfect for Phase 4 research memory.

6. **Webhook System** — Fully-featured: events filter, HMAC signing, retry with backoff, UUID dedup, TaskTracker integration. All new async endpoints MUST use it.

7. **TaskTracker** — Graceful shutdown for background tasks. Used pervasively.

8. **Rate Limiting** — Per-client IP sliding window via Valkey. Extensible pattern.

9. **Streaming Pattern** — Well-established dual-path pattern (SSE inline vs job+background). Consistent across agent, crawl, answer, search.

10. **Exception Hierarchy** — `GroktoCrawlError` base with `NotFoundError`, `InvalidRequestError`, `ScrapeError`, `BrowserError`, `UpstreamError`, `SearchError`, `RateLimitedError`. Consistent error shape.

11. **Error Response Format** — `{"success": false, "error": "...", "error_code": "...", "details": [...]}` — used consistently.

12. **Settings/Config** — `load_settings()` from `common` module. Environment variables with `.env` file support.

13. **Metrics** — Prometheus/OpenMetrics via `agent-svc/agent/metrics.py` with counters, histograms.

### Architecture Decisions to Keep in Mind

1. **No external worker queue** — Jobs run as `asyncio.create_task()` in the API process. For Phase 5 MCP server, this means MCP tool calls are synchronous within the API process.

2. **Valkey keys have 24h TTL** — All job data auto-expires. Session/memory data may need different TTLs.

3. **Per-request model override** — `model: "default"` in requests maps to `LLM_MODEL` env var. Non-"default" values override per-request.

4. **Schema injection pattern** — JSON Schema is injected into system prompt with `response_format: {"type": "json_object"}`. Not using strict `json_schema` mode.

5. **Multi-pass research is capped at 2 passes** — Gap detection triggers pass 2 only once.

6. **Crawl concurrency is bounded** — `asyncio.Semaphore` with configurable limit, forced sequential when `delay` is set.
