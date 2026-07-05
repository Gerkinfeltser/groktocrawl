"""Webhook utilities — re-export for route files that need webhook delivery.

No standalone routes exist in this domain; route handlers import
``deliver_webhook`` from ``..webhook`` directly when needed.
"""

import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter()
