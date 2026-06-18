"""Unit tests for llmstxt.py pure functions.

Tests the _extract_description() function directly without needing
a running Docker stack. Run with: python3 -m pytest tests/test_llmstxt_unit.py -v
"""

import os
import sys

# Add the agent-svc directory to the path so we can import llmstxt
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent-svc"))

from agent.llmstxt import _extract_description


def test_ends_at_sentence_boundary():
    """Description should end at a sentence boundary, not mid-word."""
    text = (
        "This is the first sentence of the page content. This second sentence "
        "continues with additional details about the topic being described on this page. "
        "And this third sentence goes even further into the subject matter to ensure "
        "we have enough content to properly evaluate the sentence boundary detection."
    )
    desc = _extract_description(text)
    assert desc.endswith(".") or desc.endswith("!") or desc.endswith("?")
    assert len(desc) >= 100  # Should be substantive
    # Should not end mid-sentence (i.e., the last char before the period should not be a space)
    assert not desc.endswith(" .")


def test_skips_boilerplate():
    """Boilerplate lines (cookie, nav, short lines) should be skipped."""
    text = (
        "This website uses cookies to improve your experience.\n"
        "Navigation\n"
        "Sign in to your account\n"
        "Skip to main content\n"
        "The real page content begins here and provides the actual value "
        "for readers who want to learn about the topic being discussed."
    )
    desc = _extract_description(text)
    assert "cookie" not in desc.lower()
    assert "navigation" not in desc.lower()
    assert "real page content" in desc


def test_skips_short_lines():
    """Very short lines under 30 chars should be filtered out."""
    text = (
        "Home\n"
        "About\n"
        "Pricing\n"
        "Contact\n"
        "The main article content starts here and provides substantial "
        "information about the topic that readers are interested in reading."
    )
    desc = _extract_description(text)
    assert "Home" not in desc
    assert len(desc) >= 50


def test_skips_headings():
    """Headings, images, and blockquotes should not be included in descriptions."""
    text = (
        "# Page Title\n"
        "![image](img.jpg)\n"
        "> A blockquote that should be skipped\n"
        "- A list item that should be skipped when it starts the line\n"
        "The actual paragraph content begins here and provides thorough "
        "information about the page's subject matter for the reader."
    )
    desc = _extract_description(text)
    assert "Page Title" not in desc
    assert "actual paragraph content" in desc


def test_joins_short_candidates():
    """When the first candidate is short, subsequent candidates should be appended."""
    text = (
        "Short line.\n"
        "Second short line with more words.\n"
        "A longer sentence that brings the total description up to a reasonable "
        "length for testing the candidate joining behavior in the extraction function."
    )
    desc = _extract_description(text)
    assert len(desc) >= 50


def test_returns_empty_for_empty_input():
    """Empty input should return empty string."""
    assert _extract_description("") == ""
    assert _extract_description("   ") == ""


def test_fallback_truncation():
    """When no sentence boundary is found, text should be truncated with ellipsis."""
    # Create text with no sentence-ending punctuation
    text = "This is a very long string of text that has no sentence boundaries " * 20
    desc = _extract_description(text)
    if len(desc) >= 300:
        assert desc.endswith("..."), (
            f"Should end with ellipsis when truncated, got: {desc[-20:]}"
        )


def test_multi_sentence_content():
    """Multi-sentence content should include complete first sentence at minimum."""
    text = (
        "This is the opening statement of the page. Here is an additional "
        "sentence that provides supplementary details. And this is a third "
        "sentence that rounds out the introductory paragraph content nicely."
    )
    desc = _extract_description(text)
    # Should include at least the first full sentence
    assert "opening statement" in desc
    # Should end with a sentence-ending punctuation
    assert desc.rstrip()[-1] in ".!?"
