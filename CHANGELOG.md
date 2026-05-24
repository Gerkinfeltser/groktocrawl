# Changelog

All notable changes to GroktoCrawl are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] — 2026-05-24

### Added

- **Unified activity endpoint** (`GET /v2/activity`) — lists all active/processing jobs across all job types (crawl, agent, extract, batch_scrape, llmstxt). The CLI `active` command was previously broken (hit a route that was never implemented).
  - `store.py`: `list_active_jobs()` method using Valkey SCAN + pipeline batch fetch
  - New Pydantic models: `ActivityItem`, `ActivityResponse`
  - CLI: `groktocrawl active` now shows job kind and URL columns; JSON output key is `active_jobs`

- **Lightweight meta tag extraction** (`POST /scrape/meta`) — new endpoint on the scraper service that does a single HTTP GET and extracts `<title>`, `<meta name="description">`, and `<meta property="og:description">` from raw HTML. No Playwright, no readability, no markdown conversion.
  - New module: `scraper-svc/scraper/meta.py`
  - New Pydantic model: `MetaResponse`

- **Sentence-boundary-aware description extraction** — the llms.txt generator now produces descriptions that end at complete sentence boundaries instead of hard-char truncation.
  - Boilerplate signal filtering (30+ signal words: cookie, nav, footer, etc.)
  - Lines under 30 chars filtered out
  - Short candidates joined to reach ~100 char minimum
  - Sentence-boundary regex scan (`. `, `! `, `? `) instead of `[:150]`
  - Ellipsis fallback when no boundary found

- **Meta tag integration** — llms.txt generation tries the meta endpoint first (cheap, one GET); falls through to full scrape + sentence-boundary extraction only when meta tags are absent or under 40 chars.

### Testing

- 8 unit tests for `_extract_description()` pure function (no Docker)
- 4 new integration tests: meta endpoint, fallback, sentence-boundary, meta preference
- 3 new fixture pages on the test-site (`/content/multi-sentence`, `/content/with-meta`, `/content/with-boilerplate`)

### Fixed

- CLI `active` command (no longer returns 404 — now hits `GET /v2/activity`)
- llms.txt descriptions no longer truncated mid-sentence
- llms.txt descriptions no longer include cookie/nav boilerplate

## [0.1.0] — 2026-05-21

Initial release. Self-hosted, Firecrawl-compatible web scraping and AI research API.

### Features

- `/v2/scrape` — Single URL to clean markdown via three-tier scraper (llms.txt → Accept: text/markdown → Playwright)
- `/v2/crawl` — Recursive site crawling with depth and page limits
- `/v2/batch/scrape` — Batch scrape multiple URLs
- `/v2/search` — Web search via SearXNG with automatic content scraping
- `/v2/map` — URL discovery on a site with optional search filter
- `/v2/agent` — Autonomous research agent (search → scrape → LLM synthesis)
- `/v2/extract` — Structured data extraction from URLs with JSON Schema support
- `/v2/browser` — Headless browser sessions (navigate, click, type, screenshot, scroll, executeScript)
- `/v2/monitor` — Scheduled change detection with cron-based checking and webhook delivery
- `/v2/parse` — Document file parsing (PDF, DOCX, PPTX, XLSX) to markdown
- `/v2/generate-llmstxt` — Generate llms.txt files for any website
- CLI with all endpoint support
- Valkey-backed job store with 24h TTL
- Webhook delivery for all async endpoints with HMAC signing and retry
- Docker Compose deployment
