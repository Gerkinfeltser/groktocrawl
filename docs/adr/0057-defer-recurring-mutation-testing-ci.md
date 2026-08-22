# Defer Recurring Mutation-Testing CI (Pilot Outcome)

- Status: accepted
- Deciders: GroktoCrawl maintainers
- Date: 2026-08-21

## Context and Problem Statement

GroktoCrawl wanted fault-detection evidence for its search decision logic: do the existing
tests actually detect when the search-client policy changes? Issue #572 ran a **bounded,
reproducible mutation-testing pilot** over the single decision-slice file
`agent-svc/agent/searxng_client.py` (mutmut 3.7.0, pinned and ephemeral, `[tool.mutmut]` in
`agent-svc/pyproject.toml`, hermetic slice `tests/service/test_searxng_client.py`). The
question this ADR records: **should recurring, repository-wide mutation testing become a CI
gate?**

## Decision Drivers

- **Fault-detection value:** the pilot must show whether tests catch real decision-logic
  changes before any decision is made.
- **Boundedness:** the tool must stay pinned/ephemeral, never a permanent dependency or an
  unbounded job.
- **Signal-to-noise:** survivors must be actionable (real test gaps), not overwhelmingly
  equivalent/invalid at the chosen oracle boundary.
- **Tooling maturity / cost:** a recurring gate must be cheap, stable, and parallelizable;
  segfault/timeout flakiness and serialization are disqualifiers for an unconditional gate.
- **Advisory stance:** the outcome is a recommendation (adopt / defer / reject), with no
  score threshold, auto test-generation loop, or PR blocker added by the pilot.

## Considered Options

- **Adopt — add recurring, repository-wide mutation CI now.** Rejected for this iteration.
  The tool is brittle on this platform (macOS CPython `urllib.request.getproxies()` →
  `getproxies_macosx_sysconf()` segfault requires a dummy-proxy workaround) and must run
  serialized (`--max-children 1`, since parallel pytest children corrupt the shared scratch
  `QA_OUTCOME_PATH` file). Extrapolated repo-wide (thousands of serialized, workaround-
  dependent mutants per file) it is disproportionate for an unconditional per-PR gate, and
  the unit-oracle signal-to-noise is low (of 330 mutants, 173 survived, of which 55 are
  equivalent behavior and 118 are invalid/cosmetic under the unit oracle — 0 genuine test
  gaps remain after hardening).
- **Defer — keep bounded, issue-scoped campaigns; no recurring gate yet.** Chosen. The
  pilot delivered genuine value (two `_parse_retry_after` oracle gaps found and hardened,
  plus three decision areas closed by follow-up hardening) without requiring a fragile,
  repo-wide gate. Defer "adopt" until the toolchain drops the segfault quirk / supports
  parallel-safe runs and a twin-backed oracle that distinguishes outbound request behavior is
  the norm for the slices under test.
- **Reject — mutation testing is not worth it at all.** Rejected. The pilot materially
  improved the test suite with TDD-grade kill evidence; mutation testing is worth doing, just
  not as an unconditional recurring gate today.

## Decision Outcome

**Defer** recurring, repository-wide mutation-testing CI. Continue running **bounded,
issue-scoped mutation campaigns on high-risk decision slices** (the search-client slice is
the reference), and revisit "adopt" when the tooling quirks and oracle-fidelity limitations
above are resolved. This stance is recorded in
[`mutation/2026-08-21-search-client/recommendation.md`](../mutation/2026-08-21-search-client/recommendation.md)
and matches the pilot recommendation.

### Consequences

Positive:

- The search-client decision slice gained real fault-detection evidence and hardened tests
  (the retained `_parse_retry_after` mutants are now killed by the committed suite).
- No mutation-score gate, threshold, auto test-generation loop, or PR blocker was added; no
  permanent dependency (`uv.lock`/manifests unchanged; mutmut stays pinned and ephemeral).
- The reproducible runner (`scripts/run_mutation_pilot.py`) and committed evidence package
  (`mutation/`, `mutation-review.md`, `triage.md`, `recommendation.md`) let any future slice
  re-run the same bounded process.

Negative / limitations:

- Recurring, repo-wide mutation CI remains deferred; teams run bounded campaigns on demand
  rather than automatically.
- The unit oracle cannot distinguish outbound request/header/metric literal changes (those
  survivors are invalid/equivalent at this boundary); distinguishing them requires the
  twin-backed (HTTP) oracle, which is demonstrated but not the committed hermetic slice.
- The macOS segfault workaround and `--max-children 1` serialization remain prerequisites for
  running the tool on this platform.

## Links

- Pilot recommendation: [mutation/2026-08-21-search-client/recommendation.md](../mutation/2026-08-21-search-client/recommendation.md)
- Pilot review: [mutation/2026-08-21-search-client/mutation-review.md](../mutation/2026-08-21-search-client/mutation-review.md)
- Issue #572 (tracked work): <https://github.com/groktopus/groktocrawl/issues/572>
