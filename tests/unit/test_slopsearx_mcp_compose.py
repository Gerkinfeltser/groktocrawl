"""Deterministic contract tests for the direct SlopSearX MCP Compose service."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text())


def _environment(service: dict[str, object]) -> dict[str, str]:
    return dict(item.split("=", 1) for item in service["environment"])


def _resolve(value: str, variables: dict[str, str]) -> str:
    """Resolve the Compose interpolation forms used by this service."""
    match = re.fullmatch(r"\$\{([A-Z0-9_]+)(?::([?-])(.+))?\}", value)
    if not match:
        return value
    key, operator, fallback = match.groups()
    configured = variables.get(key, "")
    if operator == "-":
        return configured or fallback
    if operator == "?":
        if not configured:
            raise ValueError(fallback)
        return configured
    return configured


def test_direct_slopsearx_mcp_is_default_on_and_uses_shared_wiring():
    service = COMPOSE["services"]["slopsearx-mcp"]
    environment = _environment(service)

    assert service["image"] == "ghcr.io/magnus919/slopsearx:latest"
    assert "profiles" not in service
    assert service["command"] == ["-m", "slopsearx.mcp"]
    assert service["ports"] == ["${SLOPSEARX_MCP_PORT:-8007}:8000"]
    assert _resolve("${SLOPSEARX_MCP_PORT:-8007}", {}) == "8007"
    assert (
        _resolve("${SLOPSEARX_MCP_PORT:-8007}", {"SLOPSEARX_MCP_PORT": "9007"})
        == "9007"
    )
    assert environment["ENGINE_BRAVE_API_KEY"] == "${BRAVE_API_KEY}"
    assert environment["VALKEY_URL"] == "redis://valkey:6379/0"


def test_direct_slopsearx_mcp_grants_default_on_and_allow_opt_out():
    environment = _environment(COMPOSE["services"]["slopsearx-mcp"])
    grant_names = (
        "MCP_GRANT_JOBS",
        "MCP_GRANT_SCIENCE",
        "MCP_GRANT_RESEARCH",
        "MCP_GRANT_SECURITY",
        "MCP_TARGETED_SENSITIVE_ALLOWED",
    )

    assert {_resolve(environment[name], {}) for name in grant_names} == {"1"}
    disabled: dict[str, str] = {name: "0" for name in grant_names}  # noqa: C420
    assert {_resolve(environment[name], disabled) for name in grant_names} == {"0"}


def test_direct_slopsearx_mcp_requires_token_and_has_protocol_healthcheck():
    service = COMPOSE["services"]["slopsearx-mcp"]
    environment = _environment(service)

    with pytest.raises(ValueError, match="SLOPSEARX_MCP_AUTH_TOKEN must be set"):
        _resolve(environment["MCP_AUTH_TOKEN"], {})
    assert (
        _resolve(environment["MCP_AUTH_TOKEN"], {"SLOPSEARX_MCP_AUTH_TOKEN": "token"})
        == "token"
    )

    probe = service["healthcheck"]["test"][-1]
    compile(probe, "<slopsearx-mcp healthcheck>", "exec")
    assert "http://127.0.0.1:8000/mcp" in probe
    assert "'method':'initialize'" in probe
    assert "'Authorization':'Bearer ' + os.environ['MCP_AUTH_TOKEN']" in probe
    assert "timeout=3" in probe
    assert "response.readline(65536)" in probe
    assert "range(8)" in probe
    assert "line.startswith('data:')" in probe
    assert "get_content_type() == 'text/event-stream'" in probe
    assert "response.read(65536)" in probe
    assert "json.loads(next(" in probe
    assert "serverInfo" in probe
