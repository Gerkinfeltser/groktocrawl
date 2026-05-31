"""API key authentication for GroktoCrawl.

Provides optional API key enforcement. When API_KEY is not set in the
environment, all requests are allowed (backward-compatible mode) with
a security warning emitted on every response.
"""
import logging
import os

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

# Header name used to warn callers when auth is disabled
SECURITY_WARNING_HEADER = "X-Security-Warning"
SECURITY_WARNING_BODY = (
    "No API key configured. API is publicly accessible without authentication. "
    "Set API_KEY in your .env file to enable authentication."
)

# Read API key from environment (optional)
_api_key = os.environ.get("API_KEY", "").strip()
AUTH_ENABLED = bool(_api_key)
API_KEY = _api_key


async def verify_api_key(request: Request) -> None:
    """Verify the API key from the Authorization header.

    FastAPI dependency. If no API_KEY is configured, all requests are
    allowed (backward compat). If API_KEY is configured, the caller must
    provide Authorization: Bearer <key> or X-API-Key: <key>.
    """
    if not AUTH_ENABLED:
        return

    # Try Bearer token from header
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        provided_key = auth_header[7:]
        if provided_key == API_KEY:
            return

    # Also check X-API-Key header as a convenience
    x_api_key = request.headers.get("X-API-Key", "")
    if x_api_key == API_KEY:
        return

    raise HTTPException(
        status_code=403,
        detail="Invalid or missing API key. Provide it via Authorization: Bearer <key> or X-API-Key header.",
    )
