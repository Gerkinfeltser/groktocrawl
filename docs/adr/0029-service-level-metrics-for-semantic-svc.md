# ADR-0029: Service-Level Metrics for semantic-svc

**Status:** Accepted

**Deciders:** Magnus Hedemark, Jasper (AI Agent)

**Date:** 2026-06-08

## Context

GroktoCrawl's semantic-svc is the vector indexing service that handles embedding, reranking, and vector search. It has 11 endpoints as of Phase 4 (ADR-0028) and serves as the content gateway for the persistent vector index. Despite its centrality, there is zero visibility into:

- Index size growth over time (`/index/stats` provides a point-in-time snapshot but no history)
- Query latency degradation (no timing data collected)
- Eviction rate when the index reaches capacity
- Embedding duration (BGE-M3 inference takes 50-500ms per page)

ADR-0018 (Observability Infrastructure) established metrics and health reporting for agent-svc, but explicitly scoped itself to *agent-svc only*: "Metrics scoped to agent-svc only."

Since ADR-0018 was written, the project has grown from 3 services to 8+, and semantic-svc has become the most performance-sensitive service in the stack (runs BGE-M3 ~2GB model, handles 250K+ document indices, processes synchronous embedding requests). The lack of per-service visibility creates blind spots that a single agent-svc `/metrics` cannot cover.

## Decision Drivers

1. **Follow ADR-0018's pattern** — the stdlib-based OpenMetrics approach is project convention. No new dependencies.
2. **Semantic-svc is synchronous** — unlike agent-svc (async with webhooks), semantic-svc endpoints are synchronous request-response. Per-request latency is directly user-visible.
3. **Eviction is invisible** — `_evict_if_needed()` runs silently. Counter needed for cumulative evictions.
4. **Existing Prometheus stack** — ADR-0018's `/metrics` format was designed for Prometheus consumption. Prometheus is already deployed in the homelab.
5. **Minimal code footprint** — reuse the same `MetricsCollector` / `METRICS` singleton pattern from agent-svc.

## Considered Options

### Option A: Add semantic-svc metrics to agent-svc's /metrics endpoint

Agent-svc calls semantic-svc's `/index/stats` periodically and exposes those values on its own `/metrics` endpoint.

- **Pros:** Single scrape target. No new endpoint.
- **Cons:** Semantic-svc latency histograms cannot be collected from agent-svc (timing happens inside semantic-svc's request handler). Creates coupling between services. Metric freshness depends on poll interval.
- **Rejected** — latency histograms must be captured at the point of execution.

### Option B: prometheus-client library for semantic-svc

Add `prometheus-client` to semantic-svc's dependencies and use its built-in OpenMetrics format.

- **Pros:** Industry standard, auto-generated format, histogram bucketing built-in.
- **Cons:** Explicitly rejected in ADR-0018's Option B analysis. Inconsistent with project convention. Adds a dependency for a pattern the project deliberately avoided.
- **Rejected** — consistency with ADR-0018 is a hard constraint.

### Option C: Copy agent-svc's metrics.py to semantic-svc (chosen)

Copy the `MetricsCollector` / `METRICS` singleton from `agent-svc/agent/metrics.py` into a standalone `semantic-svc/metrics.py` module. Instrument each semantic-svc endpoint with timing histograms and request counters via ASGI middleware. Expose via a `GET /metrics` endpoint on port 8003.

- **Pros:** Zero new dependencies. Follows established project convention. Thread-safe. Metrics capture latency at the point of execution. OpenMetrics format ready for Prometheus consumption.
- **Cons:** Code duplication between services (~130 lines each). Each service must be scraped separately.
- **Chosen.**

## Decision

Adopt **Option C: Copy agent-svc's metrics.py pattern to semantic-svc** with the following metrics:

| Metric Name | Type | Labels | Description |
|---|---|---|---|
| `groktocrawl_index_docs_total` | gauge | — | Current document count in Qdrant |
| `groktocrawl_index_evictions_total` | counter | — | Cumulative evictions since startup |
| `groktocrawl_index_query_duration_seconds` | histogram | `endpoint` | Request latency by endpoint |
| `groktocrawl_index_embeddings_duration_seconds` | histogram | — | Embedding model inference latency |
| `groktocrawl_search_requests_total` | counter | `endpoint` | Request counter per endpoint |

### Key Design Decisions

- **Middleware-based instrumentation, not per-handler.** A single ASGI middleware records request count and duration for all 11 endpoints automatically. Only the embedding duration (model inference time, separate from total request latency) is instrumented inline in the `/embed` handler.
- **Gauge for doc count.** The document count is a point-in-time snapshot read from Qdrant on each `/index/stats` call. A counter would require tracking cumulative changes, which is fragile across restarts.
- **Eviction counter resets on restart.** In-memory only. For restart-surviving eviction counts, store in a Qdrant point or Valkey — filed as future improvement.
- **Grafana dashboard ships as JSON export.** A dashboard JSON file in `docs/grafana/` enables one-click import on the existing Grafana instance.
- **No new endpoints.** `/metrics` is at `GET /metrics` on the existing port 8003, same security model as `/health`.

## Consequences

### Positive

- Index growth, eviction rate, query latency, and request throughput are now observable.
- Zero new dependencies — follows ADR-0018's stdlib approach.
- Prometheus-ready — the existing scraping infrastructure picks up the new target immediately.
- The same pattern can be applied to other services (scraper-svc, portal-svc) if needed.

### Negative

- Code duplication of metrics.py across services (~130 lines each).
- Eviction counter resets on container restart (in-memory only). Acceptable for current scale.

### Neutral

- Prometheus must be configured with a second scrape target for `semantic-svc:8003`.
- The Grafana dashboard JSON is a separate manual import step.

## Links

- Relates to [ADR-0018](0018-observability-infrastructure.md) (established the metrics pattern this ADR extends)
- Supersedes ADR-0018's scope limitation ("agent-svc only") by extending the metrics pattern to semantic-svc
