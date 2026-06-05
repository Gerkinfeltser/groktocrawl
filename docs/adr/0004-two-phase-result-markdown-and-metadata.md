# Two-Phase Result (Markdown + Metadata)

* Status: accepted
* Deciders: magnus, jasper
* Date: 2025-06-05

Technical Story: Site-specific adapters can extract structured metadata (video title, channel, views, duration) that the generic markdown-only pipeline cannot. The result format needs to carry both content and structured data.

## Context and Problem Statement

The generic scrape pipeline returns flat markdown. A YouTube adapter can extract structured metadata (title, channel, views, duration, publish date) that should be available to API consumers. We need a result format that carries both the markdown body and structured metadata without breaking backward compatibility.

## Decision Drivers

* Must not break existing API consumers that expect markdown
* Structured metadata should be available to API consumers that want it
* The CLI should work without changes — metadata is a bonus, not a requirement

## Considered Options

* **A. YAML frontmatter prepended to markdown** — Adapter returns `AdapterResult(markdown=body, metadata=dict)`. Framework auto-prepends YAML frontmatter to markdown before returning. CLI sees markdown with frontmatter.
* **B. Separate API response fields** — Add a `metadata` field to the `ScrapeData` model. CLI strips it and shows markdown only; `--json` output includes both.
* **C. Both** — Frontmatter in the markdown body for CLI/agent consumption, plus a separate `metadata` field in the API response for programmatic consumers.

## Decision Outcome

Chosen option: **C. Both**. The scraper merges metadata into YAML frontmatter on the markdown body. The `ScrapeData` model also carries a separate `metadata: dict` field. The CLI user sees frontmatter in the output; programmatic consumers use `--json` to get structured metadata.

### Positive Consequences

* Backward compatible — existing consumers that ignore frontmatter still get clean markdown
* CLI users get structured data without extra flags
* Programmatic consumers can access metadata via `--json` or the API directly

### Negative Consequences

* Slight complexity in the merge step (frontmatter prepend)
* The `ScrapeData` model in agent-svc needs an optional `metadata` field added

## Links

* Implemented by [ADR-0009: Zero CLI Surface Changes](0009-zero-cli-surface-changes.md)
