# API reference

GroktoCrawl implements the Firecrawl v2 API surface. All endpoints are served by agent-svc on port 8080. Interactive docs are available at `/docs` (Swagger UI) and `/openapi.json` (raw spec) when the stack is running.

## Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | Health check with per-dependency probes |
| GET | `/metrics` | OpenMetrics format for Prometheus |
| GET | `/v2/activity` | List all active/processing jobs |
| POST | `/v2/scrape` | Scrape a single URL to clean markdown |
| POST | `/v2/agent` | Start an autonomous research agent (supports SSE streaming) |
| GET | `/v2/agent/{jobId}` | Get agent job status and results |
| DELETE | `/v2/agent/{jobId}` | Cancel an agent job |
| POST | `/v2/answer` | Grounded Q&A with citations (supports SSE) |
| POST | `/v2/extract` | Extract structured data from URLs |
| GET | `/v2/extract/{jobId}` | Get extract status and results |
| POST | `/v2/crawl` | Crawl a website |
| GET | `/v2/crawl/{jobId}` | Get crawl status |
| DELETE | `/v2/crawl/{jobId}` | Cancel a crawl |
| POST | `/v2/batch/scrape` | Scrape multiple URLs |
| POST | `/v2/search` | Search the web with five retrieval modes |
| POST | `/v1/search` | Firecrawl v1-compatible search (flat results) |
| POST | `/v2/map` | Discover URLs on a site |
| POST | `/v2/parse` | Upload a file (PDF, DOCX, PPTX, XLSX) and get markdown |
| POST | `/v2/browser` | Create a headless browser session |
| GET | `/v2/browser` | List active browser sessions |
| POST | `/v2/browser/{id}/execute` | Execute browser action |
| DELETE | `/v2/browser/{id}` | Destroy a browser session |
| POST | `/v2/monitor` | Create a scheduled change monitor |
| GET | `/v2/monitor` | List all monitors |
| GET | `/v2/monitor/{id}` | Get monitor status and history |
| PATCH | `/v2/monitor/{id}` | Update monitor config |
| DELETE | `/v2/monitor/{id}` | Delete a monitor |
| POST | `/v2/generate-llmstxt` | Generate an llms.txt for a website |
| GET | `/v2/generate-llmstxt/{jobId}` | Get generation status |

## Authentication

When `API_KEY` is set in `.env`, all endpoints except `/health` and `/metrics` require:

```
Authorization: Bearer sk-your-key
```

## Common response structure

Sync endpoints return the result directly. Async endpoints return a job ID for polling:

```json
{"success": true, "id": "uuid-job-id"}
```

Poll the status endpoint to retrieve the result:

```json
{"success": true, "status": "completed", "data": {...}}
```

## Search parameters

`POST /v2/search` accepts:

| Parameter | Type | Default | Description |
|---|---|---|---|
| query | string | -- | Search query (required) |
| limit | int | 5 | Max results |
| search_type | string | "fast" | "fast" or "rich" |
| retrieval_mode | string | "keyword" | keyword, semantic, hybrid, vector, hybrid_vector |
| sources | string[] | null | web, news, images, video, social |
| categories | string[] | null | research, github, pdf, news, science, it, general |
| output_schema | object | null | JSON Schema for structured extraction |
| system_prompt | string | null | Guidance for synthesis |
