# Global Admission Control and End-to-End Cancellation

- Status: accepted
- Deciders: GroktoCrawl maintainers
- Date: 2026-01-15

## Context

GroktoCrawl bounds concurrency inside individual operations — the crawler has
a per-run semaphore, research scraping has a per-call semaphore, the scraper
service caps Playwright lifecycles, and batch scrape was sequential — but those
limits do not compose into a service-wide capacity budget. Multiple agent jobs,
crawls, and batch requests can each create their own fan-out while browser work
converges on a much smaller shared Playwright limit. Background work is tracked
in an unbounded in-process task set rather than admitted through a budget.

Cancellation was also incomplete: changing persisted job state did not reliably
stop active search, scrape, browser, or LLM work, and speculative scrape tasks
were cancelled without always being awaited through cleanup.

This change (issue #531) adds a global weighted admission controller and a real
per-job cancellation signal, while deferring distributed/multi-instance admission
and a full Docker load test.

## Decision

We introduce an in-process, weighted admission controller shared by both the
agent service and the scraper service (`common/admission.py`, wired from
`agent-svc/agent/admission.py` onto `app.state.admission`).

- Three resource classes: `lightweight_fetch`, `browser`, and `llm`, each with a
  service-wide budget from settings (`ADMISSION_LIGHT_FETCH_LIMIT`,
  `ADMISSION_BROWSER_LIMIT`, `ADMISSION_LLM_LIMIT`).
- Each in-flight operation consumes a positive integer weight (fetch=1, llm=4,
  browser=8) so an expensive browser lifecycle is not treated as a cheap HTTP
  fetch. `acquire(resource_class, weight, timeout)` admits immediately when
  capacity is available, otherwise enqueues a bounded FIFO waiter and rejects on
  overflow; `release` returns budget and wakes waiters in FIFO order.
- Per-request semaphores (crawler concurrency, research scrape concurrency, the
  scraper's browser semaphore, batch-scrape scheduling) remain underneath as
  inner caps; the controller is the outer cap across jobs.

Admission is wired into the fan-out paths: `ScraperClient.scrape()`
(`lightweight_fetch` or `browser` by the `force_browser` flag), `LLMClient`
`generate`/`generate_stream` (`llm`), and the scraper's browser tier in
`fetch_tiers.py` (`browser`). Metrics per class are exported with bounded labels:
`admission_active{class}`, `admission_queue_depth{class}`,
`admission_wait_seconds{class}`, `admission_rejected_total{class}`, and
`admission_cancelled_total{class}`.

Cancellation uses a per-job `asyncio.Event` cancel token registered with
`TaskTracker`, propagated through worker → crawler → research/answer/scrape →
scraper-client → llm via a `contextvars.ContextVar`. `DELETE` endpoints set the
token and cancel the owning task. Every safe await boundary checks the token;
cancelled child/speculative tasks are awaited with
`asyncio.gather(..., return_exceptions=True)` so browser/HTTP resources close
deterministically (no "Task was destroyed but it is pending"). Cancelled jobs
record `groktocrawl_jobs_cancelled_total{type}` and never record completed or
failed metrics/webhooks.

The cancellation bound is the next safe await boundary: cooperative checks run
before each network request (search/scrape/LLM), and forced `task.cancel()`
interrupts any in-flight await immediately, so active cancellable operations
exit within in-process task-scheduling granularity (sub-second, and no longer
than the next I/O await).

Batch scrape (`worker._process_batch_scrape_async`) is parallelized with
completion-driven scheduling bounded by `min(max_concurrency,
admission_light_fetch_limit)`, using index-keyed results so `pages`/`errors`
remain in input URL order, preserving per-URL error semantics, progress updates,
and the completed counter.

The same-domain politeness burst is fixed by atomically reserving the
next-available slot under the per-domain lock on the delay path, so N concurrent
same-domain tasks stagger their wake-ups instead of waking together.

## Consequences

- Positive: aggregate work across concurrent jobs cannot exceed documented
  service-wide budgets for lightweight fetch, browser, and LLM classes; admission
  wait, depth, active count, rejection, and cancellation are observable.
- Positive: cancelling a job stops new work and causes active cancellable
  operations to exit promptly, and cancelled speculative tasks are awaited.
- Positive: batch scrape uses available lightweight-fetch capacity efficiently
  within both per-job and global limits.
- Negative: admission is in-process only — it does not coordinate across
  instances (consistent with the rest of the sprint); multi-instance admission is
  deferred. The browser-heavy Docker load test is documented as a follow-up;
  budget bounds are proven in-process with concurrent task stubs.
- Negative: callers must release admission in a `finally` (or use the
  `resource()` context manager) and re-raise `JobCancelledError` above broad
  exception handlers so cancellation is not silently converted into a scrape/LLM
  error result.

## Links

- [ADR-0018 Observability Infrastructure](0018-observability-infrastructure.md)
- [ADR-0047 Defer Restart-Safe Execution](0047-defer-restart-safe-execution.md)
- [ADR-0048 Stage-Level Telemetry](0048-stage-level-telemetry.md)
