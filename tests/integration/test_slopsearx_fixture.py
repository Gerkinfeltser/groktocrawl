"""Docker-boundary tests for the deployed SlopSearX contract fixture."""

from __future__ import annotations

import os

import httpx

FIXTURE = os.getenv("SEARCH_FIXTURE_BASE_URL", "http://slopsearx-fixture:8080")


def test_deployed_quota_partition_isolation():
    """Quota state is shared within one partition and isolated across queries."""
    first = httpx.get(
        FIXTURE + "/search",
        params={"scenario": "quota-exhaustion", "q": "integration-partition-a"},
        timeout=10,
    )
    exhausted = httpx.get(
        FIXTURE + "/search",
        params={"scenario": "quota-exhaustion", "q": "integration-partition-a"},
        timeout=10,
    )
    isolated = httpx.get(
        FIXTURE + "/search",
        params={"scenario": "quota-exhaustion", "q": "integration-partition-b"},
        timeout=10,
    )

    assert first.status_code == 200
    assert first.json()["results"]
    assert exhausted.status_code == 429
    assert exhausted.headers["Retry-After"] == "2"
    assert isolated.status_code == 200
    assert isolated.json()["results"]

    ledger = httpx.get(FIXTURE + "/ledger", timeout=10).json()
    assert ledger["schema_version"] == "v1"
    assert "integration-partition" not in str(ledger)
