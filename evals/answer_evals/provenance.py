"""Run provenance assembly for the grounded-answer eval harness (issue #570).

Each run writes a JSON artifact containing only an allowlisted schema: run id,
timestamp, commit sha, suite version, selection, and per-case fixture
scenario/schema/fixture versions, parsed model id and base-URL host only, grader
id/version, verdicts, outcome, and artifact path. Forbidden content (prompts,
headers, URL query strings/userinfo, environment dumps, arbitrary config,
secrets) is never serialized. Provenance never auto-writes or replaces the
pinned baseline.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .harness import load_manifest

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"(?i)(api[_-]?key|secret|token|password|authorization)\s*[:=]\s*\S+"),
]

REDACTED = "[REDACTED]"


def get_commit_sha() -> str | None:
    """Best-effort commit SHA from the environment or git, never failing."""
    env_sha = os.environ.get("GITHUB_SHA")
    if env_sha:
        return env_sha
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def forbidden_keys() -> set[str]:
    manifest = load_manifest()
    return set((manifest.get("provenance") or {}).get("forbidden_keys") or [])


def allowlisted_keys() -> set[str]:
    manifest = load_manifest()
    return set((manifest.get("provenance") or {}).get("allowlisted_keys") or [])


def _redact_value(value: str) -> str:
    redacted = value
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(REDACTED, redacted)
    return redacted


def sanitize(value: Any) -> Any:
    """Recursively drop forbidden keys and redact secret-like values."""
    forbidden = forbidden_keys()
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if key in forbidden:
                continue
            if re.search(
                r"(api[_-]?key|secret|token|password|authorization|prompt|query|answer|header|cookie)",
                key,
                re.IGNORECASE,
            ):
                continue
            cleaned[key] = sanitize(item)
        return cleaned
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        return _redact_value(value)
    return value


def validate_allowlist(data: Any) -> None:
    """Fail closed when any serialized key is outside the provenance allowlist."""
    allowed = allowlisted_keys()
    stack = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for key in node:
                if key not in allowed:
                    raise ValueError(
                        f"provenance key {key!r} is not allowlisted "
                        f"(schema {load_manifest().get('provenance_schema_version')})"
                    )
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)


def build_provenance(
    *,
    run_id: str,
    selection: str,
    target: str | None,
    record_baseline: bool,
    case_records: list[dict],
    commit_sha: str | None = None,
    manifest: dict | None = None,
) -> dict:
    """Assemble the allowlisted provenance document for a selection run."""
    manifest = manifest or load_manifest()
    cases: list[dict[str, Any]] = []
    for record in case_records:
        fixture = record.get("fixture") or {}
        cases.append(
            {
                "case_id": record.get("case_id"),
                "case_path": record.get("case_path"),
                "request_hash": record.get("request_hash"),
                "search_fixture": fixture.get("search_fixture"),
                "llm_fixture": fixture.get("llm_fixture"),
                "model": fixture.get("model"),
                "llm_base_url_host": fixture.get("llm_base_url_host"),
                "graders": record.get("graders", []),
                "verdicts": [
                    {"grader": verdict.get("grader"), "pass": verdict.get("pass")}
                    for verdict in record.get("verdicts", [])
                ],
                "outcome": record.get("outcome"),
                "artifact_path": record.get("artifact_path"),
            }
        )
    provenance = {
        "schema_version": manifest.get("provenance_schema_version"),
        "suite_version": manifest.get("suite_version"),
        "run_id": run_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "commit_sha": commit_sha,
        "selection": selection,
        "target": target,
        "record_baseline": record_baseline,
        "cases": cases,
    }
    validate_allowlist(provenance)
    return sanitize(provenance)


def write_provenance(path: Path, provenance: dict) -> Path:
    """Write the sanitized provenance document to *path*."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    validate_allowlist(provenance)
    cleaned = sanitize(provenance)
    validate_allowlist(cleaned)
    path.write_text(json.dumps(cleaned, indent=2, sort_keys=True) + "\n")
    return path
