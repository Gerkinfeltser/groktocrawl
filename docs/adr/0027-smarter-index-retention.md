# Phase 3 — Smarter Index Retention: Domain TTLs, Frequency Weighting, Access Boosting

* Status: proposed
* Deciders: magnus, jasper
* Date: 2026-06-08

Technical Story: Phase 2 (ADR-0026) added a persistent Qdrant vector index with eager indexing and crude LRU eviction — the oldest points by scroll order are deleted when the cap is reached. A news article scraped yesterday and a documentation page scraped 6 months ago get the same retention priority. The index should learn what's valuable based on content type, crawl frequency, and query patterns.

## Context and Problem Statement

Phase 2's eviction strategy is:

```
docs > MAX_DOCS → scroll first N points → delete them → done
```

This treats all documents equally. Three failure modes:

1. **News articles displace reference content.** A single scrape of `reuters.com` news fills the index with ephemeral content that will never be searched again, while a `docs.docker.com` page indexed 3 months ago gets evicted — even though it's far more likely to be useful in future search queries.

2. **Batch scrapes thrash the index.** A monitor scraping 500 product pages every 10 minutes re-indexes the same URLs, each time pushing their `last_indexed_at` forward. If another batch scrape runs on a different domain at the same time, LRU eviction deletes the newly indexed pages first — the exact pages the user just paid to scrape.

3. **No feedback from search relevance.** Pages returned in search results and actually useful to users get no retention boost. A frequently-accessed reference page has the same eviction priority as a page that has never been queried.

The fix is a scoring function that considers content type, crawl frequency, and access patterns — replacing the simple scroll-and-delete with a ranked eviction that keeps what the index actually needs.

## Decision Drivers

- Must **require no new infrastructure** — no new Docker services, workers, or databases
- Must **require no new ML dependencies** — domain classification is heuristic, scoring is arithmetic
- Must be **backward compatible** — existing payload fields unchanged; new fields are additive
- Must **survive container restarts** — scores are stored in Qdrant payload, recalculated on eviction
- Must **perform adequately at 250K documents** — scoring scan must complete in under 30s
- Must **not require a migration path** — new payload fields are optional; old points get default scores
- Must be **explainable** — the scoring function should be trivially computable from payload fields

## Considered Options

### A. Composite retention score stored in payload *(chosen)*

**How it works:**

Every Qdrant point gains new payload fields at index time:

| Field | Type | Description | Set At |
|---|---|---|---|
| `domain_category` | string | `news`, `docs`, `api`, `blog`, `social`, `reference`, `unknown` | index |
| `crawl_count` | int | Number of times this URL has been re-indexed | index (increment) |
| `access_count` | int | Number of times returned in search results | search (increment) |
| `first_indexed_at` | string | ISO 8601 timestamp of first index | index (preserved) |
| `last_indexed_at` | string | ISO 8601 timestamp of most recent index | index |
| `last_accessed_at` | string | ISO 8601 timestamp of last search hit | search |
| `retention_score` | float | Computed score for eviction ordering | eviction (recalculated) |

**Eviction flow:**

```
docs > MAX_DOCS → scroll all points (payload only) → compute score for each →
  sort ascending → delete lowest-scoring excess + buffer
```

**Scoring function:**

```
retention_score = domain_multiplier * recency_factor + access_boost + crawl_boost
```

| Component | Formula | Range |
|---|---|---|
| `domain_multiplier` | Category lookup | 0.3–1.2 |
| `recency_factor` | exp(-days_since_last_index / 90) | 0.1–1.0 |
| `access_boost` | min(access_count, 100) × 0.01 | 0.0–1.0 |
| `crawl_boost` | min(crawl_count, 20) × 0.05 | 0.0–1.0 |

**Domain categories and multipliers:**

| Category | Multiplier | Examples |
|---|---|---|
| `news` | 0.3 | reuters.com, nytimes.com, cnn.com |
| `social` | 0.4 | reddit.com, twitter.com, youtube.com |
| `blog` | 0.6 | medium.com, substack.com, blog.* |
| `api` | 0.7 | api.github.com, developer.mozilla.org |
| `unknown` | 0.8 | Default for unrecognized domains |
| `reference` | 1.0 | wikipedia.org, stackoverflow.com, docs.python.org |
| `docs` | 1.2 | docs.docker.com, learn.microsoft.com, readthedocs.io |

**Worked examples:**

- **News article indexed today, never accessed** → 0.3 × 1.0 + 0 + 0 = **0.30**
- **News article indexed 90 days ago, never accessed** → 0.3 × 0.37 + 0 + 0 = **0.11**
- **Docs page indexed 90 days ago, accessed 50 times** → 1.2 × 0.37 + 0.5 + 0 = **0.94**
- **Docs page indexed 90 days ago, accessed 50 times, re-crawled 20 times** → 1.2 × 0.37 + 0.5 + 1.0 = **1.94**
- **Reference page indexed today** → 1.0 × 1.0 + 0 + 0 = **1.00**

The eviction candidate is the lowest score — news articles always evict first, well-accessed reference and docs pages persist.

**Access tracking:** After `POST /search/vector` returns results, fire a background task that increments `access_count` and updates `last_accessed_at` for the returned point IDs. This is fire-and-forget — failure never blocks the search response.

**Efficiency:** Scoring requires scrolling all points with payloads but without vectors. At 250K documents × ~200 bytes payload = ~50MB. Qdrant scroll is paginated and parallel-safe. Estimated scoring time: <10s for 250K points.

**Positive:**
- No new infrastructure or dependencies
- Backward compatible — old points get defaults (`domain_category=unknown`, `crawl_count=0`, `access_count=0`)
- Explainable — every component is a simple field lookup or arithmetic
- Search feedback loop — pages that are actually useful get better retention
- Domain classification is entirely heuristic — no model dependency

**Negative:**
- Scoring scan is O(N) — at 250K documents it's fast enough, but doesn't scale to millions
- Domain classification is heuristic — may miscategorize unfamiliar domains
- `retention_score` is stale between evictions — recalculated only when needed
- Access tracking adds latency to search endpoint (fire-and-forget mitigates this)

### B. Qdrant payload index + select before scroll

Use Qdrant's payload indexing to filter candidates before scrolling — e.g., only re-score documents with `domain_category = "news"` or `last_indexed_at > 30 days`.

**Positive:**
- Faster eviction — fewer points to score
- Scales to larger indices

**Negative:**
- More complex — payload index setup, composite condition logic
- Risk of missing the true lowest-scoring document if the filter misses it
- Qdrant payload indexing has different performance characteristics per type
- Rejected: risks evicting a low-scoring document that doesn't match the filter

### C. Background periodic re-scoring with cron

Use a cron job or background task to periodically re-score the entire index and update `retention_score` in payloads. Eviction then becomes a simple scroll sorted by score.

**Positive:**
- Eviction is O(1) — just delete lowest-N by precomputed score
- Score is always fresh — not computed at eviction time
- Better separation of concerns — scoring is a background job, eviction is a lookup

**Negative:**
- New infrastructure — cron job or background task scheduler
- Qdrant doesn't support server-side sort by payload field without a payload index
- Adds operational complexity for no benefit at 250K scale
- Rejected: scoring at eviction time is fast enough for Phase 3; background re-scoring can be added later if needed

## Decision Outcome

Chosen option: **A. Composite retention score stored in payload.** Scoring at eviction time, stored back to payload for cache efficiency. No new infrastructure. Backward compatible. Explainable.

### Changes

**semantic-svc/app.py:**

- `_compute_domain_category(url)` — new pure function mapping URLs to domain categories
- `_compute_retention_score(payload)` — new function computing the composite score
- `_evict_if_needed()` — replaced with scoring-based eviction: scroll all, score, sort, delete lowest
- `index_page()` — enriched payload with new fields; category, crawl_count, first/last indexed timestamps
- `search_vector()` — access tracking: after returning results, fire background task to increment `access_count` and update `last_accessed_at` for returned point IDs
- `IndexRequest` — no changes needed; fields are derived from URL and server state

**agent-svc/agent/worker.py:**

- `_index_page_async()` — pass the title from scrape result instead of empty string

**agent-svc/agent/semantic_client.py:**

- No changes needed — existing `index_page()` already sends url, title, content

**Domain classification:**

```python
def _compute_domain_category(url: str) -> str:
    """Classify a URL's domain into a retention category."""
    netloc = urllib.parse.urlparse(url).netloc.lower()
    if netloc.startswith(("docs.", "learn.", "help.")):
        return "docs"
    if netloc.startswith(("api.", "developer.")):
        return "api"
    if ".readthedocs." in netloc or ".help." in netloc:
        return "docs"
    known_docs = {"wikipedia.org", "stackoverflow.com",
                  "stackexchange.com", "github.com"}
    for d in known_docs:
        if d in netloc:
            return "reference"
    known_news = {"reuters.com", "nytimes.com", "cnn.com",
                  "bbc.com", "bbc.co.uk", "bloomberg.com",
                  "apnews.com", "npr.org", "theguardian.com",
                  "wsj.com", "washingtonpost.com", "economist.com"}
    for d in known_news:
        if d in netloc:
            return "news"
    known_social = {"reddit.com", "twitter.com", "x.com",
                    "youtube.com", "instagram.com", "tiktok.com",
                    "bluesky", "bsky.app", "threads.net"}
    for d in known_social:
        if d in netloc:
            return "social"
    known_blog = {"medium.com", "substack.com", "ghost.io",
                  "wordpress.com", "blogspot.com"}
    for d in known_blog:
        if d in netloc:
            return "blog"
    if netloc.startswith("blog."):
        return "blog"
    return "unknown"
```

### Positive Consequences

* News and social content evicts first — reference and docs content persists
* Pages that are actually searched for get a retention boost
* Frequently re-crawled pages (monitors, recurring jobs) stay longer
* Retains all Phase 2 architecture — no new services or dependencies
* Backward compatible — old points with missing fields get defaults

### Negative Consequences

* Domain classification is heuristic — may not cover all edge cases
* Scoring scan is O(N) — acceptable at 250K, but a ceiling
* Access tracking is fire-and-forget — if it fails, the count doesn't increment

### Risks

* **Scoring scan performance at scale:** 250K points × ~200B payload ≈ 50MB network transfer. Qdrant's paginated scroll is efficient, but at 500K+ documents the O(N) scan becomes a latency concern. Mitigated: Phase 3 cap is 250K; Option B or C are fallbacks for future growth.
* **Domain classification accuracy:** Custom domains on CDNs (cdn.company.com) or subdomains (sub.docs-site.com) may not match known patterns. Mitigated: default classification `unknown` (0.8 multiplier) is safe — it's better than news.
* **Access count inflation in parallel search:** If two concurrent searches return the same URL, the fire-and-forget task may double-increment. Mitigated: access_count is approximate to within ±5% — acceptable for a retention signal. Exact precision isn't required.

## Implementation Scope (This PR)

**In scope:**
- Domain classification function in semantic-svc/app.py
- Retention scoring function in semantic-svc/app.py
- Modified `_evict_if_needed()` using scoring-based eviction
- Enriched index payload with new metadata fields
- Access tracking in search_vector endpoint
- Title passthrough fix in agent-svc worker
- Comprehensive test suite (domain classification, retention scoring, access tracking, eviction ordering)
- ADR-0027 (this document)
- Architecture.md update (indexing pipeline diagram)

**Out of scope (future):**
- Index analytics dashboard
- Background periodic re-scoring
- Qdrant payload index for sorted eviction
- Machine-learning-based domain classification

## Links

* Issue: [#152](https://github.com/groktopus/groktocrawl/issues/152)
* Phase 2: [ADR-0026](0026-phase2-vector-index.md), PR #145
* Qdrant: [qdrant.tech](https://qdrant.tech/)
