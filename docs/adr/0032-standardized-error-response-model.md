# Standardized Error Response Model

* Status: accepted
* Deciders: magnus, jasper
* Date: 2026-06-14

Technical Story: Issue #185 — Error handling is inconsistent across API endpoints: some return 200 with `success: false`, others raise `HTTPException`, and worker functions catch broad `Exception` losing stack traces.

## Context and Problem Statement

GroktoCrawl's API surface has grown organically across multiple PRs, resulting in three distinct error-handling patterns:

1. **200 with `success: false`** — `/v2/scrape`, `/v2/parse`, `/v2/map` return HTTP 200 with a `success: false` field and an `error` string
2. **HTTPException** — job-status endpoints raise `HTTPException(404)` for missing resources; browser endpoints raise `HTTPException(502)` for upstream failures
3. **Silent failure** — `_browser_proxy`, `smart_scrape()` broad `except` handlers return degraded responses without logging the root cause

This inconsistency creates problems for API clients (every endpoint needs different error parsing logic), observability (stack traces are lost in broad catch-and-return patterns), and code maintainability (each new endpoint re-decides how to report errors).

## Decision Drivers

* API clients must be able to parse errors uniformly across all endpoints
* Stack traces must be preserved for server-side debugging
* The Firecrawl v2 API contract must remain compatible where possible
* No new dependencies should be introduced
* Both agent-svc and scraper-svc must follow the same pattern

## Considered Options

* **A. Centralized exception hierarchy + FastAPI handlers** — Define a base exception class, subclass per error type, register FastAPI exception handlers that produce a consistent JSON response shape
* **B. Middleware-only approach** — Use a single middleware to catch all exceptions and format them uniformly, no custom exception classes
* **C. Per-endpoint response model** — Every endpoint returns a result object that embeds error information (current state, formalized)

## Decision Outcome

Chosen option: **A. Centralized exception hierarchy + FastAPI handlers**, because it preserves stack traces (exceptions propagate through the normal FastAPI exception pipeline), allows per-type customization of error codes and HTTP status codes, and integrates cleanly with FastAPI's existing exception-handling infrastructure.

### Error Response Shape

All error responses (regardless of HTTP status code) follow this shape:

```json
{
  "success": false,
  "error": "Human-readable description",
  "error_code": "NOT_FOUND",
  "details": {"job_id": "abc-123"}
}
```

### Error Codes

| HTTP | Error Code | When |
|------|-----------|------|
| 400 | `INVALID_REQUEST` | Missing fields, bad input |
| 401/403 | `AUTH_ERROR` | Authentication or authorization failure |
| 404 | `NOT_FOUND` | Resources (jobs, monitors, sessions) not found |
| 422 | `INVALID_REQUEST` | Pydantic validation failures (field-level details array) |
| 429 | `RATE_LIMITED` | Rate limit exceeded |
| 502 | `SCRAPE_FAILED` | Scraper service failure |
| 502 | `BROWSER_ERROR` | Browser service failure |
| 502 | `UPSTREAM_ERROR` | Generic upstream service failure |
| 500 | `INTERNAL_ERROR` | Unhandled exceptions (generic message, logged traceback) |

### Exception Hierarchy

```
GroktoCrawlError (base)
├── NotFoundError (status=404, code=NOT_FOUND)
├── InvalidRequestError (status=400, code=INVALID_REQUEST)
├── ScrapeError (status=502, code=SCRAPE_FAILED)
├── BrowserError (status=502, code=BROWSER_ERROR)
├── UpstreamError (status=502, code=UPSTREAM_ERROR)
└── SearchError (status=502, code=SEARCH_ERROR)
```

### Positive Consequences

* Clients parse a single error shape across all endpoints
* Stack traces are preserved (exceptions propagate normally)
* New endpoints automatically get consistent error handling by raising the right exception
* Validation errors include field-level detail arrays for form-style endpoints

### Negative Consequences

* Existing clients that parse `success: false` from a 200 response must now handle 4xx/5xx HTTP status codes
* One additional import and ~80 lines of exception definitions per service

## Links

- Issue #185: Standardize error handling
- [FastAPI Exception Handling Documentation](https://fastapi.tiangolo.com/tutorial/handling-errors/)
- [Stripe API Error Codes](https://stripe.com/docs/api/errors) (inspiration for string-based error codes)
