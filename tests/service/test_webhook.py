"""Tests for agent-svc/agent/webhook.py — webhook delivery with retry and signing.

Covers:
- UUID v4 webhookId format (VAL-PARITY-011)
- Metadata echo (VAL-PARITY-009)
- ``type`` field in payload body
- ``success`` / ``error`` fields
- ``data`` array format for per-page events
- Events filter
- HMAC signature (VAL-PARITY-010)
- Retry logic
- Graceful failure on unreachable URL (VAL-PARITY-032)
"""

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _public_dns(monkeypatch):
    """Make DNS resolution hermetic: every hostname resolves to a public IP.

    Webhook destination validation (issue #469) resolves hostnames via
    ``common.url._resolve_to_ips_with_transient``. Real lookups would be
    slow and nondeterministic in CI, so tests stub them to a public
    address.
    """
    from ipaddress import ip_address

    monkeypatch.setattr(
        "common.url._resolve_to_ips_with_transient",
        lambda hostname: ([ip_address("93.184.216.34")], False),
    )


class TestSignBody:
    def test_signs_body_correctly(self):
        from agent.webhook import _sign_body

        sig = _sign_body(b'{"type":"completed","id":"123"}', "mysecret")
        assert isinstance(sig, str)
        assert len(sig) == 64  # sha256 hexdigest
        # Deterministic: same input => same output
        assert sig == _sign_body(b'{"type":"completed","id":"123"}', "mysecret")


class TestWebhookIdUuid:
    """Test that webhookId uses UUID v4 format (VAL-PARITY-011)."""

    def test_generates_valid_uuid_v4(self):
        from agent.webhook import _next_webhook_id

        whid = _next_webhook_id()
        # Should be a valid UUID v4 string
        parsed = uuid.UUID(whid)
        assert parsed.version == 4

    def test_each_call_returns_unique_value(self):
        from agent.webhook import _next_webhook_id

        ids = {_next_webhook_id() for _ in range(100)}
        assert len(ids) == 100  # All unique
        for whid in ids:
            assert uuid.UUID(whid).version == 4


class TestDeliverWebhook:
    @pytest.mark.asyncio
    async def test_no_webhook_config_does_nothing(self):
        from agent.webhook import deliver_webhook

        # Should not raise
        await deliver_webhook(None, "crawl.started", "job-1")

    @pytest.mark.asyncio
    async def test_no_url_in_config_does_nothing(self):
        from agent.webhook import deliver_webhook

        await deliver_webhook({}, "crawl.started", "job-1")
        await deliver_webhook({"events": ["crawl.completed"]}, "crawl.started", "job-1")

    @pytest.mark.asyncio
    async def test_respects_events_filter(self):
        """Events filter: if events=['crawl.completed'], only crawl.completed fires."""
        from agent.webhook import deliver_webhook

        with patch("agent.webhook.httpx.AsyncClient") as mock_client:
            cfg = {"url": "https://hook.example.com", "events": ["crawl.completed"]}
            await deliver_webhook(cfg, "crawl.started", "job-1", data=[])
            mock_client.assert_not_called()  # 'crawl.started' not in events filter

    @pytest.mark.asyncio
    async def test_respects_events_filter_allows_matching(self):
        """Events filter: matching event should be delivered."""
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

            cfg = {"url": "https://hook.example.com", "events": ["crawl.completed"]}
            await deliver_webhook(cfg, "crawl.completed", "job-1", data=[])

            mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_payload_has_type_field(self):
        """Payload uses ``type`` field instead of ``event`` (VAL-PARITY-005)."""
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
                "crawl.started",
                "job-123",
                data=[],
            )

            _args, kwargs = mock_client.post.call_args
            body = json.loads(kwargs["content"].decode())
            assert body["type"] == "crawl.started"
            assert "event" not in body  # Should use 'type' not 'event'

    @pytest.mark.asyncio
    async def test_payload_includes_success_and_error(self):
        """Payload includes success and error fields (VAL-PARITY-005)."""
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
                "crawl.started",
                "job-123",
                data=[],
            )

            _args, kwargs = mock_client.post.call_args
            body = json.loads(kwargs["content"].decode())
            assert body["success"] is True
            assert body["error"] is None

    @pytest.mark.asyncio
    async def test_payload_includes_error_for_failure_events(self):
        """Payload includes error message for failure events."""
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
                "crawl.failed",
                "job-123",
                data=[],
                success=False,
                error="Something went wrong",
            )

            _args, kwargs = mock_client.post.call_args
            body = json.loads(kwargs["content"].decode())
            assert body["success"] is False
            assert body["error"] == "Something went wrong"

    @pytest.mark.asyncio
    async def test_payload_data_is_list(self):
        """Data field is always a list (empty [] for lifecycle, [page] for per-page)."""
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

            # Lifecycle event: data is empty list
            await deliver_webhook(
                {"url": "https://hook.example.com"},
                "crawl.started",
                "job-123",
                data=[],
            )

            _args, kwargs = mock_client.post.call_args
            body = json.loads(kwargs["content"].decode())
            assert isinstance(body["data"], list)
            assert body["data"] == []

    @pytest.mark.asyncio
    async def test_payload_data_with_page_list(self):
        """Per-page webhook: data is a list with one page document."""
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

            page_data = {
                "url": "https://example.com/page1",
                "markdown": "# Page 1",
                "metadata": {"title": "Page 1", "status_code": 200},
            }
            await deliver_webhook(
                {"url": "https://hook.example.com"},
                "crawl.page",
                "job-123",
                data=[page_data],
            )

            _args, kwargs = mock_client.post.call_args
            body = json.loads(kwargs["content"].decode())
            assert isinstance(body["data"], list)
            assert len(body["data"]) == 1
            assert body["data"][0]["url"] == "https://example.com/page1"
            assert body["data"][0]["markdown"] == "# Page 1"

    @pytest.mark.asyncio
    async def test_metadata_echoed_back(self):
        """Metadata from webhook_config is echoed verbatim (VAL-PARITY-009)."""
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

            metadata = {"customer_id": "123", "campaign": "Q4"}
            cfg = {
                "url": "https://hook.example.com",
                "metadata": metadata,
            }
            await deliver_webhook(cfg, "crawl.started", "job-123", data=[])

            _args, kwargs = mock_client.post.call_args
            body = json.loads(kwargs["content"].decode())
            assert body["metadata"] == metadata

    @pytest.mark.asyncio
    async def test_metadata_is_empty_dict_when_not_set(self):
        """Metadata defaults to empty dict when not provided in webhook_config."""
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

            cfg = {"url": "https://hook.example.com"}
            await deliver_webhook(cfg, "crawl.started", "job-123", data=[])

            _args, kwargs = mock_client.post.call_args
            body = json.loads(kwargs["content"].decode())
            assert body["metadata"] == {}

    @pytest.mark.asyncio
    async def test_metadata_echoed_on_all_event_types(self):
        """Metadata is echoed on all event types (started, page, completed)."""
        from agent.webhook import deliver_webhook

        metadata = {"session": "test-123"}
        cfg = {"url": "https://hook.example.com", "metadata": metadata}

        captured_bodies = []

        with patch("agent.webhook.httpx.AsyncClient") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 200

            mock_client = MagicMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            async def _post(*a, **post_kw):
                captured_bodies.append(json.loads(post_kw["content"].decode()))
                return mock_resp

            mock_client.post = MagicMock(side_effect=_post)

            # Fire all three event types
            await deliver_webhook(cfg, "crawl.started", "job-1", data=[])
            await deliver_webhook(
                cfg, "crawl.page", "job-1", data=[{"url": "https://example.com/p1"}]
            )
            await deliver_webhook(cfg, "crawl.completed", "job-1", data=[])

            assert len(captured_bodies) == 3
            for body in captured_bodies:
                assert body["metadata"] == metadata

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
                "crawl.completed",
                "job-123",
                data=[],
            )

            mock_client.post.assert_called_once()
            args, kwargs = mock_client.post.call_args
            assert args[0] == "https://hook.example.com"
            body = json.loads(kwargs["content"].decode())
            assert body["type"] == "crawl.completed"
            assert body["id"] == "job-123"

    @pytest.mark.asyncio
    async def test_adds_signature_when_secret_set(self):
        """HMAC signature header present when WEBHOOK_SECRET is set (VAL-PARITY-010)."""
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
                "crawl.started",
                "job-1",
                data=[],
            )

            _args, kwargs = mock_client.post.call_args
            assert "X-Webhook-Signature" in kwargs["headers"]
            assert kwargs["headers"]["X-Webhook-Signature"].startswith("sha256=")

    @pytest.mark.asyncio
    async def test_signature_is_verifiable(self):
        """Signature can be verified by computing HMAC-SHA256 of body."""
        from agent.webhook import _sign_body, deliver_webhook

        secret = "test-secret-123"

        with (
            patch("agent.webhook.httpx.AsyncClient") as mock_client_cls,
            patch("agent.webhook._webhook_settings.webhook_secret", secret),
        ):
            mock_resp = MagicMock()
            mock_resp.status_code = 200

            mock_client = MagicMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            captured_body = None
            captured_signature = None

            async def _post(*a, **kw):
                nonlocal captured_body, captured_signature
                captured_body = kw["content"]
                captured_signature = kw["headers"]["X-Webhook-Signature"]
                return mock_resp

            mock_client.post = MagicMock(side_effect=_post)

            await deliver_webhook(
                {"url": "https://hook.example.com"},
                "crawl.started",
                "job-1",
                data=[],
            )

            # Verify the signature matches
            expected_sig = _sign_body(captured_body, secret)
            assert captured_signature == f"sha256={expected_sig}"

    @pytest.mark.asyncio
    async def test_retries_on_5xx(self):
        """Retries on server errors (VAL-PARITY-031)."""
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
                "crawl.started",
                "job-1",
                data=[],
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
                "crawl.started",
                "job-1",
                data=[],
            )
            assert mock_client.post.call_count > 1

    @pytest.mark.asyncio
    async def test_delivery_failure_logged_does_not_raise(self):
        """Webhook delivery failure is logged but does not raise (VAL-PARITY-032)."""
        from agent.webhook import deliver_webhook

        with patch("agent.webhook.httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            async def _post(*a, **kw):
                raise Exception("Connection refused")

            mock_client.post = MagicMock(side_effect=_post)

            # Should not raise
            await deliver_webhook(
                {"url": "https://hook.example.com"},
                "crawl.started",
                "job-1",
                data=[],
            )

    @pytest.mark.asyncio
    async def test_payload_includes_webhook_id(self):
        """Each webhook delivery includes unique webhookId."""
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
                data=[{"url": "https://example.com/page"}],
            )

            _args, kwargs = mock_client.post.call_args
            body = json.loads(kwargs["content"].decode())
            assert "webhookId" in body
            # Verify UUID v4 format
            parsed = uuid.UUID(body["webhookId"])
            assert parsed.version == 4

    @pytest.mark.asyncio
    async def test_multiple_webhooks_have_unique_ids(self):
        """Multiple webhooks from same job have unique webhookIds."""
        from agent.webhook import deliver_webhook

        webhook_ids = []
        cfg = {"url": "https://hook.example.com"}

        with patch("agent.webhook.httpx.AsyncClient") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 200

            mock_client = MagicMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            async def _post(*a, **post_kw):
                body = json.loads(post_kw["content"].decode())
                webhook_ids.append(body["webhookId"])
                return mock_resp

            mock_client.post = MagicMock(side_effect=_post)

            await deliver_webhook(cfg, "crawl.started", "job-1", data=[])
            await deliver_webhook(
                cfg, "crawl.page", "job-1", data=[{"url": "https://example.com/p1"}]
            )
            await deliver_webhook(
                cfg, "crawl.page", "job-1", data=[{"url": "https://example.com/p2"}]
            )
            await deliver_webhook(cfg, "crawl.completed", "job-1", data=[])

            # All webhookIds are unique
            assert len(set(webhook_ids)) == 4
            # All are valid UUID v4
            for whid in webhook_ids:
                parsed = uuid.UUID(whid)
                assert parsed.version == 4

    @pytest.mark.asyncio
    async def test_non_crawl_events_still_work(self):
        """Non-crawl events (completed, failed) still use the new payload format."""
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
                "job-1",
                data={"pages": [{"url": "https://example.com"}]},
            )

            _args, kwargs = mock_client.post.call_args
            body = json.loads(kwargs["content"].decode())
            assert body["type"] == "completed"
            assert body["success"] is True
            assert body["error"] is None
            assert body["data"] == {"pages": [{"url": "https://example.com"}]}


class TestWebhookSsrfGuard:
    """SSRF guard for webhook destinations (issue #469)."""

    def _mock_client_cls(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        mock_client = MagicMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client_cls = MagicMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        async def _post(*a, **kw):
            return mock_resp

        mock_client.post = MagicMock(side_effect=_post)
        return mock_client_cls, mock_client

    @pytest.mark.asyncio
    async def test_rejects_loopback_destination(self):
        """A loopback webhook destination is never posted to."""
        from agent.webhook import deliver_webhook

        with patch("agent.webhook.httpx.AsyncClient") as mock_client_cls:
            await deliver_webhook(
                {"url": "http://127.0.0.1:8080/hook"},
                "crawl.completed",
                "job-1",
                data=[],
            )
            mock_client_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_rfc1918_destination(self):
        """A private RFC 1918 webhook destination is never posted to."""
        from agent.webhook import deliver_webhook

        with patch("agent.webhook.httpx.AsyncClient") as mock_client_cls:
            await deliver_webhook(
                {"url": "http://10.0.0.5/hook"},
                "crawl.completed",
                "job-1",
                data=[],
            )
            mock_client_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_link_local_destination(self):
        """A link-local webhook destination is never posted to."""
        from agent.webhook import deliver_webhook

        with patch("agent.webhook.httpx.AsyncClient") as mock_client_cls:
            await deliver_webhook(
                {"url": "http://169.254.169.254/latest/meta-data/"},
                "crawl.completed",
                "job-1",
                data=[],
            )
            mock_client_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_ipv4_mapped_loopback_destination(self):
        """An IPv4-mapped IPv6 loopback destination is never posted to."""
        from agent.webhook import deliver_webhook

        with patch("agent.webhook.httpx.AsyncClient") as mock_client_cls:
            await deliver_webhook(
                {"url": "http://[::ffff:127.0.0.1]:8080/hook"},
                "crawl.completed",
                "job-1",
                data=[],
            )
            mock_client_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_non_http_scheme(self):
        """Non-HTTP(S) webhook destinations are never posted to."""
        from agent.webhook import deliver_webhook

        with patch("agent.webhook.httpx.AsyncClient") as mock_client_cls:
            await deliver_webhook(
                {"url": "ftp://example.com/hook"},
                "crawl.completed",
                "job-1",
                data=[],
            )
            mock_client_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_hostname_resolving_to_private_ip(self, monkeypatch):
        """A public-looking hostname resolving to a private IP is rejected."""
        from ipaddress import ip_address

        from agent.webhook import deliver_webhook

        monkeypatch.setattr(
            "common.url._resolve_to_ips_with_transient",
            lambda hostname: ([ip_address("192.168.1.99")], False),
        )
        with patch("agent.webhook.httpx.AsyncClient") as mock_client_cls:
            await deliver_webhook(
                {"url": "https://public.example.com/hook"},
                "crawl.completed",
                "job-1",
                data=[],
            )
            mock_client_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_fails_closed_on_dns_failure(self, monkeypatch):
        """An unresolvable webhook hostname is rejected (fail closed)."""
        from agent.webhook import deliver_webhook

        monkeypatch.setattr(
            "common.url._resolve_to_ips_with_transient", lambda hostname: ([], False)
        )
        with patch("agent.webhook.httpx.AsyncClient") as mock_client_cls:
            await deliver_webhook(
                {"url": "https://unresolvable.example.invalid/hook"},
                "crawl.completed",
                "job-1",
                data=[],
            )
            mock_client_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_transient_dns_failure_retries_validation(self, monkeypatch):
        """A transient DNS failure retries instead of dropping the webhook."""
        from agent.webhook import deliver_webhook

        calls = {"n": 0}

        def _flaky_resolve(hostname):
            calls["n"] += 1
            if calls["n"] == 1:
                # First attempt: transient resolver failure
                return ([], True)
            from ipaddress import ip_address

            return ([ip_address("93.184.216.34")], False)

        monkeypatch.setattr("common.url._resolve_to_ips_with_transient", _flaky_resolve)

        mock_client_cls, mock_client = self._mock_client_cls()
        with patch("agent.webhook.httpx.AsyncClient", mock_client_cls):
            await deliver_webhook(
                {"url": "https://hook.example.com"},
                "crawl.completed",
                "job-1",
                data=[],
            )
        # Transient failure was retried; the second attempt delivered
        assert calls["n"] >= 2
        mock_client.post.assert_called_once()
        assert mock_client.post.call_args.args[0] == "https://hook.example.com"

    @pytest.mark.asyncio
    async def test_persistent_transient_dns_failure_gives_up_after_retries(
        self, monkeypatch
    ):
        """A persistent transient DNS failure retries, then gives up silently."""
        from agent.webhook import deliver_webhook

        calls = {"n": 0}

        def _always_fail(hostname):
            calls["n"] += 1
            return ([], True)

        monkeypatch.setattr("common.url._resolve_to_ips_with_transient", _always_fail)

        with patch("agent.webhook.httpx.AsyncClient") as mock_client_cls:
            await deliver_webhook(
                {"url": "https://hook.example.com"},
                "crawl.completed",
                "job-1",
                data=[],
            )
        # One validation per attempt; no HTTP request was ever made
        assert calls["n"] == 3
        mock_client_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_public_ip_literal_still_delivers(self):
        """A public IP-literal webhook destination still delivers."""
        from agent.webhook import deliver_webhook

        mock_client_cls, mock_client = self._mock_client_cls()
        with patch("agent.webhook.httpx.AsyncClient", mock_client_cls):
            await deliver_webhook(
                {"url": "http://93.184.216.34/hook"},
                "crawl.completed",
                "job-1",
                data=[],
            )
        mock_client.post.assert_called_once()
        args, _kwargs = mock_client.post.call_args
        assert args[0] == "http://93.184.216.34/hook"

    @pytest.mark.asyncio
    async def test_redirects_disabled(self):
        """Redirects are disabled on the webhook HTTP client."""
        from agent.webhook import deliver_webhook

        mock_client_cls, _ = self._mock_client_cls()
        with patch("agent.webhook.httpx.AsyncClient", mock_client_cls):
            await deliver_webhook(
                {"url": "https://hook.example.com"},
                "crawl.completed",
                "job-1",
                data=[],
            )
        kwargs = mock_client_cls.call_args.kwargs
        assert kwargs["follow_redirects"] is False
