"""GroktoCrawl web portal — single-search-bar UI for human users."""

import logging
import os

import httpx
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from common.logging import setup_logging
from common.metrics import METRICS
from common.middleware import add_request_id_middleware

setup_logging()
logger = logging.getLogger(__name__)

AGENT_BASE_URL = os.getenv("AGENT_BASE_URL", "http://agent-svc:8080")
ANSWER_URL = f"{AGENT_BASE_URL}/v2/answer"

templates = Jinja2Templates(
    directory=os.path.join(os.path.dirname(__file__), "templates")
)

app = FastAPI(
    title="GroktoCrawl Portal",
    version="0.1.0",
    description="Web portal for GroktoCrawl — self-hosted AI research.",
)

# ── Instrumentation ──────────────────────────────────────────
add_request_id_middleware(app)
METRICS.counter("portal_queries_total", "Total portal queries")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "portal-svc"}


@app.get("/metrics")
async def metrics():
    """Prometheus-compatible OpenMetrics endpoint."""
    return PlainTextResponse(METRICS.generate_openmetrics(), media_type="text/plain")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@app.post("/ask")
async def ask(query: str = Form(...), num_sources: int = Form(5)):
    """Proxy a grounded Q&A query to agent-svc, streaming SSE results back."""

    async def proxy_stream():
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                ANSWER_URL,
                json={
                    "query": query,
                    "num_sources": num_sources,
                    "stream": True,
                },
            ) as response:
                async for chunk in response.aiter_bytes():
                    yield chunk

    return StreamingResponse(proxy_stream(), media_type="text/event-stream")
