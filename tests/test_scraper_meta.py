"""Tests for scraper-svc/scraper/meta.py — lightweight meta tag extraction."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestFetchMetaTags:
    @pytest.mark.asyncio
    async def test_extracts_title_and_description(self):
        from scraper.meta import fetch_meta_tags

        html = """<html><head>
            <title>Test Page</title>
            <meta name="description" content="A test page description">
            <meta property="og:description" content="OG description">
        </head></html>"""

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = html

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp

        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__.return_value = mock_client
            result = await fetch_meta_tags("https://example.com")

        assert result["title"] == "Test Page"
        assert result["description"] == "A test page description"
        assert result["og_description"] == "OG description"

    @pytest.mark.asyncio
    async def test_missing_meta_returns_none(self):
        from scraper.meta import fetch_meta_tags

        html = "<html><head></head><body><p>No meta here</p></body></html>"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = html

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp

        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__.return_value = mock_client
            result = await fetch_meta_tags("https://example.com")

        assert result["title"] is None
        assert result["description"] is None
        assert result["og_description"] is None

    @pytest.mark.asyncio
    async def test_non_200_returns_empty(self):
        from scraper.meta import fetch_meta_tags

        mock_resp = MagicMock()
        mock_resp.status_code = 404

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp

        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__.return_value = mock_client
            result = await fetch_meta_tags("https://example.com/missing")

        assert result["title"] is None

    @pytest.mark.asyncio
    async def test_handles_connection_error(self):
        import httpx
        from scraper.meta import fetch_meta_tags

        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")

        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__.return_value = mock_client
            result = await fetch_meta_tags("https://example.com")

        assert result["title"] is None

    @pytest.mark.asyncio
    async def test_strips_whitespace_from_values(self):
        from scraper.meta import fetch_meta_tags

        html = """<html><head>
            <title>  Spaced Title  </title>
            <meta name="description" content="  Spaced description  ">
        </head></html>"""

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = html

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp

        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__.return_value = mock_client
            result = await fetch_meta_tags("https://example.com")

        assert result["title"] == "Spaced Title"
        assert result["description"] == "Spaced description"
