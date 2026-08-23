"""
Shared helper utilities for site adapters.

Auto-registration is explicitly skipped for this module in base.py.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def scrape_page(url: str, timeout: float = 15.0) -> str | None:
    """Fetch a URL and extract readable content via the shared pipeline.

    Delegates to ``fetch_quality.html_to_markdown`` so adapters benefit from
    the same readability + low-yield-recovery behavior as the standard tier
    pipeline (issue #587: card-style pages no longer lose their bodies).
    Returns markdown text, or ``None`` on failure.
    """
    try:
        import httpx

        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; GroktoCrawl/0.7.0)"},
        ) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return None

            from ..fetch_quality import html_to_markdown

            html = resp.text
            markdown = html_to_markdown(html)

            if not markdown:
                return None

            from bs4 import BeautifulSoup

            title = BeautifulSoup(html, "html.parser").title
            title_text = title.get_text(strip=True) if title else ""

            return f"# {title_text}\n\n{markdown}" if title_text else markdown

    except Exception as exc:
        logger.debug("Readability fallback failed for %s: %s", url, exc)
        return None
