# Scrape caching

Active contributors: groktopus

## Purpose

The scrape cache reduces latency and external requests by caching scrape results in Valkey. It uses freshness-aware revalidation with HTTP ETag and Last-Modified support, content-change detection, and per-domain TTL configuration.

## How it works

### Cache key and storage

URLs are normalized (lowercased, query-sorted, trailing-slash-stripped) and SHA-256 hashed for cache keys: `scrape_cache:{sha256_hex}`. Cache entries store the markdown content, source tier metadata, HTTP headers, and content hash.

### Revalidation strategies

**Slow tiers (Playwright, FlareSolverr) with ETag/Last-Modified**: blocking conditional revalidation. Sends `If-None-Match` or `If-Modified-Since` headers. On 304, extends TTL and returns cached content. On 200, updates cache with fresh content.

**Fast tiers (llms.txt, content negotiation)**: returns cached content immediately. Background revalidation extends TTL when the content hash matches on re-fetch.

### Content-change detection

SHA-256 content hashing tracks volatility:

- Content unchanged between fetches: TTL multiplied by `SCRAPE_CACHE_STABLE_MULTIPLIER` (default 2.0)
- Content changes repeatedly (change_count >= 5): TTL capped at `SCRAPE_CACHE_VOLATILE_CAP` (default 300s)

### Per-domain TTL overrides

`SCRAPE_CACHE_DOMAIN_TTLS` accepts a JSON dict mapping domain suffixes to TTLs. Longest suffix match wins:

```
SCRAPE_CACHE_DOMAIN_TTLS={"news.ycombinator.com": 300, "docs.python.org": 86400}
```

### TTL bounds

| Variable | Default | Description |
|---|---|---|
| `SCRAPE_CACHE_TTL` | 3600 | Global default TTL (seconds) |
| `SCRAPE_CACHE_MIN_TTL` | 60 | Minimum TTL |
| `SCRAPE_CACHE_MAX_TTL` | 86400 | Maximum TTL |
| `SCRAPE_CACHE_VOLATILE_CAP` | 300 | TTL cap for volatile content |

## Key source files

| File | Purpose |
|---|---|
| `scraper-svc/scraper/fetch.py` | Cache logic: `_check_cache()`, `_set_cache()`, `_conditional_revalidate()` |
