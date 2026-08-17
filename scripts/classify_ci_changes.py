#!/usr/bin/env python3
"""Classify changed paths for CI runtime validation.

Pass paths as positional arguments, or provide one path per line on stdin when
no arguments are supplied.

Modes:
- default: prints ``true`` when full runtime validation is required and
  ``false`` only for a non-empty docs-only change.
- ``--affected-services``: prints the space-separated list of runtime service
  images that must be rebuilt for a pull request, or ``all`` when the change is
  cross-cutting/unrecognized and the full stack must be rebuilt.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable

DOCS_ONLY_FILES = frozenset({"README.md", "AGENTS.md", "CONTRIBUTING.md"})
DOCS_ONLY_PREFIXES = ("docs/", ".github/ISSUE_TEMPLATE/")

# Runtime service images in the build matrix / compose stack. Fixture services
# (llm-svc, test-site, tier3-fixture) are built by their own dedicated step.
RUNTIME_SERVICES = (
    "agent-svc",
    "scraper-svc",
    "browser-svc",
    "semantic-svc",
    "portal-svc",
    "parse-svc",
    "mcp-svc",
)

# Paths whose change affects every service image.
_CROSS_CUTTING_PATHS = ("docker-compose.yml",)
_COMMON_PREFIX = "common/"


def requires_full_runtime(paths: Iterable[str]) -> bool:
    """Return whether changed paths require the Docker integration runtime."""
    path_list = list(paths)
    if not path_list:
        return True

    return any(
        path not in DOCS_ONLY_FILES and not path.startswith(DOCS_ONLY_PREFIXES)
        for path in path_list
    )


def affected_services(paths: Iterable[str]) -> frozenset[str]:
    """Return the runtime services whose images must be rebuilt for a PR.

    Returns ``frozenset({"all"})`` when the change is cross-cutting, maps to no
    single service, or the path set is empty/malformed (conservative
    escalation). Returns an empty set for a pure docs-only change.
    """
    path_list = list(paths)
    if not path_list:
        return frozenset({"all"})

    affected: set[str] = set()
    for path in path_list:
        if not path.strip():
            return frozenset({"all"})
        if path in _CROSS_CUTTING_PATHS or path.startswith(_COMMON_PREFIX):
            return frozenset({"all"})
        matched = next(
            (svc for svc in RUNTIME_SERVICES if path.startswith(f"{svc}/")), None
        )
        if matched is not None:
            affected.add(matched)
            continue
        # Path is not under a known service dir. If it is runtime-relevant at
        # all (i.e. not docs-only), escalate to a full rebuild.
        if path not in DOCS_ONLY_FILES and not path.startswith(DOCS_ONLY_PREFIXES):
            return frozenset({"all"})

    return frozenset(affected)


def main(argv: list[str]) -> int:
    if "--affected-services" in argv:
        args = [a for a in argv if a != "--affected-services"]
        paths = args or sys.stdin.read().splitlines()
        print(" ".join(sorted(affected_services(paths))))
        return 0

    paths = argv or sys.stdin.read().splitlines()
    print(str(requires_full_runtime(paths)).lower())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
