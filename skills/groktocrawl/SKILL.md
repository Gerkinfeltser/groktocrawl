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
| 20+ site-specific URLs (GitHub, YouTube, Bluesky, Substack, NVD, etc.) | `scrape <url>` | Handled by adapter system, returns rich structured markdown |
| Batch scrape + synthesize | `scrape` then `agent` | Scrape multiple URLs then feed into agent |
| API endpoints, raw JSON | `curl` | No processing needed |
| Discover site URLs | `map <url>` | URL discovery only |
| Full site crawl | `crawl <url>` | Recursive site extraction |
| Structured data from URLs | `extract <url>...` | Schema-guided extraction |
| Document parsing (PDF, DOCX) | `parse <filepath>` | Convert to markdown |

## Adapter System

GroktoCrawl has a pluggable **adapter system** for site-specific content handlers — 20 adapters across code, social/media, CVE, and threat intelligence categories. When `scrape <url>` is called, the adapter registry checks for a matching handler before the generic pipeline. Highest-priority match wins. If the matched adapter raises `AdapterError` (all extraction paths exhausted), the request falls through to the generic pipeline (llms.txt → content negotiation → browser render).

Adapters are auto-discovered at startup via `AdapterRegistry.load_all()` — no configuration needed. Each adapter is a single `.py` file in `scraper-svc/scraper/adapters/`, subclassing `SiteAdapter` with the `@adapter` decorator.

**Priority conventions:**

| Priority | Category | Examples |
|----------|----------|---------|
| 200 | File/structured-content | GitHub files, CRT.sh, NVD, MITRE ATT&CK, Exploit-DB, YouTube, Bluesky, Substack |
| 190 | Social/community | GitHub issues, PRs, discussions, releases |
| 180 | API-backed security | AbuseIPDB, Shodan, VirusTotal, OTX, HIBP, Censys, VulnCheck |
| 150 | Fallback API | CVE Program (lower priority than NVD for overlapping patterns) |
| 100 | Default | Base priority when none specified |

### Code Adapters

**1. GitHub File Adapter** (`github.py`, ~810 lines, priority 200)

Handles file content, READMEs, and directory listings from `github.com` and `raw.githubusercontent.com`. URLs: repo root (README), `/blob/` (file content), `/tree/` (directory), `raw.githubusercontent.com` (direct CDN fetch). Issues/PR URLs are excluded — routed to the social adapter.

**Fallback chain:** Raw CDN fetch (zero rate-limit cost) → GitHub REST API `/repos/{owner}/{repo}/contents/{path}` → generic tier pipeline

**Config:** Optional `GITHUB_TOKEN` env var (5,000 req/hr vs 60 req/hr unauthenticated).

**2. GitHub Social Adapter** (`github_social.py`, ~1047 lines, priority 190)

Handles issue threads, pull requests, discussions, releases, and individual commits from `github.com`.

**Fallback chain:** GitHub GraphQL API (v4, single-query rich data) → GitHub REST API (v3) → readability-lxml + markdownify → generic tier

### Social / Media Adapters

**3. YouTube Adapter** (`youtube.py`, ~469 lines, priority 200)

Returns markdown with YAML frontmatter (video_id, title, channel) and full video transcript. URL variants: `/watch`, `youtu.be/`, `/shorts/`, `/embed/`, `/v/`, `m.youtube.com`.

**Fallback chain:** `youtube_transcript_api` (no API key) → `yt-dlp` subtitle download → browser render

**Metadata:** oEmbed API for title/author/thumbnail, LD+JSON for description, browser DOM for view count/publish date.

**4. Bluesky Adapter** (`bluesky.py`, ~457 lines, priority 200)

Returns markdown with YAML frontmatter (author, handle, engagement counts) and post text with richtext facets + depth-1 thread replies. URLs: `bsky.app/profile/{handle}/post/{rkey}`.

**Fallback chain:** AT Protocol XRPC API (`public.api.bsky.app`, no auth) → browser render

**5. Substack Adapter** (`substack.py`, ~396 lines, priority 200)

Returns article content from `*.substack.com/p/` posts, `*/pub/` URLs, and vanity domains probed via RSS.

**Fallback chain:** RSS/Atom feed (`{origin}/feed`, `content:encoded` → markdown) → readability-lxml → browser render

**Notes:** Vanity domain probe cached per-origin with 1-hour TTL. Detects Substack via `<generator>Substack</generator>` in RSS XML.

### CVE / Vulnerability Adapters

**6. NVD API Adapter** (`nvd.py`, ~498 lines, priority 200)

Structured CVE data from the National Vulnerability Database. URLs: `nvd.nist.gov/vuln/detail/CVE-*`, `cve:CVE-*` protocol.

**Returns:** CVSS v3.1/v4 scores, CPE matches, CWE classification, KEV status, tagged references.

**Fallback chain:** NVD API (`/rest/json/cves/2.0`) → readability-lxml → generic tier

**Config:** Optional `ADAPTER_NVD_API_KEY` (raises rate limit from 5 to 50 req/30s).

**7. CVE Program API Adapter** (`cveorg.py`, ~358 lines, priority 150)

Authoritative CVE records from the MITRE CVE Program. URLs: `cve.org/CVERecord?id=CVE-*`, `cve.mitre.org/cgi-bin/cvename.cgi`, `cve:CVE-*`.

**Returns:** CVE Record state, assigner, affected products, credits.

**Fallback chain:** CVE Services API (public read, no key) → readability-lxml → generic tier

**Priority note:** Lower priority than NVD (200) so NVD is tried first for richer data. Falls through to CVE Program on NVD failure.

**8. Exploit-DB Adapter** (`exploitdb.py`, ~52 lines, priority 200)

Public exploit and PoC page extraction from `exploit-db.com`. No API key required.

**Fallback chain:** HTML scraping only (no official API) → generic tier

**9. MITRE ATT&CK Adapter** (`mitreattack.py`, ~178 lines, priority 200)

Technique, software, and group information from the ATT&CK framework. Fetches structured STIX data from the MITRE CTI GitHub repository. No API key required.

**Fallback chain:** STIX from GitHub raw → readability-lxml → generic tier

**10. CRT.sh Adapter** (`crtsh.py`, ~99 lines, priority 200)

Certificate Transparency log lookup. No API key required.

**Fallback chain:** CRT.sh API (free, no key) → readability-lxml → generic tier

### Threat Intelligence Adapters

The following adapters (priority 180) each require an API key, with HTML scrape fallback:

| Adapter | File | Lines | API Key Env Var | Data Source |
|---------|------|-------|-----------------|-------------|
| **AbuseIPDB** | `abuseipdb.py` | 128 | `ADAPTER_ABUSEIPDB_API_KEY` | IP reputation / abuse reports |
| **Shodan** | `shodan.py` | 136 | `ADAPTER_SHODAN_API_KEY` | Internet device banners, services, CVEs |
| **VirusTotal** | `virustotal.py` | 136 | `ADAPTER_VIRUSTOTAL_API_KEY` | File hash, URL, domain, IP reputation |
| **AlienVault OTX** | `otx.py` | 129 | `ADAPTER_OTX_API_KEY` | Threat intelligence indicators |
| **Have I Been Pwned** | `hibp.py` | 116 | `ADAPTER_HIBP_API_KEY` | Breach and paste lookup |
| **Censys** | `censys.py` | 129 | `ADAPTER_CENSYS_API_ID` + `ADAPTER_CENSYS_API_SECRET` | Internet host / certificate lookup |
| **VulnCheck** | `vulncheck.py` | 140 | `ADAPTER_VULNCHECK_API_KEY` | Vulnerability advisory lookup |

All threat intelligence adapters share a two-tier fallback chain: **API → readability-lxml** (via `_helpers.py`) → generic tier. The shared `_helpers.py` module provides `scrape_page()` using readability-lxml for the HTML scrape tier.

### Integration with the Generic Pipeline

If an adapter cannot handle a URL (returns `AdapterError` for all tiers), the request falls through to the generic pipeline as if no adapter matched:

1. **Tier 1:** Check `/llms.txt` at the site root
2. **Tier 2:** Request with `Accept: text/markdown` header (per-page markdown)
3. **Tier 3:** Playwright render + readability extraction

Adapters are a **performance and quality optimization** — not a gate. The generic pipeline remains the universal fallback.

### Patterns for New Adapters

Based on the 20 existing adapters, a new adapter should:

1. **One file, one site** — single `.py` file in `scraper-svc/scraper/adapters/`
2. **Three-tier fallback chain** — cheapest structured source first, page scrape second, browser or generic last
3. **Auto-registration** — subclass `SiteAdapter`, add `@adapter` decorator
4. **URL patterns** — list of compiled regexes on the class
5. **Priority allocation** — 200 for file/structured, 190 for social, 180 for API-backed, 150 for fallback APIs, 100 default
6. **Env var config** — use `ADAPTER_<SITE>_*` convention, document in `.env.sample`
7. **Metadata frontmatter** — return structured metadata merged into YAML frontmatter via `AdapterResult`
8. **Shared helpers** — use `_helpers.scrape_page()` for the readability-lxml fallback tier to avoid code duplication

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
JS-heavy sites (SPAs, modern news) may return under 500 chars. Switch to browser pipeline. Exception: URLs matching registered adapters (GitHub, YouTube, Bluesky, Substack, NVD, and 16 more) are handled by the adapter system — scrape returns rich structured content without browser fallback.

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
