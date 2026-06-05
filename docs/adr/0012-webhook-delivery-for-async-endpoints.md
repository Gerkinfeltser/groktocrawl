# Webhook Delivery for Async Endpoints

* Status: accepted
* Deciders: magnus, jasper
* Date: 2026-06-05

Technical Story: GroktoCrawl has multiple async endpoints (agent, crawl, extract, generate-llmstxt) that return job IDs for polling. Callers needed a way to be notified when their job completes without polling.

## Context and Problem Statement

All async endpoints (`/v2/agent`, `/v2/crawl`, `/v2/extract`, `/v2/generate-llmstxt`) return a job ID. Clients must poll `GET /v2/agent/:id` to learn when work completes. This is wasteful for long-running jobs and breaks automation workflows that need event-driven notification.

## Decision Drivers

* Webhook delivery must be available on ALL async endpoints from day one
* The webhook schema must be consistent across all endpoints
* Must support both `completed` and `failed` event types so callers can handle errors
* Must not introduce a new dependency — use the existing HTTP infrastructure

## Considered Options

* **A. Per-endpoint webhook field** — Each async request accepts an optional `webhook` field with URL + event types. The worker fires a POST on completion or failure.
* **B. Central webhook registry** — Users register webhooks globally, matched by event type.
* **C. Server-Sent Events (SSE)** — Real-time stream of job status changes.

## Decision Outcome

Chosen option: **A. Per-endpoint webhook field**. Every async endpoint accepts:
```json
{
  "webhook": {
    "url": "https://example.com/hooks/groktocrawl",
    "events": ["completed", "failed"]
  }
}
```
On completion or failure, the worker POSTs a JSON payload with job details to the URL. The webhook function lives in `agent/webhook.py` and is called from every async worker.

### Positive Consequences

* Consistent interface across all async endpoints — one pattern to learn
* Self-contained — the webhook URL travels with the request, no global state
* Works with any HTTP endpoint (n8n, Zapier, custom handlers)

### Negative Consequences

* No retry mechanism in v1 — if the webhook POST fails, the event is lost
* No webhook signing/verification (HMAC) in v1 — callers should validate on their end

## Links

* Implemented by PR #10
* Defined by `agent/webhook.py` and `agent/models.py`
