# Adapter Registry Pre-Pipeline Hook

* Status: accepted
* Deciders: magnus, jasper
* Date: 2025-06-05

Technical Story: GroktoCrawl's `smart_scrape()` runs a linear three-tier pipeline (llms.txt → content negotiation → Playwright render) that fails on JS-heavy SPAs like YouTube. Adding site-specific handlers must not degrade the existing path.

## Context and Problem Statement

The `smart_scrape()` function in `scraper-svc/scraper/fetch.py` implements a generic scraping strategy that works well for static HTML sites but cannot extract content from JavaScript-heavy single-page applications. YouTube, Twitter/X, and Wikipedia's dynamic layouts are common targets that return empty results.

The simplest fix — adding `if "youtube.com"` checks directly into `smart_scrape()` — would turn a clean pipeline into a rat's nest of special cases over time. We need a mechanism to route specific URLs to specialized handlers without modifying the core pipeline code.

## Decision Drivers

* Must not break existing scrape behavior for sites that already work
* Must allow new site handlers to be added without modifying existing code
* Must be transparent to the CLI and API — `scrape <url>` should just work
* Adapter failure must not block the generic pipeline from trying

## Considered Options

* **A. Pre-pipeline registry hook** — Check the adapter registry before any HTTP requests. Adapters handle their own fetching entirely.
* **B. Post-T2 hook** — Let the cheap tiers (llms.txt, content negotiation) run first, only route to adapter if they fail.
* **C. Inline if/else chain** — Add site detection directly in `smart_scrape()`.

## Decision Outcome

Chosen option: **A. Pre-pipeline registry hook**, because adapters target sites where the generic pipeline already fails — running llms.txt first just adds latency and complexity for no benefit.

### Positive Consequences

* Zero risk to existing functionality — adapters are purely additive
* Full control for adapters (they can use APIs like youtube-transcript-api that don't even HTTP GET the URL)
* Transparent to the CLI — no new subcommands or flags needed

### Negative Consequences

* Adapter failure adds latency to the generic path. Mitigated by per-adapter timeouts (see ADR-0007).
* Skips the `/llms.txt` optimization for sites that might have it — but adapter-targeted sites are SPAs where this doesn't apply.

## Links

* Refined by [ADR-0007: Adapter Timeout and Circuit Breaker](0007-adapter-timeout-and-circuit-breaker.md)
* Refined by [ADR-0009: Zero CLI Surface Changes](0009-zero-cli-surface-changes.md)
