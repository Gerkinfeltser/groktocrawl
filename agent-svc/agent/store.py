"""Job CRUD operations backed by Valkey.

Stores job metadata, status, and results in Valkey key-value store.
Uses the same valkey connection for both the API and the worker.
"""

import json
import time
import uuid
from datetime import datetime, timezone

from redis import Redis


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
        return meta

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
