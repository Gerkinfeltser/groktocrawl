"""
Reddit adapter — extracts posts and comment threads via the official JSON API.

Fallback chain:
  1. Reddit JSON API — append ``.json`` to any Reddit URL, no auth required
  2. Browser render + DOM extraction — last resort for blocked IPs

The Reddit JSON API returns structured data without authentication for
public content.  Rate-limited (~60 req/min without OAuth credentials).
Optional ``ADAPTER_REDDIT_CLIENT_ID`` and ``ADAPTER_REDDIT_CLIENT_SECRET``
for higher limits via app-only OAuth.

URL patterns:
  - ``https://www.reddit.com/r/{subreddit}/comments/{id}/{slug}``
  - ``https://old.reddit.com/r/{subreddit}/comments/{id}/{slug}``
"""

from __future__ import annotations

import json
import logging
import re
from urllib.parse import urlparse

import httpx

from .base import AdapterContext, AdapterError, AdapterResult, SiteAdapter, adapter

logger = logging.getLogger(__name__)

# ── URL pattern matching ─────────────────────────────────────────

_REDDIT_URL_PATTERNS = [
    # www.reddit.com
    re.compile(r"^https?://(?:www\.)?reddit\.com/r/[^/]+/comments/[^/]+"),
    # old.reddit.com
    re.compile(r"^https?://old\.reddit\.com/r/[^/]+/comments/[^/]+"),
    # sh.reddit.com (newer compact UI)
    re.compile(r"^https?://sh\.reddit\.com/r/[^/]+/comments/[^/]+"),
]

# ── URL parsing ──────────────────────────────────────────────────


def _extract_post_info(url: str) -> tuple[str, str] | None:
    """Extract ``(subreddit, post_id)`` from a Reddit post URL.

    Accepts URLs like::

        https://www.reddit.com/r/python/comments/1az7z0k/...
        https://old.reddit.com/r/python/comments/1az7z0k/...

    Returns ``(subreddit, post_id)`` or ``None`` if the URL path
    doesn't match the expected pattern.
    """
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    parts = path.split("/")
    # Expected: r/<subreddit>/comments/<id>/<slug>
    if len(parts) >= 4 and parts[0] == "r" and parts[2] == "comments":
        return parts[1], parts[3]
    return None


# ── Reddit JSON API helpers ──────────────────────────────────────


def _build_json_url(url: str) -> str:
    """Append ``.json`` to a Reddit URL.

    Handles URLs with or without trailing slashes.
    """
    url = url.rstrip("/")
    # Remove any existing .json suffix
    if url.endswith(".json"):
        return url
    return url + ".json"


async def _fetch_json(
    url: str, ctx: AdapterContext, timeout: float = 20.0
) -> list | None:
    """Fetch and parse the JSON response for a Reddit post URL.

    Returns the parsed JSON array ``[post_listing, comments_listing]``
    or ``None`` on failure.
    """
    json_url = _build_json_url(url)
    # Use a descriptive User-Agent per Reddit API rules
    user_agent = "groktocrawl/1.0 (reddit-adapter; by /u/groktopus)"

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(
                json_url,
                headers={
                    "User-Agent": user_agent,
                    "Accept": "application/json",
                },
            )
            if resp.status_code == 200:
                return resp.json()
            logger.debug(
                "Reddit JSON API returned %d for %s",
                resp.status_code,
                url,
            )
    except Exception as exc:
        logger.debug("Reddit JSON API fetch failed for %s: %s", url, exc)
    return None


# ── Formatting helpers ───────────────────────────────────────────


def _format_timestamp(created_utc: float) -> str:
    """Format a Unix timestamp to ISO-8601."""
    from datetime import datetime, timezone

    dt = datetime.fromtimestamp(created_utc, tz=timezone.utc)
    return dt.isoformat()


def _format_markdown_body(text: str | None) -> str:
    """Convert Reddit markdown-ish text to clean markdown.

    Reddit's API returns raw markdown text in the ``selftext`` and
    ``body`` fields.  We leave it as-is since it's already markdown.
    Empty or ``[deleted]`` / ``[removed]`` texts are handled gracefully.
    """
    if not text:
        return ""
    # Handle deleted/removed content
    stripped = text.strip()
    if stripped in ("[deleted]", "[removed]"):
        return f"*{stripped}*"
    return stripped


def _format_post_as_markdown(post_data: dict) -> tuple[str, dict]:
    """Format a Reddit post as markdown with metadata.

    Returns ``(markdown, metadata_dict)``.
    """
    title = post_data.get("title", "Untitled")
    author = post_data.get("author", "[deleted]")
    subreddit = post_data.get("subreddit", "")
    score = post_data.get("score", 0)
    upvote_ratio = post_data.get("upvote_ratio", 0.0)
    num_comments = post_data.get("num_comments", 0)
    created_utc = post_data.get("created_utc", 0)
    selftext = _format_markdown_body(post_data.get("selftext", ""))
    permalink = post_data.get("permalink", "")
    post_url = post_data.get("url", "")
    domain = post_data.get("domain", "")
    over_18 = post_data.get("over_18", False)
    spoiler = post_data.get("spoiler", False)
    stickied = post_data.get("stickied", False)

    # Build metadata
    metadata = {
        "title": title,
        "author": author,
        "subreddit": f"r/{subreddit}",
        "score": score,
        "upvote_ratio": upvote_ratio,
        "num_comments": num_comments,
        "created_utc": created_utc,
        "timestamp": _format_timestamp(created_utc),
        "permalink": f"https://www.reddit.com{permalink}" if permalink else "",
        "domain": domain,
        "over_18": over_18,
        "spoiler": spoiler,
        "stickied": stickied,
        "source": "reddit-adapter",
    }

    # If the post is a link post (links to external content), include the URL
    link_post = ""
    if post_url and domain != f"self.{subreddit}":
        link_post = f"\n🔗 **Link:** [{post_url}]({post_url})\n\n"

    # Build markdown body
    lines = [
        f"# {title}",
        f"**Posted by u/{author}** in **r/{subreddit}** — {_format_timestamp(created_utc)}",
        f"👍 {score}  ({upvote_ratio * 100:.0f}% upvoted)  💬 {num_comments} comments",
    ]

    if over_18:
        lines.insert(1, "**🔞 NSFW**")
    if spoiler:
        lines.insert(1, "**⚠️ SPOILER**")
    if stickied:
        lines.insert(1, "**📌 Stickied post**")

    markdown = "\n\n".join(lines)
    if link_post:
        markdown += link_post + "\n---\n"
    if selftext:
        markdown += "\n\n---\n\n" + selftext

    return markdown, metadata


def _format_comment(comment_data: dict, depth: int = 0) -> str:
    """Format a single comment as indented markdown.

    Recursively handles nested replies.
    """
    author = comment_data.get("author", "[deleted]")
    body = _format_markdown_body(comment_data.get("body", ""))
    score = comment_data.get("score", 0)
    created_utc = comment_data.get("created_utc", 0)
    timestamp = _format_timestamp(created_utc)
    edited = comment_data.get("edited", False)

    indent = "  " * depth
    lines = [
        f"{indent}**u/{author}** — {timestamp}  (👍 {score})",
    ]
    if edited:
        lines[0] = lines[0].rstrip() + " *(edited)*"

    if body:
        # Indent each paragraph of the body
        for paragraph in body.split("\n"):
            lines.append(f"{indent}{paragraph}")
    else:
        lines.append(f"{indent}*[deleted]*")

    lines.append("")  # blank line separator

    # Handle nested replies
    replies = comment_data.get("replies")
    if isinstance(replies, dict):
        # replies is a Listing object
        reply_children = (
            replies.get("data", {}).get("children", [])
        )
        for reply_child in reply_children:
            if reply_child.get("kind") == "t1":  # comment
                lines.append(
                    _format_comment(reply_child["data"], depth + 1)
                )
    elif isinstance(replies, str) and replies:
        # Empty string means no replies
        pass

    return "\n".join(lines)


def _format_comments_section(
    comments_listing: dict | None,
) -> str:
    """Format the comments listing into a markdown section.

    Returns an empty string if there are no comments.
    """
    if not comments_listing:
        return ""

    children = comments_listing.get("data", {}).get("children", [])
    if not children:
        return ""

    parts = ["---\n## Comments\n"]
    for child in children:
        kind = child.get("kind")
        data = child.get("data", {})

        if kind == "t1":  # Comment
            parts.append(_format_comment(data, depth=0))
        elif kind == "more":  # "Load more" placeholder
            count = data.get("count", 0)
            if count:
                parts.append(f"\n*... {count} more replies hidden ...*\n")

    return "\n".join(parts)


def _parse_json_response(
    data: list,
) -> tuple[str, dict]:
    """Parse the Reddit JSON API response into markdown + metadata.

    The response is an array with two elements:
    ``[post_listing, comments_listing]``.
    """
    if not data or len(data) < 1:
        raise AdapterError("Empty Reddit API response")

    post_listing = data[0]
    comments_listing = data[1] if len(data) > 1 else None

    # Extract post data
    post_children = (
        post_listing.get("data", {}).get("children", [])
    )
    if not post_children:
        raise AdapterError("No post found in Reddit API response")

    post_data = post_children[0].get("data", {})

    # Format post
    markdown, metadata = _format_post_as_markdown(post_data)

    # Format comments
    comments_md = _format_comments_section(comments_listing)
    if comments_md:
        markdown += "\n\n" + comments_md

    return markdown, metadata


# ── Browser fallback ─────────────────────────────────────────────


async def _fetch_via_browser(
    url: str, ctx: AdapterContext,
) -> tuple[str, dict] | None:
    """Fallback: render Reddit page in browser, extract text + metadata.

    Returns ``(markdown, metadata)`` or ``None``.
    """
    browser_svc_url = ctx.config.get(
        "BROWSER_SVC_URL", "http://browser-svc:8012"
    )
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

            # Navigate to old.reddit.com for simpler HTML
            old_url = url.replace("www.reddit.com", "old.reddit.com")
            nav_resp = await client.post(
                f"{browser_svc_url}/browsers/{session_id}/execute",
                json={
                    "action": "navigate",
                    "url": old_url,
                    "timeout": 45000,
                },
            )
            if not nav_resp.json().get("success"):
                # Try original URL
                nav_resp = await client.post(
                    f"{browser_svc_url}/browsers/{session_id}/execute",
                    json={
                        "action": "navigate",
                        "url": url,
                        "timeout": 45000,
                    },
                )
                if not nav_resp.json().get("success"):
                    return None

            # Extract page text
            text_resp = await client.post(
                f"{browser_svc_url}/browsers/{session_id}/execute",
                json={
                    "action": "executeScript",
                    "script": "document.body.innerText",
                },
            )
            body_text = ""
            if text_resp.json().get("success"):
                body_text = (
                    text_resp.json()
                    .get("result", {})
                    .get("script_result", "")
                    or ""
                )

            # Extract metadata from DOM
            meta_resp = await client.post(
                f"{browser_svc_url}/browsers/{session_id}/execute",
                json={
                    "action": "executeScript",
                    "script": (
                        "JSON.stringify({"
                        "title: document.title,"
                        "})"
                    ),
                },
            )
            metadata: dict = {"source": "reddit-adapter"}
            if meta_resp.json().get("success"):
                raw = (
                    meta_resp.json()
                    .get("result", {})
                    .get("script_result", "{}")
                    or "{}"
                )
                try:
                    metadata.update(json.loads(raw))
                except json.JSONDecodeError:
                    pass

            if not body_text:
                return None

            markdown = (
                f"# {metadata.get('title', 'Reddit Post')}\n\n{body_text}"
            )
            return markdown, metadata

    except Exception as exc:
        logger.debug("Browser fallback failed for %s: %s", url, exc)
        return None
    finally:
        if session_id:
            try:
                async with httpx.AsyncClient(timeout=5) as c:
                    await c.delete(
                        f"{browser_svc_url}/browsers/{session_id}"
                    )
            except Exception:
                pass


# ── Adapter class ────────────────────────────────────────────────


@adapter
class RedditAdapter(SiteAdapter):
    """Extract posts and comment threads from Reddit URLs."""

    name = "reddit"

    patterns = _REDDIT_URL_PATTERNS

    priority = 200

    async def scrape(self, url: str, ctx: AdapterContext) -> AdapterResult:
        # Parse URL
        result = _extract_post_info(url)
        if not result:
            raise AdapterError(f"Could not parse Reddit URL: {url}")
        subreddit, post_id = result
        logger.info("Reddit adapter: r/%s post %s", subreddit, post_id)

        # Fallback 1: Reddit JSON API (append .json)
        try:
            data = await ctx.with_timeout(
                _fetch_json(url, ctx), timeout=20
            )
            if data:
                markdown, metadata = _parse_json_response(data)
                logger.info(
                    "Reddit adapter: JSON API hit for %s (%d chars)",
                    url,
                    len(markdown),
                )
                return AdapterResult(
                    success=True,
                    markdown=markdown,
                    metadata=metadata,
                    source="reddit-json-api",
                    url=url,
                )
        except AdapterError:
            logger.debug("Reddit JSON API failed for %s", url)

        # Fallback 2: browser render
        logger.info(
            "Reddit adapter: trying browser fallback for %s", url
        )
        browser_result = await _fetch_via_browser(url, ctx)
        if browser_result:
            markdown, dom_meta = browser_result
            return AdapterResult(
                success=True,
                markdown=markdown,
                metadata=dom_meta,
                source="reddit-browser",
                url=url,
            )

        raise AdapterError(
            f"Could not extract content from Reddit URL: {url}"
        )
