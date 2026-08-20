# Deterministic SlopSearX Contract Fixture

* Status: accepted
* Deciders: GroktoCrawl maintainers
* Date: 2026-08-19

## Context and Problem Statement

GroktoCrawl consumes only the SlopSearX-compatible `GET /search` JSON boundary,
but the Docker integration path previously depended on a live provider and
mutable result counts. Provider failures, rate limits, response-shape changes,
and translated search categories therefore could not be exercised at the real
HTTP boundary without credentials.

## Decision Drivers

* Keep pull-request tests network-free and deterministic.
* Preserve production defaults and the existing `SearXNGClient` behavior.
* Exercise HTTP status, timeout, response-shape, pagination, and request-input contracts.
* Keep fixture state isolated and diagnostic data free of raw query text.

## Considered Options

* **A. Add an in-repository FastAPI contract fixture** — chosen.
* **B. Continue monkeypatching `httpx`** — rejected because it does not exercise HTTP serialization or transport behavior.
* **C. Record live provider traffic** — rejected because it requires credentials and makes tests mutable.

## Decision Outcome

Add `slopsearx-fixture` as a fixture-only Compose service. It implements a
versioned v1 scenario catalog for the narrow SlopSearX-compatible request and
response boundary. Scenario selection is explicit through `scenario` and
`scenario_version` query parameters. Each app process owns an in-memory ledger
whose entries contain scenario, schema version, status, classification, page,
categories, and result count, but never query text.

The fixture returns URLs under `FIXTURE_SITE_BASE_URL` (the existing
`test-site` in Compose). The production `SEARXNG_URL` default remains the real
SlopSearX service; Docker tests opt into the fixture explicitly.

## Consequences

The client and downstream callers can test healthy, empty, degraded, auth,
rate-limit, server-error, delay/timeout, malformed, variant-field, pagination,
stateful quota-exhaustion, and category-capture behavior over real HTTP without
Brave credentials. The
fixture is a contract emulator until independently calibrated against live
SlopSearX observations; it does not reproduce ranking, relevance, freshness,
or index behavior. Its process-local state is intentionally not restart-safe or
shared across test runs.

## Links

* [ADR-0043: Migration from SearXNG to SlopSearX](0043-migration-to-slopsearx.md)
* [ADR-0008: Three-Layer Testing Strategy](0008-three-layer-testing-strategy.md)
* [Issue #568](https://github.com/groktopus/groktocrawl/issues/568)
