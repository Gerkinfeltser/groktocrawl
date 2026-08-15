#!/usr/bin/env python3
"""Deterministic, stdlib-only performance benchmark harness for GroktoCrawl.

Runs each fixture N times against a live stack (or a caller-supplied runner),
records raw latency samples, derives p50/p95 percentiles with stdlib
``statistics``, and writes a baseline artifact that contains no
deployment-specific identifiers (no hostname, IP, or machine values).

Usage::

    python benchmarks/run_benchmarks.py --runs 5 --json
    python benchmarks/run_benchmarks.py --dry-run

The harness is intentionally dependency-free so it can be exercised by the
service test suite without Docker (see ``tests/service/test_benchmark_harness.py``).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_DIR = REPO_ROOT / "benchmarks" / "baselines"


@dataclass(frozen=True)
class BenchmarkFixture:
    """A single measured path with a bounded, machine-readable kind."""

    name: str
    kind: str


FIXTURES: tuple[BenchmarkFixture, ...] = (
    BenchmarkFixture("cold scrape", "cold_scrape"),
    BenchmarkFixture("warm scrape", "warm_scrape"),
    BenchmarkFixture("lightweight fetch", "lightweight_fetch"),
    BenchmarkFixture("browser fallback", "browser_fallback"),
    BenchmarkFixture("answer", "answer"),
    BenchmarkFixture("agent research", "agent_research"),
    BenchmarkFixture("batch scrape", "batch_scrape"),
)

# Deployment identifiers that must never appear in a checked-in baseline.
_DEPLOYMENT_IDENTIFIER_KEYS = {"hostname", "host", "ip", "machine", "node", "pod"}


def percentile(sorted_samples: list[float], p: float) -> float:
    """Return the ``p``-th percentile (0-100) using linear interpolation.

    Uses the standard "closest ranks" method over an already-sorted list,
    which is deterministic and stdlib-only. Raises ``ValueError`` for an
    empty sample set.
    """
    if not sorted_samples:
        raise ValueError("cannot compute a percentile over zero samples")
    if p < 0 or p > 100:
        raise ValueError("percentile must be in the range [0, 100]")
    n = len(sorted_samples)
    if n == 1:
        return sorted_samples[0]
    rank = (p / 100.0) * (n - 1)
    lower = int(rank)
    upper = min(lower + 1, n - 1)
    weight = rank - lower
    return sorted_samples[lower] * (1.0 - weight) + sorted_samples[upper] * weight


def compute_summary(samples: list[float]) -> dict[str, float]:
    """Return p50 and p95 for the raw latency samples."""
    ordered = sorted(samples)
    return {
        "p50": round(percentile(ordered, 50.0), 6),
        "p95": round(percentile(ordered, 95.0), 6),
    }


def current_commit_sha() -> str:
    """Return the current git commit SHA (or a stable placeholder)."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return proc.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def build_baseline(
    commit_sha: str,
    config_class: str,
    runs: int,
    results: list[dict],
) -> dict:
    """Assemble the checked-in baseline artifact schema."""
    return {
        "schema_version": 1,
        "commit_sha": commit_sha,
        "config_class": config_class,
        "runs": runs,
        "results": results,
    }


def sanitise_baseline(baseline: dict) -> dict:
    """Return a copy of *baseline* with deployment identifiers removed."""
    cleaned = json.loads(json.dumps(baseline))

    def _scrub(obj):
        if isinstance(obj, dict):
            for key in list(obj.keys()):
                if key.lower() in _DEPLOYMENT_IDENTIFIER_KEYS:
                    obj.pop(key, None)
                else:
                    _scrub(obj[key])
        elif isinstance(obj, list):
            for item in obj:
                _scrub(item)

    _scrub(cleaned)
    return cleaned


def run_benchmarks(
    runner,
    fixtures: tuple[BenchmarkFixture, ...],
    runs: int,
    commit_sha: str,
    config_class: str,
) -> dict:
    """Execute each fixture ``runs`` times and return a baseline artifact dict.

    ``runner`` is any callable accepting a ``BenchmarkFixture`` and returning
    a latency in seconds (a real HTTP runner, or a deterministic fake in tests).
    """
    results: list[dict] = []
    for fixture in fixtures:
        samples = [float(runner(fixture)) for _ in range(runs)]
        summary = compute_summary(samples)
        results.append(
            {
                "fixture": fixture.name,
                "kind": fixture.kind,
                "runs": runs,
                "p50": summary["p50"],
                "p95": summary["p95"],
                "samples": [round(s, 6) for s in samples],
            }
        )
    return sanitise_baseline(build_baseline(commit_sha, config_class, runs, results))


class StackRunner:
    """Naive real-stack runner placeholder.

    Real stack interaction (search/scrape/answer endpoints) requires the
    full Docker compose stack and is intentionally left for operators to
    wire per deployment; the harness core remains deterministic and testable
    without Docker.

    Set ``wired = True`` after overriding :meth:`__call__` to point at a real
    deployment, or the CLI refuses to run live benchmarks (see ``main``).
    """

    wired: bool = False

    def __call__(self, fixture: BenchmarkFixture) -> float:
        raise NotImplementedError(
            "StackRunner requires a live deployment; wire your endpoint here"
        )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=3, help="runs per fixture")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the plan without executing or writing",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the baseline artifact as JSON to stdout",
    )
    parser.add_argument(
        "--config-class",
        default="default",
        help="configuration class label for the baseline",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    if args.runs < 1:
        print(
            f"error: --runs must be >= 1 (got {args.runs})",
            file=sys.stderr,
        )
        return 2

    commit_sha = current_commit_sha()

    if args.dry_run:
        plan = {
            "runs": args.runs,
            "config_class": args.config_class,
            "commit_sha": commit_sha,
            "fixtures": [f.name for f in FIXTURES],
            "baseline_dir": str(BASELINE_DIR),
        }
        print(json.dumps(plan, indent=2, sort_keys=True))
        return 0

    runner = StackRunner()
    if not runner.wired:
        print(
            "error: StackRunner is not wired for this deployment; "
            "implement StackRunner.__call__ (and set StackRunner.wired = True) "
            "to run live benchmarks.",
            file=sys.stderr,
        )
        return 2

    baseline = run_benchmarks(
        runner,
        FIXTURES,
        args.runs,
        commit_sha,
        args.config_class,
    )

    if args.json:
        print(json.dumps(baseline, indent=2, sort_keys=True))

    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = BASELINE_DIR / f"{commit_sha[:12]}-{args.config_class}-{stamp}.json"
    path.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n")
    print(f"wrote {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
