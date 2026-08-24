"""Contract tests for the fork-PR workflow-edit guard (#562).

Issue #562: a fork pull request that edits ``.github/workflows/**`` runs from
the PR merge ref, so it can strip any in-repo guard and reach the self-hosted
runner lane. The guard is defense in depth only (ADR-0056): the authoritative,
non-bypassable control is platform-level (org runner group denying public
repositories / org approval for outside-contributor workflow runs), which is
deliberately DEFERRED maintainer-side and documented as residual risk.

The decision logic lives in an executable seam (``scripts/ci_fork_pr_guard.py``)
that reads synthetic inputs from environment variables so the three VAL-FORK-001
scenarios are runnable locally AND on CI:

1. fork PR + workflow path changed  -> exit 1 (fail-fast detection fires);
2. same-repo PR + workflow path     -> exit 0;
3. fork PR + non-workflow path      -> exit 0.

A null/unknown fork flag is treated as NOT a same-repository PR (fail-closed
for detection purposes). The tests also pin the workflow wiring: the guard
step must live inside the ``changes`` classification job whose ``if`` cannot
skip classification, and every changed path must flow into the guard.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SEAM = ROOT / "scripts" / "ci_fork_pr_guard.py"
WORKFLOW = ROOT / ".github" / "workflows" / "docker.yml"

SPEC = (
    importlib.util.spec_from_file_location("ci_fork_pr_guard", SEAM)
    if SEAM.exists()
    else None
)
if SPEC and SPEC.loader:
    MODULE = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(MODULE)
else:
    MODULE = None

WORKFLOW_ABSENT_REASON = ".github/workflows/docker.yml absent from this checkout"


def run_seam(
    event_name: str,
    fork_flag: str,
    paths: str,
    env: dict[str, str] | None = None,
) -> int:
    """Run the seam's evaluate() exactly as the workflow step would."""
    if MODULE is None:
        raise RuntimeError("scripts/ci_fork_pr_guard.py not present")
    merged_env = dict(os.environ)
    merged_env.pop("CI_EVENT_NAME", None)
    merged_env.pop("CI_PR_FORK", None)
    merged_env.pop("CI_CHANGED_PATHS", None)
    if env:
        merged_env.update(env)
    return MODULE.evaluate(
        event_name=event_name,
        fork_raw=fork_flag,
        paths_text=paths,
        env=merged_env,
    )


class SeamScenarioTests(unittest.TestCase):
    """The three VAL-FORK-001 scenarios plus the null-fork guard."""

    def setUp(self) -> None:
        if MODULE is None:
            self.skipTest(
                "scripts/ci_fork_pr_guard.py not present in this environment",
            )

    def test_scenario_1_fork_pr_touching_workflows_exits_nonzero(self) -> None:
        # Fork PR that edits .github/workflows/docker.yml -> fail-fast (exit 1).
        self.assertEqual(
            run_seam("pull_request", "true", ".github/workflows/docker.yml"),
            1,
        )

    def test_scenario_2_same_repo_pr_touching_workflows_exits_zero(self) -> None:
        # Same-repo PR editing workflows is trusted; guard must not fire.
        self.assertEqual(
            run_seam("pull_request", "false", ".github/workflows/docker.yml"),
            0,
        )

    def test_scenario_3_fork_pr_without_workflow_changes_exits_zero(self) -> None:
        # Fork PR touching no workflow file does not trip the guard.
        self.assertEqual(
            run_seam(
                "pull_request",
                "true",
                "agent-svc/agent/api.py\nREADME.md\ntests/service/test_cli.py",
            ),
            0,
        )

    def test_null_fork_flag_is_fail_closed_not_same_repo(self) -> None:
        # head.repo.fork can be null (deleted forks). Null is not proof of a
        # same-repo PR, so the guard stays armed: a workflow edit still exits 1.
        self.assertEqual(
            run_seam("pull_request", "", ".github/workflows/new-workflow.yml"),
            1,
        )
        self.assertEqual(
            run_seam("pull_request", "", ".github/workflows/docker.yml"),
            1,
        )

    def test_null_fork_flag_without_workflow_changes_is_clean(self) -> None:
        # Null fork flag alone never fails a run; only the workflow-path
        # combination trips the guard.
        self.assertEqual(run_seam("pull_request", "", "agent-svc/agent/app.py"), 0)

    def test_non_pull_request_events_never_trip_the_guard(self) -> None:
        # push/tag events are same-repo by definition (workflow edits land via
        # reviewed merges); the guard must stay silent there.
        self.assertEqual(run_seam("push", "true", ".github/workflows/docker.yml"), 0)
        self.assertEqual(run_seam("schedule", "", ".github/workflows/docker.yml"), 0)

    def test_nested_workflow_paths_and_mixed_sets_are_detected(self) -> None:
        # Any path under .github/workflows/** counts, including nested dirs,
        # even when buried in a larger change set.
        mixed = "\n".join(
            [
                "docs/runbooks/x.md",
                "scraper-svc/scraper/fetch.py",
                ".github/workflows/sub/dir/job.yml",
            ]
        )
        self.assertEqual(run_seam("pull_request", "true", mixed), 1)

    def test_lookalike_paths_outside_workflows_do_not_match(self) -> None:
        # Prefix look-alikes must not false-positive: only real
        # .github/workflows/** paths count.
        self.assertEqual(
            run_seam("pull_request", "true", ".github/workflows-old/x.yml"), 0
        )
        self.assertEqual(
            run_seam("pull_request", "true", "src/.github/workflows/x.yml"), 0
        )
        self.assertEqual(
            run_seam("pull_request", "true", ".github/workflowsREADME.md"), 0
        )


class WorkflowWiringTests(unittest.TestCase):
    """Pin the docker.yml wiring: step inside the unskippable classifier job."""

    def _workflow_bytes(self) -> str:
        return WORKFLOW.read_text()

    def setUp(self) -> None:
        if not WORKFLOW.exists():
            self.skipTest(WORKFLOW_ABSENT_REASON)

    def test_workflow_parses_as_valid_yaml(self) -> None:
        parsed = yaml.safe_load(self._workflow_bytes())
        self.assertIsInstance(parsed, dict)
        self.assertIn("jobs", parsed)

    def test_guard_step_lives_in_changes_classification_job(self) -> None:
        changes_block = (
            self._workflow_bytes()
            .split("\n  changes:\n", 1)[1]
            .split("\n  twin-contracts:", 1)[0]
        )
        self.assertIn(
            "- name: Detect fork PR modifying GitHub workflows", changes_block
        )
        self.assertIn("scripts/ci_fork_pr_guard.py", changes_block)

    def test_changes_job_if_cannot_skip_classification(self) -> None:
        parsed = yaml.safe_load(self._workflow_bytes())
        changes_job = parsed["jobs"]["changes"]
        assert isinstance(changes_job, dict)
        job_if = changes_job.get("if")
        # No job-level 'if' at all means the job always runs (cannot be
        # skipped by its own condition).
        self.assertIsNone(job_if)

    def test_guard_step_runs_even_after_prior_step_failure(self) -> None:
        changes_block = (
            self._workflow_bytes()
            .split("\n  changes:\n", 1)[1]
            .split("\n  twin-contracts:", 1)[0]
        )
        # always() keeps the guard evaluated even if classification steps fail.
        self.assertIn("if: always()", changes_block)

    def test_guard_receives_all_changed_paths_as_input(self) -> None:
        changes_block = (
            self._workflow_bytes()
            .split("\n  changes:\n", 1)[1]
            .split("\n  twin-contracts:", 1)[0]
        )
        # The guard computes its own full merge-base..head path list and pipes
        # every changed path into the seam script (no classified subset).
        self.assertIn(
            "CI_BASE_SHA: ${{ github.event.pull_request.base.sha }}", changes_block
        )
        self.assertIn(
            "CI_HEAD_SHA: ${{ github.event.pull_request.head.sha }}", changes_block
        )
        self.assertIn(
            'git diff --name-only "$merge_base" "$CI_HEAD_SHA" | python3 scripts/ci_fork_pr_guard.py',
            changes_block,
        )

    def test_guard_step_fails_the_step_on_detection(self) -> None:
        # The seam runs as the step's last pipeline element, so its non-zero
        # exit fails the step (and therefore the job) directly.
        changes_block = (
            self._workflow_bytes()
            .split("\n  changes:\n", 1)[1]
            .split("\n  twin-contracts:", 1)[0]
        )
        self.assertIn(
            "| python3 scripts/ci_fork_pr_guard.py",
            changes_block,
        )

    def test_guard_condition_pins_event_and_fork_expression(self) -> None:
        changes_block = (
            self._workflow_bytes()
            .split("\n  changes:\n", 1)[1]
            .split("\n  twin-contracts:", 1)[0]
        )
        self.assertIn("github.event_name == 'pull_request'", changes_block)
        self.assertIn("github.event.pull_request.head.repo.fork == true", changes_block)


class GuardMessagingTests(unittest.TestCase):
    """VAL-FORK-002: message names the platform control as authoritative."""

    def setUp(self) -> None:
        if MODULE is None:
            self.skipTest(
                "scripts/ci_fork_pr_guard.py not present in this environment",
            )

    def test_detection_message_names_authoritative_platform_control(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            MODULE.emit_detection_message(".github/workflows/docker.yml")
        text = stderr.getvalue().lower()
        self.assertIn("platform-level", text)
        self.assertIn("authoritative", text)

    def test_detection_message_states_merge_ref_residual_risk(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            MODULE.emit_detection_message(".github/workflows/docker.yml")
        text = stderr.getvalue().lower()
        self.assertIn("merge ref", text)
        self.assertIn("defense in depth", text)

    def test_evaluate_returns_nonzero_when_message_emitted(self) -> None:
        # The exit decision belongs to evaluate(): a tripped guard returns 1.
        self.assertEqual(
            run_seam("pull_request", "true", ".github/workflows/docker.yml"), 1
        )

    def test_seam_source_carries_org_remediation_pointers(self) -> None:
        source = SEAM.read_text()
        lowered = source.lower()
        self.assertIn("allows_public_repositories=false", lowered)
        self.assertIn("restricted_to_workflows", lowered)
        self.assertIn("external contributors", lowered)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
