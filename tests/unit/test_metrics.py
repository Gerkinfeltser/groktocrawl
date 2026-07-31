"""Tests for the shared OpenMetrics exporter."""

from common.metrics import MetricsCollector


def test_openmetrics_samples_omit_timestamps_and_end_with_eof() -> None:
    collector = MetricsCollector()
    collector.counter("requests_total", "Requests").inc(value=2)
    collector.histogram("latency_seconds", "Latency", buckets=[1.0]).observe(value=0.5)
    collector.gauge("workers", "Workers").set(value=3)

    output = collector.generate_openmetrics()
    sample_lines = [
        line for line in output.splitlines() if line and not line.startswith("#")
    ]

    assert any(line.startswith("requests_total ") for line in sample_lines)
    assert any(line.startswith("latency_seconds_bucket") for line in sample_lines)
    assert any(line.startswith("workers ") for line in sample_lines)
    assert all(len(line.split()) == 2 for line in sample_lines)
    assert output.rstrip().endswith("# EOF")
