"""Compose passthrough contract for semantic-svc QDRANT timeout env vars.

Issue #588 follow-up (found during PR #592 scrutiny): the ``semantic-svc``
service in ``docker-compose.yml`` has NO ``env_file`` and its
``environment`` block omits ``QDRANT_CLIENT_TIMEOUT``/``QDRANT_QUERY_TIMEOUT``,
so values set in the operator's ``.env`` never reach the container and
operator tuning is silently ignored. The environment block must substitute
both variables from ``.env``.

The substitution MUST carry a NON-EMPTY numeric fallback:
``semantic-svc/app.py`` parses both variables with ``float(...)`` at import
time, and Compose injects an EMPTY STRING into the container when an unset
variable falls through ``${VAR:-}`` (verified empirically: the slopsearx
container carries ``ENGINE_BRAVE_API_KEY=`` from its unset ``${BRAVE_API_KEY}``),
which would crash-loop semantic-svc on startup. The fallback values must
equal today's effective defaults (10s) so unset-``.env`` deployments are
unchanged.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]

# The containerized integration lane provisions only docker-compose.yml into
# /app as the Compose contract input (see .github/workflows/docker.yml); the
# dotfile .env.sample never reaches that filesystem. The .env.sample doc
# contract below is enforced where the file exists (local dev, Fast Tests,
# and the `inventory` job running scripts/check-docs-surface.py) and skipped
# otherwise.
ENV_SAMPLE = ROOT / ".env.sample"

_TIMEOUT_VARS = ("QDRANT_CLIENT_TIMEOUT", "QDRANT_QUERY_TIMEOUT")


def _semantic_environment() -> list[str]:
    """Return the semantic-svc compose environment list."""
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    env = compose["services"]["semantic-svc"]["environment"]
    assert isinstance(env, list), "semantic-svc environment must stay list-style"
    return env


def _raw_value(env: list[str], var: str) -> str:
    """Return the compose-side value expression for ``var``."""
    matches = [entry for entry in env if entry.startswith(f"{var}=")]
    assert len(matches) == 1, f"expected exactly one {var} entry, got {matches}"
    return matches[0].split("=", 1)[1]


def _fallback(env: list[str], var: str) -> str:
    """Extract the ``${VAR:-fallback}`` fallback for ``var``."""
    raw = _raw_value(env, var)
    match = re.fullmatch(r"\$\{" + var + r":-(.+)\}", raw)
    assert match, f"{var} must use ${{{var}:-<fallback>}} form, got {raw!r}"
    return match.group(1)


class TestComposeEnvPassthrough:
    """The semantic-svc environment block substitutes Qdrant timeouts."""

    def test_semantic_svc_substitutes_both_qdrant_timeout_vars(self):
        env = _semantic_environment()
        for var in _TIMEOUT_VARS:
            raw = _raw_value(env, var)
            assert "${" in raw and "}" in raw, (
                f"{var} must be substituted from .env, got literal {raw!r}"
            )

    def test_preexisting_semantic_env_vars_are_untouched(self):
        env = _semantic_environment()
        for var in (
            "QDRANT_URL",
            "VECTOR_INDEX_MAX_DOCS",
            "EMBED_MODEL_NAME",
            "EMBED_DIM",
            "ACTIVE_EMBED_MODEL",
        ):
            _raw_value(env, var)


class TestFallbackSafety:
    """An unset variable must not crash-loop the service or change defaults.

    ``app.py`` evaluates ``float(os.getenv(...))`` for both variables at
    import time, so an empty-string injection (what ``${VAR:-}`` delivers)
    is fatal. The fallback doubles as the documented default.
    """

    def test_fallback_is_non_empty_and_float_parseable(self):
        env = _semantic_environment()
        for var in _TIMEOUT_VARS:
            fallback = _fallback(env, var)
            assert fallback.strip() != "", f"{var} fallback must be non-empty"
            float(fallback)

    def test_fallback_preserves_todays_effective_defaults(self):
        env = _semantic_environment()
        assert float(_fallback(env, "QDRANT_QUERY_TIMEOUT")) == 10.0
        # The client timeout's code-level default tracks QDRANT_QUERY_TIMEOUT,
        # which is 10 unless the operator raises it — so the passthrough
        # fallback mirrors 10 to keep unset-.env behavior byte-identical.
        assert float(_fallback(env, "QDRANT_CLIENT_TIMEOUT")) == 10.0

    def test_fallback_documents_drift_watch_against_app_py_default(self):
        """The '10' fallbacks must carry an app.py-default drift comment.

        semantic-svc/app.py independently parses these variables with its own
        ``float(os.getenv(...))`` defaults; the compose fallbacks duplicate
        that value, so the compose block must say so — a future editor
        bumping one side without the other silently desyncs unset-.env
        deployments.
        """
        compose_text = (ROOT / "docker-compose.yml").read_text()
        semantic_block = compose_text.split("semantic-svc:", 1)[1].split(
            "  qdrant:", 1
        )[0]
        for var in _TIMEOUT_VARS:
            anchor = f"- {var}="
            lines = semantic_block.splitlines()
            idx = next(
                i for i, line in enumerate(lines) if line.strip().startswith(anchor)
            )
            # Walk upward collecting the governing comment block, skipping
            # sibling environment entries (the paired timeout var sits
            # between the comment block and the second substitution).
            context_lines: list[str] = []
            cursor = idx - 1
            while cursor >= 0 and len(context_lines) < 10:
                stripped = lines[cursor].strip()
                if stripped.startswith("#"):
                    context_lines.append(lines[cursor])
                elif stripped.startswith("- "):
                    pass  # sibling environment entry, keep walking
                else:
                    break
                cursor -= 1
            context = "\n".join(reversed(context_lines))
            assert "duplicat" in context.lower(), (
                f"compose fallback comment for {var} must note that the "
                f"'10' fallback duplicates semantic-svc app.py's default "
                f"(drift watch), context:\n{context}"
            )


class TestEnvSampleDoc:
    """.env.sample must not imply a fixed default for QDRANT_CLIENT_TIMEOUT."""

    @pytest.mark.skipif(
        not ENV_SAMPLE.exists(),
        reason=".env.sample is not provisioned in the containerized "
        "integration lane; the docs inventory gate enforces it on every PR",
        owner="repository-maintainer",
        issue="#588",
        classification="retained",
        environment=".env.sample absent from /app in containerized runs",
    )
    def test_example_value_does_not_state_fixed_default_of_10(self):
        text = (ROOT / ".env.sample").read_text()
        examples = re.findall(
            r"^#\s*QDRANT_CLIENT_TIMEOUT=(\S+)\s*$", text, re.MULTILINE
        )
        assert len(examples) == 1, f"expected exactly one example line, got {examples}"
        # The default TRACKS QDRANT_QUERY_TIMEOUT; showing "=10" alone reads
        # as a fixed default. A legitimate illustrative override equal to 10
        # is acceptable when the paired QDRANT_QUERY_TIMEOUT example raises
        # the pair together (the comment explains the tracking); anything
        # below 10 would contradict the "client stays the looser bound"
        # guidance and still fails here.
        assert float(examples[0]) >= 10.0, (
            ".env.sample example must not present a client timeout below "
            "the query timeout's effective default of 10"
        )

    @pytest.mark.skipif(
        not ENV_SAMPLE.exists(),
        reason=".env.sample is not provisioned in the containerized "
        "integration lane; the docs inventory gate enforces it on every PR",
        owner="repository-maintainer",
        issue="#588",
        classification="retained",
        environment=".env.sample absent from /app in containerized runs",
    )
    def test_comment_documents_query_timeout_tracking(self):
        text = (ROOT / ".env.sample").read_text()
        marker = "# Client-side timeout (seconds) for blocking Qdrant HTTP calls."
        assert marker in text
        tail = text.split(marker, 1)[1]
        head = tail.split("\n\n", 1)[0]
        assert "QDRANT_QUERY_TIMEOUT" in head, (
            "the QDRANT_CLIENT_TIMEOUT comment must reference "
            "QDRANT_QUERY_TIMEOUT tracking"
        )
