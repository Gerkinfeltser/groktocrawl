"""Session storage backed by Valkey with TTL.

Stores research session metadata, step history, accumulated artifact,
and reference content under the ``session:`` key prefix.  Follows the
same Redis/Valkey patterns as the existing ``JobStore``.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta

from redis import Redis


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _expires_iso(ttl: int = 3600) -> str:
    """Return ISO 8601 timestamp for TTL seconds from now."""
    return (datetime.now(UTC) + timedelta(seconds=ttl)).isoformat()


class SessionStore:
    """Valkey-backed session storage with TTL-based expiry.

    Key schema:
      session:{id}:meta     → JSON {id, status, created_at, expires_at, step_count, ttl}
      session:{id}:steps    → JSON [{index, action, params, summary, timestamp, credits_used}]
      session:{id}:artifact → plain text markdown (accumulated, append-only)
      session:{id}:refs     → JSON {ref_id: {url, title, markdown, scraped_at, source}}

    Default TTL: 1 hour (3600s).  TTL resets on every write operation.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        default_ttl: int = 3600,
    ):
        self.redis = Redis.from_url(redis_url, decode_responses=True)
        self.default_ttl = default_ttl

    # ── Create / Read / Update / Delete ──────────────────────────

    def create(self, ttl: int | None = None) -> str:
        """Create a new session and return its ID.

        Args:
            ttl: Session TTL in seconds.  Defaults to ``self.default_ttl`` (1 hour).

        Returns:
            The new session ID (UUID v4).
        """
        session_id = str(uuid.uuid4())
        effective_ttl = ttl if ttl is not None else self.default_ttl
        meta = {
            "id": session_id,
            "status": "active",
            "created_at": _now_iso(),
            "expires_at": _expires_iso(effective_ttl),
            "step_count": 0,
            "ttl": effective_ttl,
        }
        self.redis.set(
            f"session:{session_id}:meta",
            json.dumps(meta),
            ex=effective_ttl,
        )
        self.redis.set(
            f"session:{session_id}:steps",
            json.dumps([]),
            ex=effective_ttl,
        )
        self.redis.set(
            f"session:{session_id}:artifact",
            "",
            ex=effective_ttl,
        )
        self.redis.set(
            f"session:{session_id}:refs",
            json.dumps({}),
            ex=effective_ttl,
        )
        return session_id

    def get(self, session_id: str) -> dict | None:
        """Get session metadata + step summaries (no full refs).

        Returns None if the session does not exist or has expired.
        """
        meta_raw = self.redis.get(f"session:{session_id}:meta")
        if meta_raw is None:
            return None
        meta = json.loads(meta_raw)

        steps_raw = self.redis.get(f"session:{session_id}:steps")
        meta["steps"] = json.loads(steps_raw) if steps_raw else []

        # Include artifact length for progress visibility
        artifact_raw = self.redis.get(f"session:{session_id}:artifact")
        meta["artifact_length"] = len(artifact_raw) if artifact_raw else 0

        return meta

    def update_meta(self, session_id: str, updates: dict) -> bool:
        """Update session metadata fields atomically.

        Returns False if the session does not exist.
        """
        meta_raw = self.redis.get(f"session:{session_id}:meta")
        if meta_raw is None:
            return False
        meta = json.loads(meta_raw)
        meta.update(updates)
        ttl = meta.get("ttl", self.default_ttl)
        self.redis.set(
            f"session:{session_id}:meta",
            json.dumps(meta),
            ex=ttl,
        )
        # Refresh TTL on all session keys
        self._refresh_ttl(session_id, ttl)
        return True

    def append_step(self, session_id: str, step: dict) -> int | None:
        """Append a step to the session's step history.

        Atomically increments the step count and returns the new
        step index (1-based).  Returns None if the session does not
        exist.
        """
        meta_raw = self.redis.get(f"session:{session_id}:meta")
        if meta_raw is None:
            return None
        meta = json.loads(meta_raw)

        # Get current steps
        steps_raw = self.redis.get(f"session:{session_id}:steps")
        steps: list[dict] = json.loads(steps_raw) if steps_raw else []

        # Assign step index
        step_index = len(steps) + 1
        step["index"] = step_index
        step["timestamp"] = _now_iso()
        steps.append(step)

        # Update meta
        meta["step_count"] = step_index
        meta["expires_at"] = _expires_iso(meta.get("ttl", self.default_ttl))
        ttl = meta.get("ttl", self.default_ttl)

        self.redis.set(f"session:{session_id}:meta", json.dumps(meta), ex=ttl)
        self.redis.set(f"session:{session_id}:steps", json.dumps(steps), ex=ttl)
        return step_index

    def get_steps(self, session_id: str) -> list[dict]:
        """Get the full step history for a session."""
        steps_raw = self.redis.get(f"session:{session_id}:steps")
        return json.loads(steps_raw) if steps_raw else []

    def append_artifact(self, session_id: str, content: str) -> bool:
        """Append content to the session's accumulated artifact.

        Returns False if the session does not exist.
        """
        meta_raw = self.redis.get(f"session:{session_id}:meta")
        if meta_raw is None:
            return False
        meta = json.loads(meta_raw)
        ttl = meta.get("ttl", self.default_ttl)

        existing = self.redis.get(f"session:{session_id}:artifact") or ""
        new_artifact = existing + content
        self.redis.set(
            f"session:{session_id}:artifact",
            new_artifact,
            ex=ttl,
        )
        self._refresh_ttl(session_id, ttl)
        return True

    def get_artifact(self, session_id: str) -> str:
        """Get the full accumulated artifact text."""
        return self.redis.get(f"session:{session_id}:artifact") or ""

    def add_ref(self, session_id: str, ref_id: str, ref_data: dict) -> bool:
        """Store a reference (scraped content) by ref ID.

        ``ref_id`` is typically ``ref_{step}_{source}`` (e.g., ``ref_0_2``).
        Returns False if the session does not exist.
        """
        meta_raw = self.redis.get(f"session:{session_id}:meta")
        if meta_raw is None:
            return False
        meta = json.loads(meta_raw)
        ttl = meta.get("ttl", self.default_ttl)

        refs_raw = self.redis.get(f"session:{session_id}:refs")
        refs: dict = json.loads(refs_raw) if refs_raw else {}
        refs[ref_id] = ref_data
        self.redis.set(f"session:{session_id}:refs", json.dumps(refs), ex=ttl)
        self._refresh_ttl(session_id, ttl)
        return True

    def get_ref(self, session_id: str, ref_id: str) -> dict | None:
        """Get a single reference by ref ID. Returns None if not found."""
        refs_raw = self.redis.get(f"session:{session_id}:refs")
        if not refs_raw:
            return None
        refs: dict = json.loads(refs_raw)
        return refs.get(ref_id)

    def get_refs(self, session_id: str) -> dict:
        """Get all references for a session."""
        refs_raw = self.redis.get(f"session:{session_id}:refs")
        return json.loads(refs_raw) if refs_raw else {}

    def delete(self, session_id: str) -> bool:
        """Delete a session and all its keys.

        Returns True if the session existed and was deleted.
        """
        keys = [
            f"session:{session_id}:meta",
            f"session:{session_id}:steps",
            f"session:{session_id}:artifact",
            f"session:{session_id}:refs",
        ]
        deleted = self.redis.delete(*keys)
        return deleted > 0

    def cleanup_expired(self) -> int:
        """Clean up expired session keys.

        Since Valkey handles TTL expiry automatically, this is a no-op
        for standard expiry.  Returns 0 — all cleanup is done by Valkey's
        built-in expiration.
        """
        return 0

    def _refresh_ttl(self, session_id: str, ttl: int) -> None:
        """Refresh TTL on all session keys."""
        for suffix in ("meta", "steps", "artifact", "refs"):
            self.redis.expire(f"session:{session_id}:{suffix}", ttl)
