"""Structured metadata extraction from raw HTML.

Extracts JSON-LD, OpenGraph tags, Twitter Card tags, and standard meta tags
from HTML that is already in memory during the scrape pipeline. Pure parsing —
no additional HTTP fetches required.

Usage:
    metadata = extract_all_metadata(html)
    # Returns: {"json_ld": [...], "og": {...}, "twitter": {...}, "meta": {...}}
"""

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Known JSON-LD @type values that indicate useful structured data
USEFUL_LD_TYPES = frozenset({
    "Article", "NewsArticle", "TechArticle", "ScholarlyArticle",
    "BlogPosting", "SocialMediaPosting",
    "Product", "Recipe", "Event", "Movie", "TVSeries", "MusicRecording",
    "Person", "Organization", "LocalBusiness",
    "FAQPage", "QAPage", "HowTo",
    "WebSite", "WebPage", "CollectionPage",
    "BreadcrumbList", "ItemList",
    "Review", "AggregateRating",
    "Dataset", "SoftwareApplication", "SoftwareSourceCode",
    "VideoObject", "AudioObject", "ImageObject",
    "Book", "Course", "CreativeWork",
    "JobPosting", "MedicalWebPage",
})


def extract_json_ld(html: str) -> list[dict]:
    """Parse all ``<script type="application/ld+json">`` blocks from HTML.

    Returns a list of parsed JSON objects. Invalid JSON blocks are silently
    skipped. Filters to known schema.org types when possible, but includes
    unknown types as well.
    """
    if not html:
        return []

    results: list[dict] = []
    # Match <script type="application/ld+json">...</script>
    # Uses a non-greedy match to handle multiple blocks
    pattern = re.compile(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        re.IGNORECASE | re.DOTALL,
    )

    for match in pattern.finditer(html):
        raw = match.group(1).strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            logger.debug("Skipping invalid JSON-LD block")
            continue

        # Normalize: if it's a @graph or @set, unwrap to list
        if isinstance(parsed, dict):
            graph = parsed.get("@graph")
            if isinstance(graph, list):
                for item in graph:
                    if isinstance(item, dict):
                        results.append(item)
                continue
            # Single item with @context
            if parsed.get("@type") or parsed.get("name") or parsed.get("url"):
                results.append(parsed)
                continue
        elif isinstance(parsed, list):
            results.extend(item for item in parsed if isinstance(item, dict))

    return results


def extract_og_tags(html: str) -> dict[str, Any]:
    """Parse OpenGraph ``<meta property="og:*">`` tags from HTML.

    Returns a dict mapping og property names to values. Multi-valued
    properties (e.g., ``og:image`` with multiple entries) are collected
    into lists.
    """
    if not html:
        return {}

    og: dict[str, Any] = {}
    pattern = re.compile(
        r'<meta[^>]+property=["\'](og:[^"\']+)["\'][^>]*content=["\']([^"\']*)["\'][^>]*/?>',
        re.IGNORECASE,
    )

    for match in pattern.finditer(html):
        prop = match.group(1).strip()
        value = match.group(2).strip()
        if not value:
            continue
        # Collect multi-valued properties into lists
        key = prop.removeprefix("og:")
        if key in og:
            existing = og[key]
            if isinstance(existing, list):
                existing.append(value)
            else:
                og[key] = [existing, value]
        else:
            og[key] = value

    return og


def extract_twitter_tags(html: str) -> dict[str, Any]:
    """Parse Twitter Card ``<meta name="twitter:*">`` tags from HTML.

    Returns a dict mapping twitter property names to values.
    """
    if not html:
        return {}

    twitter: dict[str, Any] = {}
    pattern = re.compile(
        r'<meta[^>]+name=["\'](twitter:[^"\']+)["\'][^>]*content=["\']([^"\']*)["\'][^>]*/?>',
        re.IGNORECASE,
    )

    for match in pattern.finditer(html):
        prop = match.group(1).strip()
        value = match.group(2).strip()
        if not value:
            continue
        key = prop.removeprefix("twitter:")
        twitter[key] = value

    return twitter


def extract_standard_meta(html: str) -> dict[str, Any]:
    """Extract standard meta tags from HTML.

    Returns a dict with keys:
        - description: <meta name="description">
        - canonical: <link rel="canonical">
        - author: <meta name="author">
        - publication_date: <meta name="article:published_time"> or
          <meta property="article:published_time">
        - language: <html lang=""> or <meta http-equiv="content-language">
        - viewport: <meta name="viewport">
        - robots: <meta name="robots">
        - generator: <meta name="generator">
    """
    if not html:
        return {}

    meta: dict[str, Any] = {}

    # Canonical URL (from <link rel="canonical">)
    canonical_match = re.search(
        r'<link[^>]+rel=["\']canonical["\'][^>]*href=["\']([^"\']*)["\'][^>]*/?>',
        html, re.IGNORECASE,
    )
    if canonical_match:
        meta["canonical"] = canonical_match.group(1).strip()

    # <html lang=""> attribute
    lang_match = re.search(r'<html[^>]+lang=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if lang_match:
        meta["language"] = lang_match.group(1).strip().split("-")[0]

    # Content-language meta
    if "language" not in meta:
        cl_match = re.search(
            r'<meta[^>]+http-equiv=["\']content-language["\'][^>]*content=["\']([^"\']+)["\']',
            html, re.IGNORECASE,
        )
        if cl_match:
            meta["language"] = cl_match.group(1).strip()

    # Named meta tags
    named_meta_patterns: list[tuple[str, str]] = [
        ("description", r'<meta[^>]+name=["\']description["\'][^>]*content=["\']([^"\']*)["\']'),
        ("author", r'<meta[^>]+name=["\']author["\'][^>]*content=["\']([^"\']*)["\']'),
        ("viewport", r'<meta[^>]+name=["\']viewport["\'][^>]*content=["\']([^"\']*)["\']'),
        ("robots", r'<meta[^>]+name=["\']robots["\'][^>]*content=["\']([^"\']*)["\']'),
        ("generator", r'<meta[^>]+name=["\']generator["\'][^>]*content=["\']([^"\']*)["\']'),
        ("publication_date", r'<meta[^>]+(?:name|property)=["\']article:published_time["\'][^>]*content=["\']([^"\']*)["\']'),
        ("modified_date", r'<meta[^>]+(?:name|property)=["\']article:modified_time["\'][^>]*content=["\']([^"\']*)["\']'),
        ("keywords", r'<meta[^>]+name=["\']keywords["\'][^>]*content=["\']([^"\']*)["\']'),
    ]

    for key, pattern in named_meta_patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match and match.group(1).strip():
            meta[key] = match.group(1).strip()

    return meta


def extract_all_metadata(html: str) -> dict[str, Any]:
    """Run all metadata extractors on raw HTML.

    Args:
        html: Raw HTML string from the page.

    Returns:
        Dict with keys ``json_ld``, ``og``, ``twitter``, ``meta``.
        Each key is always present (may be empty dict/list).
    """
    if not html or not html.strip():
        return {"json_ld": [], "og": {}, "twitter": {}, "meta": {}}

    return {
        "json_ld": extract_json_ld(html),
        "og": extract_og_tags(html),
        "twitter": extract_twitter_tags(html),
        "meta": extract_standard_meta(html),
    }
