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
