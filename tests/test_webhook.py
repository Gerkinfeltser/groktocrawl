"""Tests for agent-svc/agent/webhook.py — webhook delivery with retry and signing."""

from unittest.mock import MagicMock, patch

import pytest


class TestSignBody:
    def test_signs_body_correctly(self):
        from agent.webhook import _sign_body

        sig = _sign_body(b'{"event":"completed","id":"123"}', "mysecret")
        assert isinstance(sig, str)
        assert len(sig) == 64  # sha256 hexdigest
        # Deterministic: same input => same output
        assert sig == _sign_body(b'{"event":"completed","id":"123"}', "mysecret")


class TestDeliverWebhook:
    @pytest.mark.asyncio
    async def test_no_webhook_config_does_nothing(self):
        from agent.webhook import deliver_webhook

        # Should not raise
        await deliver_webhook(None, "completed", "job-1")

    @pytest.mark.asyncio
    async def test_no_url_in_config_does_nothing(self):
        from agent.webhook import deliver_webhook

        await deliver_webhook({}, "completed", "job-1")
        await deliver_webhook({"events": ["completed"]}, "completed", "job-1")

    @pytest.mark.asyncio
    async def test_respects_events_filter(self):
        from agent.webhook import deliver_webhook

        with patch("agent.webhook.httpx.AsyncClient") as mock_client:
            cfg = {"url": "https://hook.example.com", "events": ["completed"]}
            await deliver_webhook(cfg, "failed", "job-1", {"error": "bad"})
            mock_client.assert_not_called()  # 'failed' not in events filter

    @pytest.mark.asyncio
    async def test_delivers_successfully(self):
        from agent.webhook import deliver_webhook

        with patch("agent.webhook.httpx.AsyncClient") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 200

            mock_client = MagicMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            async def _post(*a, **kw):
                return mock_resp

            mock_client.post = MagicMock(side_effect=_post)

            await deliver_webhook(
                {"url": "https://hook.example.com"},
                "completed",
                "job-123",
                {"result": "done"},
            )

            mock_client.post.assert_called_once()
            args, kwargs = mock_client.post.call_args
            assert args[0] == "https://hook.example.com"
            assert '"completed"' in kwargs["content"].decode()
            assert '"job-123"' in kwargs["content"].decode()

    @pytest.mark.asyncio
    async def test_adds_signature_when_secret_set(self):
        from agent.webhook import deliver_webhook

        with (
            patch("agent.webhook.httpx.AsyncClient") as mock_client_cls,
            patch("agent.webhook._webhook_settings.webhook_secret", "my-secret"),
        ):
            mock_resp = MagicMock()
            mock_resp.status_code = 200

            mock_client = MagicMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            async def _post(*a, **kw):
                return mock_resp

            mock_client.post = MagicMock(side_effect=_post)

            await deliver_webhook(
                {"url": "https://hook.example.com"},
                "completed",
                "job-1",
            )

            _args, kwargs = mock_client.post.call_args
            assert "X-Webhook-Signature" in kwargs["headers"]
            assert kwargs["headers"]["X-Webhook-Signature"].startswith("sha256=")

    @pytest.mark.asyncio
    async def test_retries_on_5xx(self):
        from agent.webhook import deliver_webhook

        with patch("agent.webhook.httpx.AsyncClient") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 500

            mock_client = MagicMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            async def _post(*a, **kw):
                return mock_resp

            mock_client.post = MagicMock(side_effect=_post)

            await deliver_webhook(
                {"url": "https://hook.example.com"},
                "completed",
                "job-1",
            )
            assert mock_client.post.call_count > 1

    @pytest.mark.asyncio
    async def test_retries_on_timeout(self):
        import httpx
        from agent.webhook import deliver_webhook

        with patch("agent.webhook.httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            async def _post(*a, **kw):
                raise httpx.TimeoutException("timeout")

            mock_client.post = MagicMock(side_effect=_post)

            await deliver_webhook(
                {"url": "https://hook.example.com"},
                "completed",
                "job-1",
            )
            assert mock_client.post.call_count > 1


# ── Webhook idempotency (VAL-CONC-050) ──────────────────────────


class TestWebhookId:
    def test_unique_ids_for_same_job_different_events(self):
        from agent.webhook import _next_webhook_id, _webhook_id_counter

        _webhook_id_counter.clear()

        id1 = _next_webhook_id("job-1", "crawl.started")
        id2 = _next_webhook_id("job-1", "crawl.page-https://a.com")
        assert id1 != id2
        assert id1 == "job-1-crawl.started-1"
        assert id2 == "job-1-crawl.page-https://a.com-1"

    def test_incrementing_ids_for_same_event(self):
        from agent.webhook import _next_webhook_id, _webhook_id_counter

        _webhook_id_counter.clear()

        id1 = _next_webhook_id("job-1", "crawl.page-https://a.com")
        id2 = _next_webhook_id("job-1", "crawl.page-https://a.com")
        assert id1 != id2
        assert id1.endswith("-1")
        assert id2.endswith("-2")

    def test_ids_unique_across_different_jobs(self):
        from agent.webhook import _next_webhook_id, _webhook_id_counter

        _webhook_id_counter.clear()

        id1 = _next_webhook_id("job-1", "crawl.page-https://a.com")
        _webhook_id_counter.clear()
        id2 = _next_webhook_id("job-2", "crawl.page-https://a.com")
        assert id1 != id2

    @pytest.mark.asyncio
    async def test_webhook_delivery_includes_webhook_id(self):
        from agent.webhook import deliver_webhook

        with patch("agent.webhook.httpx.AsyncClient") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 200

            mock_client = MagicMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            async def _post(*a, **kw):
                return mock_resp

            mock_client.post = MagicMock(side_effect=_post)

            await deliver_webhook(
                {"url": "https://hook.example.com"},
                "crawl.page",
                "job-123",
                {"url": "https://example.com/page"},
                webhook_id_key="crawl.page-https://example.com/page",
            )

            _args, kwargs = mock_client.post.call_args
            body = kwargs["content"].decode()
            assert '"webhookId"' in body
            assert '"job-123-crawl.page-https://example.com/page-1"' in body
