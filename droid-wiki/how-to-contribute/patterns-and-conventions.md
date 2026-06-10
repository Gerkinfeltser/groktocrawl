# Patterns and conventions

## Coding style

- Python 3.12+ with type hints throughout
- Async/await for all I/O-bound operations
- FastAPI for all HTTP services
- MIT license

## Service patterns

Each service follows the same pattern:

- `app.py` -- FastAPI application factory with lifespan handlers
- Service dependencies are wired in `create_app()` and stored in `app.state`
- Routes are defined in the same file (scraper-svc, semantic-svc) or in a separate `api.py` (agent-svc)
- Pydantic models for request/response schemas

## Error handling

- Exceptions are logged and returned as structured error responses
- External service failures are handled with try/finally to close HTTP clients
- Background tasks (indexing, webhooks) fail silently -- errors are logged but never propagate

## Dependency injection

Dependencies (HTTP clients, Valkey connections) are created in `create_app()` and stored in `app.state`. Routes access them via `request.app.state.<dependency>`:

```python
scraper: ScraperClient = request.app.state.scraper_client
```

## Testing patterns

Integration tests in `tests/test_stack.py` hit all endpoints against the live Docker stack. Fixture services (search-svc, llm-svc, test-site) provide deterministic behavior. Tests use `wait_for()` to poll health endpoints before proceeding.

Unit tests live alongside the service they test (e.g., `tests/test_politeness.py` for the politeness module).

## ADR workflow

Significant architectural changes require an Architecture Decision Record in `docs/adr/`. See `docs/adr/README.md` for the index and `CONTRIBUTING.md` for the workflow. ADRs are immutable after acceptance -- to change a decision, write a new ADR and update the old one's status.

## Commit conventions

This project uses Conventional Commits:

```
feat: add YouTube adapter
fix: handle empty search results
```

Types: `feat`, `fix`, `refactor`, `docs`, `test`, `ci`, `chore`, `perf`, `style`

Every commit must include a `Signed-off-by` trailer (DCO):

```bash
git commit -s -m "feat: add widget"
```

## Webhook requirement

Any new async endpoint that returns a job ID must accept a `webhook` field and fire it on completion/failure via `deliver_webhook()` in `agent-svc/agent/webhook.py`.

## Metrics

Every service exposes a `/metrics` endpoint in OpenMetrics format for Prometheus. Use the module-level `METRICS` singleton from `metrics.py`:

```python
METRICS.counter("requests_total", "Total requests", ["endpoint"]).inc({"endpoint": "scrape"})
METRICS.histogram("latency_seconds", "Request latency", ["endpoint"]).observe({"endpoint": "search_vector"}, 0.042)
```
