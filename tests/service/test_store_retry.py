"""JobStore retry-state transition tests (ADR-0053).

Covers ``schedule_retry`` / ``resume_retry`` and the extended
``fail_job`` / ``cancel_job`` transitions from ``retry_scheduled``.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def fake_redis():
    """Return mocks that mimic Redis basic operations including scan/pipeline."""
    store_data = {}

    r = MagicMock()
    r.set = MagicMock(
        side_effect=lambda key, val, **kw: store_data.update({key: val}) or True
    )
    r.get = MagicMock(side_effect=lambda key: store_data.get(key))

    def _incr(key):
        current = store_data.get(key)
        if current is None:
            current = "0"
        new_val = str(int(current) + 1)
        store_data[key] = new_val
        return int(new_val)

    r.incr = MagicMock(side_effect=_incr)
    r.delete = MagicMock(side_effect=lambda key: store_data.pop(key, None) or True)
    r.scan = MagicMock(return_value=(0, []))
    r.pipeline = MagicMock(return_value=MagicMock())

    return r


@pytest.fixture
def store(fake_redis):
    from agent.store import JobStore

    s = JobStore(redis_url="redis://fake:6379/0")
    s.redis = fake_redis
    return s


def _meta(store, job_id) -> dict:
    raw = store.redis.get(f"job:{job_id}:meta")
    assert raw is not None
    return json.loads(raw)


class TestScheduleRetry:
    def test_processing_job_schedules_retry(self, store):
        job_id = store.create_job(kind="agent", payload={})
        ok = store.schedule_retry(
            job_id,
            retry_at="2026-08-15T16:01:37Z",
            retry_attempt=1,
            retry_limit=3,
            reason="RATE_LIMITED",
            retry_after_seconds=37,
        )
        assert ok is True
        meta = _meta(store, job_id)
        assert meta["status"] == "retry_scheduled"
        assert meta["retry_at"] == "2026-08-15T16:01:37Z"
        assert meta["retry_attempt"] == 1
        assert meta["retry_limit"] == 3
        assert meta["retry_reason"] == "RATE_LIMITED"
        assert meta["retry_after_seconds"] == 37

    def test_terminal_job_cannot_schedule_retry(self, store):
        job_id = store.create_job(kind="agent", payload={})
        store.fail_job(job_id, "boom")
        assert (
            store.schedule_retry(
                job_id,
                retry_at="t",
                retry_attempt=1,
                retry_limit=3,
                reason="RATE_LIMITED",
                retry_after_seconds=5,
            )
            is False
        )
        assert _meta(store, job_id)["status"] == "failed"

    def test_cancelled_job_cannot_schedule_retry(self, store):
        job_id = store.create_job(kind="agent", payload={})
        store.cancel_job(job_id)
        assert (
            store.schedule_retry(
                job_id,
                retry_at="t",
                retry_attempt=1,
                retry_limit=3,
                reason="RATE_LIMITED",
                retry_after_seconds=5,
            )
            is False
        )
        assert _meta(store, job_id)["status"] == "cancelled"

    def test_missing_job_cannot_schedule_retry(self, store):
        assert (
            store.schedule_retry(
                "nope",
                retry_at="t",
                retry_attempt=1,
                retry_limit=3,
                reason="RATE_LIMITED",
                retry_after_seconds=5,
            )
            is False
        )


class TestResumeRetry:
    def test_resume_returns_to_processing(self, store):
        job_id = store.create_job(kind="agent", payload={})
        store.schedule_retry(
            job_id,
            retry_at="t",
            retry_attempt=1,
            retry_limit=3,
            reason="RATE_LIMITED",
            retry_after_seconds=5,
        )
        assert store.resume_retry(job_id) is True
        meta = _meta(store, job_id)
        assert meta["status"] == "processing"
        # Retry metadata is retained for observability until terminal.
        assert meta["retry_attempt"] == 1

    def test_cancelled_job_is_not_resumed(self, store):
        job_id = store.create_job(kind="agent", payload={})
        store.schedule_retry(
            job_id,
            retry_at="t",
            retry_attempt=1,
            retry_limit=3,
            reason="RATE_LIMITED",
            retry_after_seconds=5,
        )
        store.cancel_job(job_id)
        assert store.resume_retry(job_id) is False
        assert _meta(store, job_id)["status"] == "cancelled"

    def test_processing_job_is_not_resumed(self, store):
        job_id = store.create_job(kind="agent", payload={})
        assert store.resume_retry(job_id) is False


class TestTerminalTransitions:
    def test_fail_job_transitions_from_retry_scheduled(self, store):
        job_id = store.create_job(kind="agent", payload={})
        store.schedule_retry(
            job_id,
            retry_at="t",
            retry_attempt=1,
            retry_limit=3,
            reason="RATE_LIMITED",
            retry_after_seconds=5,
        )
        store.fail_job(job_id, "RATE_LIMITED retry budget exhausted")
        meta = _meta(store, job_id)
        assert meta["status"] == "failed"
        assert "RATE_LIMITED" in meta["error"]

    def test_cancel_job_transitions_from_retry_scheduled(self, store):
        job_id = store.create_job(kind="agent", payload={})
        store.schedule_retry(
            job_id,
            retry_at="t",
            retry_attempt=1,
            retry_limit=3,
            reason="RATE_LIMITED",
            retry_after_seconds=5,
        )
        assert store.cancel_job(job_id) is True
        assert _meta(store, job_id)["status"] == "cancelled"

    def test_cancel_after_failed_retry_exhaustion_is_noop(self, store):
        job_id = store.create_job(kind="agent", payload={})
        store.schedule_retry(
            job_id,
            retry_at="t",
            retry_attempt=2,
            retry_limit=3,
            reason="RATE_LIMITED",
            retry_after_seconds=5,
        )
        store.fail_job(job_id, "exhausted")
        assert store.cancel_job(job_id) is False
        assert _meta(store, job_id)["status"] == "failed"
