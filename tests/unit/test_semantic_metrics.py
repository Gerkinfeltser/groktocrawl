"""Tests for the semantic-svc OpenMetrics renderer."""

import importlib.util
import re
from pathlib import Path


def _load_semantic_metrics():
    """Load semantic-svc's metrics module without colliding with common.metrics."""
    path = Path(__file__).parents[2] / "semantic-svc" / "metrics.py"
    spec = importlib.util.spec_from_file_location("semantic_svc_metrics", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_openmetrics_samples_omit_timestamps_and_end_with_eof() -> None:
    metrics = _load_semantic_metrics()
    collector = metrics.MetricsCollector()
    collector.counter("requests_total", "Requests", ["endpoint"]).inc(
        {"endpoint": "semantic api"}, value=2
    )
    collector.histogram(
        "latency_seconds", "Latency", ["operation"], buckets=[1.0]
    ).observe({"operation": "vector search"}, 0.5)
    collector.gauge("workers", "Workers", ["pool"]).set(
        {"pool": "background workers"}, value=3
    )

    output = collector.generate_openmetrics()
    sample_lines = [
        line for line in output.splitlines() if line and not line.startswith("#")
    ]

    assert any(
        line.startswith('requests_total{endpoint="semantic api"} ')
        for line in sample_lines
    )
    assert any(
        line.startswith('latency_seconds_bucket{operation="vector search",le="1.0"} ')
        for line in sample_lines
    )
    assert any(
        line.startswith('workers{pool="background workers"} ') for line in sample_lines
    )

    sample_line_pattern = re.compile(
        r'^[a-zA-Z_:][a-zA-Z0-9_:]*(?:\{[a-zA-Z_][a-zA-Z0-9_]*="(?:\\.|[^"\\])*"'
        r'(?:,[a-zA-Z_][a-zA-Z0-9_]*="(?:\\.|[^"\\])*")*\})? [^\s]+$'
    )
    assert all(sample_line_pattern.fullmatch(line) for line in sample_lines)
    assert output.rstrip().endswith("# EOF")
