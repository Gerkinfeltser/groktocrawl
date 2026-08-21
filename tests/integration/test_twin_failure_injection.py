"""Failure taxonomy checks against the deployed Compose fixture services."""

from __future__ import annotations

import os

import httpx
import pytest
from agent.exceptions import ProviderOutputError, RetryableRateLimitError
from agent.llm import LLMClient
from agent.searxng_client import SearXNGClient

RUN_ID = os.environ.get("TWIN_RUN_ID", "compose-failure-injection")
SEARCH_URL = os.environ.get("SEARCH_BASE_URL", "http://slopsearx-fixture:8080")
LLM_URL = os.environ.get("LLM_BASE_URL", "http://llm-svc:8011/v1")


def _llm(scenario: str) -> LLMClient:
    base_url = LLM_URL.split("?", 1)[0].rstrip("/")
    return LLMClient(
        f"{base_url}/scenarios/{scenario}?run_id={RUN_ID}",
        model="fixture-model",
    )


@pytest.mark.asyncio
async def test_deployed_search_rate_limit_has_retry_metadata():
    client = SearXNGClient(SEARCH_URL)
    try:
        with pytest.raises(RetryableRateLimitError) as raised:
            await client.search(
                "failure", scenario="rate-limit-retry-after", raise_on_rate_limit=True
            )
        assert raised.value.retry_after_seconds == 2
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_deployed_search_malformed_response_degrades_without_crash():
    client = SearXNGClient(SEARCH_URL)
    try:
        results, health = await client.search("failure", scenario="malformed-json")
        assert results == []
        assert "failed" in health.detail.lower()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_deployed_search_timeout_is_classified():
    client = SearXNGClient(SEARCH_URL)
    await client._client.aclose()
    client._client = httpx.AsyncClient(timeout=0.01)
    try:
        results, health = await client.search("failure", scenario="delayed")
        assert results == []
        assert "timed out" in health.detail.lower()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_deployed_llm_failures_are_typed():
    for scenario, error in (
        ("rate-limit", RetryableRateLimitError),
        ("malformed-json", ProviderOutputError),
        ("refusal", ProviderOutputError),
        ("truncated", ProviderOutputError),
        ("server-error", ProviderOutputError),
    ):
        client = _llm(scenario)
        try:
            with pytest.raises(error):
                await client.generate("system", "failure")
        finally:
            await client.close()


@pytest.mark.asyncio
async def test_deployed_llm_timeout_is_typed_transport_error():
    client = _llm("timeout")
    client._client.timeout = httpx.Timeout(0.05)
    try:
        with pytest.raises(ProviderOutputError, match="transport failed"):
            await client.generate("system", "failure")
    finally:
        await client.close()
