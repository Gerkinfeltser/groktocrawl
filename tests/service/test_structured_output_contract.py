"""Conforming JSON Schema validation at the LLM consuming boundary."""

import pytest
from agent.exceptions import StructuredOutputError
from agent.research.utils import _validate_json_if_schema


@pytest.mark.parametrize(
    ("schema", "value"),
    [
        (
            {
                "type": "object",
                "required": ["name"],
                "properties": {"name": {"type": "string"}},
            },
            '{"name":"ok"}',
        ),
        (
            {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["id"],
                            "properties": {"id": {"type": "integer"}},
                        },
                    }
                },
            },
            '{"items":[{"id":1}]}',
        ),
        ({"type": "string", "enum": ["a", "b"]}, '"a"'),
        (
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"ok": {"type": "boolean"}},
            },
            '{"ok":true}',
        ),
        ({"type": "string", "pattern": "^[A-Z]+$", "minLength": 2}, '"OK"'),
        ({"oneOf": [{"const": "x"}, {"type": "array", "maxItems": 1}]}, '"x"'),
    ],
)
def test_supported_json_schema_constructs(schema, value):
    _validate_json_if_schema(value, schema)


@pytest.mark.parametrize(
    ("schema", "value"),
    [
        (
            {
                "type": "object",
                "required": ["name"],
                "properties": {"name": {"type": "string"}},
            },
            "{}",
        ),
        (
            {"type": "object", "additionalProperties": False, "properties": {}},
            '{"extra":1}',
        ),
        ({"type": "string", "pattern": "^[A-Z]+$", "minLength": 2}, '"bad"'),
        ({"oneOf": [{"const": "x"}, {"type": "array", "maxItems": 1}]}, "[1,2]"),
        ({"type": "object", "properties": {"x": {"type": "mystery"}}}, '{"x":1}'),
        ({"type": "object", "properties": []}, "{}"),
        ("not-a-schema", "{}"),
    ],
)
def test_invalid_instances_and_schemas_raise_typed_error(schema, value):
    with pytest.raises(StructuredOutputError):
        _validate_json_if_schema(value, schema)
