# Grounded Answer & Research Evaluation Harness (issue #570)

A versioned, deterministic, fixture-driven evaluation harness that measures
whether GroktoCrawl's `/v2/answer` core and the `run_research` core that backs
`/v2/agent` actually
ground their answers in their cited sources, and abstain/degrade appropriately on
insufficient or contradictory evidence.

It is **separate from the lower-level fixture contract tests**
(`tests/service/test_slopsearx_fixture.py`, `test_llm_tcp_contract.py`,
`test_twin_contract.py`): those verify protocol shape and scenario behavior,
while this harness grades the *end-to-end grounded answer* against pinned
fixture content.

## Layout

```
evals/answer_evals/
  manifest.json       # suite version, schema version, provenance rules, ratio rule
  cases/              # versioned cases (stable id + content_hash)
  baselines/
    narrow.json       # pinned pre-merge baseline
    broad.json        # pinned nightly/manual baseline
    candidate/        # --record-baseline writes here ONLY, never to the pinned files
  harness.py          # runner + corpus validation + baseline comparison
  grading.py          # deterministic, stdlib-only mechanical graders
  provenance.py       # allowlisted run provenance assembly
  routing.py          # in-process fixture scenario routing (search + LLM)
```

## Usage

```bash
# Validates hashes, fixture version pins, and the negative-case ratio only.
python3 scripts/run_answer_evals.py --selection broad --dry-run

# Run the bounded pre-merge subset.
python3 scripts/run_answer_evals.py --selection narrow

# Run the full nightly suite, restricting to the research path, JSON output.
python3 scripts/run_answer_evals.py --selection broad --target research --json

# Write the observed outcomes as a CANDIDATE baseline (never the pinned file).
python3 scripts/run_answer_evals.py --selection narrow --record-baseline

# Compose lane: in-process selection + one real-route /v2/answer smoke.
python3 scripts/run_answer_evals.py --selection narrow \
  --http-smoke http://127.0.0.1:8084
```

Environment: the usual repo `PYTHONPATH` (`agent-svc:scraper-svc:llm-svc:
slopsearx-fixture:parse-svc:portal-svc:browser-svc:semantic-svc:.`), run with
`uv run --no-sync`. No Docker is required for the harness itself — it drives the
real answer/research pipeline in-process against the deterministic twins and a
harness-local scrape stub.

## How cases route to fixtures

Per-case scenario routing is **not** feasible through the HTTP `/v2/answer`
boundary (scenario params are not forwarded and `LLM_BASE_URL` is process-wide).
The harness therefore drives the real `run_answer` / `run_research` pipeline
in-process, constructing `SearXNGClient` (forcing the case's search scenario)
and `LLMClient` (scenario path/query) against the fixture apps — exactly as the
existing fixture contract tests do. It then asserts, via the search fixture's
**ledger** and the LLM fixture's **diagnostics**, that the requested scenarios
were actually exercised (a scenario-less default leak fails the case).

Scraping is served by a tiny in-process `POST /scrape` stub that returns each
case's pinned `source_content`, so the harness is hermetic and Docker-free. The
Compose lane additionally runs **one HTTP `/v2/answer` smoke** over the real
route (agent-svc-fixture) as a boundary check.

## What is mechanically graded (vs unverified)

Mechanically graded, deterministically, over the fixture outputs:

- **Protocol validity** — per-case expected status/success (`200`, or `429` /
  `503` for provider-failure cases).
- **Source presence & allowability** — non-empty, unique, and within
  `allowable_source_urls`.
- **Citation index ↔ URL ↔ source consistency** — every citation index maps to
  the indexed returned source (inline) or `[N](url)` marker (compact).
- **Citation-to-fixture-content support** — a declared claim's citation index
  resolves to the exact `source_url`, the `answer_span` appears in the answer,
  and the `evidence_span` appears in that source's **pinned content**.
  A deliberately mis-cited negative case (`negative-005-answer-miscited`) is
  pinned to FAIL this grader — it proves the grader is not vacuous.
- **Required/prohibited claims** — presence/absence of the pinned claim strings.
- **Abstention / degradation** — empty-search (insufficient evidence) and
  contradictory-sources (qualification/abstention) cases must abstain on the
  deterministic fixtures.
- **Citation integrity** — no `[N]` marker is out of range or unmapped to a
  returned source.

Explicitly **not mechanically graded** (unverified by this harness):

- General answer factual quality beyond the pinned fixture claims.
- LLM reasoning quality.
- Real-provider grounding (the fixtures are deterministic twins).

An optional calibrated LLM judge is a documented follow-up, not part of this
harness. No scalar LLM-judge score is a release oracle here.

## Failure artifacts

Every evaluated failure writes a structured artifact, including content-hash or
case-schema validation failures, selection deadlines, transport/timeouts, grader
exceptions, scenario-use mismatches, and baseline mismatches. A case artifact
always contains the full case ID, expected constraint, observed outcome, and its
own `artifact_path`. Baseline mismatch artifacts use case ID `__baseline__` and
preserve the expected baseline selection/version plus the observed diff.

## Baseline policy

- `baselines/narrow.json` and `baselines/broad.json` are **pinned, canonical**
  artifacts. The harness compares candidate case outcomes against them,
  excluding volatile fields (`timestamp`, `run_id`, `latency_ms`,
  `artifact_path`, `recorded_at`). A mismatch fails the run with a diff.
- The harness **never** auto-replaces a baseline. `--record-baseline` writes
  only to `baselines/candidate/`. Promoting a candidate into the pinned file is
  a separate, separately authorized source-control step after human review.
- The pre-merge narrow suite (`positive-001-answer-grounded`,
  `positive-003-research-grounded`, `negative-006-answer-empty-search`) is
  bounded and deterministic; the broad suite runs nightly/manual and is
  advisory (see `.github/workflows/answer-evals.yml`).

## Privacy

Each run writes a **provenance** JSON document containing only an allowlisted
schema: run id, timestamp, commit sha, suite version, selection, and per-case
case id/path + canonical request hash, fixture scenario/schema/fixture
versions, parsed model id and base-URL **host only**, grader id/version,
verdicts, outcome, and artifact path.

Prompts, queries, answers, headers, URL query strings/userinfo, environment
  dumps, and arbitrary configuration are **never serialized** in provenance or
  per-case artifacts; per-case artifacts contain only summarized observed
  outcomes (counts, protocol, and safe classifications). Secret-like values are
  redacted (`sanitize()`), and `validate_allowlist()` fails closed if a
  non-allowlisted key ever appears. Provenance never writes or replaces the
  pinned baseline.

## Negative-case rationale

At least 20% of the corpus is `kind: negative` or abstention-required, so the
suite proves the abstention/degradation paths are exercised, not just the happy
path:

- `negative-006-answer-empty-search` — real no-context abstention
  (`zero-results` search scenario).
- `negative-007-answer-contradictory` / `negative-008-research-contradictory` —
  abstention caused by **genuinely contradictory retrieved evidence**
  (`contradictory-sources` search + `contradictory-evidence` LLM).
- `negative-005-answer-miscited` — a deliberately mis-cited claim whose
  `check_citation_support` verdict is pinned to **fail**, proving the grader
  detects citation-vs-source mismatch.

Boundary cases count as non-negative for the ratio denominator.

## Fixture-enhancement note

To satisfy the grounding and abstention criteria, the source-owned twins were
extended **additively and deterministically** (no existing scenario behavior
changed, live provider boundaries untouched):

- `llm-svc`: new `grounded-answer` (emits a known fixture fact with a `[1]`
  citation), `contradictory-evidence` (qualifies/abstains on conflicting
  context), and `miscited` (cites the wrong index) scenarios. `FIXTURE_VERSION`
  remains `v2`, `SCHEMA_VERSION` stays `v1`.
- `slopsearx-fixture`: new `contradictory-sources` scenario returning two
  deterministic fixture pages with conflicting claims. `FIXTURE_VERSION` is
  `v2`; `SCHEMA_VERSION` remains `v1`.
- `test-site`: new `/pricing-v2` page ("Pro: $99") that genuinely conflicts
  with `/pricing` ("Pro: $10").

## CI

- **Pre-merge** (`.github/workflows/docker.yml` Integration Tests lane): a
  bounded narrow in-process eval plus one HTTP `/v2/answer` smoke over
  agent-svc-fixture, hard timeout, endpoint-host allowlist preflight, gated by
  the runtime/twin classifier and the existing fork guard.
- **Nightly/manual** (`.github/workflows/answer-evals.yml`): broad suite on the
  self-hosted fixture stack, schedule + `workflow_dispatch`, **no PR trigger**,
  advisory (never a required PR check), uploads the provenance artifact.
