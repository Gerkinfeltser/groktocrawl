# In-Repo Adapters with Entry-Point Path Reserved

* Status: accepted
* Deciders: magnus, jasper
* Date: 2025-06-05

Technical Story: Adapters need to live somewhere in the codebase. The decision of where affects discoverability, versioning, and extensibility.

## Context and Problem Statement

New adapter files need a home. The location choice has long-term consequences for how adapters are discovered, versioned, and extended by third parties.

## Decision Drivers

* Adapters must be versioned with the codebase they target (API surface changes)
* Adding a new adapter must be easy for the project maintainer
* The architecture should not preclude third-party adapters in the future
* Minimal infrastructure overhead for v1

## Considered Options

* **A. In-repo (`scraper-svc/scraper/adapters/`)** — Built-in adapters shipped with the codebase. Discovered by import at startup.
* **B. Entry-point plugins (pip-installable)** — Adapters register via `pyproject.toml` entry points under `groktocrawl.adapters`.
* **C. Config-file based** — Users write `~/.groktocrawl/adapters.yaml` mapping domains to handler scripts.

## Decision Outcome

Chosen option: **A. In-repo for v1**, with the adapter interface designed so that entry-point loading (option B) can be added in v2 without changing any adapter code.

### Positive Consequences

* Versioned with the codebase, reviewed in the same PRs
* Simple discoverability — all adapters in one directory
* Quick to implement, easy to test

### Negative Consequences

* Adding a new adapter requires a code change and PR
* Third parties cannot add adapters without forking. Mitigated by designing the `SiteAdapter` interface and `AdapterRegistry` dispatch logic so that entry-point loading is a drop-in addition in v2.

## Links

* Defined by [ADR-0006: Auto-Registration via @adapter Decorator](0006-auto-registration-via-adapter-decorator.md)
