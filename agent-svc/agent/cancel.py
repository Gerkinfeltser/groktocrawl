"""Per-job cooperative cancellation token.

Propagates a per-job ``asyncio.Event`` cancel signal through the worker
fan-out tree (worker → crawler → research/answer/scrape → scraper_client →
llm) using a ``contextvars.ContextVar``. Child tasks created with
``asyncio.create_task`` inherit the token, so descendants check it at safe
await boundaries without threading it through every call signature.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

# ``asyncio.Event`` is the concrete token type.
JobCancelToken = asyncio.Event

_current_token: ContextVar[JobCancelToken | None] = ContextVar(
    "job_cancel_token", default=None
)


class JobCancelledError(Exception):
    """Raised by a work function to signal cooperative cancellation.

    ``worker._run_job_with_observability`` treats this distinctly from a
    normal ``Exception`` so a cancelled job is never recorded as completed
    or failed.
    """


def current_token() -> JobCancelToken | None:
    """Return the cancel token in the current context, or ``None``."""
    return _current_token.get()


def set_token(token: JobCancelToken | None) -> None:
    """Set the cancel token for the current (worker) task context.

    Workers run one job per task, so the token is intentionally never
    reset — the task's context is discarded when the job completes.
    """
    _current_token.set(token)


def raise_if_cancelled() -> None:
    """Raise ``JobCancelledError`` if the current token is set."""
    token = _current_token.get()
    if token is not None and token.is_set():
        raise JobCancelledError("job cancelled via cancel token")


@contextmanager
def cancel_scope(token: JobCancelToken | None) -> Iterator[None]:
    """Set *token* as the active cancel token and reset on exit.

    Useful for callers (and tests) that must not leak a token into a
    surrounding context.
    """
    reset = _current_token.set(token)
    try:
        yield
    finally:
        _current_token.reset(reset)


__all__ = [
    "JobCancelToken",
    "JobCancelledError",
    "cancel_scope",
    "current_token",
    "raise_if_cancelled",
    "set_token",
]
