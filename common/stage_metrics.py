"""Shared stage-metric helpers for bounded-cardinality instrumentation.

All GroktoCrawl services record stage-level latency and capacity signals
through these helpers so metric registration stays consistent and free of
copy-paste drift (see ADR for stage-level telemetry).

Label values are always enum-like constants — never raw URLs, tokens, or
free-form content — keeping cardinality bounded.
"""

from __future__ import annotations

import time

from common.metrics import METRICS


def observe_histogram(
    name: str,
    help_text: str,
    labels: dict[str, str],
    value: float,
) -> None:
    """Observe a value on a labeled histogram."""
    METRICS.histogram(name, help_text, sorted(labels)).observe(labels, value)


def observe_elapsed(
    name: str,
    help_text: str,
    labels: dict[str, str],
    start: float,
) -> None:
    """Observe ``time.monotonic() - start`` on a labeled histogram."""
    observe_histogram(name, help_text, labels, time.monotonic() - start)


def inc_counter(name: str, help_text: str, labels: dict[str, str]) -> None:
    """Increment a labeled counter by one."""
    METRICS.counter(name, help_text, sorted(labels)).inc(labels)


def set_gauge(
    name: str,
    help_text: str,
    labels: dict[str, str],
    value: float,
) -> None:
    """Set a labeled gauge to an absolute value."""
    METRICS.gauge(name, help_text, sorted(labels)).set(labels, value)


_TTFB_SECONDS = "groktocrawl_time_to_first_event_seconds"
_TTFB_SECONDS_HELP = "Time to first SSE event by stream type"
_TTFT_SECONDS = "groktocrawl_time_to_first_token_seconds"
_TTFT_SECONDS_HELP = "Time to first answer token by stream type"


class StreamTiming:
    """Measure time-to-first-event and time-to-first-token for one SSE stream.

    Instantiate at the top of an async generator body (which runs on first
    ``__anext__``, matching "generator body entry" rather than
    ``StreamingResponse`` construction) and call :meth:`on_first_event`
    before the first yielded event and :meth:`on_first_token` before the
    first token event.
    """

    def __init__(self, stream_type: str) -> None:
        self._stream_type = stream_type
        self._started = time.monotonic()
        self._first_event_sent = False
        self._first_token_sent = False

    def on_first_event(self) -> None:
        if self._first_event_sent:
            return
        self._first_event_sent = True
        observe_elapsed(
            _TTFB_SECONDS,
            _TTFB_SECONDS_HELP,
            {"stream_type": self._stream_type},
            self._started,
        )

    def on_first_token(self) -> None:
        self.on_first_event()
        if self._first_token_sent:
            return
        self._first_token_sent = True
        observe_elapsed(
            _TTFT_SECONDS,
            _TTFT_SECONDS_HELP,
            {"stream_type": self._stream_type},
            self._started,
        )
