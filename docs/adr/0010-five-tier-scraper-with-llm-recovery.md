# Five-Tier Scraper Pipeline with LLM-Assisted Recovery

* Status: accepted
* Deciders: magnus, jasper
* Date: 2026-06-05

Technical Story: The original three-tier scraper (llms.txt → content negotiation → Playwright) fails on Cloudflare-protected sites, Substack redirect chains, and SPA pages that serve bot challenges or empty content. The pipeline has evolved to five tiers plus LLM-assisted recovery without documentation of the broader architecture.

## Context and Problem Statement

The `smart_scrape()` function in `scraper-svc/scraper/fetch.py` started as a clean three-tier pipeline. Over time the following gaps appeared:

1. **Cloudflare JS challenges** — Playwright can render the page but is blocked by JS challenges that require a dedicated solver.
2. **Sites with suspicious/empty content** — Playwright may return bot challenge pages, session frames, or truncated content that appears valid to the T3 heuristic but isn't the target content.
3. **Substack redirect chains** — Substack's session-attribution frames and channel-frame redirects cause Playwright to timeout or return empty results.
4. **Binary content** — Some URLs point to PDFs, images, or other binary files that should be returned as download payloads rather than parsed as HTML.

## Decision Drivers

* Must not break existing scrape behavior for sites that already work
* Each tier must degrade gracefully — failure passes to the next tier
* Must minimize latency — cheap tiers (adapter match, /llms.txt) run first
* LLM recovery must never loop infinitely (recovery calls smart_scrape which could call recovery again)
* Browser-svc must only be used as a true last resort (it starts a full Chromium instance in a separate container)

## Considered Options

* **A. Five-tier pipeline with LLM recovery and browser-svc fallback** — The current implementation: adapters → llms.txt → content negotiation → Playwright (with SPA retry) → FlareSolverr → LLM recovery → browser-svc fallback. After each Playwright attempt, suspicious content triggers recovery paths.
* **B. Two-tier (adapter + Playwright only)** — Drop the cheap tiers and FlareSolverr, rely on adpaters for known sites and Playwright for everything else.
* **C. Single universal adapter per domain** — Every site gets a dedicated adapter, no generic pipeline needed.

## Decision Outcome

Chosen option: **A. Five-tier pipeline with LLM recovery and browser-svc fallback**, because it provides the best balance of performance, reliability, and maintainability without requiring per-site adapter implementations for every target.

### Pipeline Architecture

```
URL enters smart_scrape()
│
├── [Pre-pipeline] Adapter registry check
│   └── Match? → return adapter result
│   └── No match? → continue
│
├── Tier 1: /llms.txt at site root
│   └── Hit? → return markdown
│   └── Miss? → continue
│
├── Tier 2: Accept: text/markdown (content negotiation)
│   ├── Binary content? → return download payload
│   └── Markdown detected? → return markdown
│   └── Neither? → continue
│
├── Tier 3: Playwright render + readability
│   ├── SPA content retry (scroll + wait, up to 2 retries)
│   ├── Cloudflare/DDoS-Guard detection (wait for resolution)
│   └── Substack redirect detection
│   ├── Content clean? → return immediately
│   └── Suspicious or embedded? → continue to T3.5
│
├── Tier 3.5: FlareSolverr (profile-gated)
│   └── Success? → return markdown
│   └── Failed/unavailable? → continue
│
├── Tier 4: LLM-assisted recovery
│   ├── Action: iframe_url → recursive smart_scrape on extracted URL
│   ├── Action: extracted_content → return extracted text
│   ├── Action: bot_challenge → classify and return error
│   └── Action: irrecoverable → continue to fallback
│
├── Substack-specific fallback
│   ├── Substack redirect detected? → try browser-svc
│   └── Not Substack? → return generic error
│
└── All tiers exhausted → return error dict
```

### Positive Consequences

* Each tier handles a specific failure mode without polluting the others
* Cheap tiers run first, expensive ones last (Playwright, LLM, browser-svc)
* Binary content detection at Tier 2 avoids unnecessary Playwright launches for PDFs/images
* SPA retry with scroll-based lazy loading catches JS-rendered content without requiring adapter per site

### Negative Consequences

* Pipeline complexity has grown significantly — 5+ tiers with conditional paths
* LLM recovery introduces a recursive risk (recovery calls smart_scrape which could hit recovery again). Mitigated by recovery passing raw HTML (not markdown from a previous recovery attempt)
* FlareSolverr is profile-gated and may not be available — pipeline degrades gracefully but unpredictably without it

## Links

* Refines [ADR-0001: Adapter Registry Pre-Pipeline Hook](0001-adapter-registry-pre-pipeline-hook.md)
* Refines [ADR-0003: Per-Adapter Fallback Chain](0003-per-adapter-fallback-chain.md)
* See [ADR-0011: Stealth Playwright Configuration](0011-stealth-playwright-configuration.md)
* See [ADR-0013: Cloudflare Cookie Persistence](0013-cloudflare-cookie-persistence.md)
