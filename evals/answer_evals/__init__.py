"""Grounded answer & research evaluation harness (issue #570).

Versioned, deterministic, fixture-driven evaluation for the ``/v2/answer`` and
research paths: citation grounding, abstention/degradation, and scenario-use
assertions against the deterministic search and LLM twins. See ``evals/README.md``
for mechanically-graded vs unverified boundaries and baseline policy.
"""

from . import grading, harness, provenance, routing
from .harness import (
    run_case,
    run_selection,
    validate_corpus,
)
from .provenance import build_provenance, sanitize, write_provenance
from .routing import (
    EndpointAllowlistError,
    validate_endpoint_allowlist,
)

__all__ = [
    "EndpointAllowlistError",
    "build_provenance",
    "grading",
    "harness",
    "provenance",
    "routing",
    "run_case",
    "run_selection",
    "sanitize",
    "validate_corpus",
    "validate_endpoint_allowlist",
    "write_provenance",
]
