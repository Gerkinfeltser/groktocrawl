"""Unit tests for the ``lightweight_only`` scrape short-circuit (issue #530).

This lives under ``tests/unit`` because it imports ``scraper.fetch``, which
transitively imports ``curl_cffi`` (only available in the Fast Tests lane).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


def _patch_common(monkeypatch, *, shielded: bool) -> None:
    import scraper.fetch as fetch

    monkeypatch.setattr(
        fetch._settings, "scraper_private_url_allowlist", "example.test"
    )
    monkeypatch.setattr(fetch, "get_registry", lambda: MagicMock(_entries={}))
    monkeypatch.setattr(fetch.curl_requests, "AsyncSession", lambda **_kw: _Session())

    async def allow(*_args, **_kwargs):
        return True, None

    async def no_cache(_url):
        return None

    async def no_set_cache(*_args, **_kwargs):
        return None

    async def enrich(result, _url):
        return result

    async def probe(_url, _client):
        return {
            "shielded": shielded,
            "redirect_url": "https://example.test",
            "is_binary": False,
            "is_empty": False,
            "status_code": 200,
            "content_type": "text/html",
        }

    monkeypatch.setattr(fetch, "_politeness_check_and_delay", allow)
    monkeypatch.setattr(fetch, "_check_cache", no_cache)
    monkeypatch.setattr(fetch, "_set_cache", no_set_cache)
    monkeypatch.setattr(fetch, "_enrich_with_politeness", enrich)
    monkeypatch.setattr(fetch, "_head_probe", probe)


@pytest.mark.asyncio
async def test_lightweight_only_short_circuits_before_browser(monkeypatch):
    """With no lightweight content, lightweight_only never enters the browser tier."""
    import scraper.fetch as fetch

    _patch_common(monkeypatch, shielded=True)

    async def unexpected_browser(_url):
        raise AssertionError("browser tier must not be reached")

    monkeypatch.setattr(fetch, "fetch_via_playwright", unexpected_browser)
    monkeypatch.setattr(fetch, "fetch_via_flaresolverr", unexpected_browser)

    result = await fetch.smart_scrape(
        "https://example.test/page", lightweight_only=True
    )
    assert result["error"]
    assert "lightweight tiers" in result["error"]


@pytest.mark.asyncio
async def test_lightweight_only_returns_best_effort_without_browser(monkeypatch):
    """Lightweight-only returns low-quality best effort rather than degrading to browser."""
    import scraper.fetch as fetch

    _patch_common(monkeypatch, shielded=False)

    async def content_negotiation(_url, _client):
        return {"markdown": "thin content", "source": "content-negotiation"}

    async def degrade(result, _tier_label, best_effort):
        best_effort.append(result)
        return None

    async def unexpected_browser(_url):
        raise AssertionError("browser tier must not be reached")

    monkeypatch.setattr(fetch, "fetch_via_content_negotiation", content_negotiation)
    monkeypatch.setattr(fetch, "_maybe_degrade", degrade)
    monkeypatch.setattr(fetch, "fetch_via_playwright", unexpected_browser)
    monkeypatch.setattr(fetch, "fetch_via_flaresolverr", unexpected_browser)

    result = await fetch.smart_scrape(
        "https://example.test/page", lightweight_only=True
    )
    assert result["markdown"] == "thin content"
    assert result.get("warning")
