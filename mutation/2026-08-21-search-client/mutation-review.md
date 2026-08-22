# Mutation Review — Search-Client Decision Slice (issue #572)

qa-methodology mutation-review for the bounded pilot over
`agent-svc/agent/searxng_client.py`. Companion evidence: `run-config.json`,
`raw-mutation-report.txt`, `classification.md`, `triage.md`, `recommendation.md`,
and `mutation/README.md`.

## Change And Scope

**Change under test:** the search-client decision logic in a single source file,
`agent-svc/agent/searxng_client.py` (`[tool.mutmut]` in `agent-svc/pyproject.toml` sets
`only_mutate = ["agent/searxng_client.py"]`). Nothing else in the repository is mutated.

**Test oracle:** the hermetic slice `tests/service/test_searxng_client.py` (30 tests,
no fixture, no live network — monkeypatched `client._client.get`). It exercises the
decision slice: retry-vs-graceful 429 handling, empty-vs-failure engine-health parsing,
Retry-After parsing, category/source translation, response limiting, timeout behavior,
search-budget enforcement, scenario/sources forwarding, and the query-text redaction
guard. A twin-backed (HTTP-level) kill against `slopsearx-fixture` on `127.0.0.1:8083`
demonstrates the boundary is distinguishable (see `triage.md` STAGE 3).

## Run Configuration

Full, machine-actionable procedure is recorded in `run-config.json`; summary:

- **Tool:** mutmut **3.7.0**, pinned and ephemeral (`uv run --with mutmut==3.7.0 --no-sync`);
  version capture committed as `mutmut-version.txt`.
- **cwd:** `agent-svc/` (required so mutant keys match the `from agent.searxng_client import`
  test import path).
- **Bounding:** single source file; `--max-children 1` (a concurrency bound, not a mutant
  budget). `mutate_only_covered_lines = true`.
- **Test selection:** `pytest_add_cli_args_test_selection = ["tests/service/test_searxng_client.py"]`;
  every pytest invocation uses `-o addopts=` + `-p no:cacheprovider` + a scratch
  `QA_OUTCOME_PATH`.
- **Prerequisites:** `cp -r ../tests agent-svc/tests` and `cp -r ../common agent-svc/common`
  (`also_copy = ["common","tests"]`), trap-cleaned after the run.
- **Timeout:** runner subprocess timeout 1800 s; no mutant timed out.
- **Environment identity:** uv 0.11.18, Python 3.12.11, root `uv.lock` untouched (no
  permanent dependency added; PyPI is the sole permitted external contact for the pinned
  ephemeral install). Proxy-env workaround for the macOS `getproxies()` segfault is recorded
  in `run-config.json`.

## Baseline Result

Clean baseline slice (no fixture, no network), neutralized addopts:

```
tests/service/test_searxng_client.py ............      [100%]
QA outcomes: passed=30, failed=0, skipped=0
30 passed in 0.39s
```

## Mutants

Full per-mutant verdicts are in `mutmut-results.txt`; every row and its operator/diff is in
`classification.md`; `mutmut show` diffs for all non-killed mutants are in `show-diffs/`.

| ID | Source path | Operator / Diff | Classification |
|----|-------------|-----------------|----------------|
| (all 330) | `agent/searxng_client.py` | see `classification.md` | see `classification.md` |

Summary of the final run (`mutmut-cicd-stats.json`, raw report tail `330/330 🎉 157 🫥 0 ⏰ 0 🤔 0 🙁 173 🔇 0 🧙 0`):

| Verdict | Count |
| --- | ---: |
| killed | 157 |
| survived | 173 |
| suspicious | 0 |
| timeout | 0 |
| no coverage (`no_tests`) | 0 |
| segfault | 0 |
| **total** | **330** |

## Accounting

- **In-scope mutants:** 330 (all from `agent/searxng_client.py`).
- **Classified:** **330 / 330** (every mutant; no silent omission — the classification ID
  set exactly equals the raw report's `mutmut-results.txt` ID set).
- **Ledger chain:** raw-report in-scope 330 == classification rows 330 == mutation-review
  accounting 330; classification survivors 173 == `mutmut-results-nonkilled.txt` 173 ==
  triage rows 173. Killed 157 + survived 173 = 330.
- **Non-killed universe:** 173 = survived 173 ∪ suspicious 0 ∪ timeout 0 ∪ no-coverage 0.
  All 173 are disposed in `triage.md` (55 equivalent behavior, 118 invalid mutation, 0 test
  gap, 0 infrastructure limitation).
- **Flake rule:** not triggered — the recorded run reported `segfault=0`, `suspicious=0`.
  Verdicts are taken from the single clean run.

## Candidate Test

The pilot hardened the confirmed oracle gaps with two behavior-level tests in
`tests/service/test_searxng_client.py`:

- `test_parse_retry_after_zero_seconds` — asserts `_parse_retry_after("0") == 0.0`.
- `test_parse_retry_after_fractional_seconds` — asserts `_parse_retry_after("0.5") == 0.5`.

Checks:

- **Non-vacuity:** each asserts a concrete expected float and fails if the function returns
  `None`/does nothing (verified: `None == 0.0`, `None == 0.5` under the retained mutants).
- **Non-redundancy:** existing positives cover only `"37"` and `"2.5"`; the new tests cover
  the `"0"` and `"0.5"` boundaries the retained mutants flip.
- **Not implementation-coupled:** both assert the public return value of `_parse_retry_after`,
  never internal state or call counts.
- **Baseline-pass / retained-mutant-fail (TDD):** baseline green (30/30), the `seconds <= 0`
  mutant (`mutmut_7`) fails the zero test, the `seconds < 1` mutant (`mutmut_8`) fails both
  new tests; revert restores the production file byte-identical to `origin/main`.

A follow-up hardening commit closed three deferred decision areas (search-budget
enforcement, scenario forwarding, sources→category routing) with three more behavior-level
tests. Verified by applying each retained mutant's `show-diffs` diff in a scratch worktree
against the corresponding test, the budget test KILLS only search `mutmut_7` (the per-request
budget check `>=` → `>`); the outcome-literal survivors `mutmut_8/9/10` (`outcome =
"rate_limited"` → `None` / `"XX…"` / `"RATE_LIMITED"`), `mutmut_12` (the budget `details={…}`
field → `None`), and `mutmut_39` (`"pageno"` → `"PAGENO"`) all SURVIVE the budget/scenario
tests (the budget test passes under 8/9/10/12; the scenario test passes under 39). The
scenario and sources-routing tests add behavior-level coverage of those decision areas but do
NOT kill these cosmetic survivors, which remain correctly triaged as survived
(invalid/equivalent) in `classification.md` / `triage.md`.

## Independent Verification

**Verifier:** F3 worker session (`429a10dc-28cb-4fde-9d75-419eb761a7ee`) — a **different
session from the test author** (F2 worker who added the hardened tests). All three reruns
below executed in a **fresh context**: a clean detached-HEAD git worktree
`/private/tmp/groktocrawl-572-f3-verify` at branch tip `dda07ec`, with `uv sync --locked
--no-dev --group fast-tests` provisioning its own environment. Every pytest invocation set
a scratch `QA_OUTCOME_PATH` (`/tmp/qa-f3-*.json`), `-o "addopts="`, and
`-p no:cacheprovider`.

1. **Baseline slice** (hermetic, no fixture/network):

   ```
   $ QA_OUTCOME_PATH=/tmp/qa-f3-baseline.json PYTHONPATH=agent-svc:scraper-svc:llm-svc:slopsearx-fixture:parse-svc:portal-svc:browser-svc:semantic-svc:. \
       uv run --no-sync pytest tests/service/test_searxng_client.py -o "addopts=" -p no:cacheprovider
   collected 30 items
   tests/service/test_searxng_client.py ............            [100%]
   QA outcomes: passed=30, failed=0, skipped=0, xfailed=0, xpassed=0
   ============================ 30 passed in 0.39s ============================
   ```

   Result: **30 passed** (exit 0).

2. **Candidate tests** (the two Retry-After boundary tests):

   ```
   $ QA_OUTCOME_PATH=/tmp/qa-f3-candidate.json PYTHONPATH=agent-svc:scraper-svc:llm-svc:slopsearx-fixture:parse-svc:portal-svc:browser-svc:semantic-svc:. \
       uv run --no-sync pytest tests/service/test_searxng_client.py \
         -k "parse_retry_after_zero or parse_retry_after_fractional" -o "addopts=" -p no:cacheprovider
   collected 30 items / 28 deselected / 2 selected
   tests/service/test_searxng_client.py ..                        [100%]
   QA outcomes: passed=2, failed=0
   ==================== 2 passed, 28 deselected in 0.04s ====================
   ```

   Result: **2 passed** (exit 0).

3. **Exact retained-mutant kill** (apply → observe failure → revert, in the scratch
   worktree only):

   - Applied `mutmut_7` (`seconds < 0` → `seconds <= 0`, line 77):
     `test_parse_retry_after_zero_seconds` → `AssertionError: assert None == 0.0`
     (**1 failed**).
   - Applied `mutmut_8` (`seconds < 0` → `seconds < 1`): both new tests fail —
     `assert None == 0.0` and `assert None == 0.5` (**2 failed**).
   - Reverted: `agent-svc/agent/searxng_client.py` byte-identical to `origin/main`
     (sha256 `43665df8a9aa73f138e43e7f09706fa1f1c05e10bc2289abc5f49330a39e5a73` ==
     `git show origin/main:agent-svc/agent/searxng_client.py | sha256sum`); worktree clean.

   All three steps reproduced the recorded outcomes.

## Decision

**Defer** recurring mutation CI. See `recommendation.md` for the full cost + failure-handling
evidence; ADR-0057 records the same stance. The pilot's unit oracle is the correct boundary
for this decision slice (the HTTP/twin boundary distinguishes the retained `_parse_retry_after`
gaps — demonstrated in `triage.md` STAGE 3 — but the committed hermetic slice stays unit-level).
