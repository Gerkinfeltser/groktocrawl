"""Tests for agent-svc/agent/auth.py — API key authentication."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException


class TestVerifyApiKey:
    @pytest.mark.asyncio
    async def test_allows_when_auth_disabled(self):
        from agent.auth import verify_api_key

        request = MagicMock()
        request.headers = {}

        with patch("agent.auth.AUTH_ENABLED", False):
            result = await verify_api_key(request)
            assert result is None

    @pytest.mark.asyncio
    async def test_allows_valid_bearer_token(self):
        from agent.auth import verify_api_key

        request = MagicMock()
        request.headers = {"Authorization": "Bearer sk-test-key-12345"}

        with (
            patch("agent.auth.AUTH_ENABLED", True),
            patch("agent.auth.API_KEY", "sk-test-key-12345"),
        ):
            result = await verify_api_key(request)
            assert result is None

    @pytest.mark.asyncio
    async def test_allows_valid_x_api_key_header(self):
        from agent.auth import verify_api_key

        request = MagicMock()
        request.headers = {"X-API-Key": "sk-another-key"}

        with (
            patch("agent.auth.AUTH_ENABLED", True),
            patch("agent.auth.API_KEY", "sk-another-key"),
        ):
            result = await verify_api_key(request)
            assert result is None

    @pytest.mark.asyncio
    async def test_rejects_invalid_key(self):
        from agent.auth import verify_api_key

        request = MagicMock()
        request.headers = {"Authorization": "Bearer wrong-key"}

        with (
            patch("agent.auth.AUTH_ENABLED", True),
            patch("agent.auth.API_KEY", "sk-real-key"),
        ):
            with pytest.raises(HTTPException) as exc:
                await verify_api_key(request)
            assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_rejects_missing_key(self):
        from agent.auth import verify_api_key

        request = MagicMock()
        request.headers = {}

        with (
            patch("agent.auth.AUTH_ENABLED", True),
            patch("agent.auth.API_KEY", "sk-real-key"),
        ):
            with pytest.raises(HTTPException) as exc:
                await verify_api_key(request)
            assert exc.value.status_code == 403

    def test_constants_on_import(self):
        """Verify constants are defined at module level."""
        import agent.auth

        assert hasattr(agent.auth, "AUTH_ENABLED")
        assert hasattr(agent.auth, "API_KEY")
        assert hasattr(agent.auth, "SECURITY_WARNING_HEADER")
        assert hasattr(agent.auth, "SECURITY_WARNING_BODY")
