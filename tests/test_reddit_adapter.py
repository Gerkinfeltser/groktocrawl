"""Unit tests for the Reddit adapter.

Tests focus on URL parsing, JSON response parsing, and markdown
formatting — the pure functions that don't require network access.
Runs directly without Docker:
    python -m pytest tests/test_reddit_adapter.py -v
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scraper-svc"))

from scraper.adapters.reddit import (
    _extract_post_info,
    _build_json_url,
    _format_markdown_body,
    _format_timestamp,
    _format_post_as_markdown,
    _format_comment,
    _format_comments_section,
    _parse_json_response,
)


# ── _extract_post_info ─────────────────────────────────────────


def test_extract_post_info_www():
    """Parse a standard www.reddit.com post URL."""
    url = "https://www.reddit.com/r/python/comments/1az7z0k/hello_world/"
    result = _extract_post_info(url)
    assert result == ("python", "1az7z0k")


def test_extract_post_info_old():
    """Parse an old.reddit.com post URL."""
    url = "https://old.reddit.com/r/python/comments/1az7z0k/hello_world/"
    result = _extract_post_info(url)
    assert result == ("python", "1az7z0k")


def test_extract_post_info_sh():
    """Parse a sh.reddit.com post URL."""
    url = "https://sh.reddit.com/r/python/comments/1az7z0k/hello_world/"
    result = _extract_post_info(url)
    assert result == ("python", "1az7z0k")


def test_extract_post_info_no_trailing_slash():
    """URL without trailing slash should still parse."""
    url = "https://www.reddit.com/r/python/comments/1az7z0k"
    result = _extract_post_info(url)
    assert result == ("python", "1az7z0k")


def test_extract_post_info_invalid_url():
    """Non-post Reddit URL should return None."""
    url = "https://www.reddit.com/r/python/"
    result = _extract_post_info(url)
    assert result is None


def test_extract_post_info_not_reddit():
    """Non-Reddit URL can be parsed by _extract_post_info (path parsing
    is domain-agnostic — domain validation is the adapter's patterns)."""
    url = "https://www.example.com/r/python/comments/1az7z0k/"
    result = _extract_post_info(url)
    # Path parser extracts (subreddit, id) regardless of domain
    assert result == ("python", "1az7z0k")


# ── _build_json_url ────────────────────────────────────────────


def test_build_json_url_appends_suffix():
    """Append .json to a plain URL."""
    url = "https://www.reddit.com/r/python/comments/1az7z0k"
    assert _build_json_url(url) == (
        "https://www.reddit.com/r/python/comments/1az7z0k.json"
    )


def test_build_json_url_trailing_slash():
    """Strip trailing slash before appending .json."""
    url = "https://www.reddit.com/r/python/comments/1az7z0k/"
    assert _build_json_url(url) == (
        "https://www.reddit.com/r/python/comments/1az7z0k.json"
    )


def test_build_json_url_already_json():
    """URL already ending in .json should not double-append."""
    url = "https://www.reddit.com/r/python/comments/1az7z0k.json"
    assert _build_json_url(url) == url


# ── _format_markdown_body ──────────────────────────────────────


def test_format_markdown_body_normal():
    """Normal markdown body passes through."""
    text = "This is a **bold** statement.\n\nAnd a new paragraph."
    assert _format_markdown_body(text) == text


def test_format_markdown_body_empty():
    """Empty body returns empty string."""
    assert _format_markdown_body("") == ""


def test_format_markdown_body_none():
    """None body returns empty string."""
    assert _format_markdown_body(None) == ""


def test_format_markdown_body_deleted():
    """Deleted content is marked with italics."""
    result = _format_markdown_body("[deleted]")
    assert result == "*[deleted]*"


def test_format_markdown_body_removed():
    """Removed content is marked with italics."""
    result = _format_markdown_body("[removed]")
    assert result == "*[removed]*"


# ── _format_timestamp ──────────────────────────────────────────


def test_format_timestamp():
    """Unix timestamp converts to ISO-8601."""
    result = _format_timestamp(1717000000.0)
    assert "T" in result
    assert result.endswith("+00:00") or result.endswith("Z")


# ── _format_post_as_markdown ───────────────────────────────────


def test_format_post_as_markdown_self_post():
    """A self/text post generates proper markdown with metadata."""
    post_data = {
        "title": "Hello World",
        "author": "testuser",
        "subreddit": "python",
        "score": 42,
        "upvote_ratio": 0.91,
        "num_comments": 7,
        "created_utc": 1717000000.0,
        "selftext": "This is the post body.\n\nIt has multiple paragraphs.",
        "permalink": "/r/python/comments/1az7z0k/hello_world/",
        "url": "https://www.reddit.com/r/python/comments/1az7z0k/hello_world/",
        "domain": "self.python",
        "over_18": False,
        "spoiler": False,
        "stickied": False,
    }
    markdown, metadata = _format_post_as_markdown(post_data)
    assert "Hello World" in markdown
    assert "testuser" in markdown
    assert "r/python" in metadata["subreddit"]
    assert metadata["score"] == 42
    assert metadata["upvote_ratio"] == 0.91
    assert "This is the post body" in markdown


def test_format_post_as_markdown_link_post():
    """A link post includes the external URL."""
    post_data = {
        "title": "Cool External Article",
        "author": "testuser",
        "subreddit": "python",
        "score": 100,
        "upvote_ratio": 0.95,
        "num_comments": 15,
        "created_utc": 1717000000.0,
        "selftext": "",
        "permalink": "/r/python/comments/1az7z0k/cool_article/",
        "url": "https://example.com/cool-article",
        "domain": "example.com",
        "over_18": False,
        "spoiler": False,
        "stickied": False,
    }
    markdown, metadata = _format_post_as_markdown(post_data)
    assert "example.com" in markdown or "Cool External Article" in markdown
    assert "Link" in markdown


def test_format_post_as_markdown_nsfw():
    """NSFW posts get marked."""
    post_data = {
        "title": "NSFW Post",
        "author": "testuser",
        "subreddit": "test",
        "score": 10,
        "upvote_ratio": 0.5,
        "num_comments": 0,
        "created_utc": 1717000000.0,
        "selftext": "Content",
        "permalink": "/r/test/comments/abc/",
        "url": "https://www.reddit.com/r/test/comments/abc/",
        "domain": "self.test",
        "over_18": True,
        "spoiler": False,
        "stickied": False,
    }
    markdown, metadata = _format_post_as_markdown(post_data)
    assert "NSFW" in markdown
    assert metadata["over_18"] is True


# ── _format_comment ────────────────────────────────────────────


def test_format_comment_simple():
    """A top-level comment formats correctly."""
    comment_data = {
        "author": "commenter1",
        "body": "This is a great post!",
        "score": 15,
        "created_utc": 1717000100.0,
        "edited": False,
        "depth": 0,
        "replies": "",
    }
    result = _format_comment(comment_data)
    assert "commenter1" in result
    assert "This is a great post!" in result
    assert "👍 15" in result


def test_format_comment_deleted():
    """Deleted comment shows [deleted] marker."""
    comment_data = {
        "author": "[deleted]",
        "body": "[deleted]",
        "score": 1,
        "created_utc": 1717000100.0,
        "edited": False,
        "depth": 0,
        "replies": "",
    }
    result = _format_comment(comment_data)
    assert "[deleted]" in result


# ── _format_comments_section ───────────────────────────────────


def test_format_comments_section_no_comments():
    """Empty comments section returns empty string."""
    assert _format_comments_section(None) == ""
    assert _format_comments_section({}) == ""


def test_format_comments_section_with_comments():
    """Comments listing produces a '## Comments' section."""
    comments_listing = {
        "data": {
            "children": [
                {
                    "kind": "t1",
                    "data": {
                        "author": "user1",
                        "body": "First comment",
                        "score": 10,
                        "created_utc": 1717000100.0,
                        "edited": False,
                        "depth": 0,
                        "replies": "",
                    },
                },
            ],
        },
    }
    result = _format_comments_section(comments_listing)
    assert "## Comments" in result
    assert "user1" in result
    assert "First comment" in result


def test_format_comments_section_more_indicator():
    """'more' children generate a 'more replies hidden' note."""
    comments_listing = {
        "data": {
            "children": [
                {
                    "kind": "more",
                    "data": {"count": 12, "name": "t1_abc", "id": "abc"},
                },
            ],
        },
    }
    result = _format_comments_section(comments_listing)
    assert "more replies hidden" in result
    assert "12" in result


# ── _parse_json_response (with mock data) ──────────────────────


def test_parse_json_response_full():
    """Parse a complete Reddit API response."""
    mock_response = [
        {
            "data": {
                "children": [
                    {
                        "kind": "t3",
                        "data": {
                            "title": "Full Parse Test",
                            "author": "testauthor",
                            "subreddit": "test",
                            "score": 50,
                            "upvote_ratio": 0.88,
                            "num_comments": 3,
                            "created_utc": 1717000000.0,
                            "selftext": "Post body text",
                            "permalink": "/r/test/comments/abc/test/",
                            "url": "https://www.reddit.com/r/test/comments/abc/test/",
                            "domain": "self.test",
                            "over_18": False,
                            "spoiler": False,
                            "stickied": False,
                        },
                    },
                ],
            },
        },
        {
            "data": {
                "children": [
                    {
                        "kind": "t1",
                        "data": {
                            "author": "replyuser",
                            "body": "A comment reply",
                            "score": 5,
                            "created_utc": 1717000100.0,
                            "edited": False,
                            "depth": 0,
                            "replies": "",
                        },
                    },
                ],
            },
        },
    ]
    markdown, metadata = _parse_json_response(mock_response)
    assert "Full Parse Test" in markdown
    assert "Post body text" in markdown
    assert "A comment reply" in markdown
    assert metadata["score"] == 50
    assert metadata["author"] == "testauthor"


def test_parse_json_response_no_comments():
    """Response without comments section still works."""
    mock_response = [
        {
            "data": {
                "children": [
                    {
                        "kind": "t3",
                        "data": {
                            "title": "No Comments",
                            "author": "author1",
                            "subreddit": "test",
                            "score": 1,
                            "upvote_ratio": 1.0,
                            "num_comments": 0,
                            "created_utc": 1717000000.0,
                            "selftext": "Just a post",
                            "permalink": "/r/test/comments/abc/",
                            "url": "https://www.reddit.com/r/test/comments/abc/",
                            "domain": "self.test",
                            "over_18": False,
                            "spoiler": False,
                            "stickied": False,
                        },
                    },
                ],
            },
        },
    ]
    markdown, metadata = _parse_json_response(mock_response)
    assert "No Comments" in markdown
    assert metadata["author"] == "author1"
