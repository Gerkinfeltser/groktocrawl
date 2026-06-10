---
name: groktocrawl
description: >-
  Scrape web pages, search the web, crawl sites, map URLs, extract structured
  data, run autonomous research agents, control headless browser sessions, parse
  document files, generate llms.txt files, and schedule change monitors via the
  GroktoCrawl API. Use when the task involves web scraping, web research,
  browser automation, document parsing, or content change detection.
license: MIT
metadata:
  author: groktopus
  version: "1.6.0"
  changelog:
    "1.6.0": "Agent endpoint SSE streaming; CLI --sync flag; streaming default for agent command"
    "1.5.1": "CLI answer default changed from sync to streaming; --stream flag replaced with --sync (opt-out)"
    "1.4.0": "Add CLI subcommands for monitor (create/list/get/update/delete), parse (file to markdown), and generate-llmstxt (with async polling)"
    "1.3.3": "Add change monitoring section with active job tracking and monitor lifecycle guidance"
    "1.3.2": "Add multi-source research fallback chain (search→scrape→browser→agent) and domain exploration strategy (llms.txt→map→crawl→search site:)"
    "1.3.1": "Add extracting structured data section with prompt guidance and error recovery across commands"
    "1.3.0": "Add full structured extraction workflow with session ID plumbing, browser session lifecycle reference, and multi-step research workflow example"
    "1.2.0": "Add browser session lifecycle guidance, structured extraction examples, search backend config reference, and cross-command chaining patterns"
    "1.1.0": "Add download command, clarify PATH-vs-script CLI path, document search bug fix"
    "1.0.0": "Initial release after SkillOpt Epoch 1 — search pitfalls, multi-step workflows"
---

# GroktoCrawl

Access the GroktoCrawl API — a self-hosted, Firecrawl-compatible web scraping and AI research service. The CLI auto-discovers the server URL from `GROKTOCRAWL_API_URL`, then `FIRECRAWL_API_URL`, then `~/.hermes/.env`, defaulting to `http://localhost:8080`.

The canonical CLI is on PATH (`groktocrawl`).

## Quick Start

```bash
groktocrawl scrape https://example.com
groktocrawl search "raspberry pi 5" --limit 3 --json
groktocrawl agent "What were the key Google I/O 2025 announcements?"  (streaming, default)
groktocrawl agent "Research multimodal models" --sync  (non-streaming, poll for results)
groktocrawl answer "What is the Fed rate?"
groktocrawl answer "How tall is the Burj Khalifa?" --sync  (non-streaming, wait for full answer)
```

## Commands

| Command | Purpose | Example |
|---------|---------|---------|
| scrape | Page to markdown | `groktocrawl scrape <url>` |
| search | Web search | `groktocrawl search <query> --limit 3 --json` |
| download | Binary files | `groktocrawl download <url>` |
| extract | Structured data | `groktocrawl extract <url> --prompt "..."` |
| map | URL discovery | `groktocrawl map <url> --limit 50` |
| crawl | Site crawling | `groktocrawl crawl <url> --max-depth 3` |
| agent | Autonomous research (streaming) | `groktocrawl agent "<prompt>"` |
| answer | Grounded Q&A (streaming) | `groktocrawl answer "<question>"` |
| browser | Headless browser | `groktocrawl browser create --ttl 300` |
| active | List crawl jobs | `groktocrawl active --json` |
| monitor | Manage monitors | `groktocrawl monitor create/list/get/update/delete` |
| parse | Doc file to markdown | `groktocrawl parse <filepath>` |
| generate-llmstxt | Generate llms.txt | `groktocrawl generate-llmstxt <url>` |

## When to Use Which

| Need | Command | Why |
|------|---------|-----|
| Multi-source deep research | `agent "<prompt>"` | Searches, scrapes, and synthesizes deeply |
| Single factual question | `answer "<question>"` | One call, cited answer, streaming by default |
| Single URL content | `scrape <url>` | One fetch, no synthesis |
| Binary files (PDF, EPUB, image) | `download <url>` | Binary content download |
| Search results | `search "<query>"` | Just the search hits |
| Interactive page, JS-heavy SPA | `browser create/exec/destroy` | Headless browser session |
| YouTube / Bluesky URLs | `scrape <url>` | Handled by adapter system, returns rich markdown |
| Batch scrape + synthesize | `scrape` then `agent` | Scrape multiple URLs then feed into agent |
| API endpoints, raw JSON | `curl` | No processing needed |
| Discover site URLs | `map <url>` | URL discovery only |
| Full site crawl | `crawl <url>` | Recursive site extraction |
| Structured data from URLs | `extract <url>...` | Schema-guided extraction |
| Document parsing (PDF, DOCX) | `parse <filepath>` | Convert to markdown |

## Adapter System

GroktoCrawl has a pluggable **adapter system** for site-specific content handlers. When `scrape <url>` is called, the adapter registry checks if a handler matches the URL before running the generic pipeline. If an adapter matches, it handles extraction with its own fallback chain. If it fails, the generic pipeline runs as normal.

Adapters are auto-discovered at startup — no configuration needed.

### YouTube Adapter

`groktocrawl scrape <youtube-url>` returns markdown with YAML frontmatter (video_id, title, channel) and full video transcript.

**Supported URL formats:** `youtube.com/watch`, `youtu.be/`, `/shorts/`, `/embed/`

**Fallback chain:** youtube_transcript_api (free, no key) → browser render

### Bluesky Adapter

`groktocrawl scrape <bsky.app-url>` returns markdown with YAML frontmatter (author, handle, engagement counts) and post text with richtext facets (links, mentions) converted to markdown + depth-1 thread replies.

**Supported URL formats:** `bsky.app/profile/{handle}/post/{rkey}`

**Fallback chain:** AT Protocol XRPC API (public, no auth) → browser render

## Multi-Source Research with Fallback Chain

```bash
# Level 1: Search for leads
groktocrawl search "p5.js 2.0 release WebGPU changes" --limit 5 --json

# Level 2a: Scrape primary sources
groktocrawl scrape https://p5js.org/download/

# Level 2b: If scrape returns under 500 chars → browser for JS-rendered content
SESSION=$(groktocrawl browser create --ttl 120 | grep -oE '[a-f0-9-]{36}' | head -1)
groktocrawl browser exec "$SESSION" navigate --url "https://p5js.org/download/"
groktocrawl browser exec "$SESSION" executeScript --script "document.body.innerText"

# Level 3: Cross-reference and synthesize all sources
groktocrawl agent "Compare the features from the p5.js release notes..."
```

## Browser Session Lifecycle

- **Default TTL:** 60 seconds if `--ttl` not set.
- **Session ID format:** UUID v4 with dashes — extract with `grep -oE '[a-f0-9-]{36}'`.
- **Idle behavior:** TTL is total lifetime, not idle timeout. Session expires N seconds after creation regardless of activity.

## Pitfalls

### Search returns no results
- **CLI bug (pre-v1.1.0):** Old CLI had `result.get("data", [])` bug that silently dropped results. Update from groktopus/groktocrawl.
- **Backend not configured:** Verify with direct curl against the API. Configure SearXNG or other search backend.

### Scrape returns short content
JS-heavy sites (SPAs, modern news) may return under 500 chars. Switch to browser pipeline. Exception: YouTube and Bluesky URLs are handled by the adapter system — scrape returns rich content without browser fallback.

### Running `which groktocrawl` before every call
Don't. The CLI is at `~/.local/bin/groktocrawl`, it's always on PATH. If it broke, the first actual call would error out and tell you. The `which` check is a cargo-cult habit that adds a wasted round-trip and 30s of latency for zero value. Just call `groktocrawl` directly.

### SearXNG Brave engines: `engine: brave` vs `engine: braveapi`

The built-in SearXNG `engine: brave` scrapes the public Brave search website. It does NOT use the Brave Search API and gets rate-limited immediately from containerized deployments.

Use `engine: braveapi` for a paid Brave Search API key — it hits `api.search.brave.com` with `X-Subscription-Token` auth.

### Environment variable substitution in bind-mounted settings.yml

Docker Compose does NOT expand `${VAR}` inside bind-mounted config files. Add a `docker-entrypoint.sh` that runs sed substitution at startup before handing off to SearXNG's real entrypoint. Use `cp → sed → cat` (not `sed -i`) to avoid temp file permission issues with non-root container users.

### Error recovery

| Error | Recovery |
|-------|----------|
| Network/HTTP errors | Check server, URL, API key |
| Content quality | scrape→browser, search→agent |
| Timeouts | Reduce `--max-depth` or add `--limit` |
