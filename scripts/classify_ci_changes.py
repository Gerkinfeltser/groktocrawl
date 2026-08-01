#!/usr/bin/env python3
"""Classify changed paths for CI runtime validation.

Pass paths as positional arguments, or provide one path per line on stdin when
no arguments are supplied. The command prints ``true`` when full runtime
validation is required and ``false`` only for a non-empty docs-only change.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable

DOCS_ONLY_FILES = frozenset({"README.md", "AGENTS.md", "CONTRIBUTING.md"})
DOCS_ONLY_PREFIXES = ("docs/", ".github/ISSUE_TEMPLATE/")


def requires_full_runtime(paths: Iterable[str]) -> bool:
    """Return whether changed paths require the Docker integration runtime."""
    path_list = list(paths)
    if not path_list:
        return True

    return any(
        path not in DOCS_ONLY_FILES and not path.startswith(DOCS_ONLY_PREFIXES)
        for path in path_list
    )


def main(argv: list[str]) -> int:
    paths = argv or sys.stdin.read().splitlines()
    print(str(requires_full_runtime(paths)).lower())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
