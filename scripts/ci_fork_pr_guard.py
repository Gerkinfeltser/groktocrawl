#!/usr/bin/env python3
"""Fail-fast guard for fork pull requests that edit GitHub workflow files (#562).

GitHub runs ``pull_request`` workflows from the PR merge ref, so a fork PR can
modify this very workflow file and strip any in-repo guard before its code
reaches the self-hosted runner lane. This script is a DETECTOR, not a security
boundary: it fails loudly (exit 1) when a fork PR touches anything under
``.github/workflows/**`` so the required checks go red and leave a paper
trail. Defense in depth only — per ADR-0056 ("Required Protected
Configuration") the authoritative, non-bypassable control is PLATFORM-LEVEL:
the org runner group used by ``runs-on: [self-hosted, groktopus, docker]``
must deny public repositories, and org Actions settings must require approval
for outside-contributor workflow runs.

Those platform-level controls are currently DEFERRED maintainer-side
(residual risk accepted). The exact remediation steps are documented in
``docs/runbooks/self-hosted-runner-fork-protection.md``:

1. Org runner group ``[self-hosted, groktopus, docker]``:
   ``allows_public_repositories=false`` (deny public/fork repositories).
2. Optionally restrict the group to selected workflows
   (``restricted_to_workflows`` plus an explicit workflow allowlist).
3. Org Settings > Actions: "Require approval for all external contributors"
   so first-time outside collaborators cannot launch workflow runs unreviewed.

Inputs (environment or CLI flags, synthetic-friendly for local simulation):
  --event-name / CI_EVENT_NAME     : github.event_name (e.g. pull_request)
  --fork        / CI_PR_FORK       : "true"/"false" from
                   github.event.pull_request.head.repo.fork; empty/unset when
                   the expression evaluated to null (deleted forks)
  paths         / CI_CHANGED_PATHS : changed paths, one per line

Decision table (exit codes):
  event != pull_request                          -> 0 (same-repo by definition)
  fork flag false (same-repository PR)           -> 0
  workflow path changed AND fork not false       -> 1 (detection fires;
                 includes null fork flags — null is NOT proof of same-repo)
  no workflow path changed                       -> 0
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence

WORKFLOW_PREFIX = ".github/workflows/"
FORK_FALSE = "false"

DETECTION_MESSAGE = """
=====================================================================
 FAILING BY DESIGN - fork-PR workflow-edit detection (#562)
=====================================================================

A PULL REQUEST FROM A FORK modified files under .github/workflows/**.
Because GitHub runs pull_request workflows from the PR MERGE REF, such a
change executes with this very workflow file already rewritten by the
fork; any in-repo guard could have been stripped before evaluation. This
step therefore treats every fork-PR workflow edit as suspicious and fails
fast on purpose: the red X on the required checks is the intended paper
trail.

THIS GUARD IS DEFENSE IN DEPTH ONLY - IT IS NOT A SECURITY BOUNDARY.
The authoritative control is PLATFORM-LEVEL and lives OUTSIDE this repo
(ADR-0056 "Required Protected Configuration"):

  1. Org runner group [self-hosted, groktopus, docker] must deny public
     repositories (allows_public_repositories=false).
  2. Optionally restrict that group to selected workflows
     (restricted_to_workflows + explicit allowlist).
  3. Org Settings > Actions: Require approval for all EXTERNAL
     CONTRIBUTORS before their workflow runs execute.

These org-level controls are currently DEFERRED by maintainer decision -
residual risk accepted. Full remediation steps:
docs/runbooks/self-hosted-runner-fork-protection.md

Detected workflow-path change(s) in this fork PR:
  {paths}
=====================================================================
""".strip()


def _is_workflow_path(path: str) -> bool:
    """True for any path under .github/workflows/ (exact prefix semantics).

    Deliberately strict: look-alikes like `.github/workflows-old/x.yml` or
    nested copies (`src/.github/workflows/x.yml`) do not match.
    """
    return path.startswith(WORKFLOW_PREFIX)


def emit_detection_message(paths: Sequence[str]) -> None:
    """Print the loud fail-fast explanation to stderr and exit non-zero."""
    listed = "\n  ".join(paths) if paths else "(none)"
    print(DETECTION_MESSAGE.format(paths=listed), file=sys.stderr)


def evaluate(
    *,
    event_name: str,
    fork_raw: str | None,
    paths_text: str,
    env: dict[str, str] | None = None,
) -> int:
    """Return the process exit code for the given synthetic inputs.

    ``fork_raw`` mirrors ``github.event.pull_request.head.repo.fork`` after
    GitHub expression evaluation: the literal string "true"/"false", or an
    empty string when the expression rendered as null (deleted forks).
    Null is treated as NOT-a-same-repo-PR (fail-closed for detection).
    """
    source = env if env is not None else os.environ
    event = (event_name or source.get("CI_EVENT_NAME", "")).strip()
    fork = (fork_raw if fork_raw is not None else source.get("CI_PR_FORK", "")).strip()
    raw_paths = paths_text or source.get("CI_CHANGED_PATHS", "")

    # Non-pull_request events (push, tag, schedule...) run from reviewed
    # commits on this repository; the guard never applies there.
    if event != "pull_request":
        return 0

    # Same-repository PRs are trusted (fork == false exactly).
    if fork.lower() == FORK_FALSE:
        return 0

    workflow_paths = [
        line.strip()
        for line in raw_paths.splitlines()
        if line.strip() and _is_workflow_path(line.strip())
    ]
    if not workflow_paths:
        # Fork PR without workflow edits: nothing suspicious detected.
        return 0

    emit_detection_message(workflow_paths)
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ci_fork_pr_guard",
        description=(
            "Fail-fast detector for fork pull requests editing "
            ".github/workflows/** (defense in depth, see ADR-0056)."
        ),
    )
    parser.add_argument(
        "--event-name",
        default=None,
        help="github.event_name (defaults to $CI_EVENT_NAME)",
    )
    parser.add_argument(
        "--fork",
        default=None,
        help=(
            "github.event.pull_request.head.repo.fork as 'true'/'false' "
            "(empty/null for deleted forks; defaults to $CI_PR_FORK)"
        ),
    )
    parser.add_argument(
        "--paths-file",
        default=None,
        help="read changed paths from this file instead of stdin",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths_text = sys.stdin.read()
    if args.paths_file:
        with open(args.paths_file, encoding="utf-8") as handle:
            paths_text = handle.read()
    return evaluate(
        event_name=args.event_name or "", fork_raw=args.fork, paths_text=paths_text
    )


if __name__ == "__main__":
    raise SystemExit(main())
