"""Small fixture website with three behaviors:
- llms.txt site
- markdown-negotiation site
- dynamic JS-rendered site
"""

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
import os

app = FastAPI(title="GroktoCrawl Test Site", version="0.1.0")

ENABLE_LLMS_TXT = os.getenv("ENABLE_LLMS_TXT", "0") == "1"
ENABLE_MARKDOWN = os.getenv("ENABLE_MARKDOWN", "0") == "1"
ENABLE_DYNAMIC = os.getenv("ENABLE_DYNAMIC", "0") == "1"
SITE_NAME = os.getenv("SITE_NAME", "Fixture Site")


@app.get("/health")
async def health():
    return {"status": "ok", "site": SITE_NAME}


@app.get("/llms.txt")
async def llms_txt():
    if not ENABLE_LLMS_TXT:
        return PlainTextResponse("not found", status_code=404)
    return PlainTextResponse(
        f"# {SITE_NAME}\n\nThis is the llms.txt entrypoint.\n\n- /pricing\n- /about\n- /dynamic\n",
        media_type="text/plain",
    )


@app.get("/pricing")
async def pricing(request: Request):
    accept = request.headers.get("accept", "")
    if ENABLE_MARKDOWN and "text/markdown" in accept:
        return PlainTextResponse(
            f"# {SITE_NAME} Pricing\n\n- Free: $0\n- Pro: $10\n- Business: $25\n",
            media_type="text/markdown",
        )
    return HTMLResponse(
        f"""
        <html>
          <body>
            <h1>{SITE_NAME} Pricing</h1>
            <p>Free: $0</p>
            <p>Pro: $10</p>
            <p>Business: $25</p>
          </body>
        </html>
        """
    )


@app.get("/")
async def root():
    return HTMLResponse(
        f"""
        <html>
          <body>
            <h1>{SITE_NAME}</h1>
            <a href="/pricing">Pricing</a>
            <a href="/about">About</a>
            <a href="/dynamic">Dynamic</a>
            <a href="/llms.txt">llms</a>
          </body>
        </html>
        """
    )


@app.get("/about")
async def about():
    return HTMLResponse(
        f"""
        <html><body><h1>About {SITE_NAME}</h1><p>Self-contained fixture site.</p></body></html>
        """
    )


@app.get("/dynamic")
async def dynamic():
    if not ENABLE_DYNAMIC:
        return HTMLResponse("<html><body><h1>Dynamic page disabled</h1></body></html>")
    return HTMLResponse(
        """
        <html>
          <body>
            <h1>Dynamic Page</h1>
            <div id="content">Loading...</div>
            <script>
              setTimeout(() => {
                document.getElementById('content').innerText = 'Dynamic Content Loaded';
              }, 10);
            </script>
          </body>
        </html>
        """
    )
