# Twin CI Evidence and Trusted Calibration

* Status: accepted
* Deciders: GroktoCrawl maintainers
* Date: 2026-08-21

## Context

The LLM and search fixtures are source-owned dependency twins. They must be
safe on fork pull requests without credentials, while self-hosted execution is
controlled by platform approval policy and runner-group access rather than by
fork-editable workflow YAML alone. Trusted live calibration detects provider
drift without changing the deterministic contract.

## Decision

CI uses three lanes in the existing GitHub Actions system. Hosted `Twin
Contracts` runs credential-free on `ubuntu-latest`, blocks non-loopback HTTP(S)
egress during tests, and emits a versioned aggregate manifest. The existing
`[self-hosted, groktopus, docker]` lane proves Compose networking and the
critical fixture journey, recording sanitized LLM diagnostics, a run-scoped
search ledger, and the same manifest shape. `Trusted Live Calibration` runs
only from schedule or manual dispatch on protected `main` in the
`live-calibration` environment.

Calibration is bounded to six outbound calls, 20 seconds per request, no
retries, 128 requested LLM tokens per call (and 512 total), and a configured
worst-case cost estimate below $1. Provider-vs-twin shape/status divergence is
advisory success; harness/configuration defects fail closed. Unknown failures
are infrastructure/harness failures, never provider drift.

The trust boundary is the checked-out source and deterministic fixtures.
Artifacts contain IDs, hashes, schema fingerprints, latency bands,
classifications, and requested/observed identities, but never raw query,
prompt, or secret values. The validity ceiling is the recorded commit,
scenario/schema versions, fixture versions, image IDs/digests, timestamps, and
bounds in the manifest.

Calibration writes only to its artifact directory and verifies fixture/scenario
source paths remain byte-identical. It never auto-records or rewrites fixtures.

## Required Protected Configuration

The `live-calibration` environment must provide `BRAVE_API_KEY`, `LLM_API_KEY`,
and protected variables `LLM_BASE_URL`, `LLM_MODEL`,
`LLM_COST_PER_1K_TOKENS_USD`, and `BRAVE_COST_PER_CALL_USD`. The cost variables
are assumptions used only to enforce a worst-case preflight ceiling, not claims
of actual spend. Values are never documented or printed.

The repository must require approval for all external-contributor workflow runs.
Runner-group restrictions should add defense in depth where organization policy
permits them. The workflow's same-repository condition is also defense in depth,
not the security boundary.

## Consequences

Fork pull requests receive hosted contract confidence without secrets. With the
required platform approval and runner-group policy, self-hosted and live-provider
execution remain unavailable to unapproved forks. A live
divergence produces evidence for review but cannot redefine the pre-merge
deterministic contract.
