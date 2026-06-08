# Search Type Spectrum — Fast and Rich Search Modes

* Status: proposed
* Deciders: magnus, jasper
* Date: 2026-06-09

Technical Story: GroktoCrawl's `/v2/search` endpoint has exactly one mode — raw SearXNG keyword search with no enrichment. Callers who want content excerpts or structured extraction must make a separate second call (scrape each URL, or feed results to an LLM). This doubles latency for enriched-search workflows and makes structured extraction from search results a multi-step process.

## Context and Problem Statement

GroktoCrawl currently has three distinct question-answering modes:

| Mode | Endpoint | Latency | What it returns |
|---|---|---|---|
| Raw search | `POST /v2/search` | <1s | URLs + titles + short descriptions |
| Grounded Q&A | `POST /v2/answer` | 1-3s | Single cited answer from top search results |
| Deep research | `POST /v2/agent` | 5-60s | Multi-source synthesized research report |

The gap is between raw search and grounded Q&A. A caller who wants **enriched search results** — the same result list but with longer excerpts scraped from each page — must do:

1. `POST /v2/search` → get 5 URLs
2. `POST /v2/scrape` × 5 → get page content
3. Feed all content to their own LLM → extract excerpts or structured data

This is three round-trips for something that should be one. It's the second-most-common pattern after raw search itself.

Additionally, there is no way to get **structured extraction from search results** in a single call. The existing `/v2/extract` endpoint requires known URLs — it doesn't discover pages. A caller who wants "top 10 YC AI startups and their websites" from web search must discover the URLs themselves, then pass them to extract. This is two round-trips.

## Decision Drivers

* Must reuse existing infrastructure — SearXNG client, scraper client, LLM client. No new dependencies.
* Must not break existing callers — `fast` mode (default) = current behavior, identical response shape.
* Must not conflict with `/v2/answer` (ADR-0017) or `/v2/agent`. The search endpoint remains single-round — no multi-step query rewriting, no multi-angle search, no iterative refinement.
* Must support both simple enrichment (longer excerpts) and structured extraction (output schema).
* Must be self-hostable without additional services.

## Considered Options

### A. Two search types: fast and rich *(chosen)*

Two modes on the existing `/v2/search` endpoint, controlled by a new `search_type` field:

| Mode | Pipeline | Latency |
|---|---|---|
| `fast` (default) | SearXNG query → return raw results | <1s |
| `rich` | SearXNG query → scrape top-N results → lightweight LLM synthesis | 1-3s |

`fast` is identical to current behavior — zero change for existing callers. `rich` runs the same pipeline as `/v2/answer` but returns enriched search results instead of a single synthesized answer.

An optional `output_schema` field enables structured extraction from search results. When provided, the LLM synthesizes schema-compliant JSON from the scraped content (or from snippet text in `fast` mode). The response includes a new `output` field with `content` (structured data) and `grounding` (per-field citations).

An optional `system_prompt` field guides the synthesis behavior (source preferences, recency filters, extraction strictness).

**Positive:**
- Existing callers unaffected — `search_type` defaults to `fast`
- Reuses search + scrape + LLM pipeline from `/v2/answer` (ADR-0017)
- Structured extraction from search results is a net-new capability not available through any other endpoint
- No new services, no new dependencies
- `output` field is additive — Firecrawl SDK clients ignore unknown response keys

**Negative:**
- `/v2/search` is no longer a pure Firecrawl v2-compatible endpoint — it's a superset with GroktoCrawl-specific fields
- `rich` mode adds LLM latency and token cost to a previously deterministic endpoint
- `system_prompt` is an injection surface — callers could craft prompts that degrade extraction quality

### B. Three search types: fast, auto, deep *(rejected)*

The original proposal included a `deep` mode with multi-step query rewriting, multi-angle search, and LLM synthesis across multiple search queries. This was rejected because it conflicts with `/v2/agent` — the agent endpoint already handles multi-round research. Two endpoints offering different implementations of multi-step search synthesis create confusion about which to use.

### C. Separate endpoint for structured search *(rejected)*

A new endpoint (`/v2/search/extract` or similar) would keep search pure but adds API surface. The `output_schema` parameter is an opt-in upgrade to the existing search endpoint — callers who don't use it see no change. A separate endpoint is premature before the feature proves its value on the existing surface.

## Decision Outcome

Chosen option: **A. Two search types: fast and rich**, with the following constraints:

1. `search_type` field name (not `type`) — consistent with `/v2/answer` which already uses `search_type`
2. `fast` is the default — backward compatible with zero latency or behavior change
3. `rich` reuses the existing search → scrape → synthesize pipeline from `/v2/answer`
4. `output_schema` is optional on both modes — `fast` extracts from snippets (lower fidelity), `rich` extracts from full page content
5. `system_prompt` only affects the synthesis LLM call — ignored for plain `fast`
6. Categories and sources filter the SearXNG phase only, same in both modes
7. The response adds an `output` field (present only when `output_schema` is provided) — no existing response fields change

### Positive Consequences

* Single-call enriched search with structured extraction — the most common multi-step pattern collapsed into one round-trip
* Existing callers see no change
* No new infrastructure required
* Explicit boundary with `/v2/agent`: single-round vs multi-round

### Negative Consequences

* Diverges from Firecrawl v2 spec — GroktoCrawl `/v2/search` is now a superset
* LLM quality risk: `fast` + `output_schema` extraction from snippets is inherently lower fidelity than from full content
* `system_prompt` injection surface — callers could degrade their own results with poor prompts

## Links

* Issue: https://github.com/groktopus/groktocrawl/issues/62
* Grounded Q&A ADR (reused pipeline): [ADR-0017](0017-grounded-qa-endpoint.md)
* Search Architecture ADR (categories/sources): [ADR-0013](0013-search-architecture-with-vertical-categories.md)
* Exa search types (inspiration): https://exa.ai/docs/reference/search-best-practices.md
