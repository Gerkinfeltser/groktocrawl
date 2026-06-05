# Per-Adapter Fallback Chain

* Status: accepted
* Deciders: magnus, jasper
* Date: 2025-06-05

Technical Story: Different sites have different content extraction paths. YouTube's primary extraction (transcript API) is fundamentally different from Twitter's (API → nitter → browser). A shared fallback system would be too abstract to be useful.

## Context and Problem Statement

Each adapter needs to try multiple strategies to extract content (API call, third-party service, browser render, etc.), in order of preference. The fallback chain is site-specific — what works for YouTube (transcript API → yt-dlp → browser) is different from what works for Twitter.

The framework should provide reusable helpers without dictating fallback structure.

## Decision Drivers

* Each adapter must own its fallback chain — the adapter knows best what to try first
* Common patterns (browser extraction, LLM extraction) should be shareable
* If all adapter strategies fail, the generic pipeline should still get a chance

## Considered Options

* **A. Per-adapter internal fallback** — Each adapter implements its own `scrape()` with a try/except chain internally. Framework provides shared helper functions.
* **B. Shared fallback pipeline in registry** — Registry runs a common fallback chain across all adapters (try all adapters, then generic).
* **C. Two-level fallback** — Per-adapter internal chain + registry-level fallback to generic pipeline.

## Decision Outcome

Chosen option: **C. Two-level fallback**. The adapter tries its own strategies first. If all fail (raises `AdapterError`), the registry moves to the next matching adapter or falls through to the generic pipeline. Shared helpers (`try_browser_extraction()`, `try_llm_extraction()`) live in `_helpers.py` for reuse.

### Positive Consequences

* Clear ownership — each adapter evolves independently
* Generic pipeline acts as the ultimate fallback — no content gap
* Shared helpers avoid code duplication without imposing structure

### Negative Consequences

* Potential for duplicated patterns across adapters. Mitigated by extracting common patterns into `_helpers.py` as they emerge.

## Links

* Defined by [ADR-0001: Pre-pipeline Registry Check](0001-adapter-registry-pre-pipeline-hook.md)
* Refined by [ADR-0007: Adapter Timeout and Circuit Breaker](0007-adapter-timeout-and-circuit-breaker.md)
