"""Thread-safe in-memory session store with TTL-based expiry."""

import time
import threading
import uuid
from typing import Any


class SessionStore:
    """Generic in-memory session store with optional TTL.

    Sessions are stored as dicts keyed by UUID string.  Each session
    carries ``type``, ``ttl``, and ``created_at`` fields.  Expired
    sessions are removed when ``cleanup_expired()`` is called.

    Thread safety is provided by a ``threading.Lock``.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, dict] = {}

    def create(self, session_type: str, ttl: int) -> str:
        """Create a new session and return its UUID.

        Args:
            session_type: Arbitrary string label (e.g. ``"browser"``).
            ttl: Time-to-live in seconds.

        Returns:
            The new session ID (UUID v4 string).
        """
        session_id = str(uuid.uuid4())
        now = time.time()
        with self._lock:
            self._sessions[session_id] = {
                "type": session_type,
                "ttl": ttl,
                "created_at": now,
                "data": {},
            }
        return session_id

    def get(self, session_id: str) -> dict | None:
        """Return the session dict or ``None`` if not found."""
        with self._lock:
            return self._sessions.get(session_id)

    def update(self, session_id: str, data: dict) -> bool:
        """Merge *data* into the session's ``data`` sub-dict.

        Returns ``True`` if the session was found and updated,
        ``False`` otherwise.
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            session.setdefault("data", {}).update(data)
            return True

    def put(self, session_id: str, session_type: str, ttl: int) -> None:
        """Create or overwrite a session with a specific ID.

        Args:
            session_id: The explicit session ID to use.
            session_type: Arbitrary string label.
            ttl: Time-to-live in seconds.
        """
        now = time.time()
        with self._lock:
            self._sessions[session_id] = {
                "type": session_type,
                "ttl": ttl,
                "created_at": now,
                "data": {},
            }

    def delete(self, session_id: str) -> bool:
        """Remove a session by ID.

        Returns ``True`` if the session existed and was removed,
        ``False`` otherwise.
        """
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def cleanup_expired(self) -> int:
        """Remove all sessions whose TTL has elapsed.

        Returns the number of sessions removed.
        """
        now = time.time()
        removed = 0
        with self._lock:
            expired_ids = [
                sid
                for sid, s in self._sessions.items()
                if now - s["created_at"] > s["ttl"]
            ]
            for sid in expired_ids:
                del self._sessions[sid]
                removed += 1
        return removed
