# Stage-Level Latency and Capacity Telemetry

- Status: accepted
- Deciders: GroktoCrawl maintainers
- Date: 2026-01-15

## Context

The existing request-level histograms (`http_request_duration_seconds{method,path}`) establish aggregate latency but cannot identify which stage owns the slow tail. The research path spans planning, search, URL ranking, research-memory and scrape-cache lookups, lightweight fetches, browser queueing/rendering, synthesis, and optional gap-filling. Browser work is additionally bounded by a service-wide semaphore, but queue wait and saturation are not visible as first-class signals.

Issue #108 established the observability foundation and #153 added vector-index metrics; this change narrows the remaining gap to performance diagnosis and regression evidence for the performance sprint. The benchmark evidence produced here is the gate for later decisions about persistent browser-process reuse and additional domain adapters — neither optimisation is implemented in this change.

## Decision

We add bounded-cardinality, stage-level instrumentation across the research pipeline, scraper/browser tiers, streaming endpoints, and workload-class capacity signals, using the existing `common.metrics` collector (ADR-0018, ADR-0029). All metric names use the `groktocrawl_` prefix and all label values are enum-like constants; raw URLs, tokens, and content are never labels.

The following signals are introduced:

- Research stages (agent-svc): `groktocrawl_research_plan_seconds`, `groktocrawl_research_total_seconds{search_type}`, `groktocrawl_research_rank_seconds{mode}`, `groktocrawl_research_gap_detection_seconds`, `groktocrawl_search_query_seconds{engine}` + `groktocrawl_search_queries_total{engine,outcome}`, and `groktocrawl_llm_call_seconds{stage}` + `groktocrawl_llm_calls_total{stage,outcome}`.
- Cache lookups: `groktocrawl_research_memory_lookup_seconds` + `groktocrawl_research_memory_lookup_total{outcome}` (agent-svc) and `groktocrawl_scrape_cache_lookup_seconds` + `groktocrawl_scrape_cache_lookup_total{outcome}` (both the crawl cache in agent-svc and the scrape-result cache in scraper-svc). Outcome values are bounded (`fresh`/`aging`/`stale`/`miss`/`error` for research memory; `hit`/`miss`/`stale`/`error` for scrape caches) and compose with the future cache-freshness model in #529.
- Browser lifecycle (scraper-svc): `groktocrawl_browser_semaphore_active`, `groktocrawl_browser_semaphore_waiters`, `groktocrawl_browser_semaphore_wait_seconds`, `groktocrawl_browser_setup_seconds`, `groktocrawl_browser_navigation_seconds`, `groktocrawl_browser_extraction_seconds`, and `groktocrawl_browser_cleanup_total{outcome}`.
- Browser sessions (browser-svc): `groktocrawl_browser_active_sessions` and `groktocrawl_browser_sessions_destroyed_total{reason}`.
- Scrape tiers and adapters: `groktocrawl_scrape_tier_total{tier,outcome}` + `groktocrawl_scrape_tier_duration_seconds{tier,outcome}` (scraper-svc) and `groktocrawl_adapter_dispatch_total{adapter_group,outcome}` (adapter registry).
- Streaming: `groktocrawl_time_to_first_event_seconds{stream_type}` and `groktocrawl_time_to_first_token_seconds{stream_type}` (`agent`/`answer`/`search`/`crawl`), measured at async-generator body entry (first `__anext__`), not at `StreamingResponse` construction.
- Workload capacity (agent-svc): `groktocrawl_active_jobs{type}` gauge and `groktocrawl_jobs_cancelled_total{type}` counter, alongside the existing `jobs_submitted_total`/`jobs_completed_total`/`jobs_failed_total`.

Shared helpers live in `common/stage_metrics.py` and `common/metrics.py` (`timer()` context manager, gauge `inc`/`dec`) so metric registration is not copy-pasted across services (jscpd gate). Latency is recorded with `time.monotonic()`; percentiles are derived by the benchmark harness using stdlib `statistics` (linear interpolation over raw samples).

A stdlib-only benchmark harness (`benchmarks/run_benchmarks.py`) runs N times across cold-scrape, warm-scrape, lightweight-fetch, browser-fallback, answer, agent-research, and batch-scrape fixtures, derives p50/p95, and writes a checked-in baseline artifact (`{commit_sha, config_class, runs, results}`) with no hostname/IP/machine identifiers.

## Consequences

- Positive: operators can attribute tail latency to a specific stage and observe browser semaphore saturation and active-work counts directly in Prometheus/Grafana.
- Positive: the benchmark harness produces reproducible, portable regression evidence for gating browser-process reuse and adapter investment.
- Negative: label cardinality must remain disciplined — every new label value must be a bounded constant, and new stages must use the shared helpers.
- Negative: the added instrumentation increases per-stage overhead marginally (`time.monotonic()` + a lock-guarded histogram/counter update); this is negligible relative to network/LLM latency.
- Scope guardrail: this change deliberately does not implement browser-process reuse or new domain adapters; those remain gated on the measured evidence.

## Links

- [ADR-0018 Observability Infrastructure](0018-observability-infrastructure.md)
- [ADR-0022 Agent SSE Streaming](0022-agent-sse-streaming.md)
- [ADR-0029 Service-Level Metrics for semantic-svc](0029-service-level-metrics-for-semantic-svc.md)
