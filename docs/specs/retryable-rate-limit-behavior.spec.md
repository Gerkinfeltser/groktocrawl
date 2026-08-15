# Specification: Retryable Rate-Limit Behavior

## Status

- **Author:** Jasper
- **Version:** 0.1.0
- **Status:** Implemented — awaiting verification gate
- **Reviewed by:** Droid implementation agent (2026-08-15)
- **Gate verdict:** Pending — implementation complete; deterministic unit/service tests cover the applicable ACs (see docs/adr/0053-retryable-rate-limit-contract.md)
- **Date:** 2026-08-15

## Problem Statement

GroktoCrawl currently returns HTTP 429 `RATE_LIMITED` when a per-client request budget is exhausted. The server rejects admission before creating a job, but the CLI converts the response into a generic exit-1 failure. A temporary capacity condition is therefore presented as if the requested search, answer, crawl, or research operation failed. Accepted asynchronous jobs also need an explicit retry state if a downstream rate-limit condition occurs after admission.

The current default is 10 requests per 60 seconds. `/v2/agent` and `/v2/answer` share the `client_ip:search` bucket. `/v2/crawl` uses the separate `client_ip:crawl` bucket. The live benchmark demonstrated 24 apparent failures that were rate-limit rejections, not operation failures.

## Success Criteria

1. A client can distinguish temporary rate limiting from permanent operation failure using status, headers, and the error body.
2. The CLI automatically performs bounded, observable retries for definitively rejected, retryable rate-limit responses.
3. A rate-limited request rejected before admission never creates a failed job record.
4. A rate-limited condition encountered by an already accepted asynchronous job is represented as retryable job state and event data, not an immediate terminal failure.
5. Tests can verify retry timing, exhaustion, job state, event delivery, and metrics without waiting real 60-second windows.
6. Benchmark and operational metrics distinguish rate-limited requests from failed operations.

## Scope

### In Scope

- Standard retry metadata on HTTP 429 `RATE_LIMITED` responses.
- A machine-readable retryable error contract.
- CLI handling for rate-limited `answer`, `agent`, and `crawl` requests, with shared client behavior where appropriate.
- Bounded exponential/backoff retry behavior with server-provided delay taking precedence.
- Retry state and retry events for rate-limit conditions after an asynchronous job has been accepted.
- Metrics and logs that separate rate limiting, scheduled retries, exhausted retries, and terminal failures.
- Deterministic unit, route, CLI, and integration tests using fake clocks or injected limiter behavior.
- Documentation of the contract and client behavior.

### Out of Scope

- Removing or weakening rate limits.
- Changing the default rate-limit policy from `10/60s`.
- Per-user quota billing, subscription tiers, or quota-management UI.
- Retrying arbitrary network errors, authentication failures, validation errors, or unknown POST outcomes.
- Retrying non-rate-limit upstream failures unless they already have a separate explicit retry contract.
- Replacing the current Valkey-backed limiter implementation.
- Solving the unrelated GitHub crawl page-limit behavior.
- Reworking the entire job durability model or making jobs restart-safe after process loss.

## User Stories

### US-001: Understand a rate-limit response

**Priority:** P0

**Description:** As an API client, I want a rate-limit response to identify itself as temporary and tell me when to retry so that I can back off instead of reporting a false operation failure.

**Acceptance Criteria:**

1. [AC-001.1] Given an admission request exceeds its per-client rate limit, when the route rejects it, then the response status is HTTP 429 and the JSON body contains `success: false`, `error_code: "RATE_LIMITED"`, `retryable: true`, and a positive `retry_after_seconds` value.
2. [AC-001.2] Given the same response, then it includes `Retry-After` with a delay in whole seconds and standard `RateLimit-Limit`, `RateLimit-Remaining`, and `RateLimit-Reset` headers.
3. [AC-001.3] Given an admission request is rejected with HTTP 429, then no job record is created and no `jobs_failed_total` increment is emitted for that request.
4. [AC-001.4] Given the response is rate limited, then existing GroktoCrawl-specific headers such as `X-Search-Rate-Remaining` and `X-Crawl-Rate-Remaining` remain backward-compatible when they are currently emitted.

**Edge Cases:**

- The remaining count is already zero.
- The request arrives immediately before a fixed-window boundary.
- The limiter backend is unavailable and the limiter fails open; the request must not be labeled rate limited merely because the limiter could not be checked.
- A proxy supplies multiple `X-Forwarded-For` values; the existing client-IP identity rule remains authoritative.
- A caller receives a 429 without `Retry-After` from an older deployment; the client uses its bounded fallback delay.

### US-002: Retry safely from the CLI

**Priority:** P0

**Description:** As a CLI user, I want GroktoCrawl to retry a temporary rate-limit response visibly and within a bound so that normal bursts do not look like failed research or scraping.

**Acceptance Criteria:**

1. [AC-002.1] Given `answer`, `agent`, or `crawl` receives HTTP 429 with `error_code: RATE_LIMITED`, when the CLI has retry budget remaining, then it waits for the server-provided delay and retries the same request.
2. [AC-002.2] Given a retry is pending, then the CLI emits a human-readable message containing the operation, retry delay, current attempt, and maximum attempt count. The message goes to stderr so machine-readable stdout remains valid.
3. [AC-002.3] Given a rate-limited request is definitively rejected before admission, then retrying it does not create duplicate jobs.
4. [AC-002.4] Given the retry budget is exhausted, then the CLI exits nonzero and emits a structured retryable error containing the final status, attempts made, and last known retry delay. It must not describe the underlying operation as successfully failed or completed.
5. [AC-002.5] Given a non-429 response such as 400, 401, 404, 422, 502, or a successful response, then the CLI does not apply this rate-limit retry policy.
6. [AC-002.6] Given `--json` is active, then retry progress is emitted only on stderr and the final stdout remains valid JSON.
7. [AC-002.7] Given the response lacks retry metadata, then the CLI uses a bounded fallback delay and still stops after the configured retry budget.

**Edge Cases:**

- The server says `Retry-After: 0`; the client applies a minimum delay plus jitter rather than a hot loop.
- The server supplies an invalid, negative, or excessively large delay; the client clamps it to the configured maximum.
- The process receives interruption while sleeping; it exits promptly without creating another attempt.
- A retry succeeds after one or more 429 responses; the final command exit status is zero.
- A retry receives a different non-429 error; the non-429 error contract takes precedence.

### US-003: Represent retryable conditions in accepted jobs

**Priority:** P1

**Description:** As a job consumer, I want a rate-limited job to be visibly waiting and retrying rather than terminally failed so that I can distinguish temporary capacity from unsuccessful work.

**Acceptance Criteria:**

1. [AC-003.1] Given an asynchronous job has already been accepted and a downstream operation returns a classified rate-limit error, when the worker handles it, then the job enters `retry_scheduled` or an explicitly equivalent non-terminal state.
2. [AC-003.2] Given a job is in `retry_scheduled`, then its status response exposes `retry_at`, `retry_attempt`, `retry_limit`, `retryable: true`, and the normalized reason `RATE_LIMITED`.
3. [AC-003.3] Given a job is in `retry_scheduled`, then it is not counted as terminally failed and does not emit the terminal failure event.
4. [AC-003.4] Given the scheduled retry time arrives and retry budget remains, then the worker attempts the blocked operation again without creating a second job ID.
5. [AC-003.5] Given the retry budget is exhausted, then the job enters terminal `failed` with an error that identifies rate-limit exhaustion, the attempts made, and the last retry delay.
6. [AC-003.6] Given a job is cancelled while `retry_scheduled`, then it enters `cancelled` and no further retry starts.

**Edge Cases:**

- The process restarts while a job is `retry_scheduled`; follow the existing restart-safety contract and do not claim durable recovery unless implemented explicitly in this feature.
- A downstream response has HTTP 429 but no parseable body.
- A downstream component returns the normalized `RATE_LIMITED` code without an HTTP status.
- The job reaches its retry time while the worker is at capacity.
- Two workers observe the same retryable job; only one retry may be claimed.

### US-004: Observe throttling separately from failure

**Priority:** P1

**Description:** As an operator, I want rate limiting and retry exhaustion separated from ordinary failures so that alerts and performance reports describe the system accurately.

**Acceptance Criteria:**

1. [AC-004.1] The service exposes counters for admission rate limits, retry schedules, retry successes, and retry exhaustion, with operation type labels.
2. [AC-004.2] Terminal failure metrics exclude requests rejected before admission and jobs currently waiting to retry.
3. [AC-004.3] Structured logs for rate limiting include operation, limiter bucket, retry attempt, retry delay, and whether the condition was admission-time or job-time, without credentials or full prompts.
4. [AC-004.4] The CLI benchmark can record HTTP status and retry classification per iteration so rate-limited samples are not mixed into operation-latency distributions.

**Edge Cases:**

- Metrics backend is unavailable; request/job behavior remains correct.
- A retry succeeds; both the retry-scheduled and retry-success counters are incremented exactly once.
- A job exhausts retries; retry exhaustion and terminal failure are both represented without double-counting the original rate-limit event.
- Multiple operation types share a limiter bucket; metrics retain both operation and bucket labels.

## Proposed Retry Policy

The implementation must make these values constants or configuration with documented defaults:

| Setting | Default | Rule |
|---|---:|---|
| Maximum total attempts | 3 | Initial attempt plus at most 2 retries |
| Maximum server-specified wait | 60 s | Clamp untrusted or excessive `Retry-After` values |
| Fallback delay | 1 s | Used when retry metadata is absent or invalid |
| Backoff | exponential with jitter | Server-provided delay takes precedence; otherwise increase bounded fallback delay |
| Retry eligibility | `429` plus normalized `RATE_LIMITED` | Do not retry unrelated errors |

The implementation must not retry a request whose outcome is ambiguous after the server may have accepted it. This feature may retry a definitively rejected admission response because the server contract guarantees that no job was created.

## Edge Cases

The implementation and tests must explicitly cover these cross-cutting cases in addition to the story-specific edge cases above:

- Admission rejected before job creation versus downstream rate limiting after job creation.
- Missing, malformed, zero, negative, or excessive `Retry-After` values.
- Fixed-window boundary rollover and a limiter backend that fails open.
- Shared `client_ip:search` budget consumed by mixed agent and answer requests.
- Separate `client_ip:crawl` budget consumed by crawl requests.
- Retry success after one or more 429 responses.
- Retry exhaustion after the maximum attempt count.
- Interruption or cancellation while waiting to retry.
- A different non-429 error after a rate-limit retry.
- Duplicate-submission risk when an admission response is ambiguous, which must not be retried by this feature.
- Job cancellation while `retry_scheduled`.
- Process restart while a retry is scheduled, under the existing restart-safety limitation.
- Valid machine-readable JSON output while human retry progress is emitted on stderr.
- Metrics and logs that must not expose client IPs, credentials, full prompts, or private deployment identifiers.

## Non-Functional Requirements

| ID | Requirement | Threshold | Verification Method |
|---|---|---|---|
| NFR-001 | Retry safety | No duplicate job ID is created by retries of a definitively rejected admission request | Route and CLI integration tests |
| NFR-002 | Retry boundedness | No command performs more than 3 total attempts; no individual wait exceeds 60 s by default | Deterministic fake-clock tests |
| NFR-003 | Machine-readable output | `--json` stdout remains valid JSON during retries and after success/exhaustion | CLI subprocess tests |
| NFR-004 | User feedback | Every actual wait produces one stderr retry message with delay and attempt number | CLI capture test |
| NFR-005 | Contract compatibility | Existing HTTP 429 status, `RATE_LIMITED` code, and existing response fields remain accepted by current clients | API compatibility tests |
| NFR-006 | Observability | Admission limits, scheduled retries, retry successes, and exhausted retries are separately countable | Metrics and log assertions |
| NFR-007 | Security | Retry metadata and logs contain no API keys, authorization values, full prompts, or private deployment identifiers | Response/log redaction tests |
| NFR-008 | Rate-limit integrity | Automatic retries must honor `Retry-After` and must not retry in a tight loop | Fake-clock and request-count tests |

## Data Contracts & Interfaces

### Admission-time HTTP 429 response

```json
{
  "success": false,
  "error": "Request temporarily deferred because client capacity is exhausted",
  "error_code": "RATE_LIMITED",
  "retryable": true,
  "retry_after_seconds": 37,
  "details": {
    "bucket": "search",
    "limit": 10,
    "remaining": 0,
    "reset_at": "2026-08-15T16:01:00Z"
  }
}
```

`details.bucket` must use a stable non-secret identifier such as `search` or `crawl`, not the client IP. `reset_at` may be omitted if the deployment cannot derive it, but `retry_after_seconds` must be present for newly emitted responses.

### HTTP headers

Required on newly emitted 429 responses:

```http
Retry-After: 37
RateLimit-Limit: 10
RateLimit-Remaining: 0
RateLimit-Reset: 37
```

Existing `X-Search-Rate-Remaining` and `X-Crawl-Rate-Remaining` headers remain supported for compatibility. The implementation must not expose the limiter key or client IP.

### Retryable job status

```json
{
  "success": true,
  "status": "retry_scheduled",
  "data": null,
  "error": {
    "code": "RATE_LIMITED",
    "message": "Downstream search capacity is temporarily exhausted",
    "retryable": true,
    "retry_at": "2026-08-15T16:01:00Z",
    "retry_attempt": 1,
    "retry_limit": 3,
    "retry_after_seconds": 37
  }
}
```

The exact existing status envelope may be preserved if these fields are added without breaking current consumers. The coding agent must update the authoritative Pydantic/OpenAPI models rather than inventing an undocumented parallel response shape.

### Retry event / webhook

```json
{
  "event": "retry_scheduled",
  "job_id": "job_123",
  "operation": "agent",
  "reason_code": "RATE_LIMITED",
  "retry_attempt": 1,
  "retry_limit": 3,
  "retry_at": "2026-08-15T16:01:00Z",
  "retry_after_seconds": 37
}
```

`retry_scheduled` is non-terminal. Existing `completed`, `failed`, and `cancelled` events retain their terminal semantics. Retry event delivery must follow the existing webhook validation, signing, and best-effort delivery contract.

## Implementation Constraints

- Preserve the existing HTTP 429 status and `RATE_LIMITED` error code.
- Do not patch installed source; implement in the repository and follow its normal test/PR workflow.
- Use the existing `ApiError.status_code` and structured error body in the CLI rather than parsing human-readable error strings.
- Keep rate-limit identity semantics unchanged in this feature: the current server uses client IP and the agent/answer routes intentionally share `client_ip:search`.
- Do not silently increase production limits to make the benchmark pass.
- Do not use real 60-second sleeps in unit or integration tests; inject a clock, limiter, or retry-delay provider.
- Do not call rate-limited admission responses failed jobs; they are rejected before job creation.
- If the implementation finds that downstream worker retry semantics require a larger job-store or task-ownership change, stop at the boundary, document the gap, and do not claim US-003 is implemented through a superficial status rename.

## Test Plan

### Unit tests

- Parse valid and invalid `Retry-After` values.
- Clamp negative, zero, malformed, and excessive retry delays.
- Compute bounded exponential backoff with deterministic injected jitter.
- Classify only HTTP 429 / `RATE_LIMITED` as eligible.
- Preserve JSON stdout and route retry messages to stderr.

### Route/API tests

- Exhaust a fake limiter and assert 429 body, headers, and no job record.
- Assert agent and answer share the search bucket while crawl uses its separate bucket.
- Assert retry metadata does not expose client IP or credentials.
- Assert OpenAPI models include newly documented response fields.

### CLI integration tests

- First attempt 429, second attempt success: exit 0, exactly two requests, one retry message.
- Three consecutive 429 responses: exit nonzero, exactly three requests, structured retryable final error.
- Non-429 error: one request, no retry.
- `--json`: parse stdout as JSON despite retry messages on stderr.
- Admission 429 followed by success: exactly one created job ID.

### Job integration tests

- Accepted job receives a downstream rate-limit signal: status becomes `retry_scheduled`, then returns to processing and eventually completes.
- Retry budget exhaustion produces terminal failed state with `RATE_LIMITED` exhaustion details.
- Cancellation during retry wait prevents the next attempt.
- Retry events are emitted once per scheduled attempt and terminal events retain existing semantics.

## Assumptions & Open Questions

| # | Assumption / Question | Impact if Wrong | Resolution |
|---|---|---|---|
| 1 | A 429 admission response guarantees that no job was created | Automatic retry could duplicate work if the server accepted then lost the response | Preserve this invariant in route tests and document it in the API contract |
| 2 | The existing webhook event envelope can carry `retry_scheduled` | A new webhook version or consumer migration may be needed | Inspect the authoritative webhook model during implementation; update OpenAPI if needed |
| 3 | Three total attempts is an acceptable default | Users may wait longer or give up sooner than desired | Make the policy configurable or record a follow-up decision before merge |
| 4 | `Retry-After` should describe the fixed-window reset delay | A true rolling-window limiter would require different reset calculation | Derive it from the deployed limiter semantics; do not call the current fixed bucket sliding without evidence |
| 5 | Agent and answer sharing one client-IP bucket is intentional | They may starve each other during normal use | Preserve for this feature; file a separate quota-isolation decision if product intent differs |
| 6 | Downstream rate-limit exceptions are distinguishable from terminal upstream failures | Retrying the wrong errors could amplify load or duplicate side effects | Require explicit normalized `RATE_LIMITED` classification in worker tests |
| 7 | Job retry persistence across process restart remains out of scope | A scheduled retry could be lost during restart | Keep the existing restart-safety limitation visible; do not claim durable retry ownership |

## Acceptance Summary

The implementation is ready for verification only when every applicable AC has a deterministic PASS/FAIL result, the HTTP and CLI contracts are documented, rate-limited admission is not counted as a failed job, and the test suite proves bounded retry behavior without real-time waits.

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1.0 | 2026-08-15 | Jasper | Initial source-grounded specification from live benchmark and repository inspection |
