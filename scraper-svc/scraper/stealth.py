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
    "--disable-features=IsolateOrigins,site-per-process",
    "--disable-web-security",
    "--disable-features=BlockInsecurePrivateNetworkRequests",
]

# ── Browser context settings ────────────────────────────────────
STEALTH_CONTEXT_KWARGS = {
    "viewport": {"width": 1920, "height": 1080},
    "user_agent": REAL_CHROME_UA,
    "locale": "en-US",
    "timezone_id": "America/New_York",
    "permissions": ["geolocation"],
    "geolocation": {"latitude": 40.7128, "longitude": -74.0060},
}

# ── Init script to hide automation signals ─────────────────────
STEALTH_INIT_SCRIPT = """() => {
    // Hide webdriver property
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined
    });

    // Populate plugins array (headless Chromium has empty array)
    Object.defineProperty(navigator, 'plugins', {
        get: () => [
            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
            { name: 'Native Client', filename: 'internal-nacl-plugin' },
        ]
    });

    // Set languages
    Object.defineProperty(navigator, 'languages', {
        get: () => ['en-US', 'en']
    });

    // Chrome runtime presence (some sites check this)
    window.chrome = {
        runtime: {},
        loadTimes: function() {},
        csi: function() {},
        app: {}
    };

    // Override permissions query to hide headless
    if (navigator.permissions && navigator.permissions.query) {
        const originalQuery = navigator.permissions.query.bind(navigator.permissions);
        navigator.permissions.query = (desc) => {
            if (desc.name === 'notifications' || desc.name === 'clipboard-read') {
                return Promise.resolve({ state: 'granted' });
            }
            return originalQuery(desc);
        };
    }

    // WebGL vendor/renderer spoofing
    const getParameterProxyHandler = {
        apply: function(target, thisArg, args) {
            const param = args[0];
            if (param === 37445) return 'Intel Inc.';       // UNMASKED_VENDOR_WEBGL
            if (param === 37446) return 'Intel Iris OpenGL Engine';  // UNMASKED_RENDERER_WEBGL
            return Reflect.apply(target, thisArg, args);
        }
    };
    const canvas = document.createElement('canvas');
    const gl = canvas.getContext('webgl');
    if (gl) {
        const originalGetParameter = gl.getParameter.bind(gl);
        gl.getParameter = new Proxy(originalGetParameter, getParameterProxyHandler);
    }
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


async def create_stealth_context(browser):
    """Create a browser context with stealth settings.

    Args:
        browser: A Browser instance from create_stealth_browser.

    Returns:
        A BrowserContext with realistic fingerprint settings.
    """
    logger.debug("Creating stealth browser context")
    context = await browser.new_context(**STEALTH_CONTEXT_KWARGS)
    await context.add_init_script(STEALTH_INIT_SCRIPT)
    return context
