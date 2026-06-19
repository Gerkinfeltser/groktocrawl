"""Webhook delivery for async job endpoints.

Called from worker functions after store.complete_job() / store.fail_job().
Retries with exponential backoff, optional HMAC signing.
Each event includes a unique ``webhookId`` for receiver-side deduplication
(VAL-CONC-050).
"""

import asyncio
import hashlib
import hmac
import json
import logging

import httpx

from .settings import load_settings

logger = logging.getLogger(__name__)

_webhook_settings = load_settings()
MAX_RETRIES = 3
TIMEOUT_SECONDS = 5

# Counter for generating unique webhook IDs within a job/event scope
_webhook_id_counter: dict[str, int] = {}


def _next_webhook_id(job_id: str, event: str) -> str:
    """Generate a unique, deterministic webhook ID for deduplication.

    Uses an in-memory counter per (job_id, event) pair. The resulting
    ID has the format ``{job_id}-{event}-{seq}`` where ``seq`` is a
    monotonically increasing integer unique within that job+event scope.

    For page events, the caller should pass a page-specific event key
    (e.g. ``crawl.page-{url}``) so that each page gets distinct IDs.
    For lifecycle events (started, completed), the plain event name
    ensures exactly one firing.

    Returns:
        A unique string like ``"abc-123-crawl.page-1"``.
    """
    counter_key = f"{job_id}:{event}"
    _webhook_id_counter[counter_key] = _webhook_id_counter.get(counter_key, 0) + 1
    seq = _webhook_id_counter[counter_key]
    return f"{job_id}-{event}-{seq}"


def _sign_body(body: bytes, secret: str) -> str:
    """HMAC-SHA256 sign the request body."""
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def deliver_webhook(
    webhook_config: dict | None,
    event: str,
    job_id: str,
    data: dict | None = None,
    webhook_id_key: str | None = None,
    task_tracker: object = None,
) -> None:
    """POST a job event to the configured webhook URL with retry logic.

    Each delivery includes a unique ``webhookId`` field for receiver-side
    deduplication (VAL-CONC-050). The ID is generated deterministically
    based on ``job_id`` and ``webhook_id_key`` (or ``event`` if not given).

    Args:
        webhook_config: Dict with 'url' and optional 'events' list.
                        Example: ``{"url": "https://example.com/hook", "events": ["completed", "failed"]}``
        event: The event type (e.g. ``"completed"``, ``"failed"``,
               ``"crawl.started"``, ``"crawl.page"``).
        job_id: The job identifier.
        data: Optional payload to include in the body.
        webhook_id_key: Key used to generate a unique webhookId. If not set,
                        falls back to ``event``. Pass unique values per-page
                        (e.g. ``f"crawl.page-{url}"``) to ensure each page
                        gets a distinct idempotency key.
        task_tracker: Optional ``TaskTracker`` instance. If provided, the
                      webhook delivery is spawned as a tracked background
                      task instead of executing inline.
    """
    if not webhook_config:
        return

    url = webhook_config.get("url")
    if not url:
        return

    # Respect events filter — if events list provided, only fire for matching events
    events_filter = webhook_config.get("events")
    if events_filter and event not in events_filter:
        return

    id_key = webhook_id_key or event
    webhook_id = _next_webhook_id(job_id, id_key)

    payload = {
        "event": event,
        "id": job_id,
        "webhookId": webhook_id,
        "data": data or {},
    }
    body = json.dumps(payload).encode()

    headers = {"Content-Type": "application/json"}
    if _webhook_settings.webhook_secret:
        headers["X-Webhook-Signature"] = (
            f"sha256={_sign_body(body, _webhook_settings.webhook_secret)}"
        )

    async def _do_deliver() -> None:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
                    resp = await client.post(url, content=body, headers=headers)
                    if resp.status_code < 500:
                        logger.info(
                            "Webhook delivered %s for job %s (webhookId=%s, status %d)",
                            event,
                            job_id,
                            webhook_id,
                            resp.status_code,
                        )
                        return
                    logger.warning(
                        "Webhook attempt %d/%d returned %d for job %s (webhookId=%s)",
                        attempt,
                        MAX_RETRIES,
                        resp.status_code,
                        job_id,
                        webhook_id,
                    )
            except httpx.TimeoutException:
                logger.warning(
                    "Webhook attempt %d/%d timed out for job %s (webhookId=%s)",
                    attempt,
                    MAX_RETRIES,
                    job_id,
                    webhook_id,
                )
            except Exception as e:
                logger.warning(
                    "Webhook attempt %d/%d failed for job %s: %s (webhookId=%s)",
                    attempt,
                    MAX_RETRIES,
                    job_id,
                    e,
                    webhook_id,
                )

            if attempt < MAX_RETRIES:
                await asyncio.sleep(2**attempt)  # 2s, 4s

        logger.error(
            "Webhook delivery failed for job %s after %d attempts (webhookId=%s)",
            job_id,
            MAX_RETRIES,
            webhook_id,
        )

    if task_tracker is not None and hasattr(task_tracker, "create_background_task"):
        task_tracker.create_background_task(_do_deliver())
    else:
        await _do_deliver()
