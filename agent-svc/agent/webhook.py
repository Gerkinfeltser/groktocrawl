"""Webhook delivery for async job endpoints.

Called from worker functions after store.complete_job() / store.fail_job().
Retries with exponential backoff, optional HMAC signing.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os

import httpx

logger = logging.getLogger(__name__)

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
MAX_RETRIES = 3
TIMEOUT_SECONDS = 5


def _sign_body(body: bytes, secret: str) -> str:
    """HMAC-SHA256 sign the request body."""
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def deliver_webhook(
    webhook_config: dict | None,
    event: str,
    job_id: str,
    data: dict | None = None,
) -> None:
    """POST a job event to the configured webhook URL with retry logic.

    Args:
        webhook_config: Dict with 'url' and optional 'events' list.
                        Example: {"url": "https://example.com/hook", "events": ["completed", "failed"]}
        event: The event type (e.g. "completed", "failed", "started").
        job_id: The job identifier.
        data: Optional payload to include in the body.
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

    payload = {
        "event": event,
        "id": job_id,
        "data": data or {},
    }
    body = json.dumps(payload).encode()

    headers = {"Content-Type": "application/json"}
    if WEBHOOK_SECRET:
        headers["X-Webhook-Signature"] = f"sha256={_sign_body(body, WEBHOOK_SECRET)}"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
                resp = await client.post(url, content=body, headers=headers)
                if resp.status_code < 500:
                    logger.info("Webhook delivered %s for job %s (status %d)", event, job_id, resp.status_code)
                    return
                logger.warning("Webhook attempt %d/%d returned %d for job %s", attempt, MAX_RETRIES, resp.status_code, job_id)
        except httpx.TimeoutException:
            logger.warning("Webhook attempt %d/%d timed out for job %s", attempt, MAX_RETRIES, job_id)
        except Exception as e:
            logger.warning("Webhook attempt %d/%d failed for job %s: %s", attempt, MAX_RETRIES, job_id, e)

        if attempt < MAX_RETRIES:
            await asyncio.sleep(2 ** attempt)  # 2s, 4s

    logger.error("Webhook delivery failed for job %s after %d attempts", job_id, MAX_RETRIES)
