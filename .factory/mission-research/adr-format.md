# ADR Format Report — GroktoCrawl

## 1. Numbering Scheme

- **Format:** `NNNN-title-with-dashes.md`
- **NNNN:** 4-digit zero-padded sequential number (0001, 0002, ..., 0039)
- **Title:** lowercase, hyphenated, imperative verb phrase (e.g., `webhook-delivery-for-async-endpoints`)
- Currently 39 ADRs exist, numbered 0001 through 0039.

## 2. Template Sections (MADR-based)

Every ADR follows the same section structure. The template is based on [MADR](https://github.com/architecture-decision-record/architecture-decision-record/tree/main/locales/en/templates/decision-record-template-of-the-madr-project).

### Required sections (present in every ADR):

| Section | Content |
|---|---|
| **Title** | `# Title of the Decision` (H1, imperative verb phrase) |
| **Metadata block** | Bulleted list: `Status`, `Deciders`, `Date` |
| **Context and Problem Statement** | What problem is being solved, why now, background |
| **Decision Drivers** | Bulleted list of forces/constraints shaping the decision |
| **Considered Options** | Numbered or lettered alternatives (usually 2-4), each with pros/cons |
| **Decision Outcome** | Chosen option with justification, implementation details, code snippets |
| **Positive Consequences** | Bulleted list of benefits |
| **Negative Consequences** | Bulleted list of trade-offs, limitations, known gaps |
| **Links** | References to related ADRs, issues, PRs, external docs |

### Optional sections (present in some ADRs):

| Section | When used |
|---|---|
| **Technical Story** | One-liner after metadata describing the user story or trigger |
| **Event Schema** | When the ADR defines an API protocol (see ADR-0022) |
| **Response Format** | When the ADR defines data shapes (see ADR-0016) |
| **Default Thresholds** | Tabular configuration defaults (see ADR-0016) |
| **CLI Default** | When CLI behavior changes (see ADR-0022) |
| **Integration** | Code-level integration diagram (see ADR-0016) |
| **Architecture** | ASCII diagram of the system design (see ADR-0022) |

## 3. Cross-Referencing Conventions

- **ADR-to-ADR links:** Relative links with descriptive text:
  ```
  [ADR-0017: Grounded Q&A Endpoint](0017-grounded-qa-endpoint.md)
  ```
  Or shorter form:
  ```
  [ADR-0015](0015-barrier-classification.md)
  ```

- **Superseding:** When a decision changes, the old ADR's status is updated to `superseded by ADR-NNNN` and the new ADR links back to the old one.

- **External references:** Full URLs for issues, PRs, and external docs:
  ```
  [ADR-0012: Webhook Delivery for Async Endpoints](0012-webhook-delivery-for-async-endpoints.md)
  Issue [#130: ...](https://github.com/groktopus/groktocrawl/issues/130)
  ```

## 4. Status Values

| Status | Meaning |
|---|---|
| `accepted` | Decision is approved and implemented |
| `proposed` | Under discussion, not yet finalized |
| `rejected` | Considered but not adopted |
| `deprecated` | No longer applies (but not replaced by a specific ADR) |
| `superseded by ADR-NNNN` | Replaced by a newer decision |

Among the 39 ADRs, most are `accepted`, with a handful of `proposed`.

## 5. Immutability Rule

ADRs are immutable. Existing records are never edited in substance. If a decision changes:
1. Write a new ADR with the next sequential number.
2. Update the old ADR's status to `superseded by ADR-NNNN`.
3. Link from the new ADR back to the old one.

The README index is updated when new ADRs are added but ADR bodies remain frozen.

## 6. Representative ADR Full Text

### ADR-0012: Webhook Delivery for Async Endpoints (Simple / Short)

```
# Webhook Delivery for Async Endpoints

* Status: accepted
* Deciders: magnus, jasper
* Date: 2026-06-05

Technical Story: GroktoCrawl has multiple async endpoints (agent, crawl, extract, generate-llmstxt)
that return job IDs for polling. Callers needed a way to be notified when their job completes
without polling.

## Context and Problem Statement

All async endpoints (`/v2/agent`, `/v2/crawl`, `/v2/extract`, `/v2/generate-llmstxt`) return
a job ID. Clients must poll `GET /v2/agent/:id` to learn when work completes. This is wasteful
for long-running jobs and breaks automation workflows that need event-driven notification.

## Decision Drivers

* Webhook delivery must be available on ALL async endpoints from day one
* The webhook schema must be consistent across all endpoints
* Must support both `completed` and `failed` event types so callers can handle errors
* Must not introduce a new dependency — use the existing HTTP infrastructure

## Considered Options

* **A. Per-endpoint webhook field** — Each async request accepts an optional `webhook` field with
  URL + event types. The worker fires a POST on completion or failure.
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
On completion or failure, the worker POSTs a JSON payload with job details to the URL.
The webhook function lives in `agent/webhook.py` and is called from every async worker.

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
```

### ADR-0022: Agent SSE Streaming (Medium / Feature)

```
# Agent SSE Streaming — Real-Time Research for Interactive Clients

* Status: accepted
* Deciders: magnus, jasper
* Date: 2026-06-08

Technical Story: The agent endpoint (`POST /v2/agent`) currently uses an async create-job→poll
pattern. Interactive clients (web portal, CLI) need real-time progress visibility and token
streaming during deep research.

## Context and Problem Statement

GroktoCrawl has two research-oriented endpoints:

| Endpoint | Pattern | Latency | Use Case |
|---|---|---|---|
| `POST /v2/answer` | Sync inline + SSE streaming | 1-5s | Single-turn Q&A, fast path |
| `POST /v2/agent` | Async create→poll | 5-30s+ | Multi-source deep research |

The agent endpoint returns a job ID, processes research in a background task
(`asyncio.create_task`), and writes results to Valkey. The client polls
`GET /v2/agent/{job_id}` until completion.

This works for programmatic clients (curl, agent tools) but creates a poor experience for:

- **Web portal users** who see a blank screen while the agent researches for 15-30 seconds
- **CLI users** who see only a spinner with no visibility into what sources are being consulted
- **Chat UI integrations** that want to stream the answer token by token as it's generated

The `answer` endpoint already solves the same problem with SSE streaming (see ADR-0017).
The agent endpoint needs the same capability.

## Decision Drivers

- Must provide **real-time progress visibility** during the discovery phase
  (what URLs are being scraped)
- Must **stream tokens** during the synthesis phase (LLM generation)
- Must **reuse the SSE event protocol** established by the `answer` endpoint —
  no new streaming mechanism
- Must **preserve backward compatibility** — existing clients that don't set `stream: true`
  get the current create→poll behavior unchanged
- Must support all existing agent features: seed URLs, schema-based structured output,
  model override
- Must not require new infrastructure dependencies

## Considered Options

### A. Inline SSE streaming — chosen

Run the research loop inline in the route handler when `stream: true`, wrapping the
generator in FastAPI's `StreamingResponse`. Reuse the two-phase event schema from the
`answer` endpoint with one addition: intermediate `source_scraped` events during discovery.

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
- Not suitable for very long-running research (minutes); the current create→poll pattern
  remains available for those cases via `--sync`

### B. Valkey pub/sub bridge

The background task publishes events to a Valkey channel. The SSE handler subscribes to
the channel and relays events to the client.

**Positive:**

- Decouples processing from HTTP delivery
- Survives connection drops with reconnection logic
- Scales to multiple listeners per job

**Negative:**

- Adds significant infrastructure complexity (pub/sub channels, message serialization,
  reconnect logic)
- Valkey bridge itself can fail, adding a new failure mode
- No immediate benefit — the research loop already runs inside the API process
  (no separate worker)
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

The create→poll pattern remains available for clients that prefer it, via the `--sync`
CLI flag or by omitting `stream: true` in the API call.

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

When `schema` is provided (structured JSON output), Phase 2 delivers the full response
in a single `done` event rather than streaming tokens — structured JSON output does not
benefit from token-level streaming.

### CLI Default

The `groktocrawl agent` command uses streaming by default, with `--sync` to opt out of
streaming and fall back to the create→poll pattern. This mirrors the existing
`groktocrawl answer` default (ADR-0017, v1.5.1).

### Consequences

**Positive:**

- Web portal users see sources appear as they're discovered, then the answer streaming
  in real time
- CLI users see the same live progress — URL scraping and answer generation visible immediately
- The `answer` and `agent` endpoints now have parallel streaming interfaces
- Integration test surface grows by one test case (modeled on
  `test_answer_streaming_returns_sse_events`)

**Negative:**

- The agent's `SYSTEM_PROMPT` (68 lines) is much richer than `ANSWER_SYSTEM_PROMPT` (10 lines) —
  the streaming LLM call uses the same prompt unchanged, but the token stream is longer
- HTTP connection held for the full research duration — long-running research (60s+) should
  use `--sync` instead
- Schema-based (structured JSON) requests don't get token-level streaming — the full JSON
  arrives in a single `done` event

## Links

- [ADR-0017: Grounded Q&A Endpoint](0017-grounded-qa-endpoint.md) — establishes the SSE
  streaming pattern and event schema
- [ADR-0012: Webhook Delivery for Async Endpoints](0012-webhook-delivery-for-async-endpoints.md) —
  the background-task pattern this complements
- Issue [#130: feat: add SSE streaming support to the agent endpoint](
  https://github.com/groktopus/groktocrawl/issues/130)
```

## 7. Summary: How to Write a New ADR

1. Pick the next sequential number (currently 0040).
2. Name the file `0040-your-title-with-dashes.md`.
3. Use the template sections from above: Status, Deciders, Date, Technical Story (optional), Context and Problem Statement, Decision Drivers, Considered Options, Decision Outcome, Consequences (Positive + Negative), Links.
4. Cross-reference related ADRs with relative links.
5. Use `proposed` status initially; change to `accepted` after PR review and merge.
6. Add an entry to the index table in `docs/adr/README.md`.
7. Never edit existing ADRs — if a decision changes, write a new ADR and supersede the old one.
