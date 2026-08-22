"""Config tests for the QDRANT_CLIENT_TIMEOUT env var (issue #588).

The semantic-svc Qdrant client previously used a hardcoded 5s timeout in
``_is_qdrant_ready`` and the qdrant-client library default (5s) in
``_ensure_qdrant``. On slow-but-healthy indexes that client timeout fired
BEFORE the ``QDRANT_QUERY_TIMEOUT`` asyncio.wait_for wrapper, making the
wrapper unreachable and the index look unavailable. ``QDRANT_CLIENT_TIMEOUT``
(default: ``QDRANT_QUERY_TIMEOUT``) must now govern BOTH construction
sites so the wrapper stays the binding bound (issue #588 criterion 2,
unit-level verification decision: no live slow Qdrant required).

Default-resolution cases run in an isolated interpreter via subprocess:
``semantic-svc/app.py`` computes module constants at import time and the
module name ``app`` makes in-process re-import fragile (router_search
binds imported constants at import time).
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_SEMANTIC_SVC_DIR = Path(__file__).resolve().parents[2] / "semantic-svc"
_REPO_ROOT = Path(__file__).resolve().parents[2]

# Scale real seconds down so an "8s" operation costs ~0.8s wall clock.
_SCALE = 0.1


def _import_app_with_stubbed_routers():
    """Import semantic-svc app + real routers with circular imports broken.

    Mirrors the workaround in tests/unit/test_semantic_svc_unit.py: stub
    the router modules, import app with include_router disabled, then let
    the real router modules load (app is already cached in sys.modules).
    """
    import fastapi

    for mod_name in ["router_index", "router_migration", "router_search"]:
        if mod_name not in sys.modules or not hasattr(
            sys.modules[mod_name], "__file__"
        ):
            mod = types.ModuleType(mod_name)
            setattr(mod, mod_name, fastapi.APIRouter())
            sys.modules[mod_name] = mod

    original_include = fastapi.applications.FastAPI.include_router
    fastapi.applications.FastAPI.include_router = lambda self, router, **kwargs: None
    try:
        import app  # noqa: F401
    finally:
        fastapi.applications.FastAPI.include_router = original_include

    # Drop the stubs so the REAL router modules can be imported on demand.
    for mod_name in ["router_index", "router_migration", "router_search"]:
        if getattr(sys.modules.get(mod_name), "__file__", None) is None:
            del sys.modules[mod_name]


def _resolve_module_constant(env: dict[str, str], constant: str) -> float:
    """Import semantic-svc/app.py in a fresh interpreter with patched env.

    Router imports at the bottom of app.py are stubbed out (same
    circular-import workaround as tests/unit/test_semantic_svc_unit.py)
    so no model or service dependencies load; only module constants are
    evaluated. The environment is NOT inherited from the pytest process
    beyond PATH/HOME, giving true isolated-interpreter resolution.
    """
    code = (
        "import sys, types\n"
        "import fastapi\n"
        "from fastapi import APIRouter\n"
        "for mod_name in ['router_index', 'router_migration', 'router_search']:\n"
        "    mod = types.ModuleType(mod_name)\n"
        f"    setattr(mod, mod_name, APIRouter())\n"
        "    sys.modules[mod_name] = mod\n"
        "original_include = fastapi.applications.FastAPI.include_router\n"
        "fastapi.applications.FastAPI.include_router = "
        "lambda self, router, **kwargs: None\n"
        "import app\n"
        "fastapi.applications.FastAPI.include_router = original_include\n"
        f"print(repr(app.{constant}))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=_SEMANTIC_SVC_DIR,
        env={
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", "/tmp"),
            # app.py imports common.logging/common.middleware from the repo
            # root (PYTHONPATH-style), like the containerized service does.
            "PYTHONPATH": str(_REPO_ROOT),
            **env,
        },
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return float(result.stdout.strip())


class TestQdrantClientTimeoutDefault:
    """VAL-FIND-010: unset QDRANT_CLIENT_TIMEOUT tracks QDRANT_QUERY_TIMEOUT."""

    def test_unset_defaults_to_qdrant_query_timeout_default(self):
        """Both vars unset → resolved default equals 10.0 (QDRANT_QUERY_TIMEOUT)."""
        assert _resolve_module_constant({}, "QDRANT_QUERY_TIMEOUT") == 10.0
        assert _resolve_module_constant({}, "QDRANT_CLIENT_TIMEOUT") == 10.0

    def test_unset_tracks_custom_qdrant_query_timeout(self):
        """QDRANT_QUERY_TIMEOUT=12 with client var unset → resolved value 12."""
        assert (
            _resolve_module_constant(
                {"QDRANT_QUERY_TIMEOUT": "12"}, "QDRANT_CLIENT_TIMEOUT"
            )
            == 12.0
        )

    def test_default_is_never_below_query_wrapper_timeout(self):
        """Invariant across permutations: default >= QDRANT_QUERY_TIMEOUT."""
        for query_timeout in ("10", "12"):
            resolved = _resolve_module_constant(
                {"QDRANT_QUERY_TIMEOUT": query_timeout}, "QDRANT_CLIENT_TIMEOUT"
            )
            assert resolved >= float(query_timeout)


class TestQdrantClientTimeoutAppliedAtConstructionSites:
    """VAL-FIND-011: the configured timeout reaches BOTH construction sites."""

    def test_ensure_qdrant_uses_configured_client_timeout(self, monkeypatch):
        """The persistent client in _ensure_qdrant gets QDRANT_CLIENT_TIMEOUT."""
        _import_app_with_stubbed_routers()
        import app

        captured: dict = {}

        class _FakeQdrantClient:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            def get_collections(self):
                collections = MagicMock()
                collections.collections = []
                return collections

            def create_collection(self, **kwargs):
                pass

        monkeypatch.setattr(app, "_qdrant", None)
        monkeypatch.setattr(app, "_qdrant_ready", False)
        # The module constant is int-typed (qdrant-client contract).
        monkeypatch.setattr(app, "QDRANT_CLIENT_TIMEOUT", 15)
        monkeypatch.setattr(app, "QdrantClient", _FakeQdrantClient)

        asyncio.run(app._ensure_qdrant())

        assert captured.get("timeout") == 15
        assert captured.get("url") == app.QDRANT_URL

    def test_is_qdrant_ready_uses_configured_client_timeout(self, monkeypatch):
        """The temporary readiness client gets QDRANT_CLIENT_TIMEOUT (not 5)."""
        _import_app_with_stubbed_routers()
        import app

        captured: dict = {}

        class _FakeQdrantClient:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            def get_collections(self):
                return MagicMock()

            def close(self):
                pass

        monkeypatch.setattr(app, "_qdrant", None)
        monkeypatch.setattr(app, "_qdrant_ready", False)
        monkeypatch.setattr(app, "QDRANT_CLIENT_TIMEOUT", 15)
        monkeypatch.setattr(app, "QdrantClient", _FakeQdrantClient)

        assert app._is_qdrant_ready() is True
        assert captured.get("timeout") == 15


class TestSlowIndexReachability:
    """VAL-FIND-012: paired fail-at-5s / succeed-at-15s scenario.

    Simulated unit-level per the verification decision for issue #588
    criterion 2: the blocking Qdrant query needs ~8 seconds (scaled to
    ~0.8s wall clock via ``_SCALE``) and the wait_for wrapper is kept
    non-binding (QDRANT_QUERY_TIMEOUT=30 scaled) so the CLIENT timeout
    is the constraint actually under test.

    The client-side abort is simulated inside the stubbed blocking call
    exactly as qdrant-client behaves end-to-end: it aborts AT its
    configured timeout when the operation outlasts it (the library
    ceil()s a float timeout onto its REST/gRPC calls and raises a
    timeout error from inside the blocking call), so a slow-but-healthy
    index is reachable if and only if QDRANT_CLIENT_TIMEOUT exceeds the
    operation duration.
    """

    @staticmethod
    def _ready_router(monkeypatch, client_timeout):
        """Wire router_search.search_vector against a slow-but-healthy index.

        The fake Qdrant honors its configured client timeout: an operation
        needing 8 scaled seconds raises the client-level TimeoutError when
        the configured timeout is shorter, and completes otherwise.
        """
        import numpy as np

        # Import app first with stubbed routers (same workaround as
        # tests/unit/test_semantic_svc_unit.py), then the real router_search
        # — avoids the app.py <-> router_search circular import at test time.
        _import_app_with_stubbed_routers()

        import router_search

        class _SlowHealthyQdrant:
            def __init__(self, **kwargs):
                # Configured client timeout arrives in scaled seconds so it
                # competes on equal footing with the scaled op duration.
                self.timeout = kwargs["timeout"]

            def query_points(self, **kwargs):
                needed = 8 * _SCALE  # "8 seconds" (scaled)
                start = time.monotonic()
                while time.monotonic() - start < needed:
                    if time.monotonic() - start > self.timeout:
                        # The client bound fires INSIDE the blocking call —
                        # mirroring qdrant-client's real abort behavior.
                        raise TimeoutError("client timeout fired")
                    time.sleep(0.02)
                return type("_Resp", (), {"points": []})()

        class _FakeModel:
            def encode(self, text, **kwargs):
                return np.array([0.1] * 8)

        monkeypatch.setenv("QDRANT_CLIENT_TIMEOUT", str(client_timeout))
        # Wrapper non-binding (30 scaled seconds) so only the client binds.
        monkeypatch.setattr(router_search, "QDRANT_QUERY_TIMEOUT", 30 * _SCALE)
        monkeypatch.setattr(router_search, "_get_embed_model", lambda: _FakeModel())

        async def _fake_ensure():
            return _SlowHealthyQdrant(
                url="http://qdrant:6333", timeout=client_timeout * _SCALE
            )

        monkeypatch.setattr(router_search, "_ensure_qdrant", _fake_ensure)
        import app

        monkeypatch.setattr(app, "_models_ready", True)
        return router_search

    def test_legacy_5s_client_timeout_fails_the_slow_call(self, monkeypatch):
        """With the legacy hardcoded 5s client timeout, the ~8s call fails.

        This pins the bug: the short client timeout structurally breaks a
        slow-but-healthy index even though the wrapper allows ample time.
        """
        from fastapi import HTTPException
        from models import VectorSearchRequest

        router_search = self._ready_router(monkeypatch, client_timeout=5.0)

        started = time.monotonic()
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                router_search.search_vector(VectorSearchRequest(query="herbs", limit=3))
            )
        assert exc_info.value.status_code == 503
        # The failure came from the client bound (~5 scaled s), not the wrapper
        # (30 scaled s): the call aborted well before the wrapper could fire.
        assert time.monotonic() - started < 20 * _SCALE

    def test_raised_15s_client_timeout_lets_the_slow_call_succeed(self, monkeypatch):
        """With QDRANT_CLIENT_TIMEOUT=15, the identical ~8s call completes."""
        from models import VectorSearchRequest

        router_search = self._ready_router(monkeypatch, client_timeout=15.0)

        started = time.monotonic()
        resp = asyncio.run(
            router_search.search_vector(VectorSearchRequest(query="herbs", limit=3))
        )
        # The call really ran to completion instead of failing early.
        assert time.monotonic() - started >= 8 * _SCALE * 0.9
        assert list(resp.results) == []
