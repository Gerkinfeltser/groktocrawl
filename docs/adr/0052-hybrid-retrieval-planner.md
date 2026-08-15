# Concurrent Cache-Assisted Hybrid Retrieval Planner

- Status: accepted
- Deciders: GroktoCrawl maintainers
- Date: 2026-01-15

## Context

`hybrid_vector` retrieval combined SlopSearX (web) and Qdrant (vector) results by
running the two lookups sequentially and then concatenating web results before
vector results, truncating to the requested limit. Two consequences followed:

1. The independent searches did not overlap in time, so latency was the sum of
   both lookups.
2. A full web result budget suppressed every Qdrant-only candidate, because web
   results were always placed first and the merge was truncated.

The local page index is not a substitute for open-web search: it stores an
embedding plus URL/title metadata, not page Markdown or a complete web corpus.
However, its URLs can be combined with the Valkey scrape cache to avoid repeat
network work when cached content meets the caller's freshness policy.

This change (issue #532) introduces a single hybrid retrieval planner that runs
the two discovery branches concurrently, blends them deterministically with a
floor guarantee, and reuses compatible cached Markdown before live-scraping
misses.

## Decision

We introduce `agent-svc/agent/research/hybrid.py` with one
`plan_hybrid_retrieval(...)` function. The three existing `hybrid_vector` call
sites (`routes/search.py`, `research/search.py:run_search_stream`, and
`research/rerank.py:_rerank_answer_sources`) delegate to it rather than each
maintaining a copy of the merge.

**Concurrent, independently timeout-bounded discovery.** SlopSearX and Qdrant
(`semantic.search_vector`) run via `asyncio.gather(..., return_exceptions=True)`,
each wrapped in `asyncio.wait_for` (web 15s, vector 8s by default). The
concurrent work runs inside the global admission budget
(`app.state.admission.acquire("lightweight_fetch", ...)`); a cancelled or timed-out
branch releases its budget via the `resource()` context manager.

**Deterministic blend with a floor guarantee.** URLs are normalised (lowercased
scheme/host, default ports dropped, fragment stripped, trailing slash stripped)
and deduplicated by that normalised form, recording per-URL provenance
(`web`/`vector`/`both`). The blend uses::

    floor_web    = max(0, limit - len(vector_unique))
    floor_vector = max(0, limit - len(web_unique))

The web floor and vector floor are emitted first (each in its source's rank
order), then the remaining slots are filled by round-robin interleaving of the
two rank orders (web first). Rank order within a source is preserved, keeping
each source's own relevance signal; the round-robin interleave is the
deterministic cross-source tie-break, and overlapping URLs are emitted once,
keeping web's richer metadata and the vector score when present. This guarantees
a full budget from either source cannot starve the other — a Qdrant-only
candidate always has a chance to enter the final candidate set.

**Cache-assisted acquisition.** When a scraper is supplied, each surviving
candidate consults `CrawlCache.check_cache(url, max_age_ms=...)` (default
1-hour freshness window). A fresh, compatible entry (non-empty Markdown) is
reused and recorded with `cache_state="from_cache"` and `cache_age_ms`; misses
and stale entries are live-scraped via the existing `_scrape_urls` machinery and
recorded with `cache_state="live"`. Cache lookups are best-effort: a failure
degrades to a live scrape. Canonically-equivalent URLs are scraped or cache-read
once because they are deduplicated before acquisition.

**Provenance on the artifact.** `SourceArtifact` gains `retrieval`
(`web`/`vector`/`both`), `score` (optional float), and `cache_age_ms` (optional
int); the existing `cache_state` field records cache vs live acquisition. This
metadata is carried into ranking and synthesis.

**Graceful degradation.** If the semantic service is disabled or unavailable,
the planner returns web-only results (equivalent to the keyword path). If
SearXNG fails or returns nothing, it returns vector-only results. Transport
failures never propagate to callers.

The web/vector ratio is intentionally not configurable: the deterministic floor
policy is hardcoded, as the ratio is a cross-cutting retrieval-quality concern
that warrants a dedicated experiment (the benchmark script) before any tuning
knob is added.

## Consequences

- Positive: web and vector discovery overlap, bounded independently, so hybrid
  latency is the max of the two branches rather than their sum.
- Positive: Qdrant-only candidates can enter the final set even when web returns
  a full budget, improving source diversity.
- Positive: fresh, compatible cached Markdown is reused for both web and vector
  candidates, avoiding repeat network work; provenance is observable per source.
- Positive: semantic failure degrades to keyword behaviour and SearXNG failure to
  vector-only behaviour, with no exceptions leaking to callers.
- Negative: the cache freshness window (default 1 hour) is a hardcoded policy;
  the cache-contract issue (#529) owns stale-serving semantics, and this planner
  never reuses stale content.
- Negative: the floor/blend policy is deterministic but not yet tuned against a
  live workload; the benchmark script compares latency, source diversity,
  citation validity, and answer quality but explicitly makes no universal claim
  from a single run.

## Links

- [ADR-0050 Request-Scoped Source Artifact](0050-source-artifact-and-lightweight-only-scrape.md)
- [ADR-0051 Global Admission Control and End-to-End Cancellation](0051-global-admission-control-and-cancellation.md)
- [ADR-0048 Stage-Level Telemetry](0048-stage-level-telemetry.md)
