"""SSRF guard tests for monitor webhook delivery (issue #469).

Both monitor paths (scrape and search) post to a user-supplied ``webhook``
URL when a change is detected. These tests verify that private/restricted
destinations are rejected before any HTTP request is attempted, and that
public destinations still deliver with redirects disabled.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _public_dns(monkeypatch):
    """Make DNS resolution hermetic: every hostname resolves to a public IP."""
    from ipaddress import ip_address

    monkeypatch.setattr(
        "common.url._resolve_to_ips_with_transient",
        lambda hostname: ([ip_address("93.184.216.34")], False),
    )


def _fake_redis():
    r = MagicMock()
    r.sismember.return_value = False
    r.sadd.return_value = 1
    r.expire.return_value = True
    return r


def _scrape_response():
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "success": True,
        "data": {"markdown": "NEW CONTENT"},
    }
    return resp


def _changed_config(webhook_url: str) -> dict:
    return {
        "url": "https://example.com/page",
        "webhook": webhook_url,
        "last_content": "OLD CONTENT",
        "scraper_url": "http://scraper-svc:8001",
    }


class TestScrapeMonitorWebhookSsrf:
    @pytest.mark.asyncio
    async def test_private_webhook_destination_not_posted(self):
        """A loopback monitor webhook is skipped; the check still succeeds."""
        from agent.monitor import check_monitor

        config = _changed_config("http://127.0.0.1:8080/hook")

        with (
            patch("agent.monitor._get_redis", return_value=_fake_redis()),
            patch("agent.monitor.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = MagicMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.post = AsyncMock(return_value=_scrape_response())

            result = await check_monitor("m1", config)

        assert result["changed"] is True
        # Only the scrape request was made — the webhook was rejected
        mock_client.post.assert_awaited_once()
        call_args = mock_client.post.await_args.args[0]
        assert call_args.endswith("/scrape")

    @pytest.mark.asyncio
    async def test_rfc1918_webhook_destination_not_posted(self):
        """A private RFC 1918 monitor webhook is skipped."""
        from agent.monitor import check_monitor

        config = _changed_config("http://192.168.1.10/hook")

        with (
            patch("agent.monitor._get_redis", return_value=_fake_redis()),
            patch("agent.monitor.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = MagicMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.post = AsyncMock(return_value=_scrape_response())

            result = await check_monitor("m1", config)

        assert result["changed"] is True
        mock_client.post.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_public_webhook_destination_delivers_with_redirects_disabled(self):
        """A public monitor webhook still delivers; redirects are disabled."""
        from agent.monitor import check_monitor

        config = _changed_config("https://hook.example.com/changed")

        with (
            patch("agent.monitor._get_redis", return_value=_fake_redis()),
            patch("agent.monitor.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = MagicMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.post = AsyncMock(return_value=_scrape_response())

            result = await check_monitor("m1", config)

        assert result["changed"] is True
        # Scrape + webhook delivery
        assert mock_client.post.await_count == 2
        webhook_call = mock_client.post.await_args
        assert webhook_call.args[0] == "https://hook.example.com/changed"
        # Webhook client (second AsyncClient construction) disables redirects
        calls = mock_client_cls.call_args_list
        assert len(calls) == 2
        assert calls[1].kwargs["follow_redirects"] is False

    @pytest.mark.asyncio
    async def test_transient_dns_retried_then_delivers(self, monkeypatch):
        """Transient DNS is retried by the shared validator before delivery."""
        from agent.monitor import check_monitor

        # Skip the exponential backoff so the test does not sleep
        monkeypatch.setattr("agent.webhook.asyncio.sleep", AsyncMock())

        calls = {"n": 0}

        def _flaky_resolve(hostname):
            calls["n"] += 1
            if calls["n"] == 1:
                return ([], True)  # transient failure on first attempt
            from ipaddress import ip_address

            return ([ip_address("93.184.216.34")], False)

        monkeypatch.setattr("common.url._resolve_to_ips_with_transient", _flaky_resolve)

        config = _changed_config("https://hook.example.com/changed")
        with (
            patch("agent.monitor._get_redis", return_value=_fake_redis()),
            patch("agent.monitor.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = MagicMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.post = AsyncMock(return_value=_scrape_response())

            result = await check_monitor("m1", config)

        assert result["changed"] is True
        # DNS was retried, then the webhook was delivered (scrape + webhook)
        assert calls["n"] >= 2
        assert mock_client.post.await_count == 2
        assert mock_client.post.await_args.args[0] == "https://hook.example.com/changed"

    @pytest.mark.asyncio
    async def test_persistent_transient_dns_gives_up_without_posting(
        self,
        monkeypatch,
    ):
        """Persistent transient DNS never posts; the check still succeeds."""
        from agent.monitor import check_monitor

        monkeypatch.setattr("agent.webhook.asyncio.sleep", AsyncMock())
        monkeypatch.setattr(
            "common.url._resolve_to_ips_with_transient", lambda hostname: ([], True)
        )

        config = _changed_config("https://hook.example.com/changed")
        with (
            patch("agent.monitor._get_redis", return_value=_fake_redis()),
            patch("agent.monitor.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = MagicMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.post = AsyncMock(return_value=_scrape_response())

            result = await check_monitor("m1", config)

        assert result["changed"] is True
        # Only the scrape POST happened; the webhook validation gave up
        mock_client.post.assert_awaited_once()
        call_args = mock_client.post.await_args.args[0]
        assert call_args.endswith("/scrape")


class TestSearchMonitorWebhookSsrf:
    def _search_results(self):
        return [
            {
                "url": "https://news.example.com/article/1",
                "title": "Example article",
                "description": "A new result.",
            }
        ]

    @pytest.mark.asyncio
    async def test_private_webhook_destination_not_posted(self):
        """A private search-monitor webhook is skipped."""
        from agent.monitor import run_search_monitor

        config = {
            "monitor_type": "search",
            "search_config": {"query": "breaking news", "numResults": 10},
            "webhook": "http://10.0.0.5/hook",
        }

        with (
            patch("agent.monitor._get_redis", return_value=_fake_redis()),
            patch("agent.monitor.httpx.AsyncClient") as mock_client_cls,
            patch("agent.searxng_client.SearXNGClient") as mock_searxng_cls,
        ):
            mock_searxng = MagicMock()
            mock_searxng.search = AsyncMock(
                return_value=(self._search_results(), "healthy")
            )
            mock_searxng.close = AsyncMock()
            mock_searxng_cls.return_value = mock_searxng

            result = await run_search_monitor("m1", config)

        assert result["changed"] is True
        assert result["new_count"] == 1
        # No webhook HTTP request was attempted at all
        mock_client_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_public_webhook_destination_delivers_with_redirects_disabled(self):
        """A public search-monitor webhook still delivers; redirects disabled."""
        from agent.monitor import run_search_monitor

        config = {
            "monitor_type": "search",
            "search_config": {"query": "breaking news", "numResults": 10},
            "webhook": "https://hook.example.com/changed",
        }

        with (
            patch("agent.monitor._get_redis", return_value=_fake_redis()),
            patch("agent.monitor.httpx.AsyncClient") as mock_client_cls,
            patch("agent.searxng_client.SearXNGClient") as mock_searxng_cls,
        ):
            mock_client = MagicMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.post = AsyncMock(return_value=MagicMock())

            mock_searxng = MagicMock()
            mock_searxng.search = AsyncMock(
                return_value=(self._search_results(), "healthy")
            )
            mock_searxng.close = AsyncMock()
            mock_searxng_cls.return_value = mock_searxng

            result = await run_search_monitor("m1", config)

        assert result["changed"] is True
        mock_client.post.assert_awaited_once()
        assert mock_client.post.await_args.args[0] == "https://hook.example.com/changed"
        assert mock_client_cls.call_args.kwargs["follow_redirects"] is False

    @pytest.mark.asyncio
    async def test_no_new_results_skips_webhook(self):
        """Search monitor with no new results does not fire the webhook."""
        from agent.monitor import run_search_monitor

        config = {
            "monitor_type": "search",
            "search_config": {"query": "breaking news", "numResults": 10},
            "webhook": "https://hook.example.com/changed",
        }

        with (
            patch("agent.monitor.httpx.AsyncClient") as mock_client_cls,
            patch("agent.searxng_client.SearXNGClient") as mock_searxng_cls,
        ):
            mock_searxng = MagicMock()
            # All URLs already seen → no new results
            r = _fake_redis()
            r.sismember.return_value = True
            mock_searxng.search = AsyncMock(return_value=([], "healthy"))
            mock_searxng.close = AsyncMock()
            mock_searxng_cls.return_value = mock_searxng

            with patch("agent.monitor._get_redis", return_value=r):
                result = await run_search_monitor("m1", config)

        assert result["changed"] is False
        mock_client_cls.assert_not_called()
