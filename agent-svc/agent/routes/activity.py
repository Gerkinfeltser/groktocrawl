"""Activity route handler — lists active jobs across all types."""

import logging

from fastapi import APIRouter, Request

from ..models import ActivityItem, ActivityResponse
from ..store import JobStore

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/v2/activity", response_model=ActivityResponse)
async def list_activity(request: Request) -> ActivityResponse:
    """List all active/processing jobs across all job types.

    Returns jobs with status ``processing``, ordered by creation time.
    Completed and failed jobs are excluded (they TTL out after 24h).
    """
    store: JobStore = request.app.state.job_store
    jobs = store.list_active_jobs(limit=50)
    items: list[ActivityItem] = []
    for job in jobs:
        payload = job.get("payload") or {}
        url = payload.get("url") if isinstance(payload, dict) else None
        items.append(
            ActivityItem(
                id=job["id"],
                kind=job.get("kind", "unknown"),
                status=job.get("status", "processing"),
                url=url,
                created_at=job.get("created_at", ""),
                completed_at=job.get("completed_at"),
            )
        )
    return ActivityResponse(data=items)
