"""Headless browser session management service.

Manages Playwright browser sessions with TTL-based lifecycle.
Each session is an isolated Chromium instance with its own context.
"""

import asyncio
import logging
import time
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

# ── Stealth configuration ─────────────────────────────────────
# Real Chrome user agent to avoid bot detection
REAL_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

CLOUDFLARE_INDICATORS = [
    "Just a moment...",
    "Checking your browser",
    "DDoS protection by",
    "cf-browser-verification",
    "challenge-platform",
]


def _is_cloudflare_challenge(title: str, url: str) -> bool:
    """Heuristic: does the page indicate a Cloudflare challenge?"""
    for indicator in CLOUDFLARE_INDICATORS:
        if indicator.lower() in title.lower():
            return True
    # Cloudflare challenge URLs often contain cf_chl_opt or __cf_chl
    if "cf_chl" in url.lower() or "challenge-platform" in url.lower():
        return True
    return False

app = FastAPI(title="GroktoCrawl Browser Service", version="0.1.0")

# In-memory session store
_sessions: dict[str, "SessionData"] = {}
_CLEANUP_INTERVAL = 30  # seconds


class SessionData:
    """Holds Playwright objects for a single session."""

    def __init__(self, browser, context, page, ttl: int):
        self.browser = browser
        self.context = context
        self.page = page
        self.created_at = time.time()
        self.ttl = ttl
        self.last_used = time.time()

    @property
    def expired(self) -> bool:
        return time.time() - self.created_at > self.ttl

    @property
    def idle_seconds(self) -> float:
        return time.time() - self.last_used


class BrowserCreateRequest(BaseModel):
    ttl: int = 300  # seconds, default 5 minutes


class BrowserExecuteRequest(BaseModel):
    action: str  # navigate, click, type, screenshot, scroll, wait, getContent, executeScript
    url: str | None = None
    selector: str | None = None
    text: str | None = None
    script: str | None = None
    timeout: int = 10000


class BrowserCreateResponse(BaseModel):
    success: bool = True
    id: str


class BrowserExecuteResponse(BaseModel):
    success: bool = True
    result: Any = None
    error: str | None = None


class BrowserListResponse(BaseModel):
    success: bool = True
    sessions: list[dict] = []


@app.on_event("startup")
async def startup():
    asyncio.create_task(_cleanup_loop())


async def _cleanup_loop():
    """Periodically remove expired sessions."""
    while True:
        await asyncio.sleep(_CLEANUP_INTERVAL)
        expired = [sid for sid, s in _sessions.items() if s.expired]
        for sid in expired:
            logger.info("Cleaning up expired session %s", sid)
            await _destroy_session(sid)


async def _destroy_session(session_id: str) -> None:
    """Close and remove a browser session."""
    session = _sessions.pop(session_id, None)
    if session is None:
        return
    try:
        await session.page.close()
        await session.context.close()
        await session.browser.close()
    except Exception as e:
        logger.warning("Error closing session %s: %s", session_id, e)


@app.get("/health")
async def health():
    return {"status": "ok", "active_sessions": len(_sessions)}


@app.post("/browsers", response_model=BrowserCreateResponse)
async def create_browser(req: BrowserCreateRequest):
    """Create a new headless browser session."""
    session_id = str(uuid.uuid4())

    try:
        p = await async_playwright().start()
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=REAL_CHROME_UA,
            locale="en-US",
            timezone_id="America/New_York",
            permissions=["geolocation"],
        )
        page = await context.new_page()
        # Hide Playwright automation signals from bot detection
        await page.add_init_script("""() => {
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        }""")
        session = SessionData(browser, context, page, req.ttl)
        _sessions[session_id] = session
        logger.info("Created browser session %s (TTL: %ds)", session_id, req.ttl)
        return BrowserCreateResponse(id=session_id)
    except Exception as e:
        logger.error("Failed to create browser session: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to create browser session: {e}")


@app.post("/browsers/{session_id}/execute", response_model=BrowserExecuteResponse)
async def execute_action(session_id: str, req: BrowserExecuteRequest):
    """Execute an action in an existing browser session."""
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    if session.expired:
        await _destroy_session(session_id)
        raise HTTPException(status_code=404, detail="Session expired")

    session.last_used = time.time()
    page = session.page

    try:
        if req.action == "navigate":
            if not req.url:
                raise HTTPException(status_code=400, detail="url required for navigate action")
            await page.goto(req.url, wait_until="networkidle", timeout=req.timeout)
            # Cloudflare challenge detection — wait for JS challenge to resolve
            title = await page.title()
            current_url = page.url
            if _is_cloudflare_challenge(title, current_url):
                logger.info("Cloudflare challenge detected on %s, waiting for resolution...", req.url)
                await page.wait_for_timeout(8000)
                title = await page.title()
                current_url = page.url
                if _is_cloudflare_challenge(title, current_url):
                    logger.warning("Cloudflare challenge persisted after wait for %s", req.url)
            return BrowserExecuteResponse(result={"url": current_url, "title": title})

        elif req.action == "click":
            if not req.selector:
                raise HTTPException(status_code=400, detail="selector required for click action")
            await page.click(req.selector, timeout=req.timeout)
            return BrowserExecuteResponse(result={"clicked": req.selector})

        elif req.action == "type":
            if not req.selector or req.text is None:
                raise HTTPException(status_code=400, detail="selector and text required for type action")
            await page.fill(req.selector, req.text, timeout=req.timeout)
            return BrowserExecuteResponse(result={"typed": req.selector})

        elif req.action == "screenshot":
            buf = await page.screenshot(full_page=True)
            import base64
            b64 = base64.b64encode(buf).decode()
            return BrowserExecuteResponse(result={"screenshot": b64, "format": "png"})

        elif req.action == "scroll":
            await page.evaluate("window.scrollBy(0, window.innerHeight)")
            return BrowserExecuteResponse(result={"scrolled": True})

        elif req.action == "wait":
            if req.selector:
                await page.wait_for_selector(req.selector, timeout=req.timeout)
            else:
                await asyncio.sleep(min(req.timeout / 1000, 5))
            return BrowserExecuteResponse(result={"waited": True})

        elif req.action == "getContent":
            html = await page.content()
            title = await page.title()
            url = page.url
            return BrowserExecuteResponse(result={"url": url, "title": title, "html_length": len(html)})

        elif req.action == "executeScript":
            if not req.script:
                raise HTTPException(status_code=400, detail="script required for executeScript action")
            result = await page.evaluate(req.script)
            return BrowserExecuteResponse(result={"script_result": result})

        else:
            raise HTTPException(status_code=400, detail=f"Unknown action: {req.action}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Action %s failed in session %s: %s", req.action, session_id, e)
        return BrowserExecuteResponse(success=False, error=str(e))


@app.get("/browsers", response_model=BrowserListResponse)
async def list_browsers():
    """List all active browser sessions."""
    sessions = []
    for sid, s in list(_sessions.items()):
        if s.expired:
            await _destroy_session(sid)
        else:
            sessions.append({
                "id": sid,
                "age_seconds": int(time.time() - s.created_at),
                "ttl": s.ttl,
                "idle_seconds": int(s.idle_seconds),
            })
    return BrowserListResponse(sessions=sessions)


@app.delete("/browsers/{session_id}", response_model=dict)
async def destroy_browser(session_id: str):
    """Destroy a browser session."""
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    await _destroy_session(session_id)
    return {"success": True, "id": session_id}
