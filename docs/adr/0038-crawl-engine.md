# ADR-0038: Crawl Engine — BFS Orchestrator with Shared Link Extraction

**Status:** accepted

**Deciders:** @magnus919

**Date:** 2026-06-19

## Context

GroktoCrawl's original `/v2/crawl` endpoint scraped only the start URL and returned it as a single-page result — it was a stub with no recursive link following. The mission called for a full recursive crawl engine matching Firecrawl's `/v2/crawl` feature set.

Three distinct code paths independently extracted links from HTML pages:

- The **stub crawl worker** (`_process_crawl_async` in `worker.py`) — no link extraction at all initially
- The **`/v2/map` endpoint** — inline BeautifulSoup parsing directly in the route handler
- The **`llmstxt.py` `discover_pages()` function** — its own link extraction logic

Each used different HTML parsing approaches, had different edge-case handling (malformed HTML, `<base>` tag resolution, fragment stripping), and maintained its own URL dedup logic. This divergence meant bug fixes and improvements to link extraction had to be applied in three places.

The crawl engine itself needed decisions across several dimensions:

1. **Traversal strategy** — breadth-first (BFS) vs depth-first (DFS) for ordering page discovery
2. **Link extraction ownership** — one shared module vs per-consumer extraction
3. **Deduplication approach** — within-run seen sets, canonical URL resolution, content hash comparison
4. **Concurrency model** — sequential vs parallel page scraping, coordination across workers
5. **Path filtering** — how include/exclude patterns work with glob vs regex semantics
6. **Sitemap integration** — how sitemap-discovered URLs interact with BFS discovery

## Decision Drivers

1. **Firecrawl API compatibility** — the output shape (BFS-order data, status response fields, path filter patterns) must match what Firecrawl users expect
2. **No separate worker container** — crawl jobs are processed inline via `asyncio.create_task()` in the API process, matching the existing job architecture (ADR-0000 precedent)
3. **Deterministic ordering** — users polling `GET /v2/crawl/{id}` expect pages to appear in a predictable order with the start URL first
4. **Consistency across features** — `/v2/map`, `/v2/crawl`, and `/v2/generate-llmstxt` should discover the same links from the same HTML
5. **Low latency for small crawls** — sub-second overhead for `max_pages=1` crawls (the common case)
6. **Self-hosted simplicity** — avoid external dependencies where possible; Valkey is already in the stack

## Considered Options

### Traversal Strategy — BFS vs DFS

**Option A: BFS (breadth-first search).** Use a FIFO deque. Start URL at depth 0 is scraped first, then all depth-1 pages, then depth-2, and so on.

**Option B: DFS (depth-first search).** Use a stack (LIFO). The crawl follows one branch to its deepest page before backtracking.

| Criterion | BFS | DFS |
|-----------|-----|-----|
| Start URL appears first | Yes | No |
| Predictable page ordering | Yes | Depends on discovery order |
| Memory usage for deep sites | Higher (queue holds all siblings) | Lower (stack holds one branch) |
| User expectation (Firecrawl compat) | Matches | Does not match |
| Early results visible in polling | Better (depth-1 pages appear quickly) | Worse (deep pages appear first) |

**Chosen: BFS** — Firecrawl returns pages in BFS order, and users polling for progress expect to see shallow pages first. The start URL is always at index 0, making validation trivial. Memory overhead is acceptable for our concurrency model (max_pages caps the queue).

### Link Extraction — Shared vs Per-Consumer

**Option A: Shared `LinkExtractor` module.** A single stateless module with `extract_links()` and `filter_links()` used by all three consumers.

**Option B: Per-consumer extraction.** Each consumer (crawl, map, llmstxt) maintains its own link extraction logic.

| Criterion | Shared | Per-Consumer |
|-----------|--------|--------------|
| Bug-fix surface | One place | Three places |
| Edge-case consistency | Guaranteed | Divergent over time |
| Test surface | One test suite | Three test suites |
| Consumer coupling | Tighter | Looser |
| Adding a new consumer | Import the module | Rewrite extraction |

**Chosen: Shared `LinkExtractor`** — The extraction logic is complex enough (relative URL resolution, `<base>` tag handling, fragment stripping, non-HTTP scheme filtering, dedup, malformed HTML tolerance) that maintaining three copies would create a constant tax of inconsistent behavior. The shared module is stateless (pure functions), making it testable in isolation and safe to call from concurrent contexts.

### Deduplication Strategy

**Option A: URL-level only.** Track a `set[str]` of normalized URLs within a crawl run. Normalization handles fragments, trailing slashes, default ports, and query parameter sorting. Optional `ignoreQueryParameters` mode strips query strings entirely.

**Option B: URL + canonical tag.** After scraping, extract `<link rel="canonical">` from HTML. If the canonical URL differs from the fetched URL, replace the page reference and check against the seen set.

**Option C: URL + canonical + content hash.** Compute a SHA-256 hash of the extracted markdown text. If two pages produce the same content hash, skip the duplicate.

**Chosen: Option A (URL-level) for core, with canonical and content hash as layered extensions planned for Milestone 4.** URL-level dedup is sufficient for the core crawl loop and avoids the complexity of parsing scraped HTML a second time (content hash) or making additional scraper calls (canonical). The seen-set is an in-memory Python set, O(1) lookup, no Valkey round-trips. Content hash dedup requires storing hashes per crawl run and adds latency for the hashing operation.

### Concurrency Model

**Option A: Sequential.** Process one page at a time in the BFS loop. Simple, no coordination needed.

**Option B: `asyncio.Semaphore` worker pool.** A fixed-size pool of concurrent scrape tasks coordinated by `asyncio.Semaphore(N)`. Workers pop from the shared BFS queue.

**Option C: Valkey-backed distributed semaphore.** Similar to Option B but using a Valkey (Redis) distributed semaphore for multi-instance coordination.

**Chosen: Option A (sequential) for initial implementation, with Option B planned for Milestone 3.** The initial crawl engine processes pages synchronously within the BFS loop, matching the existing `_process_batch_scrape_async` pattern. Sequential processing is sufficient for the common case (small crawls, low concurrency requirements). The architecture supports adding `asyncio.Semaphore` later without changing the BFS queue or dedup structures. Valkey coordination (Option C) is deferred until multi-instance deployments are demonstrated.

### Path Filtering — Glob vs Regex

**Option A: Glob only.** Use Unix glob-style patterns (`*`, `**`, `?`). Familiar to most users, fewer escaping edge cases.

**Option B: Regex only.** Use Python regular expressions. More expressive but requires users to understand regex syntax.

**Option C: Both, controlled by `regexOnFullUrl` flag.** Default to glob (backward-compatible with Firecrawl defaults), switch to regex when the flag is set.

**Chosen: Option C (both).** Firecrawl supports both glob and regex patterns for `includePaths` and `excludePaths`. The `regexOnFullUrl` flag controls which mode is used. In glob mode, special regex characters (`.`, `+`, `?`, etc.) are escaped to prevent accidental false matches. In regex mode, patterns are passed directly to `re.search()` and can match against the full URL (including query parameters) when enabled.

### Sitemap Integration

**Option A: Ignore sitemaps entirely.** Only discover pages via BFS link following from the start URL.

**Option B: Sitemap as seed only.** Fetch sitemap URLs, deduplicate them against the BFS seen-set, and insert them at the front of the queue. Pages from sitemaps are subject to the same path filtering and max_pages limits as BFS-discovered pages.

**Option C: Three sitemap modes (include/skip/only).** An explicit `sitemap` field with three values:
- `include` (default): sitemap URLs seeded into BFS queue, combined with HTML link discovery
- `skip`: no sitemap fetch, HTML-only discovery
- `only`: exclusively sitemap URLs, no HTML link extraction

**Chosen: Option C (three modes).** This matches Firecrawl's sitemap behavior and gives users explicit control. The sitemap parser (`SitemapParser`) is a separate module that handles XML sitemap parsing, nested sitemap index recursion, robots.txt sitemap directive processing, and fallback to common locations (`/sitemap.xml`, `/sitemap_index.xml`). The `ignoreSitemap` boolean field is preserved as a backward-compatible alias for `sitemap: "skip"`.

## Decision

**BFS traversal, shared `LinkExtractor`, URL-level dedup, sequential concurrency (with planned Semaphore), glob+regex path filtering, and three-mode sitemap integration.**

## Consequences

### Positive

- **Predictable BFS order.** The start URL is always first, depth-1 pages appear next, and polling users see progress in a natural top-down order.
- **Single source of truth for link extraction.** All link discovery (crawl, map, llmstxt) routes through the same `extract_links()` function, ensuring consistent handling of `<base>` tags, fragments, relative URLs, non-HTTP schemes, and malformed HTML.
- **Low per-crawl overhead.** The sequential loop with an in-memory seen set avoids Valkey round-trips for dedup and coordination. Small crawls (1-3 pages) complete in under a second.
- **Path filtering is both powerful and familiar.** Glob patterns work the way users expect (`*` matches path segments, `**` matches across segments), while regex mode provides an escape hatch for complex patterns.
- **Sitemap integration without behavioral surprises.** Sitemap-discovered URLs are deduplicated against BFS-discovered URLs, counted toward `max_pages`, and subject to the same path filters.

### Negative

- **Sequential scraping is slow for large crawls.** Without concurrency, crawl wall-clock time is the sum of all individual page scrape times. Milestone 3 (asyncio.Semaphore) is a required follow-up for production use cases.
- **No canonical-tag dedup in core.** Pages with different URLs but identical content (e.g., `/product` and `/product?ref=home`) are both scraped unless `ignoreQueryParameters` is set. Content hash dedup requires a separate pass.
- **Distributed coordination is deferred.** Multi-instance deployments must coordinate via Valkey job status (cooperative cancellation) rather than a distributed semaphore. Concurrent instances of the same crawl are not supported.
- **SitemapParser is a separate module dependency.** The crawl engine must import and coordinate with `SitemapParser`, adding module coupling. The parser's fallback logic (robots.txt → common locations) can mask misconfigured sites.

### Neutral

- **The `normalize_url()` function centralizes dedup logic.** Changes to normalization rules (e.g., adding trailing-slash policy) apply everywhere automatically.
- **Path filter evaluation order is fixed:** exclude checks run first, then include checks. This is documented and tested. Changing the order in the future would be a breaking change.
- **Module boundaries follow existing patterns** (ADR-0036, ADR-0037): `crawler.py` (orchestrator), `link_extractor.py` (shared extraction), `sitemap_parser.py` (XML parsing), with dedup and cache logic inlined where appropriate.

## Module Architecture

```
agent-svc/agent/
  crawler.py           — CrawlEngine BFS loop, normalize_url, path filtering,
                         queue management, seen-set dedup, store updates
  link_extractor.py    — extract_links(), filter_links(), classify_links()
                         (shared with /v2/map and llmstxt.py)
  sitemap_parser.py    — SitemapParser: fetch XML sitemaps, handle nested
                         index files, fallback to common locations
  dedup.py             — DedupManager: multi-layer URL normalization,
                         canonical tag extraction, content hash comparison
  crawl_cache.py       — CrawlCache: Valkey-backed response cache with
                         maxAge/minAge semantics
  worker.py            — _process_crawl_async(): orchestrates CrawlEngine +
                         job store + webhooks + metrics
  store.py             — JobStore: Valkey CRUD for job lifecycle
  scraper_client.py    — ScraperClient: HTTP client to scraper-svc
  webhook.py           — Webhook delivery: crawl.started, crawl.page,
                         crawl.completed, crawl.failed
  metrics.py           — Prometheus metrics: crawl jobs, pages, duration
```

## Data Flow

```
POST /v2/crawl { url, max_pages, max_depth, include_paths, ... }
  │
  ▼
api.py: create_crawl()
  ├── Validate CrawlRequest (Pydantic)
  ├── store.create_job(kind="crawl", status="processing")
  ├── task_tracker.create_background_task(_process_crawl_async(...))
  └── return { id, success: true }
       │
       ▼
worker.py: _process_crawl_async()
  ├── Fire crawl.started webhook
  ├── CrawlEngine.run(start_url, job_id)
  │   ├── [sitemap mode != skip]
  │   │   └── SitemapParser.get_urls(domain) → seed queue
  │   ├── BFS loop: deque.pop() → process (url, depth)
  │   │   ├── normalize_url(url) → _seen check → skip if duplicate
  │   │   ├── depth > max_depth? → skip
  │   │   ├── _match_path(url, include_paths, exclude_paths)? → skip
  │   │   ├── scraper.scrape(url, scrape_options)
  │   │   ├── Record page in result with metadata
  │   │   ├── [depth < max_depth]:
  │   │   │   ├── fetch_html(url) → raw HTML
  │   │   │   ├── LinkExtractor.extract_links(html, base_url)
  │   │   │   ├── LinkExtractor.filter_links(links, base_domain, ...)
  │   │   │   └── Enqueue unique child URLs at depth+1
  │   │   ├── Fire crawl.page webhook per page
  │   │   ├── Periodic store update for polling
  │   │   └── Check cancellation flag
  │   └── Stop: max_pages reached, queue empty, or cancelled
  ├── store.complete_job() or cancel_job()
  ├── Fire crawl.completed webhook
  └── Record Prometheus metrics
```

## Path Filter Precedence Rules

1. **URL-level checks are positional** — exclude_paths is checked before include_paths (short-circuit: if a URL matches any exclude pattern, it is immediately rejected)
2. **Exclude always wins over include** — a URL matching both exclude and include patterns is excluded
3. **Missing include_paths means "include all"** — when include_paths is `None`, all non-excluded URLs pass
4. **Empty include_paths (`[]`) means "include nothing"** — an explicit empty list is treated as blocking all paths that aren't explicitly included (implementation detail: the list is treated as a constraint, not a no-op)
5. **Mode selector (`regexOnFullUrl`)** — `false` (default): patterns are globs matched against URL path only; `true`: patterns are regexes matched against full URL
6. **Target selection depends on mode and flags** — in glob mode, matching is against the parsed path component; in regex mode, when `regexOnFullUrl` is true, matching is against the full URL including query parameters
7. **Path filters apply to every URL including the start URL** — if the start URL does not pass filters, the crawl returns 0 pages
8. **Filter evaluation happens before scraper dispatch** — filtered URLs do not consume scraper budget and do not count toward max_pages

## Dedup Normalization Pipeline

The `normalize_url()` function applies these transformations in order:

1. **Lowercase scheme and host** — `HTTP://Example.COM/Path` → `http://example.com/Path`
2. **Remove default ports** — `http://example.com:80/` → `http://example.com/`; `https://example.com:443/` → `https://example.com/`
3. **Strip fragment** — `/page#section` → `/page`
4. **Collapse dot segments** — `/./` removed, `/../` resolved via `posixpath.normpath()`
5. **Normalize trailing slash** — non-root paths ending in `/` have the slash removed
6. **Sort query parameters** — `?b=2&a=1` → `?a=1&b=2` (only when `ignoreQueryParameters` is false)
7. **Strip query strings** — when `ignoreQueryParameters` is true, `?ref=abc` is removed entirely

## Links

- Milestone 1 implementation: `agent-svc/agent/crawler.py`, `agent-svc/agent/link_extractor.py`
- Milestone 3 (concurrency): Planned `asyncio.Semaphore` worker pool in `crawler.py`
- Milestone 4 (content dedup): Planned canonical tag and content hash dedup in `dedup.py`
- Milestone 2 (sitemap): Planned `SitemapParser` in `agent-svc/agent/sitemap_parser.py`
- Refines ADR-0012: Webhook delivery pattern reused for crawl lifecycle webhooks
