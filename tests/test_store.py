"""Tests for agent-svc/agent/store.py — JobStore backed by a fake Redis."""

import json
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def fake_redis():
    """Return mocks that mimic Redis basic operations including scan/pipeline."""
    store_data = {}

    r = MagicMock()
    r.set = MagicMock(
        side_effect=lambda key, val, ex=None: store_data.update({key: val}) or True
    )
    r.get = MagicMock(side_effect=lambda key: store_data.get(key))

    def mock_scan(cursor=0, match=None, count=10):
        import fnmatch

        all_keys = list(store_data.keys())
        if match:
            matched = [k for k in all_keys if fnmatch.fnmatch(k, match)]
        else:
            matched = all_keys
        return (0, matched)

    r.scan = MagicMock(side_effect=mock_scan)

    # Pipeline support
    class _Pipeline:
        def __init__(self):
            self._keys = []

        def get(self, key):
            self._keys.append(key)
            return self

        def execute(self):
            results = [store_data.get(k) for k in self._keys]
            self._keys = []
            return results

    r.pipeline = MagicMock(return_value=_Pipeline())

    return r


@pytest.fixture
def store(fake_redis):
    from agent.store import JobStore

    s = JobStore(redis_url="redis://fake:6379/0")
    s.redis = fake_redis
    return s


class TestJobStore:
    def test_create_job_returns_id_and_sets_meta(self, store, fake_redis):
        job_id = store.create_job(kind="agent", payload={"prompt": "hello"})
        assert job_id is not None
        assert len(job_id) > 0
        raw = fake_redis.get(f"job:{job_id}:meta")
        assert raw is not None
        meta = json.loads(raw)
        assert meta["kind"] == "agent"
        assert meta["status"] == "processing"
        assert meta["payload"] == {"prompt": "hello"}

    def test_get_job_returns_meta(self, store, fake_redis):
        job_id = store.create_job(kind="agent")
        meta = store.get_job(job_id)
        assert meta is not None
        assert meta["status"] == "processing"

    def test_get_job_returns_none_for_missing(self, store):
        assert store.get_job("nonexistent") is None

    def test_complete_job(self, store, fake_redis):
        job_id = store.create_job(kind="agent")
        store.complete_job(job_id, {"result": "done"})
        meta = store.get_job(job_id)
        assert meta["status"] == "completed"
        assert meta["completed_at"] is not None
        assert meta["data"] == {"result": "done"}

    def test_complete_job_unknown_id_does_not_raise(self, store):
        store.complete_job("unknown", {"result": "done"})  # should not raise

    def test_fail_job(self, store, fake_redis):
        job_id = store.create_job(kind="agent")
        store.fail_job(job_id, "Something went wrong")
        meta = store.get_job(job_id)
        assert meta["status"] == "failed"
        assert meta["error"] == "Something went wrong"

    def test_fail_job_unknown_id_does_not_raise(self, store):
        store.fail_job("unknown", "error")  # should not raise

    def test_cancel_job(self, store, fake_redis):
        job_id = store.create_job(kind="agent")
        cancelled = store.cancel_job(job_id)
        assert cancelled is True
        meta = store.get_job(job_id)
        assert meta["status"] == "cancelled"

    def test_cancel_completed_job_returns_false(self, store, fake_redis):
        job_id = store.create_job(kind="agent")
        store.complete_job(job_id, {"result": "done"})
        cancelled = store.cancel_job(job_id)
        assert cancelled is False  # already completed

    def test_cancel_unknown_job_returns_false(self, store):
        cancelled = store.cancel_job("nonexistent")
        assert cancelled is False

    def test_list_active_jobs(self, store, fake_redis):
        store.create_job(kind="agent")
        store.create_job(kind="crawl")
        id3 = store.create_job(kind="agent")
        store.complete_job(id3, {})  # complete one

        # Should return processing jobs only
        active = store.list_active_jobs()
        assert len(active) >= 2  # at least 2 processing
        statuses = [j["status"] for j in active]
        assert all(s == "processing" for s in statuses)

    def test_list_active_jobs_filters_by_kind(self, store, fake_redis):
        store.create_job(kind="agent")
        store.create_job(kind="crawl")

        agent_jobs = store.list_active_jobs(kind="agent")
        assert all(j["kind"] == "agent" for j in agent_jobs)
        assert len(agent_jobs) >= 1

    def test_list_active_jobs_empty_when_all_completed(self, store, fake_redis):
        ids = [store.create_job(kind="agent") for _ in range(3)]
        for jid in ids:
            store.complete_job(jid, {})

        active = store.list_active_jobs()
        assert len(active) == 0

    def test_reuses_fake_redis_connection(self, store, fake_redis):
        """Verify that create_job and get_job use the same store."""
        jid = store.create_job(kind="test")
        meta = store.get_job(jid)
        assert meta["kind"] == "test"

    def test_complete_job_attaches_data(self, store, fake_redis):
        jid = store.create_job(kind="agent")
        data = {"result": "the answer", "sources": ["https://a.com"]}
        store.complete_job(jid, data)
        meta = store.get_job(jid)
        assert meta["data"] == data
