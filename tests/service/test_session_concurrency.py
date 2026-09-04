"""Regression tests for opt-in independent session step concurrency."""

import asyncio
import time

import pytest


class ParallelStore:
    def __init__(self):
        self.reservations = {}
        self.steps = []
        self.refs = {}
        self.artifact = ""
        self.deleted = False
        self.next_index = 0
        self._guard = asyncio.Lock()

    async def aget(self, _session_id):
        return None if self.deleted else {"id": "session-1", "revision": 0}

    async def areserve_step(self, _session_id, key, _lease_ttl):
        async with self._guard:
            if self.deleted:
                return None
            if key in self.reservations:
                existing = dict(self.reservations[key])
                existing.pop("acquired", None)
                return existing
            self.next_index += 1
            reservation = {
                "status": "pending",
                "acquired": True,
                "idempotency_key": key,
                "token": f"token-{len(self.reservations) + 1}",
                "index": self.next_index,
                "revision": len(self.steps),
            }
            self.reservations[key] = reservation
            return dict(reservation)

    async def acommit_step(
        self, _session_id, reservation, step, refs, artifact, result
    ):
        async with self._guard:
            if self.deleted:
                return None
            current = self.reservations[reservation["idempotency_key"]]
            if current.get("status") == "committed":
                return current["result"]
            self.steps.append(dict(step))
            self.refs.update(refs)
            self.artifact += artifact
            committed = dict(result)
            current.update(status="committed", result=committed)
            return committed

    async def arelease_step(self, _session_id, reservation):
        async with self._guard:
            current = self.reservations.get(reservation["idempotency_key"])
            if current and current.get("token") == reservation["token"]:
                self.reservations.pop(reservation["idempotency_key"], None)


@pytest.mark.asyncio
async def test_opt_in_search_steps_overlap_and_commit_unique_refs(monkeypatch):
    from agent.session import SessionManager

    store = ParallelStore()
    manager = SessionManager.__new__(SessionManager)
    manager.store = store
    started = []

    class Search:
        def __init__(self, *_args, **_kwargs):
            pass

        async def search(self, **kwargs):
            started.append(kwargs["query"])
            await asyncio.sleep(0.05)
            return (
                [
                    {
                        "url": f"https://example.test/{kwargs['query']}",
                        "title": kwargs["query"],
                        "description": "summary",
                    }
                ],
                None,
            )

        async def close(self):
            pass

    monkeypatch.setattr("agent.session.SearXNGClient", Search)
    start = time.perf_counter()
    results = await asyncio.gather(
        manager.step(
            "session-1",
            "search",
            {"query": "one"},
            llm_model="model",
            parallel=True,
            idempotency_key="one-request",
        ),
        manager.step(
            "session-1",
            "search",
            {"query": "two"},
            llm_model="model",
            parallel=True,
            idempotency_key="two-request",
        ),
    )
    elapsed = time.perf_counter() - start

    assert elapsed < 0.09
    assert started == ["one", "two"]
    assert {result["step_index"] for result in results} == {1, 2}
    assert set(store.refs) == {"ref_1_1", "ref_2_1"}
    assert len(store.steps) == 2

    pending = await store.areserve_step("session-1", "pending", 120)
    duplicate_pending = await store.areserve_step("session-1", "pending", 120)
    assert pending["acquired"] is True
    assert duplicate_pending.get("acquired", False) is False

    # A completed idempotency key returns its recorded result without another
    # remote search or a second reference/artifact commit.
    repeat = await manager.step(
        "session-1",
        "search",
        {"query": "one"},
        llm_model="model",
        parallel=True,
        idempotency_key="one-request",
    )
    assert repeat == results[0]
    assert started == ["one", "two"]
    assert len(store.steps) == 2


@pytest.mark.asyncio
async def test_failed_parallel_step_releases_reservation_for_retry(monkeypatch):
    from agent.session import SessionManager

    store = ParallelStore()
    manager = SessionManager.__new__(SessionManager)
    manager.store = store
    attempts = 0

    class Search:
        def __init__(self, *_args, **_kwargs):
            pass

        async def search(self, **_kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("search unavailable")
            return ([{"url": "https://example.test/retry", "description": "ok"}], None)

        async def close(self):
            pass

    monkeypatch.setattr("agent.session.SearXNGClient", Search)
    with pytest.raises(RuntimeError):
        await manager.step(
            "session-1",
            "search",
            {"query": "retry"},
            llm_model="model",
            parallel=True,
            idempotency_key="retry-request",
        )
    result = await manager.step(
        "session-1",
        "search",
        {"query": "retry"},
        llm_model="model",
        parallel=True,
        idempotency_key="retry-request",
    )
    assert attempts == 2
    assert result["step_index"] == 2


@pytest.mark.asyncio
async def test_late_parallel_commit_after_delete_is_rejected():
    from agent.session import SessionManager

    store = ParallelStore()
    manager = SessionManager.__new__(SessionManager)
    manager.store = store
    reservation = await store.areserve_step("session-1", "late", 120)
    store.deleted = True
    assert (
        await manager._store_call(
            "acommit_step",
            "commit_step",
            "session-1",
            reservation,
            {"action": "search", "index": 1},
            {},
            "late",
            {"step_index": 1},
        )
        is None
    )
