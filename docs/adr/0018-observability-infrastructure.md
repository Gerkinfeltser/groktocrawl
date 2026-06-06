# ADR-0018: Observability Infrastructure — Health, Metrics, and Structured Logging

**Status:** Accepted

**Deciders:** Magnus Hedemark, Jasper (AI Agent)

**Date:** 2026-06-06

## Context

GroktoCrawl runs 8 containers (agent-svc, scraper-svc, browser-svc, parse-svc, valkey, searxng, ofelia, flare-solverr) with zero aggregate health visibility. The existing `/health` endpoint on agent-svc returns a static `{"status": "ok"}` with no dependency probes. There is no metrics collection, and logging is unstructured (ad-hoc `print()` statements and `logging.info()` with no common schema).

This creates several failure modes:
- A silent OOM in browser-svc or parse-svc is undetectable until a user reports a failure.
- SearXNG can degrade (fewer engines responding) without triggering any alert.
- The known single-process job processing bottleneck is dangerous without visibility into whether jobs are completing vs silently failing.
- Capacity planning and latency regression debugging are impossible without per-request timing data.

## Decision Drivers

1. **Zero new infrastructure services** — the observability layer must live inside agent-svc. No separate collector, no Grafana dependency, no `otel-collector`.
2. **Prometheus-compatible** — the /metrics endpoint must export OpenMetrics text format for future Prometheus scraping, but no Prometheus deployment is required at this stage.
3. **Minimal dependencies** — avoid adding heavy observability libraries. The OpenMetrics format is simple enough to implement with stdlib data structures.
4. **The /health endpoint is already consumed** — the integration test (`tests/test_stack.py`) already calls `/health`. The response shape must remain backward-compatible (top-level `status: "ok"`) while adding a dependant `checks` field.
5. **Request ID correlation** — each request must carry a traceable ID through logs for debugging multi-hop flows (agent-svc → scraper-svc → browser-svc).

## Considered Options

### Option A: Full OpenTelemetry with OTLP exporter
- Push-based telemetry to an OTLP collector.
- **Pros:** Industry standard, auto-instrumentation available for FastAPI.
- **Cons:** Requires a collector container, adds 3+ dependencies (`opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-instrumentation-fastapi`), introduces a push dependency the project doesn't need yet. Rejected.

### Option B: Prometheus client library (`prometheus-client`)
- Standard pull‑based metrics with built-in OpenMetrics support.
- **Pros:** Handles histogram bucketing, counter inc/dec, and OpenMetrics formatting. Zero-collector architecture — Prometheus scrapes agent-svc directly. Mature, widely deployed.
- **Cons:** Adds a library dependency (`prometheus-client`). Rejected — the OpenMetrics text format is simple enough to implement in ~100 lines of stdlib Python, and the project values minimal dependencies.

### Option C: Manual in-memory metrics + stdlib OpenMetrics formatting (chosen)
- A `metrics.py` module with `Counter`, `Histogram`, and `Gauge` wrappers around `collections.defaultdict` + `threading.Lock`. Exports native OpenMetrics text via a FastAPI endpoint.
- **Pros:** Zero new dependencies. Full control over format. Simple to understand and extend. Matches the project's "keep dependencies minimal" convention.
- **Cons:** No auto-instrumentation — every timing call is explicit. This is acceptable at current scale (single-process, known code paths).

## Decision

Adopt **Option C: Manual in-memory metrics with stdlib OpenMetrics formatting**.

The metrics layer consists of:

1. **`agent-svc/agent/metrics.py`** — a module providing thread-safe `Counter`, `Histogram`, and `Gauge` classes backed by plain Python data structures. Exposes `generate_openmetrics()` that returns the complete OpenMetrics text representation.

2. **`GET /health` enhancement** — the existing endpoint returns `{"status": "ok"}` as the top-level field. A new `checks` field lists each dependency with status, latency, and (for SearXNG) degradation detail. Response is backward-compatible: consumers that only check `status` continue to work unchanged.

3. **`GET /metrics`** — a new unauthenticated endpoint on the agent-svc root (same security model as `/health`) returning OpenMetrics text for Prometheus consumption.

4. **Structured JSON logging** — a middleware that:
   - Generates a `request_id` per request (UUID4)
   - Logs request start, request end (with duration, method, path, status_code)
   - All log records emitted in JSON format with fields: `timestamp`, `level`, `service`, `request_id`, `message`, and optional structured fields (`duration_ms`, `status_code`, `method`, `path`, `url`)

5. **Dependency health probes** — each client class (`ScraperClient`, `SearXNGClient`) gains a `check_health()` method that returns `{"status": "ok"|"degraded"|"down", "latency_ms": N}`. Valkey health is checked via existing `redis.ping()`.

### Key Design Decisions

- **Client-level health, not endpoint-level.** Each client class gets a `check_health()` method. This means the health check tests the client's actual connection (HTTP, TCP, or valkey ping) rather than trying to reach a `/health` endpoint on the downstream service (browser-svc and parse-svc don't expose health endpoints). For HTTP services without health endpoints, we test a lightweight GET to the base URL; for Valkey, we call `PING`.
- **Metrics scoped to agent-svc only.** The issue scope says "health endpoint on agent-svc" — not a distributed health system. scraper-svc, browser-svc, and parse-svc are dependencies of agent-svc; they are probed FROM agent-svc, not independently instrumented.
- **Latency histograms by tier and adapter.** The `scraper_client` and `worker` functions record timing with tier labels (`llms.txt`, `content-negotiation`, `playwright`, `adapter`) for scrape latency, and job type labels for job processing.
- **Request ID via middleware.** The middleware adds `request_id` to `request.state` and skips it for the `/health` and `/metrics` endpoints (to avoid generating noise from pollers).

## Consequences

### Positive
- Operators can detect browser-svc OOMs, SearXNG degradation, and job queue backlogs before users report them.
- Capacity planning is possible from latency histograms and job completion counters.
- Debugging multi-hop flows (agent → scraper → browser) with request_id correlation.
- Zero new infrastructure or dependencies.
- Backward-compatible `/health` response.
- The `/metrics` endpoint is ready for Prometheus scraping immediately when a Prometheus instance is deployed.

### Negative
- No auto-instrumentation — every timed call must be explicitly wrapped. When new endpoints or workers are added, the author must remember to add timing calls (enforceable via code review).
- No distributed tracing — request_id correlation across services requires manual header propagation. Agent-svc would need to pass its request_id to scraper-svc and browser-svc as an HTTP header. This is deferred (not in scope for this ADR).
- Histogram buckets are static (defaults: 0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0, 30.0, 60.0). These may need tuning after observing real traffic patterns.

### Risks
- If the metrics endpoint itself becomes a performance bottleneck (unlikely — it's a static text generation from in-memory dicts), it can be rate-limited or cached with a 5s TTL.
- Request ID generation adds ~0.1µs per request — negligible.

## Links

- [Prometheus OpenMetrics exposition format](https://github.com/OpenObservability/OpenMetrics/blob/main/specification/OpenMetrics.md)
- [Firecrawl v2 API — no health endpoint](https://docs.firecrawl.dev/api-reference/introduction)
- [ADR-0008](0008-three-layer-testing-strategy.md) — testing strategy for new endpoints
