# ADR-0055: Deterministic LLM Contract Fixture

* Status: accepted
* Date: 2026-08-20

## Context

The LLM fixture tests provider error handling, structured output, and
streaming without making provider-quality or production-model claims. Tests
must select scenarios through the same HTTP URL shape that `LLMClient` uses.

## Decision

The fixture exposes `/v1/scenarios/{scenario}/chat/completions` and preserves
`/v1/chat/completions` as the default-compatible route. `SCHEMA_VERSION`
versions the HTTP contract and `FIXTURE_VERSION` versions scenario semantics.
Requests may carry a path-safe `run_id`; diagnostics are bounded, filterable,
resettable, and contain only provenance and classifications, never prompts,
context, authorization headers, or secrets.

The fixture is a deterministic contract emulator. It does not emulate provider
quality, ranking, latency distributions, tokenization, or safety behavior.
Malformed envelopes, refusals, truncation, malformed SSE, and missing stream
terminators are explicit failure conditions. Structured output is validated by
the maintained `jsonschema` implementation at the consuming boundary.

## Consequences

Docker integration tests can upload sanitized fixture diagnostics alongside
their outcomes. Scenario behavior is reproducible, but the validity ceiling is
the documented contract surface, not a real provider substitute.
