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
    RETRY_CLASS_RATE_LIMITED,
    Sample,
    compute_summary,
    main,
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


def test_main_rejects_non_positive_runs(monkeypatch, capsys):
    import io

    for bad in (0, -1, -5):
        err = io.StringIO()
        monkeypatch.setattr(sys, "stderr", err)
        code = main(["--runs", str(bad), "--json"])
        assert code == 2
        out = err.getvalue()
        assert "error: --runs must be >= 1" in out
        assert "Traceback" not in out


def test_main_rejects_non_positive_runs_even_with_dry_run(monkeypatch, capsys):
    import io

    err = io.StringIO()
    monkeypatch.setattr(sys, "stderr", err)
    code = main(["--runs", "0", "--dry-run"])
    assert code == 2
    assert "error: --runs must be >= 1" in err.getvalue()
    assert "Traceback" not in err.getvalue()


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


def test_rate_limited_samples_are_excluded_from_latency_distributions():
    """ADR-0053 AC-004.4: throttling must never look like operation latency."""

    def fake_runner(_fixture):
        return Sample(latency=0.2, status=200, retry_class=None)

    def rate_limited_runner(_fixture):
        return Sample(latency=60.0, status=429, retry_class=RETRY_CLASS_RATE_LIMITED)

    normal = run_benchmarks(
        fake_runner, FIXTURES, runs=3, commit_sha="abc", config_class="default"
    )
    throttled = run_benchmarks(
        rate_limited_runner, FIXTURES, runs=3, commit_sha="abc", config_class="default"
    )

    for result in throttled["results"]:
        # Status and retry classification are recorded per iteration...
        assert result["status_counts"] == {"429": 3}
        assert result["retry_class_counts"] == {RETRY_CLASS_RATE_LIMITED: 3}
        # ...but rate-limited samples are excluded from the distributions.
        assert result["p50"] is None
        assert result["p95"] is None
    for result in normal["results"]:
        assert result["status_counts"] == {"200": 3}
        assert result["p50"] is not None


def test_mixed_samples_keep_healthy_latencies():
    import itertools

    samples = itertools.cycle(
        [
            Sample(latency=0.1, status=429, retry_class=RETRY_CLASS_RATE_LIMITED),
            Sample(latency=0.5, status=200, retry_class=None),
        ]
    )
    baseline = run_benchmarks(
        lambda f: next(samples), FIXTURES, runs=2, commit_sha="abc", config_class="x"
    )
    result = baseline["results"][0]
    assert result["p50"] == 0.5
    assert result["samples"] == [0.1, 0.5]
    assert result["status_counts"] == {"200": 1, "429": 1}


def test_float_runner_remains_backward_compatible():
    import itertools

    latencies = itertools.cycle([0.1, 0.2])

    def float_runner(_fixture):
        return next(latencies)

    baseline = run_benchmarks(
        float_runner, FIXTURES, runs=2, commit_sha="abc", config_class="x"
    )
    result = baseline["results"][0]
    # p50 over [0.1, 0.2] interpolates to 0.15; p95 to 0.195.
    assert result["p50"] == 0.15
    assert result["p95"] == 0.195
    assert result["status_counts"] == {}  # unknown → omitted
