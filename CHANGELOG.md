# Changelog

All notable changes to GroktoCrawl are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] — 2026-05-24

### Added

#### Five-Tier Scrape Pipeline

Complete overhaul of the scraper from a fixed three-tier system to an adaptive five-tier pipeline:

- **Tier 3.5: FlareSolverr** — optional profile-gated container for hard Cloudflare challenges (CAPTCHA, strict fingerprinting). Enable with `docker compose --profile flare-solverr up`.
- **Tier 4: LLM-Assisted Recovery** — when standard tiers return suspicious content (Cloudflare challenges, error pages), the scraper calls a configured LLM to analyze the page. The LLM can extract iframe URLs and retry the scrape on the real content URL, return extracted text embedded in the page, or identify bot challenge types.
- **Tier 5: LLM Cloudflare Classification** — when all bypass methods fail, the LLM explains the block type (CAPTCHA, JS challenge, rate limit) and suggests alternative access paths (Wayback Machine, Google Cache), turning a hard failure into actionable information.

#### Binary Content Support

- **Content-Type detection** (`scraper-svc`) — auto-detects PDF, EPUB, images, and archives at the HTTP tier. Returns a structured `download` payload (filename, size, content_type) alongside markdown instead of failing.
- **`groktocrawl download <url>`** — new CLI subcommand that fetches binary content directly via HTTP with a real Chrome User-Agent. Supports `--extract-text` for PDF/EPUB text extraction (requires optional `pymupdf`/`ebooklib` deps). Auto-derives filenames from URL or Content-Type.

#### Iframe Content Detection

- **`_has_embedded_content()`** — detects when a Playwright-rendered page contains an `<iframe>`, `<embed>`, or `<object>` pointing to document URLs (PDFs, EPUBs, known document-serving domains like Sci-Hub, Academia, ResearchGate). Pages with embedded content are escalated to LLM recovery for URL extraction instead of returning the portal page text.

#### Cloudflare Bypass

- **Stealth browser config** — browser-svc now launches Playwright with real Chrome User-Agent, `--disable-blink-features=AutomationControlled`, `navigator.webdriver` override, realistic viewport/locale/timezone, and `networkidle` wait strategy. Cloudflare challenge pages are detected and given an 8-second resolution window.
- **Cookie persistence** — `cf_clearance` cookies are cached in Valkey with a 25-minute TTL. Subsequent scrapes to the same domain skip the Cloudflare challenge.
- **FlareSolverr sidecar** — profile-gated container (`profiles: [flare-solverr]`) for sites with aggressive Cloudflare protection.

#### DDoS-Guard Detection

- **Browser-svc**: DDoS-Guard JS challenge detection alongside Cloudflare — title checks for "DDoS-Guard", URL checks for `/.well-known/ddos-guard/`.
- **Scraper-svc**: `fetch_via_playwright()` now uses `networkidle` wait and checks for bot challenges post-navigation, with an 8-second resolution window.

#### LLM Fixture

- **Prompt-aware fixture** — the `llm-svc` fixture now handles recovery prompt schemas: extracts `<iframe src>` URLs from page content when the prompt mentions `iframe_url` or `recovery`, returns Cloudflare/DDoS-Guard classification data when the prompt mentions `cloudflare` or `block_type`. Makes the full pipeline demonstrable with `docker compose --profile fixture up` (no external API key needed).

### Changed

- **Real Chrome User-Agent everywhere**: scraper-svc's `smart_scrape()` httpx client now uses a real Chrome 131 User-Agent instead of the custom `GroktoCrawl/0.1` string that triggered Cloudflare.
- **`LLM_BASE_URL` configured in docker-compose**: scraper-svc now has `LLM_BASE_URL=http://llm-svc:8011/v1` in its environment block, fixing the port mismatch with the llm-svc fixture.
- **Recovery prompt content**: removed 4000-char truncation — the LLM recovery module now sends the full page content instead of the first 4000 characters. URL fragments (`#view=FitH`) are stripped from extracted iframe URLs before retrying.

### Fixed

- **Recovery received markdown, not raw HTML** — the LLM recovery module was receiving the markdown-converted page text (no HTML tags) instead of the raw HTML. Iframe URLs in the HTML were invisible to the LLM. Fixed by passing `raw_html_start` when available.
- **Duplicate `app = FastAPI(...)`** line in browser-svc left from a previous merge conflict resolution.
- **LLM fixture returned wrong JSON schema** — the fixture was returning `{"result": "structured response"}` which didn't match the recovery module's expected `{"action": "iframe_url", "url": "..."}` schema.

### Infrastructure

- **Contribution templates**: added bug report and feature request issue templates (`.github/ISSUE_TEMPLATE/`), PR template (`.github/PULL_REQUEST_TEMPLATE.md`), and updated `CONTRIBUTING.md` with Conventional Commits, DCO sign-off requirements, and PR template reference.

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
