"""Regression tests for the stdlib-only benchmark harness.

Runs the harness core against a deterministic fake runner (no Docker) and
validates percentile correctness, artifact schema, and the absence of
deployment-specific identifiers in the checked-in baseline shape.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.run_benchmarks import (
    FIXTURES,
    compute_summary,
    percentile,
    run_benchmarks,
    sanitise_baseline,
)


def test_percentile_linear_interpolation():
    samples = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert percentile(sorted(samples), 50.0) == 3.0
    assert percentile(sorted(samples), 95.0) == 4.8
    assert percentile([7.0], 95.0) == 7.0


def test_compute_summary_orders_percentiles():
    summary = compute_summary([10.0, 1.0, 5.0, 2.0, 9.0])
    assert summary["p50"] <= summary["p95"]


def test_run_benchmarks_builds_portable_baseline():
    latencies = iter([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7])

    def fake_runner(_fixture):
        return next(latencies)

    baseline = run_benchmarks(
        fake_runner, FIXTURES, runs=1, commit_sha="abc123", config_class="default"
    )

    assert baseline["schema_version"] == 1
    assert baseline["commit_sha"] == "abc123"
    assert baseline["config_class"] == "default"
    assert baseline["runs"] == 1
    assert len(baseline["results"]) == len(FIXTURES)
    kinds = {r["kind"] for r in baseline["results"]}
    assert {
        "cold_scrape",
        "warm_scrape",
        "lightweight_fetch",
        "browser_fallback",
        "answer",
        "agent_research",
        "batch_scrape",
    } <= kinds
    for result in baseline["results"]:
        assert result["p50"] <= result["p95"]
        assert "fixture" in result
        assert "samples" in result


def test_sanitise_baseline_removes_deployment_identifiers():
    dirty = {
        "schema_version": 1,
        "commit_sha": "abc123",
        "hostname": "worker-01.internal",
        "results": [{"fixture": "answer", "ip": "10.0.0.5", "p50": 0.1}],
    }
    cleaned = sanitise_baseline(dirty)
    assert "hostname" not in cleaned
    assert "ip" not in cleaned["results"][0]
    assert cleaned["commit_sha"] == "abc123"
