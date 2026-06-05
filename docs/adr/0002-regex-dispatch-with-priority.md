# Regex Dispatch with Priority

* Status: accepted
* Deciders: magnus, jasper
* Date: 2025-06-05

Technical Story: Multiple adapters may match the same URL (e.g., a general `twitter.com` adapter and a specific Spaces adapter both matching `twitter.com/i/spaces/...`). We need a deterministic way to resolve which adapter handles a given URL.

## Context and Problem Statement

URL patterns overlap. A single URL could match multiple adapters' regex patterns. The dispatch mechanism needs to handle this without ambiguity or race conditions.

## Decision Drivers

* Must be deterministic — same URL always routes to the same adapter
* Must support overlapping URL patterns (site-wide handlers vs specific sub-path handlers)
* Must be fast — the check happens on every `scrape` call
* Must allow adapters to be added without modifying the registry logic

## Considered Options

* **A. Static regex list per adapter with priority ordering** — Each adapter declares `patterns: list[re.Pattern]` and a `priority: int`. Registry sorts by descending priority, iterates in order, first match wins.
* **B. Concurrent try-all, first success wins** — Fire every adapter at the URL simultaneously, take the first result.
* **C. URL-parse map** — Use `urlparse(url).netloc` as a dict key for O(1) lookup.

## Decision Outcome

Chosen option: **A. Static regex list with priority ordering**, because it's deterministic, fast, and handles overlapping patterns cleanly.

### Positive Consequences

* Priority lets site-specific supersets (e.g., Twitter Spaces) win over broad handlers (e.g., general Twitter/X)
* Deterministic — no race conditions
* Fast — regex matching on URL strings is microseconds

### Negative Consequences

* Regex maintenance burden. Mitigated by using well-tested patterns and unit-testing pattern matching.
* URL-parse optimization (prefix filter before regex) can be added later if profiling shows it matters.

## Links

* Defined by [ADR-0001: Pre-pipeline Registry Check](0001-adapter-registry-pre-pipeline-hook.md)
