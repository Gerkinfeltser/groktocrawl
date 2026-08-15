"""Worker job-time retry behavior tests (ADR-0053, US-003).

Exercises ``_run_job_with_observability`` with a fake store, a patched
cancellable sleep, and the shared in-memory metrics collector: retry
scheduling → resume → completion, retry-budget exhaustion, cancellation
while waiting, single retry event per attempt, and metric counts without
double counting.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from agent.exceptions import RetryableRateLimitError
from agent.retry import RetryPolicy
from agent.worker import _run_job_with_observability


class FakeStore:
    """In-memory JobStore stand-in recording transitions."""

    def __init__(self):
        self.status = "processing"
        self.completed_data = None
        self.failed_error = None
        self.scheduled = []
        self.retry_metadata = None

    def complete_job(self, job_id: str, data: dict) -> None:
        self.status = "completed"
        self.completed_data = data

    def fail_job(self, job_id: str, error: str) -> None:
        self.status = "failed"
        self.failed_error = error

    def schedule_retry(self, job_id: str, **kwargs) -> bool:
        self.scheduled.append(kwargs)
        self.retry_metadata = kwargs
        self.status = "retry_scheduled"
        return True

    def resume_retry(self, job_id: str) -> bool:
        if self.status != "retry_scheduled":
            return False
        self.status = "processing"
        return True


class BlockingStore(FakeStore):
    """Fake store simulating a job cancelled while waiting to retry."""

    def __init__(self):
        super().__init__()
        self.status = "cancelled"

    def resume_retry(self, job_id: str) -> bool:
        # A concurrent DELETE marked the job cancelled: the retry wakeup
        # must not resume it.
        self.status = "cancelled"
        return False


_POLICY = RetryPolicy(max_attempts=3, fallback_seconds=1.0, max_wait_seconds=60.0)


def _metric(name: str) -> float:
    from agent.metrics import METRICS

    text = METRICS.generate_openmetrics()
    for line in text.splitlines():
        if line.startswith(name):
            return float(line.rsplit(" ", 1)[1])
    return 0.0


def _record_webhooks(webhooks: list):
    """Return an AsyncMock side_effect capturing ``(args, kwargs)`` pairs."""

    def _capture(*args, **kwargs):
        webhooks.append((args, kwargs))

    return _capture


def _event_data(entry: tuple) -> tuple[str, str, dict | None]:
    """Normalize a captured webhook call into (event, job_id, data).

    ``data`` may arrive positionally (completed/failed) or as a keyword
    (retry_scheduled).
    """
    args, kwargs = entry
    event = args[1]
    job_id = args[2]
    data = kwargs.get("data") if len(args) <= 3 else args[3]
    return event, job_id, data


@pytest.fixture(autouse=True)
def _patch_sleep():
    """Never sleep for real; record requested delays."""
    calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        calls.append(delay)

    with patch("agent.worker.retry_sleep", fake_sleep) as patched:
        patched.calls = calls
        yield patched


class TestRetrySuccess:
    @pytest.mark.asyncio
    async def test_retry_then_complete(self, _patch_sleep):
        store = FakeStore()
        webhooks = []
        with patch(
            "agent.worker.deliver_webhook",
            new=AsyncMock(side_effect=_record_webhooks(webhooks)),
        ):
            attempts = {"n": 0}

            async def work_fn():
                attempts["n"] += 1
                if attempts["n"] == 1:
                    raise RetryableRateLimitError(
                        "downstream capacity", retry_after_seconds=37
                    )
                return {"result": "ok"}

            scheduled_before = _metric('job_retries_scheduled_total{type="agent"}')
            succeeded_before = _metric('job_retries_succeeded_total{type="agent"}')
            failed_before = _metric('jobs_failed_total{type="agent"}')
            completed_before = _metric('jobs_completed_total{type="agent"}')

            await _run_job_with_observability(
                "job_1", "agent", store, None, work_fn, retry_policy=_POLICY
            )

        assert attempts["n"] == 2
        assert store.status == "completed"
        assert store.completed_data == {"result": "ok"}
        assert len(store.scheduled) == 1
        assert store.scheduled[0]["retry_attempt"] == 1
        assert store.scheduled[0]["retry_limit"] == 3
        assert store.scheduled[0]["reason"] == "RATE_LIMITED"
        assert store.scheduled[0]["retry_after_seconds"] == 37
        assert _patch_sleep.calls == [37.0]
        # One retry_scheduled webhook event, no terminal event.
        retry_events = [
            _event_data(w) for w in webhooks if _event_data(w)[0] == "retry_scheduled"
        ]
        assert len(retry_events) == 1
        event, job_id, payload = retry_events[0]
        assert event == "retry_scheduled"
        assert job_id == "job_1"
        assert payload["operation"] == "agent"
        assert payload["reason_code"] == "RATE_LIMITED"
        assert payload["retry_attempt"] == 1
        # Metrics: scheduled +1, succeeded +1, completed +1, failed +0.
        assert (
            _metric('job_retries_scheduled_total{type="agent"}') == scheduled_before + 1
        )
        assert (
            _metric('job_retries_succeeded_total{type="agent"}') == succeeded_before + 1
        )
        assert _metric('jobs_completed_total{type="agent"}') == completed_before + 1
        assert _metric('jobs_failed_total{type="agent"}') == failed_before


class TestRetryExhaustion:
    @pytest.mark.asyncio
    async def test_exhaustion_fails_with_rate_limit_details(self, _patch_sleep):
        store = FakeStore()
        webhooks = []
        with patch(
            "agent.worker.deliver_webhook",
            new=AsyncMock(side_effect=_record_webhooks(webhooks)),
        ):

            async def work_fn():
                raise RetryableRateLimitError(
                    "downstream capacity", retry_after_seconds=10
                )

            exhausted_before = _metric('job_retry_exhaustion_total{type="agent"}')
            failed_before = _metric('jobs_failed_total{type="agent"}')

            await _run_job_with_observability(
                "job_1", "agent", store, None, work_fn, retry_policy=_POLICY
            )

        # 3 total attempts: 2 scheduled retries, then terminal failure.
        assert len(store.scheduled) == 2
        assert len(_patch_sleep.calls) == 2
        assert store.status == "failed"
        assert store.failed_error is not None
        assert "RATE_LIMITED" in store.failed_error
        assert "3 attempt" in store.failed_error
        assert "10s" in store.failed_error  # last retry delay reported
        # Exactly one terminal failure event; no retry_scheduled for the
        # final attempt.
        failed_events = [w for w in webhooks if _event_data(w)[0] == "failed"]
        retry_events = [w for w in webhooks if _event_data(w)[0] == "retry_scheduled"]
        assert len(failed_events) == 1
        assert len(retry_events) == 2
        assert (
            _metric('job_retry_exhaustion_total{type="agent"}') == exhausted_before + 1
        )
        assert _metric('jobs_failed_total{type="agent"}') == failed_before + 1

    @pytest.mark.asyncio
    async def test_non_retryable_exception_fails_immediately(self):
        store = FakeStore()
        webhooks = []
        with patch(
            "agent.worker.deliver_webhook",
            new=AsyncMock(side_effect=_record_webhooks(webhooks)),
        ):

            async def work_fn():
                raise RuntimeError("boom")

            await _run_job_with_observability(
                "job_1", "agent", store, None, work_fn, retry_policy=_POLICY
            )

        assert store.status == "failed"
        assert store.failed_error == "boom"
        assert store.scheduled == []  # never scheduled a retry


class TestCancellation:
    @pytest.mark.asyncio
    async def test_cancel_while_waiting_prevents_next_attempt(self, _patch_sleep):
        store = BlockingStore()
        webhooks = []
        with patch(
            "agent.worker.deliver_webhook",
            new=AsyncMock(side_effect=_record_webhooks(webhooks)),
        ):
            attempts = {"n": 0}

            async def work_fn():
                attempts["n"] += 1
                raise RetryableRateLimitError("downstream capacity")

            await _run_job_with_observability(
                "job_1", "agent", store, None, work_fn, retry_policy=_POLICY
            )

        # Exactly one attempt: the retry was scheduled but the job was
        # cancelled while waiting, so no second attempt ever started.
        assert attempts["n"] == 1
        assert len(store.scheduled) == 1
        assert store.status == "cancelled"
        assert store.failed_error is None
        retry_events = [w for w in webhooks if _event_data(w)[0] == "retry_scheduled"]
        assert len(retry_events) == 1

    @pytest.mark.asyncio
    async def test_task_cancel_during_wait_records_cancelled(self, _patch_sleep):
        store = FakeStore()

        async def work_fn():
            raise RetryableRateLimitError("downstream capacity")

        async def cancelling_sleep(delay: float) -> None:
            raise asyncio.CancelledError

        with (
            patch("agent.worker.retry_sleep", cancelling_sleep),
            patch("agent.worker.deliver_webhook", new=AsyncMock()),
        ):
            with pytest.raises(asyncio.CancelledError):
                await _run_job_with_observability(
                    "job_1", "agent", store, None, work_fn, retry_policy=_POLICY
                )

        # Task cancellation propagates for cleanup: the job was scheduled
        # for retry but never resumed and never failed. (In production the
        # DELETE handler marks the store cancelled before cancelling the
        # task.)
        assert len(store.scheduled) == 1
        assert store.status == "retry_scheduled"
        assert store.failed_error is None
