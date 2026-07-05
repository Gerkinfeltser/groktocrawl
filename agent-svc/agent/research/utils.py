"""Utility functions for the research package."""

import json
import logging

logger = logging.getLogger(__name__)


def _validate_json_if_schema(answer: str, schema: dict | None) -> None:
    """If a schema was provided, attempt to parse the answer as JSON."""
    if not schema:
        return
    try:
        cleaned = answer.strip()
        cleaned = cleaned.removeprefix("```json")
        cleaned = cleaned.removeprefix("```")
        cleaned = cleaned.removesuffix("```")
        json.loads(cleaned)
    except (json.JSONDecodeError, Exception) as e:
        logger.warning("LLM response not valid JSON despite schema: %s", e)
