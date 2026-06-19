"""Job CRUD operations backed by Valkey.

Stores job metadata, status, and results in Valkey key-value store.
Uses the same valkey connection for both the API and the worker.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta

from redis import Redis


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _expires_iso() -> str:
    """Return ISO 8601 timestamp for 24 hours from now."""
    return (datetime.now(UTC) + timedelta(hours=24)).isoformat()


def _default_ttl() -> int:
    """Jobs expire after 24 hours."""
    return 86400


class JobStore:
    """Simple Valkey-backed job store.

    Key schema:
      job:{id}:meta  -> JSON with status, created_at, etc.
      job:{id}:data  -> JSON with result data (set on completion)
    """

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self.redis = Redis.from_url(redis_url, decode_responses=True)

    def create_job(self, kind: str = "agent", payload: dict | None = None) -> str:
        """Create a new job and return its ID."""
        job_id = str(uuid.uuid4())
        meta = {
            "id": job_id,
            "kind": kind,
            "status": "processing",
            "created_at": _now_iso(),
            "expires_at": _expires_iso(),
            "payload": payload or {},
        }
        self.redis.set(f"job:{job_id}:meta", json.dumps(meta), ex=_default_ttl())
        return job_id

    def get_job(self, job_id: str) -> dict | None:
        """Get job metadata. Returns None if not found."""
        raw = self.redis.get(f"job:{job_id}:meta")
        if raw is None:
            return None
        meta = json.loads(raw)
        # Attach data if available
        data_raw = self.redis.get(f"job:{job_id}:data")
        if data_raw:
            meta["data"] = json.loads(data_raw)
        return meta  # type: ignore[no-any-return]

    def complete_job(self, job_id: str, data: dict) -> None:
        """Mark a job as completed with its result data."""
        meta_raw = self.redis.get(f"job:{job_id}:meta")
        if meta_raw is None:
            return
        meta = json.loads(meta_raw)
        meta["status"] = "completed"
        meta["completed_at"] = _now_iso()
        self.redis.set(f"job:{job_id}:meta", json.dumps(meta), ex=_default_ttl())
        self.redis.set(f"job:{job_id}:data", json.dumps(data), ex=_default_ttl())

    def fail_job(self, job_id: str, error: str) -> None:
        """Mark a job as failed with an error message."""
        meta_raw = self.redis.get(f"job:{job_id}:meta")
        if meta_raw is None:
            return
        meta = json.loads(meta_raw)
        meta["status"] = "failed"
        meta["error"] = error
        meta["completed_at"] = _now_iso()
        self.redis.set(f"job:{job_id}:meta", json.dumps(meta), ex=_default_ttl())

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a job that's still processing. Returns True if cancelled."""
        meta_raw = self.redis.get(f"job:{job_id}:meta")
        if meta_raw is None:
            return False
        meta = json.loads(meta_raw)
        if meta["status"] != "processing":
            return False
        meta["status"] = "cancelled"
        meta["completed_at"] = _now_iso()
        self.redis.set(f"job:{job_id}:meta", json.dumps(meta), ex=_default_ttl())
        return True

    def list_active_jobs(
        self, kind: str | None = None, status: str = "processing", limit: int = 50
    ) -> list[dict]:
        """List jobs by status, optionally filtered by kind.

        Uses Valkey SCAN with pattern ``job:*:meta`` — no dedicated index.
        For production at scale, replace with a sorted set or dedicated index.

        Args:
            kind: If set, only return jobs of this kind (``crawl``, ``agent``, etc.)
            status: Status filter (default ``processing``)
            limit: Maximum jobs to return (default 50)

        Returns:
            List of job metadata dicts (without attached data payloads).
        """
        active: list[dict] = []
        cursor = 0
        while len(active) < limit:
            cursor, keys = self.redis.scan(cursor=cursor, match="job:*:meta", count=100)
            if not keys:
                if cursor == 0:
                    break
                continue
            pipe = self.redis.pipeline()
            for key in keys:
                pipe.get(key)
            results = pipe.execute()
            for raw in results:
                if raw is None:
                    continue
                meta = json.loads(raw)
                if meta.get("status") != status:
                    continue
                if kind is not None and meta.get("kind") != kind:
                    continue
                active.append(meta)
                if len(active) >= limit:
                    return active
            if cursor == 0:
                break
        return active
