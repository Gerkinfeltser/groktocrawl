# Metrics

Active contributors: groktopus

## Purpose

The metrics system provides in-memory counter, histogram, and gauge primitives with OpenMetrics text export for Prometheus consumption. It has zero external dependencies -- the collector is built from Python stdlib types.

## Architecture

The `MetricsCollector` singleton (`METRICS`) is a registry that manages thread-safe metric instances:

- `_SafeCounter` -- increment-only counter with optional label dimensions
- `_SafeHistogram` -- bucketed histogram with configurable buckets (default 16 buckets from 5ms to 60s)
- `_SafeGauge` -- set/inc/dec gauge

All primitives use `threading.Lock` for thread safety.

## Endpoints

Both agent-svc and semantic-svc expose `/metrics` endpoints:

- `GET /metrics` on agent-svc (port 8080) -- job counters, scrape latency, queue depth, dependency health
- `GET /metrics` on semantic-svc (port 8003) -- document count, eviction count, request latency per endpoint, embedding duration

## Metrics in agent-svc

| Metric | Type | Labels |
|---|---|---|
| `groktocrawl_info` | info | version |
| `http_request_duration_seconds` | histogram | method, path |
| `scrape_duration_seconds` | histogram | tier |
| `scrapes_total` | counter | tier |
| `jobs_submitted_total` | counter | type |
| `jobs_completed_total` | counter | type |
| `jobs_failed_total` | counter | type |
| `job_duration_seconds` | histogram | type, status |
| `queue_depth` | gauge | -- |
| `dependency_health` | gauge | dependency |

## Key source files

| File | Purpose |
|---|---|
| `agent-svc/agent/metrics.py` | MetricsCollector for agent-svc |
| `semantic-svc/metrics.py` | MetricsCollector for semantic-svc (duplicated) |
