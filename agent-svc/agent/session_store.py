"""Session storage backed by Valkey with TTL.

Stores research session metadata, step history, accumulated artifact,
and reference content under the ``session:`` key prefix.  Follows the
same Redis/Valkey patterns as the existing ``JobStore``.

Key schema (HSET for meta and refs, string for steps and artifact):
  session:{id}:meta     → HSET {id, status, created_at, expires_at, step_count, ttl, artifact_chars}
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

import asyncio
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


def _step_log_key(session_id: str) -> str:
    return f"session:{session_id}:step_log"


def _artifact_key(session_id: str) -> str:
    return f"session:{session_id}:artifact"


def _refs_key(session_id: str) -> str:
    return f"session:{session_id}:refs"


def _lock_key(session_id: str) -> str:
    return f"session:{session_id}:lock"


def _idempotency_key(session_id: str) -> str:
    return f"session:{session_id}:idempotency"


def _all_keys(session_id: str) -> list[str]:
    """Return all session keys (used for delete and TTL refresh)."""
    return [
        _meta_key(session_id),
        _steps_key(session_id),
        _step_log_key(session_id),
        _artifact_key(session_id),
        _refs_key(session_id),
        _idempotency_key(session_id),
    ]


class SessionStore:
    """Valkey-backed session storage with TTL-based expiry.

    Key schema:
      session:{id}:meta     → HSET {id, status, created_at, expires_at, step_count, ttl, artifact_chars}
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
            # Redis STRLEN reports bytes.  Keep a separate character count so
            # the public API retains its existing Unicode semantics.
            "artifact_chars": "0",
            "revision": "0",
            "next_step_index": "0",
        }
        self.redis.hset(meta_key, mapping=meta_mapping)  # type: ignore[arg-type]
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
        artifact_chars = meta.get("artifact_chars")
        if artifact_chars is not None:
            meta["artifact_length"] = int(artifact_chars)
        else:
            # Existing sessions predate the counter.  This one-time fallback
            # preserves their character-count behavior without changing the
            # public response shape.
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

        self.redis.hset(_meta_key(session_id), mapping=string_updates)  # type: ignore[arg-type]

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
        steps = json.loads(steps_raw) if steps_raw else []
        try:
            step_log = self.redis.lrange(_step_log_key(session_id), 0, -1)
        except AttributeError:
            step_log = []
        return steps + [json.loads(raw) for raw in step_log]

    def append_artifact(self, session_id: str, content: str) -> bool:
        """Append content to the session's accumulated artifact.

        Returns False if the session does not exist.
        """
        meta_key = _meta_key(session_id)
        if not self.redis.exists(meta_key):
            return False

        ttl_raw = self.redis.hget(meta_key, "ttl")
        ttl = int(ttl_raw) if ttl_raw else self.default_ttl

        existing: str = str(self.redis.get(_artifact_key(session_id)) or "")
        new_artifact = existing + content
        self.redis.set(
            _artifact_key(session_id),
            new_artifact,
            ex=ttl,
        )
        self.redis.hset(meta_key, "artifact_chars", len(new_artifact))
        self._refresh_ttl(session_id, ttl)
        return True

    def get_artifact(self, session_id: str) -> str:
        """Get the full accumulated artifact text."""
        return str(self.redis.get(_artifact_key(session_id)) or "")

    # ── Async storage boundary ─────────────────────────────────

    async def acreate(self, ttl: int | None = None) -> str:
        """Create a session without running blocking Redis I/O on the loop."""
        return await asyncio.to_thread(self.create, ttl)

    async def aget(self, session_id: str) -> dict | None:
        """Read session metadata off the event loop."""
        return await asyncio.to_thread(self.get, session_id)

    async def aupdate_meta(self, session_id: str, updates: dict) -> bool:
        return await asyncio.to_thread(self.update_meta, session_id, updates)

    async def aappend_step(self, session_id: str, step: dict) -> int | None:
        return await asyncio.to_thread(self.append_step, session_id, step)

    async def aget_steps(self, session_id: str) -> list[dict]:
        return await asyncio.to_thread(self.get_steps, session_id)

    async def aappend_artifact(self, session_id: str, content: str) -> bool:
        """Append a section atomically and maintain a Unicode length counter.

        ``APPEND`` avoids downloading and rewriting the accumulated artifact.
        The metadata counter uses Python's character length, deliberately
        avoiding Redis ``STRLEN`` byte semantics.  The existing sync method is
        retained for callers outside the async session path.
        """
        return await asyncio.to_thread(
            self._append_artifact_atomic, session_id, content
        )

    def _append_artifact_atomic(self, session_id: str, content: str) -> bool:
        meta_key = _meta_key(session_id)
        meta_raw = self.redis.hgetall(meta_key)
        if not meta_raw:
            return False
        ttl = int(meta_raw.get("ttl", self.default_ttl))
        counter_missing = meta_raw.get("artifact_chars") is None
        previous_chars = 0
        if counter_missing:
            # Read once when migrating a pre-counter session.  APPEND below
            # remains the only operation used for subsequent commits.
            previous_chars = len(str(self.redis.get(_artifact_key(session_id)) or ""))

        # A Lua commit closes the delete race between the metadata read and
        # the append: an expired/deleted session cannot have its meta key
        # recreated by HINCRBY.  The pipeline below remains a compatibility
        # fallback for small Redis doubles and older clients.
        script = """
        if redis.call('exists', KEYS[1]) == 0 then return 0 end
        redis.call('append', KEYS[2], ARGV[1])
        if ARGV[3] == 'set' then
            redis.call('hset', KEYS[1], 'artifact_chars', ARGV[2])
        else
            redis.call('hincrby', KEYS[1], 'artifact_chars', ARGV[2])
        end
        redis.call('hset', KEYS[1], 'expires_at', ARGV[4])
        for i = 1, 4 do redis.call('expire', KEYS[i], ARGV[5]) end
        return 1
        """
        try:
            result = self.redis.eval(
                script,
                4,
                meta_key,
                _artifact_key(session_id),
                _steps_key(session_id),
                _refs_key(session_id),
                content,
                str(previous_chars + len(content) if counter_missing else len(content)),
                "set" if counter_missing else "increment",
                _expires_iso(ttl),
                ttl,
            )
            if isinstance(result, int):
                return bool(result)
        except (AttributeError, TypeError, NotImplementedError):
            pass

        # Queue the append, counter, and one TTL refresh per session key in a
        # single transaction.  The fallback is for lightweight test doubles
        # and older Redis-compatible clients without pipeline transactions.
        try:
            pipe = self.redis.pipeline(transaction=True)
        except (AttributeError, TypeError):
            self.redis.append(_artifact_key(session_id), content)
            if counter_missing:
                self.redis.hset(
                    meta_key, "artifact_chars", previous_chars + len(content)
                )
            else:
                self.redis.hincrby(meta_key, "artifact_chars", len(content))
            self._refresh_ttl(session_id, ttl)
            return True

        pipe.append(_artifact_key(session_id), content)
        if counter_missing:
            pipe.hset(meta_key, "artifact_chars", previous_chars + len(content))
        else:
            pipe.hincrby(meta_key, "artifact_chars", len(content))
        pipe.hset(meta_key, "expires_at", _expires_iso(ttl))
        for key in _all_keys(session_id):
            pipe.expire(key, ttl)
        try:
            pipe.execute()
        except (AttributeError, TypeError):
            # A minimal fake may expose pipeline() but not these commands.
            # Do not swallow connection errors, which must remain visible to
            # callers instead of causing a second, duplicate append.
            self.redis.append(_artifact_key(session_id), content)
            if counter_missing:
                self.redis.hset(
                    meta_key, "artifact_chars", previous_chars + len(content)
                )
            else:
                self.redis.hincrby(meta_key, "artifact_chars", len(content))
            self._refresh_ttl(session_id, ttl)
        return True

    async def aget_artifact(self, session_id: str) -> str:
        return await asyncio.to_thread(self.get_artifact, session_id)

    async def aadd_ref(self, session_id: str, ref_id: str, ref_data: dict) -> bool:
        return await self.aadd_refs(session_id, {ref_id: ref_data})

    async def aadd_refs(self, session_id: str, refs: dict[str, dict]) -> bool:
        """Commit all refs for one step in one offloaded, pipelined operation."""
        return await asyncio.to_thread(self.add_refs, session_id, refs)

    def add_refs(self, session_id: str, refs: dict[str, dict]) -> bool:
        """Store a step's refs in bulk while refreshing its TTL once."""
        meta_key = _meta_key(session_id)
        meta_raw = self.redis.hgetall(meta_key)
        if not meta_raw:
            return False
        if not refs:
            return True
        ttl = int(meta_raw.get("ttl", self.default_ttl))
        encoded = {ref_id: json.dumps(ref_data) for ref_id, ref_data in refs.items()}
        refs_key = _refs_key(session_id)

        try:
            pipe = self.redis.pipeline(transaction=True)
        except (AttributeError, TypeError):
            self.redis.hset(refs_key, mapping=encoded)
            self.redis.hset(meta_key, "expires_at", _expires_iso(ttl))
            self._refresh_ttl(session_id, ttl)
            return True

        pipe.hset(refs_key, mapping=encoded)
        pipe.hset(meta_key, "expires_at", _expires_iso(ttl))
        for key in _all_keys(session_id):
            pipe.expire(key, ttl)
        try:
            pipe.execute()
        except (AttributeError, TypeError):
            self.redis.hset(refs_key, mapping=encoded)
            self.redis.hset(meta_key, "expires_at", _expires_iso(ttl))
            self._refresh_ttl(session_id, ttl)
        return True

    async def aget_ref(self, session_id: str, ref_id: str) -> dict | None:
        return await asyncio.to_thread(self.get_ref, session_id, ref_id)

    async def aget_refs(self, session_id: str) -> dict:
        return await asyncio.to_thread(self.get_refs, session_id)

    async def adelete(self, session_id: str) -> bool:
        return await asyncio.to_thread(self.delete, session_id)

    async def areserve_step(
        self,
        session_id: str,
        idempotency_key: str,
        lease_ttl: int = 120,
    ) -> dict | None:
        """Reserve an independent step without holding the session lock."""
        return await asyncio.to_thread(
            self.reserve_step, session_id, idempotency_key, lease_ttl
        )

    def reserve_step(
        self,
        session_id: str,
        idempotency_key: str,
        lease_ttl: int = 120,
    ) -> dict | None:
        """Reserve a stable step index and idempotency identity atomically."""
        meta_key = _meta_key(session_id)
        idempotency_hash = _idempotency_key(session_id)
        token = str(uuid.uuid4())
        now = int(datetime.now(UTC).timestamp())
        script = """
        if redis.call('exists', KEYS[1]) == 0 then return '' end
        local existing = redis.call('hget', KEYS[2], ARGV[1])
        if existing then
            local item = cjson.decode(existing)
            if item.status == 'committed' then return existing end
            if tonumber(item.expires_at or 0) > tonumber(ARGV[4]) then return existing end
        end
        local next_index = redis.call('hget', KEYS[1], 'next_step_index')
        if not next_index then
            next_index = redis.call('hget', KEYS[1], 'step_count') or '0'
            redis.call('hset', KEYS[1], 'next_step_index', next_index)
        end
        local index = redis.call('hincrby', KEYS[1], 'next_step_index', 1)
        local item = cjson.encode({status='pending', token=ARGV[2], index=index,
                                   revision=tonumber(redis.call('hget', KEYS[1], 'revision') or '0'),
                                   expires_at=tonumber(ARGV[4]) + tonumber(ARGV[3])})
        redis.call('hset', KEYS[2], ARGV[1], item)
        redis.call('expire', KEYS[2], ARGV[3])
        return item
        """
        try:
            raw = self.redis.eval(
                script,
                2,
                meta_key,
                idempotency_hash,
                idempotency_key,
                token,
                lease_ttl,
                now,
            )
            if raw in (None, ""):
                return None
            item = json.loads(raw)
            if item.get("status") == "pending" and item.get("token") == token:
                item["acquired"] = True
            return item
        except (AttributeError, TypeError, NotImplementedError):
            meta = self.redis.hgetall(meta_key)
            if not meta:
                return None
            existing_raw = self.redis.hget(idempotency_hash, idempotency_key)
            if existing_raw:
                existing = json.loads(existing_raw)
                if (
                    existing.get("status") == "committed"
                    or int(existing.get("expires_at", 0)) > now
                ):
                    return existing
            next_index = int(meta.get("next_step_index", meta.get("step_count", 0))) + 1
            revision = int(meta.get("revision", 0))
            item = {
                "status": "pending",
                "token": token,
                "index": next_index,
                "revision": revision,
                "expires_at": now + lease_ttl,
            }
            self.redis.hset(meta_key, "next_step_index", next_index)
            self.redis.hset(idempotency_hash, idempotency_key, json.dumps(item))
            self.redis.expire(idempotency_hash, lease_ttl)
            item["acquired"] = True
            return item

    async def acommit_step(
        self,
        session_id: str,
        reservation: dict,
        step: dict,
        refs: dict[str, dict],
        artifact: str,
        result: dict,
        ttl: int | None = None,
    ) -> dict | None:
        return await asyncio.to_thread(
            self.commit_step,
            session_id,
            reservation,
            step,
            refs,
            artifact,
            result,
            ttl,
        )

    def commit_step(
        self,
        session_id: str,
        reservation: dict,
        step: dict,
        refs: dict[str, dict],
        artifact: str,
        result: dict,
        ttl: int | None = None,
    ) -> dict | None:
        """Publish an independent step atomically after its remote work."""
        meta_key = _meta_key(session_id)
        steps_key = _steps_key(session_id)
        step_log_key = _step_log_key(session_id)
        artifact_key = _artifact_key(session_id)
        refs_key = _refs_key(session_id)
        idempotency_hash = _idempotency_key(session_id)
        effective_ttl = ttl or self.default_ttl
        encoded_refs = {ref_id: json.dumps(data) for ref_id, data in refs.items()}
        stored_result = json.dumps({"status": "committed", "result": result})
        step_json = json.dumps(step)
        refs_args: list[str] = []
        for ref_id, data in encoded_refs.items():
            refs_args.extend((ref_id, data))
        script = """
        if redis.call('exists', KEYS[1]) == 0 then return '' end
        local existing = redis.call('hget', KEYS[5], ARGV[1])
        if not existing then return '' end
        local item = cjson.decode(existing)
        if item.status == 'committed' then return existing end
        if item.token ~= ARGV[2] then return '' end
        local revision = tonumber(redis.call('hget', KEYS[1], 'revision') or '0')
        if revision < tonumber(ARGV[4]) then return '' end
        local step = cjson.decode(ARGV[5])
        local ref_count = tonumber(ARGV[6])
        local artifact_arg = 7 + (ref_count * 2)
        redis.call('rpush', KEYS[6], ARGV[5])
        local arg = 7
        for i = 1, ref_count do
            redis.call('hset', KEYS[4], ARGV[arg], ARGV[arg + 1])
            arg = arg + 2
        end
        redis.call('append', KEYS[3], ARGV[artifact_arg])
        redis.call('hincrby', KEYS[1], 'step_count', 1)
        redis.call('hincrby', KEYS[1], 'artifact_chars', tonumber(ARGV[artifact_arg + 1]))
        redis.call('hset', KEYS[1], 'revision', revision + 1,
                   'expires_at', ARGV[artifact_arg + 3])
        redis.call('hset', KEYS[5], ARGV[1], ARGV[artifact_arg + 2])
        for i = 1, 6 do redis.call('expire', KEYS[i], ARGV[artifact_arg + 4]) end
        return ARGV[artifact_arg + 2]
        """
        # ARGV layout after refs: artifact, character delta, result, expires_at,
        # and the fixed TTL. Build the prefix and append values, then let Lua
        # index from the ref count.
        args = [
            reservation["idempotency_key"],
            reservation["token"],
            str(effective_ttl),
            str(reservation["revision"]),
            step_json,
            str(len(encoded_refs)),
            *refs_args,
            artifact,
            str(len(artifact)),
            stored_result,
            _expires_iso(effective_ttl),
            str(effective_ttl),
        ]
        try:
            raw = self.redis.eval(
                script,
                6,
                meta_key,
                steps_key,
                artifact_key,
                refs_key,
                idempotency_hash,
                step_log_key,
                *args,
            )
            if raw in (None, ""):
                return None
            decoded = json.loads(raw)
            return (
                decoded.get("result")
                if decoded.get("status") == "committed"
                else decoded
            )
        except (AttributeError, TypeError, NotImplementedError):
            # Compatibility fallback for minimal test doubles.  The normal
            # deployment path uses the atomic script above.
            if not self.redis.exists(meta_key):
                return None
            current = self.redis.hget(idempotency_hash, reservation["idempotency_key"])
            if not current:
                return None
            current_item = json.loads(current)
            if current_item.get("status") == "committed":
                return current_item.get("result")
            if current_item.get("token") != reservation["token"]:
                return None
            step_index = int(reservation["index"])
            step["index"] = step_index
            try:
                self.redis.rpush(step_log_key, json.dumps(step))
            except AttributeError:
                steps_raw = self.redis.get(steps_key)
                steps = json.loads(steps_raw) if steps_raw else []
                steps.append(step)
                self.redis.set(steps_key, json.dumps(steps), ex=effective_ttl)
            self.redis.hset(
                idempotency_hash, reservation["idempotency_key"], stored_result
            )
            for ref_id, data in encoded_refs.items():
                self.redis.hset(refs_key, ref_id, data)
            self.redis.append(artifact_key, artifact)
            self.redis.hincrby(meta_key, "step_count", 1)
            self.redis.hincrby(meta_key, "artifact_chars", len(artifact))
            self.redis.hincrby(meta_key, "revision", 1)
            self.redis.expire(step_log_key, effective_ttl)
            return result

    async def arelease_step(self, session_id: str, reservation: dict) -> None:
        await asyncio.to_thread(self.release_step, session_id, reservation)

    def release_step(self, session_id: str, reservation: dict) -> None:
        """Release only this caller's pending idempotency reservation."""
        script = """
        local existing = redis.call('hget', KEYS[1], ARGV[1])
        if existing and cjson.decode(existing).token == ARGV[2] then
            redis.call('hdel', KEYS[1], ARGV[1])
        end
        return 1
        """
        try:
            self.redis.eval(
                script,
                1,
                _idempotency_key(session_id),
                reservation["idempotency_key"],
                reservation["token"],
            )
        except (AttributeError, TypeError, NotImplementedError):
            current = self.redis.hget(
                _idempotency_key(session_id), reservation["idempotency_key"]
            )
            if current and json.loads(current).get("token") == reservation["token"]:
                self.redis.hdel(
                    _idempotency_key(session_id), reservation["idempotency_key"]
                )

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

    async def acquire_lock(
        self, session_id: str, timeout: int = 30, lease_ttl: int = 120
    ) -> str | None:
        """Acquire a per-session lock for concurrent step execution.

        Uses ``SETNX`` with async blocking retry so that concurrent steps
        on the same session are serialised rather than rejected.  The lock
        value is an ownership token (UUID) used for compare-and-delete on
        release, preventing accidental deletion of another caller's lock
        after lease expiry.

        Per ADR-0040: "If two steps race on the same session, the second
        waits for the first's step to complete."  This implementation
        blocks with exponential backoff (up to 50ms max delay) using
        ``asyncio.sleep`` to avoid blocking the FastAPI event loop.

        Args:
            session_id: The session to lock.
            timeout: Maximum time in seconds to wait for the lock
                (default 30).  Only affects how long we block before
                giving up.
            lease_ttl: How long the lock key lives in Valkey before
                auto-expiring (default 120).  Must be longer than the
                longest expected step (e.g. scrape timeout = 70s).

        Returns:
            The ownership token (str) if the lock was acquired, or
            ``None`` if the timeout was exceeded without acquiring
            the lock.
        """
        import time as _time
        import uuid as _uuid

        owner_token = str(_uuid.uuid4())
        deadline = _time.monotonic() + timeout
        backoff = 0.005  # start at 5ms
        max_backoff = 0.05  # cap at 50ms

        while _time.monotonic() < deadline:
            acquired = await asyncio.to_thread(
                self.redis.set,
                _lock_key(session_id),
                owner_token,
                nx=True,
                ex=lease_ttl,
            )
            if acquired:
                return owner_token
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)

        return None

    def release_lock(self, session_id: str, owner_token: str) -> None:
        """Release the per-session lock using compare-and-delete.

        Only deletes the lock key if its current value matches
        *owner_token*, preventing accidental deletion of another
        caller's lock after lease expiry and re-acquisition.

        Args:
            session_id: The session to unlock.
            owner_token: The ownership token returned by
                :meth:`acquire_lock`.
        """
        lock_key = _lock_key(session_id)
        # Lua script for atomic compare-and-delete
        script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """
        self.redis.eval(script, 1, lock_key, owner_token)

    async def arelease_lock(self, session_id: str, owner_token: str) -> None:
        """Release a lock without blocking the event loop."""
        await asyncio.to_thread(self.release_lock, session_id, owner_token)

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
