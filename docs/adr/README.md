# Architecture Decision Records

This directory contains Architecture Decision Records (ADRs) for GroktoCrawl.

## What is an ADR?

An Architecture Decision Record captures an important architectural decision made along with its context and consequences. ADRs are immutable — existing records are never edited. If a decision changes, a new ADR is created and the old one is marked as superseded.

## Convention

- **Location:** `docs/adr/`
- **Naming:** `NNNN-title-with-dashes.md` (sequential numbers, imperative verb phrase)
- **Template:** [MADR](https://github.com/architecture-decision-record/architecture-decision-record/tree/main/locales/en/templates/decision-record-template-of-the-madr-project) — structured with Status, Deciders, Date, Context, Decision Drivers, Considered Options, Outcome, and Links
- **Immutability:** ADRs are immutable. To change a decision, write a new ADR and update the old one's status to `superseded by ADR-NNNN`.
- **Linking:** ADRs reference each other via relative links (`[ADR-0001](0001-adapter-registry-pre-pipeline-hook.md)`)
- **Statuses:** `proposed`, `accepted`, `rejected`, `deprecated`, `superseded by ADR-NNNN`

## Index

| ADR | Title | Status |
|-----|-------|--------|
| 0001 | [Adapter Registry Pre-Pipeline Hook](0001-adapter-registry-pre-pipeline-hook.md) | accepted |
| 0002 | [Regex Dispatch with Priority](0002-regex-dispatch-with-priority.md) | accepted |
| 0003 | [Per-Adapter Fallback Chain](0003-per-adapter-fallback-chain.md) | accepted |
| 0004 | [Two-Phase Result (Markdown + Metadata)](0004-two-phase-result-markdown-and-metadata.md) | accepted |
| 0005 | [In-Repo Adapters with Entry-Point Path Reserved](0005-in-repo-adapters-with-entry-point-path-reserved.md) | accepted |
| 0006 | [Auto-Registration via @adapter Decorator](0006-auto-registration-via-adapter-decorator.md) | accepted |
| 0007 | [Adapter Timeout and Circuit Breaker](0007-adapter-timeout-and-circuit-breaker.md) | accepted |
| 0008 | [Three-Layer Testing Strategy](0008-three-layer-testing-strategy.md) | accepted |
| 0009 | [Zero CLI Surface Changes](0009-zero-cli-surface-changes.md) | accepted |
| 0010 | [Five-Tier Scraper Pipeline with LLM Recovery](0010-five-tier-scraper-with-llm-recovery.md) | accepted |
| 0011 | [Stealth Playwright Configuration](0011-stealth-playwright-configuration.md) | accepted |
| 0012 | [Webhook Delivery for Async Endpoints](0012-webhook-delivery-for-async-endpoints.md) | accepted |
| 0013 | [Search Architecture with Vertical Categories](0013-search-architecture-with-vertical-categories.md) | accepted |
| 0014 | [Binary Content Detection and Download](0014-binary-content-detection-and-download.md) | accepted |
| 0015 | [Barrier Classification Phase 1](0015-barrier-classification.md) | accepted |
| 0016 | [Extraction Quality Gates](0016-extraction-quality-gates.md) | accepted |
| 0017 | [Grounded Q&A Endpoint](0017-grounded-qa-endpoint.md) | accepted |
| 0018 | [Observability Infrastructure](0018-observability-infrastructure.md) | accepted |
| 0019 | [Intelligent Scrape Cache](0019-intelligent-scrape-cache.md) | accepted |
| 0020 | [Proxy Support with Guardrails](0020-proxy-support-with-guardrails.md) | accepted |
| 0021 | [Web Portal](0021-web-portal.md) | accepted |
| 0022 | [Agent SSE Streaming](0022-agent-sse-streaming.md) | accepted |

See [CONTRIBUTING.md](../../CONTRIBUTING.md) for the full ADR workflow: when to write an ADR, how to number it, and how to get it reviewed in a PR.
