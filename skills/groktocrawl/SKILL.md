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
  version: "1.0.0"
---
# groktocrawl

Access the GroktoCrawl API — a self-hosted, Firecrawl-compatible web scraping and AI research service. The CLI auto-discovers the server URL from `GROKTOCRAWL_API_URL`, then `FIRECRAWL_API_URL`, then `~/.hermes/.env`, defaulting to `http://localhost:8080`.

## Quick start

```bash
# Scrape a page
scripts/groktocrawl scrape https://example.com

# Search the web
scripts/groktocrawl search "raspberry pi 5" --limit 3 --json

# Run autonomous research (searches, scrapes, synthesizes)
scripts/groktocrawl agent "What were the key Google I/O 2025 announcements?"
```

All commands accept `--server <url>` to override the server endpoint, `--json` for machine-readable output, and `--dry-run` to preview without executing.

## Commands

### scrape — Single page to markdown
```
scripts/groktocrawl scrape <url> [--format markdown links json] [--timeout ms] [-o file]
```

### search — Web search with content
```
scripts/groktocrawl search <query> [--limit N] [--scrape-results] [--json]
```

### map — URL discovery
```
scripts/groktocrawl map <url> [--limit N] [--search term]
```

### crawl — Site crawling
```
scripts/groktocrawl crawl <url> [--limit N] [--max-depth N] [--no-poll]
```
Without `--no-poll`, polls until the crawl completes. With `--json`, returns structured page data.

### agent — Autonomous research
```
scripts/groktocrawl agent "<prompt>" [--urls <url>...] [--no-poll]
```
Searches the web, scrapes relevant pages, and synthesizes an answer using the configured LLM. Polls for completion unless `--no-poll` is passed.

### extract — Structured data from URLs
```
scripts/groktocrawl extract <url> [<url>...] [--prompt "extraction prompt"] [--no-poll]
```

### browser — Headless browser sessions
```
scripts/groktocrawl browser create --ttl 300
scripts/groktocrawl browser exec <id> navigate --url <url>
scripts/groktocrawl browser exec <id> click --selector "#btn"
scripts/groktocrawl browser exec <id> screenshot
scripts/groktocrawl browser list
scripts/groktocrawl browser destroy <id>
```
Actions: navigate, click, type, screenshot, scroll, wait, getContent, executeScript

### active — List active crawl jobs
```
scripts/groktocrawl active [--json]
```

## Output handling

- Default: human-readable text to stdout
- `--json`: structured JSON to stdout (pipe to `jq` or tools)
- Errors go to stderr
- Exit code 0 on success, 1 on error

## Server configuration

The CLI resolves the server URL in this order:
1. `--server <url>` flag
2. `GROKTOCRAWL_API_URL` environment variable
3. `FIRECRAWL_API_URL` environment variable (backward compat)
4. `~/.hermes/.env` file (checks both var names)
5. Default: `http://localhost:8080`

## Prerequisites

The CLI requires `requests` (Python package). Install with `pip install requests` if not already present. Python 3.8+.

## Related files

- [references/triggers.md](references/triggers.md) — Keywords and patterns that should activate this skill
- [assets/examples.md](assets/examples.md) — Extended usage examples for every subcommand
