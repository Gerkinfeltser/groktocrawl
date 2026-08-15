# GroktoCrawl performance benchmarks

Stdlib-only, deterministic performance harness for the paths exercised by the
performance sprint. It produces the evidence used to gate future
browser-process-reuse and adapter-investment decisions (see ADR-0048).

## Usage

```bash
# Print the plan without executing (validates the fixture matrix and schema)
python benchmarks/run_benchmarks.py --dry-run
```

`--runs` controls repetitions per fixture (default 3). `--config-class` labels
the hardware/config cohort (default `default`). `--json` prints the artifact to
stdout in addition to writing it.

**The live-stack run is not functional out of the box.** `StackRunner` is a
placeholder and is intentionally left unwired: running the CLI in live mode
exits with a clear error (non-zero, no traceback) until you implement
`StackRunner.__call__` for your deployment and set `StackRunner.wired = True`.

```bash
# NOT runnable until StackRunner is wired for a live deployment.
python benchmarks/run_benchmarks.py --runs 5 --json
```

The harness core (`run_benchmarks`) accepts any `runner(fixture) -> float`
callable, so the service test suite can exercise it deterministically without
Docker (`tests/service/test_benchmark_harness.py`). The percentile math
(`percentile`, `compute_summary`) and baseline-writing/sanitisation logic are
real and fully covered by those tests.

## Fixtures

| Fixture | Kind | Purpose |
|---|---|---|
| cold scrape | `cold_scrape` | scrape a URL with an empty scrape cache |
| warm scrape | `warm_scrape` | scrape a URL already present in the scrape cache |
| lightweight fetch | `lightweight_fetch` | tier 1/2 fetch (llms.txt / content negotiation) |
| browser fallback | `browser_fallback` | tier 3 Playwright render fallback |
| answer | `answer` | grounded Q&A (`/v2/answer`) |
| agent research | `agent_research` | multi-stage research loop (`/v2/agent`) |
| batch scrape | `batch_scrape` | concurrent multi-URL scrape |

## Baseline artifact schema

Each artifact in `benchmarks/baselines/` is JSON with:

```json
{
  "schema_version": 1,
  "commit_sha": "<git sha>",
  "config_class": "<cohort label>",
  "runs": 3,
  "results": [
    {
      "fixture": "answer",
      "kind": "answer",
      "runs": 3,
      "p50": 0.62,
      "p95": 0.98,
      "samples": [0.61, 0.62, 0.98]
    }
  ]
}
```

`p50`/`p95` are derived with stdlib `statistics`-style linear interpolation over
the raw samples. Artifacts must never contain deployment identifiers (hostname,
IP, machine, node, or pod values); the harness strips these via
`sanitise_baseline`.

## Hybrid retrieval old-vs-new comparison

`scripts/benchmark_hybrid_retrieval.py` compares the pre-#532 sequential
web-first `hybrid_vector` merge against the #532 concurrent, floor-guaranteed
blend across four dimensions — latency, source diversity (Qdrant-only
candidates that survive), citation validity, and answer quality (recall@k proxy).
It is a deterministic, stdlib-only, in-process simulation (no Docker), so it is
runnable anywhere:

```bash
python scripts/benchmark_hybrid_retrieval.py --runs 5
python scripts/benchmark_hybrid_retrieval.py --runs 5 --json
```

The results demonstrate the structural change (concurrent latency is the max of
the two branches rather than their sum, and a Qdrant-only candidate can enter a
full web budget) but are **not** a live-stack benchmark and make **no universal
quality claim from a single run** — the metrics are structural proxies, and real
latency/diversity/citation/answer-quality numbers require the live Docker stack
plus an LLM-judge harness (documented follow-up, consistent with #528).
