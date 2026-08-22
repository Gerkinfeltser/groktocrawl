# Recommendation — Recurring Mutation CI (issue #572)

This is the pilot's decision on whether to stand up **recurring, repository-wide mutation
testing in CI**. The evidence is the bounded run in this directory (`raw-mutation-report.txt`,
`mutmut-cicd-stats.json`, `classification.md`, `triage.md`, `mutation-review.md`).

## Recommendation: **Defer** recurring mutation CI

Defer a recurring, unconditional mutation CI gate. The pilot proved mutation testing finds
genuine defects in this codebase's decision logic — it surfaced two real oracle gaps
(`_parse_retry_after` at `"0"` → `0.0` and `"0.5"` → `0.5`) that were hardened with
behavior-level tests, plus three more decision areas (search-budget enforcement, scenario
forwarding, sources→category routing) closed by follow-up hardening. That is exactly the
fault-detection signal the project wanted.

However, the evidence does **not** justify a recurring, repo-wide CI gate yet. The pilot's
value comes from **bounded, issue-scoped campaigns** run as an investigative/hardening tool
(which is what this mission did), not from an unconditional gate. Revisit "adopt" when the
tooling quirks below are resolved and an oracle that distinguishes outbound behavior
(twin-backed) is the norm.

## Cost evidence

Measured from the committed final run and an independent re-run:

- **Full-run wall time:** ~**50 s** for 330 mutants (`/usr/bin/time` of a fresh re-run of
  `scripts/run_mutation_pilot.py --max-children 1` reported `real 50.17s`), of which the
  mutant-testing phase is ~**40 s** (330 mutants at `8.19 mutations/second` in the raw
  report), plus the coverage pass and artifact capture.
- **Per-mutant wall time:** ~**0.12 s** for the run phase (40 s / 330) or ~**0.15 s**
  including coverage + setup overhead (50 s / 330).
- **Extrapolation (why a repo-wide gate is expensive):** this is a *single* 318-line file.
  Scaling `mutate_only_covered_lines` over the whole agent/scraper/browser/parse/portal/
  semantic service corpus would be thousands of mutants, each spawning a serialized pytest
  child under `--max-children 1` — minutes to tens of minutes per run with no parallel speedup
  (see the concurrency constraint in Failure-handling evidence). That is disproportionate for
  an unconditional per-PR gate at the current tooling maturity.

## Failure-handling evidence

- **Segfault/suspicious rerun rule:** mutmut's per-mutant pytest children occasionally crash
  on this machine (root cause: macOS CPython `urllib.request.getproxies()` →
  `getproxies_macosx_sysconf()` segfaults when no proxy vars are set, triggered by
  `httpx.AsyncClient()` init). The gate treats `segfault > 0` or `suspicious > 0` in
  `mutmut-cicd-stats.json` as "rerun required", never as a verdict.
- **Cache-reset mitigation:** on the flake rule firing, the runner clears the mutmut cache
  (`mutants/`) and reruns once before trusting verdicts. The recorded run did not trigger the
  rule (`segfault=0`, `suspicious=0`).
- **Segfault workaround:** every mutmut invocation sets dummy localhost proxies plus
  `NO_PROXY=*` so `getproxies_environment()` is non-empty and the crashing
  SystemConfiguration path is skipped (hermetic — the slice monkeypatches the HTTP client).
- **Timeout handling:** the runner bounds each run with a subprocess timeout (1800 s); the
  `[tool.mutmut]` `pytest_add_cli_args` neutralizes the repo's baked-in `addopts` per mutant,
  and no mutant timed out in the recorded run.
- **Concurrency constraint:** `--max-children 1` is required because concurrent pytest
  children corrupt the shared scratch `QA_OUTCOME_PATH` file read by `tests/conftest.py`
  (JSONDecodeError noise). This serialization caps throughput and is the main blocker to
  economical repo-wide mutation runs.

## Why defer (not adopt / not reject)

- **Not reject:** the pilot materially improved the test suite — real faults were found and
  fixed, with TDD-grade kill evidence. That is decisive value.
- **Not adopt yet:** the tooling is brittle (macOS segfault workaround, mandatory
  serialization, the `cp -r tests/common` prerequisite) and the signal-to-noise is low at the
  unit boundary — of 330 mutants, 157 killed and 173 survived, of which 55 are equivalent
  behavior and 118 are invalid/cosmetic under the unit oracle (0 genuine test gaps remain
  after hardening). An unconditional repo-wide gate would run thousands of serialized,
  workaround-dependent mutants for mostly non-actionable survivors.
- **Deferred path:** continue running **bounded, issue-scoped mutation campaigns on high-risk
  decision slices** (the search-client slice being the reference), and revisit "adopt" when
  (a) the toolchain drops the segfault quirk / supports parallel-safe runs and (b) a
  twin-backed oracle that distinguishes outbound request behavior is standard for the
  decision slices under test. No mutation-score gate, threshold, auto test-generation loop, or
  PR blocker is added by this pilot.
