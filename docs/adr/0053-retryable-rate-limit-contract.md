# Retryable Rate-Limit Contract

- Status: accepted
- Deciders: GroktoCrawl maintainers
- Date: 2026-08-15

## Context

GroktoCrawl returns HTTP 429 `RATE_LIMITED` when a per-client request budget is
exhausted, but the response carried no way for a client to distinguish a
temporary capacity condition from a failed operation: the server rejected
admission with a bare error body, and the CLI converted every such response into
a generic exit-1 failure. A live benchmark surfaced 24 apparent operation
failures that were actually rate-limit rejections, polluting latency
distributions and misleading operators.

Accepted asynchronous jobs had the same gap in the other direction: a
rate-limit condition encountered by a worker after admission (e.g. SlopSearX
answering 429) was swallowed into empty results or turned into a terminal
failure, even though the condition is temporary by definition.

The spec `docs/specs/retryable-rate-limit-behavior.spec.md` defines the target
behavior; this ADR records the implementation decisions.

## Decision

### 1. Admission-time 429 responses carry retry metadata

The existing `RateLimitedError` (HTTP 429, `error_code: RATE_LIMITED`) gains
optional `retry_after_seconds`, `bucket`, `limit`, `remaining`, and `reset_at`
metadata. The FastAPI exception handler renders, for rate-limit errors that
carry a retry delay:

- Body fields: `retryable: true` and `retry_after_seconds` (whole seconds),
  plus `details.bucket` / `details.limit` / `details.remaining` /
  `details.reset_at`. `bucket` is a stable non-secret identifier (`search` or
  `crawl`), never the client IP.
- Headers: `Retry-After`, `RateLimit-Limit`, `RateLimit-Remaining`,
  `RateLimit-Reset` (delta seconds).

`retryable` is emitted only together with a positive `retry_after_seconds`;
rate-limit-shaped errors without metadata keep the legacy body shape. The
existing `X-Search-Rate-Remaining` / `X-Crawl-Rate-Remaining` success headers
are unchanged. The limiter's fixed-window bucket key (`now // window`) makes the
reset derivable as `window - (now % window)`, exposed as
`SlidingWindowRateLimiter.retry_after_seconds()`.

Rejection still happens before `create_job()`, so a rate-limited admission
never creates a job record and never increments `jobs_failed_total`.

### 2. CLI retries only definitively rejected 429 RATE_LIMITED responses

The `groktocrawl` CLI applies a bounded retry policy to `answer`, `agent`, and
`crawl` requests only. Eligibility is strict: HTTP 429 **and** the normalized
`error_code: RATE_LIMITED`. Ambiguous outcomes, network errors, and all other
status codes are never retried — the server contract guarantees a rejected
admission created no job, so retrying cannot duplicate work.

Policy (documented defaults, overridable via `GROKTOCRAWL_RETRY_MAX_ATTEMPTS`,
`GROKTOCRAWL_RETRY_MAX_WAIT_SECONDS`, `GROKTOCRAWL_RETRY_FALLBACK_SECONDS`):

- Maximum total attempts: 3 (initial attempt plus at most 2 retries).
- Server-provided delay takes precedence (`retry_after_seconds` body field,
  then `Retry-After` header), clamped to `[1, 60]` seconds.
- Fallback: bounded exponential backoff `fallback * 2^(attempt-1)` plus jitter
  (uniform 0–0.5s), never below 1s (so `Retry-After: 0` cannot become a hot
  loop) and never above 60s.

Retry progress is emitted on stderr only (`Rate limited (<operation>):
retrying in Ns (attempt X/Y)`), so `--json` stdout stays valid JSON. Exhaustion
raises a structured `RetryExhaustedError` (final status, attempts made, last
retry delay) that exits nonzero and never describes the operation as failed or
completed. Interruption during a retry sleep exits promptly without another
attempt. The two SSE entry points (`create_agent_stream`, streaming
`answer`) apply the same policy before the stream is opened.

### 3. Job-time retry state for accepted jobs

Downstream HTTP 429 `RATE_LIMITED` responses are classified at a single point:
`SearXNGClient.search()` raises `RetryableRateLimitError` (a `RateLimitedError`
subclass carrying the upstream `Retry-After`) when SlopSearX answers 429. The
per-request search-budget guard (`Search budget exceeded`) is **not**
retryable — it is a local safety bound, not a server capacity signal. The
research discovery and plan-execution call sites re-raise the classified error
instead of swallowing it into empty results, so a whole-job capacity condition
is visible to the worker.

`JobStore` gains two non-terminal transitions:

- `schedule_retry()`: `processing` → `retry_scheduled`, storing `retry_at`,
  `retry_attempt`, `retry_limit`, `retry_reason`, `retry_after_seconds` on the
  job meta (exposed by `GET /v2/agent/{id}` and `GET /v2/crawl/{id}`).
- `resume_retry()`: `retry_scheduled` → `processing`, claimed only by the
  job's single owning task, so at most one retry is ever claimed.

`fail_job()` and `cancel_job()` accept transitions from `retry_scheduled` too,
so exhaustion fails terminally and `DELETE` cancels a waiting retry.

The worker's `_run_job_with_observability` scaffolding (shared by agent,
extract, llmstxt, plan-execute, and batch-scrape jobs) wraps `work_fn` in a
retry loop:

1. `work_fn` raises `RetryableRateLimitError` with budget remaining →
   `schedule_retry`, fire the non-terminal `retry_scheduled` webhook (existing
   envelope, events filter, HMAC signing), increment
   `job_retries_scheduled_total`, sleep the bounded delay (cancellable via the
   job cancel token and task cancellation), `resume_retry`, try again.
2. Budget exhausted → terminal `failed` with a structured error naming
   `RATE_LIMITED`, the attempts made, and the last retry delay; increments
   `job_retry_exhaustion_total` and `jobs_failed_total` exactly once each.
3. Success after one or more retries → `job_retries_succeeded_total` and the
   normal `completed` path.

Job-time retry applies to jobs whose whole operation can be retried
idempotently (agent research is the concrete case). Crawl and batch-scrape jobs
keep per-page error semantics: a 429 on one page is a page-level error, and the
whole crawl is never retried (that would amplify load).

### 4. Metrics and logs separate throttling from failure

New counters with operation-type labels:

- `rate_limited_admissions_total{operation, bucket}` — admission rejections
  (before job creation).
- `job_retries_scheduled_total{type}` — job-time retries scheduled.
- `job_retries_succeeded_total{type}` — jobs completed after ≥1 retry.
- `job_retry_exhaustion_total{type}` — retry budget exhausted.

`jobs_failed_total` continues to count only terminal failures; rejected
admissions and jobs waiting in `retry_scheduled` never increment it. Structured
logs include operation, bucket, retry attempt, retry delay, and whether the
condition was admission-time or job-time — never client IPs, credentials, or
prompts.

### 5. Benchmark classification

`benchmarks/run_benchmarks.py` runners may return a `Sample(latency, status,
retry_class)` per iteration (bare floats remain supported). Samples classified
`retry_class == "rate_limited"` are excluded from p50/p95 latency
distributions and reported through `status_counts` / `retry_class_counts`, so
throttling is never mistaken for operation latency.

### 6. Restart-safety boundary

Scheduled retries are held in the job meta and resumed only by the owning
in-process task. A process restart while a job is `retry_scheduled` leaves the
job in that state until TTL expiry — no durable retry ownership is claimed.
This is consistent with ADR-0047 (defer restart-safe execution) and the spec's
explicit out-of-scope carve-out.

## Consequences

Positive:

- Clients distinguish temporary throttling from failure via status, headers,
  and body; the CLI absorbs normal bursts with bounded, visible retries.
- Accepted jobs surface retryable conditions instead of failing or silently
  degrading; cancellation and exhaustion behave deterministically.
- Operators get separate counters for admissions, schedules, successes, and
  exhaustion.

Negative / limitations:

- Mid-stream SSE downstream 429s still terminate the stream (retry applies at
  admission and to sync/job-store paths only).
- A restart can lose a scheduled retry (documented boundary, ADR-0047).
- Job-time retry does not cover whole-crawl retries; per-page 429s remain page
  errors.

## Alternatives considered

- **Client-side retry for all statuses with backoff** — rejected: retrying
  ambiguous outcomes can duplicate work; eligibility is deliberately strict.
- **A distributed retry queue** — rejected for this iteration: requires job
  ownership, leases, and durability design per ADR-0047; the inline task retry
  covers the documented scope.
- **Renaming failure to retry without store support** — rejected: the spec
  forbids claiming US-003 through a superficial status rename; the store
  transitions and worker loop are implemented.

## Links

- Spec: [docs/specs/retryable-rate-limit-behavior.spec.md](../specs/retryable-rate-limit-behavior.spec.md)
- ADR-0047: [Defer Restart-Safe Execution](0047-defer-restart-safe-execution.md)
- ADR-0032: [Standardized Error Response Model](0032-standardized-error-response-model.md)
