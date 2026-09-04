"""Focused regression tests for asynchronous, batched session persistence."""

import asyncio
import json
import time

import pytest


class _Pipeline:
    def __init__(self, redis):
        self.redis = redis
        self.operations = []

    def __getattr__(self, name):
        def queue(*args, **kwargs):
            self.operations.append((name, args, kwargs))
            return self

        return queue

    def execute(self):
        results = []
        for name, args, kwargs in self.operations:
            results.append(getattr(self.redis, name)(*args, **kwargs))
        self.operations = []
        return results


class FakeRedis:
    """Small Redis double that records commands and applies pipelines."""

    def __init__(self):
        self.data = {}
        self.expiries = {}
        self.commands = []
        self.delay = 0

    def _call(self, name):
        self.commands.append(name)
        if self.delay:
            time.sleep(self.delay)

    def hset(self, key, field=None, value=None, *, mapping=None):
        self._call("hset")
        current = self.data.setdefault(key, {})
        if mapping is not None:
            current.update(mapping)
            return len(mapping)
        current[field] = value
        return 1

    def hgetall(self, key):
        self._call("hgetall")
        return dict(self.data.get(key, {}))

    def hget(self, key, field):
        self._call("hget")
        return self.data.get(key, {}).get(field)

    def hdel(self, key, field):
        self._call("hdel")
        return int(self.data.get(key, {}).pop(field, None) is not None)

    def exists(self, key):
        self._call("exists")
        return int(key in self.data)

    def set(self, key, value, **kwargs):
        self._call("set")
        self.data[key] = value
        return True

    def get(self, key):
        self._call("get")
        return self.data.get(key)

    def append(self, key, value):
        self._call("append")
        self.data[key] = str(self.data.get(key, "")) + value
        return len(self.data[key].encode())

    def hincrby(self, key, field, amount):
        self._call("hincrby")
        current = int(self.data.setdefault(key, {}).get(field, 0)) + amount
        self.data[key][field] = str(current)
        return current

    def expire(self, key, ttl):
        self._call("expire")
        self.expiries[key] = ttl
        return True

    def pipeline(self, **_kwargs):
        self._call("pipeline")
        return _Pipeline(self)

    def delete(self, *keys):
        self._call("delete")
        removed = 0
        for key in keys:
            removed += int(self.data.pop(key, None) is not None)
            self.expiries.pop(key, None)
        return removed


@pytest.fixture
def store():
    from agent.session_store import SessionStore

    result = SessionStore(redis_url="redis://unused")
    result.redis = FakeRedis()
    return result


@pytest.mark.asyncio
async def test_async_session_lifecycle_batches_refs_and_preserves_unicode(store):
    session_id = await store.acreate(ttl=120)
    refs = {
        f"ref_1_{i}": {"url": f"https://example.test/{i}", "markdown": "é"}
        for i in range(100)
    }

    before_refs = len(store.redis.commands)
    assert await store.aadd_refs(session_id, refs)
    ref_commands = store.redis.commands[before_refs:]
    # One metadata read, one pipeline transaction, one bulk HSET, one
    # metadata HSET, and four fixed TTL commands; no command per ref.
    assert ref_commands.count("hset") == 2
    assert len(ref_commands) <= 9

    assert await store.aappend_artifact(session_id, "é🙂")
    assert await store.aappend_artifact(session_id, "\nmore")
    store.redis.commands.clear()
    session = await store.aget(session_id)
    assert session["artifact_length"] == len("é🙂\nmore")
    # The only GET is the legacy JSON step history; artifact length comes
    # directly from metadata and does not fetch the markdown value.
    assert store.redis.commands.count("get") == 1
    assert (await store.aget_refs(session_id))["ref_1_0"]["markdown"] == "é"
    assert list((await store.aget_refs(session_id)).keys()) == list(refs.keys())

    assert await store.adelete(session_id)
    assert await store.aget(session_id) is None


@pytest.mark.parametrize("ref_count", [1, 20, 100])
def test_bulk_ref_command_count_is_bounded(store, ref_count):
    session_id = store.create()
    refs = {f"ref_{i}": {"url": f"https://example.test/{i}"} for i in range(ref_count)}
    store.redis.commands.clear()
    assert store.add_refs(session_id, refs)
    assert len(store.redis.commands) == 8


@pytest.mark.asyncio
async def test_blocked_redis_read_does_not_block_event_loop(store):
    session_id = await store.acreate()
    store.redis.delay = 0.08
    beats = 0

    async def heartbeat():
        nonlocal beats
        deadline = asyncio.get_running_loop().time() + 0.05
        while asyncio.get_running_loop().time() < deadline:
            beats += 1
            await asyncio.sleep(0.005)

    await asyncio.gather(store.aget(session_id), heartbeat())
    assert beats >= 5


@pytest.mark.asyncio
async def test_search_step_commits_refs_as_one_storage_batch(store, monkeypatch):
    from agent.session import SessionManager

    session_id = await store.acreate()
    manager = SessionManager.__new__(SessionManager)
    manager.store = store

    class Search:
        def __init__(self, *_args, **_kwargs):
            pass

        async def search(self, **_kwargs):
            return (
                [
                    {
                        "url": f"https://example.test/{i}",
                        "title": f"Source {i}",
                        "description": "summary",
                    }
                    for i in range(20)
                ],
                None,
            )

        async def close(self):
            pass

    monkeypatch.setattr("agent.session.SearXNGClient", Search)
    before = len(store.redis.commands)
    outcome = await manager._step_search(session_id, {"query": "batch"}, "unused")

    assert outcome["ref_count"] == 20
    assert len(await store.aget_refs(session_id)) == 20
    committed = store.redis.commands[before:]
    assert committed.count("hset") == 4  # fixed writes, independent of ref count
    assert committed.count("pipeline") == 2


@pytest.mark.asyncio
async def test_async_manager_uses_offloaded_store_methods():
    from agent.session import SessionManager

    manager = SessionManager.__new__(SessionManager)
    calls = []

    class Store:
        def get(self, session_id):
            time.sleep(0.03)
            calls.append(session_id)
            return {"id": session_id}

    manager.store = Store()
    result = await manager.get_session("s-1")
    assert result == {"id": "s-1"}
    assert calls == ["s-1"]


def test_sync_append_keeps_legacy_character_count(store):
    session_id = store.create()
    assert store.append_artifact(session_id, "é🙂")
    assert store.get(session_id)["artifact_length"] == 2
    artifact = store.get_artifact(session_id)
    assert json.loads(json.dumps(artifact, ensure_ascii=False)) == "é🙂"


@pytest.mark.parametrize("prefix", ["", "é🙂" * 5_000])
def test_artifact_append_does_not_download_existing_value(store, prefix):
    session_id = store.create()
    if prefix:
        store.append_artifact(session_id, prefix)
    store.redis.commands.clear()
    assert store._append_artifact_atomic(session_id, "追加🙂")
    assert "get" not in store.redis.commands
    assert store.get(session_id)["artifact_length"] == len(prefix) + 3
