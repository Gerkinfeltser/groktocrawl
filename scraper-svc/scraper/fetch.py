"""Three-tier fetch strategy for turning URLs into clean markdown.

Tier 1: /llms.txt — entire site as markdown, one GET.
Tier 2: Accept: text/markdown — per-page markdown via content negotiation.
Tier 3: Playwright render + readability extraction (heavyweight).
"""

import logging
import os
import re
import socket
from ipaddress import ip_address, ip_network
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

FLARE_SOLVERR_URL = os.getenv("FLARE_SOLVERR_URL", "http://flare-solverr:8191/v1")

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


# ── Bot challenge detection (title/URL level) ──────────────────
CLOUDFLARE_INDICATORS = [
    "Just a moment",
    "Checking your browser",
    "DDoS protection by",
    "cf-browser-verification",
    "challenge-platform",
]

DDOS_GUARD_INDICATORS = [
    "DDoS-Guard",
    "DDOS-GUARD",
    "ddos-guard",
    "Checking your browser before accessing",
    ".well-known/ddos-guard",
]

# ── Substack session/channel frame redirect detection ──────────
SUBSTACK_REDIRECT_PATTERNS = [
    "substack.com/session-attribution-frame",
    "substack.com/channel-frame",
    "substack.com/iframe",
    "googletagmanager.com/ns.html",
]

# ── Bot challenge and redirect detection (title/URL level) ─────


def _is_bot_challenge(title: str, url: str) -> bool:
    """Check if the page title or URL indicates a bot challenge page.

    Mirrors browser-svc's _is_bot_challenge() logic.
    """
    for indicator in CLOUDFLARE_INDICATORS:
        if indicator.lower() in title.lower():
            return True
    if "cf_chl" in url.lower() or "challenge-platform" in url.lower():
        return True
    for indicator in DDOS_GUARD_INDICATORS:
        if indicator.lower() in title.lower():
            return True
    if "ddos-guard" in url.lower() or "/.well-known/ddos-guard" in url.lower():
        return True
    return False


def _is_substack_redirect(url: str) -> bool:
    """Check if the URL indicates a Substack session/channel frame redirect."""
    for pattern in SUBSTACK_REDIRECT_PATTERNS:
        if pattern in url.lower():
            return True
    return False


# ── Suspicious content detection (for LLM recovery trigger) ────


def _looks_suspicious(content: str) -> bool:
    """Heuristic: does the page content look like a challenge/error page?"""
    if not content:
        return True
    if len(content) < 100:
        return True
    for indicator in CLOUDFLARE_INDICATORS + DDOS_GUARD_INDICATORS + SUBSTACK_REDIRECT_PATTERNS:
        if indicator.lower() in content.lower():
            return True
    return False


# ── Embedded content detection ─────────────────────────────────
# Extensions and domain patterns that suggest an iframe/embed points
# to downloadable document content rather than another web page.
EMBEDDED_CONTENT_EXTENSIONS = {
    ".pdf", ".epub", ".doc", ".docx", ".xls", ".xlsx",
    ".ppt", ".pptx", ".zip", ".tar", ".gz",
}
EMBEDDED_CONTENT_DOMAINS = {
    "sci-hub", "sci.bban", "docdrop", "academia",
    "researchgate", "arxiv.org", "cdn.",
}


def _has_embedded_content(html: str) -> bool:
    """Check if page HTML contains iframe/embed/object pointing to document content.

    Uses lightweight string matching — no HTML parser needed.
    Returns True if the page appears to be a portal to document content elsewhere.
    """
    if not html:
        return False
    html_lower = html.lower()
    # Quick reject: no iframe, embed, or object tags at all
    if not any(tag in html_lower for tag in ("<iframe", "<embed", "<object")):
        return False
    # Check for document extensions in src/data attributes
    for ext in EMBEDDED_CONTENT_EXTENSIONS:
        if ext in html_lower:
            return True
    # Check for known document-serving domains
    for domain in EMBEDDED_CONTENT_DOMAINS:
        if domain in html_lower:
            return True
    # Check for common document URL patterns
    if "/pdf/" in html_lower or "/download/" in html_lower:
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


# ── Private IP / SSRF protection ─────────────────────────────────

_PRIVATE_NETWORKS = [
    ip_network("10.0.0.0/8"),
    ip_network("172.16.0.0/12"),
    ip_network("192.168.0.0/16"),
    ip_network("127.0.0.0/8"),
    ip_network("::1/128"),
    ip_network("169.254.0.0/16"),
    ip_network("0.0.0.0/8"),
    ip_network("100.64.0.0/10"),
    ip_network("198.18.0.0/15"),
    ip_network("240.0.0.0/4"),
]

_METADATA_IPS = {
    ip_address("169.254.169.254"),
    ip_address("fd00:ec2::254"),
}

_PRIVATE_HOSTNAME_SUFFIXES = [
    ".docker.internal",
]


def _resolve_to_ips(hostname: str) -> list:
    try:
        addrinfo = socket.getaddrinfo(hostname, None)
        ips = set()
        for family, _, _, _, sockaddr in addrinfo:
            try:
                ips.add(ip_address(sockaddr[0]))
            except ValueError:
                continue
        return list(ips)
    except socket.gaierror:
        return []


def _is_private_url(url: str) -> tuple[bool, str]:
    """Check if a URL targets a private/internal IP or hostname.

    Returns (is_private, reason) tuple. Shared logic with browser-svc.
    """
    parsed = urlparse(url)
    hostname = parsed.hostname or ""

    if not hostname:
        return True, "Empty or relative URL"

    hostname_lower = hostname.lower()
    for suffix in _PRIVATE_HOSTNAME_SUFFIXES:
        if hostname_lower.endswith(suffix):
            return True, f"Hostname '{hostname}' resolves to Docker host machine"

    try:
        addr = ip_address(hostname)
        for net in _PRIVATE_NETWORKS:
            if addr in net:
                return True, f"IP address {hostname} is in private range {net}"
        if addr in _METADATA_IPS:
            return True, f"IP address {hostname} is a cloud metadata endpoint"
        return False, ""
    except ValueError:
        pass

    ips = _resolve_to_ips(hostname)
    if not ips:
        return True, f"Could not resolve hostname '{hostname}' — blocked for safety"

    for addr in ips:
        for net in _PRIVATE_NETWORKS:
            if addr in net:
                return True, f"Hostname '{hostname}' resolves to private IP {addr} ({net})"
        if addr in _METADATA_IPS:
            return True, f"Hostname '{hostname}' resolves to metadata endpoint {addr}"

    return False, ""


async def fetch_via_playwright(url: str) -> dict | None:
    """Tier 3: Render with stealth Playwright, then extract main content.

    Uses the same stealth configuration as browser-svc to avoid headless
    detection by Substack, Cloudflare JS challenges, and similar mechanisms.

    This requires playwright and chromium to be installed.
    Falls back gracefully if playwright is not available.
    """
    try:
        from playwright.async_api import async_playwright, TimeoutError
        from .cookie_store import inject_cookies, store_cookies
        from .stealth import create_stealth_browser, create_stealth_context

        async with async_playwright() as p:
            browser = await create_stealth_browser(p)
            context = await create_stealth_context(browser)
            page = await context.new_page()
            try:
                # Security: reject private/internal destination URLs
                is_private, reason = _is_private_url(url)
                if is_private:
                    logger.warning("Blocked navigation to private URL %s: %s", url, reason)
                    return None

                # Inject cached Cloudflare clearance cookies before navigation
                await inject_cookies(url, context)

                # Navigate with networkidle — same strategy as browser-svc
                await page.goto(url, wait_until="networkidle", timeout=45000)

                # Check for bot challenges (Cloudflare / DDoS-Guard)
                title = await page.title()
                current_url = page.url
                if _is_bot_challenge(title, current_url):
                    logger.info("Bot challenge detected on %s, waiting for resolution...", url)
                    await page.wait_for_timeout(8000)
                    title = await page.title()
                    current_url = page.url
                    if _is_bot_challenge(title, current_url):
                        logger.warning("Bot challenge persisted after wait for %s", url)

                # Check for Substack session/channel frame redirect
                if _is_substack_redirect(current_url):
                    logger.info("Substack redirect detected on %s (-> %s), waiting for content...", url, current_url)
                    # Substack sometimes resolves after a longer wait
                    await page.wait_for_timeout(5000)
                    current_url = page.url
                    if _is_substack_redirect(current_url):
                        logger.warning("Substack redirect persisted for %s", url)

                # SPA content retry: if the page loaded but content is short
                # or suspicious, it may be a JS-rendered page that needs more
                # time or a scroll to trigger lazy loading
                html = await page.content()
                markdown = html_to_markdown(html) if html else ""

                if not markdown or len(markdown) < 500 or _looks_suspicious(markdown):
                    for attempt in range(2):
                        logger.info(
                            "SPA retry %d for %s (markdown: %d chars)",
                            attempt + 1, url, len(markdown),
                        )
                        # Scroll to trigger lazy-loaded content
                        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        await page.wait_for_timeout(3000)

                        html = await page.content()
                        markdown = html_to_markdown(html) if html else ""
                        if markdown and len(markdown) >= 500 and not _looks_suspicious(markdown):
                            logger.info(
                                "SPA retry %d succeeded for %s (%d chars)",
                                attempt + 1, url, len(markdown),
                            )
                            break

                # html and markdown now hold the best result from the retry loop
            finally:
                await browser.close()

        if html:
            markdown = html_to_markdown(html)
            if markdown and len(markdown) > 50:
                logger.info("Tier 3 hit: playwright render for %s", url)
                # Store any new cf_clearance cookies for future scrapes
                await store_cookies(url, context)
                return {
                    "markdown": markdown,
                    "source": "playwright",
                    "url": url,
                    "raw_html_start": html,
                }
    except ImportError:
        logger.warning("Playwright not installed; skipping Tier 3")
    except Exception as e:
        logger.warning("Tier 3 miss for %s: %s", url, e)
    return None


async def fetch_via_flaresolverr(url: str) -> dict | None:
    """Tier 3.5: Route through FlareSolverr for hard Cloudflare challenges.

    Requires the flare-solverr service to be running (profile-gated in
    docker-compose.yml). Gracefully falls back if unavailable.
    """
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{FLARE_SOLVERR_URL}/v1",
                json={
                    "cmd": "request.get",
                    "url": url,
                    "maxTimeout": 60000,
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                solution = data.get("solution", {})
                if solution.get("status") == 200:
                    html = solution.get("response", "")
                    if html:
                        markdown = html_to_markdown(html)
                        if markdown and len(markdown) > 50:
                            logger.info("Tier 3.5 hit: flare-solverr for %s", url)
                            return {"markdown": markdown, "source": "flare-solverr", "url": url}
    except (httpx.ConnectError, httpx.TimeoutException):
        logger.debug("FlareSolverr not available for %s", url)
    except Exception as e:
        logger.warning("FlareSolverr failed for %s: %s", url, e)
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


async def _fetch_via_browser_svc(url: str) -> dict | None:
    """Fallback: use the browser-svc API to navigate and extract content.

    The browser-svc's Playwright configuration is able to handle sites
    that the scraper-svc's Tier 3 cannot (e.g., Substack redirect chains).

    Browser-svc is available at http://browser-svc:8012.
    """
    browser_svc_url = os.getenv("BROWSER_SVC_URL", "http://browser-svc:8012")
    session_id = None
    try:
        # Create a browser session
        async with httpx.AsyncClient(timeout=30) as client:
            create_resp = await client.post(
                f"{browser_svc_url}/browsers",
                json={"ttl": 60},  # Short TTL, we only need one page load
            )
            if create_resp.status_code != 200:
                logger.warning("Browser-svc session creation failed: %d", create_resp.status_code)
                return None
            session_id = create_resp.json().get("id")
            if not session_id:
                return None

            # Navigate to the URL
            nav_resp = await client.post(
                f"{browser_svc_url}/browsers/{session_id}/execute",
                json={"action": "navigate", "url": url, "timeout": 45000},
            )
            if not nav_resp.json().get("success"):
                logger.warning("Browser-svc navigation failed for %s", url)
                return None

            # Get page content (HTML)
            content_resp = await client.post(
                f"{browser_svc_url}/browsers/{session_id}/execute",
                json={"action": "getContent"},
            )
            if not content_resp.json().get("success"):
                return None

            result = content_resp.json()["result"]
            html = None

            # Try to extract article text via executeScript first
            text_resp = await client.post(
                f"{browser_svc_url}/browsers/{session_id}/execute",
                json={
                    "action": "executeScript",
                    "script": (
                        "document.querySelector('article') "
                        "? document.querySelector('article').innerText "
                        ": document.body.innerText"
                    ),
                },
            )
            if text_resp.json().get("success"):
                text = text_resp.json()["result"].get("script_result", "")
                if text and len(text) > 200:
                    logger.info("Browser-svc fallback hit for %s (article text: %d chars)", url, len(text))
                    return {
                        "markdown": text,
                        "source": "browser-svc",
                        "url": url,
                    }

            # Fallback: get HTML and convert to markdown
            html = result.get("html_length") and (
                await _get_browser_page_content(browser_svc_url, session_id)
            )
            if html:
                markdown = html_to_markdown(html)
                if markdown and len(markdown) > 50:
                    logger.info("Browser-svc fallback hit for %s (HTML: %d chars)", url, len(html))
                    return {
                        "markdown": markdown,
                        "source": "browser-svc",
                        "url": url,
                    }

    except Exception as e:
        logger.warning("Browser-svc fallback failed for %s: %s", url, e)
    finally:
        # Clean up the browser session
        if session_id:
            try:
                async with httpx.AsyncClient(timeout=5) as c:
                    await c.delete(f"{browser_svc_url}/browsers/{session_id}")
            except Exception:
                pass

    return None


async def _get_browser_page_content(browser_svc_url: str, session_id: str) -> str | None:
    """Get the full page HTML from a browser-svc session via executeScript."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{browser_svc_url}/browsers/{session_id}/execute",
                json={
                    "action": "executeScript",
                    "script": "document.documentElement.outerHTML",
                },
            )
            if resp.json().get("success"):
                return resp.json()["result"].get("script_result", "")
    except Exception:
        pass
    return None


async def smart_scrape(url: str) -> dict:
    """Try each tier in order. Return the first successful result.

    Returns a dict with keys: markdown, source, url, error (optional).
    """
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=30,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        },
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
    if result:
        content_good = not _looks_suspicious(result.get("markdown", ""))
        content_embedded = _has_embedded_content(result.get("raw_html_start", ""))
        if content_good:
            return result  # genuinely good content, return immediately
        logger.info("Tier 3 content flagged: suspicious=%s, embedded=%s",
                     not content_good, content_embedded)

    # Tier 3.5: FlareSolverr for hard Cloudflare challenges
    if result:
        fs_result = await fetch_via_flaresolverr(url)
        if fs_result:
            return fs_result

    # Tier 4: LLM-assisted recovery when content looks suspicious
    if result:
        logger.info("Tier 4: attempting LLM recovery for %s", url)
        from .recovery import attempt_llm_recovery
        # Pass raw HTML (with iframe tags) instead of converted markdown
        page_content = result.get("raw_html_start") or result.get("markdown", "")
        recovery_result = await attempt_llm_recovery(url, page_content)
        if recovery_result:
            return recovery_result

    # Check for specific failure modes — try browser-svc fallback for Substack
    if result:
        raw_html = result.get("raw_html_start", "")
        redirected_url = ""
        # Extract redirected URL from raw HTML if available (Substack embeds it)
        import re as _re
        substack_match = _re.search(r'substack\.com/[^"\'\\s]+', raw_html)
        if substack_match:
            redirected_url = f" (redirected to {substack_match.group()})"

        if _is_substack_redirect(raw_html):
            # Fallback: use the browser-svc which handles Substack correctly
            logger.info("Substack redirect detected, trying browser-svc fallback for %s", url)
            browser_result = await _fetch_via_browser_svc(url)
            if browser_result:
                return browser_result
            return {
                "error": (
                    f"Could not extract content from {url}{redirected_url}. "
                    f"Substack blocked the headless browser. "
                    f"Try: groktocrawl browser exec <id> navigate --url <url> "
                    f"then browser exec <id> executeScript "
                    f"--script \"document.querySelector('article').innerText\""
                ),
                "markdown": "",
                "source": "none",
                "url": url,
            }

    return {
        "error": f"Could not extract content from {url}",
        "markdown": "",
        "source": "none",
        "url": url,
    }
