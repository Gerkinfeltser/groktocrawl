# Agent SSE Streaming — Real-Time Research for Interactive Clients

* Status: proposed
* Deciders: magnus, jasper
* Date: 2026-06-08

Technical Story: The agent endpoint (`POST /v2/agent`) currently uses an async create-job→poll pattern. Interactive clients (web portal, CLI) need real-time progress visibility and token streaming during deep research.

## Context and Problem Statement

GroktoCrawl has two research-oriented endpoints:

| Endpoint | Pattern | Latency | Use Case |
|---|---|---|---|
| `POST /v2/answer` | Sync inline + SSE streaming | 1-5s | Single-turn Q&A, fast path |
| `POST /v2/agent` | Async create→poll | 5-30s+ | Multi-source deep research |

The agent endpoint returns a job ID, processes research in a background task (`asyncio.create_task`), and writes results to Valkey. The client polls `GET /v2/agent/{job_id}` until completion.

This works for programmatic clients (curl, agent tools) but creates a poor experience for:

- **Web portal users** who see a blank screen while the agent researches for 15-30 seconds
- **CLI users** who see only a spinner with no visibility into what sources are being consulted
- **Chat UI integrations** that want to stream the answer token by token as it's generated

The `answer` endpoint already solves the same problem with SSE streaming (see ADR-0017). The agent endpoint needs the same capability.

## Decision Drivers

- Must provide **real-time progress visibility** during the discovery phase (what URLs are being scraped)
- Must **stream tokens** during the synthesis phase (LLM generation)
- Must **reuse the SSE event protocol** established by the `answer` endpoint — no new streaming mechanism
- Must **preserve backward compatibility** — existing clients that don't set `stream: true` get the current create→poll behavior unchanged
- Must support all existing agent features: seed URLs, schema-based structured output, model override
- Must not require new infrastructure dependencies

## Considered Options

### A. Inline SSE streaming — chosen

Run the research loop inline in the route handler when `stream: true`, wrapping the generator in FastAPI's `StreamingResponse`. Reuse the two-phase event schema from the `answer` endpoint with one addition: intermediate `source_scraped` events during discovery.

**Architecture:**
```
POST /v2/agent { stream: true }
  → create_agent() checks body.stream
  → run_research_stream() inline (no background task)
    → Phase 1: search → scrape, yielding source_scraped events
    → Phase 2: llm.generate_stream(), yielding token events
    → Final: done event with result + sources + latency
  → StreamingResponse(event_stream(), media_type="text/event-stream")
```

**Positive:**

- Matches the proven `answer` endpoint pattern (ADR-0017) exactly
- No new infrastructure (no pub/sub, no Valkey channels, no WebSocket manager)
- Client sees progress in real time — sources appearing, then tokens streaming
- Simple implementation: `run_research_stream()` parallels `run_answer_stream()`
- Backward compatible: `stream` defaults to `false`
- Same LLM client — `generate_stream()` already exists and is tested

**Negative:**

- Ties up the HTTP connection for the duration of the research loop (5-30s+)
- No retry mechanism — if the connection drops mid-stream, progress is lost
- Not suitable for very long-running research (minutes); the current create→poll pattern remains available for those cases via `--sync`

### B. Valkey pub/sub bridge

The background task publishes events to a Valkey channel. The SSE handler subscribes to the channel and relays events to the client.

**Positive:**

- Decouples processing from HTTP delivery
- Survives connection drops with reconnection logic
- Scales to multiple listeners per job

**Negative:**

- Adds significant infrastructure complexity (pub/sub channels, message serialization, reconnect logic)
- Valkey bridge itself can fail, adding a new failure mode
- No immediate benefit — the research loop already runs inside the API process (no separate worker)
- Over-engineering for the current deployment scale

### C. WebSocket endpoint

Add a WebSocket endpoint `/v2/agent/ws/{job_id}` that streams events.

**Positive:**

- Native bidirectional streaming
- Standard reconnection semantics
- Well-suited for long-lived connections

**Negative:**

- Breaks from the REST-only API surface (all other endpoints are HTTP)
- Requires WebSocket connection management and lifecycle handling
- Not compatible with simple curl/httpx consumption
- Web portal would need a separate WebSocket client library

## Decision Outcome

Chose option A (inline SSE streaming) because it:
1. Reuses an established and tested pattern (the `answer` endpoint's SSE implementation)
2. Requires no new infrastructure dependencies
3. Preserves full backward compatibility
4. Is simpler to implement, review, and maintain

The create→poll pattern remains available for clients that prefer it, via the `--sync` CLI flag or by omitting `stream: true` in the API call.

### Event Schema

```
Phase 1 — Discovery (search → scrape):
  sources_pending  →  {sources: [{url, title, relevance}]}  — search results found
  source_scraped   →  {url, source, chars}                   — each URL scraped

Phase 2 — Synthesis (LLM):
  sources          →  {sources: [url, ...]}                   — final source list
  token            →  {content: "..."}                        — individual LLM token
  done             →  {result, sources, latency_ms}           — final answer

  error            →  {content: "..."}                        — any phase
```

When `schema` is provided (structured JSON output), Phase 2 delivers the full response in a single `done` event rather than streaming tokens — structured JSON output does not benefit from token-level streaming.

### CLI Default

The `groktocrawl agent` command uses streaming by default, with `--sync` to opt out of streaming and fall back to the create→poll pattern. This mirrors the existing `groktocrawl answer` default (ADR-0017, v1.5.1).

### Consequences

**Positive:**

- Web portal users see sources appear as they're discovered, then the answer streaming in real time
- CLI users see the same live progress — URL scraping and answer generation visible immediately
- The `answer` and `agent` endpoints now have parallel streaming interfaces
- Integration test surface grows by one test case (modeled on `test_answer_streaming_returns_sse_events`)

**Negative:**

- The agent's `SYSTEM_PROMPT` (68 lines) is much richer than `ANSWER_SYSTEM_PROMPT` (10 lines) — the streaming LLM call uses the same prompt unchanged, but the token stream is longer
- HTTP connection held for the full research duration — long-running research (60s+) should use `--sync` instead
- Schema-based (structured JSON) requests don't get token-level streaming — the full JSON arrives in a single `done` event

## Links

- [ADR-0017: Grounded Q&A Endpoint](0017-grounded-qa-endpoint.md) — establishes the SSE streaming pattern and event schema
- [ADR-0012: Webhook Delivery for Async Endpoints](0012-webhook-delivery-for-async-endpoints.md) — the background-task pattern this complements
- Issue [#130: feat: add SSE streaming support to the agent endpoint](https://github.com/groktopus/groktocrawl/issues/130)
