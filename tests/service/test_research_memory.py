"""Unit tests for research-memory compatibility, freshness, SWR, and sweep.

Covers issue #529: the replay compatibility fingerprint, fail-closed
freshness from stored timestamps, ``max_age_hours`` gating, accurate
age/expiry/compatibility metadata, automatic dual-store sweep, and the
opt-in stale-while-revalidate path with single-flight refresh.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.research_memory import (
    ResearchMemory,
    compute_fingerprint,
    run_research_memory_sweep_loop,
)


# ── Helpers ──────────────────────────────────────────────────────


def _dict_redis(store: dict[str, str]) -> MagicMock:
    """Dict-backed mock Redis/Valkey client for get/set/exists/delete."""
    mock = MagicMock()
    mock.get.side_effect = lambda key: store.get(key)
    mock.exists.side_effect = lambda key: key in store
    mock.set.side_effect = lambda key, value, ex=None: store.__setitem__(key, value)
    mock.sadd.side_effect = lambda key, *members: 1
    mock.srem.side_effect = lambda key, *members: 1
    mock.delete.side_effect = lambda key: 1 if store.pop(key, None) is not None else 0
    return mock


def _stored_entry(
    memory_id: str,
    *,
    fingerprint: str | None = None,
    age_hours: float | None = 1.0,
    ttl_hours: float = 168.0,
    text: str = "cached answer",
    sources: list[dict] | None = None,
) -> dict:
    """Build a stored research-memory entry with controllable timestamps."""
    now = datetime.now(UTC)
    created_at = now - timedelta(hours=age_hours or 1.0)
    expires_at = created_at + timedelta(hours=ttl_hours)
    entry: dict = {
        "query": "q",
        "artifact": text,
        "sources": sources or [{"url": "https://a.com", "title": "A"}],
        "model": "m",
        "created_at": created_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "user_id": None,
        "memory_id": memory_id,
    }
    if fingerprint:
        entry["fingerprint"] = fingerprint
    return entry


def _make_memory(
    store: dict[str, str], results: list[dict]
) -> tuple[ResearchMemory, MagicMock]:
    """Construct a ResearchMemory with mocked embed/Qdrant and dict redis."""
    memory = ResearchMemory("redis://localhost:6379/0")
    memory.redis = _dict_redis(store)
    memory._embed = AsyncMock(return_value=[0.0] * 1024)
    memory._ensure_collection = AsyncMock()
    qdrant = MagicMock()
    resp = MagicMock()
    resp.json.return_value = {"result": results}
    resp.raise_for_status = MagicMock()
    qdrant.post = AsyncMock(return_value=resp)
    memory._get_qdrant = AsyncMock(return_value=qdrant)
    return memory, qdrant


def _result(memory_id: str, score: float = 0.95) -> dict:
    return {"score": score, "payload": {"memory_id": memory_id}}


# ── Compatibility fingerprint ────────────────────────────────────


class TestCompatibilityFingerprint:
    def _fp(self, **overrides) -> str:
        kwargs = dict(
            prompt="p",
            urls=["https://a.com"],
            schema={"type": "object"},
            model="gpt-4o",
            search_type="deep",
            include_images=False,
            citation_style="inline",
            strict_constrain_to_urls=False,
            force_fresh=False,
        )
        kwargs.update(overrides)
        return compute_fingerprint(**kwargs)

    def test_normalizes_whitespace_and_sorts_urls(self):
        a = compute_fingerprint(
            prompt="hello   world", urls=["https://b.com", "https://a.com"]
        )
        b = compute_fingerprint(
            prompt="hello world", urls=["https://a.com", "https://b.com"]
        )
        assert a == b

    def test_schema_key_order_is_insensitive(self):
        a = compute_fingerprint(
            schema={"type": "object", "properties": {"x": {"type": "string"}}}
        )
        b = compute_fingerprint(
            schema={"properties": {"x": {"type": "string"}}, "type": "object"}
        )
        assert a == b

    def test_model_default_and_none_canonicalize(self):
        a = compute_fingerprint(model="default")
        b = compute_fingerprint(model=None)
        assert a == b

    def test_varies_per_incompatibility_dimension(self):
        base = self._fp()
        assert self._fp(prompt="p2") != base
        assert self._fp(urls=["https://b.com"]) != base
        assert self._fp(schema={"type": "string"}) != base
        assert self._fp(model="other-model") != base
        assert self._fp(search_type="focused") != base
        assert self._fp(include_images=True) != base
        assert self._fp(citation_style="compact") != base
        assert self._fp(strict_constrain_to_urls=True) != base
        assert self._fp(force_fresh=True) != base


# ── Query: compatibility + freshness + gates ─────────────────────


class TestResearchMemoryQuery:
    @pytest.mark.asyncio
    async def test_compatible_replay_hit(self):
        fp = compute_fingerprint(prompt="q")
        store = {"memory:mid:data": json.dumps(_stored_entry("mid", fingerprint=fp))}
        memory, _ = _make_memory(store, [_result("mid")])
        result = await memory.query("q", fingerprint=fp)
        assert result["hit"] is True
        assert result["freshness"] == "fresh"
        assert result["compatibility"] == "compatible"
        assert result["age_hours"] is not None
        assert result["expires_at"] is not None

    @pytest.mark.asyncio
    async def test_incompatible_fingerprint_miss(self):
        stored_fp = compute_fingerprint(prompt="q", model="gpt-4o")
        store = {
            "memory:mid:data": json.dumps(_stored_entry("mid", fingerprint=stored_fp))
        }
        memory, _ = _make_memory(store, [_result("mid")])
        result = await memory.query(
            "q", fingerprint=compute_fingerprint(prompt="q", model="other")
        )
        assert result["hit"] is False
        assert result.get("compatibility") == "incompatible"

    @pytest.mark.asyncio
    async def test_missing_stored_fingerprint_miss(self):
        store = {"memory:mid:data": json.dumps(_stored_entry("mid"))}
        memory, _ = _make_memory(store, [_result("mid")])
        result = await memory.query("q", fingerprint=compute_fingerprint(prompt="q"))
        assert result["hit"] is False

    @pytest.mark.asyncio
    async def test_missing_or_malformed_timestamps_miss(self):
        fp = compute_fingerprint(prompt="q")
        good = _stored_entry("mid", fingerprint=fp)
        missing = dict(good)
        del missing["created_at"]
        store = {"memory:mid:data": json.dumps(missing)}
        memory, _ = _make_memory(store, [_result("mid")])
        assert (await memory.query("q", fingerprint=fp))["hit"] is False

        malformed = _stored_entry("mid2", fingerprint=fp)
        malformed["created_at"] = "not-a-timestamp"
        store2 = {"memory:mid2:data": json.dumps(malformed)}
        memory2, _ = _make_memory(store2, [_result("mid2")])
        assert (await memory2.query("q", fingerprint=fp))["hit"] is False

    @pytest.mark.asyncio
    async def test_expired_timestamp_miss(self):
        fp = compute_fingerprint(prompt="q")
        entry = _stored_entry("mid", fingerprint=fp)
        entry["expires_at"] = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        store = {"memory:mid:data": json.dumps(entry)}
        memory, _ = _make_memory(store, [_result("mid")])
        assert (await memory.query("q", fingerprint=fp))["hit"] is False

    @pytest.mark.asyncio
    async def test_max_age_hours_gate(self):
        fp = compute_fingerprint(prompt="q")
        entry = _stored_entry("mid", fingerprint=fp, age_hours=50.0)
        store = {"memory:mid:data": json.dumps(entry)}
        memory, _ = _make_memory(store, [_result("mid")])
        assert (await memory.query("q", fingerprint=fp, max_age_hours=10))[
            "hit"
        ] is False
        assert (await memory.query("q", fingerprint=fp, max_age_hours=100))[
            "hit"
        ] is True

    @pytest.mark.asyncio
    async def test_freshness_boundaries(self):
        fp = compute_fingerprint(prompt="q")
        cases = [
            (20.0, "fresh"),  # < TTL/4 (42h)
            (60.0, "aging"),  # TTL/4 <= age < TTL/2 (84h)
            (100.0, "stale"),  # >= TTL/2
        ]
        for age, expected in cases:
            entry = _stored_entry("mid", fingerprint=fp, age_hours=age)
            store = {"memory:mid:data": json.dumps(entry)}
            memory, _ = _make_memory(store, [_result("mid")])
            result = await memory.query("q", fingerprint=fp)
            assert result["freshness"] == expected

    @pytest.mark.asyncio
    async def test_swr_eligibility_window(self):
        fp = compute_fingerprint(prompt="q")
        entry = _stored_entry("mid", fingerprint=fp, age_hours=100.0)  # stale
        store = {"memory:mid:data": json.dumps(entry)}
        memory, _ = _make_memory(store, [_result("mid")])

        within = await memory.query("q", fingerprint=fp, max_stale_hours=20.0)
        assert within["swr_eligible"] is True

        outside = await memory.query("q", fingerprint=fp, max_stale_hours=10.0)
        assert outside["swr_eligible"] is False

        no_window = await memory.query("q", fingerprint=fp)
        assert no_window["swr_eligible"] is False


class TestStoreFingerprint:
    @pytest.mark.asyncio
    async def test_store_records_fingerprint_on_entry_and_payload(self):
        store: dict[str, str] = {}
        memory = ResearchMemory("redis://localhost:6379/0")
        memory.redis = _dict_redis(store)
        memory._embed = AsyncMock(return_value=[0.0] * 1024)
        memory._ensure_collection = AsyncMock()
        qdrant = MagicMock()
        put_resp = MagicMock()
        put_resp.status_code = 200
        put_resp.text = ""
        qdrant.put = AsyncMock(return_value=put_resp)
        memory._get_qdrant = AsyncMock(return_value=qdrant)

        mid = await memory.store(
            prompt="q",
            artifact="answer",
            sources=[{"url": "https://a.com", "title": "A"}],
            model="m",
            fingerprint="fp123",
        )

        entry = json.loads(store[f"memory:{mid}:data"])
        assert entry["fingerprint"] == "fp123"
        point = qdrant.put.await_args.kwargs["json"]["points"][0]
        assert point["payload"]["fingerprint"] == "fp123"


# ── Single-flight refresh ────────────────────────────────────────


class TestSingleFlightRefresh:
    @pytest.mark.asyncio
    async def test_concurrent_refresh_suppressed(self):
        memory = ResearchMemory("redis://localhost:6379/0")
        calls = 0

        async def factory() -> str:
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.01)
            return "result"

        t1 = memory.start_refresh("key", factory)
        t2 = memory.start_refresh("key", factory)
        assert t1 is t2
        assert await t1 == "result"
        assert calls == 1


# ── Stale replay streaming (SWR) ─────────────────────────────────


class TestStaleWhileRevalidateStreaming:
    async def _chunks(self, refresh_awaitable):
        from agent.models import CitationStyle
        from agent.research.streaming import stream_cached_artifact

        return [
            chunk
            async for chunk in stream_cached_artifact(
                artifact_text="stale answer [1]",
                sources=[{"url": "https://a.com", "title": "A"}],
                memory_id="m",
                freshness="stale",
                similarity=0.9,
                citation_style=CitationStyle.inline,
                has_schema=False,
                age_hours=50.0,
                refresh_awaitable=refresh_awaitable,
            )
        ]

    @pytest.mark.asyncio
    async def test_refresh_failure_still_stale_no_crash(self):
        async def fail():
            raise RuntimeError("refresh boom")

        chunks = await self._chunks(fail())
        done = json.loads(chunks[-2].removeprefix("data: "))
        assert done["freshness"] == "stale"
        assert done["refreshed"] is False
        assert done["age_hours"] == 50.0
        assert chunks[-1] == "data: [DONE]\n\n"
        assert not any('"type": "refreshed"' in chunk for chunk in chunks)

    @pytest.mark.asyncio
    async def test_refresh_success_emits_refreshed_event(self):
        async def ok():
            return {
                "result": "fresh answer",
                "sources": ["https://a.com"],
                "research_memory_id": "new-mid",
            }

        chunks = await self._chunks(ok())
        refreshed = [
            json.loads(chunk.removeprefix("data: "))
            for chunk in chunks
            if '"type": "refreshed"' in chunk
        ]
        assert len(refreshed) == 1
        assert refreshed[0]["freshness"] == "refreshed"
        assert refreshed[0]["result"] == "fresh answer"
        assert refreshed[0]["memory_id"] == "new-mid"


# ── Agent cache lookup (streaming replay gate) ───────────────────


class TestLookupAgentCache:
    @pytest.mark.asyncio
    async def test_force_fresh_bypasses_cache(self):
        from agent.models import AgentRequest
        from agent.routes.agent import _lookup_agent_cache

        request = MagicMock()
        memory = MagicMock()
        memory.query = AsyncMock()
        request.app.state.research_memory = memory
        body = AgentRequest(prompt="q", force_fresh=True)

        result = await _lookup_agent_cache(request, body, "fp")
        assert result is None
        memory.query.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_stale_swr_off_returns_none(self):
        from agent.models import AgentRequest
        from agent.routes.agent import _lookup_agent_cache

        request = MagicMock()
        memory = MagicMock()
        memory.query = AsyncMock(
            return_value={"hit": True, "freshness": "stale", "swr_eligible": True}
        )
        request.app.state.research_memory = memory
        body = AgentRequest(prompt="q")

        with patch("agent.routes.agent._derive_user_id", return_value=None):
            result = await _lookup_agent_cache(request, body, "fp")
        assert result is None

    @pytest.mark.asyncio
    async def test_stale_swr_on_eligible_returns_result(self):
        from agent.models import AgentRequest
        from agent.routes.agent import _lookup_agent_cache

        request = MagicMock()
        memory = MagicMock()
        memory.query = AsyncMock(
            return_value={"hit": True, "freshness": "stale", "swr_eligible": True}
        )
        request.app.state.research_memory = memory
        body = AgentRequest(prompt="q", stale_while_revalidate=True)

        with patch("agent.routes.agent._derive_user_id", return_value=None):
            result = await _lookup_agent_cache(request, body, "fp")
        assert result is not None
        assert result["freshness"] == "stale"


# ── Worker non-streaming SWR ─────────────────────────────────────


class TestWorkerStaleWhileRevalidate:
    async def _run_stale(
        self, *, stale_while_revalidate: bool, swr_eligible: bool
    ) -> dict:
        from agent.worker import _process_agent_async

        mock_store = MagicMock()
        mock_store.get_completed.return_value = 0
        memory = MagicMock()
        memory.query = AsyncMock(
            return_value={
                "hit": True,
                "freshness": "stale",
                "swr_eligible": swr_eligible,
                "artifact": {
                    "artifact": "stale [1]",
                    "sources": [{"url": "https://a.com", "title": "A"}],
                },
                "similarity": 0.9,
                "memory_id": "m",
                "age_hours": 50.0,
            }
        )
        memory.start_refresh = MagicMock()
        memory.store = AsyncMock()
        mock_run_research = AsyncMock(
            return_value={
                "result": "fresh",
                "sources": ["https://a.com"],
                "source_details": [{"url": "https://a.com", "title": "A"}],
            }
        )
        mock_deliver_webhook = AsyncMock()
        mock_metrics = MagicMock()
        mock_metrics.counter.return_value.inc = MagicMock()
        mock_metrics.histogram.return_value.observe = MagicMock()

        with (
            patch("agent.worker.JobStore", return_value=mock_store),
            patch("agent.worker.run_research", mock_run_research),
            patch("agent.worker.deliver_webhook", mock_deliver_webhook),
            patch("agent.worker.METRICS", mock_metrics),
            patch(
                "agent.worker.load_settings",
                return_value=MagicMock(
                    valkey_host="valkey",
                    valkey_port=6379,
                    valkey_db=0,
                    crawl_max_duration_seconds=1800,
                    crawl_idle_timeout_seconds=300,
                ),
            ),
        ):
            await _process_agent_async(
                job_id="swr-job",
                prompt="q",
                urls=None,
                schema_=None,
                llm_base_url="http://llm",
                llm_api_key="k",
                llm_model="m",
                searxng_url="http://searxng",
                scraper_url="http://scraper",
                research_memory=memory,
                stale_while_revalidate=stale_while_revalidate,
                max_stale_hours=6.0,
                fingerprint="fp",
            )

        return {
            "store": mock_store,
            "memory": memory,
            "run_research": mock_run_research,
        }

    @pytest.mark.asyncio
    async def test_stale_swr_serves_stale_and_starts_refresh(self):
        mocks = await self._run_stale(stale_while_revalidate=True, swr_eligible=True)
        payload = mocks["store"].complete_job.call_args.args[1]
        assert payload["freshness"] == "stale"
        assert payload["refreshed"] is False
        assert payload["age_hours"] == 50.0
        mocks["memory"].start_refresh.assert_called_once()
        mocks["run_research"].assert_not_awaited()

    @pytest.mark.asyncio
    async def test_stale_swr_off_runs_fresh_pipeline(self):
        mocks = await self._run_stale(stale_while_revalidate=False, swr_eligible=True)
        mocks["memory"].start_refresh.assert_not_called()
        mocks["run_research"].assert_awaited_once()
        payload = mocks["store"].complete_job.call_args.args[1]
        assert payload["cached_version_exists"] is True
        assert payload["cached_version_age_hours"] == 50.0


# ── Sweep ────────────────────────────────────────────────────────


class TestSweep:
    @pytest.mark.asyncio
    async def test_sweep_removes_orphan_preserves_active_and_records_metric(self):
        store = {"memory:active:data": json.dumps(_stored_entry("active"))}
        memory = ResearchMemory("redis://localhost:6379/0")
        memory.redis = _dict_redis(store)

        qdrant = MagicMock()
        scroll = MagicMock()
        scroll.status_code = 200
        scroll.raise_for_status = MagicMock()
        scroll.json.return_value = {
            "result": {
                "points": [
                    {"id": "o1", "payload": {"memory_id": "orphan1"}},
                    {"id": "a1", "payload": {"memory_id": "active"}},
                ],
                "next_page_offset": None,
            }
        }
        delete = MagicMock()
        delete.status_code = 200
        qdrant.post = AsyncMock(side_effect=[scroll, delete])
        memory._get_qdrant = AsyncMock(return_value=qdrant)

        with (
            patch("agent.research_memory.inc_counter") as inc_counter,
            patch("agent.research_memory.set_gauge") as set_gauge,
            patch("agent.research_memory.METRICS") as metrics,
        ):
            metrics.counter.return_value.inc = MagicMock()
            removed = await memory.sweep()

        assert removed == 1
        assert qdrant.post.await_count == 2

        # The delete call targets the orphaned memory_id only.
        delete_filter = qdrant.post.await_args_list[1].kwargs["json"]["filter"]
        assert delete_filter["must"][0]["match"]["value"] == "orphan1"

        inc_counter.assert_called_once_with(
            "groktocrawl_research_memory_sweep_runs_total",
            "Research memory sweep invocations",
            {},
        )
        metrics.counter.assert_called_once_with(
            "groktocrawl_research_memory_orphans_swept_total",
            "Orphaned Qdrant points removed by research memory sweep",
        )
        metrics.counter.return_value.inc.assert_called_once_with(value=1.0)
        set_gauge.assert_called_once_with(
            "groktocrawl_research_memory_orphans",
            "Orphaned Qdrant points removed in the most recent sweep",
            {},
            1.0,
        )

    @pytest.mark.asyncio
    async def test_sweep_loop_calls_sweep_and_stops_on_shutdown(self):
        memory = MagicMock()
        memory.sweep = AsyncMock(return_value=2)
        shutdown = asyncio.Event()
        task = asyncio.create_task(
            run_research_memory_sweep_loop(memory, 0.01, shutdown)
        )
        await asyncio.sleep(0.06)
        shutdown.set()
        await task
        assert memory.sweep.await_count >= 1
