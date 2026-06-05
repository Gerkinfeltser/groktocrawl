# Three-Layer Testing Strategy

* Status: accepted
* Deciders: magnus, jasper
* Date: 2025-06-05

Technical Story: Adapters are inherently more brittle than generic scraping because they depend on external APIs and site structures that change without notice.

## Context and Problem Statement

A YouTube adapter that works today may break tomorrow if YouTube changes its transcript API response format, its oEmbed endpoint, or its page DOM structure. We need a testing strategy that catches regressions fast without requiring network access for every test run.

## Decision Drivers

* CI must be fast — most tests run without network access
* API breakage must be detected quickly, not silently
* Test maintenance should be minimal

## Considered Options

* **A. Contract tests (schema validation) + VCR recordings** — Layer 1: unit tests that validate output schema against known inputs. Layer 2: recorded API responses replayed in CI. Layer 3: weekly live API tests.
* **B. Always hit real APIs** — Every test run makes real network calls to YouTube/Twitter/Wikipedia APIs.
* **C. Mock everything** — All external dependencies are mocked at the HTTP layer.

## Decision Outcome

Chosen option: **A. Three-layer strategy**. Layer 1 (contract tests) run in milliseconds and validate output shape. Layer 2 (VCR-recorded) run in seconds and catch regressions against known API responses. Layer 3 (live) runs weekly in CI to detect API drift.

### Positive Consequences

* Fast CI — Layer 1+2 run in <5s per adapter
* Early warning of API changes via Layer 3
* Recordings can be refreshed automatically via scheduled CI job

### Negative Consequences

* VCR recordings require periodic maintenance. Mitigated by automating re-recording in a weekly CI job.
* Live tests require API keys (YouTube Data API, Twitter OAuth). Mitigated by documenting required env vars.

## Links

* Defined by [ADR-0004: Two-Phase Result](0004-two-phase-result-markdown-and-metadata.md) (output schema that contract tests validate against)
