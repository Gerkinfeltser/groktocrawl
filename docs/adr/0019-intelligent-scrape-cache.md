# ADR-0019: Intelligent Scrape Cache — Freshness-Aware Revalidation

**Status:** Accepted

**Deciders:** Magnus Hedemark, Jasper (AI Agent)

**Date:** 2026-06-06

## Context

GroktoCrawl's scrape cache (introduced in v0.6.0) is a simple TTL-based Valkey store. Each cached entry has a fixed TTL (default: 3600s), after which it is evicted and the next request fetches fresh content regardless of whether the source actually changed. This creates two opposing failure modes:

1. **Stale content served for too long.** A page that changes frequently (a news article, a blog homepage) may be hours stale before the TTL expires and a re-fetch occurs.

2. **Pointless re-fetches of stable content.** A page that never changes (an API reference, a static spec) is re-fetched on every cache expiry, consuming bandwidth and SearXNG resources even though the content is identical to what is already cached.

Both failure modes are amplified by the politeness protocol (ADR-0013 from [#106]): each re-fetch incurs a crawl-delay, so every unnecessary re-fetch delays subsequent requests to the same domain.

The existing cache key structure (`scrape_cache:{sha256_of_normalized_url}`) stores the full JSON-serialized scrape result with a flat TTL. No HTTP headers, content hashes, or domain statistics are tracked.

## Decision Drivers

1. **Reduce bandwidth and SearXNG load** — stop re-fetching content that hasn't changed since the last fetch.
2. **Reduce p50 latency** — serve cached content immediately when the server confirms freshness via conditional GET (304 Not Modified).
3. **No new infrastructure dependencies** — the existing Valkey instance already serves the cache. No new services.
4. **Backward-compatible cache key structure** — existing cached entries must not break. The cache format extension must be additive.
5. **Complement the politeness protocol** — fewer fetches means fewer crawl-delay pauses, improving throughput for rate-limited domains.
6. **Configurable per-domain policy** — news sites and API docs have different freshness requirements. The system must support domain-specific TTLs without sacrificing the simple global default.

## Considered Options

### Option A: Optimistic cache-first with background revalidation (chosen)

On cache hit, return cached content immediately while spawning a fire-and-forget background task to revalidate via conditional GET. If the server returns 304 (Not Modified), extend the cache TTL. If the server returns 200 (modified), silently update the cache for the next request.

**Pros:**
- Lowest latency for the caller — the cache hit path adds zero blocking I/O beyond the Valkey read.
- The background revalidation is invisible to the caller.

**Cons:**
- Background tasks in FastAPI (via `asyncio.create_task`) are fire-and-forget with no error recovery — a failed revalidation silently leaves stale content.
- Two concurrent requests for the same URL after cache expiry both trigger re-fetches (the background task doesn't serialize revalidation).
- Requires the Valkey cache client to be thread/loop-safe (it already uses async, so it is).

### Option B: Cache-aside with conditional revalidation (blocking)

On cache hit, the caller sends a conditional GET (If-None-Match / If-Modified-Since) before returning. If the server returns 304, extend TTL and return cached content. If 200, update cache and return fresh content.

**Pros:**
- Deterministic freshness — every cache hit is verified before the caller sees data.
- Simple execution model — no background tasks, no concurrency hazards.
- The conditional GET is cheap (no body transfer on 304).

**Cons:**
- Adds a network round-trip to every cache hit that has ETag/Last-Modified headers stored — increases p50 latency for cache hits.
- The latency penalty is smaller than a full re-fetch but larger than a pure cache hit.

### Option C: Tiered approach — cache-first for fast tiers, cache-aside for expensive tiers (chosen, refinement)

Use **cache-first with background revalidation** for content fetched via Tiers 1-2 (llms.txt, content-negotiation — fast, cheap). Use **cache-aside with blocking conditional revalidation** for content fetched via Tier 3+ (playwright, flaresolverr — slow, expensive).

**Pros:**
- Best of both options: fast path stays fast for cheaply-refetchable content; expensive tiers are protected by deterministic freshness.
- Background revalidation on Tier 1-2 content has minimal risk — if it fails, the cost of a full re-fetch on the next cache check is low.

**Cons:**
- More complex execution logic — the tier that produced the cache entry determines the revalidation strategy.
- Background task lifecycle management (cleanup, rate limiting) adds surface area.

## Decision

Adopt **Option C**: cache-first with background revalidation for Tier 1-2 content, cache-aside with blocking conditional revalidation for Tier 3+ content. The cache entry stores the source tier, so the revalidation strategy is resolved at lookup time.

### Cache Data Model Extension

Each cache entry stores a JSON object with the following new fields alongside existing ones:

| Field | Type | Description |
|---|---|---|
| `etag` | `str \| null` | HTTP ETag header from the original 200 response |
| `last_modified` | `str \| null` | HTTP Last-Modified header from the original 200 response |
| `content_hash` | `str` | SHA-256 of the markdown content (for change detection when no ETag/LM available) |
| `source_tier` | `str` | The tier that produced the entry: `llms.txt`, `content-negotiation`, `playwright`, `flare-solverr`, `browser-svc` |
| `fetch_count` | `int` | How many times this URL has been fetched (cumulative across cache lives) |
| `first_fetched_at` | `float \| null` | Unix timestamp of the first fetch |
| `last_checked_at` | `float \| null` | Unix timestamp of the last revalidation check |
| `change_count` | `int` | How many times the content has changed since first cached (0 indicates stable) |

### Revalidation Flow

```
Cache hit → source_tier in {llms.txt, content-negotiation}?
  │
  ├── Yes (fast tiers): return cached content immediately
  │   └── Background: conditional GET (If-None-Match / If-Modified-Since)
  │       ├── 304 Not Modified → extend TTL by domain TTL × 2
  │       └── 200 OK → update cache entry (new content + headers + TTL reset)
  │
  └── No (slow tiers): blocking conditional HEAD/GET
      ├── 304 Not Modified → extend TTL, return cached content
      ├── 200 OK → update cache, return fresh content
      └── Connection error → return cached content with warning
```

### Content-Change Detection (No ETag/LM)

When a cache entry has no ETag or Last-Modified headers (e.g., content from playwright or browser-svc), a content-hash comparison is used instead:

1. On first fetch, compute `content_hash = SHA-256(markdown_content)`.
2. On re-fetch (after cache expiry), if a conditional GET is not possible, perform a full re-fetch.
3. After re-fetch, compare new content hash against stored hash.
4. If hashes match: content unchanged → extend TTL by 2× base TTL (stable content bonus).
5. If hashes differ: content changed → increment `change_count`, set TTL to base domain TTL (or default).
6. Track `change_count` per domain in a Valkey sorted set (`scrape_cache:domain_stats:{domain}`) for freshness-aware eviction prioritization.

### Per-Domain TTL Resolution

The TTL for a cache entry is resolved as follows:

1. Check `SCRAPE_CACHE_DOMAIN_TTLS` env var (JSON dict mapping domain suffixes to TTL in seconds): `{"news.ycombinator.com": 300, "docs.python.org": 86400}`
2. Match against domain suffix (longest prefix wins): e.g., `docs.python.org` matches `docs.python.org` (86400s), not `python.org`.
3. If no domain match, use the global default (`SCRAPE_CACHE_TTL`, default 3600).
4. After content-change detection: if content is stable (hashes match), multiply TTL by `SCRAPE_CACHE_STABLE_MULTIPLIER` (default 2.0). If content is volatile (change_count > threshold), cap to `SCRAPE_CACHE_VOLATILE_CAP` (default 300s).

### Domain Volatility Tracking

A Valkey sorted set `scrape_cache:domain_stats:{domain}` tracks per-domain volatility:

- **Member:** `{hostname}` (e.g., `docs.python.org`)
- **Score:** Number of content-change events (incremented each time a re-fetch detects new content)
- **TTL:** 24 hours (volatility is a sliding window, not permanent)
- Used during Valkey memory pressure to preferentially evict volatile domains' entries (Valkey's own eviction handles this, but the TTL adjustment per volatility score influences which entries are naturally evicted first).

### Conditional GET Implementation

The conditional GET is performed by sending a `HEAD` request (for revalidation) with:

```
If-None-Match: "{etag}"
If-Modified-Since: "{last_modified}"
```

A `HEAD` request is preferred over `GET` for revalidation because:
- It transfers no body — minimal bandwidth.
- ETags and Last-Modified headers are typically the same for HEAD and GET responses on standards-compliant servers.
- On 304 Not Modified, no body is returned regardless.

If the server does not support `HEAD` or returns an unexpected status, fall back to `GET` with the same conditional headers.

## Consequences

### Positive

- **Bandwidth reduction:** Conditional GETs (304) and content-hash skips eliminate body transfer for unchanged content. For stable docs sites (which may be hit hundreds of times across different scrape jobs), this is a ~10-50× reduction in downstream bandwidth.
- **Latency improvement:** Cache hits on Tier 3+ content with 304 revalidation return in one lightweight HEAD round-trip instead of a full Playwright render (seconds → milliseconds).
- **Politeness synergy:** Fewer full re-fetches means fewer crawl-delay pauses. The politeness protocol's rate limits are now split between full fetches (rare) and conditional requests (cheap).
- **Per-domain policy:** News aggregation use cases can set short TTLs for dynamic pages without paying the latency penalty on static content.
- **No new dependencies:** All logic is in `fetch.py`. Valkey is already deployed.

### Negative

- **Background task complexity:** Fire-and-forget `asyncio.create_task()` for background revalidation has no built-in error recovery. A failed revalidation (network error, timeout) silently extends the TTL of potentially stale content. This is acceptable for Tier 1-2 content (cheap to re-fetch on next miss).
- **Content-hash comparison is not on-the-wire verification.** An ETag or Last-Modified header is a server-authoritative freshness signal. A content hash is a client-side heuristic — it cannot detect that the *server's* content has changed if the re-fetch itself failed.
- **No dynamic TTL adjustment for individual entries beyond the stability multiplier.** Real traffic patterns may show that some domains need more granular tuning than a single env var JSON blob can provide. This is deferred to a future ADR.

### Risks

- **HEAD request non-standard behavior.** Some CDNs and web servers return different headers for HEAD vs GET (e.g., Cloudflare returns ETag on GET but not HEAD). Mitigation: fall back to GET with conditional headers if HEAD returns no ETag.
- **Valkey memory growth.** Additional fields per cache entry (etag, last_modified, content_hash, etc.) increase per-entry storage by ~200-500 bytes. At current cache scale (under 1000 entries), this is negligible. If the cache grows to 100k+ entries, the 50MB overhead may warrant a dedicated Valkey instance for cache. Mitigation: monitor Valkey `used_memory` via the existing observability infrastructure (ADR-0018).

## Links

- [Issue #109 — Intelligent scrape cache](https://github.com/groktopus/groktocrawl/issues/109)
- [ADR-0013](0013-search-architecture-with-vertical-categories.md) — Politeness protocol foundation (cache-aware revalidation)
- [ADR-0018](0018-observability-infrastructure.md) — Valkey health monitoring for cache sizing
- [RFC 7232 — HTTP Conditional Requests](https://httpwg.org/specs/rfc7232.html)
- [Valkey Eviction Policies](https://valkey.io/topics/lru-cache/)
