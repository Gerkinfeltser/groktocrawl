"""Bounded retry policy for downstream rate-limit conditions (ADR-0053).

Pure, deterministic helpers shared by the worker retry loop. The policy
defaults are configuration-backed (``JOB_RETRY_*``) and every delay
decision is bounded: no individual wait exceeds ``max_wait_seconds`` and
no job performs more than ``max_attempts`` total attempts.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass

from .cancel import raise_if_cancelled

# Minimum delay applied even when the server explicitly answers
# ``Retry-After: 0`` so a retry can never become a hot loop.
_MIN_RETRY_DELAY_SECONDS = 1.0

# Slice granularity for the cancellable retry sleep: small enough that a
# cancel-token-only DELETE interrupts the wait promptly, coarse enough to
# avoid waking the event loop in a busy loop.
_SLEEP_SLICE_SECONDS = 0.25


@dataclass(frozen=True)
class RetryPolicy:
    """Retry budget and delay bounds for a single job.

    Attributes:
        max_attempts: Maximum total attempts for the blocked operation
            (initial attempt plus at most ``max_attempts - 1`` retries).
        fallback_seconds: Base delay used when the downstream response
            carries no retry metadata; grows exponentially per attempt.
        max_wait_seconds: Ceiling for any individual wait (server-provided
            delays are clamped to this).
    """

    max_attempts: int = 3
    fallback_seconds: float = 1.0
    max_wait_seconds: float = 60.0


def default_retry_policy() -> RetryPolicy:
    """Build the retry policy from ``JOB_RETRY_*`` settings."""
    from .settings import load_settings

    settings = load_settings()
    return RetryPolicy(
        max_attempts=settings.job_retry_max_attempts,
        fallback_seconds=settings.job_retry_fallback_seconds,
        max_wait_seconds=settings.job_retry_max_wait_seconds,
    )


def clamp_retry_delay(
    server_delay: float | None,
    *,
    attempt: int,
    policy: RetryPolicy,
    jitter_fn=None,
) -> float:
    """Resolve the delay to wait before the next attempt.

    Server-provided delays take precedence and are clamped to
    ``[min, max_wait_seconds]``. When retry metadata is absent, invalid,
    zero, or negative, the bounded fallback ``fallback * 2**(attempt-1)``
    grows exponentially with the attempt and is extended by jitter.

    Args:
        server_delay: Retry delay from the downstream response, or
            ``None`` when absent/invalid.
        attempt: The attempt that just failed (1-based).
        policy: Bounds for the delay computation.
        jitter_fn: Zero-argument jitter source (tests inject a
            deterministic value); defaults to uniform(0, 0.5).
    """
    if server_delay is not None and server_delay > 0:
        return min(max(server_delay, _MIN_RETRY_DELAY_SECONDS), policy.max_wait_seconds)
    if policy.max_wait_seconds <= 0:
        return _MIN_RETRY_DELAY_SECONDS
    fallback = min(
        policy.fallback_seconds * (2 ** (attempt - 1)), policy.max_wait_seconds
    )
    jitter = jitter_fn() if jitter_fn is not None else random.uniform(0.0, 0.5)
    return min(
        max(fallback + jitter, _MIN_RETRY_DELAY_SECONDS), policy.max_wait_seconds
    )


async def retry_sleep(delay: float) -> None:
    """Sleep until the retry time, honouring the job cancel token.

    Waits in small slices so a cancel-token-only DELETE (no owning task)
    interrupts the wait promptly via ``JobCancelledError``; full task
    cancellation interrupts immediately via ``asyncio.CancelledError``.
    """
    deadline = asyncio.get_running_loop().time() + max(0.0, delay)
    while True:
        raise_if_cancelled()
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return
        await asyncio.sleep(min(remaining, _SLEEP_SLICE_SECONDS))
