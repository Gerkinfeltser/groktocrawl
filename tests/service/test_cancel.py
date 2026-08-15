"""Tests for per-job cooperative cancellation (ADR-0051)."""

import asyncio

import pytest


class TestCancelToken:
    @pytest.mark.asyncio
    async def test_no_token_is_noop(self):
        from agent.cancel import current_token, raise_if_cancelled

        assert current_token() is None
        raise_if_cancelled()  # must not raise

    @pytest.mark.asyncio
    async def test_set_token_raises(self):
        from agent.cancel import JobCancelledError, cancel_scope, raise_if_cancelled

        token = asyncio.Event()
        token.set()
        with cancel_scope(token):
            with pytest.raises(JobCancelledError):
                raise_if_cancelled()

    @pytest.mark.asyncio
    async def test_cancel_scope_resets_token(self):
        from agent.cancel import cancel_scope, current_token

        token = asyncio.Event()
        with cancel_scope(token):
            assert current_token() is token
        assert current_token() is None


class TestTaskTrackerCancellation:
    @pytest.mark.asyncio
    async def test_cancel_job_sets_token_and_cancels_task(self):
        from agent.tasks import TaskTracker

        tracker = TaskTracker()

        async def _hang() -> None:
            await asyncio.Future()

        task = tracker.create_background_task(_hang(), job_id="job-1")
        assert tracker.cancel_token("job-1").is_set() is False

        assert tracker.cancel_job("job-1") is True
        assert tracker.cancel_token("job-1").is_set() is True

        with pytest.raises(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio
    async def test_cancel_job_without_owner_returns_false(self):
        from agent.tasks import TaskTracker

        tracker = TaskTracker()
        assert tracker.cancel_job("no-owner") is False

    @pytest.mark.asyncio
    async def test_cancel_token_is_stable_per_job(self):
        from agent.tasks import TaskTracker

        tracker = TaskTracker()
        assert tracker.cancel_token("job-1") is tracker.cancel_token("job-1")
