"""Opt-in distributed pacing must fail closed without shared coordination."""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from scraper.politeness import PolitenessManager, _DomainState


def manager():
    value = PolitenessManager()
    value._enabled = True
    value._distributed = True
    value._domains["example.org"] = _DomainState(
        robots_cached_at=time.time(), crawl_delay=0.5
    )
    return value


@pytest.mark.asyncio
async def test_replicas_use_same_atomic_origin_key(monkeypatch):
    client = SimpleNamespace(eval=AsyncMock(side_effect=[0, 500, 1000]))
    monkeypatch.setattr(
        "scraper.cache._get_cache_client", AsyncMock(return_value=client)
    )
    replicas = [manager() for _ in range(3)]
    results = await asyncio.gather(
        *(r.check("https://example.org/a") for r in replicas)
    )
    assert [r.delay_seconds for r in results] == [0, 0.5, 1]
    calls = client.eval.call_args_list
    assert len({call.args[2] for call in calls}) == 1
    assert all(call.args[1] == 1 and call.args[3:] == (500, 30000) for call in calls)


@pytest.mark.asyncio
async def test_readonly_tier_does_not_reserve_again(monkeypatch):
    client = SimpleNamespace(eval=AsyncMock(return_value=0))
    monkeypatch.setattr(
        "scraper.cache._get_cache_client", AsyncMock(return_value=client)
    )
    result = await manager().check("https://example.org/a", rate_limit=False)
    assert result.action == "proceed"
    client.eval.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [None, -1, ConnectionError("offline")])
async def test_missing_capacity_or_coordination_blocks(monkeypatch, response):
    client = None if response is None else SimpleNamespace(eval=AsyncMock())
    if client:
        if isinstance(response, Exception):
            client.eval.side_effect = response
        else:
            client.eval.return_value = response
    monkeypatch.setattr(
        "scraper.cache._get_cache_client", AsyncMock(return_value=client)
    )
    assert (await manager().check("https://example.org/a")).action == "blocked"


@pytest.mark.asyncio
async def test_cancellation_propagates(monkeypatch):
    client = SimpleNamespace(eval=AsyncMock(side_effect=asyncio.CancelledError()))
    monkeypatch.setattr(
        "scraper.cache._get_cache_client", AsyncMock(return_value=client)
    )
    with pytest.raises(asyncio.CancelledError):
        await manager().check("https://example.org/a")
