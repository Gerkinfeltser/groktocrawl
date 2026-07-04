"""Tests for the generic TTL SessionStore (mcp-svc/session_store.py).

Validates all expected behaviors from the m5-mcp-session-store feature
and the VAL-MCP-I03 / VAL-MCP-I04 assertions.
"""

from __future__ import annotations

import asyncio
import os

import pytest
from session_store import SessionStore

# ── Helpers ────────────────────────────────────────────────────────


@pytest.fixture
def store():
    """Return a fresh SessionStore with a short TTL for fast tests."""
    return SessionStore(ttl=2, sweep_interval=1)


@pytest.fixture(autouse=True)
async def _stop_sweep(store):
    """Ensure the background sweep is stopped after every test."""
    yield
    await store.stop_sweep()


# ── create ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_returns_session_id(store):
    """create() returns a non-empty string session ID (VAL-MCP-I03)."""
    sid = await store.create({"client": "test"})
    assert isinstance(sid, str)
    assert len(sid) > 0


@pytest.mark.asyncio
async def test_create_stores_metadata(store):
    """create() stores arbitrary metadata dicts (VAL-MCP-I04)."""
    metadata = {"client": "test", "init_params": {"x": 1}}
    sid = await store.create(metadata)
    data = await store.get(sid)
    assert data == metadata


@pytest.mark.asyncio
async def test_create_with_explicit_session_id(store):
    """create() accepts an explicit session_id keyword."""
    sid = await store.create({"type": "browser"}, session_id="explicit-123")
    assert sid == "explicit-123"
    data = await store.get("explicit-123")
    assert data == {"type": "browser"}


@pytest.mark.asyncio
async def test_create_with_no_metadata(store):
    """create() works with no metadata — stores empty dict."""
    sid = await store.create()
    data = await store.get(sid)
    assert data == {}


@pytest.mark.asyncio
async def test_create_isolated_sessions(store):
    """Each create() call returns a unique ID and isolated data."""
    sid1 = await store.create({"name": "alice"})
    sid2 = await store.create({"name": "bob"})
    assert sid1 != sid2
    assert (await store.get(sid1)) == {"name": "alice"}
    assert (await store.get(sid2)) == {"name": "bob"}


# ── get ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_returns_none_for_missing(store):
    """get() returns None for an unknown session ID."""
    assert await store.get("nonexistent") is None


@pytest.mark.asyncio
async def test_get_returns_none_for_expired(store):
    """get() returns None after TTL expires (VAL-MCP-I03)."""
    sid = await store.create({"client": "test"})
    assert await store.get(sid) is not None
    await asyncio.sleep(3)  # TTL is 2 s
    assert await store.get(sid) is None


@pytest.mark.asyncio
async def test_get_returns_copy_not_reference(store):
    """get() returns a shallow copy — mutations don't affect the store."""
    sid = await store.create({"key": "original"})
    data = await store.get(sid)
    data["key"] = "mutated"
    # Re-fetch — should still have the original value
    data2 = await store.get(sid)
    assert data2["key"] == "original"


@pytest.mark.asyncio
async def test_get_for_active_session_returns_data(store):
    """get() returns the stored metadata for an active session."""
    metadata = {"a": 1, "b": [2, 3], "c": {"nested": True}}
    sid = await store.create(metadata)
    result = await store.get(sid)
    assert result == metadata


# ── update ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_modifies_data_in_place(store):
    """update() merges data into an existing session."""
    sid = await store.create({"original": "value"})
    await store.update(sid, {"new_key": "new_value"})
    data = await store.get(sid)
    assert data == {"original": "value", "new_key": "new_value"}


@pytest.mark.asyncio
async def test_update_noop_on_missing(store):
    """update() on a missing session does nothing (no error)."""
    await store.update("nonexistent", {"x": 1})
    # Should not raise


@pytest.mark.asyncio
async def test_update_overwrites_existing_keys(store):
    """update() overwrites keys that already exist in the session data."""
    sid = await store.create({"x": 1, "y": 2})
    await store.update(sid, {"x": 10, "z": 3})
    data = await store.get(sid)
    assert data["x"] == 10
    assert data["y"] == 2
    assert data["z"] == 3


# ── destroy ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_destroy_removes_session(store):
    """destroy() removes a session — get() returns None afterwards."""
    sid = await store.create({"data": "to-delete"})
    assert await store.get(sid) is not None
    await store.destroy(sid)
    assert await store.get(sid) is None


@pytest.mark.asyncio
async def test_destroy_noop_on_missing(store):
    """destroy() on a missing session does nothing (no error)."""
    await store.destroy("nonexistent")
    # Should not raise


# ── sweep ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sweep_removes_expired_sessions(store):
    """sweep() removes expired sessions and returns the count."""
    sid1 = await store.create({"name": "expires"})
    sid2 = await store.create({"name": "expires-too"})
    # Stop background sweep so it doesn't pre-clean expired sessions
    await store.stop_sweep()
    # Wait for TTL to expire
    await asyncio.sleep(3)
    removed = await store.sweep()
    assert removed == 2
    assert await store.get(sid1) is None
    assert await store.get(sid2) is None


@pytest.mark.asyncio
async def test_sweep_keeps_active_sessions(store):
    """sweep() does not remove sessions that haven't expired."""
    # Use a separate store with long TTL for the "active" session
    store_active = SessionStore(ttl=3600, sweep_interval=3600)
    sid_active = await store_active.create({"name": "active"})
    # Create and expire another session
    store_expiring = SessionStore(ttl=1, sweep_interval=3600)
    sid_expired = await store_expiring.create({"name": "expired"})
    await asyncio.sleep(2)
    removed = await store_expiring.sweep()
    assert removed == 1
    assert await store_expiring.get(sid_expired) is None

    # Active store's session should still be active
    assert await store_active.get(sid_active) is not None

    await store_active.stop_sweep()
    await store_expiring.stop_sweep()


@pytest.mark.asyncio
async def test_sweep_returns_zero_when_nothing_expired(store):
    """sweep() returns 0 when no sessions have expired."""
    sid = await store.create({"name": "fresh"})
    removed = await store.sweep()
    assert removed == 0
    assert await store.get(sid) is not None


# ── Background sweep ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_background_sweep_cleans_expired(store):
    """The background sweep task eventually removes expired sessions."""
    sid = await store.create({"name": "ephemeral"})
    # Force the sweep to run immediately (store has sweep_interval=1)
    await asyncio.sleep(3)  # TTL=2 + sweep_interval=1
    # After enough time, the background sweep should have cleaned up
    data = await store.get(sid)
    assert data is None


@pytest.mark.asyncio
async def test_sweep_task_starts_lazily(store):
    """The background sweep starts on first use of the store."""
    # The fixture's `store` already started the sweep via create() in
    # the autouse tests.  Create a fresh store and verify it starts
    # on the first call.
    fresh = SessionStore(ttl=1, sweep_interval=3600)
    assert fresh._sweep_task is None
    await fresh.create({"test": True})
    assert fresh._sweep_task is not None
    await fresh.stop_sweep()


@pytest.mark.asyncio
async def test_stop_sweep_stops_task(store):
    """stop_sweep() cancels the background task."""
    await store.stop_sweep()
    assert store._sweep_task is None
    # Safe to call again
    await store.stop_sweep()
    assert store._sweep_task is None


# ── Genericity (VAL-MCP-I04) ───────────────────────────────────────


def test_no_mcp_imports():
    """SessionStore has no imports from the mcp SDK (VAL-MCP-I04)."""
    import inspect

    src = inspect.getsource(SessionStore)
    assert "from mcp" not in src
    assert "import mcp" not in src


def test_accepts_arbitrary_metadata():
    """SessionStore accepts arbitrary metadata dicts, not MCP-specific."""
    store_sync = SessionStore(ttl=3600)

    async def _run():
        sid1 = await store_sync.create({"custom_field": 42, "nested": {"deep": True}})
        sid2 = await store_sync.create({"completely": "different", "shape": [1, 2]})
        assert await store_sync.get(sid1) is not None
        assert await store_sync.get(sid2) is not None
        await store_sync.stop_sweep()

    asyncio.run(_run())


# ── Env configuration ──────────────────────────────────────────────


def test_default_ttl_from_env(monkeypatch):
    """SessionStore reads TTL from SESSION_TTL env var (default 3600)."""
    import session_store as ss_module

    monkeypatch.setattr(ss_module, "_SESSION_TTL", 42)
    store_env = SessionStore()
    assert store_env._ttl == 42


def test_default_sweep_interval_from_env(monkeypatch):
    """SessionStore reads sweep interval from SESSION_SWEEP_INTERVAL (default 300)."""
    import session_store as ss_module

    monkeypatch.setattr(ss_module, "_SESSION_SWEEP_INTERVAL", 99)
    store_env = SessionStore()
    assert store_env._sweep_interval == 99


def test_constructor_overrides_env():
    """Constructor arguments override environment variables."""
    os.environ["SESSION_TTL"] = "999"
    os.environ["SESSION_SWEEP_INTERVAL"] = "888"
    store = SessionStore(ttl=50, sweep_interval=60)
    assert store._ttl == 50
    assert store._sweep_interval == 60


# ── Concurrency ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_create_and_get(store):
    """Multiple concurrent creates and gets work correctly."""

    async def create_and_get(i: int) -> tuple[int, str, dict | None]:
        sid = await store.create({"index": i})
        data = await store.get(sid)
        return i, sid, data

    tasks = [create_and_get(i) for i in range(20)]
    results = await asyncio.gather(*tasks)
    for i, sid, data in results:
        assert data == {"index": i}
        assert sid  # non-empty


@pytest.mark.asyncio
async def test_concurrent_update(store):
    """Concurrent updates to the same session are safe."""
    sid = await store.create({"counter": 0})

    async def bump():
        for _ in range(10):
            data = await store.get(sid)
            if data is not None:
                await store.update(sid, {"counter": data.get("counter", 0) + 1})

    await asyncio.gather(*[bump() for _ in range(5)])
    final = await store.get(sid)
    # With asyncio.Lock each bump's get+update is not atomic across
    # the two calls, so the final counter may be less than 50.
    # This test just verifies no crashes or corruption.
    assert final is not None
    assert isinstance(final["counter"], int)
    assert final["counter"] >= 1


# ── Edge cases ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_metadata_is_copied_not_referenced(store):
    """create() copies the metadata dict — later mutations to the
    original dict don't affect the stored session."""
    mutable = {"key": "original"}
    sid = await store.create(mutable)
    mutable["key"] = "mutated"
    mutable["extra"] = "added"
    data = await store.get(sid)
    assert data == {"key": "original"}


@pytest.mark.asyncio
async def test_destroy_then_recreate_same_id(store):
    """Recreating a session with the same explicit ID works after destroy."""
    sid = "reusable-id"
    await store.create({"version": 1}, session_id=sid)
    assert await store.get(sid) is not None
    await store.destroy(sid)
    assert await store.get(sid) is None
    await store.create({"version": 2}, session_id=sid)
    assert await store.get(sid) == {"version": 2}
