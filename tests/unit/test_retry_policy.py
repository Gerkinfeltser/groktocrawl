"""Unit tests for the server-side rate-limit retry policy (ADR-0053).

Covers delay clamping/backoff with deterministic jitter, the fixed-window
reset math, and the retry metadata carried by the exception hierarchy.
"""

from __future__ import annotations

import pytest
from agent.cancel import JobCancelledError, set_token
from agent.exceptions import RateLimitedError, RetryableRateLimitError
from agent.rate_limiter import SlidingWindowRateLimiter
from agent.retry import (
    RetryPolicy,
    clamp_retry_delay,
    retry_sleep,
)


class TestClampRetryDelay:
    def test_server_delay_takes_precedence(self):
        policy = RetryPolicy(
            max_attempts=3, fallback_seconds=1.0, max_wait_seconds=60.0
        )
        delay = clamp_retry_delay(
            37.0, attempt=1, policy=policy, jitter_fn=lambda: 99.0
        )
        assert delay == 37.0

    def test_server_delay_zero_uses_minimum_fallback(self):
        policy = RetryPolicy(
            max_attempts=3, fallback_seconds=1.0, max_wait_seconds=60.0
        )
        # Retry-After: 0 must not become a hot loop (ADR-0053 edge case).
        delay = clamp_retry_delay(0, attempt=1, policy=policy, jitter_fn=lambda: 0.0)
        assert delay == 1.0

    def test_negative_server_delay_falls_back(self):
        policy = RetryPolicy(
            max_attempts=3, fallback_seconds=1.0, max_wait_seconds=60.0
        )
        delay = clamp_retry_delay(-5.0, attempt=1, policy=policy, jitter_fn=lambda: 0.0)
        assert delay == 1.0

    def test_excessive_server_delay_is_clamped_to_max_wait(self):
        policy = RetryPolicy(
            max_attempts=3, fallback_seconds=1.0, max_wait_seconds=60.0
        )
        delay = clamp_retry_delay(
            9999.0, attempt=1, policy=policy, jitter_fn=lambda: 0.0
        )
        assert delay == 60.0

    def test_server_delay_below_minimum_is_raised_to_minimum(self):
        policy = RetryPolicy(
            max_attempts=3, fallback_seconds=1.0, max_wait_seconds=60.0
        )
        delay = clamp_retry_delay(0.25, attempt=1, policy=policy, jitter_fn=lambda: 0.0)
        assert delay == 1.0

    def test_bounded_exponential_backoff_with_injected_jitter(self):
        policy = RetryPolicy(
            max_attempts=3, fallback_seconds=1.0, max_wait_seconds=60.0
        )
        assert (
            clamp_retry_delay(None, attempt=1, policy=policy, jitter_fn=lambda: 0.0)
            == 1.0
        )
        assert (
            clamp_retry_delay(None, attempt=2, policy=policy, jitter_fn=lambda: 0.0)
            == 2.0
        )
        assert (
            clamp_retry_delay(None, attempt=3, policy=policy, jitter_fn=lambda: 0.0)
            == 4.0
        )
        assert (
            clamp_retry_delay(None, attempt=1, policy=policy, jitter_fn=lambda: 0.5)
            == 1.5
        )

    def test_backoff_capped_at_max_wait(self):
        policy = RetryPolicy(
            max_attempts=10, fallback_seconds=1.0, max_wait_seconds=60.0
        )
        delay = clamp_retry_delay(None, attempt=7, policy=policy, jitter_fn=lambda: 0.0)
        assert delay == 60.0

    def test_zero_max_wait_yields_minimum_delay(self):
        policy = RetryPolicy(max_attempts=3, fallback_seconds=1.0, max_wait_seconds=0.0)
        delay = clamp_retry_delay(None, attempt=1, policy=policy, jitter_fn=lambda: 0.0)
        assert delay == 1.0

    def test_zero_max_wait_never_defeats_floor_with_server_delay(self):
        """A zero ceiling must not yield a 0s delay even for a positive server delay."""
        policy = RetryPolicy(max_attempts=3, fallback_seconds=1.0, max_wait_seconds=0.0)
        delay = clamp_retry_delay(37.0, attempt=1, policy=policy, jitter_fn=lambda: 0.0)
        assert delay == 1.0

    def test_non_finite_server_delay_falls_back(self):
        policy = RetryPolicy(
            max_attempts=3, fallback_seconds=1.0, max_wait_seconds=60.0
        )
        # inf is clamped to the ceiling (bounded, never crashes); nan fails
        # the > 0 comparison and falls back to the minimum delay.
        assert (
            clamp_retry_delay(
                float("inf"), attempt=1, policy=policy, jitter_fn=lambda: 0.0
            )
            == 60.0
        )
        assert (
            clamp_retry_delay(
                float("nan"), attempt=1, policy=policy, jitter_fn=lambda: 0.0
            )
            == 1.0
        )


class TestRetrySleepCancellation:
    @pytest.mark.asyncio
    async def test_zero_delay_returns_immediately(self):
        await retry_sleep(0.0)

    @pytest.mark.asyncio
    async def test_cancel_token_interrupts_wait(self):
        token = __import__("asyncio").Event()
        set_token(token)
        try:
            token.set()
            with pytest.raises(JobCancelledError):
                await retry_sleep(60.0)
        finally:
            set_token(None)


class TestLimiterResetMath:
    def test_retry_after_is_window_minus_offset(self):
        limiter = SlidingWindowRateLimiter(redis=object(), limit=10, window_seconds=60)
        assert limiter.retry_after_seconds(now=30.0) == 30
        assert limiter.retry_after_seconds(now=59.0) == 1
        assert limiter.retry_after_seconds(now=0.0) == 60
        assert limiter.retry_after_seconds(now=60.0) == 60
        assert limiter.retry_after_seconds(now=119.9) == 1

    def test_reset_at_iso_derivable(self):
        import datetime as _dt

        limiter = SlidingWindowRateLimiter(redis=object(), limit=10, window_seconds=60)
        reset = limiter.reset_at_iso(now=30.0)
        assert reset is not None
        assert reset.endswith("+00:00")
        # reset_at is the next window boundary (now + retry_after = 60s past
        # the epoch), not the current time.
        parsed = _dt.datetime.fromisoformat(reset)
        assert parsed.timestamp() == 60.0


class TestRetryMetadata:
    def test_rate_limited_error_builds_details(self):
        err = RateLimitedError(
            "rejected",
            retry_after_seconds=37,
            bucket="search",
            limit=10,
            remaining=0,
            reset_at="2026-08-15T16:01:00Z",
        )
        assert err.status_code == 429
        assert err.error_code == "RATE_LIMITED"
        assert err.retry_after_seconds == 37
        assert err.details == {
            "bucket": "search",
            "limit": 10,
            "remaining": 0,
            "reset_at": "2026-08-15T16:01:00Z",
        }

    def test_rate_limited_error_without_metadata_keeps_legacy_shape(self):
        err = RateLimitedError("budget exhausted")
        assert err.details is None
        assert err.retry_after_seconds is None

    def test_retryable_rate_limit_error_is_a_rate_limited_error(self):
        err = RetryableRateLimitError("downstream capacity", retry_after_seconds=5)
        assert isinstance(err, RateLimitedError)
        assert err.status_code == 429
        assert err.error_code == "RATE_LIMITED"
        assert err.retry_after_seconds == 5
        assert err.retryable is True
