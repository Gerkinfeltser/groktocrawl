# Observability

**Owner:** GroktoCrawl maintainers

| Source of truth | Artifact |
|---|---|
| Prometheus scrape jobs | `docs/prometheus/scrape-config.yml` |
| Prometheus alerts | `docs/prometheus/alerts.yml` |
| Grafana dashboards | `docs/grafana/*-svc-dashboard.json` |
| Incident response | `docs/runbooks/` |

| Service | Metrics endpoint | Prometheus job | Dashboard UID |
|---|---|---|---|
| agent-svc | `http://agent-svc:8080/metrics` | `agent-svc` | `groktocrawl_agent_svc` |
| scraper-svc | `http://scraper-svc:8001/metrics` | `scraper-svc` | `groktocrawl_scraper_svc` |
| semantic-svc | `http://semantic-svc:8003/metrics` | `semantic-svc` | `groktocrawl_semantic_svc` |

| Alert | Runbook |
|---|---|
| HighJobErrorRate | `docs/runbooks/high-job-error-rate.md` |
| QueueDepthSpike | `docs/runbooks/queue-depth-spike.md` |
| ServiceDown | `docs/runbooks/service-down.md` |

Environment-specific target addresses and contact-point secrets are deployment overlays and must never enter this public repository.

`scraper-svc` exports `captcha_attempts_total{provider,strategy,outcome}`. All
labels are bounded provider and strategy constants; URLs, challenge content,
tokens, and screenshots are never metric labels.

## Stage-level telemetry

Performance-stage latency and capacity signals (ADR-0048) are exported with a
`groktocrawl_` prefix and bounded, enum-like label values. Raw URLs, tokens, and
content are never metric labels.

| Service | Metric families |
|---|---|
| agent-svc | `groktocrawl_research_plan_seconds`, `groktocrawl_research_total_seconds{search_type}`, `groktocrawl_research_rank_seconds{mode}`, `groktocrawl_research_gap_detection_seconds`, `groktocrawl_search_query_seconds{engine}`, `groktocrawl_search_queries_total{engine,outcome}`, `groktocrawl_llm_call_seconds{stage}`, `groktocrawl_llm_calls_total{stage,outcome}`, `groktocrawl_research_memory_lookup_seconds`, `groktocrawl_research_memory_lookup_total{outcome}`, `groktocrawl_research_memory_sweep_runs_total`, `groktocrawl_research_memory_orphans_swept_total`, `groktocrawl_research_memory_orphans`, `groktocrawl_scrape_cache_lookup_seconds`, `groktocrawl_scrape_cache_lookup_total{outcome}`, `groktocrawl_active_jobs{type}`, `groktocrawl_jobs_cancelled_total{type}`, `groktocrawl_time_to_first_event_seconds{stream_type}`, `groktocrawl_time_to_first_token_seconds{stream_type}`, `admission_active{class}`, `admission_queue_depth{class}`, `admission_wait_seconds{class}`, `admission_rejected_total{class}`, `admission_cancelled_total{class}` |
| scraper-svc | `groktocrawl_scrape_tier_total{tier,outcome}`, `groktocrawl_scrape_tier_duration_seconds{tier,outcome}`, `groktocrawl_scrape_cache_lookup_seconds`, `groktocrawl_scrape_cache_lookup_total{outcome}`, `groktocrawl_adapter_dispatch_total{adapter_group,outcome}`, `groktocrawl_browser_semaphore_active`, `groktocrawl_browser_semaphore_waiters`, `groktocrawl_browser_semaphore_wait_seconds`, `groktocrawl_browser_setup_seconds`, `groktocrawl_browser_navigation_seconds`, `groktocrawl_browser_extraction_seconds`, `groktocrawl_browser_cleanup_total{outcome}`, `admission_active{class="browser"}`, `admission_queue_depth{class="browser"}`, `admission_wait_seconds{class="browser"}`, `admission_rejected_total{class="browser"}`, `admission_cancelled_total{class="browser"}` |
| browser-svc | `groktocrawl_browser_active_sessions`, `groktocrawl_browser_sessions_destroyed_total{reason}` |

Latency metrics use `_duration_seconds`/`_seconds` (histograms) and outcome
counters use `_total` (counters). The `outcome` label values for
research-memory lookups (`fresh`/`aging`/`stale`/`miss`/`error`) and for
scrape-cache lookups (`hit`/`miss`/`stale`/`error`) are shared with the
cache-freshness model so they compose across services.

## Deduplication and retry counters

`agent-svc` exports two counters so deduplicated fetches and explicit retries
are observable separately. Label values are bounded, enum-like constants; raw
URLs, content, and tokens are never metric labels.

| Metric | Labels | Meaning |
|---|---|---|
| `fetches_deduped_total` | `reason` (`rerank_reuse`) | Scrapes avoided by reusing source content already fetched during ranking |
| `scrape_retries_total` | `stage` (`generic_to_browser`) | Explicit scrape retries by stage transition |

## Verification

1. Validate the deployment's Prometheus configuration and rules with its native check commands.
2. Confirm all three targets are healthy and query a current metric, for example `up{job="agent-svc"}`.
3. Import or provision the dashboards and confirm their UIDs are loaded.
4. Confirm the alert rules are loaded and test the deployment contact point.
5. Run the supported external API probe:

   ```bash
   groktocrawl --server "$GROKTOCRAWL_API_URL" --json search "observability probe" --limit 1
   ```
