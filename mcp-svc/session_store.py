"""Generic TTL session store with asyncio.Lock and periodic sweep.

In-process dict-based storage.  Sessions carry arbitrary metadata and
are expired after a configurable TTL.  A background asyncio task
periodically sweeps expired sessions.

Configuration (environment variables):
    SESSION_TTL            TTL in seconds (default 3600).
    SESSION_SWEEP_INTERVAL Sweep interval in seconds (default 300).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from contextlib import suppress

logger = logging.getLogger(__name__)

_SESSION_TTL = int(os.environ.get("SESSION_TTL", "3600"))
_SESSION_SWEEP_INTERVAL = int(os.environ.get("SESSION_SWEEP_INTERVAL", "300"))


class SessionStore:
    """Generic in-memory session store with TTL-based expiry.

    Sessions are stored in a plain ``dict`` protected by an
    ``asyncio.Lock``.  A background sweep task removes expired
    sessions on a configurable interval.

    The store is **generic** — it imports nothing from the MCP SDK and
    places no constraints on the shape of stored metadata.
    """

    def __init__(
        self,
        ttl: int | None = None,
        sweep_interval: int | None = None,
    ) -> None:
        """Initialise the store and start the background sweep task.

        Args:
            ttl: Session TTL in seconds.  Defaults to ``SESSION_TTL``
                env var (3600 s).
            sweep_interval: Interval between sweep passes in seconds.
                Defaults to ``SESSION_SWEEP_INTERVAL`` env var (300 s).
        """
        self._ttl = ttl if ttl is not None else _SESSION_TTL
        self._sweep_interval = (
            sweep_interval if sweep_interval is not None else _SESSION_SWEEP_INTERVAL
        )

        self._sessions: dict[str, dict] = {}
        self._lock = asyncio.Lock()

        self._stop_event = asyncio.Event()
        self._sweep_task: asyncio.Task | None = None

    # ── Public API ─────────────────────────────────────────────────

    async def _ensure_sweep_running(self) -> None:
        """Start the background sweep task if it is not already running.

        Called lazily on first use so that the sweep task runs inside
        the server's asyncio event loop regardless of whether the
        ``SessionStore`` was created at module level or on demand.
        """
        if self._sweep_task is not None and not self._sweep_task.done():
            return
        self._stop_event.clear()
        self._sweep_task = asyncio.create_task(self._sweep_loop())
        logger.debug(
            "Sweep task started (ttl=%ds, interval=%ds)",
            self._ttl,
            self._sweep_interval,
        )

    async def create(
        self,
        metadata: dict | None = None,
        *,
        session_id: str | None = None,
    ) -> str:
        """Create a new session and return its identifier.

        Args:
            metadata: Arbitrary key-value data to store with the session.
            session_id: Explicit session identifier.  A UUID v4 is
                generated when *session_id* is ``None``.

        Returns:
            The session identifier (provided or generated).
        """
        sid = session_id or str(uuid.uuid4())
        now = time.time()
        await self._ensure_sweep_running()
        async with self._lock:
            self._sessions[sid] = {
                "created_at": now,
                "data": dict(metadata) if metadata else {},
            }
        return sid

    async def get(self, session_id: str) -> dict | None:
        """Retrieve session metadata, or ``None`` if missing / expired.

        Returns a shallow copy of the stored data dict so callers
        cannot mutate internal state.
        """
        await self._ensure_sweep_running()
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            if time.time() - session["created_at"] > self._ttl:
                return None
            return dict(session["data"])

    async def update(self, session_id: str, data: dict) -> None:
        """Merge *data* into an existing session's metadata in-place.

        Does nothing when the session does not exist.
        """
        await self._ensure_sweep_running()
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is not None:
                session["data"].update(data)

    async def destroy(self, session_id: str) -> None:
        """Remove a session by identifier (no-op for unknown IDs)."""
        await self._ensure_sweep_running()
        async with self._lock:
            self._sessions.pop(session_id, None)

    async def sweep(self) -> int:
        """Remove all expired sessions.

        Returns:
            Number of sessions removed.
        """
        now = time.time()
        removed = 0
        await self._ensure_sweep_running()
        async with self._lock:
            expired = [
                sid
                for sid, s in self._sessions.items()
                if now - s["created_at"] > self._ttl
            ]
            for sid in expired:
                del self._sessions[sid]
            removed = len(expired)
        if removed:
            logger.debug("Sweep removed %d expired sessions", removed)
        return removed

    # ── Lifecycle ──────────────────────────────────────────────────

    def start_sweep(self) -> None:
        """Launch the periodic background sweep task.

        Safe to call multiple times — subsequent calls are no-ops when
        a sweep task is already running.
        """
        if self._sweep_task is not None and not self._sweep_task.done():
            return
        self._stop_event.clear()
        self._sweep_task = asyncio.create_task(self._sweep_loop())
        logger.debug(
            "Sweep task started (ttl=%ds, interval=%ds)",
            self._ttl,
            self._sweep_interval,
        )

    async def stop_sweep(self) -> None:
        """Cancel the background sweep task and wait for it to finish."""
        if self._sweep_task is None:
            return
        self._stop_event.set()
        with suppress(asyncio.CancelledError):
            await self._sweep_task
        self._sweep_task = None
        logger.debug("Sweep task stopped")

    async def _sweep_loop(self) -> None:
        """Run ``sweep()`` on a fixed interval until stopped."""
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self._sweep_interval
                )
                # _stop_event was set — exit
                break
            except TimeoutError:
                # Interval elapsed — sweep
                await self.sweep()
