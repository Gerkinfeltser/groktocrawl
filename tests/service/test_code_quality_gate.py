"""Contract tests for the Code Quality Gate aggregate job.

The gate job in `.github/workflows/code-quality.yml` mirrors the proven
Runtime Gate pattern from `docker.yml`: an always-run aggregate over the
three Code Quality source jobs that concludes `failure` (never `skipped`
or `neutral`) when any dependency does not succeed. Branch rules require
the stable `Code Quality Gate` check context, so its structure is pinned
by these regression tests (same idea as `test_ci_change_classification.py`).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "code-quality.yml"

GATE_NAME = "Code Quality Gate"
SOURCE_JOBS = {"python-checks", "duplicate-code", "secret-scan"}


class CodeQualityGateContractTests(unittest.TestCase):
    """Structural contract for the Code Quality Gate aggregate job."""

    @classmethod
    def setUpClass(cls) -> None:
        if not WORKFLOW.exists():
            raise unittest.SkipTest(
                "code-quality.yml is not present in this environment "
                "(the Docker integration container only receives "
                "docker.yml and fast-tests.yml)"
            )
        cls.workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        # PyYAML parses the `on:` key as the YAML 1.1 boolean True.
        cls.triggers = cls.workflow.get("on") or cls.workflow.get(True)
        cls.jobs = cls.workflow["jobs"]

    @classmethod
    def gate_jobs(cls) -> list[tuple[str, dict]]:
        return [
            (job_id, job)
            for job_id, job in cls.jobs.items()
            if job.get("name") == GATE_NAME
        ]

    def test_gate_job_exists_exactly_once_and_is_not_a_matrix(self) -> None:
        gates = self.gate_jobs()
        self.assertEqual(len(gates), 1)
        job_id, job = gates[0]
        self.assertNotIn("strategy", job)
        self.assertNotIn("matrix", job)
        # The gate is an aggregate over the three source jobs, not a source itself.
        self.assertNotIn(job_id, SOURCE_JOBS)

    def test_gate_depends_on_exactly_the_three_source_jobs(self) -> None:
        _, job = self.gate_jobs()[0]
        self.assertEqual(set(job["needs"]), SOURCE_JOBS)
        # Every needed job id exists as a job in the same workflow file.
        for source in SOURCE_JOBS:
            self.assertIn(source, self.jobs)

    def test_gate_runs_unconditionally(self) -> None:
        _, job = self.gate_jobs()[0]
        self.assertEqual(job["if"], "always()")

    def test_no_continue_on_error_in_gate_job(self) -> None:
        _, job = self.gate_jobs()[0]
        for step in job.get("steps", []):
            self.assertNotIn("continue-on-error", step)

    def test_every_exit_1_step_is_conditioned_on_a_non_success_dependency(
        self,
    ) -> None:
        _, job = self.gate_jobs()[0]
        exit_steps = [
            step
            for step in job.get("steps", [])
            if "exit 1" in str(step.get("run", ""))
        ]
        self.assertGreaterEqual(len(exit_steps), len(SOURCE_JOBS))
        conditions = " ".join(step.get("if", "") for step in exit_steps)
        for step in exit_steps:
            condition = step.get("if", "")
            self.assertIn("needs.", condition)
            self.assertIn("result != 'success'", condition)
        # Each source job has at least one dedicated failure step.
        for source in SOURCE_JOBS:
            self.assertIn(f"needs.{source}.result != 'success'", conditions)

    def test_no_unconditional_failure_step_exists(self) -> None:
        _, job = self.gate_jobs()[0]
        for step in job.get("steps", []):
            run = str(step.get("run", ""))
            if "exit 1" in run:
                self.assertIn(
                    "needs.", step.get("if", ""), f"unconditional exit step: {step}"
                )
                self.assertIn("result != 'success'", step.get("if", ""))

    def test_each_failure_step_references_exactly_one_dependency(self) -> None:
        _, job = self.gate_jobs()[0]
        for step in job.get("steps", []):
            if "exit 1" not in str(step.get("run", "")):
                continue
            condition = step.get("if", "")
            referenced = set(re.findall(r"needs\.(\S+?)\.result", condition))
            self.assertEqual(len(referenced), 1, condition)
            self.assertIn(next(iter(referenced)), SOURCE_JOBS)

    def test_workflow_triggers_unchanged(self) -> None:
        self.assertEqual(self.triggers["push"]["branches"], ["main"])
        self.assertEqual(self.triggers["pull_request"]["branches"], ["main"])

    def test_source_jobs_still_present(self) -> None:
        for source in SOURCE_JOBS:
            self.assertIn(source, self.jobs)
            self.assertNotIn("strategy", self.jobs[source])


if __name__ == "__main__":
    unittest.main()
