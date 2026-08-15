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


def test_timer_context_manager_observes_elapsed() -> None:
    collector = MetricsCollector()
    with collector.timer("stage_seconds", "Stage latency", {"stage": "plan"}):
        pass

    output = collector.generate_openmetrics()
    assert "# TYPE stage_seconds histogram" in output
    assert 'stage_seconds_count{stage="plan"}' in output
    assert 'stage_seconds_sum{stage="plan"}' in output


def test_timer_context_manager_observes_even_on_error() -> None:
    collector = MetricsCollector()
    try:
        with collector.timer("boom_seconds", "Boom", {"stage": "x"}):
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    output = collector.generate_openmetrics()
    assert 'boom_seconds_count{stage="x"} 1.0' in output


def test_gauge_inc_and_dec() -> None:
    collector = MetricsCollector()
    gauge = collector.gauge("active", "Active work", ["type"])
    gauge.inc({"type": "agent"})
    gauge.inc({"type": "agent"})
    gauge.dec({"type": "agent"})

    output = collector.generate_openmetrics()
    assert 'active{type="agent"} 1.0' in output


def test_gauge_dec_clamps_at_zero() -> None:
    collector = MetricsCollector()
    gauge = collector.gauge("active", "Active work", ["type"])
    gauge.inc({"type": "agent"})
    gauge.dec({"type": "agent"})
    gauge.dec({"type": "agent"})

    output = collector.generate_openmetrics()
    assert 'active{type="agent"} 0.0' in output
