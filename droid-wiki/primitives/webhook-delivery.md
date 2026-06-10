# Webhook delivery

Active contributors: groktopus

## Purpose

The webhook system delivers asynchronous job completion and failure notifications to external URLs. It supports HMAC-SHA256 signing, event filtering, and exponential backoff retries.

## How it works

### Delivery flow

1. After `store.complete_job()` or `store.fail_job()`, the worker calls `deliver_webhook()`
2. The function checks if a webhook URL is configured and if the event matches the filter
3. A JSON payload with `event`, `id`, and `data` fields is POSTed to the URL
4. The webhook secret (from `WEBHOOK_SECRET` env var) is used for HMAC-SHA256 signing, sent as `X-Webhook-Signature` header

### Retry logic

- Up to 3 attempts
- Exponential backoff: 2s, 4s
- 5 second timeout per attempt
- Server errors (500+) and timeouts trigger retries

### Event filtering

Webhook configs can include an `events` list. When provided, the webhook only fires for matching event types. Example:

```json
{"url": "https://example.com/hook", "events": ["completed"]}
```

## Key source files

| File | Purpose |
|---|---|
| `agent-svc/agent/webhook.py` | `deliver_webhook()` function |
