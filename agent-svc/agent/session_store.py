"""Session storage backed by Valkey with TTL.

Stores research session metadata, step history, accumulated artifact,
and reference content under the ``session:`` key prefix.  Follows the
same Redis/Valkey patterns as the existing ``JobStore``.

Key schema (HSET for meta and refs, string for steps and artifact):
  session:{id}:meta     → HSET {id, status, created_at, expires_at, step_count, ttl}
  session:{id}:steps    → JSON array of step objects
  session:{id}:artifact → plain text markdown (accumulated, append-only)
  session:{id}:refs     → HSET of ref_id → JSON {url, title, char_count, markdown}

Concurrency guarantees:
  - Atomic step counter via Valkey ``HINCRBY`` on ``session:{id}:meta``
    field ``step_count``.  No read-modify-write race possible.
  - Per-session locking via ``SETNX`` with 30s timeout to serialise
    concurrent step execution on the same session.

Default TTL: 1 hour (3600s).  TTL resets on every write operation.
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


# ── Key helpers ─────────────────────────────────────────────────


def _meta_key(session_id: str) -> str:
    return f"session:{session_id}:meta"


def _steps_key(session_id: str) -> str:
    return f"session:{session_id}:steps"


def _artifact_key(session_id: str) -> str:
    return f"session:{session_id}:artifact"


def _refs_key(session_id: str) -> str:
    return f"session:{session_id}:refs"


def _lock_key(session_id: str) -> str:
    return f"session:{session_id}:lock"


def _all_keys(session_id: str) -> list[str]:
    """Return all session keys (used for delete and TTL refresh)."""
    return [
        _meta_key(session_id),
        _steps_key(session_id),
        _artifact_key(session_id),
        _refs_key(session_id),
    ]


class SessionStore:
    """Valkey-backed session storage with TTL-based expiry.

    Key schema:
      session:{id}:meta     → HSET {id, status, created_at, expires_at, step_count, ttl}
      session:{id}:steps    → JSON [{index, action, params, summary, timestamp, credits_used}]
      session:{id}:artifact → plain text markdown (accumulated, append-only)
      session:{id}:refs     → HSET of ref_id → JSON {url, title, markdown, scraped_at, source, char_count}

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

        Stores meta as a HSET so ``HINCRBY`` can atomically increment
        ``step_count`` without read-modify-write races.

        Args:
            ttl: Session TTL in seconds.  Defaults to ``self.default_ttl`` (1 hour).

        Returns:
            The new session ID (UUID v4).
        """
        session_id = str(uuid.uuid4())
        effective_ttl = ttl if ttl is not None else self.default_ttl

        # Store meta as a HSET — individual fields for HINCRBY support
        meta_key = _meta_key(session_id)
        meta_mapping: dict[str, str] = {
            "id": session_id,
            "status": "active",
            "created_at": _now_iso(),
            "expires_at": _expires_iso(effective_ttl),
            "step_count": "0",  # string for HINCRBY compatibility
            "ttl": str(effective_ttl),
        }
        self.redis.hset(meta_key, mapping=meta_mapping)
        self.redis.expire(meta_key, effective_ttl)

        # Steps stored as JSON string (same as before)
        self.redis.set(
            _steps_key(session_id),
            json.dumps([]),
            ex=effective_ttl,
        )
        # Artifact stored as plain string
        self.redis.set(
            _artifact_key(session_id),
            "",
            ex=effective_ttl,
        )
        # Refs stored as HSET (ref_id → JSON ref_data)
        refs_key = _refs_key(session_id)
        # Create an empty hash so the key exists with TTL
        self.redis.hset(refs_key, "__init__", "1")
        self.redis.hdel(refs_key, "__init__")
        self.redis.expire(refs_key, effective_ttl)

        return session_id

    def get(self, session_id: str) -> dict | None:
        """Get session metadata + step summaries (no full refs).

        Returns None if the session does not exist or has expired.
        The returned dict has the same shape as the old JSON-meta format
        for backward compatibility with ``session.py`` and ``api.py``.
        """
        meta_raw = self.redis.hgetall(_meta_key(session_id))
        if not meta_raw:
            return None

        # Build meta dict, converting string values back to appropriate types
        meta: dict = dict(meta_raw)
        meta["step_count"] = int(meta.get("step_count", "0"))
        meta["ttl"] = int(meta.get("ttl", str(self.default_ttl)))

        # Attach steps
        steps_raw = self.redis.get(_steps_key(session_id))
        meta["steps"] = json.loads(steps_raw) if steps_raw else []

        # Include artifact length for progress visibility
        artifact_raw = self.redis.get(_artifact_key(session_id))
        meta["artifact_length"] = len(artifact_raw) if artifact_raw else 0

        return meta

    def update_meta(self, session_id: str, updates: dict) -> bool:
        """Update session metadata fields atomically.

        Uses ``HSET`` for individual field updates.  ``step_count`` and
        ``ttl`` updates are stored as strings for HINCRBY compatibility.

        Returns False if the session does not exist.
        """
        if not self.redis.exists(_meta_key(session_id)):
            return False

        # Coerce numeric values to strings for HSET
        string_updates: dict[str, str] = {}
        for k, v in updates.items():
            if k in ("step_count", "ttl"):
                string_updates[k] = str(v)
            else:
                string_updates[k] = str(v) if not isinstance(v, str) else v

        self.redis.hset(_meta_key(session_id), mapping=string_updates)

        # Determine TTL for refresh
        ttl_raw = self.redis.hget(_meta_key(session_id), "ttl")
        ttl = int(ttl_raw) if ttl_raw else self.default_ttl
        self._refresh_ttl(session_id, ttl)
        return True

    def append_step(self, session_id: str, step: dict) -> int | None:
        """Append a step to the session's step history.

        Atomically increments the step count via ``HINCRBY`` and returns
        the new step index (1-based).  Returns None if the session does
        not exist.

        Steps are stored as a JSON array string (not HSET) since they
        are represented as an ordered list.
        """
        meta_key = _meta_key(session_id)
        if not self.redis.exists(meta_key):
            return None

        # Atomic step counter — no read-modify-write race
        step_index = self.redis.hincrby(meta_key, "step_count", 1)

        # Get current steps list
        steps_raw = self.redis.get(_steps_key(session_id))
        steps: list[dict] = json.loads(steps_raw) if steps_raw else []

        # Assign step metadata
        step["index"] = step_index
        step["timestamp"] = _now_iso()
        steps.append(step)

        # Update expires_at in meta
        ttl_raw = self.redis.hget(meta_key, "ttl")
        ttl = int(ttl_raw) if ttl_raw else self.default_ttl
        self.redis.hset(meta_key, "expires_at", _expires_iso(ttl))

        # Persist steps and refresh TTL
        self.redis.set(_steps_key(session_id), json.dumps(steps), ex=ttl)
        self._refresh_ttl(session_id, ttl)
        return step_index

    def get_steps(self, session_id: str) -> list[dict]:
        """Get the full step history for a session."""
        steps_raw = self.redis.get(_steps_key(session_id))
        return json.loads(steps_raw) if steps_raw else []

    def append_artifact(self, session_id: str, content: str) -> bool:
        """Append content to the session's accumulated artifact.

        Returns False if the session does not exist.
        """
        meta_key = _meta_key(session_id)
        if not self.redis.exists(meta_key):
            return False

        ttl_raw = self.redis.hget(meta_key, "ttl")
        ttl = int(ttl_raw) if ttl_raw else self.default_ttl

        existing = self.redis.get(_artifact_key(session_id)) or ""
        new_artifact = existing + content
        self.redis.set(
            _artifact_key(session_id),
            new_artifact,
            ex=ttl,
        )
        self._refresh_ttl(session_id, ttl)
        return True

    def get_artifact(self, session_id: str) -> str:
        """Get the full accumulated artifact text."""
        return self.redis.get(_artifact_key(session_id)) or ""

    # ── Reference Storage (HSET-based) ──────────────────────────

    def add_ref(self, session_id: str, ref_id: str, ref_data: dict) -> bool:
        """Store a reference (scraped content) by ref ID.

        ``ref_id`` is typically ``ref_{step}_{source}`` (e.g., ``ref_0_2``).
        Each ref is stored as an individual HSET field, allowing O(1)
        single-ref lookup without deserialising the entire refs collection.

        Returns False if the session does not exist.
        """
        meta_key = _meta_key(session_id)
        if not self.redis.exists(meta_key):
            return False

        ttl_raw = self.redis.hget(meta_key, "ttl")
        ttl = int(ttl_raw) if ttl_raw else self.default_ttl

        self.redis.hset(
            _refs_key(session_id),
            ref_id,
            json.dumps(ref_data),
        )
        self.redis.expire(_refs_key(session_id), ttl)
        self._refresh_ttl(session_id, ttl)
        return True

    def get_ref(self, session_id: str, ref_id: str) -> dict | None:
        """Get a single reference by ref ID.

        Uses ``HGET`` for O(1) single-ref lookup.  Returns None if
        the ref or session does not exist.
        """
        raw = self.redis.hget(_refs_key(session_id), ref_id)
        if raw is None:
            return None
        return json.loads(raw)  # type: ignore[no-any-return]

    def get_refs(self, session_id: str) -> dict:
        """Get all references for a session.

        Returns a dict of ``{ref_id: ref_data}``.  Each ref_data is
        deserialised from its JSON HSET value.
        """
        raw = self.redis.hgetall(_refs_key(session_id))
        if not raw:
            return {}
        return {k: json.loads(v) for k, v in raw.items()}  # type: ignore[no-any-return]

    # ── Lifecycle ───────────────────────────────────────────────

    def delete(self, session_id: str) -> bool:
        """Delete a session and all its keys (meta, steps, artifact, refs, lock).

        Returns True if the session existed and was deleted.
        """
        keys = [*_all_keys(session_id), _lock_key(session_id)]
        deleted = self.redis.delete(*keys)
        return deleted > 0

    def cleanup_expired(self) -> int:
        """Clean up expired session keys.

        Since Valkey handles TTL expiry automatically, this is a no-op
        for standard expiry.  Returns 0 — all cleanup is done by Valkey's
        built-in expiration.
        """
        return 0

    # ── Per-Session Locking ─────────────────────────────────────

    def acquire_lock(self, session_id: str, timeout: int = 30) -> bool:
        """Acquire a per-session lock for concurrent step execution.

        Uses ``SETNX`` with an expiry timeout so stale locks do not
        permanently block a session.  The lock value is a timestamp
        for debugging.

        Args:
            session_id: The session to lock.
            timeout: Lock timeout in seconds (default 30).  If a step
                takes longer than this, the lock auto-expires and
                another caller can acquire it.

        Returns:
            True if the lock was acquired, False if another caller
            holds the lock.
        """
        lock_val = f"{_now_iso()}"
        acquired = self.redis.set(
            _lock_key(session_id),
            lock_val,
            nx=True,
            ex=timeout,
        )
        return bool(acquired)

    def release_lock(self, session_id: str) -> None:
        """Release the per-session lock.

        Only deletes the lock key — does not check ownership.  The
        lock timeout provides a safety net against orphaned locks.
        """
        self.redis.delete(_lock_key(session_id))

    def is_locked(self, session_id: str) -> bool:
        """Check whether the session lock is currently held."""
        return bool(self.redis.exists(_lock_key(session_id)))

    # ── TTL Management ──────────────────────────────────────────

    def _refresh_ttl(self, session_id: str, ttl: int) -> None:
        """Refresh TTL on all session keys (meta, steps, artifact, refs).

        Called after every write operation to reset the idle timeout.
        """
        for key in _all_keys(session_id):
            self.redis.expire(key, ttl)
