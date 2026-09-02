"""Contract tests for the Droid Auto Review fork gate hygiene (#562, round 2).

PR #605 hardened docker.yml's self-hosted-lane admission onto the string-
rendered ``format('{0}', ... fork) == 'false'`` because GHA loose equality
coerces Null->0 and Boolean false->0 (actions/runner
``src/Sdk/Expressions/EvaluationResult.cs``): a raw ``fork == false`` evaluates
TRUE for deleted forks (``head.repo.fork == null``). ``droid-review.yml``
retained that pre-existing raw comparison — low impact (review-only job on the
hosted lane, no self-hosted exposure) but after #605 it was the LAST raw fork
comparison under ``.github/workflows/``.

These tests pin (1) the string-rendered form on the review job's ``if``, (2)
the ACTUAL condition's semantics over the simulated GHA loose-equality subset
(``tests.service._gha_expr_sim``) for fork in {proven, deleted, same-repo}, and
(3) a directory-wide sweep asserting the raw-comparison class cannot quietly
return in any workflow.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from tests.outcome_governance import governed_skip
from tests.service._gha_expr_sim import GhaScalar, gha_eval

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
DROID_REVIEW = WORKFLOW_DIR / "droid-review.yml"

if not DROID_REVIEW.exists():
    governed_skip(
        ".github/workflows/droid-review.yml not present in this checkout",
        owner="repository-maintainer",
        issue="#562",
        classification="retained",
        environment=(
            "agent-svc integration container provisions only docker.yml/fast-tests.yml"
        ),
        allow_module_level=True,
    )


def _workflow_text() -> str:
    return DROID_REVIEW.read_text()


def _review_condition() -> str:
    parsed = yaml.safe_load(_workflow_text())
    condition = parsed["jobs"]["droid-review"]["if"]
    assert isinstance(condition, str)
    return " ".join(condition.split())


class TestDroidReviewGateText:
    """Pin the string-rendered fork gate on the review job."""

    def test_workflow_parses_as_valid_yaml(self) -> None:
        parsed = yaml.safe_load(_workflow_text())
        assert isinstance(parsed, dict)
        assert "jobs" in parsed

    def test_review_job_uses_string_rendered_fork_gate(self) -> None:
        condition = _review_condition()
        # The PR #605 hardened form: admission requires the STRING rendering to
        # equal 'false' (renders 'true'/'false'/'' for null), so deleted forks
        # fail closed OFF automated AI review.
        assert (
            "format('{0}', github.event.pull_request.head.repo.fork) == 'false'"
            in condition
        )
        # The raw loose comparison must be gone: under Null->0/false->0
        # coercion it admitted null forks (deleted forks) onto the lane.
        assert "github.event.pull_request.head.repo.fork == false" not in condition

    def test_raw_quoted_fork_comparison_is_gone_repo_wide(self) -> None:
        """No workflow may loosely compare head.repo.fork against a quoted literal.

        Sweep every workflow file: strip the sanctioned format()-rendered
        occurrences, then assert neither a quoted-literal loose comparison nor
        the raw ``fork == false`` keyword form remains anywhere. Keyword
        ``== true`` / ``== null`` stay legal — the documented detector
        disjunction (``fork == true || fork == null``) arms for every
        pull_request event by design and the seam discriminates on the
        rendered value; ``== false`` has NO sanctioned use because loose
        equality admits null forks onto whatever the condition gates.
        """
        quoted_pattern = re.compile(
            r"github\.event\.pull_request\.head\.repo\.fork\s*[=!]=\s*'"
        )
        offenders: list[str] = []
        for workflow in sorted(WORKFLOW_DIR.glob("*.y*ml")):
            normalized = " ".join(workflow.read_text().split())
            sanitized = normalized.replace(
                "format('{0}', github.event.pull_request.head.repo.fork)", ""
            )
            if quoted_pattern.search(sanitized) or (
                "github.event.pull_request.head.repo.fork == false" in sanitized
            ):
                offenders.append(workflow.name)
        assert offenders == []


class TestDroidReviewGateSemantics:
    """Evaluate the ACTUAL review-job condition over GHA loose equality."""

    @staticmethod
    def _runs_for(
        *,
        fork: object,
        draft: bool = False,
        actor: str = "maintainer",
        event_name: str = "pull_request",
    ) -> bool:
        ctx: dict[str, object] = {
            "github": {
                "event_name": event_name,
                "actor": actor,
                "event": {
                    "pull_request": {
                        "draft": GhaScalar(draft),
                        "head": {"repo": {"fork": GhaScalar(fork)}},
                    }
                },
            },
        }
        return bool(gha_eval(_review_condition(), ctx))

    def test_same_repo_pr_is_reviewed(self) -> None:
        # Proven same-repository PR renders 'false' -> admitted to review.
        assert self._runs_for(fork=False)

    def test_deleted_fork_pr_null_is_not_reviewed(self) -> None:
        # head.repo deref on a deleted fork renders null -> '' != 'false'
        # -> fail closed. The raw `fork == false` gate admitted this case.
        assert not self._runs_for(fork=None)

    def test_proven_fork_pr_is_not_reviewed(self) -> None:
        assert not self._runs_for(fork=True)

    def test_dependabot_actor_is_not_reviewed(self) -> None:
        assert not self._runs_for(fork=False, actor="app/dependabot")

    def test_draft_pr_is_not_reviewed(self) -> None:
        assert not self._runs_for(fork=False, draft=True)

    def test_manual_dispatch_still_runs_the_review(self) -> None:
        # workflow_dispatch is a declared trigger of droid-review.yml; on
        # dispatch events the whole pull_request context is null, so the OLD
        # loose comparisons made the job run there. The explicit dispatch
        # branch preserves that behavior instead of silently dropping it.
        assert self._runs_for(fork=None, event_name="workflow_dispatch")
