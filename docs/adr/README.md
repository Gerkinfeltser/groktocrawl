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

## For Contributors

See [CONTRIBUTING.md](../../CONTRIBUTING.md) for the full ADR workflow: when to write an ADR, how to number it, and how to get it reviewed in a PR.
