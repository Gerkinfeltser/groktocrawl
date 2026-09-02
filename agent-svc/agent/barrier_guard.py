"""Shared barrier-refusal helper for scrape consumers (#586).

The invariant: barrier/challenge content must NEVER reach the LLM. Every
agent-svc seam that ingests scraper results funnels its flagged-payload
decision through :func:`is_barrier_flagged` so refusal semantics stay
consistent (warned OR block-fail ⇒ refused; clean ⇒ pass-through).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def is_barrier_flagged(result: dict) -> bool:
    """Return True when a scraper result payload is barrier-flagged.

    A payload is flagged when it carries a ``warning`` key (degraded
    content — quality below threshold, low-yield truncation, or an
    interstitial warning) or when its quality assessment reports
    ``checks.block_detected`` in {"warn", "fail"} (challenge/error page
    text survived extraction, ADR-0015/ADR-0016).

    Clean payloads return False. Missing keys are tolerated — anything
    that is not explicitly flagged passes through unchanged.
    """
    if not isinstance(result, dict):
        return False
    if result.get("warning"):
        return True
    return _block_flagged(result)


def is_block_flagged(result: dict) -> bool:
    """Return True only when the block-page gate flagged the payload.

    Narrower than :func:`is_barrier_flagged`: keyed solely on
    ``data.quality.checks.block_detected`` in {"warn", "fail"}. Used by
    surfaces that must keep passing through non-block warnings (#587
    low-yield pass-through) while still refusing challenge interstitials.
    """
    if not isinstance(result, dict):
        return False
    return _block_flagged(result)


def _block_flagged(result: dict) -> bool:
    checks = ((result.get("data") or {}).get("quality") or {}).get("checks") or {}
    return checks.get("block_detected") in ("warn", "fail")


# Challenge-specific content markers for artifacts that lost the scraper's
# ``warning``/``quality`` envelope (only markdown survives rerank reuse).
# Mirrors the challenge/interstitial families of scraper-svc's
# BLOCK_PAGE_PATTERNS; deliberately excludes the generic cookie/maintenance/
# paywall families so legitimate pages mentioning them are not refused here
# (the strict-quote policy still applies: verbatim barrier phrases flag).
_CHALLENGE_CONTENT_MARKERS = (
    "javascript is disabled",
    "please enable javascript",
    "enable javascript to continue",
    "javascript is required",
    "please turn javascript on",
    "a required part of this site could",
    "/_fs-ch-",
    "please verify you are",
    "verify you are a human",
    "checking your browser",
    "attention required",
    "cloudflare-ray-id",
    "ddos-guard",
)


def markdown_is_challenge(markdown: str | None) -> bool:
    """Return True when bare markdown carries challenge-interstitial text.

    Used by seams that receive markdown without the scraper envelope
    (e.g. rerank-reuse artifacts built from bare ``scraper.scrape()`` calls),
    so the #586 invariant holds even when no ``warning``/``quality`` fields
    survive. Checks the leading 4,000 characters, mirroring the quality
    gate's assessment window.
    """
    if not markdown:
        return False
    lowered = markdown[:4000].lower()
    return any(marker in lowered for marker in _CHALLENGE_CONTENT_MARKERS)


def refuse_reason(result: dict) -> str:
    """Human-readable reason string for a flagged payload (for logs/errors)."""
    checks = ((result.get("data") or {}).get("quality") or {}).get("checks") or {}
    return (
        f"warning={result.get('warning')!r} "
        f"block_detected={checks.get('block_detected')!r}"
    )


def log_refusal(url: str, result: dict) -> None:
    """Log that a barrier-flagged scrape was refused at a consumer seam."""
    logger.info(
        "Barrier-flagged content refused for %s (%s) — never fed to the LLM (#586)",
        url,
        refuse_reason(result),
    )
