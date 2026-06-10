# How to monitor

GroktoCrawl exposes observability data through structured JSON logging and OpenMetrics-formatted `/metrics` endpoints.

## Logging

All agent-svc logs use structured JSON format with fields: `timestamp`, `level`, `logger`, `message`, and optional `extra_fields` (request_id, method, path, status_code, duration_ms). Log level is controlled by `LOG_LEVEL` env var.

View logs:

```bash
docker compose logs -f agent-svc
docker compose logs -f scraper-svc
docker compose logs -f semantic-svc
```

## Metrics

Both agent-svc (port 8080) and semantic-svc (port 8003) expose `/metrics` endpoints in OpenMetrics format for Prometheus scraping:

```bash
curl http://localhost:8080/metrics
curl http://localhost:8003/metrics
```

Key agent-svc metrics:

| Metric | Type | Description |
|---|---|---|
| `groktocrawl_info` | info | Service version |
| `http_request_duration_seconds` | histogram | Request latency by method and path |
| `scrape_duration_seconds` | histogram | Scrape latency by source tier |
| `scrapes_total` | counter | Total scrapes by tier |
| `jobs_submitted_total` | counter | Jobs by type |
| `jobs_completed_total` | counter | Completed jobs by type |
| `jobs_failed_total` | counter | Failed jobs by type |
| `job_duration_seconds` | histogram | Job duration by type and status |
| `queue_depth` | gauge | Current processing jobs |
| `dependency_health` | gauge | Dependency health (1=ok, 0=down) |

Key semantic-svc metrics:

| Metric | Type | Description |
|---|---|---|
| `groktocrawl_index_docs_total` | gauge | Current document count |
| `groktocrawl_index_evictions_total` | counter | Cumulative evictions |
| `groktocrawl_index_query_duration_seconds` | histogram | Query latency by endpoint |
| `groktocrawl_index_embeddings_duration_seconds` | histogram | Embedding inference duration |

## Health

`GET /health` on agent-svc returns per-dependency probe results for valkey, searxng, scraper, and browser. Each probe reports status (ok/degraded/down), latency, and detail.

## Grafana

A Grafana dashboard for semantic-svc is available at `docs/grafana/semantic-svc-dashboard.json`. Import this into your Grafana instance, pointing the data source at the Prometheus server scraping agent-svc and semantic-svc.
