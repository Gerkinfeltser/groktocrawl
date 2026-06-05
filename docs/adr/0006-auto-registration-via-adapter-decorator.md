# Auto-Registration via @adapter Decorator

* Status: accepted
* Deciders: magnus, jasper
* Date: 2025-06-05

Technical Story: Each adapter needs to register itself with the `AdapterRegistry` without requiring a central config file or manual registration call in `app.py`.

## Context and Problem Statement

Every time someone adds a new adapter, they should not have to also edit a registry config, update a list, or wire it into the application startup. Registration should be automatic and local to the adapter file.

## Decision Drivers

* Adding a new adapter should require exactly one new file (plus tests)
* Registration must be explicit — no metaclass magic or automatic discovery of all classes in a module
* The mechanism should not prevent future entry-point-based loading of external adapters

## Considered Options

* **A. @adapter decorator** — A decorator that wraps a `SiteAdapter` subclass and auto-registers it into a module-level registry list at import time.
* **B. Metaclass** — A metaclass on `SiteAdapter` that auto-registers all subclasses.
* **C. Manual registration in app.py** — Each adapter is explicitly registered in the application's startup code.

## Decision Outcome

Chosen option: **A. @adapter decorator**, because it's explicit, local to the adapter file, and avoids metaclass complexity.

### Positive Consequences

* Registration is visible in the adapter file itself — no hidden magic
* Simple to test — registry state is deterministic after imports
* Works naturally with entry-point loading in v2 (the decorator can also populate an entry-point-compatible registry)

### Negative Consequences

* Import order matters — adapters must be imported for registration to trigger. Mitigated by having `adapters/__init__.py` explicitly import all known adapter modules at startup.

## Links

* Implemented by [ADR-0005: In-Repo Adapters](0005-in-repo-adapters-with-entry-point-path-reserved.md)
