"""
Shared helper utilities for site adapters.

Auto-registration is explicitly skipped for this module in base.py.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def scrape_page(url: str, timeout: float = 15.0) -> str | None:
    """Fetch a URL and extract readable content with readability-lxml.

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

            from bs4 import BeautifulSoup
            from readability import Document

            html = resp.text
            doc = Document(html)
            title = doc.title()
            summary_html = doc.summary()

            soup = BeautifulSoup(summary_html, "html.parser")
            text = soup.get_text(separator="\n", strip=True)

            if not text:
                return None

            return f"# {title}\n\n{text}" if title else text

    except Exception as exc:
        logger.debug("Readability fallback failed for %s: %s", url, exc)
        return None
