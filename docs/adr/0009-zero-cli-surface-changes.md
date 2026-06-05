# Zero CLI Surface Changes

* Status: accepted
* Deciders: magnus, jasper
* Date: 2025-06-05

Technical Story: The adapter architecture must be transparent to users. `groktocrawl scrape <url>` should work identically for all URLs — users should not need to know whether an adapter exists for a given site.

## Context and Problem Statement

If adapters require new CLI flags (`--adapter youtube`), new subcommands (`groktocrawl youtube-transcript <url>`), or manual URL classification before scraping, the user experience degrades. The CLI surface should remain stable regardless of how many adapters are added.

## Decision Drivers

* Backward compatibility with existing CLI usage and scripts
* Users should not need to learn about adapters to use them
* API consumers (including the `agent` pipeline) should benefit automatically

## Considered Options

* **A. No CLI changes** — Adapter routing happens entirely in `smart_scrape()` in scraper-svc. The CLI, agent-svc route handler, and `agent` pipeline are unaware of adapters.
* **B. --adapter flag** — Optional `--adapter youtube` flag to force a specific adapter. `auto` (default) uses the registry; `generic` skips adapters and uses the raw pipeline.
* **C. New subcommands** — `groktocrawl youtube <url>` as a separate entry point for site-specific extraction.

## Decision Outcome

Chosen option: **A. No CLI changes**. The only code change is a 3-line registry check at the top of `smart_scrape()` in scraper-svc. The CLI, agent-svc route handler, and `agent` pipeline all call the same `/v2/scrape` endpoint — they all benefit automatically.

### Positive Consequences

* Fully backward compatible — existing scripts and workflows unchanged
* No documentation changes needed for existing users
* The `agent` pipeline (which calls `/v2/scrape` for content) automatically gets richer results from adapted sites

### Negative Consequences

* No way to force adapter selection from the CLI. If an adapter returns poor results for a specific URL, the user cannot bypass it without modifying env vars. Mitigated: this is an acceptable tradeoff for v1 — the registry already falls through to the generic pipeline if the adapter fails.
