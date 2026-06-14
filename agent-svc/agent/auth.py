"""API key authentication for GroktoCrawl."""

import logging

from fastapi import HTTPException, Request

from .settings import load_settings

logger = logging.getLogger(__name__)

SECURITY_WARNING_HEADER = "X-Security-Warning"
SECURITY_WARNING_BODY = (
    "No API key configured. API is publicly accessible without authentication. "
    "Set API_KEY in your .env file to enable authentication."
)

_settings = load_settings()
AUTH_ENABLED = _settings.api_key != ""
API_KEY = _settings.api_key


async def verify_api_key(request: Request) -> None:
    if not AUTH_ENABLED:
        return
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer ") and auth_header[7:] == API_KEY:
        return
    x_api_key = request.headers.get("X-API-Key", "")
    if x_api_key == API_KEY:
        return
    raise HTTPException(status_code=403, detail="Invalid or missing API key.")
