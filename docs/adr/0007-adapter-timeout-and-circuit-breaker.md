# Adapter Timeout and Circuit Breaker

* Status: accepted
* Deciders: magnus, jasper
* Date: 2025-06-05

Technical Story: A misbehaving adapter (rate-limited API, network hang, slow browser render) must not hold up the scrape pipeline for longer than a bounded duration.

## Context and Problem Statement

The adapter registry is checked before the generic pipeline. If an adapter hangs (e.g., YouTube API rate-limited, yt-dlp stuck on a large video), the user waits. Without timeouts, a single bad adapter call can make `scrape <url>` appear broken even when the generic pipeline would have worked fine.

## Decision Drivers

* Worst-case latency should be bounded (configurable, per-adapter)
* Timeout should be per-adapter call, not per-adapter lifecycle
* No sophisticated circuit breaker for v1 (tripping after N failures) — keep it simple

## Considered Options

* **A. Per-adapter timeout with wrapper helper** — `AdapterContext` provides a `with_timeout(coro, default=15)` helper. All framework-provided calls inside adapters use it.
* **B. Global timeout in the registry** — The registry wraps every adapter `scrape()` call in a single global timeout.
* **C. No timeout (trust the adapter)** — Adapters are responsible for their own time management.

## Decision Outcome

Chosen option: **A. Per-adapter timeout with configurable defaults**, because different adapters have different latency profiles (YouTube transcript API is fast, browser fallback is slow).

### Positive Consequences

* Bounded latency — worst case adds 15s per adapter attempt
* Configurable per-site via `.env` (e.g., `ADAPTER_YOUTUBE_TIMEOUT=30`)
* Defaults are sane (15s) and documented in README.md

### Negative Consequences

* No circuit breaker (tripping after N consecutive failures). Mitigated: defer to v2 if needed, and the registry already falls through to the generic pipeline on `AdapterError` or timeout.
