"""Legacy-cache migration tests for native-int ``source_html_size`` (#587 hardening).

PR #593 stored the Tier 2 HTML-fallback source size as a string; the
hardening change stores it natively as an int and consumes it
arithmetically in the quality assessment. Scrape results persisted to
Valkey BEFORE the upgrade still carry the string form, so the cache read
path must normalize legacy entries instead of letting the volume gate
raise TypeError on every cache hit during the migration window.
"""

from __future__ import annotations

import json

import pytest

CACHED_URL = "https://example.test/hardware"


class _FakeCacheClient:
    def __init__(self, payloads: dict[str, bytes]):
        self._payloads = payloads

    async def get(self, key: str):
        return self._payloads.get(key)


@pytest.fixture()
def seeded_cache(monkeypatch):
    """Serve one canned payload from an otherwise-absent Valkey client."""
    from scraper import cache as cache_mod

    holder: dict = {"client": None}

    async def _fake_get_client():
        return holder["client"]

    monkeypatch.setattr(cache_mod, "_get_cache_client", _fake_get_client)

    def _seed(payload: dict):
        key = cache_mod._scrape_cache_key(CACHED_URL)
        holder["client"] = _FakeCacheClient({key: json.dumps(payload).encode()})
        return payload

    return _seed


@pytest.mark.asyncio
async def test_check_cache_normalizes_legacy_string_source_html_size(seeded_cache):
    """Pre-upgrade cache entries carrying str sizes come back as int."""
    seeded_cache(
        {
            "markdown": "# Intro\n\nCached body.",
            "source": "content-negotiation",
            "url": CACHED_URL,
            "source_html_size": "94978",
        }
    )
    from scraper.cache import _check_cache

    cached = await _check_cache(CACHED_URL)
    assert cached is not None
    assert cached["source_html_size"] == 94978
    assert isinstance(cached["source_html_size"], int)


@pytest.mark.asyncio
async def test_check_cache_leaves_native_int_untouched(seeded_cache):
    """Entries already written with native ints pass through unchanged."""
    seeded_cache(
        {
            "markdown": "# Intro\n\nCached body.",
            "source": "content-negotiation",
            "url": CACHED_URL,
            "source_html_size": 94978,
        }
    )
    from scraper.cache import _check_cache

    cached = await _check_cache(CACHED_URL)
    assert cached is not None
    assert isinstance(cached["source_html_size"], int)
    assert cached["source_html_size"] == 94978


@pytest.mark.asyncio
async def test_add_quality_volume_gate_works_on_normalized_cache_hit(seeded_cache):
    """End-to-end: a legacy hit re-assessed by _add_quality must not TypeError."""
    thin_markdown = "# Intro\n\n" + "Short intro paragraph only. " * 15
    seeded_cache(
        {
            "markdown": thin_markdown,
            "url": CACHED_URL,
            "source_html_size": "94978",  # legacy string form
        }
    )
    from scraper.cache import _check_cache
    from scraper.fetch_quality import _add_quality

    cached = await _check_cache(CACHED_URL)
    enriched = _add_quality(cached)
    assert enriched["quality"]["checks"]["volume"] == "fail"
    assert enriched.get("warning")
