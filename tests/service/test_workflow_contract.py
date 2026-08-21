"""Contract checks for sanitized LLM fixture CI evidence."""

from pathlib import Path


def test_docker_workflow_captures_and_uploads_sanitized_fixture_diagnostics():
    workflow = (Path(__file__).parents[2] / ".github/workflows/docker.yml").read_text()
    assert "Capture sanitized LLM fixture diagnostics" in workflow
    assert "llm-fixture-diagnostics.json" in workflow
    assert "Upload LLM fixture diagnostics" in workflow
    assert '"prompt"' not in workflow
    assert '"context"' not in workflow
