"""Utility functions for the research package."""

import json
import logging

from jsonschema import SchemaError, ValidationError
from jsonschema.validators import validator_for

from ..exceptions import StructuredOutputError

logger = logging.getLogger(__name__)


def _validate_json_if_schema(answer: str, schema: dict | None) -> None:
    """Reject non-JSON or schema-invalid structured output.

    This intentionally covers the JSON Schema constructs used by public
    ``output_schema`` examples without adding a second schema dependency.
    """
    if not schema:
        return
    try:
        cleaned = answer.strip()
        cleaned = cleaned.removeprefix("```json")
        cleaned = cleaned.removeprefix("```")
        cleaned = cleaned.removesuffix("```")
        value = json.loads(cleaned)
        validator_cls = validator_for(schema)
        validator_cls.check_schema(schema)
        validator_cls(schema).validate(value)
    except (
        json.JSONDecodeError,
        SchemaError,
        ValidationError,
        TypeError,
        AttributeError,
        KeyError,
    ) as exc:
        logger.warning("LLM response failed structured-output validation: %s", exc)
        raise StructuredOutputError(
            detail="LLM response did not satisfy the requested output schema"
        ) from exc
