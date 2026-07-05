"""URL scoring, ranking, and video-platform domain filtering."""

import logging

from common.url import extract_domain

logger = logging.getLogger(__name__)

# ── Video-platform URL filtering ────────────────────────────────
# Domains whose primary content is audio-visual (video, audio,
# short-form) rather than text.  Transcripts extracted from these
# platforms are low-signal for factual text queries and pollute the
# LLM context.  They are deprioritised — only used as a fallback
# when text sources can't fill the ``min_sources`` quota.
_VIDEO_PLATFORM_DOMAINS: frozenset[str] = frozenset(
    {
        "youtube.com",
        "youtu.be",
        "m.youtube.com",
        "tiktok.com",
        "www.tiktok.com",
        "vm.tiktok.com",
        "instagram.com",
        "www.instagram.com",
    }
)


def _is_video_platform_url(url: str) -> bool:
    """Return True when *url* belongs to a video-first platform."""
    hostname = extract_domain(url).lower()
    # Strip leading "www." for comparison (the frozenset includes
    # both canonicalised and www-prefixed variants).
    return (
        hostname in _VIDEO_PLATFORM_DOMAINS
        or hostname.removeprefix("www.") in _VIDEO_PLATFORM_DOMAINS
    )


# ── URL scoring and pre-filtering ────────────────────────────────
# Each URL discovered by search is scored for expected extractability
# before scraping. Low-value URLs (login, checkout, index pages) are
# excluded or deprioritised to maximise the scrape budget.


def _score_url(url: str) -> int:
    """Score a URL's expected extractability. Higher = more likely to yield content."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    path = parsed.path.lower()

    # ── Exclude immediately ────────────────────────────────────
    skip_paths = (
        "/login",
        "/signup",
        "/cart",
        "/checkout",
        "/terms",
        "/privacy",
        "/tag/",
    )
    if any(p in path for p in skip_paths):
        return -9999

    # ── Deprioritise tracking-param URLs ───────────────────────
    if "utm_" in parsed.query:
        return -5000

    score = 0

    # ── Domain authority boosts ────────────────────────────────
    if hostname.endswith(".edu"):
        score += 2
    if "wikipedia.org" in hostname:
        score += 2
    if "github.com" in hostname:
        score += 2
    if "youtube.com" in hostname or "youtu.be" in hostname:
        score += 2

    # Known high-quality domains (gardening, health, academic, news)
    _high_quality = frozenset(
        {
            "provenwinners.com",
            "logees.com",
            "almanac.com",
            "nhs.uk",
            "mayoclinic.org",
            "webmd.com",
            "sciencedirect.com",
            "scholar.google.com",
            "acm.org",
            "ieee.org",
            "arstechnica.com",
            "reuters.com",
            "apnews.com",
            "npr.org",
        }
    )
    if any(d in hostname for d in _high_quality):
        score += 2
    if hostname.endswith(".gov") or hostname.endswith(".org"):
        score += 1

    # Established blogs / developer sites
    _known_blogs = frozenset({"medium.com", "dev.to", "smashingmagazine.com"})
    if any(d in hostname for d in _known_blogs):
        score += 1

    # ── Penalise social media / aggregators ────────────────────
    _low_quality = frozenset(
        {
            "reddit.com",
            "pinterest.com",
            "facebook.com",
            "twitter.com",
            "x.com",
            "linkedin.com",
            "tumblr.com",
            "quora.com",
            "stackexchange.com",
        }
    )
    if any(d in hostname for d in _low_quality):
        score -= 1

    # ── Prefer specific article pages over index/root ──────────
    if path.count("/") >= 2:
        score += 1
    elif path in ("", "/"):
        score -= 1

    return score


def _filter_and_rank_urls(urls: list[str], max_urls: int = 20) -> list[str]:
    """Score, sort, filter URLs and return the top N."""
    scored = [(url, _score_url(url)) for url in urls]
    # Exclude skip-score URLs
    scored = [(url, s) for url, s in scored if s > -1000]
    # Sort by score descending
    scored.sort(key=lambda x: x[1], reverse=True)
    return [url for url, _ in scored[:max_urls]]
