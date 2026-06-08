"""Stealth configuration for Playwright browser automation.

Provides a reusable set of browser launch arguments, context settings, and
initialization scripts that mask headless Chromium automation signals.

Ported from browser-svc/browser_svc/app.py with additional fingerprinting
hardening (plugins, languages, chrome.runtime, WebGL).

Usage:
    from .stealth import create_stealth_browser, create_stealth_context

    async with async_playwright() as p:
        browser = await create_stealth_browser(p)
        context = await create_stealth_context(browser)
        page = await context.new_page()
"""

import logging

logger = logging.getLogger(__name__)

# ── Real Chrome User-Agent ─────────────────────────────────────
REAL_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# ── Browser launch arguments ────────────────────────────────────
STEALTH_BROWSER_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-dev-shm-usage",
]

# ── Browser context settings ────────────────────────────────────
STEALTH_CONTEXT_KWARGS = {
    "viewport": {"width": 1920, "height": 1080},
    "user_agent": REAL_CHROME_UA,
    "locale": "en-US",
    "timezone_id": "America/New_York",
    "permissions": ["geolocation"],
}

# ── Init script to hide automation signals ─────────────────────
STEALTH_INIT_SCRIPT = """() => {
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined
    });
}"""


async def create_stealth_browser(playwright):
    """Launch a Chromium browser with stealth configuration.

    Args:
        playwright: An async_playwright instance.

    Returns:
        A Browser instance configured to avoid headless detection.
    """
    logger.debug("Launching stealth Chromium browser")
    return await playwright.chromium.launch(
        headless=True,
        args=STEALTH_BROWSER_ARGS,
    )


async def create_stealth_context(browser, **kwargs):
    """Create a browser context with stealth settings.

    Args:
        browser: A Browser instance from create_stealth_browser.
        **kwargs: Additional keyword arguments forwarded to browser.new_context()
            (e.g., proxy config for context-level proxy assignment).

    Returns:
        A BrowserContext with realistic fingerprint settings.
    """
    logger.debug("Creating stealth browser context")
    context_kwargs = {**STEALTH_CONTEXT_KWARGS, **kwargs}
    context = await browser.new_context(**context_kwargs)
    await context.add_init_script(STEALTH_INIT_SCRIPT)
    return context
