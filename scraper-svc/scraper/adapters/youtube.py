"""
YouTube adapter — extracts video transcripts and metadata.

Fallback chain:
  1. youtube_transcript_api — no API key required, fast
  2. yt-dlp subtitle download — heavier dependency, slower
  3. Browser render + DOM extraction — last resort

Metadata sources:
  - oEmbed API (https://www.youtube.com/oembed?format=json) for title,
    author_name, author_url, thumbnail_url
  - Browser DOM parsing for view count, publish date (fallback)
"""

from __future__ import annotations

import logging
import os
import re
from urllib.parse import parse_qs, urlparse

from .base import AdapterContext, AdapterError, AdapterResult, SiteAdapter, adapter

logger = logging.getLogger(__name__)

# ── URL pattern matching ─────────────────────────────────────────

# Matches standard watch URLs, short links, shorts, and embeds.
_YOUTUBE_URL_PATTERNS = [
    re.compile(r"^https?://(?:www\.)?youtube\.com/watch\?v=[\w-]{11}"),
    re.compile(r"^https?://(?:www\.)?youtube\.com/v/[\w-]{11}"),
    re.compile(r"^https?://(?:www\.)?youtube\.com/embed/[\w-]{11}"),
    re.compile(r"^https?://(?:www\.)?youtube\.com/shorts/[\w-]{11}"),
    re.compile(r"^https?://youtu\.be/[\w-]{11}"),
    re.compile(r"^https?://m\.youtube\.com/watch\?v=[\w-]{11}"),
]

# ── Video ID extraction ──────────────────────────────────────────

_VIDEO_ID_RE = re.compile(r"^[\w-]{11}$")


def _extract_video_id(url: str) -> str | None:
    """Extract the 11-character YouTube video ID from any known URL format."""
    parsed = urlparse(url)
    if parsed.hostname and "youtu.be" in parsed.hostname:
        video_id = parsed.path.strip("/")
        return video_id if _VIDEO_ID_RE.match(video_id) else None

    # Standard watch / shorts / embed
    if parsed.hostname and "youtube.com" in parsed.hostname:
        # Try ?v= parameter first
        query = parse_qs(parsed.query)
        if "v" in query:
            video_id = query["v"][0]
            if _VIDEO_ID_RE.match(video_id):
                return video_id
        # Try path-based (shorts, embed, /v/)
        path_parts = parsed.path.strip("/").split("/")
        for part in path_parts:
            if _VIDEO_ID_RE.match(part):
                return part

    return None


# ── oEmbed metadata ──────────────────────────────────────────────


async def _fetch_oembed(video_id: str) -> dict:
    """Fetch video metadata from YouTube's oEmbed endpoint.

    Returns a dict with keys like ``title``, ``author_name``,
    ``author_url``, ``thumbnail_url``, etc.

    Raises ``AdapterError`` on failure.
    """
    import httpx

    oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(oembed_url)
            if resp.status_code == 200:
                return resp.json()
            logger.debug("oEmbed returned %d for video %s", resp.status_code, video_id)
    except Exception as exc:
        logger.debug("oEmbed failed for video %s: %s", video_id, exc)
    return {}


# ── Transcript via youtube_transcript_api ────────────────────────


async def _fetch_transcript(video_id: str) -> str | None:
    """Fetch the video transcript via ``youtube_transcript_api``.

    Runs the sync API in a thread to avoid blocking the event loop.

    Returns the full transcript as a single text block, or ``None``
    if unavailable.
    """
    import asyncio

    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        def _get_transcript():
            api = YouTubeTranscriptApi()
            transcript_list = api.fetch(video_id, languages=["en"])
            return " ".join(item.text for item in transcript_list)

        transcript = await asyncio.to_thread(_get_transcript)
        return transcript if transcript else None
    except ImportError:
        logger.debug("youtube_transcript_api not installed")
        return None
    except Exception as exc:
        logger.debug("youtube_transcript_api failed for %s: %s", video_id, exc)
        return None


# ── Browser fallback ─────────────────────────────────────────────


async def _fetch_via_browser(
    url: str, video_id: str, ctx: AdapterContext
) -> tuple[str, dict] | None:
    """Fallback: render YouTube page in browser, extract text + metadata.

    Returns ``(markdown, metadata)`` or ``None``.
    """
    import httpx

    browser_svc_url = ctx.config.get("BROWSER_SVC_URL", "http://browser-svc:8012")
    session_id = None
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # Create session
            create_resp = await client.post(
                f"{browser_svc_url}/browsers",
                json={"ttl": 60},
            )
            if create_resp.status_code != 200:
                return None
            session_id = create_resp.json().get("id")
            if not session_id:
                return None

            # Navigate
            nav_resp = await client.post(
                f"{browser_svc_url}/browsers/{session_id}/execute",
                json={"action": "navigate", "url": url, "timeout": 45000},
            )
            if not nav_resp.json().get("success"):
                return None

            # Extract page text
            text_resp = await client.post(
                f"{browser_svc_url}/browsers/{session_id}/execute",
                json={
                    "action": "executeScript",
                    "script": (
                        "document.querySelector('#description-inline-expander') "
                        "?.textContent?.trim() || document.body.innerText"
                    ),
                },
            )
            body_text = ""
            if text_resp.json().get("success"):
                body_text = (
                    text_resp.json().get("result", {}).get("script_result", "") or ""
                )

            # Extract metadata from DOM
            meta_resp = await client.post(
                f"{browser_svc_url}/browsers/{session_id}/execute",
                json={
                    "action": "executeScript",
                    "script": (
                        "JSON.stringify({"
                        "title: document.title,"
                        "channel: document.querySelector('#owner #channel-name')?.textContent?.trim() || '',"
                        "views: document.querySelector('.view-count')?.textContent?.trim() || '',"
                        "})"
                    ),
                },
            )
            metadata: dict = {"video_id": video_id}
            if meta_resp.json().get("success"):
                raw = meta_resp.json().get("result", {}).get("script_result", "{}") or "{}"
                import json

                try:
                    dom_meta = json.loads(raw)
                    metadata["title"] = dom_meta.get("title", "")
                    metadata["channel"] = dom_meta.get("channel", "")
                    if dom_meta.get("views"):
                        metadata["views"] = dom_meta["views"]
                except json.JSONDecodeError:
                    pass

            if not body_text:
                return None

            markdown = (
                f"# {metadata.get('title', 'YouTube Video')}\n\n"
                f"{body_text}"
            )
            return markdown, metadata

    except Exception as exc:
        logger.debug("Browser fallback failed for %s: %s", url, exc)
        return None
    finally:
        if session_id:
            try:
                async with httpx.AsyncClient(timeout=5) as c:
                    await c.delete(f"{browser_svc_url}/browsers/{session_id}")
            except Exception:
                pass


# ── Adapter class ────────────────────────────────────────────────


@adapter
class YouTubeAdapter(SiteAdapter):
    """Extract transcripts and metadata from YouTube video URLs."""

    name = "youtube"

    patterns = _YOUTUBE_URL_PATTERNS

    # YouTube adapter should be checked before generic site-wide adapters
    priority = 200

    async def scrape(self, url: str, ctx: AdapterContext) -> AdapterResult:
        video_id = _extract_video_id(url)
        if not video_id:
            raise AdapterError(f"Could not extract video ID from {url}")

        logger.info("YouTube adapter: video_id=%s", video_id)

        # Fetch metadata from oEmbed (fast, lightweight)
        oembed = {}
        try:
            oembed = await ctx.with_timeout(_fetch_oembed(video_id), timeout=8)
        except AdapterError:
            logger.debug("oEmbed timed out for %s", video_id)

        # Build metadata dict
        metadata: dict = {
            "video_id": video_id,
            "title": oembed.get("title", ""),
            "channel": oembed.get("author_name", ""),
            "channel_url": oembed.get("author_url", ""),
            "thumbnail_url": oembed.get("thumbnail_url", ""),
            "source": "youtube-adapter",
        }

        # Fallback 1: youtube_transcript_api
        transcript = None
        try:
            transcript = await ctx.with_timeout(
                _fetch_transcript(video_id), timeout=12
            )
        except AdapterError:
            logger.debug("Transcript fetch timed out for %s", video_id)

        if transcript:
            logger.info(
                "YouTube adapter: transcript hit for %s (%d chars)",
                video_id,
                len(transcript),
            )
            title = oembed.get("title", "YouTube Video")
            author = oembed.get("author_name", "")
            markdown = (
                f"# {title}\n\n"
                f"**Channel:** {author}\n\n"
                f"---\n\n"
                f"## Transcript\n\n{transcript}"
            )
            return AdapterResult(
                success=True,
                markdown=markdown,
                metadata=metadata,
                source="youtube-transcript-api",
                url=url,
            )

        # Fallback 2: browser render
        logger.info("YouTube adapter: trying browser fallback for %s", video_id)
        browser_result = await _fetch_via_browser(url, video_id, ctx)
        if browser_result:
            markdown, dom_meta = browser_result
            metadata.update(dom_meta)
            return AdapterResult(
                success=True,
                markdown=markdown,
                metadata=metadata,
                source="youtube-browser",
                url=url,
            )

        raise AdapterError(
            f"Could not extract content from YouTube video {video_id}"
        )
