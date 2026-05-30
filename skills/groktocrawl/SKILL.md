     1|---
     2|name: groktocrawl
     3|description: >-
     4|  Scrape web pages, search the web, crawl sites, map URLs, extract structured
     5|  data, run autonomous research agents, control headless browser sessions, parse
     6|  document files, generate llms.txt files, and schedule change monitors via the
     7|  GroktoCrawl API. Use when the task involves web scraping, web research,
     8|  browser automation, document parsing, or content change detection.
     9|license: MIT
    10|metadata:
    11|  author: groktopus
    12|  version: "1.1.0"
    13|  changelog:
    14|    "1.1.0": "Add download command, clarify PATH-vs-script CLI path, document search bug fix"
    15|    "1.0.0": "Initial release after SkillOpt Epoch 1 — search pitfalls, multi-step workflows"
    16|---
    17|# groktocrawl
    18|
    19|Access the GroktoCrawl API — a self-hosted, Firecrawl-compatible web scraping and AI research service. The CLI auto-discovers the server URL from `GROKTOCRAWL_API_URL`, then `FIRECRAWL_API_URL`, then `~/.hermes/.env`, defaulting to `http://localhost:8080`.
    20|
    21|The canonical CLI is on PATH (`groktocrawl`). The skill's `scripts/groktocrawl` is a reference copy that may lag behind the upstream release; when in doubt, check `which groktocrawl` and update from `groktopus/groktocrawl` on GitHub.
    22|
    23|## Quick start
    24|
    25|```bash
    26|groktocrawl scrape https://example.com
    27|groktocrawl search "raspberry pi 5" --limit 3 --json
    28|groktocrawl agent "What were the key Google I/O 2025 announcements?"
    29|```
    30|
    31|## Commands
    32|
    33|| Command | Purpose | Example |
    34||---------|---------|---------|
    35|| scrape | Page to markdown | `groktocrawl scrape <url>` |
    36|| search | Web search | `groktocrawl search <query> --limit 3 --json` |
    37|| download | Binary files | `groktocrawl download <url>` |
    38|| extract | Structured data | `groktocrawl extract <url> --prompt "..."` |
    39|| map | URL discovery | `groktocrawl map <url> --limit 50` |
    40|| crawl | Site crawling | `groktocrawl crawl <url> --max-depth 3` |
    41|| agent | Autonomous research | `groktocrawl agent "<prompt>"` |
    42|| browser | Headless browser | `groktocrawl browser create --ttl 300` |
    43|| active | List crawl jobs | `groktocrawl active --json` |
    44|
    45|## When to use which
    46|
    47|- **2+ sources needing synthesis** → agent
    48|- **Single URL** → scrape
    49|- **Binary files (PDF, EPUB, image)** → download
    50|- **Search results** → search
    51|- **Interactive page, JS-heavy SPA, YouTube** → browser (also needed when scrape returns short/empty content)
    52|- **API endpoints, raw JSON** → curl
    53|
    54|## Pitfalls
    55|
    56|### Search returns no results — two distinct causes
    57|
    58|1. **CLI parsing bug (fixed in v1.1.0):** Old CLI versions had `result.get("data", [])` which grabbed the `{"web":[...]}` dict and silently dropped it. Fix: update from `groktopus/groktocrawl`. Verify with `--json` — if the API returns results but the CLI shows empty, update the CLI.
    59|
    60|2. **Search backend not configured.** Verify with `curl -s -X POST $GROKTOCRAWL_API_URL/v2/search -d '{"query":"test","limit":3}'`. If curl returns empty, the server needs a search engine configured.
    61|
    62|Fallback when search is persistently empty: use `agent` command (different pipeline), pre-find URLs, or use specific known domains with `site:` filters.
    63|
    64|### Scrape returns short or empty content — try browser mode
    65|
    66|`scrape` works best on text-heavy, server-rendered sites (Wikipedia, documentation, blogs with static HTML). JS-heavy sites — single-page apps (SPAs), YouTube, modern news sites that fetch content via JavaScript — may return minimal or empty content because they require a headless browser to render.
    67|
    68|If a URL seems valid but `scrape` returns under 500 chars, try:
    69|
    70|```bash
    71|groktocrawl browser create --ttl 60       # Get a browser session (returns session ID)
    72|groktocrawl browser exec <session> navigate --url <url>   # Load page with JS rendering
    73|groktocrawl browser exec <session> executeScript --script "document.body.innerText"  # Get rendered text
    74|```
    75|
    76|Note: `getContent` returns metadata only (url, title, html_length) — not page content. Use `executeScript` to extract rendered text.
    77|
    78|### CLI vs reference copy
    79|
    80|The active CLI is on PATH. The skill's `scripts/groktocrawl` is a reference copy that may lag upstream. To sync: `curl -L https://github.com/groktopus/groktocrawl/raw/main/groktocrawl -o ~/.local/bin/groktocrawl`.
    81|
    82|## Related files
    83|
    84|- [references/triggers.md](references/triggers.md) — Decision table
    85|- [assets/examples.md](assets/examples.md) — Extended usage examples
    86|