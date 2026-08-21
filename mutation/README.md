# Mutation-Testing Pilot (issue #572)

This directory holds the evidence for the **bounded mutation-testing pilot** on the
search-client decision slice (`agent-svc/agent/searxng_client.py`), the work tracked in
[GitHub issue #572](https://github.com/groktopus/groktocrawl/issues/572).

## What

A one-off, bounded, reproducible mutation-testing campaign over the single file that
carries the search-client decision logic. It uses **mutmut 3.7.0**, installed pinned and
ephemeral (`uv run --with mutmut==3.7.0 --no-sync`), configured via `[tool.mutmut]` in
`agent-svc/pyproject.toml` to mutate only `agent/searxng_client.py`, run from the
`agent-svc/` cwd against the hermetic slice `tests/service/test_searxng_client.py`.

Each run's evidence lives in a single dated subdirectory
`mutation/<iso-date>-search-client/`:

- `run-config.json` — the full, self-contained reproducible procedure (command, tool +
  version + install method, scope, seed statement, timeout, test command, environment
  identity).
- `raw-mutation-report.txt` — the captured mutmut stdout of the final bounded run.
- `mutmut-results.txt` / `mutmut-results-nonkilled.txt` — full / non-killed verdict lists.
- `mutmut-cicd-stats.json` — machine-readable `export-cicd-stats` output (incl.
  segfault/suspicious counts so the flake rule is auditable).
- `mutmut-version.txt` — `mutmut --version` capture from the actual run (recorded AND used).
- `show-diffs/` — `mutmut show` diff captures for every non-killed mutant.
- `classification.md` — every in-scope mutant classified (killed / survived / …) with an
  explicit denominator.
- `triage.md` — survivor disposition (test gap / equivalent behavior / invalid mutation /
  infrastructure limitation).
- `mutation-review.md` — the qa-methodology review (change/scope, run config, baseline,
  mutants, accounting, candidate tests, independent verification, decision).
- `recommendation.md` — adopt / defer / reject for recurring mutation CI with cost +
  failure-handling evidence.

## Why

The mission wanted fault-detection evidence for the search decision logic: do the existing
tests actually notice when the policy changes? The pilot found **two genuine oracle gaps**
(`_parse_retry_after` boundary handling at `"0"` → `0.0` and `"0.5"` → `0.5`), which were
hardened with behavior-level tests that now kill the retained mutants, plus three more
decision areas (search-budget enforcement, scenario forwarding, sources→category routing)
closed by follow-up hardening. The recommendation (`recommendation.md`, mirrored by
ADR-0057) is the decision for whether recurring mutation CI is worth it.

## How to rerun

The committed runner `scripts/run_mutation_pilot.py` is self-provisioning (it runs
`uv sync --locked --no-dev --group fast-tests` unless `--no-self-provision`). From a clean
checkout it provisions its own environment, creates the `agent-svc/tests` and
`agent-svc/common` copies required by `[tool.mutmut]`'s `also_copy`, runs the bounded pilot
(`--max-children 1`, serialized), captures the raw report + stats + version + show-diffs,
applies the flake rule, writes `run-config.json` and `classification.md`, and trap-cleans
every transient artifact.

```bash
# from the repository root (network access to PyPI required for the pinned ephemeral mutmut install)
python3 scripts/run_mutation_pilot.py --no-self-provision --max-children 1
```

The runner defaults to the same `mutation/<iso-date>-search-client/` dir used by the
committed evidence, so a rerun regenerates the package in place (stale `show-diffs` are
cleared). To reproduce the committed package exactly, ensure the working tree is at the
commit whose evidence you are regenerating — the in-scope mutant set is coverage-driven
(`mutate_only_covered_lines = true`), so a different test suite produces a different mutant
count.

Manual step for the surviving-mutant analysis (not produced by the runner): the human/agent
author writes `triage.md` (survivor dispositions) and the `mutation-review.md` +
`recommendation.md` reports.

### Environment / known quirks (from `library/environment.md`)

- Every pytest invocation must set `QA_OUTCOME_PATH` to a scratch path (the repo conftest
  writes `test-outcomes.*` to cwd) and neutralize the root `addopts` (`-o "addopts="`) with
  `-p no:cacheprovider`. The runner does this for every subprocess.
- **macOS `getproxies()` segfault:** with no proxy vars set, CPython's
  `urllib.request.getproxies()` can segfault in `getproxies_macosx_sysconf()` (triggered by
  `httpx.AsyncClient()` init in every per-mutant pytest child). The runner sets dummy
  localhost proxies plus `NO_PROXY=*` so `getproxies_environment()` is non-empty (skips the
  crashing path) while uv can still reach PyPI.
- **Flake rule:** if `mutmut-cicd-stats.json` reports `segfault > 0` or `suspicious > 0`,
  clear `mutants/` and rerun once before trusting verdicts; a first occurrence is never a
  verdict. The recorded run had `segfault=0`, `suspicious=0`.
- **Serialization:** the runner uses `--max-children 1` so concurrent pytest children do not
  corrupt the shared scratch `QA_OUTCOME_PATH` file read by `tests/conftest.py`.
