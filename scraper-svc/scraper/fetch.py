"""Three-tier fetch strategy for turning URLs into clean markdown.

Tier 1: /llms.txt — entire site as markdown, one GET.
Tier 2: Accept: text/markdown — per-page markdown via content negotiation.
Tier 3: Playwright render + readability extraction (heavyweight).
"""

import logging
import os
import re
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# ── Binary content-type detection ──────────────────────────────
BINARY_TYPE_PREFIXES = ("image/", "audio/", "video/")
BINARY_TYPE_EXACT = {
    "application/pdf",
    "application/epub+zip",
    "application/zip",
    "application/gzip",
    "application/x-tar",
    "application/x-rar-compressed",
    "application/x-7z-compressed",
    "application/vnd.android.package-archive",
    "application/vnd.openxmlformats-officedocument",
}


def _is_binary_content_type(content_type: str) -> bool:
    """Check if a Content-Type indicates binary content that shouldn't be parsed as HTML."""
    if not content_type:
        return False
    ct = content_type.lower().split(";")[0].strip()
    if ct in BINARY_TYPE_EXACT:
        return True
    for prefix in BINARY_TYPE_PREFIXES:
        if ct.startswith(prefix):
            return True
    return False


def _derive_filename(url: str, content_type: str) -> str:
    """Derive a sensible filename from URL path + Content-Type."""
    parsed = urlparse(url)
    path = parsed.path or parsed.query or "download"
    basename = path.rstrip("/").split("/")[-1]
    if basename and "." in basename:
        return basename
    ext_map = {
        "application/pdf": ".pdf",
        "application/epub+zip": ".epub",
        "application/zip": ".zip",
        "application/gzip": ".gz",
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/svg+xml": ".svg",
        "text/csv": ".csv",
        "application/json": ".json",
    }
    ext = ext_map.get(content_type.split(";")[0].strip(), "")
    return f"{basename}{ext}" if basename else f"download{ext}"


def _make_download_payload(url: str, content: bytes, content_type: str) -> dict:
    """Build a download payload dict for binary content."""
    return {
        "markdown": "",
        "source": "binary",
        "url": url,
        "download": {
            "filename": _derive_filename(url, content_type),
            "content_type": content_type,
            "size": len(content),
            "data_url": None,
        },
    }


# ── Suspicious content detection (for LLM recovery trigger) ────
CLOUDFLARE_INDICATORS = [
    "Just a moment",
    "Checking your browser",
    "DDoS protection by",
    "cf-browser-verification",
    "challenge-platform",
]


def _looks_suspicious(content: str) -> bool:
    """Heuristic: does the page content look like a challenge/error page?"""
    if not content:
        return True
    if len(content) < 100:
        return True
    for indicator in CLOUDFLARE_INDICATORS:
        if indicator.lower() in content.lower():
            return True
    return False


def _looks_like_markdown(text: str) -> bool:
    """Heuristic: does the response look like markdown vs HTML?"""
    if not text:
        return False
    # If the first non-whitespace character isn't '<', it's probably not HTML
    stripped = text.strip()
    if not stripped:
        return False
    # Check for markdown indicators: headings, lists, code fences, links
    md_indicators = 0
    for line in stripped[:2000].split("\n"):
        line = line.strip()
        if line.startswith("# ") or line.startswith("## ") or line.startswith("### "):
            md_indicators += 1
        if line.startswith("- ") or line.startswith("* "):
            md_indicators += 1
        if line.startswith("```"):
            md_indicators += 1
        if re.match(r"^\[.+\]\(.+\)", line):
            md_indicators += 1
    return md_indicators >= 3


async def fetch_via_llms_txt(url: str, client: httpx.AsyncClient) -> dict | None:
    """Tier 1: Check for /llms.txt at the site root."""
    parsed = urlparse(url)
    llms_url = f"{parsed.scheme}://{parsed.netloc}/llms.txt"
    try:
        resp = await client.get(llms_url, follow_redirects=True, timeout=10)
        if resp.status_code == 200 and resp.text.strip():
            # llms.txt files should start with # or be plain markdown
            if _looks_like_markdown(resp.text) or resp.text.strip().startswith("#"):
                logger.info("Tier 1 hit: /llms.txt at %s", llms_url)
                return {"markdown": resp.text, "source": "llms.txt", "url": llms_url}
    except Exception as e:
        logger.debug("Tier 1 miss for %s: %s", llms_url, e)
    return None


async def fetch_via_content_negotiation(url: str, client: httpx.AsyncClient) -> dict | None:
    """Tier 2: Request with Accept: text/markdown header.

    Also checks for binary content types and short-circuits to a download payload.
    """
    try:
        resp = await client.get(
            url,
            headers={"Accept": "text/markdown, text/plain;q=0.9, */*;q=0.8"},
            follow_redirects=True,
            timeout=15,
        )
        if resp.status_code == 200:
            # Check for binary content first
            ct = resp.headers.get("content-type", "")
            if _is_binary_content_type(ct):
                logger.info("Tier 2 binary hit: %s (%s)", url, ct)
                return _make_download_payload(url, resp.content, ct)
            # Standard markdown detection
            if _looks_like_markdown(resp.text):
                logger.info("Tier 2 hit: content negotiation for %s", url)
                return {"markdown": resp.text, "source": "content-negotiation", "url": url}
    except Exception as e:
        logger.debug("Tier 2 miss for %s: %s", url, e)
    return None


async def fetch_via_playwright(url: str) -> dict | None:
    """Tier 3: Render with Playwright, then extract main content.

    This requires playwright and chromium to be installed.
    Falls back gracefully if playwright is not available.
    """
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                # Wait a bit for JS to execute
                await page.wait_for_timeout(2000)
                html = await page.content()
            finally:
                await browser.close()

        if html:
            markdown = html_to_markdown(html)
            if markdown and len(markdown) > 50:
                logger.info("Tier 3 hit: playwright render for %s", url)
                return {"markdown": markdown, "source": "playwright", "url": url}
    except ImportError:
        logger.warning("Playwright not installed; skipping Tier 3")
    except Exception as e:
        logger.warning("Tier 3 miss for %s: %s", url, e)
    return None


def html_to_markdown(html: str) -> str:
    """Convert HTML to clean markdown using readability + markdownify."""
    try:
        from readability import Document
        from markdownify import markdownify as md

        doc = Document(html)
        summary = doc.summary()
        # Clean up readability's artifacts
        markdown = md(summary, heading_style="ATX", strip=["script", "style"])
        # Collapse multiple blank lines
        markdown = re.sub(r"\n{3,}", "\n\n", markdown)
        return markdown.strip()
    except Exception as e:
        logger.error("HTML-to-markdown conversion failed: %s", e)
        # Fallback: try BeautifulSoup for text extraction
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            # Remove script/style
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
            return text[:10000]  # Limit to 10K chars as fallback
        except Exception:
            return html[:5000]  # Last resort raw truncation


async def smart_scrape(url: str) -> dict:
    """Try each tier in order. Return the first successful result.

    Returns a dict with keys: markdown, source, url, error (optional).
    """
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=30,
        headers={"User-Agent": "Mozilla/5.0 (compatible; GroktoCrawl/0.1; +https://github.com/groktocrawl)"},
    ) as client:
        # Tier 1
        result = await fetch_via_llms_txt(url, client)
        if result:
            return result

        # Tier 2
        result = await fetch_via_content_negotiation(url, client)
        if result:
            return result

    # Tier 3 (no shared client needed)
    result = await fetch_via_playwright(url)
    if result and not _looks_suspicious(result.get("markdown", "")):
        return result

    # Tier 4: LLM-assisted recovery when content looks suspicious
    if result:
        logger.info("Tier 4: attempting LLM recovery for %s", url)
        from .recovery import attempt_llm_recovery
        recovery_result = await attempt_llm_recovery(url, result.get("markdown", ""))
        if recovery_result:
            return recovery_result

    return {
        "error": f"Could not extract content from {url}",
        "markdown": "",
        "source": "none",
        "url": url,
    }
