# Request-Scoped Source Artifact and Lightweight-Only Scrape Contract

- Status: accepted
- Deciders: GroktoCrawl maintainers
- Date: 2026-08-15

## Context

Several request paths performed avoidable duplicate work. A non-streaming agent request could run the research-memory semantic lookup in the route and again in the background worker. Semantic and hybrid answer reranking scraped candidate URLs sequentially and then the normal answer pipeline scraped the selected URLs again. Hybrid reranking ranked against search-result descriptions instead of the fetched content. And `scrape_with_fallback()` called the full generic scraper pipeline — which can itself reach the Playwright browser tier — before starting a separate forced-browser retry, potentially leaving an unobserved browser lifecycle running while a second one started.

Issue #530 targets these residual problems without introducing a global admission budget (#531) or the provenance/cache-age fields on the artifact (#532).

## Decision

We introduce two coordinated mechanisms.

### 1. Request-scoped source artifact

A new `agent-svc/agent/research/sources.py` defines a `SourceArtifact` dataclass carrying `url`, `title`, `relevance`, optional `markdown`, `source` (tier provenance), `char_count`, `cache_state`, and `fetched_at`. `_scrape_single` and `_scrape_urls` in `research/discovery.py` now produce and return artifacts; `_scrape_urls` still honors the `min_sources` / `max_concurrent` contract and awaits cancelled speculative tasks before returning.

`research/rerank.py:_rerank_answer_sources` scrapes ranking candidates concurrently under an `asyncio.Semaphore` (default 5, mirroring `_scrape_urls`) and returns `(ranked_results, artifacts)`. For hybrid mode it passes the fetched Markdown to `semantic.rerank` instead of search-result descriptions. `_run_answer_discover_and_scrape` and `run_answer_stream` reuse artifact Markdown for synthesis and scrape only URLs whose content is missing, falling back to video-platform URLs as before. The replayable `CompactSource` projection in `research/state.py` remains content-free — Markdown is never persisted into the event state.

### 2. Lightweight-only scrape contract

`lightweight_only: bool = False` is threaded through `ScraperClient.scrape` → `ScrapeRequest` → `smart_scrape`. When true, `smart_scrape` runs only the lightweight tiers (adapter, cache, Tier 1 llms.txt, Tier 2 content negotiation) and short-circuits before Tier 3 Playwright. `scrape_with_fallback` uses `lightweight_only=True` for the generic stage and, on a generic timeout, cancels and awaits the timed-out task before starting the forced-browser stage.

## Consequences

- Positive: a non-streaming agent request performs at most one research-memory lookup; a URL is scraped at most once per request unless an explicit, observable retry authorizes another attempt; hybrid ranking ranks fetched content rather than discarding it.
- Positive: the generic fallback stage can no longer silently enter the browser tier, and timed-out generic work is awaited through cleanup before any retry.
- Positive: `fetches_deduped_total{reason}` and `scrape_retries_total{stage}` make deduplicated fetches and explicit retries independently observable.
- Negative: `_scrape_urls` and `_rerank_answer_sources` return artifacts rather than the legacy `(documents, source_details)` pair, so callers (including tests) must project artifacts through `SourceArtifact.to_document()` / `to_source_detail()` or `artifacts_to_documents_and_details()`.
- Scope guardrail: this change deliberately does not add #532's provenance/score/cache-age fields to the artifact, does not rework the search-route duplicate-scrape pattern, and does not implement the #531 global admission budget.

## Links

- [ADR-0041 Research Memory — Cross-Session Semantic Cache](0041-research-memory.md)
- [ADR-0048 Stage-Level Latency and Capacity Telemetry](0048-stage-level-telemetry.md)
- [ADR-0049 Research Memory Compatibility Fingerprint, Freshness, and Stale-While-Revalidate](0049-research-memory-compatibility-freshness-swr.md)
